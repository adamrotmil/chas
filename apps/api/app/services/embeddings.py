from __future__ import annotations

import hashlib
import re
from typing import Any, Dict, Iterable, List, Optional

from sqlmodel import Session, select

from app.models import Boundary, EmbeddingRecord, MetadataProfile, utcnow


MAX_EMBEDDING_INPUT_CHARS = 4000


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
    record.model_name = model_name
    record.input_checksum = checksum
    record.input_text = text
    record.input_preview = text[:280]
    record.vector_dims = None
    record.vector_uri = None
    record.provider_record_id = None
    record.status = "ready_for_embedding"
    record.truth_status = truth_status
    snapshot = boundary_snapshot if boundary_snapshot is not None else boundary_snapshot_for_target(session, target_type, target_id)
    record.boundary_snapshot = _normalize_boundary_snapshot(snapshot)
    record.metadata_json = {
        **(metadata or {}),
        "input_checksum": checksum,
        "input_char_count": len(text),
        "live_embedding_call": False,
        "storage_note": "Vector values are not stored in ordinary DB rows in this scaffold; this record is the durable embedding input plan.",
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
