from __future__ import annotations

from typing import Any, Dict, List, Optional

from sqlmodel import Session, select

from app.models import ContextPack, Generation, PromptSpec, Segment, Task, VoiceReferenceExample
from app.services.model_generation import TextDraftRequest, generate_text_draft
from app.services.prompt_pair_reference_pack import select_prompt_pair_reference_examples


DEFAULT_SYSTEM_PROMPT = "You are Charles Rotmil."
NATURAL_SYSTEM_PROMPT = "You are Charles Rotmil. Write naturally in his voice."

PROMPT_INTENT_FAMILIES = {
    "email_reply_candidate": "verbatim_email_reply",
    "memory_scene_candidate": "source_based_story_recall",
    "factual_archive_answer": "source_based_story_recall",
    "style_eval_case": "adam_prompted_memory",
    "anti_pattern_probe": "adam_prompted_memory",
    "grounded_voice_response": "adam_prompted_memory",
}

TARGET_SHAPE_FAMILIES = {
    "short_email_reply": "verbatim_email_reply",
    "longer_letter": "adam_prompted_memory",
    "memoir_paragraph": "source_based_story_recall",
    "archive_answer": "source_based_story_recall",
    "eval_prompt": "adam_prompted_memory",
    "short_voice_response": "adam_prompted_memory",
}


def _human_id(prefix: str, count: int) -> str:
    return f"{prefix}_{count:06d}"


def _count(session: Session, model: Any) -> int:
    return len(session.exec(select(model)).all()) + 1


def _string(value: Any, fallback: str = "") -> str:
    return value if isinstance(value, str) and value.strip() else fallback


def _bool(value: Any, fallback: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return fallback


def _string_list(value: Any) -> List[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item).strip()]


def _segment_source_text(session: Session, task: Task, decisions: Dict[str, Any]) -> str:
    selected_chunk_ids = _string_list(decisions.get("source_chunks_to_use")) or _string_list(
        decisions.get("selected_chunk_ids")
    ) or _string_list(task.input_payload.get("pairing_ready_chunk_ids")) or _string_list(
        task.input_payload.get("selected_chunk_ids")
    )
    if selected_chunk_ids:
        chunks = session.exec(select(Segment).where(Segment.id.in_(selected_chunk_ids))).all()
        chunks_by_id = {chunk.id: chunk for chunk in chunks}
        text = "\n\n".join(
            chunks_by_id[chunk_id].text_content or ""
            for chunk_id in selected_chunk_ids
            if chunk_id in chunks_by_id and chunks_by_id[chunk_id].text_content
        )
        if text.strip():
            return text.strip()

    segment_id = _string(task.input_payload.get("segment_id")) or task.target_id
    segment = session.get(Segment, segment_id)
    if segment and segment.text_content:
        return segment.text_content.strip()

    return _string(task.input_payload.get("preview_text")) or _string(task.input_payload.get("text"))


def _source_title(session: Session, task: Task) -> str:
    for key in ["source_filename", "asset_title", "title", "segment_title"]:
        value = _string(task.input_payload.get(key))
        if value:
            return value
    segment_id = _string(task.input_payload.get("segment_id")) or task.target_id
    segment = session.get(Segment, segment_id)
    if segment and segment.title:
        return segment.title
    return task.human_id


def _clean_source_title(title: str) -> str:
    cleaned = title.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
    for suffix in [".docx", ".txt", ".md", ".pdf"]:
        if cleaned.lower().endswith(suffix):
            cleaned = cleaned[: -len(suffix)]
    cleaned = cleaned.replace("_", " ").replace("-", " ").strip()
    parts = [part for part in cleaned.split() if not part.isdigit()]
    cleaned = " ".join(parts)
    if len(cleaned) > 70:
        return ""
    generic = {"prompt pair source", "factory source segment", "text preview", "source segment"}
    return "" if cleaned.lower() in generic else cleaned


def _conversation_family(decisions: Dict[str, Any], prompt_intent: str, target_response_shape: str) -> str:
    explicit = _string(decisions.get("conversation_family"))
    if explicit:
        return explicit
    return PROMPT_INTENT_FAMILIES.get(prompt_intent) or TARGET_SHAPE_FAMILIES.get(target_response_shape) or "adam_prompted_memory"


def _system_prompt(decisions: Dict[str, Any], family: str) -> str:
    explicit = _string(decisions.get("system_prompt"))
    if explicit:
        return explicit
    if family in {"source_based_story_recall", "long_literary_source_excerpt"}:
        return NATURAL_SYSTEM_PROMPT
    return DEFAULT_SYSTEM_PROMPT


