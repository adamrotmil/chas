from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.config import Settings, get_settings
from app.db.session import get_session
from app.main import app
from app.models import EmbeddingRecord, MetadataProfile, Task


def build_client(app_settings: Settings):
    app_settings = app_settings.model_copy(update={"chat_require_live_model": False})
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
    app.dependency_overrides[get_settings] = lambda: app_settings
    return TestClient(app), engine


def seed_ai_spine_inventory(engine) -> None:
    with Session(engine) as session:
        session.add(
            Task(
                human_id="TASK_AI_SPINE_DPO",
                task_type="gold_voice_edit",
                target_type="prompt_pair",
                target_id="pair-ai-spine",
                queue="prompt_pairs_needing_gold_edits",
                input_payload={"artifact_mode": "dpo"},
                created_by="test",
            )
        )
        session.add(
            Task(
                human_id="TASK_AI_SPINE_VISION",
                task_type="vision_draft_review",
                target_type="asset",
                target_id="asset-ai-spine",
                queue="vision_drafts_needing_review",
                input_payload={"asset_title": "Photo needing review", "no_live_model_call": True},
                created_by="test",
            )
        )
        session.add(
            MetadataProfile(
                target_type="asset",
                target_id="asset-ai-spine",
                profile_type="vision_draft",
                raw_profile={"no_live_model_call": True},
                quality_signals={"no_live_model_call": True},
            )
        )
        session.commit()


def test_ai_spine_audit_reports_live_text_and_scaffold_vision() -> None:
    client, engine = build_client(
        Settings(
            openai_api_key="test-key",
            text_generation_live_calls_enabled=True,
            text_generation_model="gpt-5.5",
            text_generation_reasoning_effort="medium",
            vision_live_calls_enabled=False,
        )
    )
    seed_ai_spine_inventory(engine)

    response = client.get("/api/ai-spine/audit")

    assert response.status_code == 200
    body = response.json()
    assert body["audit_type"] == "ai_spine_audit"
    assert body["summary"]["text_generation_ready"] is True
    assert body["summary"]["vision_live_ready"] is False
    assert body["providers"]["text_generation"]["model"] == "gpt-5.5"
    assert body["counts"]["vision_review_task_count"] == 1
    assert body["counts"]["no_live_vision_profile_count"] == 1
    assert body["counts"]["no_live_vision_ready_task_count"] == 1
    paths = {path["id"]: path for path in body["paths"]}
    assert paths["chat_operator"]["status"] == "live_ready"
    assert paths["vision_pipeline"]["status"] == "scaffold"
    assert paths["vision_pipeline"]["live_capability"] == "blocked_by_env"
    assert any(risk["path_id"] == "vision_pipeline" and risk["severity"] == "high" for risk in body["risks"])


def test_ai_spine_audit_reports_text_fallback_when_credentials_are_missing() -> None:
    client, _engine = build_client(
        Settings(
            openai_api_key="",
            text_generation_live_calls_enabled=True,
            vision_live_calls_enabled=False,
        )
    )

    response = client.get("/api/ai-spine/audit")

    assert response.status_code == 200
    body = response.json()
    assert body["summary"]["text_generation_ready"] is False
    assert body["providers"]["text_generation"]["api_key_configured"] is False
    paths = {path["id"]: path for path in body["paths"]}
    assert paths["chat_operator"]["status"] == "fallback"
    assert paths["text_draft_generation"]["status"] == "scaffold"


def test_ai_spine_audit_reports_live_vision_when_gate_and_key_are_configured() -> None:
    client, _engine = build_client(
        Settings(
            openai_api_key="test-key",
            text_generation_live_calls_enabled=True,
            vision_live_calls_enabled=True,
            vision_model="gpt-4.1-mini",
        )
    )

    response = client.get("/api/ai-spine/audit")

    assert response.status_code == 200
    body = response.json()
    assert body["summary"]["vision_live_ready"] is True
    assert body["providers"]["vision"]["ready"] is True
    paths = {path["id"]: path for path in body["paths"]}
    assert paths["vision_pipeline"]["status"] == "live_ready"
    assert paths["vision_pipeline"]["live_capability"] == "available"


def test_ai_spine_audit_prioritizes_live_vision_scaffold_backlog() -> None:
    client, engine = build_client(
        Settings(
            openai_api_key="test-key",
            text_generation_live_calls_enabled=True,
            vision_live_calls_enabled=True,
            embedding_live_calls_enabled=True,
        )
    )
    with Session(engine) as session:
        session.add(
            Task(
                human_id="TASK_AI_SPINE_NO_LIVE_VISION",
                task_type="vision_draft_review",
                target_type="metadata_profile",
                target_id="profile-no-live",
                queue="vision_drafts_needing_review",
                status="ready",
                input_payload={"asset_title": "Scaffolded photo", "no_live_model_call": True},
                created_by="test",
            )
        )
        session.add(
            MetadataProfile(
                target_type="asset",
                target_id="asset-no-live",
                profile_type="photo_memory",
                raw_profile={"no_live_model_call": True},
                quality_signals={"no_live_model_call": True},
            )
        )
        session.commit()

    response = client.get("/api/ai-spine/audit")

    assert response.status_code == 200
    body = response.json()
    assert body["summary"]["vision_live_ready"] is True
    assert body["summary"]["highest_risk"] == "vision_scaffold_backlog"
    assert body["summary"]["recommended_next_step"] == "Run live vision for remaining scaffolded ready review tasks."
    assert body["providers"]["vision"]["no_live_vision_ready_task_count"] == 1
    assert body["counts"]["no_live_vision_profile_count"] == 1
    assert body["counts"]["no_live_vision_ready_task_count"] == 1
    paths = {path["id"]: path for path in body["paths"]}
    assert "1 ready vision review task(s)" in " ".join(paths["vision_pipeline"]["risks"])


