from __future__ import annotations

from typing import Any, Dict

from sqlmodel import Session, select

from app.config import settings
from app.models import Asset, Boundary, Task, utcnow
from app.services.vision import create_vision_draft_for_asset


def _string(value: Any, fallback: str = "") -> str:
    return value if isinstance(value, str) and value.strip() else fallback


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"yes", "true", "1", "ready", "approved"}
    return False


def _find_or_create_boundary(session: Session, asset_id: str) -> Boundary:
    boundary = session.exec(
        select(Boundary).where(Boundary.target_type == "asset").where(Boundary.target_id == asset_id)
    ).first()
    if boundary is None:
        boundary = Boundary(target_type="asset", target_id=asset_id)
    return boundary


def upsert_asset_triage_artifacts(
    *,
    session: Session,
    task: Task,
    decisions: Dict[str, Any],
    annotation_id: str,
) -> Dict[str, Any]:
    if task.task_type != "asset_triage":
        return {}
    asset = session.get(Asset, task.target_id)
    if asset is None:
        return {}

    source_type = _string(decisions.get("source_type"), asset.asset_type)
    if source_type != "unknown":
        asset.asset_type = source_type
    asset.processing_status = "triaged"
    asset.maturity_level = "L1_triaged"
    asset.updated_at = utcnow()
    session.add(asset)

    boundary = _find_or_create_boundary(session, asset.id)
    privacy_level = _string(decisions.get("initial_privacy_level"), "unreviewed")
    boundary.privacy_level = privacy_level
    boundary.searchable = privacy_level not in {"sealed", "private_sensitive"} and _truthy(decisions.get("process_next"))
    boundary.summarizable = privacy_level != "sealed"
    boundary.usable_for_voice_context = False
    boundary.usable_for_eval = False
    boundary.usable_for_gallery_family = False
    boundary.usable_for_gallery_public = False
    boundary.notes = _string(decisions.get("notes")) or f"Initial asset triage annotation {annotation_id}."
    boundary.reviewed_by = "adam"
    boundary.reviewed_at = utcnow()
    session.add(boundary)
    session.flush()

    result: Dict[str, Any] = {
        "asset_id": asset.id,
        "boundary_id": boundary.id,
    }

    if _truthy(decisions.get("process_next")) and asset.asset_type in {"photo", "scan"}:
        created = create_vision_draft_for_asset(
            session=session,
            asset=asset,
            queue="vision_drafts_needing_review",
            draft_type="photo_metadata",
            model_name=settings.vision_model,
            input_detail="low",
        )
        result.update(
            {
                "metadata_profile_id": created["metadata_profile_id"],
                "review_task_id": created["review_task_id"],
                "next_queue": "vision_drafts_needing_review",
            }
        )

    return result
