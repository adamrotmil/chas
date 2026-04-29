from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from app.db.session import get_session
from app.models import Annotation, Task, TaskDraft
from app.schemas import TaskDraftUpsert, TaskStatusUpdate, TaskSubmit
from app.services.asset_triage import upsert_asset_triage_artifacts
from app.services.gold_voice import upsert_gold_voice_artifacts
from app.services.pair_generation import create_make_gold_tasks_from_review, preview_make_gold_tasks_from_review
from app.services.photo_context_projection import build_photo_context_submit_projection
from app.services.photo_memory import upsert_photo_context_artifacts
from app.services.prompt_pairs import create_prompt_pair_review_task
from app.services.source_spans import create_source_span_annotations
from app.services.source_review import upsert_segment_boundary_review_artifacts, upsert_source_review_artifacts
from app.services.task_receipts import create_task_receipt
from app.services.vision import upsert_vision_review_artifacts

router = APIRouter(prefix="/tasks", tags=["tasks"])


def _task_or_404(session: Session, task_id: str) -> Task:
    task = session.get(Task, task_id)
    if not task:
        task = session.exec(select(Task).where(Task.human_id == task_id)).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return task


def _task_draft(session: Session, task_id: str, user_id: str = "adam") -> Optional[TaskDraft]:
    return session.exec(
        select(TaskDraft).where(TaskDraft.task_id == task_id).where(TaskDraft.user_id == user_id)
    ).first()


def _receipt_safe_submit_projection(projection: dict) -> dict:
    if projection.get("projection_type") != "photo_context_submit_projection":
        return {}
    vector_handoff = projection.get("memory_embedding_vector_handoff")
    boundary = projection.get("boundary")
    gallery = projection.get("gallery")
    return {
        "projection_type": projection.get("projection_type"),
        "review_policy": projection.get("review_policy"),
        "content_sha256": projection.get("content_sha256"),
        "export_preview_yaml": projection.get("export_preview_yaml"),
        "submit_readiness": projection.get("submit_readiness"),
        "blocked_reasons": projection.get("blocked_reasons", []),
        "vector_handoff_status": vector_handoff.get("status") if isinstance(vector_handoff, dict) else None,
        "boundary_privacy_level": (
            (boundary.get("snapshot_after") or {}).get("privacy_level") if isinstance(boundary, dict) else None
        ),
        "gallery_scope_after": gallery.get("scope_after") if isinstance(gallery, dict) else None,
        "does_not_mutate_state": projection.get("does_not_mutate_state") is True,
        "no_live_embedding_call": projection.get("no_live_embedding_call") is True,
        "ordinary_db_vector_storage": projection.get("ordinary_db_vector_storage") is True,
    }


@router.get("", response_model=List[Task])
def list_tasks(
    queue: Optional[str] = None,
    status: Optional[str] = None,
    session: Session = Depends(get_session),
) -> List[Task]:
    statement = select(Task).order_by(Task.priority.desc(), Task.created_at.asc())
    if queue:
        statement = statement.where(Task.queue == queue)
    if status:
        statement = statement.where(Task.status == status)
    return session.exec(statement).all()


@router.get("/next", response_model=Optional[Task])
def next_task(
    queue: Optional[str] = None,
    session: Session = Depends(get_session),
) -> Optional[Task]:
    statement = (
        select(Task)
        .where(Task.status == "ready")
        .order_by(Task.priority.desc(), Task.created_at.asc())
    )
    if queue:
        statement = statement.where(Task.queue == queue)
    return session.exec(statement).first()


@router.get("/{task_id}", response_model=Task)
def get_task(task_id: str, session: Session = Depends(get_session)) -> Task:
    return _task_or_404(session, task_id)


@router.get("/{task_id}/draft", response_model=Optional[TaskDraft])
def get_task_draft(
    task_id: str,
    user_id: str = "adam",
    session: Session = Depends(get_session),
) -> Optional[TaskDraft]:
    task = _task_or_404(session, task_id)
    return _task_draft(session, task.id, user_id=user_id)


