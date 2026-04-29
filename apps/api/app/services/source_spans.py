from __future__ import annotations

from typing import Any, Dict, List

from sqlmodel import Session

from app.models import SourceSpanAnnotation, Task


def _string(value: Any, fallback: str = "") -> str:
    return value if isinstance(value, str) else fallback


def _int(value: Any, fallback: int = 0) -> int:
    if isinstance(value, bool):
        return fallback
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str) and value.strip().lstrip("-").isdigit():
        return int(value.strip())
    return fallback


def _span_items(decisions: Dict[str, Any]) -> List[Dict[str, Any]]:
    raw = decisions.get("source_spans")
    if not isinstance(raw, list):
        return []
    return [item for item in raw if isinstance(item, dict)]


def create_source_span_annotations(
    *,
    session: Session,
    task: Task,
    decisions: Dict[str, Any],
    annotation_id: str,
) -> List[SourceSpanAnnotation]:
    created: List[SourceSpanAnnotation] = []
    source_asset_id = _string(decisions.get("source_asset_id")) or _string(task.input_payload.get("asset_id")) or None
    source_segment_id = _string(decisions.get("source_segment_id")) or (
        task.target_id if task.target_type == "segment" else _string(task.input_payload.get("segment_id")) or None
    )
    for item in _span_items(decisions):
        selected_text = _string(item.get("text")) or _string(item.get("selected_text"))
        start_char = _int(item.get("start_char"))
        end_char = _int(item.get("end_char"))
        if not selected_text.strip() or end_char <= start_char:
            continue
        span = SourceSpanAnnotation(
            task_id=task.id,
            annotation_id=annotation_id,
            target_type=task.target_type,
            target_id=task.target_id,
            source_asset_id=source_asset_id,
            source_segment_id=source_segment_id,
            start_char=start_char,
            end_char=end_char,
            selected_text=selected_text,
            span_type=_string(item.get("span_type"), "context"),
            speaker=_string(item.get("speaker")) or None,
            code=_string(item.get("code")) or None,
            notes=_string(item.get("notes")) or None,
            metadata_json={
                key: value
                for key, value in item.items()
                if key not in {"text", "selected_text", "start_char", "end_char", "span_type", "speaker", "code", "notes"}
            },
        )
        session.add(span)
        created.append(span)
    session.flush()
    return created
