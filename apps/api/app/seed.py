from typing import Any, Dict, Optional, Type, TypeVar

from sqlmodel import Session, select

from app.db.session import engine
from app.models import (
    AntiPattern,
    Asset,
    Boundary,
    ContextPack,
    ContextPackItem,
    DPOPair,
    Derivative,
    Entity,
    EntityAlias,
    EvalCase,
    ExternalRef,
    Gallery,
    GalleryItem,
    Generation,
    GoldVoiceExample,
    Memory,
    MemorySource,
    ObjectFile,
    PromptSpec,
    SFTCandidate,
    Segment,
    StyleRule,
    Task,
)

T = TypeVar("T")


def one_by(session: Session, model: Type[T], field: str, value: Any) -> Optional[T]:
    return session.exec(select(model).where(getattr(model, field) == value)).first()


def add_if_missing(session: Session, model: Type[T], field: str, value: Any, data: Dict[str, Any]) -> T:
    existing = one_by(session, model, field, value)
    if existing:
        return existing
    record = model(**data)
    session.add(record)
    session.flush()
    return record


def seed_assets(session: Session) -> Dict[str, Asset]:
    photo = add_if_missing(
        session,
        Asset,
        "human_id",
        "CR_ASSET_PHOTO_0001",
        {
            "human_id": "CR_ASSET_PHOTO_0001",
            "asset_type": "photo",
            "title": "Maine kitchen photo",
            "original_filename": "maine_kitchen_seed.jpg",
            "mime_type": "image/jpeg",
            "source_system": "local_seed",
            "maturity_level": "L2_extracted",
        },
    )
    text = add_if_missing(
        session,
        Asset,
        "human_id",
        "CR_ASSET_TEXT_0001",
        {
            "human_id": "CR_ASSET_TEXT_0001",
            "asset_type": "text",
            "title": "Seed email after a visit",
            "original_filename": "email_after_visit.txt",
            "mime_type": "text/plain",
            "source_system": "local_seed",
            "maturity_level": "L2_extracted",
        },
    )
    audio = add_if_missing(
        session,
        Asset,
        "human_id",
        "CR_ASSET_AUDIO_0001",
        {
            "human_id": "CR_ASSET_AUDIO_0001",
            "asset_type": "audio",
            "title": "Seed interview clip",
            "original_filename": "interview_clip_seed.m4a",
            "mime_type": "audio/mp4",
            "source_system": "local_seed",
            "maturity_level": "L1_mirrored",
        },
    )

    for asset in [photo, text, audio]:
        add_if_missing(
            session,
            ExternalRef,
            "external_id",
            f"seed:{asset.human_id}",
            {
                "asset_id": asset.id,
                "source_system": "local_seed",
                "external_id": f"seed:{asset.human_id}",
                "uri": f"file://import_samples/{asset.original_filename}",
                "metadata_json": {"source_note": "Demo seed reference"},
            },
        )
        object_file = add_if_missing(
            session,
            ObjectFile,
            "object_key",
            f"raw/{asset.human_id}/original",
            {
                "storage_provider": "local",
                "object_key": f"raw/{asset.human_id}/original",
                "uri": f"object://raw/{asset.human_id}/original",
                "content_type": asset.mime_type,
                "metadata_json": {"source_asset_id": asset.human_id, "seed": True},
            },
        )
        add_if_missing(
            session,
            Boundary,
            "target_id",
            asset.id,
            {
                "target_type": "asset",
                "target_id": asset.id,
                "privacy_level": "unreviewed",
                "summarizable": True,
                "notes": "Seed boundary awaiting review.",
            },
        )
        if asset.asset_type == "photo":
            add_if_missing(
                session,
                Derivative,
                "asset_id",
                asset.id,
                {
                    "asset_id": asset.id,
                    "derivative_type": "thumbnail",
                    "object_file_id": object_file.id,
                    "status": "placeholder",
                    "metadata_json": {"note": "MVP placeholder derivative"},
                },
            )

    return {"photo": photo, "text": text, "audio": audio}


