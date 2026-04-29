import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Response, UploadFile
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
    EmbeddingRecord,
    EvalCase,
    ExternalRef,
    GoldVoiceExample,
    MetadataProfile,
    ObjectFile,
    Segment,
    SFTCandidate,
    StyleRule,
    Task,
    TaskReceipt,
    VoiceReferenceExample,
)
from app.schemas import (
    AssetCreate,
    AssetMirrorResponse,
    AssetUpdate,
    AssetUploadResponse,
    PhotoContextTaskCreate,
    PhotoContextTaskCreateResponse,
)
from app.services.asset_mirror import mirror_upload_for_asset
from app.services.photo_context_progress import (
    build_photo_context_retrieval_gap_payoff_preview,
    build_photo_context_retrieval_gap_field_worklist,
    build_photo_context_session_progress_artifact,
    build_photo_context_session_progress,
)
from app.services.photo_context_review_pack import (
    build_photo_context_review_pack,
    build_photo_context_review_session_plan,
    build_photo_context_top_slice,
)
from app.services.photo_review_priority import build_photo_review_priority_summary

router = APIRouter(prefix="/assets", tags=["assets"])


def _asset_or_404(session: Session, asset_id: str) -> Asset:
    asset = session.get(Asset, asset_id)
    if not asset:
        asset = session.exec(select(Asset).where(Asset.human_id == asset_id)).first()
    if not asset:
        raise HTTPException(status_code=404, detail="Asset not found")
    return asset


def _safe_human_id_part(value: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9]+", "_", value).strip("_").upper()
    return safe[:32] or "ARTIFACT"


def _count(session: Session, model: Any) -> int:
    return len(session.exec(select(model)).all()) + 1


def _asset_type_for_upload(content_type: Optional[str], filename: str) -> str:
    mime = (content_type or "").lower()
    lowered_name = filename.lower()
    if mime.startswith("image/"):
        return "photo"
    if mime.startswith("audio/"):
        return "audio"
    if mime.startswith("video/"):
        return "video"
    if (
        mime.startswith("text/")
        or mime == "application/pdf"
        or mime in {
            "application/json",
            "application/rtf",
            "application/x-yaml",
            "application/yaml",
            "text/yaml",
            "application/msword",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        }
        or lowered_name.endswith((".doc", ".docx", ".eml", ".htm", ".html", ".md", ".pdf", ".rtf", ".txt", ".yaml", ".yml"))
    ):
        return "text"
    return "file"


def _direct_upload_storage_provider(storage_access_token: Optional[str]) -> str:
    provider = settings.object_storage_provider.lower()
    if provider == "gcs" and not storage_access_token:
        return "local"
    return provider


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


def _photo_title(asset: Asset) -> str:
    return asset.title or asset.original_filename or asset.human_id


def _photo_group_key(asset: Asset) -> str:
    stem = Path(_photo_title(asset)).stem.lower()
    stem = re.sub(r"\s+-\s+copy(?:\s+-\s+copy)*", "", stem)
    stem = re.sub(r"\s*\(\d+\)\s*", " ", stem)
    stem = re.sub(r"\bcopy\b", "", stem)
    stem = re.sub(r"[^a-z0-9]+", " ", stem)
    return re.sub(r"\s+", " ", stem).strip() or asset.id


def _is_copy_variant(asset: Asset) -> bool:
    title = _photo_title(asset).lower()
    return "copy" in title or bool(re.search(r"\(\d+\)", title))


def _canonical_photo_asset(assets: List[Asset]) -> Asset:
    return sorted(assets, key=lambda asset: (_is_copy_variant(asset), len(_photo_title(asset)), _photo_title(asset)))[0]


def _retrieval_gap_review_fields(source_query: str) -> List[Dict[str, str]]:
    return [
        {
            "field_key": "visual_description_correction",
            "label": "Visible facts",
            "reason": "Describe only what the image shows before adding memory or interpretation.",
        },
        {
            "field_key": "retrieval_query_relevance",
            "label": "Connection to retrieval query",
            "reason": f"Say what, if anything, connects this photo to '{source_query}'. The query itself is not evidence.",
        },
        {
            "field_key": "invisible_context_note",
            "label": "Adam context",
            "reason": "Add the memory, relationship, place, or event that a viewer could not infer from pixels.",
        },
        {
            "field_key": "open_questions",
            "label": "Uncertainty",
            "reason": "Preserve unresolved details as uncertainty rather than turning them into source truth.",
        },
        {
            "field_key": "privacy_level",
            "label": "Boundary",
            "reason": "Choose retrieval, gallery, and downstream permissions before vector handoff.",
        },
    ]


