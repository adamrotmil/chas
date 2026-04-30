from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from sqlmodel import Session, select

from app.models import Asset, Boundary, EmbeddingRecord, Memory, MetadataProfile, Task
from app.services.photo_constants import (
    PHOTO_MEMORY_PROFILE_TYPE,
    PHOTO_SENSITIVE_PRIVACY_LEVELS,
    PHOTO_STATUS_MACHINE_DRAFT,
)


STOPWORDS = {
    "a",
    "an",
    "and",
    "as",
    "at",
    "do",
    "there",
    "together",
    "in",
    "of",
    "the",
    "that",
    "time",
    "up",
    "we",
}

SEMANTIC_ALIASES = {
    "aircraft": ["airplane", "flight", "flying", "plane"],
    "airplane": ["aircraft", "flight", "flying", "plane"],
    "flew": ["airplane", "flight", "flying", "plane"],
    "fly": ["airplane", "flight", "flying", "plane"],
    "flying": ["airplane", "flight", "flew", "plane"],
    "plane": ["aircraft", "airplane", "flight", "flying"],
    "boat": ["dock", "ferry", "harbor", "water"],
    "harbor": ["dock", "ferry", "pier", "water"],
    "food": ["bread", "breakfast", "brie", "coffee"],
    "meal": ["bread", "breakfast", "brie", "coffee", "food"],
    "ceremony": ["honor", "honors", "microphone", "testimony"],
    "honor": ["ceremony", "honors", "testimony"],
    "honors": ["ceremony", "honor", "testimony"],
    "flute": ["music", "shakuhachi"],
}
REVIEWED_PHOTO_MEMORY_TRUTH_STATUSES = {
    "adam_memory",
    "adam_inference",
    "adam_expert_reconstruction",
    "archival_source",
    "spoken_source",
    "interpretive_synthesis",
}
PHOTO_MEMORY_PROMOTION_REQUIREMENTS = {
    "required_decisions": [
        "vision_accuracy",
        "accepted_visual_description",
        "question_answers",
        "adam_context_note",
        "privacy_level",
        "ready_for_downstream",
        "ocr_review_status",
    ],
    "minimum_for_reviewed_vector_handoff": [
        "Adam-authored context in adam_context_note or question_answers",
        "privacy_level is family_private or public_candidate",
        "ready_for_downstream is true",
        "boundary reviewed_by is adam",
    ],
    "reviewed_record_requirements": {
        "metadata_source": "photo_memory_review",
        "truth_status_any_of": sorted(REVIEWED_PHOTO_MEMORY_TRUTH_STATUSES),
        "boundary_reviewed_by": "adam",
    },
    "promotion_effect": "Creates or updates a canonical reviewed photo memory embedding row eligible for the default vector handoff.",
}


def _tokens(text: str) -> List[str]:
    return [token for token in re.findall(r"[a-z0-9]+", text.lower()) if token not in STOPWORDS and len(token) > 1]


def _query_term_weights(query_tokens: List[str]) -> Dict[str, int]:
    weights: Dict[str, int] = {}
    for token in query_tokens:
        weights[token] = max(weights.get(token, 0), 10)
        for alias in SEMANTIC_ALIASES.get(token, []):
            weights[alias] = max(weights.get(alias, 0), 6)
    return weights


def _boundary_allows(snapshot: Dict[str, Any], *, scope: str) -> bool:
    if not snapshot or snapshot.get("boundary_status") == "missing":
        return False
    if snapshot.get("privacy_level") in PHOTO_SENSITIVE_PRIVACY_LEVELS:
        return False
    if not snapshot.get("searchable") and not snapshot.get("retrievable_in_chat"):
        return False
    if scope == "public":
        return bool(snapshot.get("usable_for_gallery_public")) or snapshot.get("privacy_level") in {"public_candidate", "public_safe"}
    if scope == "family_private":
        return snapshot.get("privacy_level") in {"family_private", "public_candidate", "public_safe"} or bool(
            snapshot.get("retrievable_in_chat")
        )
    return bool(snapshot.get("retrievable_in_chat") or snapshot.get("searchable"))


def _asset_boundary_snapshot(session: Session, asset_id: Optional[str]) -> Dict[str, Any]:
    if not asset_id:
        return {}
    boundary = session.exec(
        select(Boundary).where(Boundary.target_type == "asset").where(Boundary.target_id == asset_id)
    ).first()
    return boundary.model_dump(mode="json") if boundary else {}


