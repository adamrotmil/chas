from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.config import Settings, get_settings
from app.db.session import get_session
from app.main import app
from app.models import Asset, EmbeddingRecord


def build_client(app_settings: Settings):
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


def assert_forbidden_vector_keys_absent(value):
    if isinstance(value, dict):
        assert "vector_uri" not in value
        assert "provider_record_id" not in value
        assert "vector_values" not in value
        for item in value.values():
            assert_forbidden_vector_keys_absent(item)
    elif isinstance(value, list):
        for item in value:
            assert_forbidden_vector_keys_absent(item)


def test_embedding_status_reports_live_gate(tmp_path):
    client, _ = build_client(
        Settings(
            openai_api_key="",
            embedding_live_calls_enabled=False,
            embedding_model="text-embedding-3-small",
            storage_root=str(tmp_path),
        )
    )

    response = client.get("/api/retrieval/embeddings/status")

    assert response.status_code == 200
    body = response.json()
    assert body["embedding_model"] == "text-embedding-3-small"
    assert body["embedding_live_ready"] is False
    assert body["vector_values_in_db"] is False
    assert body["vector_values_in_exports"] is False


def test_live_embedding_batch_writes_vector_pointer(monkeypatch, tmp_path):
    client, engine = build_client(
        Settings(
            openai_api_key="test-key",
            embedding_live_calls_enabled=True,
            embedding_model="text-embedding-3-small",
            storage_root=str(tmp_path),
        )
    )

    def fake_embedding_model(**kwargs):
        assert kwargs["model_name"] == "text-embedding-3-small"
        assert "Market Street breakfast" in kwargs["input_text"]
        return {"embedding": [0.1, 0.2, 0.3], "provider_record_id": "emb_live_test"}

    monkeypatch.setattr("app.services.embeddings._call_live_embedding_model", fake_embedding_model)
    with Session(engine) as session:
        record = EmbeddingRecord(
            target_type="memory",
            target_id="memory-live-embedding",
            embedding_type="memory_text",
            modality="text",
            model_name="pending_text_embedding",
            input_checksum="checksum-live",
            input_text="Market Street breakfast with family memory context.",
            input_preview="Market Street breakfast",
            status="ready_for_embedding",
            metadata_json={"source": "photo_memory_review"},
        )
        session.add(record)
        session.commit()
        record_id = record.id

    response = client.post("/api/retrieval/embeddings/live-batch?limit=5")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "completed"
    assert body["created_count"] == 1
    assert body["embedded_record_ids"] == [record_id]

    with Session(engine) as session:
        record = session.get(EmbeddingRecord, record_id)
        assert record is not None
        assert record.status == "embedded"
        assert record.model_name == "text-embedding-3-small"
        assert record.vector_dims == 3
        assert record.vector_uri == f"local://embedding_vectors/{record_id}.json"
        assert record.provider_record_id == "emb_live_test"
        assert record.metadata_json["live_embedding_call"] is True
        assert record.metadata_json["vector_values_in_db"] is False
        vector_path = tmp_path / "embedding_vectors" / f"{record_id}.json"
        assert vector_path.is_file()
        assert '"embedding":[0.1,0.2,0.3]' in vector_path.read_text()


def test_retrieval_search_uses_live_query_vector_for_embedded_records(monkeypatch, tmp_path):
    client, engine = build_client(
        Settings(
            openai_api_key="test-key",
            embedding_live_calls_enabled=True,
            embedding_model="text-embedding-3-small",
            storage_root=str(tmp_path),
        )
    )

    def fake_embedding_model(**kwargs):
        return {"embedding": [0.4, 0.5, 0.6], "provider_record_id": "emb_query_test"}

    monkeypatch.setattr("app.services.embeddings._call_live_embedding_model", fake_embedding_model)
    with Session(engine) as session:
        record = EmbeddingRecord(
            target_type="memory",
            target_id="memory-vector-only",
            embedding_type="memory_text",
            modality="text",
            model_name="pending_text_embedding",
            input_checksum="checksum-vector",
            input_text="Words with no lexical overlap.",
            input_preview="Words with no lexical overlap.",
            status="ready_for_embedding",
            truth_status="adam_memory",
            boundary_snapshot={"reviewed_by": "adam", "privacy_level": "family_private", "searchable": True, "retrievable_in_chat": True},
            metadata_json={"source": "photo_memory_review"},
        )
        session.add(record)
        session.commit()
        record_id = record.id

    embed_response = client.post("/api/retrieval/embeddings/live-batch?limit=1")
    assert embed_response.status_code == 200

    search_response = client.get("/api/retrieval/search?q=breakfast&scope=family_private&limit=5")

    assert search_response.status_code == 200
    body = search_response.json()
    assert body["retrieval_strategy"] == "boundary_filtered_vector_similarity_with_lexical_fallback"
    assert body["vector_query_used"] is True
    assert body["results"][0]["embedding_record_id"] == record_id
    assert body["results"][0]["lexical_score"] == 0
    assert body["results"][0]["vector_similarity"] > 0.99
    assert body["results"][0]["why_matched"].startswith("Vector similarity")


