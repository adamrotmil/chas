from __future__ import annotations

from datetime import datetime, timezone

from typing import Any, Dict

from fastapi import APIRouter, Body, Depends, Query, Response
from sqlmodel import Session, select

from app.db.session import get_session
from app.models import Annotation, Task
from app.schemas import PromptPairBatchRequest, PromptPairBatchResponse
from app.services.pair_export import preflight_pair_export_gate
from app.services.prompt_pair_audit import (
    compile_prompt_pair_audit,
    compile_prompt_pair_audit_pack,
    compile_dpo_rejected_reason_repair_packet,
    compile_dpo_rejected_reason_repair_projection,
    compile_prompt_pair_candidate_review_pack,
    compile_prompt_pair_review_progress,
    compile_prompt_pair_top_blocker_review_session_plan,
    compile_prompt_pair_top_blocker_slice,
)
from app.services.prompt_pair_dpo import synthesize_dpo_candidates
from app.services.prompt_pair_reference_pack import compile_prompt_pair_reference_pack
from app.services.prompt_pair_voice_modes import backfill_prompt_pair_voice_modes
from app.services.prompt_pairs import create_prompt_pair_review_task

router = APIRouter(prefix="/prompt-pairs", tags=["prompt-pairs"])


@router.get("/audit")
def prompt_pair_audit(
    sample_limit: int = 20,
    session: Session = Depends(get_session),
) -> dict:
    return compile_prompt_pair_audit(session=session, sample_limit=sample_limit)


@router.post("/preflight-export-gate")
def prompt_pair_preflight_export_gate(payload: Dict[str, Any] = Body(...)) -> dict:
    return preflight_pair_export_gate(payload)


@router.get("/audit-pack")
def prompt_pair_audit_pack(
    sample_limit: int = 20,
    session: Session = Depends(get_session),
) -> dict:
    return compile_prompt_pair_audit_pack(session=session, sample_limit=sample_limit)


@router.get("/held-candidates")
def prompt_pair_held_candidates(
    limit: int = 30,
    session: Session = Depends(get_session),
) -> dict:
    return compile_prompt_pair_candidate_review_pack(session=session, limit=limit)


@router.get("/review-progress")
def prompt_pair_review_progress(
    session: Session = Depends(get_session),
) -> dict:
    return compile_prompt_pair_review_progress(session=session)


@router.get("/top-blocker-slice")
def prompt_pair_top_blocker_slice(
    limit: int = 5,
    session: Session = Depends(get_session),
) -> dict:
    return compile_prompt_pair_top_blocker_slice(session=session, limit=limit)


@router.get("/top-blocker-review-session-plan")
def prompt_pair_top_blocker_review_session_plan(
    limit: int = 5,
    session: Session = Depends(get_session),
) -> dict:
    return compile_prompt_pair_top_blocker_review_session_plan(session=session, limit=limit)


@router.get("/top-blocker-review-session-plan/yaml")
def prompt_pair_top_blocker_review_session_plan_yaml(
    limit: int = 5,
    session: Session = Depends(get_session),
) -> Response:
    plan = compile_prompt_pair_top_blocker_review_session_plan(session=session, limit=limit)
    filename = f"charlesops_prompt_pair_top_blocker_session_plan_{plan['selected_count']}.yaml"
    return Response(
        content=plan["export_preview_yaml"],
        media_type="text/yaml; charset=utf-8",
        headers={"Content-Disposition": f'inline; filename="{filename}"'},
    )


@router.get("/dpo-rejected-reason-repair-pack")
def prompt_pair_dpo_rejected_reason_repair_pack(
    limit: int = 25,
    session: Session = Depends(get_session),
) -> dict:
    return compile_dpo_rejected_reason_repair_packet(session=session, limit=limit)


@router.get("/dpo-rejected-reason-repair-pack/yaml")
def prompt_pair_dpo_rejected_reason_repair_pack_yaml(
    limit: int = 25,
    session: Session = Depends(get_session),
) -> Response:
    packet = compile_dpo_rejected_reason_repair_packet(session=session, limit=limit)
    filename = f"charlesops_dpo_rejected_reason_repair_pack_{packet['reported_candidate_count']}.yaml"
    return Response(
        content=packet["export_preview_yaml"],
        media_type="text/yaml; charset=utf-8",
        headers={"Content-Disposition": f'inline; filename="{filename}"'},
    )


@router.get("/dpo-rejected-reason-repair-projection")
def prompt_pair_dpo_rejected_reason_repair_projection(
    task_id: str | None = Query(default=None),
    failure_mode: str = Query(default="too_generic_not_charles_voice", min_length=1, max_length=200),
    session: Session = Depends(get_session),
) -> dict:
    return compile_dpo_rejected_reason_repair_projection(
        session=session,
        task_id=task_id,
        failure_mode=failure_mode,
    )


