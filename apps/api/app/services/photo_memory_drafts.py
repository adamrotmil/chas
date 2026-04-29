from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from sqlmodel import Session, select

from app.models import (
    Annotation,
    Asset,
    Boundary,
    ContextPack,
    EmbeddingRecord,
    Gallery,
    GalleryItem,
    GraphEdge,
    Memory,
    MemorySource,
    MetadataProfile,
    PromptSpec,
    Task,
    utcnow,
)
from app.services.embeddings import boundary_embedding_text, upsert_embedding_record, upsert_profile_embedding
from app.services.pair_export import NATURAL_SYSTEM_PROMPT, compile_pair_export


PHOTO_DRAFT_TEMPLATES: List[Dict[str, Any]] = [
    {
        "match": "Japanese Flute",
        "title": "Photo memory: Charles with Japanese flute",
        "summary": "Charles sits in his apartment playing a Japanese flute, surrounded by books, coffee, pistachios, papers, and ordinary working objects.",
        "context": "Machine draft from image preview and filename. This looks like a memory anchor for music practice, apartment rituals, food nearby, books, and Charles making a private daily practice visible.",
        "people": ["Charles Rotmil"],
        "place": "Portland apartment",
        "themes": ["Japanese flute", "music practice", "daily ritual", "apartment life", "books and objects"],
        "objects": ["Japanese flute", "coffee mug", "pistachios", "books", "papers"],
        "queries": ["Japanese flute", "music practice", "pistachios and coffee"],
    },
    {
        "match": "Honors VIII",
        "title": "Photo memory: honors ceremony",
        "summary": "Black-and-white image of Charles speaking at a microphone inside a synagogue-like hall during an honors or remembrance ceremony.",
        "context": "Machine draft from image preview and filename. This appears connected to public testimony, honors, remembrance, Jewish community, and Charles speaking from the front of a room.",
        "people": ["Charles Rotmil"],
        "place": "ceremonial hall",
        "themes": ["honors ceremony", "public testimony", "Jewish memory", "remembrance", "community event"],
        "objects": ["microphone", "podium", "pews", "arched windows"],
        "queries": ["honors ceremony", "public testimony", "Jewish memory"],
    },
    {
        "match": "Adam with flowers",
        "title": "Photo memory: Adam with flowers",
        "summary": "A young Adam stands outside holding yellow flowers in soft light, with grass and greenery behind him.",
        "context": "Machine draft from image preview and filename. This is a family-memory anchor for Adam as a child, flowers, tenderness, and the kind of small visual detail that can carry emotional memory.",
        "people": ["Adam Rotmil"],
        "place": "outdoors",
        "themes": ["Adam childhood", "flowers", "father and son memory", "tenderness", "family archive"],
        "objects": ["yellow flowers", "grass", "child portrait"],
        "queries": ["Adam flowers", "child with flowers", "family archive"],
    },
    {
        "match": "Street Walker",
        "title": "Photo memory: street portrait",
        "summary": "Black-and-white street portrait of a woman standing against weathered doors, with French signage visible above her.",
        "context": "Machine draft from image preview and filename. This looks like one of Charles' street-photography anchors: a face, a doorway, texture, and a fleeting encounter held by the camera.",
        "people": ["unknown woman"],
        "place": "street with French signage",
        "themes": ["street photography", "portrait", "France", "urban texture", "encounter"],
        "objects": ["weathered door", "French sign", "black-and-white film grain"],
        "queries": ["street photography", "French sign", "street portrait"],
    },
    {
        "match": "Rotmil 2021 I",
        "title": "Photo memory: Mr. Nixon student performance",
        "summary": "A student performance or school display with a young person labeled Mr. Nixon in front of a painted American flag and a SET IT FREE sign.",
        "context": "Machine draft from image preview and filename. This appears to be a staged school or youth performance with political theater imagery, American flag symbolism, and a handmade public-display quality.",
        "people": ["unidentified young performers"],
        "place": "school or public room",
        "themes": ["student performance", "political theater", "American flag", "youth", "archive photo"],
        "objects": ["painted American flag", "Mr. Nixon sign", "globe", "trophy"],
        "queries": ["Mr Nixon", "student performance", "American flag"],
    },
]


