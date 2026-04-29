from __future__ import annotations

import hashlib
import json
from typing import Any

from fastapi import APIRouter, Body, Depends, Query
from sqlmodel import Session, select

from app.config import Settings, get_settings
from app.db.session import get_session
from app.models import ContextPack, Generation, PromptSpec, Task
from app.services.model_generation import TextDraftRequest, generate_text_draft, live_text_generation_ready
from app.services.prompt_pair_reference_pack import compile_prompt_pair_reference_pack, select_prompt_pair_reference_examples

router = APIRouter(prefix="/model-status", tags=["model status"])


def _count(session: Session, model: Any) -> int:
    return len(session.exec(select(model)).all())


def _generation_blockers(app_settings: Settings) -> list[str]:
    blockers = []
    if not app_settings.text_generation_live_calls_enabled:
        blockers.append("text_generation_live_calls_disabled")
    if not app_settings.openai_api_key:
        blockers.append("openai_api_key_missing")
    return blockers


def _demo_safety_policy() -> dict:
    return {
        "outputs_truth_status": "model_generated",
        "adam_review_required": True,
        "never_training_truth_without_review": True,
        "fine_tuning_api_calls_allowed": False,
    }


def _held_out_prompts(session: Session, *, limit: int) -> list[dict]:
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
        if not isinstance(prompt, str) or not prompt.strip() or not isinstance(response, str) or not response.strip():
            continue
        held_out.append(
            {
                "task_id": task.id,
                "task_human_id": task.human_id,
                "prompt": prompt,
                "prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
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
        )
        if len(held_out) >= limit:
            break
    return held_out


def _demo_generation_input_plan(
    *,
    app_settings: Settings,
    blockers: list[str],
    held_out: list[dict],
    reference_pack: dict,
) -> dict:
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
        "reference_pack_content_sha256": reference_pack["content_sha256"],
        "reference_pack_sample_count": reference_pack["sample_count"],
        "reference_pack_ready_for_generation_context": reference_pack["ready_for_generation_context"],
        "held_out_prompt_count": len(prompt_inputs),
        "held_out_prompt_set_sha256": hashlib.sha256(prompt_set_json.encode("utf-8")).hexdigest(),
        "held_out_prompts": prompt_inputs,
        "safety_policy": _demo_safety_policy(),
    }


@router.get("")
def get_model_status(app_settings: Settings = Depends(get_settings)) -> dict:
    return {
        "text_generation_model": app_settings.text_generation_model,
        "text_generation_reasoning_effort": app_settings.text_generation_reasoning_effort,
        "text_generation_live_calls_enabled": app_settings.text_generation_live_calls_enabled,
        "openai_api_key_configured": bool(app_settings.openai_api_key),
        "text_generation_live_ready": live_text_generation_ready(app_settings),
        "fine_tuning_enabled_in_mvp": False,
    }


@router.get("/demo-readiness")
def get_demo_generation_readiness(
    limit: int = Query(default=5, ge=1, le=20),
    app_settings: Settings = Depends(get_settings),
    session: Session = Depends(get_session),
) -> dict:
    blockers = _generation_blockers(app_settings)
    held_out = _held_out_prompts(session, limit=limit)
    reference_pack = compile_prompt_pair_reference_pack(session=session, sample_limit=200)
    return {
        "demo_type": "charles_voice_model_demo",
        "status": "ready_for_live_generation" if not blockers else "blocked_missing_credentials_or_live_gate",
        "model_name": app_settings.text_generation_model,
        "reasoning_effort": app_settings.text_generation_reasoning_effort,
        "can_generate": not blockers and len(held_out) >= limit,
        "blockers": blockers,
        "held_out_prompt_count": len(held_out),
        "held_out_prompts": held_out,
        "generation_input_plan": _demo_generation_input_plan(
            app_settings=app_settings,
            blockers=blockers,
            held_out=held_out,
            reference_pack=reference_pack,
        ),
        "safety_policy": _demo_safety_policy(),
    }


