from __future__ import annotations

import hashlib
import json
from collections import Counter
from typing import Any, Dict, List, Optional

from sqlmodel import Session, select

from app.models import Asset, Task, TaskDraft
from app.services.photo_context_projection import build_photo_context_submit_projection


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


def _sorted_counts(counts: Dict[str, int]) -> List[Dict[str, Any]]:
    return [
        {"field_key": key, "count": count}
        for key, count in sorted(counts.items(), key=lambda item: (-int(item[1]), item[0]))
    ]


def _sorted_query_counts(counts: Dict[str, int]) -> List[Dict[str, Any]]:
    return [
        {"query": key, "count": count}
        for key, count in sorted(counts.items(), key=lambda item: (-int(item[1]), item[0]))
    ]


FIELD_GUIDANCE: Dict[str, Dict[str, str]] = {
    "visual_description_correction": {
        "label": "Reviewed visible facts",
        "why_required": "Grounds the record in what is actually visible before any memory context is added.",
        "adam_prompt": "Correct or confirm the visual description in plain language.",
        "unlocks": "A reviewed visual anchor for semantic search and gallery display.",
    },
    "retrieval_query_relevance": {
        "label": "Search seed connection",
        "why_required": "Optional unless the photo genuinely surfaced from search evidence; backlog-only review seeds are not memory questions.",
        "adam_prompt": "If the photo actually connects to the search seed, say how. Otherwise leave this blank and write the memory the photo itself brings up.",
        "unlocks": "Better ranking for future searches while preserving weak search seeds as provenance rather than memory evidence.",
    },
    "invisible_context_note": {
        "label": "Adam memory context",
        "why_required": "Captures meaning, relationships, or event context that is not visible in the image itself.",
        "adam_prompt": "Add the remembered story, relationship, event, or uncertainty behind the image.",
        "unlocks": "Embedding text that can support memory-like retrieval after Adam review.",
    },
    "open_questions": {
        "label": "Open questions",
        "why_required": "Keeps uncertainty explicit instead of letting the system fill gaps with inference.",
        "adam_prompt": "List what remains unknown: date, place, people, photographer, or event.",
        "unlocks": "A no-claim record that remains useful while preserving uncertainty.",
    },
    "privacy_level": {
        "label": "Boundary and permission",
        "why_required": "Determines whether the reviewed context can be searched, retrieved, shown, or exported.",
        "adam_prompt": "Choose the privacy level and any usage limits for this photo context.",
        "unlocks": "Boundary-cleared handoff to gallery, vector, voice-context, or review-only queues.",
    },
}


def _field_guidance_for_keys(field_keys: List[str]) -> List[Dict[str, str]]:
    guidance = []
    for field_key in sorted(set(field_keys)):
        defaults = {
            "label": field_key.replace("_", " ").title(),
            "why_required": "Documents why this field is needed before downstream use.",
            "adam_prompt": "Add Adam-authored context or mark the field not applicable.",
            "unlocks": "A more complete reviewed photo-context record.",
        }
        item = {**defaults, **FIELD_GUIDANCE.get(field_key, {})}
        guidance.append({"field_key": field_key, **item})
    return guidance


def _task_asset(session: Session, task: Task) -> Optional[Asset]:
    return session.get(Asset, task.target_id) if task.target_type == "asset" else None


def _task_title(session: Session, task: Task) -> str:
    asset = _task_asset(session, task)
    return (
        (asset.title if asset else None)
        or task.input_payload.get("asset_title")
        or task.input_payload.get("source_title")
        or task.human_id
    )


def _draft_for_task(session: Session, task_id: str, user_id: str) -> Optional[TaskDraft]:
    return session.exec(
        select(TaskDraft).where(TaskDraft.task_id == task_id).where(TaskDraft.user_id == user_id)
    ).first()


def _progress_status(*, has_draft: bool, projection: Optional[Dict[str, Any]]) -> str:
    if not has_draft:
        return "needs_draft"
    blocked_reasons = projection.get("blocked_reasons", []) if projection else []
    if not blocked_reasons:
        return "submit_ready"
    if "missing_reviewed_memory_text" in blocked_reasons:
        return "needs_more_context"
    if "not_ready_for_downstream" in blocked_reasons:
        return "held_pending_downstream_clearance"
    if "excluded_by_boundary" in blocked_reasons or "boundary_redaction_required" in blocked_reasons:
        return "boundary_excluded"
    return "draft_has_blockers"


