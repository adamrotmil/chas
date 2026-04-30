from __future__ import annotations

from typing import Any, Dict, List, Optional

from sqlmodel import Session, select

from app.models import Asset, Boundary, Gallery, GalleryItem, GraphEdge, Memory, MemorySource, MetadataProfile, Segment, Task, utcnow
from app.services.embeddings import boundary_embedding_text, upsert_embedding_record, upsert_profile_embedding
from app.services.photo_constants import (
    PHOTO_MEMORY_PROFILE_TYPE,
    PHOTO_SENSITIVE_PRIVACY_LEVELS,
    PHOTO_STATUS_ADAM_REVIEWED,
    PHOTO_TRUTH_ADAM_MEMORY,
)


def _count(session: Session, model: Any) -> int:
    return len(session.exec(select(model)).all()) + 1


def _human_id(prefix: str, count: int) -> str:
    return f"{prefix}_{count:06d}"


def _string(value: Any, fallback: str = "") -> str:
    return value if isinstance(value, str) and value.strip() else fallback


def _string_list(value: Any) -> List[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _suggested_questions(task: Task) -> List[Dict[str, Any]]:
    questions = task.input_payload.get("suggested_questions")
    if not isinstance(questions, list):
        return []
    return [question for question in questions if isinstance(question, dict)]


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


def _retrieval_origin_text(origin: Optional[Dict[str, Any]]) -> str:
    if not origin:
        return ""
    return "\n".join(
        [
            f"Retrieval origin query: {origin['query']}",
            f"Retrieval candidate quality: {origin['candidate_match_quality']}",
            f"Retrieval selection reason: {origin['selection_reason']}",
            "Retrieval origin truth status: no_claim",
            "Retrieval origin is not a memory claim.",
        ]
    )


def _profile_retrieval_origin(profile: MetadataProfile) -> Optional[Dict[str, Any]]:
    origin = (profile.raw_profile or {}).get("retrieval_gap_origin")
    return origin if isinstance(origin, dict) and origin.get("query") else None


def _question_answer_rows(task: Task, decisions: Dict[str, Any]) -> List[Dict[str, str]]:
    answers = decisions.get("question_answers")
    if not isinstance(answers, dict):
        return []
    question_by_id = {
        str(question.get("id") or f"question_{index + 1}"): str(question.get("question") or f"Question {index + 1}")
        for index, question in enumerate(_suggested_questions(task))
    }
    rows: List[Dict[str, str]] = []
    for key, value in answers.items():
        answer = str(value or "").strip()
        if not answer:
            continue
        question_id = str(key)
        rows.append(
            {
                "id": question_id,
                "question": question_by_id.get(question_id, question_id),
                "answer": answer,
            }
        )
    return rows


def _question_answer_context(rows: List[Dict[str, str]]) -> str:
    return "\n\n".join(
        f"Question: {row['question']}\nAnswer: {row['answer']}"
        for row in rows
        if row.get("question") and row.get("answer")
    )


def _open_questions_from_context(
    *,
    task: Task,
    decisions: Dict[str, Any],
    answered_rows: List[Dict[str, str]],
) -> List[str]:
    answered_ids = {row["id"] for row in answered_rows}
    open_questions = _string_list(decisions.get("open_questions"))
    for question in _suggested_questions(task):
        question_id = str(question.get("id") or "")
        question_text = str(question.get("question") or "").strip()
        if question_id and question_text and question_id not in answered_ids:
            open_questions.append(question_text)
    deduped: List[str] = []
    for question in open_questions:
        if question not in deduped:
            deduped.append(question)
    return deduped


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"yes", "true", "1", "ready", "approved", "public_candidate", "family_private"}
    if isinstance(value, (int, float)):
        return value > 0
    return False


def _asset_title(asset: Optional[Asset], fallback: str = "Photo") -> str:
    if asset is None:
        return fallback
    return asset.title or asset.original_filename or asset.human_id or fallback


def _privacy_from_photo_context(decisions: Dict[str, Any]) -> str:
    explicit = _string(decisions.get("privacy_level"))
    if explicit:
        return explicit
    gallery = _string(decisions.get("gallery_eligibility"), "family_private")
    sensitivity = decisions.get("privacy_sensitivity")
    if isinstance(sensitivity, (int, float)) and sensitivity >= 4:
        return "private_sensitive"
    if gallery == "public_candidate":
        return "public_candidate"
    if gallery == "none":
        return "family_private"
    return "family_private"


