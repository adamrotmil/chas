from typing import List, Optional

from fastapi import APIRouter, Depends
from sqlmodel import Session, select

from app.db.session import get_session
from app.models import Annotation
from app.schemas import AnnotationCreate

router = APIRouter(tags=["annotations"])


@router.get("/annotations", response_model=List[Annotation])
def list_annotations(
    task_id: Optional[str] = None,
    target_type: Optional[str] = None,
    target_id: Optional[str] = None,
    session: Session = Depends(get_session),
) -> List[Annotation]:
    statement = select(Annotation).order_by(Annotation.created_at.desc())
    if task_id:
        statement = statement.where(Annotation.task_id == task_id)
    if target_type:
        statement = statement.where(Annotation.target_type == target_type)
    if target_id:
        statement = statement.where(Annotation.target_id == target_id)
    return session.exec(statement).all()


@router.post("/annotations", response_model=Annotation)
def create_annotation(
    payload: AnnotationCreate,
    session: Session = Depends(get_session),
) -> Annotation:
    annotation = Annotation(**payload.model_dump())
    session.add(annotation)
    session.commit()
    session.refresh(annotation)
    return annotation


@router.get("/targets/{target_type}/{target_id}/annotations", response_model=List[Annotation])
def list_target_annotations(
    target_type: str,
    target_id: str,
    session: Session = Depends(get_session),
) -> List[Annotation]:
    return session.exec(
        select(Annotation)
        .where(Annotation.target_type == target_type)
        .where(Annotation.target_id == target_id)
        .order_by(Annotation.created_at.desc())
    ).all()
