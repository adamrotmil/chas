import hashlib

from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select
from fastapi.testclient import TestClient

from app.db.session import get_session
from app.main import app
from app.routers.tasks import _attach_photo_prompt_pair_candidates
from app.models import (
    Annotation,
    Asset,
    Boundary,
    ContextPack,
    EmbeddingRecord,
    Gallery,
    GalleryItem,
    Memory,
    MemorySource,
    MetadataProfile,
    PromptSpec,
    Segment,
    Task,
    TaskDraft,
    TaskReceipt,
)


def build_client():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    app.dependency_overrides.clear()

    def override_session():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_session] = override_session
    return TestClient(app), engine


def _projection_table_counts(session: Session) -> dict[str, int]:
    models = [Annotation, Boundary, EmbeddingRecord, Gallery, GalleryItem, Memory, MemorySource, MetadataProfile, Segment]
    return {model.__name__: len(session.exec(select(model)).all()) for model in models}


def test_photo_context_creates_embedding_input_with_visual_meaning_tags_and_open_questions():
    client, engine = build_client()

    with Session(engine) as session:
        photo = Asset(
            human_id="ASSET_RALPH_AIRPLANE_PHOTO",
            asset_type="photo",
            title="Airplane in Maine",
            original_filename="airplane-maine.jpg",
            mime_type="image/jpeg",
        )
        session.add(photo)
        session.flush()
        task = Task(
            human_id="TASK_RALPH_AIRPLANE_PHOTO_CONTEXT",
            task_type="photo_context",
            target_type="asset",
            target_id=photo.id,
            queue="photo_assets_needing_context",
            input_payload={"asset_id": photo.id, "asset_title": photo.title, "asset_type": "photo"},
            required_decisions=["visual_description_correction", "invisible_context_note", "privacy_level"],
            created_by="test",
        )
        session.add(task)
        session.commit()
        task_id = task.id
        photo_id = photo.id
        photo_id = photo.id

    response = client.post(
        f"/api/tasks/{task_id}/submit",
        json={
            "decisions": {
                "visible_people": ["Adam", "Charles"],
                "place": "Maine",
                "date_or_range": "late 1980s",
                "date_confidence": "approximate",
                "event": "small airplane flight",
                "themes": ["airplane", "Maine", "fatherhood", "adventure"],
                "concrete_objects": ["small airplane", "runway", "Maine trees"],
                "visual_description_correction": "Adam and Charles near a small airplane in Maine.",
                "invisible_context_note": "This photo anchors the memory of flying in Maine together.",
                "open_questions": ["Which airfield was this?", "Who took the photograph?"],
                "memory_potential": 5,
                "privacy_sensitivity": 2,
                "gallery_eligibility": "family_private",
                "privacy_level": "family_private",
                "privacy_notes": "Family-private memory; searchable for family context.",
                "ready_for_downstream": "yes",
            }
        },
    )

    assert response.status_code == 200
    created = response.json()["creates_or_updates"]
    assert created["metadata_profile_id"]
    assert created["memory_id"]
    assert created["gallery_item_id"]
    assert created["embedding_record_id"]
    assert created["memory_embedding_record_id"]

    with Session(engine) as session:
        profile = session.get(MetadataProfile, created["metadata_profile_id"])
        boundary = session.get(Boundary, created["boundary_id"])
        memory = session.get(Memory, created["memory_id"])
        gallery_item = session.get(GalleryItem, created["gallery_item_id"])
        profile_embedding = session.get(EmbeddingRecord, created["embedding_record_id"])
        memory_embedding = session.get(EmbeddingRecord, created["memory_embedding_record_id"])

        assert profile is not None
        assert profile.target_id == photo_id
        assert profile.summary == "Adam and Charles near a small airplane in Maine."
        assert profile.adam_context_note == "This photo anchors the memory of flying in Maine together."
        assert profile.people == ["Adam", "Charles"]
        assert profile.places == ["Maine"]
        assert profile.date_label == "late 1980s"
        assert profile.date_confidence == "approximate"
        assert profile.themes == ["airplane", "Maine", "fatherhood", "adventure"]
        assert profile.concrete_objects == ["small airplane", "runway", "Maine trees"]
        assert profile.open_questions == ["Which airfield was this?", "Who took the photograph?"]
        assert profile.truth_status == "adam_memory"

        assert boundary is not None
        assert boundary.searchable is True
        assert boundary.retrievable_in_chat is True
        assert boundary.usable_for_gallery_family is True
        assert boundary.usable_for_sft is False
        assert boundary.usable_for_dpo is False

        assert memory is not None
        assert memory.truth_status == "adam_memory"
        assert memory.maturity_level == "L3_reviewed"
        assert "small airplane" in memory.summary
        assert "flying in Maine" in memory.summary

        assert gallery_item is not None
        assert gallery_item.asset_id == photo_id
        assert gallery_item.gallery_scope == "family_private"
        assert gallery_item.boundary_snapshot["privacy_level"] == "family_private"

        assert profile_embedding is not None
        assert profile_embedding.target_type == "metadata_profile"
        assert profile_embedding.status == "ready_for_embedding"
        assert profile_embedding.truth_status == "adam_memory"
        assert profile_embedding.boundary_snapshot["retrievable_in_chat"] is True
        embedding_text = profile_embedding.input_text
        for expected in [
            "summary: Adam and Charles near a small airplane in Maine.",
            "adam_context: This photo anchors the memory of flying in Maine together.",
            "people: Adam, Charles",
            "places: Maine",
            "date: late 1980s",
            "themes: airplane, Maine, fatherhood, adventure",
            "concrete_objects: small airplane, runway, Maine trees",
            "open_questions: Which airfield was this?, Who took the photograph?",
            "boundary_privacy_level: family_private",
            "boundary_retrievable_in_chat: true",
            "boundary_usable_for_voice_context: true",
            "boundary_usable_for_sft: false",
            "boundary_usable_for_dpo: false",
        ]:
            assert expected in embedding_text
        assert "Family-private memory; searchable for family context." not in embedding_text

        assert memory_embedding is not None
        assert memory_embedding.target_type == "memory"
        assert memory_embedding.boundary_snapshot["target_type"] == "asset"
        assert memory_embedding.boundary_snapshot["target_id"] == photo_id
        assert memory_embedding.metadata_json["asset_id"] == photo_id
        assert "boundary_privacy_level: family_private" in memory_embedding.input_text
        assert "boundary_usable_for_sft: false" in memory_embedding.input_text


def test_gallery_review_endpoint_defaults_to_reviewed_and_can_preview_drafts():
    client, engine = build_client()

    with Session(engine) as session:
        reviewed_photo = Asset(
            human_id="ASSET_GALLERY_REVIEWED",
            asset_type="photo",
            title="Reviewed airplane photo",
            original_filename="reviewed-airplane.jpg",
            mime_type="image/jpeg",
            processing_status="image_preview_ready",
        )
        draft_photo = Asset(
            human_id="ASSET_GALLERY_DRAFT",
            asset_type="photo",
            title="Draft flute photo",
            original_filename="draft-flute.jpg",
            mime_type="image/jpeg",
            processing_status="image_preview_ready",
        )
        session.add(reviewed_photo)
        session.add(draft_photo)
        session.flush()
        gallery = Gallery(
            human_id="GALLERY_REVIEWED_PHOTOS",
            title="Reviewed Photo Candidates",
            scope="family_private",
        )
        session.add(gallery)
        session.flush()
        reviewed_profile = MetadataProfile(
            target_type="asset",
            target_id=reviewed_photo.id,
            profile_type="photo_memory",
            metadata_status="adam_reviewed",
            title="Reviewed airplane memory",
            summary="Adam and Charles near a small airplane in Maine.",
            adam_context_note="Adam says this anchors the flying-in-Maine memory.",
            truth_status="adam_memory",
            reviewed_by="adam",
        )
        draft_profile = MetadataProfile(
            target_type="asset",
            target_id=draft_photo.id,
            profile_type="photo_memory",
            metadata_status="machine_draft_needs_adam_review",
            title="Draft flute memory",
            summary="Charles holding a Japanese flute.",
            truth_status="system_inference",
            reviewed_by="system_draft",
        )
        session.add(reviewed_profile)
        session.add(draft_profile)
        session.flush()
        review_task = Task(
            human_id="TASK_GALLERY_DRAFT_REVIEW",
            task_type="vision_draft_review",
            target_type="metadata_profile",
            target_id=draft_profile.id,
            queue="vision_drafts_needing_review",
            status="ready",
            input_payload={"asset_id": draft_photo.id, "source_photo_memory_draft": True},
            created_by="test",
        )
        session.add(review_task)
        session.add(
            GalleryItem(
                gallery_id=gallery.id,
                asset_id=reviewed_photo.id,
                gallery_scope="family_private",
                title="Reviewed airplane memory",
                display_caption="Adam and Charles near a small airplane in Maine.",
                memory_caption="Adam says this anchors the flying-in-Maine memory.",
                boundary_snapshot={
                    "privacy_level": "family_private",
                    "usable_for_gallery_family": True,
                    "usable_for_gallery_public": False,
                },
            )
        )
        session.add(
            GalleryItem(
                gallery_id=gallery.id,
                asset_id=draft_photo.id,
                gallery_scope="family_private",
                title="Draft flute memory",
                display_caption="Charles holding a Japanese flute.",
                boundary_snapshot={
                    "privacy_level": "family_private",
                    "usable_for_gallery_family": True,
                    "usable_for_gallery_public": False,
                },
            )
        )
        session.commit()
        reviewed_photo_id = reviewed_photo.id
        draft_photo_id = draft_photo.id
        review_task_id = review_task.id

    default_response = client.get("/api/gallery/reviewed-photos?scope=family_private")
    assert default_response.status_code == 200
    default_body = default_response.json()
    assert default_body["review_policy"] == "reviewed_only_by_default"
    assert default_body["item_count"] == 1
    assert default_body["hidden_draft_count"] == 1
    assert default_body["items"][0]["source_photo_id"] == reviewed_photo_id
    assert default_body["items"][0]["review_status"] == "reviewed"
    assert default_body["items"][0]["requires_adam_review"] is False
    assert default_body["items"][0]["preview_url"] == f"/api/assets/{reviewed_photo_id}/preview?variant=display"

    draft_response = client.get("/api/gallery/reviewed-photos?scope=family_private&include_drafts=true")
    assert draft_response.status_code == 200
    draft_body = draft_response.json()
    assert draft_body["item_count"] == 2
    draft_item = next(item for item in draft_body["items"] if item["source_photo_id"] == draft_photo_id)
    assert draft_item["review_status"] == "needs_review"
    assert draft_item["requires_adam_review"] is True
    assert draft_item["profile_truth_status"] == "system_inference"
    assert draft_item["review_task_id"] == review_task_id
    assert draft_item["review_task_human_id"] == "TASK_GALLERY_DRAFT_REVIEW"
    assert draft_item["review_task_queue"] == "vision_drafts_needing_review"
    assert draft_item["review_task_status"] == "ready"


def _create_photo_memory(
    client: TestClient,
    engine,
    *,
    human_id: str,
    title: str,
    description: str,
    context: str,
    place: str,
    event: str,
    themes: list[str],
    privacy_level: str = "family_private",
    retrieval_origin: dict | None = None,
) -> str:
    with Session(engine) as session:
        photo = Asset(
            human_id=human_id,
            asset_type="photo",
            title=title,
            original_filename=f"{human_id.lower()}.jpg",
            mime_type="image/jpeg",
        )
        session.add(photo)
        session.flush()
        task = Task(
            human_id=f"TASK_{human_id}",
            task_type="photo_context",
            target_type="asset",
            target_id=photo.id,
            queue="photo_assets_needing_context",
            input_payload={
                "asset_id": photo.id,
                "asset_title": photo.title,
                "asset_type": "photo",
                **({"retrieval_gap_origin": retrieval_origin} if retrieval_origin else {}),
            },
            created_by="test",
        )
        session.add(task)
        session.commit()
        task_id = task.id
        photo_id = photo.id

    response = client.post(
        f"/api/tasks/{task_id}/submit",
        json={
            "decisions": {
                "visible_people": ["Adam", "Charles"],
                "place": place,
                "date_or_range": "1980s",
                "date_confidence": "approximate",
                "event": event,
                "themes": themes,
                "visual_description_correction": description,
                "invisible_context_note": context,
                "memory_potential": 5,
                "privacy_sensitivity": 2 if privacy_level != "sealed" else 5,
                "gallery_eligibility": "family_private" if privacy_level != "sealed" else "none",
                "privacy_level": privacy_level,
                "privacy_notes": f"{privacy_level} fixture.",
                "ready_for_downstream": "yes",
            }
        },
    )
    assert response.status_code == 200
    return photo_id


def test_photo_semantic_retrieval_finds_matching_memory_and_respects_boundaries():
    client, engine = build_client()
    airplane_photo_id = _create_photo_memory(
        client,
        engine,
        human_id="ASSET_RALPH_RETRIEVAL_AIRPLANE",
        title="Airplane in Maine",
        description="Adam and Charles standing beside a small airplane in Maine.",
        context="The photograph anchors the memory of flying an airplane together in Maine.",
        place="Maine",
        event="small airplane flight",
        themes=["airplane", "Maine", "flight", "fatherhood"],
    )
    food_photo_id = _create_photo_memory(
        client,
        engine,
        human_id="ASSET_RALPH_RETRIEVAL_FOOD",
        title="Market Street breakfast",
        description="Breakfast on the white table at Market Street.",
        context="Food as care: brie, bread, coffee, and the ceremony of being together.",
        place="Portland",
        event="breakfast",
        themes=["food", "care", "Market Street", "fatherhood"],
    )
    harbor_photo_id = _create_photo_memory(
        client,
        engine,
        human_id="ASSET_RALPH_RETRIEVAL_HARBOR",
        title="Portland harbor",
        description="The harbor and water in Portland.",
        context="Portland harbor light and the feeling of home.",
        place="Portland",
        event="harbor walk",
        themes=["Portland", "harbor", "water", "home"],
    )
    _create_photo_memory(
        client,
        engine,
        human_id="ASSET_RALPH_RETRIEVAL_CHESS",
        title="Chess table",
        description="A chess position on a table.",
        context="Online chess and the ritual of making moves.",
        place="Portland",
        event="chess",
        themes=["chess", "game", "thinking"],
    )
    sealed_photo_id = _create_photo_memory(
        client,
        engine,
        human_id="ASSET_RALPH_RETRIEVAL_SEALED",
        title="Sealed airplane memory",
        description="Another airplane photograph with private context.",
        context="Sealed private airplane memory that must not be retrieved.",
        place="Maine",
        event="airplane private",
        themes=["airplane", "Maine", "sealed"],
        privacy_level="sealed",
    )

    airplane = client.get("/api/retrieval/search", params={"q": "airplane in Maine", "scope": "family_private", "limit": 3})
    assert airplane.status_code == 200
    assert airplane.json()["retrieval_strategy"] == "boundary_filtered_lexical_semantic_expansion"
    assert airplane.json()["result_dedupe_policy"] == {
        "one_result_per_source_photo": True,
        "preferred_photo_target_order": ["memory", "metadata_profile"],
    }
    airplane_results = airplane.json()["results"]
    assert airplane_results[0]["source_photo_id"] == airplane_photo_id
    assert airplane_results[0]["target_type"] == "memory"
    assert airplane_results[0]["review_policy"] == {
        "requires_adam_review": False,
        "truth_status": "adam_memory",
        "boundary_reviewed_by": "adam",
        "does_not_certify_final_memory": False,
    }
    assert len([result["source_photo_id"] for result in airplane_results]) == len(
        {result["source_photo_id"] for result in airplane_results}
    )
    assert sealed_photo_id not in [result["source_photo_id"] for result in airplane_results]
    assert "airplane" in airplane_results[0]["matched_terms"]
    assert "maine" in airplane_results[0]["matched_terms"]
    assert airplane_results[0]["boundary_snapshot"]["retrievable_in_chat"] is True

    fuzzy_airplane = client.get(
        "/api/retrieval/search",
        params={"q": "flew together up there", "scope": "family_private", "limit": 3},
    )
    assert fuzzy_airplane.status_code == 200
    fuzzy_body = fuzzy_airplane.json()
    assert "airplane" in fuzzy_body["expanded_query_terms"]
    assert fuzzy_body["results"][0]["source_photo_id"] == airplane_photo_id
    assert fuzzy_body["results"][0]["target_type"] == "memory"
    assert fuzzy_body["results"][0]["review_policy"]["requires_adam_review"] is False
    assert len([result["source_photo_id"] for result in fuzzy_body["results"]]) == len(
        {result["source_photo_id"] for result in fuzzy_body["results"]}
    )
    assert set(fuzzy_body["results"][0]["matched_terms"]).intersection({"airplane", "flight", "flying"})

    food = client.get("/api/retrieval/search", params={"q": "food as care", "scope": "family_private", "limit": 3})
    assert food.status_code == 200
    assert food.json()["results"][0]["source_photo_id"] == food_photo_id
    assert food.json()["results"][0]["target_type"] == "memory"
    assert food.json()["results"][0]["review_policy"]["requires_adam_review"] is False
    assert len([result["source_photo_id"] for result in food.json()["results"]]) == len(
        {result["source_photo_id"] for result in food.json()["results"]}
    )

    harbor = client.get("/api/retrieval/search", params={"q": "Portland harbor", "scope": "family_private", "limit": 3})
    assert harbor.status_code == 200
    assert harbor.json()["results"][0]["source_photo_id"] == harbor_photo_id
    assert harbor.json()["results"][0]["target_type"] == "memory"
    assert harbor.json()["results"][0]["review_policy"]["requires_adam_review"] is False
    assert len([result["source_photo_id"] for result in harbor.json()["results"]]) == len(
        {result["source_photo_id"] for result in harbor.json()["results"]}
    )


def test_family_private_retrieval_excludes_sensitive_privacy_even_if_flags_are_wrong():
    client, engine = build_client()
    sensitive_photo_id = _create_photo_memory(
        client,
        engine,
        human_id="ASSET_RALPH_RETRIEVAL_SENSITIVE",
        title="Sensitive airplane memory",
        description="A private-sensitive airplane photograph.",
        context="This sensitive private context should never be retrieved from family-private search.",
        place="Maine",
        event="sensitive airplane",
        themes=["airplane", "Maine", "sensitive"],
        privacy_level="private_sensitive",
    )
    with Session(engine) as session:
        boundary = session.exec(
            select(Boundary).where(Boundary.target_type == "asset").where(Boundary.target_id == sensitive_photo_id)
        ).one()
        boundary.searchable = True
        boundary.retrievable_in_chat = True
        session.add(boundary)
        records = session.exec(select(EmbeddingRecord)).all()
        for record in records:
            if (record.metadata_json or {}).get("asset_id") == sensitive_photo_id:
                snapshot = dict(record.boundary_snapshot or {})
                snapshot["privacy_level"] = "private_sensitive"
                snapshot["searchable"] = True
                snapshot["retrievable_in_chat"] = True
                snapshot["reviewed_by"] = "adam"
                record.boundary_snapshot = snapshot
                session.add(record)
        session.commit()

    response = client.get("/api/retrieval/search", params={"q": "sensitive airplane Maine", "scope": "family_private"})
    assert response.status_code == 200
    body = response.json()
    assert sensitive_photo_id not in [result["source_photo_id"] for result in body["results"]]