def seed_memory_graph(session: Session, assets: Dict[str, Asset]) -> Dict[str, Any]:
    adam = add_if_missing(
        session,
        Entity,
        "human_id",
        "CR_ENTITY_ADAM",
        {
            "human_id": "CR_ENTITY_ADAM",
            "entity_type": "person",
            "canonical_name": "Adam Rotmil",
            "relationship_to_charles": "son",
            "relationship_to_adam": "self",
            "confidence": "high",
        },
    )
    charles = add_if_missing(
        session,
        Entity,
        "human_id",
        "CR_ENTITY_CHARLES",
        {
            "human_id": "CR_ENTITY_CHARLES",
            "entity_type": "person",
            "canonical_name": "Charles Rotmil",
            "relationship_to_adam": "father",
            "confidence": "high",
        },
    )
    add_if_missing(
        session,
        EntityAlias,
        "alias",
        "Dad",
        {"entity_id": charles.id, "alias": "Dad", "source": "seed", "confidence": "high"},
    )

    segment = add_if_missing(
        session,
        Segment,
        "human_id",
        "CR_SEG_EMAIL_0001",
        {
            "human_id": "CR_SEG_EMAIL_0001",
            "asset_id": assets["text"].id,
            "segment_type": "email_body",
            "title": "Post-visit email fragment",
            "text_content": "Found your coffee cup in the sink. Call when you get in.",
            "locator": {"source": "seed email"},
            "source_truth_status": "archival_source",
            "maturity_level": "L3_reviewed",
            "metadata_json": {"voice_mode_candidates": ["father_to_adam", "logistical_note"]},
        },
    )

    maine_memory = add_if_missing(
        session,
        Memory,
        "human_id",
        "CR_MEMORY_0001",
        {
            "human_id": "CR_MEMORY_0001",
            "title": "Maine visits and practical tenderness",
            "summary": "Charles often let ordinary objects, food, and logistics carry affection after visits.",
            "truth_status": "interpretive_synthesis",
            "reliability": "medium_high",
            "emotional_tone": ["tender", "comic", "melancholy"],
            "themes": ["fatherhood", "food_as_care", "ordinary_tenderness"],
            "open_questions": ["Which exact summer does the kitchen photo belong to?"],
            "maturity_level": "L4_linked",
        },
    )
    photo_memory = add_if_missing(
        session,
        Memory,
        "human_id",
        "CR_MEMORY_0002",
        {
            "human_id": "CR_MEMORY_0002",
            "title": "Photography as witness",
            "summary": "Photos are treated as memory anchors, not decoration, and need Adam's invisible context.",
            "truth_status": "adam_memory",
            "reliability": "medium",
            "emotional_tone": ["careful", "observant"],
            "themes": ["photography", "memory", "archive"],
            "open_questions": [],
            "maturity_level": "L3_reviewed",
        },
    )

    for memory, source_type, source_id in [
        (maine_memory, "segment", segment.id),
        (maine_memory, "asset", assets["photo"].id),
        (photo_memory, "asset", assets["photo"].id),
    ]:
        key = f"{memory.id}:{source_type}:{source_id}"
        add_if_missing(
            session,
            MemorySource,
            "notes",
            key,
            {
                "memory_id": memory.id,
                "source_type": source_type,
                "source_id": source_id,
                "role": "supports",
                "confidence": "medium",
                "notes": key,
            },
        )

    return {
        "adam": adam,
        "charles": charles,
        "segment": segment,
        "maine_memory": maine_memory,
        "photo_memory": photo_memory,
    }


