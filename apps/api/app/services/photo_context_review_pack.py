from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from sqlmodel import Session, select

from app.models import Asset, Boundary, Gallery, GalleryItem, MetadataProfile, Task
from app.services.retrieval import REVIEWED_PHOTO_MEMORY_TRUTH_STATUSES, photo_memory_embedding_export


UNSAFE_VECTOR_TRUTH_STATUSES = {"system_inference", "model_generated"}


def _photo_title(asset: Optional[Asset], fallback: str = "Untitled photo") -> str:
    if asset is None:
        return fallback
    return asset.title or asset.original_filename or asset.human_id or fallback


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


def _is_previewable_photo(asset: Asset) -> bool:
    return asset.processing_status in {"image_preview_ready", "photo_memory_reviewed"}


def _canonical_photo_asset(assets: List[Asset]) -> Asset:
    return sorted(assets, key=lambda asset: (_is_copy_variant(asset), len(_photo_title(asset)), _photo_title(asset)))[0]


def _preview_urls(asset_id: str) -> Dict[str, str]:
    return {
        "preview_url": f"/api/assets/{asset_id}/preview?variant=display",
        "thumbnail_url": f"/api/assets/{asset_id}/preview?variant=thumbnail",
    }


def _task_summary(task: Optional[Task]) -> Dict[str, Optional[str]]:
    return {
        "task_id": task.id if task else None,
        "task_human_id": task.human_id if task else None,
        "queue": task.queue if task else None,
        "status": task.status if task else None,
    }


def _existing_photo_context_task(session: Session, asset_id: str) -> Optional[Task]:
    return session.exec(
        select(Task)
        .where(Task.task_type == "photo_context")
        .where(Task.target_type == "asset")
        .where(Task.target_id == asset_id)
        .where(Task.status == "ready")
        .order_by(Task.created_at.asc())
    ).first()


def _review_task_for_profile(session: Session, profile_id: str) -> Optional[Task]:
    return session.exec(
        select(Task)
        .where(Task.target_type == "metadata_profile")
        .where(Task.target_id == profile_id)
        .where(Task.task_type.in_(["vision_draft_review", "photo_context"]))
        .where(Task.status != "canceled")
        .order_by(Task.status.asc(), Task.created_at.asc())
    ).first()


def _profile_for_gallery_asset(session: Session, asset_id: str) -> Optional[MetadataProfile]:
    return session.exec(
        select(MetadataProfile)
        .where(MetadataProfile.target_type == "asset")
        .where(MetadataProfile.target_id == asset_id)
        .order_by(MetadataProfile.updated_at.desc())
    ).first()


def _boundary_for_asset(session: Session, asset_id: str) -> Optional[Boundary]:
    return session.exec(
        select(Boundary).where(Boundary.target_type == "asset").where(Boundary.target_id == asset_id)
    ).first()


def _gallery_review_status(profile: Optional[MetadataProfile], gallery: Optional[Gallery]) -> str:
    if profile and (profile.metadata_status in {"reviewed", "adam_reviewed"} or profile.reviewed_by == "adam"):
        return "reviewed"
    if gallery and gallery.human_id == "GALLERY_MACHINE_DRAFT_PHOTOS":
        return "machine_draft"
    return "needs_review"


def _reviewed_vector_record_is_safe(record: Dict[str, Any]) -> bool:
    metadata = record.get("metadata") if isinstance(record.get("metadata"), dict) else {}
    boundary = metadata.get("boundary_snapshot") if isinstance(metadata.get("boundary_snapshot"), dict) else {}
    truth_status = metadata.get("truth_status")
    return (
        metadata.get("source") == "photo_memory_review"
        and truth_status in REVIEWED_PHOTO_MEMORY_TRUTH_STATUSES
        and truth_status not in UNSAFE_VECTOR_TRUTH_STATUSES
        and boundary.get("reviewed_by") == "adam"
    )


def _safe_preview(value: Optional[str], *, limit: int = 320) -> str:
    if not value:
        return ""
    normalized = re.sub(r"\s+", " ", value).strip()
    return normalized[:limit]


def _yaml_scalar(value: Any) -> str:
    if value is True:
        return "true"
    if value is False:
        return "false"
    if value is None:
        return "null"
    if isinstance(value, (int, float)):
        return str(value)
    text = str(value)
    if re.fullmatch(r"[A-Za-z0-9_./:-]+(?: [A-Za-z0-9_./:-]+)*", text):
        return text
    return json.dumps(text, ensure_ascii=False)


