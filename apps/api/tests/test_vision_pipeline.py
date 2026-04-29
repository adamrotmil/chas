from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app.db.session import get_session
from app.main import app
from app.models import Annotation, Asset, Boundary, EmbeddingRecord, GalleryItem, Memory, MetadataProfile, Segment, Task, TaskReceipt


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
    assert body["creates_or_updates"]["embedding_record_id"]
    assert body["creates_or_updates"]["memory_id"]
    assert body["creates_or_updates"]["memory_embedding_record_id"]
    assert body["creates_or_updates"]["task_receipt_id"]
    assert body["creates_or_updates"]["receipt"]["boundary_status"] == "blocked"
    assert "privacy_level=private_sensitive" in body["creates_or_updates"]["receipt"]["blocked_reasons"]

    with Session(engine) as session:
        annotation = session.get(Annotation, body["id"])
        profile = session.get(MetadataProfile, body["creates_or_updates"]["metadata_profile_id"])
        ocr_segment = session.get(Segment, body["creates_or_updates"]["ocr_segment_id"])
        memory = session.get(Memory, body["creates_or_updates"]["memory_id"])
        receipt = session.get(TaskReceipt, body["creates_or_updates"]["task_receipt_id"])
        embedding = session.get(EmbeddingRecord, body["creates_or_updates"]["embedding_record_id"])
        memory_embedding = session.get(EmbeddingRecord, body["creates_or_updates"]["memory_embedding_record_id"])

        assert annotation is not None
        assert profile is not None
        assert profile.metadata_status == "adam_reviewed"
        assert profile.summary == "A handwritten journal page on lined paper."
        assert profile.truth_status == "adam_memory"
        assert "Potential journal source; needs careful transcription." in profile.adam_context_note
        assert "Question: Who is visible or directly represented here?" in profile.adam_context_note
        assert "Keep private until journal context is reviewed." in profile.adam_context_note
        assert profile.quality_signals["vision_accuracy"] == "minor_issues"
        assert profile.embedding_hints["question_answers"]["privacy"] == "Keep private until journal context is reviewed."
        assert profile.raw_profile["adam_review"]["answered_questions"][0]["id"] == "who_is_visible"
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
        assert memory is not None
        assert memory.truth_status == "adam_memory"
        assert "handwritten journal page" in memory.summary
        assert embedding is not None
        assert embedding.status == "ready_for_embedding"
        assert embedding.embedding_type == "retrieval_text"
        assert memory_embedding is not None
        assert memory_embedding.embedding_type == "memory_text"
        assert receipt is not None
        assert receipt.downstream_status == "blocked"


def test_photo_context_submission_creates_memory_gallery_and_receipt():
    client, engine = build_client()

    with Session(engine) as session:
        photo = Asset(
            human_id="ASSET_PHOTO_CONTEXT",
            asset_type="photo",
            title="Market Street breakfast",
            original_filename="market-breakfast.jpg",
            mime_type="image/jpeg",
        )
        session.add(photo)
        session.flush()
        task = Task(
            human_id="TASK_PHOTO_CONTEXT",
            task_type="photo_context",
            target_type="asset",
            target_id=photo.id,
            queue="photo_assets_needing_context",
            input_payload={"asset_id": photo.id, "asset_title": photo.title, "asset_type": "photo"},
            required_decisions=["visible_people", "place", "invisible_context_note", "privacy_level", "ready_for_downstream"],
            created_by="test",
        )
        session.add(task)
        session.commit()
        task_id = task.id

    response = client.post(
        f"/api/tasks/{task_id}/submit",
        json={
            "decisions": {
                "visible_people": ["Adam", "Charles"],
                "absent_but_relevant_people": ["Cathryn"],
                "place": "Market Street, Portland",
                "date_or_range": "1980s",
                "date_confidence": "decade",
                "event": "breakfast",
                "visual_description_correction": "Breakfast on the white table at Market Street.",
                "invisible_context_note": "The brie stayed out all weekend; the food was a ceremony.",
                "memory_potential": 5,
                "privacy_sensitivity": 2,
                "gallery_eligibility": "family_private",
                "privacy_level": "family_private",
                "privacy_notes": "Family-memory safe, not public.",
                "ready_for_downstream": "yes",
            }
        },
    )

    assert response.status_code == 200
    body = response.json()
    created = body["creates_or_updates"]
    assert created["metadata_profile_id"]
    assert created["boundary_id"]
    assert created["memory_id"]
    assert created["gallery_item_id"]
    assert created["embedding_record_id"]
    assert created["memory_embedding_record_id"]
    assert created["receipt"]["boundary_status"] == "passed"

    with Session(engine) as session:
        profile = session.get(MetadataProfile, created["metadata_profile_id"])
        boundary = session.get(Boundary, created["boundary_id"])
        memory = session.get(Memory, created["memory_id"])
        gallery_item = session.get(GalleryItem, created["gallery_item_id"])
        receipt = session.get(TaskReceipt, created["task_receipt_id"])

        assert profile is not None
        assert profile.profile_type == "photo_memory"
        assert profile.truth_status == "adam_memory"
        assert "Cathryn" in profile.people
        assert boundary is not None
        assert boundary.retrievable_in_chat is True
        assert boundary.usable_for_gallery_family is True
        assert memory is not None
        assert memory.maturity_level == "L3_reviewed"
        assert gallery_item is not None
        assert gallery_item.gallery_scope == "family_private"
        assert receipt is not None
        assert receipt.next_action_label == "Use photo metadata in retrieval/context packs"