def _count(session: Session, model: Any) -> int:
    return len(session.exec(select(model)).all()) + 1


def _asset_title(asset: Asset) -> str:
    return asset.title or asset.original_filename or asset.human_id


def _string(value: Any, fallback: str = "") -> str:
    return value if isinstance(value, str) and value.strip() else fallback


def _human_id(prefix: str, count: int) -> str:
    return f"{prefix}_{count:06d}"


def _find_asset_for_template(session: Session, template: Dict[str, Any]) -> Optional[Asset]:
    marker = str(template["match"]).lower()
    assets = session.exec(
        select(Asset)
        .where(Asset.asset_type == "photo")
        .where(Asset.processing_status == "image_preview_ready")
        .order_by(Asset.created_at.asc())
    ).all()
    matches = [asset for asset in assets if marker in _asset_title(asset).lower()]
    if not matches:
        return None
    matches.sort(key=lambda asset: ("copy" in _asset_title(asset).lower(), len(_asset_title(asset)), _asset_title(asset)))
    return matches[0]


def _profile_asset(session: Session, profile: MetadataProfile) -> Optional[Asset]:
    return session.get(Asset, profile.target_id) if profile.target_type == "asset" else None


def _profile_boundary(session: Session, profile: MetadataProfile) -> Optional[Boundary]:
    if profile.target_type != "asset":
        return None
    return session.exec(
        select(Boundary)
        .where(Boundary.target_type == "asset")
        .where(Boundary.target_id == profile.target_id)
    ).first()


def _profile_memory(session: Session, profile: MetadataProfile) -> Optional[Memory]:
    link = session.exec(
        select(MemorySource)
        .where(MemorySource.source_type == "asset")
        .where(MemorySource.source_id == profile.target_id)
        .where(MemorySource.role == "photo_memory_anchor")
    ).first()
    return session.get(Memory, link.memory_id) if link else None


def _profile_embedding(session: Session, profile: MetadataProfile, memory: Optional[Memory]) -> Optional[EmbeddingRecord]:
    embedding = session.exec(
        select(EmbeddingRecord)
        .where(EmbeddingRecord.target_type == "metadata_profile")
        .where(EmbeddingRecord.target_id == profile.id)
        .order_by(EmbeddingRecord.created_at.desc())
    ).first()
    if embedding:
        return embedding
    if memory:
        return session.exec(
            select(EmbeddingRecord)
            .where(EmbeddingRecord.target_type == "memory")
            .where(EmbeddingRecord.target_id == memory.id)
            .order_by(EmbeddingRecord.created_at.desc())
        ).first()
    return None


def _profile_embedding_text(profile: MetadataProfile, memory: Optional[Memory], embedding: Optional[EmbeddingRecord]) -> str:
    if embedding and embedding.input_text.strip():
        return embedding.input_text
    parts = [
        f"title: {profile.title}" if profile.title else "",
        f"summary: {profile.summary}" if profile.summary else "",
        f"adam_context: {profile.adam_context_note}" if profile.adam_context_note else "",
        f"memory: {memory.summary}" if memory and memory.summary else "",
        f"people: {', '.join(profile.people)}" if profile.people else "",
        f"places: {', '.join(profile.places)}" if profile.places else "",
        f"date: {profile.date_label}" if profile.date_label else "",
        f"themes: {', '.join(profile.themes)}" if profile.themes else "",
        f"concrete_objects: {', '.join(profile.concrete_objects)}" if profile.concrete_objects else "",
        f"open_questions: {', '.join(profile.open_questions)}" if profile.open_questions else "",
    ]
    return "\n".join(part for part in parts if part).strip()


def _profile_retrieval_origin(profile: MetadataProfile) -> Optional[Dict[str, Any]]:
    origin = (profile.raw_profile or {}).get("retrieval_gap_origin")
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


def _is_filename_like(value: str) -> bool:
    lowered = value.strip().lower()
    return lowered.endswith((".jpg", ".jpeg", ".png", ".gif", ".heic", ".tif", ".tiff"))