def _photo_context_questions(asset: Asset, group_assets: List[Asset], source_query: Optional[str] = None) -> List[Dict[str, str]]:
    title = _photo_title(asset)
    variant_note = (
        f"This group has {len(group_assets)} file variants; answer for the canonical image, not each duplicate."
        if len(group_assets) > 1
        else "Answer for this photo."
    )
    questions = [
        {
            "id": "visible_facts",
            "question": "What is visibly present in the photograph?",
            "reason": "Keeps visual description separate from memory or inference.",
        },
        {
            "id": "invisible_context",
            "question": "What does Adam know about this photo that is not visible in the pixels?",
            "reason": "This becomes Adam-provided memory context for retrieval and future voice context packs.",
        },
    ]
    if source_query:
        questions.append(
            {
                "id": "retrieval_query_relevance",
                "question": f"What, if anything, connects this photo to the retrieval query '{source_query}'?",
                "reason": "The query is only workflow provenance. Adam's answer is what can make this searchable memory context.",
            }
        )
    questions.extend(
        [
            {
                "id": "meaning",
                "question": f"What memory, story, relationship, or event does {title} anchor?",
                "reason": "Turns the image into a searchable memory record rather than a loose file.",
            },
            {
                "id": "uncertainty",
                "question": "What should remain uncertain or be checked later?",
                "reason": f"{variant_note} Unanswered uncertainty is stored as open questions, not source truth.",
            },
        ]
    )
    return questions


def _existing_photo_context_task(session: Session, asset_id: str) -> Optional[Task]:
    return session.exec(
        select(Task)
        .where(Task.task_type == "photo_context")
        .where(Task.target_type == "asset")
        .where(Task.target_id == asset_id)
        .where(Task.status == "ready")
        .order_by(Task.created_at.asc())
    ).first()


def _photo_memory_profile_for_asset(session: Session, asset_id: str) -> Optional[MetadataProfile]:
    return session.exec(
        select(MetadataProfile)
        .where(MetadataProfile.target_type == "asset")
        .where(MetadataProfile.target_id == asset_id)
        .where(MetadataProfile.profile_type == "photo_memory")
    ).first()


def _asset_for_photo_context_request(
    session: Session,
    payload: PhotoContextTaskCreate,
) -> tuple[Asset, str]:
    if payload.asset_id:
        asset = _asset_or_404(session, payload.asset_id)
        if asset.asset_type != "photo":
            raise HTTPException(status_code=400, detail="asset_id must reference a photo asset")
        return asset, _photo_group_key(asset)
    if payload.group_key:
        photos = session.exec(select(Asset).where(Asset.asset_type == "photo")).all()
        matches = [asset for asset in photos if _photo_group_key(asset) == payload.group_key]
        if not matches:
            raise HTTPException(status_code=404, detail="Photo group not found")
        existing_profile = None
        for asset in matches:
            existing_profile = _photo_memory_profile_for_asset(session, asset.id)
            if existing_profile:
                break
        if existing_profile:
            raise HTTPException(status_code=409, detail="Photo group already has a photo-memory profile")
        return _canonical_photo_asset(matches) if payload.use_canonical else matches[0], payload.group_key
    raise HTTPException(status_code=400, detail="asset_id or group_key is required")


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