def _task_retrieval_origin(task: Task) -> Optional[Dict[str, Any]]:
    origin = (task.input_payload or {}).get("retrieval_gap_origin")
    return origin if isinstance(origin, dict) and origin.get("query") else None


def _task_review_session_origin(task: Task) -> Optional[Dict[str, Any]]:
    origin = (task.input_payload or {}).get("review_session_origin")
    if not isinstance(origin, dict):
        return None
    return origin if origin.get("session_type") == "photo_context_review_session" else None


def _task_retrieval_review(task: Task) -> Dict[str, Any]:
    review = (task.input_payload or {}).get("retrieval_gap_review")
    return review if isinstance(review, dict) else {}


def _missing_retrieval_fields(*, task: Task, projection: Optional[Dict[str, Any]]) -> List[str]:
    origin = _task_retrieval_origin(task)
    if not origin:
        return []
    candidate_match_quality = str(origin.get("candidate_match_quality") or "")
    optional_field_keys = {"retrieval_query_relevance"} if candidate_match_quality == "backlog_only" else set()
    if projection:
        requirements = projection.get("field_requirements", [])
        if isinstance(requirements, list):
            return [
                str(item.get("field_key"))
                for item in requirements
                if isinstance(item, dict) and item.get("field_key") and item.get("status") != "complete"
                and str(item.get("field_key")) not in optional_field_keys
            ]
    review = _task_retrieval_review(task)
    fields = review.get("required_fields", [])
    if isinstance(fields, list) and fields:
        return [
            str(item.get("field_key"))
            for item in fields
            if isinstance(item, dict) and item.get("field_key") and str(item.get("field_key")) not in optional_field_keys
        ]
    default_fields = [
        "visual_description_correction",
        "retrieval_query_relevance",
        "invisible_context_note",
        "open_questions",
        "privacy_level",
    ]
    return [field for field in default_fields if field not in optional_field_keys]