def test_photo_review_inventory_groups_copy_variants_and_counts_context_gap():
    client, engine = build_client()
    with Session(engine) as session:
        original = Asset(
            human_id="ASSET_INVENTORY_HONORS_ORIGINAL",
            asset_type="photo",
            title="Rotmil Honors I.jpg",
            original_filename="Rotmil Honors I.jpg",
            mime_type="image/jpeg",
            import_status="mirrored",
            processing_status="image_preview_ready",
        )
        copy = Asset(
            human_id="ASSET_INVENTORY_HONORS_COPY",
            asset_type="photo",
            title="Rotmil Honors I - Copy (2).jpg",
            original_filename="Rotmil Honors I - Copy (2).jpg",
            mime_type="image/jpeg",
            import_status="mirrored",
            processing_status="image_preview_ready",
        )
        solo = Asset(
            human_id="ASSET_INVENTORY_SOLO",
            asset_type="photo",
            title="Market Street table.jpg",
            original_filename="Market Street table.jpg",
            mime_type="image/jpeg",
            import_status="mirrored",
            processing_status="image_preview_ready",
        )
        new_context = Asset(
            human_id="ASSET_INVENTORY_NEW_CONTEXT",
            asset_type="photo",
            title="Rangeley dock.jpg",
            original_filename="Rangeley dock.jpg",
            mime_type="image/jpeg",
            import_status="mirrored",
            processing_status="image_preview_ready",
        )
        session.add_all([original, copy, solo, new_context])
        session.flush()
        session.add(
            MetadataProfile(
                target_type="asset",
                target_id=original.id,
                profile_type="photo_memory",
                metadata_status="machine_draft_needs_adam_review",
                title="Honors ceremony draft",
                summary="Draft context.",
                truth_status="system_inference",
            )
        )
        session.add(
            Boundary(
                target_type="asset",
                target_id=original.id,
                privacy_level="family_private",
            )
        )
        session.add(
            Task(
                human_id="TASK_INVENTORY_SOLO_CONTEXT",
                task_type="photo_context",
                target_type="asset",
                target_id=solo.id,
                queue="photo_assets_needing_context",
                input_payload={"asset_id": solo.id},
                created_by="test",
            )
        )
        session.commit()

    response = client.get("/api/assets/photo-review-inventory")
    assert response.status_code == 200
    body = response.json()
    assert body["inventory_type"] == "photo_review_inventory"
    assert body["photo_count"] == 4
    assert body["preview_ready_count"] == 4
    assert body["profile_count"] == 1
    assert body["machine_draft_profile_count"] == 1
    assert body["needs_context_count"] == 2
    assert body["needs_context_group_count"] == 2
    assert body["duplicate_group_count"] == 1

    duplicate = body["duplicate_groups"][0]
    assert duplicate["group_key"] == "rotmil honors i"
    assert duplicate["asset_count"] == 2
    assert duplicate["profile_count"] == 1
    assert duplicate["needs_context_count"] == 0
    assert duplicate["needs_context"] is False
    assert duplicate["machine_draft_count"] == 1
    assert [variant["is_copy_variant"] for variant in duplicate["variants"]] == [False, True]
    assert {variant["profile_status"] for variant in duplicate["variants"]} == {
        "machine_draft_needs_adam_review",
        "covered_by_group_profile",
    }
    copy_variant = next(variant for variant in duplicate["variants"] if variant["is_copy_variant"])
    assert copy_variant["covered_by_group_profile_id"]

    solo_group = next(group for group in body["groups"] if group["display_title"] == "Market Street table.jpg")
    assert solo_group["needs_context_count"] == 1
    assert solo_group["needs_context"] is True
    assert solo_group["ready_task_count"] == 1
    new_group = next(group for group in body["groups"] if group["display_title"] == "Rangeley dock.jpg")
    assert new_group["needs_context_count"] == 1
    assert new_group["needs_context"] is True
    assert new_group["ready_task_count"] == 0

    created = client.post(
        "/api/assets/photo-review-inventory/context-task",
        json={"group_key": new_group["group_key"], "use_canonical": True},
    )
    assert created.status_code == 200
    created_body = created.json()
    assert created_body["created"] is True
    assert created_body["asset_title"] == "Rangeley dock.jpg"
    assert created_body["group_key"] == "rangeley dock"
    with Session(engine) as session:
        task = session.get(Task, created_body["task_id"])
        assert task is not None
        assert task.task_type == "photo_context"
        assert task.queue == "photo_assets_needing_context"
        assert task.input_payload["source_photo_inventory"] is True
        assert task.input_payload["group_variant_count"] == 1
        assert task.input_payload["group_variants"][0]["title"] == "Rangeley dock.jpg"
        assert [question["id"] for question in task.input_payload["suggested_questions"]] == [
            "visible_facts",
            "invisible_context",
            "meaning",
            "uncertainty",
        ]
        assert "question_answers" in task.required_decisions
        assert "open_questions" in task.required_decisions

    repeat = client.post(
        "/api/assets/photo-review-inventory/context-task",
        json={"asset_id": created_body["asset_id"]},
    )
    assert repeat.status_code == 200
    assert repeat.json()["created"] is False
    assert repeat.json()["task_id"] == created_body["task_id"]
    assert repeat.json()["reason"] == "existing_ready_photo_context_task"

    duplicate_create = client.post(
        "/api/assets/photo-review-inventory/context-task",
        json={"group_key": duplicate["group_key"], "use_canonical": True},
    )
    assert duplicate_create.status_code == 409


def test_photo_context_review_pack_combines_no_claim_gaps_held_drafts_and_vector_ready_records():
    client, engine = build_client()
    with Session(engine) as session:
        context_original = Asset(
            human_id="ASSET_PACK_CONTEXT_ORIGINAL",
            asset_type="photo",
            title="Family picnic archive.jpg",
            original_filename="Family picnic archive.jpg",
            mime_type="image/jpeg",
            import_status="mirrored",
            processing_status="image_preview_ready",
        )
        context_copy = Asset(
            human_id="ASSET_PACK_CONTEXT_COPY",
            asset_type="photo",
            title="Family picnic archive - Copy (2).jpg",
            original_filename="Family picnic archive - Copy (2).jpg",
            mime_type="image/jpeg",
            import_status="mirrored",
            processing_status="image_preview_ready",
        )
        draft_photo = Asset(
            human_id="ASSET_PACK_FLUTE_DRAFT",
            asset_type="photo",
            title="Rotmil and Japanese Flute II.jpg",
            original_filename="Rotmil and Japanese Flute II.jpg",
            mime_type="image/jpeg",
            import_status="mirrored",
            processing_status="image_preview_ready",
        )
        reviewed_photo = Asset(
            human_id="ASSET_PACK_AIRPLANE_REVIEWED",
            asset_type="photo",
            title="Airplane in Maine.jpg",
            original_filename="Airplane in Maine.jpg",
            mime_type="image/jpeg",
            import_status="mirrored",
            processing_status="image_preview_ready",
        )
        session.add_all([context_original, context_copy, draft_photo, reviewed_photo])
        session.commit()
        reviewed_photo_id = reviewed_photo.id

    draft = client.post("/api/photo-memory-drafts", params={"limit": 1, "dry_run": "false"})
    assert draft.status_code == 200
    draft_body = draft.json()
    assert draft_body["created_count"] == 1
    draft_review_task_id = draft_body["review_task_ids"][0]

    context_task = client.post(
        "/api/assets/photo-review-inventory/context-task",
        json={"asset_id": reviewed_photo_id},
    )
    assert context_task.status_code == 200
    review = client.post(
        f"/api/tasks/{context_task.json()['task_id']}/submit",
        json={
            "decisions": {
                "visible_people": ["Adam", "Charles"],
                "place": "Maine",
                "date_or_range": "late 1980s",
                "date_confidence": "approximate",
                "event": "small airplane flight",
                "themes": ["airplane", "Maine", "flight"],
                "concrete_objects": ["small airplane", "runway"],
                "visual_description_correction": "Adam and Charles are beside a small airplane in Maine.",
                "invisible_context_note": "Adam confirms this photo anchors the remembered airplane outing in Maine.",
                "question_answers": {
                    "meaning": "This should be retrievable when someone asks about flying in Maine.",
                },
                "privacy_level": "family_private",
                "privacy_notes": "Reviewed for family retrieval.",
                "ready_for_downstream": "yes",
            }
        },
    )
    assert review.status_code == 200
    reviewed_embedding_id = review.json()["creates_or_updates"]["memory_embedding_record_id"]

    response = client.get("/api/assets/photo-context-review-pack", params={"scope": "family_private", "limit": 20})
    assert response.status_code == 200
    pack = response.json()

    assert pack["pack_type"] == "photo_context_review_pack"
    assert pack["review_policy"] == "reviewed_only_by_default"
    assert pack["manifest"]["photo_count"] == 4
    assert pack["manifest"]["preview_ready_count"] == 4
    assert pack["manifest"]["needs_context_group_count"] == 1
    assert pack["manifest"]["needs_context_count"] == 2
    assert pack["manifest"]["machine_draft_count"] == 1
    assert pack["manifest"]["held_for_adam_review_count"] == 1
    assert pack["manifest"]["reviewed_vector_ready_count"] == 1
    assert pack["manifest"]["vector_policy_violation_count"] == 0
    assert pack["manifest"]["gallery_preview_item_count"] >= 2
    assert pack["manifest"]["photo_context_worklist_count"] >= 2
    assert pack["manifest"]["vector_policy"] == {
        "reviewed_only_by_default": True,
        "system_inference_excluded_by_default": True,
        "model_generated_excluded_by_default": True,
        "ordinary_db_vector_storage": False,
    }

    worklists = {worklist["worklist_key"]: worklist for worklist in pack["review_worklists"]}
    assert "photo_context:no_claim_needs_context" in worklists
    assert "photo_context:machine_draft_needs_adam_review" in worklists
    no_claim_worklist = worklists["photo_context:no_claim_needs_context"]
    assert no_claim_worklist["candidate_count"] == 1
    assert no_claim_worklist["truth_status"] == "no_claim"
    assert no_claim_worklist["not_memory_claim"] is True
    assert no_claim_worklist["review_policy"] == "create_or_open_context_task_before_memory_claim"
    assert len(no_claim_worklist["review_sequence_key"]) == 64
    assert no_claim_worklist["recommended_action"]["action_type"] == "create_photo_context_task"
    assert no_claim_worklist["candidate_previews"][0]["display_title"] == "Family picnic archive.jpg"
    assert no_claim_worklist["candidate_previews"][0]["not_memory_claim"] is True
    machine_worklist = worklists["photo_context:machine_draft_needs_adam_review"]
    assert machine_worklist["candidate_count"] == 1
    assert machine_worklist["truth_status"] == "system_inference"
    assert machine_worklist["review_policy"] == "adam_review_required_before_vector_handoff"
    assert len(machine_worklist["review_sequence_key"]) == 64
    assert machine_worklist["recommended_action"]["action_type"] == "open_machine_draft_review"
    assert machine_worklist["candidate_previews"][0]["display_title"] == "Rotmil and Japanese Flute II.jpg"
    assert machine_worklist["candidate_previews"][0]["requires_adam_review"] is True

    no_claim_group = pack["needs_context_groups"][0]
    assert no_claim_group["group_key"] == "family picnic archive"
    assert no_claim_group["display_title"] == "Family picnic archive.jpg"
    assert no_claim_group["truth_status"] == "no_claim"
    assert no_claim_group["not_memory_claim"] is True
    assert no_claim_group["evidence_source"] == "title_filename_only"
    assert no_claim_group["primary_action"]["action_type"] == "create_photo_context_task"
    assert no_claim_group["primary_action"]["request"]["body"]["use_canonical"] is True
    assert no_claim_group["preview_url"].endswith("/preview?variant=display")

    held = pack["machine_drafts_held"][0]
    assert held["source_photo_title"] == "Rotmil and Japanese Flute II.jpg"
    assert held["truth_status"] == "system_inference"
    assert held["requires_adam_review"] is True
    assert held["does_not_certify_final_memory"] is True
    assert held["not_for_downstream_vector_store"] is True
    assert held["task_id"] == draft_review_task_id
    assert held["candidate_evidence"] == {
        "not_memory_claim": True,
        "evidence_source": "machine_photo_memory_draft",
        "truth_status": "system_inference",
        "requires_adam_review": True,
        "does_not_certify_final_memory": True,
    }

    ready = pack["reviewed_vector_ready"][0]
    assert ready["source_photo_id"] == reviewed_photo_id
    assert ready["embedding_record_id"] == reviewed_embedding_id
    assert ready["truth_status"] == "adam_memory"
    assert ready["metadata_source"] == "photo_memory_review"
    assert ready["boundary_snapshot"]["reviewed_by"] == "adam"
    assert ready["truth_status"] not in {"system_inference", "model_generated"}

    assert "photo_context_review_pack:" in pack["export_preview_yaml"]
    assert "review_worklists:" in pack["export_preview_yaml"]
    assert "truth_status: no_claim" in pack["export_preview_yaml"]
    assert "truth_status: system_inference" in pack["export_preview_yaml"]
    assert "truth_status: adam_memory" in pack["export_preview_yaml"]
    assert "Photo Context Review Pack" in pack["markdown"]
    assert "Review Worklists" in pack["markdown"]
    assert len(pack["content_sha256"]) == 64

    top_slice_response = client.get(
        "/api/assets/photo-context-review-pack/top-context-slice",
        params={"scope": "family_private", "limit": 2},
    )
    assert top_slice_response.status_code == 200
    top_slice = top_slice_response.json()
    assert top_slice["slice_type"] == "photo_context_top_slice"
    assert top_slice["review_policy"] == "top_photo_context_slice_no_memory_claim"
    assert top_slice["does_not_create_memory_claim"] is True
    assert top_slice["requires_adam_context"] is True
    assert top_slice["worklist_key"] == "photo_context:no_claim_needs_context"
    assert top_slice["candidate_count"] == 1
    assert top_slice["reported_candidate_count"] == 1
    assert top_slice["completion_signal"] == "needs_context_group_count_decreases_or_review_task_becomes_submit_ready"
    assert len(top_slice["content_sha256"]) == 64
    assert any("no_claim" in boundary for boundary in top_slice["safety_boundaries"])
    top_item = top_slice["items"][0]
    assert top_item["display_title"] == "Family picnic archive.jpg"
    assert top_item["truth_status"] == "no_claim"
    assert top_item["not_memory_claim"] is True
    assert top_item["preview_url"].endswith("/preview?variant=display")
    assert top_item["suggested_context_fields"] == [
        "visible_facts",
        "invisible_context",
        "meaning",
        "uncertainty",
        "privacy_level",
        "ready_for_downstream",
    ]
    assert top_item["action"]["action_type"] == "create_photo_context_task"
    assert top_item["completion_criteria"][0].startswith("Open or create")

    plan_response = client.get(
        "/api/assets/photo-context-review-pack/review-session-plan",
        params={"scope": "family_private", "limit": 2, "source_query": "airplane in Maine"},
    )
    assert plan_response.status_code == 200
    plan = plan_response.json()
    assert plan["plan_type"] == "photo_context_review_session_plan"
    assert plan["review_policy"] == "query_aware_photo_context_session_plan_no_mutation"
    assert plan["does_not_mutate_state"] is True
    assert plan["does_not_create_memory_claim"] is True
    assert plan["requires_adam_context"] is True
    assert plan["source_query"] == "airplane in Maine"
    assert plan["selected_count"] == 1
    assert plan["candidate_count"] == 1
    assert plan["completion_signal"].startswith("create_or_open_context_tasks")
    assert len(plan["content_sha256"]) == 64
    assert plan["export_preview_yaml"].startswith("photo_context_review_session_plan:")
    assert len(plan["export_preview_sha256"]) == 64
    assert plan["dry_run_action_counts"] == {"create_photo_context_task": 1}
    assert plan["field_plan"][0]["field"] == "visible_facts"
    assert plan["items"][0]["display_title"] == "Family picnic archive.jpg"
    assert plan["items"][0]["truth_status"] == "no_claim"
    assert plan["items"][0]["not_memory_claim"] is True
    assert plan["items"][0]["query_origin"] == {
        "source_query": "airplane in Maine",
        "query_is_context_prioritization_only": True,
        "not_memory_claim": True,
    }
    assert plan["items"][0]["field_plan"][1]["field"] == "invisible_context"
    assert plan["items"][0]["action"]["action_type"] == "create_photo_context_task"
    action = plan["items"][0]["action"]
    assert action["query_provenance"] == {
        "source_query": "airplane in Maine",
        "query_is_context_prioritization_only": True,
        "not_memory_claim": True,
        "candidate_match_quality": "backlog_only",
        "candidate_selection_reason": "selected_from_photo_context_review_session_plan",
    }
    assert action["session_sequence_number"] == 1
    assert action["session_selected_count"] == 1
    action_body = action["request"]["body"]
    assert action_body["source_query"] == "airplane in Maine"
    assert action_body["query_is_context_prioritization_only"] is True
    assert action_body["not_memory_claim"] is True
    assert action_body["candidate_match_quality"] == "backlog_only"
    assert action_body["candidate_selection_reason"] == "selected_from_photo_context_review_session_plan"
    assert action_body["session_sequence_number"] == 1
    assert action_body["session_selected_count"] == 1

    plan_yaml = client.get(
        "/api/assets/photo-context-review-pack/review-session-plan/yaml",
        params={"scope": "family_private", "limit": 2, "source_query": "airplane in Maine"},
    )
    assert plan_yaml.status_code == 200
    assert plan_yaml.headers["content-type"].startswith("text/yaml")
    assert plan_yaml.text == plan["export_preview_yaml"]
    assert "query_is_context_prioritization_only: true" in plan_yaml.text
    assert "action_source_query: airplane in Maine" in plan_yaml.text
    assert "candidate_match_quality: backlog_only" in plan_yaml.text
    assert "candidate_selection_reason: selected_from_photo_context_review_session_plan" in plan_yaml.text

    contract = client.get("/api/runtime-contract").json()
    assert "/api/assets/photo-context-review-pack/review-session-plan" in contract["required_response_fields"]


def test_photo_context_review_session_dry_runs_then_creates_no_claim_context_tasks():
    client, engine = build_client()
    with Session(engine) as session:
        photos = [
            Asset(
                human_id="ASSET_SESSION_CONTEXT_ALPHA",
                asset_type="photo",
                title="Alpha archive.jpg",
                original_filename="Alpha archive.jpg",
                mime_type="image/jpeg",
                import_status="mirrored",
                processing_status="image_preview_ready",
            ),
            Asset(
                human_id="ASSET_SESSION_CONTEXT_BETA",
                asset_type="photo",
                title="Beta archive.jpg",
                original_filename="Beta archive.jpg",
                mime_type="image/jpeg",
                import_status="mirrored",
                processing_status="image_preview_ready",
            ),
        ]
        session.add_all(photos)
        session.commit()

    dry_run = client.post(
        "/api/assets/photo-context-review-pack/review-session",
        params={"limit": 2, "dry_run": "true"},
    )
    assert dry_run.status_code == 200
    dry_body = dry_run.json()
    assert dry_body["session_type"] == "photo_context_review_session"
    assert dry_body["dry_run"] is True
    assert dry_body["selected_count"] == 2
    assert dry_body["created_count"] == 0
    assert dry_body["existing_count"] == 0
    assert dry_body["review_task_ids"] == []
    assert dry_body["review_policy"] == "no_claim_until_adam_context_submission"
    assert dry_body["selection_policy"] == "from_photo_context_review_session_plan"
    assert dry_body["source_query"] == "Old Orchard beach"
    assert len(dry_body["plan_content_sha256"]) == 64
    assert len(dry_body["plan_export_preview_sha256"]) == 64
    assert dry_body["selected_item_keys"] == [item["group_key"] for item in dry_body["items"]]
    assert dry_body["projected_task_delta"] == {
        "would_create_count": 2,
        "would_open_existing_count": 0,
        "mutation_count": 0,
        "dry_run_does_not_mutate": True,
    }
    assert {item["truth_status"] for item in dry_body["items"]} == {"no_claim"}
    assert {item["not_memory_claim"] for item in dry_body["items"]} == {True}
    assert {item["action_type"] for item in dry_body["items"]} == {"would_create_photo_context_task"}
    assert {item["plan_item_key"] for item in dry_body["items"]} == set(dry_body["selected_item_keys"])
    assert all(item["query_origin"]["query_is_context_prioritization_only"] is True for item in dry_body["items"])
    assert [item["review_session_origin"]["sequence_number"] for item in dry_body["items"]] == [1, 2]
    assert all(item["review_session_origin"]["selected_count"] == 2 for item in dry_body["items"])
    assert all(item["review_session_origin"]["plan_content_sha256"] == dry_body["plan_content_sha256"] for item in dry_body["items"])
    assert all(item["review_session_origin"]["not_memory_claim"] is True for item in dry_body["items"])
    assert all(item["review_session_origin"]["query_is_context_prioritization_only"] is True for item in dry_body["items"])
    assert all(item["review_session_origin"]["candidate_match_quality"] == "backlog_only" for item in dry_body["items"])
    assert all(
        item["review_session_origin"]["candidate_selection_reason"] == "selected_from_photo_context_review_session_plan"
        for item in dry_body["items"]
    )
    with Session(engine) as session:
        assert session.exec(select(Task).where(Task.task_type == "photo_context")).all() == []

    created = client.post(
        "/api/assets/photo-context-review-pack/review-session",
        params={"limit": 2, "dry_run": "false"},
    )
    assert created.status_code == 200
    created_body = created.json()
    assert created_body["dry_run"] is False
    assert created_body["selected_count"] == 2
    assert created_body["created_count"] == 2
    assert created_body["existing_count"] == 0
    assert len(created_body["review_task_ids"]) == 2
    assert created_body["selection_policy"] == "from_photo_context_review_session_plan"
    assert created_body["selected_item_keys"] == dry_body["selected_item_keys"]
    assert created_body["plan_content_sha256"] == dry_body["plan_content_sha256"]
    assert created_body["projected_task_delta"]["mutation_count"] == 2
    assert {item["action_type"] for item in created_body["items"]} == {"created_photo_context_task"}
    assert {item["truth_status"] for item in created_body["items"]} == {"no_claim"}

    repeat = client.post(
        "/api/assets/photo-context-review-pack/review-session",
        params={"limit": 2, "dry_run": "false"},
    )
    assert repeat.status_code == 200
    repeat_body = repeat.json()
    assert repeat_body["created_count"] == 0
    assert repeat_body["existing_count"] == 2
    assert set(repeat_body["review_task_ids"]) == set(created_body["review_task_ids"])
    assert repeat_body["selected_item_keys"] == dry_body["selected_item_keys"]
    assert repeat_body["projected_task_delta"]["would_open_existing_count"] == 2
    assert {item["action_type"] for item in repeat_body["items"]} == {"open_existing_photo_context_task"}

    with Session(engine) as session:
        tasks = session.exec(select(Task).where(Task.task_type == "photo_context").order_by(Task.created_at.asc())).all()
        assert len(tasks) == 2
        assert {task.queue for task in tasks} == {"photo_assets_needing_context"}
        assert all(task.input_payload["source_photo_inventory"] is True for task in tasks)
        assert [task.input_payload["review_session_origin"]["sequence_number"] for task in tasks] == [1, 2]
        assert all(task.input_payload["review_session_origin"]["selected_count"] == 2 for task in tasks)
        assert all(task.input_payload["review_session_origin"]["plan_content_sha256"] == created_body["plan_content_sha256"] for task in tasks)
        assert all(task.input_payload["review_session_origin"]["not_memory_claim"] is True for task in tasks)
        assert all(task.input_payload["review_session_origin"]["query_is_context_prioritization_only"] is True for task in tasks)
        assert all(task.input_payload["review_session_origin"]["candidate_match_quality"] == "backlog_only" for task in tasks)
        assert all(
            task.input_payload["review_session_origin"]["candidate_selection_reason"] == "selected_from_photo_context_review_session_plan"
            for task in tasks
        )
        assert all(task.input_payload["retrieval_gap_origin"]["candidate_match_quality"] == "backlog_only" for task in tasks)
        assert all(
            task.input_payload["retrieval_gap_origin"]["selection_reason"] == "selected_from_photo_context_review_session_plan"
            for task in tasks
        )
        assert all(task.status == "ready" for task in tasks)

    contract = client.get("/api/runtime-contract").json()
    assert "/api/assets/photo-context-review-pack/review-session" in contract["required_response_fields"]


