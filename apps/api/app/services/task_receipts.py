from __future__ import annotations

from typing import Any, Dict, List, Optional

from sqlmodel import Session, select

from app.models import Boundary, DPOPair, SFTCandidate, Task, TaskReceipt, utcnow


def _count(session: Session) -> int:
    return len(session.exec(select(TaskReceipt)).all()) + 1


def _human_id(count: int) -> str:
    return f"RECEIPT_{count:06d}"


def _boundary_status(session: Session, creates_or_updates: Dict[str, Any]) -> tuple[str, List[str], Optional[Dict[str, Any]]]:
    boundary_id = creates_or_updates.get("boundary_id")
    if not isinstance(boundary_id, str):
        return "unknown", [], None

    boundary = session.get(Boundary, boundary_id)
    if boundary is None:
        return "unknown", ["boundary_record_missing"], None

    snapshot = boundary.model_dump(mode="json")
    reasons: List[str] = []
    if boundary.privacy_level in {"sealed", "private_sensitive"}:
        reasons.append(f"privacy_level={boundary.privacy_level}")
    if boundary.redaction_required:
        reasons.append("redaction_required")
    if not boundary.searchable and not boundary.usable_for_voice_context and not boundary.usable_for_eval:
        reasons.append("no_downstream_use_enabled")
    status = "blocked" if reasons else "passed"
    return status, reasons, snapshot


def _gold_status(session: Session, creates_or_updates: Dict[str, Any]) -> tuple[str, List[str]]:
    sft_id = creates_or_updates.get("sft_candidate_id")
    dpo_id = creates_or_updates.get("dpo_pair_id")
    if isinstance(sft_id, str):
        sft = session.get(SFTCandidate, sft_id)
        if sft is None:
            return "recorded", ["sft_candidate_missing"]
        if sft.export_status != "approved":
            return "candidate", [f"sft_export_status={sft.export_status}"]
        return "export_ready", []
    if isinstance(dpo_id, str):
        dpo = session.get(DPOPair, dpo_id)
        if dpo is None:
            return "recorded", ["dpo_pair_missing"]
        if dpo.export_status != "approved":
            return "candidate", [f"dpo_export_status={dpo.export_status}"]
        return "export_ready", []
    return "recorded", []


