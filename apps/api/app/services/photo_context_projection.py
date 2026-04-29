from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, Optional

from sqlmodel import Session, select

from app.models import Asset, Boundary, EmbeddingRecord, Gallery, GalleryItem, Memory, MemorySource, MetadataProfile, Segment, Task
from app.services.embeddings import boundary_embedding_text, profile_embedding_text
from app.services.photo_memory import (
    _apply_photo_boundary,
    _asset_title,
    _existing_photo_profile,
    _find_photo_memory,
    _open_questions_from_context,
    _privacy_from_photo_context,
    _profile_retrieval_origin,
    _question_answer_context,
    _question_answer_rows,
    _retrieval_origin,
    _retrieval_origin_text,
    _string,
    _string_list,
    _truthy,
)


def _existing_memory_embedding(session: Session, memory: Optional[Memory]) -> Optional[EmbeddingRecord]:
    if memory is None:
        return None
    return session.exec(
        select(EmbeddingRecord)
        .where(EmbeddingRecord.target_type == "memory")
        .where(EmbeddingRecord.target_id == memory.id)
        .where(EmbeddingRecord.embedding_type == "memory_text")
        .where(EmbeddingRecord.modality == "text")
    ).first()


def _existing_profile_embedding(session: Session, profile: Optional[MetadataProfile]) -> Optional[EmbeddingRecord]:
    if profile is None:
        return None
    return session.exec(
        select(EmbeddingRecord)
        .where(EmbeddingRecord.target_type == "metadata_profile")
        .where(EmbeddingRecord.target_id == profile.id)
        .where(EmbeddingRecord.embedding_type == "retrieval_text")
        .where(EmbeddingRecord.modality == "text")
    ).first()


def _existing_ocr_segment(session: Session, asset_id: str, segment_type: str) -> Optional[Segment]:
    return session.exec(
        select(Segment).where(Segment.asset_id == asset_id).where(Segment.segment_type == segment_type)
    ).first()


def _existing_gallery_item(session: Session, asset_id: str) -> Optional[GalleryItem]:
    gallery = session.exec(select(Gallery).where(Gallery.human_id == "GALLERY_REVIEWED_PHOTOS")).first()
    if gallery is None:
        return None
    return session.exec(
        select(GalleryItem).where(GalleryItem.gallery_id == gallery.id).where(GalleryItem.asset_id == asset_id)
    ).first()