@router.post("/upload", response_model=AssetUploadResponse)
async def upload_artifact(
    file: UploadFile = File(...),
    title: Optional[str] = Form(default=None),
    asset_type: Optional[str] = Form(default=None),
    source_system: str = Form(default="local_upload"),
    source_uri: Optional[str] = Form(default=None),
    source_modified_time: Optional[datetime] = Form(default=None),
    storage_access_token: Optional[str] = Form(default=None),
    session: Session = Depends(get_session),
) -> AssetUploadResponse:
    filename = file.filename or "uploaded_artifact"
    resolved_title = title.strip() if title and title.strip() else filename
    resolved_asset_type = asset_type.strip() if asset_type and asset_type.strip() else _asset_type_for_upload(file.content_type, filename)
    human_id = f"UPL_{_safe_human_id_part(Path(filename).stem)}_{uuid.uuid4().hex[:10].upper()}"
    asset = Asset(
        human_id=human_id,
        asset_type=resolved_asset_type,
        title=resolved_title,
        original_filename=filename,
        mime_type=file.content_type,
        source_system=source_system,
        source_modified_time=source_modified_time,
        import_status="upload_received",
        processing_status="ready",
        maturity_level="L0_source_seen",
    )
    session.add(asset)
    session.flush()

    boundary = Boundary(
        target_type="asset",
        target_id=asset.id,
        privacy_level="unreviewed",
        notes="Default unreviewed boundary created during direct artifact upload.",
    )
    session.add(boundary)
    session.flush()

    try:
        mirror = await mirror_upload_for_asset(
            session,
            asset,
            file,
            storage_root=Path(settings.storage_root),
            storage_provider=_direct_upload_storage_provider(storage_access_token),
            gcs_bucket=settings.gcs_bucket,
            gcs_prefix=settings.gcs_prefix,
            storage_access_token=storage_access_token,
            source_system=source_system,
            source_uri=source_uri or f"upload://{filename}",
            export_mime_type=file.content_type,
            source_modified_time=source_modified_time,
        )
    except OSError as exc:
        session.rollback()
        raise HTTPException(status_code=500, detail=f"Unable to write uploaded artifact: {exc}") from exc
    except ValueError as exc:
        session.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    segments = session.exec(select(Segment).where(Segment.asset_id == asset.id).order_by(Segment.created_at.asc())).all()
    target_ids = [asset.id, *(segment.id for segment in segments)]
    review_tasks = session.exec(
        select(Task).where(Task.target_id.in_(target_ids)).order_by(Task.created_at.asc())
    ).all()
    session.commit()
    return AssetUploadResponse(
        asset_id=asset.id,
        human_id=asset.human_id,
        title=asset.title or filename,
        asset_type=asset.asset_type,
        boundary_id=boundary.id,
        mirror=mirror,
        segment_ids=[segment.id for segment in segments],
        review_task_ids=[task.id for task in review_tasks],
    )


