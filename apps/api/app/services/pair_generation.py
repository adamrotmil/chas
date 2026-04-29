from __future__ import annotations

import json
import re
import hashlib
from collections import Counter
from typing import Any, Dict, List, Optional

import yaml
from sqlmodel import Session, select

from app.config import Settings, settings
from app.models import ContextPack, Generation, PromptSpec, Segment, SourceSpanAnnotation, Task
from app.services.model_generation import live_text_generation_ready
from app.services.pair_export import DEFAULT_SYSTEM_PROMPT, NATURAL_SYSTEM_PROMPT, compile_pair_export
from app.services.prompt_pair_voice_modes import classify_prompt_pair_voice_mode


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


def _source_title(session: Session, task: Task) -> str:
    for key in ["source_filename", "source_title", "asset_title", "title", "segment_title"]:
        value = _string(task.input_payload.get(key))
        if value:
            return value
    segment = session.get(Segment, task.target_id) if task.target_type == "segment" else None
    return segment.title if segment and segment.title else task.human_id


def _chunks_for_task(session: Session, task: Task, decisions: Dict[str, Any]) -> List[Segment]:
    chunk_ids = (
        _string_list(decisions.get("source_chunks_to_use"))
        or _string_list(decisions.get("selected_chunk_ids"))
        or _string_list(task.input_payload.get("pairing_ready_chunk_ids"))
        or _string_list(task.input_payload.get("selected_chunk_ids"))
    )
    if chunk_ids:
        chunks = session.exec(select(Segment).where(Segment.id.in_(chunk_ids))).all()
        by_id = {chunk.id: chunk for chunk in chunks}
        return [by_id[chunk_id] for chunk_id in chunk_ids if chunk_id in by_id]

    segment = session.get(Segment, task.target_id) if task.target_type == "segment" else None
    asset_id = _string(task.input_payload.get("asset_id")) or (segment.asset_id if segment else "")
    if asset_id:
        chunks = session.exec(
            select(Segment)
            .where(Segment.asset_id == asset_id)
            .where(Segment.segment_type == "text_chunk")
            .order_by(Segment.created_at.asc())
        ).all()
        if chunks:
            return chunks
    return [segment] if segment else []


def source_text_for_pair_generation(session: Session, task: Task, decisions: Dict[str, Any]) -> str:
    decision_text = _string(decisions.get("source_text"))
    if decision_text:
        return decision_text
    chunks = _chunks_for_task(session, task, decisions)
    text = "\n\n".join(chunk.text_content or "" for chunk in chunks if chunk.text_content).strip()
    if text:
        return text
    return (
        _string(task.input_payload.get("preview_text"))
        or _string(task.input_payload.get("source_excerpt"))
        or _string(task.input_payload.get("text"))
    )


def _message_content(messages: List[Dict[str, Any]], role: str) -> str:
    for message in messages:
        if message.get("role") == role and isinstance(message.get("content"), str):
            return message["content"]
    return ""


def _pairs_from_messages(item: Dict[str, Any], index: int) -> List[Dict[str, Any]]:
    raw_messages = item.get("messages")
    if not isinstance(raw_messages, list):
        return []
    messages = [message for message in raw_messages if isinstance(message, dict)]
    system_prompt = _message_content(messages, "system") or DEFAULT_SYSTEM_PROMPT
    pairs: List[Dict[str, Any]] = []
    current_user = ""
    turn = 0
    for message in messages:
        role = message.get("role")
        content = message.get("content")
        if not isinstance(content, str) or not content.strip():
            continue
        if role == "user":
            current_user = content.strip()
        elif role == "assistant" and current_user:
            turn += 1
            voice_mode = classify_prompt_pair_voice_mode(
                prompt=current_user,
                response=content,
                context=_string(item.get("context")),
                current_voice_mode=_string(item.get("voice_mode"), "father_to_adam"),
            )
            pairs.append(
                {
                    "artifact_mode": "sft",
                    "system_prompt": system_prompt,
                    "prompt": current_user,
                    "content": content.strip(),
                    "voice_mode": voice_mode,
                    "synthetic": item.get("synthetic", True),
                    "context": _string(item.get("context")),
                    "source_item_index": index,
                    "source_turn_index": turn,
                    "pair_generation_strategy": "structured_yaml_messages",
                }
            )
            current_user = ""
    return pairs


