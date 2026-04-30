from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, List, Optional

from sqlmodel import Session, select

from app.models import Asset, Task


PHOTO_REVIEW_TASK_TYPES = {"photo_context", "vision_draft_review"}
THROUGHPUT_POLICY = "rank_by_fastest_review_path_then_missing_adam_fields_then_downstream_payoff"
COMPLETION_SIGNAL = "open_top_photo_task_and_reduce_missing_adam_fields_or_submit_ready_count_increases"


def _stable_hash(payload: Dict[str, Any]) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _yaml_scalar(value: Any) -> str:
    if value is True:
        return "true"
    if value is False:
        return "false"
    if value is None:
        return "null"
    if isinstance(value, (int, float)):
        return str(value)
    text = str(value)
    if not text:
        return '""'
    if all(ch.isalnum() or ch in " _./:-" for ch in text):
        return text
    return json.dumps(text, ensure_ascii=False)


def _payload_string(payload: Dict[str, Any], key: str, fallback: str = "") -> str:
    value = payload.get(key)
    return value.strip() if isinstance(value, str) and value.strip() else fallback


def _photo_title(asset: Optional[Asset], task: Task) -> str:
    payload = task.input_payload or {}
    return (
        _payload_string(payload, "asset_title")
        or _payload_string(payload, "source_photo_title")
        or _payload_string(payload, "source_title")
        or (asset.title if asset and asset.title else None)
        or (asset.original_filename if asset and asset.original_filename else None)
        or task.human_id
    )


def _task_asset(session: Session, task: Task) -> Optional[Asset]:
    if task.target_type == "asset":
        asset = session.get(Asset, task.target_id)
        if asset:
            return asset
    payload = task.input_payload or {}
    for key in ("asset_id", "source_photo_id"):
        value = payload.get(key)
        if isinstance(value, str) and value:
            asset = session.get(Asset, value)
            if asset:
                return asset
    return None


def _asset_preview_ready(asset: Optional[Asset]) -> bool:
    return bool(asset and asset.processing_status in {"image_preview_ready", "photo_memory_reviewed"})


def photo_priority_rank(task: Task) -> int:
    payload = task.input_payload or {}
    if task.task_type == "vision_draft_review" and payload.get("source_photo_memory_draft") is True:
        return 0
    if task.task_type == "photo_context" and isinstance(payload.get("retrieval_gap_origin"), dict):
        return 1
    if task.task_type == "photo_context":
        return 2
    if task.task_type == "vision_draft_review":
        return 3
    return 99


def _downstream_payoff_score(*, rank: int, missing_field_count: int, preview_ready: bool, has_retrieval_query: bool) -> int:
    base = {
        0: 95,
        1: 82,
        2: 68,
        3: 42,
    }.get(rank, 10)
    return max(0, base + (5 if preview_ready else -15) + (8 if has_retrieval_query else 0) - missing_field_count)


def _rank_label(rank: int) -> str:
    if rank == 0:
        return "Fastest vector path"
    if rank == 1:
        return "Retrieval context path"
    if rank == 2:
        return "Context path"
    if rank == 3:
        return "Photo review path"
    return "Other path"


def _retrieval_query(task: Task) -> str:
    retrieval_origin = (task.input_payload or {}).get("retrieval_gap_origin")
    if not isinstance(retrieval_origin, dict):
        return ""
    query = retrieval_origin.get("query")
    return query.strip() if isinstance(query, str) and query.strip() else ""