@router.get("/photo-review-inventory")
def photo_review_inventory(
    limit: int = Query(default=100, ge=1, le=500),
    session: Session = Depends(get_session),
) -> Dict[str, Any]:
    photos = session.exec(select(Asset).where(Asset.asset_type == "photo").order_by(Asset.created_at.asc())).all()
    photo_ids = [asset.id for asset in photos]
    profiles = (
        session.exec(
            select(MetadataProfile)
            .where(MetadataProfile.target_type == "asset")
            .where(MetadataProfile.target_id.in_(photo_ids))
            .where(MetadataProfile.profile_type == "photo_memory")
        ).all()
        if photo_ids
        else []
    )
    tasks = (
        session.exec(select(Task).where(Task.target_id.in_(photo_ids)).order_by(Task.created_at.asc())).all()
        if photo_ids
        else []
    )
    boundaries = (
        session.exec(
            select(Boundary)
            .where(Boundary.target_type == "asset")
            .where(Boundary.target_id.in_(photo_ids))
        ).all()
        if photo_ids
        else []
    )
    profile_by_asset = {profile.target_id: profile for profile in profiles}
    boundary_by_asset = {boundary.target_id: boundary for boundary in boundaries}
    tasks_by_asset: Dict[str, List[Task]] = {}
    for task in tasks:
        tasks_by_asset.setdefault(task.target_id, []).append(task)

    grouped: Dict[str, List[Asset]] = {}
    for asset in photos:
        grouped.setdefault(_photo_group_key(asset), []).append(asset)

    groups: List[Dict[str, Any]] = []
    for key, group_assets in grouped.items():
        canonical = _canonical_photo_asset(group_assets)
        group_profiles = [profile_by_asset[asset.id] for asset in group_assets if asset.id in profile_by_asset]
        covering_profile = group_profiles[0] if group_profiles else None
        variants = []
        for asset in sorted(group_assets, key=lambda item: (_is_copy_variant(item), _photo_title(item))):
            profile = profile_by_asset.get(asset.id)
            boundary = boundary_by_asset.get(asset.id)
            ready_tasks = [
                task
                for task in tasks_by_asset.get(asset.id, [])
                if task.status == "ready"
                and task.task_type in {"photo_context", "vision_draft_review", "asset_triage"}
            ]
            variants.append(
                {
                    "asset_id": asset.id,
                    "human_id": asset.human_id,
                    "title": _photo_title(asset),
                    "original_filename": asset.original_filename,
                    "import_status": asset.import_status,
                    "processing_status": asset.processing_status,
                    "preview_ready": asset.processing_status == "image_preview_ready",
                    "is_copy_variant": _is_copy_variant(asset),
                    "profile_id": profile.id if profile else None,
                    "covered_by_group_profile_id": None if profile else (covering_profile.id if covering_profile else None),
                    "profile_status": profile.metadata_status if profile else ("covered_by_group_profile" if covering_profile else "missing"),
                    "truth_status": profile.truth_status if profile else (covering_profile.truth_status if covering_profile else "unreviewed"),
                    "boundary_privacy_level": boundary.privacy_level if boundary else "missing",
                    "ready_task_count": len(ready_tasks),
                }
            )
        preview_ready_count = len([asset for asset in group_assets if asset.processing_status == "image_preview_ready"])
        needs_context_count = 0 if group_profiles else preview_ready_count
        groups.append(
            {
                "group_key": key,
                "display_title": _photo_title(canonical),
                "canonical_asset_id": canonical.id,
                "asset_count": len(group_assets),
                "preview_ready_count": preview_ready_count,
                "profile_count": len(group_profiles),
                "needs_context_count": needs_context_count,
                "needs_context": preview_ready_count > 0 and len(group_profiles) == 0,
                "machine_draft_count": len(
                    [profile for profile in group_profiles if profile.metadata_status == "machine_draft_needs_adam_review"]
                ),
                "adam_reviewed_count": len(
                    [profile for profile in group_profiles if profile.metadata_status in {"adam_reviewed", "approved"}]
                ),
                "ready_task_count": sum(variant["ready_task_count"] for variant in variants),
                "variants": variants,
            }
        )
    groups.sort(
        key=lambda group: (
            group["needs_context"] is not True,
            -int(group["asset_count"]),
            str(group["display_title"]),
        )
    )
    duplicate_groups = [group for group in groups if int(group["asset_count"]) > 1]
    needs_context_groups = [group for group in groups if group["needs_context"] is True]
    return {
        "inventory_type": "photo_review_inventory",
        "photo_count": len(photos),
        "preview_ready_count": len([asset for asset in photos if asset.processing_status == "image_preview_ready"]),
        "profile_count": len(profiles),
        "machine_draft_profile_count": len(
            [profile for profile in profiles if profile.metadata_status == "machine_draft_needs_adam_review"]
        ),
        "adam_reviewed_profile_count": len(
            [profile for profile in profiles if profile.metadata_status in {"adam_reviewed", "approved"}]
        ),
        "needs_context_count": sum(int(group["needs_context_count"]) for group in groups),
        "needs_context_group_count": len(needs_context_groups),
        "group_count": len(groups),
        "duplicate_group_count": len(duplicate_groups),
        "groups": groups[:limit],
        "duplicate_groups": duplicate_groups[:limit],
    }


@router.get("/photo-context-review-pack")
def photo_context_review_pack(
    scope: str = Query(default="family_private", pattern="^(public|family_private|private)$"),
    limit: int = Query(default=100, ge=1, le=500),
    session: Session = Depends(get_session),
) -> Dict[str, Any]:
    return build_photo_context_review_pack(session=session, scope=scope, limit=limit)


@router.get("/photo-context-review-pack/top-context-slice")
def photo_context_top_slice(
    scope: str = Query(default="family_private", pattern="^(public|family_private|private)$"),
    limit: int = Query(default=5, ge=1, le=25),
    session: Session = Depends(get_session),
) -> Dict[str, Any]:
    return build_photo_context_top_slice(session=session, scope=scope, limit=limit)


@router.get("/photo-context-review-pack/session-progress")
def photo_context_review_session_progress(
    scope: str = Query(default="family_private", pattern="^(public|family_private|private)$"),
    limit: int = Query(default=100, ge=1, le=500),
    user_id: str = Query(default="adam"),
    session: Session = Depends(get_session),
) -> Dict[str, Any]:
    return build_photo_context_session_progress(session=session, scope=scope, limit=limit, user_id=user_id)


@router.get("/photo-context-review-pack/session-progress/artifact")
def photo_context_review_session_progress_artifact(
    scope: str = Query(default="family_private", pattern="^(public|family_private|private)$"),
    limit: int = Query(default=100, ge=1, le=500),
    user_id: str = Query(default="adam"),
    session: Session = Depends(get_session),
) -> Dict[str, Any]:
    return build_photo_context_session_progress_artifact(session=session, scope=scope, limit=limit, user_id=user_id)