def test_photo_context_submit_projection_is_non_mutating_and_matches_downstream_readiness():
    client, engine = build_client()

    with Session(engine) as session:
        photo = Asset(
            human_id="ASSET_PROJECTION_AIRPLANE_CONTEXT",
            asset_type="photo",
            title="Airplane in Maine projection.jpg",
            original_filename="Airplane in Maine projection.jpg",
            mime_type="image/jpeg",
            import_status="mirrored",
            processing_status="image_preview_ready",
        )
        session.add(photo)
        session.flush()
        task = Task(
            human_id="TASK_PROJECTION_AIRPLANE_CONTEXT",
            task_type="photo_context",
            target_type="asset",
            target_id=photo.id,
            queue="photo_assets_needing_context",
            input_payload={
                "asset_id": photo.id,
                "asset_title": photo.title,
                "asset_type": "photo",
                "suggested_questions": [
                    {
                        "id": "meaning",
                        "question": "What does this photo mean beyond what is visible?",
                        "reason": "Capture Adam memory context.",
                    }
                ],
            },
            required_decisions=["visual_description_correction", "invisible_context_note", "privacy_level"],
            created_by="test",
        )
        session.add(task)
        session.commit()
        task_id = task.id
        before_counts = _projection_table_counts(session)

    projection = client.post(
        f"/api/tasks/{task_id}/photo-context/projection",
        json={
            "decisions": {
                "visible_people": ["Adam", "Charles"],
                "place": "Maine",
                "date_or_range": "late 1980s",
                "date_confidence": "approximate",
                "event": "small airplane flight",
                "themes": ["airplane", "Maine", "fatherhood"],
                "concrete_objects": ["small airplane", "runway"],
                "visual_description_correction": "Adam and Charles are beside a small airplane in Maine.",
                "invisible_context_note": "Adam says this anchors the memory of flying in Maine together.",
                "question_answers": {"meaning": "This should be retrievable when someone asks about flying in Maine."},
                "privacy_level": "family_private",
                "privacy_notes": "Reviewed for family retrieval.",
                "ready_for_downstream": "yes",
                "gallery_eligibility": "family_private",
                "ocr_review_status": "adam_corrected",
                "ocr_truth_status": "adam_expert_reconstruction",
                "corrected_ocr_text": "Rangeley airfield",
            }
        },
    )

    assert projection.status_code == 200
    body = projection.json()
    assert body["projection_type"] == "photo_context_submit_projection"
    assert body["review_policy"] == "preview_only_non_mutating"
    assert body["supported"] is True
    assert body["does_not_mutate_state"] is True
    assert body["no_live_embedding_call"] is True
    assert body["ordinary_db_vector_storage"] is False
    assert body["metadata_profile"]["would_create"] is True
    assert body["metadata_profile"]["metadata_status_after"] == "adam_reviewed"
    assert body["metadata_profile"]["truth_status_after"] == "adam_memory"
    assert body["boundary"]["snapshot_after"]["privacy_level"] == "family_private"
    assert body["boundary"]["snapshot_after"]["retrievable_in_chat"] is True
    assert body["boundary"]["usable_for_sft"] is False
    assert body["boundary"]["usable_for_dpo"] is False
    assert body["profile_embedding"]["would_create"] is True
    assert body["profile_embedding"]["status_after"] == "ready_for_embedding"
    assert "small airplane in Maine" in body["profile_embedding"]["input_preview"]
    assert body["memory"]["would_create"] is True
    assert body["memory"]["truth_status_after"] == "adam_memory"
    assert body["memory_embedding_vector_handoff"]["would_create_embedding_record"] is True
    assert body["memory_embedding_vector_handoff"]["status"] == "eligible_reviewed_record"
    assert body["memory_embedding_vector_handoff"]["reviewed_only_by_default"] is True
    assert body["gallery"]["would_create"] is True
    assert body["gallery"]["scope_after"] == "family_private"
    assert body["ocr_segment"]["would_create"] is True
    assert body["ocr_segment"]["truth_status_after"] == "adam_expert_reconstruction"
    assert body["submit_readiness"] == "ready_to_submit"
    assert body["missing_required_fields"] == []
    assert len(body["content_sha256"]) == 64
    assert "photo_context_submit_preview:" in body["export_preview_yaml"]
    assert "metadata_profile:" in body["export_preview_yaml"]
    assert "vector_handoff_status: \"eligible_reviewed_record\"" in body["export_preview_yaml"]
    assert "ordinary_db_vector_storage: false" in body["export_preview_yaml"]
    assert {item["field_key"]: item["status"] for item in body["field_requirements"]} == {
        "visual_description_correction": "complete",
        "adam_context": "complete",
        "privacy_level": "complete",
        "ready_for_downstream": "complete",
        "ocr_review_status": "complete",
    }
    assert body["blocked_reasons"] == []

    with Session(engine) as session:
        assert _projection_table_counts(session) == before_counts


def test_photo_context_submit_receipt_carries_projection_hash_and_payload_preview():
    client, engine = build_client()

    with Session(engine) as session:
        photo = Asset(
            human_id="ASSET_PROJECTION_RECEIPT_AIRPLANE",
            asset_type="photo",
            title="Airplane receipt continuity.jpg",
            original_filename="Airplane receipt continuity.jpg",
            mime_type="image/jpeg",
            import_status="mirrored",
            processing_status="image_preview_ready",
        )
        session.add(photo)
        session.flush()
        task = Task(
            human_id="TASK_PROJECTION_RECEIPT_AIRPLANE",
            task_type="photo_context",
            target_type="asset",
            target_id=photo.id,
            queue="photo_assets_needing_context",
            input_payload={
                "asset_id": photo.id,
                "asset_title": photo.title,
                "asset_type": "photo",
                "review_session_origin": {
                    "sequence_number": 2,
                    "selected_count": 5,
                    "source_query": "airplane in Maine",
                    "plan_content_sha256": "a" * 64,
                    "completion_signal": "submit_adam_context_until_needs_context_count_decreases",
                    "review_policy": "retrieval_gap_no_claim_until_adam_context",
                    "not_memory_claim": True,
                },
            },
            required_decisions=["visual_description_correction", "invisible_context_note", "privacy_level"],
            created_by="test",
        )
        session.add(task)
        session.commit()
        task_id = task.id
        photo_id = photo.id

    decisions = {
        "visible_people": ["Adam", "Charles"],
        "place": "Maine",
        "date_or_range": "late 1980s",
        "date_confidence": "approximate",
        "event": "small airplane flight",
        "themes": ["airplane", "Maine", "fatherhood"],
        "concrete_objects": ["small airplane", "runway"],
        "visual_description_correction": "Adam and Charles stand beside a small airplane in Maine.",
        "invisible_context_note": "Adam says this should anchor the memory of flying in Maine together.",
        "question_answers": {"meaning": "This is the airplane memory Adam wants retrievable later."},
        "privacy_level": "family_private",
        "privacy_notes": "Reviewed for family retrieval.",
        "ready_for_downstream": "yes",
        "gallery_eligibility": "family_private",
        "ocr_review_status": "not_present",
    }

    projected = client.post(
        f"/api/tasks/{task_id}/photo-context/projection",
        json={"decisions": decisions},
    )
    assert projected.status_code == 200
    projected_body = projected.json()
    assert projected_body["submit_readiness"] == "ready_to_submit"

    submitted = client.post(
        f"/api/tasks/{task_id}/submit",
        json={"decisions": decisions},
    )
    assert submitted.status_code == 200
    created = submitted.json()["creates_or_updates"]
    submit_projection = created["submit_projection"]
    receipt_projection = created["receipt"]["submit_projection"]

    assert created["metadata_profile_id"]
    assert created["memory_id"]
    assert created["boundary_id"]
    assert created["memory_embedding_record_id"]
    assert created["submit_projection_content_sha256"] == projected_body["content_sha256"]
    assert submit_projection["content_sha256"] == projected_body["content_sha256"]
    assert submit_projection["export_preview_yaml"] == projected_body["export_preview_yaml"]
    assert submit_projection["submit_readiness"] == "ready_to_submit"
    assert submit_projection["vector_handoff_status"] == "eligible_reviewed_record"
    assert submit_projection["does_not_mutate_state"] is True
    assert submit_projection["no_live_embedding_call"] is True
    assert submit_projection["ordinary_db_vector_storage"] is False
    assert "photo_context_submit_preview:" in submit_projection["export_preview_yaml"]
    assert "ordinary_db_vector_storage: false" in submit_projection["export_preview_yaml"]
    assert receipt_projection["content_sha256"] == projected_body["content_sha256"]
    assert receipt_projection["export_preview_yaml"] == projected_body["export_preview_yaml"]
    assert receipt_projection["submit_readiness"] == "ready_to_submit"
    assert created["receipt"]["vector_handoff_status"] == "eligible_reviewed_record"
    assert created["receipt"]["review_session_origin"] == {
        "sequence_number": 2,
        "selected_count": 5,
        "source_query": "airplane in Maine",
        "plan_content_sha256": "a" * 64,
        "completion_signal": "submit_adam_context_until_needs_context_count_decreases",
        "review_policy": "retrieval_gap_no_claim_until_adam_context",
        "not_memory_claim": True,
    }

    with Session(engine) as session:
        receipt = session.get(TaskReceipt, created["task_receipt_id"])
        assert receipt is not None
        assert receipt.created_or_updated["submit_projection"]["content_sha256"] == projected_body["content_sha256"]
        assert receipt.summary["submit_projection"]["content_sha256"] == projected_body["content_sha256"]
        assert receipt.summary["review_session_origin"]["sequence_number"] == 2
        assert receipt.summary["submit_projection"]["export_preview_yaml"] == projected_body["export_preview_yaml"]

    dossier = client.get(f"/api/assets/{photo_id}/dossier")
    assert dossier.status_code == 200
    dossier_body = dossier.json()
    assert dossier_body["counts"]["task_receipts"] == 1
    dossier_receipt = dossier_body["task_receipts"][0]
    assert dossier_receipt["id"] == created["task_receipt_id"]
    assert dossier_receipt["summary"]["submit_projection"]["content_sha256"] == projected_body["content_sha256"]
    assert dossier_receipt["summary"]["submit_projection"]["export_preview_yaml"] == projected_body["export_preview_yaml"]


def test_photo_context_submit_projection_reports_boundary_and_context_holds_without_mutation():
    client, engine = build_client()

    with Session(engine) as session:
        photos = [
            Asset(
                human_id="ASSET_PROJECTION_SEALED",
                asset_type="photo",
                title="Sealed family photo.jpg",
                original_filename="Sealed family photo.jpg",
                mime_type="image/jpeg",
                import_status="mirrored",
                processing_status="image_preview_ready",
            ),
            Asset(
                human_id="ASSET_PROJECTION_LATER",
                asset_type="photo",
                title="Later family photo.jpg",
                original_filename="Later family photo.jpg",
                mime_type="image/jpeg",
                import_status="mirrored",
                processing_status="image_preview_ready",
            ),
            Asset(
                human_id="ASSET_PROJECTION_EMPTY",
                asset_type="photo",
                title="Empty context photo.jpg",
                original_filename="Empty context photo.jpg",
                mime_type="image/jpeg",
                import_status="mirrored",
                processing_status="image_preview_ready",
            ),
        ]
        session.add_all(photos)
        session.flush()
        tasks = []
        for index, photo in enumerate(photos, start=1):
            task = Task(
                human_id=f"TASK_PROJECTION_HOLD_{index}",
                task_type="photo_context",
                target_type="asset",
                target_id=photo.id,
                queue="photo_assets_needing_context",
                input_payload={"asset_id": photo.id, "asset_title": photo.title, "asset_type": "photo"},
                required_decisions=["visual_description_correction", "invisible_context_note", "privacy_level"],
                created_by="test",
            )
            session.add(task)
            tasks.append(task)
        session.commit()
        task_ids = [task.id for task in tasks]
        before_counts = _projection_table_counts(session)

    sealed = client.post(
        f"/api/tasks/{task_ids[0]}/photo-context/projection",
        json={
            "decisions": {
                "visual_description_correction": "A reviewed but sealed family image.",
                "invisible_context_note": "Meaningful but sensitive.",
                "privacy_level": "sealed",
                "privacy_notes": "sealed by Adam",
                "ready_for_downstream": "yes",
            }
        },
    )
    later = client.post(
        f"/api/tasks/{task_ids[1]}/photo-context/projection",
        json={
            "decisions": {
                "visual_description_correction": "A family image that needs more review.",
                "invisible_context_note": "Adam has context, but not ready yet.",
                "privacy_level": "family_private",
                "privacy_notes": "hold until reviewed again",
                "ready_for_downstream": "later",
            }
        },
    )
    empty = client.post(
        f"/api/tasks/{task_ids[2]}/photo-context/projection",
        json={
            "decisions": {
                "visual_description_correction": "",
                "invisible_context_note": "",
                "privacy_level": "family_private",
                "privacy_notes": "not enough context",
                "ready_for_downstream": "yes",
            }
        },
    )

    assert sealed.status_code == 200
    assert later.status_code == 200
    assert empty.status_code == 200
    sealed_body = sealed.json()
    later_body = later.json()
    empty_body = empty.json()

    assert sealed_body["memory_embedding_vector_handoff"]["status"] == "excluded_by_boundary"
    assert sealed_body["submit_readiness"] == "ready_to_submit_boundary_excluded"
    assert sealed_body["gallery"]["hidden_by_boundary"] is True
    assert "excluded_by_boundary" in sealed_body["blocked_reasons"]
    assert sealed_body["boundary"]["snapshot_after"]["usable_for_sft"] is False
    assert sealed_body["boundary"]["snapshot_after"]["usable_for_dpo"] is False

    assert later_body["memory"]["would_create"] is False
    assert later_body["submit_readiness"] == "ready_to_save_hold"
    assert later_body["memory_embedding_vector_handoff"]["status"] == "held_pending_downstream_clearance"
    assert later_body["gallery"]["hidden_by_boundary"] is True
    assert "not_ready_for_downstream" in later_body["blocked_reasons"]

    assert empty_body["memory"]["would_create"] is False
    assert empty_body["submit_readiness"] == "needs_required_fields"
    assert "submit_readiness: \"needs_required_fields\"" in empty_body["export_preview_yaml"]
    assert empty_body["missing_required_fields"] == ["visual_description_correction"]
    assert empty_body["memory_embedding_vector_handoff"]["status"] == "held_missing_memory_context"
    assert empty_body["gallery"]["would_create"] is True
    assert "missing_reviewed_memory_text" in empty_body["blocked_reasons"]

    with Session(engine) as session:
        assert _projection_table_counts(session) == before_counts


def test_photo_context_session_progress_summarizes_drafts_and_projection_blockers_without_mutation():
    client, engine = build_client()

    with Session(engine) as session:
        photos = [
            Asset(
                human_id="ASSET_PROGRESS_READY",
                asset_type="photo",
                title="Progress ready photo.jpg",
                original_filename="Progress ready photo.jpg",
                mime_type="image/jpeg",
                import_status="mirrored",
                processing_status="image_preview_ready",
            ),
            Asset(
                human_id="ASSET_PROGRESS_HELD",
                asset_type="photo",
                title="Progress held photo.jpg",
                original_filename="Progress held photo.jpg",
                mime_type="image/jpeg",
                import_status="mirrored",
                processing_status="image_preview_ready",
            ),
            Asset(
                human_id="ASSET_PROGRESS_NO_DRAFT",
                asset_type="photo",
                title="Progress no draft photo.jpg",
                original_filename="Progress no draft photo.jpg",
                mime_type="image/jpeg",
                import_status="mirrored",
                processing_status="image_preview_ready",
            ),
        ]
        session.add_all(photos)
        session.flush()
        tasks = []
        for index, photo in enumerate(photos, start=1):
            task = Task(
                human_id=f"TASK_PROGRESS_CONTEXT_{index}",
                task_type="photo_context",
                target_type="asset",
                target_id=photo.id,
                queue="photo_assets_needing_context",
                input_payload={"asset_id": photo.id, "asset_title": photo.title, "asset_type": "photo"},
                required_decisions=["visual_description_correction", "invisible_context_note", "privacy_level"],
                created_by="test",
            )
            session.add(task)
            tasks.append(task)
        session.flush()
        session.add(
            TaskDraft(
                task_id=tasks[0].id,
                user_id="adam",
                decisions={
                    "visual_description_correction": "Adam and Charles are beside a small airplane in Maine.",
                    "invisible_context_note": "Adam says this anchors the flying in Maine memory.",
                    "privacy_level": "family_private",
                    "privacy_notes": "Family retrieval is fine.",
                    "ready_for_downstream": "yes",
                    "gallery_eligibility": "family_private",
                },
            )
        )
        session.add(
            TaskDraft(
                task_id=tasks[1].id,
                user_id="adam",
                decisions={
                    "visual_description_correction": "A family photo that needs another pass.",
                    "invisible_context_note": "Adam is not ready to release this one yet.",
                    "privacy_level": "family_private",
                    "privacy_notes": "Hold until reviewed again.",
                    "ready_for_downstream": "later",
                    "gallery_eligibility": "family_private",
                },
            )
        )
        session.commit()
        before_counts = _projection_table_counts(session)

    progress = client.get(
        "/api/assets/photo-context-review-pack/session-progress",
        params={"scope": "family_private", "limit": 10},
    )

    assert progress.status_code == 200
    body = progress.json()
    assert body["progress_type"] == "photo_context_session_progress"
    assert body["review_policy"] == "drafts_projected_without_mutation"
    assert body["does_not_mutate_state"] is True
    assert body["does_not_create_memory_claim"] is True
    assert body["does_not_create_embedding_record"] is True
    assert body["requires_adam_context"] is True
    assert body["completion_signal"] == "submit_ready_count_increases_or_retrieval_gap_missing_fields_decrease"
    assert len(body["content_sha256"]) == 64
    assert any("not a memory claim" in boundary for boundary in body["safety_boundaries"])
    assert any("No embedding record" in boundary for boundary in body["safety_boundaries"])
    assert body["total_context_task_count"] == 3
    assert body["reported_task_count"] == 3
    assert body["draft_count"] == 2
    assert body["no_draft_count"] == 1
    assert body["submit_ready_count"] == 1
    assert body["blocked_count"] == 1
    assert body["status_counts"] == {
        "submit_ready": 1,
        "held_pending_downstream_clearance": 1,
        "needs_draft": 1,
    }
    assert body["blocked_reason_counts"] == {
        "held_pending_downstream_clearance": 1,
        "not_ready_for_downstream": 1,
    }

    by_title = {item["source_photo_title"]: item for item in body["items"]}
    ready_item = by_title["Progress ready photo.jpg"]
    held_item = by_title["Progress held photo.jpg"]
    no_draft_item = by_title["Progress no draft photo.jpg"]
    assert ready_item["has_draft"] is True
    assert ready_item["progress_status"] == "submit_ready"
    assert ready_item["vector_handoff_status"] == "eligible_reviewed_record"
    assert ready_item["next_action"] == "submit_review"
    assert ready_item["projection"]["does_not_mutate_state"] is True
    assert held_item["has_draft"] is True
    assert held_item["progress_status"] == "held_pending_downstream_clearance"
    assert held_item["blocked_reasons"] == ["held_pending_downstream_clearance", "not_ready_for_downstream"]
    assert no_draft_item["has_draft"] is False
    assert no_draft_item["progress_status"] == "needs_draft"
    assert no_draft_item["projection"] is None

    with Session(engine) as session:
        assert _projection_table_counts(session) == before_counts

    contract = client.get("/api/runtime-contract").json()
    assert "/api/assets/photo-context-review-pack/session-progress" in contract["required_response_fields"]
    required_fields = contract["required_response_fields"]["/api/assets/photo-context-review-pack/session-progress"]
    assert "does_not_create_memory_claim" in required_fields
    assert "does_not_create_embedding_record" in required_fields
    assert "review_session_task_count" in required_fields
    assert "provenance_policy" in required_fields
    assert "content_sha256" in required_fields


