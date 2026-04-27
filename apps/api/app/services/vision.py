from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import HTTPException
from sqlmodel import Session, select

from app.models import Asset, Boundary, MetadataProfile, Segment, Task, utcnow


VISION_DRAFT_SCHEMA: Dict[str, Any] = {
    "name": "charlesops_vision_draft_v1",
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "visual_summary": {"type": "string"},
            "visible_people": {"type": "array", "items": {"type": "string"}},
            "places": {"type": "array", "items": {"type": "string"}},
            "time_period_guess": {"type": "string"},
            "objects": {"type": "array", "items": {"type": "string"}},
            "themes": {"type": "array", "items": {"type": "string"}},
            "ocr_text": {"type": "string"},
            "handwriting_text": {"type": "string"},
            "uncertainties": {"type": "array", "items": {"type": "string"}},
            "suggested_questions": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "id": {"type": "string"},
                        "question": {"type": "string"},
                        "reason": {"type": "string"},
                        "answer_type": {"type": "string"},
                    },
                    "required": ["id", "question", "reason", "answer_type"],
                },
            },
            "privacy_flags": {"type": "array", "items": {"type": "string"}},
            "confidence": {"type": "string"},
        },
        "required": [
            "visual_summary",
            "visible_people",
            "places",
            "time_period_guess",
            "objects",
            "themes",
            "ocr_text",
            "handwriting_text",
            "uncertainties",
            "suggested_questions",
            "privacy_flags",
            "confidence",
        ],
    },
}

VISION_SYSTEM_PROMPT = (
    "You are drafting metadata for CharlesOps. Describe only what is visible or legibly written. "
    "Do not identify private people unless the source context explicitly names them. "
    "Mark uncertain observations as uncertainties. Output structured JSON only. "
    "Every observation is system_inference until Adam reviews it."
)

BASE_REVIEW_QUESTIONS: List[Dict[str, str]] = [
    {
        "id": "who_is_visible",
        "question": "Who is visible or directly represented here?",
        "reason": "Names and relationships usually need Adam's memory, not model guessing.",
        "answer_type": "people",
    },
    {
        "id": "where_is_this",
        "question": "Where is this, if you know?",
        "reason": "Place labels are high-value retrieval and gallery metadata.",
        "answer_type": "place",
    },
    {
        "id": "when_is_this",
        "question": "When is this from or about?",
        "reason": "Dates anchor memories, timelines, galleries, and retrieval.",
        "answer_type": "date_or_range",
    },
    {
        "id": "why_it_matters",
        "question": "Why does Adam think this source matters?",
        "reason": "This is Adam context, separate from model inference.",
        "answer_type": "long_text",
    },
    {
        "id": "privacy",
        "question": "Is anything private, sensitive, or not safe for downstream use?",
        "reason": "Boundaries must be set before retrieval, gallery, or training use.",
        "answer_type": "privacy_note",
    },
]


def _human_id(prefix: str, count: int) -> str:
    return f"{prefix}_{count:06d}"


def _count(session: Session, model: Any) -> int:
    return len(session.exec(select(model)).all()) + 1


def _string(value: Any, fallback: str = "") -> str:
    return value if isinstance(value, str) and value.strip() else fallback


def _string_list(value: Any) -> List[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item).strip()]


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"yes", "true", "1", "approved", "accepted", "ready"}
    return False


def _asset_title(asset: Asset) -> str:
    return asset.title or asset.original_filename or asset.human_id


def _vision_candidate_statement(asset_ids: List[str]):
    statement = (
        select(Asset)
        .where(Asset.asset_type.in_(["photo", "scan"]))
        .order_by(Asset.created_at.asc())
    )
    if asset_ids:
        statement = statement.where(Asset.id.in_(asset_ids))
    return statement


def _existing_profile(session: Session, asset: Asset, draft_type: str) -> Optional[MetadataProfile]:
    return session.exec(
        select(MetadataProfile)
        .where(MetadataProfile.target_type == "asset")
        .where(MetadataProfile.target_id == asset.id)
        .where(MetadataProfile.profile_type == draft_type)
    ).first()


