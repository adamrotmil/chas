from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlmodel import Session

from app.config import Settings, get_settings
from app.db.session import get_session
from app.services.ai_spine_audit import compile_ai_spine_audit

router = APIRouter(prefix="/ai-spine", tags=["ai spine"])


@router.get("/audit")
def get_ai_spine_audit(
    app_settings: Settings = Depends(get_settings),
    session: Session = Depends(get_session),
) -> dict:
    return compile_ai_spine_audit(session=session, app_settings=app_settings)