def test_photo_context_session_progress_summarizes_retrieval_gap_missing_fields():
    client, engine = build_client()

    review_plan = {
        "query": "airplane in Maine",
        "review_policy": "retrieval_gap_no_claim_until_adam_context",
        "not_memory_claim": True,
        "completion_signal": "visual_facts_memory_context_uncertainty_boundary",
        "required_fields": [
            {"field_key": "visual_description_correction", "label": "Visible facts"},
            {"field_key": "invisible_context_note", "label": "Adam context"},
            {"field_key": "open_questions", "label": "Uncertainty"},
            {"field_key": "privacy_level", "label": "Boundary"},
        ],
    }
    review_session_origin = {
        "session_type": "photo_context_review_session",
        "sequence_number": 1,
        "selected_count": 2,
        "source_query": "airplane in Maine",
        "plan_content_sha256": "a" * 64,
        "completion_signal": "create_or_open_context_tasks_then_submit_adam_context_until_needs_context_count_decreases",
        "review_policy": "query_aware_photo_context_session_plan_no_mutation",
        "not_memory_claim": True,
        "query_is_context_prioritization_only": True,
        "candidate_match_quality": "backlog_only",
        "candidate_selection_reason": "selected_from_photo_context_review_session_plan",
    }

    with Session(engine) as session:
        photos = [
            Asset(
                human_id="ASSET_RETRIEVAL_PROGRESS_DRAFT",
                asset_type="photo",
                title="Retrieval progress draft.jpg",
                original_filename="Retrieval progress draft.jpg",
                mime_type="image/jpeg",
                import_status="mirrored",
                processing_status="image_preview_ready",
            ),
            Asset(
                human_id="ASSET_RETRIEVAL_PROGRESS_NO_DRAFT",
                asset_type="photo",
                title="Retrieval progress no draft.jpg",
                original_filename="Retrieval progress no draft.jpg",
                mime_type="image/jpeg",
                import_status="mirrored",
                processing_status="image_preview_ready",
            ),
        ]
        session.add_all(photos)
        session.flush()
        tasks = []
        for index, photo in enumerate(photos, start=1):
            task = Task(
                human_id=f"TASK_RETRIEVAL_PROGRESS_{index}",
                task_type="photo_context",
                target_type="asset",
                target_id=photo.id,
                queue="photo_assets_needing_context",
                input_payload={
                    "asset_id": photo.id,
                    "asset_title": photo.title,
                    "asset_type": "photo",
                    "retrieval_gap_origin": {
                        "query": "airplane in Maine",
                        "candidate_match_quality": "backlog_only",
                        "selection_reason": "backlog_sample_no_semantic_match",
                        "truth_status": "no_claim",
                        "not_memory_claim": True,
                    },
                    "retrieval_gap_review": review_plan,
                    "review_session_origin": {**review_session_origin, "sequence_number": index},
                },
                required_decisions=["visual_description_correction", "question_answers", "privacy_level"],
                created_by="test",
            )
            session.add(task)
            tasks.append(task)
        session.flush()
        session.add(
            TaskDraft(
                task_id=tasks[0].id,
                user_id="adam",
                decisions={
                    "visual_description_correction": "Adam and Charles are beside a small airplane in Maine.",
                    "invisible_context_note": "Adam says this anchors the flying in Maine memory.",
                    "question_answers": {
                        "visible_facts": "The image shows a small airplane.",
                    },
                    "privacy_level": "family_private",
                    "ready_for_downstream": "yes",
                    "gallery_eligibility": "family_private",
                    "ocr_review_status": "not_present",
                },
            )
        )
        session.commit()

    progress = client.get(
        "/api/assets/photo-context-review-pack/session-progress",
        params={"scope": "family_private", "limit": 10},
    )

    assert progress.status_code == 200
    body = progress.json()
    assert body["does_not_create_memory_claim"] is True
    assert body["does_not_create_embedding_record"] is True
    assert body["completion_signal"] == "submit_ready_count_increases_or_retrieval_gap_missing_fields_decrease"
    assert len(body["content_sha256"]) == 64
    assert body["retrieval_gap_task_count"] == 2
    assert body["review_session_task_count"] == 2
    assert body["provenance_policy"] == {
        "retrieval_gap_origin_is_not_memory_claim": True,
        "review_session_origin_is_not_memory_claim": True,
        "query_is_context_prioritization_only": True,
        "vector_ready_requires_submit": True,
    }
    assert body["retrieval_gap_missing_field_counts"] == {
        "visual_description_correction": 1,
        "invisible_context_note": 1,
        "open_questions": 1,
        "privacy_level": 1,
    }
    by_title = {item["source_photo_title"]: item for item in body["items"]}
    draft_item = by_title["Retrieval progress draft.jpg"]
    no_draft_item = by_title["Retrieval progress no draft.jpg"]
    assert draft_item["retrieval_gap_origin"]["query"] == "airplane in Maine"
    assert draft_item["retrieval_gap_origin"]["truth_status"] == "no_claim"
    assert draft_item["retrieval_gap_origin"]["not_memory_claim"] is True
    assert draft_item["review_session_origin"]["source_query"] == "airplane in Maine"
    assert draft_item["review_session_origin"]["not_memory_claim"] is True
    assert draft_item["review_session_origin"]["query_is_context_prioritization_only"] is True
    assert draft_item["review_session_origin"]["candidate_match_quality"] == "backlog_only"
    assert draft_item["review_session_origin"]["candidate_selection_reason"] == "selected_from_photo_context_review_session_plan"
    assert draft_item["provenance_boundary"] == {
        "retrieval_origin_truth_status": "no_claim",
        "retrieval_origin_not_memory_claim": True,
        "review_session_origin_not_memory_claim": True,
        "query_is_context_prioritization_only": True,
        "vector_ready_requires_submit": True,
    }
    assert draft_item["retrieval_gap_review_policy"] == "retrieval_gap_no_claim_until_adam_context"
    assert draft_item["retrieval_gap_completion_signal"] == "visual_facts_memory_context_uncertainty_boundary"
    assert draft_item["retrieval_gap_missing_fields"] == []
    assert no_draft_item["retrieval_gap_missing_fields"] == [
        "visual_description_correction",
        "invisible_context_note",
        "open_questions",
        "privacy_level",
    ]

    artifact_response = client.get(
        "/api/assets/photo-context-review-pack/session-progress/artifact",
        params={"scope": "family_private", "limit": 10},
    )
    assert artifact_response.status_code == 200
    artifact = artifact_response.json()
    assert artifact["artifact_type"] == "photo_context_session_progress_artifact"
    assert artifact["source_progress_content_sha256"] == body["content_sha256"]
    assert artifact["does_not_create_memory_claim"] is True
    assert artifact["does_not_create_embedding_record"] is True
    assert artifact["review_session_task_count"] == 2
    assert artifact["provenance_policy"] == body["provenance_policy"]
    artifact_by_title = {item["source_photo_title"]: item for item in artifact["items"]}
    assert artifact_by_title["Retrieval progress draft.jpg"]["retrieval_gap_origin"] == draft_item["retrieval_gap_origin"]
    assert artifact_by_title["Retrieval progress draft.jpg"]["review_session_origin"] == draft_item["review_session_origin"]
    assert artifact_by_title["Retrieval progress draft.jpg"]["provenance_boundary"] == draft_item["provenance_boundary"]

    worklist_response = client.get(
        "/api/assets/photo-context-review-pack/retrieval-gap-field-worklist",
        params={"scope": "family_private", "limit": 10},
    )
    assert worklist_response.status_code == 200
    worklist = worklist_response.json()
    assert worklist["worklist_type"] == "photo_context_retrieval_gap_field_worklist"
    assert worklist["review_policy"] == "retrieval_gap_missing_fields_no_memory_claim_until_adam_context"
    assert worklist["does_not_mutate_state"] is True
    assert worklist["does_not_create_memory_claim"] is True
    assert worklist["requires_adam_context"] is True
    assert worklist["no_live_embedding_call"] is True
    assert worklist["retrieval_gap_task_count"] == 2
    assert worklist["reported_item_count"] == 1
    assert len(worklist["content_sha256"]) == 64
    assert len(worklist["export_preview_sha256"]) == 64
    assert hashlib.sha256(worklist["export_preview_yaml"].encode("utf-8")).hexdigest() == worklist["export_preview_sha256"]
    assert worklist["missing_field_counts"][0] == {"field_key": "invisible_context_note", "count": 1}
    guidance = {item["field_key"]: item for item in worklist["field_guidance"]}
    assert set(guidance) == {
        "visual_description_correction",
        "invisible_context_note",
        "open_questions",
        "privacy_level",
    }
    assert guidance["invisible_context_note"]["unlocks"] == (
        "Embedding text that can support memory-like retrieval after Adam review."
    )
    assert worklist["query_counts"] == [{"query": "airplane in Maine", "count": 1}]
    assert worklist["items"][0]["missing_field_count"] == 4
    assert worklist["items"][0]["truth_status"] == "no_claim"
    assert worklist["items"][0]["not_memory_claim"] is True
    assert worklist["items"][0]["completion_signal"] == "visual_facts_memory_context_uncertainty_boundary"
    assert "photo_context_retrieval_gap_field_worklist:" in worklist["export_preview_yaml"]
    assert "field_guidance:" in worklist["export_preview_yaml"]
    assert "retrieval_query_relevance" not in worklist["export_preview_yaml"]
    assert "backlog-only review seeds are not memory questions" not in worklist["export_preview_yaml"]

    worklist_yaml = client.get(
        "/api/assets/photo-context-review-pack/retrieval-gap-field-worklist/yaml",
        params={"scope": "family_private", "limit": 10},
    )
    assert worklist_yaml.status_code == 200
    assert worklist_yaml.headers["content-type"].startswith("text/yaml")
    assert worklist_yaml.text == worklist["export_preview_yaml"]

    payoff = client.get(
        "/api/assets/photo-context-review-pack/retrieval-gap-payoff-preview",
        params={"scope": "family_private", "limit": 10},
    )
    assert payoff.status_code == 200
    payoff_body = payoff.json()
    assert payoff_body["preview_type"] == "photo_context_retrieval_gap_payoff_preview"
    assert payoff_body["review_policy"] == "read_only_payoff_preview_no_generated_memory_claims"
    assert payoff_body["does_not_mutate_state"] is True
    assert payoff_body["does_not_create_memory_claim"] is True
    assert payoff_body["uses_placeholders_for_missing_adam_context"] is True
    assert payoff_body["requires_adam_context"] is True
    assert payoff_body["source_worklist_content_sha256"] == worklist["content_sha256"]
    assert len(payoff_body["content_sha256"]) == 64
    assert hashlib.sha256(payoff_body["export_preview_yaml"].encode("utf-8")).hexdigest() == payoff_body["export_preview_sha256"]
    assert payoff_body["items"][0]["truth_status_before_completion"] == "no_claim"
    assert payoff_body["items"][0]["does_not_create_memory_claim"] is True
    assert "reviewed_only_vector_handoff_record" in payoff_body["items"][0]["unlocked_records"]
    assert "[requires Adam:" in payoff_body["items"][0]["vector_text_template"]
    assert "photo_context_retrieval_gap_payoff_preview:" in payoff_body["export_preview_yaml"]

    payoff_yaml = client.get(
        "/api/assets/photo-context-review-pack/retrieval-gap-payoff-preview/yaml",
        params={"scope": "family_private", "limit": 10},
    )
    assert payoff_yaml.status_code == 200
    assert payoff_yaml.headers["content-type"].startswith("text/yaml")
    assert payoff_yaml.text == payoff_body["export_preview_yaml"]


def test_photo_context_task_created_from_retrieval_gap_preserves_query_origin():
    client, engine = build_client()

    with Session(engine) as session:
        photo = Asset(
            human_id="ASSET_RETRIEVAL_ORIGIN_CONTEXT",
            asset_type="photo",
            title="Rangeley airplane dock.jpg",
            original_filename="Rangeley airplane dock.jpg",
            mime_type="image/jpeg",
            import_status="mirrored",
            processing_status="image_preview_ready",
        )
        session.add(photo)
        session.commit()
        photo_id = photo.id

    created = client.post(
        "/api/assets/photo-review-inventory/context-task",
        json={
            "asset_id": photo_id,
            "source_query": "airplane in Maine",
            "candidate_match_quality": "weak_evidence_match",
            "candidate_selection_reason": "reviewable_evidence_overlap",
        },
    )
    assert created.status_code == 200
    body = created.json()
    assert body["created"] is True

    with Session(engine) as session:
        task = session.get(Task, body["task_id"])
        assert task is not None
        assert task.task_type == "photo_context"
        assert task.input_payload["retrieval_gap_origin"] == {
            "query": "airplane in Maine",
            "candidate_match_quality": "weak_evidence_match",
            "selection_reason": "reviewable_evidence_overlap",
            "truth_status": "no_claim",
            "not_memory_claim": True,
        }
        assert task.input_payload["retrieval_gap_review"]["review_policy"] == "retrieval_gap_no_claim_until_adam_context"
        assert task.input_payload["retrieval_gap_review"]["not_memory_claim"] is True
        assert task.input_payload["retrieval_gap_review"]["completion_signal"] == (
            "visual_facts_query_relevance_adam_context_uncertainty_boundary"
        )
        assert [field["field_key"] for field in task.input_payload["retrieval_gap_review"]["required_fields"]] == [
            "visual_description_correction",
            "retrieval_query_relevance",
            "invisible_context_note",
            "open_questions",
            "privacy_level",
        ]
        assert [question["id"] for question in task.input_payload["suggested_questions"]] == [
            "visible_facts",
            "invisible_context",
            "retrieval_query_relevance",
            "meaning",
            "uncertainty",
        ]
        assert task.input_payload["source_photo_inventory"] is True
        assert task.input_payload["canonical_asset_id"] == photo_id

    projection_before_answer = client.post(
        f"/api/tasks/{body['task_id']}/photo-context/projection",
        json={
            "decisions": {
                "visual_description_correction": "A small airplane is visible near a lake in Maine.",
                "invisible_context_note": "Adam confirms this should be reviewed as an uncertain Maine airplane scene.",
                "question_answers": {
                    "visible_facts": "A small airplane appears in the photo.",
                },
                "open_questions": ["Was this Rangeley?"],
                "privacy_level": "family_private",
                "ready_for_downstream": "yes",
            }
        },
    )
    assert projection_before_answer.status_code == 200
    relevance_requirement = next(
        item for item in projection_before_answer.json()["field_requirements"]
        if item["field_key"] == "retrieval_query_relevance"
    )
    assert relevance_requirement["status"] == "missing"
    assert relevance_requirement["required_for_submit"] is False
    assert "workflow provenance only" in relevance_requirement["reason"]

    projection_after_answer = client.post(
        f"/api/tasks/{body['task_id']}/photo-context/projection",
        json={
            "decisions": {
                "visual_description_correction": "A small airplane is visible near a lake in Maine.",
                "invisible_context_note": "Adam confirms this should be reviewed as an uncertain Maine airplane scene.",
                "question_answers": {
                    "visible_facts": "A small airplane appears in the photo.",
                    "retrieval_query_relevance": "This is probably connected to the airplane-in-Maine memory, but the airport is uncertain.",
                },
                "open_questions": ["Was this Rangeley?"],
                "privacy_level": "family_private",
                "ready_for_downstream": "yes",
            }
        },
    )
    assert projection_after_answer.status_code == 200
    relevance_requirement = next(
        item for item in projection_after_answer.json()["field_requirements"]
        if item["field_key"] == "retrieval_query_relevance"
    )
    assert relevance_requirement["status"] == "complete"

    submitted = client.post(
        f"/api/tasks/{body['task_id']}/submit",
        json={
            "decisions": {
                "visual_description_correction": "A small airplane is visible near a lake in Maine.",
                "invisible_context_note": "Adam confirms this should be reviewed as an uncertain Maine airplane scene.",
                "question_answers": {
                    "visible_facts": "A small airplane appears in the photo.",
                    "retrieval_query_relevance": "This is probably connected to the airplane-in-Maine memory, but the airport is uncertain.",
                    "uncertainty": "The exact location is still uncertain.",
                },
                "open_questions": ["Was this Rangeley?"],
                "privacy_level": "family_private",
                "ready_for_downstream": "yes",
            }
        },
    )
    assert submitted.status_code == 200
    created_records = submitted.json()["creates_or_updates"]
    receipt = submitted.json()["creates_or_updates"]["receipt"]
    assert receipt["retrieval_origin"] == {
        "query": "airplane in Maine",
        "candidate_match_quality": "weak_evidence_match",
        "selection_reason": "reviewable_evidence_overlap",
        "truth_status": "no_claim",
        "not_memory_claim": True,
    }

    with Session(engine) as session:
        receipt_record = session.get(TaskReceipt, created_records["task_receipt_id"])
        assert receipt_record is not None
        assert receipt_record.summary["retrieval_origin"]["query"] == "airplane in Maine"
        profile = session.get(MetadataProfile, created_records["metadata_profile_id"])
        assert profile is not None
        assert profile.raw_profile["retrieval_gap_origin"]["not_memory_claim"] is True
        assert profile.quality_signals["retrieval_origin_query"] == "airplane in Maine"
        assert "Retrieval origin query: airplane in Maine" in (profile.retrieval_notes or "")
        profile_embedding = session.get(EmbeddingRecord, created_records["embedding_record_id"])
        assert profile_embedding is not None
        assert "Retrieval origin query: airplane in Maine" in profile_embedding.input_text
        assert profile_embedding.metadata_json["retrieval_gap_origin"]["not_memory_claim"] is True
        memory_embedding = session.get(EmbeddingRecord, created_records["memory_embedding_record_id"])
        assert memory_embedding is not None
        assert "Retrieval origin query: airplane in Maine" in memory_embedding.input_text
        assert memory_embedding.metadata_json["retrieval_gap_origin"]["truth_status"] == "no_claim"


def test_existing_photo_context_task_opened_from_retrieval_gap_backfills_review_plan():
    client, engine = build_client()

    with Session(engine) as session:
        photo = Asset(
            human_id="ASSET_RALPH_EXISTING_RETRIEVAL_TASK",
            asset_type="photo",
            title="Old context task photo.jpg",
            original_filename="Old context task photo.jpg",
            mime_type="image/jpeg",
            processing_status="image_preview_ready",
        )
        session.add(photo)
        session.commit()
        photo_id = photo.id
        old_task = Task(
            human_id="TASK_OLD_PHOTO_CONTEXT_WITHOUT_QUERY_PLAN",
            task_type="photo_context",
            target_type="asset",
            target_id=photo_id,
            priority=80,
            status="ready",
            queue="photo_assets_needing_context",
            reason_created="Older context task created before retrieval-gap field plan existed.",
            input_payload={
                "asset_id": photo_id,
                "asset_title": "Old context task photo.jpg",
                "asset_type": "photo",
                "photo_group_key": "old context task photo",
                "suggested_questions": [
                    {
                        "id": "visible_facts",
                        "question": "What is visibly present in the photograph?",
                        "reason": "Keeps visual description separate from memory or inference.",
                    }
                ],
                "source_photo_inventory": True,
            },
            required_decisions=["visual_description_correction", "question_answers", "privacy_level"],
        )
        session.add(old_task)
        session.commit()
        old_task_id = old_task.id

    response = client.post(
        "/api/assets/photo-review-inventory/context-task",
        json={
            "asset_id": photo_id,
            "source_query": "airplane in Maine",
            "candidate_match_quality": "backlog_only",
            "candidate_selection_reason": "backlog_sample_no_semantic_match",
        },
    )
    assert response.status_code == 200
    assert response.json()["created"] is False
    assert response.json()["task_id"] == old_task_id

    with Session(engine) as session:
        task = session.get(Task, old_task_id)
        assert task is not None
        assert task.input_payload["retrieval_gap_origin"] == {
            "query": "airplane in Maine",
            "candidate_match_quality": "backlog_only",
            "selection_reason": "backlog_sample_no_semantic_match",
            "truth_status": "no_claim",
            "not_memory_claim": True,
        }
        assert [field["field_key"] for field in task.input_payload["retrieval_gap_review"]["required_fields"]] == [
            "visual_description_correction",
            "invisible_context_note",
            "open_questions",
            "privacy_level",
        ]
        assert not any(
            question["id"] == "retrieval_query_relevance"
            for question in task.input_payload["suggested_questions"]
        )


