from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import Session, select

from app.db.session import get_session
from app.models import Asset, ExternalRef
from app.schemas import DriveImportRecord, DriveImportRequest, DriveImportResponse
from app.services.drive_import import SOURCE_SYSTEM, import_drive_file

router = APIRouter(prefix="/imports", tags=["imports"])


def _nested_metadata(metadata: Dict[str, Any]) -> Dict[str, Any]:
    nested = metadata.get("drive_metadata")
    return nested if isinstance(nested, dict) else {}


def _metadata_string(metadata: Dict[str, Any], key: str) -> Optional[str]:
    value = metadata.get(key)
    return value if isinstance(value, str) else None


def _metadata_int(metadata: Dict[str, Any], key: str) -> Optional[int]:
    value = metadata.get(key)
    return value if isinstance(value, int) else None


def _drive_import_record(session: Session, external_ref: ExternalRef) -> Optional[DriveImportRecord]:
    asset = session.get(Asset, external_ref.asset_id)
    if asset is None:
        return None

    metadata = external_ref.metadata_json or {}
    drive_metadata = _nested_metadata(metadata)
    drive_path = drive_metadata.get("charlesOpsPath")
    candidate_kind = drive_metadata.get("charlesOpsCandidateKind")

    return DriveImportRecord(
        asset_id=asset.id,
        human_id=asset.human_id,
        title=asset.title,
        asset_type=asset.asset_type,
        mime_type=asset.mime_type,
        import_status=asset.import_status,
        processing_status=asset.processing_status,
        maturity_level=asset.maturity_level,
        drive_file_id=external_ref.external_id,
        drive_name=_metadata_string(metadata, "drive_name"),
        drive_mime_type=_metadata_string(metadata, "drive_mime_type"),
        drive_path=drive_path if isinstance(drive_path, str) else None,
        drive_candidate_kind=candidate_kind if isinstance(candidate_kind, str) else None,
        drive_size=_metadata_int(metadata, "drive_size"),
        drive_created_time=_metadata_string(metadata, "drive_created_time"),
        drive_modified_time=_metadata_string(metadata, "drive_modified_time"),
        drive_web_view_link=_metadata_string(metadata, "drive_web_view_link"),
        mirror_status=_metadata_string(metadata, "mirror_status"),
        latest_mirror_uri=_metadata_string(metadata, "latest_mirror_uri"),
        parent_ref=external_ref.parent_ref,
    )


@router.get("/drive/recent", response_model=list[DriveImportRecord])
def recent_drive_imports(
    limit: int = Query(default=100, ge=1, le=500),
    session: Session = Depends(get_session),
) -> list[DriveImportRecord]:
    refs = session.exec(
        select(ExternalRef)
        .where(ExternalRef.source_system == SOURCE_SYSTEM)
        .order_by(ExternalRef.created_at.desc())
        .limit(limit)
    ).all()
    records = [_drive_import_record(session, ref) for ref in refs]
    return [record for record in records if record is not None]


@router.post("/drive", response_model=DriveImportResponse)
def import_drive_files(
    payload: DriveImportRequest,
    session: Session = Depends(get_session),
) -> DriveImportResponse:
    if not payload.files:
        raise HTTPException(status_code=400, detail="At least one Drive file is required.")
    if len(payload.files) > 50:
        raise HTTPException(status_code=400, detail="Import at most 50 Drive files at a time.")

    try:
        imported = [
            import_drive_file(
                session,
                file,
                imported_by=payload.imported_by,
                create_triage_tasks=payload.create_triage_tasks,
            )
            for file in payload.files
        ]
    except ValueError as exc:
        session.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    session.commit()
    return DriveImportResponse(
        imported=imported,
        created_count=sum(1 for item in imported if item.created),
        existing_count=sum(1 for item in imported if not item.created),
    )