def _yaml_preview(pack: Dict[str, Any]) -> str:
    manifest = pack["manifest"]
    lines = [
        "photo_context_review_pack:",
        f"  review_policy: {_yaml_scalar(pack['review_policy'])}",
        f"  content_sha256: {_yaml_scalar(pack['content_sha256'])}",
        "  counts:",
    ]
    for key in [
        "photo_count",
        "preview_ready_count",
        "needs_context_count",
        "needs_context_group_count",
        "machine_draft_count",
        "held_for_adam_review_count",
        "reviewed_vector_ready_count",
        "gallery_preview_item_count",
        "photo_context_worklist_count",
    ]:
        lines.append(f"    {key}: {_yaml_scalar(manifest.get(key, 0))}")
    lines.extend(
        [
            "  review_worklists:",
            *[
                "\n".join(
                    [
                        f"    - key: {_yaml_scalar(item['worklist_key'])}",
                        f"      title: {_yaml_scalar(item['title'])}",
                        f"      truth_status: {_yaml_scalar(item['truth_status'])}",
                        f"      not_memory_claim: {_yaml_scalar(item['not_memory_claim'])}",
                        f"      candidate_count: {_yaml_scalar(item['candidate_count'])}",
                        f"      review_sequence_key: {_yaml_scalar(item['review_sequence_key'])}",
                    ]
                )
                for item in pack["review_worklists"][:5]
            ],
        ]
    )
    if not pack["review_worklists"]:
        lines.append("    []")
    lines.extend(
        [
            "  no_claim_photo_groups:",
            *[
                "\n".join(
                    [
                        f"    - title: {_yaml_scalar(item['display_title'])}",
                        f"      group_key: {_yaml_scalar(item['group_key'])}",
                        f"      truth_status: {_yaml_scalar(item['truth_status'])}",
                        f"      not_memory_claim: {_yaml_scalar(item['not_memory_claim'])}",
                        f"      action: {_yaml_scalar(item['primary_action']['action_type'])}",
                    ]
                )
                for item in pack["needs_context_groups"][:5]
            ],
        ]
    )
    if not pack["needs_context_groups"]:
        lines.append("    []")
    lines.append("  machine_drafts_held:")
    if pack["machine_drafts_held"]:
        for item in pack["machine_drafts_held"][:5]:
            lines.extend(
                [
                    f"    - title: {_yaml_scalar(item['source_photo_title'])}",
                    f"      truth_status: {_yaml_scalar(item['truth_status'])}",
                    f"      requires_adam_review: {_yaml_scalar(item['requires_adam_review'])}",
                    f"      review_task_human_id: {_yaml_scalar(item.get('review_task_human_id'))}",
                ]
            )
    else:
        lines.append("    []")
    lines.append("  reviewed_vector_ready:")
    if pack["reviewed_vector_ready"]:
        for item in pack["reviewed_vector_ready"][:5]:
            lines.extend(
                [
                    f"    - title: {_yaml_scalar(item['title'])}",
                    f"      truth_status: {_yaml_scalar(item['truth_status'])}",
                    f"      source_photo_id: {_yaml_scalar(item['source_photo_id'])}",
                    f"      embedding_record_id: {_yaml_scalar(item['embedding_record_id'])}",
                ]
            )
    else:
        lines.append("    []")
    return "\n".join(lines) + "\n"


def _markdown(pack: Dict[str, Any]) -> str:
    manifest = pack["manifest"]
    lines = [
        "# Photo Context Review Pack",
        "",
        f"- Review policy: `{pack['review_policy']}`",
        f"- Photos: {manifest['preview_ready_count']} preview-ready of {manifest['photo_count']}",
        f"- Needs context: {manifest['needs_context_group_count']} groups / {manifest['needs_context_count']} assets",
        f"- Machine drafts held: {manifest['held_for_adam_review_count']}",
        f"- Reviewed vector-ready records: {manifest['reviewed_vector_ready_count']}",
        f"- Review worklists: {manifest['photo_context_worklist_count']}",
        "",
        "## Review Worklists",
    ]
    for item in pack["review_worklists"]:
        lines.append(
            f"- {item['title']}: {item['candidate_count']} candidates, `{item['truth_status']}`, sequence `{item['review_sequence_key']}`"
        )
    if not pack["review_worklists"]:
        lines.append("- None")
    lines.extend(
        [
            "",
            "## Needs Context",
        ]
    )
    for item in pack["needs_context_groups"][:10]:
        lines.append(
            f"- {item['display_title']} ({item['asset_count']} assets): `{item['truth_status']}`, not memory claim, action `{item['primary_action']['action_type']}`"
        )
    if not pack["needs_context_groups"]:
        lines.append("- None")
    lines.extend(["", "## Machine Drafts Held"])
    for item in pack["machine_drafts_held"][:10]:
        lines.append(
            f"- {item['source_photo_title']}: `{item['truth_status']}`, requires Adam review via `{item.get('review_task_human_id') or 'missing task'}`"
        )
    if not pack["machine_drafts_held"]:
        lines.append("- None")
    lines.extend(["", "## Reviewed Vector Handoff"])
    for item in pack["reviewed_vector_ready"][:10]:
        lines.append(f"- {item['title']}: `{item['truth_status']}`, `{item['embedding_record_id']}`")
    if not pack["reviewed_vector_ready"]:
        lines.append("- None yet")
    return "\n".join(lines) + "\n"


