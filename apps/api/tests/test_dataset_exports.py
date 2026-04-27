from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.db.session import get_session
from app.main import app
from app.models import ContextPack, GoldVoiceExample, SFTCandidate


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


def add_gold_with_sft(session: Session, human_id: str, boundary_status: str, export_status: str = "approved") -> None:
    context = ContextPack(
        human_id=f"CTX_{human_id}",
        user_intent="gold_voice_generation",
        requested_voice_mode="father_to_adam",
        truth_mode="adam_expert_reconstruction",
        boundaries_snapshot={"boundary_status": boundary_status},
    )
    session.add(context)
    session.flush()
    gold = GoldVoiceExample(
        human_id=human_id,
        context_pack_id=context.id,
        voice_mode="father_to_adam",
        truth_status="adam_expert_reconstruction",
        adam_gold_edit="house is quiet now. call when you get in.",
        downstream_use={"sft": True},
        ratings={
            "response_rubric": {
                "response_b": {
                    "privacy_export_safety": {"status": "no_issues"},
                }
            }
        },
    )
    session.add(gold)
    session.flush()
    session.add(
        SFTCandidate(
            source_gold_voice_example_id=gold.id,
            messages=[
                {"role": "system", "content": "Write in Charles voice."},
                {"role": "user", "content": "Say goodnight."},
                {"role": "assistant", "content": gold.adam_gold_edit},
            ],
            export_status=export_status,
        )
    )


def test_export_dry_run_excludes_boundary_blocked_and_candidate_items():
    client, engine = build_client()
    with Session(engine) as session:
        add_gold_with_sft(session, "GOLD_APPROVED", "passed")
        add_gold_with_sft(session, "GOLD_BLOCKED", "blocked")
        add_gold_with_sft(session, "GOLD_CANDIDATE", "passed", export_status="candidate")
        session.commit()

    dry_run = client.get("/api/dataset-exports/dry-run?export_type=sft")
    assert dry_run.status_code == 200
    body = dry_run.json()
    assert body["included_count"] == 1
    assert body["excluded_count"] == 2
    assert body["included"][0]["source"]["gold_human_id"] == "GOLD_APPROVED"
    assert body["included"][0]["source"]["context_boundary_status"] == "passed"
    reasons = [reason for item in body["excluded"] for reason in item["reasons"]]
    assert "context_pack_boundary_blocked" in reasons
    assert "artifact_status_is_candidate" in reasons

    jsonl = client.get("/api/dataset-exports/jsonl?export_type=sft")
    assert jsonl.status_code == 200
    assert jsonl.text.count("\n") == 1

    export = client.post("/api/dataset-exports/build", json={"export_type": "sft", "version": "v-test"})
    assert export.status_code == 200
    manifest = export.json()["manifest"]
    assert manifest["item_count"] == 1
    assert manifest["dry_run"]["excluded_count"] == 2