def seed_voice_records(session: Session, graph: Dict[str, Any]) -> Dict[str, Any]:
    prompt = add_if_missing(
        session,
        PromptSpec,
        "human_id",
        "PROMPT_FATHER_NOTE_0001",
        {
            "human_id": "PROMPT_FATHER_NOTE_0001",
            "prompt_type": "gold_voice_edit",
            "voice_mode": "father_to_adam",
            "truth_mode": "generative_reconstruction",
            "prompt_text": "Write Adam a short note after he leaves Maine.",
            "success_criteria": {
                "voice_fidelity_min": 4,
                "must_avoid": ["therapy language", "generic sentimentality"],
            },
            "metadata_json": {"seed": True},
        },
    )
    context_pack = add_if_missing(
        session,
        ContextPack,
        "human_id",
        "CTX_SEED_0001",
        {
            "human_id": "CTX_SEED_0001",
            "user_intent": "photo_reflection",
            "requested_voice_mode": "father_to_adam",
            "truth_mode": "generative_reconstruction",
            "allowed_facts": [
                "The visit is connected to Maine.",
                "Adam remembers affection arriving through ordinary objects and logistics.",
            ],
            "boundaries_snapshot": {"quote_source_text": False, "disclose_generated": True},
            "style_guidance": {
                "mode": "father_to_adam",
                "avoid": ["generic sentimentality", "therapy language"],
            },
        },
    )
    add_if_missing(
        session,
        ContextPackItem,
        "item_id",
        graph["maine_memory"].id,
        {
            "context_pack_id": context_pack.id,
            "item_type": "memory",
            "item_id": graph["maine_memory"].id,
            "role": "primary_memory",
            "rank": 1,
        },
    )

    generation = add_if_missing(
        session,
        Generation,
        "output_text",
        "Dear Adam,\n\nI want you to know how meaningful our time together was. I feel very grateful for the visit and for the bond we share.\n\nLove,\nDad",
        {
            "prompt_spec_id": prompt.id,
            "context_pack_id": context_pack.id,
            "model_name": "manual_seed_draft",
            "model_parameters": {"temperature": 0.7, "note": "No live model call was made."},
            "output_text": "Dear Adam,\n\nI want you to know how meaningful our time together was. I feel very grateful for the visit and for the bond we share.\n\nLove,\nDad",
        },
    )
    gold = add_if_missing(
        session,
        GoldVoiceExample,
        "human_id",
        "CR_GOLD_VOICE_0001",
        {
            "human_id": "CR_GOLD_VOICE_0001",
            "generation_id": generation.id,
            "prompt_spec_id": prompt.id,
            "context_pack_id": context_pack.id,
            "voice_mode": "father_to_adam",
            "truth_status": "adam_expert_reconstruction",
            "adam_gold_edit": "Adam\n\nhouse is too quiet now.\neven the refrigerator sounds dramatic.\n\nfound your coffee cup in the sink.\ngood.\nproof you were here.\n\ncall when you get in\n\ndad",
            "ratings": {
                "voice_fidelity": 5,
                "mode_match": 5,
                "emotional_truth": 5,
                "concrete_detail": 5,
                "restraint": 5,
                "non_parody": 5,
                "grounding": 5,
            },
            "failure_modes": ["too_generic", "too_therapy_like", "too_emotionally_explicit"],
            "downstream_use": {"sft": True, "dpo": True, "eval": True, "anti_pattern": True},
            "approved_by": "adam",
        },
    )

    add_if_missing(
        session,
        SFTCandidate,
        "source_gold_voice_example_id",
        gold.id,
        {
            "source_gold_voice_example_id": gold.id,
            "messages": [
                {
                    "role": "system",
                    "content": "Write in Charles's father-to-Adam mode. Use indirect tenderness, concrete objects, restraint, and practical endings. Do not claim generated text is archival.",
                },
                {"role": "user", "content": prompt.prompt_text},
                {"role": "assistant", "content": gold.adam_gold_edit},
            ],
            "quality_gate": {
                "approved_by": "adam",
                "min_voice_fidelity_met": True,
                "boundaries_checked": True,
                "no_archival_misattribution": True,
            },
            "export_status": "approved",
        },
    )
    add_if_missing(
        session,
        DPOPair,
        "source_gold_voice_example_id",
        gold.id,
        {
            "source_gold_voice_example_id": gold.id,
            "prompt": prompt.prompt_text,
            "chosen": gold.adam_gold_edit,
            "rejected": generation.output_text,
            "reason": ["too_generic", "too_therapy_like", "chosen_has_object_carried_feeling"],
            "export_status": "approved",
        },
    )
    add_if_missing(
        session,
        EvalCase,
        "human_id",
        "EVAL_0001",
        {
            "human_id": "EVAL_0001",
            "prompt": prompt.prompt_text,
            "voice_mode": "father_to_adam",
            "truth_mode": "generative_reconstruction",
            "success_criteria": {
                "voice_fidelity_min": 4,
                "must_include": ["concrete object carrying emotion"],
                "must_avoid": ["therapy language", "over-explanation"],
            },
            "gold_reference_id": gold.id,
            "status": "approved",
        },
    )
    add_if_missing(
        session,
        AntiPattern,
        "human_id",
        "ANTI_0001",
        {
            "human_id": "ANTI_0001",
            "name": "generic_therapy_language",
            "voice_mode": "father_to_adam",
            "examples": [generation.output_text],
            "why_wrong": "Too smooth, too therapeutic, and too emotionally explicit for this mode.",
            "source_gold_voice_example_id": gold.id,
            "status": "approved",
        },
    )
    add_if_missing(
        session,
        StyleRule,
        "human_id",
        "STYLE_0001",
        {
            "human_id": "STYLE_0001",
            "voice_mode": "father_to_adam",
            "rule": "Let the object do the emotional work before explaining the feeling.",
            "rationale": "The coffee cup carries the loss after the visit.",
            "source_gold_voice_example_id": gold.id,
            "status": "candidate",
        },
    )

    return {"prompt": prompt, "context_pack": context_pack, "generation": generation, "gold": gold}