@router.get("/audit-pack/markdown")
def prompt_pair_audit_pack_markdown(
    sample_limit: int = 200,
    session: Session = Depends(get_session),
) -> Response:
    pack = compile_prompt_pair_audit_pack(session=session, sample_limit=sample_limit)
    filename = f"charlesops_prompt_pair_audit_pack_{pack['sample_count']}.md"
    return Response(
        content=pack["markdown"],
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f'inline; filename="{filename}"'},
    )


@router.get("/reference-pack")
def prompt_pair_reference_pack(
    sample_limit: int = 200,
    session: Session = Depends(get_session),
) -> dict:
    return compile_prompt_pair_reference_pack(session=session, sample_limit=sample_limit)


@router.get("/reference-pack/jsonl")
def prompt_pair_reference_pack_jsonl(
    sample_limit: int = 200,
    session: Session = Depends(get_session),
) -> Response:
    pack = compile_prompt_pair_reference_pack(session=session, sample_limit=sample_limit)
    filename = f"charlesops_prompt_pair_voice_reference_pack_{pack['sample_count']}.jsonl"
    return Response(
        content=pack["jsonl"],
        media_type="application/x-ndjson; charset=utf-8",
        headers={"Content-Disposition": f'inline; filename="{filename}"'},
    )


@router.get("/reference-pack/markdown")
def prompt_pair_reference_pack_markdown(
    sample_limit: int = 200,
    session: Session = Depends(get_session),
) -> Response:
    pack = compile_prompt_pair_reference_pack(session=session, sample_limit=sample_limit)
    filename = f"charlesops_prompt_pair_voice_reference_pack_{pack['sample_count']}.md"
    return Response(
        content=pack["markdown"],
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f'inline; filename="{filename}"'},
    )


@router.post("/backfill-voice-modes")
def backfill_voice_modes(
    dry_run: bool = True,
    session: Session = Depends(get_session),
) -> dict:
    return backfill_prompt_pair_voice_modes(session=session, dry_run=dry_run)


@router.post("/synthesize-dpo-candidates")
def create_synthetic_dpo_candidates(
    limit: int = 25,
    dry_run: bool = True,
    session: Session = Depends(get_session),
) -> dict:
    return synthesize_dpo_candidates(session=session, limit=limit, dry_run=dry_run)


@router.post("/batches", response_model=PromptPairBatchResponse)
def create_prompt_pair_batch(
    payload: PromptPairBatchRequest,
    session: Session = Depends(get_session),
) -> PromptPairBatchResponse:
    limit = max(0, min(payload.limit, 50))
    if limit == 0:
        return PromptPairBatchResponse(created_count=0)
    candidates = session.exec(
        select(Task)
        .where(Task.task_type == "grounded_prompt_pair_candidate")
        .where(Task.status == "ready")
        .where(Task.queue == payload.queue)
        .order_by(Task.priority.desc(), Task.created_at.asc())
    ).all()[:limit]

    response = PromptPairBatchResponse(created_count=0)
    decisions = {
        "prompt_intent": payload.prompt_intent,
        "voice_mode": payload.voice_mode,
        "truth_mode": payload.truth_mode,
        "target_response_shape": payload.target_response_shape,
        "boundary_clearance_needed": payload.boundary_clearance_needed,
        "no_live_model_call": payload.no_live_model_call,
    }
    if payload.conversation_family:
        decisions["conversation_family"] = payload.conversation_family
    if payload.system_prompt:
        decisions["system_prompt"] = payload.system_prompt

    for task in candidates:
        annotation = Annotation(
            task_id=task.id,
            target_type=task.target_type,
            target_id=task.target_id,
            annotation_type="prompt_pair_factory_batch",
            decisions=decisions,
            notes="Batch-created prompt pair draft.",
        )
        session.add(annotation)
        session.flush()
        created = create_prompt_pair_review_task(
            session=session,
            candidate_task=task,
            decisions=decisions,
            annotation_id=annotation.id,
        )
        annotation.creates_or_updates = created
        task.status = "submitted"
        task.completed_at = datetime.now(timezone.utc)
        task.updated_at = datetime.now(timezone.utc)
        session.add(annotation)
        session.add(task)

        response.candidate_task_ids.append(task.id)
        response.annotation_ids.append(annotation.id)
        if created.get("review_task_id"):
            response.review_task_ids.append(created["review_task_id"])

    response.created_count = len(response.review_task_ids)
    session.commit()
    return response
