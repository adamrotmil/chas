from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, RedirectResponse
from sqlmodel import Session, select

from app.config import settings
from app.db.session import get_session
from app.models import Asset, AssetSnapshot, ExternalRef, ObjectFile
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


def _drive_thumbnail_link(session: Session, asset_id: str) -> Optional[str]:
    external_ref = session.exec(
        select(ExternalRef)
        .where(ExternalRef.asset_id == asset_id)
        .where(ExternalRef.source_system == "google_drive")
    ).first()
    if not external_ref:
        return None
    thumbnail = external_ref.metadata_json.get("drive_thumbnail_link")
    return thumbnail if isinstance(thumbnail, str) and thumbnail.startswith("https://") else None


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


@router.get("/{asset_id}/preview")
def preview_asset(asset_id: str, session: Session = Depends(get_session)) -> FileResponse:
    asset = _asset_or_404(session, asset_id)
    snapshot = session.exec(
        select(AssetSnapshot)
        .where(AssetSnapshot.asset_id == asset.id)
        .where(AssetSnapshot.snapshot_type == "source_mirror")
        .order_by(AssetSnapshot.version.desc())
    ).first()
    if snapshot is None or snapshot.object_file_id is None:
        thumbnail_link = _drive_thumbnail_link(session, asset.id)
        if thumbnail_link:
            return RedirectResponse(thumbnail_link, status_code=307)
        raise HTTPException(status_code=404, detail="No mirrored preview file found")

    object_file = session.get(ObjectFile, snapshot.object_file_id)
    if object_file is None:
        raise HTTPException(status_code=404, detail="Mirrored preview file not found")
    content_type = object_file.content_type or asset.mime_type or ""
    if not content_type.startswith("image/"):
        raise HTTPException(status_code=415, detail="Mirrored file is not an image")
    if object_file.storage_provider != "local":
        thumbnail_link = _drive_thumbnail_link(session, asset.id)
        if thumbnail_link:
            return RedirectResponse(thumbnail_link, status_code=307)
        raise HTTPException(status_code=404, detail="Preview is only available for local mirrored files")

    storage_root = Path(settings.storage_root).resolve()
    preview_path = (storage_root / object_file.object_key).resolve()
    if not preview_path.is_relative_to(storage_root) or not preview_path.is_file():
        raise HTTPException(status_code=404, detail="Mirrored preview file is missing")

    return FileResponse(
        preview_path,
        media_type=content_type,
        filename=asset.original_filename or asset.title or object_file.object_key.rsplit("/", 1)[-1],
    )


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
