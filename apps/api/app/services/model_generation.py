from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from app.config import Settings, settings

TEXT_GENERATION_MAX_OUTPUT_TOKENS = 1800


@dataclass
class TextDraftRequest:
    system_prompt: str
    user_prompt: str
    source_title: str
    source_text: str
    voice_mode: str
    conversation_family: str
    target_response_shape: str
    truth_mode: str
    reference_examples: List[Dict[str, Any]] = field(default_factory=list)
    model_name: Optional[str] = None
    reasoning_effort: Optional[str] = None


@dataclass
class TextDraftResult:
    output_text: str
    generation_status: str
    model_name: str
    model_parameters: Dict[str, Any]
    error: Optional[str] = None


def live_text_generation_ready(app_settings: Settings = settings) -> bool:
    return bool(app_settings.text_generation_live_calls_enabled and app_settings.openai_api_key)


def _clean(value: Any, fallback: str = "") -> str:
    return value if isinstance(value, str) and value.strip() else fallback


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 20].rstrip() + "\n[truncated]"


def scaffold_voice_draft(request: TextDraftRequest) -> TextDraftResult:
    source_hint = " ".join(request.source_text.split())[:220]
    if request.conversation_family in {"verbatim_email_reply", "mundane_text_message"}:
        output = "sounds good...\nlet me know\n\ndad"
    elif source_hint:
        output = f"i remember this...\n{source_hint}\n\nmore there than one thinks.\n\nlove\ndad"
    else:
        output = "i remember this...\nnot sure all the details now.\n\nlove\ndad"
    return TextDraftResult(
        output_text=output,
        generation_status="scaffold_no_model_call",
        model_name="charlesops_scaffold_no_model_call",
        model_parameters={
            "source": "deterministic_scaffold",
            "no_live_model_call": True,
            "conversation_family": request.conversation_family,
            "target_response_shape": request.target_response_shape,
        },
    )


def _format_reference_examples(examples: List[Dict[str, Any]]) -> str:
    formatted: List[str] = []
    for index, example in enumerate(examples[:6], start=1):
        messages = example.get("messages") if isinstance(example, dict) else None
        if not isinstance(messages, list):
            continue
        turns: List[str] = []
        for message in messages:
            if not isinstance(message, dict):
                continue
            role = _clean(message.get("role"))
            content = _clean(message.get("content"))
            if role and content:
                turns.append(f"{role}: {content}")
        if turns:
            formatted.append(f"Example {index}\n" + "\n".join(turns))
    return "\n\n".join(formatted)


def _developer_instructions(request: TextDraftRequest) -> str:
    return (
        "You create one draft response for Adam to review and rewrite. "
        "The target voice is Charles Rotmil, but this is only a model draft, not an archival quote. "
        "Write the response only; do not explain the task, cite metadata, or include labels. "
        "Use the supplied examples as a shape and rhythm reference, not as text to copy. "
        "Keep source truth, Adam memory, and generated connective tissue conceptually distinct. "
        "If source details are sparse, stay modest rather than inventing specific facts."
    )


def _user_input(request: TextDraftRequest) -> str:
    references = _format_reference_examples(request.reference_examples)
    parts = [
        f"Exported system prompt:\n{request.system_prompt}",
        f"Exported user message:\n{request.user_prompt}",
        f"Conversation family:\n{request.conversation_family}",
        f"Voice mode:\n{request.voice_mode}",
        f"Response shape:\n{request.target_response_shape}",
        f"Truth mode:\n{request.truth_mode}",
        f"Source title:\n{request.source_title}",
        "Reviewed grounding source:\n" + _truncate(request.source_text, 6000),
    ]
    if references:
        parts.append("Selected reference prompt pairs:\n" + _truncate(references, 6000))
    parts.append("Now write only the draft assistant response.")
    return "\n\n---\n\n".join(parts)


def build_responses_api_request_body(
    request: TextDraftRequest,
    *,
    model_name: str,
    reasoning_effort: str,
) -> Dict[str, Any]:
    return {
        "model": model_name,
        "reasoning": {"effort": reasoning_effort},
        "input": [
            {"role": "developer", "content": _developer_instructions(request)},
            {"role": "user", "content": _user_input(request)},
        ],
        "max_output_tokens": TEXT_GENERATION_MAX_OUTPUT_TOKENS,
        "store": False,
    }


def generate_text_draft(
    request: TextDraftRequest,
    *,
    no_live_model_call: bool,
    app_settings: Settings = settings,
) -> TextDraftResult:
    model_name = request.model_name or app_settings.text_generation_model
    reasoning_effort = request.reasoning_effort or app_settings.text_generation_reasoning_effort
    if no_live_model_call or not live_text_generation_ready(app_settings):
        return scaffold_voice_draft(request)

    try:
        from openai import OpenAI

        client = OpenAI(
            api_key=app_settings.openai_api_key,
            project=app_settings.openai_project_id or None,
            timeout=180,
        )
        response = client.responses.create(
            **build_responses_api_request_body(
                request,
                model_name=model_name,
                reasoning_effort=reasoning_effort,
            )
        )
        output_text = _clean(getattr(response, "output_text", None))
        if not output_text:
            output_text = scaffold_voice_draft(request).output_text
            status = "live_empty_fallback"
        else:
            status = "live_model_call"
        return TextDraftResult(
            output_text=output_text,
            generation_status=status,
            model_name=model_name,
            model_parameters={
                "api": "responses",
                "reasoning": {"effort": reasoning_effort},
                "store": False,
                "max_output_tokens": TEXT_GENERATION_MAX_OUTPUT_TOKENS,
                "conversation_family": request.conversation_family,
                "target_response_shape": request.target_response_shape,
                "no_live_model_call": False,
            },
        )
    except Exception as exc:  # pragma: no cover - network/provider failures are recorded as metadata.
        fallback = scaffold_voice_draft(request)
        fallback.generation_status = "live_error_fallback"
        fallback.model_name = model_name
        fallback.model_parameters = {
            **fallback.model_parameters,
            "requested_model": model_name,
            "requested_reasoning": {"effort": reasoning_effort},
            "no_live_model_call": False,
            "live_call_error": type(exc).__name__,
        }
        fallback.error = str(exc)
        return fallback
