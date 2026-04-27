import asyncio
from io import BytesIO
from pathlib import Path

from fastapi import UploadFile
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app.config import settings
from app.db.session import get_session
from app.main import app
from app.models import Annotation, Asset, AssetSnapshot, Derivative, ObjectFile, Segment, Task
from app.services import asset_mirror
from app.services.asset_mirror import mirror_upload_for_asset
from app.services.text_extraction import extract_text_from_file


def build_client(tmp_path: Path):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    settings.storage_root = str(tmp_path / "storage")
    settings.object_storage_provider = "local"
    settings.gcs_bucket = ""
    settings.gcs_prefix = "charlesops"
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
                "thumbnail_link": "https://lh3.googleusercontent.com/drive-thumbnail-test=s220",
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


def text_drive_payload() -> dict:
    return {
        "files": [
            {
                "drive_file_id": "drive-text-123",
                "name": "letter.txt",
                "mime_type": "text/plain",
                "web_view_link": "https://drive.google.com/file/d/drive-text-123/view",
                "size_bytes": 1024,
                "created_time": "2026-04-01T10:00:00Z",
                "modified_time": "2026-04-02T10:00:00Z",
                "parents": ["parent-folder"],
                "picker_document": {"id": "drive-text-123"},
                "drive_metadata": {
                    "charlesOpsPath": "Vault/Letters/letter.txt",
                    "charlesOpsCandidateKind": "documents",
                },
            }
        ],
        "imported_by": "adam",
    }


def email_drive_payload() -> dict:
    return {
        "files": [
            {
                "drive_file_id": "drive-email-123",
                "name": "thread.eml",
                "mime_type": "message/rfc822",
                "web_view_link": "https://drive.google.com/file/d/drive-email-123/view",
                "size_bytes": 2048,
                "created_time": "2026-04-01T10:00:00Z",
                "modified_time": "2026-04-02T10:00:00Z",
                "parents": ["parent-folder"],
                "picker_document": {"id": "drive-email-123"},
                "drive_metadata": {
                    "charlesOpsPath": "Vault/Email/thread.eml",
                    "charlesOpsCandidateKind": "email",
                },
            }
        ],
        "imported_by": "adam",
    }


def test_asset_mirror_upload_creates_local_object_snapshot_and_annotation(tmp_path):
    client, engine = build_client(tmp_path)
    imported = client.post("/api/imports/drive", json=drive_payload()).json()["imported"][0]

    metadata_preview = client.get(f"/api/assets/{imported['asset_id']}/preview", follow_redirects=False)
    assert metadata_preview.status_code == 307
    assert metadata_preview.headers["location"] == "https://lh3.googleusercontent.com/drive-thumbnail-test=s220"

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

    preview = client.get(f"/api/assets/{imported['asset_id']}/preview")
    assert preview.status_code == 200
    assert preview.content == b"hello mirror"
    assert preview.headers["content-type"] == "image/jpeg"

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


def test_text_mirror_upload_extracts_preview_segments_and_review_task(tmp_path):
    client, engine = build_client(tmp_path)
    imported = client.post("/api/imports/drive", json=text_drive_payload()).json()["imported"][0]
    source_text = b"Dear Adam,\n\nThis is a small source letter with Charles voice material.\n\nLove, Dad"

    response = client.post(
        f"/api/assets/{imported['asset_id']}/mirror/upload",
        data={
            "source_system": "google_drive",
            "source_uri": "https://drive.google.com/file/d/drive-text-123/view",
            "drive_file_id": "drive-text-123",
            "drive_mime_type": "text/plain",
            "source_modified_time": "2026-04-02T10:00:00Z",
        },
        files={"file": ("letter.txt", source_text, "text/plain")},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["created"] is True
    chunk_response = client.get(f"/api/segments?asset_id={imported['asset_id']}&segment_type=text_chunk")
    assert chunk_response.status_code == 200
    assert len(chunk_response.json()) == 1

    with Session(engine) as session:
        asset = session.get(Asset, imported["asset_id"])
        assert asset is not None
        assert asset.processing_status == "text_extracted"
        assert asset.maturity_level == "L2_extracted"

        derivative = session.exec(select(Derivative).where(Derivative.asset_id == asset.id)).first()
        assert derivative is not None
        assert derivative.derivative_type == "text_extraction"
        assert derivative.status == "extracted"
        assert "Dear Adam" in derivative.metadata_json["preview_text"]

        segments = session.exec(select(Segment).where(Segment.asset_id == asset.id)).all()
        assert {segment.segment_type for segment in segments} >= {"text_preview", "text_chunk"}
        assert any("Charles voice material" in (segment.text_content or "") for segment in segments)

        task = session.exec(select(Task).where(Task.task_type == "text_segment_review")).first()
        assert task is not None
        assert task.created_by == "text_extraction"
        assert task.input_payload["source_type"] == "document"
        assert "Dear Adam" in task.input_payload["preview_text"]
        assert "source_genre" in task.required_decisions
        assert "creator_entity_ids" in task.required_decisions
        assert "fictionality_status" in task.required_decisions
        assert "voice_presence" in task.required_decisions

        annotations = session.exec(select(Annotation).where(Annotation.target_id == asset.id)).all()
        assert any(annotation.annotation_type == "text_extraction" for annotation in annotations)


def test_email_mirror_upload_creates_multi_voice_review_task(tmp_path):
    client, engine = build_client(tmp_path)
    imported = client.post("/api/imports/drive", json=email_drive_payload()).json()["imported"][0]
    source_email = (
        b"From: Charles <charles@example.com>\n"
        b"To: Adam <adam@example.com>\n"
        b"Subject: Re: visit\n"
        b"Date: Thu, 2 Apr 2026 10:00:00 -0400\n"
        b"Content-Type: text/plain; charset=utf-8\n"
        b"\n"
        b"Adam,\n\nThe house is too quiet now.\n\n> On Wednesday, Adam wrote: I made it home.\n"
    )

    response = client.post(
        f"/api/assets/{imported['asset_id']}/mirror/upload",
        data={
            "source_system": "google_drive",
            "source_uri": "https://drive.google.com/file/d/drive-email-123/view",
            "drive_file_id": "drive-email-123",
            "drive_mime_type": "message/rfc822",
            "source_modified_time": "2026-04-02T10:00:00Z",
        },
        files={"file": ("thread.eml", source_email, "message/rfc822")},
    )

    assert response.status_code == 200

    with Session(engine) as session:
        task = session.exec(select(Task).where(Task.task_type == "email_voice_sample")).first()
        assert task is not None
        assert task.created_by == "text_extraction"
        assert task.input_payload["source_type"] == "email"
        assert task.input_payload["email_headers"]["subject"] == "Re: visit"
        assert "charles_voice_presence" in task.required_decisions
        assert "context_use" in task.required_decisions
        assert "privacy_notes" in task.required_decisions


def test_html_email_text_extraction_preserves_inline_spacing(tmp_path):
    path = tmp_path / "thread.eml"
    path.write_bytes(
        b"From: Charles <charles@example.com>\n"
        b"To: Adam <adam@example.com>\n"
        b"Subject: HTML spacing\n"
        b"Content-Type: text/html; charset=utf-8\n"
        b"\n"
        b"<html><body><p><span>Hello</span><span>Adam</span></p><div>Next sentence.</div></body></html>"
    )

    result = extract_text_from_file(path, filename="thread.eml", content_type="message/rfc822", asset_type="text")

    assert result.status == "extracted"
    assert "Hello Adam" in result.text
    assert "Next sentence." in result.text


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
