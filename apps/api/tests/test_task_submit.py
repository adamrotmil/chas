from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select
from fastapi.testclient import TestClient

from app.db.session import get_session
from app.main import app
from app.models import (
    AntiPattern,
    ContextPack,
    DPOPair,
    Generation,
    GoldVoiceExample,
    PromptSpec,
    SFTCandidate,
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