def _priority_explanation(task: Task, rank: int) -> Dict[str, Any]:
    query = _retrieval_query(task)
    if rank == 0:
        return {
            "why_first": "A machine draft already supplies visible-image scaffolding, so Adam can focus on corrections, meaning, and boundaries.",
            "projected_outcome": "Held until Adam adds context and sets downstream clearance; then eligible for reviewed photo memory and vector handoff.",
            "submit_outcome_badge": "On submit: vector-safe memory",
            "submit_outcome_label": "Creates vector-safe memory after Adam review",
            "submit_outcome_detail": "Completing Adam context, downstream clearance, and boundary review can promote the draft into reviewed-only memory/vector handoff.",
            "vector_handoff_preview_status": "held_until_adam_context",
            "missing_fields": [
                "Adam context or answers",
                "Downstream choice: set Yes for retrieval",
                "Boundary review for family/public use",
            ],
            "safeguards": ["No memory claim yet", "No vector write before submit", "Not SFT/DPO training material"],
            "truth_status_before_review": "system_inference_requires_adam_review",
        }
    if rank == 1:
        return {
            "why_first": (
                f'This was created from the retrieval gap "{query}," so completing it directly improves future recall.'
                if query
                else "This was created from a retrieval gap, so completing it directly improves future recall."
            ),
            "projected_outcome": "Adam-authored context can create reviewed memory text, boundary settings, and embedding-ready handoff records.",
            "submit_outcome_badge": "On submit: closes retrieval gap",
            "submit_outcome_label": "Creates reviewed context for this retrieval gap",
            "submit_outcome_detail": "Adam-authored answers can become searchable memory text and embedding-ready handoff records without making a training example.",
            "vector_handoff_preview_status": "eligible_after_required_context",
            "missing_fields": [
                "Reviewed visual description",
                "Adam context or answers",
                "Downstream choice: set Yes for retrieval",
                "Boundary review for family/public use",
            ],
            "safeguards": ["No memory claim yet", "Filename/title evidence only until reviewed", "Not SFT/DPO training material"],
            "truth_status_before_review": "no_claim",
        }
    return {
        "why_first": "This task can add missing photo context and boundaries, but it may need more Adam-authored detail before retrieval use.",
        "projected_outcome": "Likely held as photo context until reviewed memory text and downstream clearance are present.",
        "submit_outcome_badge": "On submit: context hold",
        "submit_outcome_label": "Saves photo context until memory is complete",
        "submit_outcome_detail": "The review creates durable context, then waits for Adam-authored memory detail and downstream clearance before vector handoff.",
        "vector_handoff_preview_status": "held_until_required_context",
        "missing_fields": [
            "Reviewed visual description",
            "Adam context or answers",
            "Downstream choice: set Yes for retrieval",
        ],
        "safeguards": ["No memory claim yet", "No vector write before submit", "Not SFT/DPO training material"],
        "truth_status_before_review": "no_claim",
    }


def _priority_yaml(summary: Dict[str, Any]) -> str:
    lines = [
        "photo_review_priority:",
        f"  summary_type: {_yaml_scalar(summary.get('summary_type'))}",
        f"  focus: {_yaml_scalar(summary.get('focus'))}",
        f"  review_policy: {_yaml_scalar(summary.get('review_policy'))}",
        f"  throughput_policy: {_yaml_scalar(summary.get('throughput_policy'))}",
        f"  completion_signal: {_yaml_scalar(summary.get('completion_signal'))}",
        f"  content_sha256: {_yaml_scalar(summary.get('content_sha256'))}",
        "  boundaries:",
        f"    does_not_mutate_state: {_yaml_scalar(summary.get('does_not_mutate_state'))}",
        f"    does_not_create_memory_claim: {_yaml_scalar(summary.get('does_not_create_memory_claim'))}",
        f"    no_live_model_call: {_yaml_scalar(summary.get('no_live_model_call'))}",
        f"    no_live_embedding_call: {_yaml_scalar(summary.get('no_live_embedding_call'))}",
        "  counts:",
        f"    total_candidate_count: {_yaml_scalar(summary.get('total_candidate_count'))}",
        f"    reported_count: {_yaml_scalar(summary.get('reported_count'))}",
        "  items:",
    ]
    items = summary.get("items") if isinstance(summary.get("items"), list) else []
    if not items:
        lines.append("    []")
    for item in items:
        if not isinstance(item, dict):
            continue
        lines.extend(
            [
                f"    - sequence_number: {_yaml_scalar(item.get('sequence_number'))}",
                f"      task_human_id: {_yaml_scalar(item.get('task_human_id'))}",
                f"      source_photo_title: {_yaml_scalar(item.get('source_photo_title'))}",
                f"      path_label: {_yaml_scalar(item.get('path_label'))}",
                f"      preview_ready: {_yaml_scalar(item.get('preview_ready'))}",
                f"      missing_adam_field_count: {_yaml_scalar(item.get('missing_adam_field_count'))}",
                f"      downstream_payoff_score: {_yaml_scalar(item.get('downstream_payoff_score'))}",
                f"      next_action: {_yaml_scalar(item.get('next_action'))}",
                "      missing_fields:",
            ]
        )
        fields = item.get("missing_fields") if isinstance(item.get("missing_fields"), list) else []
        if fields:
            for field in fields:
                lines.append(f"        - {_yaml_scalar(field)}")
        else:
            lines.append("        []")
    return "\n".join(lines) + "\n"