def _stable_hash(payload: Dict[str, Any]) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _photo_context_worklists(
    *,
    needs_context_groups: List[Dict[str, Any]],
    machine_drafts_held: List[Dict[str, Any]],
    gallery_preview_items: List[Dict[str, Any]],
    preview_limit: int = 10,
) -> List[Dict[str, Any]]:
    worklists: List[Dict[str, Any]] = []

    if needs_context_groups:
        preview_items = needs_context_groups[:preview_limit]
        sequence_ids = [f"{item['group_key']}:{item['canonical_asset_id']}" for item in needs_context_groups]
        worklists.append(
            {
                "worklist_key": "photo_context:no_claim_needs_context",
                "title": "No-claim photo groups needing Adam context",
                "priority_rank": 1,
                "item_kind": "photo_group",
                "truth_status": "no_claim",
                "not_memory_claim": True,
                "candidate_count": len(needs_context_groups),
                "reported_candidate_count": len(preview_items),
                "review_sequence_key": _stable_hash({"worklist_key": "photo_context:no_claim_needs_context", "sequence_ids": sequence_ids}),
                "review_policy": "create_or_open_context_task_before_memory_claim",
                "recommended_action": needs_context_groups[0]["primary_action"],
                "candidate_previews": [
                    {
                        "sequence_number": index,
                        "item_key": item["group_key"],
                        "display_title": item["display_title"],
                        "source_photo_id": item["canonical_asset_id"],
                        "preview_url": item["preview_url"],
                        "thumbnail_url": item["thumbnail_url"],
                        "truth_status": item["truth_status"],
                        "not_memory_claim": item["not_memory_claim"],
                        "evidence_source": item["evidence_source"],
                        "asset_count": item["asset_count"],
                        "action": item["primary_action"],
                    }
                    for index, item in enumerate(preview_items, start=1)
                ],
            }
        )

    if machine_drafts_held:
        preview_items = machine_drafts_held[:preview_limit]
        sequence_ids = [f"{item['metadata_profile_id']}:{item['source_photo_id']}" for item in machine_drafts_held]
        first = machine_drafts_held[0]
        worklists.append(
            {
                "worklist_key": "photo_context:machine_draft_needs_adam_review",
                "title": "Machine photo-memory drafts needing Adam review",
                "priority_rank": 2,
                "item_kind": "metadata_profile",
                "truth_status": "system_inference",
                "not_memory_claim": True,
                "candidate_count": len(machine_drafts_held),
                "reported_candidate_count": len(preview_items),
                "review_sequence_key": _stable_hash(
                    {"worklist_key": "photo_context:machine_draft_needs_adam_review", "sequence_ids": sequence_ids}
                ),
                "review_policy": "adam_review_required_before_vector_handoff",
                "recommended_action": {
                    "action_type": "open_machine_draft_review",
                    "label": "Open machine draft review",
                    "task_id": first.get("task_id"),
                    "task_human_id": first.get("task_human_id"),
                    "source_photo_id": first["source_photo_id"],
                    "queue": first.get("queue"),
                },
                "candidate_previews": [
                    {
                        "sequence_number": index,
                        "item_key": item["metadata_profile_id"],
                        "display_title": item["source_photo_title"],
                        "source_photo_id": item["source_photo_id"],
                        "preview_url": item["preview_url"],
                        "thumbnail_url": item["thumbnail_url"],
                        "truth_status": item["truth_status"],
                        "requires_adam_review": item["requires_adam_review"],
                        "not_memory_claim": True,
                        "summary_preview": item["summary_preview"],
                        "action": {
                            "action_type": "open_machine_draft_review",
                            "label": "Open machine draft review",
                            "task_id": item.get("task_id"),
                            "task_human_id": item.get("task_human_id"),
                            "queue": item.get("queue"),
                        },
                    }
                    for index, item in enumerate(preview_items, start=1)
                ],
            }
        )

    draft_gallery_items = [item for item in gallery_preview_items if item["requires_adam_review"]]
    if draft_gallery_items:
        preview_items = draft_gallery_items[:preview_limit]
        sequence_ids = [f"{item['gallery_item_id']}:{item['source_photo_id']}" for item in draft_gallery_items]
        first = draft_gallery_items[0]
        worklists.append(
            {
                "worklist_key": "photo_context:gallery_draft_needs_review",
                "title": "Gallery draft photos needing review labels",
                "priority_rank": 3,
                "item_kind": "gallery_item",
                "truth_status": first.get("profile_truth_status") or "system_inference",
                "not_memory_claim": True,
                "candidate_count": len(draft_gallery_items),
                "reported_candidate_count": len(preview_items),
                "review_sequence_key": _stable_hash({"worklist_key": "photo_context:gallery_draft_needs_review", "sequence_ids": sequence_ids}),
                "review_policy": "draft_gallery_items_require_adam_review_before_public_or_vector_use",
                "recommended_action": {
                    "action_type": "open_gallery_draft_review",
                    "label": "Open gallery draft review",
                    "task_id": first.get("task_id"),
                    "task_human_id": first.get("task_human_id"),
                    "source_photo_id": first["source_photo_id"],
                    "queue": first.get("queue"),
                },
                "candidate_previews": [
                    {
                        "sequence_number": index,
                        "item_key": item["gallery_item_id"],
                        "display_title": item["title"],
                        "source_photo_id": item["source_photo_id"],
                        "preview_url": item["preview_url"],
                        "thumbnail_url": item["thumbnail_url"],
                        "truth_status": item.get("profile_truth_status") or "system_inference",
                        "requires_adam_review": item["requires_adam_review"],
                        "not_memory_claim": True,
                        "review_status": item["review_status"],
                        "action": {
                            "action_type": "open_gallery_draft_review",
                            "label": "Open gallery draft review",
                            "task_id": item.get("task_id"),
                            "task_human_id": item.get("task_human_id"),
                            "queue": item.get("queue"),
                        },
                    }
                    for index, item in enumerate(preview_items, start=1)
                ],
            }
        )

    return worklists