def _export_artifact_summary(session: Session, creates_or_updates: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    gold_id = creates_or_updates.get("gold_voice_example_id")
    sft_id = creates_or_updates.get("sft_candidate_id")
    dpo_id = creates_or_updates.get("dpo_pair_id")
    if not any(isinstance(value, str) and value for value in [gold_id, sft_id, dpo_id]):
        return None

    statuses: Dict[str, str] = {}
    artifact_ids: Dict[str, str] = {}
    blockers: List[str] = []
    checks: Dict[str, Any] = {}

    if isinstance(gold_id, str) and gold_id:
        artifact_ids["gold_voice_example_id"] = gold_id

    if isinstance(sft_id, str) and sft_id:
        artifact_ids["sft_candidate_id"] = sft_id
        sft = session.get(SFTCandidate, sft_id)
        if sft is None:
            statuses["sft"] = "missing"
            blockers.append("sft_candidate_missing")
        else:
            statuses["sft"] = sft.export_status
            quality_gate = sft.quality_gate if isinstance(sft.quality_gate, dict) else {}
            export_blockers = quality_gate.get("export_blockers")
            if isinstance(export_blockers, list):
                blockers.extend(str(blocker) for blocker in export_blockers if str(blocker).strip())
            if sft.export_status != "approved":
                blockers.append(f"sft_export_status={sft.export_status}")
            messages = sft.messages if isinstance(sft.messages, list) else []
            checks["sft_message_count"] = len(messages)
            checks["sft_has_system_user_assistant"] = [message.get("role") for message in messages if isinstance(message, dict)] == [
                "system",
                "user",
                "assistant",
            ]

    if isinstance(dpo_id, str) and dpo_id:
        artifact_ids["dpo_pair_id"] = dpo_id
        dpo = session.get(DPOPair, dpo_id)
        if dpo is None:
            statuses["dpo"] = "missing"
            blockers.append("dpo_pair_missing")
        else:
            statuses["dpo"] = dpo.export_status
            reasons = [str(reason) for reason in dpo.reason] if isinstance(dpo.reason, list) else []
            blockers.extend(reason for reason in reasons if reason.startswith("dpo_"))
            if dpo.export_status != "approved":
                blockers.append(f"dpo_export_status={dpo.export_status}")
            checks["dpo_reason_count"] = len(reasons)
            prompt = dpo.prompt or ""
            chosen = dpo.chosen or ""
            rejected = dpo.rejected or ""
            checks["dpo_has_prompt_chosen_rejected"] = bool(prompt.strip() and chosen.strip() and rejected.strip())
            checks["dpo_chosen_rejected_distinct"] = chosen.strip() != rejected.strip()

    modes = list(statuses.keys())
    return {
        "artifact_ids": artifact_ids,
        "artifact_modes": modes,
        "primary_artifact_mode": modes[0] if modes else "gold_voice",
        "statuses": statuses,
        "export_ready": bool(statuses) and all(status == "approved" for status in statuses.values()),
        "review_blockers": list(dict.fromkeys(blockers)),
        "checks": checks,
    }


def _next_action(task: Task, creates_or_updates: Dict[str, Any], downstream_status: str) -> tuple[str, Optional[str]]:
    if isinstance(creates_or_updates.get("segment_boundary_review_task_id"), str):
        return "Review extracted chunks and boundaries", "text_segments_needing_boundary_review"
    if isinstance(creates_or_updates.get("prompt_pair_candidate_task_id"), str):
        return "Create a grounded prompt pair draft", "grounded_prompt_pairs_needing_drafts"
    if isinstance(creates_or_updates.get("make_gold_task_ids"), list) and creates_or_updates.get("make_gold_task_ids"):
        return "Review generated prompt pairs", "prompt_pairs_needing_gold_edits"
    if isinstance(creates_or_updates.get("review_task_id"), str):
        if task.task_type == "asset_triage":
            return "Review photo memory metadata", "vision_drafts_needing_review"
        return "Review the generated prompt pair", "prompt_pairs_needing_gold_edits"
    if task.task_type in {"photo_context", "vision_draft_review"}:
        return "Use photo metadata in retrieval/context packs", None
    if task.task_type == "gold_voice_edit":
        if downstream_status == "export_ready":
            return "Review or build JSONL export", "dataset_exports"
        return "Resolve prompt-pair export blockers", "prompt_pairs_needing_gold_edits"
    return "Pick the next ready task", None


def _outcomes(creates_or_updates: Dict[str, Any]) -> List[Dict[str, str]]:
    labels = {
        "metadata_profile_id": "Metadata profile",
        "boundary_id": "Boundary",
        "memory_id": "Memory",
        "memory_source_id": "Memory source",
        "graph_edge_id": "Graph link",
        "gallery_item_id": "Gallery item",
        "embedding_record_id": "Embedding record",
        "photo_embedding_record_id": "Photo embedding plan",
        "memory_embedding_record_id": "Memory embedding plan",
        "vector_handoff_record_id": "Vector handoff record",
        "ocr_segment_id": "OCR/handwriting segment",
        "voice_reference_example_ids": "Voice references",
        "gold_voice_example_id": "Gold voice example",
        "sft_candidate_id": "SFT candidate",
        "dpo_pair_id": "DPO pair",
        "eval_case_id": "Eval case",
        "anti_pattern_id": "Anti-pattern",
        "style_rule_id": "Style rule",
        "prompt_pair_candidate_task_id": "Prompt pair task",
        "review_task_id": "Prompt pair task",
        "make_gold_task_ids": "Prompt pair tasks",
        "pair_generation_run": "Pair generation run",
        "source_span_annotation_ids": "Source span annotations",
        "segment_boundary_review_task_id": "Boundary review task",
    }
    rows: List[Dict[str, str]] = []
    for key, label in labels.items():
        value = creates_or_updates.get(key)
        if isinstance(value, str) and value:
            rows.append({"label": label, "id": value})
        elif isinstance(value, list) and value:
            rows.append({"label": label, "id": f"{len(value)} created"})
    return rows


def _retrieval_origin(task: Task) -> Optional[Dict[str, Any]]:
    origin = (task.input_payload or {}).get("retrieval_gap_origin")
    if not isinstance(origin, dict):
        return None
    query = origin.get("query")
    if not isinstance(query, str) or not query.strip():
        return None
    return {
        "query": query.strip(),
        "candidate_match_quality": origin.get("candidate_match_quality") or "unknown",
        "selection_reason": origin.get("selection_reason") or "unknown",
        "truth_status": origin.get("truth_status") or "no_claim",
        "not_memory_claim": origin.get("not_memory_claim") is True,
    }


def _review_session_origin(task: Task) -> Optional[Dict[str, Any]]:
    origin = (task.input_payload or {}).get("review_session_origin")
    if not isinstance(origin, dict):
        return None

    return {
        "sequence_number": origin.get("sequence_number"),
        "selected_count": origin.get("selected_count"),
        "source_query": origin.get("source_query"),
        "plan_content_sha256": origin.get("plan_content_sha256"),
        "completion_signal": origin.get("completion_signal"),
        "review_policy": origin.get("review_policy"),
        "not_memory_claim": origin.get("not_memory_claim") is True,
    }


def create_task_receipt(
    *,
    session: Session,
    task: Task,
    annotation_id: str,
    creates_or_updates: Dict[str, Any],
) -> TaskReceipt:
    boundary_status, boundary_reasons, boundary_snapshot = _boundary_status(session, creates_or_updates)
    downstream_status, downstream_reasons = _gold_status(session, creates_or_updates)
    if downstream_status == "recorded" and boundary_status == "blocked":
        downstream_status = "blocked"
    blocked_reasons = [*boundary_reasons, *downstream_reasons]
    next_action_label, next_queue = _next_action(task, creates_or_updates, downstream_status)

    receipt = TaskReceipt(
        human_id=_human_id(_count(session)),
        task_id=task.id,
        annotation_id=annotation_id,
        task_type=task.task_type,
        target_type=task.target_type,
        target_id=task.target_id,
        created_or_updated=creates_or_updates,
        downstream_status=downstream_status,
        boundary_status=boundary_status,
        blocked_reasons=blocked_reasons,
        next_action_label=next_action_label,
        next_queue=next_queue,
        summary={
            "outcomes": _outcomes(creates_or_updates),
            "boundary_snapshot": boundary_snapshot,
            "retrieval_origin": _retrieval_origin(task),
            "review_session_origin": _review_session_origin(task),
            "export_artifact": _export_artifact_summary(session, creates_or_updates),
            "pair_generation_run": creates_or_updates.get("pair_generation_run"),
            "submit_projection": creates_or_updates.get("submit_projection"),
            "created_at": utcnow().isoformat(),
        },
    )
    session.add(receipt)
    session.flush()
    return receipt
