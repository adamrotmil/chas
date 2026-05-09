from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends, Query, Response
from sqlmodel import Session, select

from app.config import Settings, get_settings
from app.db.session import get_session
from app.models import ContextPack, Generation, PromptSpec
from app.services.demo_generation import (
    compile_demo_generation_request_preview,
    demo_generation_input_plan,
    demo_reference_examples_for_item,
    demo_safety_policy,
    demo_text_draft_request_for_item,
    generation_blockers,
    held_out_prompts,
    public_held_out_prompt,
    text_generation_credential_requirements,
)
from app.services.model_generation import generate_text_draft, live_text_generation_ready
from app.services.prompt_pair_reference_pack import compile_prompt_pair_reference_pack

router = APIRouter(prefix="/model-status", tags=["model status"])


def _count(session: Session, model: Any) -> int:
    return len(session.exec(select(model)).all())


@router.get("")
def get_model_status(app_settings: Settings = Depends(get_settings)) -> dict:
    return {
        "text_generation_model": app_settings.text_generation_model,
        "text_generation_reasoning_effort": app_settings.text_generation_reasoning_effort,
        "text_generation_live_calls_enabled": app_settings.text_generation_live_calls_enabled,
        "chat_reasoning_effort": app_settings.chat_reasoning_effort,
        "chat_require_live_model": app_settings.chat_require_live_model,
        "openai_api_key_configured": bool(app_settings.openai_api_key),
        "text_generation_live_ready": live_text_generation_ready(app_settings),
        "fine_tuning_enabled_in_mvp": False,
        "credential_requirements": text_generation_credential_requirements(app_settings),
    }


@router.get("/demo-readiness")
def get_demo_generation_readiness(
    limit: int = Query(default=5, ge=1, le=20),
    app_settings: Settings = Depends(get_settings),
    session: Session = Depends(get_session),
) -> dict:
    blockers = generation_blockers(app_settings)
    held_out = held_out_prompts(session, limit=limit)
    reference_pack = compile_prompt_pair_reference_pack(session=session, sample_limit=200)
    return {
        "demo_type": "charles_voice_model_demo",
        "status": "ready_for_live_generation" if not blockers else "blocked_missing_credentials_or_live_gate",
        "model_name": app_settings.text_generation_model,
        "reasoning_effort": app_settings.text_generation_reasoning_effort,
        "can_generate": not blockers and len(held_out) >= limit,
        "blockers": blockers,
        "held_out_prompt_count": len(held_out),
        "held_out_prompts": [public_held_out_prompt(item) for item in held_out],
        "generation_input_plan": demo_generation_input_plan(
            app_settings=app_settings,
            blockers=blockers,
            held_out=held_out,
            reference_pack=reference_pack,
        ),
        "credential_requirements": text_generation_credential_requirements(app_settings),
        "safety_policy": demo_safety_policy(),
    }


@router.get("/demo-generation-request-preview")
def get_demo_generation_request_preview(
    limit: int = Query(default=5, ge=1, le=20),
    app_settings: Settings = Depends(get_settings),
    session: Session = Depends(get_session),
) -> dict:
    return compile_demo_generation_request_preview(session=session, app_settings=app_settings, limit=limit)


@router.get("/demo-generation-request-preview/yaml")
def get_demo_generation_request_preview_yaml(
    limit: int = Query(default=5, ge=1, le=20),
    app_settings: Settings = Depends(get_settings),
    session: Session = Depends(get_session),
) -> Response:
    preview = compile_demo_generation_request_preview(session=session, app_settings=app_settings, limit=limit)
    return Response(
        content=preview["export_preview_yaml"],
        media_type="text/yaml; charset=utf-8",
        headers={"Content-Disposition": 'inline; filename="charlesops_demo_generation_request_preview.yaml"'},
    )


@router.post("/demo-generations")
def create_demo_generations(
    payload: dict[str, Any] | None = Body(default=None),
    app_settings: Settings = Depends(get_settings),
    session: Session = Depends(get_session),
) -> dict:
    request_payload = payload or {}
    limit = max(1, min(int(request_payload.get("limit") or 1), 5))
    blockers = generation_blockers(app_settings)
    held_out = held_out_prompts(session, limit=limit)
    if blockers:
        return {
            "demo_type": "charles_voice_model_demo_generation_batch",
            "status": "blocked_missing_credentials_or_live_gate",
            "can_generate": False,
            "blockers": blockers,
            "created_count": 0,
            "created_generations": [],
            "credential_requirements": text_generation_credential_requirements(app_settings),
            "safety_policy": demo_safety_policy(),
        }

    created = []
    held_out_task_ids = {str(item["task_id"]) for item in held_out}
    for item in held_out:
        reference_examples = demo_reference_examples_for_item(
            session=session,
            item=item,
            exclude_task_ids=held_out_task_ids,
            limit=6,
        )
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
                "safety_policy": demo_safety_policy(),
            },
        )
        session.add(prompt_spec)
        session.add(context_pack)
        session.flush()

        result = generate_text_draft(
            demo_text_draft_request_for_item(
                item=item,
                reference_examples=reference_examples,
                app_settings=app_settings,
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
        "credential_requirements": text_generation_credential_requirements(app_settings),
        "safety_policy": demo_safety_policy(),
    }
