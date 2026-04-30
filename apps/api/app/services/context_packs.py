from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, List, Optional

from sqlmodel import Session, select

from app.models import Asset, Boundary, ContextPack, ContextPackItem, GoldVoiceExample, Memory, MemorySource, MetadataProfile, Segment, Task
from app.schemas import ContextPackBuildRequest
from app.services.photo_constants import (
    PHOTO_MEMORY_PROFILE_TYPE,
    PHOTO_SENSITIVE_PRIVACY_LEVELS,
    PHOTO_STATUS_ADAM_REVIEWED,
    PHOTO_STATUS_MACHINE_DRAFT,
    PHOTO_TRUTH_SYSTEM,
)


def _human_id(prefix: str, count: int) -> str:
    return f"{prefix}_{count:06d}"


def _stable_hash(payload: Dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str, separators=(",", ":")).encode("utf-8")).hexdigest()


def _count(session: Session, model: Any) -> int:
    return len(session.exec(select(model)).all()) + 1


def _boundary_for(session: Session, item_type: str, item_id: str) -> Optional[Boundary]:
    boundary = session.exec(
        select(Boundary).where(Boundary.target_type == item_type).where(Boundary.target_id == item_id)
    ).first()
    if boundary:
        return boundary
    if item_type == "segment":
        segment = session.get(Segment, item_id)
        if segment:
            return session.exec(
                select(Boundary).where(Boundary.target_type == "asset").where(Boundary.target_id == segment.asset_id)
            ).first()
    return None


CONTEXT_SAFE_TRUTH_STATUSES = {
    "archival_source",
    "spoken_source",
    "adam_memory",
    "adam_inference",
    "adam_expert_reconstruction",
    "interpretive_synthesis",
}


def _comma_join(values: List[Any]) -> str:
    return ", ".join(str(value).strip() for value in values if str(value).strip())


def _append_line(lines: List[str], label: str, value: Any) -> None:
    if isinstance(value, list):
        text = _comma_join(value)
    else:
        text = str(value or "").strip()
    if text:
        lines.append(f"{label}: {text}")


def _reviewed_photo_profile(session: Session, asset_id: str) -> Optional[MetadataProfile]:
    return session.exec(
        select(MetadataProfile)
        .where(MetadataProfile.target_type == "asset")
        .where(MetadataProfile.target_id == asset_id)
        .where(MetadataProfile.profile_type == PHOTO_MEMORY_PROFILE_TYPE)
        .where(MetadataProfile.metadata_status == PHOTO_STATUS_ADAM_REVIEWED)
        .order_by(MetadataProfile.updated_at.desc())
    ).first()


def _linked_reviewed_memories(session: Session, asset_id: str) -> List[Memory]:
    sources = session.exec(
        select(MemorySource)
        .where(MemorySource.source_type == "asset")
        .where(MemorySource.source_id == asset_id)
        .order_by(MemorySource.confidence.desc())
    ).all()
    memories: List[Memory] = []
    seen: set[str] = set()
    for source in sources:
        if source.memory_id in seen:
            continue
        memory = session.get(Memory, source.memory_id)
        if memory is None:
            continue
        if memory.truth_status not in CONTEXT_SAFE_TRUTH_STATUSES:
            continue
        if memory.maturity_level != "L3_reviewed":
            continue
        memories.append(memory)
        seen.add(memory.id)
    return memories


def _review_task_for_photo_memory_draft(session: Session, profile_id: str) -> Optional[Task]:
    return session.exec(
        select(Task)
        .where(Task.task_type == "vision_draft_review")
        .where(Task.target_type == "metadata_profile")
        .where(Task.target_id == profile_id)
        .where(Task.status != "canceled")
        .order_by(Task.created_at.asc())
    ).first()


def _photo_context_readiness_status(
    *,
    ready_count: int,
    blocked_count: int,
    filename_only_count: int,
    system_inference_leak_count: int,
    machine_draft_count: int,
    reviewed_profile_count: int,
) -> str:
    if system_inference_leak_count:
        return "blocked_system_inference_leak"
    if ready_count > 0 and machine_draft_count > 0:
        return "partially_ready_needs_adam_review"
    if machine_draft_count > 0:
        return "needs_adam_review"
    if blocked_count or filename_only_count:
        return "needs_boundary_or_context_fix"
    if ready_count > 0:
        return "ready"
    if reviewed_profile_count > 0:
        return "needs_boundary_or_context_fix"
    return "needs_photo_context_review"