@router.get("/photo-context-review-pack/retrieval-gap-field-worklist")
def photo_context_retrieval_gap_field_worklist(
    scope: str = Query(default="family_private", pattern="^(public|family_private|private)$"),
    limit: int = Query(default=100, ge=1, le=500),
    user_id: str = Query(default="adam"),
    session: Session = Depends(get_session),
) -> Dict[str, Any]:
    return build_photo_context_retrieval_gap_field_worklist(
        session=session,
        scope=scope,
        limit=limit,
        user_id=user_id,
    )


@router.get("/photo-context-review-pack/retrieval-gap-field-worklist/yaml")
def photo_context_retrieval_gap_field_worklist_yaml(
    scope: str = Query(default="family_private", pattern="^(public|family_private|private)$"),
    limit: int = Query(default=100, ge=1, le=500),
    user_id: str = Query(default="adam"),
    session: Session = Depends(get_session),
) -> Response:
    worklist = build_photo_context_retrieval_gap_field_worklist(
        session=session,
        scope=scope,
        limit=limit,
        user_id=user_id,
    )
    filename = f"charlesops_retrieval_gap_field_worklist_{scope}.yaml"
    return Response(
        content=worklist["export_preview_yaml"],
        media_type="text/yaml; charset=utf-8",
        headers={"Content-Disposition": f'inline; filename="{filename}"'},
    )


@router.get("/photo-context-review-pack/retrieval-gap-payoff-preview")
def photo_context_retrieval_gap_payoff_preview(
    scope: str = Query(default="family_private", pattern="^(public|family_private|private)$"),
    limit: int = Query(default=10, ge=1, le=50),
    user_id: str = Query(default="adam"),
    session: Session = Depends(get_session),
) -> Dict[str, Any]:
    return build_photo_context_retrieval_gap_payoff_preview(
        session=session,
        scope=scope,
        limit=limit,
        user_id=user_id,
    )


@router.get("/photo-context-review-pack/retrieval-gap-payoff-preview/yaml")
def photo_context_retrieval_gap_payoff_preview_yaml(
    scope: str = Query(default="family_private", pattern="^(public|family_private|private)$"),
    limit: int = Query(default=10, ge=1, le=50),
    user_id: str = Query(default="adam"),
    session: Session = Depends(get_session),
) -> Response:
    preview = build_photo_context_retrieval_gap_payoff_preview(
        session=session,
        scope=scope,
        limit=limit,
        user_id=user_id,
    )
    filename = f"charlesops_retrieval_gap_payoff_preview_{scope}.yaml"
    return Response(
        content=preview["export_preview_yaml"],
        media_type="text/yaml; charset=utf-8",
        headers={"Content-Disposition": f'inline; filename="{filename}"'},
    )


@router.get("/photo-context-review-pack/review-session-plan")
def photo_context_review_session_plan(
    scope: str = Query(default="family_private", pattern="^(public|family_private|private)$"),
    limit: int = Query(default=5, ge=1, le=25),
    source_query: str = Query(default="airplane in Maine", min_length=1, max_length=200),
    session: Session = Depends(get_session),
) -> Dict[str, Any]:
    return build_photo_context_review_session_plan(
        session=session,
        scope=scope,
        limit=limit,
        source_query=source_query,
    )


@router.get("/photo-context-review-pack/review-session-plan/yaml")
def photo_context_review_session_plan_yaml(
    scope: str = Query(default="family_private", pattern="^(public|family_private|private)$"),
    limit: int = Query(default=5, ge=1, le=25),
    source_query: str = Query(default="airplane in Maine", min_length=1, max_length=200),
    session: Session = Depends(get_session),
) -> Response:
    plan = build_photo_context_review_session_plan(
        session=session,
        scope=scope,
        limit=limit,
        source_query=source_query,
    )
    filename = f"charlesops_photo_context_review_session_{scope}.yaml"
    return Response(
        content=plan["export_preview_yaml"],
        media_type="text/yaml; charset=utf-8",
        headers={"Content-Disposition": f'inline; filename="{filename}"'},
    )