def _topic_phrase(source_title: str) -> str:
    cleaned = _clean_source_title(source_title)
    if cleaned:
        return cleaned
    return "this memory"


def _natural_prompt(
    decisions: Dict[str, Any],
    *,
    source_title: str,
    prompt_intent: str,
    voice_mode: str,
    target_response_shape: str,
    family: str,
) -> str:
    explicit = _string(decisions.get("prompt_text")) or _string(decisions.get("user_prompt"))
    if explicit:
        return explicit

    topic = _string(decisions.get("prompt_subject")) or _topic_phrase(source_title)
    if family == "verbatim_email_reply":
        return f"Write back about {topic}."
    if family == "mundane_text_message":
        return f"Dad, how's {topic} today?"
    if family == "ps_digression":
        return f"Dad, tell me what's on your mind about {topic}."
    if family == "nb_digression":
        return f"Dad, what do you notice when you think about {topic}?"
    if family == "multi_turn_thread":
        return f"Continue this exchange about {topic}."
    if family == "long_literary_source_excerpt" or target_response_shape == "memoir_paragraph":
        return f"Tell me about {topic}."
    if voice_mode == "logistical_note":
        return f"Dad, what should we do about {topic}?"
    if voice_mode == "photography_reflection":
        return f"Dad, what do you see in {topic}?"
    return f"Hey Dad, tell me about {topic}."


def _reference_examples(decisions: Dict[str, Any], task: Task) -> List[Dict[str, Any]]:
    examples = decisions.get("reference_examples") or task.input_payload.get("reference_examples") or []
    return examples if isinstance(examples, list) else []


def _reference_examples_for_task(session: Session, decisions: Dict[str, Any], task: Task) -> List[Dict[str, Any]]:
    explicit = _reference_examples(decisions, task)
    if explicit:
        return explicit
    chunk_ids = _string_list(task.input_payload.get("pairing_ready_chunk_ids")) or _string_list(
        task.input_payload.get("selected_chunk_ids")
    )
    if chunk_ids:
        examples = session.exec(
            select(VoiceReferenceExample)
            .where(VoiceReferenceExample.source_segment_id.in_(chunk_ids))
            .where(VoiceReferenceExample.status == "active")
            .order_by(VoiceReferenceExample.source_chunk_index.asc())
        ).all()
        chunk_examples = [
            {
                "messages": example.messages,
                "metadata": {
                    "voice_mode": example.voice_mode,
                    "conversation_family": example.conversation_family,
                    "truth_status": example.truth_status,
                    "quality_status": example.quality_status,
                    "source_segment_id": example.source_segment_id,
                },
            }
            for example in examples[:8]
        ]
        if chunk_examples:
            return chunk_examples
    return select_prompt_pair_reference_examples(
        session=session,
        voice_mode=_string(decisions.get("voice_mode")) or _string(task.input_payload.get("voice_mode")),
        conversation_family=_string(decisions.get("conversation_family"))
        or _string(task.input_payload.get("conversation_family")),
        limit=8,
    )


def _boundary_blocks_live_model_call(source_policy: Dict[str, Any], boundary_clearance: str) -> bool:
    return (
        boundary_clearance == "do_not_export"
        or source_policy.get("privacy_clearance") == "do_not_export"
        or source_policy.get("quote_policy") == "do_not_quote_or_export"
    )


def _existing_review_task(session: Session, candidate_task: Task) -> Optional[Task]:
    tasks = session.exec(select(Task).where(Task.task_type == "gold_voice_edit")).all()
    for task in tasks:
        if task.input_payload.get("source_prompt_pair_task_id") == candidate_task.id:
            return task
    return None


