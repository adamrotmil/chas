from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from app.db.session import get_session
from app.models import Asset
from app.schemas import AssetCreate, AssetUpdate

router = APIRouter(prefix="/assets", tags=["assets"])


def _asset_or_404(session: Session, asset_id: str) -> Asset:
    asset = session.get(Asset, asset_id)
    if not asset:
        asset = session.exec(select(Asset).where(Asset.human_id == asset_id)).first()
    if not asset:
        raise HTTPException(status_code=404, detail="Asset not found")
    return asset


@router.get("", response_model=List[Asset])
def list_assets(
    asset_type: Optional[str] = None,
    session: Session = Depends(get_session),
) -> List[Asset]:
    statement = select(Asset).order_by(Asset.created_at.desc())
    if asset_type:
        statement = statement.where(Asset.asset_type == asset_type)
    return session.exec(statement).all()


@router.post("", response_model=Asset)
def create_asset(payload: AssetCreate, session: Session = Depends(get_session)) -> Asset:
    asset = Asset(**payload.model_dump())
    session.add(asset)
    session.commit()
    session.refresh(asset)
    return asset


@router.get("/{asset_id}", response_model=Asset)
def get_asset(asset_id: str, session: Session = Depends(get_session)) -> Asset:
    return _asset_or_404(session, asset_id)


@router.patch("/{asset_id}", response_model=Asset)
def update_asset(
    asset_id: str,
    payload: AssetUpdate,
    session: Session = Depends(get_session),
) -> Asset:
    asset = _asset_or_404(session, asset_id)
    updates = payload.model_dump(exclude_unset=True)
    for key, value in updates.items():
        setattr(asset, key, value)
    asset.updated_at = datetime.now(timezone.utc)
    session.add(asset)
    session.commit()
    session.refresh(asset)
    return asset
