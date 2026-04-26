from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.db.session import get_session
from app.main import app


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
    return TestClient(app)


def test_entities_can_be_created_listed_and_updated():
    client = build_client()

    created = client.post(
        "/api/entities",
        json={
            "entity_type": "person",
            "canonical_name": "Cathryn",
            "description": "A person connected to Charles's archive.",
            "relationship_to_charles": "family",
            "relationship_to_adam": "family",
            "confidence": "medium",
        },
    )

    assert created.status_code == 200
    body = created.json()
    assert body["canonical_name"] == "Cathryn"
    assert body["human_id"].startswith("CR_ENTITY_CATHRYN")

    listed = client.get("/api/entities?entity_type=person")
    assert listed.status_code == 200
    assert [entity["canonical_name"] for entity in listed.json()] == ["Cathryn"]

    updated = client.patch(
        f"/api/entities/{body['id']}",
        json={"relationship_to_charles": "poet Charles read", "confidence": "high"},
    )

    assert updated.status_code == 200
    assert updated.json()["relationship_to_charles"] == "poet Charles read"
    assert updated.json()["confidence"] == "high"
