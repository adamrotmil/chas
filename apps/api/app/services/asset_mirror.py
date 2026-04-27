from __future__ import annotations

import hashlib
import json
import re
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from fastapi import UploadFile
from sqlmodel import Session, select

from app.models import Annotation, Asset, AssetSnapshot, ExternalRef, ObjectFile, utcnow
from app.schemas import AssetMirrorResponse
from app.services.image_derivatives import create_image_derivatives
from app.services.text_extraction import extract_text_from_file, persist_text_extraction, should_attempt_text_extraction


SOURCE_MIRROR_ROOT = "source_mirror"
CHUNK_SIZE = 1024 * 1024


def _safe_path_part(value: str, fallback: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", value).strip("._-")
    return safe[:120] or fallback


def _same_datetime(left: Optional[datetime], right: Optional[datetime]) -> bool:
    if left is None or right is None:
        return left is None and right is None
    return left.replace(tzinfo=None) == right.replace(tzinfo=None)


def _latest_mirror_snapshot(session: Session, asset_id: str) -> Optional[AssetSnapshot]:
    return session.exec(
        select(AssetSnapshot)
        .where(AssetSnapshot.asset_id == asset_id)
        .where(AssetSnapshot.snapshot_type == "source_mirror")
        .order_by(AssetSnapshot.version.desc())
    ).first()


async def _write_upload_to_temp(upload: UploadFile, temp_path: Path) -> tuple[int, str]:
    digest = hashlib.sha256()
    byte_size = 0

    with temp_path.open("wb") as output:
        while True:
            chunk = await upload.read(CHUNK_SIZE)
            if not chunk:
                break
            byte_size += len(chunk)
            digest.update(chunk)
            output.write(chunk)

    return byte_size, digest.hexdigest()


def _mirror_metadata(
    *,
    source_system: str,
    source_uri: Optional[str],
    drive_file_id: Optional[str],
    drive_mime_type: Optional[str],
    export_mime_type: Optional[str],
    original_filename: str,
    source_modified_time: Optional[datetime],
    byte_size: int,
    checksum_sha256: str,
    object_key: str,
    storage_provider: str,
    bucket: Optional[str],
    uri: str,
) -> Dict[str, Any]:
    return {
        "source_system": source_system,
        "source_uri": source_uri,
        "drive_file_id": drive_file_id,
        "drive_mime_type": drive_mime_type,
        "export_mime_type": export_mime_type,
        "original_filename": original_filename,
        "source_modified_time": source_modified_time.isoformat() if source_modified_time else None,
        "mirror_status": "mirrored",
        "mirror_kind": "source_copy",
        "mirror_storage": storage_provider,
        "mirror_bucket": bucket,
        "mirror_object_key": object_key,
        "mirror_uri": uri,
        "byte_size": byte_size,
        "checksum_sha256": checksum_sha256,
    }


def _upload_to_gcs(
    *,
    path: Path,
    bucket: str,
    object_key: str,
    content_type: Optional[str],
    access_token: str,
) -> Dict[str, Any]:
    encoded_bucket = quote(bucket, safe="")
    encoded_name = quote(object_key, safe="")
    url = f"https://storage.googleapis.com/upload/storage/v1/b/{encoded_bucket}/o?uploadType=media&name={encoded_name}"
    request = Request(
        url,
        data=path.read_bytes(),
        method="POST",
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": content_type or "application/octet-stream",
        },
    )
    try:
        with urlopen(request, timeout=120) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise ValueError(f"GCS upload failed: {exc.code} {body}") from exc
    except URLError as exc:
        raise ValueError(f"GCS upload failed: {exc.reason}") from exc