def _pairs_from_dpo(item: Dict[str, Any], index: int) -> List[Dict[str, Any]]:
    prompt = _string(item.get("prompt"))
    chosen = _string(item.get("chosen"))
    rejected = _string(item.get("rejected"))
    if not prompt or not chosen or not rejected:
        return []
    return [
        {
            "artifact_mode": "dpo",
            "system_prompt": _string(item.get("system"), DEFAULT_SYSTEM_PROMPT),
            "prompt": prompt,
            "chosen": chosen,
            "rejected": rejected,
            "voice_mode": classify_prompt_pair_voice_mode(
                prompt=prompt,
                response=chosen,
                context=_string(item.get("context")),
                current_voice_mode=_string(item.get("voice_mode"), "father_to_adam"),
            ),
            "synthetic": item.get("synthetic", True),
            "context": _string(item.get("context")),
            "source_item_index": index,
            "pair_generation_strategy": "structured_yaml_dpo",
        }
    ]


def parse_prompt_pairs_from_yaml(source_text: str, *, limit: int = 500) -> List[Dict[str, Any]]:
    try:
        parsed = yaml.safe_load(source_text)
    except yaml.YAMLError:
        return []
    if isinstance(parsed, dict):
        if isinstance(parsed.get("examples"), list):
            items = parsed["examples"]
        elif isinstance(parsed.get("items"), list):
            items = parsed["items"]
        else:
            items = [parsed]
    elif isinstance(parsed, list):
        items = parsed
    else:
        return []

    pairs: List[Dict[str, Any]] = []
    for index, item in enumerate(items, start=1):
        if not isinstance(item, dict):
            continue
        pairs.extend(_pairs_from_messages(item, index))
        pairs.extend(_pairs_from_dpo(item, index))
        if len(pairs) >= limit:
            break
    return pairs[:limit]


def _pairs_from_structured_chunk_metadata(
    session: Session,
    task: Task,
    decisions: Dict[str, Any],
    *,
    limit: int = 500,
) -> List[Dict[str, Any]]:
    chunks = _chunks_for_task(session, task, decisions)
    pairs: List[Dict[str, Any]] = []
    for index, chunk in enumerate(chunks, start=1):
        raw_messages = (chunk.metadata_json or {}).get("structured_messages")
        if not isinstance(raw_messages, list):
            continue
        messages = [message for message in raw_messages if isinstance(message, dict)]
        chunk_pairs = _pairs_from_messages(
            {
                "messages": messages,
                "voice_mode": _string((chunk.metadata_json or {}).get("voice_mode"))
                or _string(decisions.get("voice_mode"), "father_to_adam"),
                "synthetic": decisions.get("synthetic", True),
                "context": _string((chunk.metadata_json or {}).get("context")) or _string(decisions.get("context")),
            },
            index,
        )
        for pair in chunk_pairs:
            pair["source_segment_id"] = chunk.id
            pair["source_chunk_index"] = (chunk.metadata_json or {}).get("chunk_index") or chunk.locator.get("chunk_index")
            pair["source_prompt_pair_example_index"] = (chunk.metadata_json or {}).get("prompt_pair_example_index")
            pair["source_excerpt"] = chunk.text_content
            pair["pair_generation_strategy"] = "structured_chunk_metadata"
            pairs.append(pair)
            if len(pairs) >= limit:
                return pairs
    return pairs


def _natural_section_body(text: str) -> str:
    lines = text.strip().splitlines()
    if len(lines) <= 1:
        return text.strip()
    heading = lines[0].strip()
    if heading.endswith(":"):
        return "\n".join(lines[1:]).strip() or text.strip()
    return text.strip()


def _prompt_from_natural_section(text: str, heading: str) -> str:
    body = _natural_section_body(text)
    body_first_line = next((line.strip() for line in body.splitlines() if line.strip()), "")
    heading_text = heading.strip().rstrip(":").strip()
    heading_lower = heading_text.lower()
    greeting = re.match(r"^(?:hi|dear)\s+([^,\n!.?]+)", body_first_line, flags=re.IGNORECASE)
    if heading_lower.startswith(("email", "letter", "message")) and greeting:
        return f"What were you writing to {greeting.group(1).strip()} about?"
    if body_first_line.endswith("?"):
        return body_first_line
    if heading_lower.startswith(("memoir", "story", "scene", "fragment")) and body_first_line:
        return f"Tell me about {body_first_line.rstrip('.!?')}."
    if heading_lower.startswith("note"):
        return "What were you trying to say in this note?"
    if heading_text:
        return f"Tell me about {heading_text}."
    return "Tell me about this."