def build_photo_context_review_pack(
    *,
    session: Session,
    scope: str = "family_private",
    limit: int = 100,
) -> Dict[str, Any]:
    capped_limit = max(1, min(limit, 500))
    photos = session.exec(select(Asset).where(Asset.asset_type == "photo").order_by(Asset.created_at.asc())).all()
    photo_ids = [asset.id for asset in photos]
    profiles = (
        session.exec(
            select(MetadataProfile)
            .where(MetadataProfile.target_type == "asset")
            .where(MetadataProfile.target_id.in_(photo_ids))
            .where(MetadataProfile.profile_type == "photo_memory")
            .order_by(MetadataProfile.updated_at.desc())
        ).all()
        if photo_ids
        else []
    )
    profiles_by_asset: Dict[str, List[MetadataProfile]] = {}
    for profile in profiles:
        profiles_by_asset.setdefault(profile.target_id, []).append(profile)

    grouped: Dict[str, List[Asset]] = {}
    for asset in photos:
        grouped.setdefault(_photo_group_key(asset), []).append(asset)

    needs_context_groups: List[Dict[str, Any]] = []
    for group_key, group_assets in grouped.items():
        preview_assets = [asset for asset in group_assets if _is_previewable_photo(asset)]
        if not preview_assets:
            continue
        group_profiles = [profile for asset in group_assets for profile in profiles_by_asset.get(asset.id, [])]
        if group_profiles:
            continue
        canonical = _canonical_photo_asset(preview_assets)
        context_task = _existing_photo_context_task(session, canonical.id)
        primary_action = (
            {
                "action_type": "open_existing_photo_context_task",
                "label": "Open context task",
                "task_id": context_task.id,
                "task_human_id": context_task.human_id,
                "queue": context_task.queue,
            }
            if context_task
            else {
                "action_type": "create_photo_context_task",
                "label": "Create context task",
                "queue": "photo_assets_needing_context",
                "request": {
                    "endpoint": "/api/assets/photo-review-inventory/context-task",
                    "method": "POST",
                    "body": {"group_key": group_key, "asset_id": canonical.id, "use_canonical": True},
                },
            }
        )
        needs_context_groups.append(
            {
                "group_key": group_key,
                "display_title": _photo_title(canonical),
                "canonical_asset_id": canonical.id,
                **_preview_urls(canonical.id),
                "asset_count": len(group_assets),
                "preview_ready_count": len(preview_assets),
                "variant_titles": [_photo_title(asset) for asset in sorted(group_assets, key=_photo_title)],
                "truth_status": "no_claim",
                "not_memory_claim": True,
                "evidence_source": "title_filename_only",
                "candidate_queue": "photo_assets_needing_context",
                "existing_context_task": _task_summary(context_task),
                "primary_action": primary_action,
                "suggested_context_fields": [
                    "visible_facts",
                    "invisible_context",
                    "meaning",
                    "uncertainty",
                    "privacy_level",
                    "ready_for_downstream",
                ],
            }
        )
    needs_context_groups.sort(key=lambda item: (-int(item["asset_count"]), item["display_title"]))

    machine_drafts_held: List[Dict[str, Any]] = []
    for profile in profiles:
        if profile.metadata_status != "machine_draft_needs_adam_review":
            continue
        asset = session.get(Asset, profile.target_id)
        if asset is None:
            continue
        boundary = _boundary_for_asset(session, asset.id)
        review_task = _review_task_for_profile(session, profile.id)
        machine_drafts_held.append(
            {
                "source_photo_id": asset.id,
                "source_photo_title": _photo_title(asset),
                **_preview_urls(asset.id),
                "metadata_profile_id": profile.id,
                "profile_status": profile.metadata_status,
                "truth_status": profile.truth_status or "system_inference",
                "reviewed_by": profile.reviewed_by or "system_draft",
                "requires_adam_review": True,
                "does_not_certify_final_memory": True,
                "not_for_downstream_vector_store": True,
                "summary_preview": _safe_preview(profile.summary),
                "context_preview": _safe_preview(profile.adam_context_note),
                "open_questions": profile.open_questions,
                "boundary_snapshot": boundary.model_dump(mode="json") if boundary else {"boundary_status": "missing"},
                **_task_summary(review_task),
                "candidate_evidence": {
                    "not_memory_claim": True,
                    "evidence_source": "machine_photo_memory_draft",
                    "truth_status": profile.truth_status or "system_inference",
                    "requires_adam_review": True,
                    "does_not_certify_final_memory": True,
                },
            }
        )
    machine_drafts_held.sort(key=lambda item: item["source_photo_title"])

    vector_export = photo_memory_embedding_export(session=session, scope=scope, limit=capped_limit)
    reviewed_vector_ready: List[Dict[str, Any]] = []
    vector_policy_violations: List[Dict[str, Any]] = []
    for record in vector_export["records"]:
        metadata = record.get("metadata") if isinstance(record.get("metadata"), dict) else {}
        source_photo_id = metadata.get("source_photo_id")
        row = {
            "id": record.get("id"),
            "embedding_record_id": metadata.get("embedding_record_id"),
            "target_type": metadata.get("target_type"),
            "target_id": metadata.get("target_id"),
            "source_photo_id": source_photo_id,
            "title": metadata.get("title"),
            "truth_status": metadata.get("truth_status"),
            "input_preview": _safe_preview(record.get("text"), limit=420),
            "metadata_source": metadata.get("source"),
            "boundary_snapshot": metadata.get("boundary_snapshot") if isinstance(metadata.get("boundary_snapshot"), dict) else {},
            **(_preview_urls(str(source_photo_id)) if isinstance(source_photo_id, str) and source_photo_id else {}),
        }
        if _reviewed_vector_record_is_safe(record):
            reviewed_vector_ready.append(row)
        else:
            vector_policy_violations.append(row)

    gallery_by_id = {gallery.id: gallery for gallery in session.exec(select(Gallery)).all()}
    gallery_preview_items: List[Dict[str, Any]] = []
    gallery_items = session.exec(select(GalleryItem).order_by(GalleryItem.sort_order.asc(), GalleryItem.title.asc())).all()
    for item in gallery_items[:capped_limit]:
        asset = session.get(Asset, item.asset_id)
        profile = _profile_for_gallery_asset(session, item.asset_id)
        gallery = gallery_by_id.get(item.gallery_id)
        review_status = _gallery_review_status(profile, gallery)
        review_task = _review_task_for_profile(session, profile.id) if profile else None
        gallery_preview_items.append(
            {
                "gallery_item_id": item.id,
                "gallery_human_id": gallery.human_id if gallery else None,
                "gallery_scope": item.gallery_scope,
                "source_photo_id": item.asset_id,
                "source_photo_title": _photo_title(asset, item.title or "Untitled photo"),
                **_preview_urls(item.asset_id),
                "title": item.title or _photo_title(asset, "Untitled photo"),
                "display_caption": item.display_caption,
                "memory_caption": item.memory_caption,
                "review_status": review_status,
                "requires_adam_review": review_status != "reviewed",
                "profile_id": profile.id if profile else None,
                "profile_truth_status": profile.truth_status if profile else None,
                "profile_metadata_status": profile.metadata_status if profile else None,
                "boundary_snapshot": item.boundary_snapshot,
                **_task_summary(review_task),
            }
        )

    held_for_adam_review_count = len(machine_drafts_held)
    if isinstance(vector_export.get("manifest"), dict):
        held_for_adam_review_count = max(
            held_for_adam_review_count,
            int(vector_export["manifest"].get("held_for_adam_review_count") or 0),
        )
    review_worklists = _photo_context_worklists(
        needs_context_groups=needs_context_groups,
        machine_drafts_held=machine_drafts_held,
        gallery_preview_items=gallery_preview_items,
    )
    manifest = {
        "photo_count": len(photos),
        "preview_ready_count": len([asset for asset in photos if _is_previewable_photo(asset)]),
        "needs_context_count": sum(int(item["preview_ready_count"]) for item in needs_context_groups),
        "needs_context_group_count": len(needs_context_groups),
        "machine_draft_count": len(machine_drafts_held),
        "held_for_adam_review_count": held_for_adam_review_count,
        "reviewed_vector_ready_count": len(reviewed_vector_ready),
        "vector_policy_violation_count": len(vector_policy_violations),
        "gallery_preview_item_count": len(gallery_preview_items),
        "photo_context_worklist_count": len(review_worklists),
        "scope": scope,
        "limit": capped_limit,
        "review_policy": "reviewed_only_by_default",
        "vector_policy": {
            "reviewed_only_by_default": True,
            "system_inference_excluded_by_default": True,
            "model_generated_excluded_by_default": True,
            "ordinary_db_vector_storage": False,
        },
    }
    pack_without_previews = {
        "pack_type": "photo_context_review_pack",
        "review_policy": "reviewed_only_by_default",
        "manifest": manifest,
        "needs_context_groups": needs_context_groups[:capped_limit],
        "machine_drafts_held": machine_drafts_held[:capped_limit],
        "reviewed_vector_ready": reviewed_vector_ready[:capped_limit],
        "vector_policy_violations": vector_policy_violations[:capped_limit],
        "gallery_preview_items": gallery_preview_items[:capped_limit],
        "review_worklists": review_worklists,
    }
    content_sha256 = _stable_hash(pack_without_previews)
    pack: Dict[str, Any] = {
        **pack_without_previews,
        "content_sha256": content_sha256,
    }
    pack["export_preview_yaml"] = _yaml_preview(pack)
    pack["markdown"] = _markdown(pack)
    return pack