def _photo_memory_draft_review_actions(
    *,
    session: Session,
    profiles: List[MetadataProfile],
    limit: int,
) -> List[Dict[str, Any]]:
    actions: List[Dict[str, Any]] = []
    for profile in profiles[:limit]:
        asset = session.get(Asset, profile.target_id) if profile.target_type == "asset" else None
        task = _review_task_for_photo_memory_draft(session, profile.id)
        action_type = "open_photo_memory_review_task" if task else "create_photo_memory_review_task"
        actions.append(
            {
                "action_type": action_type,
                "reason": "promote_machine_draft_with_adam_review",
                "review_status": "held_for_adam_review",
                "metadata_profile_id": profile.id,
                "metadata_status": profile.metadata_status,
                "truth_status_before_review": profile.truth_status,
                "source_photo_id": asset.id if asset else profile.target_id,
                "source_photo_human_id": asset.human_id if asset else None,
                "source_photo_title": (asset.title or asset.original_filename or asset.human_id) if asset else None,
                "review_task_id": task.id if task else None,
                "review_task_human_id": task.human_id if task else None,
                "review_queue": task.queue if task else "vision_drafts_needing_review",
                "suggested_next_action": (
                    "Open this photo memory review task and add Adam-authored context, boundary, "
                    "and downstream readiness before context-pack or vector use."
                    if task
                    else "Create a photo memory review task before this machine draft can move downstream."
                ),
            }
        )
    return actions


def _photo_asset_fact(session: Session, asset: Asset) -> Optional[str]:
    profile = _reviewed_photo_profile(session, asset.id)
    memories = _linked_reviewed_memories(session, asset.id)
    if profile is None and not memories:
        return asset.title or asset.original_filename or asset.human_id

    lines = ["photo_context:"]
    _append_line(lines, "  source_photo", asset.title or asset.original_filename or asset.human_id)
    _append_line(lines, "  source_photo_id", asset.id)
    if profile is not None and profile.truth_status in CONTEXT_SAFE_TRUTH_STATUSES:
        _append_line(lines, "  profile_title", profile.title)
        _append_line(lines, "  visual_description", profile.summary)
        _append_line(lines, "  adam_context", profile.adam_context_note)
        _append_line(lines, "  truth_status", profile.truth_status)
        _append_line(lines, "  metadata_status", profile.metadata_status)
        _append_line(lines, "  reviewed_by", profile.reviewed_by)
        _append_line(lines, "  date", profile.date_label)
        _append_line(lines, "  date_confidence", profile.date_confidence)
        _append_line(lines, "  people", profile.people)
        _append_line(lines, "  places", profile.places)
        _append_line(lines, "  themes", profile.themes)
        _append_line(lines, "  concrete_objects", profile.concrete_objects)
        _append_line(lines, "  open_questions", profile.open_questions)
    if memories:
        lines.append("  linked_memories:")
        for memory in memories[:5]:
            lines.append(f"    - title: {memory.title}")
            _append_line(lines, "      summary", memory.summary)
            _append_line(lines, "      truth_status", memory.truth_status)
            _append_line(lines, "      themes", memory.themes)
            _append_line(lines, "      open_questions", memory.open_questions)
    return "\n".join(lines)[:1200]


