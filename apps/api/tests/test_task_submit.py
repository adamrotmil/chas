from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select
from fastapi.testclient import TestClient

from app.db.session import get_session
from app.main import app
from app.models import (
    AntiPattern,
    Asset,
    Boundary,
    ContextPack,
    DPOPair,
    Entity,
    Generation,
    GoldVoiceExample,
    MetadataProfile,
    PromptSpec,
    SFTCandidate,
    Segment,
    Task,
    TaskDraft,
)


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


def test_gold_voice_submission_creates_annotation_and_training_artifacts():
    client, engine = build_client()

    with Session(engine) as session:
        prompt = PromptSpec(
            human_id="PROMPT_TEST",
            prompt_type="gold_voice_edit",
            voice_mode="father_to_adam",
            truth_mode="generative_reconstruction",
            prompt_text="Write Adam a note after Maine.",
        )
        context = ContextPack(
            human_id="CTX_TEST",
            user_intent="photo_reflection",
            requested_voice_mode="father_to_adam",
            truth_mode="generative_reconstruction",
        )
        session.add(prompt)
        session.add(context)
        session.flush()
        generation = Generation(
            prompt_spec_id=prompt.id,
            context_pack_id=context.id,
            model_name="manual_test",
            output_text="Dear Adam, this visit meant so much to me.",
        )
        session.add(generation)
        session.flush()
        task = Task(
            human_id="TASK_TEST_GOLD",
            task_type="gold_voice_edit",
            target_type="generation",
            target_id=generation.id,
            queue="generated_responses_needing_gold_edits",
            input_payload={
                "generation_id": generation.id,
                "prompt_spec_id": prompt.id,
                "context_pack_id": context.id,
                "voice_mode": "father_to_adam",
            },
        )
        session.add(task)
        session.commit()
        task_id = task.id

    response = client.post(
        f"/api/tasks/{task_id}/submit",
        json={
            "decisions": {
                "prompt": "Write Adam a note after Maine.",
                "voice_mode": "father_to_adam",
                "truth_mode": "generative_reconstruction",
                "model_draft": "Dear Adam, this visit meant so much to me.",
                "adam_gold_edit": "Adam\n\nleft the cup in the sink.\nreasonable.\n\ncall when you get in\n\ndad",
                "ratings": {
                    "voice_fidelity": 5,
                    "emotional_truth": 5,
                    "restraint": 5,
                    "non_parody": 5,
                },
                "response_rubric": {
                    "response_a": {
                        "restraint": {
                            "status": "minor_issues",
                            "notes": "The rejected draft is too polished.",
                            "issue_tags": [],
                        }
                    },
                    "response_b": {
                        "restraint": {
                            "status": "no_issues",
                            "notes": "",
                            "issue_tags": [],
                        }
                    },
                },
                "rubric_summary": {
                    "rejected_issue_count": 1,
                    "preferred_issue_count": 0,
                    "sft_ready": True,
                },
                "export_flags": {
                    "sft": True,
                    "dpo": True,
                    "eval": True,
                    "anti_pattern": True,
                    "style_rule": True,
                },
            },
            "notes": "Good test edit.",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["annotation_type"] == "gold_voice_edit"
    assert body["creates_or_updates"]["gold_voice_example_id"]

    with Session(engine) as session:
        task = session.get(Task, task_id)
        assert task.status == "submitted"
        gold = session.exec(select(GoldVoiceExample)).first()
        assert gold
        assert gold.ratings["response_rubric"]["response_a"]["restraint"]["issue_tags"] == []
        assert gold.ratings["response_rubric"]["response_b"]["restraint"]["status"] == "no_issues"
        assert gold.ratings["rubric_summary"]["sft_ready"] is True
        assert session.exec(select(SFTCandidate)).first().export_status == "approved"
        dpo_pair = session.exec(select(DPOPair)).first()
        assert dpo_pair.export_status == "approved"
        assert dpo_pair.reason == ["restraint: The rejected draft is too polished."]
        anti_pattern = session.exec(select(AntiPattern)).first()
        assert anti_pattern
        assert anti_pattern.why_wrong == "restraint: The rejected draft is too polished."

    sft = client.get("/api/dataset-exports/jsonl?export_type=sft")
    dpo = client.get("/api/dataset-exports/jsonl?export_type=dpo")
    assert sft.status_code == 200
    assert "messages" in sft.text
    assert dpo.status_code == 200
    assert "preferred_output" in dpo.text


def test_task_draft_autosaves_and_is_cleared_on_submit():
    client, engine = build_client()

    with Session(engine) as session:
        asset = Asset(
            human_id="ASSET_DRAFT_REVIEW",
            asset_type="text",
            title="Draft review source",
            mime_type="text/plain",
        )
        session.add(asset)
        session.flush()
        segment = Segment(
            human_id="SEG_DRAFT_REVIEW",
            asset_id=asset.id,
            segment_type="text_preview",
            title="Draft review preview",
            text_content="A small source text.",
        )
        session.add(segment)
        session.flush()
        task = Task(
            human_id="TASK_DRAFT_REVIEW",
            task_type="text_segment_review",
            target_type="segment",
            target_id=segment.id,
            queue="text_segments_needing_review",
            input_payload={"asset_id": asset.id, "source_filename": "draft.txt"},
            created_by="text_extraction",
        )
        session.add(task)
        session.commit()
        task_id = task.id

    saved = client.put(
        f"/api/tasks/{task_id}/draft",
        json={
            "decisions": {
                "source_genre": "letter",
                "authorship": "third_party",
                "authorship_note": "Not Charles voice, but part of the source world.",
            },
            "notes": "Mid-review scratch note.",
        },
    )

    assert saved.status_code == 200
    assert saved.json()["decisions"]["source_genre"] == "letter"
    assert saved.json()["notes"] == "Mid-review scratch note."

    loaded = client.get(f"/api/tasks/{task_id}/draft")
    assert loaded.status_code == 200
    assert loaded.json()["decisions"]["authorship"] == "third_party"

    submitted = client.post(
        f"/api/tasks/{task_id}/submit",
        json={
            "decisions": {
                "segment_boundary_good": "yes",
                "source_genre": "letter",
                "authorship": "third_party",
                "fictionality_status": "factual",
                "truth_status": "archival_source",
                "voice_presence": "context_only",
                "usable_for_voice_context": "yes",
                "usable_for_grounded_generation": "no",
                "boundary_rationale": "Local context only.",
            },
            "notes": "Final review.",
        },
    )

    assert submitted.status_code == 200
    with Session(engine) as session:
        assert session.exec(select(TaskDraft)).first() is None


def test_text_source_review_submission_creates_processing_task_then_prompt_candidate():
    client, engine = build_client()

    with Session(engine) as session:
        asset = Asset(
            human_id="ASSET_TEXT_REVIEW",
            asset_type="text",
            title="Novel draft",
            mime_type="text/plain",
        )
        session.add(asset)
        creator = Entity(
            human_id="CR_ENTITY_CATHRYN_TEST",
            entity_type="person",
            canonical_name="Cathryn",
            relationship_to_charles="family",
            relationship_to_adam="family",
            confidence="medium",
        )
        session.add(creator)
        session.flush()
        preview = Segment(
            human_id="SEG_PREVIEW_REVIEW",
            asset_id=asset.id,
            segment_type="text_preview",
            title="Novel draft preview",
            text_content="Adam walks into a room and Charles narrates.",
        )
        chunk = Segment(
            human_id="SEG_CHUNK_REVIEW_0001",
            asset_id=asset.id,
            segment_type="text_chunk",
            title="Novel draft chunk 1",
            text_content="This is a useful chunk for grounded prompt work.",
            locator={"chunk_index": 1, "char_start": 0, "char_end": 49},
        )
        session.add(preview)
        session.add(chunk)
        session.flush()
        task = Task(
            human_id="TASK_TEXT_REVIEW",
            task_type="text_segment_review",
            target_type="segment",
            target_id=preview.id,
            queue="text_segments_needing_review",
            input_payload={"asset_id": asset.id, "source_filename": "novel.txt"},
            created_by="text_extraction",
        )
        session.add(task)
        session.commit()
        task_id = task.id
        chunk_id = chunk.id
        preview_id = preview.id
        creator_id = creator.id

    response = client.post(
        f"/api/tasks/{task_id}/submit",
        json={
            "decisions": {
                "segment_boundary_good": "yes",
                "source_genre": "novel_draft",
                "authorship": "third_party",
                "creator_entity_ids": [creator_id],
                "creator_name": "Cathryn",
                "authorship_note": "Cathryn wrote this piece; Charles kept it as source context, but it is not Charles voice.",
                "fictionality_status": "fiction",
                "truth_status": "archival_source",
                "voice_presence": "context_only",
                "adam_context_note": "Third-party source Charles kept; useful as context but not as Charles voice.",
                "ready_for_processing": "yes",
                "privacy_level": "family_private",
                "usable_for_voice_context": "yes",
                "usable_for_grounded_generation": "yes",
                "cleaned_text": "Reviewed cleaned text for annotation storage.",
                "cleaned_text_scope": "active_chunk",
                "cleaned_text_chunk_id": chunk_id,
                "privacy_notes": "Safe for local source review.",
            },
            "notes": "Good source candidate.",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["creates_or_updates"]["reviewed_segment_id"] == preview_id
    assert body["creates_or_updates"]["reviewed_chunk_ids"] == []
    assert body["creates_or_updates"]["segment_boundary_review_task_id"]

    with Session(engine) as session:
        preview = session.get(Segment, preview_id)
        chunk = session.get(Segment, chunk_id)
        boundary = session.exec(select(Boundary).where(Boundary.target_id == preview_id)).first()
        boundary_task = session.get(Task, body["creates_or_updates"]["segment_boundary_review_task_id"])
        profile = session.get(MetadataProfile, body["creates_or_updates"]["metadata_profile_id"])

        assert preview.maturity_level == "L3_reviewed"
        assert preview.metadata_json["latest_source_review"]["source_genre"] == "novel_draft"
        assert "selected_for_grounded_generation" not in chunk.metadata_json
        assert boundary is not None
        assert boundary.usable_for_voice_context is True
        assert boundary_task is not None
        assert boundary_task.task_type == "text_segment_boundary_review"
        assert boundary_task.queue == "text_segments_needing_boundary_review"
        assert boundary_task.input_payload["source_review_annotation_id"] == body["id"]
        assert profile is not None
        assert profile.profile_type == "novel_draft"
        assert profile.metadata_status == "adam_reviewed"
        assert profile.authorship == "third_party"
        assert profile.creator_entity_ids == [creator_id]
        assert profile.authorship_note == "Cathryn wrote this piece; Charles kept it as source context, but it is not Charles voice."
        assert profile.fictionality_status == "fiction"
        assert profile.voice_presence == "context_only"
        assert profile.adam_context_note == "Third-party source Charles kept; useful as context but not as Charles voice."
        assert profile.themes == []
        assert profile.embedding_hints.get("selected_chunk_ids", []) == []
        assert profile.raw_profile["cleaned_text"] == "[stored on annotation only]"
        assert boundary.notes == "Safe for local source review."

    boundary_task_id = body["creates_or_updates"]["segment_boundary_review_task_id"]
    boundary_response = client.post(
        f"/api/tasks/{boundary_task_id}/submit",
        json={
            "decisions": {
                "segment_boundary_status": "approved_chunks",
                "selected_chunk_ids": [chunk_id],
                "chunk_scope": "selected_chunks",
                "source_use_modes": ["verbatim_preferred", "grounded_synthesis_allowed"],
                "source_use_mode": "grounded_synthesis_allowed",
                "prompt_pair_decision": "yes",
                "prompt_pair_potential": "high",
                "quote_policy": "source_quote_allowed_after_boundary_review",
                "privacy_clearance": "ok_for_local_generation",
                "privacy_notes": "Use locally; review before export.",
            },
            "notes": "Boundaries look usable.",
        },
    )

    assert boundary_response.status_code == 200
    boundary_body = boundary_response.json()
    assert boundary_body["creates_or_updates"]["reviewed_chunk_ids"] == [chunk_id]
    assert boundary_body["creates_or_updates"]["prompt_pair_candidate_task_id"]

    with Session(engine) as session:
        chunk = session.get(Segment, chunk_id)
        candidate = session.get(Task, boundary_body["creates_or_updates"]["prompt_pair_candidate_task_id"])
        preview = session.get(Segment, preview_id)
        boundary = session.exec(select(Boundary).where(Boundary.target_id == preview_id)).first()

        assert preview.maturity_level == "L4_boundary_reviewed"
        assert chunk.metadata_json["selected_for_grounded_generation"] is True
        assert chunk.metadata_json["source_use_modes"] == ["verbatim_preferred", "grounded_synthesis_allowed"]
        assert boundary.quotable is True
        assert candidate is not None
        assert candidate.task_type == "grounded_prompt_pair_candidate"
        assert candidate.input_payload["segment_boundary_review_annotation_id"] == boundary_body["id"]
        assert candidate.input_payload["source_use_modes"] == ["verbatim_preferred", "grounded_synthesis_allowed"]


def test_boundary_review_needs_split_does_not_create_prompt_candidate():
    client, engine = build_client()

    with Session(engine) as session:
        asset = Asset(
            human_id="ASSET_BOUNDARY_SPLIT",
            asset_type="text",
            title="Long draft",
            mime_type="text/plain",
        )
        session.add(asset)
        session.flush()
        preview = Segment(
            human_id="SEG_BOUNDARY_SPLIT_PREVIEW",
            asset_id=asset.id,
            segment_type="text_preview",
            title="Long draft preview",
            text_content="A preview that needs cleaner segmentation.",
        )
        chunk = Segment(
            human_id="SEG_BOUNDARY_SPLIT_CHUNK",
            asset_id=asset.id,
            segment_type="text_chunk",
            title="Long draft chunk",
            text_content="This chunk contains several moments and should be split before prompt work.",
            locator={"chunk_index": 1, "char_start": 0, "char_end": 72},
        )
        session.add(preview)
        session.add(chunk)
        session.flush()
        task = Task(
            human_id="TASK_BOUNDARY_SPLIT",
            task_type="text_segment_boundary_review",
            target_type="segment",
            target_id=preview.id,
            queue="text_segments_needing_boundary_review",
            input_payload={"asset_id": asset.id, "segment_id": preview.id},
            created_by="source_review",
        )
        session.add(task)
        session.commit()
        task_id = task.id
        chunk_id = chunk.id
        preview_id = preview.id

    response = client.post(
        f"/api/tasks/{task_id}/submit",
        json={
            "decisions": {
                "segment_boundary_status": "needs_split",
                "selected_chunk_ids": [chunk_id],
                "chunk_scope": "selected_chunks",
                "source_use_mode": "grounded_synthesis_allowed",
                "prompt_pair_potential": "high",
                "privacy_clearance": "ok_for_local_generation",
                "segmentation_notes": "This chunk contains multiple scenes; split before using it.",
                "privacy_notes": "Local only until cleaner boundaries exist.",
            },
            "notes": "Needs another segmentation pass.",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["creates_or_updates"]["reviewed_chunk_ids"] == [chunk_id]
    assert body["creates_or_updates"]["prompt_pair_candidate_task_id"] is None

    with Session(engine) as session:
        preview = session.get(Segment, preview_id)
        chunk = session.get(Segment, chunk_id)
        candidates = session.exec(select(Task).where(Task.task_type == "grounded_prompt_pair_candidate")).all()

        assert candidates == []
        assert chunk.metadata_json["selected_for_grounded_generation"] is False
        assert preview.metadata_json["latest_segment_boundary_review"]["ready_for_prompt_pair_factory"] == "no"
        assert preview.metadata_json["latest_segment_boundary_review"]["segmentation_notes"].startswith("This chunk")


def test_metadata_profile_endpoint_crud():
    client, _engine = build_client()

    created = client.post(
        "/api/metadata-profiles",
        json={
            "target_type": "segment",
            "target_id": "seg_test",
            "profile_type": "document_text",
            "metadata_status": "machine_draft",
            "title": "Draft profile",
            "summary": "A short draft summary.",
            "people": ["Charles"],
            "themes": ["photography"],
            "embedding_hints": {"profile_use": ["retrieval"]},
        },
    )

    assert created.status_code == 200
    profile_id = created.json()["id"]

    updated = client.patch(
        f"/api/metadata-profiles/{profile_id}",
        json={
            "metadata_status": "adam_reviewed",
            "reviewed_by": "adam",
            "adam_context_note": "This is useful as archive context.",
        },
    )

    assert updated.status_code == 200
    body = updated.json()
    assert body["metadata_status"] == "adam_reviewed"
    assert body["reviewed_at"]

    listed = client.get("/api/metadata-profiles?target_type=segment&target_id=seg_test")
    assert listed.status_code == 200
    assert listed.json()[0]["id"] == profile_id


def test_prompt_pair_candidate_submission_creates_stub_gold_edit_task():
    client, engine = build_client()

    with Session(engine) as session:
        asset = Asset(
            human_id="ASSET_PROMPT_PAIR_FACTORY",
            asset_type="text",
            title="Prompt pair source",
            mime_type="text/plain",
        )
        session.add(asset)
        session.flush()
        segment = Segment(
            human_id="SEG_PROMPT_PAIR_FACTORY",
            asset_id=asset.id,
            segment_type="text_preview",
            title="Factory source segment",
            text_content="The house is too quiet now. The cup is still in the sink.",
        )
        chunk = Segment(
            human_id="SEG_PROMPT_PAIR_FACTORY_CHUNK",
            asset_id=asset.id,
            segment_type="text_chunk",
            title="Factory source chunk",
            text_content="The cup is still in the sink. Call when you get in.",
            locator={"chunk_index": 1, "char_start": 0, "char_end": 51},
        )
        session.add(segment)
        session.add(chunk)
        session.flush()
        task = Task(
            human_id="TASK_PROMPT_PAIR_FACTORY",
            task_type="grounded_prompt_pair_candidate",
            target_type="segment",
            target_id=segment.id,
            queue="grounded_prompt_pairs_needing_drafts",
            input_payload={
                "segment_id": segment.id,
                "asset_id": asset.id,
                "selected_chunk_ids": [chunk.id],
                "source_review_annotation_id": "ann_source_review",
            },
            required_decisions=[
                "prompt_intent",
                "source_chunks_to_use",
                "target_response_shape",
                "boundary_clearance_needed",
            ],
            created_by="source_review",
        )
        session.add(task)
        session.commit()
        task_id = task.id
        chunk_id = chunk.id

    response = client.post(
        f"/api/tasks/{task_id}/submit",
        json={
            "decisions": {
                "prompt_intent": "email_reply_candidate",
                "source_chunks_to_use": [chunk_id],
                "voice_mode": "father_to_adam",
                "truth_mode": "adam_expert_reconstruction",
                "target_response_shape": "short_email_reply",
                "boundary_clearance_needed": "review_before_export",
            },
            "notes": "Create a stubbed prompt pair draft.",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["annotation_type"] == "grounded_prompt_pair_candidate"
    assert body["creates_or_updates"]["review_task_id"]

    with Session(engine) as session:
        factory_task = session.get(Task, task_id)
        review_task = session.get(Task, body["creates_or_updates"]["review_task_id"])
        generation = session.get(Generation, body["creates_or_updates"]["generation_id"])
        prompt = session.get(PromptSpec, body["creates_or_updates"]["prompt_spec_id"])

        assert factory_task.status == "submitted"
        assert review_task.task_type == "gold_voice_edit"
        assert review_task.queue == "prompt_pairs_needing_gold_edits"
        assert review_task.input_payload["prompt_pair_factory_no_model_call"] is True
        assert review_task.input_payload["source_excerpt"].startswith("The cup is still")
        assert generation.model_name == "prompt_pair_factory_stub_no_model_call"
        assert generation.model_parameters["no_live_model_call"] is True
        assert prompt.prompt_type == "grounded_prompt_pair"