@router.put("/{task_id}/draft", response_model=TaskDraft)
def upsert_task_draft(
    task_id: str,
    payload: TaskDraftUpsert,
    session: Session = Depends(get_session),
) -> TaskDraft:
    task = _task_or_404(session, task_id)
    draft = _task_draft(session, task.id, user_id=payload.user_id)
    if draft is None:
        draft = TaskDraft(task_id=task.id, user_id=payload.user_id)
    draft.decisions = payload.decisions
    draft.notes = payload.notes
    draft.updated_at = datetime.now(timezone.utc)
    session.add(draft)
    session.commit()
    session.refresh(draft)
    return draft


@router.post("/{task_id}/photo-context/projection")
def preview_photo_context_submit(
    task_id: str,
    payload: TaskSubmit,
    session: Session = Depends(get_session),
) -> dict:
    task = _task_or_404(session, task_id)
    return build_photo_context_submit_projection(
        session=session,
        task=task,
        decisions=payload.decisions,
    )


@router.post("/{task_id}/pair-generation/preview")
def preview_source_review_pair_generation(
    task_id: str,
    payload: TaskSubmit,
    session: Session = Depends(get_session),
) -> dict:
    task = _task_or_404(session, task_id)
    if task.task_type not in {"text_segment_review", "text_segment_boundary_review", "email_voice_sample"}:
        raise HTTPException(status_code=400, detail="Task does not support source-review pair generation")
    return preview_make_gold_tasks_from_review(
        session=session,
        task=task,
        decisions=payload.decisions,
    )


@router.delete("/{task_id}/draft")
def delete_task_draft(
    task_id: str,
    user_id: str = "adam",
    session: Session = Depends(get_session),
) -> dict:
    task = _task_or_404(session, task_id)
    draft = _task_draft(session, task.id, user_id=user_id)
    if draft:
        session.delete(draft)
        session.commit()
    return {"deleted": bool(draft)}