@router.post("/demo-generations")
def create_demo_generations(
    payload: dict[str, Any] | None = Body(default=None),
    app_settings: Settings = Depends(get_settings),
    session: Session = Depends(get_session),
) -> dict:
    request_payload = payload or {}
    limit = max(1, min(int(request_payload.get("limit") or 1), 5))
    blockers = _generation_blockers(app_settings)
    held_out = _held_out_prompts(session, limit=limit)
    if blockers:
        return {
            "demo_type": "charles_voice_model_demo_generation_batch",
            "status": "blocked_missing_credentials_or_live_gate",
            "can_generate": False,
            "blockers": blockers,
            "created_count": 0,
            "created_generations": [],
            "safety_policy": _demo_safety_policy(),
        }

    created = []
    for item in held_out:
        reference_examples = [
            example
            for example in select_prompt_pair_reference_examples(
                session=session,
                voice_mode=item.get("voice_mode"),
                conversation_family=item.get("conversation_family"),
                limit=8,
            )
            if (example.get("metadata") or {}).get("task_id") != item["task_id"]
        ][:6]
        reference_ids = [
            (example.get("metadata") or {}).get("reference_id")
            for example in reference_examples
            if (example.get("metadata") or {}).get("reference_id")
        ]
        prompt_spec = PromptSpec(
            human_id=f"PROMPT_DEMO_{_count(session, PromptSpec) + 1:06d}",
            prompt_type="charles_voice_demo_generation",
            voice_mode=item.get("voice_mode"),
            truth_mode="model_generated",
            prompt_text=item["prompt"],
            success_criteria={
                "output_truth_status": "model_generated",
                "adam_review_required": True,
                "not_training_truth": True,
            },
            metadata_json={
                "source_task_id": item["task_id"],
                "source_task_human_id": item["task_human_id"],
                "excluded_from_training_export": True,
                "held_out_prompt": True,
                "model_name": app_settings.text_generation_model,
                "reasoning_effort": app_settings.text_generation_reasoning_effort,
            },
        )
        context_pack = ContextPack(
            human_id=f"CTX_DEMO_{_count(session, ContextPack) + 1:06d}",
            user_intent="charles_voice_demo_generation",
            requested_voice_mode=item.get("voice_mode"),
            truth_mode="model_generated",
            allowed_facts=[],
            boundaries_snapshot={
                "demo_generation_only": True,
                "excluded_from_training_export": True,
            },
            style_guidance={
                "reference_ids": reference_ids,
                "reference_use": "voice_shape_only_not_training_truth",
                "safety_policy": _demo_safety_policy(),
            },
        )
        session.add(prompt_spec)
        session.add(context_pack)
        session.flush()

        source_text = "\n\n".join(
            part
            for part in [str(item.get("source_excerpt") or "").strip(), str(item.get("context") or "").strip()]
            if part
        )
        result = generate_text_draft(
            TextDraftRequest(
                system_prompt=str(item.get("system_prompt") or "You are Charles Rotmil."),
                user_prompt=item["prompt"],
                source_title=str(item.get("source_title") or "held-out prompt"),
                source_text=source_text,
                voice_mode=str(item.get("voice_mode") or "unknown"),
                conversation_family=str(item.get("conversation_family") or "unknown"),
                target_response_shape="demo_response",
                truth_mode="model_generated",
                reference_examples=reference_examples,
                model_name=app_settings.text_generation_model,
                reasoning_effort=app_settings.text_generation_reasoning_effort,
            ),
            no_live_model_call=False,
            app_settings=app_settings,
        )
        generation = Generation(
            prompt_spec_id=prompt_spec.id,
            context_pack_id=context_pack.id,
            model_name=result.model_name,
            model_parameters={
                **result.model_parameters,
                "generation_status": result.generation_status,
                "truth_status": "model_generated",
                "adam_review_required": True,
                "excluded_from_training_export": True,
                "source_task_id": item["task_id"],
                "reference_ids": reference_ids,
            },
            output_text=result.output_text,
        )
        session.add(generation)
        session.flush()
        created.append(
            {
                "generation_id": generation.id,
                "prompt_spec_id": prompt_spec.id,
                "context_pack_id": context_pack.id,
                "source_task_id": item["task_id"],
                "source_task_human_id": item["task_human_id"],
                "prompt": item["prompt"],
                "output_text": generation.output_text,
                "model_name": generation.model_name,
                "truth_status": "model_generated",
                "adam_review_required": True,
                "excluded_from_training_export": True,
                "reference_ids": reference_ids,
            }
        )
    session.commit()
    return {
        "demo_type": "charles_voice_model_demo_generation_batch",
        "status": "created_model_generated_demo_outputs",
        "can_generate": True,
        "blockers": [],
        "created_count": len(created),
        "created_generations": created,
        "safety_policy": _demo_safety_policy(),
    }
