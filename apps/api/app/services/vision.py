from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import HTTPException
from sqlmodel import Session, select

from app.config import Settings, settings
from app.models import Asset, AssetSnapshot, Boundary, Derivative, MetadataProfile, ObjectFile, Segment, Task, utcnow
from app.services.photo_constants import PHOTO_MEMORY_PROFILE_TYPE, PHOTO_STATUS_MACHINE_DRAFT
from app.services.photo_memory import promote_photo_profile_downstream

MAX_VISION_IMAGE_BYTES = 8 * 1024 * 1024


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
    "Mark uncertain observations as uncertainties. If the image is viewable, visual_summary must be a concrete "
    "one-sentence description of the pixels, even when the content is unclear. Output structured JSON only. "
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


def _suggested_questions(task: Task) -> List[Dict[str, Any]]:
    questions = task.input_payload.get("suggested_questions")
    if not isinstance(questions, list):
        return []
    return [question for question in questions if isinstance(question, dict)]


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


def _derive_reviewed_truth_status(decisions: Dict[str, Any], *, adam_context: str, description: str) -> str:
    explicit = _string(decisions.get("truth_status"))
    if explicit and explicit not in {"system_inference", "model_generated"}:
        return explicit
    if adam_context.strip():
        return "adam_memory"
    if description.strip() and _string(decisions.get("vision_accuracy"), "not_applicable") != "rejected":
        return "adam_inference"
    return explicit or "system_inference"


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"yes", "true", "1", "approved", "accepted", "ready"}
    return False


def _asset_title(asset: Asset) -> str:
    return asset.title or asset.original_filename or asset.human_id


def _parse_json_object(text: str) -> Dict[str, Any]:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        lines = cleaned.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        cleaned = "\n".join(lines).strip()
    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError:
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start == -1 or end == -1 or end <= start:
            return {}
        try:
            parsed = json.loads(cleaned[start : end + 1])
        except json.JSONDecodeError:
            return {}
    return parsed if isinstance(parsed, dict) else {}


def _question_list(value: Any) -> List[Dict[str, str]]:
    if not isinstance(value, list):
        return []
    questions: List[Dict[str, str]] = []
    for index, item in enumerate(value[:6], start=1):
        if not isinstance(item, dict):
            continue
        question = _string(item.get("question"))
        if not question:
            continue
        questions.append(
            {
                "id": _string(item.get("id"), f"model_question_{index}"),
                "question": question,
                "reason": _string(item.get("reason"), "Model-suggested follow-up for Adam review."),
                "answer_type": _string(item.get("answer_type"), "text"),
            }
        )
    return questions


def _normalise_vision_draft(raw: Dict[str, Any]) -> Dict[str, Any]:
    suggested_questions = _question_list(raw.get("suggested_questions"))
    if not suggested_questions:
        suggested_questions = BASE_REVIEW_QUESTIONS
    return {
        "visual_summary": _string(raw.get("visual_summary")),
        "visible_people": _string_list(raw.get("visible_people")),
        "places": _string_list(raw.get("places")),
        "time_period_guess": _string(raw.get("time_period_guess")),
        "objects": _string_list(raw.get("objects")),
        "themes": _string_list(raw.get("themes")),
        "ocr_text": _string(raw.get("ocr_text")),
        "handwriting_text": _string(raw.get("handwriting_text")),
        "uncertainties": _string_list(raw.get("uncertainties")),
        "suggested_questions": suggested_questions,
        "privacy_flags": _string_list(raw.get("privacy_flags")),
        "confidence": _string(raw.get("confidence"), "unreviewed_model_inference"),
    }


