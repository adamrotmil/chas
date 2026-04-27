from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app.db.session import get_session
from app.main import app
from app.models import Annotation, Asset, Boundary, MetadataProfile, Segment, Task


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


def test_vision_draft_batch_creates_system_inference_profile_and_review_task():
    client, engine = build_client()

    with Session(engine) as session:
        photo = Asset(
            human_id="ASSET_VISION_PHOTO",
            asset_type="photo",
            title="Porch photograph",
            original_filename="porch.jpg",
            mime_type="image/jpeg",
            source_system="google_drive",
        )
        text = Asset(
            human_id="ASSET_NOT_VISION",
            asset_type="text",
            title="Letter",
            mime_type="text/plain",
        )
        session.add(photo)
        session.add(text)
        session.commit()
        photo_id = photo.id

    response = client.post("/api/vision/drafts/batches", json={"limit": 10})

    assert response.status_code == 200
    body = response.json()
    assert body["created_count"] == 1
    assert len(body["metadata_profile_ids"]) == 1
    assert len(body["review_task_ids"]) == 1

    with Session(engine) as session:
        profile = session.get(MetadataProfile, body["metadata_profile_ids"][0])
        task = session.get(Task, body["review_task_ids"][0])

        assert profile is not None
        assert profile.target_type == "asset"
        assert profile.target_id == photo_id
        assert profile.profile_type == "photo_metadata"
        assert profile.metadata_status == "machine_draft"
        assert profile.truth_status == "system_inference"
        assert profile.raw_profile["no_live_model_call"] is True
        assert profile.raw_profile["system_inference_draft"]["suggested_questions"]

        assert task is not None
        assert task.task_type == "vision_draft_review"
        assert task.queue == "vision_drafts_needing_review"
        assert task.input_payload["asset_id"] == photo_id
        assert task.input_payload["no_live_model_call"] is True
        assert "question_answers" in task.required_decisions


def test_live_vision_calls_are_blocked_in_scaffold():
    client, engine = build_client()

    with Session(engine) as session:
        session.add(
            Asset(
                human_id="ASSET_VISION_BLOCKED",
                asset_type="photo",
                title="Blocked live call",
                mime_type="image/jpeg",
            )
        )
        session.commit()

    response = client.post("/api/vision/drafts/batches", json={"limit": 1, "no_live_model_call": False})

    assert response.status_code == 400
    assert "Live vision calls" in response.text


def test_vision_review_submission_promotes_profile_and_creates_ocr_segment():
    client, engine = build_client()

    with Session(engine) as session:
        photo = Asset(
            human_id="ASSET_VISION_REVIEW",
            asset_type="photo",
            title="Journal page",
            original_filename="journal.jpg",
            mime_type="image/jpeg",
        )
        session.add(photo)
        session.commit()
        photo_id = photo.id

    batch = client.post("/api/vision/drafts/batches", json={"asset_ids": [photo_id], "limit": 1}).json()
    task_id = batch["review_task_ids"][0]

    response = client.post(
        f"/api/tasks/{task_id}/submit",
        json={
            "decisions": {
                "vision_accuracy": "minor_issues",
                "accepted_visual_description": "A handwritten journal page on lined paper.",
                "people": ["Charles"],
                "places": ["Maine"],
                "date_or_range": "unknown",
                "accepted_tags": ["journal", "handwriting", "lined paper"],
                "concrete_objects": ["paper", "handwriting"],
                "rejected_system_inferences": ["wrong_person_guess"],
                "question_answers": {
                    "who_is_visible": "No person visible; Charles may have written it.",
                    "privacy": "Keep private until journal context is reviewed.",
                },
                "adam_context_note": "Potential journal source; needs careful transcription.",
                "privacy_level": "private_sensitive",
                "privacy_notes": "Handwriting may contain private material.",
                "ready_for_downstream": "yes",
                "ocr_review_status": "adam_corrected",
                "ocr_truth_status": "adam_expert_reconstruction",
                "corrected_ocr_text": "first corrected line\nsecond corrected line",
            },
            "notes": "Vision review complete.",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["annotation_type"] == "vision_draft_review"
    assert body["creates_or_updates"]["metadata_profile_id"]
    assert body["creates_or_updates"]["ocr_segment_id"]

    with Session(engine) as session:
        annotation = session.get(Annotation, body["id"])
        profile = session.get(MetadataProfile, body["creates_or_updates"]["metadata_profile_id"])
        ocr_segment = session.get(Segment, body["creates_or_updates"]["ocr_segment_id"])

        assert annotation is not None
        assert profile is not None
        assert profile.metadata_status == "adam_reviewed"
        assert profile.summary == "A handwritten journal page on lined paper."
        assert profile.adam_context_note == "Potential journal source; needs careful transcription."
        assert profile.quality_signals["vision_accuracy"] == "minor_issues"
        assert profile.embedding_hints["question_answers"]["privacy"] == "Keep private until journal context is reviewed."
        assert profile.raw_profile["rejected_system_inferences"] == ["wrong_person_guess"]
        assert profile.source_annotation_id == annotation.id
        boundary = session.exec(select(Boundary).where(Boundary.target_type == "asset").where(Boundary.target_id == photo_id)).first()
        assert boundary is not None
        assert boundary.privacy_level == "private_sensitive"
        assert boundary.redaction_required is True
        assert boundary.retrievable_in_chat is False
        assert boundary.usable_for_eval is True
        asset = session.get(Asset, photo_id)
        assert asset is not None
        assert asset.processing_status == "vision_reviewed"
        assert asset.maturity_level == "L2_needs_review"

        assert ocr_segment is not None
        assert ocr_segment.asset_id == photo_id
        assert ocr_segment.segment_type == "vision_ocr_text"
        assert ocr_segment.source_truth_status == "adam_expert_reconstruction"
        assert "first corrected line" in (ocr_segment.text_content or "")