def _existing_review_task(session: Session, profile: MetadataProfile) -> Optional[Task]:
    return session.exec(
        select(Task)
        .where(Task.task_type == "vision_draft_review")
        .where(Task.target_type == "metadata_profile")
        .where(Task.target_id == profile.id)
        .where(Task.status == "ready")
    ).first()


def build_vision_request_plan(asset: Asset, *, model_name: str, input_detail: str, draft_type: str) -> Dict[str, Any]:
    return {
        "api": "responses",
        "model": model_name,
        "input_detail": input_detail,
        "draft_type": draft_type,
        "system_prompt": VISION_SYSTEM_PROMPT,
        "text_format": VISION_DRAFT_SCHEMA,
        "input_strategy": "use mirrored object if available; otherwise use signed cloud/object URL",
        "provenance_rule": "store all model observations as system_inference until Adam reviews them",
    }


def create_vision_draft_for_asset(
    *,
    session: Session,
    asset: Asset,
    queue: str,
    draft_type: str,
    model_name: str,
    input_detail: str,
) -> Dict[str, str]:
    profile = _existing_profile(session, asset, draft_type)
    created_profile = False
    if profile is None:
        profile = MetadataProfile(
            target_type="asset",
            target_id=asset.id,
            profile_type=draft_type,
            profile_version="v1",
        )
        created_profile = True

    request_plan = build_vision_request_plan(
        asset,
        model_name=model_name,
        input_detail=input_detail,
        draft_type=draft_type,
    )
    profile.metadata_status = "machine_draft"
    profile.title = _asset_title(asset)
    profile.summary = ""
    profile.truth_status = "system_inference"
    profile.source_genre = "photo" if asset.asset_type == "photo" else "scan"
    profile.voice_presence = "absent"
    profile.open_questions = [question["question"] for question in BASE_REVIEW_QUESTIONS]
    profile.quality_signals = {
        "vision_draft_status": "not_run",
        "model_name": model_name,
        "input_detail": input_detail,
        "requires_adam_review": True,
        "no_live_model_call": True,
    }
    profile.embedding_hints = {
        "recommended_embedding_targets": ["visual_summary", "adam_context_note", "accepted_tags", "ocr_text"],
        "modality": asset.asset_type,
        "use_before_review": False,
    }
    profile.raw_profile = {
        "vision_request_plan": request_plan,
        "system_inference_draft": {
            "visual_summary": "",
            "visible_people": [],
            "places": [],
            "time_period_guess": "",
            "objects": [],
            "themes": [],
            "ocr_text": "",
            "handwriting_text": "",
            "uncertainties": ["No live model call has been made yet."],
            "suggested_questions": BASE_REVIEW_QUESTIONS,
            "privacy_flags": [],
            "confidence": "not_run",
        },
        "no_live_model_call": True,
    }
    profile.created_by = "vision_pipeline"
    profile.updated_at = utcnow()
    session.add(profile)
    session.flush()

    review_task = _existing_review_task(session, profile)
    if review_task is None:
        review_task = Task(
            human_id=_human_id("TASK_VISION_REVIEW", _count(session, Task)),
            task_type="vision_draft_review",
            target_type="metadata_profile",
            target_id=profile.id,
            priority=72,
            queue=queue,
            reason_created="Vision pipeline prepared draft metadata/questions for Adam review. No live model call was made.",
            input_payload={
                "asset_id": asset.id,
                "asset_type": asset.asset_type,
                "asset_title": _asset_title(asset),
                "source_filename": asset.original_filename,
                "source_type": asset.asset_type,
                "metadata_profile_id": profile.id,
                "draft_type": draft_type,
                "truth_status": "system_inference",
                "vision_request_plan": request_plan,
                "vision_draft": profile.raw_profile["system_inference_draft"],
                "suggested_questions": BASE_REVIEW_QUESTIONS,
                "no_live_model_call": True,
            },
            required_decisions=[
                "vision_accuracy",
                "accepted_visual_description",
                "question_answers",
                "adam_context_note",
                "privacy_level",
                "ready_for_downstream",
                "ocr_review_status",
            ],
            created_by="vision_pipeline",
        )
        session.add(review_task)
        session.flush()

    return {
        "metadata_profile_id": profile.id,
        "review_task_id": review_task.id,
        "created_profile": str(created_profile),
    }


