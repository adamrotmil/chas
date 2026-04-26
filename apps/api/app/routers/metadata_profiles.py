from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from app.db.session import get_session
from app.models import MetadataProfile
from app.schemas import MetadataProfileCreate, MetadataProfileUpdate

router = APIRouter(prefix="/metadata-profiles", tags=["metadata-profiles"])


def _profile_or_404(session: Session, profile_id: str) -> MetadataProfile:
    profile = session.get(MetadataProfile, profile_id)
    if not profile:
        raise HTTPException(status_code=404, detail="Metadata profile not found")
    return profile


def _maybe_reviewed_at(profile: MetadataProfile) -> None:
    if profile.reviewed_by or profile.metadata_status in {"adam_reviewed", "approved"}:
        profile.reviewed_at = datetime.now(timezone.utc)


@router.get("", response_model=List[MetadataProfile])
def list_metadata_profiles(
    target_type: Optional[str] = None,
    target_id: Optional[str] = None,
    profile_type: Optional[str] = None,
    metadata_status: Optional[str] = None,
    limit: int = 100,
    session: Session = Depends(get_session),
) -> List[MetadataProfile]:
    statement = select(MetadataProfile).order_by(MetadataProfile.updated_at.desc())
    if target_type:
        statement = statement.where(MetadataProfile.target_type == target_type)
    if target_id:
        statement = statement.where(MetadataProfile.target_id == target_id)
    if profile_type:
        statement = statement.where(MetadataProfile.profile_type == profile_type)
    if metadata_status:
        statement = statement.where(MetadataProfile.metadata_status == metadata_status)
    return session.exec(statement.limit(min(max(limit, 1), 500))).all()


@router.post("", response_model=MetadataProfile)
def create_metadata_profile(
    payload: MetadataProfileCreate,
    session: Session = Depends(get_session),
) -> MetadataProfile:
    profile = MetadataProfile(**payload.model_dump())
    _maybe_reviewed_at(profile)
    session.add(profile)
    session.commit()
    session.refresh(profile)
    return profile


@router.get("/{profile_id}", response_model=MetadataProfile)
def get_metadata_profile(profile_id: str, session: Session = Depends(get_session)) -> MetadataProfile:
    return _profile_or_404(session, profile_id)


@router.patch("/{profile_id}", response_model=MetadataProfile)
def update_metadata_profile(
    profile_id: str,
    payload: MetadataProfileUpdate,
    session: Session = Depends(get_session),
) -> MetadataProfile:
    profile = _profile_or_404(session, profile_id)
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(profile, key, value)
    profile.updated_at = datetime.now(timezone.utc)
    _maybe_reviewed_at(profile)
    session.add(profile)
    session.commit()
    session.refresh(profile)
    return profile