def _photo_prompt(profile: MetadataProfile) -> str:
    haystack = " ".join(
        [
            profile.title or "",
            profile.summary or "",
            profile.adam_context_note or "",
            " ".join(profile.people),
            " ".join(profile.places),
            " ".join(profile.themes),
            " ".join(profile.concrete_objects),
        ]
    ).lower()
    if any(term in haystack for term in ["airplane", "flight", "flying"]):
        place = profile.places[0] if profile.places else "Maine"
        return f"Dad, what do you remember about flying in {place}?"
    if "flute" in haystack:
        return "Dad, what do you remember about the Japanese flute?"
    if "honors" in haystack or "ceremony" in haystack or "testimony" in haystack:
        return "Dad, what do you remember about that honors ceremony?"
    if "adam" in haystack and "flowers" in haystack:
        return "Dad, what do you remember about Adam holding the flowers?"
    if "street" in haystack or "portrait" in haystack:
        return "Dad, what do you see in this street photograph?"
    topic = next((theme for theme in profile.themes if theme and not _is_filename_like(theme)), "")
    if topic:
        return f"Dad, what does this photograph bring back about {topic}?"
    return "Dad, what does this photograph bring back for you?"


def _photo_response_draft(profile: MetadataProfile) -> str:
    summary = _string(profile.summary)
    context = _string(profile.adam_context_note)
    truth_status = _string(profile.truth_status, "system_inference")
    opening = "i remember this..." if truth_status in {"adam_memory", "adam_inference"} else "i look at this photograph..."
    grounded_lines = [line for line in [summary, context] if line]
    middle = grounded_lines[:2] or ["the photograph is doing the work, the light and the objects holding a small piece of time."]
    return "\n".join(
        [
            opening,
            *middle,
            "",
            "a photograph is never only what is visible.",
            "it carries the room around it...",
            "the light, the objects, the silence before and after.",
            "",
            "love",
            "dad",
        ]
    )


def _existing_photo_pair_task(session: Session, profile_id: str) -> Optional[Task]:
    tasks = session.exec(
        select(Task)
        .where(Task.task_type == "gold_voice_edit")
        .where(Task.queue == "prompt_pairs_needing_gold_edits")
        .order_by(Task.created_at.asc())
    ).all()
    for task in tasks:
        if (task.input_payload or {}).get("source_photo_profile_id") == profile_id:
            return task
    return None


def _photo_profiles_for_pair_candidates(session: Session) -> List[MetadataProfile]:
    profiles = session.exec(
        select(MetadataProfile)
        .where(MetadataProfile.target_type == "asset")
        .where(MetadataProfile.profile_type == "photo_memory")
        .order_by(MetadataProfile.updated_at.desc(), MetadataProfile.created_at.desc())
    ).all()
    ready_statuses = {"adam_reviewed", "machine_draft_needs_adam_review"}
    return [profile for profile in profiles if profile.metadata_status in ready_statuses]