def build_photo_context_session_progress(
    *,
    session: Session,
    scope: str = "family_private",
    limit: int = 100,
    user_id: str = "adam",
) -> Dict[str, Any]:
    tasks = session.exec(
        select(Task)
        .where(Task.task_type == "photo_context")
        .order_by(Task.created_at.asc())
    ).all()
    capped_tasks = tasks[:limit]
    items: List[Dict[str, Any]] = []
    blocked_reason_counts: Counter[str] = Counter()
    status_counts: Counter[str] = Counter()
    retrieval_gap_missing_field_counts: Counter[str] = Counter()
    draft_count = 0
    submit_ready_count = 0
    retrieval_gap_task_count = 0
    review_session_task_count = 0

    for task in capped_tasks:
        draft = _draft_for_task(session, task.id, user_id)
        projection = None
        retrieval_origin = _task_retrieval_origin(task)
        review_session_origin = _task_review_session_origin(task)
        retrieval_review = _task_retrieval_review(task)
        if draft is not None:
            draft_count += 1
            projection = build_photo_context_submit_projection(
                session=session,
                task=task,
                decisions=draft.decisions or {},
            )
            for reason in projection.get("blocked_reasons", []):
                blocked_reason_counts[str(reason)] += 1
        progress_status = _progress_status(has_draft=draft is not None, projection=projection)
        if progress_status == "submit_ready":
            submit_ready_count += 1
        status_counts[progress_status] += 1
        missing_retrieval_fields = _missing_retrieval_fields(task=task, projection=projection)
        if retrieval_origin:
            retrieval_gap_task_count += 1
            for field in missing_retrieval_fields:
                retrieval_gap_missing_field_counts[field] += 1
        if review_session_origin:
            review_session_task_count += 1
        provenance_boundary = {
            "retrieval_origin_truth_status": retrieval_origin.get("truth_status") if retrieval_origin else None,
            "retrieval_origin_not_memory_claim": bool(retrieval_origin and retrieval_origin.get("not_memory_claim") is True),
            "review_session_origin_not_memory_claim": bool(
                review_session_origin and review_session_origin.get("not_memory_claim") is True
            ),
            "query_is_context_prioritization_only": bool(
                retrieval_origin is not None
                or (review_session_origin or {}).get("query_is_context_prioritization_only") is True
            ),
            "vector_ready_requires_submit": True,
        }
        items.append(
            {
                "task_id": task.id,
                "task_human_id": task.human_id,
                "queue": task.queue,
                "task_status": task.status,
                "source_photo_id": task.target_id,
                "source_photo_title": _task_title(session, task),
                "has_draft": draft is not None,
                "draft_updated_at": draft.updated_at.isoformat() if draft else None,
                "progress_status": progress_status,
                "blocked_reasons": projection.get("blocked_reasons", []) if projection else [],
                "vector_handoff_status": (
                    projection.get("memory_embedding_vector_handoff", {}).get("status") if projection else None
                ),
                "gallery_scope_after": projection.get("gallery", {}).get("scope_after") if projection else None,
                "projection": projection,
                "retrieval_gap_origin": retrieval_origin,
                "review_session_origin": review_session_origin,
                "provenance_boundary": provenance_boundary,
                "retrieval_gap_review_policy": retrieval_review.get("review_policy"),
                "retrieval_gap_completion_signal": retrieval_review.get("completion_signal"),
                "retrieval_gap_missing_fields": missing_retrieval_fields,
                "next_action": "submit_review" if progress_status == "submit_ready" else "continue_review",
            }
        )

    no_draft_count = len(capped_tasks) - draft_count
    completion_signal = "submit_ready_count_increases_or_retrieval_gap_missing_fields_decrease"
    safety_boundaries = [
        "Progress is projected from saved drafts and does not mutate tasks, memories, assets, or raw files.",
        "A submit-ready projection is not a memory claim until Adam submits the review.",
        "No embedding record is created by reading this progress proof.",
    ]
    progress_items = [
        {
            "task_id": item["task_id"],
            "task_human_id": item["task_human_id"],
            "progress_status": item["progress_status"],
            "has_draft": item["has_draft"],
            "blocked_reasons": item["blocked_reasons"],
            "vector_handoff_status": item["vector_handoff_status"],
            "retrieval_gap_origin": item["retrieval_gap_origin"],
            "review_session_origin": item["review_session_origin"],
            "provenance_boundary": item["provenance_boundary"],
            "retrieval_gap_missing_fields": item["retrieval_gap_missing_fields"],
        }
        for item in items
    ]
    stable_payload = {
        "progress_type": "photo_context_session_progress",
        "scope": scope,
        "user_id": user_id,
        "review_policy": "drafts_projected_without_mutation",
        "does_not_mutate_state": True,
        "does_not_create_memory_claim": True,
        "does_not_create_embedding_record": True,
        "requires_adam_context": True,
        "completion_signal": completion_signal,
        "safety_boundaries": safety_boundaries,
        "total_context_task_count": len(tasks),
        "reported_task_count": len(capped_tasks),
        "draft_count": draft_count,
        "submit_ready_count": submit_ready_count,
        "retrieval_gap_task_count": retrieval_gap_task_count,
        "review_session_task_count": review_session_task_count,
        "retrieval_gap_missing_field_counts": dict(sorted(retrieval_gap_missing_field_counts.items())),
        "status_counts": dict(sorted(status_counts.items())),
        "blocked_reason_counts": dict(sorted(blocked_reason_counts.items())),
        "items": progress_items,
    }
    payload = {
        "progress_type": "photo_context_session_progress",
        "scope": scope,
        "user_id": user_id,
        "review_policy": "drafts_projected_without_mutation",
        "does_not_mutate_state": True,
        "does_not_create_memory_claim": True,
        "does_not_create_embedding_record": True,
        "requires_adam_context": True,
        "limit": limit,
        "total_context_task_count": len(tasks),
        "reported_task_count": len(capped_tasks),
        "draft_count": draft_count,
        "no_draft_count": no_draft_count,
        "submit_ready_count": submit_ready_count,
        "blocked_count": draft_count - submit_ready_count,
        "retrieval_gap_task_count": retrieval_gap_task_count,
        "review_session_task_count": review_session_task_count,
        "provenance_policy": {
            "retrieval_gap_origin_is_not_memory_claim": True,
            "review_session_origin_is_not_memory_claim": True,
            "query_is_context_prioritization_only": True,
            "vector_ready_requires_submit": True,
        },
        "retrieval_gap_missing_field_counts": dict(retrieval_gap_missing_field_counts),
        "status_counts": dict(status_counts),
        "blocked_reason_counts": dict(blocked_reason_counts),
        "completion_signal": completion_signal,
        "safety_boundaries": safety_boundaries,
        "items": items,
    }
    payload["content_sha256"] = _stable_hash(stable_payload)
    return payload


