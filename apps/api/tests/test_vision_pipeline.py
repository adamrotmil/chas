from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app.config import Settings, get_settings
from app.db.session import get_session
from app.main import app
from app.models import (
    Annotation,
    Asset,
    AssetSnapshot,
    Boundary,
    Derivative,
    EmbeddingRecord,
    GalleryItem,
    Memory,
    MetadataProfile,
    ObjectFile,
    Segment,
    Task,
    TaskReceipt,
)
from app.services.vision import _normalise_vision_draft, _vision_draft_has_observations


def build_client(app_settings: Settings | None = None):
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
    app.dependency_overrides[get_settings] = lambda: app_settings or Settings(openai_api_key="", vision_live_calls_enabled=False)
    return TestClient(app), engine


def test_blank_live_vision_draft_is_not_considered_observed_content():
    draft = _normalise_vision_draft(
        {
            "visual_summary": "",
            "visible_people": [],
            "places": [],
            "time_period_guess": "",
            "objects": [],
            "themes": [],
            "ocr_text": "",
            "handwriting_text": "",
            "uncertainties": [],
            "suggested_questions": [],
            "privacy_flags": [],
            "confidence": "",
        }
    )

    assert _vision_draft_has_observations(draft) is False


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


def test_live_vision_batch_stores_unreviewed_system_inference(monkeypatch, tmp_path):
    client, engine = build_client(
        Settings(
            openai_api_key="test-key",
            vision_live_calls_enabled=True,
            vision_model="gpt-4.1-mini",
            storage_root=str(tmp_path),
        )
    )

    def fake_live_vision_model(**kwargs):
        assert kwargs["model_name"] == "gpt-4.1-mini"
        assert kwargs["schema"]["name"] == "charlesops_vision_draft_v1"
        assert kwargs["image_data_url"].startswith("data:image/png;base64,")
        return {
            "draft": {
                "visual_summary": "A small test image with indistinct visible content.",
                "visible_people": [],
                "places": [],
                "time_period_guess": "unknown",
                "objects": ["image artifact"],
                "themes": ["source review"],
                "ocr_text": "",
                "handwriting_text": "",
                "uncertainties": ["The image is too small to infer details."],
                "suggested_questions": [
                    {
                        "id": "what_is_this",
                        "question": "What should Adam remember about this image?",
                        "reason": "The model cannot infer private context from pixels alone.",
                        "answer_type": "long_text",
                    }
                ],
                "privacy_flags": [],
                "confidence": "low",
            },
            "response_id": "resp_vision_test",
        }

    monkeypatch.setattr("app.services.vision._call_live_vision_model", fake_live_vision_model)

    image_key = "vision-live-test/source.png"
    image_path = tmp_path / image_key
    image_path.parent.mkdir(parents=True)
    image_path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        b"\x00\x00\x00\rIHDR"
        b"\x00\x00\x00\x01\x00\x00\x00\x01"
        b"\x08\x06\x00\x00\x00"
        b"\x1f\x15\xc4\x89"
        b"\x00\x00\x00\x00IEND\xaeB`\x82"
    )

    with Session(engine) as session:
        photo = Asset(
            human_id="ASSET_VISION_LIVE",
            asset_type="photo",
            title="Live vision test image",
            original_filename="live.png",
            mime_type="image/png",
            processing_status="image_preview_ready",
        )
        session.add(photo)
        session.flush()
        object_file = ObjectFile(
            storage_provider="local",
            object_key=image_key,
            uri=f"local://{image_key}",
            content_type="image/png",
            byte_size=image_path.stat().st_size,
        )
        session.add(object_file)
        session.flush()
        snapshot = AssetSnapshot(
            asset_id=photo.id,
            snapshot_type="source_mirror",
            version=1,
            object_file_id=object_file.id,
        )
        session.add(snapshot)
        session.flush()
        session.add(
            Derivative(
                asset_id=photo.id,
                source_snapshot_id=snapshot.id,
                derivative_type="image_preview",
                object_file_id=object_file.id,
                status="ready",
                metadata_json={"variant": "display"},
            )
        )
        session.commit()
        photo_id = photo.id

    response = client.post("/api/vision/drafts/batches", json={"asset_ids": [photo_id], "limit": 1, "no_live_model_call": False})

    assert response.status_code == 200
    body = response.json()
    assert body["created_count"] == 1

    with Session(engine) as session:
        profile = session.get(MetadataProfile, body["metadata_profile_ids"][0])
        task = session.get(Task, body["review_task_ids"][0])

        assert profile is not None
        assert profile.truth_status == "system_inference"
        assert profile.metadata_status == "machine_draft"
        assert profile.summary == "A small test image with indistinct visible content."
        assert profile.quality_signals["no_live_model_call"] is False
        assert profile.quality_signals["live_model_call_used"] is True
        assert profile.quality_signals["live_response_id"] == "resp_vision_test"
        assert profile.raw_profile["system_inference_draft"]["objects"] == ["image artifact"]
        assert profile.raw_profile["no_live_model_call"] is False

        assert task is not None
        assert task.input_payload["no_live_model_call"] is False
        assert task.input_payload["live_model_call_used"] is True
        assert task.input_payload["vision_draft"]["visual_summary"] == "A small test image with indistinct visible content."
        assert task.input_payload["suggested_questions"][0]["id"] == "what_is_this"