def build_photo_context_top_slice(
    *,
    session: Session,
    scope: str = "family_private",
    limit: int = 5,
) -> Dict[str, Any]:
    safe_limit = max(1, min(limit, 25))
    pack = build_photo_context_review_pack(session=session, scope=scope, limit=max(safe_limit, 25))
    worklists = pack.get("review_worklists") if isinstance(pack.get("review_worklists"), list) else []
    top_worklist = worklists[0] if worklists else None
    if not isinstance(top_worklist, dict):
        stable_payload = {"worklist_key": None, "items": []}
        return {
            "slice_type": "photo_context_top_slice",
            "review_policy": "top_photo_context_slice_no_memory_claim",
            "does_not_create_memory_claim": True,
            "requires_adam_context": True,
            "worklist_key": None,
            "candidate_count": 0,
            "reported_candidate_count": 0,
            "completion_signal": "needs_context_group_count_decreases_or_review_task_becomes_submit_ready",
            "safety_boundaries": [
                "Photo filename/title evidence remains no_claim until Adam-authored context exists.",
                "Do not create vector-ready memory records from this read-only slice.",
            ],
            "recommended_action": None,
            "items": [],
            "content_sha256": _stable_hash(stable_payload),
        }

    groups_by_key = {
        group["group_key"]: group
        for group in pack.get("needs_context_groups", [])
        if isinstance(group, dict) and group.get("group_key")
    }
    previews = top_worklist.get("candidate_previews") if isinstance(top_worklist.get("candidate_previews"), list) else []
    items = []
    for preview in previews[:safe_limit]:
        if not isinstance(preview, dict):
            continue
        group = groups_by_key.get(str(preview.get("item_key"))) or {}
        action = preview.get("action") if isinstance(preview.get("action"), dict) else {}
        items.append(
            {
                "sequence_number": preview.get("sequence_number"),
                "item_key": preview.get("item_key"),
                "display_title": preview.get("display_title"),
                "source_photo_id": preview.get("source_photo_id"),
                "preview_url": preview.get("preview_url"),
                "thumbnail_url": preview.get("thumbnail_url"),
                "asset_count": preview.get("asset_count") or group.get("asset_count"),
                "variant_titles": group.get("variant_titles") if isinstance(group.get("variant_titles"), list) else [],
                "truth_status": preview.get("truth_status") or "no_claim",
                "not_memory_claim": preview.get("not_memory_claim") is not False,
                "evidence_source": preview.get("evidence_source") or group.get("evidence_source") or "title_filename_only",
                "suggested_context_fields": group.get("suggested_context_fields")
                if isinstance(group.get("suggested_context_fields"), list)
                else ["visible_facts", "invisible_context", "meaning", "uncertainty"],
                "action": action,
                "completion_criteria": [
                    "Open or create the photo context task for this canonical photo group.",
                    "Add Adam-authored visible facts, invisible context, meaning, uncertainty, and boundary decisions.",
                    "Submit only when the photo is no longer a filename-only no_claim candidate.",
                ],
            }
        )

    stable_payload = {
        "worklist_key": top_worklist.get("worklist_key"),
        "review_sequence_key": top_worklist.get("review_sequence_key"),
        "items": items,
    }
    return {
        "slice_type": "photo_context_top_slice",
        "review_policy": "top_photo_context_slice_no_memory_claim",
        "does_not_create_memory_claim": True,
        "requires_adam_context": True,
        "worklist_key": top_worklist.get("worklist_key"),
        "title": top_worklist.get("title"),
        "candidate_count": top_worklist.get("candidate_count"),
        "reported_candidate_count": len(items),
        "review_sequence_key": top_worklist.get("review_sequence_key"),
        "completion_signal": "needs_context_group_count_decreases_or_review_task_becomes_submit_ready",
        "safety_boundaries": [
            "Photo filename/title evidence remains no_claim until Adam-authored context exists.",
            "Do not create vector-ready memory records from this read-only slice.",
        ],
        "recommended_action": top_worklist.get("recommended_action"),
        "items": items,
        "content_sha256": _stable_hash(stable_payload),
    }