def create_photo_prompt_pair_candidates(session: Session, *, limit: int = 5, dry_run: bool = True) -> Dict[str, Any]:
    limit = max(0, min(limit, 25))
    candidates: List[Dict[str, Any]] = []
    created_task_ids: List[str] = []
    skipped: List[Dict[str, str]] = []

    for profile in _photo_profiles_for_pair_candidates(session):
        if len(candidates) >= limit:
            break
        asset = _profile_asset(session, profile)
        boundary = _profile_boundary(session, profile)
        memory = _profile_memory(session, profile)
        embedding = _profile_embedding(session, profile, memory)
        existing = _existing_photo_pair_task(session, profile.id)
        retrieval_origin = _profile_retrieval_origin(profile)
        if asset is None:
            skipped.append({"metadata_profile_id": profile.id, "reason": "missing_photo_asset"})
            continue
        if boundary is None:
            skipped.append({"metadata_profile_id": profile.id, "reason": "missing_photo_boundary"})
            continue

        embedding_text = _profile_embedding_text(profile, memory, embedding)
        prompt = _photo_prompt(profile)
        content = _photo_response_draft(profile)
        truth_status = _string(profile.truth_status, "system_inference")
        pair = {
            "artifact_mode": "sft",
            "voice_mode": "photography_reflection",
            "synthetic": True,
            "truth_status": truth_status,
            "system_prompt": NATURAL_SYSTEM_PROMPT,
            "prompt": prompt,
            "content": content,
            "context": "\n".join(
                part
                for part in [
                    "Photo-grounded prompt-pair candidate. Adam must review/edit before training export.",
                    f"photo_profile_status: {profile.metadata_status}",
                    f"source_truth_status: {truth_status}",
                    f"photo_title: {_asset_title(asset)}",
                    (
                        "retrieval_gap_origin: "
                        f"{retrieval_origin['query']} "
                        f"({retrieval_origin['candidate_match_quality']}; not a memory claim)"
                    )
                    if retrieval_origin
                    else "",
                    profile.adam_context_note or "",
                ]
                if part
            ),
            "grounding_asset_id": asset.id,
        }
        compiled = compile_pair_export(pair, fallback_truth_status=truth_status)
        candidate = {
            "asset_id": asset.id,
            "asset_title": _asset_title(asset),
            "metadata_profile_id": profile.id,
            "memory_id": memory.id if memory else None,
            "boundary_id": boundary.id,
            "embedding_record_id": embedding.id if embedding else None,
            "prompt": prompt,
            "truth_status": truth_status,
            "retrieval_gap_origin": retrieval_origin,
            "existing_task_id": existing.id if existing else None,
        }
        candidates.append(candidate)
        if dry_run or existing:
            continue

        prompt_spec = PromptSpec(
            human_id=_human_id("PROMPT_PHOTO_PAIR", _count(session, PromptSpec)),
            prompt_type="photo_memory_prompt_pair_candidate",
            voice_mode=compiled["voice_mode"],
            truth_mode=truth_status,
            prompt_text=compiled["prompt"],
            success_criteria={
                "must_preserve_truth_boundary": True,
                "must_link_source_photo": True,
                "must_remain_review_candidate_until_adam_gold_edit": True,
                "must_not_claim_archival_quote": True,
            },
            metadata_json={
                "system_prompt": compiled["system_prompt"],
                "source_photo_id": asset.id,
                "source_photo_profile_id": profile.id,
                "source_photo_memory_id": memory.id if memory else None,
                "source_embedding_record_id": embedding.id if embedding else None,
                "source_profile_status": profile.metadata_status,
                "source_truth_status": truth_status,
                "retrieval_gap_origin": retrieval_origin,
                "export_preview_yaml": compiled["yaml_preview"],
            },
        )
        session.add(prompt_spec)
        session.flush()

        context_pack = ContextPack(
            human_id=_human_id("CTX_PHOTO_PAIR", _count(session, ContextPack)),
            user_intent="photo_memory_prompt_pair_generation",
            requested_voice_mode=compiled["voice_mode"],
            truth_mode=truth_status,
            allowed_facts=[embedding_text[:1800]] if embedding_text else [],
            boundaries_snapshot={
                "source_photo_id": asset.id,
                "source_photo_profile_id": profile.id,
                "source_photo_memory_id": memory.id if memory else None,
                "source_embedding_record_id": embedding.id if embedding else None,
                "retrieval_gap_origin": retrieval_origin,
                "requires_adam_gold_edit": True,
                "candidate_only": True,
                "boundary": boundary.model_dump(mode="json"),
            },
            style_guidance={
                "system_prompt": compiled["system_prompt"],
                "voice_mode": compiled["voice_mode"],
                "artifact_mode": compiled["artifact_mode"],
                "source_modality": "photo",
                "retrieval_gap_origin_policy": "workflow provenance only; not a source fact or memory claim"
                if retrieval_origin
                else None,
            },
        )
        session.add(context_pack)
        session.flush()

        task = Task(
            human_id=_human_id("TASK_PHOTO_PAIR", _count(session, Task)),
            task_type="gold_voice_edit",
            target_type="prompt_pair",
            target_id=prompt_spec.id,
            priority=82,
            queue="prompt_pairs_needing_gold_edits",
            reason_created="Photo memory record generated a prompt-pair candidate for Adam gold-edit review.",
            input_payload={
                **compiled,
                "export_flags": {"sft": False, "dpo": False, "eval": False, "anti_pattern": False, "style_rule": False},
                "prompt_spec_id": prompt_spec.id,
                "context_pack_id": context_pack.id,
                "source_title": profile.title or _asset_title(asset),
                "source_excerpt": embedding_text[:6000],
                "source_photo_id": asset.id,
                "source_photo_profile_id": profile.id,
                "source_photo_memory_id": memory.id if memory else None,
                "source_embedding_record_id": embedding.id if embedding else None,
                "retrieval_gap_origin": retrieval_origin,
                "embedding_input_text": embedding_text,
                "boundary_snapshot": boundary.model_dump(mode="json"),
                "source_profile_status": profile.metadata_status,
                "source_truth_status": truth_status,
                "candidate_requires_adam_gold_edit": True,
                "no_live_model_call": True,
                "pair_index": f"photo-{len(created_task_ids) + 1:03d}",
                "failure_modes": ["photo_grounded_synthetic_candidate_needs_adam_review"],
            },
            required_decisions=["artifact_mode", "voice_mode", "prompt", "content", "response_rubric"],
            created_by="photo_memory_prompt_pair_generation",
        )
        session.add(task)
        session.flush()
        created_task_ids.append(task.id)
        candidate["created_task_id"] = task.id

    if not dry_run:
        session.commit()
    return {
        "dry_run": dry_run,
        "requested_limit": limit,
        "created_count": len(candidates),
        "created_task_ids": created_task_ids,
        "candidates": candidates,
        "skipped": skipped,
    }