def test_unified_evidence_corpus_lists_reviewed_and_holds_unreviewed(tmp_path):
    client, engine = build_client(
        Settings(
            openai_api_key="",
            embedding_live_calls_enabled=False,
            embedding_model="text-embedding-3-small",
            storage_root=str(tmp_path),
        )
    )
    with Session(engine) as session:
        session.add(
            EmbeddingRecord(
                target_type="gold_voice_example",
                target_id="gold-reviewed",
                embedding_type="gold_voice_text",
                modality="text",
                model_name="pending_text_embedding",
                input_checksum="checksum-gold",
                input_text="voice_mode: father_to_adam\nassistant: porch light is on",
                input_preview="porch light is on",
                status="ready_for_embedding",
                truth_status="adam_expert_reconstruction",
                metadata_json={"source": "gold_voice_edit", "source_annotation_id": "annotation-gold"},
            )
        )
        session.add(
            EmbeddingRecord(
                target_type="memory",
                target_id="machine-photo-memory",
                embedding_type="memory_text",
                modality="text",
                model_name="pending_text_embedding",
                input_checksum="checksum-photo",
                input_text="machine draft photo memory awaiting Adam context",
                input_preview="machine draft photo memory",
                status="ready_for_embedding",
                truth_status="system_inference",
                boundary_snapshot={
                    "privacy_level": "family_private",
                    "searchable": True,
                    "retrievable_in_chat": True,
                    "reviewed_by": "system",
                },
                metadata_json={"source": "photo_memory_machine_draft", "asset_id": "asset-photo"},
            )
        )
        session.commit()

    response = client.get("/api/retrieval/evidence-corpus?scope=family_private&limit=10")

    assert response.status_code == 200
    body = response.json()
    assert body["corpus_type"] == "unified_evidence_embedding_corpus"
    assert body["record_count"] == 1
    assert body["excluded_count"] == 1
    assert body["records"][0]["corpus_family"] == "approved_training_voice"
    assert body["records"][0]["review_status"] == "reviewed_or_approved"
    assert body["excluded"][0]["corpus_family"] == "photo_memory"
    assert body["excluded"][0]["excluded_reason"] == "held_for_adam_review"

    preview = client.get("/api/retrieval/evidence-corpus?scope=family_private&limit=10&include_unreviewed=true")
    assert preview.status_code == 200
    assert preview.json()["record_count"] == 2


def test_ranked_evidence_clusters_group_source_records_and_omit_vector_pointers(tmp_path):
    client, engine = build_client(
        Settings(
            openai_api_key="",
            embedding_live_calls_enabled=False,
            embedding_model="text-embedding-3-small",
            storage_root=str(tmp_path),
        )
    )
    boundary = {
        "boundary_status": "reviewed",
        "privacy_level": "family_private",
        "searchable": True,
        "retrievable_in_chat": True,
        "reviewed_by": "adam",
    }
    with Session(engine) as session:
        source_asset = Asset(
            human_id="ASSET_CLUSTER_JOURNAL",
            asset_type="text",
            title="Cooking journal",
            mime_type="text/plain",
        )
        photo_asset = Asset(
            human_id="ASSET_CLUSTER_PHOTO",
            asset_type="photo",
            title="Market Street breakfast photo",
            mime_type="image/jpeg",
            processing_status="image_preview_ready",
        )
        session.add(source_asset)
        session.add(photo_asset)
        session.flush()
        source_asset_id = source_asset.id
        photo_asset_id = photo_asset.id
        session.add(
            EmbeddingRecord(
                target_type="segment",
                target_id="segment-cooking-1",
                embedding_type="retrieval_text",
                modality="text",
                model_name="text-embedding-3-small",
                input_checksum="checksum-cooking-1",
                input_text="Breakfast cooking at Market Street with coffee and brie.",
                input_preview="Breakfast cooking at Market Street",
                status="embedded",
                vector_uri="local://embedding_vectors/source-secret-1.json",
                vector_dims=3,
                provider_record_id="provider-source-secret-1",
                truth_status="archival_source",
                metadata_json={"source": "source_review", "source_asset_id": source_asset_id, "source_segment_id": "segment-cooking-1"},
            )
        )
        session.add(
            EmbeddingRecord(
                target_type="segment",
                target_id="segment-cooking-2",
                embedding_type="retrieval_text",
                modality="text",
                model_name="text-embedding-3-small",
                input_checksum="checksum-cooking-2",
                input_text="Cooking notes about hunger, garlic, and learning by doing.",
                input_preview="Cooking notes about hunger",
                status="embedded",
                vector_uri="local://embedding_vectors/source-secret-2.json",
                vector_dims=3,
                provider_record_id="provider-source-secret-2",
                truth_status="archival_source",
                metadata_json={"source": "source_review", "source_asset_id": source_asset_id, "source_segment_id": "segment-cooking-2"},
            )
        )
        session.add(
            EmbeddingRecord(
                target_type="memory",
                target_id="memory-market-breakfast",
                embedding_type="memory_text",
                modality="text",
                model_name="text-embedding-3-small",
                input_checksum="checksum-photo-memory",
                input_text="Adam reviewed memory of a Market Street breakfast and learning to cook.",
                input_preview="Adam reviewed Market Street breakfast memory",
                status="embedded",
                vector_uri="local://embedding_vectors/photo-secret.json",
                vector_dims=3,
                provider_record_id="provider-photo-secret",
                truth_status="adam_memory",
                boundary_snapshot=boundary,
                metadata_json={"source": "photo_memory_review", "asset_id": photo_asset_id},
            )
        )
        session.commit()

    response = client.get("/api/retrieval/evidence-clusters?q=cooking breakfast&scope=family_private&limit=5&per_cluster_limit=2")

    assert response.status_code == 200
    body = response.json()
    assert body["plan_type"] == "ranked_evidence_cluster_plan"
    assert body["cluster_count"] >= 2
    assert body["source_result_count"] == 3
    assert_forbidden_vector_keys_absent(body)
    source_cluster = next(cluster for cluster in body["clusters"] if cluster["cluster_key"] == f"source_asset:{source_asset_id}")
    assert source_cluster["cluster_family"] == "source_context"
    assert source_cluster["display_title"] == "Cooking journal"
    assert source_cluster["record_count"] == 2
    assert len(source_cluster["top_records"]) == 2
    assert "document cluster" in source_cluster["planning_hint"]
    photo_cluster = next(cluster for cluster in body["clusters"] if cluster["cluster_key"] == f"photo:{photo_asset_id}")
    assert photo_cluster["cluster_family"] == "photo_memory"
    assert photo_cluster["top_records"][0]["truth_status"] == "adam_memory"
    assert photo_cluster["top_records"][0]["boundary_summary"]["reviewed_by"] == "adam"


