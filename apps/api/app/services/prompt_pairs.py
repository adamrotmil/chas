from __future__ import annotations

from typing import Any, Dict, List, Optional

from sqlmodel import Session, select

from app.models import ContextPack, Generation, PromptSpec, Segment, Task


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


def _segment_source_text(session: Session, task: Task, decisions: Dict[str, Any]) -> str:
    selected_chunk_ids = _string_list(decisions.get("source_chunks_to_use")) or _string_list(
        decisions.get("selected_chunk_ids")
    ) or _string_list(task.input_payload.get("selected_chunk_ids"))
    if selected_chunk_ids:
        chunks = session.exec(select(Segment).where(Segment.id.in_(selected_chunk_ids))).all()
        text = "\n\n".join(chunk.text_content or "" for chunk in chunks if chunk.text_content)
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


def _stub_draft(source_text: str, target_response_shape: str) -> str:
    excerpt = " ".join(source_text.split())[:420]
    if not excerpt:
        excerpt = "Source excerpt was not available in the task payload."
    return (
        "[stub draft - no live model call]\n\n"
        f"Use this {target_response_shape.replace('_', ' ')} as a starting point for Adam to rewrite.\n\n"
        f"Grounding noticed: {excerpt}"
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
    source_policy = {
        "source_use_modes": decisions.get("source_use_modes") or candidate_task.input_payload.get("source_use_modes", []),
        "source_use_mode": decisions.get("source_use_mode") or candidate_task.input_payload.get("source_use_mode"),
        "quote_policy": decisions.get("quote_policy") or candidate_task.input_payload.get("quote_policy"),
        "privacy_clearance": decisions.get("privacy_clearance") or candidate_task.input_payload.get("privacy_clearance"),
        "redaction_instructions": decisions.get("redaction_instructions")
        or candidate_task.input_payload.get("redaction_instructions"),
    }
    prompt_text = _string(decisions.get("prompt_text")) or (
        "Using the reviewed source material as grounding, draft a Charles-style response "
        f"in {voice_mode.replace('_', ' ')} mode. Keep source facts distinct from generated voice. "
        "Do not present the response as an archival quote."
    )
    model_draft = _string(decisions.get("model_draft")) or _stub_draft(source_text, target_response_shape)

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
        },
        metadata_json={
            "source_prompt_pair_task_id": candidate_task.id,
            "source_review_annotation_id": candidate_task.input_payload.get("source_review_annotation_id"),
            "factory_annotation_id": annotation_id,
            "no_live_model_call": True,
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
            **source_policy,
        },
        style_guidance={
            "voice_mode": voice_mode,
            "target_response_shape": target_response_shape,
            "source_title": source_title,
        },
    )
    session.add(context_pack)
    session.flush()

    generation = Generation(
        prompt_spec_id=prompt_spec.id,
        context_pack_id=context_pack.id,
        model_name="prompt_pair_factory_stub_no_model_call",
        model_parameters={
            "source": "deterministic_stub",
            "no_live_model_call": True,
            "source_prompt_pair_task_id": candidate_task.id,
        },
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
            "prompt_pair_factory_no_model_call": True,
            **source_policy,
            "target_response_shape": target_response_shape,
            "prompt_intent": prompt_intent,
            "failure_modes": ["stub_needs_adam_rewrite"],
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
