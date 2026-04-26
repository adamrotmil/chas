from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Dict, Optional

from sqlmodel import Session, select

from app.models import Annotation, Asset, AssetSnapshot, Boundary, ExternalRef, ObjectFile, Task
from app.schemas import DriveFileImport, DriveImportItemResult


SOURCE_SYSTEM = "google_drive"


def _asset_type_for(mime_type: Optional[str], name: str) -> str:
    mime = (mime_type or "").lower()
    lowered_name = name.lower()
    if mime.startswith("image/"):
        return "photo"
    if mime.startswith("audio/"):
        return "audio"
    if mime.startswith("video/"):
        return "video"
    if (
        mime.startswith("text/")
        or mime == "application/pdf"
        or mime in {"application/rtf", "application/json"}
        or mime.startswith("application/vnd.google-apps.")
        or lowered_name.endswith((".txt", ".md", ".rtf", ".pdf", ".doc", ".docx"))
    ):
        return "text"
    return "file"


def _human_id_for_drive_file(drive_file_id: str) -> str:
    safe_id = re.sub(r"[^A-Za-z0-9]+", "_", drive_file_id).strip("_").upper()
    return f"DRV_{safe_id}"


def _drive_uri(drive_file_id: str) -> str:
    return f"gdrive://files/{drive_file_id}"


def _metadata_for(file: DriveFileImport, imported_by: str) -> Dict[str, Any]:
    return {
        "source_system": SOURCE_SYSTEM,
        "drive_file_id": file.drive_file_id,
        "drive_name": file.name,
        "drive_mime_type": file.mime_type,
        "drive_created_time": file.created_time.isoformat() if file.created_time else None,
        "drive_modified_time": file.modified_time.isoformat() if file.modified_time else None,
        "drive_parents": file.parents,
        "drive_web_view_link": file.web_view_link,
        "drive_icon_link": file.icon_link,
        "drive_thumbnail_link": file.thumbnail_link,
        "drive_md5_checksum": file.md5_checksum,
        "drive_sha1_checksum": file.sha1_checksum,
        "drive_sha256_checksum": file.sha256_checksum,
        "drive_size": file.size_bytes,
        "picker_document": file.picker_document,
        "drive_metadata": file.drive_metadata,
        "imported_by": imported_by,
        "mirror_status": "metadata_only",
    }


def _find_latest_snapshot(session: Session, asset_id: str) -> Optional[AssetSnapshot]:
    return session.exec(
        select(AssetSnapshot)
        .where(AssetSnapshot.asset_id == asset_id)
        .where(AssetSnapshot.snapshot_type == "drive_metadata")
        .order_by(AssetSnapshot.version.desc())
    ).first()


def _same_datetime(left: Optional[datetime], right: Optional[datetime]) -> bool:
    if left is None or right is None:
        return left is None and right is None
    return left.replace(tzinfo=None) == right.replace(tzinfo=None)


def _find_or_create_boundary(session: Session, asset: Asset) -> Boundary:
    boundary = session.exec(
        select(Boundary).where(Boundary.target_type == "asset").where(Boundary.target_id == asset.id)
    ).first()
    if boundary:
        return boundary

    boundary = Boundary(
        target_type="asset",
        target_id=asset.id,
        privacy_level="unreviewed",
        notes="Default unreviewed boundary created during Google Drive metadata import.",
    )
    session.add(boundary)
    session.flush()
    return boundary


def _find_or_create_triage_task(session: Session, asset: Asset, metadata: Dict[str, Any]) -> Task:
    task = session.exec(
        select(Task)
        .where(Task.target_type == "asset")
        .where(Task.target_id == asset.id)
        .where(Task.task_type == "asset_triage")
        .where(Task.status.in_(["ready", "sensitive_hold"]))
    ).first()
    if task:
        return task

    task = Task(
        human_id=f"TASK_TRIAGE_{asset.human_id}",
        task_type="asset_triage",
        target_type="asset",
        target_id=asset.id,
        priority=70,
        queue="drive_import_triage",
        reason_created="Google Drive asset was selected for CharlesOps intake and needs initial triage.",
        input_payload={
            "title": asset.title,
            "asset_type": asset.asset_type,
            "source_system": SOURCE_SYSTEM,
            "drive_file_id": metadata["drive_file_id"],
            "drive_mime_type": metadata["drive_mime_type"],
            "drive_web_view_link": metadata["drive_web_view_link"],
            "mirror_status": metadata["mirror_status"],
        },
        required_decisions=["source_type", "importance", "initial_privacy_level", "process_next"],
        created_by="drive_import",
    )
    session.add(task)
    session.flush()
    return task