def _find_or_create_asset_boundary(session: Session, asset_id: str) -> Boundary:
    boundary = session.exec(
        select(Boundary).where(Boundary.target_type == "asset").where(Boundary.target_id == asset_id)
    ).first()
    if boundary is None:
        boundary = Boundary(target_type="asset", target_id=asset_id)
    return boundary


def _apply_photo_boundary(boundary: Boundary, *, privacy_level: str, ready_for_downstream: bool, notes: str) -> Boundary:
    redaction_required = privacy_level in PHOTO_SENSITIVE_PRIVACY_LEVELS or "redact" in notes.lower()
    boundary.privacy_level = privacy_level
    boundary.searchable = ready_for_downstream and privacy_level != "sealed"
    boundary.retrievable_in_chat = ready_for_downstream and privacy_level not in PHOTO_SENSITIVE_PRIVACY_LEVELS
    boundary.quotable = False
    boundary.summarizable = ready_for_downstream
    boundary.usable_for_voice_context = ready_for_downstream and privacy_level not in PHOTO_SENSITIVE_PRIVACY_LEVELS
    boundary.usable_for_sft = False
    boundary.usable_for_dpo = False
    boundary.usable_for_eval = ready_for_downstream and privacy_level != "sealed"
    boundary.usable_for_gallery_public = ready_for_downstream and privacy_level == "public_candidate" and not redaction_required
    boundary.usable_for_gallery_family = ready_for_downstream and privacy_level in {"family_private", "public_candidate"}
    boundary.usable_for_simulation = ready_for_downstream and privacy_level not in PHOTO_SENSITIVE_PRIVACY_LEVELS
    boundary.contains_living_person_sensitive_material = privacy_level in {"sensitive_living_people", "private_sensitive"}
    boundary.redaction_required = redaction_required
    boundary.notes = notes or "Photo memory boundary generated from Adam review."
    boundary.reviewed_by = "adam"
    boundary.reviewed_at = utcnow()
    return boundary


def _existing_photo_profile(session: Session, asset_id: str, profile_type: str) -> Optional[MetadataProfile]:
    return session.exec(
        select(MetadataProfile)
        .where(MetadataProfile.target_type == "asset")
        .where(MetadataProfile.target_id == asset_id)
        .where(MetadataProfile.profile_type == profile_type)
    ).first()


def _upsert_photo_profile_from_context(
    *,
    session: Session,
    task: Task,
    asset: Optional[Asset],
    decisions: Dict[str, Any],
    annotation_id: str,
) -> MetadataProfile:
    asset_id = asset.id if asset else task.target_id
    profile = _existing_photo_profile(session, asset_id, PHOTO_MEMORY_PROFILE_TYPE)
    if profile is None:
        profile = MetadataProfile(target_type="asset", target_id=asset_id, profile_type=PHOTO_MEMORY_PROFILE_TYPE)
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
    profile.profile_version = "v1"
    profile.metadata_status = PHOTO_STATUS_ADAM_REVIEWED
    profile.title = _asset_title(asset, _string(task.input_payload.get("title"), "Photo"))
    profile.summary = description
    profile.adam_context_note = adam_context
    profile.source_genre = "photo"
    profile.truth_status = PHOTO_TRUTH_ADAM_MEMORY if adam_context else "adam_inference"
    profile.date_label = _string(decisions.get("date_or_range"), "unknown")
    profile.date_confidence = _string(decisions.get("date_confidence"), "unknown")
    profile.people = [*visible_people, *[person for person in absent_people if person not in visible_people]]
    profile.places = [] if place == "unknown" else [place]
    profile.themes = _string_list(decisions.get("themes")) or [value for value in [event] if value and value != "unknown"]
    profile.concrete_objects = _string_list(decisions.get("concrete_objects"))
    profile.open_questions = open_questions
    profile.retrieval_notes = "\n\n".join(
        part for part in [adam_context, description, ocr_context, retrieval_origin_context] if part
    )
    profile.training_notes = "Photo memory is retrieval/context material, not direct voice training text."
    profile.quality_signals = {
        "memory_potential": decisions.get("memory_potential"),
        "privacy_sensitivity": decisions.get("privacy_sensitivity"),
        "gallery_eligibility": decisions.get("gallery_eligibility"),
        "ready_for_downstream": decisions.get("ready_for_downstream", "yes"),
        "answered_question_count": len(question_answer_rows),
        "open_question_count": len(open_questions),
        "retrieval_origin_query": retrieval_origin.get("query") if retrieval_origin else None,
    }
    profile.embedding_hints = {
        "recommended_embedding_targets": ["summary", "adam_context_note", "people", "places", "themes"],
        "modality": "photo",
        "use_before_review": False,
        "retrieval_origin_is_memory_claim": False if retrieval_origin else None,
    }
    profile.raw_profile = {
        **decisions,
        "source_annotation_id": annotation_id,
        "retrieval_gap_origin": retrieval_origin,
        "answered_questions": question_answer_rows,
        "question_answer_context": question_answer_context,
        "unanswered_suggested_questions": open_questions,
        "ocr_review_status": ocr_review_status,
        "ocr_truth_status": _string(decisions.get("ocr_truth_status"), "system_inference"),
    }
    profile.source_annotation_id = annotation_id
    profile.created_by = "photo_memory_review"
    profile.reviewed_by = "adam"
    profile.reviewed_at = utcnow()
    profile.updated_at = utcnow()
    session.add(profile)
    session.flush()
    return profile