def compile_photo_context_pack_readiness_audit(
    *,
    session: Session,
    scope: str = "family_private",
    limit: int = 50,
) -> Dict[str, Any]:
    safe_limit = max(1, min(limit, 500))
    reviewed_profiles = session.exec(
        select(MetadataProfile)
        .where(MetadataProfile.target_type == "asset")
        .where(MetadataProfile.profile_type == PHOTO_MEMORY_PROFILE_TYPE)
        .where(MetadataProfile.metadata_status == PHOTO_STATUS_ADAM_REVIEWED)
        .order_by(MetadataProfile.updated_at.desc())
    ).all()
    machine_draft_profiles = session.exec(
        select(MetadataProfile)
        .where(MetadataProfile.target_type == "asset")
        .where(MetadataProfile.profile_type == PHOTO_MEMORY_PROFILE_TYPE)
        .where(MetadataProfile.metadata_status == PHOTO_STATUS_MACHINE_DRAFT)
        .order_by(MetadataProfile.updated_at.desc())
    ).all()
    candidate_asset_ids: List[str] = []
    for profile in reviewed_profiles:
        if profile.target_id not in candidate_asset_ids:
            candidate_asset_ids.append(profile.target_id)

    items: List[Dict[str, Any]] = []
    ready_count = 0
    blocked_count = 0
    filename_only_count = 0
    system_inference_leak_count = 0
    linked_memory_count = 0

    for asset_id in candidate_asset_ids[:safe_limit]:
        asset = session.get(Asset, asset_id)
        if asset is None or asset.asset_type != "photo":
            continue
        boundary = _boundary_for(session, "asset", asset.id)
        boundary_check = _boundary_check(boundary, "asset", asset.id)
        profile = _reviewed_photo_profile(session, asset.id)
        memories = _linked_reviewed_memories(session, asset.id)
        fact = _photo_asset_fact(session, asset) or ""
        fallback_title = asset.title or asset.original_filename or asset.human_id
        system_drafts = session.exec(
            select(MetadataProfile)
            .where(MetadataProfile.target_type == "asset")
            .where(MetadataProfile.target_id == asset.id)
            .where(MetadataProfile.profile_type == PHOTO_MEMORY_PROFILE_TYPE)
            .where(MetadataProfile.truth_status == PHOTO_TRUTH_SYSTEM)
        ).all()
        leaked_system_draft_summaries = [
            str(draft.summary)
            for draft in system_drafts
            if draft.summary and str(draft.summary) in fact
        ]
        includes_reviewed_context = bool(profile and profile.summary and str(profile.summary) in fact)
        includes_linked_memory = bool(memories and any(memory.summary and memory.summary in fact for memory in memories))
        is_filename_only = fact.strip() == str(fallback_title or "").strip()
        if boundary_check["included"] and includes_reviewed_context and not is_filename_only and not leaked_system_draft_summaries:
            ready_count += 1
        if not boundary_check["included"]:
            blocked_count += 1
        if is_filename_only:
            filename_only_count += 1
        if leaked_system_draft_summaries:
            system_inference_leak_count += 1
        linked_memory_count += len(memories)
        items.append(
            {
                "asset_id": asset.id,
                "asset_human_id": asset.human_id,
                "title": fallback_title,
                "boundary_included": boundary_check["included"],
                "boundary_reason": boundary_check["reason"],
                "privacy_level": boundary.privacy_level if boundary else None,
                "includes_reviewed_photo_context": includes_reviewed_context,
                "includes_linked_reviewed_memory": includes_linked_memory,
                "linked_reviewed_memory_count": len(memories),
                "system_inference_draft_excluded": not leaked_system_draft_summaries,
                "filename_only_fallback": is_filename_only,
                "fact_char_count": len(fact),
                "fact_preview": fact[:500],
            }
        )

    next_review_actions = _photo_memory_draft_review_actions(
        session=session,
        profiles=machine_draft_profiles,
        limit=min(safe_limit, 25),
    )
    readiness_status = _photo_context_readiness_status(
        ready_count=ready_count,
        blocked_count=blocked_count,
        filename_only_count=filename_only_count,
        system_inference_leak_count=system_inference_leak_count,
        machine_draft_count=len(machine_draft_profiles),
        reviewed_profile_count=len(reviewed_profiles),
    )
    payload = {
        "audit_type": "photo_context_pack_readiness_audit",
        "scope": scope,
        "readiness_status": readiness_status,
        "review_policy": "read_only_context_pack_fact_projection",
        "does_not_mutate_state": True,
        "requires_boundary_clearance": True,
        "uses_reviewed_photo_context": True,
        "uses_linked_reviewed_memories": True,
        "excludes_system_inference_drafts": True,
        "completion_signal": "reviewed_photo_context_assets_have_non_filename_context_or_are_boundary_blocked",
        "reviewed_photo_profile_count": len(reviewed_profiles),
        "machine_draft_profile_count": len(machine_draft_profiles),
        "held_for_adam_review_count": len(machine_draft_profiles),
        "candidate_photo_asset_count": len(candidate_asset_ids),
        "reported_item_count": len(items),
        "ready_context_pack_asset_count": ready_count,
        "blocked_context_pack_asset_count": blocked_count,
        "filename_only_fallback_count": filename_only_count,
        "linked_reviewed_memory_count": linked_memory_count,
        "system_inference_leak_count": system_inference_leak_count,
        "next_review_action_count": len(next_review_actions),
        "next_review_actions": next_review_actions,
        "items": items,
    }
    payload["content_sha256"] = _stable_hash({key: value for key, value in payload.items() if key != "content_sha256"})
    return payload