async def mirror_upload_for_asset(
    session: Session,
    asset: Asset,
    upload: UploadFile,
    *,
    storage_root: Path,
    storage_provider: str = "local",
    gcs_bucket: Optional[str] = None,
    gcs_prefix: str = "charlesops",
    storage_access_token: Optional[str] = None,
    source_system: str = "google_drive",
    source_uri: Optional[str] = None,
    drive_file_id: Optional[str] = None,
    drive_mime_type: Optional[str] = None,
    export_mime_type: Optional[str] = None,
    source_modified_time: Optional[datetime] = None,
) -> AssetMirrorResponse:
    filename = _safe_path_part(upload.filename or asset.original_filename or asset.title or asset.human_id, "source_file")
    asset_key = _safe_path_part(asset.human_id or asset.id, asset.id)
    temp_dir = storage_root / SOURCE_MIRROR_ROOT / ".tmp"
    temp_dir.mkdir(parents=True, exist_ok=True)
    temp_path = temp_dir / f"{uuid.uuid4()}.part"

    byte_size, checksum_sha256 = await _write_upload_to_temp(upload, temp_path)
    latest_snapshot = _latest_mirror_snapshot(session, asset.id)
    provider = storage_provider.lower()
    configured_bucket = gcs_bucket or None
    content_type = export_mime_type or upload.content_type or asset.mime_type
    text_extraction = (
        extract_text_from_file(temp_path, filename=filename, content_type=content_type, asset_type=asset.asset_type)
        if should_attempt_text_extraction(filename, content_type, asset.asset_type)
        else None
    )

    if (
        latest_snapshot
        and latest_snapshot.object_file_id
        and latest_snapshot.checksum_sha256 == checksum_sha256
        and _same_datetime(latest_snapshot.source_modified_time, source_modified_time)
    ):
        object_file = session.get(ObjectFile, latest_snapshot.object_file_id)
        if object_file and object_file.storage_provider == provider and object_file.bucket == configured_bucket:
            temp_path.unlink(missing_ok=True)
            return AssetMirrorResponse(
                asset_id=asset.id,
                created=False,
                object_file_id=object_file.id,
                asset_snapshot_id=latest_snapshot.id,
                object_key=object_file.object_key,
                uri=object_file.uri,
                filename=filename,
                content_type=object_file.content_type,
                byte_size=object_file.byte_size or byte_size,
                checksum_sha256=object_file.checksum_sha256 or checksum_sha256,
            )

    version = (latest_snapshot.version + 1) if latest_snapshot else 1
    source_key = _safe_path_part(source_system, "source")
    object_key_parts = [gcs_prefix.strip("/")] if provider == "gcs" and gcs_prefix.strip("/") else []
    object_key_parts.extend([SOURCE_MIRROR_ROOT, source_key, asset_key, f"v{version}", filename])
    object_key = "/".join(object_key_parts)

    if provider == "local":
        final_path = storage_root / object_key
        final_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path.replace(final_path)
        bucket = None
        uri = f"local://{object_key}"
        source_preview_path = final_path
    elif provider == "gcs":
        bucket = configured_bucket or ""
        if not bucket:
            temp_path.unlink(missing_ok=True)
            raise ValueError("GCS mirror storage is enabled, but GCS_BUCKET is not configured.")
        if not storage_access_token:
            temp_path.unlink(missing_ok=True)
            raise ValueError("GCS mirror storage requires a Google Cloud Storage access token.")
        try:
            _upload_to_gcs(
                path=temp_path,
                bucket=bucket,
                object_key=object_key,
                content_type=content_type,
                access_token=storage_access_token,
            )
        except Exception:
            temp_path.unlink(missing_ok=True)
            raise
        uri = f"gs://{bucket}/{object_key}"
        source_preview_path = temp_path
    else:
        temp_path.unlink(missing_ok=True)
        raise ValueError(f"Unsupported object storage provider: {storage_provider}")

    metadata = _mirror_metadata(
        source_system=source_system,
        source_uri=source_uri,
        drive_file_id=drive_file_id,
        drive_mime_type=drive_mime_type,
        export_mime_type=export_mime_type,
        original_filename=filename,
        source_modified_time=source_modified_time,
        byte_size=byte_size,
        checksum_sha256=checksum_sha256,
        object_key=object_key,
        storage_provider=provider,
        bucket=bucket,
        uri=uri,
    )

    object_file = ObjectFile(
        storage_provider=provider,
        bucket=bucket,
        object_key=object_key,
        uri=uri,
        content_type=content_type,
        byte_size=byte_size,
        checksum_sha256=checksum_sha256,
        metadata_json=metadata,
    )
    session.add(object_file)
    session.flush()

    snapshot = AssetSnapshot(
        asset_id=asset.id,
        snapshot_type="source_mirror",
        version=version,
        checksum_sha256=checksum_sha256,
        source_modified_time=source_modified_time,
        object_file_id=object_file.id,
    )
    session.add(snapshot)
    session.flush()

    try:
        image_derivatives = create_image_derivatives(
            session=session,
            asset=asset,
            source_snapshot=snapshot,
            source_object_file=object_file,
            source_path=source_preview_path,
            filename=filename,
            storage_root=storage_root,
            storage_provider=provider,
            gcs_bucket=bucket,
            gcs_prefix=gcs_prefix,
            storage_access_token=storage_access_token,
            upload_to_gcs=_upload_to_gcs,
        )
    finally:
        if provider == "gcs":
            temp_path.unlink(missing_ok=True)

    asset.import_status = "mirrored"
    if asset.maturity_level == "L0_source_seen":
        asset.maturity_level = "L1_mirrored"
    if image_derivatives:
        asset.processing_status = "image_preview_ready"
        asset.maturity_level = "L3_previewable"
    asset.updated_at = utcnow()
    session.add(asset)

    external_ref = session.exec(
        select(ExternalRef)
        .where(ExternalRef.asset_id == asset.id)
        .where(ExternalRef.source_system == source_system)
    ).first()
    if external_ref:
        external_metadata = dict(external_ref.metadata_json)
        external_metadata.update(
            {
                "mirror_status": "mirrored",
                "latest_mirror_object_file_id": object_file.id,
                "latest_mirror_asset_snapshot_id": snapshot.id,
                "latest_mirror_checksum_sha256": checksum_sha256,
                "latest_mirror_byte_size": byte_size,
                "latest_mirror_uri": uri,
                "mirrored_at": utcnow().isoformat(),
            }
        )
        external_ref.metadata_json = external_metadata
        session.add(external_ref)

    text_extraction_summary = None
    if text_extraction and text_extraction.status != "skipped":
        text_extraction_summary = persist_text_extraction(
            session,
            asset=asset,
            source_snapshot=snapshot,
            source_object_file=object_file,
            filename=filename,
            content_type=content_type,
            extraction=text_extraction,
        )

    annotation = Annotation(
        annotator_id="system",
        target_type="asset",
        target_id=asset.id,
        annotation_type="asset_mirrored",
        decisions=metadata,
        notes="Source content copied into CharlesOps-controlled mirror storage; source vault original left untouched.",
        creates_or_updates={
            "asset_id": asset.id,
            "object_file_id": object_file.id,
            "asset_snapshot_id": snapshot.id,
            "external_ref_id": external_ref.id if external_ref else None,
            "image_derivatives": image_derivatives,
            "text_extraction": text_extraction_summary,
        },
    )
    session.add(annotation)
    session.flush()

    return AssetMirrorResponse(
        asset_id=asset.id,
        created=True,
        object_file_id=object_file.id,
        asset_snapshot_id=snapshot.id,
        annotation_id=annotation.id,
        object_key=object_file.object_key,
        uri=object_file.uri,
        filename=filename,
        content_type=object_file.content_type,
        byte_size=byte_size,
        checksum_sha256=checksum_sha256,
    )