def _memory_summary(profile: MetadataProfile) -> str:
    parts = [
        profile.summary or "",
        profile.adam_context_note or "",
        f"People: {', '.join(profile.people)}" if profile.people else "",
        f"Place: {', '.join(profile.places)}" if profile.places else "",
        f"Date: {profile.date_label}" if profile.date_label else "",
    ]
    return "\n\n".join(part for part in parts if part.strip()) or profile.title or "Photo memory"


def _find_photo_memory(session: Session, asset_id: str) -> Optional[Memory]:
    link = session.exec(
        select(MemorySource)
        .where(MemorySource.source_type == "asset")
        .where(MemorySource.source_id == asset_id)
        .where(MemorySource.role == "photo_memory_anchor")
    ).first()
    return session.get(Memory, link.memory_id) if link else None


def _upsert_photo_memory(
    *,
    session: Session,
    asset: Optional[Asset],
    profile: MetadataProfile,
    boundary: Boundary,
    annotation_id: str,
    ready_for_downstream: bool,
) -> tuple[Optional[Memory], Optional[MemorySource], Optional[GraphEdge], Optional[Any]]:
    asset_id = profile.target_id
    if not ready_for_downstream or not (profile.summary or profile.adam_context_note):
        return None, None, None, None
    memory = _find_photo_memory(session, asset_id)
    if memory is None:
        memory = Memory(
            human_id=f"MEM_PHOTO_{_count(session, Memory):06d}",
            title=profile.title or _asset_title(asset),
            summary=_memory_summary(profile),
            truth_status=PHOTO_TRUTH_ADAM_MEMORY if profile.adam_context_note else "interpretive_synthesis",
            reliability="medium",
            maturity_level="L3_reviewed",
        )
    memory.title = profile.title or memory.title
    memory.summary = _memory_summary(profile)
    memory.truth_status = PHOTO_TRUTH_ADAM_MEMORY if profile.adam_context_note else "interpretive_synthesis"
    memory.reliability = "medium"
    memory.maturity_level = "L3_reviewed"
    memory.themes = profile.themes
    memory.open_questions = profile.open_questions
    memory.updated_at = utcnow()
    session.add(memory)
    session.flush()

    source = session.exec(
        select(MemorySource)
        .where(MemorySource.memory_id == memory.id)
        .where(MemorySource.source_type == "asset")
        .where(MemorySource.source_id == asset_id)
    ).first()
    if source is None:
        source = MemorySource(
            memory_id=memory.id,
            source_type="asset",
            source_id=asset_id,
            role="photo_memory_anchor",
            confidence="medium",
        )
    source.confidence = "medium"
    retrieval_origin = _profile_retrieval_origin(profile)
    source.notes = "\n".join(
        part
        for part in [
            f"Created from photo review annotation {annotation_id}.",
            _retrieval_origin_text(retrieval_origin),
        ]
        if part
    )
    session.add(source)
    session.flush()

    edge = session.exec(
        select(GraphEdge)
        .where(GraphEdge.from_type == "asset")
        .where(GraphEdge.from_id == asset_id)
        .where(GraphEdge.relation == "evokes_memory")
        .where(GraphEdge.to_type == "memory")
        .where(GraphEdge.to_id == memory.id)
    ).first()
    if edge is None:
        edge = GraphEdge(
            from_type="asset",
            from_id=asset_id,
            relation="evokes_memory",
            to_type="memory",
            to_id=memory.id,
            confidence="medium",
            created_by="photo_memory_review",
        )
    edge.evidence = {"metadata_profile_id": profile.id, "source_annotation_id": annotation_id}
    session.add(edge)
    session.flush()

    embedding = upsert_embedding_record(
        session=session,
        target_type="memory",
        target_id=memory.id,
        input_text="\n\n".join(
            part
            for part in [
                memory.title,
                memory.summary,
                profile.retrieval_notes,
                boundary_embedding_text(boundary.model_dump(mode="json")),
            ]
            if part
        ),
        modality="text",
        embedding_type="memory_text",
        truth_status=memory.truth_status,
        boundary_snapshot=boundary.model_dump(mode="json"),
        metadata={
            "source": "photo_memory_review",
            "metadata_profile_id": profile.id,
            "asset_id": asset_id,
            "retrieval_gap_origin": retrieval_origin,
        },
        created_by="photo_memory_review",
    )
    return memory, source, edge, embedding