def seed_tasks(session: Session, assets: Dict[str, Asset], graph: Dict[str, Any], voice: Dict[str, Any]) -> None:
    task_specs = [
        {
            "human_id": "TASK_ASSET_TRIAGE_0001",
            "task_type": "asset_triage",
            "target_type": "asset",
            "target_id": assets["audio"].id,
            "priority": 80,
            "queue": "highest_value_next",
            "reason_created": "Audio asset is mirrored but needs initial processing decision.",
            "input_payload": {
                "title": assets["audio"].title,
                "source_type": "audio",
                "preview": "Seed interview clip awaiting triage.",
            },
            "required_decisions": ["source_type", "importance", "initial_privacy_level", "process_next"],
        },
        {
            "human_id": "TASK_PHOTO_CONTEXT_0001",
            "task_type": "photo_context",
            "target_type": "asset",
            "target_id": assets["photo"].id,
            "priority": 95,
            "queue": "photos_needing_context",
            "reason_created": "Photo needs people, place, date, invisible context, and gallery eligibility.",
            "input_payload": {
                "title": assets["photo"].title,
                "machine_guess_people": ["Charles?", "Adam?"],
                "machine_guess_place": "Maine?",
                "prompt": "What would a stranger miss from looking at this?",
            },
            "required_decisions": ["visible_people", "place", "date_or_range", "invisible_context_note", "gallery_eligibility"],
        },
        {
            "human_id": "TASK_TEXT_REVIEW_0001",
            "task_type": "text_segment_review",
            "target_type": "segment",
            "target_id": graph["segment"].id,
            "priority": 70,
            "queue": "text_segments_needing_review",
            "reason_created": "Email body segment needs source status, Adam context, and boundary rationale.",
            "input_payload": {
                "segment_title": graph["segment"].title,
                "text": graph["segment"].text_content,
            },
            "required_decisions": [
                "segment_boundary_good",
                "segment_title",
                "source_genre",
                "authorship",
                "creator_entity_ids",
                "authorship_note",
                "fictionality_status",
                "truth_status",
                "voice_presence",
                "adam_context_note",
                "boundary_rationale",
            ],
        },
        {
            "human_id": "TASK_BOUNDARY_0001",
            "task_type": "boundary_review",
            "target_type": "memory",
            "target_id": graph["maine_memory"].id,
            "priority": 90,
            "queue": "sensitive_items_needing_boundary_decisions",
            "reason_created": "Memory card can be useful downstream only after explicit permission decisions.",
            "input_payload": {
                "title": graph["maine_memory"].title,
                "summary": graph["maine_memory"].summary,
            },
            "required_decisions": ["privacy_level", "searchable", "usable_for_voice_context", "usable_for_sft"],
        },
        {
            "human_id": "TASK_EMAIL_VOICE_0001",
            "task_type": "email_voice_sample",
            "target_type": "segment",
            "target_id": graph["segment"].id,
            "priority": 85,
            "queue": "emails_needing_voice_review",
            "reason_created": "Real Charles email fragment may be a useful voice sample.",
            "input_payload": {
                "text": graph["segment"].text_content,
                "voice_mode_candidates": ["father_to_adam", "logistical_note"],
            },
            "required_decisions": [
                "charles_voice_presence",
                "charles_email_role",
                "context_use",
                "authenticity_value",
                "voice_density",
                "boundary_rationale",
                "usable_for_voice_context",
            ],
        },
        {
            "human_id": "TASK_GOLD_VOICE_0001",
            "task_type": "gold_voice_edit",
            "target_type": "generation",
            "target_id": voice["generation"].id,
            "priority": 100,
            "queue": "generated_responses_needing_gold_edits",
            "reason_created": "Seed model draft needs Adam gold edit and export artifact creation.",
            "input_payload": {
                "prompt_spec_id": voice["prompt"].id,
                "context_pack_id": voice["context_pack"].id,
                "generation_id": voice["generation"].id,
                "prompt": voice["prompt"].prompt_text,
                "voice_mode": "father_to_adam",
                "truth_mode": "generative_reconstruction",
                "model_draft": voice["generation"].output_text,
                "adam_gold_edit": voice["gold"].adam_gold_edit,
                "ratings": voice["gold"].ratings,
                "failure_modes": voice["gold"].failure_modes,
            },
            "required_decisions": ["adam_gold_edit", "ratings", "failure_modes", "export_flags"],
        },
    ]

    for spec in task_specs:
        add_if_missing(session, Task, "human_id", spec["human_id"], {**spec, "status": "ready"})