def _asset_boundary(session: Session, asset_id: str) -> Boundary:
    boundary = session.exec(
        select(Boundary).where(Boundary.target_type == "asset").where(Boundary.target_id == asset_id)
    ).first()
    desired = {
        "privacy_level": "family_private",
        "searchable": True,
        "retrievable_in_chat": True,
        "quotable": False,
        "summarizable": True,
        "usable_for_voice_context": True,
        "usable_for_sft": False,
        "usable_for_dpo": False,
        "usable_for_eval": True,
        "usable_for_gallery_public": False,
        "usable_for_gallery_family": True,
        "usable_for_simulation": True,
        "contains_living_person_sensitive_material": False,
        "redaction_required": False,
        "notes": "Machine-drafted family-private photo memory boundary; Adam review still required before quotation/public use.",
        "reviewed_by": "system_draft",
    }
    if boundary is None:
        boundary = Boundary(target_type="asset", target_id=asset_id)
        changed = True
    else:
        changed = any(getattr(boundary, key) != value for key, value in desired.items())
    for key, value in desired.items():
        setattr(boundary, key, value)
    if changed:
        boundary.reviewed_at = utcnow()
    session.add(boundary)
    session.flush()
    return boundary


def _existing_photo_memory_profile(session: Session, asset_id: str) -> Optional[MetadataProfile]:
    return session.exec(
        select(MetadataProfile)
        .where(MetadataProfile.target_type == "asset")
        .where(MetadataProfile.target_id == asset_id)
        .where(MetadataProfile.profile_type == "photo_memory")
    ).first()


def _profile_has_human_truth(profile: MetadataProfile) -> bool:
    return profile.metadata_status in {"adam_reviewed", "approved"} or profile.truth_status in {
        "adam_memory",
        "adam_inference",
        "adam_expert_reconstruction",
        "archival_source",
        "spoken_source",
    }


def _upsert_machine_draft_annotation(
    session: Session,
    *,
    asset: Asset,
    template: Dict[str, Any],
) -> Tuple[Annotation, bool]:
    decisions = {"template": template, "asset_title": _asset_title(asset)}
    existing = session.exec(
        select(Annotation)
        .where(Annotation.target_type == "asset")
        .where(Annotation.target_id == asset.id)
        .where(Annotation.annotation_type == "photo_memory_machine_draft")
    ).first()
    if existing:
        return existing, False
    annotation = Annotation(
        task_id=None,
        annotator_id="system_draft",
        target_type="asset",
        target_id=asset.id,
        annotation_type="photo_memory_machine_draft",
        decisions=decisions,
        notes="Machine-generated photo memory draft from imported preview and filename; Adam review required.",
    )
    session.add(annotation)
    session.flush()
    return annotation, True


