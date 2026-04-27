from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, RedirectResponse
from sqlmodel import Session, select

from app.config import settings
from app.db.session import get_session
from app.models import (
    Annotation,
    AntiPattern,
    Asset,
    AssetSnapshot,
    Boundary,
    ContextPack,
    ContextPackItem,
    DPOPair,
    Derivative,
    EvalCase,
    ExternalRef,
    GoldVoiceExample,
    MetadataProfile,
    ObjectFile,
    Segment,
    SFTCandidate,
    StyleRule,
    Task,
)
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


def _dump(model: Any) -> Dict[str, Any]:
    return model.model_dump(mode="json")


def _image_derivative(session: Session, asset_id: str, variant: str) -> Optional[Derivative]:
    derivatives = session.exec(
        select(Derivative)
        .where(Derivative.asset_id == asset_id)
        .where(Derivative.derivative_type == "image_preview")
        .where(Derivative.status == "ready")
    ).all()
    matches = [item for item in derivatives if item.metadata_json.get("variant") == variant]
    if not matches:
        return None
    return sorted(matches, key=lambda item: item.created_at, reverse=True)[0]


def _file_response_for_object(
    *,
    object_file: ObjectFile,
    asset: Asset,
    filename: str,
    missing_detail: str,
) -> Optional[FileResponse]:
    content_type = object_file.content_type or asset.mime_type or ""
    if not content_type.startswith("image/"):
        raise HTTPException(status_code=415, detail="Preview object is not an image")

    storage_root = Path(settings.storage_root).resolve()
    if object_file.storage_provider == "local":
        preview_path = (storage_root / object_file.object_key).resolve()
    elif object_file.storage_provider == "gcs":
        cache_key = object_file.metadata_json.get("local_preview_cache_key")
        preview_path = (storage_root / cache_key).resolve() if isinstance(cache_key, str) else None
    else:
        preview_path = None

    if preview_path is None:
        return None
    if not preview_path.is_relative_to(storage_root) or not preview_path.is_file():
        raise HTTPException(status_code=404, detail=missing_detail)

    return FileResponse(preview_path, media_type=content_type, filename=filename)


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


