from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlmodel import Session, select

from app.config import settings
from app.db.session import get_session
from app.models import Asset
from app.schemas import AssetCreate, AssetMirrorResponse, AssetUpdate
from app.services.asset_mirror import mirror_upload_for_asset

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


@router.post("/{asset_id}/mirror/upload", response_model=AssetMirrorResponse)
async def upload_asset_mirror(
    asset_id: str,
    file: UploadFile = File(...),
    source_system: str = Form(default="google_drive"),
    source_uri: Optional[str] = Form(default=None),
    drive_file_id: Optional[str] = Form(default=None),
    drive_mime_type: Optional[str] = Form(default=None),
    export_mime_type: Optional[str] = Form(default=None),
    source_modified_time: Optional[datetime] = Form(default=None),
    storage_access_token: Optional[str] = Form(default=None),
    session: Session = Depends(get_session),
) -> AssetMirrorResponse:
    asset = _asset_or_404(session, asset_id)
    try:
        mirrored = await mirror_upload_for_asset(
            session,
            asset,
            file,
            storage_root=Path(settings.storage_root),
            storage_provider=settings.object_storage_provider,
            gcs_bucket=settings.gcs_bucket,
            gcs_prefix=settings.gcs_prefix,
            storage_access_token=storage_access_token,
            source_system=source_system,
            source_uri=source_uri,
            drive_file_id=drive_file_id,
            drive_mime_type=drive_mime_type,
            export_mime_type=export_mime_type,
            source_modified_time=source_modified_time,
        )
    except OSError as exc:
        session.rollback()
        raise HTTPException(status_code=500, detail=f"Unable to write mirror file: {exc}") from exc
    except ValueError as exc:
        session.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    session.commit()
    return mirrored