def build_photo_context_session_progress_artifact(
    *,
    session: Session,
    scope: str = "family_private",
    limit: int = 100,
    user_id: str = "adam",
) -> Dict[str, Any]:
    progress = build_photo_context_session_progress(
        session=session,
        scope=scope,
        limit=limit,
        user_id=user_id,
    )
    items = []
    progress_items = progress.get("items") if isinstance(progress.get("items"), list) else []
    for item in progress_items:
        if not isinstance(item, dict):
            continue
        items.append(
            {
                "task_id": item.get("task_id"),
                "task_human_id": item.get("task_human_id"),
                "queue": item.get("queue"),
                "task_status": item.get("task_status"),
                "source_photo_id": item.get("source_photo_id"),
                "source_photo_title": item.get("source_photo_title"),
                "has_draft": item.get("has_draft") is True,
                "progress_status": item.get("progress_status"),
                "blocked_reasons": item.get("blocked_reasons") if isinstance(item.get("blocked_reasons"), list) else [],
                "vector_handoff_status": item.get("vector_handoff_status"),
                "retrieval_gap_origin": item.get("retrieval_gap_origin"),
                "review_session_origin": item.get("review_session_origin"),
                "provenance_boundary": item.get("provenance_boundary"),
                "retrieval_gap_missing_fields": (
                    item.get("retrieval_gap_missing_fields")
                    if isinstance(item.get("retrieval_gap_missing_fields"), list)
                    else []
                ),
                "next_action": item.get("next_action"),
            }
        )
    artifact = {
        "artifact_type": "photo_context_session_progress_artifact",
        "progress_type": progress.get("progress_type"),
        "scope": progress.get("scope"),
        "user_id": progress.get("user_id"),
        "review_policy": progress.get("review_policy"),
        "does_not_mutate_state": progress.get("does_not_mutate_state") is True,
        "does_not_create_memory_claim": progress.get("does_not_create_memory_claim") is True,
        "does_not_create_embedding_record": progress.get("does_not_create_embedding_record") is True,
        "requires_adam_context": progress.get("requires_adam_context") is True,
        "completion_signal": progress.get("completion_signal"),
        "safety_boundaries": progress.get("safety_boundaries") if isinstance(progress.get("safety_boundaries"), list) else [],
        "source_progress_content_sha256": progress.get("content_sha256"),
        "total_context_task_count": progress.get("total_context_task_count"),
        "reported_task_count": progress.get("reported_task_count"),
        "draft_count": progress.get("draft_count"),
        "no_draft_count": progress.get("no_draft_count"),
        "submit_ready_count": progress.get("submit_ready_count"),
        "blocked_count": progress.get("blocked_count"),
        "retrieval_gap_task_count": progress.get("retrieval_gap_task_count"),
        "review_session_task_count": progress.get("review_session_task_count"),
        "provenance_policy": progress.get("provenance_policy"),
        "retrieval_gap_missing_field_counts": progress.get("retrieval_gap_missing_field_counts"),
        "status_counts": progress.get("status_counts"),
        "blocked_reason_counts": progress.get("blocked_reason_counts"),
        "items": items,
    }
    artifact["content_sha256"] = _stable_hash(artifact)
    return artifact