def test_existing_backlog_photo_context_task_refreshes_stale_review_seed():
    client, engine = build_client()

    with Session(engine) as session:
        photo = Asset(
            human_id="ASSET_RALPH_STALE_REVIEW_SEED",
            asset_type="photo",
            title="Old Orchard archive photo.jpg",
            original_filename="Old Orchard archive photo.jpg",
            mime_type="image/jpeg",
            processing_status="image_preview_ready",
        )
        session.add(photo)
        session.commit()
        photo_id = photo.id
        old_task = Task(
            human_id="TASK_STALE_BACKLOG_REVIEW_SEED",
            task_type="photo_context",
            target_type="asset",
            target_id=photo_id,
            priority=80,
            status="ready",
            queue="photo_assets_needing_context",
            reason_created="Older context task created from a generic backlog seed.",
            input_payload={
                "asset_id": photo_id,
                "asset_title": "Old Orchard archive photo.jpg",
                "asset_type": "photo",
                "photo_group_key": "old orchard archive photo",
                "retrieval_gap_origin": {
                    "query": "airplane in Maine",
                    "candidate_match_quality": "backlog_only",
                    "selection_reason": "backlog_sample_no_semantic_match",
                    "truth_status": "no_claim",
                    "not_memory_claim": True,
                },
                "retrieval_gap_review": {
                    "query": "airplane in Maine",
                    "review_policy": "retrieval_gap_no_claim_until_adam_context",
                    "not_memory_claim": True,
                    "completion_signal": "visual_facts_memory_context_uncertainty_boundary",
                    "required_fields": [{"field_key": "visual_description_correction", "label": "Visible facts"}],
                },
                "source_photo_inventory": True,
            },
            required_decisions=["visual_description_correction", "question_answers", "privacy_level"],
        )
        session.add(old_task)
        session.commit()
        old_task_id = old_task.id

    response = client.post(
        "/api/assets/photo-review-inventory/context-task",
        json={
            "asset_id": photo_id,
            "source_query": "Old Orchard beach",
            "candidate_match_quality": "backlog_only",
            "candidate_selection_reason": "selected_from_photo_context_review_session_plan",
        },
    )
    assert response.status_code == 200
    assert response.json()["created"] is False
    assert response.json()["task_id"] == old_task_id

    with Session(engine) as session:
        task = session.get(Task, old_task_id)
        assert task is not None
        assert task.input_payload["retrieval_gap_origin"] == {
            "query": "Old Orchard beach",
            "candidate_match_quality": "backlog_only",
            "selection_reason": "selected_from_photo_context_review_session_plan",
            "truth_status": "no_claim",
            "not_memory_claim": True,
        }
        assert task.input_payload["retrieval_gap_review"]["query"] == "Old Orchard beach"
        assert task.input_payload["retrieval_gap_review"]["completion_signal"] == "visual_facts_memory_context_uncertainty_boundary"


def test_photo_retrieval_gap_is_actionable_without_inventing_memory():
    client, engine = build_client()

    with Session(engine) as session:
        photo = Asset(
            human_id="ASSET_RETRIEVAL_GAP_AIRPLANE",
            asset_type="photo",
            title="Airplane contact sheet.jpg",
            original_filename="Airplane contact sheet.jpg",
            mime_type="image/jpeg",
            import_status="mirrored",
            processing_status="image_preview_ready",
        )
        covered_original = Asset(
            human_id="ASSET_RETRIEVAL_GAP_COVERED_ORIGINAL",
            asset_type="photo",
            title="Covered harbor photo.jpg",
            original_filename="Covered harbor photo.jpg",
            mime_type="image/jpeg",
            import_status="mirrored",
            processing_status="image_preview_ready",
        )
        covered_copy = Asset(
            human_id="ASSET_RETRIEVAL_GAP_COVERED_COPY",
            asset_type="photo",
            title="Covered harbor photo - Copy.jpg",
            original_filename="Covered harbor photo - Copy.jpg",
            mime_type="image/jpeg",
            import_status="mirrored",
            processing_status="image_preview_ready",
        )
        session.add(photo)
        session.add(covered_original)
        session.add(covered_copy)
        session.flush()
        session.add(
            MetadataProfile(
                target_type="asset",
                target_id=covered_original.id,
                profile_type="photo_memory",
                metadata_status="adam_reviewed",
                title="Already reviewed covered group",
                summary="This group already has a reviewed photo-memory profile.",
                truth_status="adam_memory",
            )
        )
        session.commit()
        photo_id = photo.id

    response = client.get("/api/retrieval/search", params={"q": "airplane in Maine", "scope": "family_private", "limit": 3})
    assert response.status_code == 200
    body = response.json()
    assert body["results"] == []
    assert body["retrieval_gap"]["status"] == "no_boundary_cleared_memory_result"
    assert body["retrieval_gap"]["truth_status"] == "no_claim"
    assert body["retrieval_gap"]["workflow"] == "photo_context_review"
    assert body["retrieval_gap"]["next_queue"] == "photo_assets_needing_context"
    assert body["retrieval_gap"]["next_queues"] == ["photo_assets_needing_context", "vision_drafts_needing_review"]
    assert body["retrieval_gap"]["candidate_group_selection_policy"] == "reviewable_evidence_overlap_then_backlog_sample"
    assert body["retrieval_gap"]["sample_groups_are_not_memory_claims"] is True
    assert body["retrieval_gap"]["photo_groups_needing_context_count"] == 1
    assert body["retrieval_gap"]["photo_assets_needing_context_count"] == 1
    assert body["retrieval_gap"]["candidate_photo_group_count"] == 1
    assert body["retrieval_gap"]["weak_evidence_candidate_count"] == 1
    assert body["retrieval_gap"]["backlog_only_candidate_count"] == 0
    assert body["retrieval_gap"]["sample_context_groups"][0]["canonical_asset_id"] == photo_id
    assert body["retrieval_gap"]["sample_context_groups"][0]["candidate_status"] == "needs_photo_context"
    assert body["retrieval_gap"]["sample_context_groups"][0]["candidate_queue"] == "photo_assets_needing_context"
    assert body["retrieval_gap"]["sample_context_groups"][0]["candidate_media_kind"] == "photograph_like"
    assert body["retrieval_gap"]["sample_context_groups"][0]["matched_query_terms"] == ["airplane"]
    assert body["retrieval_gap"]["sample_context_groups"][0]["candidate_match_quality"] == "weak_evidence_match"
    assert body["retrieval_gap"]["sample_context_groups"][0]["selection_reason"] == "reviewable_evidence_overlap"
    assert body["retrieval_gap"]["sample_context_groups"][0]["primary_action"] == {
        "action_type": "create_photo_context_task",
        "label": "Create context task",
        "queue": "photo_assets_needing_context",
        "request": {
            "endpoint": "/api/assets/photo-review-inventory/context-task",
            "method": "POST",
            "body": {
                "group_key": "airplane contact sheet",
                "asset_id": photo_id,
                "use_canonical": True,
                "source_query": "airplane in Maine",
                "candidate_match_quality": "weak_evidence_match",
                "candidate_selection_reason": "reviewable_evidence_overlap",
            },
        },
    }
    evidence = body["retrieval_gap"]["sample_context_groups"][0]["candidate_evidence"]
    assert evidence["not_memory_claim"] is True
    assert evidence["evidence_source"] == "title_filename_only"
    assert evidence["truth_status"] == "no_claim"
    assert evidence["candidate_media_kind"] == "photograph_like"
    assert evidence["candidate_queue"] == "photo_assets_needing_context"
    assert all(
        group["display_title"] != "Covered harbor photo.jpg"
        for group in body["retrieval_gap"]["sample_context_groups"]
    )
    assert "No boundary-cleared photo memory" in body["retrieval_gap"]["message"]

    slice_response = client.get(
        "/api/retrieval/gap-review-slice",
        params={"q": "airplane in Maine", "scope": "family_private", "limit": 5},
    )
    assert slice_response.status_code == 200
    review_slice = slice_response.json()
    assert review_slice["slice_type"] == "retrieval_gap_review_slice"
    assert review_slice["review_policy"] == "retrieval_gap_no_claim_until_adam_context"
    assert review_slice["query"] == "airplane in Maine"
    assert review_slice["gap_open"] is True
    assert review_slice["truth_status"] == "no_claim"
    assert review_slice["does_not_create_memory_claim"] is True
    assert review_slice["requires_adam_context"] is True
    assert review_slice["workflow"] == "photo_context_review"
    assert review_slice["candidate_group_selection_policy"] == "reviewable_evidence_overlap_then_backlog_sample"
    assert review_slice["candidate_count"] == 1
    assert review_slice["weak_evidence_candidate_count"] == 1
    assert review_slice["backlog_only_candidate_count"] == 0
    assert review_slice["reported_candidate_count"] == 1
    assert review_slice["completion_signal"] == "retrieval_query_returns_boundary_cleared_memory_or_context_task_submit_ready"
    assert len(review_slice["content_sha256"]) == 64
    assert any("no_claim" in boundary for boundary in review_slice["safety_boundaries"])
    assert review_slice["recommended_action"]["request"]["body"]["source_query"] == "airplane in Maine"
    item = review_slice["items"][0]
    assert item["source_photo_id"] == photo_id
    assert item["preview_url"] == f"/api/assets/{photo_id}/preview?variant=display"
    assert item["thumbnail_url"] == f"/api/assets/{photo_id}/preview?variant=thumbnail"
    assert item["matched_query_terms"] == ["airplane"]
    assert item["candidate_match_quality"] == "weak_evidence_match"
    assert item["selection_reason"] == "reviewable_evidence_overlap"
    assert item["retrieval_gap_truth_status"] == "no_claim"
    assert item["truth_status_before_review"] == "no_claim"
    assert item["not_memory_claim"] is True
    assert item["candidate_evidence"]["evidence_source"] == "title_filename_only"
    assert item["action"]["request"]["body"]["candidate_match_quality"] == "weak_evidence_match"
    assert "visible_facts" in item["suggested_context_fields"]
    assert "invisible_context" in item["suggested_context_fields"]
    assert any("Adam-authored context" in criterion for criterion in item["completion_criteria"])


def test_photo_retrieval_gap_surfaces_machine_draft_candidates_as_non_memory_claims():
    client, engine = build_client()

    with Session(engine) as session:
        draft_photo = Asset(
            human_id="ASSET_RETRIEVAL_GAP_MACHINE_DRAFT",
            asset_type="photo",
            title="Maine aviation machine draft.jpg",
            original_filename="Maine aviation machine draft.jpg",
            mime_type="image/jpeg",
            import_status="mirrored",
            processing_status="image_preview_ready",
        )
        backlog_photo = Asset(
            human_id="ASSET_RETRIEVAL_GAP_BACKLOG",
            asset_type="photo",
            title="Laundry day.jpg",
            original_filename="Laundry day.jpg",
            mime_type="image/jpeg",
            import_status="mirrored",
            processing_status="image_preview_ready",
        )
        session.add_all([draft_photo, backlog_photo])
        session.flush()
        profile = MetadataProfile(
            target_type="asset",
            target_id=draft_photo.id,
            profile_type="photo_memory",
            metadata_status="machine_draft_needs_adam_review",
            title="Photo memory draft: airplane in Maine",
            summary="Machine draft suggests a small airplane memory in Maine.",
            adam_context_note="Machine-only draft; Adam has not reviewed the meaning.",
            retrieval_notes="Queries: airplane in Maine, small flight, aviation",
            themes=["airplane", "Maine", "flight"],
            concrete_objects=["small airplane"],
            truth_status="system_inference",
            reviewed_by="system_draft",
        )
        session.add(profile)
        session.flush()
        task = Task(
            human_id="TASK_RETRIEVAL_GAP_MACHINE_DRAFT_REVIEW",
            task_type="vision_draft_review",
            target_type="metadata_profile",
            target_id=profile.id,
            queue="vision_drafts_needing_review",
            input_payload={"asset_id": draft_photo.id, "source_photo_memory_draft": True},
            created_by="test",
        )
        session.add(task)
        session.commit()
        draft_photo_id = draft_photo.id
        task_id = task.id

    response = client.get("/api/retrieval/search", params={"q": "airplane in Maine", "scope": "family_private", "limit": 3})
    assert response.status_code == 200
    body = response.json()
    assert body["results"] == []
    gap = body["retrieval_gap"]
    assert gap["truth_status"] == "no_claim"
    assert gap["candidate_group_selection_policy"] == "reviewable_evidence_overlap_then_backlog_sample"
    assert gap["photo_groups_needing_context_count"] == 1
    assert gap["photo_groups_needing_draft_review_count"] == 1
    assert gap["candidate_photo_group_count"] == 2
    assert gap["weak_evidence_candidate_count"] == 1
    assert gap["backlog_only_candidate_count"] == 1

    machine_candidate = gap["sample_context_groups"][0]
    assert machine_candidate["canonical_asset_id"] == draft_photo_id
    assert machine_candidate["candidate_status"] == "machine_draft_needs_adam_review"
    assert machine_candidate["candidate_queue"] == "vision_drafts_needing_review"
    assert machine_candidate["candidate_media_kind"] == "photograph_like"
    assert machine_candidate["candidate_match_quality"] == "weak_evidence_match"
    assert machine_candidate["selection_reason"] == "reviewable_evidence_overlap"
    assert machine_candidate["primary_action"] == {
        "action_type": "open_existing_draft_review_task",
        "label": "Open draft review",
        "task_id": task_id,
        "task_human_id": "TASK_RETRIEVAL_GAP_MACHINE_DRAFT_REVIEW",
        "queue": "vision_drafts_needing_review",
    }
    assert set(machine_candidate["matched_query_terms"]).issuperset({"airplane", "maine"})
    evidence = machine_candidate["candidate_evidence"]
    assert evidence["not_memory_claim"] is True
    assert evidence["evidence_source"] == "machine_photo_memory_draft"
    assert evidence["truth_status"] == "system_inference"
    assert evidence["profile_status"] == "machine_draft_needs_adam_review"
    assert evidence["candidate_media_kind"] == "photograph_like"
    assert evidence["profile_reviewed_by"] == "system_draft"
    assert evidence["requires_adam_review"] is True
    assert evidence["does_not_certify_final_memory"] is True
    assert evidence["review_task_id"] == task_id
    assert evidence["review_task_human_id"] == "TASK_RETRIEVAL_GAP_MACHINE_DRAFT_REVIEW"
    assert evidence["candidate_queue"] == "vision_drafts_needing_review"
    assert "metadata_profile.summary" in evidence["source_fields"]
    assert evidence["suggested_next_action"].startswith("Open the existing photo memory draft review task")

    slice_response = client.get(
        "/api/retrieval/gap-review-slice",
        params={"q": "airplane in Maine", "scope": "family_private", "limit": 5},
    )
    assert slice_response.status_code == 200
    review_slice = slice_response.json()
    machine_item = review_slice["items"][0]
    assert machine_item["candidate_status"] == "machine_draft_needs_adam_review"
    assert machine_item["truth_status_before_review"] == "system_inference"
    assert machine_item["retrieval_gap_truth_status"] == "no_claim"
    assert machine_item["not_memory_claim"] is True
    assert machine_item["action"] == {
        "action_type": "open_existing_draft_review_task",
        "label": "Open draft review",
        "task_id": task_id,
        "task_human_id": "TASK_RETRIEVAL_GAP_MACHINE_DRAFT_REVIEW",
        "queue": "vision_drafts_needing_review",
    }
    assert set(machine_item["matched_query_terms"]).issuperset({"airplane", "maine"})


def test_photo_retrieval_gap_backlog_prefers_photo_like_assets_over_design_files():
    client, engine = build_client()

    with Session(engine) as session:
        design_asset = Asset(
            human_id="ASSET_RETRIEVAL_GAP_DESIGN_BACKLOG",
            asset_type="photo",
            title="Complete Lectures Cover.psd",
            original_filename="Complete Lectures Cover.psd",
            mime_type="image/vnd.adobe.photoshop",
            import_status="mirrored",
            processing_status="image_preview_ready",
        )
        photo_asset = Asset(
            human_id="ASSET_RETRIEVAL_GAP_PHOTO_BACKLOG",
            asset_type="photo",
            title="Family picnic archive.jpg",
            original_filename="Family picnic archive.jpg",
            mime_type="image/jpeg",
            import_status="mirrored",
            processing_status="image_preview_ready",
        )
        session.add_all([design_asset, photo_asset])
        session.commit()
        photo_id = photo_asset.id

    response = client.get("/api/retrieval/search", params={"q": "zither lesson", "scope": "family_private", "limit": 3})
    assert response.status_code == 200
    gap = response.json()["retrieval_gap"]
    assert gap["candidate_photo_group_count"] == 2
    assert gap["weak_evidence_candidate_count"] == 0
    assert gap["backlog_only_candidate_count"] == 2
    first = gap["sample_context_groups"][0]
    assert first["canonical_asset_id"] == photo_id
    assert first["display_title"] == "Family picnic archive.jpg"
    assert first["candidate_match_quality"] == "backlog_only"
    assert first["candidate_media_kind"] == "photograph_like"
    assert first["candidate_evidence"]["candidate_media_kind"] == "photograph_like"
    assert first["primary_action"]["action_type"] == "create_photo_context_task"
    assert any(
        group["display_title"] == "Complete Lectures Cover.psd"
        and group["candidate_media_kind"] == "design_or_document_image"
        for group in gap["sample_context_groups"]
    )


def test_photo_context_question_answers_become_searchable_memory_and_embedding_text():
    client, engine = build_client()

    with Session(engine) as session:
        photo = Asset(
            human_id="ASSET_RALPH_AIRPLANE_CONTEXT_QUESTIONS",
            asset_type="photo",
            title="Airplane in Maine.jpg",
            original_filename="Airplane in Maine.jpg",
            mime_type="image/jpeg",
            processing_status="image_preview_ready",
        )
        session.add(photo)
        session.commit()
        photo_id = photo.id

    created = client.post(
        "/api/assets/photo-review-inventory/context-task",
        json={"asset_id": photo_id},
    )
    assert created.status_code == 200
    task_id = created.json()["task_id"]

    with Session(engine) as session:
        task = session.get(Task, task_id)
        assert task is not None
        suggested_question_ids = [question["id"] for question in task.input_payload["suggested_questions"]]
        assert suggested_question_ids == ["visible_facts", "invisible_context", "meaning", "uncertainty"]

    response = client.post(
        f"/api/tasks/{task_id}/submit",
        json={
            "decisions": {
                "visible_people": ["Adam", "Charles"],
                "place": "Maine",
                "date_or_range": "late 1980s",
                "date_confidence": "approximate",
                "event": "small airplane flight",
                "themes": ["airplane", "Maine", "fatherhood"],
                "concrete_objects": ["small airplane", "runway"],
                "visual_description_correction": "Adam and Charles are near a small airplane in Maine.",
                "invisible_context_note": "The photograph belongs to the remembered airplane outing in Maine.",
                "question_answers": {
                    "visible_facts": "The picture shows Adam, Charles, and a small airplane near trees.",
                    "meaning": "This anchors the memory of flying together in Maine, which should be findable from airplane questions.",
                },
                "open_questions": ["Which small airport was this?"],
                "ocr_review_status": "adam_corrected",
                "ocr_truth_status": "adam_expert_reconstruction",
                "corrected_ocr_text": "Back of photo note: airplane ride in Maine",
                "memory_potential": 5,
                "privacy_sensitivity": 2,
                "gallery_eligibility": "family_private",
                "privacy_level": "family_private",
                "privacy_notes": "Family-safe but not public.",
                "ready_for_downstream": "yes",
            }
        },
    )

    assert response.status_code == 200
    created_records = response.json()["creates_or_updates"]

    with Session(engine) as session:
        profile = session.get(MetadataProfile, created_records["metadata_profile_id"])
        memory = session.get(Memory, created_records["memory_id"])
        profile_embedding = session.get(EmbeddingRecord, created_records["embedding_record_id"])
        memory_embedding = session.get(EmbeddingRecord, created_records["memory_embedding_record_id"])
        ocr_segment = session.get(Segment, created_records["ocr_segment_id"])

        assert profile is not None
        assert profile.truth_status == "adam_memory"
        assert "Question: What is visibly present in the photograph?" in profile.adam_context_note
        assert "flying together in Maine" in profile.adam_context_note
        assert profile.raw_profile["answered_questions"][1]["id"] == "meaning"
        assert profile.quality_signals["answered_question_count"] == 2
        assert "Which small airport was this?" in profile.open_questions
        assert "What does Adam know about this photo that is not visible in the pixels?" in profile.open_questions
        assert "Back of photo note" in profile.retrieval_notes

        assert memory is not None
        assert "airplane outing in Maine" in memory.summary
        assert "flying together in Maine" in memory.summary

        assert profile_embedding is not None
        assert "flying together in Maine" in profile_embedding.input_text
        assert "Back of photo note" in profile_embedding.input_text
        assert memory_embedding is not None
        assert "flying together in Maine" in memory_embedding.input_text

        assert ocr_segment is not None
        assert ocr_segment.asset_id == photo_id
        assert ocr_segment.segment_type == "photo_context_ocr_text"
        assert ocr_segment.source_truth_status == "adam_expert_reconstruction"
        assert ocr_segment.maturity_level == "L3_reviewed"
        assert "airplane ride in Maine" in (ocr_segment.text_content or "")


