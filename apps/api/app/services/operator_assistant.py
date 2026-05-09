from __future__ import annotations

import json
from typing import Any, Dict, Optional

from app.config import Settings, settings
from app.models import Task
from app.services.model_generation import live_text_generation_ready


PHOTO_ASSISTANT_STEPS = [
    {
        "target_decision_key": "visual_description_correction",
        "label": "Reviewed visual description",
        "question": "What is visibly present in this photo? Keep this to what can be seen.",
        "rationale": "Visible facts anchor the gallery caption and retrieval description without becoming a memory claim.",
    },
    {
        "target_decision_key": "adam_context_note",
        "label": "Memory this photo brings up",
        "question": "What memory, story, relationship, or association does this photo bring up for you?",
        "rationale": "This is the generative memory field: Adam-authored context that can later support retrieval and prompt-pair candidates.",
    },
    {
        "target_decision_key": "invisible_context_note",
        "label": "Invisible context",
        "question": "What would someone not know from the pixels alone?",
        "rationale": "Invisible context keeps people, circumstances, and meaning separate from visible description.",
    },
    {
        "target_decision_key": "open_questions",
        "label": "Open questions",
        "question": "What uncertainty should stay unresolved instead of being smoothed over?",
        "rationale": "Open questions preserve uncertainty for downstream retrieval and generation.",
    },
    {
        "target_decision_key": "privacy_notes",
        "label": "Boundary note",
        "question": "Is there any privacy or boundary note future exports should remember?",
        "rationale": "Boundary notes help keep search, gallery, and training use dignified and permissioned.",
    },
]

PHOTO_UPDATE_KEYS = {
    "visual_description_correction",
    "accepted_visual_description",
    "adam_context_note",
    "invisible_context_note",
    "open_questions",
    "privacy_notes",
    "question_answers",
    "visible_people",
    "people",
    "absent_but_relevant_people",
    "place",
    "places",
    "date_or_range",
    "date_confidence",
    "event",
    "accepted_tags",
    "themes",
    "concrete_objects",
    "rejected_system_inferences",
    "privacy_level",
    "ready_for_downstream",
    "gallery_eligibility",
    "memory_potential",
    "privacy_sensitivity",
}

PROMPT_PAIR_UPDATE_KEYS = {
    "artifact_mode",
    "editor_mode",
    "prompt",
    "system_prompt",
    "voice_mode",
    "synthetic",
    "truth_status",
    "truth_mode",
    "grounding_asset_id",
    "context",
    "content",
    "chosen",
    "rejected",
    "export_flags",
    "failure_modes",
    "preferred_failure_modes",
    "operator_candidate_triage_intent",
}

SOURCE_UPDATE_KEYS = {
    "segment_boundary_good",
    "source_genre",
    "authorship",
    "authorship_note",
    "fictionality_status",
    "truth_status",
    "voice_presence",
    "charles_voice_presence",
    "voice_training_role",
    "context_use",
    "adam_context_note",
    "summary",
    "why_it_matters",
    "ready_for_processing",
    "privacy_level",
    "privacy_notes",
    "boundary_notes",
    "boundary_rationale",
    "usable_for_voice_context",
    "usable_for_grounded_generation",
    "usable_for_sft",
    "usable_for_dpo",
    "generate_pairs_on_submit",
    "prompt_pair_potential",
    "prompt_pair_decision",
    "ready_for_prompt_pair_factory",
    "source_section_review_hint",
    "source_section_context_resolved",
    "source_section_review_resolved",
    "source_use_mode",
    "source_use_modes",
    "people",
    "places",
    "date_or_range",
    "date_confidence",
    "themes",
    "concrete_objects",
    "open_questions",
    "retrieval_notes",
    "training_notes",
}

GENERIC_UPDATE_KEYS = {
    "session_notes",
    "context",
}


def _string(value: Any, fallback: str = "") -> str:
    return value if isinstance(value, str) and value.strip() else fallback


def _truncate_text(value: Any, limit: int = 2500) -> str:
    text = value if isinstance(value, str) else json.dumps(value, default=str, ensure_ascii=False)
    if len(text) <= limit:
        return text
    return text[: limit - 20].rstrip() + "\n[truncated]"