def _retrieval_gap_field_worklist_yaml(worklist: Dict[str, Any]) -> str:
    lines = [
        "photo_context_retrieval_gap_field_worklist:",
        f"  worklist_type: {_yaml_scalar(worklist.get('worklist_type'))}",
        f"  scope: {_yaml_scalar(worklist.get('scope'))}",
        f"  user_id: {_yaml_scalar(worklist.get('user_id'))}",
        f"  review_policy: {_yaml_scalar(worklist.get('review_policy'))}",
        f"  content_sha256: {_yaml_scalar(worklist.get('content_sha256'))}",
        "  boundaries:",
        f"    does_not_mutate_state: {_yaml_scalar(worklist.get('does_not_mutate_state'))}",
        f"    does_not_create_memory_claim: {_yaml_scalar(worklist.get('does_not_create_memory_claim'))}",
        f"    requires_adam_context: {_yaml_scalar(worklist.get('requires_adam_context'))}",
        f"    no_live_model_call: {_yaml_scalar(worklist.get('no_live_model_call'))}",
        f"    no_live_embedding_call: {_yaml_scalar(worklist.get('no_live_embedding_call'))}",
        "  counts:",
        f"    retrieval_gap_task_count: {_yaml_scalar(worklist.get('retrieval_gap_task_count'))}",
        f"    reported_item_count: {_yaml_scalar(worklist.get('reported_item_count'))}",
        f"    missing_field_total: {_yaml_scalar(worklist.get('missing_field_total'))}",
        f"    submit_ready_count: {_yaml_scalar(worklist.get('submit_ready_count'))}",
        "  missing_field_counts:",
    ]
    field_counts = worklist.get("missing_field_counts") if isinstance(worklist.get("missing_field_counts"), list) else []
    if field_counts:
        for item in field_counts:
            if not isinstance(item, dict):
                continue
            lines.extend(
                [
                    f"    - field_key: {_yaml_scalar(item.get('field_key'))}",
                    f"      count: {_yaml_scalar(item.get('count'))}",
                ]
            )
    else:
        lines.append("    []")
    lines.append("  field_guidance:")
    guidance_items = worklist.get("field_guidance") if isinstance(worklist.get("field_guidance"), list) else []
    if guidance_items:
        for item in guidance_items:
            if not isinstance(item, dict):
                continue
            lines.extend(
                [
                    f"    - field_key: {_yaml_scalar(item.get('field_key'))}",
                    f"      label: {_yaml_scalar(item.get('label'))}",
                    f"      why_required: {_yaml_scalar(item.get('why_required'))}",
                    f"      adam_prompt: {_yaml_scalar(item.get('adam_prompt'))}",
                    f"      unlocks: {_yaml_scalar(item.get('unlocks'))}",
                ]
            )
    else:
        lines.append("    []")
    lines.append("  queries:")
    query_counts = worklist.get("query_counts") if isinstance(worklist.get("query_counts"), list) else []
    if query_counts:
        for item in query_counts:
            if not isinstance(item, dict):
                continue
            lines.extend(
                [
                    f"    - query: {_yaml_scalar(item.get('query'))}",
                    f"      count: {_yaml_scalar(item.get('count'))}",
                ]
            )
    else:
        lines.append("    []")
    lines.append("  items:")
    items = worklist.get("items") if isinstance(worklist.get("items"), list) else []
    if not items:
        lines.append("    []")
    for item in items:
        if not isinstance(item, dict):
            continue
        lines.extend(
            [
                f"    - task_human_id: {_yaml_scalar(item.get('task_human_id'))}",
                f"      source_photo_title: {_yaml_scalar(item.get('source_photo_title'))}",
                f"      retrieval_query: {_yaml_scalar(item.get('retrieval_query'))}",
                f"      progress_status: {_yaml_scalar(item.get('progress_status'))}",
                f"      has_draft: {_yaml_scalar(item.get('has_draft'))}",
                f"      missing_field_count: {_yaml_scalar(item.get('missing_field_count'))}",
                "      missing_fields:",
            ]
        )
        missing_fields = item.get("missing_fields") if isinstance(item.get("missing_fields"), list) else []
        if missing_fields:
            for field in missing_fields:
                lines.append(f"        - {_yaml_scalar(field)}")
        else:
            lines.append("        []")
        lines.extend(
            [
                f"      next_action: {_yaml_scalar(item.get('next_action'))}",
                f"      completion_signal: {_yaml_scalar(item.get('completion_signal'))}",
            ]
        )
    return "\n".join(lines) + "\n"


