from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, List

from sqlmodel import Session, select

from app.config import Settings
from app.models import Task
from app.services.model_generation import TextDraftRequest, build_responses_api_request_body
from app.services.prompt_pair_reference_pack import compile_prompt_pair_reference_pack, select_prompt_pair_reference_examples


def stable_hash(payload: Dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def content_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def stable_json(payload: Dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str, separators=(",", ":"))


def demo_safety_policy() -> Dict[str, Any]:
    return {
        "outputs_truth_status": "model_generated",
        "adam_review_required": True,
        "never_training_truth_without_review": True,
        "fine_tuning_api_calls_allowed": False,
    }


def generation_blockers(app_settings: Settings) -> List[str]:
    blockers = []
    if not app_settings.text_generation_live_calls_enabled:
        blockers.append("text_generation_live_calls_disabled")
    if not app_settings.openai_api_key:
        blockers.append("openai_api_key_missing")
    return blockers


def text_generation_credential_requirements(app_settings: Settings) -> Dict[str, Any]:
    return {
        "requirements_type": "text_generation_credentials",
        "api": "responses",
        "model_name": app_settings.text_generation_model,
        "reasoning_effort": app_settings.text_generation_reasoning_effort,
        "required_env": [
            {
                "name": "OPENAI_API_KEY",
                "configured": bool(app_settings.openai_api_key),
                "purpose": "Authenticate GPT text generation draft calls.",
                "secret": True,
            },
            {
                "name": "TEXT_GENERATION_LIVE_CALLS_ENABLED",
                "configured": bool(app_settings.text_generation_live_calls_enabled),
                "required_value": "true",
                "purpose": "Explicitly opt in to live model-generated demo drafts.",
                "secret": False,
            },
        ],
        "optional_env": [
            {
                "name": "OPENAI_PROJECT_ID",
                "configured": bool(app_settings.openai_project_id),
                "purpose": "Optional OpenAI project scoping for Responses API calls.",
                "secret": False,
            }
        ],
        "env_file_policy": {
            "secret_env_files_ignored": True,
            "ignored_patterns": [".env", ".env.*"],
            "tracked_template": ".env.example",
            "never_return_secret_values": True,
            "operator_note": "Put real credentials in a local .env or process environment; commit only .env.example.",
        },
        "safety_policy": demo_safety_policy(),
    }


def held_out_prompts(session: Session, *, limit: int, include_private_text_for_checks: bool = False) -> List[Dict[str, Any]]:
    tasks = session.exec(
        select(Task)
        .where(Task.task_type == "gold_voice_edit")
        .where(Task.queue == "prompt_pairs_needing_gold_edits")
        .where(Task.status == "ready")
        .order_by(Task.created_at.asc())
    ).all()
    held_out = []
    for task in tasks:
        payload = task.input_payload or {}
        prompt = payload.get("prompt")
        response = payload.get("content") or payload.get("chosen")
        rejected = payload.get("rejected")
        if not isinstance(prompt, str) or not prompt.strip() or not isinstance(response, str) or not response.strip():
            continue
        item = {
            "task_id": task.id,
            "task_human_id": task.human_id,
            "prompt": prompt,
            "prompt_sha256": content_hash(prompt),
            "held_out_response_sha256": content_hash(response),
            "rejected_response_sha256": content_hash(rejected) if isinstance(rejected, str) and rejected.strip() else None,
            "system_prompt": payload.get("system_prompt") or "You are Charles Rotmil.",
            "voice_mode": payload.get("voice_mode"),
            "conversation_family": payload.get("conversation_family") or payload.get("family") or "unknown",
            "artifact_mode": payload.get("artifact_mode") or "sft",
            "truth_status": payload.get("truth_status"),
            "source_title": payload.get("source_title"),
            "source_excerpt": payload.get("source_excerpt") or "",
            "context": payload.get("context") or "",
            "synthetic": payload.get("synthetic"),
            "excluded_from_training_export": True,
        }
        if include_private_text_for_checks:
            item["_held_out_response_text"] = response
            item["_rejected_response_text"] = rejected if isinstance(rejected, str) else ""
        held_out.append(item)
        if len(held_out) >= limit:
            break
    return held_out


def public_held_out_prompt(item: Dict[str, Any]) -> Dict[str, Any]:
    return {key: value for key, value in item.items() if not key.startswith("_")}


def demo_generation_input_plan(
    *,
    app_settings: Settings,
    blockers: List[str],
    held_out: List[Dict[str, Any]],
    reference_pack: Dict[str, Any],
) -> Dict[str, Any]:
    prompt_inputs = [
        {
            "task_id": item["task_id"],
            "task_human_id": item["task_human_id"],
            "prompt": item["prompt"],
            "prompt_sha256": item["prompt_sha256"],
            "voice_mode": item.get("voice_mode"),
            "artifact_mode": item.get("artifact_mode"),
            "excluded_from_training_export": True,
        }
        for item in held_out
    ]
    prompt_set_json = json.dumps(prompt_inputs, sort_keys=True, separators=(",", ":"))
    return {
        "api": "responses",
        "model_name": app_settings.text_generation_model,
        "reasoning_effort": app_settings.text_generation_reasoning_effort,
        "store": False,
        "live_generation_ready": not blockers,
        "live_generation_blockers": blockers,
        "credential_requirements": text_generation_credential_requirements(app_settings),
        "reference_pack_content_sha256": reference_pack["content_sha256"],
        "reference_pack_sample_count": reference_pack["sample_count"],
        "reference_pack_ready_for_generation_context": reference_pack["ready_for_generation_context"],
        "held_out_prompt_count": len(prompt_inputs),
        "held_out_prompt_set_sha256": content_hash(prompt_set_json),
        "held_out_prompts": prompt_inputs,
        "safety_policy": demo_safety_policy(),
    }


def demo_reference_examples_for_item(
    *,
    session: Session,
    item: Dict[str, Any],
    exclude_task_ids: set[str] | None = None,
    limit: int = 6,
) -> List[Dict[str, Any]]:
    excluded = set(exclude_task_ids or set())
    excluded.add(str(item["task_id"]))
    examples = [
        example
        for example in select_prompt_pair_reference_examples(
            session=session,
            voice_mode=item.get("voice_mode"),
            conversation_family=item.get("conversation_family"),
            limit=max(limit + 2, 8),
        )
        if str((example.get("metadata") or {}).get("task_id") or "") not in excluded
    ]
    return examples[:limit]


def demo_text_draft_request_for_item(
    *,
    item: Dict[str, Any],
    reference_examples: List[Dict[str, Any]],
    app_settings: Settings,
) -> TextDraftRequest:
    source_text = "\n\n".join(
        part
        for part in [str(item.get("source_excerpt") or "").strip(), str(item.get("context") or "").strip()]
        if part
    )
    return TextDraftRequest(
        system_prompt=str(item.get("system_prompt") or "You are Charles Rotmil."),
        user_prompt=str(item["prompt"]),
        source_title=str(item.get("source_title") or "held-out prompt"),
        source_text=source_text,
        voice_mode=str(item.get("voice_mode") or "unknown"),
        conversation_family=str(item.get("conversation_family") or "unknown"),
        target_response_shape="demo_response",
        truth_mode="model_generated",
        reference_examples=reference_examples,
        model_name=app_settings.text_generation_model,
        reasoning_effort=app_settings.text_generation_reasoning_effort,
    )


def _response_api_input(messages: List[Dict[str, Any]], role: str) -> str:
    for message in messages:
        if message.get("role") == role:
            return str(message.get("content") or "")
    return ""


def _request_preview_item(
    *,
    session: Session,
    item: Dict[str, Any],
    app_settings: Settings,
    sequence_number: int,
    exclude_reference_task_ids: set[str] | None = None,
) -> Dict[str, Any]:
    reference_examples = demo_reference_examples_for_item(
        session=session,
        item=item,
        exclude_task_ids=exclude_reference_task_ids,
        limit=6,
    )
    reference_ids = [
        (example.get("metadata") or {}).get("reference_id")
        for example in reference_examples
        if (example.get("metadata") or {}).get("reference_id")
    ]
    request = demo_text_draft_request_for_item(
        item=item,
        reference_examples=reference_examples,
        app_settings=app_settings,
    )
    request_body = build_responses_api_request_body(
        request,
        model_name=app_settings.text_generation_model,
        reasoning_effort=app_settings.text_generation_reasoning_effort,
    )
    request_body_json = json.dumps(request_body, ensure_ascii=False, sort_keys=True, indent=2)
    compact_request_body_json = json.dumps(request_body, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    held_out_response = str(item.get("_held_out_response_text") or "")
    rejected_response = str(item.get("_rejected_response_text") or "")
    developer_message = _response_api_input(request_body.get("input") or [], "developer")
    user_message = _response_api_input(request_body.get("input") or [], "user")
    return {
        "sequence_number": sequence_number,
        "task_id": item["task_id"],
        "task_human_id": item["task_human_id"],
        "artifact_mode": item.get("artifact_mode"),
        "voice_mode": item.get("voice_mode"),
        "conversation_family": item.get("conversation_family"),
        "prompt": item["prompt"],
        "prompt_sha256": item["prompt_sha256"],
        "held_out_response_sha256": item.get("held_out_response_sha256"),
        "rejected_response_sha256": item.get("rejected_response_sha256"),
        "source_title": item.get("source_title") or "held-out prompt",
        "reference_example_count": len(reference_examples),
        "reference_ids": reference_ids,
        "request_body": request_body,
        "request_body_sha256": content_hash(compact_request_body_json),
        "developer_message_sha256": content_hash(developer_message),
        "user_message_sha256": content_hash(user_message),
        "user_message_char_count": len(user_message),
        "safety_checks": {
            "no_live_model_call": True,
            "does_not_create_generation": True,
            "store_false": request_body.get("store") is False,
            "fine_tuning_api_calls_allowed": False,
            "held_out_answer_excluded_from_request": not held_out_response or held_out_response not in request_body_json,
            "rejected_response_excluded_from_request": not rejected_response or rejected_response not in request_body_json,
            "output_truth_status": "model_generated",
            "adam_review_required": True,
        },
        "request_body_json": request_body_json,
    }


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


def _indent_block(value: str, spaces: int = 6) -> str:
    prefix = " " * spaces
    if not value:
        return f"{prefix}''"
    return "\n".join(prefix + line for line in value.splitlines())


def demo_generation_request_preview_yaml(payload: Dict[str, Any]) -> str:
    lines = [
        "demo_generation_request_preview:",
        f"  preview_type: {_yaml_scalar(payload.get('preview_type'))}",
        f"  review_policy: {_yaml_scalar(payload.get('review_policy'))}",
        f"  model_name: {_yaml_scalar(payload.get('model_name'))}",
        f"  reasoning_effort: {_yaml_scalar(payload.get('reasoning_effort'))}",
        f"  request_count: {_yaml_scalar(payload.get('request_count'))}",
        f"  content_sha256: {_yaml_scalar(payload.get('content_sha256'))}",
        "  safety_policy:",
        f"    outputs_truth_status: {_yaml_scalar((payload.get('safety_policy') or {}).get('outputs_truth_status'))}",
        f"    adam_review_required: {_yaml_scalar((payload.get('safety_policy') or {}).get('adam_review_required'))}",
        f"    fine_tuning_api_calls_allowed: {_yaml_scalar((payload.get('safety_policy') or {}).get('fine_tuning_api_calls_allowed'))}",
        "  requests:",
    ]
    for request in payload.get("requests", []):
        safety = request.get("safety_checks") if isinstance(request.get("safety_checks"), dict) else {}
        lines.extend(
            [
                f"    - sequence_number: {_yaml_scalar(request.get('sequence_number'))}",
                f"      task_human_id: {_yaml_scalar(request.get('task_human_id'))}",
                f"      voice_mode: {_yaml_scalar(request.get('voice_mode'))}",
                f"      artifact_mode: {_yaml_scalar(request.get('artifact_mode'))}",
                f"      prompt: {_yaml_scalar(request.get('prompt'))}",
                f"      request_body_sha256: {_yaml_scalar(request.get('request_body_sha256'))}",
                f"      reference_example_count: {_yaml_scalar(request.get('reference_example_count'))}",
                "      safety_checks:",
                f"        no_live_model_call: {_yaml_scalar(safety.get('no_live_model_call'))}",
                f"        store_false: {_yaml_scalar(safety.get('store_false'))}",
                "        held_out_answer_excluded_from_request: "
                + _yaml_scalar(safety.get("held_out_answer_excluded_from_request")),
                "        rejected_response_excluded_from_request: "
                + _yaml_scalar(safety.get("rejected_response_excluded_from_request")),
                "      request_body_json: |-",
                _indent_block(str(request.get("request_body_json") or ""), 8),
            ]
        )
    return "\n".join(lines).rstrip() + "\n"


def compile_demo_generation_request_preview(
    *,
    session: Session,
    app_settings: Settings,
    limit: int = 5,
) -> Dict[str, Any]:
    safe_limit = max(1, min(limit, 20))
    blockers = generation_blockers(app_settings)
    held_out = held_out_prompts(session, limit=safe_limit, include_private_text_for_checks=True)
    held_out_task_ids = {str(item["task_id"]) for item in held_out}
    reference_pack = compile_prompt_pair_reference_pack(session=session, sample_limit=200)
    requests = [
        _request_preview_item(
            session=session,
            item=item,
            app_settings=app_settings,
            sequence_number=index,
            exclude_reference_task_ids=held_out_task_ids,
        )
        for index, item in enumerate(held_out, start=1)
    ]
    payload: Dict[str, Any] = {
        "preview_type": "charles_voice_model_demo_generation_request_preview",
        "review_policy": "dry_run_only_no_live_model_call_no_generation_created",
        "does_not_mutate_state": True,
        "no_live_model_call": True,
        "no_generation_created": True,
        "does_not_promote_to_training_export": True,
        "api": "responses",
        "model_name": app_settings.text_generation_model,
        "reasoning_effort": app_settings.text_generation_reasoning_effort,
        "store": False,
        "max_output_tokens": 1800,
        "live_generation_ready": not blockers,
        "live_generation_blockers": blockers,
        "credential_requirements": text_generation_credential_requirements(app_settings),
        "reference_pack_content_sha256": reference_pack["content_sha256"],
        "reference_pack_sample_count": reference_pack["sample_count"],
        "reference_pack_ready_for_generation_context": reference_pack["ready_for_generation_context"],
        "request_count": len(requests),
        "requests": requests,
        "safety_policy": demo_safety_policy(),
    }
    payload["content_sha256"] = stable_hash(
        {
            key: value
            for key, value in payload.items()
            if key not in {"content_sha256", "export_preview_yaml", "export_preview_sha256"}
        }
    )
    payload["export_preview_yaml"] = demo_generation_request_preview_yaml(payload)
    payload["export_preview_sha256"] = content_hash(payload["export_preview_yaml"])
    return payload