def test_ranked_evidence_clusters_return_retrieval_gap_without_memory_claim(tmp_path):
    client, _engine = build_client(
        Settings(
            openai_api_key="",
            embedding_live_calls_enabled=False,
            embedding_model="text-embedding-3-small",
            storage_root=str(tmp_path),
        )
    )

    response = client.get("/api/retrieval/evidence-clusters?q=nonexistent%20query&scope=family_private&limit=3")

    assert response.status_code == 200
    body = response.json()
    assert body["cluster_count"] == 0
    assert body["retrieval_gap"]["status"] == "no_boundary_cleared_memory_result"
    assert body["retrieval_gap"]["truth_status"] == "no_claim"
    assert_forbidden_vector_keys_absent(body)


def test_retrieval_search_excludes_unreviewed_machine_photo_memory_by_default(tmp_path):
    client, engine = build_client(
        Settings(
            openai_api_key="",
            embedding_live_calls_enabled=False,
            embedding_model="text-embedding-3-small",
            storage_root=str(tmp_path),
        )
    )
    boundary = {
        "privacy_level": "family_private",
        "searchable": True,
        "retrievable_in_chat": True,
        "reviewed_by": "adam",
    }
    with Session(engine) as session:
        session.add(
            EmbeddingRecord(
                target_type="memory",
                target_id="machine-memory",
                embedding_type="memory_text",
                modality="text",
                model_name="pending_text_embedding",
                input_checksum="checksum-machine",
                input_text="breakfast on Market Street from a machine draft",
                input_preview="breakfast machine",
                status="ready_for_embedding",
                truth_status="system_inference",
                boundary_snapshot={**boundary, "reviewed_by": "system_draft"},
                metadata_json={"source": "photo_memory_machine_draft", "asset_id": "asset-machine"},
            )
        )
        session.add(
            EmbeddingRecord(
                target_type="memory",
                target_id="reviewed-memory",
                embedding_type="memory_text",
                modality="text",
                model_name="pending_text_embedding",
                input_checksum="checksum-reviewed",
                input_text="breakfast on Market Street from Adam reviewed memory",
                input_preview="breakfast reviewed",
                status="ready_for_embedding",
                truth_status="adam_memory",
                boundary_snapshot=boundary,
                metadata_json={"source": "photo_memory_review", "asset_id": "asset-reviewed"},
            )
        )
        session.commit()

    response = client.get("/api/retrieval/search?q=breakfast&scope=family_private&limit=10")

    assert response.status_code == 200
    body = response.json()
    assert [item["target_id"] for item in body["results"]] == ["reviewed-memory"]
    assert body["results"][0]["review_policy"]["requires_adam_review"] is False