PHOTO_CONTEXT_FIELD_PLAN = [
    {
        "field": "visible_facts",
        "prompt": "What is visibly present in the photograph?",
        "truth_status_after_submit": "adam_memory",
    },
    {
        "field": "invisible_context",
        "prompt": "What does Adam know about this photo that is not visible in the pixels?",
        "truth_status_after_submit": "adam_memory",
    },
    {
        "field": "meaning",
        "prompt": "What memory, story, relationship, or event does this photo anchor?",
        "truth_status_after_submit": "adam_memory",
    },
    {
        "field": "uncertainty",
        "prompt": "What should remain uncertain or be checked later?",
        "truth_status_after_submit": "adam_inference",
    },
]


def _review_session_plan_yaml(plan: Dict[str, Any]) -> str:
    lines = [
        "photo_context_review_session_plan:",
        f"  review_policy: {_yaml_scalar(plan.get('review_policy'))}",
        f"  source_query: {_yaml_scalar(plan.get('source_query'))}",
        f"  scope: {_yaml_scalar(plan.get('scope'))}",
        f"  selected_count: {_yaml_scalar(plan.get('selected_count'))}",
        f"  candidate_count: {_yaml_scalar(plan.get('candidate_count'))}",
        f"  content_sha256: {_yaml_scalar(plan.get('content_sha256'))}",
        "  boundaries:",
        f"    does_not_mutate_state: {_yaml_scalar(plan.get('does_not_mutate_state'))}",
        f"    does_not_create_memory_claim: {_yaml_scalar(plan.get('does_not_create_memory_claim'))}",
        f"    requires_adam_context: {_yaml_scalar(plan.get('requires_adam_context'))}",
        "    query_is_context_prioritization_only: true",
        "  field_plan:",
    ]
    for field in plan.get("field_plan") or []:
        if not isinstance(field, dict):
            continue
        lines.extend(
            [
                f"    - field: {_yaml_scalar(field.get('field'))}",
                f"      prompt: {_yaml_scalar(field.get('prompt'))}",
                f"      truth_status_after_submit: {_yaml_scalar(field.get('truth_status_after_submit'))}",
            ]
        )
    lines.append("  items:")
    items = plan.get("items") if isinstance(plan.get("items"), list) else []
    if not items:
        lines.append("    []")
    for item in items:
        if not isinstance(item, dict):
            continue
        query_origin = item.get("query_origin") if isinstance(item.get("query_origin"), dict) else {}
        action = item.get("action") if isinstance(item.get("action"), dict) else {}
        lines.extend(
            [
                f"    - sequence_number: {_yaml_scalar(item.get('sequence_number'))}",
                f"      title: {_yaml_scalar(item.get('display_title'))}",
                f"      canonical_asset_id: {_yaml_scalar(item.get('canonical_asset_id'))}",
                f"      truth_status: {_yaml_scalar(item.get('truth_status'))}",
                f"      not_memory_claim: {_yaml_scalar(item.get('not_memory_claim'))}",
                f"      query_origin: {_yaml_scalar(query_origin.get('source_query'))}",
                f"      query_is_context_prioritization_only: {_yaml_scalar(query_origin.get('query_is_context_prioritization_only'))}",
                f"      action: {_yaml_scalar(action.get('action_type'))}",
                f"      task_human_id: {_yaml_scalar(action.get('task_human_id'))}",
            ]
        )
    return "\n".join(lines) + "\n"