@router.get("/photo-review-priority")
def photo_review_priority(
    focus: str = Query(default="fastest_vector", pattern="^(all|fastest_vector)$"),
    limit: int = Query(default=10, ge=1, le=50),
    session: Session = Depends(get_session),
) -> Dict[str, Any]:
    return build_photo_review_priority_summary(session=session, focus=focus, limit=limit)


@router.post("/photo-review-inventory/context-task", response_model=PhotoContextTaskCreateResponse)
def create_photo_context_task_from_inventory(
    payload: PhotoContextTaskCreate,
    session: Session = Depends(get_session),
) -> PhotoContextTaskCreateResponse:
    asset, group_key = _asset_for_photo_context_request(session, payload)
    if asset.processing_status != "image_preview_ready":
        raise HTTPException(status_code=400, detail="Photo must have a ready preview before context review")
    if _photo_memory_profile_for_asset(session, asset.id):
        raise HTTPException(status_code=409, detail="Photo already has a photo-memory profile")

    source_query = payload.source_query.strip() if payload.source_query and payload.source_query.strip() else None
    review_session_origin = None
    if (
        payload.session_sequence_number is not None
        or payload.session_selected_count is not None
        or payload.session_plan_content_sha256
        or payload.session_completion_signal
    ):
        review_session_origin = {
            "session_type": "photo_context_review_session",
            "sequence_number": payload.session_sequence_number,
            "selected_count": payload.session_selected_count,
            "source_query": source_query,
            "plan_content_sha256": payload.session_plan_content_sha256,
            "completion_signal": payload.session_completion_signal,
            "review_policy": payload.session_review_policy or "query_aware_photo_context_session_plan_no_mutation",
            "not_memory_claim": True,
        }
    existing = _existing_photo_context_task(session, asset.id)
    if existing:
        if source_query or review_session_origin:
            next_payload = dict(existing.input_payload or {})
            if source_query:
                next_payload.setdefault(
                    "retrieval_gap_origin",
                    {
                        "query": source_query,
                        "candidate_match_quality": payload.candidate_match_quality or "unknown",
                        "selection_reason": payload.candidate_selection_reason or "unknown",
                        "truth_status": "no_claim",
                        "not_memory_claim": True,
                    },
                )
                review_plan = next_payload.get("retrieval_gap_review")
                review_fields = review_plan.get("required_fields") if isinstance(review_plan, dict) else None
                if not isinstance(review_plan, dict) or not isinstance(review_fields, list) or not review_fields:
                    next_payload["retrieval_gap_review"] = {
                        "query": source_query,
                        "review_policy": "retrieval_gap_no_claim_until_adam_context",
                        "not_memory_claim": True,
                        "completion_signal": "visual_facts_query_relevance_adam_context_uncertainty_boundary",
                        "required_fields": _retrieval_gap_review_fields(source_query),
                    }
                raw_questions = next_payload.get("suggested_questions", [])
                existing_questions = [item for item in raw_questions if isinstance(item, dict)] if isinstance(raw_questions, list) else []
                if not any(item.get("id") == "retrieval_query_relevance" for item in existing_questions):
                    next_payload["suggested_questions"] = _photo_context_questions(asset, [asset], source_query)
            if review_session_origin:
                next_payload["review_session_origin"] = review_session_origin
            existing.input_payload = next_payload
            session.add(existing)
            session.commit()
        return PhotoContextTaskCreateResponse(
            created=False,
            task_id=existing.id,
            task_human_id=existing.human_id,
            asset_id=asset.id,
            asset_title=_photo_title(asset),
            group_key=group_key,
            reason="existing_ready_photo_context_task",
        )

    group_assets = [
        item
        for item in session.exec(select(Asset).where(Asset.asset_type == "photo")).all()
        if _photo_group_key(item) == group_key
    ]
    task_input_payload = {
        "asset_id": asset.id,
        "asset_title": _photo_title(asset),
        "asset_type": asset.asset_type,
        "photo_group_key": group_key,
        "canonical_asset_id": asset.id,
        "group_variant_count": len(group_assets),
        "group_variants": [
            {
                "asset_id": item.id,
                "title": _photo_title(item),
                "is_copy_variant": _is_copy_variant(item),
                "processing_status": item.processing_status,
            }
            for item in sorted(group_assets, key=lambda item: (_is_copy_variant(item), _photo_title(item)))
        ],
        "suggested_questions": _photo_context_questions(asset, group_assets, source_query),
        "source_photo_inventory": True,
    }
    if source_query:
        task_input_payload["retrieval_gap_origin"] = {
            "query": source_query,
            "candidate_match_quality": payload.candidate_match_quality or "unknown",
            "selection_reason": payload.candidate_selection_reason or "unknown",
            "truth_status": "no_claim",
            "not_memory_claim": True,
        }
        task_input_payload["retrieval_gap_review"] = {
            "query": source_query,
            "review_policy": "retrieval_gap_no_claim_until_adam_context",
            "not_memory_claim": True,
            "completion_signal": "visual_facts_query_relevance_adam_context_uncertainty_boundary",
            "required_fields": _retrieval_gap_review_fields(source_query),
        }
    if review_session_origin:
        task_input_payload["review_session_origin"] = review_session_origin
    task = Task(
        human_id=f"TASK_PHOTO_CONTEXT_{_count(session, Task):06d}",
        task_type="photo_context",
        target_type="asset",
        target_id=asset.id,
        priority=84,
        queue="photo_assets_needing_context",
        reason_created="Created from photo review inventory so Adam can add context to a canonical preview-ready photo.",
        input_payload=task_input_payload,
        required_decisions=[
            "visual_description_correction",
            "invisible_context_note",
            "question_answers",
            "open_questions",
            "privacy_level",
            "ready_for_downstream",
        ],
        created_by="photo_review_inventory",
    )
    session.add(task)
    session.commit()
    session.refresh(task)
    return PhotoContextTaskCreateResponse(
        created=True,
        task_id=task.id,
        task_human_id=task.human_id,
        asset_id=asset.id,
        asset_title=_photo_title(asset),
        group_key=group_key,
        reason="created_photo_context_task",
    )