def _pairs_from_natural_section_chunks(
    session: Session,
    task: Task,
    decisions: Dict[str, Any],
    *,
    limit: int = 500,
) -> List[Dict[str, Any]]:
    pairs: List[Dict[str, Any]] = []
    chunks = _chunks_for_task(session, task, decisions)
    for index, chunk in enumerate(chunks, start=1):
        metadata = chunk.metadata_json or {}
        locator = chunk.locator or {}
        if locator.get("kind") != "natural_section" and metadata.get("chunking_strategy") != "natural_section":
            continue
        section_text = (chunk.text_content or "").strip()
        if not section_text:
            continue
        heading = section_text.split("\n", 1)[0].strip()
        review_hint = _string(metadata.get("section_review_hint"))
        context_parts = [
            _string(decisions.get("context")),
            f"Natural source section: {heading.rstrip(':')}.",
            f"section_review_hint: {review_hint}." if review_hint else "",
        ]
        pairs.append(
            {
                "artifact_mode": "sft",
                "system_prompt": NATURAL_SYSTEM_PROMPT,
                "prompt": _prompt_from_natural_section(section_text, heading),
                "content": _natural_section_body(section_text),
                "voice_mode": _string(decisions.get("voice_mode"), "father_to_adam"),
                "synthetic": decisions.get("synthetic", True),
                "context": "\n".join(part for part in context_parts if part.strip()),
                "source_segment_id": chunk.id,
                "source_chunk_index": metadata.get("chunk_index") or locator.get("chunk_index") or index,
                "source_excerpt": section_text,
                "source_item_index": index,
                "pair_generation_strategy": "natural_section",
            }
        )
        if len(pairs) >= limit:
            return pairs
    return pairs


def _json_from_text(text: str) -> Any:
    cleaned = text.strip()
    fenced = re.search(r"```(?:json)?\s*(.*?)```", cleaned, flags=re.DOTALL | re.IGNORECASE)
    if fenced:
        cleaned = fenced.group(1).strip()
    return json.loads(cleaned)


def _llm_pair_generation(
    *,
    source_text: str,
    source_title: str,
    decisions: Dict[str, Any],
    app_settings: Settings = settings,
) -> List[Dict[str, Any]]:
    if not live_text_generation_ready(app_settings):
        return []
    try:
        from openai import OpenAI

        client = OpenAI(
            api_key=app_settings.openai_api_key,
            project=app_settings.openai_project_id or None,
            timeout=240,
        )
        response = client.responses.create(
            model=app_settings.text_generation_model,
            reasoning={"effort": app_settings.text_generation_reasoning_effort},
            input=[
                {
                    "role": "developer",
                    "content": (
                        "You segment source text into high-quality CharlesOps prompt/response examples for Adam to review. "
                        "Return only JSON: an array of objects. Each object must have artifact_mode='sft', prompt, content, "
                        "voice_mode, synthetic, and context. Use source spans and coding if supplied. Do not invent facts; "
                        "when in doubt produce fewer, cleaner complete pairs."
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "source_title": source_title,
                            "source_text": source_text[:50000],
                            "source_spans": decisions.get("source_spans", []),
                            "requested_voice_mode": decisions.get("voice_mode"),
                            "context": decisions.get("context") or decisions.get("adam_context_note"),
                        },
                        ensure_ascii=False,
                    ),
                },
            ],
            max_output_tokens=12000,
            store=False,
        )
        raw = _string(getattr(response, "output_text", None))
        parsed = _json_from_text(raw)
        pairs = [item for item in parsed if isinstance(item, dict)] if isinstance(parsed, list) else []
        for pair in pairs:
            pair.setdefault("pair_generation_strategy", "live_model_pair_generation")
        return pairs
    except Exception:
        return []


def _pairs_from_spans(decisions: Dict[str, Any]) -> List[Dict[str, Any]]:
    raw_spans = decisions.get("source_spans")
    if not isinstance(raw_spans, list):
        return []
    spans = [span for span in raw_spans if isinstance(span, dict)]
    prompts = [span for span in spans if _string(span.get("span_type")).lower() == "prompt"]
    responses = [span for span in spans if _string(span.get("span_type")).lower() == "response"]
    pairs: List[Dict[str, Any]] = []
    for prompt_span, response_span in zip(prompts, responses):
        prompt = _string(prompt_span.get("text")) or _string(prompt_span.get("selected_text"))
        content = _string(response_span.get("text")) or _string(response_span.get("selected_text"))
        if prompt and content:
            context_parts = [_string(decisions.get("context"))]
            for label, span in [("prompt", prompt_span), ("response", response_span)]:
                speaker = _string(span.get("speaker"))
                code = _string(span.get("code"))
                notes = _string(span.get("notes"))
                if speaker or code or notes:
                    context_parts.append(
                        "; ".join(
                            part
                            for part in [
                                f"{label}_speaker: {speaker}" if speaker else "",
                                f"{label}_code: {code}" if code else "",
                                f"{label}_notes: {notes}" if notes else "",
                            ]
                            if part
                        )
                    )
            pairs.append(
                {
                    "artifact_mode": "sft",
                    "system_prompt": NATURAL_SYSTEM_PROMPT,
                    "prompt": prompt,
                    "content": content,
                    "voice_mode": _string(response_span.get("voice_mode")) or _string(decisions.get("voice_mode"), "father_to_adam"),
                    "synthetic": decisions.get("synthetic", True),
                    "context": "\n".join(part for part in context_parts if part.strip()),
                    "pair_generation_strategy": "human_source_spans",
                }
            )
    return pairs