def _vision_draft_has_observations(draft: Dict[str, Any]) -> bool:
    return any(
        [
            _string(draft.get("visual_summary")),
            _string_list(draft.get("visible_people")),
            _string_list(draft.get("places")),
            _string(draft.get("time_period_guess")),
            _string_list(draft.get("objects")),
            _string_list(draft.get("themes")),
            _string(draft.get("ocr_text")),
            _string(draft.get("handwriting_text")),
            _string_list(draft.get("uncertainties")),
            _string_list(draft.get("privacy_flags")),
        ]
    )


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
    exact = session.exec(
        select(MetadataProfile)
        .where(MetadataProfile.target_type == "asset")
        .where(MetadataProfile.target_id == asset.id)
        .where(MetadataProfile.profile_type == draft_type)
    ).first()
    if exact is not None:
        return exact

    candidates = session.exec(
        select(MetadataProfile)
        .where(MetadataProfile.target_type == "asset")
        .where(MetadataProfile.target_id == asset.id)
        .order_by(MetadataProfile.updated_at.desc())
    ).all()
    for candidate in candidates:
        if _existing_review_task(session, candidate) is not None:
            return candidate
    return None


def _existing_review_task(session: Session, profile: MetadataProfile) -> Optional[Task]:
    return session.exec(
        select(Task)
        .where(Task.task_type == "vision_draft_review")
        .where(Task.target_type == "metadata_profile")
        .where(Task.target_id == profile.id)
        .where(Task.status == "ready")
    ).first()


def _vision_review_task_payload(
    *,
    asset: Asset,
    profile: MetadataProfile,
    draft_type: str,
    request_plan: Dict[str, Any],
    system_inference_draft: Dict[str, Any],
    no_live_model_call: bool,
    model_name: str,
    input_detail: str,
) -> Dict[str, Any]:
    return {
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
        "suggested_questions": system_inference_draft["suggested_questions"],
        "no_live_model_call": no_live_model_call,
        "live_model_call_used": not no_live_model_call,
        "model_name": model_name,
        "input_detail": input_detail,
    }


def _latest_image_derivative(session: Session, asset_id: str, variant: str) -> Optional[Derivative]:
    derivatives = session.exec(
        select(Derivative)
        .where(Derivative.asset_id == asset_id)
        .where(Derivative.derivative_type == "image_preview")
        .where(Derivative.status == "ready")
    ).all()
    matches = [item for item in derivatives if item.metadata_json.get("variant") == variant]
    return sorted(matches, key=lambda item: item.created_at, reverse=True)[0] if matches else None


def _object_file_local_path(object_file: ObjectFile, app_settings: Settings) -> Optional[Path]:
    storage_root = Path(app_settings.storage_root).resolve()
    if object_file.storage_provider == "local":
        path = (storage_root / object_file.object_key).resolve()
    elif object_file.storage_provider == "gcs":
        cache_key = object_file.metadata_json.get("local_preview_cache_key")
        if not isinstance(cache_key, str) or not cache_key.strip():
            cache_key = "/".join(["preview_cache/gcs", object_file.object_key])
        path = (storage_root / cache_key).resolve()
    else:
        return None
    if not path.is_relative_to(storage_root) or not path.is_file():
        return None
    return path


def _image_object_file_for_asset(session: Session, asset: Asset) -> Optional[ObjectFile]:
    object_file: Optional[ObjectFile] = None
    for variant in ("display", "thumbnail"):
        derivative = _latest_image_derivative(session, asset.id, variant)
        if derivative and derivative.object_file_id:
            object_file = session.get(ObjectFile, derivative.object_file_id)
            if object_file:
                break
    if object_file is not None:
        return object_file

    snapshot = session.exec(
        select(AssetSnapshot)
        .where(AssetSnapshot.asset_id == asset.id)
        .where(AssetSnapshot.snapshot_type == "source_mirror")
        .order_by(AssetSnapshot.version.desc())
    ).first()
    if snapshot and snapshot.object_file_id:
        return session.get(ObjectFile, snapshot.object_file_id)
    return None