def test_photo_memory_prompt_pair_candidates_link_photo_profile_boundary_and_embedding_text():
    client, engine = build_client()
    photo_id = _create_photo_memory(
        client,
        engine,
        human_id="ASSET_RALPH_PHOTO_PAIR_AIRPLANE",
        title="Airplane in Maine",
        description="Adam and Charles standing beside a small airplane in Maine.",
        context="This photo anchors the memory of flying an airplane together in Maine.",
        place="Maine",
        event="small airplane flight",
        themes=["airplane", "Maine", "flight", "fatherhood"],
        retrieval_origin={
            "query": "airplane in Maine",
            "candidate_match_quality": "weak_evidence_match",
            "selection_reason": "reviewable_evidence_overlap",
            "truth_status": "no_claim",
            "not_memory_claim": True,
        },
    )

    dry_run = client.post("/api/photo-memory-drafts/prompt-pair-candidates", params={"limit": 1, "dry_run": "true"})
    assert dry_run.status_code == 200
    assert dry_run.json()["created_count"] == 1
    assert dry_run.json()["created_task_ids"] == []

    response = client.post("/api/photo-memory-drafts/prompt-pair-candidates", params={"limit": 1, "dry_run": "false"})
    assert response.status_code == 200
    body = response.json()
    assert body["created_count"] == 1
    assert body["created_task_ids"] == []
    assert body["generation_batch_id"].startswith("PHOTO_PAIR_BATCH_")
    assert body["generation_batch_ids"] == [body["generation_batch_id"]]
    assert body["candidates"][0]["asset_id"] == photo_id
    assert body["candidates"][0]["existing_task_id"]
    assert body["candidates"][0]["photo_pair_generation_batch_id"] == body["generation_batch_id"]
    assert body["candidates"][0]["prompt"] == "Dad, what do you remember about flying in Maine?"
    assert body["candidates"][0]["retrieval_gap_origin"] == {
        "query": "airplane in Maine",
        "candidate_match_quality": "weak_evidence_match",
        "selection_reason": "reviewable_evidence_overlap",
        "truth_status": "no_claim",
        "not_memory_claim": True,
    }
    assert body["candidates"][0]["truth_status"] == "interpretive_synthesis"
    assert body["candidates"][0]["source_truth_status"] == "adam_memory"
    assert body["candidates"][0]["candidate_response_truth_status"] == "interpretive_synthesis"
    assert ".jpg" not in body["candidates"][0]["prompt"].lower()

    with Session(engine) as session:
        task = session.get(Task, body["candidates"][0]["existing_task_id"])
        assert task is not None
        payload = task.input_payload
        profile = session.get(MetadataProfile, payload["source_photo_profile_id"])
        prompt_spec = session.get(PromptSpec, payload["prompt_spec_id"])
        context_pack = session.get(ContextPack, payload["context_pack_id"])

        assert task.task_type == "gold_voice_edit"
        assert task.queue == "prompt_pairs_needing_gold_edits"
        assert task.created_by == "photo_memory_prompt_pair_generation"
        assert task.status == "ready"
        assert payload["artifact_mode"] == "sft"
        assert payload["prompt"] == "Dad, what do you remember about flying in Maine?"
        assert payload["content"].endswith("love\ndad")
        assert payload["synthetic"] is True
        assert payload["truth_status"] == "interpretive_synthesis"
        assert payload["source_truth_status"] == "adam_memory"
        assert payload["candidate_response_truth_status"] == "interpretive_synthesis"
        assert payload["photo_pair_generation_batch_id"] == body["generation_batch_id"]
        assert payload["source_photo_id"] == photo_id
        assert payload["grounding_asset_id"] == photo_id
        assert payload["source_photo_profile_id"] == profile.id
        assert payload["source_photo_memory_id"]
        assert payload["source_embedding_record_id"]
        assert payload["retrieval_gap_origin"] == {
            "query": "airplane in Maine",
            "candidate_match_quality": "weak_evidence_match",
            "selection_reason": "reviewable_evidence_overlap",
            "truth_status": "no_claim",
            "not_memory_claim": True,
        }
        assert payload["boundary_snapshot"]["target_type"] == "asset"
        assert payload["boundary_snapshot"]["target_id"] == photo_id
        assert payload["boundary_snapshot"]["usable_for_sft"] is False
        assert payload["candidate_requires_adam_gold_edit"] is True
        assert payload["export_flags"] == {
            "sft": False,
            "dpo": False,
            "eval": False,
            "anti_pattern": False,
            "style_rule": False,
        }
        assert "small airplane" in payload["embedding_input_text"]
        assert "flying an airplane together in Maine" in payload["embedding_input_text"]
        assert payload["photo_pair_generation_strategy"] == "deterministic_photo_memory_reconstruction_template"
        assert "photo_grounded_synthetic_candidate_needs_adam_review" in payload["failure_modes"]

        assert prompt_spec is not None
        assert prompt_spec.prompt_type == "photo_memory_prompt_pair_candidate"
        assert prompt_spec.truth_mode == "interpretive_synthesis"
        assert prompt_spec.prompt_text == payload["prompt"]
        assert prompt_spec.metadata_json["source_photo_id"] == photo_id
        assert prompt_spec.metadata_json["source_photo_profile_id"] == profile.id
        assert prompt_spec.metadata_json["source_truth_status"] == "adam_memory"
        assert prompt_spec.metadata_json["candidate_response_truth_status"] == "interpretive_synthesis"
        assert prompt_spec.metadata_json["photo_pair_generation_batch_id"] == body["generation_batch_id"]
        assert prompt_spec.metadata_json["retrieval_gap_origin"]["not_memory_claim"] is True
        assert prompt_spec.success_criteria["must_link_source_photo"] is True

        assert context_pack is not None
        assert context_pack.user_intent == "photo_memory_prompt_pair_generation"
        assert context_pack.truth_mode == "interpretive_synthesis"
        assert context_pack.boundaries_snapshot["source_photo_id"] == photo_id
        assert context_pack.boundaries_snapshot["source_truth_status"] == "adam_memory"
        assert context_pack.boundaries_snapshot["candidate_response_truth_status"] == "interpretive_synthesis"
        assert context_pack.boundaries_snapshot["photo_pair_generation_batch_id"] == body["generation_batch_id"]
        assert context_pack.boundaries_snapshot["retrieval_gap_origin"]["query"] == "airplane in Maine"
        assert (
            context_pack.style_guidance["retrieval_gap_origin_policy"]
            == "workflow provenance only; not a source fact or memory claim"
        )
        assert context_pack.boundaries_snapshot["requires_adam_gold_edit"] is True
        assert "small airplane" in context_pack.allowed_facts[0]

    repeat = client.post("/api/photo-memory-drafts/prompt-pair-candidates", params={"limit": 1, "dry_run": "false"})
    assert repeat.status_code == 200
    assert repeat.json()["created_task_ids"] == []
    assert repeat.json()["generation_batch_id"] == body["generation_batch_id"]
    assert repeat.json()["candidates"][0]["existing_task_id"] == body["candidates"][0]["existing_task_id"]