@router.get("/{asset_id}/dossier")
def get_asset_dossier(asset_id: str, session: Session = Depends(get_session)) -> Dict[str, Any]:
    asset = _asset_or_404(session, asset_id)
    segments = session.exec(select(Segment).where(Segment.asset_id == asset.id).order_by(Segment.created_at.asc())).all()
    segment_ids = [segment.id for segment in segments]
    target_ids = [asset.id, *segment_ids]

    snapshots = session.exec(
        select(AssetSnapshot).where(AssetSnapshot.asset_id == asset.id).order_by(AssetSnapshot.version.asc())
    ).all()
    derivatives = session.exec(
        select(Derivative).where(Derivative.asset_id == asset.id).order_by(Derivative.created_at.asc())
    ).all()
    object_file_ids = {
        object_file_id
        for object_file_id in [
            *(snapshot.object_file_id for snapshot in snapshots),
            *(derivative.object_file_id for derivative in derivatives),
        ]
        if object_file_id
    }
    object_files = (
        session.exec(select(ObjectFile).where(ObjectFile.id.in_(object_file_ids)).order_by(ObjectFile.created_at.asc())).all()
        if object_file_ids
        else []
    )
    boundaries = session.exec(
        select(Boundary).where(Boundary.target_id.in_(target_ids)).order_by(Boundary.created_at.asc())
    ).all()
    tasks = session.exec(
        select(Task).where(Task.target_id.in_(target_ids)).order_by(Task.created_at.asc())
    ).all()
    task_ids = [task.id for task in tasks]
    annotations = session.exec(
        select(Annotation)
        .where((Annotation.target_id.in_(target_ids)) | (Annotation.task_id.in_(task_ids)))
        .order_by(Annotation.created_at.asc())
    ).all()
    metadata_profiles = session.exec(
        select(MetadataProfile).where(MetadataProfile.target_id.in_(target_ids)).order_by(MetadataProfile.updated_at.asc())
    ).all()
    external_refs = session.exec(
        select(ExternalRef).where(ExternalRef.asset_id == asset.id).order_by(ExternalRef.created_at.asc())
    ).all()
    context_pack_items = session.exec(
        select(ContextPackItem).where(ContextPackItem.item_id.in_(target_ids)).order_by(ContextPackItem.rank.asc())
    ).all()
    context_pack_ids = {item.context_pack_id for item in context_pack_items}
    context_packs = (
        session.exec(select(ContextPack).where(ContextPack.id.in_(context_pack_ids)).order_by(ContextPack.created_at.asc())).all()
        if context_pack_ids
        else []
    )
    gold_examples = (
        session.exec(
            select(GoldVoiceExample)
            .where(GoldVoiceExample.context_pack_id.in_(context_pack_ids))
            .order_by(GoldVoiceExample.created_at.asc())
        ).all()
        if context_pack_ids
        else []
    )
    gold_ids = {gold.id for gold in gold_examples}
    sft_candidates = (
        session.exec(
            select(SFTCandidate)
            .where(SFTCandidate.source_gold_voice_example_id.in_(gold_ids))
            .order_by(SFTCandidate.created_at.asc())
        ).all()
        if gold_ids
        else []
    )
    dpo_pairs = (
        session.exec(
            select(DPOPair)
            .where(DPOPair.source_gold_voice_example_id.in_(gold_ids))
            .order_by(DPOPair.created_at.asc())
        ).all()
        if gold_ids
        else []
    )
    eval_cases = (
        session.exec(select(EvalCase).where(EvalCase.gold_reference_id.in_(gold_ids)).order_by(EvalCase.created_at.asc())).all()
        if gold_ids
        else []
    )
    anti_patterns = (
        session.exec(
            select(AntiPattern)
            .where(AntiPattern.source_gold_voice_example_id.in_(gold_ids))
            .order_by(AntiPattern.created_at.asc())
        ).all()
        if gold_ids
        else []
    )
    style_rules = (
        session.exec(
            select(StyleRule)
            .where(StyleRule.source_gold_voice_example_id.in_(gold_ids))
            .order_by(StyleRule.created_at.asc())
        ).all()
        if gold_ids
        else []
    )

    return {
        "asset": _dump(asset),
        "external_refs": [_dump(item) for item in external_refs],
        "snapshots": [_dump(item) for item in snapshots],
        "object_files": [_dump(item) for item in object_files],
        "derivatives": [_dump(item) for item in derivatives],
        "segments": [_dump(item) for item in segments],
        "boundaries": [_dump(item) for item in boundaries],
        "tasks": [_dump(item) for item in tasks],
        "annotations": [_dump(item) for item in annotations],
        "metadata_profiles": [_dump(item) for item in metadata_profiles],
        "context_packs": [_dump(item) for item in context_packs],
        "context_pack_items": [_dump(item) for item in context_pack_items],
        "gold_voice_examples": [_dump(item) for item in gold_examples],
        "sft_candidates": [_dump(item) for item in sft_candidates],
        "dpo_pairs": [_dump(item) for item in dpo_pairs],
        "eval_cases": [_dump(item) for item in eval_cases],
        "anti_patterns": [_dump(item) for item in anti_patterns],
        "style_rules": [_dump(item) for item in style_rules],
        "counts": {
            "segments": len(segments),
            "snapshots": len(snapshots),
            "derivatives": len(derivatives),
            "tasks": len(tasks),
            "annotations": len(annotations),
            "metadata_profiles": len(metadata_profiles),
            "boundaries": len(boundaries),
            "context_packs": len(context_packs),
            "gold_voice_examples": len(gold_examples),
            "sft_candidates": len(sft_candidates),
            "dpo_pairs": len(dpo_pairs),
            "eval_cases": len(eval_cases),
            "anti_patterns": len(anti_patterns),
            "style_rules": len(style_rules),
        },
    }


@router.get("/{asset_id}/preview")
def preview_asset(
    asset_id: str,
    variant: str = Query(default="display", pattern="^(thumbnail|display|original)$"),
    session: Session = Depends(get_session),
) -> FileResponse:
    asset = _asset_or_404(session, asset_id)
    if variant != "original":
        variant_order = list(dict.fromkeys([variant, "display", "thumbnail"]))
        for derivative_variant in variant_order:
            derivative = _image_derivative(session, asset.id, derivative_variant)
            if derivative and derivative.object_file_id:
                object_file = session.get(ObjectFile, derivative.object_file_id)
                if object_file:
                    filename = (
                        asset.original_filename
                        or asset.title
                        or object_file.object_key.rsplit("/", 1)[-1]
                    )
                    response = _file_response_for_object(
                        object_file=object_file,
                        asset=asset,
                        filename=filename,
                        missing_detail="Preview derivative file is missing",
                    )
                    if response:
                        return response

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
    filename = asset.original_filename or asset.title or object_file.object_key.rsplit("/", 1)[-1]
    response = _file_response_for_object(
        object_file=object_file,
        asset=asset,
        filename=filename,
        missing_detail="Mirrored preview file is missing",
    )
    if response:
        return response

    if object_file.storage_provider == "gcs":
        thumbnail_link = _drive_thumbnail_link(session, asset.id)
        if thumbnail_link:
            return RedirectResponse(thumbnail_link, status_code=307)
        raise HTTPException(status_code=404, detail="No local cache or signed preview is available for this GCS object")

    raise HTTPException(status_code=404, detail="Mirrored preview file is missing")


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