def _list_has_value(value: Any) -> bool:
    if isinstance(value, list):
        return any(str(item).strip() for item in value)
    return bool(_string(value))


def _decision_has_value(decisions: Dict[str, Any], key: str) -> bool:
    if key == "visual_description_correction":
        return bool(_string(decisions.get("visual_description_correction")) or _string(decisions.get("accepted_visual_description")))
    if key == "open_questions":
        return _list_has_value(decisions.get("open_questions"))
    return bool(_string(decisions.get(key)))


def _allowed_update_keys(task: Task) -> set[str]:
    if task.task_type in {"photo_context", "vision_draft_review"}:
        return PHOTO_UPDATE_KEYS
    if task.task_type in {"gold_voice_edit", "grounded_prompt_pair_candidate"}:
        return PROMPT_PAIR_UPDATE_KEYS
    if task.task_type in {"text_segment_review", "text_segment_boundary_review", "email_voice_sample"}:
        return SOURCE_UPDATE_KEYS
    return GENERIC_UPDATE_KEYS


def _safe_json_value(value: Any) -> Any:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, bool) or isinstance(value, int) or isinstance(value, float):
        return value
    if isinstance(value, list):
        return [_safe_json_value(item) for item in value if _safe_json_value(item) not in ("", None)]
    if isinstance(value, dict):
        return {
            str(key): _safe_json_value(item)
            for key, item in value.items()
            if _safe_json_value(item) not in ("", None, [], {})
        }
    return None


def _filter_field_updates(task: Task, updates: Any) -> Dict[str, Any]:
    if not isinstance(updates, dict):
        return {}
    allowed = _allowed_update_keys(task)
    filtered: Dict[str, Any] = {}
    for key, value in updates.items():
        if key not in allowed:
            continue
        safe_value = _safe_json_value(value)
        if safe_value in ("", None, [], {}):
            continue
        filtered[key] = safe_value
    return filtered


def _submit_requested(text: str) -> bool:
    normalized = text.lower()
    return any(phrase in normalized for phrase in ["submit", "send it", "turn it in", "mark it done", "ready to submit"])


def _required_missing_fields(task: Task, decisions: Dict[str, Any], updates: Optional[Dict[str, Any]] = None) -> list[str]:
    merged = {**decisions, **(updates or {})}
    if task.task_type in {"gold_voice_edit", "grounded_prompt_pair_candidate"}:
        artifact_mode = _string(merged.get("artifact_mode")) or _string((task.input_payload or {}).get("artifact_mode")) or "sft"
        required = ["prompt", "voice_mode"]
        if artifact_mode == "dpo":
            required.extend(["chosen", "rejected"])
        else:
            required.append("content")
        return [key for key in required if not _decision_has_value(merged, key)]
    if task.task_type in {"photo_context", "vision_draft_review"}:
        required = ["visual_description_correction", "adam_context_note", "privacy_level", "ready_for_downstream"]
        return [key for key in required if not _decision_has_value(merged, key)]
    return []


def _base_response(
    *,
    task: Task,
    app_settings: Settings,
    suggestion: Dict[str, Any],
    model_ready: bool,
    status: str,
    live_model_call_used: bool,
    field_updates: Optional[Dict[str, Any]] = None,
    field_update_summary: str = "",
    submit_recommendation: Optional[Dict[str, Any]] = None,
    error: Optional[str] = None,
) -> Dict[str, Any]:
    return {
        "assistant_type": "neutral_operator_assistant",
        "status": status,
        "task_id": task.id,
        "task_type": task.task_type,
        "model_name": app_settings.text_generation_model,
        "reasoning_effort": app_settings.text_generation_reasoning_effort,
        "model_ready": model_ready,
        "live_model_call_used": live_model_call_used,
        "target_decision_key": suggestion["target_decision_key"],
        "target_label": suggestion["label"],
        "next_question": suggestion["question"],
        "answer_format": "free_text",
        "apply_label": f"Apply to {suggestion['label']}",
        "rationale": suggestion["rationale"],
        "field_updates": field_updates or {},
        "field_update_summary": field_update_summary,
        "submit_recommendation": submit_recommendation or {
            "requested": False,
            "ready": False,
            "reason": "No submit request detected.",
            "missing_fields": [],
            "action_label": "Keep reviewing",
        },
        "safety_policy": {
            "not_charles_voice": True,
            "does_not_mutate_source": True,
            "applies_only_to_review_draft": True,
            "keeps_truth_boundaries": True,
            "no_secret_values_returned": True,
        },
        **({"error": error} if error else {}),
    }