def _upsert_profile(
    session: Session,
    *,
    asset: Asset,
    template: Dict[str, Any],
    annotation: Annotation,
) -> MetadataProfile:
    profile = _existing_photo_memory_profile(session, asset.id)
    if profile is None:
        profile = MetadataProfile(target_type="asset", target_id=asset.id, profile_type="photo_memory")
    profile.profile_version = "v1"
    profile.metadata_status = "machine_draft_needs_adam_review"
    profile.title = str(template["title"])
    profile.summary = str(template["summary"])
    profile.adam_context_note = str(template["context"])
    profile.source_genre = "photo"
    profile.truth_status = "system_inference"
    profile.date_label = str(asset.source_modified_time.date()) if asset.source_modified_time else "unknown"
    profile.date_confidence = "source_file_modified_time" if asset.source_modified_time else "unknown"
    profile.people = list(template["people"])
    profile.places = [str(template["place"])]
    profile.themes = list(template["themes"])
    profile.concrete_objects = list(template["objects"])
    profile.open_questions = [
        "Adam should confirm people, place, date, and why this photo matters before any public or training use."
    ]
    profile.retrieval_notes = " ".join([str(template["context"]), "Queries:", ", ".join(template["queries"])])
    profile.training_notes = "Machine photo draft for retrieval/context only; not direct SFT/DPO training text."
    profile.quality_signals = {"draft_source": "filename_and_image_preview", "needs_adam_review": True}
    profile.embedding_hints = {"modality": "photo", "use_before_review": "family_private_retrieval_only"}
    profile.raw_profile = {"template": template, "asset_title": _asset_title(asset), "source_annotation_id": annotation.id}
    profile.source_annotation_id = annotation.id
    profile.created_by = "photo_memory_machine_draft"
    profile.reviewed_by = "system_draft"
    profile.reviewed_at = utcnow()
    profile.updated_at = utcnow()
    session.add(profile)
    session.flush()
    return profile


def _upsert_memory(
    session: Session,
    *,
    asset: Asset,
    profile: MetadataProfile,
    annotation: Annotation,
) -> Memory:
    link = session.exec(
        select(MemorySource)
        .where(MemorySource.source_type == "asset")
        .where(MemorySource.source_id == asset.id)
        .where(MemorySource.role == "photo_memory_anchor")
    ).first()
    memory = session.get(Memory, link.memory_id) if link else None
    if memory is None:
        memory = Memory(
            human_id=f"MEM_PHOTO_DRAFT_{_count(session, Memory):06d}",
            title=profile.title or _asset_title(asset),
            summary="",
            truth_status="system_inference",
            reliability="low",
            maturity_level="L2_machine_draft",
        )
    memory.title = profile.title or memory.title
    memory.summary = "\n\n".join(
        part
        for part in [
            "Photo memory machine draft.",
            profile.summary,
            profile.adam_context_note,
            f"People: {', '.join(profile.people)}" if profile.people else "",
            f"Place: {', '.join(profile.places)}" if profile.places else "",
            f"Themes: {', '.join(profile.themes)}" if profile.themes else "",
            f"Objects: {', '.join(profile.concrete_objects)}" if profile.concrete_objects else "",
        ]
        if part
    )
    memory.truth_status = "system_inference"
    memory.reliability = "low"
    memory.themes = profile.themes
    memory.open_questions = profile.open_questions
    memory.updated_at = utcnow()
    session.add(memory)
    session.flush()

    if link is None:
        link = MemorySource(
            memory_id=memory.id,
            source_type="asset",
            source_id=asset.id,
            role="photo_memory_anchor",
            confidence="low",
        )
    link.notes = f"Machine draft from photo preview annotation {annotation.id}; Adam review required."
    session.add(link)
    session.flush()

    edge = session.exec(
        select(GraphEdge)
        .where(GraphEdge.from_type == "asset")
        .where(GraphEdge.from_id == asset.id)
        .where(GraphEdge.relation == "draft_evokes_memory")
        .where(GraphEdge.to_type == "memory")
        .where(GraphEdge.to_id == memory.id)
    ).first()
    if edge is None:
        edge = GraphEdge(
            from_type="asset",
            from_id=asset.id,
            relation="draft_evokes_memory",
            to_type="memory",
            to_id=memory.id,
            confidence="low",
            created_by="photo_memory_machine_draft",
        )
    edge.evidence = {"metadata_profile_id": profile.id, "source_annotation_id": annotation.id}
    session.add(edge)
    session.flush()
    return memory


