from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Query
from sqlmodel import Session, select

from app.db.session import get_session
from app.models import Asset, Gallery, GalleryItem, Memory, MetadataProfile, Task

router = APIRouter(prefix="/gallery", tags=["gallery"])


def _profile_for_asset(session: Session, asset_id: str) -> Optional[MetadataProfile]:
    profiles = session.exec(
        select(MetadataProfile)
        .where(MetadataProfile.target_type == "asset")
        .where(MetadataProfile.target_id == asset_id)
        .order_by(MetadataProfile.updated_at.desc())
    ).all()
    return profiles[0] if profiles else None


def _memory_titles(session: Session, memory_ids: List[str]) -> List[str]:
    titles: List[str] = []
    for memory_id in memory_ids:
        memory = session.get(Memory, memory_id)
        if memory:
            titles.append(memory.title)
    return titles


def _boundary_allows_scope(item: GalleryItem, scope: str) -> bool:
    snapshot = item.boundary_snapshot if isinstance(item.boundary_snapshot, dict) else {}
    if scope == "public":
        return bool(snapshot.get("usable_for_gallery_public")) or item.gallery_scope == "public_candidate"
    return (
        bool(snapshot.get("usable_for_gallery_family"))
        or bool(snapshot.get("family_private"))
        or item.gallery_scope in {"family_private", "public_candidate"}
    )


def _review_status(profile: Optional[MetadataProfile], gallery: Optional[Gallery]) -> str:
    if profile and profile.metadata_status in {"reviewed", "adam_reviewed"}:
        return "reviewed"
    if profile and profile.reviewed_by == "adam":
        return "reviewed"
    if gallery and gallery.human_id == "GALLERY_MACHINE_DRAFT_PHOTOS":
        return "machine_draft"
    return "needs_review"


def _review_task_for_profile(session: Session, profile: Optional[MetadataProfile]) -> Optional[Task]:
    if profile is None:
        return None
    return session.exec(
        select(Task)
        .where(Task.target_type == "metadata_profile")
        .where(Task.target_id == profile.id)
        .where(Task.task_type.in_(["vision_draft_review", "photo_context"]))
        .where(Task.status != "canceled")
        .order_by(Task.status.asc(), Task.created_at.asc())
    ).first()


@router.get("/reviewed-photos")
def reviewed_photo_gallery(
    scope: str = Query(default="family_private", pattern="^(family_private|public)$"),
    include_drafts: bool = False,
    limit: int = Query(default=24, ge=1, le=100),
    session: Session = Depends(get_session),
) -> Dict[str, Any]:
    gallery_by_id = {gallery.id: gallery for gallery in session.exec(select(Gallery)).all()}
    all_items = session.exec(select(GalleryItem).order_by(GalleryItem.sort_order.asc(), GalleryItem.title.asc())).all()

    rows: List[Dict[str, Any]] = []
    boundary_excluded = 0
    hidden_drafts = 0
    draft_count = 0
    reviewed_count = 0

    for item in all_items:
        gallery = gallery_by_id.get(item.gallery_id)
        if not _boundary_allows_scope(item, scope):
            boundary_excluded += 1
            continue

        asset = session.get(Asset, item.asset_id)
        profile = _profile_for_asset(session, item.asset_id)
        review_status = _review_status(profile, gallery)
        requires_adam_review = review_status != "reviewed"
        review_task = _review_task_for_profile(session, profile)
        if requires_adam_review:
            draft_count += 1
            if not include_drafts:
                hidden_drafts += 1
                continue
        else:
            reviewed_count += 1

        rows.append(
            {
                "gallery_item_id": item.id,
                "gallery_id": item.gallery_id,
                "gallery_human_id": gallery.human_id if gallery else None,
                "gallery_title": gallery.title if gallery else None,
                "gallery_scope": item.gallery_scope,
                "source_photo_id": item.asset_id,
                "source_photo_title": asset.title if asset else item.title,
                "title": item.title or (asset.title if asset else "Untitled photo"),
                "display_caption": item.display_caption,
                "memory_caption": item.memory_caption,
                "linked_memory_ids": item.linked_memories,
                "linked_memory_titles": _memory_titles(session, item.linked_memories),
                "boundary_snapshot": item.boundary_snapshot,
                "review_status": review_status,
                "requires_adam_review": requires_adam_review,
                "profile_id": profile.id if profile else None,
                "profile_truth_status": profile.truth_status if profile else None,
                "profile_metadata_status": profile.metadata_status if profile else None,
                "review_task_id": review_task.id if review_task else None,
                "review_task_human_id": review_task.human_id if review_task else None,
                "review_task_queue": review_task.queue if review_task else None,
                "review_task_status": review_task.status if review_task else None,
                "preview_url": f"/api/assets/{item.asset_id}/preview?variant=display",
                "thumbnail_url": f"/api/assets/{item.asset_id}/preview?variant=thumbnail",
                "not_public_claim": scope != "public" or item.gallery_scope != "public_candidate",
            }
        )

    limited = rows[:limit]
    return {
        "gallery_type": "reviewed_photo_gallery",
        "scope": scope,
        "include_drafts": include_drafts,
        "item_count": len(limited),
        "total_available_count": len(rows),
        "reviewed_item_count": reviewed_count,
        "draft_item_count": draft_count,
        "hidden_draft_count": hidden_drafts,
        "boundary_excluded_count": boundary_excluded,
        "review_policy": "reviewed_only_by_default",
        "items": limited,
    }
