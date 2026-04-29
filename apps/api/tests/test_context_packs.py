from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app.db.session import get_session
from app.main import app
from app.models import Asset, Boundary, ContextPack, ContextPackItem, Memory, MemorySource, MetadataProfile, Segment


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
                profile_type="photo_context",
                metadata_status="reviewed",
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
                profile_type="photo_context",
                metadata_status="machine_draft",
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
                profile_type="photo_context",
                metadata_status="reviewed",
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