def _image_data_url_for_asset(session: Session, asset: Asset, app_settings: Settings) -> Dict[str, Any]:
    object_file = _image_object_file_for_asset(session, asset)
    if object_file is None:
        return {"image_data_url": "", "reason": "no_mirrored_image_file"}
    content_type = object_file.content_type or asset.mime_type or ""
    if not content_type.startswith("image/"):
        return {"image_data_url": "", "object_file_id": object_file.id, "content_type": content_type, "reason": "not_an_image"}
    path = _object_file_local_path(object_file, app_settings)
    if path is None:
        return {"image_data_url": "", "object_file_id": object_file.id, "content_type": content_type, "reason": "local_image_unavailable"}
    byte_size = path.stat().st_size
    if byte_size > MAX_VISION_IMAGE_BYTES:
        return {
            "image_data_url": "",
            "object_file_id": object_file.id,
            "content_type": content_type,
            "byte_size": byte_size,
            "reason": "image_too_large",
        }
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return {
        "image_data_url": f"data:{content_type};base64,{encoded}",
        "object_file_id": object_file.id,
        "content_type": content_type,
        "byte_size": byte_size,
        "reason": "ready",
    }


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


def live_vision_ready(app_settings: Settings = settings) -> bool:
    return bool(app_settings.vision_live_calls_enabled and app_settings.openai_api_key)


def _live_vision_user_prompt(asset: Asset) -> str:
    return (
        "Analyze this image for CharlesOps review. Return one JSON object matching the requested schema. "
        "Do not identify people by name unless visible text or supplied metadata explicitly names them. "
        "Use visible_people for generic descriptions like 'older man' or 'child' when identity is uncertain. "
        "Put all uncertainty in uncertainties. Do not leave visual_summary blank; if the image is blurry or ambiguous, "
        "describe the uncertainty in visual_summary and uncertainties. Suggest questions Adam should answer to turn "
        "this into reviewed memory context.\n\n"
        f"Asset title: {_asset_title(asset)}\n"
        f"Original filename: {asset.original_filename or ''}\n"
        f"Asset type: {asset.asset_type}\n"
    )


def _call_live_vision_model(
    *,
    asset: Asset,
    image_data_url: str,
    schema: Dict[str, Any],
    model_name: str,
    input_detail: str,
    app_settings: Settings,
) -> Dict[str, Any]:
    from openai import OpenAI

    client = OpenAI(
        api_key=app_settings.openai_api_key,
        project=app_settings.openai_project_id or None,
        timeout=180,
    )
    text_format = {
        "type": "json_schema",
        "name": _string(schema.get("name"), "charlesops_vision_draft_v1"),
        "schema": schema.get("schema") if isinstance(schema.get("schema"), dict) else schema,
        "strict": True,
    }
    response = client.responses.create(
        model=model_name,
        input=[
            {"role": "developer", "content": VISION_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": [
                    {
                        "type": "input_text",
                        "text": "\n\n".join(
                            [
                                _live_vision_user_prompt(asset),
                                "Required JSON schema:\n" + json.dumps(schema, ensure_ascii=False),
                            ]
                        ),
                    },
                    {"type": "input_image", "image_url": image_data_url, "detail": input_detail},
                ],
            },
        ],
        text={"format": text_format},
        max_output_tokens=1400,
        store=False,
    )
    output_text = _string(getattr(response, "output_text", None))
    raw = _parse_json_object(output_text)
    if not raw:
        raise ValueError("Vision model returned no parseable JSON object.")
    draft = _normalise_vision_draft(raw)
    if not _vision_draft_has_observations(draft):
        raise ValueError("Vision model returned structured JSON with no usable image observations.")
    return {
        "draft": draft,
        "raw_model_output": raw,
        "response_id": _string(getattr(response, "id", None)),
    }


def analyze_photo_with_model(
    *,
    session: Session,
    asset_id: str,
    schema: Dict[str, Any] = VISION_DRAFT_SCHEMA,
    model_name: str,
    input_detail: str,
    app_settings: Settings = settings,
) -> Dict[str, Any]:
    asset = session.get(Asset, asset_id)
    if asset is None:
        raise HTTPException(status_code=404, detail="Photo asset not found")
    if asset.asset_type not in {"photo", "scan"}:
        raise HTTPException(status_code=400, detail="Live vision analysis requires a photo or scan asset.")
    if not live_vision_ready(app_settings):
        raise HTTPException(
            status_code=400,
            detail="Live vision calls require VISION_LIVE_CALLS_ENABLED=true and OPENAI_API_KEY.",
        )
    image_payload = _image_data_url_for_asset(session, asset, app_settings)
    if not image_payload.get("image_data_url"):
        raise HTTPException(status_code=400, detail=f"Live vision image unavailable: {image_payload.get('reason')}")
    try:
        live_result = _call_live_vision_model(
            asset=asset,
            image_data_url=str(image_payload["image_data_url"]),
            schema=schema,
            model_name=model_name,
            input_detail=input_detail,
            app_settings=app_settings,
        )
    except ValueError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {
        "asset_id": asset.id,
        "schema_name": _string(schema.get("name")) if isinstance(schema, dict) else "",
        "draft": live_result["draft"],
        "raw_model_output": live_result.get("raw_model_output"),
        "response_id": live_result.get("response_id"),
        "object_file_id": image_payload.get("object_file_id"),
        "content_type": image_payload.get("content_type"),
        "byte_size": image_payload.get("byte_size"),
    }