@router.post("/{task_id}/submit", response_model=Annotation)
def submit_task(
    task_id: str,
    payload: TaskSubmit,
    session: Session = Depends(get_session),
) -> Annotation:
    task = _task_or_404(session, task_id)
    annotation = Annotation(
        task_id=task.id,
        target_type=task.target_type,
        target_id=task.target_id,
        annotation_type=payload.annotation_type or task.task_type,
        decisions=payload.decisions,
        notes=payload.notes,
    )
    session.add(annotation)
    session.flush()

    creates_or_updates = {}
    source_span_annotations = []
    if task.task_type in {"text_segment_review", "text_segment_boundary_review", "email_voice_sample"}:
        source_span_annotations = create_source_span_annotations(
            session=session,
            task=task,
            decisions=payload.decisions,
            annotation_id=annotation.id,
        )
    if task.task_type == "gold_voice_edit":
        creates_or_updates = upsert_gold_voice_artifacts(
            session=session,
            task=task,
            decisions=payload.decisions,
            annotation_id=annotation.id,
        )
        annotation.creates_or_updates = creates_or_updates
    elif task.task_type in {"text_segment_review", "email_voice_sample"}:
        creates_or_updates = upsert_source_review_artifacts(
            session=session,
            task=task,
            decisions=payload.decisions,
            annotation_id=annotation.id,
        )
        annotation.creates_or_updates = creates_or_updates
    elif task.task_type == "text_segment_boundary_review":
        creates_or_updates = upsert_segment_boundary_review_artifacts(
            session=session,
            task=task,
            decisions=payload.decisions,
            annotation_id=annotation.id,
        )
        annotation.creates_or_updates = creates_or_updates
    elif task.task_type == "grounded_prompt_pair_candidate":
        creates_or_updates = create_prompt_pair_review_task(
            session=session,
            candidate_task=task,
            decisions=payload.decisions,
            annotation_id=annotation.id,
        )
        annotation.creates_or_updates = creates_or_updates
    elif task.task_type == "vision_draft_review":
        creates_or_updates = upsert_vision_review_artifacts(
            session=session,
            task=task,
            decisions=payload.decisions,
            annotation_id=annotation.id,
        )
        annotation.creates_or_updates = creates_or_updates
    elif task.task_type == "photo_context":
        submit_projection = _receipt_safe_submit_projection(
            build_photo_context_submit_projection(
                session=session,
                task=task,
                decisions=payload.decisions,
            )
        )
        creates_or_updates = upsert_photo_context_artifacts(
            session=session,
            task=task,
            decisions=payload.decisions,
            annotation_id=annotation.id,
        )
        if submit_projection:
            creates_or_updates = {
                **creates_or_updates,
                "submit_projection": submit_projection,
                "submit_projection_content_sha256": submit_projection.get("content_sha256"),
            }
        annotation.creates_or_updates = creates_or_updates
    elif task.task_type == "asset_triage":
        creates_or_updates = upsert_asset_triage_artifacts(
            session=session,
            task=task,
            decisions=payload.decisions,
            annotation_id=annotation.id,
        )
        annotation.creates_or_updates = creates_or_updates

    if task.task_type in {"text_segment_review", "text_segment_boundary_review", "email_voice_sample"} and payload.decisions.get(
        "generate_pairs_on_submit"
    ) in {"yes", "generate", True}:
        pair_updates = create_make_gold_tasks_from_review(
            session=session,
            task=task,
            decisions=payload.decisions,
            annotation_id=annotation.id,
            source_span_annotations=source_span_annotations,
        )
        creates_or_updates = {**creates_or_updates, **pair_updates}
        annotation.creates_or_updates = creates_or_updates

    receipt = create_task_receipt(
        session=session,
        task=task,
        annotation_id=annotation.id,
        creates_or_updates=creates_or_updates,
    )
    annotation.creates_or_updates = {
        **creates_or_updates,
        "task_receipt_id": receipt.id,
        "receipt": {
            "id": receipt.id,
            "human_id": receipt.human_id,
            "downstream_status": receipt.downstream_status,
            "boundary_status": receipt.boundary_status,
            "blocked_reasons": receipt.blocked_reasons,
            "next_action_label": receipt.next_action_label,
            "next_queue": receipt.next_queue,
            "outcomes": receipt.summary.get("outcomes", []),
            "export_artifact": receipt.summary.get("export_artifact"),
            "pair_generation_run": receipt.summary.get("pair_generation_run"),
            "retrieval_origin": receipt.summary.get("retrieval_origin"),
            "review_session_origin": receipt.summary.get("review_session_origin"),
            "vector_handoff_status": creates_or_updates.get("vector_handoff_status"),
            "vector_handoff_reason": creates_or_updates.get("vector_handoff_reason"),
            "vector_handoff_record_id": creates_or_updates.get("vector_handoff_record_id"),
            "submit_projection": receipt.summary.get("submit_projection"),
        },
    }

    task.status = "submitted"
    task.completed_at = datetime.now(timezone.utc)
    task.updated_at = datetime.now(timezone.utc)
    draft = _task_draft(session, task.id)
    if draft:
        session.delete(draft)
    session.add(task)
    session.add(annotation)
    session.commit()
    session.refresh(annotation)
    return annotation


@router.post("/{task_id}/skip", response_model=Task)
def skip_task(
    task_id: str,
    payload: TaskStatusUpdate,
    session: Session = Depends(get_session),
) -> Task:
    task = _task_or_404(session, task_id)
    task.status = "skipped"
    task.updated_at = datetime.now(timezone.utc)
    task.input_payload = {**task.input_payload, "skip_reason": payload.reason, "skip_notes": payload.notes}
    session.add(task)
    session.commit()
    session.refresh(task)
    return task


@router.post("/{task_id}/flag", response_model=Task)
def flag_task(
    task_id: str,
    payload: TaskStatusUpdate,
    session: Session = Depends(get_session),
) -> Task:
    task = _task_or_404(session, task_id)
    task.status = "sensitive_hold"
    task.updated_at = datetime.now(timezone.utc)
    task.input_payload = {**task.input_payload, "flag_reason": payload.reason, "flag_notes": payload.notes}
    session.add(task)
    session.commit()
    session.refresh(task)
    return task
