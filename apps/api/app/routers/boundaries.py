from datetime import datetime, timezone
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from app.db.session import get_session
from app.models import Boundary
from app.schemas import BoundaryCreate, BoundaryUpdate

router = APIRouter(prefix="/boundaries", tags=["boundaries"])


@router.get("", response_model=List[Boundary])
def list_boundaries(session: Session = Depends(get_session)) -> List[Boundary]:
    return session.exec(select(Boundary).order_by(Boundary.created_at.desc())).all()


@router.get("/{target_type}/{target_id}", response_model=Boundary)
def get_boundary(
    target_type: str,
    target_id: str,
    session: Session = Depends(get_session),
) -> Boundary:
    boundary = session.exec(
        select(Boundary)
        .where(Boundary.target_type == target_type)
        .where(Boundary.target_id == target_id)
        .order_by(Boundary.created_at.desc())
    ).first()
    if not boundary:
        raise HTTPException(status_code=404, detail="Boundary not found")
    return boundary


@router.post("", response_model=Boundary)
def create_boundary(
    payload: BoundaryCreate,
    session: Session = Depends(get_session),
) -> Boundary:
    boundary = Boundary(**payload.model_dump())
    boundary.reviewed_at = datetime.now(timezone.utc) if boundary.reviewed_by else None
    session.add(boundary)
    session.commit()
    session.refresh(boundary)
    return boundary


@router.patch("/{boundary_id}", response_model=Boundary)
def update_boundary(
    boundary_id: str,
    payload: BoundaryUpdate,
    session: Session = Depends(get_session),
) -> Boundary:
    boundary = session.get(Boundary, boundary_id)
    if not boundary:
        raise HTTPException(status_code=404, detail="Boundary not found")
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(boundary, key, value)
    boundary.reviewed_at = datetime.now(timezone.utc)
    session.add(boundary)
    session.commit()
    session.refresh(boundary)
    return boundary