def test_ai_spine_audit_reports_vector_inventory_and_backlog() -> None:
    client, engine = build_client(
        Settings(
            openai_api_key="test-key",
            text_generation_live_calls_enabled=True,
            vision_live_calls_enabled=True,
            embedding_live_calls_enabled=True,
        )
    )
    with Session(engine) as session:
        session.add(
            EmbeddingRecord(
                target_type="gold_voice",
                target_id="gold-vectorized",
                embedding_type="gold_voice_text",
                modality="text",
                model_name="text-embedding-3-small",
                input_checksum="checksum-vectorized",
                input_text="Vectorized approved voice evidence.",
                input_preview="Vectorized approved voice evidence.",
                status="embedded",
                vector_uri="local://embedding_vectors/gold-vectorized.json",
                vector_dims=1536,
                truth_status="adam_expert_reconstruction",
            )
        )
        session.add(
            EmbeddingRecord(
                target_type="gold_voice",
                target_id="gold-ready",
                embedding_type="gold_voice_text",
                modality="text",
                model_name="pending_text_embedding",
                input_checksum="checksum-ready",
                input_text="Approved voice evidence waiting for embedding.",
                input_preview="Approved voice evidence waiting for embedding.",
                status="ready_for_embedding",
                truth_status="adam_expert_reconstruction",
            )
        )
        session.commit()

    response = client.get("/api/ai-spine/audit")

    assert response.status_code == 200
    body = response.json()
    assert body["summary"]["embedding_live_ready"] is True
    assert body["summary"]["embedded_text_record_count"] == 1
    assert body["summary"]["ready_for_embedding_count"] == 1
    assert body["summary"]["vector_ready"] is True
    assert body["summary"]["highest_risk"] == "embedding_backlog_not_vectorized"
    assert body["providers"]["embeddings"]["embedded_text_record_count"] == 1
    assert body["providers"]["embeddings"]["ready_for_embedding_count"] == 1


def test_ai_spine_audit_moves_to_source_cluster_creation_after_photo_cluster_action_exists() -> None:
    client, engine = build_client(
        Settings(
            openai_api_key="test-key",
            text_generation_live_calls_enabled=True,
            vision_live_calls_enabled=True,
            embedding_live_calls_enabled=True,
        )
    )
    with Session(engine) as session:
        session.add(
            EmbeddingRecord(
                target_type="gold_voice",
                target_id="gold-vectorized",
                embedding_type="gold_voice_text",
                modality="text",
                model_name="text-embedding-3-small",
                input_checksum="checksum-vectorized",
                input_text="Vectorized approved voice evidence.",
                input_preview="Vectorized approved voice evidence.",
                status="embedded",
                vector_uri="local://embedding_vectors/gold-vectorized.json",
                vector_dims=1536,
                truth_status="adam_expert_reconstruction",
            )
        )
        session.commit()

    response = client.get("/api/ai-spine/audit")

    assert response.status_code == 200
    body = response.json()
    assert body["summary"]["vector_ready"] is True
    assert body["summary"]["vision_live_ready"] is True
    assert body["summary"]["ready_for_embedding_count"] == 0
    assert body["summary"]["highest_risk"] == "workflow_qa_unverified"
    assert body["summary"]["recommended_next_step"].startswith("QA the full evidence-cluster workflow")
    paths = {path["id"]: path for path in body["paths"]}
    assert any("Draft-edit claims are sanitized" in evidence for evidence in paths["chat_operator"]["evidence"])
    assert any("plan_ranked_evidence_clusters" in evidence for evidence in paths["chat_operator"]["evidence"])
    assert any("inspect_work_queue_plan" in evidence for evidence in paths["chat_operator"]["evidence"])
    assert any("create_or_open_review_task" in evidence for evidence in paths["chat_operator"]["evidence"])
    assert any("source_review task from a source cluster" in evidence for evidence in paths["chat_operator"]["evidence"])
    assert any("continue the same-route batch" in evidence for evidence in paths["chat_operator"]["evidence"])
    assert any("opens the first generated candidate" in evidence for evidence in paths["chat_operator"]["evidence"])
    assert any("ranked by evidence quality" in evidence for evidence in paths["chat_operator"]["evidence"])
    assert any("renders ranked evidence clusters" in evidence for evidence in paths["chat_operator"]["evidence"])
    assert any("ranked evidence packets" in evidence for evidence in paths["source_pair_generation"]["evidence"])
    assert any("Generated prompt-pair review UI shows evidence gate status" in evidence for evidence in paths["source_pair_generation"]["evidence"])
    assert any("request a source/photo review task from a cluster" in evidence for evidence in paths["source_pair_generation"]["evidence"])
    assert any("evidence-clusters" in evidence for evidence in paths["semantic_memory"]["evidence"])
    assert any("review-cluster control" in evidence for evidence in paths["semantic_memory"]["evidence"])