def _fallback_pair(source_text: str, source_title: str, decisions: Dict[str, Any]) -> List[Dict[str, Any]]:
    if not source_text.strip():
        return []
    first_line = next((line.strip() for line in source_text.splitlines() if line.strip()), "")
    prompt = _string(decisions.get("prompt"))
    if not prompt and first_line.endswith("?"):
        prompt = first_line
    if not prompt and first_line:
        prompt = f"Tell me about {first_line[:120].rstrip('.!?')}."
    if not prompt:
        prompt = "What should this source become as a Charles prompt pair?"
    return [
        {
            "artifact_mode": "sft",
            "system_prompt": NATURAL_SYSTEM_PROMPT,
            "prompt": prompt,
            "content": source_text.strip()[:6000],
            "voice_mode": _string(decisions.get("voice_mode"), "father_to_adam"),
            "synthetic": decisions.get("synthetic", True),
            "context": _string(decisions.get("context"))
            or "Fallback pair from reviewed source text; Adam should edit before export.",
            "pair_generation_strategy": "deterministic_fallback_source_text",
        }
    ]


PAIR_GENERATION_PROMPT_INSTRUCTIONS_VERSION = "charlesops_source_review_pair_generation_v1"


def _source_text_hash(source_text: str) -> Optional[str]:
    source_text_normalized = source_text.strip()
    if not source_text_normalized:
        return None
    return hashlib.sha256(source_text_normalized.encode("utf-8")).hexdigest()


