import asyncio
from io import BytesIO
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app.config import settings
from app.db.session import get_session
from app.main import app
from app.models import Annotation, Asset, AssetSnapshot, ObjectFile
from app.services import asset_mirror
from app.services.asset_mirror import mirror_upload_for_asset


def build_client(tmp_path: Path):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    settings.storage_root = str(tmp_path / "storage")
    app.dependency_overrides.clear()

    def override_session():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_session] = override_session
    return TestClient(app), engine


def drive_payload() -> dict:
    return {
        "files": [
            {
                "drive_file_id": "drive-file-123",
                "name": "Maine porch photo.jpg",
                "mime_type": "image/jpeg",
                "web_view_link": "https://drive.google.com/file/d/drive-file-123/view",
                "size_bytes": 2048,
                "md5_checksum": "abc123",
                "created_time": "2026-04-01T10:00:00Z",
                "modified_time": "2026-04-02T10:00:00Z",
                "parents": ["parent-folder"],
                "picker_document": {"id": "drive-file-123"},
                "drive_metadata": {"version": "7"},
            }
        ],
        "imported_by": "adam",
    }


def test_asset_mirror_upload_creates_local_object_snapshot_and_annotation(tmp_path):
    client, engine = build_client(tmp_path)
    imported = client.post("/api/imports/drive", json=drive_payload()).json()["imported"][0]

    response = client.post(
        f"/api/assets/{imported['asset_id']}/mirror/upload",
        data={
            "source_system": "google_drive",
            "source_uri": "https://drive.google.com/file/d/drive-file-123/view",
            "drive_file_id": "drive-file-123",
            "drive_mime_type": "image/jpeg",
            "source_modified_time": "2026-04-02T10:00:00Z",
        },
        files={"file": ("Maine porch photo.jpg", b"hello mirror", "image/jpeg")},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["created"] is True
    assert body["byte_size"] == len(b"hello mirror")
    assert body["object_key"].startswith("source_mirror/google_drive/")

    mirrored_path = tmp_path / "storage" / body["object_key"]
    assert mirrored_path.read_bytes() == b"hello mirror"

    with Session(engine) as session:
        asset = session.get(Asset, imported["asset_id"])
        assert asset is not None
        assert asset.import_status == "mirrored"
        assert asset.maturity_level == "L1_mirrored"

        object_file = session.get(ObjectFile, body["object_file_id"])
        assert object_file is not None
        assert object_file.storage_provider == "local"
        assert object_file.metadata_json["mirror_status"] == "mirrored"

        snapshot = session.get(AssetSnapshot, body["asset_snapshot_id"])
        assert snapshot is not None
        assert snapshot.snapshot_type == "source_mirror"
        assert snapshot.object_file_id == object_file.id

        annotation = session.get(Annotation, body["annotation_id"])
        assert annotation is not None
        assert annotation.annotation_type == "asset_mirrored"


def test_asset_mirror_upload_is_idempotent_for_same_source_snapshot(tmp_path):
    client, engine = build_client(tmp_path)
    imported = client.post("/api/imports/drive", json=drive_payload()).json()["imported"][0]
    data = {
        "source_system": "google_drive",
        "drive_file_id": "drive-file-123",
        "drive_mime_type": "image/jpeg",
        "source_modified_time": "2026-04-02T10:00:00Z",
    }
    files = {"file": ("Maine porch photo.jpg", b"hello mirror", "image/jpeg")}

    first = client.post(f"/api/assets/{imported['asset_id']}/mirror/upload", data=data, files=files)
    second = client.post(f"/api/assets/{imported['asset_id']}/mirror/upload", data=data, files=files)

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["created"] is True
    assert second.json()["created"] is False
    assert first.json()["object_file_id"] == second.json()["object_file_id"]

    with Session(engine) as session:
        local_objects = session.exec(select(ObjectFile).where(ObjectFile.storage_provider == "local")).all()
        mirror_snapshots = session.exec(
            select(AssetSnapshot).where(AssetSnapshot.snapshot_type == "source_mirror")
        ).all()
        assert len(local_objects) == 1
        assert len(mirror_snapshots) == 1


def test_asset_mirror_service_can_record_gcs_object_without_local_final_copy(tmp_path, monkeypatch):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    uploads = []

    def fake_upload_to_gcs(**kwargs):
        uploads.append(kwargs)
        return {"name": kwargs["object_key"], "bucket": kwargs["bucket"]}

    monkeypatch.setattr(asset_mirror, "_upload_to_gcs", fake_upload_to_gcs)

    async def run():
        with Session(engine) as session:
            asset = Asset(
                human_id="DRV_GCS_SMOKE",
                asset_type="text",
                title="smoke.txt",
                original_filename="smoke.txt",
                mime_type="text/plain",
                source_system="google_drive",
                import_status="drive_metadata_imported",
                maturity_level="L0_source_seen",
            )
            session.add(asset)
            session.flush()
            upload = UploadFile(file=BytesIO(b"hello gcs"), filename="smoke.txt")
            return await mirror_upload_for_asset(
                session,
                asset,
                upload,
                storage_root=tmp_path / "storage",
                storage_provider="gcs",
                gcs_bucket="charlesops-vault-1030126815863",
                gcs_prefix="charlesops",
                storage_access_token="fake-token",
                source_system="google_drive",
                drive_file_id="drive-gcs-smoke",
                drive_mime_type="text/plain",
            )

    result = asyncio.run(run())

    assert result.created is True
    assert result.uri.startswith("gs://charlesops-vault-1030126815863/charlesops/source_mirror/")
    assert uploads[0]["bucket"] == "charlesops-vault-1030126815863"
    assert uploads[0]["object_key"] == result.object_key