def build_photo_context_review_session_plan(
    *,
    session: Session,
    scope: str = "family_private",
    limit: int = 5,
    source_query: str = "airplane in Maine",
) -> Dict[str, Any]:
    safe_limit = max(1, min(limit, 25))
    top_slice = build_photo_context_top_slice(session=session, scope=scope, limit=safe_limit)
    items = []
    action_counts: Dict[str, int] = {}
    for item in (top_slice.get("items") if isinstance(top_slice.get("items"), list) else []):
        if not isinstance(item, dict):
            continue
        action = item.get("action") if isinstance(item.get("action"), dict) else {}
        action_type = str(action.get("action_type") or "unknown_action")
        action_counts[action_type] = action_counts.get(action_type, 0) + 1
        items.append(
            {
                "sequence_number": item.get("sequence_number"),
                "group_key": item.get("item_key"),
                "display_title": item.get("display_title"),
                "canonical_asset_id": item.get("source_photo_id"),
                "preview_url": item.get("preview_url"),
                "thumbnail_url": item.get("thumbnail_url"),
                "asset_count": item.get("asset_count"),
                "truth_status": item.get("truth_status") or "no_claim",
                "not_memory_claim": item.get("not_memory_claim") is not False,
                "query_origin": {
                    "source_query": source_query,
                    "query_is_context_prioritization_only": True,
                    "not_memory_claim": True,
                },
                "field_plan": PHOTO_CONTEXT_FIELD_PLAN,
                "action": action,
                "completion_criteria": item.get("completion_criteria") or [],
            }
        )

    stable_payload = {
        "source_query": source_query,
        "scope": scope,
        "worklist_key": top_slice.get("worklist_key"),
        "review_sequence_key": top_slice.get("review_sequence_key"),
        "items": items,
    }
    plan = {
        "plan_type": "photo_context_review_session_plan",
        "review_policy": "query_aware_photo_context_session_plan_no_mutation",
        "does_not_mutate_state": True,
        "does_not_create_memory_claim": True,
        "requires_adam_context": True,
        "scope": scope,
        "source_query": source_query,
        "requested_limit": safe_limit,
        "selected_count": len(items),
        "candidate_count": top_slice.get("candidate_count") or 0,
        "worklist_key": top_slice.get("worklist_key"),
        "review_sequence_key": top_slice.get("review_sequence_key"),
        "completion_signal": "create_or_open_context_tasks_then_submit_adam_context_until_needs_context_count_decreases",
        "safety_boundaries": [
            "This plan is read-only and does not create tasks.",
            "Filename/title evidence remains no_claim until Adam-authored context is submitted.",
            "Source query is prioritization context, not evidence that the photo depicts the query.",
        ],
        "field_plan": PHOTO_CONTEXT_FIELD_PLAN,
        "dry_run_action_counts": action_counts,
        "items": items,
        "content_sha256": _stable_hash(stable_payload),
    }
    export_preview_yaml = _review_session_plan_yaml(plan)
    plan["export_preview_yaml"] = export_preview_yaml
    plan["export_preview_sha256"] = hashlib.sha256(export_preview_yaml.encode("utf-8")).hexdigest()
    return plan