def _item_fact(session: Session, item_type: str, item_id: str) -> Optional[str]:
    if item_type == "segment":
        segment = session.get(Segment, item_id)
        if segment and segment.text_content:
            return segment.text_content[:1200]
        if segment and segment.title:
            return segment.title
    if item_type == "memory":
        memory = session.get(Memory, item_id)
        if memory:
            return f"{memory.title}: {memory.summary}"
    if item_type == "asset":
        asset = session.get(Asset, item_id)
        if asset:
            if asset.asset_type == "photo":
                return _photo_asset_fact(session, asset)
            return asset.title or asset.original_filename or asset.human_id
    if item_type == "gold_voice_example":
        gold = session.get(GoldVoiceExample, item_id)
        if gold:
            return gold.adam_gold_edit[:1200]
    return None


def _boundary_check(boundary: Optional[Boundary], item_type: str, item_id: str) -> Dict[str, Any]:
    if boundary is None:
        return {
            "included": False,
            "warning": None,
            "reason": "boundary_missing",
            "snapshot": None,
        }
    snapshot = boundary.model_dump(mode="json")
    if boundary.privacy_level in PHOTO_SENSITIVE_PRIVACY_LEVELS:
        return {
            "included": False,
            "warning": None,
            "reason": f"privacy_level={boundary.privacy_level}",
            "snapshot": snapshot,
        }
    if boundary.privacy_level == "unreviewed":
        return {
            "included": False,
            "warning": None,
            "reason": "boundary is unreviewed",
            "snapshot": snapshot,
        }
    if boundary.redaction_required:
        return {
            "included": False,
            "warning": None,
            "reason": "redaction required before context-pack use",
            "snapshot": snapshot,
        }
    if not (boundary.retrievable_in_chat or boundary.usable_for_voice_context or boundary.usable_for_eval):
        return {
            "included": False,
            "warning": None,
            "reason": "boundary does not allow retrieval, voice context, or eval use",
            "snapshot": snapshot,
        }
    return {"included": True, "warning": None, "reason": None, "snapshot": snapshot}


def build_context_pack(session: Session, payload: ContextPackBuildRequest) -> Dict[str, Any]:
    checks: List[Dict[str, Any]] = []
    included_items: List[Dict[str, Any]] = []
    excluded_items: List[Dict[str, Any]] = []
    warnings: List[str] = []
    allowed_facts = list(payload.allowed_facts)

    for index, item in enumerate(payload.items):
        boundary = _boundary_for(session, item.item_type, item.item_id)
        check = _boundary_check(boundary, item.item_type, item.item_id)
        check.update(
            {
                "item_type": item.item_type,
                "item_id": item.item_id,
                "role": item.role,
                "rank": item.rank or index,
            }
        )
        checks.append(check)
        if check["warning"]:
            warnings.append(str(check["warning"]))
        fact = _item_fact(session, item.item_type, item.item_id)
        if check["included"]:
            included_items.append(check)
            if fact:
                allowed_facts.append(fact)
        else:
            excluded_items.append(check)

    context_pack = ContextPack(
        human_id=_human_id("CTX_BUILDER", _count(session, ContextPack)),
        user_intent=payload.user_intent,
        requested_voice_mode=payload.requested_voice_mode,
        truth_mode=payload.truth_mode,
        allowed_facts=allowed_facts,
        boundaries_snapshot={
            "boundary_status": "blocked" if excluded_items else "warnings" if warnings else "passed",
            "included_items": included_items,
            "excluded_items": excluded_items,
            "warnings": warnings,
            "blocked_facts": payload.blocked_facts,
            "checks": checks,
        },
        style_guidance={
            **payload.style_guidance,
            "blocked_facts": payload.blocked_facts,
            "builder_version": "v1",
        },
    )
    session.add(context_pack)
    session.flush()

    for index, item in enumerate(payload.items):
        check = checks[index]
        session.add(
            ContextPackItem(
                context_pack_id=context_pack.id,
                item_type=item.item_type,
                item_id=item.item_id,
                role=item.role,
                rank=item.rank or index,
                included=bool(check["included"]),
                exclusion_reason=check["reason"],
            )
        )
    session.flush()

    return {
        "context_pack": context_pack,
        "included_count": len(included_items),
        "excluded_count": len(excluded_items),
        "warnings": warnings,
    }
