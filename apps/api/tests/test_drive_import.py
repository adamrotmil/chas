from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select
from fastapi.testclient import TestClient

from app.db.session import get_session
from app.main import app
from app.models import Annotation, Asset, AssetSnapshot, Boundary, ExternalRef, ObjectFile, Task


def build_client():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)

    def override_session():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_session] = override_session
    return TestClient(app), engine


def drive_payload(name: str = "Maine porch photo.jpg") -> dict:
    return {
        "files": [
            {
                "drive_file_id": "drive-file-123",
                "name": name,
                "mime_type": "image/jpeg",
                "web_view_link": "https://drive.google.com/file/d/drive-file-123/view",
                "icon_link": "https://drive-thirdparty.googleusercontent.com/icon",
                "thumbnail_link": "https://lh3.googleusercontent.com/thumb",
                "size_bytes": 2048,
                "md5_checksum": "abc123",
                "sha256_checksum": "def456",
                "created_time": "2026-04-01T10:00:00Z",
                "modified_time": "2026-04-02T10:00:00Z",
                "parents": ["parent-folder"],
                "picker_document": {"id": "drive-file-123"},
                "drive_metadata": {"version": "7"},
            }
        ],
        "imported_by": "adam",
    }


def test_drive_import_creates_asset_provenance_boundary_task_and_annotation():
    client, engine = build_client()

    response = client.post("/api/imports/drive", json=drive_payload())

    assert response.status_code == 200
    body = response.json()
    assert body["created_count"] == 1
    assert body["existing_count"] == 0
    imported = body["imported"][0]
    assert imported["asset_type"] == "photo"
    assert imported["task_id"]

    with Session(engine) as session:
        asset = session.get(Asset, imported["asset_id"])
        assert asset is not None
        assert asset.source_system == "google_drive"
        assert asset.import_status == "drive_metadata_imported"
        assert asset.processing_status == "needs_triage"
        assert asset.maturity_level == "L0_source_seen"

        external_ref = session.get(ExternalRef, imported["external_ref_id"])
        assert external_ref is not None
        assert external_ref.external_id == "drive-file-123"
        assert external_ref.metadata_json["drive_md5_checksum"] == "abc123"

        object_file = session.get(ObjectFile, imported["object_file_id"])
        assert object_file is not None
        assert object_file.storage_provider == "google_drive"
        assert object_file.uri == "gdrive://files/drive-file-123"

        snapshot = session.get(AssetSnapshot, imported["asset_snapshot_id"])
        assert snapshot is not None
        assert snapshot.snapshot_type == "drive_metadata"
        assert snapshot.object_file_id == object_file.id

        boundary = session.get(Boundary, imported["boundary_id"])
        assert boundary is not None
        assert boundary.privacy_level == "unreviewed"
        assert boundary.summarizable is True
        assert boundary.searchable is False

        task = session.get(Task, imported["task_id"])
        assert task is not None
        assert task.task_type == "asset_triage"
        assert task.queue == "drive_import_triage"
        assert task.target_id == asset.id

        annotation = session.get(Annotation, imported["annotation_id"])
        assert annotation is not None
        assert annotation.annotation_type == "drive_metadata_import"
        assert annotation.creates_or_updates["asset_id"] == asset.id


def test_drive_import_is_idempotent_for_existing_drive_file():
    client, engine = build_client()

    first = client.post("/api/imports/drive", json=drive_payload())
    second = client.post("/api/imports/drive", json=drive_payload(name="Renamed porch photo.jpg"))

    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["created_count"] == 0
    assert second.json()["existing_count"] == 1

    with Session(engine) as session:
        assert len(session.exec(select(Asset)).all()) == 1
        assert len(session.exec(select(ExternalRef)).all()) == 1
        assert len(session.exec(select(Task)).all()) == 1
        assert len(session.exec(select(AssetSnapshot)).all()) == 1
        asset = session.exec(select(Asset)).one()
        assert asset.title == "Renamed porch photo.jpg"