def _photo_suggestion(task: Task, decisions: Dict[str, Any]) -> Dict[str, Any]:
    for step in PHOTO_ASSISTANT_STEPS:
        if not _decision_has_value(decisions, step["target_decision_key"]):
            return step
    return {
        "target_decision_key": "session_notes",
        "label": "Optional extra context",
        "question": "Anything else you want the system to remember about this item before submit?",
        "rationale": "The required review fields look complete; extra notes can still help future review.",
    }


def _prompt_pair_suggestion(task: Task, decisions: Dict[str, Any]) -> Dict[str, Any]:
    artifact_mode = _string(decisions.get("artifact_mode")) or _string((task.input_payload or {}).get("artifact_mode")) or "sft"
    payload = task.input_payload or {}
    if payload.get("source_photo_id") and payload.get("candidate_requires_adam_gold_edit") is True and not _string(decisions.get("context")):
        return {
            "target_decision_key": "context",
            "label": "Keep/edit/delete note",
            "question": "Looking at this photo-generated candidate, what is the main edit it needs, or should it be deleted?",
            "rationale": "Photo candidates arrive as alternatives. This note helps decide whether to refine this one or remove it from the queue.",
        }
    if not _string(decisions.get("prompt")) and not _string((task.input_payload or {}).get("prompt")):
        return {
            "target_decision_key": "prompt",
            "label": "User prompt",
            "question": "What should the user ask in this prompt pair?",
            "rationale": "A clear user prompt makes the training example inspectable as a singleton ticket.",
        }
    if artifact_mode == "dpo" and not _string(decisions.get("chosen")):
        return {
            "target_decision_key": "chosen",
            "label": "Chosen response",
            "question": "What should the stronger Charles-style response say?",
            "rationale": "The chosen side is the positive target for DPO review.",
        }
    if artifact_mode == "dpo" and not _string(decisions.get("rejected")):
        return {
            "target_decision_key": "rejected",
            "label": "Rejected response",
            "question": "What weak or less-authentic response should this be compared against?",
            "rationale": "The rejected side teaches what to avoid, but remains review metadata until approved.",
        }
    if artifact_mode != "dpo" and not _string(decisions.get("content")):
        return {
            "target_decision_key": "content",
            "label": "Assistant content",
            "question": "What should the assistant response say after Adam edits it?",
            "rationale": "SFT content should be the reviewed assistant answer, not a source excerpt by accident.",
        }
    return {
        "target_decision_key": "context",
        "label": "Context note",
        "question": "Any short context note explaining what still needs review before this is gold?",
        "rationale": "Context notes help future passes understand why a candidate is still rough or ready.",
    }


def _deterministic_operator_response(
    *,
    task: Task,
    decisions: Dict[str, Any],
    latest_user_answer: str,
    app_settings: Settings,
    model_ready: bool,
    status: str = "deterministic_no_model_call",
    error: Optional[str] = None,
) -> Dict[str, Any]:
    if task.task_type in {"photo_context", "vision_draft_review"}:
        suggestion = _photo_suggestion(task, decisions)
    elif task.task_type in {"gold_voice_edit", "grounded_prompt_pair_candidate"}:
        suggestion = _prompt_pair_suggestion(task, decisions)
    else:
        suggestion = {
            "target_decision_key": "session_notes",
            "label": "Review note",
            "question": "What is the next useful note or decision for this task?",
            "rationale": "This neutral assistant is task-scoped and only helps fill review fields.",
        }

    field_updates: Dict[str, Any] = {}
    if latest_user_answer.strip() and not _submit_requested(latest_user_answer):
        key = suggestion["target_decision_key"]
        if key in _allowed_update_keys(task):
            field_updates[key] = latest_user_answer.strip()

    requested = _submit_requested(latest_user_answer)
    missing_fields = _required_missing_fields(task, decisions, field_updates)
    submit_recommendation = {
        "requested": requested,
        "ready": requested and not missing_fields,
        "reason": (
            "Submit requested and required fields appear complete."
            if requested and not missing_fields
            else "Submit requested, but required fields still need review."
            if requested
            else "No submit request detected."
        ),
        "missing_fields": missing_fields,
        "action_label": "Submit ticket" if requested and not missing_fields else "Keep reviewing",
    }
    return _base_response(
        task=task,
        app_settings=app_settings,
        suggestion=suggestion,
        model_ready=model_ready,
        status=status,
        live_model_call_used=False,
        field_updates=field_updates,
        field_update_summary=(
            f"Applied to {suggestion['label']}." if field_updates else "No field update applied by fallback helper."
        ),
        submit_recommendation=submit_recommendation,
        error=error,
    )