def test_photo_memory_prompt_pair_candidates_can_target_one_reviewed_photo():
    client, engine = build_client()
    first_photo_id = _create_photo_memory(
        client,
        engine,
        human_id="ASSET_RALPH_PHOTO_PAIR_TARGETED_FLOWERS",
        title="Adam holding yellow flowers",
        description="Adam is holding yellow flowers in a family photograph.",
        context="Adam says the yellow flowers sparked a memory about arriving for a family visit.",
        place="Maine",
        event="family visit",
        themes=["yellow flowers", "family visit"],
    )
    second_photo_id = _create_photo_memory(
        client,
        engine,
        human_id="ASSET_RALPH_PHOTO_PAIR_TARGETED_FLUTE",
        title="Charles with Japanese flute",
        description="Charles is holding a Japanese flute.",
        context="Adam says this is about Charles studying shakuhachi.",
        place="Portland",
        event="music practice",
        themes=["flute", "music"],
    )

    response = client.post(
        "/api/photo-memory-drafts/prompt-pair-candidates",
        params={"limit": 5, "dry_run": "false", "asset_id": first_photo_id},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["asset_id"] == first_photo_id
    assert body["metadata_profile_id"] is None
    assert body["generation_batch_id"].startswith("PHOTO_PAIR_BATCH_")
    assert body["generation_batch_ids"] == [body["generation_batch_id"]]
    assert body["created_count"] == 5
    task_ids = body["created_task_ids"] or [candidate["existing_task_id"] for candidate in body["candidates"]]
    assert len(task_ids) == 5
    assert {candidate["asset_id"] for candidate in body["candidates"]} == {first_photo_id}
    assert {candidate["photo_pair_generation_batch_id"] for candidate in body["candidates"]} == {body["generation_batch_id"]}
    assert {candidate["variant_key"] for candidate in body["candidates"]} == {
        "direct_memory",
        "first_look",
        "surrounding_day",
        "relationship_thread",
        "photographer_eye",
    }
    assert len({candidate["prompt"] for candidate in body["candidates"]}) == 5

    with Session(engine) as session:
        tasks = [session.get(Task, task_id) for task_id in task_ids]
        assert all(task is not None for task in tasks)
        payloads = [task.input_payload for task in tasks if task is not None]
        assert {payload["source_photo_id"] for payload in payloads} == {first_photo_id}
        assert {payload["grounding_asset_id"] for payload in payloads} == {first_photo_id}
        assert {payload["photo_pair_generation_batch_id"] for payload in payloads} == {body["generation_batch_id"]}
        assert {payload["photo_pair_variant_key"] for payload in payloads} == {
            "direct_memory",
            "first_look",
            "surrounding_day",
            "relationship_thread",
            "photographer_eye",
        }
        assert len({payload["prompt"] for payload in payloads}) == 5
        assert all(second_photo_id not in payload["embedding_input_text"] for payload in payloads)

    repeat = client.post(
        "/api/photo-memory-drafts/prompt-pair-candidates",
        params={"limit": 5, "dry_run": "false", "asset_id": first_photo_id},
    )
    assert repeat.status_code == 200
    assert repeat.json()["created_task_ids"] == []
    assert repeat.json()["generation_batch_id"] == body["generation_batch_id"]
    assert {candidate["existing_task_id"] for candidate in repeat.json()["candidates"]} == set(task_ids)


def test_prompt_pair_candidate_delete_is_audited_and_removed_from_ready_queue():
    client, engine = build_client()
    photo_id = _create_photo_memory(
        client,
        engine,
        human_id="ASSET_RALPH_PHOTO_PAIR_DELETE",
        title="Adam holding yellow flowers",
        description="Adam is holding yellow flowers in a family photograph.",
        context="Adam says the yellow flowers sparked a memory about arriving for a family visit.",
        place="Maine",
        event="family visit",
        themes=["yellow flowers", "family visit"],
    )
    created = client.post(
        "/api/photo-memory-drafts/prompt-pair-candidates",
        params={"limit": 5, "dry_run": "false", "asset_id": photo_id},
    )
    assert created.status_code == 200
    created_body = created.json()
    task_id = created_body["created_task_ids"][0] if created_body["created_task_ids"] else created_body["candidates"][0]["existing_task_id"]
    assert task_id

    with Session(engine) as session:
        session.add(TaskDraft(task_id=task_id, user_id="adam", decisions={"prompt": "rough"}, notes="working"))
        session.commit()

    response = client.post(
        f"/api/tasks/{task_id}/delete-candidate",
        json={"reason": "Not the strongest generated option", "notes": "Keeping better flower candidates."},
    )
    assert response.status_code == 200
    annotation_body = response.json()
    assert annotation_body["annotation_type"] == "prompt_pair_candidate_deleted"
    assert annotation_body["decisions"]["hard_deleted"] is False
    assert annotation_body["decisions"]["audit_record_preserved"] is True
    assert annotation_body["decisions"]["source_photo_id"] == photo_id
    assert annotation_body["creates_or_updates"]["new_status"] == "rejected_candidate"

    with Session(engine) as session:
        task = session.get(Task, task_id)
        assert task is not None
        assert task.status == "rejected_candidate"
        assert task.input_payload["candidate_rejection_reason"] == "Not the strongest generated option"
        assert task.input_payload["candidate_rejection_annotation_type"] == "prompt_pair_candidate_deleted"
        assert session.get(Annotation, annotation_body["id"]) is not None
        assert session.exec(select(TaskDraft).where(TaskDraft.task_id == task_id)).first() is None


def test_operator_assistant_asks_next_photo_review_question_without_secret_leakage():
    client, engine = build_client()
    with Session(engine) as session:
        photo = Asset(
            human_id="ASSET_OPERATOR_ASSISTANT_PHOTO",
            asset_type="photo",
            title="Cathryn by the window",
            original_filename="cathryn-window.jpg",
            mime_type="image/jpeg",
        )
        session.add(photo)
        session.flush()
        task = Task(
            human_id="TASK_OPERATOR_ASSISTANT_PHOTO",
            task_type="photo_context",
            target_type="asset",
            target_id=photo.id,
            queue="photo_assets_needing_context",
            input_payload={"asset_id": photo.id, "asset_title": photo.title, "asset_type": "photo"},
            created_by="test",
        )
        session.add(task)
        session.commit()
        task_id = task.id

    first = client.post(f"/api/tasks/{task_id}/operator-assistant", json={"decisions": {}})
    assert first.status_code == 200
    first_body = first.json()
    assert first_body["assistant_type"] == "neutral_operator_assistant"
    assert first_body["status"] == "deterministic_no_model_call"
    assert first_body["live_model_call_used"] is False
    assert first_body["target_decision_key"] == "visual_description_correction"
    assert first_body["safety_policy"]["not_charles_voice"] is True
    assert first_body["safety_policy"]["no_secret_values_returned"] is True
    assert "api" not in str(first_body).lower()

    second = client.post(
        f"/api/tasks/{task_id}/operator-assistant",
        json={
            "decisions": {
                "visual_description_correction": "Cathryn is standing by a window in soft interior light.",
            }
        },
    )
    assert second.status_code == 200
    second_body = second.json()
    assert second_body["target_decision_key"] == "adam_context_note"
    assert "memory" in second_body["next_question"].lower()

    parsed = client.post(
        f"/api/tasks/{task_id}/operator-assistant",
        json={
            "decisions": {
                "visual_description_correction": "Cathryn is standing by a window in soft interior light.",
            },
            "operator_answer": "It brings back the feeling of visiting Cathryn in that apartment, the quiet by the windows.",
        },
    )
    assert parsed.status_code == 200
    parsed_body = parsed.json()
    assert parsed_body["field_updates"]["adam_context_note"].startswith("It brings back")
    assert parsed_body["submit_recommendation"]["requested"] is False
    assert parsed_body["safety_policy"]["does_not_mutate_source"] is True


def test_operator_assistant_guides_photo_generated_prompt_pair_triage():
    client, engine = build_client()
    photo_id = _create_photo_memory(
        client,
        engine,
        human_id="ASSET_OPERATOR_ASSISTANT_PAIR",
        title="Adam holding yellow flowers",
        description="Adam is holding yellow flowers in a family photograph.",
        context="Adam says the yellow flowers sparked a memory about arriving for a family visit.",
        place="Maine",
        event="family visit",
        themes=["yellow flowers", "family visit"],
    )
    created = client.post(
        "/api/photo-memory-drafts/prompt-pair-candidates",
        params={"limit": 5, "dry_run": "false", "asset_id": photo_id},
    )
    assert created.status_code == 200
    created_body = created.json()
    task_id = created_body["created_task_ids"][0] if created_body["created_task_ids"] else created_body["candidates"][0]["existing_task_id"]
    assert task_id

    response = client.post(f"/api/tasks/{task_id}/operator-assistant", json={"decisions": {}})
    assert response.status_code == 200
    body = response.json()
    assert body["assistant_type"] == "neutral_operator_assistant"
    assert body["target_decision_key"] == "context"
    assert body["target_label"] == "Keep/edit/delete note"
    assert "delete" in body["next_question"].lower()
    assert body["safety_policy"]["not_charles_voice"] is True

    delete_parse = client.post(
        f"/api/tasks/{task_id}/operator-assistant",
        json={"decisions": {}, "operator_answer": "Delete this candidate; it feels too generic."},
    )
    assert delete_parse.status_code == 200
    delete_body = delete_parse.json()
    assert delete_body["field_updates"]["context"].startswith("Delete this candidate")


def test_machine_photo_memory_drafts_create_profiles_memories_embeddings_and_retrieval():
    client, engine = build_client()
    with Session(engine) as session:
        assets = [
            Asset(
                human_id="ASSET_FLUTE",
                asset_type="photo",
                title="Rotmil and Japanese Flute II.jpg",
                original_filename="Rotmil and Japanese Flute II.jpg",
                mime_type="image/jpeg",
                import_status="mirrored",
                processing_status="image_preview_ready",
            ),
            Asset(
                human_id="ASSET_HONORS",
                asset_type="photo",
                title="Rotmil Honors VIII.jpg",
                original_filename="Rotmil Honors VIII.jpg",
                mime_type="image/jpeg",
                import_status="mirrored",
                processing_status="image_preview_ready",
            ),
            Asset(
                human_id="ASSET_ADAM_FLOWERS",
                asset_type="photo",
                title="Rotmil_Scan_15_2-2018 - Adam with flowers.jpg",
                original_filename="Rotmil_Scan_15_2-2018 - Adam with flowers.jpg",
                mime_type="image/jpeg",
                import_status="mirrored",
                processing_status="image_preview_ready",
            ),
            Asset(
                human_id="ASSET_STREET",
                asset_type="photo",
                title="Rotmil-Street Walker.jpg",
                original_filename="Rotmil-Street Walker.jpg",
                mime_type="image/jpeg",
                import_status="mirrored",
                processing_status="image_preview_ready",
            ),
            Asset(
                human_id="ASSET_NIXON",
                asset_type="photo",
                title="Rotmil 2021 I.jpg",
                original_filename="Rotmil 2021 I.jpg",
                mime_type="image/jpeg",
                import_status="mirrored",
                processing_status="image_preview_ready",
            ),
        ]
        session.add_all(assets)
        session.commit()

    dry_run = client.post("/api/photo-memory-drafts", params={"limit": 5, "dry_run": "true"})
    assert dry_run.status_code == 200
    assert dry_run.json()["created_count"] == 5

    response = client.post("/api/photo-memory-drafts", params={"limit": 5, "dry_run": "false"})
    assert response.status_code == 200
    body = response.json()
    assert body["created_count"] == 5
    assert body["candidate_count"] == 5
    assert body["created_new_count"] == 5
    assert body["reused_count"] == 0
    assert body["skipped"] == []
    assert all(item["metadata_profile_id"] for item in body["candidates"])
    assert all(item["memory_id"] for item in body["candidates"])
    assert len(body["review_task_ids"]) == 5
    assert all(item["review_task_id"] for item in body["candidates"])
    assert all(item["profile_embedding_record_id"] for item in body["candidates"])
    assert all(item["memory_embedding_record_id"] for item in body["candidates"])

    with Session(engine) as session:
        profiles = session.exec(select(MetadataProfile)).all()
        memories = session.exec(select(Memory)).all()
        embeddings = session.exec(select(EmbeddingRecord)).all()
        annotations = session.exec(select(Annotation).where(Annotation.annotation_type == "photo_memory_machine_draft")).all()
        boundaries = session.exec(select(Boundary)).all()
        tasks = session.exec(select(Task).where(Task.task_type == "vision_draft_review")).all()
        assert len(profiles) == 5
        assert len(memories) == 5
        assert len(embeddings) == 10
        assert len(annotations) == 5
        assert len(boundaries) == 5
        assert len(tasks) == 5
        assert {task.queue for task in tasks} == {"vision_drafts_needing_review"}
        assert all(task.input_payload["source_photo_memory_draft"] is True for task in tasks)
        assert all(task.input_payload["vision_draft"]["visual_summary"] for task in tasks)
        assert all("boundary_privacy_level: family_private" in embedding.input_text for embedding in embeddings)
        assert all("boundary_usable_for_sft: false" in embedding.input_text for embedding in embeddings)
        assert {profile.metadata_status for profile in profiles} == {"machine_draft_needs_adam_review"}
        assert {profile.truth_status for profile in profiles} == {"system_inference"}
        assert all(boundary.retrievable_in_chat for boundary in boundaries)
        assert all(boundary.reviewed_by == "system_draft" for boundary in boundaries)

    first_export = client.get("/api/retrieval/photo-memory-corpus/export", params={"scope": "family_private", "limit": 20})
    assert first_export.status_code == 200
    first_export_body = first_export.json()
    assert first_export_body["manifest"]["record_count"] == 0
    assert first_export_body["manifest"]["source_photo_count"] == 0
    assert first_export_body["manifest"]["excluded_count"] == 5
    assert first_export_body["manifest"]["reviewed_ready_count"] == 0
    assert first_export_body["manifest"]["held_for_adam_review_count"] == 5
    assert first_export_body["manifest"]["boundary_excluded_count"] == 0
    assert first_export_body["manifest"]["exclusion_reason_counts"] == {"requires_adam_review": 5}
    assert first_export_body["manifest"]["review_policy"] == "reviewed_only_by_default"
    assert first_export_body["manifest"]["include_machine_drafts"] is False
    assert first_export_body["manifest"]["preview_only"] is False
    assert first_export_body["manifest"]["not_for_downstream_vector_store"] is False
    assert len(first_export_body["manifest"]["next_review_actions"]) == 5
    assert all(action["review_task_id"] for action in first_export_body["manifest"]["next_review_actions"])
    assert all(action["review_status"] == "held_for_adam_review" for action in first_export_body["manifest"]["next_review_actions"])
    assert first_export_body["next_review_actions"] == first_export_body["manifest"]["next_review_actions"]
    assert first_export_body["jsonl"] == ""
    assert {item["reasons"][0] for item in first_export_body["excluded"]} == {"requires_adam_review"}
    assert {item["review_status"] for item in first_export_body["excluded"]} == {"held_for_adam_review"}
    assert all(item["source_photo_id"] for item in first_export_body["excluded"])
    assert all(item["source_photo_title"] for item in first_export_body["excluded"])
    assert all(item["review_task_id"] for item in first_export_body["excluded"])
    assert all(item["review_task_human_id"].startswith("TASK_") for item in first_export_body["excluded"])
    assert all(item["suggested_next_action"].startswith("Open the photo memory review task") for item in first_export_body["excluded"])
    assert all("adam_context_note" in item["promotion_requirements"]["required_decisions"] for item in first_export_body["excluded"])
    assert all(
        item["promotion_requirements"]["reviewed_record_requirements"]["metadata_source"] == "photo_memory_review"
        for item in first_export_body["excluded"]
    )
    first_hash = first_export_body["manifest"]["content_sha256"]
    manifest_response = client.get(
        "/api/retrieval/photo-memory-corpus/export.manifest",
        params={"scope": "family_private", "limit": 20},
    )
    assert manifest_response.status_code == 200
    assert manifest_response.json() == first_export_body["manifest"]
    jsonl_response = client.get(
        "/api/retrieval/photo-memory-corpus/export.jsonl",
        params={"scope": "family_private", "limit": 20},
    )
    assert jsonl_response.status_code == 200
    assert jsonl_response.headers["content-type"].startswith("application/x-ndjson")
    assert "charlesops_photo_memory_vector_handoff_family_private_0.jsonl" in jsonl_response.headers["content-disposition"]
    assert jsonl_response.text == first_export_body["jsonl"]

    repeat = client.post("/api/photo-memory-drafts", params={"limit": 5, "dry_run": "false"})
    assert repeat.status_code == 200
    repeat_body = repeat.json()
    assert repeat_body["created_count"] == 5
    assert repeat_body["candidate_count"] == 5
    assert repeat_body["created_new_count"] == 0
    assert repeat_body["reused_count"] == 5
    assert set(repeat_body["review_task_ids"]) == set(body["review_task_ids"])
    assert all(item["reused_existing"] is True for item in repeat_body["candidates"])

    with Session(engine) as session:
        assert len(session.exec(select(MetadataProfile)).all()) == 5
        assert len(session.exec(select(Memory)).all()) == 5
        assert len(session.exec(select(EmbeddingRecord)).all()) == 10
        assert len(session.exec(select(Annotation).where(Annotation.annotation_type == "photo_memory_machine_draft")).all()) == 5
        assert len(session.exec(select(Task).where(Task.task_type == "vision_draft_review")).all()) == 5

    repeat_export = client.get("/api/retrieval/photo-memory-corpus/export", params={"scope": "family_private", "limit": 20})
    assert repeat_export.status_code == 200
    assert repeat_export.json()["manifest"]["content_sha256"] == first_hash

    flute = client.get("/api/retrieval/search", params={"q": "Japanese flute", "scope": "family_private", "limit": 3})
    assert flute.status_code == 200
    assert flute.json()["results"]
    assert "Japanese flute" in flute.json()["results"][0]["title"]
    assert flute.json()["results"][0]["target_type"] == "memory"
    assert flute.json()["results"][0]["review_policy"] == {
        "requires_adam_review": True,
        "truth_status": "system_inference",
        "boundary_reviewed_by": "system_draft",
        "does_not_certify_final_memory": True,
    }
    assert len([result["source_photo_id"] for result in flute.json()["results"]]) == len(
        {result["source_photo_id"] for result in flute.json()["results"]}
    )

    honors = client.get("/api/retrieval/search", params={"q": "honors ceremony", "scope": "family_private", "limit": 3})
    assert honors.status_code == 200
    assert honors.json()["results"]
    assert "honors ceremony" in honors.json()["results"][0]["input_preview"].lower()
    assert honors.json()["results"][0]["target_type"] == "memory"
    assert honors.json()["results"][0]["review_policy"]["requires_adam_review"] is True
    assert len([result["source_photo_id"] for result in honors.json()["results"]]) == len(
        {result["source_photo_id"] for result in honors.json()["results"]}
    )

    flowers = client.get("/api/retrieval/search", params={"q": "Adam flowers", "scope": "family_private", "limit": 3})
    assert flowers.status_code == 200
    assert flowers.json()["results"]
    assert "Adam" in flowers.json()["results"][0]["title"]
    assert flowers.json()["results"][0]["target_type"] == "memory"
    assert flowers.json()["results"][0]["review_policy"]["requires_adam_review"] is True
    assert len([result["source_photo_id"] for result in flowers.json()["results"]]) == len(
        {result["source_photo_id"] for result in flowers.json()["results"]}
    )

    corpus = client.get("/api/retrieval/photo-memory-corpus", params={"scope": "family_private", "limit": 20})
    assert corpus.status_code == 200
    corpus_body = corpus.json()
    assert corpus_body["corpus_type"] == "photo_memory_embedding_text"
    assert corpus_body["review_policy"] == "reviewed_only_by_default"
    assert corpus_body["include_machine_drafts"] is False
    assert corpus_body["record_count"] == 0
    assert corpus_body["excluded_count"] == 5
    assert corpus_body["reviewed_ready_count"] == 0
    assert corpus_body["held_for_adam_review_count"] == 5
    assert corpus_body["boundary_excluded_count"] == 0
    assert {item["reasons"][0] for item in corpus_body["excluded"]} == {"requires_adam_review"}
    assert {item["review_status"] for item in corpus_body["excluded"]} == {"held_for_adam_review"}
    assert {item["review_queue"] for item in corpus_body["excluded"]} == {"vision_drafts_needing_review"}
    assert {item["review_task_id"] for item in corpus_body["excluded"]} == set(body["review_task_ids"])
    assert len(corpus_body["next_review_actions"]) == 5
    assert {item["review_task_id"] for item in corpus_body["next_review_actions"]} == set(body["review_task_ids"])
    assert all(
        item["promotion_requirements"]["reviewed_record_requirements"]["boundary_reviewed_by"] == "adam"
        for item in corpus_body["excluded"]
    )

    preview_corpus = client.get(
        "/api/retrieval/photo-memory-corpus",
        params={"scope": "family_private", "limit": 20, "include_machine_drafts": "true"},
    )
    assert preview_corpus.status_code == 200
    preview_body = preview_corpus.json()
    assert preview_body["record_count"] == 5
    assert preview_body["include_machine_drafts"] is True
    assert preview_body["preview_only"] is True
    assert preview_body["not_for_downstream_vector_store"] is True
    assert all(record["source_photo_id"] for record in preview_body["records"])
    assert all(record["input_text"] for record in preview_body["records"])
    assert all(record["boundary_snapshot"]["retrievable_in_chat"] for record in preview_body["records"])
    assert len([record["source_photo_id"] for record in preview_body["records"]]) == len(
        {record["source_photo_id"] for record in preview_body["records"]}
    )
    assert {record["target_type"] for record in preview_body["records"]} == {"memory"}

    preview_export = client.get(
        "/api/retrieval/photo-memory-corpus/export",
        params={"scope": "family_private", "limit": 20, "include_machine_drafts": "true"},
    )
    assert preview_export.status_code == 200
    preview_export_body = preview_export.json()
    assert preview_export_body["manifest"]["record_count"] == 5
    assert preview_export_body["manifest"]["reviewed_ready_count"] == 0
    assert preview_export_body["manifest"]["machine_draft_preview_record_count"] == 5
    assert preview_export_body["manifest"]["include_machine_drafts"] is True
    assert preview_export_body["manifest"]["preview_only"] is True
    assert preview_export_body["manifest"]["not_for_downstream_vector_store"] is True
    assert all(
        item["metadata"]["truth_status"] == "system_inference"
        for item in preview_export_body["records"]
    )


def test_machine_photo_memory_drafts_reopen_ready_task_if_prior_review_task_closed():
    client, engine = build_client()
    with Session(engine) as session:
        photo = Asset(
            human_id="ASSET_REOPEN_FLUTE_REVIEW",
            asset_type="photo",
            title="Rotmil and Japanese Flute II.jpg",
            original_filename="Rotmil and Japanese Flute II.jpg",
            mime_type="image/jpeg",
            import_status="mirrored",
            processing_status="vision_reviewed",
        )
        session.add(photo)
        session.commit()

    first = client.post("/api/photo-memory-drafts", params={"limit": 1, "dry_run": "false"})
    assert first.status_code == 200
    first_task_id = first.json()["review_task_ids"][0]

    with Session(engine) as session:
        task = session.get(Task, first_task_id)
        assert task is not None
        task.status = "submitted"
        session.add(task)
        session.commit()

    repeat = client.post("/api/photo-memory-drafts", params={"limit": 1, "dry_run": "false"})
    assert repeat.status_code == 200
    body = repeat.json()
    assert len(body["review_task_ids"]) == 1
    assert body["review_task_ids"][0] != first_task_id
    assert body["candidates"][0]["review_task_id"] == body["review_task_ids"][0]

    with Session(engine) as session:
        reopened = session.get(Task, body["review_task_ids"][0])
        assert reopened is not None
        assert reopened.status == "ready"
        assert reopened.input_payload["previous_review_task_id"] == first_task_id
        assert reopened.input_payload["previous_review_task_status"] == "submitted"


def test_machine_photo_memory_review_promotes_adam_context_over_system_inference():
    client, engine = build_client()
    with Session(engine) as session:
        photo = Asset(
            human_id="ASSET_REVIEWED_FLUTE_PROMOTION",
            asset_type="photo",
            title="Rotmil and Japanese Flute II.jpg",
            original_filename="Rotmil and Japanese Flute II.jpg",
            mime_type="image/jpeg",
            import_status="mirrored",
            processing_status="image_preview_ready",
        )
        session.add(photo)
        session.commit()
        photo_id = photo.id

    draft = client.post("/api/photo-memory-drafts", params={"limit": 1, "dry_run": "false"})
    assert draft.status_code == 200
    draft_body = draft.json()
    assert draft_body["created_count"] == 1
    review_task_id = draft_body["review_task_ids"][0]

    review = client.post(
        f"/api/tasks/{review_task_id}/submit",
        json={
            "decisions": {
                "vision_accuracy": "minor_issues",
                "accepted_visual_description": "Charles is seated with a Japanese flute in his Portland apartment.",
                "people": ["Charles Rotmil"],
                "places": ["Portland apartment"],
                "date_or_range": "unknown",
                "accepted_tags": ["Japanese flute", "music practice", "apartment ritual"],
                "themes": ["Japanese flute", "music practice", "daily ritual"],
                "concrete_objects": ["Japanese flute", "coffee mug", "books"],
                "question_answers": {
                    "why_this_photo_matters": "This photo anchors Charles's practice ritual with the Japanese flute.",
                    "what_should_be_corrected": "Do not treat the machine's apartment-object guesses as certain.",
                    "downstream_boundary": "Family-private retrieval is fine.",
                },
                "adam_context_note": "Adam confirms this is about the flute practice ritual, not only a generic portrait.",
                "privacy_level": "family_private",
                "privacy_notes": "Adam-reviewed family-private memory.",
                "ready_for_downstream": "yes",
                "truth_status": "system_inference",
                "ocr_review_status": "not_present",
            }
        },
    )
    assert review.status_code == 200
    created = review.json()["creates_or_updates"]
    assert created["vector_handoff_status"] == "eligible_reviewed_record"
    assert created["vector_handoff_record_id"] == created["memory_embedding_record_id"]
    assert created["removed_machine_draft_gallery_item_id"]
    assert "default reviewed-only vector handoff" in created["vector_handoff_reason"]
    assert created["photo_prompt_pair_generation"]["created_count"] == 5
    assert len(created["photo_prompt_pair_generation"]["created_task_ids"]) == 5
    assert created["photo_prompt_pair_task_ids"] == created["photo_prompt_pair_generation"]["created_task_ids"]
    assert created["photo_prompt_pair_generation_batch_id"].startswith("PHOTO_PAIR_BATCH_")
    assert created["receipt"]["vector_handoff_status"] == "eligible_reviewed_record"
    assert created["receipt"]["vector_handoff_record_id"] == created["memory_embedding_record_id"]
    assert any(outcome["label"] == "Vector handoff record" for outcome in created["receipt"]["outcomes"])

    with Session(engine) as session:
        reopened_pair_handoff = _attach_photo_prompt_pair_candidates(
            session=session,
            creates_or_updates={
                "metadata_profile_id": created["metadata_profile_id"],
                "boundary_id": created["boundary_id"],
                "vector_handoff_status": created["vector_handoff_status"],
            },
        )
    assert reopened_pair_handoff["photo_prompt_pair_generation"]["created_task_ids"] == []
    assert len(reopened_pair_handoff["photo_prompt_pair_task_ids"]) == 5
    assert set(reopened_pair_handoff["photo_prompt_pair_task_ids"]) == set(created["photo_prompt_pair_task_ids"])
    assert reopened_pair_handoff["photo_prompt_pair_generation_batch_id"] == created["photo_prompt_pair_generation_batch_id"]

    with Session(engine) as session:
        profile = session.get(MetadataProfile, created["metadata_profile_id"])
        memory = session.get(Memory, created["memory_id"])
        profile_embedding = session.get(EmbeddingRecord, created["embedding_record_id"])
        memory_embedding = session.get(EmbeddingRecord, created["memory_embedding_record_id"])

        assert profile is not None
        assert profile.target_id == photo_id
        assert profile.metadata_status == "adam_reviewed"
        assert profile.reviewed_by == "adam"
        assert profile.truth_status == "adam_memory"
        assert "Question: What does this photo mean to you, beyond what is visible?" in profile.adam_context_note
        assert "practice ritual with the Japanese flute" in profile.adam_context_note
        assert profile.raw_profile["adam_review"]["answered_questions"][0]["id"] == "why_this_photo_matters"

        assert memory is not None
        assert memory.truth_status == "adam_memory"
        assert memory.maturity_level == "L3_reviewed"
        assert "flute practice ritual" in memory.summary

        assert profile_embedding is not None
        assert profile_embedding.truth_status == "adam_memory"
        assert "practice ritual with the Japanese flute" in profile_embedding.input_text
        assert memory_embedding is not None
        assert memory_embedding.truth_status == "adam_memory"
        assert "flute practice ritual" in memory_embedding.input_text

    search = client.get(
        "/api/retrieval/search",
        params={"q": "Japanese flute practice ritual", "scope": "family_private", "limit": 3},
    )
    assert search.status_code == 200
    top = search.json()["results"][0]
    assert top["source_photo_id"] == photo_id
    assert top["target_type"] == "memory"
    assert top["truth_status"] == "adam_memory"
    assert top["review_policy"] == {
        "requires_adam_review": False,
        "truth_status": "adam_memory",
        "boundary_reviewed_by": "adam",
        "does_not_certify_final_memory": False,
    }

    corpus = client.get("/api/retrieval/photo-memory-corpus", params={"scope": "family_private", "limit": 5})
    assert corpus.status_code == 200
    corpus_body = corpus.json()
    assert corpus_body["records"][0]["source_photo_id"] == photo_id
    assert corpus_body["records"][0]["truth_status"] == "adam_memory"
    assert photo_id not in {item["source_photo_id"] for item in corpus_body["excluded"]}

    gallery = client.get("/api/gallery/reviewed-photos", params={"scope": "family_private", "include_drafts": "true"})
    assert gallery.status_code == 200
    gallery_body = gallery.json()
    reviewed_items = [item for item in gallery_body["items"] if item["source_photo_id"] == photo_id]
    assert len(reviewed_items) == 1
    assert reviewed_items[0]["review_status"] == "reviewed"
    assert reviewed_items[0]["requires_adam_review"] is False
    assert reviewed_items[0]["profile_truth_status"] == "adam_memory"
    assert reviewed_items[0]["display_caption"] == "Charles is seated with a Japanese flute in his Portland apartment."
    assert "flute practice ritual" in reviewed_items[0]["memory_caption"]

    pair_seed = client.post("/api/photo-memory-drafts/prompt-pair-candidates", params={"limit": 1, "dry_run": "false"})
    assert pair_seed.status_code == 200
    pair_body = pair_seed.json()
    assert pair_body["created_count"] == 1
    assert pair_body["created_task_ids"] == []
    task_id = pair_body["candidates"][0]["existing_task_id"]
    with Session(engine) as session:
        task = session.get(Task, task_id)
        assert task is not None
        payload = task.input_payload
        assert payload["source_photo_id"] == photo_id
        assert payload["source_profile_status"] == "adam_reviewed"
        assert payload["truth_status"] == "interpretive_synthesis"
        assert payload["source_truth_status"] == "adam_memory"
        assert payload["candidate_response_truth_status"] == "interpretive_synthesis"
        assert payload["content"].startswith("i remember this...")
        assert "practice ritual with the Japanese flute" in payload["embedding_input_text"]


def test_sealed_photo_review_receipt_reports_boundary_exclusion_from_vector_handoff():
    client, engine = build_client()
    with Session(engine) as session:
        photo = Asset(
            human_id="ASSET_REVIEWED_SEALED_VECTOR_RECEIPT",
            asset_type="photo",
            title="Rotmil and Japanese Flute Private Sealed.jpg",
            original_filename="Rotmil and Japanese Flute Private Sealed.jpg",
            mime_type="image/jpeg",
            import_status="mirrored",
            processing_status="image_preview_ready",
        )
        session.add(photo)
        session.commit()
        photo_id = photo.id

    draft = client.post("/api/photo-memory-drafts", params={"limit": 1, "dry_run": "false"})
    assert draft.status_code == 200
    review_task_id = draft.json()["review_task_ids"][0]

    review = client.post(
        f"/api/tasks/{review_task_id}/submit",
        json={
            "decisions": {
                "vision_accuracy": "minor_issues",
                "accepted_visual_description": "A private family photo that Adam reviewed but sealed.",
                "question_answers": {
                    "why_this_photo_matters": "This is meaningful but should not be available downstream.",
                    "what_should_be_corrected": "Keep it sealed.",
                    "downstream_boundary": "Do not use this in retrieval or vector search.",
                },
                "adam_context_note": "Adam reviewed this as sensitive family material.",
                "privacy_level": "sealed",
                "privacy_notes": "Sealed by Adam; not for retrieval or vector handoff.",
                "ready_for_downstream": "yes",
                "truth_status": "adam_memory",
                "ocr_review_status": "not_present",
            }
        },
    )
    assert review.status_code == 200
    created = review.json()["creates_or_updates"]
    assert created["vector_handoff_status"] == "excluded_by_boundary"
    assert created["vector_handoff_record_id"] is None
    assert created["removed_machine_draft_gallery_item_id"]
    assert "photo_prompt_pair_generation" not in created
    assert created["receipt"]["vector_handoff_status"] == "excluded_by_boundary"
    assert "not eligible" in created["receipt"]["vector_handoff_reason"]

    vector_export = client.get("/api/retrieval/photo-memory-corpus/export", params={"scope": "family_private", "limit": 5})
    assert vector_export.status_code == 200
    body = vector_export.json()
    assert body["manifest"]["record_count"] == 0
    assert body["manifest"]["excluded_count"] == 1
    assert body["manifest"]["reviewed_ready_count"] == 0
    assert body["manifest"]["held_for_adam_review_count"] == 0
    assert body["manifest"]["boundary_excluded_count"] == 1
    assert body["manifest"]["exclusion_reason_counts"] == {"boundary_not_allowed_for_scope": 1}
    assert body["excluded"][0]["source_photo_id"] == photo_id
    assert body["excluded"][0]["reasons"] == ["boundary_not_allowed_for_scope"]
    assert body["excluded"][0]["review_status"] == "excluded_by_boundary"

    gallery = client.get("/api/gallery/reviewed-photos", params={"scope": "family_private", "include_drafts": "true"})
    assert gallery.status_code == 200
    assert [item for item in gallery.json()["items"] if item["source_photo_id"] == photo_id] == []


def test_photo_review_later_boundary_hold_is_not_masked_by_machine_draft():
    client, engine = build_client()
    with Session(engine) as session:
        photo = Asset(
            human_id="ASSET_REVIEWED_LATER_ADAM_FLOWERS",
            asset_type="photo",
            title="Rotmil_Scan_15_2-2018 - Adam with flowers.jpg",
            original_filename="Rotmil_Scan_15_2-2018 - Adam with flowers.jpg",
            mime_type="image/jpeg",
            import_status="mirrored",
            processing_status="image_preview_ready",
        )
        session.add(photo)
        session.commit()
        photo_id = photo.id

    draft = client.post("/api/photo-memory-drafts", params={"limit": 1, "dry_run": "false"})
    assert draft.status_code == 200
    review_task_id = draft.json()["review_task_ids"][0]

    review = client.post(
        f"/api/tasks/{review_task_id}/submit",
        json={
            "decisions": {
                "vision_accuracy": "minor_issues",
                "accepted_visual_description": "A young Adam stands outside holding yellow flowers.",
                "people": ["Adam Rotmil"],
                "places": ["Sheepscot, Maine"],
                "themes": ["flowers", "father and son memory"],
                "concrete_objects": ["yellow flowers"],
                "question_answers": {
                    "why_this_photo_matters": "This photo brings back Adam gathering flowers at Charles's place.",
                    "what_should_be_corrected": "The exact age and location still need refinement.",
                    "downstream_boundary": "Hold this until I decide the downstream boundary.",
                },
                "adam_context_note": "Adam reviewed the photo, but chose to decide downstream use later.",
                "privacy_level": "public_safe",
                "privacy_notes": "Boundary not cleared for retrieval yet.",
                "ready_for_downstream": "later",
                "truth_status": "adam_memory",
                "ocr_review_status": "not_present",
            }
        },
    )
    assert review.status_code == 200
    created = review.json()["creates_or_updates"]
    assert created["vector_handoff_status"] == "held_pending_downstream_clearance"
    assert created["photo_prompt_pair_generation"]["created_count"] == 5
    assert len(created["photo_prompt_pair_generation"]["created_task_ids"]) == 5
    assert created["receipt"]["blocked_reasons"] == ["no_downstream_use_enabled"]

    vector_export = client.get("/api/retrieval/photo-memory-corpus/export", params={"scope": "family_private", "limit": 5})
    assert vector_export.status_code == 200
    body = vector_export.json()
    assert body["manifest"]["record_count"] == 0
    assert body["manifest"]["held_for_adam_review_count"] == 0
    assert body["manifest"]["boundary_excluded_count"] == 1
    assert body["excluded"][0]["source_photo_id"] == photo_id
    assert body["excluded"][0]["review_status"] == "excluded_by_boundary"
    assert body["excluded"][0]["metadata_source"] == "photo_memory_review"
    assert body["excluded"][0]["boundary_reviewed_by"] == "adam"
    assert body["next_review_actions"][0]["review_status"] == "excluded_by_boundary"


def test_machine_photo_memory_drafts_do_not_overwrite_adam_reviewed_photo_profiles():
    client, engine = build_client()
    with Session(engine) as session:
        photo = Asset(
            human_id="ASSET_REVIEWED_HONORS",
            asset_type="photo",
            title="Rotmil Honors VIII.jpg",
            original_filename="Rotmil Honors VIII.jpg",
            mime_type="image/jpeg",
            import_status="mirrored",
            processing_status="image_preview_ready",
        )
        session.add(photo)
        session.flush()
        profile = MetadataProfile(
            target_type="asset",
            target_id=photo.id,
            profile_type="photo_memory",
            metadata_status="adam_reviewed",
            title="Adam-reviewed honors ceremony",
            summary="Adam confirmed this ceremony context.",
            adam_context_note="Human-reviewed meaning should not be replaced by a machine template.",
            truth_status="adam_memory",
            reviewed_by="adam",
        )
        session.add(profile)
        session.commit()
        photo_id = photo.id
        profile_id = profile.id

    response = client.post("/api/photo-memory-drafts", params={"limit": 1, "dry_run": "false"})
    assert response.status_code == 200
    body = response.json()
    assert body["created_count"] == 0
    assert body["candidate_count"] == 0
    assert body["created_new_count"] == 0
    assert body["review_task_ids"] == []
    assert body["candidates"] == []
    assert body["skipped"] == [
        {
            "asset_id": photo_id,
            "asset_title": "Rotmil Honors VIII.jpg",
            "metadata_profile_id": profile_id,
            "reason": "existing_human_reviewed_photo_memory",
        }
    ]

    with Session(engine) as session:
        profile = session.get(MetadataProfile, profile_id)
        assert profile is not None
        assert profile.metadata_status == "adam_reviewed"
        assert profile.title == "Adam-reviewed honors ceremony"
        assert profile.summary == "Adam confirmed this ceremony context."
        assert profile.adam_context_note == "Human-reviewed meaning should not be replaced by a machine template."
        assert profile.truth_status == "adam_memory"
        assert session.exec(select(Annotation).where(Annotation.annotation_type == "photo_memory_machine_draft")).all() == []
        assert session.exec(select(Task).where(Task.task_type == "vision_draft_review")).all() == []


def test_photo_memory_embedding_export_is_stable_jsonl_with_manifest_and_boundaries():
    client, engine = build_client()
    retrieval_origin = {
        "query": "airplane in Maine",
        "candidate_match_quality": "weak_evidence_match",
        "selection_reason": "reviewable_evidence_overlap",
        "truth_status": "no_claim",
        "not_memory_claim": True,
    }
    photo_id = _create_photo_memory(
        client,
        engine,
        human_id="ASSET_RALPH_VECTOR_EXPORT_AIRPLANE",
        title="Airplane in Maine",
        description="Adam and Charles standing beside a small airplane in Maine.",
        context="This photo anchors the memory of flying an airplane together in Maine.",
        place="Maine",
        event="small airplane flight",
        themes=["airplane", "Maine", "flight", "fatherhood"],
        retrieval_origin=retrieval_origin,
    )
    sealed_photo_id = _create_photo_memory(
        client,
        engine,
        human_id="ASSET_RALPH_VECTOR_EXPORT_SEALED",
        title="Sealed airplane memory",
        description="A sealed airplane photograph.",
        context="Private sealed context that must not be exported for family retrieval.",
        place="Maine",
        event="sealed airplane",
        themes=["airplane", "sealed"],
        privacy_level="sealed",
    )

    first = client.get("/api/retrieval/photo-memory-corpus/export", params={"scope": "family_private", "limit": 20})
    second = client.get("/api/retrieval/photo-memory-corpus/export", params={"scope": "family_private", "limit": 20})

    assert first.status_code == 200
    assert second.status_code == 200
    body = first.json()
    assert body == second.json()
    assert body["export_type"] == "photo_memory_vector_handoff"
    assert body["format"] == "jsonl"
    assert body["manifest"]["record_count"] == 1
    assert body["manifest"]["source_photo_count"] == 1
    assert body["manifest"]["excluded_count"] == 1
    assert body["manifest"]["reviewed_ready_count"] == 1
    assert body["manifest"]["retrieval_origin_record_count"] == 1
    assert body["manifest"]["retrieval_origin_no_claim_count"] == 1
    assert body["manifest"]["boundary_excluded_count"] == 1
    assert body["manifest"]["scope"] == "family_private"
    assert body["manifest"]["vector_values_included"] is False
    assert body["manifest"]["live_embedding_call"] is False
    assert body["manifest"]["preview_only"] is False
    assert body["manifest"]["not_for_downstream_vector_store"] is False
    assert body["manifest"]["content_sha256"]
    assert body["manifest"]["boundary_policy_snapshot"]["excluded_privacy_levels"] == [
        "private_sensitive",
        "sealed",
        "sensitive_living_people",
    ]
    assert body["manifest"]["next_review_actions"] == [
        {
            "source_photo_id": sealed_photo_id,
            "source_photo_title": "Sealed airplane memory",
            "review_task_id": None,
            "review_task_human_id": None,
            "review_queue": None,
            "review_status": "excluded_by_boundary",
            "reasons": ["boundary_not_allowed_for_scope"],
            "suggested_next_action": "Adjust boundary clearance before using this photo memory in downstream vector exports.",
        }
    ]
    assert body["next_review_actions"] == body["manifest"]["next_review_actions"]
    assert body["manifest"]["dedupe_policy_snapshot"] == {
        "one_record_per_source_photo": True,
        "preferred_target_order": ["memory", "metadata_profile"],
    }
    assert body["excluded"][0]["source_photo_id"] == sealed_photo_id
    assert body["excluded"][0]["reasons"] == ["boundary_not_allowed_for_scope"]
    assert body["excluded"][0]["review_status"] == "excluded_by_boundary"
    assert body["excluded"][0]["suggested_next_action"].startswith("Adjust boundary clearance")
    assert body["records"][0]["review_status"] == "reviewed_vector_ready"
    assert body["records"][0]["inclusion_reason"] == "reviewed_by_adam_and_boundary_allows_scope"
    assert body["records"][0]["metadata"]["inclusion_reason"] == "reviewed_by_adam_and_boundary_allows_scope"
    assert "boundary_reviewed_by=adam" in body["records"][0]["metadata"]["inclusion_trace"]
    assert "dedupe=one_record_per_source_photo" in body["records"][0]["metadata"]["inclusion_trace"]

    lines = [line for line in body["jsonl"].splitlines() if line.strip()]
    assert len(lines) == 1
    records = [__import__("json").loads(line) for line in lines]
    assert all(record["id"].startswith("photo-memory:") for record in records)
    assert records[0]["review_status"] == "reviewed_vector_ready"
    assert records[0]["inclusion_reason"] == "reviewed_by_adam_and_boundary_allows_scope"
    assert {record["metadata"]["source_photo_id"] for record in records} == {photo_id}
    assert {record["metadata"]["target_type"] for record in records} == {"memory"}
    assert records[0]["metadata"]["retrieval_gap_origin"] == retrieval_origin
    assert records[0]["metadata"]["inclusion_reason"] == "reviewed_by_adam_and_boundary_allows_scope"
    assert "truth_status=adam_memory" in records[0]["metadata"]["inclusion_trace"]
    assert body["records"][0]["metadata"]["retrieval_gap_origin"] == retrieval_origin
    assert all(record["metadata"]["boundary_snapshot"]["privacy_level"] == "family_private" for record in records)
    assert all(record["metadata"]["truth_status"] == "adam_memory" for record in records)
    assert all(record["embedding_plan"]["model_name"] == "pending_text_embedding" for record in records)
    assert all(record["embedding_plan"]["live_embedding_call"] is False for record in records)
    assert all(record["embedding_plan"]["vector_values_included"] is False for record in records)
    assert all("vector" not in record for record in records)
    assert all("airplane" in record["text"].lower() for record in records)

    corpus = client.get("/api/retrieval/photo-memory-corpus", params={"scope": "family_private", "limit": 20})
    assert corpus.status_code == 200
    assert corpus.json()["retrieval_origin_record_count"] == 1
    assert corpus.json()["retrieval_origin_no_claim_count"] == 1
    assert corpus.json()["records"][0]["retrieval_gap_origin"] == retrieval_origin
    assert corpus.json()["records"][0]["metadata"]["retrieval_gap_origin"] == retrieval_origin
    assert corpus.json()["records"][0]["inclusion_reason"] == "reviewed_by_adam_and_boundary_allows_scope"
    assert "scope=family_private" in corpus.json()["records"][0]["inclusion_trace"]

    search = client.get("/api/retrieval/search", params={"q": "airplane in Maine", "scope": "family_private", "limit": 3})
    assert search.status_code == 200
    assert search.json()["results"][0]["source_photo_id"] == photo_id
    assert search.json()["results"][0]["retrieval_gap_origin"] == retrieval_origin


def test_reviewed_photo_memory_demo_readiness_is_truthful_before_and_after_adam_review():
    client, engine = build_client()

    with Session(engine) as session:
        photo = Asset(
            human_id="ASSET_REVIEWED_DEMO_NEEDS_CONTEXT",
            asset_type="photo",
            title="Unreviewed dock photo",
            original_filename="unreviewed-dock.jpg",
            mime_type="image/jpeg",
            processing_status="image_preview_ready",
        )
        session.add(photo)
        session.flush()
        task = Task(
            human_id="TASK_REVIEWED_DEMO_CONTEXT",
            task_type="photo_context",
            target_type="asset",
            target_id=photo.id,
            queue="photo_assets_needing_context",
            status="ready",
            input_payload={"asset_id": photo.id, "asset_title": photo.title, "asset_type": "photo"},
            created_by="test",
        )
        session.add(task)
        session.commit()
        task_id = task.id
        photo_id = photo.id

    not_ready = client.get(
        "/api/retrieval/photo-memory-corpus/reviewed-demo-readiness",
        params={"scope": "family_private", "limit": 5},
    )
    assert not_ready.status_code == 200
    body = not_ready.json()
    assert body["demo_type"] == "reviewed_photo_memory_demo_readiness"
    assert body["status"] == "needs_adam_review"
    assert body["can_show_reviewed_vector_memory"] is False
    assert body["reviewed_vector_ready_count"] == 0
    assert body["blockers"] == ["no_reviewed_vector_ready_photo_memory"]
    assert body["safety_policy"]["does_not_fabricate_adam_memory"] is True
    assert body["safety_policy"]["does_not_mutate_state"] is True
    assert body["safety_policy"]["no_live_embedding_call"] is True
    assert body["safety_policy"]["no_fine_tuning_api_call"] is True
    assert body["safety_policy"]["outputs_truth_status"] == "no_claim_until_adam_context_submission"
    assert body["sample_reviewed_records"] == []
    assert body["candidate_actions"][0]["action_type"] == "open_photo_context_task"
    assert body["candidate_actions"][0]["task_id"] == task_id
    assert body["candidate_actions"][0]["source_photo_id"] == photo_id
    assert body["candidate_actions"][0]["not_memory_claim"] is True
    assert body["candidate_actions"][0]["truth_status_before_review"] == "no_claim"

    reviewed_photo_id = _create_photo_memory(
        client,
        engine,
        human_id="ASSET_REVIEWED_DEMO_READY",
        title="Reviewed airplane demo",
        description="Adam and Charles standing beside a small airplane in Maine.",
        context="Adam reviewed this as the memory of flying together in Maine.",
        place="Maine",
        event="small airplane flight",
        themes=["airplane", "Maine", "fatherhood"],
    )
    ready = client.get(
        "/api/retrieval/photo-memory-corpus/reviewed-demo-readiness",
        params={"scope": "family_private", "limit": 5},
    )
    assert ready.status_code == 200
    ready_body = ready.json()
    assert ready_body["status"] == "ready"
    assert ready_body["can_show_reviewed_vector_memory"] is True
    assert ready_body["reviewed_vector_ready_count"] == 1
    assert ready_body["blockers"] == []
    assert ready_body["safety_policy"]["outputs_truth_status"] == "reviewed_photo_memory_records_only"
    sample = ready_body["sample_reviewed_records"][0]
    assert sample["source_photo_id"] == reviewed_photo_id
    assert sample["review_status"] == "reviewed_vector_ready"
    assert sample["truth_status"] == "adam_memory"
    assert sample["inclusion_reason"] == "reviewed_by_adam_and_boundary_allows_scope"
    assert "dedupe=one_record_per_source_photo" in sample["inclusion_trace"]
    assert sample["vector_values_included"] is False
    assert sample["live_embedding_call"] is False


def test_photo_review_priority_summary_orders_fastest_paths_and_preserves_no_claim_policy():
    client, engine = build_client()

    with Session(engine) as session:
        draft_photo = Asset(
            human_id="ASSET_PRIORITY_DRAFT",
            asset_type="photo",
            title="Charles with Japanese flute",
            original_filename="flute.jpg",
            mime_type="image/jpeg",
            processing_status="image_preview_ready",
        )
        retrieval_photo = Asset(
            human_id="ASSET_PRIORITY_RETRIEVAL",
            asset_type="photo",
            title="Airplane in Maine",
            original_filename="airplane-maine.jpg",
            mime_type="image/jpeg",
            processing_status="image_preview_ready",
        )
        context_photo = Asset(
            human_id="ASSET_PRIORITY_CONTEXT",
            asset_type="photo",
            title="Old Orchard beach",
            original_filename="beach.jpg",
            mime_type="image/jpeg",
            processing_status="image_preview_ready",
        )
        slow_photo = Asset(
            human_id="ASSET_PRIORITY_SLOW_DRAFT",
            asset_type="photo",
            title="Unscaffolded photo review",
            original_filename="slow.jpg",
            mime_type="image/jpeg",
            processing_status="image_preview_ready",
        )
        session.add_all([draft_photo, retrieval_photo, context_photo, slow_photo])
        session.flush()
        session.add_all(
            [
                Task(
                    human_id="TASK_PRIORITY_RETRIEVAL",
                    task_type="photo_context",
                    target_type="asset",
                    target_id=retrieval_photo.id,
                    queue="photo_assets_needing_context",
                    priority=99,
                    input_payload={
                        "asset_id": retrieval_photo.id,
                        "asset_title": retrieval_photo.title,
                        "retrieval_gap_origin": {
                            "query": "airplane in Maine",
                            "truth_status": "no_claim",
                            "not_memory_claim": True,
                        },
                    },
                    created_by="test",
                ),
                Task(
                    human_id="TASK_PRIORITY_DRAFT",
                    task_type="vision_draft_review",
                    target_type="asset",
                    target_id=draft_photo.id,
                    queue="vision_drafts_needing_review",
                    priority=10,
                    input_payload={
                        "asset_id": draft_photo.id,
                        "asset_title": draft_photo.title,
                        "source_photo_memory_draft": True,
                        "vision_draft": {"visual_summary": "Charles plays the Japanese flute at home."},
                    },
                    created_by="test",
                ),
                Task(
                    human_id="TASK_PRIORITY_CONTEXT",
                    task_type="photo_context",
                    target_type="asset",
                    target_id=context_photo.id,
                    queue="photo_assets_needing_context",
                    priority=90,
                    input_payload={"asset_id": context_photo.id, "asset_title": context_photo.title},
                    created_by="test",
                ),
                Task(
                    human_id="TASK_PRIORITY_SLOW_DRAFT",
                    task_type="vision_draft_review",
                    target_type="asset",
                    target_id=slow_photo.id,
                    queue="vision_drafts_needing_review",
                    priority=100,
                    input_payload={"asset_id": slow_photo.id, "asset_title": slow_photo.title},
                    created_by="test",
                ),
            ]
        )
        session.commit()
        before_task_count = len(session.exec(select(Task)).all())

    fastest = client.get("/api/assets/photo-review-priority", params={"focus": "fastest_vector", "limit": 10})
    assert fastest.status_code == 200
    body = fastest.json()
    assert body["summary_type"] == "photo_review_priority"
    assert body["review_policy"] == "prioritization_only_no_memory_claim_until_submit"
    assert body["throughput_policy"] == "rank_by_fastest_review_path_then_missing_adam_fields_then_downstream_payoff"
    assert body["does_not_mutate_state"] is True
    assert body["does_not_create_memory_claim"] is True
    assert body["no_live_model_call"] is True
    assert body["no_live_embedding_call"] is True
    assert body["completion_signal"] == "open_top_photo_task_and_reduce_missing_adam_fields_or_submit_ready_count_increases"
    assert body["content_sha256"]
    assert "photo_review_priority:" in body["export_preview_yaml"]
    assert body["export_preview_sha256"]
    assert body["reported_count"] == 3
    assert [item["task_human_id"] for item in body["items"]] == [
        "TASK_PRIORITY_DRAFT",
        "TASK_PRIORITY_RETRIEVAL",
        "TASK_PRIORITY_CONTEXT",
    ]
    assert [item["path_label"] for item in body["items"]] == [
        "Fastest vector path",
        "Retrieval context path",
        "Context path",
    ]

    first = body["items"][0]
    assert first["sequence_number"] == 1
    assert first["source_photo_title"] == "Charles with Japanese flute"
    assert first["truth_status_before_review"] == "system_inference_requires_adam_review"
    assert first["preview_ready"] is True
    assert first["not_memory_claim"] is True
    assert first["missing_adam_field_count"] == 3
    assert first["downstream_payoff_score"] > body["items"][2]["downstream_payoff_score"]
    assert first["next_action"] == "open_review_task"
    assert first["completion_signal"] == body["completion_signal"]
    assert first["ranking_inputs"]["path_rank"] == 0
    assert first["ranking_inputs"]["preview_ready"] is True
    assert first["ranking_inputs"]["missing_adam_field_count"] == 3
    assert first["submit_outcome_badge"] == "On submit: vector-safe memory"
    assert first["submit_outcome_label"] == "Creates vector-safe memory after Adam review"
    assert first["vector_handoff_preview_status"] == "held_until_adam_context"
    assert "reviewed-only memory/vector handoff" in first["submit_outcome_detail"]
    assert first["missing_fields"] == [
        "Adam context or answers",
        "Downstream choice: set Yes for retrieval",
        "Boundary review for family/public use",
    ]
    assert first["safeguards"] == ["No memory claim yet", "No vector write before submit", "Not SFT/DPO training material"]

    second = body["items"][1]
    assert second["retrieval_query"] == "airplane in Maine"
    assert second["preview_ready"] is True
    assert second["missing_adam_field_count"] == 4
    assert second["ranking_inputs"]["has_retrieval_query"] is True
    assert second["downstream_payoff_score"] > 0
    assert second["truth_status_before_review"] == "no_claim"
    assert second["submit_outcome_badge"] == "On submit: closes retrieval gap"
    assert second["submit_outcome_label"] == "Creates reviewed context for this retrieval gap"
    assert second["vector_handoff_preview_status"] == "eligible_after_required_context"
    assert "without making a training example" in second["submit_outcome_detail"]
    assert second["missing_fields"] == [
        "Reviewed visual description",
        "Adam context or answers",
        "Downstream choice: set Yes for retrieval",
        "Boundary review for family/public use",
    ]
    assert "Filename/title evidence only until reviewed" in second["safeguards"]
    assert "airplane in Maine" in second["why_first"]

    all_paths = client.get("/api/assets/photo-review-priority", params={"focus": "all", "limit": 10})
    assert all_paths.status_code == 200
    assert [item["task_human_id"] for item in all_paths.json()["items"]] == [
        "TASK_PRIORITY_DRAFT",
        "TASK_PRIORITY_RETRIEVAL",
        "TASK_PRIORITY_CONTEXT",
        "TASK_PRIORITY_SLOW_DRAFT",
    ]

    priority_yaml = client.get("/api/assets/photo-review-priority/yaml", params={"focus": "fastest_vector", "limit": 10})
    assert priority_yaml.status_code == 200
    assert "photo_review_priority:" in priority_yaml.text
    assert "throughput_policy: rank_by_fastest_review_path_then_missing_adam_fields_then_downstream_payoff" in priority_yaml.text

    contract = client.get("/api/runtime-contract").json()
    assert "/api/assets/photo-review-priority" in contract["required_response_fields"]
    for field in ["throughput_policy", "completion_signal", "content_sha256", "export_preview_yaml"]:
        assert field in contract["required_response_fields"]["/api/assets/photo-review-priority"]

    with Session(engine) as session:
        assert len(session.exec(select(Task)).all()) == before_task_count
