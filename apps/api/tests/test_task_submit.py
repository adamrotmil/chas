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
    Generation,
    GoldVoiceExample,
    PromptSpec,
    SFTCandidate,
    Segment,
    Task,
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
                "failure_modes": ["too_generic", "too_therapy_like"],
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
        assert session.exec(select(GoldVoiceExample)).first()
        assert session.exec(select(SFTCandidate)).first().export_status == "approved"
        assert session.exec(select(DPOPair)).first().export_status == "approved"
        assert session.exec(select(AntiPattern)).first()

    sft = client.get("/api/dataset-exports/jsonl?export_type=sft")
    dpo = client.get("/api/dataset-exports/jsonl?export_type=dpo")
    assert sft.status_code == 200
    assert "messages" in sft.text
    assert dpo.status_code == 200
    assert "preferred_output" in dpo.text


def test_text_source_review_submission_updates_segment_boundary_and_candidate_task():
    client, engine = build_client()

    with Session(engine) as session:
        asset = Asset(
            human_id="ASSET_TEXT_REVIEW",
            asset_type="text",
            title="Novel draft",
            mime_type="text/plain",
        )
        session.add(asset)
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

    response = client.post(
        f"/api/tasks/{task_id}/submit",
        json={
            "decisions": {
                "segment_boundary_good": "yes",
                "source_genre": "novel_draft",
                "authorship": "charles",
                "voice_role": "primary_charles_voice",
                "truth_status": "archival_source",
                "themes": ["fiction", "family"],
                "prompt_pair_potential": "high",
                "usable_for_voice_context": "yes",
                "usable_for_grounded_generation": "yes",
                "selected_chunk_ids": [chunk_id],
                "chunk_scope": "selected_chunks",
                "boundary_notes": "Safe for local source review.",
            },
            "notes": "Good source candidate.",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["creates_or_updates"]["reviewed_segment_id"] == preview_id
    assert body["creates_or_updates"]["reviewed_chunk_ids"] == [chunk_id]
    assert body["creates_or_updates"]["prompt_pair_candidate_task_id"]

    with Session(engine) as session:
        preview = session.get(Segment, preview_id)
        chunk = session.get(Segment, chunk_id)
        boundary = session.exec(select(Boundary).where(Boundary.target_id == preview_id)).first()
        candidate = session.get(Task, body["creates_or_updates"]["prompt_pair_candidate_task_id"])

        assert preview.maturity_level == "L3_reviewed"
        assert preview.metadata_json["latest_source_review"]["source_genre"] == "novel_draft"
        assert chunk.metadata_json["selected_for_grounded_generation"] is True
        assert boundary is not None
        assert boundary.usable_for_voice_context is True
        assert candidate is not None
        assert candidate.task_type == "grounded_prompt_pair_candidate"