def import_drive_file(
    session: Session,
    file: DriveFileImport,
    *,
    imported_by: str,
    create_triage_tasks: bool,
) -> DriveImportItemResult:
    metadata = _metadata_for(file, imported_by)
    external_ref = session.exec(
        select(ExternalRef)
        .where(ExternalRef.source_system == SOURCE_SYSTEM)
        .where(ExternalRef.external_id == file.drive_file_id)
    ).first()

    created = external_ref is None
    if external_ref:
        asset = session.get(Asset, external_ref.asset_id)
        if asset is None:
            raise ValueError(f"External ref {external_ref.id} points to missing asset {external_ref.asset_id}")
    else:
        asset = Asset(
            human_id=_human_id_for_drive_file(file.drive_file_id),
            asset_type=_asset_type_for(file.mime_type, file.name),
            title=file.name,
            original_filename=file.name,
            mime_type=file.mime_type,
            source_system=SOURCE_SYSTEM,
            source_created_time=file.created_time,
            source_modified_time=file.modified_time,
            import_status="drive_metadata_imported",
            processing_status="needs_triage",
            maturity_level="L0_source_seen",
        )
        session.add(asset)
        session.flush()
        external_ref = ExternalRef(
            asset_id=asset.id,
            source_system=SOURCE_SYSTEM,
            external_id=file.drive_file_id,
            uri=file.web_view_link or _drive_uri(file.drive_file_id),
            parent_ref=",".join(file.parents) if file.parents else None,
            metadata_json=metadata,
        )
        session.add(external_ref)
        session.flush()

    asset.title = file.name
    asset.original_filename = file.name
    asset.mime_type = file.mime_type
    asset.source_system = SOURCE_SYSTEM
    asset.source_created_time = file.created_time
    asset.source_modified_time = file.modified_time
    asset.import_status = "drive_metadata_imported"
    if asset.processing_status == "ready":
        asset.processing_status = "needs_triage"
    if asset.maturity_level == "L1_mirrored" and created:
        asset.maturity_level = "L0_source_seen"
    session.add(asset)

    external_ref.uri = file.web_view_link or _drive_uri(file.drive_file_id)
    external_ref.parent_ref = ",".join(file.parents) if file.parents else None
    external_ref.metadata_json = metadata
    session.add(external_ref)

    latest_snapshot = _find_latest_snapshot(session, asset.id)
    object_file: Optional[ObjectFile] = None
    if latest_snapshot and latest_snapshot.object_file_id:
        object_file = session.get(ObjectFile, latest_snapshot.object_file_id)

    if object_file is None:
        object_file = ObjectFile(
            storage_provider=SOURCE_SYSTEM,
            object_key=f"drive/{file.drive_file_id}",
            uri=_drive_uri(file.drive_file_id),
        )

    object_file.content_type = file.mime_type
    object_file.byte_size = file.size_bytes
    object_file.checksum_sha256 = file.sha256_checksum
    object_file.metadata_json = metadata
    session.add(object_file)
    session.flush()

    if (
        latest_snapshot
        and _same_datetime(latest_snapshot.source_modified_time, file.modified_time)
        and latest_snapshot.checksum_sha256 == file.sha256_checksum
    ):
        snapshot = latest_snapshot
    else:
        snapshot = AssetSnapshot(
            asset_id=asset.id,
            snapshot_type="drive_metadata",
            version=(latest_snapshot.version + 1) if latest_snapshot else 1,
            checksum_sha256=file.sha256_checksum,
            source_modified_time=file.modified_time,
            object_file_id=object_file.id,
        )
        session.add(snapshot)
        session.flush()

    boundary = _find_or_create_boundary(session, asset)
    task = _find_or_create_triage_task(session, asset, metadata) if create_triage_tasks else None

    annotation = Annotation(
        target_type="asset",
        target_id=asset.id,
        annotation_type="drive_metadata_import",
        annotator_id=imported_by,
        decisions=metadata,
        notes="Google Drive metadata imported. Binary mirroring/export is intentionally deferred.",
        creates_or_updates={
            "asset_id": asset.id,
            "external_ref_id": external_ref.id,
            "object_file_id": object_file.id,
            "asset_snapshot_id": snapshot.id,
            "boundary_id": boundary.id,
            "task_id": task.id if task else None,
        },
    )
    session.add(annotation)
    session.flush()

    return DriveImportItemResult(
        asset_id=asset.id,
        human_id=asset.human_id,
        title=asset.title or file.name,
        asset_type=asset.asset_type,
        created=created,
        external_ref_id=external_ref.id,
        object_file_id=object_file.id,
        asset_snapshot_id=snapshot.id,
        boundary_id=boundary.id,
        task_id=task.id if task else None,
        annotation_id=annotation.id,
    )