def build_photo_context_retrieval_gap_field_worklist(
    *,
    session: Session,
    scope: str = "family_private",
    limit: int = 100,
    user_id: str = "adam",
) -> Dict[str, Any]:
    safe_limit = max(1, min(limit, 500))
    progress = build_photo_context_session_progress(
        session=session,
        scope=scope,
        limit=safe_limit,
        user_id=user_id,
    )
    progress_items = progress.get("items") if isinstance(progress.get("items"), list) else []
    retrieval_items = [
        item
        for item in progress_items
        if isinstance(item, dict)
        and isinstance(item.get("retrieval_gap_origin"), dict)
        and item.get("retrieval_gap_missing_fields")
    ]
    retrieval_items.sort(
        key=lambda item: (
            -len(item.get("retrieval_gap_missing_fields") if isinstance(item.get("retrieval_gap_missing_fields"), list) else []),
            str(item.get("source_photo_title") or ""),
            str(item.get("task_human_id") or ""),
        )
    )
    reported_items = retrieval_items[:safe_limit]
    query_counter: Counter[str] = Counter()
    items: List[Dict[str, Any]] = []
    missing_field_total = 0
    submit_ready_count = 0
    for sequence_number, item in enumerate(reported_items, start=1):
        origin = item.get("retrieval_gap_origin") if isinstance(item.get("retrieval_gap_origin"), dict) else {}
        query = str(origin.get("query") or "unknown_query")
        query_counter[query] += 1
        missing_fields = [
            str(field)
            for field in (item.get("retrieval_gap_missing_fields") if isinstance(item.get("retrieval_gap_missing_fields"), list) else [])
        ]
        missing_field_total += len(missing_fields)
        if item.get("progress_status") == "submit_ready":
            submit_ready_count += 1
        items.append(
            {
                "sequence_number": sequence_number,
                "task_id": item.get("task_id"),
                "task_human_id": item.get("task_human_id"),
                "queue": item.get("queue"),
                "source_photo_id": item.get("source_photo_id"),
                "source_photo_title": item.get("source_photo_title"),
                "retrieval_query": query,
                "candidate_match_quality": origin.get("candidate_match_quality"),
                "selection_reason": origin.get("selection_reason"),
                "truth_status": origin.get("truth_status") or "no_claim",
                "not_memory_claim": origin.get("not_memory_claim") is not False,
                "review_policy": item.get("retrieval_gap_review_policy") or "retrieval_gap_no_claim_until_adam_context",
                "completion_signal": item.get("retrieval_gap_completion_signal")
                or "visual_facts_query_relevance_adam_context_uncertainty_boundary",
                "has_draft": item.get("has_draft") is True,
                "progress_status": item.get("progress_status"),
                "missing_fields": missing_fields,
                "missing_field_count": len(missing_fields),
                "blocked_reasons": item.get("blocked_reasons") if isinstance(item.get("blocked_reasons"), list) else [],
                "next_action": item.get("next_action") or "continue_review",
            }
        )
    field_count_dict = (
        progress.get("retrieval_gap_missing_field_counts")
        if isinstance(progress.get("retrieval_gap_missing_field_counts"), dict)
        else {}
    )
    guidance_keys = [str(key) for key in field_count_dict] or list(FIELD_GUIDANCE)
    field_guidance = _field_guidance_for_keys(guidance_keys)
    stable_payload = {
        "scope": scope,
        "user_id": user_id,
        "retrieval_gap_task_count": progress.get("retrieval_gap_task_count"),
        "reported_item_count": len(items),
        "missing_field_counts": field_count_dict,
        "field_guidance": field_guidance,
        "query_counts": dict(query_counter),
        "items": items,
    }
    content_sha256 = _stable_hash(stable_payload)
    worklist: Dict[str, Any] = {
        "worklist_type": "photo_context_retrieval_gap_field_worklist",
        "scope": scope,
        "user_id": user_id,
        "review_policy": "retrieval_gap_missing_fields_no_memory_claim_until_adam_context",
        "does_not_mutate_state": True,
        "does_not_create_memory_claim": True,
        "requires_adam_context": True,
        "no_live_model_call": True,
        "no_live_embedding_call": True,
        "retrieval_gap_task_count": progress.get("retrieval_gap_task_count") or 0,
        "reported_item_count": len(items),
        "missing_field_total": missing_field_total,
        "submit_ready_count": submit_ready_count,
        "missing_field_counts": _sorted_counts({str(key): int(value) for key, value in field_count_dict.items()}),
        "field_guidance": field_guidance,
        "query_counts": _sorted_query_counts(dict(query_counter)),
        "completion_signal": "retrieval_gap_missing_field_counts_reach_zero_or_tasks_leave_gap_worklist",
        "items": items,
        "content_sha256": content_sha256,
    }
    export_preview_yaml = _retrieval_gap_field_worklist_yaml(worklist)
    worklist["export_preview_yaml"] = export_preview_yaml
    worklist["export_preview_sha256"] = hashlib.sha256(export_preview_yaml.encode("utf-8")).hexdigest()
    return worklist


