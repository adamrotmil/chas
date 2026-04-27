from __future__ import annotations

from typing import Any, Dict, List, Optional

from sqlmodel import Session, select

from app.models import Asset, Boundary, ContextPack, ContextPackItem, GoldVoiceExample, Memory, Segment
from app.schemas import ContextPackBuildRequest


def _human_id(prefix: str, count: int) -> str:
    return f"{prefix}_{count:06d}"


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
            return asset.title or asset.original_filename or asset.human_id
    if item_type == "gold_voice_example":
        gold = session.get(GoldVoiceExample, item_id)
        if gold:
            return gold.adam_gold_edit[:1200]
    return None


def _boundary_check(boundary: Optional[Boundary], item_type: str, item_id: str) -> Dict[str, Any]:
    if boundary is None:
        return {
            "included": True,
            "warning": f"{item_type}/{item_id} has no explicit boundary yet.",
            "reason": None,
            "snapshot": None,
        }
    snapshot = boundary.model_dump(mode="json")
    if boundary.privacy_level in {"sealed", "private_sensitive"}:
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