def _operator_prompt(task: Task, decisions: Dict[str, Any], suggestion: Dict[str, Any], latest_user_answer: str) -> str:
    input_payload = task.input_payload or {}
    safe_payload = {
        key: value
        for key, value in input_payload.items()
        if key
        in {
            "asset_title",
            "source_title",
            "source_filename",
            "prompt",
            "content",
            "chosen",
            "rejected",
            "artifact_mode",
            "voice_mode",
            "truth_status",
            "source_excerpt",
            "candidate_requires_adam_gold_edit",
            "source_photo_title",
            "photo_pair_variant_label",
            "retrieval_gap_origin",
            "suggested_questions",
            "required_decisions",
        }
    }
    return "\n\n".join(
        [
            "You are the neutral CharlesOps operator assistant. You are not Charles Rotmil and must not imitate his voice.",
            "Goal: help Adam complete the current review ticket by asking one useful next question or by turning Adam's latest reply into structured field updates.",
            "Rules:",
            "- Never mutate source files or claim something is archival truth.",
            "- Do not expose secrets, credentials, environment variables, or API keys.",
            "- Only update fields from the allowed field list.",
            "- If Adam asks to submit, set submit_recommendation.requested=true and ready=true only when required fields appear complete.",
            "- If information is ambiguous, preserve uncertainty and ask a short follow-up question.",
            "- Return JSON only. No Markdown.",
            f"Task type: {task.task_type}",
            f"Task title/source: {_string(input_payload.get('asset_title')) or _string(input_payload.get('source_title')) or _string(input_payload.get('source_filename')) or task.human_id}",
            "Allowed field updates:\n" + json.dumps(sorted(_allowed_update_keys(task))),
            "Current decisions:\n" + _truncate_text(decisions, 4500),
            "Task payload excerpt:\n" + _truncate_text(safe_payload, 4500),
            "Deterministic next-field hint:\n"
            + json.dumps(
                {
                    "target_decision_key": suggestion["target_decision_key"],
                    "target_label": suggestion["label"],
                    "next_question": suggestion["question"],
                }
            ),
            "Latest Adam reply:\n" + (latest_user_answer.strip() or "[none yet]"),
            (
                "Return exactly this JSON shape: "
                '{"target_decision_key":"string","target_label":"string","next_question":"string",'
                '"apply_label":"string","rationale":"string","field_updates":{},'
                '"field_update_summary":"string","submit_recommendation":{"requested":false,"ready":false,'
                '"reason":"string","missing_fields":[],"action_label":"string"}}'
            ),
        ]
    )


def _parse_json_object(text: str) -> Dict[str, Any]:
    try:
        parsed = json.loads(text)
        return parsed if isinstance(parsed, dict) else {}
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end == -1 or end <= start:
            return {}
        try:
            parsed = json.loads(text[start : end + 1])
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            return {}