def _yaml_scalar(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    return json.dumps(str(value), ensure_ascii=False)


def _yaml_dump(value: Any, indent: int = 0) -> List[str]:
    prefix = " " * indent
    if isinstance(value, dict):
        rows: List[str] = []
        for key, item in value.items():
            if isinstance(item, str) and "\n" in item:
                rows.append(f"{prefix}{key}: |-")
                rows.extend(f"{prefix}  {line}" for line in item.splitlines())
            elif isinstance(item, (dict, list)):
                rows.append(f"{prefix}{key}:")
                rows.extend(_yaml_dump(item, indent + 2))
            else:
                rows.append(f"{prefix}{key}: {_yaml_scalar(item)}")
        return rows
    if isinstance(value, list):
        if not value:
            return [f"{prefix}[]"]
        rows = []
        for item in value:
            if isinstance(item, dict):
                rows.append(f"{prefix}-")
                rows.extend(_yaml_dump(item, indent + 2))
            else:
                rows.append(f"{prefix}- {_yaml_scalar(item)}")
        return rows
    return [f"{prefix}{_yaml_scalar(value)}"]


def _project_profile(task: Task, asset: Optional[Asset], decisions: Dict[str, Any]) -> MetadataProfile:
    asset_id = asset.id if asset else task.target_id
    visible_people = _string_list(decisions.get("visible_people"))
    absent_people = _string_list(decisions.get("absent_but_relevant_people"))
    place = _string(decisions.get("place"), "unknown")
    description = _string(decisions.get("visual_description_correction")) or _string(decisions.get("accepted_visual_description"))
    invisible_context = _string(decisions.get("invisible_context_note")) or _string(decisions.get("adam_context_note"))
    question_answer_rows = _question_answer_rows(task, decisions)
    question_answer_context = _question_answer_context(question_answer_rows)
    adam_context = "\n\n".join(part for part in [invisible_context, question_answer_context] if part)
    corrected_ocr = _string(decisions.get("corrected_ocr_text"))
    ocr_review_status = _string(decisions.get("ocr_review_status"), "not_present")
    ocr_context = (
        f"Photo OCR/handwriting ({ocr_review_status}):\n{corrected_ocr}"
        if corrected_ocr and ocr_review_status != "not_present"
        else ""
    )
    retrieval_origin = _retrieval_origin(task)
    retrieval_origin_context = _retrieval_origin_text(retrieval_origin)
    open_questions = _open_questions_from_context(
        task=task,
        decisions=decisions,
        answered_rows=question_answer_rows,
    )
    event = _string(decisions.get("event"), "unknown")
    return MetadataProfile(
        target_type="asset",
        target_id=asset_id,
        profile_type="photo_memory",
        profile_version="v1",
        metadata_status="adam_reviewed",
        title=_asset_title(asset, _string(task.input_payload.get("title"), "Photo")),
        summary=description,
        adam_context_note=adam_context,
        source_genre="photo",
        truth_status="adam_memory" if adam_context else "adam_inference",
        date_label=_string(decisions.get("date_or_range"), "unknown"),
        date_confidence=_string(decisions.get("date_confidence"), "unknown"),
        people=[*visible_people, *[person for person in absent_people if person not in visible_people]],
        places=[] if place == "unknown" else [place],
        themes=_string_list(decisions.get("themes")) or [value for value in [event] if value and value != "unknown"],
        concrete_objects=_string_list(decisions.get("concrete_objects")),
        open_questions=open_questions,
        retrieval_notes="\n\n".join(
            part for part in [adam_context, description, ocr_context, retrieval_origin_context] if part
        ),
        training_notes="Photo memory is retrieval/context material, not direct voice training text.",
        quality_signals={
            "memory_potential": decisions.get("memory_potential"),
            "privacy_sensitivity": decisions.get("privacy_sensitivity"),
            "gallery_eligibility": decisions.get("gallery_eligibility"),
            "ready_for_downstream": decisions.get("ready_for_downstream", "yes"),
            "answered_question_count": len(question_answer_rows),
            "open_question_count": len(open_questions),
            "retrieval_origin_query": retrieval_origin.get("query") if retrieval_origin else None,
        },
        embedding_hints={
            "recommended_embedding_targets": ["summary", "adam_context_note", "people", "places", "themes"],
            "modality": "photo",
            "use_before_review": False,
            "retrieval_origin_is_memory_claim": False if retrieval_origin else None,
        },
        raw_profile={
            **decisions,
            "retrieval_gap_origin": retrieval_origin,
            "answered_questions": question_answer_rows,
            "question_answer_context": question_answer_context,
            "unanswered_suggested_questions": open_questions,
            "ocr_review_status": ocr_review_status,
            "ocr_truth_status": _string(decisions.get("ocr_truth_status"), "system_inference"),
        },
        created_by="photo_memory_review",
        reviewed_by="adam",
    )


def _vector_status(
    *,
    boundary: Boundary,
    ready_for_downstream: bool,
    would_create_memory_embedding: bool,
) -> tuple[str, str]:
    if boundary.privacy_level in {"sealed", "private_sensitive"} or boundary.redaction_required:
        return "excluded_by_boundary", "Photo memory is not eligible for vector handoff under the reviewed boundary."
    if would_create_memory_embedding:
        return "eligible_reviewed_record", "Adam-reviewed photo memory is eligible for the default reviewed-only vector handoff."
    if not ready_for_downstream:
        return "held_pending_downstream_clearance", "Adam review would be recorded, but downstream readiness is not approved."
    return "held_missing_memory_context", "A reviewed vector handoff record requires Adam context or accepted visual description."


def _field_requirements(
    *,
    profile: MetadataProfile,
    decisions: Dict[str, Any],
    privacy_level: str,
) -> List[Dict[str, Any]]:
    ready_choice = _string(decisions.get("ready_for_downstream"))
    ocr_status = _string(decisions.get("ocr_review_status"), "not_present")
    requirements = [
        {
            "field_key": "visual_description_correction",
            "label": "Reviewed visual description",
            "status": "complete" if profile.summary else "missing",
            "required_for_submit": True,
            "reason": "Needed so retrieval and gallery surfaces describe visible pixels in Adam-reviewed language.",
        },
        {
            "field_key": "adam_context",
            "label": "Adam context or answers",
            "status": "complete" if profile.adam_context_note else "missing",
            "required_for_submit": False,
            "reason": "Needed for an adam_memory truth label; otherwise the photo remains Adam-reviewed inference.",
        },
        {
            "field_key": "privacy_level",
            "label": "Privacy level",
            "status": "complete" if privacy_level else "missing",
            "required_for_submit": True,
            "reason": "Every downstream photo record needs an explicit boundary before export or retrieval.",
        },
        {
            "field_key": "ready_for_downstream",
            "label": "Downstream choice",
            "status": "complete" if ready_choice in {"yes", "later", "no"} else "missing",
            "required_for_submit": True,
            "reason": "Submit should record whether this can move to retrieval, gallery, and embedding handoff now.",
        },
        {
            "field_key": "ocr_review_status",
            "label": "OCR or handwriting status",
            "status": "complete" if ocr_status else "missing",
            "required_for_submit": True,
            "reason": "The review should say whether visible text is absent, machine-drafted, accepted, or corrected.",
        },
    ]
    raw_profile = profile.raw_profile if isinstance(profile.raw_profile, dict) else {}
    retrieval_origin = raw_profile.get("retrieval_gap_origin") if isinstance(raw_profile.get("retrieval_gap_origin"), dict) else {}
    if retrieval_origin:
        question_answers = decisions.get("question_answers") if isinstance(decisions.get("question_answers"), dict) else {}
        query_answer = _string(question_answers.get("retrieval_query_relevance"))
        requirements.insert(
            1,
            {
                "field_key": "retrieval_query_relevance",
                "label": "Retrieval query relevance",
                "status": "complete" if query_answer else "missing",
                "required_for_submit": False,
                "reason": (
                    f"Query '{retrieval_origin.get('query')}' is workflow provenance only; Adam's answer is what can make it retrieval context."
                ),
            },
        )
    return requirements


def _submit_readiness(
    *,
    field_requirements: List[Dict[str, Any]],
    blocked_reasons: List[str],
) -> str:
    missing_required = [
        item["field_key"]
        for item in field_requirements
        if item.get("required_for_submit") is True and item.get("status") != "complete"
    ]
    if missing_required:
        return "needs_required_fields"
    if "not_ready_for_downstream" in blocked_reasons:
        return "ready_to_save_hold"
    if "excluded_by_boundary" in blocked_reasons or "boundary_redaction_required" in blocked_reasons:
        return "ready_to_submit_boundary_excluded"
    if "missing_reviewed_memory_text" in blocked_reasons:
        return "needs_reviewed_memory_text"
    return "ready_to_submit"


def _submit_preview_yaml(payload: Dict[str, Any]) -> str:
    text = "\n".join(_yaml_dump({"photo_context_submit_preview": payload})) + "\n"
    return text


def build_photo_context_submit_projection(
    *,
    session: Session,
    task: Task,
    decisions: Dict[str, Any],
) -> Dict[str, Any]:
    if task.task_type != "photo_context":
        return {
            "projection_type": "photo_context_submit_projection",
            "task_id": task.id,
            "supported": False,
            "blocked_reasons": ["projection_supported_for_photo_context_tasks_only"],
            "does_not_mutate_state": True,
            "no_live_embedding_call": True,
        }

    asset = session.get(Asset, task.target_id)
    asset_id = asset.id if asset else task.target_id
    existing_profile = _existing_photo_profile(session, asset_id, "photo_memory")
    existing_boundary = session.exec(
        select(Boundary).where(Boundary.target_type == "asset").where(Boundary.target_id == asset_id)
    ).first()
    existing_memory = _find_photo_memory(session, asset_id)
    existing_profile_embedding = _existing_profile_embedding(session, existing_profile)
    existing_memory_embedding = _existing_memory_embedding(session, existing_memory)
    existing_gallery_item = _existing_gallery_item(session, asset_id)

    profile = _project_profile(task, asset, decisions)
    ready_for_downstream = _truthy(decisions.get("ready_for_downstream", "yes"))
    privacy_level = _privacy_from_photo_context(decisions)
    privacy_notes = _string(decisions.get("privacy_notes")) or _string(decisions.get("invisible_context_note"))
    boundary = Boundary(target_type="asset", target_id=asset_id)
    _apply_photo_boundary(
        boundary,
        privacy_level=privacy_level,
        ready_for_downstream=ready_for_downstream,
        notes=privacy_notes,
    )
    boundary_snapshot = boundary.model_dump(mode="json")
    profile_text = "\n".join(part for part in [profile_embedding_text(profile), boundary_embedding_text(boundary_snapshot)] if part)
    memory_text_available = bool((profile.summary or "").strip() or (profile.adam_context_note or "").strip())
    would_create_memory = ready_for_downstream and memory_text_available
    vector_status, vector_reason = _vector_status(
        boundary=boundary,
        ready_for_downstream=ready_for_downstream,
        would_create_memory_embedding=would_create_memory,
    )
    corrected_ocr = _string(decisions.get("corrected_ocr_text"))
    ocr_review_status = _string(decisions.get("ocr_review_status"), "not_present")
    ocr_segment_type = "photo_context_ocr_text"
    existing_ocr_segment = _existing_ocr_segment(session, asset_id, ocr_segment_type)
    blocked_reasons = []
    if vector_status != "eligible_reviewed_record":
        blocked_reasons.append(vector_status)
    if not memory_text_available:
        blocked_reasons.append("missing_reviewed_memory_text")
    if boundary.redaction_required:
        blocked_reasons.append("boundary_redaction_required")
    if not ready_for_downstream:
        blocked_reasons.append("not_ready_for_downstream")
    field_requirements = _field_requirements(profile=profile, decisions=decisions, privacy_level=privacy_level)
    missing_required_fields = [
        item["field_key"]
        for item in field_requirements
        if item.get("required_for_submit") is True and item.get("status") != "complete"
    ]
    submit_readiness = _submit_readiness(field_requirements=field_requirements, blocked_reasons=blocked_reasons)
    preview_payload = {
        "task": {
            "id": task.id,
            "human_id": task.human_id,
            "type": task.task_type,
        },
        "source_photo": {
            "id": asset_id,
            "title": _asset_title(asset),
        },
        "metadata_profile": {
            "action": "update" if existing_profile else "create",
            "profile_type": "photo_memory",
            "metadata_status_after": "adam_reviewed",
            "truth_status_after": profile.truth_status,
            "summary": profile.summary,
            "adam_context_note": profile.adam_context_note,
            "people": profile.people,
            "places": profile.places,
            "themes": profile.themes,
            "open_questions": profile.open_questions,
        },
        "boundary": {
            "action": "update" if existing_boundary else "create",
            "privacy_level": boundary.privacy_level,
            "searchable": boundary.searchable,
            "retrievable_in_chat": boundary.retrievable_in_chat,
            "usable_for_voice_context": boundary.usable_for_voice_context,
            "usable_for_sft": False,
            "usable_for_dpo": False,
            "usable_for_gallery_family": boundary.usable_for_gallery_family,
            "usable_for_gallery_public": boundary.usable_for_gallery_public,
            "redaction_required": boundary.redaction_required,
        },
        "downstream": {
            "submit_readiness": submit_readiness,
            "profile_embedding_status": "ready_for_embedding" if profile_text.strip() else "held_empty_input",
            "memory_action": "update" if existing_memory and would_create_memory else "create" if would_create_memory else "not_created",
            "vector_handoff_status": vector_status,
            "gallery_scope_after": "public_candidate" if boundary.usable_for_gallery_public else "family_private"
            if boundary.usable_for_gallery_family
            else None,
            "ocr_segment_action": "update" if existing_ocr_segment and corrected_ocr and ocr_review_status != "not_present"
            else "create" if corrected_ocr and ocr_review_status != "not_present"
            else "not_created",
            "blocked_reasons": blocked_reasons,
        },
        "safety": {
            "does_not_mutate_state": True,
            "no_live_embedding_call": True,
            "ordinary_db_vector_storage": False,
        },
    }
    export_preview_yaml = _submit_preview_yaml(preview_payload)

    return {
        "projection_type": "photo_context_submit_projection",
        "review_policy": "preview_only_non_mutating",
        "task_id": task.id,
        "task_human_id": task.human_id,
        "source_photo_id": asset_id,
        "source_photo_title": _asset_title(asset),
        "supported": True,
        "does_not_mutate_state": True,
        "no_live_embedding_call": True,
        "ordinary_db_vector_storage": False,
        "metadata_profile": {
            "would_create": existing_profile is None,
            "would_update": existing_profile is not None,
            "existing_id": existing_profile.id if existing_profile else None,
            "profile_type": "photo_memory",
            "metadata_status_after": "adam_reviewed",
            "truth_status_after": profile.truth_status,
            "reviewed_by_after": "adam",
            "summary_preview": profile.summary,
            "adam_context_preview": profile.adam_context_note,
            "open_questions": profile.open_questions,
            "retrieval_origin": _profile_retrieval_origin(profile),
        },
        "boundary": {
            "would_create": existing_boundary is None,
            "would_update": existing_boundary is not None,
            "existing_id": existing_boundary.id if existing_boundary else None,
            "snapshot_after": boundary_snapshot,
            "usable_for_sft": False,
            "usable_for_dpo": False,
        },
        "profile_embedding": {
            "would_create": existing_profile_embedding is None,
            "would_update": existing_profile_embedding is not None,
            "existing_id": existing_profile_embedding.id if existing_profile_embedding else None,
            "status_after": "ready_for_embedding" if profile_text.strip() else "held_empty_input",
            "truth_status_after": profile.truth_status,
            "input_preview": " ".join(profile_text.split())[:400],
            "source": "photo_memory_review",
        },
        "memory": {
            "would_create": existing_memory is None and would_create_memory,
            "would_update": existing_memory is not None and would_create_memory,
            "existing_id": existing_memory.id if existing_memory else None,
            "truth_status_after": "adam_memory" if profile.adam_context_note else "interpretive_synthesis",
            "maturity_level_after": "L3_reviewed" if would_create_memory else "not_created",
            "would_link_asset": would_create_memory,
        },
        "memory_embedding_vector_handoff": {
            "would_create_embedding_record": existing_memory_embedding is None and would_create_memory,
            "would_update_embedding_record": existing_memory_embedding is not None and would_create_memory,
            "existing_embedding_record_id": existing_memory_embedding.id if existing_memory_embedding else None,
            "status": vector_status,
            "reason": vector_reason,
            "record_id_after_submit": existing_memory_embedding.id if vector_status == "eligible_reviewed_record" and existing_memory_embedding else None,
            "reviewed_only_by_default": True,
        },
        "gallery": {
            "would_create": existing_gallery_item is None
            and (boundary.usable_for_gallery_family or boundary.usable_for_gallery_public),
            "would_update": existing_gallery_item is not None
            and (boundary.usable_for_gallery_family or boundary.usable_for_gallery_public),
            "existing_id": existing_gallery_item.id if existing_gallery_item else None,
            "scope_after": "public_candidate" if boundary.usable_for_gallery_public else "family_private"
            if boundary.usable_for_gallery_family
            else None,
            "hidden_by_boundary": not (boundary.usable_for_gallery_family or boundary.usable_for_gallery_public),
        },
        "ocr_segment": {
            "would_create": existing_ocr_segment is None and bool(corrected_ocr and ocr_review_status != "not_present"),
            "would_update": existing_ocr_segment is not None and bool(corrected_ocr and ocr_review_status != "not_present"),
            "existing_id": existing_ocr_segment.id if existing_ocr_segment else None,
            "segment_type": ocr_segment_type,
            "truth_status_after": _string(decisions.get("ocr_truth_status"), "system_inference"),
            "status_after": ocr_review_status,
        },
        "field_requirements": field_requirements,
        "submit_readiness": submit_readiness,
        "missing_required_fields": missing_required_fields,
        "export_preview_yaml": export_preview_yaml,
        "content_sha256": hashlib.sha256(export_preview_yaml.encode("utf-8")).hexdigest(),
        "blocked_reasons": blocked_reasons,
    }