def _stable_hash(payload: Dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, default=str, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _pair_generation_metadata(
    *,
    source_text: str,
    source_title: str,
    decisions: Dict[str, Any],
    raw_pair: Dict[str, Any],
    compiled: Dict[str, Any],
    app_settings: Settings = settings,
) -> Dict[str, Any]:
    source_text_normalized = source_text.strip()
    live_ready = live_text_generation_ready(app_settings)
    strategy = _string(raw_pair.get("pair_generation_strategy"), "unknown")
    live_model_call = strategy == "live_model_pair_generation" and live_ready
    return {
        "prompt_instructions_version": PAIR_GENERATION_PROMPT_INSTRUCTIONS_VERSION,
        "strategy": strategy,
        "model_name": app_settings.text_generation_model,
        "reasoning_effort": app_settings.text_generation_reasoning_effort,
        "live_model_call": live_model_call,
        "no_live_model_call": not live_model_call,
        "live_generation_ready": live_ready,
        "source_title": source_title,
        "source_text_sha256": _source_text_hash(source_text),
        "source_text_char_count": len(source_text_normalized),
        "source_text_preview": source_text_normalized[:1200],
        "source_spans_supplied": isinstance(decisions.get("source_spans"), list) and bool(decisions.get("source_spans")),
        "voice_mode": compiled.get("voice_mode"),
        "artifact_mode": compiled.get("artifact_mode"),
        "truth_status": compiled.get("truth_status"),
        "candidate_requires_adam_review": True,
    }


def _pairs_for_review_source(
    session: Session,
    task: Task,
    decisions: Dict[str, Any],
    *,
    allow_live_model: bool = True,
) -> List[Dict[str, Any]]:
    source_text = source_text_for_pair_generation(session, task, decisions)
    source_title = _source_title(session, task)
    pairs = _pairs_from_structured_chunk_metadata(session, task, decisions)
    if pairs:
        return pairs
    pairs = parse_prompt_pairs_from_yaml(source_text)
    if pairs:
        return pairs
    pairs = _pairs_from_spans(decisions)
    if pairs:
        return pairs
    if allow_live_model:
        pairs = _llm_pair_generation(source_text=source_text, source_title=source_title, decisions=decisions)
        if pairs:
            return pairs
    pairs = _pairs_from_natural_section_chunks(session, task, decisions)
    if pairs:
        return pairs
    return _fallback_pair(source_text, source_title, decisions)


def _generation_strategy_label(strategy: str) -> str:
    labels = {
        "structured_chunk_metadata": "Structured prompt-pair chunks",
        "structured_yaml_messages": "YAML SFT messages",
        "structured_yaml_dpo": "YAML DPO rows",
        "human_source_spans": "Annotated Prompt/Response spans",
        "live_model_pair_generation": "Live LLM pair generation",
        "natural_section": "Natural source sections",
        "deterministic_fallback_source_text": "Fallback source-text pair",
    }
    return labels.get(strategy, strategy.replace("_", " ").title())


def _preview_hold_reason(compiled: Dict[str, Any]) -> str:
    if compiled["artifact_mode"] == "sft" and not _string(compiled.get("content")):
        return "empty_sft_content"
    if compiled["artifact_mode"] == "dpo" and (
        not _string(compiled.get("chosen")) or not _string(compiled.get("rejected"))
    ):
        return "empty_dpo_chosen_or_rejected"
    return ""


def preview_make_gold_tasks_from_review(
    *,
    session: Session,
    task: Task,
    decisions: Dict[str, Any],
) -> Dict[str, Any]:
    source_text = source_text_for_pair_generation(session, task, decisions)
    source_title = _source_title(session, task)
    pairs = _pairs_for_review_source(session, task, decisions, allow_live_model=False)
    source_sections = _source_sections_for_receipt(session, task, decisions)
    strategy_counts = Counter(_string(pair.get("pair_generation_strategy"), "unknown") for pair in pairs)
    source_spans = decisions.get("source_spans") if isinstance(decisions.get("source_spans"), list) else []
    creatable_pairs: List[Dict[str, Any]] = []
    held_pairs: List[Dict[str, Any]] = []
    fallback_truth_status = _string(task.input_payload.get("truth_status"), "archival_source")

    for index, raw_pair in enumerate(pairs, start=1):
        pair = {
            "voice_mode": _string(decisions.get("voice_mode"), "father_to_adam"),
            "synthetic": True,
            "context": _string(decisions.get("context")),
            **raw_pair,
        }
        compiled = compile_pair_export(pair, fallback_truth_status=fallback_truth_status)
        strategy = _string(raw_pair.get("pair_generation_strategy"), "unknown")
        hold_reason = _preview_hold_reason(compiled)
        preview_item = {
            "pair_index": index,
            "artifact_mode": compiled["artifact_mode"],
            "voice_mode": compiled["voice_mode"],
            "truth_status": compiled["truth_status"],
            "strategy": strategy,
            "strategy_label": _generation_strategy_label(strategy),
            "prompt_preview": compiled["prompt"][:240],
            "content_preview": _string(compiled.get("content"))[:240],
            "chosen_preview": _string(compiled.get("chosen"))[:240],
            "rejected_preview": _string(compiled.get("rejected"))[:240],
            "source_segment_id": raw_pair.get("source_segment_id"),
            "source_chunk_index": raw_pair.get("source_chunk_index"),
            "source_prompt_pair_example_index": raw_pair.get("source_prompt_pair_example_index"),
        }
        if hold_reason:
            held_pairs.append({**preview_item, "reason": hold_reason})
        else:
            creatable_pairs.append(preview_item)

    creatable_source_segment_ids = {
        str(pair.get("source_segment_id"))
        for pair in creatable_pairs
        if pair.get("source_segment_id")
    }
    held_source_sections = [
        {
            **section,
            "reason": "no_prompt_pair_created_from_this_section",
        }
        for section in source_sections
        if section["source_segment_id"] not in creatable_source_segment_ids
    ]
    primary_strategy = next(iter(strategy_counts.keys()), "none")
    source_text_normalized = source_text.strip()
    preview_payload = {
        "preview_type": "source_review_generate_pairs_preview",
        "review_policy": "dry_run_only_no_tasks_created_no_raw_source_mutation",
        "does_not_mutate_state": True,
        "no_live_model_call": True,
        "prompt_instructions_version": PAIR_GENERATION_PROMPT_INSTRUCTIONS_VERSION,
        "source_task_id": task.id,
        "source_task_human_id": task.human_id,
        "source_title": source_title,
        "source_text_sha256": _source_text_hash(source_text),
        "source_text_char_count": len(source_text_normalized),
        "source_text_preview": source_text_normalized[:600],
        "source_spans_supplied": bool(source_spans),
        "source_span_draft_count": len(source_spans),
        "source_section_count": len(source_sections),
        "candidate_pair_count": len(pairs),
        "projected_created_pair_count": len(creatable_pairs),
        "projected_held_pair_count": len(held_pairs),
        "projected_held_source_section_count": len(held_source_sections),
        "strategy_counts": dict(sorted(strategy_counts.items())),
        "primary_strategy": primary_strategy,
        "primary_strategy_label": _generation_strategy_label(primary_strategy),
        "next_queue": "prompt_pairs_needing_gold_edits" if creatable_pairs else None,
        "created_pairs_preview": creatable_pairs[:10],
        "held_pairs_preview": held_pairs[:10],
        "held_source_sections_preview": held_source_sections[:10],
        "completion_signal": (
            "generate_pairs_creates_singleton_prompt_pair_tickets"
            if creatable_pairs
            else "generate_pairs_has_no_creatable_prompt_pairs"
        ),
        "safety_boundaries": [
            "Preview does not create prompt specs, generations, context packs, annotations, or tasks.",
            "Submit still creates candidate Prompt Pair tickets requiring Adam gold review.",
            "Raw imported source files remain unchanged.",
        ],
    }
    preview_payload["content_sha256"] = _stable_hash(preview_payload)
    return preview_payload


def _source_sections_for_receipt(session: Session, task: Task, decisions: Dict[str, Any]) -> List[Dict[str, Any]]:
    sections: List[Dict[str, Any]] = []
    for fallback_index, chunk in enumerate(_chunks_for_task(session, task, decisions), start=1):
        metadata = chunk.metadata_json or {}
        locator = chunk.locator or {}
        is_reviewable_section = bool(
            locator.get("kind")
            in {
                "natural_section",
                "prompt_pair_example",
            }
            or metadata.get("chunking_strategy")
            in {
                "natural_section",
                "prompt_pair_yaml",
            }
            or metadata.get("structured_messages")
        )
        if not is_reviewable_section:
            continue
        sections.append(
            {
                "source_segment_id": chunk.id,
                "title": chunk.title or chunk.human_id,
                "chunk_index": metadata.get("chunk_index") or locator.get("chunk_index") or fallback_index,
                "chunking_strategy": metadata.get("chunking_strategy") or locator.get("kind") or "unknown",
            }
        )
    return sections


def _pair_generation_run_receipt(
    *,
    session: Session,
    task: Task,
    decisions: Dict[str, Any],
    annotation_id: str,
    source_text: str,
    source_title: str,
    source_span_ids: List[str],
    pairs: List[Dict[str, Any]],
    created_pairs: List[Dict[str, Any]],
    held_pairs: List[Dict[str, Any]],
) -> Dict[str, Any]:
    source_sections = _source_sections_for_receipt(session, task, decisions)
    created_source_segment_ids = {
        str(pair.get("source_segment_id"))
        for pair in created_pairs
        if pair.get("source_segment_id")
    }
    held_source_sections = [
        {
            **section,
            "reason": "no_prompt_pair_created_from_this_section",
        }
        for section in source_sections
        if section["source_segment_id"] not in created_source_segment_ids
    ]
    created_strategy_counts = Counter(_string(pair.get("strategy"), "unknown") for pair in created_pairs)
    candidate_strategy_counts = Counter(_string(pair.get("pair_generation_strategy"), "unknown") for pair in pairs)
    live_model_call_count = len(
        [
            pair
            for pair in created_pairs
            if (pair.get("pair_generation_metadata") or {}).get("live_model_call") is True
        ]
    )
    source_text_normalized = source_text.strip()
    return {
        "run_type": "source_review_generate_pairs",
        "prompt_instructions_version": PAIR_GENERATION_PROMPT_INSTRUCTIONS_VERSION,
        "source_review_annotation_id": annotation_id,
        "source_task_id": task.id,
        "source_task_human_id": task.human_id,
        "source_title": source_title,
        "source_text_sha256": _source_text_hash(source_text),
        "source_text_char_count": len(source_text_normalized),
        "source_text_preview": source_text_normalized[:600],
        "source_span_annotation_ids": source_span_ids,
        "source_section_count": len(source_sections),
        "candidate_pair_count": len(pairs),
        "created_pair_count": len(created_pairs),
        "held_pair_count": len(held_pairs),
        "held_source_section_count": len(held_source_sections),
        "strategy_counts": dict(sorted(created_strategy_counts.items())),
        "candidate_strategy_counts": dict(sorted(candidate_strategy_counts.items())),
        "live_model_call_count": live_model_call_count,
        "no_live_model_call": live_model_call_count == 0,
        "created_pairs": created_pairs[:50],
        "held_pairs": held_pairs[:50],
        "held_source_sections": held_source_sections[:50],
        "next_queue": "prompt_pairs_needing_gold_edits" if created_pairs else None,
    }


def create_make_gold_tasks_from_review(
    *,
    session: Session,
    task: Task,
    decisions: Dict[str, Any],
    annotation_id: str,
    source_span_annotations: Optional[List[SourceSpanAnnotation]] = None,
) -> Dict[str, Any]:
    pair_decision = _string(decisions.get("generate_pairs_on_submit")) or _string(decisions.get("prompt_pair_decision"))
    if pair_decision and pair_decision not in {"yes", "generate", "high", "medium"}:
        return {}

    pairs = _pairs_for_review_source(session, task, decisions)
    source_title = _source_title(session, task)
    source_text = source_text_for_pair_generation(session, task, decisions)
    source_span_ids = [span.id for span in source_span_annotations or []]
    make_gold_task_ids: List[str] = []
    prompt_spec_ids: List[str] = []
    context_pack_ids: List[str] = []
    generation_ids: List[str] = []
    created_pairs: List[Dict[str, Any]] = []
    held_pairs: List[Dict[str, Any]] = []

    fallback_truth_status = _string(task.input_payload.get("truth_status"), "archival_source")
    for index, raw_pair in enumerate(pairs, start=1):
        pair = {
            "voice_mode": _string(decisions.get("voice_mode"), "father_to_adam"),
            "synthetic": True,
            "context": _string(decisions.get("context")),
            **raw_pair,
        }
        compiled = compile_pair_export(pair, fallback_truth_status=fallback_truth_status)
        if compiled["artifact_mode"] == "sft" and not _string(compiled.get("content")):
            held_pairs.append(
                {
                    "pair_index": index,
                    "artifact_mode": compiled["artifact_mode"],
                    "strategy": _string(raw_pair.get("pair_generation_strategy"), "unknown"),
                    "source_segment_id": raw_pair.get("source_segment_id"),
                    "source_chunk_index": raw_pair.get("source_chunk_index"),
                    "reason": "empty_sft_content",
                }
            )
            continue
        if compiled["artifact_mode"] == "dpo" and (
            not _string(compiled.get("chosen")) or not _string(compiled.get("rejected"))
        ):
            held_pairs.append(
                {
                    "pair_index": index,
                    "artifact_mode": compiled["artifact_mode"],
                    "strategy": _string(raw_pair.get("pair_generation_strategy"), "unknown"),
                    "source_segment_id": raw_pair.get("source_segment_id"),
                    "source_chunk_index": raw_pair.get("source_chunk_index"),
                    "reason": "empty_dpo_chosen_or_rejected",
                }
            )
            continue
        pair_source_excerpt = _string(raw_pair.get("source_excerpt")) or source_text[:3000]
        generation_metadata = _pair_generation_metadata(
            source_text=source_text,
            source_title=source_title,
            decisions=decisions,
            raw_pair=raw_pair,
            compiled=compiled,
        )

        prompt_spec = PromptSpec(
            human_id=_human_id("PROMPT_REVIEW_PAIR", _count(session, PromptSpec)),
            prompt_type=f"{compiled['artifact_mode']}_review_pair",
            voice_mode=compiled["voice_mode"],
            truth_mode=compiled["truth_status"],
            prompt_text=compiled["prompt"],
            success_criteria={
                "must_preserve_truth_boundary": True,
                "must_not_claim_archival_quote": compiled["synthetic"],
                "artifact_mode": compiled["artifact_mode"],
            },
            metadata_json={
                "system_prompt": compiled["system_prompt"],
                "source_review_annotation_id": annotation_id,
                "source_task_id": task.id,
                "source_title": source_title,
                "source_span_annotation_ids": source_span_ids,
                "export_preview_yaml": compiled["yaml_preview"],
                "pair_index": index,
                "source_item_index": raw_pair.get("source_item_index"),
                "source_turn_index": raw_pair.get("source_turn_index"),
                "source_segment_id": raw_pair.get("source_segment_id"),
                "source_chunk_index": raw_pair.get("source_chunk_index"),
                "source_prompt_pair_example_index": raw_pair.get("source_prompt_pair_example_index"),
                "pair_generation_metadata": generation_metadata,
            },
        )
        session.add(prompt_spec)
        session.flush()

        context_pack = ContextPack(
            human_id=_human_id("CTX_REVIEW_PAIR", _count(session, ContextPack)),
            user_intent="source_review_pair_generation",
            requested_voice_mode=compiled["voice_mode"],
            truth_mode=compiled["truth_status"],
            allowed_facts=[pair_source_excerpt[:1800]] if pair_source_excerpt else [],
            boundaries_snapshot={
                "source_review_annotation_id": annotation_id,
                "source_task_id": task.id,
                "source_span_annotation_ids": source_span_ids,
                "source_title": source_title,
                "requires_boundary_review_before_export": True,
            },
            style_guidance={
                "system_prompt": compiled["system_prompt"],
                "voice_mode": compiled["voice_mode"],
                "artifact_mode": compiled["artifact_mode"],
                "context": compiled.get("context"),
            },
        )
        session.add(context_pack)
        session.flush()

        generation_id = None
        if compiled["artifact_mode"] == "dpo" and _string(compiled.get("rejected")):
            generation = Generation(
                prompt_spec_id=prompt_spec.id,
                context_pack_id=context_pack.id,
                model_name="imported_rejected_response",
                model_parameters={
                    "source": "source_review_pair_generation",
                    "artifact_mode": "dpo",
                    "source_review_annotation_id": annotation_id,
                },
                output_text=compiled["rejected"],
            )
            session.add(generation)
            session.flush()
            generation_id = generation.id
            generation_ids.append(generation.id)

        input_payload = {
            "artifact_mode": compiled["artifact_mode"],
            "voice_mode": compiled["voice_mode"],
            "synthetic": compiled["synthetic"],
            "truth_status": compiled["truth_status"],
            "system_prompt": compiled["system_prompt"],
            "prompt": compiled["prompt"],
            "content": compiled.get("content"),
            "chosen": compiled.get("chosen"),
            "rejected": compiled.get("rejected"),
            "context": compiled.get("context"),
            "grounding_asset_id": compiled.get("grounding_asset_id") or _string(task.input_payload.get("asset_id")),
            "export_preview_yaml": compiled["yaml_preview"],
            "prompt_spec_id": prompt_spec.id,
            "context_pack_id": context_pack.id,
            "generation_id": generation_id,
            "source_title": source_title,
            "source_excerpt": pair_source_excerpt[:6000],
            "source_review_annotation_id": annotation_id,
            "source_task_id": task.id,
            "source_span_annotation_ids": source_span_ids,
            "pair_generation_metadata": generation_metadata,
            "candidate_requires_adam_gold_edit": True,
            "pair_index": index,
            "source_segment_id": raw_pair.get("source_segment_id"),
            "source_chunk_index": raw_pair.get("source_chunk_index"),
            "source_prompt_pair_example_index": raw_pair.get("source_prompt_pair_example_index"),
        }
        review_task = Task(
            human_id=_human_id("TASK_MAKE_GOLD", _count(session, Task)),
            task_type="gold_voice_edit",
            target_type="prompt_pair",
            target_id=prompt_spec.id,
            priority=90,
            queue="prompt_pairs_needing_gold_edits",
            reason_created="Source Review generated a prompt/response pair for Adam to make gold.",
            input_payload=input_payload,
            required_decisions=["artifact_mode", "voice_mode", "prompt", "response_rubric"],
            created_by="source_review_pair_generation",
        )
        session.add(review_task)
        session.flush()
        prompt_spec_ids.append(prompt_spec.id)
        context_pack_ids.append(context_pack.id)
        make_gold_task_ids.append(review_task.id)
        created_pairs.append(
            {
                "pair_index": index,
                "task_id": review_task.id,
                "task_human_id": review_task.human_id,
                "prompt_spec_id": prompt_spec.id,
                "context_pack_id": context_pack.id,
                "generation_id": generation_id,
                "artifact_mode": compiled["artifact_mode"],
                "voice_mode": compiled["voice_mode"],
                "truth_status": compiled["truth_status"],
                "strategy": generation_metadata["strategy"],
                "prompt_preview": compiled["prompt"][:240],
                "source_segment_id": raw_pair.get("source_segment_id"),
                "source_chunk_index": raw_pair.get("source_chunk_index"),
                "source_prompt_pair_example_index": raw_pair.get("source_prompt_pair_example_index"),
                "pair_generation_metadata": generation_metadata,
            }
        )

    run_receipt = _pair_generation_run_receipt(
        session=session,
        task=task,
        decisions=decisions,
        annotation_id=annotation_id,
        source_text=source_text,
        source_title=source_title,
        source_span_ids=source_span_ids,
        pairs=pairs,
        created_pairs=created_pairs,
        held_pairs=held_pairs,
    )
    if not make_gold_task_ids:
        return {
            "make_gold_task_ids": [],
            "generated_pair_count": 0,
            "source_span_annotation_ids": source_span_ids,
            "pair_generation_run": run_receipt,
        }
    return {
        "make_gold_task_ids": make_gold_task_ids,
        "prompt_spec_ids": prompt_spec_ids,
        "context_pack_ids": context_pack_ids,
        "generation_ids": generation_ids,
        "generated_pair_count": len(make_gold_task_ids),
        "source_span_annotation_ids": source_span_ids,
        "pair_generation_run": run_receipt,
    }
