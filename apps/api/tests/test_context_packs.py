from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app.db.session import get_session
from app.main import app
from app.models import Asset, Boundary, ContextPack, ContextPackItem, Memory, MemorySource, MetadataProfile, Segment, Task


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


def test_context_pack_builder_excludes_blocked_items_and_snapshots_boundaries():
    client, engine = build_client()
    with Session(engine) as session:
        asset = Asset(
            human_id="ASSET_CTX",
            asset_type="text",
            title="Context source",
            import_status="mirrored",
            maturity_level="L3_reviewed",
        )
        session.add(asset)
        session.flush()
        allowed = Segment(
            human_id="SEG_ALLOWED",
            asset_id=asset.id,
            segment_type="text_chunk",
            title="Allowed chunk",
            text_content="The house is quiet and the refrigerator makes a little drama.",
        )
        blocked = Segment(
            human_id="SEG_BLOCKED",
            asset_id=asset.id,
            segment_type="text_chunk",
            title="Blocked chunk",
            text_content="A private detail that needs redaction.",
        )
        session.add(allowed)
        session.add(blocked)
        session.flush()
        session.add(
            Boundary(
                target_type="segment",
                target_id=allowed.id,
                privacy_level="family_private",
                retrievable_in_chat=True,
                usable_for_voice_context=True,
                notes="OK for local context pack use.",
            )
        )
        session.add(
            Boundary(
                target_type="segment",
                target_id=blocked.id,
                privacy_level="family_private",
                retrievable_in_chat=True,
                usable_for_voice_context=True,
                redaction_required=True,
                notes="Needs redaction before use.",
            )
        )
        session.commit()
        allowed_id = allowed.id
        blocked_id = blocked.id

    response = client.post(
        "/api/context-packs/build",
        json={
            "user_intent": "gold_voice_generation",
            "requested_voice_mode": "father_to_adam",
            "truth_mode": "adam_expert_reconstruction",
            "items": [
                {"item_type": "segment", "item_id": allowed_id, "role": "source_evidence", "rank": 1},
                {"item_type": "segment", "item_id": blocked_id, "role": "source_evidence", "rank": 2},
            ],
            "allowed_facts": ["Adam is asking for a short note."],
            "blocked_facts": ["Do not name private third parties."],
            "style_guidance": {"avoid": ["therapy language"]},
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["included_count"] == 1
    assert body["excluded_count"] == 1

    with Session(engine) as session:
        context = session.get(ContextPack, body["context_pack_id"])
        assert context is not None
        assert context.boundaries_snapshot["boundary_status"] == "blocked"
        assert context.boundaries_snapshot["blocked_facts"] == ["Do not name private third parties."]
        assert "refrigerator" in "\n".join(context.allowed_facts)

        items = session.exec(select(ContextPackItem).where(ContextPackItem.context_pack_id == context.id)).all()
        assert len(items) == 2
        assert {item.included for item in items} == {True, False}
        excluded = next(item for item in items if not item.included)
        assert excluded.exclusion_reason == "redaction required before context-pack use"


def test_context_pack_builder_excludes_missing_boundaries_by_default():
    client, engine = build_client()
    with Session(engine) as session:
        asset = Asset(
            human_id="ASSET_CTX_MISSING_BOUNDARY",
            asset_type="text",
            title="No boundary source",
            import_status="mirrored",
            maturity_level="L3_reviewed",
        )
        session.add(asset)
        session.flush()
        segment = Segment(
            human_id="SEG_MISSING_BOUNDARY",
            asset_id=asset.id,
            segment_type="text_chunk",
            title="Missing boundary chunk",
            text_content="This should not appear without an explicit boundary.",
        )
        session.add(segment)
        session.commit()
        segment_id = segment.id

    response = client.post(
        "/api/context-packs/build",
        json={
            "user_intent": "gold_voice_generation",
            "requested_voice_mode": "father_to_adam",
            "truth_mode": "adam_expert_reconstruction",
            "items": [{"item_type": "segment", "item_id": segment_id, "role": "source_evidence", "rank": 1}],
            "allowed_facts": [],
            "blocked_facts": [],
            "style_guidance": {},
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["included_count"] == 0
    assert body["excluded_count"] == 1

    with Session(engine) as session:
        context = session.get(ContextPack, body["context_pack_id"])
        assert context is not None
        assert context.boundaries_snapshot["boundary_status"] == "blocked"
        excluded = context.boundaries_snapshot["excluded_items"][0]
        assert excluded["reason"] == "boundary_missing"
        assert "explicit boundary" not in "\n".join(context.allowed_facts)


def test_context_pack_builder_uses_reviewed_photo_context_not_filename_only():
    client, engine = build_client()
    with Session(engine) as session:
        reviewed_photo = Asset(
            human_id="ASSET_PHOTO_AIRPLANE",
            asset_type="photo",
            title="Airplane in Maine",
            original_filename="airplane-maine.jpg",
            import_status="mirrored",
            processing_status="image_preview_ready",
            maturity_level="L3_reviewed",
        )
        sealed_photo = Asset(
            human_id="ASSET_PHOTO_SEALED",
            asset_type="photo",
            title="Sealed family photo",
            original_filename="sealed-family.jpg",
            import_status="mirrored",
            processing_status="image_preview_ready",
            maturity_level="L3_reviewed",
        )
        session.add(reviewed_photo)
        session.add(sealed_photo)
        session.flush()
        session.add(
            Boundary(
                target_type="asset",
                target_id=reviewed_photo.id,
                privacy_level="family_private",
                retrievable_in_chat=True,
                usable_for_voice_context=True,
                usable_for_eval=True,
                notes="Adam-cleared family-private photo context.",
                reviewed_by="adam",
            )
        )
        session.add(
            Boundary(
                target_type="asset",
                target_id=sealed_photo.id,
                privacy_level="sealed",
                retrievable_in_chat=False,
                usable_for_voice_context=False,
                notes="Do not use in context packs.",
                reviewed_by="adam",
            )
        )
        session.add(
            MetadataProfile(
                target_type="asset",
                target_id=reviewed_photo.id,
                profile_type="photo_memory",
                metadata_status="adam_reviewed",
                title="Airplane in Maine reviewed photo",
                summary="Adam and Charles are beside a small airplane in Maine.",
                adam_context_note="Adam says this anchors the family memory of flying in Maine together.",
                truth_status="adam_memory",
                date_label="late 1980s",
                date_confidence="approximate",
                people=["Adam", "Charles"],
                places=["Maine"],
                themes=["airplane", "fatherhood", "adventure"],
                concrete_objects=["small airplane", "runway", "Maine trees"],
                open_questions=["Which airfield was this?"],
                reviewed_by="adam",
            )
        )
        session.add(
            MetadataProfile(
                target_type="asset",
                target_id=reviewed_photo.id,
                profile_type="photo_memory",
                metadata_status="machine_draft_needs_adam_review",
                title="Machine draft airplane photo",
                summary="System guess: this is a celebrity airport event.",
                adam_context_note="System-inferred story that Adam has not reviewed.",
                truth_status="system_inference",
                reviewed_by="system_draft",
            )
        )
        session.add(
            MetadataProfile(
                target_type="asset",
                target_id=sealed_photo.id,
                profile_type="photo_memory",
                metadata_status="adam_reviewed",
                title="Sealed photo reviewed profile",
                summary="This sealed photo context must not be included.",
                adam_context_note="Private sealed context.",
                truth_status="adam_memory",
                reviewed_by="adam",
            )
        )
        memory = Memory(
            human_id="MEM_AIRPLANE_MAINE",
            title="Flying in Maine",
            summary="A reviewed Adam memory about standing with Charles near the airplane before the flight.",
            truth_status="adam_memory",
            reliability="high",
            themes=["airplane", "Maine", "fatherhood"],
            open_questions=["Who took the photograph?"],
        )
        session.add(memory)
        session.flush()
        session.add(
            MemorySource(
                memory_id=memory.id,
                source_type="asset",
                source_id=reviewed_photo.id,
                role="photo_context",
                confidence="high",
            )
        )
        session.commit()
        reviewed_photo_id = reviewed_photo.id
        sealed_photo_id = sealed_photo.id

    response = client.post(
        "/api/context-packs/build",
        json={
            "user_intent": "grounded_voice_response",
            "requested_voice_mode": "father_to_adam",
            "truth_mode": "adam_memory",
            "items": [
                {"item_type": "asset", "item_id": reviewed_photo_id, "role": "photo_memory_context", "rank": 1},
                {"item_type": "asset", "item_id": sealed_photo_id, "role": "photo_memory_context", "rank": 2},
            ],
            "allowed_facts": [],
            "blocked_facts": ["Do not use sealed family photo context."],
            "style_guidance": {"context_pack_use": "retrieval_grounding_only"},
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["included_count"] == 1
    assert body["excluded_count"] == 1

    audit_response = client.get("/api/context-packs/photo-context-readiness-audit")
    assert audit_response.status_code == 200
    audit = audit_response.json()
    assert audit["audit_type"] == "photo_context_pack_readiness_audit"
    assert audit["review_policy"] == "read_only_context_pack_fact_projection"
    assert audit["does_not_mutate_state"] is True
    assert audit["requires_boundary_clearance"] is True
    assert audit["uses_reviewed_photo_context"] is True
    assert audit["uses_linked_reviewed_memories"] is True
    assert audit["excludes_system_inference_drafts"] is True
    assert audit["ready_context_pack_asset_count"] == 1
    assert audit["blocked_context_pack_asset_count"] == 1
    assert audit["filename_only_fallback_count"] == 0
    assert audit["system_inference_leak_count"] == 0
    assert len(audit["content_sha256"]) == 64
    reviewed_item = next(item for item in audit["items"] if item["asset_id"] == reviewed_photo_id)
    assert reviewed_item["boundary_included"] is True
    assert reviewed_item["includes_reviewed_photo_context"] is True
    assert reviewed_item["includes_linked_reviewed_memory"] is True
    assert reviewed_item["system_inference_draft_excluded"] is True
    assert reviewed_item["filename_only_fallback"] is False
    assert "Adam and Charles are beside a small airplane in Maine." in reviewed_item["fact_preview"]
    sealed_item = next(item for item in audit["items"] if item["asset_id"] == sealed_photo_id)
    assert sealed_item["boundary_included"] is False
    assert sealed_item["boundary_reason"] == "privacy_level=sealed"

    with Session(engine) as session:
        context = session.get(ContextPack, body["context_pack_id"])
        assert context is not None
        facts = "\n".join(context.allowed_facts)
        assert "Adam and Charles are beside a small airplane in Maine." in facts
        assert "Adam says this anchors the family memory of flying in Maine together." in facts
        assert "A reviewed Adam memory about standing with Charles near the airplane before the flight." in facts
        assert "truth_status: adam_memory" in facts
        assert "people: Adam, Charles" in facts
        assert "concrete_objects: small airplane, runway, Maine trees" in facts
        assert "open_questions: Which airfield was this?" in facts
        assert "System guess: this is a celebrity airport event." not in facts
        assert "This sealed photo context must not be included." not in facts
        assert facts != "Airplane in Maine"
        assert context.boundaries_snapshot["boundary_status"] == "blocked"
        excluded = context.boundaries_snapshot["excluded_items"][0]
        assert excluded["item_id"] == sealed_photo_id
        assert excluded["reason"] == "privacy_level=sealed"


def test_photo_context_pack_audit_surfaces_machine_drafts_needing_adam_review():
    client, engine = build_client()
    with Session(engine) as session:
        photo = Asset(
            human_id="ASSET_PHOTO_HELD_DRAFT",
            asset_type="photo",
            title="Rotmil Honors VIII.jpg",
            original_filename="Rotmil Honors VIII.jpg",
            mime_type="image/jpeg",
            import_status="mirrored",
            processing_status="image_preview_ready",
            maturity_level="L2_needs_review",
        )
        session.add(photo)
        session.flush()
        profile = MetadataProfile(
            target_type="asset",
            target_id=photo.id,
            profile_type="photo_memory",
            metadata_status="machine_draft_needs_adam_review",
            title="Photo memory draft: honors ceremony",
            summary="Machine draft suggests Charles is speaking at an honors ceremony.",
            adam_context_note="Machine-only draft; Adam has not reviewed this meaning.",
            truth_status="system_inference",
            reviewed_by="system_draft",
        )
        session.add(profile)
        session.flush()
        task = Task(
            human_id="TASK_HELD_PHOTO_MEMORY_DRAFT",
            task_type="vision_draft_review",
            target_type="metadata_profile",
            target_id=profile.id,
            queue="vision_drafts_needing_review",
            input_payload={
                "asset_id": photo.id,
                "asset_title": photo.title,
                "source_photo_memory_draft": True,
                "metadata_profile_id": profile.id,
            },
            created_by="test",
        )
        session.add(task)
        session.commit()
        photo_id = photo.id
        profile_id = profile.id
        task_id = task.id

    audit_response = client.get("/api/context-packs/photo-context-readiness-audit", params={"limit": 10})

    assert audit_response.status_code == 200
    audit = audit_response.json()
    assert audit["audit_type"] == "photo_context_pack_readiness_audit"
    assert audit["readiness_status"] == "needs_adam_review"
    assert audit["reviewed_photo_profile_count"] == 0
    assert audit["ready_context_pack_asset_count"] == 0
    assert audit["machine_draft_profile_count"] == 1
    assert audit["held_for_adam_review_count"] == 1
    assert audit["next_review_action_count"] == 1
    assert audit["system_inference_leak_count"] == 0
    assert audit["items"] == []
    action = audit["next_review_actions"][0]
    assert action["action_type"] == "open_photo_memory_review_task"
    assert action["reason"] == "promote_machine_draft_with_adam_review"
    assert action["review_status"] == "held_for_adam_review"
    assert action["metadata_profile_id"] == profile_id
    assert action["source_photo_id"] == photo_id
    assert action["source_photo_title"] == "Rotmil Honors VIII.jpg"
    assert action["review_task_id"] == task_id
    assert action["review_task_human_id"] == "TASK_HELD_PHOTO_MEMORY_DRAFT"
    assert action["review_queue"] == "vision_drafts_needing_review"
    assert "Adam-authored context" in action["suggested_next_action"]
    assert len(audit["content_sha256"]) == 64


def test_real_photo_context_submit_feeds_context_pack_with_photo_memory_profile_shape():
    client, engine = build_client()
    with Session(engine) as session:
        photo = Asset(
            human_id="ASSET_PHOTO_REAL_SUBMIT",
            asset_type="photo",
            title="Airfield day",
            original_filename="airfield-day.jpg",
            mime_type="image/jpeg",
            import_status="mirrored",
            processing_status="image_preview_ready",
            maturity_level="L2_needs_review",
        )
        session.add(photo)
        session.flush()
        task = Task(
            human_id="TASK_PHOTO_REAL_SUBMIT",
            task_type="photo_context",
            target_type="asset",
            target_id=photo.id,
            queue="photo_assets_needing_context",
            input_payload={"asset_id": photo.id, "asset_title": photo.title, "asset_type": "photo"},
            created_by="test",
        )
        session.add(task)
        session.commit()
        photo_id = photo.id
        task_id = task.id

    submit = client.post(
        f"/api/tasks/{task_id}/submit",
        json={
            "decisions": {
                "visible_people": ["Adam", "Charles"],
                "place": "Maine",
                "date_or_range": "late 1980s",
                "date_confidence": "approximate",
                "event": "airfield visit",
                "themes": ["airplane", "Maine", "fatherhood"],
                "concrete_objects": ["small airplane", "runway"],
                "visual_description_correction": "Adam and Charles stand beside a small airplane in Maine.",
                "invisible_context_note": "Adam remembers this as the day Charles made flying feel possible and funny.",
                "privacy_level": "family_private",
                "privacy_notes": "Adam-cleared family context.",
                "ready_for_downstream": "yes",
                "gallery_eligibility": "family_private",
            }
        },
    )
    assert submit.status_code == 200

    with Session(engine) as session:
        session.add(
            MetadataProfile(
                target_type="asset",
                target_id=photo_id,
                profile_type="photo_memory",
                metadata_status="machine_draft_needs_adam_review",
                title="Machine draft that should not leak",
                summary="System guess that should stay out of context packs.",
                truth_status="system_inference",
                reviewed_by="system_draft",
            )
        )
        session.commit()

    response = client.post(
        "/api/context-packs/build",
        json={
            "user_intent": "grounded_voice_response",
            "requested_voice_mode": "father_to_adam",
            "truth_mode": "adam_memory",
            "items": [{"item_type": "asset", "item_id": photo_id, "role": "photo_memory_context", "rank": 1}],
            "allowed_facts": [],
            "blocked_facts": [],
            "style_guidance": {"context_pack_use": "retrieval_grounding_only"},
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["included_count"] == 1
    assert body["excluded_count"] == 0

    audit_response = client.get("/api/context-packs/photo-context-readiness-audit")
    assert audit_response.status_code == 200
    audit = audit_response.json()
    assert audit["ready_context_pack_asset_count"] == 1
    assert audit["filename_only_fallback_count"] == 0
    assert audit["system_inference_leak_count"] == 0

    with Session(engine) as session:
        profile = session.exec(
            select(MetadataProfile)
            .where(MetadataProfile.target_id == photo_id)
            .where(MetadataProfile.metadata_status == "adam_reviewed")
        ).one()
        assert profile.profile_type == "photo_memory"
        context = session.get(ContextPack, body["context_pack_id"])
        assert context is not None
        facts = "\n".join(context.allowed_facts)
        assert "Adam and Charles stand beside a small airplane in Maine." in facts
        assert "Adam remembers this as the day Charles made flying feel possible and funny." in facts
        assert "System guess that should stay out of context packs." not in facts
        assert facts != "Airfield day"
