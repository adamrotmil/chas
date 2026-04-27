from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app.db.session import get_session
from app.main import app
from app.models import Asset, Boundary, ContextPack, ContextPackItem, Segment


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
