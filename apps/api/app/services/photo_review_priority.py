from __future__ import annotations

from typing import Any, Dict, List, Optional

from sqlmodel import Session, select

from app.models import Asset, Task


PHOTO_REVIEW_TASK_TYPES = {"photo_context", "vision_draft_review"}


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
    ranked.sort(key=lambda item: (item[0], -item[1].priority, -item[1].created_at.timestamp()))

    items: List[Dict[str, Any]] = []
    for rank, task in ranked[:safe_limit]:
        asset = _task_asset(session, task)
        explanation = _priority_explanation(task, rank)
        items.append(
            {
                "rank": rank,
                "path_label": _rank_label(rank),
                "task_id": task.id,
                "task_human_id": task.human_id,
                "task_type": task.task_type,
                "queue": task.queue,
                "priority": task.priority,
                "source_photo_id": asset.id if asset else task.target_id if task.target_type == "asset" else None,
                "source_photo_title": _photo_title(asset, task),
                "retrieval_query": _retrieval_query(task) or None,
                "not_memory_claim": True,
                **explanation,
            }
        )

    return {
        "summary_type": "photo_review_priority",
        "focus": focus,
        "review_policy": "prioritization_only_no_memory_claim_until_submit",
        "does_not_mutate_state": True,
        "no_live_model_call": True,
        "total_candidate_count": len(ranked),
        "reported_count": len(items),
        "items": items,
    }
