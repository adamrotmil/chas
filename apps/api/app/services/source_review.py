from __future__ import annotations

from typing import Any, Dict, List, Optional

from sqlmodel import Session, select

from app.models import Boundary, MetadataProfile, Segment, Task, utcnow


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


def _meaningful(value: Any) -> bool:
    return value is not None and value != "" and value != []


def _clean_dict(value: Dict[str, Any]) -> Dict[str, Any]:
    return {key: item for key, item in value.items() if _meaningful(item)}


def _safe_decision_profile(decisions: Dict[str, Any]) -> Dict[str, Any]:
    profile = dict(decisions)
    if "cleaned_text" in profile:
        profile["cleaned_text"] = "[stored on annotation only]"
    return profile


def _profile_type(task: Task, decisions: Dict[str, Any]) -> str:
    if task.task_type == "email_voice_sample":
        return "email"
    source_genre = _string(decisions.get("source_genre"), "document")
    if source_genre in {"novel_draft", "memoir_fragment", "letter", "essay", "notes"}:
        return source_genre
    return "document_text"


def _upsert_metadata_profile(
    session: Session,
    *,
    task: Task,
    segment: Segment,
    decisions: Dict[str, Any],
    annotation_id: str,
    selected_chunk_ids: List[str],
    chunk_scope: str,
) -> MetadataProfile:
    profile_type = _profile_type(task, decisions)
    profile = session.exec(
        select(MetadataProfile)
        .where(MetadataProfile.target_type == "segment")
        .where(MetadataProfile.target_id == segment.id)
        .where(MetadataProfile.profile_type == profile_type)
    ).first()
    if profile is None:
        profile = MetadataProfile(target_type="segment", target_id=segment.id, profile_type=profile_type)

    profile.profile_version = "v1"
    profile.metadata_status = "adam_reviewed"
    profile.title = _string(decisions.get("segment_title"), segment.title or task.human_id)
    profile.summary = _string(decisions.get("summary"))
    profile.adam_context_note = _string(decisions.get("adam_context_note")) or _string(decisions.get("why_it_matters"))
    profile.source_genre = _string(decisions.get("source_genre"), profile_type)
    profile.authorship = _string(decisions.get("authorship"), "unknown")
    profile.authorship_note = _string(decisions.get("authorship_note"))
    profile.creator_entity_ids = _string_list(decisions.get("creator_entity_ids"))
    profile.fictionality_status = _string(decisions.get("fictionality_status"), "unknown")
    profile.voice_presence = _string(decisions.get("charles_voice_presence")) or _string(decisions.get("voice_presence"))
    profile.voice_role = _string(decisions.get("voice_training_role")) or _string(decisions.get("voice_role")) or _string(
        decisions.get("context_use")
    )
    profile.truth_status = _string(decisions.get("truth_status"), segment.source_truth_status)
    profile.date_label = _string(decisions.get("date_or_range"), "unknown")
    profile.date_confidence = _string(decisions.get("date_confidence"), "unknown")
    profile.people = _string_list(decisions.get("people"))
    profile.mentioned_entity_ids = _string_list(decisions.get("mentioned_entity_ids"))
    profile.places = _string_list(decisions.get("places"))
    profile.themes = _string_list(decisions.get("themes"))
    profile.motifs = _string_list(decisions.get("motifs"))
    profile.emotional_tone = _string_list(decisions.get("emotional_tone"))
    profile.concrete_objects = _string_list(decisions.get("concrete_objects"))
    profile.open_questions = _string_list(decisions.get("open_questions"))
    profile.retrieval_notes = _string(decisions.get("retrieval_notes")) or _string(decisions.get("why_it_matters"))
    profile.training_notes = _string(decisions.get("training_notes"))
    profile.quality_signals = _clean_dict(
        {
            "factual_reliability": decisions.get("factual_reliability") or decisions.get("source_reliability"),
            "segment_boundary_good": decisions.get("segment_boundary_good"),
            "prompt_pair_potential": decisions.get("prompt_pair_potential"),
            "context_use": decisions.get("context_use"),
            "authenticity_value": decisions.get("authenticity_value"),
            "voice_density": decisions.get("voice_density"),
            "usable_for_voice_context": decisions.get("usable_for_voice_context"),
            "usable_for_grounded_generation": decisions.get("usable_for_grounded_generation"),
            "usable_for_sft": decisions.get("usable_for_sft"),
            "usable_for_dpo": decisions.get("usable_for_dpo"),
            "extraction_edit_notes": decisions.get("extraction_edit_notes"),
        }
    )
    profile.embedding_hints = _clean_dict(
        {
            "recommended_embedding_targets": ["source_text", "profile_summary", "adam_context_note"],
            "selected_chunk_ids": selected_chunk_ids,
            "chunk_scope": chunk_scope,
            "cleaned_text_scope": decisions.get("cleaned_text_scope"),
            "cleaned_text_chunk_id": decisions.get("cleaned_text_chunk_id"),
            "profile_use": ["retrieval", "rag_context", "source_prioritization"],
        }
    )
    profile.raw_profile = _safe_decision_profile(decisions)
    profile.source_annotation_id = annotation_id
    profile.created_by = "source_review"
    profile.reviewed_by = "adam"
    profile.reviewed_at = utcnow()
    profile.updated_at = utcnow()
    session.add(profile)
    session.flush()
    return profile


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
    boundary.notes = _string(decisions.get("boundary_rationale")) or _string(decisions.get("boundary_notes"))
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
            "creator_entity_ids": decisions.get("creator_entity_ids", []),
            "creator_name": decisions.get("creator_name"),
            "authorship_note": decisions.get("authorship_note"),
            "fictionality_status": decisions.get("fictionality_status"),
            "voice_presence": decisions.get("voice_presence") or decisions.get("charles_voice_presence"),
            "voice_training_role": decisions.get("voice_training_role") or decisions.get("voice_role"),
            "context_use": decisions.get("context_use"),
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
        "creator_entity_ids": decisions.get("creator_entity_ids", []),
        "creator_name": decisions.get("creator_name"),
        "authorship_note": decisions.get("authorship_note"),
        "fictionality_status": decisions.get("fictionality_status"),
        "voice_presence": decisions.get("voice_presence") or decisions.get("charles_voice_presence"),
        "voice_training_role": decisions.get("voice_training_role") or decisions.get("voice_role"),
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
    metadata_profile = _upsert_metadata_profile(
        session,
        task=task,
        segment=segment,
        decisions=decisions,
        annotation_id=annotation_id,
        selected_chunk_ids=selected_chunk_ids,
        chunk_scope=chunk_scope,
    )
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
        "metadata_profile_id": metadata_profile.id,
        "prompt_pair_candidate_task_id": candidate_task.id if candidate_task else None,
    }