def _upsert_gallery_item(session: Session, *, asset: Asset, profile: MetadataProfile, boundary: Boundary) -> GalleryItem:
    gallery = session.exec(select(Gallery).where(Gallery.human_id == "GALLERY_MACHINE_DRAFT_PHOTOS")).first()
    if gallery is None:
        gallery = Gallery(
            human_id="GALLERY_MACHINE_DRAFT_PHOTOS",
            title="Machine Draft Photo Memories",
            description="Family-private photo memory drafts awaiting Adam review.",
            scope="family_private",
        )
        session.add(gallery)
        session.flush()
    item = session.exec(
        select(GalleryItem).where(GalleryItem.gallery_id == gallery.id).where(GalleryItem.asset_id == asset.id)
    ).first()
    if item is None:
        item = GalleryItem(gallery_id=gallery.id, asset_id=asset.id)
    item.gallery_scope = "family_private"
    item.title = profile.title
    item.display_caption = profile.summary
    item.memory_caption = profile.adam_context_note
    item.boundary_snapshot = boundary.model_dump(mode="json")
    session.add(item)
    session.flush()
    return item


def _vision_draft_from_template(template: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "visual_summary": str(template["summary"]),
        "visible_people": list(template["people"]),
        "places": [str(template["place"])],
        "time_period_guess": "unknown",
        "objects": list(template["objects"]),
        "themes": list(template["themes"]),
        "ocr_text": "",
        "handwriting_text": "",
        "uncertainties": [
            "Machine draft created from imported image preview and filename; Adam should verify people, place, date, and meaning."
        ],
        "suggested_questions": [
            {
                "id": "why_this_photo_matters",
                "question": "What does this photo mean to you, beyond what is visible?",
                "reason": "This becomes Adam-provided context for retrieval and memory use.",
                "answer_type": "long_text",
            },
            {
                "id": "what_should_be_corrected",
                "question": "What did the machine draft get wrong or miss?",
                "reason": "Rejected system inferences should stay separate from reviewed memory.",
                "answer_type": "long_text",
            },
            {
                "id": "downstream_boundary",
                "question": "Can this stay family-private retrieval/gallery material?",
                "reason": "Photo records need explicit boundary clearance before downstream use.",
                "answer_type": "privacy_note",
            },
        ],
        "privacy_flags": ["family_private_review_required"],
        "confidence": "low_machine_draft",
    }


def _upsert_review_task(
    session: Session,
    *,
    asset: Asset,
    profile: MetadataProfile,
    template: Dict[str, Any],
) -> Tuple[Task, bool]:
    existing = session.exec(
        select(Task)
        .where(Task.task_type == "vision_draft_review")
        .where(Task.target_type == "metadata_profile")
        .where(Task.target_id == profile.id)
        .where(Task.status != "canceled")
        .order_by(Task.created_at.asc())
    ).first()
    if existing:
        return existing, False
    task = Task(
        human_id=f"TASK_PHOTO_MEMORY_REVIEW_{_count(session, Task):06d}",
        task_type="vision_draft_review",
        target_type="metadata_profile",
        target_id=profile.id,
        priority=78,
        queue="vision_drafts_needing_review",
        reason_created="Machine photo-memory draft needs Adam review before being treated as durable memory.",
        input_payload={
            "asset_id": asset.id,
            "asset_type": asset.asset_type,
            "asset_title": _asset_title(asset),
            "source_filename": asset.original_filename,
            "source_type": asset.asset_type,
            "metadata_profile_id": profile.id,
            "draft_type": "photo_memory_machine_draft",
            "truth_status": "system_inference",
            "vision_draft": _vision_draft_from_template(template),
            "suggested_questions": _vision_draft_from_template(template)["suggested_questions"],
            "no_live_model_call": True,
            "source_photo_memory_draft": True,
        },
        required_decisions=[
            "vision_accuracy",
            "accepted_visual_description",
            "question_answers",
            "adam_context_note",
            "privacy_level",
            "ready_for_downstream",
            "ocr_review_status",
        ],
        created_by="photo_memory_machine_draft",
    )
    session.add(task)
    session.flush()
    return task, True