def _live_operator_response(
    *,
    task: Task,
    decisions: Dict[str, Any],
    latest_user_answer: str,
    app_settings: Settings,
    suggestion: Dict[str, Any],
) -> Dict[str, Any]:
    from openai import OpenAI

    client = OpenAI(
        api_key=app_settings.openai_api_key,
        project=app_settings.openai_project_id or None,
        timeout=180,
    )
    response = client.responses.create(
        model=app_settings.text_generation_model,
        reasoning={"effort": app_settings.text_generation_reasoning_effort},
        input=[
            {
                "role": "developer",
                "content": (
                    "You are a precise workflow assistant for an archival review tool. "
                    "Return one valid JSON object only. Keep Adam-authored memory, system inference, and source truth separate."
                ),
            },
            {"role": "user", "content": _operator_prompt(task, decisions, suggestion, latest_user_answer)},
        ],
        max_output_tokens=1200,
        store=False,
    )
    parsed = _parse_json_object(_string(getattr(response, "output_text", None)))
    field_updates = _filter_field_updates(task, parsed.get("field_updates"))
    missing_fields = _required_missing_fields(task, decisions, field_updates)
    submit_payload = parsed.get("submit_recommendation") if isinstance(parsed.get("submit_recommendation"), dict) else {}
    requested = bool(submit_payload.get("requested")) or _submit_requested(latest_user_answer)
    ready = bool(submit_payload.get("ready")) and not missing_fields
    submit_recommendation = {
        "requested": requested,
        "ready": ready,
        "reason": _string(submit_payload.get("reason"))
        or (
            "Submit requested and required fields appear complete."
            if requested and not missing_fields
            else "Submit requested, but required fields still need review."
            if requested
            else "No submit request detected."
        ),
        "missing_fields": missing_fields,
        "action_label": _string(submit_payload.get("action_label"), "Submit ticket" if ready else "Keep reviewing"),
    }
    live_suggestion = {
        "target_decision_key": _string(parsed.get("target_decision_key"), suggestion["target_decision_key"]),
        "label": _string(parsed.get("target_label"), suggestion["label"]),
        "question": _string(parsed.get("next_question"), suggestion["question"]),
        "rationale": _string(parsed.get("rationale"), suggestion["rationale"]),
    }
    if live_suggestion["target_decision_key"] not in _allowed_update_keys(task):
        live_suggestion["target_decision_key"] = suggestion["target_decision_key"]
        live_suggestion["label"] = suggestion["label"]

    return _base_response(
        task=task,
        app_settings=app_settings,
        suggestion=live_suggestion,
        model_ready=True,
        status="live_model_call",
        live_model_call_used=True,
        field_updates=field_updates,
        field_update_summary=_string(parsed.get("field_update_summary"), "Model parsed the reply into review fields."),
        submit_recommendation=submit_recommendation,
    )


def operator_assistant_suggestion(
    *,
    task: Task,
    decisions: Optional[Dict[str, Any]] = None,
    latest_user_answer: Optional[str] = None,
    app_settings: Settings = settings,
) -> Dict[str, Any]:
    decision_payload = decisions or {}
    answer_text = latest_user_answer or ""
    if task.task_type in {"photo_context", "vision_draft_review"}:
        suggestion = _photo_suggestion(task, decision_payload)
    elif task.task_type in {"gold_voice_edit", "grounded_prompt_pair_candidate"}:
        suggestion = _prompt_pair_suggestion(task, decision_payload)
    else:
        suggestion = {
            "target_decision_key": "session_notes",
            "label": "Review note",
            "question": "What is the next useful note or decision for this task?",
            "rationale": "This neutral assistant is task-scoped and only helps fill review fields.",
        }

    model_ready = live_text_generation_ready(app_settings)
    if not model_ready:
        return _deterministic_operator_response(
            task=task,
            decisions=decision_payload,
            latest_user_answer=answer_text,
            app_settings=app_settings,
            model_ready=model_ready,
        )

    try:
        return _live_operator_response(
            task=task,
            decisions=decision_payload,
            latest_user_answer=answer_text,
            app_settings=app_settings,
            suggestion=suggestion,
        )
    except Exception as exc:  # pragma: no cover - provider/network failures fall back into normal review mode.
        return _deterministic_operator_response(
            task=task,
            decisions=decision_payload,
            latest_user_answer=answer_text,
            app_settings=app_settings,
            model_ready=model_ready,
            status="live_error_fallback",
            error=f"{type(exc).__name__}: {exc}",
        )