def _retrieval_origin_metadata(metadata: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    origin = metadata.get("retrieval_gap_origin")
    if not isinstance(origin, dict):
        return None
    query = origin.get("query")
    if not isinstance(query, str) or not query.strip():
        return None
    return {
        "query": query.strip(),
        "candidate_match_quality": origin.get("candidate_match_quality") or "unknown",
        "selection_reason": origin.get("selection_reason") or "unknown",
        "truth_status": origin.get("truth_status") or "no_claim",
        "not_memory_claim": origin.get("not_memory_claim") is True,
    }


def _source_photo_id(session: Session, record: EmbeddingRecord) -> Optional[str]:
    metadata = record.metadata_json or {}
    asset_id = metadata.get("asset_id")
    if isinstance(asset_id, str) and asset_id:
        return asset_id
    profile_target_id = metadata.get("profile_target_id")
    if metadata.get("profile_target_type") == "asset" and isinstance(profile_target_id, str):
        asset = session.get(Asset, profile_target_id)
        if asset and asset.asset_type in {"photo", "scan"}:
            return asset.id
    if record.target_type == "metadata_profile":
        profile = session.get(MetadataProfile, record.target_id)
        if profile and profile.target_type == "asset":
            asset = session.get(Asset, profile.target_id)
            if asset and asset.asset_type in {"photo", "scan"}:
                return asset.id
    return None


def _title_for_record(session: Session, record: EmbeddingRecord, source_photo_id: Optional[str]) -> str:
    if record.target_type == "memory":
        memory = session.get(Memory, record.target_id)
        if memory:
            return memory.title
    if record.target_type == "metadata_profile":
        profile = session.get(MetadataProfile, record.target_id)
        if profile and profile.title:
            return profile.title
    if source_photo_id:
        asset = session.get(Asset, source_photo_id)
        if asset:
            return asset.title or asset.original_filename or asset.human_id
    return record.target_id


def _source_photo_title(session: Session, source_photo_id: Optional[str]) -> Optional[str]:
    if not source_photo_id:
        return None
    asset = session.get(Asset, source_photo_id)
    if not asset:
        return None
    return _photo_title(asset)


def _photo_review_task_reference(session: Session, source_photo_id: Optional[str]) -> Dict[str, Optional[str]]:
    if not source_photo_id:
        return {"review_task_id": None, "review_task_human_id": None}
    tasks = session.exec(
        select(Task)
        .where(Task.task_type == "vision_draft_review")
        .where(Task.status == "ready")
        .order_by(Task.created_at.asc())
    ).all()
    for task in tasks:
        if (task.input_payload or {}).get("asset_id") == source_photo_id:
            return {"review_task_id": task.id, "review_task_human_id": task.human_id}
    return {"review_task_id": None, "review_task_human_id": None}


def _photo_context_task_reference(session: Session, source_photo_id: Optional[str]) -> Dict[str, Optional[str]]:
    if not source_photo_id:
        return {"review_task_id": None, "review_task_human_id": None}
    tasks = session.exec(
        select(Task)
        .where(Task.task_type == "photo_context")
        .where(Task.status == "ready")
        .order_by(Task.created_at.asc())
    ).all()
    for task in tasks:
        payload = task.input_payload or {}
        if payload.get("asset_id") == source_photo_id or task.target_id == source_photo_id:
            return {"review_task_id": task.id, "review_task_human_id": task.human_id}
    return {"review_task_id": None, "review_task_human_id": None}


def _photo_title(asset: Asset) -> str:
    return asset.title or asset.original_filename or asset.human_id


def _photo_group_key(asset: Asset) -> str:
    stem = Path(_photo_title(asset)).stem.lower()
    stem = re.sub(r"\s+-\s+copy(?:\s+-\s+copy)*", "", stem)
    stem = re.sub(r"\s*\(\d+\)\s*", " ", stem)
    stem = re.sub(r"\bcopy\b", "", stem)
    stem = re.sub(r"[^a-z0-9]+", " ", stem)
    return re.sub(r"\s+", " ", stem).strip() or asset.id


def _photo_candidate_media_kind(asset: Asset) -> str:
    title = _photo_title(asset).lower()
    mime_type = (asset.mime_type or "").lower()
    if title.endswith((".jpg", ".jpeg", ".png", ".heic", ".tif", ".tiff")):
        return "photograph_like"
    if mime_type in {"image/jpeg", "image/png", "image/heic", "image/heif", "image/tiff"}:
        return "photograph_like"
    if title.endswith((".psd", ".ai", ".eps")) or "photoshop" in mime_type or "postscript" in mime_type:
        return "design_or_document_image"
    return "image_asset_unknown_kind"


def _group_media_kind(assets: List[Asset]) -> str:
    kinds = {_photo_candidate_media_kind(asset) for asset in assets}
    if "photograph_like" in kinds:
        return "photograph_like"
    if "image_asset_unknown_kind" in kinds:
        return "image_asset_unknown_kind"
    return "design_or_document_image"


def _is_reviewed_photo_profile(profile: MetadataProfile) -> bool:
    return (
        profile.metadata_status == "adam_reviewed"
        or profile.reviewed_by == "adam"
        or profile.truth_status in REVIEWED_PHOTO_MEMORY_TRUTH_STATUSES
    )


def _profile_evidence_text(profile: Optional[MetadataProfile]) -> str:
    if profile is None:
        return ""
    return " ".join(
        part
        for part in [
            profile.title or "",
            profile.summary or "",
            profile.adam_context_note or "",
            profile.retrieval_notes or "",
            " ".join(profile.people),
            " ".join(profile.places),
            " ".join(profile.themes),
            " ".join(profile.concrete_objects),
            " ".join(profile.open_questions),
        ]
        if part
    )


def _reviewable_candidate_evidence(
    *,
    session: Session,
    assets: List[Asset],
    profile: Optional[MetadataProfile],
) -> Dict[str, Any]:
    canonical = sorted(assets, key=lambda asset: (len(_photo_title(asset)), _photo_title(asset)))[0]
    if profile is None:
        task_reference = _photo_context_task_reference(session, canonical.id)
        return {
            "not_memory_claim": True,
            "evidence_source": "title_filename_only",
            "truth_status": "no_claim",
            "profile_status": "missing",
            "source_fields": ["asset.title", "asset.original_filename", "asset.human_id"],
            "source_titles": [_photo_title(asset) for asset in assets],
            "source_photo_ids": [asset.id for asset in assets],
            "candidate_media_kind": _group_media_kind(assets),
            "candidate_queue": "photo_assets_needing_context",
            "review_task_id": task_reference.get("review_task_id"),
            "review_task_human_id": task_reference.get("review_task_human_id"),
            "suggested_next_action": "Create or open a photo context task and add Adam-authored context before treating this as memory.",
        }

    task_reference = _photo_review_task_reference(session, canonical.id)
    return {
        "not_memory_claim": True,
        "evidence_source": "machine_photo_memory_draft",
        "truth_status": profile.truth_status or "system_inference",
        "profile_id": profile.id,
        "profile_status": profile.metadata_status,
        "profile_title": profile.title,
        "profile_summary_preview": (profile.summary or "")[:280],
        "profile_reviewed_by": profile.reviewed_by or "unknown",
        "source_fields": [
            "asset.title",
            "asset.original_filename",
            "metadata_profile.title",
            "metadata_profile.summary",
            "metadata_profile.adam_context_note",
            "metadata_profile.retrieval_notes",
            "metadata_profile.themes",
            "metadata_profile.concrete_objects",
        ],
        "source_titles": [_photo_title(asset) for asset in assets],
        "source_photo_ids": [asset.id for asset in assets],
        "candidate_media_kind": _group_media_kind(assets),
        "candidate_queue": "vision_drafts_needing_review",
        "review_task_id": task_reference.get("review_task_id"),
        "review_task_human_id": task_reference.get("review_task_human_id"),
        "requires_adam_review": True,
        "does_not_certify_final_memory": True,
        "suggested_next_action": "Open the existing photo memory draft review task and promote Adam-authored context before treating this as memory.",
    }


def _retrieval_gap_primary_action(
    *,
    group_key: str,
    canonical_asset_id: str,
    candidate_evidence: Dict[str, Any],
    source_query: str,
    candidate_match_quality: str,
    selection_reason: str,
) -> Dict[str, Any]:
    review_task_id = candidate_evidence.get("review_task_id")
    review_task_human_id = candidate_evidence.get("review_task_human_id")
    candidate_queue = str(candidate_evidence.get("candidate_queue") or "")
    if isinstance(review_task_id, str) and review_task_id:
        if candidate_queue == "vision_drafts_needing_review":
            action_type = "open_existing_draft_review_task"
            label = "Open draft review"
        else:
            action_type = "open_existing_photo_context_task"
            label = "Open context task"
        return {
            "action_type": action_type,
            "label": label,
            "task_id": review_task_id,
            "task_human_id": review_task_human_id,
            "queue": candidate_queue,
        }
    return {
        "action_type": "create_photo_context_task",
        "label": "Create context task",
        "queue": "photo_assets_needing_context",
        "request": {
            "endpoint": "/api/assets/photo-review-inventory/context-task",
            "method": "POST",
            "body": {
                "group_key": group_key,
                "asset_id": canonical_asset_id,
                "use_canonical": True,
                "source_query": source_query,
                "candidate_match_quality": candidate_match_quality,
                "candidate_selection_reason": selection_reason,
            },
        },
    }


def _preview_urls(asset_id: str) -> Dict[str, str]:
    return {
        "preview_url": f"/api/assets/{asset_id}/preview?variant=display",
        "thumbnail_url": f"/api/assets/{asset_id}/preview?variant=thumbnail",
    }


def _retrieval_gap(
    *,
    session: Session,
    query: str,
    scope: str,
    expanded_query_terms: List[str],
) -> Dict[str, Any]:
    photos = session.exec(select(Asset).where(Asset.asset_type == "photo").order_by(Asset.created_at.asc())).all()
    photo_ids = [photo.id for photo in photos]
    profiles = (
        session.exec(
            select(MetadataProfile)
            .where(MetadataProfile.target_type == "asset")
            .where(MetadataProfile.target_id.in_(photo_ids))
            .where(MetadataProfile.profile_type == PHOTO_MEMORY_PROFILE_TYPE)
        ).all()
        if photo_ids
        else []
    )
    profiles_by_asset_id: Dict[str, List[MetadataProfile]] = {}
    for profile in profiles:
        profiles_by_asset_id.setdefault(profile.target_id, []).append(profile)
    preview_ready = [photo for photo in photos if photo.processing_status == "image_preview_ready"]
    preview_groups: Dict[str, List[Asset]] = {}
    for photo in preview_ready:
        preview_groups.setdefault(_photo_group_key(photo), []).append(photo)
    candidate_groups: Dict[str, Dict[str, Any]] = {}
    groups_needing_context = 0
    assets_needing_context = 0
    groups_needing_draft_review = 0
    for key, assets in preview_groups.items():
        group_profiles = [
            profile
            for asset in assets
            for profile in profiles_by_asset_id.get(asset.id, [])
            if profile.profile_type == PHOTO_MEMORY_PROFILE_TYPE
        ]
        if any(_is_reviewed_photo_profile(profile) for profile in group_profiles):
            continue
        candidate_profile = next((profile for profile in group_profiles if profile), None)
        if candidate_profile:
            groups_needing_draft_review += 1
        else:
            groups_needing_context += 1
            assets_needing_context += len(assets)
        candidate_groups[key] = {
            "assets": assets,
            "profile": candidate_profile,
            "candidate_status": PHOTO_STATUS_MACHINE_DRAFT if candidate_profile else "needs_photo_context",
        }
    query_terms = set(expanded_query_terms)

    def evidence_text(key: str, assets: List[Asset], profile: Optional[MetadataProfile]) -> str:
        return " ".join([key, *[_photo_title(asset) for asset in assets], _profile_evidence_text(profile)]).lower()

    def matched_terms_for(key: str, assets: List[Asset], profile: Optional[MetadataProfile]) -> List[str]:
        return sorted(query_terms.intersection(set(_tokens(evidence_text(key, assets, profile)))))

    weak_evidence_candidate_count = sum(
        1
        for key, data in candidate_groups.items()
        if matched_terms_for(key, data["assets"], data.get("profile"))
    )
    backlog_only_candidate_count = len(candidate_groups) - weak_evidence_candidate_count

    def group_rank(item: tuple[str, Dict[str, Any]]) -> tuple[int, int, int, str]:
        key, data = item
        assets = data["assets"]
        title_tokens = set(_tokens(evidence_text(key, assets, data.get("profile"))))
        overlap = len(query_terms.intersection(title_tokens))
        if overlap:
            status_rank = 0 if data["candidate_status"] == PHOTO_STATUS_MACHINE_DRAFT else 1
        else:
            status_rank = 0 if data["candidate_status"] == "needs_photo_context" else 1
        media_rank = 0 if _group_media_kind(assets) == "photograph_like" else 1
        return (-overlap, media_rank, status_rank, key)

    sample_groups = []
    for key, data in sorted(candidate_groups.items(), key=group_rank)[:5]:
        assets = data["assets"]
        profile = data.get("profile")
        canonical = sorted(assets, key=lambda asset: (len(_photo_title(asset)), _photo_title(asset)))[0]
        candidate_evidence = _reviewable_candidate_evidence(session=session, assets=assets, profile=profile)
        matched_terms = matched_terms_for(key, assets, profile)
        candidate_match_quality = "weak_evidence_match" if matched_terms else "backlog_only"
        selection_reason = "reviewable_evidence_overlap" if matched_terms else "backlog_sample_no_semantic_match"
        sample_groups.append(
            {
                "group_key": key,
                "display_title": _photo_title(canonical),
                "canonical_asset_id": canonical.id,
                "preview_ready_count": len(assets),
                "candidate_status": data["candidate_status"],
                "candidate_queue": candidate_evidence["candidate_queue"],
                "candidate_media_kind": candidate_evidence["candidate_media_kind"],
                "matched_query_terms": matched_terms,
                "candidate_match_quality": candidate_match_quality,
                "selection_reason": selection_reason,
                "candidate_evidence": candidate_evidence,
                "primary_action": _retrieval_gap_primary_action(
                    group_key=key,
                    canonical_asset_id=canonical.id,
                    candidate_evidence=candidate_evidence,
                    source_query=query,
                    candidate_match_quality=candidate_match_quality,
                    selection_reason=selection_reason,
                ),
            }
        )

    return {
        "status": "no_boundary_cleared_memory_result",
        "query": query,
        "scope": scope,
        "truth_status": "no_claim",
        "message": "No boundary-cleared photo memory matched this query yet.",
        "suggested_next_action": "Review candidate photos and create Adam-authored photo context before treating this as memory.",
        "next_queue": "photo_assets_needing_context",
        "next_queues": ["photo_assets_needing_context", "vision_drafts_needing_review"],
        "workflow": "photo_context_review",
        "preview_ready_photo_count": len(preview_ready),
        "photo_assets_needing_context_count": assets_needing_context,
        "photo_groups_needing_context_count": groups_needing_context,
        "photo_groups_needing_draft_review_count": groups_needing_draft_review,
        "candidate_photo_group_count": len(candidate_groups),
        "weak_evidence_candidate_count": weak_evidence_candidate_count,
        "backlog_only_candidate_count": backlog_only_candidate_count,
        "candidate_group_selection_policy": "reviewable_evidence_overlap_then_backlog_sample",
        "sample_groups_are_not_memory_claims": True,
        "sample_context_groups": sample_groups,
    }


def _score(query_terms: Dict[str, int], text: str) -> tuple[int, List[str]]:
    text_tokens = set(_tokens(text))
    matched = sorted(set(query_terms).intersection(text_tokens))
    score = sum(query_terms[token] for token in matched)
    lowered = text.lower()
    for token in matched:
        if re.search(rf"\b{re.escape(token)}\b", lowered):
            score += 1
    return score, matched


def _photo_result_rank(item: Dict[str, Any]) -> tuple[int, int, str, str]:
    target_rank = 0 if item.get("target_type") == "memory" else 1
    return (
        target_rank,
        -int(item.get("score") or 0),
        str(item.get("title") or ""),
        str(item.get("embedding_record_id") or ""),
    )


def _retrieval_review_policy(record: EmbeddingRecord, boundary_snapshot: Dict[str, Any]) -> Dict[str, Any]:
    truth_status = record.truth_status or "unknown"
    reviewed_by = boundary_snapshot.get("reviewed_by")
    requires_review = truth_status in {"system_inference", "model_generated"} or reviewed_by != "adam"
    return {
        "requires_adam_review": requires_review,
        "truth_status": truth_status,
        "boundary_reviewed_by": reviewed_by or "unknown",
        "does_not_certify_final_memory": requires_review,
    }


def search_embedding_records(
    *,
    session: Session,
    query: str,
    scope: str = "family_private",
    limit: int = 10,
) -> Dict[str, Any]:
    query_tokens = _tokens(query)
    if not query_tokens:
        return {
            "query": query,
            "scope": scope,
            "retrieval_strategy": "boundary_filtered_lexical_semantic_expansion",
            "result_dedupe_policy": {
                "one_result_per_source_photo": True,
                "preferred_photo_target_order": ["memory", "metadata_profile"],
            },
            "results": [],
            "retrieval_gap": _retrieval_gap(session=session, query=query, scope=scope, expanded_query_terms=[]),
        }
    query_terms = _query_term_weights(query_tokens)

    records = session.exec(
        select(EmbeddingRecord)
        .where(EmbeddingRecord.status == "ready_for_embedding")
        .where(EmbeddingRecord.modality == "text")
        .order_by(EmbeddingRecord.created_at.asc())
    ).all()

    results: List[Dict[str, Any]] = []
    for record in records:
        source_photo_id = _source_photo_id(session, record)
        metadata = record.metadata_json or {}
        boundary_snapshot = record.boundary_snapshot or {}
        if source_photo_id and not _boundary_allows(boundary_snapshot, scope=scope):
            boundary_snapshot = _asset_boundary_snapshot(session, source_photo_id)
        if source_photo_id and not _boundary_allows(boundary_snapshot, scope=scope):
            continue

        score, matched = _score(query_terms, record.input_text)
        if score <= 0:
            continue
        results.append(
            {
                "embedding_record_id": record.id,
                "target_type": record.target_type,
                "target_id": record.target_id,
                "source_photo_id": source_photo_id,
                "title": _title_for_record(session, record, source_photo_id),
                "score": score,
                "matched_terms": matched,
                "input_preview": record.input_preview or record.input_text[:280],
                "truth_status": record.truth_status,
                "retrieval_gap_origin": _retrieval_origin_metadata(metadata),
                "boundary_snapshot": boundary_snapshot,
                "review_policy": _retrieval_review_policy(record, boundary_snapshot),
                "why_matched": f"Matched query terms: {', '.join(matched)}.",
            }
        )

    results_by_key: Dict[str, Dict[str, Any]] = {}
    for item in results:
        result_key = item["source_photo_id"] or f"{item['target_type']}:{item['target_id']}"
        current = results_by_key.get(result_key)
        if current is None:
            results_by_key[result_key] = item
            continue
        if item["source_photo_id"] and _photo_result_rank(item) < _photo_result_rank(current):
            results_by_key[result_key] = item
        elif not item["source_photo_id"] and (-int(item["score"]), item["title"], item["embedding_record_id"]) < (
            -int(current["score"]),
            current["title"],
            current["embedding_record_id"],
        ):
            results_by_key[result_key] = item
    deduped_results = list(results_by_key.values())
    deduped_results.sort(key=lambda item: (-int(item["score"]), item["title"], item["embedding_record_id"]))
    response = {
        "query": query,
        "scope": scope,
        "retrieval_strategy": "boundary_filtered_lexical_semantic_expansion",
        "result_dedupe_policy": {
            "one_result_per_source_photo": True,
            "preferred_photo_target_order": ["memory", "metadata_profile"],
        },
        "expanded_query_terms": sorted(query_terms),
        "results": deduped_results[: max(1, min(limit, 50))],
    }
    if not response["results"]:
        response["retrieval_gap"] = _retrieval_gap(
            session=session,
            query=query,
            scope=scope,
            expanded_query_terms=sorted(query_terms),
        )
    return response


def retrieval_gap_review_slice(
    *,
    session: Session,
    query: str,
    scope: str = "family_private",
    limit: int = 5,
) -> Dict[str, Any]:
    safe_limit = max(1, min(limit, 10))
    search = search_embedding_records(session=session, query=query, scope=scope, limit=1)
    results = search.get("results") if isinstance(search.get("results"), list) else []
    if results:
        stable_payload = {
            "query": query,
            "scope": scope,
            "status": "resolved_boundary_filtered_memory_result",
            "top_result": results[0],
        }
        return {
            "slice_type": "retrieval_gap_review_slice",
            "review_policy": "resolved_result_no_gap_work",
            "query": query,
            "scope": scope,
            "gap_open": False,
            "truth_status": results[0].get("truth_status"),
            "does_not_create_memory_claim": True,
            "requires_adam_context": False,
            "workflow": "photo_memory_retrieval",
            "status": "resolved_boundary_filtered_memory_result",
            "message": "This query already returns a boundary-filtered photo memory result.",
            "candidate_group_selection_policy": None,
            "candidate_count": 0,
            "weak_evidence_candidate_count": 0,
            "backlog_only_candidate_count": 0,
            "reported_candidate_count": 0,
            "completion_signal": "query_already_returns_boundary_filtered_memory",
            "safety_boundaries": [
                "Resolved retrieval results still carry their own truth status and review policy.",
                "This read-only slice does not create or promote memory records.",
            ],
            "recommended_action": None,
            "resolved_result": results[0],
            "items": [],
            "content_sha256": hashlib.sha256(
                json.dumps(stable_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
            ).hexdigest(),
        }

    gap = search.get("retrieval_gap") if isinstance(search.get("retrieval_gap"), dict) else {}
    groups = gap.get("sample_context_groups") if isinstance(gap.get("sample_context_groups"), list) else []
    items: List[Dict[str, Any]] = []
    for index, group in enumerate(groups[:safe_limit], start=1):
        if not isinstance(group, dict):
            continue
        source_photo_id = str(group.get("canonical_asset_id") or "")
        candidate_evidence = group.get("candidate_evidence") if isinstance(group.get("candidate_evidence"), dict) else {}
        action = group.get("primary_action") if isinstance(group.get("primary_action"), dict) else {}
        items.append(
            {
                "sequence_number": index,
                "item_key": f"{query}:{group.get('group_key')}",
                "query": query,
                "group_key": group.get("group_key"),
                "display_title": group.get("display_title"),
                "source_photo_id": source_photo_id,
                **(_preview_urls(source_photo_id) if source_photo_id else {"preview_url": "", "thumbnail_url": ""}),
                "preview_ready_count": group.get("preview_ready_count"),
                "candidate_status": group.get("candidate_status"),
                "candidate_queue": group.get("candidate_queue"),
                "candidate_media_kind": group.get("candidate_media_kind"),
                "matched_query_terms": group.get("matched_query_terms") or [],
                "candidate_match_quality": group.get("candidate_match_quality"),
                "selection_reason": group.get("selection_reason"),
                "retrieval_gap_truth_status": gap.get("truth_status") or "no_claim",
                "truth_status_before_review": candidate_evidence.get("truth_status") or "no_claim",
                "not_memory_claim": candidate_evidence.get("not_memory_claim") is True,
                "candidate_evidence": candidate_evidence,
                "action": action,
                "suggested_context_fields": [
                    "visible_facts",
                    "invisible_context",
                    "meaning",
                    "uncertainty",
                    "privacy_level",
                    "ready_for_downstream",
                ],
                "completion_criteria": [
                    "Open or create the review task from this retrieval-gap candidate.",
                    "Preserve the source query as no_claim retrieval provenance.",
                    "Add Adam-authored context before treating the photo as memory.",
                    "After submit, the same query should return a boundary-cleared reviewed memory or a clearer next gap.",
                ],
            }
        )

    stable_payload = {
        "query": query,
        "scope": scope,
        "candidate_group_selection_policy": gap.get("candidate_group_selection_policy"),
        "items": items,
    }
    return {
        "slice_type": "retrieval_gap_review_slice",
        "review_policy": "retrieval_gap_no_claim_until_adam_context",
        "query": query,
        "scope": scope,
        "gap_open": True,
        "truth_status": gap.get("truth_status") or "no_claim",
        "does_not_create_memory_claim": True,
        "requires_adam_context": True,
        "workflow": gap.get("workflow") or "photo_context_review",
        "status": gap.get("status") or "no_boundary_cleared_memory_result",
        "message": gap.get("message") or "No boundary-cleared photo memory matched this query yet.",
        "candidate_group_selection_policy": gap.get("candidate_group_selection_policy"),
        "candidate_count": gap.get("candidate_photo_group_count") or 0,
        "weak_evidence_candidate_count": gap.get("weak_evidence_candidate_count") or 0,
        "backlog_only_candidate_count": gap.get("backlog_only_candidate_count") or 0,
        "reported_candidate_count": len(items),
        "completion_signal": "retrieval_query_returns_boundary_cleared_memory_or_context_task_submit_ready",
        "safety_boundaries": [
            "Retrieval-gap candidates are no_claim workflow provenance, not memories.",
            "Filename/title or machine-draft evidence cannot become vector-ready until Adam submits context.",
            "This read-only slice does not mutate archive files or create training examples.",
        ],
        "recommended_action": items[0]["action"] if items else None,
        "resolved_result": None,
        "items": items,
        "content_sha256": hashlib.sha256(
            json.dumps(stable_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest(),
    }


def photo_memory_embedding_corpus(
    *,
    session: Session,
    scope: str = "family_private",
    limit: int = 100,
    include_machine_drafts: bool = False,
) -> Dict[str, Any]:
    rows, excluded = _photo_memory_embedding_rows(
        session=session,
        scope=scope,
        include_machine_drafts=include_machine_drafts,
    )
    capped = rows[: max(1, min(limit, 1000))]
    summary = _photo_memory_handoff_summary(rows=capped, excluded=excluded)
    next_review_actions = _photo_memory_next_review_actions(excluded)
    return {
        "scope": scope,
        "corpus_type": "photo_memory_embedding_text",
        "review_policy": "reviewed_only_by_default",
        "include_machine_drafts": include_machine_drafts,
        "preview_only": include_machine_drafts,
        "not_for_downstream_vector_store": include_machine_drafts,
        "record_count": len(capped),
        "excluded_count": len(excluded),
        **summary,
        "next_review_actions": next_review_actions,
        "records": capped,
        "excluded": excluded,
    }


def _photo_memory_embedding_rows(
    *,
    session: Session,
    scope: str,
    include_machine_drafts: bool = False,
) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    records = session.exec(
        select(EmbeddingRecord)
        .where(EmbeddingRecord.status == "ready_for_embedding")
        .where(EmbeddingRecord.modality == "text")
        .order_by(EmbeddingRecord.created_at.asc())
    ).all()
    rows_by_photo: Dict[str, Dict[str, Any]] = {}
    excluded_by_photo: Dict[str, Dict[str, Any]] = {}
    row_order: List[str] = []
    excluded_order: List[str] = []

    def rank(row: Dict[str, Any]) -> int:
        if row["target_type"] == "memory":
            return 0
        if row["target_type"] == "metadata_profile":
            return 1
        return 2

    def keep_best(target: Dict[str, Dict[str, Any]], order: List[str], row: Dict[str, Any]) -> None:
        source_photo_id = str(row["source_photo_id"])
        if source_photo_id not in target:
            target[source_photo_id] = row
            order.append(source_photo_id)
            return
        current = target[source_photo_id]
        if (rank(row), row["embedding_record_id"]) < (rank(current), current["embedding_record_id"]):
            target[source_photo_id] = row

    def exclusion_rank(row: Dict[str, Any]) -> tuple[int, int, str]:
        is_reviewed_boundary_hold = (
            row.get("review_status") == "excluded_by_boundary"
            and row.get("metadata_source") == "photo_memory_review"
            and row.get("boundary_reviewed_by") == "adam"
        )
        if is_reviewed_boundary_hold:
            status_rank = 0
        elif row.get("review_status") == "excluded_by_boundary":
            status_rank = 1
        elif row.get("review_status") == "held_for_adam_review":
            status_rank = 2
        else:
            status_rank = 3
        return (status_rank, rank(row), str(row.get("embedding_record_id") or ""))

    def keep_best_excluded(row: Dict[str, Any]) -> None:
        source_photo_id = str(row["source_photo_id"])
        if source_photo_id not in excluded_by_photo:
            excluded_by_photo[source_photo_id] = row
            excluded_order.append(source_photo_id)
            return
        current = excluded_by_photo[source_photo_id]
        if exclusion_rank(row) < exclusion_rank(current):
            excluded_by_photo[source_photo_id] = row

    def reviewed_for_vector_handoff(record: EmbeddingRecord, metadata: Dict[str, Any], boundary_snapshot: Dict[str, Any]) -> bool:
        if include_machine_drafts:
            return True
        if metadata.get("source") != "photo_memory_review":
            return False
        if record.truth_status not in REVIEWED_PHOTO_MEMORY_TRUTH_STATUSES:
            return False
        return boundary_snapshot.get("reviewed_by") == "adam"

    for record in records:
        source_photo_id = _source_photo_id(session, record)
        if not source_photo_id:
            continue
        metadata = record.metadata_json or {}
        retrieval_origin = _retrieval_origin_metadata(metadata)
        if metadata.get("source") not in {"photo_memory_machine_draft", "photo_memory_review"}:
            continue
        boundary_snapshot = record.boundary_snapshot or {}
        if not _boundary_allows(boundary_snapshot, scope=scope):
            boundary_snapshot = _asset_boundary_snapshot(session, source_photo_id)
        if not _boundary_allows(boundary_snapshot, scope=scope):
            keep_best_excluded(
                {
                    "embedding_record_id": record.id,
                    "target_type": record.target_type,
                    "target_id": record.target_id,
                    "source_photo_id": source_photo_id,
                    "title": _title_for_record(session, record, source_photo_id),
                    "source_photo_title": _source_photo_title(session, source_photo_id),
                    "truth_status": record.truth_status,
                    "metadata_source": metadata.get("source"),
                    "boundary_reviewed_by": boundary_snapshot.get("reviewed_by"),
                    "privacy_level": boundary_snapshot.get("privacy_level"),
                    "review_status": "excluded_by_boundary",
                    "suggested_next_action": "Adjust boundary clearance before using this photo memory in downstream vector exports.",
                    "reasons": ["boundary_not_allowed_for_scope"],
                },
            )
            continue
        if not reviewed_for_vector_handoff(record, metadata, boundary_snapshot):
            review_task_reference = _photo_review_task_reference(session, source_photo_id)
            keep_best_excluded(
                {
                    "embedding_record_id": record.id,
                    "target_type": record.target_type,
                    "target_id": record.target_id,
                    "source_photo_id": source_photo_id,
                    "title": _title_for_record(session, record, source_photo_id),
                    "source_photo_title": _source_photo_title(session, source_photo_id),
                    "truth_status": record.truth_status,
                    "metadata_source": metadata.get("source"),
                    "boundary_reviewed_by": boundary_snapshot.get("reviewed_by"),
                    "review_status": "held_for_adam_review",
                    "review_queue": "vision_drafts_needing_review",
                    **review_task_reference,
                    "promotion_requirements": PHOTO_MEMORY_PROMOTION_REQUIREMENTS,
                    "suggested_next_action": "Open the photo memory review task and promote Adam-authored context before vector export.",
                    "reasons": ["requires_adam_review"],
                },
            )
            continue
        is_reviewed_ready = (
            metadata.get("source") == "photo_memory_review"
            and record.truth_status in REVIEWED_PHOTO_MEMORY_TRUTH_STATUSES
            and boundary_snapshot.get("reviewed_by") == "adam"
        )
        keep_best(
            rows_by_photo,
            row_order,
            {
                "embedding_record_id": record.id,
                "target_type": record.target_type,
                "target_id": record.target_id,
                "source_photo_id": source_photo_id,
                "title": _title_for_record(session, record, source_photo_id),
                "embedding_type": record.embedding_type,
                "model_name": record.model_name,
                "input_checksum": record.input_checksum,
                "truth_status": record.truth_status,
                "input_text": record.input_text,
                "input_preview": record.input_preview or record.input_text[:280],
                "retrieval_gap_origin": retrieval_origin,
                "boundary_snapshot": boundary_snapshot,
                "metadata": metadata,
                "review_status": "reviewed_vector_ready" if is_reviewed_ready else "machine_draft_preview_only",
                "inclusion_reason": "reviewed_by_adam_and_boundary_allows_scope"
                if is_reviewed_ready
                else "preview_only_machine_draft_included_by_request",
                "inclusion_trace": [
                    f"metadata_source={metadata.get('source') or 'unknown'}",
                    f"truth_status={record.truth_status or 'unknown'}",
                    f"boundary_reviewed_by={boundary_snapshot.get('reviewed_by') or 'unknown'}",
                    f"scope={scope}",
                    "dedupe=one_record_per_source_photo",
                    "preferred_target=memory" if record.target_type == "memory" else f"preferred_target={record.target_type}",
                ],
            },
        )
    rows = [rows_by_photo[source_photo_id] for source_photo_id in row_order]
    excluded = [
        excluded_by_photo[source_photo_id]
        for source_photo_id in excluded_order
        if source_photo_id not in rows_by_photo
    ]
    return rows, excluded


def _stable_json(data: Dict[str, Any]) -> str:
    return json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _photo_memory_handoff_summary(*, rows: List[Dict[str, Any]], excluded: List[Dict[str, Any]]) -> Dict[str, Any]:
    review_status_counts: Dict[str, int] = {}
    exclusion_reason_counts: Dict[str, int] = {}
    reviewed_ready_count = 0
    machine_draft_preview_record_count = 0
    retrieval_origin_record_count = 0
    retrieval_origin_no_claim_count = 0
    for row in rows:
        metadata = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
        boundary_snapshot = row.get("boundary_snapshot") if isinstance(row.get("boundary_snapshot"), dict) else {}
        is_reviewed_ready = (
            metadata.get("source") == "photo_memory_review"
            and row.get("truth_status") in REVIEWED_PHOTO_MEMORY_TRUTH_STATUSES
            and boundary_snapshot.get("reviewed_by") == "adam"
        )
        if is_reviewed_ready:
            reviewed_ready_count += 1
        else:
            machine_draft_preview_record_count += 1
        retrieval_origin = metadata.get("retrieval_gap_origin")
        if isinstance(retrieval_origin, dict) and retrieval_origin.get("query"):
            retrieval_origin_record_count += 1
            if retrieval_origin.get("truth_status") == "no_claim" and retrieval_origin.get("not_memory_claim") is True:
                retrieval_origin_no_claim_count += 1
    for item in excluded:
        status = str(item.get("review_status") or "unknown")
        review_status_counts[status] = review_status_counts.get(status, 0) + 1
        reasons = item.get("reasons") if isinstance(item.get("reasons"), list) else []
        for reason in reasons:
            reason_key = str(reason)
            exclusion_reason_counts[reason_key] = exclusion_reason_counts.get(reason_key, 0) + 1
    return {
        "reviewed_ready_count": reviewed_ready_count,
        "machine_draft_preview_record_count": machine_draft_preview_record_count,
        "retrieval_origin_record_count": retrieval_origin_record_count,
        "retrieval_origin_no_claim_count": retrieval_origin_no_claim_count,
        "held_for_adam_review_count": review_status_counts.get("held_for_adam_review", 0),
        "boundary_excluded_count": review_status_counts.get("excluded_by_boundary", 0),
        "review_status_counts": review_status_counts,
        "exclusion_reason_counts": exclusion_reason_counts,
    }


def _photo_memory_next_review_actions(excluded: List[Dict[str, Any]], *, limit: int = 5) -> List[Dict[str, Any]]:
    actions: List[Dict[str, Any]] = []
    for item in excluded:
        reasons = item.get("reasons") if isinstance(item.get("reasons"), list) else []
        status = item.get("review_status")
        if status == "held_for_adam_review":
            actions.append(
                {
                    "source_photo_id": item.get("source_photo_id"),
                    "source_photo_title": item.get("source_photo_title") or item.get("title"),
                    "review_task_id": item.get("review_task_id"),
                    "review_task_human_id": item.get("review_task_human_id"),
                    "review_queue": item.get("review_queue"),
                    "review_status": status,
                    "reasons": reasons,
                    "suggested_next_action": item.get("suggested_next_action"),
                }
            )
        elif status == "excluded_by_boundary":
            actions.append(
                {
                    "source_photo_id": item.get("source_photo_id"),
                    "source_photo_title": item.get("source_photo_title") or item.get("title"),
                    "review_task_id": None,
                    "review_task_human_id": None,
                    "review_queue": None,
                    "review_status": status,
                    "reasons": reasons,
                    "suggested_next_action": item.get("suggested_next_action"),
                }
            )
        if len(actions) >= limit:
            break
    return actions


def photo_memory_embedding_export(
    *,
    session: Session,
    scope: str = "family_private",
    limit: int = 100,
    include_machine_drafts: bool = False,
) -> Dict[str, Any]:
    rows, excluded = _photo_memory_embedding_rows(
        session=session,
        scope=scope,
        include_machine_drafts=include_machine_drafts,
    )
    capped = rows[: max(1, min(limit, 1000))]
    items: List[Dict[str, Any]] = []
    for row in capped:
        metadata = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
        boundary_snapshot = row.get("boundary_snapshot") if isinstance(row.get("boundary_snapshot"), dict) else {}
        retrieval_origin = row.get("retrieval_gap_origin")
        items.append(
            {
                "id": f"photo-memory:{row['embedding_record_id']}",
                "text": row["input_text"],
                "metadata": {
                    "embedding_record_id": row["embedding_record_id"],
                    "target_type": row["target_type"],
                    "target_id": row["target_id"],
                    "source_photo_id": row["source_photo_id"],
                    "title": row["title"],
                    "truth_status": row["truth_status"],
                    "embedding_type": row["embedding_type"],
                    "input_checksum": row["input_checksum"],
                    "source": metadata.get("source"),
                    "review_status": row.get("review_status"),
                    "inclusion_reason": row.get("inclusion_reason"),
                    "inclusion_trace": row.get("inclusion_trace"),
                    "retrieval_gap_origin": retrieval_origin,
                    "boundary_snapshot": boundary_snapshot,
                },
                "embedding_plan": {
                    "model_name": row["model_name"],
                    "embedding_type": row["embedding_type"],
                    "modality": "text",
                    "live_embedding_call": False,
                    "vector_values_included": False,
                    "vector_uri": None,
                    "provider_record_id": None,
                },
                "review_status": row.get("review_status"),
                "inclusion_reason": row.get("inclusion_reason"),
            }
        )
    jsonl = "\n".join(_stable_json(item) for item in items)
    if jsonl:
        jsonl += "\n"
    content_sha256 = hashlib.sha256(jsonl.encode("utf-8")).hexdigest()
    summary = _photo_memory_handoff_summary(rows=capped, excluded=excluded)
    next_review_actions = _photo_memory_next_review_actions(excluded)
    return {
        "export_type": "photo_memory_vector_handoff",
        "format": "jsonl",
        "scope": scope,
        "manifest": {
            "export_type": "photo_memory_vector_handoff",
            "format": "jsonl",
            "format_version": "2026-04-29.v1",
            "scope": scope,
            "filters": {"scope": scope, "limit": max(1, min(limit, 1000))},
            "review_policy": "reviewed_only_by_default",
            "include_machine_drafts": include_machine_drafts,
            "preview_only": include_machine_drafts,
            "not_for_downstream_vector_store": include_machine_drafts,
            "record_count": len(items),
            "excluded_count": len(excluded),
            **summary,
            "next_review_actions": next_review_actions,
            "source_photo_count": len({item["metadata"]["source_photo_id"] for item in items}),
            "item_ids": [item["id"] for item in items],
            "content_sha256": content_sha256,
            "vector_values_included": False,
            "live_embedding_call": False,
            "boundary_policy_snapshot": {
                "requires_searchable_or_retrievable": True,
                "excluded_privacy_levels": sorted(PHOTO_SENSITIVE_PRIVACY_LEVELS),
                "scope": scope,
            },
            "dedupe_policy_snapshot": {
                "one_record_per_source_photo": True,
                "preferred_target_order": ["memory", "metadata_profile"],
            },
            "embedding_policy_snapshot": {
                "model_status": "pending_provider_embedding",
                "vector_storage": "external_provider_or_object_storage_pointer",
                "ordinary_db_vector_storage": False,
            },
        },
        "jsonl": jsonl,
        "records": items,
        "next_review_actions": next_review_actions,
        "excluded": excluded,
    }


def reviewed_photo_memory_demo_readiness(
    *,
    session: Session,
    scope: str = "family_private",
    limit: int = 5,
) -> Dict[str, Any]:
    safe_limit = max(1, min(limit, 50))
    handoff = photo_memory_embedding_export(
        session=session,
        scope=scope,
        limit=safe_limit,
        include_machine_drafts=False,
    )
    manifest = handoff.get("manifest") if isinstance(handoff.get("manifest"), dict) else {}
    records = handoff.get("records") if isinstance(handoff.get("records"), list) else []
    next_review_actions = handoff.get("next_review_actions") if isinstance(handoff.get("next_review_actions"), list) else []
    photo_context_tasks = session.exec(
        select(Task)
        .where(Task.task_type == "photo_context")
        .where(Task.status == "ready")
        .order_by(Task.created_at.asc())
    ).all()
    context_actions = []
    for task in photo_context_tasks[:safe_limit]:
        payload = task.input_payload or {}
        source_photo_id = payload.get("asset_id") or (task.target_id if task.target_type == "asset" else None)
        asset = session.get(Asset, source_photo_id) if isinstance(source_photo_id, str) else None
        context_actions.append(
            {
                "action_type": "open_photo_context_task",
                "task_id": task.id,
                "task_human_id": task.human_id,
                "review_task_id": task.id,
                "review_task_human_id": task.human_id,
                "review_queue": task.queue,
                "source_photo_id": source_photo_id,
                "source_photo_title": _photo_title(asset) if asset else payload.get("asset_title"),
                "reason": "add_adam_context_and_submit",
                "suggested_next_action": "Open this photo context task and add Adam-authored context, boundary, and downstream readiness.",
                "truth_status_before_review": "no_claim",
                "not_memory_claim": True,
            }
        )
    candidate_actions = []
    for action in next_review_actions[:safe_limit]:
        review_status = action.get("review_status")
        candidate_actions.append(
            {
                "action_type": "open_photo_memory_review_task"
                if review_status == "held_for_adam_review"
                else "resolve_boundary_clearance",
                "reason": "promote_machine_draft_with_adam_review"
                if review_status == "held_for_adam_review"
                else "boundary_not_allowed_for_scope",
                **action,
            }
        )
    candidate_actions.extend(context_actions)
    can_show_reviewed = int(manifest.get("reviewed_ready_count") or 0) > 0
    blockers = []
    if not can_show_reviewed:
        blockers.append("no_reviewed_vector_ready_photo_memory")
    if not can_show_reviewed and not candidate_actions:
        blockers.append("no_ready_review_action")
    sample_reviewed_records = [
        {
            "id": record.get("id"),
            "text_preview": str(record.get("text") or "")[:500],
            "source_photo_id": (record.get("metadata") or {}).get("source_photo_id"),
            "title": (record.get("metadata") or {}).get("title"),
            "truth_status": (record.get("metadata") or {}).get("truth_status"),
            "review_status": record.get("review_status"),
            "inclusion_reason": record.get("inclusion_reason"),
            "inclusion_trace": (record.get("metadata") or {}).get("inclusion_trace"),
            "vector_values_included": (record.get("embedding_plan") or {}).get("vector_values_included"),
            "live_embedding_call": (record.get("embedding_plan") or {}).get("live_embedding_call"),
        }
        for record in records[:safe_limit]
    ]
    return {
        "demo_type": "reviewed_photo_memory_demo_readiness",
        "scope": scope,
        "status": "ready" if can_show_reviewed else "needs_adam_review",
        "can_show_reviewed_vector_memory": can_show_reviewed,
        "reviewed_vector_ready_count": int(manifest.get("reviewed_ready_count") or 0),
        "held_for_adam_review_count": int(manifest.get("held_for_adam_review_count") or 0),
        "boundary_excluded_count": int(manifest.get("boundary_excluded_count") or 0),
        "photo_context_task_count": len(photo_context_tasks),
        "blockers": blockers,
        "candidate_actions": candidate_actions[:safe_limit],
        "sample_reviewed_records": sample_reviewed_records,
        "sample_records": sample_reviewed_records,
        "safety_policy": {
            "does_not_fabricate_adam_memory": True,
            "does_not_create_reviewed_memory": True,
            "does_not_mutate_state": True,
            "does_not_use_filename_as_memory": True,
            "requires_adam_context_for_reviewed_demo": True,
            "outputs_truth_status": "reviewed_photo_memory_records_only"
            if can_show_reviewed
            else "no_claim_until_adam_context_submission",
            "no_live_embedding_call": True,
            "no_fine_tuning_api_call": True,
        },
    }