def _upsert_gallery_item(
    *,
    session: Session,
    asset: Optional[Asset],
    boundary: Boundary,
    profile: MetadataProfile,
) -> Optional[GalleryItem]:
    if not boundary.usable_for_gallery_family and not boundary.usable_for_gallery_public:
        return None
    gallery = session.exec(select(Gallery).where(Gallery.human_id == "GALLERY_REVIEWED_PHOTOS")).first()
    if gallery is None:
        gallery = Gallery(
            human_id="GALLERY_REVIEWED_PHOTOS",
            title="Reviewed Photo Candidates",
            description="Photos Adam has reviewed for future gallery or memory use.",
            scope="family_private",
        )
        session.add(gallery)
        session.flush()
    item = session.exec(
        select(GalleryItem).where(GalleryItem.gallery_id == gallery.id).where(GalleryItem.asset_id == profile.target_id)
    ).first()
    if item is None:
        item = GalleryItem(gallery_id=gallery.id, asset_id=profile.target_id)
    item.gallery_scope = "public_candidate" if boundary.usable_for_gallery_public else "family_private"
    item.title = profile.title or _asset_title(asset)
    item.display_caption = profile.summary
    item.memory_caption = profile.adam_context_note
    item.boundary_snapshot = boundary.model_dump(mode="json")
    session.add(item)
    session.flush()
    return item


def _remove_machine_draft_gallery_item(session: Session, asset_id: str) -> Optional[str]:
    draft_gallery = session.exec(select(Gallery).where(Gallery.human_id == "GALLERY_MACHINE_DRAFT_PHOTOS")).first()
    if draft_gallery is None:
        return None
    draft_item = session.exec(
        select(GalleryItem).where(GalleryItem.gallery_id == draft_gallery.id).where(GalleryItem.asset_id == asset_id)
    ).first()
    if draft_item is None:
        return None
    removed_id = draft_item.id
    session.delete(draft_item)
    session.flush()
    return removed_id


def promote_photo_profile_downstream(
    *,
    session: Session,
    profile: MetadataProfile,
    asset: Optional[Asset],
    boundary: Boundary,
    annotation_id: str,
    ready_for_downstream: bool,
) -> Dict[str, Any]:
    retrieval_origin = _profile_retrieval_origin(profile)
    profile_embedding = upsert_profile_embedding(
        session=session,
        profile=profile,
        target_boundary_type="asset",
        target_boundary_id=profile.target_id,
        metadata={"source": "photo_memory_review", "retrieval_gap_origin": retrieval_origin},
    )
    memory, source, edge, memory_embedding = _upsert_photo_memory(
        session=session,
        asset=asset,
        profile=profile,
        boundary=boundary,
        annotation_id=annotation_id,
        ready_for_downstream=ready_for_downstream,
    )
    gallery_item = _upsert_gallery_item(session=session, asset=asset, boundary=boundary, profile=profile)
    removed_draft_gallery_item_id = _remove_machine_draft_gallery_item(session, profile.target_id)
    if boundary.privacy_level in PHOTO_SENSITIVE_PRIVACY_LEVELS or boundary.redaction_required:
        vector_handoff_status = "excluded_by_boundary"
        vector_handoff_reason = "Photo memory is not eligible for vector handoff under the reviewed boundary."
    elif memory_embedding:
        vector_handoff_status = "eligible_reviewed_record"
        vector_handoff_reason = "Adam-reviewed photo memory is eligible for the default reviewed-only vector handoff."
    elif not ready_for_downstream:
        vector_handoff_status = "held_pending_downstream_clearance"
        vector_handoff_reason = "Adam review was recorded, but downstream readiness was not approved."
    else:
        vector_handoff_status = "held_missing_memory_context"
        vector_handoff_reason = "A reviewed vector handoff record requires Adam context or accepted visual description."
    return {
        "embedding_record_id": profile_embedding.id if profile_embedding else None,
        "memory_id": memory.id if memory else None,
        "memory_source_id": source.id if source else None,
        "graph_edge_id": edge.id if edge else None,
        "memory_embedding_record_id": memory_embedding.id if memory_embedding else None,
        "gallery_item_id": gallery_item.id if gallery_item else None,
        "removed_machine_draft_gallery_item_id": removed_draft_gallery_item_id,
        "vector_handoff_status": vector_handoff_status,
        "vector_handoff_reason": vector_handoff_reason,
        "vector_handoff_record_id": memory_embedding.id if vector_handoff_status == "eligible_reviewed_record" else None,
    }