def build_photo_review_priority_summary(*, session: Session, focus: str = "fastest_vector", limit: int = 10) -> Dict[str, Any]:
    safe_limit = max(1, min(limit, 50))
    tasks = session.exec(
        select(Task)
        .where(Task.status == "ready")
        .where(Task.task_type.in_(PHOTO_REVIEW_TASK_TYPES))
    ).all()
    ranked = [(photo_priority_rank(task), task) for task in tasks]
    if focus == "fastest_vector":
        ranked = [(rank, task) for rank, task in ranked if rank < 3]
    ranked_rows = []
    for rank, task in ranked:
        asset = _task_asset(session, task)
        explanation = _priority_explanation(task, rank)
        missing_field_count = len(explanation.get("missing_fields") or [])
        retrieval_query = _retrieval_query(task)
        preview_ready = _asset_preview_ready(asset)
        downstream_payoff_score = _downstream_payoff_score(
            rank=rank,
            missing_field_count=missing_field_count,
            preview_ready=preview_ready,
            has_retrieval_query=bool(retrieval_query),
        )
        ranked_rows.append(
            {
                "rank": rank,
                "task": task,
                "asset": asset,
                "explanation": explanation,
                "retrieval_query": retrieval_query,
                "preview_ready": preview_ready,
                "missing_field_count": missing_field_count,
                "downstream_payoff_score": downstream_payoff_score,
            }
        )
    ranked_rows.sort(
        key=lambda row: (
            int(row["rank"]),
            int(row["missing_field_count"]),
            -int(row["downstream_payoff_score"]),
            -int(row["task"].priority),
            -row["task"].created_at.timestamp(),
        )
    )

    items: List[Dict[str, Any]] = []
    for sequence_number, row in enumerate(ranked_rows[:safe_limit], start=1):
        task = row["task"]
        asset = row["asset"]
        rank = int(row["rank"])
        retrieval_query = str(row["retrieval_query"] or "")
        explanation = row["explanation"]
        items.append(
            {
                "sequence_number": sequence_number,
                "rank": rank,
                "path_label": _rank_label(rank),
                "task_id": task.id,
                "task_human_id": task.human_id,
                "task_type": task.task_type,
                "queue": task.queue,
                "priority": task.priority,
                "source_photo_id": asset.id if asset else task.target_id if task.target_type == "asset" else None,
                "source_photo_title": _photo_title(asset, task),
                "retrieval_query": retrieval_query or None,
                "preview_ready": bool(row["preview_ready"]),
                "not_memory_claim": True,
                "missing_adam_field_count": int(row["missing_field_count"]),
                "downstream_payoff_score": int(row["downstream_payoff_score"]),
                "next_action": "open_review_task",
                "completion_signal": COMPLETION_SIGNAL,
                "ranking_inputs": {
                    "path_rank": rank,
                    "preview_ready": bool(row["preview_ready"]),
                    "missing_adam_field_count": int(row["missing_field_count"]),
                    "downstream_payoff_score": int(row["downstream_payoff_score"]),
                    "has_retrieval_query": bool(retrieval_query),
                    "task_priority": task.priority,
                },
                **explanation,
            }
        )

    summary: Dict[str, Any] = {
        "summary_type": "photo_review_priority",
        "focus": focus,
        "review_policy": "prioritization_only_no_memory_claim_until_submit",
        "throughput_policy": THROUGHPUT_POLICY,
        "does_not_mutate_state": True,
        "does_not_create_memory_claim": True,
        "no_live_model_call": True,
        "no_live_embedding_call": True,
        "completion_signal": COMPLETION_SIGNAL,
        "ranking_inputs": {
            "primary": "path_rank",
            "secondary": "missing_adam_field_count",
            "tertiary": "downstream_payoff_score",
        },
        "total_candidate_count": len(ranked_rows),
        "reported_count": len(items),
        "items": items,
    }
    stable_payload = {
        "summary_type": summary["summary_type"],
        "focus": summary["focus"],
        "review_policy": summary["review_policy"],
        "throughput_policy": summary["throughput_policy"],
        "completion_signal": summary["completion_signal"],
        "total_candidate_count": summary["total_candidate_count"],
        "reported_count": summary["reported_count"],
        "items": [
            {
                "sequence_number": item["sequence_number"],
                "rank": item["rank"],
                "task_human_id": item["task_human_id"],
                "source_photo_id": item["source_photo_id"],
                "missing_adam_field_count": item["missing_adam_field_count"],
                "downstream_payoff_score": item["downstream_payoff_score"],
                "preview_ready": item["preview_ready"],
                "ranking_inputs": item["ranking_inputs"],
            }
            for item in items
        ],
    }
    summary["content_sha256"] = _stable_hash(stable_payload)
    summary["export_preview_yaml"] = _priority_yaml(summary)
    summary["export_preview_sha256"] = hashlib.sha256(summary["export_preview_yaml"].encode("utf-8")).hexdigest()
    return summary