def seed_gallery(session: Session, assets: Dict[str, Asset], graph: Dict[str, Any]) -> None:
    gallery = add_if_missing(
        session,
        Gallery,
        "human_id",
        "GAL_FAMILY_0001",
        {
            "human_id": "GAL_FAMILY_0001",
            "title": "Family-private memory candidates",
            "description": "Seed gallery for reviewed photo candidates.",
            "scope": "family_private",
        },
    )
    add_if_missing(
        session,
        GalleryItem,
        "asset_id",
        assets["photo"].id,
        {
            "gallery_id": gallery.id,
            "asset_id": assets["photo"].id,
            "gallery_scope": "family_private",
            "title": "Maine kitchen photo",
            "display_caption": "A seeded photo placeholder awaiting Adam's context.",
            "memory_caption": "Connected to practical tenderness and post-visit quiet.",
            "image_uri": "object://display/CR_ASSET_PHOTO_0001_large.jpg",
            "thumbnail_uri": "object://thumbs/CR_ASSET_PHOTO_0001_512.jpg",
            "linked_memories": [graph["maine_memory"].id],
            "boundary_snapshot": {"family_private": True, "public_safe": False},
        },
    )


def seed() -> None:
    with Session(engine) as session:
        assets = seed_assets(session)
        graph = seed_memory_graph(session, assets)
        voice = seed_voice_records(session, graph)
        seed_tasks(session, assets, graph, voice)
        seed_gallery(session, assets, graph)
        session.commit()


def main() -> None:
    seed()
    print("Seeded CharlesOps demo data.")


if __name__ == "__main__":
    main()