def test_live_vision_rerun_refreshes_existing_ready_review_task(monkeypatch, tmp_path):
    client, engine = build_client(
        Settings(
            openai_api_key="test-key",
            vision_live_calls_enabled=True,
            vision_model="gpt-4.1-mini",
            storage_root=str(tmp_path),
        )
    )

    def fake_live_vision_model(**kwargs):
        assert kwargs["image_data_url"].startswith("data:image/png;base64,")
        return {
            "draft": {
                "visual_summary": "Live model now sees a framed family photograph on a table.",
                "visible_people": ["one person in a framed photograph"],
                "places": [],
                "time_period_guess": "unknown",
                "objects": ["picture frame", "table"],
                "themes": ["family memory"],
                "ocr_text": "",
                "handwriting_text": "",
                "uncertainties": ["The person is not identifiable from pixels alone."],
                "suggested_questions": [
                    {
                        "id": "identify_person",
                        "question": "Who is the person shown in the framed photograph?",
                        "reason": "Only Adam can safely provide the private identity.",
                        "answer_type": "people",
                    }
                ],
                "privacy_flags": ["possible_private_person"],
                "confidence": "medium",
            },
            "response_id": "resp_vision_refresh",
        }

    monkeypatch.setattr("app.services.vision._call_live_vision_model", fake_live_vision_model)

    image_key = "vision-refresh/source.png"
    image_path = tmp_path / image_key
    image_path.parent.mkdir(parents=True)
    image_path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        b"\x00\x00\x00\rIHDR"
        b"\x00\x00\x00\x01\x00\x00\x00\x01"
        b"\x08\x06\x00\x00\x00"
        b"\x1f\x15\xc4\x89"
        b"\x00\x00\x00\x00IEND\xaeB`\x82"
    )

    with Session(engine) as session:
        photo = Asset(
            human_id="ASSET_VISION_REFRESH",
            asset_type="photo",
            title="Existing scaffolded vision task",
            original_filename="refresh.png",
            mime_type="image/png",
            processing_status="image_preview_ready",
        )
        session.add(photo)
        session.flush()
        object_file = ObjectFile(
            storage_provider="local",
            object_key=image_key,
            uri=f"local://{image_key}",
            content_type="image/png",
            byte_size=image_path.stat().st_size,
        )
        session.add(object_file)
        session.flush()
        snapshot = AssetSnapshot(
            asset_id=photo.id,
            snapshot_type="source_mirror",
            version=1,
            object_file_id=object_file.id,
        )
        session.add(snapshot)
        session.add(
            Derivative(
                asset_id=photo.id,
                source_snapshot_id=snapshot.id,
                derivative_type="image_preview",
                object_file_id=object_file.id,
                status="ready",
                metadata_json={"variant": "display"},
            )
        )
        session.commit()
        photo_id = photo.id

    scaffold = client.post("/api/vision/drafts/batches", json={"asset_ids": [photo_id], "limit": 1})
    assert scaffold.status_code == 200
    scaffold_body = scaffold.json()
    task_id = scaffold_body["review_task_ids"][0]
    profile_id = scaffold_body["metadata_profile_ids"][0]

    live_refresh = client.post(
        "/api/vision/drafts/batches",
        json={"asset_ids": [photo_id], "limit": 1, "no_live_model_call": False},
    )
    assert live_refresh.status_code == 200
    live_body = live_refresh.json()
    assert live_body["metadata_profile_ids"] == [profile_id]
    assert live_body["review_task_ids"] == [task_id]

    with Session(engine) as session:
        profile = session.get(MetadataProfile, profile_id)
        task = session.get(Task, task_id)
        ready_tasks = session.exec(select(Task).where(Task.task_type == "vision_draft_review")).all()

        assert len(ready_tasks) == 1
        assert profile is not None
        assert profile.summary == "Live model now sees a framed family photograph on a table."
        assert profile.raw_profile["no_live_model_call"] is False
        assert profile.raw_profile["live_response_id"] == "resp_vision_refresh"

        assert task is not None
        assert task.input_payload["no_live_model_call"] is False
        assert task.input_payload["live_model_call_used"] is True
        assert task.input_payload["vision_draft"]["visual_summary"] == "Live model now sees a framed family photograph on a table."
        assert task.input_payload["suggested_questions"][0]["id"] == "identify_person"