def create_vision_draft_batch(
    *,
    session: Session,
    asset_ids: List[str],
    limit: int,
    queue: str,
    draft_type: str,
    model_name: str,
    input_detail: str,
    no_live_model_call: bool,
) -> Dict[str, Any]:
    if not no_live_model_call:
        raise HTTPException(
            status_code=400,
            detail="Live vision calls are intentionally disabled in this scaffold. Set up the provider gate before sending private media.",
        )

    assets = session.exec(_vision_candidate_statement(asset_ids)).all()
    assets = assets[: max(0, min(limit, 50))]
    response: Dict[str, Any] = {
        "created_count": 0,
        "skipped_count": 0,
        "metadata_profile_ids": [],
        "review_task_ids": [],
        "skipped_asset_ids": [],
    }

    for asset in assets:
        created = create_vision_draft_for_asset(
            session=session,
            asset=asset,
            queue=queue,
            draft_type=draft_type,
            model_name=model_name,
            input_detail=input_detail,
        )
        response["metadata_profile_ids"].append(created["metadata_profile_id"])
        if created["review_task_id"] not in response["review_task_ids"]:
            response["review_task_ids"].append(created["review_task_id"])

    requested = set(asset_ids)
    found = {asset.id for asset in assets}
    response["skipped_asset_ids"] = sorted(requested - found)
    response["skipped_count"] = len(response["skipped_asset_ids"])
    response["created_count"] = len(response["review_task_ids"])
    return response


