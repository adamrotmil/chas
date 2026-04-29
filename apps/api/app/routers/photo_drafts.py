from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlmodel import Session

from app.db.session import get_session
from app.services.photo_memory_drafts import create_photo_memory_drafts, create_photo_prompt_pair_candidates

router = APIRouter(prefix="/photo-memory-drafts", tags=["photo memory drafts"])


@router.post("")
def create_drafts(
    limit: int = 5,
    dry_run: bool = True,
    session: Session = Depends(get_session),
) -> dict:
    return create_photo_memory_drafts(session=session, limit=limit, dry_run=dry_run)


@router.post("/prompt-pair-candidates")
def create_prompt_pair_candidates(
    limit: int = 5,
    dry_run: bool = True,
    session: Session = Depends(get_session),
) -> dict:
    return create_photo_prompt_pair_candidates(session=session, limit=limit, dry_run=dry_run)
