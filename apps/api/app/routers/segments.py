from typing import List, Optional

from fastapi import APIRouter, Depends, Query
from sqlmodel import Session, select

from app.db.session import get_session
from app.models import Segment

router = APIRouter(prefix="/segments", tags=["segments"])


def _segment_sort_key(segment: Segment) -> tuple[int, str]:
    chunk_index = segment.locator.get("chunk_index") if isinstance(segment.locator, dict) else None
    return (chunk_index if isinstance(chunk_index, int) else 0, segment.created_at.isoformat())


@router.get("", response_model=List[Segment])
def list_segments(
    asset_id: Optional[str] = None,
    segment_type: Optional[str] = None,
    text_extraction_derivative_id: Optional[str] = None,
    limit: int = Query(default=500, ge=1, le=1000),
    session: Session = Depends(get_session),
) -> List[Segment]:
    statement = select(Segment)
    if asset_id:
        statement = statement.where(Segment.asset_id == asset_id)
    if segment_type:
        statement = statement.where(Segment.segment_type == segment_type)

    segments = session.exec(statement).all()
    if text_extraction_derivative_id:
        segments = [
            segment
            for segment in segments
            if (
                isinstance(segment.metadata_json, dict)
                and segment.metadata_json.get("text_extraction_derivative_id") == text_extraction_derivative_id
            )
            or (
                isinstance(segment.locator, dict)
                and segment.locator.get("text_extraction_derivative_id") == text_extraction_derivative_id
            )
        ]
    return sorted(segments, key=_segment_sort_key)[:limit]