def _retrieval_gap_payoff_preview_yaml(preview: Dict[str, Any]) -> str:
    lines = [
        "photo_context_retrieval_gap_payoff_preview:",
        f"  preview_type: {_yaml_scalar(preview.get('preview_type'))}",
        f"  scope: {_yaml_scalar(preview.get('scope'))}",
        f"  user_id: {_yaml_scalar(preview.get('user_id'))}",
        f"  review_policy: {_yaml_scalar(preview.get('review_policy'))}",
        f"  content_sha256: {_yaml_scalar(preview.get('content_sha256'))}",
        "  boundaries:",
        f"    does_not_mutate_state: {_yaml_scalar(preview.get('does_not_mutate_state'))}",
        f"    does_not_create_memory_claim: {_yaml_scalar(preview.get('does_not_create_memory_claim'))}",
        f"    uses_placeholders_for_missing_adam_context: {_yaml_scalar(preview.get('uses_placeholders_for_missing_adam_context'))}",
        f"    no_live_embedding_call: {_yaml_scalar(preview.get('no_live_embedding_call'))}",
        "  counts:",
        f"    reported_item_count: {_yaml_scalar(preview.get('reported_item_count'))}",
        f"    unlockable_vector_record_count: {_yaml_scalar(preview.get('unlockable_vector_record_count'))}",
        f"    current_submit_ready_count: {_yaml_scalar(preview.get('current_submit_ready_count'))}",
        "  items:",
    ]
    items = preview.get("items") if isinstance(preview.get("items"), list) else []
    if not items:
        lines.append("    []")
    for item in items:
        if not isinstance(item, dict):
            continue
        lines.extend(
            [
                f"    - task_human_id: {_yaml_scalar(item.get('task_human_id'))}",
                f"      source_photo_title: {_yaml_scalar(item.get('source_photo_title'))}",
                f"      retrieval_query: {_yaml_scalar(item.get('retrieval_query'))}",
                f"      payoff_score: {_yaml_scalar(item.get('payoff_score'))}",
                f"      after_completion_vector_status: {_yaml_scalar(item.get('after_completion_vector_status'))}",
                "      missing_fields:",
            ]
        )
        for field in item.get("missing_fields", []):
            lines.append(f"        - {_yaml_scalar(field)}")
        if not item.get("missing_fields"):
            lines.append("        []")
        lines.extend(
            [
                "      unlocked_records:",
                *[f"        - {_yaml_scalar(record)}" for record in item.get("unlocked_records", [])],
                "      vector_text_template: |-",
            ]
        )
        for line in str(item.get("vector_text_template") or "").splitlines():
            lines.append(f"        {line}")
    return "\n".join(lines) + "\n"


def _payoff_field_label(field_key: str) -> str:
    return {
        "visual_description_correction": "reviewed visible facts",
        "retrieval_query_relevance": "Adam's answer about search seed connection",
        "invisible_context_note": "Adam's invisible memory context",
        "open_questions": "explicit uncertainty/open questions",
        "privacy_level": "boundary and retrieval permission",
    }.get(field_key, field_key.replace("_", " "))


def _placeholder(field_key: str) -> str:
    return f"[requires Adam: {_payoff_field_label(field_key)}]"


def _current_projection_for_item(
    *,
    session: Session,
    item: Dict[str, Any],
    user_id: str,
) -> Optional[Dict[str, Any]]:
    task_id = item.get("task_id")
    if not isinstance(task_id, str):
        return None
    task = session.get(Task, task_id)
    if task is None:
        return None
    draft = _draft_for_task(session, task.id, user_id)
    if draft is None:
        return None
    return build_photo_context_submit_projection(
        session=session,
        task=task,
        decisions=draft.decisions or {},
    )