def test_live_vision_upgrades_existing_photo_memory_review_without_duplicate(monkeypatch, tmp_path):
    client, engine = build_client(
        Settings(
            openai_api_key="test-key",
            vision_live_calls_enabled=True,
            vision_model="gpt-4.1-mini",
            storage_root=str(tmp_path),
        )
    )

    def fake_live_vision_model(**kwargs):
        assert kwargs["schema"]["name"] == "charlesops_vision_draft_v1"
        return {
            "draft": {
                "visual_summary": "Live vision describes Charles seated with a flute and books nearby.",
                "visible_people": ["one seated adult"],
                "places": ["indoor room"],
                "time_period_guess": "unknown",
                "objects": ["flute", "books", "chair"],
                "themes": ["music", "home archive"],
                "ocr_text": "",
                "handwriting_text": "",
                "uncertainties": ["Identity needs Adam confirmation."],
                "suggested_questions": [
                    {
                        "id": "confirm_context",
                        "question": "What should Adam remember about this music scene?",
                        "reason": "The pixels cannot supply the private memory.",
                        "answer_type": "long_text",
                    }
                ],
                "privacy_flags": ["family_private_review_required"],
                "confidence": "medium",
            },
            "response_id": "resp_photo_memory_upgrade",
        }

    monkeypatch.setattr("app.services.vision._call_live_vision_model", fake_live_vision_model)

    image_key = "vision-photo-memory/source.png"
    image_path = tmp_path / image_key
    image_path.parent.mkdir(parents=True)
    image_path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        b"\x00\x00\x00\rIHDR"
        b"\x00\x00\x00\x01\x00\x00\x00\x01"
        b"\x08\x06\x00\x00\x00"
        b"\x1f\x15\xc4\x89"
        b"\x00\x00\x00\x00IEND\xaeB`\x82"
    )

    with Session(engine) as session:
        photo = Asset(
            human_id="ASSET_PHOTO_MEMORY_UPGRADE",
            asset_type="photo",
            title="Romil and Japanese Flute IV.jpg",
            original_filename="Romil and Japanese Flute IV.jpg",
            mime_type="image/png",
            processing_status="image_preview_ready",
        )
        session.add(photo)
        session.flush()
        object_file = ObjectFile(
            storage_provider="local",
            object_key=image_key,
            uri=f"local://{image_key}",
            content_type="image/png",
            byte_size=image_path.stat().st_size,
        )
        session.add(object_file)
        session.flush()
        snapshot = AssetSnapshot(
            asset_id=photo.id,
            snapshot_type="source_mirror",
            version=1,
            object_file_id=object_file.id,
        )
        session.add(snapshot)
        session.flush()
        session.add(
            Derivative(
                asset_id=photo.id,
                source_snapshot_id=snapshot.id,
                derivative_type="image_preview",
                object_file_id=object_file.id,
                status="ready",
                metadata_json={"variant": "display"},
            )
        )
        profile = MetadataProfile(
            target_type="asset",
            target_id=photo.id,
            profile_type="photo_memory",
            profile_version="v1",
            metadata_status="machine_draft_needs_adam_review",
            title="Photo memory: Charles with Japanese flute",
            summary="Template summary before live vision.",
            truth_status="system_inference",
            quality_signals={"draft_source": "filename_and_image_preview"},
            embedding_hints={"modality": "photo"},
            raw_profile={"template": {"match": "Japanese Flute"}},
            created_by="photo_memory_machine_draft",
        )
        session.add(profile)
        session.flush()
        task = Task(
            human_id="TASK_PHOTO_MEMORY_REVIEW_EXISTING",
            task_type="vision_draft_review",
            target_type="metadata_profile",
            target_id=profile.id,
            queue="vision_drafts_needing_review",
            status="ready",
            input_payload={
                "asset_id": photo.id,
                "metadata_profile_id": profile.id,
                "draft_type": "photo_memory_machine_draft",
                "source_photo_memory_draft": True,
                "vision_draft": {"visual_summary": "Template summary before live vision."},
                "suggested_questions": [],
                "no_live_model_call": True,
            },
            created_by="photo_memory_machine_draft",
        )
        session.add(task)
        session.commit()
        photo_id = photo.id
        profile_id = profile.id
        task_id = task.id

    live_refresh = client.post(
        "/api/vision/drafts/batches",
        json={"asset_ids": [photo_id], "limit": 1, "no_live_model_call": False},
    )
    assert live_refresh.status_code == 200
    body = live_refresh.json()
    assert body["metadata_profile_ids"] == [profile_id]
    assert body["review_task_ids"] == [task_id]

    with Session(engine) as session:
        profiles = session.exec(select(MetadataProfile)).all()
        tasks = session.exec(select(Task).where(Task.task_type == "vision_draft_review")).all()
        profile = session.get(MetadataProfile, profile_id)
        task = session.get(Task, task_id)

        assert len(profiles) == 1
        assert len(tasks) == 1
        assert profile is not None
        assert profile.profile_type == "photo_memory"
        assert profile.metadata_status == "machine_draft_needs_adam_review"
        assert profile.title == "Photo memory: Charles with Japanese flute"
        assert profile.summary == "Live vision describes Charles seated with a flute and books nearby."
        assert profile.quality_signals["draft_source"] == "filename_and_image_preview"
        assert profile.quality_signals["no_live_model_call"] is False
        assert profile.raw_profile["template"]["match"] == "Japanese Flute"
        assert profile.raw_profile["live_response_id"] == "resp_photo_memory_upgrade"

        assert task is not None
        assert task.input_payload["draft_type"] == "photo_memory"
        assert task.input_payload["source_photo_memory_draft"] is True
        assert task.input_payload["no_live_model_call"] is False
        assert task.input_payload["live_model_call_used"] is True
        assert task.input_payload["vision_draft"]["objects"] == ["flute", "books", "chair"]


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
