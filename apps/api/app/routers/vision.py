from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlmodel import Session

from app.config import settings
from app.db.session import get_session
from app.schemas import VisionDraftBatchRequest, VisionDraftBatchResponse
from app.services.vision import VISION_DRAFT_SCHEMA, create_vision_draft_batch

router = APIRouter(prefix="/vision", tags=["vision"])


@router.get("/schema")
def get_vision_schema() -> dict:
    return {
        "structured_output": VISION_DRAFT_SCHEMA,
        "truth_status": "system_inference",
        "review_required": True,
        "live_calls_enabled": settings.vision_live_calls_enabled,
        "default_model": settings.vision_model,
    }


@router.post("/drafts/batches", response_model=VisionDraftBatchResponse)
def create_vision_draft_batch_endpoint(
    payload: VisionDraftBatchRequest,
    session: Session = Depends(get_session),
) -> VisionDraftBatchResponse:
    result = create_vision_draft_batch(
        session=session,
        asset_ids=payload.asset_ids,
        limit=payload.limit,
        queue=payload.queue,
        draft_type=payload.draft_type,
        model_name=payload.model_name or settings.vision_model,
        input_detail=payload.input_detail,
        no_live_model_call=payload.no_live_model_call,
    )
    session.commit()
    return VisionDraftBatchResponse(**result)
