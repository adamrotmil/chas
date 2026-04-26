from __future__ import annotations

from typing import Any, Dict, List, Optional

from sqlmodel import Session, select

from app.models import Boundary, Segment, Task, utcnow


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"yes", "true", "1", "high", "approved"}
    return False


def _string(value: Any, fallback: str = "") -> str:
    return value if isinstance(value, str) else fallback


def _string_list(value: Any) -> List[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item).strip()]


def _find_or_create_segment_boundary(session: Session, segment: Segment, decisions: Dict[str, Any]) -> Boundary:
    boundary = session.exec(
        select(Boundary).where(Boundary.target_type == "segment").where(Boundary.target_id == segment.id)
    ).first()
    if boundary is None:
        boundary = Boundary(target_type="segment", target_id=segment.id)

    boundary.privacy_level = _string(decisions.get("privacy_level"), "family_private")
    boundary.searchable = _truthy(decisions.get("segment_boundary_good"))
    boundary.retrievable_in_chat = _truthy(decisions.get("usable_for_voice_context")) or _truthy(
        decisions.get("usable_for_grounded_generation")
    )
    boundary.quotable = False
    boundary.summarizable = True
    boundary.usable_for_voice_context = _truthy(decisions.get("usable_for_voice_context"))
    boundary.usable_for_sft = _truthy(decisions.get("usable_for_sft"))
    boundary.usable_for_dpo = _truthy(decisions.get("usable_for_dpo"))
    boundary.usable_for_eval = _truthy(decisions.get("usable_for_grounded_generation"))
    boundary.redaction_required = _truthy(decisions.get("redaction_required"))
    boundary.notes = _string(decisions.get("boundary_notes"))
    boundary.reviewed_by = "adam"
    boundary.reviewed_at = utcnow()
    session.add(boundary)
    session.flush()
    return boundary


def _candidate_is_wanted(task: Task, decisions: Dict[str, Any]) -> bool:
    if task.task_type == "text_segment_review":
        return _string(decisions.get("prompt_pair_potential"), "none") in {"high", "medium"} and _truthy(
            decisions.get("usable_for_grounded_generation")
        )
    if task.task_type == "email_voice_sample":
        return _string(decisions.get("context_use")) in {"charles_voice_sample", "prompt_response_context"} and (
            _truthy(decisions.get("usable_for_voice_context")) or _truthy(decisions.get("usable_for_sft"))
        )
    return False


def _create_prompt_pair_candidate_task(
    session: Session,
    *,
    source_task: Task,
    segment: Segment,
    decisions: Dict[str, Any],
    annotation_id: str,
    selected_chunk_ids: List[str],
) -> Optional[Task]:
    if not _candidate_is_wanted(source_task, decisions):
        return None

    existing = session.exec(
        select(Task)
        .where(Task.task_type == "grounded_prompt_pair_candidate")
        .where(Task.target_type == "segment")
        .where(Task.target_id == segment.id)
        .where(Task.status == "ready")
    ).first()
    if existing:
        return existing

    task = Task(
        human_id=f"TASK_PROMPT_PAIR_{segment.human_id}_{source_task.id[:8]}",
        task_type="grounded_prompt_pair_candidate",
        target_type="segment",
        target_id=segment.id,
        priority=70 if _string(decisions.get("prompt_pair_potential")) == "high" else 55,
        queue="grounded_prompt_pairs_needing_drafts",
        reason_created="Reviewed source material was marked as useful for grounded prompt/response candidate creation.",
        input_payload={
            "source_review_annotation_id": annotation_id,
            "source_task_id": source_task.id,
            "asset_id": segment.asset_id,
            "segment_id": segment.id,
            "selected_chunk_ids": selected_chunk_ids,
            "source_genre": decisions.get("source_genre"),
            "authorship": decisions.get("authorship"),
            "voice_role": decisions.get("voice_role"),
            "context_use": decisions.get("context_use"),
            "themes": decisions.get("themes", []),
            "truth_status": decisions.get("truth_status", segment.source_truth_status),
        },
        required_decisions=[
            "prompt_intent",
            "source_chunks_to_use",
            "target_response_shape",
            "boundary_clearance_needed",
        ],
        created_by="source_review",
    )
    session.add(task)
    session.flush()
    return task


def upsert_source_review_artifacts(
    *,
    session: Session,
    task: Task,
    decisions: Dict[str, Any],
    annotation_id: str,
) -> Dict[str, Any]:
    if task.task_type not in {"text_segment_review", "email_voice_sample"}:
        return {}

    segment = session.get(Segment, task.target_id)
    if segment is None:
        return {}

    selected_chunk_ids = _string_list(decisions.get("selected_chunk_ids"))
    chunk_scope = _string(decisions.get("chunk_scope"), "preview_only")
    review_summary = {
        "source_review_annotation_id": annotation_id,
        "source_task_id": task.id,
        "reviewed_at": utcnow().isoformat(),
        "review_type": task.task_type,
        "source_genre": decisions.get("source_genre"),
        "authorship": decisions.get("authorship"),
        "voice_role": decisions.get("voice_role"),
        "charles_voice_presence": decisions.get("charles_voice_presence"),
        "context_use": decisions.get("context_use"),
        "prompt_pair_potential": decisions.get("prompt_pair_potential"),
        "selected_chunk_ids": selected_chunk_ids,
        "chunk_scope": chunk_scope,
    }

    segment.metadata_json = {
        **dict(segment.metadata_json),
        "latest_source_review": review_summary,
        "review_decisions": decisions,
    }
    segment.maturity_level = "L3_reviewed"
    if decisions.get("truth_status"):
        segment.source_truth_status = _string(decisions.get("truth_status"), segment.source_truth_status)
    session.add(segment)

    reviewed_chunk_ids: List[str] = []
    if selected_chunk_ids:
        chunks = session.exec(select(Segment).where(Segment.id.in_(selected_chunk_ids))).all()
        for chunk in chunks:
            chunk.metadata_json = {
                **dict(chunk.metadata_json),
                "selected_for_grounded_generation": True,
                "source_review_annotation_id": annotation_id,
                "selection_scope": chunk_scope,
            }
            chunk.maturity_level = "L3_reviewed"
            session.add(chunk)
            reviewed_chunk_ids.append(chunk.id)

    boundary = _find_or_create_segment_boundary(session, segment, decisions)
    candidate_task = _create_prompt_pair_candidate_task(
        session,
        source_task=task,
        segment=segment,
        decisions=decisions,
        annotation_id=annotation_id,
        selected_chunk_ids=selected_chunk_ids,
    )

    session.flush()
    return {
        "source_review": review_summary,
        "reviewed_segment_id": segment.id,
        "reviewed_chunk_ids": reviewed_chunk_ids,
        "boundary_id": boundary.id,
        "prompt_pair_candidate_task_id": candidate_task.id if candidate_task else None,
    }