def build_photo_context_retrieval_gap_payoff_preview(
    *,
    session: Session,
    scope: str = "family_private",
    limit: int = 10,
    user_id: str = "adam",
) -> Dict[str, Any]:
    safe_limit = max(1, min(limit, 50))
    field_worklist = build_photo_context_retrieval_gap_field_worklist(
        session=session,
        scope=scope,
        limit=max(safe_limit, 100),
        user_id=user_id,
    )
    source_items = field_worklist.get("items") if isinstance(field_worklist.get("items"), list) else []
    items: List[Dict[str, Any]] = []
    unlockable_vector_record_count = 0
    current_submit_ready_count = 0
    for item in source_items[:safe_limit]:
        if not isinstance(item, dict):
            continue
        missing_fields = [str(field) for field in item.get("missing_fields", []) if isinstance(field, str)]
        current_projection = _current_projection_for_item(session=session, item=item, user_id=user_id)
        current_vector = (
            current_projection.get("memory_embedding_vector_handoff")
            if isinstance(current_projection, dict) and isinstance(current_projection.get("memory_embedding_vector_handoff"), dict)
            else {}
        )
        current_status = current_vector.get("status") if isinstance(current_vector, dict) else None
        if current_projection and current_projection.get("submit_readiness") == "ready_to_submit":
            current_submit_ready_count += 1
        query = str(item.get("retrieval_query") or "unknown query")
        title = str(item.get("source_photo_title") or "Untitled photo")
        missing_set = set(missing_fields)
        vector_text_template = "\n".join(
            [
                f"Photo memory: {title}",
                f"Search seed: {query}",
                f"Visible facts: {_placeholder('visual_description_correction') if 'visual_description_correction' in missing_set else '[draft visible facts present]'}",
                f"Search connection: {_placeholder('retrieval_query_relevance') if 'retrieval_query_relevance' in missing_set else '[draft search connection present]'}",
                f"Adam context: {_placeholder('invisible_context_note') if 'invisible_context_note' in missing_set else '[draft Adam context present]'}",
                f"Uncertainty: {_placeholder('open_questions') if 'open_questions' in missing_set else '[open questions reviewed]'}",
                f"Boundary: {_placeholder('privacy_level') if 'privacy_level' in missing_set else '[boundary selected]'}",
            ]
        )
        unlocks_vector = "privacy_level" in missing_set or "invisible_context_note" in missing_set or "retrieval_query_relevance" in missing_set
        unlockable_vector_record_count += 1 if unlocks_vector else 0
        unlocked_records = [
            "photo_memory_metadata_profile",
            "photo_memory_text_record",
            "reviewed_only_vector_handoff_record",
            "retrieval_search_candidate_for_query",
        ]
        payoff_score = len(missing_fields) + (3 if "retrieval_query_relevance" in missing_set else 0) + (2 if "privacy_level" in missing_set else 0)
        items.append(
            {
                "task_id": item.get("task_id"),
                "task_human_id": item.get("task_human_id"),
                "queue": item.get("queue"),
                "source_photo_id": item.get("source_photo_id"),
                "source_photo_title": title,
                "retrieval_query": query,
                "truth_status_before_completion": "no_claim",
                "does_not_create_memory_claim": True,
                "missing_fields": missing_fields,
                "missing_field_labels": [_payoff_field_label(field) for field in missing_fields],
                "payoff_score": payoff_score,
                "current_vector_status": current_status or "not_projected_without_draft",
                "after_completion_vector_status": "eligible_reviewed_record_after_adam_context_and_boundary",
                "unlocked_records": unlocked_records,
                "vector_text_template": vector_text_template,
                "placeholder_policy": "missing Adam context remains bracketed and is not generated by the system",
                "completion_signal": item.get("completion_signal"),
                "next_action": item.get("next_action"),
            }
        )
    items.sort(key=lambda item: (-int(item.get("payoff_score") or 0), str(item.get("source_photo_title") or "")))
    stable_payload = {
        "scope": scope,
        "user_id": user_id,
        "source_worklist_sha256": field_worklist.get("content_sha256"),
        "items": items,
    }
    content_sha256 = _stable_hash(stable_payload)
    preview: Dict[str, Any] = {
        "preview_type": "photo_context_retrieval_gap_payoff_preview",
        "scope": scope,
        "user_id": user_id,
        "review_policy": "read_only_payoff_preview_no_generated_memory_claims",
        "does_not_mutate_state": True,
        "does_not_create_memory_claim": True,
        "uses_placeholders_for_missing_adam_context": True,
        "requires_adam_context": True,
        "no_live_model_call": True,
        "no_live_embedding_call": True,
        "source_worklist_content_sha256": field_worklist.get("content_sha256"),
        "source_worklist_export_preview_sha256": field_worklist.get("export_preview_sha256"),
        "reported_item_count": len(items),
        "unlockable_vector_record_count": unlockable_vector_record_count,
        "current_submit_ready_count": current_submit_ready_count,
        "items": items,
        "content_sha256": content_sha256,
    }
    export_preview_yaml = _retrieval_gap_payoff_preview_yaml(preview)
    preview["export_preview_yaml"] = export_preview_yaml
    preview["export_preview_sha256"] = hashlib.sha256(export_preview_yaml.encode("utf-8")).hexdigest()
    return preview