def create_vision_draft_for_asset(
    *,
    session: Session,
    asset: Asset,
    queue: str,
    draft_type: str,
    model_name: str,
    input_detail: str,
    no_live_model_call: bool = True,
    app_settings: Settings = settings,
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
    effective_draft_type = profile.profile_type or draft_type

    request_plan = build_vision_request_plan(
        asset,
        model_name=model_name,
        input_detail=input_detail,
        draft_type=effective_draft_type,
    )
    if no_live_model_call:
        system_inference_draft = {
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
        }
        live_metadata: Dict[str, Any] = {"no_live_model_call": True}
        reason_created = "Vision pipeline prepared draft metadata/questions for Adam review. No live model call was made."
    else:
        if not live_vision_ready(app_settings):
            raise HTTPException(
                status_code=400,
                detail="Live vision calls require VISION_LIVE_CALLS_ENABLED=true and OPENAI_API_KEY.",
            )
        live_result = analyze_photo_with_model(
            session=session,
            asset_id=asset.id,
            schema=VISION_DRAFT_SCHEMA,
            model_name=model_name,
            input_detail=input_detail,
            app_settings=app_settings,
        )
        system_inference_draft = live_result["draft"]
        live_metadata = {
            "no_live_model_call": False,
            "live_model_call_used": True,
            "live_response_id": live_result.get("response_id"),
            "object_file_id": live_result.get("object_file_id"),
            "content_type": live_result.get("content_type"),
            "byte_size": live_result.get("byte_size"),
            "schema_name": live_result.get("schema_name"),
            "raw_model_output": live_result.get("raw_model_output"),
        }
        reason_created = "Live vision model drafted system-inference metadata/questions for Adam review."

    raw_profile = dict(profile.raw_profile or {})
    profile.metadata_status = PHOTO_STATUS_MACHINE_DRAFT if profile.profile_type == PHOTO_MEMORY_PROFILE_TYPE else "machine_draft"
    profile.title = profile.title or _asset_title(asset)
    profile.summary = system_inference_draft["visual_summary"]
    profile.truth_status = "system_inference"
    profile.source_genre = "photo" if asset.asset_type == "photo" else "scan"
    profile.voice_presence = "absent"
    profile.open_questions = [question["question"] for question in system_inference_draft["suggested_questions"]]
    profile.quality_signals = {
        **(profile.quality_signals or {}),
        "vision_draft_status": "not_run" if no_live_model_call else "live_model_call",
        "model_name": model_name,
        "input_detail": input_detail,
        "requires_adam_review": True,
        **live_metadata,
    }
    profile.embedding_hints = {
        **(profile.embedding_hints or {}),
        "recommended_embedding_targets": ["visual_summary", "adam_context_note", "accepted_tags", "ocr_text"],
        "modality": asset.asset_type,
        "use_before_review": False,
    }
    profile.raw_profile = {
        **raw_profile,
        "vision_request_plan": request_plan,
        "system_inference_draft": system_inference_draft,
        **live_metadata,
    }
    if created_profile:
        profile.created_by = "vision_pipeline"
    profile.updated_at = utcnow()
    session.add(profile)
    session.flush()

    task_payload = _vision_review_task_payload(
        asset=asset,
        profile=profile,
        draft_type=effective_draft_type,
        request_plan=request_plan,
        system_inference_draft=system_inference_draft,
        no_live_model_call=no_live_model_call,
        model_name=model_name,
        input_detail=input_detail,
    )
    review_task = _existing_review_task(session, profile)
    if review_task is None:
        review_task = Task(
            human_id=_human_id("TASK_VISION_REVIEW", _count(session, Task)),
            task_type="vision_draft_review",
            target_type="metadata_profile",
            target_id=profile.id,
            priority=72,
            queue=queue,
            reason_created=reason_created,
            input_payload=task_payload,
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
    else:
        review_task.queue = queue
        review_task.reason_created = reason_created
        review_task.input_payload = {
            **(review_task.input_payload or {}),
            **task_payload,
        }
        required = list(review_task.required_decisions or [])
        for decision in [
            "vision_accuracy",
            "accepted_visual_description",
            "question_answers",
            "adam_context_note",
            "privacy_level",
            "ready_for_downstream",
            "ocr_review_status",
        ]:
            if decision not in required:
                required.append(decision)
        review_task.required_decisions = required
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
    app_settings: Settings = settings,
) -> Dict[str, Any]:
    if not no_live_model_call and not live_vision_ready(app_settings):
        raise HTTPException(
            status_code=400,
            detail="Live vision calls require VISION_LIVE_CALLS_ENABLED=true and OPENAI_API_KEY.",
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
            no_live_model_call=no_live_model_call,
            app_settings=app_settings,
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
    question_answer_rows = _question_answer_rows(task, decisions)
    question_answer_context = _question_answer_context(question_answer_rows)
    accepted_tags = _string_list(decisions.get("accepted_tags"))
    rejected_inferences = _string_list(decisions.get("rejected_system_inferences"))
    corrected_ocr = _string(decisions.get("corrected_ocr_text"))
    ocr_review_status = _string(decisions.get("ocr_review_status"), "not_present")
    ocr_truth_status = _string(decisions.get("ocr_truth_status"), "system_inference")
    description = _string(decisions.get("accepted_visual_description"), profile.summary or "")
    adam_context = "\n\n".join(
        part
        for part in [
            _string(decisions.get("adam_context_note")) or _string(decisions.get("invisible_context_note")),
            question_answer_context,
        ]
        if part
    )
    ocr_context = (
        f"Vision OCR/handwriting ({ocr_review_status}):\n{corrected_ocr}"
        if corrected_ocr and ocr_review_status != "not_present"
        else ""
    )

    profile.metadata_status = "adam_reviewed"
    profile.title = _string(decisions.get("title"), profile.title or task.human_id)
    profile.summary = description
    profile.adam_context_note = adam_context
    profile.truth_status = _derive_reviewed_truth_status(decisions, adam_context=adam_context, description=description)
    profile.source_genre = _string(decisions.get("source_genre"), profile.source_genre or "photo")
    profile.voice_presence = _string(decisions.get("voice_presence"), "absent")
    profile.date_label = _string(decisions.get("date_or_range"))
    profile.date_confidence = _string(decisions.get("date_confidence"), "unknown")
    profile.people = _string_list(decisions.get("people"))
    profile.places = _string_list(decisions.get("places"))
    profile.themes = _string_list(decisions.get("themes")) or accepted_tags
    profile.concrete_objects = _string_list(decisions.get("concrete_objects"))
    profile.open_questions = _string_list(decisions.get("remaining_questions"))
    profile.retrieval_notes = "\n\n".join(
        part
        for part in [_string(decisions.get("retrieval_notes")), adam_context, ocr_context]
        if part
    )
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
            "answered_questions": question_answer_rows,
            "question_answer_context": question_answer_context,
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

    downstream = promote_photo_profile_downstream(
        session=session,
        profile=profile,
        asset=asset,
        boundary=boundary,
        annotation_id=annotation_id,
        ready_for_downstream=ready_for_downstream,
    )
    creates.update({key: value for key, value in downstream.items() if value})
    for key in ["vector_handoff_status", "vector_handoff_reason", "vector_handoff_record_id"]:
        creates[key] = downstream.get(key)

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
