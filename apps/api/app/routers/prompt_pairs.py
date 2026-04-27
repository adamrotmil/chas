from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlmodel import Session, select

from app.db.session import get_session
from app.models import Annotation, Task
from app.schemas import PromptPairBatchRequest, PromptPairBatchResponse
from app.services.prompt_pairs import create_prompt_pair_review_task

router = APIRouter(prefix="/prompt-pairs", tags=["prompt-pairs"])


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
        "no_live_model_call": True,
    }

    for task in candidates:
        annotation = Annotation(
            task_id=task.id,
            target_type=task.target_type,
            target_id=task.target_id,
            annotation_type="prompt_pair_factory_batch",
            decisions=decisions,
            notes="Batch-created stub prompt pair draft. No live model call was made.",
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