def _upsert_photo_ocr_segment(
    *,
    session: Session,
    task: Task,
    asset_id: str,
    profile: MetadataProfile,
    decisions: Dict[str, Any],
    annotation_id: str,
) -> Optional[Segment]:
    corrected_ocr = _string(decisions.get("corrected_ocr_text"))
    ocr_review_status = _string(decisions.get("ocr_review_status"), "not_present")
    if not corrected_ocr or ocr_review_status == "not_present":
        return None
    ocr_truth_status = _string(decisions.get("ocr_truth_status"), "system_inference")
    candidate_segments = session.exec(
        select(Segment)
        .where(Segment.asset_id == asset_id)
        .where(Segment.segment_type == "photo_context_ocr_text")
    ).all()
    existing = next(
        (segment for segment in candidate_segments if segment.locator.get("metadata_profile_id") == profile.id),
        None,
    )
    segment = existing or Segment(
        human_id=_human_id("SEG_PHOTO_OCR", _count(session, Segment)),
        asset_id=asset_id,
        segment_type="photo_context_ocr_text",
        title=f"OCR from {_string(task.input_payload.get('asset_title'), profile.title or 'photo source')}",
        locator={"metadata_profile_id": profile.id, "source_annotation_id": annotation_id},
    )
    segment.text_content = corrected_ocr
    segment.source_truth_status = ocr_truth_status
    segment.maturity_level = "L2_extracted" if ocr_truth_status == "system_inference" else "L3_reviewed"
    segment.metadata_json = {
        **(segment.metadata_json or {}),
        "ocr_review_status": ocr_review_status,
        "source": "photo_context_review",
        "requires_quote_check": ocr_truth_status != "archival_source",
    }
    segment.updated_at = utcnow()
    session.add(segment)
    session.flush()
    return segment


def upsert_photo_context_artifacts(
    *,
    session: Session,
    task: Task,
    decisions: Dict[str, Any],
    annotation_id: str,
) -> Dict[str, Any]:
    if task.task_type != "photo_context":
        return {}
    asset = session.get(Asset, task.target_id)
    asset_id = asset.id if asset else task.target_id
    profile = _upsert_photo_profile_from_context(
        session=session,
        task=task,
        asset=asset,
        decisions=decisions,
        annotation_id=annotation_id,
    )
    ready_for_downstream = _truthy(decisions.get("ready_for_downstream", "yes"))
    privacy_level = _privacy_from_photo_context(decisions)
    privacy_notes = _string(decisions.get("privacy_notes")) or _string(decisions.get("invisible_context_note"))
    boundary = _find_or_create_asset_boundary(session, asset_id)
    _apply_photo_boundary(
        boundary,
        privacy_level=privacy_level,
        ready_for_downstream=ready_for_downstream,
        notes=privacy_notes,
    )
    session.add(boundary)
    session.flush()
    if asset:
        asset.processing_status = "photo_memory_reviewed"
        asset.maturity_level = "L3_reviewed" if ready_for_downstream and not boundary.redaction_required else "L2_needs_review"
        asset.updated_at = utcnow()
        session.add(asset)
    downstream = promote_photo_profile_downstream(
        session=session,
        profile=profile,
        asset=asset,
        boundary=boundary,
        annotation_id=annotation_id,
        ready_for_downstream=ready_for_downstream,
    )
    ocr_segment = _upsert_photo_ocr_segment(
        session=session,
        task=task,
        asset_id=asset_id,
        profile=profile,
        decisions=decisions,
        annotation_id=annotation_id,
    )
    return {
        "metadata_profile_id": profile.id,
        "boundary_id": boundary.id,
        "ocr_segment_id": ocr_segment.id if ocr_segment else None,
        **downstream,
    }