def create_prompt_pair_review_task(
    *,
    session: Session,
    candidate_task: Task,
    decisions: Dict[str, Any],
    annotation_id: str,
) -> Dict[str, str]:
    existing = _existing_review_task(session, candidate_task)
    if existing:
        return {"review_task_id": existing.id}

    prompt_intent = _string(decisions.get("prompt_intent"), "grounded_voice_response")
    voice_mode = _string(decisions.get("voice_mode"), "father_to_adam")
    truth_mode = _string(decisions.get("truth_mode"), "adam_expert_reconstruction")
    target_response_shape = _string(decisions.get("target_response_shape"), "short_voice_response")
    source_text = _segment_source_text(session, candidate_task, decisions)
    source_title = _source_title(session, candidate_task)
    conversation_family = _conversation_family(decisions, prompt_intent, target_response_shape)
    system_prompt = _system_prompt(decisions, conversation_family)
    source_policy = {
        "source_use_modes": decisions.get("source_use_modes") or candidate_task.input_payload.get("source_use_modes", []),
        "source_use_mode": decisions.get("source_use_mode") or candidate_task.input_payload.get("source_use_mode"),
        "quote_policy": decisions.get("quote_policy") or candidate_task.input_payload.get("quote_policy"),
        "privacy_clearance": decisions.get("privacy_clearance") or candidate_task.input_payload.get("privacy_clearance"),
        "redaction_instructions": decisions.get("redaction_instructions")
        or candidate_task.input_payload.get("redaction_instructions"),
    }
    prompt_text = _natural_prompt(
        decisions,
        source_title=source_title,
        prompt_intent=prompt_intent,
        voice_mode=voice_mode,
        target_response_shape=target_response_shape,
        family=conversation_family,
    )
    reference_examples = _reference_examples_for_task(session, decisions, candidate_task)
    no_live_model_call = _bool(
        decisions.get("no_live_model_call"),
        _bool(candidate_task.input_payload.get("no_live_model_call"), True),
    )
    boundary_blocks_live_model_call = _boundary_blocks_live_model_call(
        source_policy,
        _string(decisions.get("boundary_clearance_needed"), "review_before_export"),
    )
    effective_no_live_model_call = no_live_model_call or boundary_blocks_live_model_call
    model_draft = _string(decisions.get("model_draft"))
    if model_draft:
        draft_result = None
    else:
        draft_result = generate_text_draft(
            TextDraftRequest(
                system_prompt=system_prompt,
                user_prompt=prompt_text,
                source_title=source_title,
                source_text=source_text,
                voice_mode=voice_mode,
                conversation_family=conversation_family,
                target_response_shape=target_response_shape,
                truth_mode=truth_mode,
                reference_examples=reference_examples,
            ),
            no_live_model_call=effective_no_live_model_call,
        )
        model_draft = draft_result.output_text
    generation_status = "manual_model_draft" if draft_result is None else draft_result.generation_status
    generation_model_name = "manual_factory_draft" if draft_result is None else draft_result.model_name
    generation_parameters = (
        {
            "source": "manual_factory_draft",
            "no_live_model_call": effective_no_live_model_call,
            "requested_no_live_model_call": no_live_model_call,
            "live_model_call_blocked_by_boundary": boundary_blocks_live_model_call,
        }
        if draft_result is None
        else draft_result.model_parameters
    )
    generation_parameters["requested_no_live_model_call"] = no_live_model_call
    generation_parameters["live_model_call_blocked_by_boundary"] = boundary_blocks_live_model_call

    prompt_spec = PromptSpec(
        human_id=_human_id("PROMPT_PAIR", _count(session, PromptSpec)),
        prompt_type="grounded_prompt_pair",
        voice_mode=voice_mode,
        truth_mode=truth_mode,
        prompt_text=prompt_text,
        success_criteria={
            "must_preserve_truth_boundary": True,
            "must_not_claim_archival_quote": True,
            "target_response_shape": target_response_shape,
            "prompt_intent": prompt_intent,
            "conversation_family": conversation_family,
        },
        metadata_json={
            "system_prompt": system_prompt,
            "conversation_family": conversation_family,
            "export_shape": "natural_messages",
            "source_prompt_pair_task_id": candidate_task.id,
            "source_review_annotation_id": candidate_task.input_payload.get("source_review_annotation_id"),
            "factory_annotation_id": annotation_id,
            "no_live_model_call": generation_parameters.get("no_live_model_call", True),
            "requested_no_live_model_call": no_live_model_call,
            "live_model_call_blocked_by_boundary": boundary_blocks_live_model_call,
            "draft_generation_status": generation_status,
            "draft_model_name": generation_model_name,
            "reference_example_count": len(reference_examples),
            "chunk_quality_profile": candidate_task.input_payload.get("chunk_quality_profile"),
            "pairing_ready_chunk_ids": candidate_task.input_payload.get("pairing_ready_chunk_ids", []),
            "needs_adam_edit_chunk_ids": candidate_task.input_payload.get("needs_adam_edit_chunk_ids", []),
            "pairing_gate": candidate_task.input_payload.get("pairing_gate"),
            "reference_example_count": len(reference_examples),
            **source_policy,
        },
    )
    session.add(prompt_spec)
    session.flush()

    context_pack = ContextPack(
        human_id=_human_id("CTX_PROMPT_PAIR", _count(session, ContextPack)),
        user_intent=prompt_intent,
        requested_voice_mode=voice_mode,
        truth_mode=truth_mode,
        allowed_facts=[source_text[:1800]] if source_text else [],
        boundaries_snapshot={
            "source_prompt_pair_task_id": candidate_task.id,
            "boundary_clearance_needed": decisions.get("boundary_clearance_needed", "review_before_export"),
            "quote_source_text": source_policy.get("quote_policy") == "source_quote_allowed_after_boundary_review",
            "disclose_generated": True,
            "chunk_quality_profile": candidate_task.input_payload.get("chunk_quality_profile"),
            "pairing_ready_chunk_ids": candidate_task.input_payload.get("pairing_ready_chunk_ids", []),
            "needs_adam_edit_chunk_ids": candidate_task.input_payload.get("needs_adam_edit_chunk_ids", []),
            "pairing_gate": candidate_task.input_payload.get("pairing_gate"),
            **source_policy,
        },
        style_guidance={
            "system_prompt": system_prompt,
            "user_prompt": prompt_text,
            "voice_mode": voice_mode,
            "target_response_shape": target_response_shape,
            "conversation_family": conversation_family,
            "source_title": source_title,
        },
    )
    session.add(context_pack)
    session.flush()

    generation = Generation(
        prompt_spec_id=prompt_spec.id,
        context_pack_id=context_pack.id,
        model_name=generation_model_name,
        model_parameters={**generation_parameters, "source_prompt_pair_task_id": candidate_task.id},
        output_text=model_draft,
    )
    session.add(generation)
    session.flush()

    review_task = Task(
        human_id=_human_id("TASK_PAIR_REVIEW", _count(session, Task)),
        task_type="gold_voice_edit",
        target_type="generation",
        target_id=generation.id,
        priority=85,
        queue="prompt_pairs_needing_gold_edits",
        reason_created="Prompt Pair Factory created a grounded draft for Adam gold-edit review.",
        input_payload={
            "prompt_spec_id": prompt_spec.id,
            "context_pack_id": context_pack.id,
            "generation_id": generation.id,
            "system_prompt": system_prompt,
            "prompt": prompt_text,
            "voice_mode": voice_mode,
            "truth_mode": truth_mode,
            "model_draft": model_draft,
            "adam_gold_edit": "",
            "source_title": source_title,
            "source_excerpt": source_text[:3000],
            "source_prompt_pair_task_id": candidate_task.id,
            "source_review_annotation_id": candidate_task.input_payload.get("source_review_annotation_id"),
            "factory_annotation_id": annotation_id,
            "prompt_pair_factory_no_model_call": generation_parameters.get("no_live_model_call", True),
            "requested_no_live_model_call": no_live_model_call,
            "live_model_call_blocked_by_boundary": boundary_blocks_live_model_call,
            "prompt_pair_factory_generation_status": generation_status,
            "reference_example_count": len(reference_examples),
            "conversation_family": conversation_family,
            "chunk_quality_profile": candidate_task.input_payload.get("chunk_quality_profile"),
            "pairing_ready_chunk_ids": candidate_task.input_payload.get("pairing_ready_chunk_ids", []),
            "needs_adam_edit_chunk_ids": candidate_task.input_payload.get("needs_adam_edit_chunk_ids", []),
            "ready_reference_chunk_range": candidate_task.input_payload.get("ready_reference_chunk_range"),
            "needs_adam_edit_chunk_range": candidate_task.input_payload.get("needs_adam_edit_chunk_range"),
            "chunk_quality_notes": candidate_task.input_payload.get("chunk_quality_notes"),
            "pairing_gate": candidate_task.input_payload.get("pairing_gate"),
            **source_policy,
            "target_response_shape": target_response_shape,
            "prompt_intent": prompt_intent,
            "failure_modes": ["scaffold_needs_adam_rewrite"] if generation_status != "live_model_call" else [],
            "ratings": {
                "voice_fidelity": 3,
                "mode_match": 3,
                "emotional_truth": 3,
                "concrete_detail": 3,
                "restraint": 3,
                "non_parody": 5,
                "grounding": 4,
            },
        },
        required_decisions=["adam_gold_edit", "response_rubric", "export_flags"],
        created_by="prompt_pair_factory",
    )
    session.add(review_task)
    session.flush()

    return {
        "prompt_spec_id": prompt_spec.id,
        "context_pack_id": context_pack.id,
        "generation_id": generation.id,
        "review_task_id": review_task.id,
    }