def create_photo_memory_drafts(session: Session, *, limit: int = 5, dry_run: bool = True) -> Dict[str, Any]:
    limit = max(0, min(limit, len(PHOTO_DRAFT_TEMPLATES)))
    candidates: List[Dict[str, Any]] = []
    review_task_ids: List[str] = []
    skipped: List[Dict[str, str]] = []
    created_new_count = 0
    reused_count = 0
    for template in PHOTO_DRAFT_TEMPLATES:
        if len(candidates) >= limit:
            break
        asset = _find_asset_for_template(session, template)
        if not asset:
            continue
        existing_profile = _existing_photo_memory_profile(session, asset.id)
        if existing_profile and _profile_has_human_truth(existing_profile):
            skipped.append(
                {
                    "asset_id": asset.id,
                    "asset_title": _asset_title(asset),
                    "metadata_profile_id": existing_profile.id,
                    "reason": "existing_human_reviewed_photo_memory",
                }
            )
            continue
        candidates.append({"asset_id": asset.id, "asset_title": _asset_title(asset), "template_title": template["title"]})
        if dry_run:
            continue
        annotation, annotation_created = _upsert_machine_draft_annotation(session, asset=asset, template=template)
        boundary = _asset_boundary(session, asset.id)
        profile = _upsert_profile(session, asset=asset, template=template, annotation=annotation)
        memory = _upsert_memory(session, asset=asset, profile=profile, annotation=annotation)
        gallery_item = _upsert_gallery_item(session, asset=asset, profile=profile, boundary=boundary)
        review_task, review_task_created = _upsert_review_task(session, asset=asset, profile=profile, template=template)
        if annotation_created or review_task_created:
            created_new_count += 1
        else:
            reused_count += 1
        review_task_ids.append(review_task.id)
        profile_embedding = upsert_profile_embedding(
            session=session,
            profile=profile,
            target_boundary_type="asset",
            target_boundary_id=asset.id,
            metadata={"source": "photo_memory_machine_draft", "asset_id": asset.id},
        )
        memory_embedding = upsert_embedding_record(
            session=session,
            target_type="memory",
            target_id=memory.id,
            input_text="\n\n".join(
                [
                    f"{memory.title}\n\n{memory.summary}",
                    f"Retrieval queries: {', '.join(template['queries'])}",
                    boundary_embedding_text(boundary.model_dump(mode="json")),
                ]
            ),
            modality="text",
            embedding_type="memory_text",
            truth_status="system_inference",
            boundary_snapshot=boundary.model_dump(mode="json"),
            metadata={
                "source": "photo_memory_machine_draft",
                "asset_id": asset.id,
                "metadata_profile_id": profile.id,
                "source_annotation_id": annotation.id,
            },
            created_by="photo_memory_machine_draft",
        )
        candidates[-1].update(
            {
                "annotation_id": annotation.id,
                "boundary_id": boundary.id,
                "metadata_profile_id": profile.id,
                "memory_id": memory.id,
                "gallery_item_id": gallery_item.id,
                "review_task_id": review_task.id,
                "profile_embedding_record_id": profile_embedding.id if profile_embedding else None,
                "memory_embedding_record_id": memory_embedding.id if memory_embedding else None,
                "created_new": annotation_created or review_task_created,
                "reused_existing": not (annotation_created or review_task_created),
            }
        )
        asset.maturity_level = "L2_machine_draft"
        asset.updated_at = utcnow()
        session.add(asset)

    if not dry_run:
        session.commit()
    return {
        "dry_run": dry_run,
        "requested_limit": limit,
        "created_count": len(candidates),
        "candidate_count": len(candidates),
        "created_new_count": created_new_count,
        "reused_count": reused_count,
        "review_task_ids": review_task_ids,
        "candidates": candidates,
        "skipped": skipped,
    }
