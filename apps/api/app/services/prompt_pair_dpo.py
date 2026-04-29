from __future__ import annotations

import re
from typing import Any, Dict, List

from sqlmodel import Session, select

from app.models import Task, utcnow
from app.services.pair_export import compile_pair_export

RUBRIC_CRITERIA = [
    "voice_authenticity",
    "grounding_truth",
    "restraint",
    "concrete_detail",
    "prompt_fit",
    "privacy_export_safety",
]


def _count(session: Session, model: Any) -> int:
    return len(session.exec(select(model)).all()) + 1


def _response_text(payload: Dict[str, Any]) -> str:
    return str(payload.get("content") or payload.get("chosen") or payload.get("adam_gold_edit") or "").strip()


def _topic_from_prompt(prompt: str) -> str:
    cleaned = re.sub(r"\s+", " ", prompt).strip().strip("?!.")
    if len(cleaned) > 80:
        cleaned = cleaned[:77].rstrip() + "..."
    return cleaned or "this memory"


def synthetic_rejected_response(prompt: str, chosen: str) -> str:
    topic = _topic_from_prompt(prompt).lower()
    rejected = (
        f"This is a straightforward response about {topic}. "
        "It explains the situation clearly, but it does not preserve Charles' cadence, "
        "sideways humor, concrete sensory detail, pauses, or intimate sign-off."
    )
    if rejected.strip() == chosen.strip():
        rejected += " It is intentionally generic and should be rejected."
    return rejected


def synthetic_dpo_reasons() -> List[str]:
    return [
        "voice_authenticity: Rejected is a generic summary instead of Charles' cadence, pauses, concrete aside, and intimate sign-off.",
        "concrete_detail: Rejected describes the topic abstractly and does not preserve source-specific sensory or relational detail.",
        "restraint: Rejected explains the intended effect too directly instead of letting the ordinary phrasing carry feeling.",
    ]


def _no_issue_decision(note: str) -> Dict[str, Any]:
    return {"status": "no_issues", "notes": note, "issue_tags": []}


def synthetic_dpo_rubric() -> Dict[str, Any]:
    chosen = {
        key: _no_issue_decision(
            "Preferred candidate side copied from the SFT ticket; Adam review is still required before export."
        )
        for key in RUBRIC_CRITERIA
    }
    rejected = {
        key: _no_issue_decision("No specific issue marked for this criterion in the synthetic comparison scaffold.")
        for key in RUBRIC_CRITERIA
    }
    rejected["voice_authenticity"] = {
        "status": "minor_issues",
        "notes": "Generic explanatory prose; lacks Charles' broken-line cadence, sideways humor, and natural sign-off.",
        "issue_tags": ["too_generic", "not_charles_voice", "wrong_register"],
    }
    rejected["restraint"] = {
        "status": "minor_issues",
        "notes": "Overexplains the quality gap instead of letting concrete language and understatement do the work.",
        "issue_tags": ["overexplained", "too_polished"],
    }
    rejected["concrete_detail"] = {
        "status": "minor_issues",
        "notes": "Names the topic but lacks the specific object, scene, sensory detail, or relational turn that makes Charles sound alive.",
        "issue_tags": ["lost_specificity", "generic_detail"],
    }
    return {
        "response_a": rejected,
        "response_b": chosen,
        "rubric_source": "system_suggested_dpo_scaffold_requires_adam_review",
    }


def synthetic_dpo_rubric_summary(reasons: List[str]) -> Dict[str, Any]:
    return {
        "rejected_issue_count": 3,
        "rejected_major_issue_count": 0,
        "preferred_issue_count": 0,
        "preferred_major_issue_count": 0,
        "preferred_export_blocked": False,
        "sft_ready": True,
        "dpo_reason_count": len(reasons),
        "rubric_source": "system_suggested_dpo_scaffold_requires_adam_review",
    }


def synthesize_dpo_candidates(session: Session, *, limit: int = 25, dry_run: bool = True) -> Dict[str, Any]:
    limit = max(0, min(limit, 200))
    existing_source_ids = {
        str(task.input_payload.get("source_sft_task_id"))
        for task in session.exec(
            select(Task)
            .where(Task.task_type == "gold_voice_edit")
            .where(Task.queue == "prompt_pairs_needing_gold_edits")
        ).all()
        if isinstance(task.input_payload, dict) and task.input_payload.get("source_sft_task_id")
    }
    candidates = session.exec(
        select(Task)
        .where(Task.task_type == "gold_voice_edit")
        .where(Task.queue == "prompt_pairs_needing_gold_edits")
        .where(Task.status == "ready")
        .order_by(Task.created_at.asc())
    ).all()

    created: List[Dict[str, Any]] = []
    for source_task in candidates:
        if len(created) >= limit:
            break
        if source_task.id in existing_source_ids:
            continue
        payload = dict(source_task.input_payload or {})
        if str(payload.get("artifact_mode") or "sft") != "sft":
            continue
        prompt = str(payload.get("prompt") or "").strip()
        chosen = _response_text(payload)
        if not prompt or not chosen:
            continue
        rejected = synthetic_rejected_response(prompt, chosen)
        dpo_reasons = synthetic_dpo_reasons()
        response_rubric = synthetic_dpo_rubric()
        dpo_payload = {
            **payload,
            "artifact_mode": "dpo",
            "chosen": chosen,
            "rejected": rejected,
            "content": None,
            "rejected_truth_status": "model_generated",
            "dpo_reason": dpo_reasons,
            "failure_modes": dpo_reasons,
            "response_rubric": response_rubric,
            "rubric_summary": synthetic_dpo_rubric_summary(dpo_reasons),
            "source_sft_task_id": source_task.id,
            "source_sft_task_human_id": source_task.human_id,
            "synthetic": True,
            "context": "\n".join(
                part
                for part in [
                    str(payload.get("context") or "").strip(),
                    "DPO candidate synthesized from an SFT review ticket. Rejected response is intentionally generic and model-generated for Adam review.",
                ]
                if part
            ),
        }
        compiled = compile_pair_export(dpo_payload, fallback_truth_status=str(payload.get("truth_status") or "archival_source"))
        dpo_payload["export_preview_yaml"] = compiled["yaml_preview"]
        created.append(
            {
                "source_task_id": source_task.id,
                "source_task_human_id": source_task.human_id,
                "prompt": prompt,
                "voice_mode": dpo_payload.get("voice_mode"),
            }
        )
        if dry_run:
            continue
        dpo_task = Task(
            human_id=f"TASK_DPO_CANDIDATE_{_count(session, Task):06d}",
            task_type="gold_voice_edit",
            target_type="prompt_pair",
            target_id=str(payload.get("prompt_spec_id") or source_task.target_id),
            priority=max(10, int(source_task.priority or 50) - 5),
            queue="prompt_pairs_needing_gold_edits",
            reason_created="Synthetic DPO rejected response generated from an SFT prompt-pair candidate for Adam review.",
            input_payload=dpo_payload,
            required_decisions=["artifact_mode", "voice_mode", "prompt", "chosen", "rejected", "response_rubric"],
            created_by="synthetic_dpo_candidate_generation",
        )
        dpo_task.updated_at = utcnow()
        session.add(dpo_task)
        session.flush()
        created[-1]["dpo_task_id"] = dpo_task.id
        created[-1]["dpo_task_human_id"] = dpo_task.human_id

    if not dry_run:
        session.commit()

    return {
        "dry_run": dry_run,
        "requested_limit": limit,
        "created_count": len(created),
        "candidates": created,
    }
