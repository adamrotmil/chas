from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from sqlmodel import Session, select

from app.config import Settings, settings
from app.models import Boundary, EmbeddingRecord, MetadataProfile, utcnow


MAX_EMBEDDING_INPUT_CHARS = 4000
EMBEDDING_VECTOR_DIR = "embedding_vectors"


def _checksum(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _clean(value: Any) -> str:
    return value if isinstance(value, str) and value.strip() else ""


def _clean_list(values: Any) -> List[str]:
    if not isinstance(values, list):
        return []
    return [str(value).strip() for value in values if str(value).strip()]


def _join_labeled(parts: Iterable[tuple[str, Any]]) -> str:
    rows: List[str] = []
    for label, value in parts:
        if isinstance(value, list):
            cleaned = ", ".join(_clean_list(value))
        else:
            cleaned = _clean(value)
        if cleaned:
            rows.append(f"{label}: {cleaned}")
    return "\n".join(rows)


def _normalize_boundary_snapshot(value: Any, key: str = "") -> Any:
    if isinstance(value, dict):
        return {item_key: _normalize_boundary_snapshot(item_value, item_key) for item_key, item_value in value.items()}
    if isinstance(value, list):
        return [_normalize_boundary_snapshot(item) for item in value]
    if hasattr(value, "isoformat"):
        return str(value.isoformat()).replace("+00:00", "Z")
    if isinstance(value, str) and key.endswith("_at"):
        normalized = value.replace("+00:00", "Z")
        if normalized.endswith("Z"):
            return normalized
        if re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?$", normalized):
            return f"{normalized}Z"
    return value


def boundary_snapshot_for_target(session: Session, target_type: str, target_id: str) -> Dict[str, Any]:
    boundary = session.exec(
        select(Boundary).where(Boundary.target_type == target_type).where(Boundary.target_id == target_id)
    ).first()
    if boundary:
        return _normalize_boundary_snapshot(boundary.model_dump(mode="json"))
    return {"target_type": target_type, "target_id": target_id, "boundary_status": "missing"}


def profile_embedding_text(profile: MetadataProfile) -> str:
    return _join_labeled(
        [
            ("title", profile.title),
            ("summary", profile.summary),
            ("adam_context", profile.adam_context_note),
            ("people", profile.people),
            ("places", profile.places),
            ("date", profile.date_label),
            ("themes", profile.themes),
            ("motifs", profile.motifs),
            ("emotional_tone", profile.emotional_tone),
            ("concrete_objects", profile.concrete_objects),
            ("retrieval_notes", profile.retrieval_notes),
            ("open_questions", profile.open_questions),
        ]
    )


def boundary_embedding_text(snapshot: Dict[str, Any]) -> str:
    privacy_level = _clean(snapshot.get("privacy_level")) or _clean(snapshot.get("boundary_status")) or "unknown"
    safe_parts = [
        ("boundary_privacy_level", privacy_level),
        ("boundary_searchable", str(bool(snapshot.get("searchable"))).lower()),
        ("boundary_retrievable_in_chat", str(bool(snapshot.get("retrievable_in_chat"))).lower()),
        ("boundary_usable_for_voice_context", str(bool(snapshot.get("usable_for_voice_context"))).lower()),
        ("boundary_usable_for_gallery_family", str(bool(snapshot.get("usable_for_gallery_family"))).lower()),
        ("boundary_usable_for_gallery_public", str(bool(snapshot.get("usable_for_gallery_public"))).lower()),
        ("boundary_usable_for_sft", str(bool(snapshot.get("usable_for_sft"))).lower()),
        ("boundary_usable_for_dpo", str(bool(snapshot.get("usable_for_dpo"))).lower()),
        ("boundary_redaction_required", str(bool(snapshot.get("redaction_required"))).lower()),
    ]
    return _join_labeled(safe_parts)


def live_embedding_ready(app_settings: Settings = settings) -> bool:
    return bool(app_settings.embedding_live_calls_enabled and app_settings.openai_api_key)


def _vector_relative_path(record: EmbeddingRecord) -> str:
    return f"{EMBEDDING_VECTOR_DIR}/{record.id}.json"


def _vector_path(record: EmbeddingRecord, app_settings: Settings) -> Path:
    storage_root = Path(app_settings.storage_root).resolve()
    return (storage_root / _vector_relative_path(record)).resolve()


def load_embedding_vector(record: EmbeddingRecord, app_settings: Settings = settings) -> List[float]:
    uri = record.vector_uri or ""
    if not uri.startswith("local://"):
        return []
    relative = uri.removeprefix("local://")
    storage_root = Path(app_settings.storage_root).resolve()
    path = (storage_root / relative).resolve()
    if not path.is_relative_to(storage_root) or not path.is_file():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    if payload.get("input_checksum") != record.input_checksum:
        return []
    vector = payload.get("embedding")
    if not isinstance(vector, list):
        return []
    try:
        return [float(value) for value in vector]
    except (TypeError, ValueError):
        return []


def _call_live_embedding_model(*, input_text: str, model_name: str, app_settings: Settings) -> Dict[str, Any]:
    from openai import OpenAI

    client = OpenAI(
        api_key=app_settings.openai_api_key,
        project=app_settings.openai_project_id or None,
        timeout=180,
    )
    response = client.embeddings.create(model=model_name, input=input_text)
    data = getattr(response, "data", None)
    first = data[0] if isinstance(data, list) and data else None
    embedding = getattr(first, "embedding", None) if first is not None else None
    if embedding is None and isinstance(first, dict):
        embedding = first.get("embedding")
    if not isinstance(embedding, list) or not embedding:
        raise ValueError("Embedding model returned no vector values.")
    return {
        "embedding": [float(value) for value in embedding],
        "provider_record_id": _clean(getattr(response, "id", None)),
    }


def embed_query_text(
    *,
    query: str,
    app_settings: Settings = settings,
    model_name: Optional[str] = None,
) -> List[float]:
    if not live_embedding_ready(app_settings):
        return []
    result = _call_live_embedding_model(
        input_text=query,
        model_name=model_name or app_settings.embedding_model,
        app_settings=app_settings,
    )
    vector = result.get("embedding")
    return vector if isinstance(vector, list) else []


def embed_embedding_record(
    *,
    session: Session,
    record: EmbeddingRecord,
    app_settings: Settings = settings,
    model_name: Optional[str] = None,
) -> EmbeddingRecord:
    if not live_embedding_ready(app_settings):
        raise ValueError("Live embeddings require EMBEDDING_LIVE_CALLS_ENABLED=true and OPENAI_API_KEY.")
    selected_model = model_name or app_settings.embedding_model
    result = _call_live_embedding_model(input_text=record.input_text, model_name=selected_model, app_settings=app_settings)
    vector = result["embedding"]
    path = _vector_path(record, app_settings)
    storage_root = Path(app_settings.storage_root).resolve()
    if not path.is_relative_to(storage_root):
        raise ValueError("Embedding vector path escaped storage root.")
    path.parent.mkdir(parents=True, exist_ok=True)
    vector_payload = {
        "embedding_record_id": record.id,
        "target_type": record.target_type,
        "target_id": record.target_id,
        "model_name": selected_model,
        "input_checksum": record.input_checksum,
        "dims": len(vector),
        "embedding": vector,
    }
    path.write_text(json.dumps(vector_payload, separators=(",", ":")), encoding="utf-8")
    record.model_name = selected_model
    record.vector_dims = len(vector)
    record.vector_uri = f"local://{_vector_relative_path(record)}"
    record.provider_record_id = result.get("provider_record_id") or f"openai:{selected_model}:{record.input_checksum}"
    record.status = "embedded"
    record.metadata_json = {
        **(record.metadata_json or {}),
        "live_embedding_call": True,
        "embedding_provider": "openai",
        "embedding_model": selected_model,
        "vector_storage": "local_json_file",
        "vector_values_in_db": False,
        "vector_values_in_exports": False,
        "embedded_at": utcnow().isoformat(),
    }
    record.updated_at = utcnow()
    session.add(record)
    session.flush()
    return record


def embed_ready_embedding_records(
    *,
    session: Session,
    limit: int = 20,
    app_settings: Settings = settings,
    model_name: Optional[str] = None,
) -> Dict[str, Any]:
    if not live_embedding_ready(app_settings):
        return {
            "status": "skipped",
            "reason": "live_embedding_not_ready",
            "live_embedding_ready": False,
            "created_count": 0,
            "embedded_record_ids": [],
        }
    safe_limit = max(1, min(limit, 100))
    records = session.exec(
        select(EmbeddingRecord)
        .where(EmbeddingRecord.status == "ready_for_embedding")
        .where(EmbeddingRecord.modality == "text")
        .order_by(EmbeddingRecord.created_at.asc())
    ).all()[:safe_limit]
    embedded_ids: List[str] = []
    failed: List[Dict[str, str]] = []
    for record in records:
        try:
            embed_embedding_record(session=session, record=record, app_settings=app_settings, model_name=model_name)
            embedded_ids.append(record.id)
        except Exception as exc:
            failed.append({"embedding_record_id": record.id, "error": f"{type(exc).__name__}: {exc}"})
    return {
        "status": "completed" if not failed else "completed_with_errors",
        "live_embedding_ready": True,
        "model_name": model_name or app_settings.embedding_model,
        "requested_limit": safe_limit,
        "eligible_count": len(records),
        "created_count": len(embedded_ids),
        "embedded_record_ids": embedded_ids,
        "failed": failed,
    }


def upsert_embedding_record(
    *,
    session: Session,
    target_type: str,
    target_id: str,
    input_text: str,
    modality: str = "text",
    embedding_type: str = "retrieval_text",
    model_name: str = "pending_text_embedding",
    truth_status: Optional[str] = None,
    boundary_snapshot: Optional[Dict[str, Any]] = None,
    metadata: Optional[Dict[str, Any]] = None,
    created_by: str = "system",
) -> Optional[EmbeddingRecord]:
    text = " ".join(input_text.split())
    if not text:
        return None
    if len(text) > MAX_EMBEDDING_INPUT_CHARS:
        text = text[: MAX_EMBEDDING_INPUT_CHARS - 14].rstrip() + " [truncated]"
    checksum = _checksum(text)
    existing = session.exec(
        select(EmbeddingRecord)
        .where(EmbeddingRecord.target_type == target_type)
        .where(EmbeddingRecord.target_id == target_id)
        .where(EmbeddingRecord.embedding_type == embedding_type)
        .where(EmbeddingRecord.modality == modality)
    ).first()
    record = existing or EmbeddingRecord(
        target_type=target_type,
        target_id=target_id,
        embedding_type=embedding_type,
        modality=modality,
        input_checksum=checksum,
        input_text=text,
    )
    keep_existing_vector = bool(
        existing
        and existing.input_checksum == checksum
        and existing.status == "embedded"
        and existing.vector_uri
        and existing.vector_dims
    )
    record.input_checksum = checksum
    record.input_text = text
    record.input_preview = text[:280]
    if not keep_existing_vector:
        record.model_name = model_name
        record.vector_dims = None
        record.vector_uri = None
        record.provider_record_id = None
        record.status = "ready_for_embedding"
    record.truth_status = truth_status
    snapshot = boundary_snapshot if boundary_snapshot is not None else boundary_snapshot_for_target(session, target_type, target_id)
    existing_metadata = record.metadata_json if keep_existing_vector and isinstance(record.metadata_json, dict) else {}
    record.boundary_snapshot = _normalize_boundary_snapshot(snapshot)
    record.metadata_json = {
        **existing_metadata,
        **(metadata or {}),
        "input_checksum": checksum,
        "input_char_count": len(text),
        "live_embedding_call": bool(keep_existing_vector and existing_metadata.get("live_embedding_call") is True),
        "storage_note": "Vector values are stored outside ordinary DB rows; this DB row keeps the durable embedding input and vector pointer.",
    }
    record.created_by = created_by
    record.updated_at = utcnow()
    session.add(record)
    session.flush()
    return record


def upsert_profile_embedding(
    *,
    session: Session,
    profile: MetadataProfile,
    target_boundary_type: Optional[str] = None,
    target_boundary_id: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> Optional[EmbeddingRecord]:
    boundary_target_type = target_boundary_type or profile.target_type
    boundary_target_id = target_boundary_id or profile.target_id
    boundary_snapshot = boundary_snapshot_for_target(session, boundary_target_type, boundary_target_id)
    embedding_text = "\n".join(
        part for part in [profile_embedding_text(profile), boundary_embedding_text(boundary_snapshot)] if part
    )
    return upsert_embedding_record(
        session=session,
        target_type="metadata_profile",
        target_id=profile.id,
        input_text=embedding_text,
        modality="text",
        embedding_type="retrieval_text",
        truth_status=profile.truth_status,
        boundary_snapshot=boundary_snapshot,
        metadata={
            "profile_type": profile.profile_type,
            "profile_target_type": profile.target_type,
            "profile_target_id": profile.target_id,
            **(metadata or {}),
        },
        created_by="metadata_profile_review",
    )