def upsert_vision_review_artifacts(
    *,
    session: Session,
    task: Task,
    decisions: Dict[str, Any],
    annotation_id: str,
) -> Dict[str, Any]:
    profile = session.get(MetadataProfile, task.target_id)
    if profile is None:
        raise HTTPException(status_code=404, detail="Vision metadata profile not found")

    raw_profile = dict(profile.raw_profile or {})
    question_answers = decisions.get("question_answers") if isinstance(decisions.get("question_answers"), dict) else {}
    accepted_tags = _string_list(decisions.get("accepted_tags"))
    rejected_inferences = _string_list(decisions.get("rejected_system_inferences"))
    corrected_ocr = _string(decisions.get("corrected_ocr_text"))
    ocr_review_status = _string(decisions.get("ocr_review_status"), "not_present")
    ocr_truth_status = _string(decisions.get("ocr_truth_status"), "system_inference")

    profile.metadata_status = "adam_reviewed"
    profile.title = _string(decisions.get("title"), profile.title or task.human_id)
    profile.summary = _string(decisions.get("accepted_visual_description"), profile.summary or "")
    profile.adam_context_note = _string(decisions.get("adam_context_note"))
    profile.truth_status = _string(decisions.get("truth_status"), "system_inference")
    profile.source_genre = _string(decisions.get("source_genre"), profile.source_genre or "photo")
    profile.voice_presence = _string(decisions.get("voice_presence"), "absent")
    profile.date_label = _string(decisions.get("date_or_range"))
    profile.date_confidence = _string(decisions.get("date_confidence"), "unknown")
    profile.people = _string_list(decisions.get("people"))
    profile.places = _string_list(decisions.get("places"))
    profile.themes = _string_list(decisions.get("themes")) or accepted_tags
    profile.concrete_objects = _string_list(decisions.get("concrete_objects"))
    profile.open_questions = _string_list(decisions.get("remaining_questions"))
    profile.retrieval_notes = _string(decisions.get("retrieval_notes")) or _string(decisions.get("adam_context_note"))
    profile.training_notes = "Vision metadata is review/context material, not voice training text by itself."
    profile.quality_signals = {
        **(profile.quality_signals or {}),
        "vision_accuracy": decisions.get("vision_accuracy"),
        "ocr_review_status": ocr_review_status,
        "ready_for_downstream": decisions.get("ready_for_downstream"),
        "rejected_system_inference_count": len(rejected_inferences),
    }
    profile.embedding_hints = {
        **(profile.embedding_hints or {}),
        "accepted_tags": accepted_tags,
        "question_answers": question_answers,
        "ocr_segment_created": bool(corrected_ocr and ocr_review_status != "not_present"),
    }
    profile.raw_profile = {
        **raw_profile,
        "adam_review": {
            **decisions,
            "source_annotation_id": annotation_id,
            "question_answers": question_answers,
        },
        "rejected_system_inferences": rejected_inferences,
    }
    profile.source_annotation_id = annotation_id
    profile.reviewed_by = "adam"
    profile.reviewed_at = utcnow()
    profile.updated_at = utcnow()
    session.add(profile)
    session.flush()

    creates: Dict[str, Any] = {"metadata_profile_id": profile.id}
    asset_id = _string(task.input_payload.get("asset_id")) or profile.target_id
    asset = session.get(Asset, asset_id)
    ready_for_downstream = _truthy(decisions.get("ready_for_downstream"))
    privacy_level = _string(decisions.get("privacy_level"), "unreviewed")
    privacy_notes = _string(decisions.get("privacy_notes"))
    redaction_required = privacy_level in {"sealed", "private_sensitive"} or "redact" in privacy_notes.lower()

    boundary = session.exec(
        select(Boundary).where(Boundary.target_type == "asset").where(Boundary.target_id == asset_id)
    ).first()
    if boundary is None:
        boundary = Boundary(target_type="asset", target_id=asset_id)
    boundary.privacy_level = privacy_level
    boundary.searchable = ready_for_downstream and privacy_level not in {"sealed"}
    boundary.retrievable_in_chat = ready_for_downstream and privacy_level not in {"sealed", "private_sensitive"}
    boundary.quotable = False
    boundary.summarizable = ready_for_downstream
    boundary.usable_for_voice_context = ready_for_downstream and privacy_level not in {"sealed", "private_sensitive"}
    boundary.usable_for_sft = False
    boundary.usable_for_dpo = False
    boundary.usable_for_eval = ready_for_downstream and privacy_level not in {"sealed"}
    boundary.usable_for_gallery_public = ready_for_downstream and privacy_level == "public_candidate" and not redaction_required
    boundary.usable_for_gallery_family = ready_for_downstream and privacy_level in {"family_private", "public_candidate"}
    boundary.redaction_required = redaction_required
    boundary.notes = privacy_notes or "Vision review boundary generated from Adam review."
    boundary.reviewed_by = "adam"
    boundary.reviewed_at = utcnow()
    session.add(boundary)
    session.flush()
    creates["boundary_id"] = boundary.id

    if asset is not None:
        asset.processing_status = "vision_reviewed"
        asset.maturity_level = "L3_reviewed" if ready_for_downstream and not redaction_required else "L2_needs_review"
        asset.updated_at = utcnow()
        session.add(asset)

    if corrected_ocr and ocr_review_status != "not_present":
        candidate_segments = session.exec(
            select(Segment)
            .where(Segment.asset_id == asset_id)
            .where(Segment.segment_type == "vision_ocr_text")
        ).all()
        existing = next(
            (segment for segment in candidate_segments if segment.locator.get("metadata_profile_id") == profile.id),
            None,
        )
        segment = existing or Segment(
            human_id=_human_id("SEG_VISION_OCR", _count(session, Segment)),
            asset_id=asset_id,
            segment_type="vision_ocr_text",
            title=f"OCR from {_string(task.input_payload.get('asset_title'), 'vision source')}",
            locator={"metadata_profile_id": profile.id, "source_annotation_id": annotation_id},
        )
        segment.text_content = corrected_ocr
        segment.source_truth_status = ocr_truth_status
        segment.maturity_level = "L2_extracted" if ocr_truth_status == "system_inference" else "L3_reviewed"
        segment.metadata_json = {
            **(segment.metadata_json or {}),
            "ocr_review_status": ocr_review_status,
            "source": "vision_review",
            "requires_quote_check": ocr_truth_status != "archival_source",
        }
        segment.updated_at = utcnow()
        session.add(segment)
        session.flush()
        creates["ocr_segment_id"] = segment.id

    return creates