@router.post("/photo-context-review-pack/review-session")
def create_photo_context_review_session(
    scope: str = Query(default="family_private", pattern="^(public|family_private|private)$"),
    limit: int = Query(default=5, ge=1, le=25),
    dry_run: bool = Query(default=True),
    source_query: str = Query(default="airplane in Maine", min_length=1, max_length=200),
    session: Session = Depends(get_session),
) -> Dict[str, Any]:
    plan = build_photo_context_review_session_plan(
        session=session,
        scope=scope,
        limit=limit,
        source_query=source_query,
    )
    selected_items = plan.get("items") if isinstance(plan.get("items"), list) else []
    items: List[Dict[str, Any]] = []
    created_count = 0
    existing_count = 0
    review_task_ids: List[str] = []
    selected_item_keys = [str(item.get("group_key")) for item in selected_items if isinstance(item, dict) and item.get("group_key")]
    selected_count = len(selected_items)
    would_create_count = 0
    would_open_existing_count = 0

    def review_session_origin_for_item(item: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "session_type": "photo_context_review_session",
            "sequence_number": item.get("sequence_number"),
            "selected_count": selected_count,
            "source_query": source_query,
            "plan_content_sha256": plan.get("content_sha256"),
            "completion_signal": plan.get("completion_signal"),
            "review_policy": plan.get("review_policy"),
            "not_memory_claim": True,
        }

    for item in selected_items:
        if not isinstance(item, dict):
            continue
        review_session_origin = review_session_origin_for_item(item)
        action = item.get("action") if isinstance(item.get("action"), dict) else {}
        if action.get("action_type") == "open_existing_photo_context_task" and action.get("task_id"):
            existing_count += 1
            would_open_existing_count += 1
            review_task_ids.append(action["task_id"])
            items.append(
                {
                    "group_key": item["group_key"],
                    "display_title": item["display_title"],
                    "canonical_asset_id": item["canonical_asset_id"],
                    "truth_status": item["truth_status"],
                    "not_memory_claim": item["not_memory_claim"],
                    "query_origin": item.get("query_origin"),
                    "review_session_origin": review_session_origin,
                    "plan_item_key": item["group_key"],
                    "action_type": "open_existing_photo_context_task",
                    "task_id": action["task_id"],
                    "task_human_id": action.get("task_human_id"),
                    "queue": action.get("queue"),
                    "created": False,
                    "dry_run": dry_run,
                }
            )
            continue
        if dry_run:
            would_create_count += 1
            items.append(
                {
                    "group_key": item["group_key"],
                    "display_title": item["display_title"],
                    "canonical_asset_id": item["canonical_asset_id"],
                    "truth_status": item["truth_status"],
                    "not_memory_claim": item["not_memory_claim"],
                    "query_origin": item.get("query_origin"),
                    "review_session_origin": review_session_origin,
                    "plan_item_key": item["group_key"],
                    "action_type": "would_create_photo_context_task",
                    "task_id": None,
                    "task_human_id": None,
                    "queue": "photo_assets_needing_context",
                    "created": False,
                    "dry_run": True,
                }
            )
            continue
        created = create_photo_context_task_from_inventory(
            PhotoContextTaskCreate(
                asset_id=item.get("canonical_asset_id"),
                group_key=item.get("group_key"),
                use_canonical=True,
                source_query=source_query,
                session_sequence_number=item.get("sequence_number"),
                session_selected_count=selected_count,
                session_plan_content_sha256=plan.get("content_sha256"),
                session_completion_signal=plan.get("completion_signal"),
                session_review_policy=plan.get("review_policy"),
            ),
            session=session,
        )
        if created.created:
            created_count += 1
            would_create_count += 1
        else:
            existing_count += 1
            would_open_existing_count += 1
        review_task_ids.append(created.task_id)
        items.append(
            {
                "group_key": item["group_key"],
                "display_title": item["display_title"],
                "canonical_asset_id": created.asset_id,
                "truth_status": item["truth_status"],
                "not_memory_claim": item["not_memory_claim"],
                "query_origin": item.get("query_origin"),
                "review_session_origin": review_session_origin,
                "plan_item_key": item["group_key"],
                "action_type": "created_photo_context_task" if created.created else "open_existing_photo_context_task",
                "task_id": created.task_id,
                "task_human_id": created.task_human_id,
                "queue": "photo_assets_needing_context",
                "created": created.created,
                "dry_run": False,
            }
        )

    return {
        "session_type": "photo_context_review_session",
        "scope": scope,
        "dry_run": dry_run,
        "requested_limit": limit,
        "selected_count": selected_count,
        "created_count": created_count,
        "existing_count": existing_count,
        "review_task_ids": review_task_ids,
        "review_policy": "no_claim_until_adam_context_submission",
        "selection_policy": "from_photo_context_review_session_plan",
        "source_query": source_query,
        "plan_content_sha256": plan.get("content_sha256"),
        "plan_export_preview_sha256": plan.get("export_preview_sha256"),
        "selected_item_keys": selected_item_keys,
        "projected_task_delta": {
            "would_create_count": would_create_count,
            "would_open_existing_count": would_open_existing_count,
            "mutation_count": 0 if dry_run else created_count,
            "dry_run_does_not_mutate": dry_run is True,
        },
        "items": items,
    }


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
    annotation_ids = [annotation.id for annotation in annotations]
    task_receipts = (
        session.exec(
            select(TaskReceipt)
            .where((TaskReceipt.task_id.in_(task_ids)) | (TaskReceipt.annotation_id.in_(annotation_ids)))
            .order_by(TaskReceipt.created_at.asc())
        ).all()
        if task_ids or annotation_ids
        else []
    )
    metadata_profiles = session.exec(
        select(MetadataProfile).where(MetadataProfile.target_id.in_(target_ids)).order_by(MetadataProfile.updated_at.asc())
    ).all()
    profile_ids = [profile.id for profile in metadata_profiles]
    voice_reference_examples = (
        session.exec(
            select(VoiceReferenceExample)
            .where(VoiceReferenceExample.source_segment_id.in_(segment_ids))
            .order_by(VoiceReferenceExample.source_chunk_index.asc(), VoiceReferenceExample.created_at.asc())
        ).all()
        if segment_ids
        else []
    )
    embedding_target_ids = [asset.id, *segment_ids, *profile_ids, *(example.id for example in voice_reference_examples)]
    embedding_records = (
        session.exec(
            select(EmbeddingRecord)
            .where(EmbeddingRecord.target_id.in_(embedding_target_ids))
            .order_by(EmbeddingRecord.created_at.asc())
        ).all()
        if embedding_target_ids
        else []
    )
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
        "task_receipts": [_dump(item) for item in task_receipts],
        "metadata_profiles": [_dump(item) for item in metadata_profiles],
        "voice_reference_examples": [_dump(item) for item in voice_reference_examples],
        "embedding_records": [_dump(item) for item in embedding_records],
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
            "task_receipts": len(task_receipts),
            "metadata_profiles": len(metadata_profiles),
            "voice_reference_examples": len(voice_reference_examples),
            "embedding_records": len(embedding_records),
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
