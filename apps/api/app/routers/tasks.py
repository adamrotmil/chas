from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from app.db.session import get_session
from app.models import Annotation, Task, TaskDraft
from app.schemas import TaskDraftUpsert, TaskStatusUpdate, TaskSubmit
from app.services.gold_voice import upsert_gold_voice_artifacts
from app.services.prompt_pairs import create_prompt_pair_review_task
from app.services.source_review import upsert_segment_boundary_review_artifacts, upsert_source_review_artifacts
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
