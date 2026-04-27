from __future__ import annotations

import hashlib
import re
from io import BytesIO
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from PIL import Image, ImageOps, UnidentifiedImageError
from sqlmodel import Session

from app.models import Asset, AssetSnapshot, Derivative, ObjectFile


IMAGE_DERIVATIVE_ROOT = "derivatives/images"
GCS_PREVIEW_CACHE_ROOT = "preview_cache/gcs"

IMAGE_VARIANTS = {
    "thumbnail": (320, 320),
    "display": (1600, 1600),
}


def _safe_path_part(value: str, fallback: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", value).strip("._-")
    return safe[:120] or fallback


def is_image_content(content_type: Optional[str], asset_type: str) -> bool:
    return asset_type in {"photo", "scan"} or (content_type or "").lower().startswith("image/")


def _derivative_filename(filename: str, variant: str, image_format: str) -> str:
    stem = Path(filename).stem or "image"
    extension = ".png" if image_format == "PNG" else ".jpg"
    return f"{_safe_path_part(stem, 'image')}.{variant}{extension}"


def _render_variant(image: Image.Image, max_size: tuple[int, int]) -> tuple[bytes, str, str, int, int]:
    framed = ImageOps.exif_transpose(image).copy()
    framed.thumbnail(max_size, Image.Resampling.LANCZOS)
    has_alpha = framed.mode in {"RGBA", "LA"} or (framed.mode == "P" and "transparency" in framed.info)
    output = BytesIO()
    if has_alpha:
        framed.save(output, format="PNG", optimize=True)
        return output.getvalue(), "image/png", "PNG", framed.width, framed.height
    if framed.mode != "RGB":
        framed = framed.convert("RGB")
    framed.save(output, format="JPEG", quality=86, optimize=True)
    return output.getvalue(), "image/jpeg", "JPEG", framed.width, framed.height


def _write_local(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def create_image_derivatives(
    *,
    session: Session,
    asset: Asset,
    source_snapshot: AssetSnapshot,
    source_object_file: ObjectFile,
    source_path: Path,
    filename: str,
    storage_root: Path,
    storage_provider: str,
    gcs_bucket: Optional[str],
    gcs_prefix: str,
    storage_access_token: Optional[str],
    upload_to_gcs: Callable[..., Dict[str, Any]],
) -> List[Dict[str, Any]]:
    provider = storage_provider.lower()
    if not is_image_content(source_object_file.content_type, asset.asset_type):
        return []

    try:
        image = Image.open(source_path)
        image.verify()
        image = Image.open(source_path)
    except (OSError, UnidentifiedImageError):
        return []

    asset_key = _safe_path_part(asset.human_id or asset.id, asset.id)
    created: List[Dict[str, Any]] = []

    for variant, max_size in IMAGE_VARIANTS.items():
        data, content_type, image_format, width, height = _render_variant(image, max_size)
        checksum = hashlib.sha256(data).hexdigest()
        derivative_filename = _derivative_filename(filename, variant, image_format)
        object_key_parts = [gcs_prefix.strip("/")] if provider == "gcs" and gcs_prefix.strip("/") else []
        object_key_parts.extend(
            [
                IMAGE_DERIVATIVE_ROOT,
                asset_key,
                f"v{source_snapshot.version}",
                variant,
                derivative_filename,
            ]
        )
        object_key = "/".join(object_key_parts)
        metadata: Dict[str, Any] = {
            "derivative_kind": "image_preview",
            "variant": variant,
            "width": width,
            "height": height,
            "source_snapshot_id": source_snapshot.id,
            "source_object_file_id": source_object_file.id,
            "source_filename": filename,
            "image_format": image_format,
        }

        if provider == "gcs":
            bucket = gcs_bucket or ""
            if not bucket or not storage_access_token:
                continue
            temp_derivative_path = _bytes_to_temp_file(storage_root, data, variant)
            try:
                upload_to_gcs(
                    path=temp_derivative_path,
                    bucket=bucket,
                    object_key=object_key,
                    content_type=content_type,
                    access_token=storage_access_token,
                )
            finally:
                temp_derivative_path.unlink(missing_ok=True)
            cache_key = "/".join([GCS_PREVIEW_CACHE_ROOT, object_key])
            _write_local(storage_root / cache_key, data)
            metadata["local_preview_cache_key"] = cache_key
            storage_bucket = bucket
            uri = f"gs://{bucket}/{object_key}"
            object_provider = "gcs"
        else:
            _write_local(storage_root / object_key, data)
            storage_bucket = None
            uri = f"local://{object_key}"
            object_provider = "local"

        object_file = ObjectFile(
            storage_provider=object_provider,
            bucket=storage_bucket,
            object_key=object_key,
            uri=uri,
            content_type=content_type,
            byte_size=len(data),
            checksum_sha256=checksum,
            metadata_json=metadata,
        )
        session.add(object_file)
        session.flush()

        derivative = Derivative(
            asset_id=asset.id,
            source_snapshot_id=source_snapshot.id,
            derivative_type="image_preview",
            version=source_snapshot.version,
            object_file_id=object_file.id,
            status="ready",
            metadata_json=metadata,
        )
        session.add(derivative)
        session.flush()

        created.append(
            {
                "variant": variant,
                "derivative_id": derivative.id,
                "object_file_id": object_file.id,
                "object_key": object_key,
                "uri": uri,
                "width": width,
                "height": height,
                "byte_size": len(data),
                "checksum_sha256": checksum,
            }
        )

    return created


def _bytes_to_temp_file(storage_root: Path, data: bytes, variant: str) -> Path:
    temp_dir = storage_root / IMAGE_DERIVATIVE_ROOT / ".tmp"
    temp_dir.mkdir(parents=True, exist_ok=True)
    temp_path = temp_dir / f"{hashlib.sha256(data).hexdigest()}.{variant}.part"
    temp_path.write_bytes(data)
    return temp_path
