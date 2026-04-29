import hashlib
import json

from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select
from fastapi.testclient import TestClient

from app.db.session import get_session
from app.main import app
from app.config import Settings, get_settings
from app.models import Asset, Generation, PromptSpec, Task
from app.services.pair_export import compile_pair_export
from app.services.prompt_pair_reference_pack import select_prompt_pair_reference_examples
from app.services.prompt_pair_voice_modes import classify_prompt_pair_voice_mode
from app.services.prompt_pairs import create_prompt_pair_review_task
from app.runtime_contract import RUNTIME_CONTRACT, runtime_contract_payload


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


def test_runtime_contract_endpoint_matches_source_contract():
    client, _engine = build_client()

    response = client.get("/api/runtime-contract")

    assert response.status_code == 200
    body = response.json()
    expected = runtime_contract_payload()
    assert body["contract_id"] == RUNTIME_CONTRACT["contract_id"]
    assert body["contract_id"] == expected["contract_id"]
    assert body["runtime_contract_source_sha256"] == expected["runtime_contract_source_sha256"]
    assert body["required_response_fields"] == expected["required_response_fields"]
    assert body["no_fine_tuning_api_calls_in_mvp"] is True


def test_downstream_bottleneck_queue_is_api_ranked_and_machine_verifiable():
    client, engine = build_client()
    app.dependency_overrides[get_settings] = lambda: Settings(
        openai_api_key="",
        text_generation_live_calls_enabled=False,
    )

    with Session(engine) as session:
        decisions = {
            "artifact_mode": "sft",
            "system_prompt": "You are Charles Rotmil. Write naturally in his voice.",
            "prompt": "How's Portland today?",
            "content": "gray here...\nlight rain\n\nlove\ndad",
            "voice_mode": "mundane_text_message",
            "truth_status": "adam_expert_reconstruction",
            "rubric_summary": {"preferred_export_blocked": True},
        }
        compiled = compile_pair_export(decisions)
        session.add(
            Task(
                human_id="TASK_BOTTLENECK_PAIR",
                task_type="gold_voice_edit",
                target_type="prompt_pair",
                target_id="prompt_pair_bottleneck",
                queue="prompt_pairs_needing_gold_edits",
                input_payload={**decisions, "pair_index": 1, "export_preview_yaml": compiled["yaml_preview"]},
                created_by="test",
            )
        )
        photo = Asset(
            human_id="ASSET_BOTTLENECK_PHOTO",
            asset_type="photo",
            title="Airplane in Maine",
            original_filename="airplane-maine.jpg",
            mime_type="image/jpeg",
            processing_status="image_preview_ready",
        )
        session.add(photo)
        session.commit()

    response = client.get("/api/downstream-readiness/bottlenecks", params={"scope": "family_private", "limit": 4})

    assert response.status_code == 200
    queue = response.json()
    assert queue["queue_type"] == "downstream_bottleneck_queue"
    assert queue["review_policy"] == "ranked_operator_actions_no_source_mutation"
    assert queue["does_not_mutate_state"] is True
    assert queue["no_live_model_call"] is True
    assert queue["no_fine_tuning_api_calls_in_mvp"] is True
    assert queue["priority_policy"] == "priority_rank_ascending_then_count_descending"
    assert queue["ordered_area_keys"][:2] == ["prompt_pairs", "photo_context"]
    assert "demo_generation" in queue["ordered_area_keys"]
    assert len(queue["machine_verification"]["queue_sha256"]) == 64
    assert queue["machine_verification"]["every_item_has_action"] is True

    items = {item["area_key"]: item for item in queue["items"]}
    prompt_item = items["prompt_pairs"]
    assert prompt_item["priority_rank"] == 1
    assert prompt_item["count"] == 1
    assert prompt_item["action"]["enabled"] is True
    assert prompt_item["action"]["task_human_id"] == "TASK_BOTTLENECK_PAIR"
    assert prompt_item["policy"]["training_export_status"] == "candidate_until_gold_clearance"
    assert prompt_item["policy"]["does_not_certify_final_authenticity"] is True

    photo_item = items["photo_context"]
    assert photo_item["priority_rank"] == 2
    assert photo_item["count"] == 1
    assert photo_item["action"]["enabled"] is True
    assert photo_item["action"]["action_type"] == "create_photo_context_review_session"
    assert photo_item["action"]["label"] == "Create top context tasks"
    assert photo_item["policy"]["truth_status_before_review"] == "no_claim"
    assert photo_item["policy"]["not_memory_claim_until_adam_context"] is True

    demo_item = items["demo_generation"]
    assert demo_item["priority_rank"] == 4
    assert demo_item["action"]["enabled"] is False
    assert demo_item["source_metrics"]["model_name"] == "gpt-5.5"
    assert demo_item["source_metrics"]["reasoning_effort"] == "xhigh"
    assert set(demo_item["source_metrics"]["blockers"]) == {
        "text_generation_live_calls_disabled",
        "openai_api_key_missing",
    }
    assert demo_item["policy"]["outputs_truth_status"] == "model_generated"
    assert demo_item["policy"]["fine_tuning_api_calls_allowed"] is False

    contract = client.get("/api/runtime-contract").json()
    assert "/api/downstream-readiness/bottlenecks" in contract["required_response_fields"]


def test_downstream_artifact_manifest_lists_hashable_outputs_without_side_effects():
    client, _engine = build_client()

    response = client.get(
        "/api/downstream-readiness/artifact-manifest",
        params={"scope": "family_private", "prompt_sample_limit": 20, "vector_limit": 20},
    )

    assert response.status_code == 200
    manifest = response.json()
    assert manifest["manifest_type"] == "downstream_artifact_manifest"
    assert manifest["review_policy"] == "inspectable_outputs_no_build_side_effects"
    assert manifest["does_not_mutate_state"] is True
    assert manifest["no_live_model_call"] is True
    assert manifest["no_live_embedding_call"] is True
    assert manifest["no_fine_tuning_api_calls_in_mvp"] is True
    assert len(manifest["content_sha256"]) == 64
    assert manifest["artifact_count"] == len(manifest["items"]) >= 10
    assert {"jsonl", "markdown", "json", "yaml"}.issubset(set(manifest["formats"]))

    items = {item["artifact_key"]: item for item in manifest["items"]}
    required_keys = {
        "prompt_pair_audit_markdown",
        "prompt_pair_review_progress_json",
        "prompt_pair_top_blocker_session_plan_yaml",
        "prompt_pair_reference_jsonl",
        "prompt_pair_reference_markdown",
        "dataset_sft_approved_jsonl",
        "dataset_dpo_approved_jsonl",
        "dataset_sft_candidate_dry_run",
        "dataset_dpo_candidate_dry_run",
        "photo_context_pack_readiness_json",
        "photo_context_review_pack_yaml_preview",
        "photo_context_review_session_plan_yaml",
        "photo_context_session_progress_json",
        "photo_context_retrieval_gap_field_worklist_yaml",
        "photo_context_retrieval_gap_payoff_preview_yaml",
        "photo_vector_handoff_jsonl",
        "photo_vector_handoff_manifest",
        "morning_handoff_yaml",
        "dpo_rejected_reason_repair_yaml",
        "source_review_pair_generation_preview_json",
    }
    assert required_keys.issubset(set(items))
    for item in manifest["items"]:
        assert item["source_endpoint"].startswith("/api/")
        assert len(item["content_sha256"]) == 64
        assert item["format"] in {"jsonl", "markdown", "json", "yaml"}
        assert {"training", "vector", "gallery", "human_review"}.issubset(set(item["eligibility"]))
        assert isinstance(item["policy"], dict)

    assert items["prompt_pair_audit_markdown"]["eligibility"]["training"] is False
    assert items["prompt_pair_audit_markdown"]["eligibility"]["human_review"] is True
    assert items["prompt_pair_review_progress_json"]["artifact_family"] == "prompt_pair_review"
    assert items["prompt_pair_review_progress_json"]["format"] == "json"
    assert items["prompt_pair_review_progress_json"]["source_endpoint"] == "/api/prompt-pairs/review-progress"
    assert items["prompt_pair_review_progress_json"]["eligibility"]["training"] is False
    assert items["prompt_pair_review_progress_json"]["policy"]["does_not_mutate_state"] is True
    assert items["prompt_pair_review_progress_json"]["policy"]["does_not_promote_to_training_export"] is True
    assert items["prompt_pair_review_progress_json"]["policy"]["requires_adam_gold_edit"] is True
    assert items["prompt_pair_review_progress_json"]["policy"]["completion_signal"] == "candidate_count_decreases_or_blocker_worklist_changes"
    assert len(items["prompt_pair_review_progress_json"]["policy"]["progress_content_sha256"]) == 64
    assert items["prompt_pair_top_blocker_session_plan_yaml"]["artifact_family"] == "prompt_pair_review"
    assert items["prompt_pair_top_blocker_session_plan_yaml"]["format"] == "yaml"
    assert items["prompt_pair_top_blocker_session_plan_yaml"]["source_endpoint"] == "/api/prompt-pairs/top-blocker-review-session-plan?limit=5"
    assert items["prompt_pair_top_blocker_session_plan_yaml"]["download_endpoint"] == "/api/prompt-pairs/top-blocker-review-session-plan/yaml?limit=5"
    assert items["prompt_pair_top_blocker_session_plan_yaml"]["eligibility"]["training"] is False
    assert items["prompt_pair_top_blocker_session_plan_yaml"]["policy"]["does_not_mutate_state"] is True
    assert items["prompt_pair_top_blocker_session_plan_yaml"]["policy"]["does_not_promote_to_training_export"] is True
    assert items["prompt_pair_top_blocker_session_plan_yaml"]["policy"]["requires_adam_gold_edit"] is True
    assert items["prompt_pair_top_blocker_session_plan_yaml"]["policy"]["projected_task_delta"]["approved_exports_created"] == 0
    assert len(items["prompt_pair_top_blocker_session_plan_yaml"]["policy"]["content_sha256"]) == 64
    assert items["prompt_pair_reference_jsonl"]["eligibility"]["vector"] is True
    assert items["dataset_sft_approved_jsonl"]["eligibility"]["training"] is True
    assert items["dataset_sft_candidate_dry_run"]["eligibility"]["training"] is False
    assert items["photo_context_pack_readiness_json"]["artifact_family"] == "photo_context_review"
    assert items["photo_context_pack_readiness_json"]["format"] == "json"
    assert items["photo_context_pack_readiness_json"]["source_endpoint"].startswith(
        "/api/context-packs/photo-context-readiness-audit"
    )
    assert items["photo_context_pack_readiness_json"]["policy"]["does_not_mutate_state"] is True
    assert items["photo_context_pack_readiness_json"]["policy"]["requires_boundary_clearance"] is True
    assert items["photo_context_pack_readiness_json"]["policy"]["uses_reviewed_photo_context"] is True
    assert items["photo_context_pack_readiness_json"]["policy"]["uses_linked_reviewed_memories"] is True
    assert items["photo_context_pack_readiness_json"]["policy"]["excludes_system_inference_drafts"] is True
    assert items["photo_context_pack_readiness_json"]["policy"]["system_inference_leak_count"] == 0
    assert len(items["photo_context_pack_readiness_json"]["policy"]["audit_content_sha256"]) == 64
    assert items["photo_context_review_pack_yaml_preview"]["policy"]["not_memory_claim_worklists"] is True
    assert items["photo_context_review_session_plan_yaml"]["artifact_family"] == "photo_context_review"
    assert items["photo_context_review_session_plan_yaml"]["format"] == "yaml"
    assert items["photo_context_review_session_plan_yaml"]["download_endpoint"].startswith(
        "/api/assets/photo-context-review-pack/review-session-plan/yaml"
    )
    assert items["photo_context_review_session_plan_yaml"]["policy"]["query_is_context_prioritization_only"] is True
    assert items["photo_context_review_session_plan_yaml"]["policy"]["does_not_create_memory_claim"] is True
    assert items["photo_context_session_progress_json"]["artifact_family"] == "photo_context_review"
    assert items["photo_context_session_progress_json"]["format"] == "json"
    assert items["photo_context_session_progress_json"]["source_endpoint"].startswith(
        "/api/assets/photo-context-review-pack/session-progress/artifact"
    )
    assert items["photo_context_session_progress_json"]["download_endpoint"].startswith(
        "/api/assets/photo-context-review-pack/session-progress/artifact"
    )
    assert items["photo_context_session_progress_json"]["policy"]["does_not_mutate_state"] is True
    assert items["photo_context_session_progress_json"]["policy"]["does_not_create_memory_claim"] is True
    assert items["photo_context_session_progress_json"]["policy"]["does_not_create_embedding_record"] is True
    assert items["photo_context_session_progress_json"]["policy"]["requires_adam_context"] is True
    assert items["photo_context_session_progress_json"]["policy"]["completion_signal"] == (
        "submit_ready_count_increases_or_retrieval_gap_missing_fields_decrease"
    )
    assert len(items["photo_context_session_progress_json"]["policy"]["progress_content_sha256"]) == 64
    assert items["photo_context_retrieval_gap_field_worklist_yaml"]["artifact_family"] == "photo_context_review"
    assert items["photo_context_retrieval_gap_field_worklist_yaml"]["format"] == "yaml"
    assert items["photo_context_retrieval_gap_field_worklist_yaml"]["download_endpoint"].startswith(
        "/api/assets/photo-context-review-pack/retrieval-gap-field-worklist/yaml"
    )
    assert items["photo_context_retrieval_gap_field_worklist_yaml"]["policy"]["does_not_create_memory_claim"] is True
    assert items["photo_context_retrieval_gap_field_worklist_yaml"]["policy"]["requires_adam_context"] is True
    assert items["photo_context_retrieval_gap_payoff_preview_yaml"]["artifact_family"] == "photo_context_review"
    assert items["photo_context_retrieval_gap_payoff_preview_yaml"]["format"] == "yaml"
    assert items["photo_context_retrieval_gap_payoff_preview_yaml"]["download_endpoint"].startswith(
        "/api/assets/photo-context-review-pack/retrieval-gap-payoff-preview/yaml"
    )
    assert items["photo_context_retrieval_gap_payoff_preview_yaml"]["policy"]["does_not_create_memory_claim"] is True
    assert items["photo_context_retrieval_gap_payoff_preview_yaml"]["policy"]["uses_placeholders_for_missing_adam_context"] is True
    assert items["photo_vector_handoff_jsonl"]["eligibility"]["vector"] is True
    assert items["photo_vector_handoff_jsonl"]["policy"]["ordinary_db_vector_storage"] is False
    assert items["morning_handoff_yaml"]["artifact_family"] == "operator_handoff"
    assert items["morning_handoff_yaml"]["format"] == "yaml"
    assert items["morning_handoff_yaml"]["download_endpoint"].startswith("/api/downstream-readiness/morning-handoff.yaml")
    assert items["morning_handoff_yaml"]["policy"]["operator_packet"] is True
    assert items["morning_handoff_yaml"]["policy"]["no_fine_tuning_api_calls_in_mvp"] is True
    assert items["dpo_rejected_reason_repair_yaml"]["artifact_family"] == "prompt_pair_repair"
    assert items["dpo_rejected_reason_repair_yaml"]["format"] == "yaml"
    assert items["dpo_rejected_reason_repair_yaml"]["download_endpoint"].startswith("/api/prompt-pairs/dpo-rejected-reason-repair-pack/yaml")
    assert items["dpo_rejected_reason_repair_yaml"]["policy"]["blocker"] == "dpo_rejected_reason_empty"
    assert items["dpo_rejected_reason_repair_yaml"]["policy"]["repair_packet"] is True
    assert items["source_review_pair_generation_preview_json"]["artifact_family"] == "source_review_preview"
    assert items["source_review_pair_generation_preview_json"]["format"] == "json"
    assert items["source_review_pair_generation_preview_json"]["source_endpoint"].startswith("/api/tasks/")
    assert items["source_review_pair_generation_preview_json"]["policy"]["does_not_mutate_state"] is True
    assert items["source_review_pair_generation_preview_json"]["policy"]["no_live_model_call"] is True
    assert items["source_review_pair_generation_preview_json"]["policy"]["submit_creates_candidate_prompt_pair_tasks"] is True

    contract = client.get("/api/runtime-contract").json()
    assert "/api/downstream-readiness/artifact-manifest" in contract["required_response_fields"]


def test_downstream_artifact_audit_recomputes_manifest_hashes():
    client, _engine = build_client()

    response = client.get(
        "/api/downstream-readiness/artifact-audit",
        params={"scope": "family_private", "prompt_sample_limit": 20, "vector_limit": 20},
    )

    assert response.status_code == 200
    audit = response.json()
    assert audit["audit_type"] == "downstream_artifact_hash_audit"
    assert audit["review_policy"] == "recompute_declared_manifest_hashes_without_export_build"
    assert audit["does_not_mutate_state"] is True
    assert audit["no_live_model_call"] is True
    assert audit["no_live_embedding_call"] is True
    assert audit["no_fine_tuning_api_calls_in_mvp"] is True
    assert audit["checked_count"] == 20
    assert audit["mismatch_count"] == 0
    assert audit["all_hashes_match"] is True
    assert len(audit["manifest_content_sha256"]) == 64
    assert len(audit["content_sha256"]) == 64
    checked = {check["artifact_key"]: check for check in audit["checks"]}
    assert checked["prompt_pair_review_progress_json"]["hash_matches"] is True
    assert checked["prompt_pair_review_progress_json"]["format"] == "json"
    assert checked["prompt_pair_review_progress_json"]["policy"]["does_not_mutate_state"] is True
    assert checked["prompt_pair_review_progress_json"]["policy"]["does_not_promote_to_training_export"] is True
    assert len(checked["prompt_pair_review_progress_json"]["policy"]["progress_content_sha256"]) == 64
    assert checked["prompt_pair_top_blocker_session_plan_yaml"]["hash_matches"] is True
    assert checked["prompt_pair_top_blocker_session_plan_yaml"]["format"] == "yaml"
    assert checked["prompt_pair_top_blocker_session_plan_yaml"]["policy"]["does_not_mutate_state"] is True
    assert checked["prompt_pair_top_blocker_session_plan_yaml"]["policy"]["projected_task_delta"]["raw_sources_mutated"] is False
    assert checked["prompt_pair_reference_jsonl"]["hash_matches"] is True
    assert checked["dataset_sft_candidate_dry_run"]["hash_matches"] is True
    assert checked["photo_context_pack_readiness_json"]["hash_matches"] is True
    assert checked["photo_context_pack_readiness_json"]["format"] == "json"
    assert checked["photo_context_pack_readiness_json"]["policy"]["uses_reviewed_photo_context"] is True
    assert checked["photo_context_pack_readiness_json"]["policy"]["excludes_system_inference_drafts"] is True
    assert checked["photo_context_pack_readiness_json"]["policy"]["system_inference_leak_count"] == 0
    assert checked["photo_vector_handoff_jsonl"]["hash_matches"] is True
    assert checked["morning_handoff_yaml"]["hash_matches"] is True
    assert checked["morning_handoff_yaml"]["format"] == "yaml"
    assert checked["dpo_rejected_reason_repair_yaml"]["hash_matches"] is True
    assert checked["dpo_rejected_reason_repair_yaml"]["format"] == "yaml"
    assert checked["source_review_pair_generation_preview_json"]["hash_matches"] is True
    assert checked["source_review_pair_generation_preview_json"]["format"] == "json"
    assert checked["photo_context_review_session_plan_yaml"]["hash_matches"] is True
    assert checked["photo_context_review_session_plan_yaml"]["format"] == "yaml"
    assert checked["photo_context_session_progress_json"]["hash_matches"] is True
    assert checked["photo_context_session_progress_json"]["format"] == "json"
    assert checked["photo_context_session_progress_json"]["policy"]["does_not_create_memory_claim"] is True
    assert checked["photo_context_session_progress_json"]["policy"]["does_not_create_embedding_record"] is True
    assert len(checked["photo_context_session_progress_json"]["policy"]["progress_content_sha256"]) == 64
    assert checked["photo_context_retrieval_gap_field_worklist_yaml"]["hash_matches"] is True
    assert checked["photo_context_retrieval_gap_field_worklist_yaml"]["format"] == "yaml"
    assert checked["photo_context_retrieval_gap_payoff_preview_yaml"]["hash_matches"] is True
    assert checked["photo_context_retrieval_gap_payoff_preview_yaml"]["format"] == "yaml"
    for check in audit["checks"]:
        assert len(check["declared_sha256"]) == 64
        assert check["declared_sha256"] == check["recomputed_sha256"]
        assert check["source_endpoint"].startswith("/api/")

    yaml_response = client.get(
        "/api/downstream-readiness/morning-handoff.yaml",
        params={"scope": "family_private", "prompt_sample_limit": 20, "vector_limit": 20},
    )
    assert yaml_response.status_code == 200
    assert yaml_response.headers["content-type"].startswith("text/yaml")
    assert yaml_response.text.startswith("morning_handoff:")
    assert "retrieval_gap_work:" in yaml_response.text
    assert "operator_checklist:" in yaml_response.text
    assert hashlib.sha256(yaml_response.text.encode("utf-8")).hexdigest() == checked["morning_handoff_yaml"]["recomputed_sha256"]

    repair_yaml = client.get("/api/prompt-pairs/dpo-rejected-reason-repair-pack/yaml", params={"limit": 25})
    assert repair_yaml.status_code == 200
    assert repair_yaml.headers["content-type"].startswith("text/yaml")
    assert repair_yaml.text.startswith("dpo_rejected_reason_repair_packet:")
    assert "blocker: \"dpo_rejected_reason_empty\"" in repair_yaml.text
    assert hashlib.sha256(repair_yaml.text.encode("utf-8")).hexdigest() == checked["dpo_rejected_reason_repair_yaml"]["recomputed_sha256"]

    photo_session_yaml = client.get(
        "/api/assets/photo-context-review-pack/review-session-plan/yaml",
        params={"scope": "family_private", "limit": 5, "source_query": "airplane in Maine"},
    )
    assert photo_session_yaml.status_code == 200
    assert photo_session_yaml.headers["content-type"].startswith("text/yaml")
    assert photo_session_yaml.text.startswith("photo_context_review_session_plan:")
    assert "query_is_context_prioritization_only: true" in photo_session_yaml.text
    assert (
        hashlib.sha256(photo_session_yaml.text.encode("utf-8")).hexdigest()
        == checked["photo_context_review_session_plan_yaml"]["recomputed_sha256"]
    )

    photo_progress = client.get(
        "/api/assets/photo-context-review-pack/session-progress/artifact",
        params={"scope": "family_private", "limit": 100},
    )
    assert photo_progress.status_code == 200
    assert photo_progress.json()["artifact_type"] == "photo_context_session_progress_artifact"
    assert photo_progress.json()["does_not_create_embedding_record"] is True

    field_worklist_yaml = client.get(
        "/api/assets/photo-context-review-pack/retrieval-gap-field-worklist/yaml",
        params={"scope": "family_private", "limit": 100},
    )
    assert field_worklist_yaml.status_code == 200
    assert field_worklist_yaml.headers["content-type"].startswith("text/yaml")
    assert field_worklist_yaml.text.startswith("photo_context_retrieval_gap_field_worklist:")
    assert (
        hashlib.sha256(field_worklist_yaml.text.encode("utf-8")).hexdigest()
        == checked["photo_context_retrieval_gap_field_worklist_yaml"]["recomputed_sha256"]
    )

    payoff_yaml = client.get(
        "/api/assets/photo-context-review-pack/retrieval-gap-payoff-preview/yaml",
        params={"scope": "family_private", "limit": 10},
    )
    assert payoff_yaml.status_code == 200
    assert payoff_yaml.headers["content-type"].startswith("text/yaml")
    assert payoff_yaml.text.startswith("photo_context_retrieval_gap_payoff_preview:")
    assert (
        hashlib.sha256(payoff_yaml.text.encode("utf-8")).hexdigest()
        == checked["photo_context_retrieval_gap_payoff_preview_yaml"]["recomputed_sha256"]
    )

    contract = client.get("/api/runtime-contract").json()
    assert "/api/downstream-readiness/artifact-audit" in contract["required_response_fields"]


def test_downstream_morning_handoff_summarizes_live_bottlenecks_and_artifacts():
    client, engine = build_client()
    app.dependency_overrides[get_settings] = lambda: Settings(
        openai_api_key="",
        text_generation_live_calls_enabled=False,
    )

    with Session(engine) as session:
        decisions = {
            "artifact_mode": "sft",
            "system_prompt": "You are Charles Rotmil. Write naturally in his voice.",
            "prompt": "How's Portland today?",
            "content": "gray here...\nlight rain\n\nlove\ndad",
            "voice_mode": "mundane_text_message",
            "truth_status": "adam_expert_reconstruction",
            "rubric_summary": {"preferred_export_blocked": True},
        }
        compiled = compile_pair_export(decisions)
        session.add(
            Task(
                human_id="TASK_HANDOFF_PAIR",
                task_type="gold_voice_edit",
                target_type="prompt_pair",
                target_id="prompt_pair_handoff",
                queue="prompt_pairs_needing_gold_edits",
                input_payload={**decisions, "pair_index": 1, "export_preview_yaml": compiled["yaml_preview"]},
                created_by="test",
            )
        )
        session.add(
            Asset(
                human_id="ASSET_HANDOFF_PHOTO",
                asset_type="photo",
                title="Rotmil airplane in Maine",
                original_filename="rotmil-airplane-maine.jpg",
                mime_type="image/jpeg",
                processing_status="image_preview_ready",
            )
        )
        session.commit()

    response = client.get(
        "/api/downstream-readiness/morning-handoff",
        params={"scope": "family_private", "prompt_sample_limit": 20, "vector_limit": 20, "bottleneck_limit": 4},
    )

    assert response.status_code == 200
    handoff = response.json()
    assert handoff["report_type"] == "morning_handoff"
    assert handoff["review_policy"] == "read_only_status_no_source_mutation"
    assert handoff["does_not_mutate_state"] is True
    assert handoff["no_live_model_call"] is True
    assert handoff["no_live_embedding_call"] is True
    assert handoff["no_fine_tuning_api_calls_in_mvp"] is True
    assert handoff["primary_bottleneck_area_key"] == "prompt_pairs"
    assert handoff["ordered_bottleneck_area_keys"][:2] == ["prompt_pairs", "photo_context"]
    assert len(handoff["content_sha256"]) == 64

    summaries = {item["area_key"]: item for item in handoff["readiness_summary"]}
    assert summaries["prompt_pairs"]["status"] == "needs_gold_review"
    assert summaries["photo_context"]["status"] == "needs_adam_context"
    assert summaries["artifacts"]["status"] == "hash_audited"
    assert summaries["demo_generation"]["truth_policy"].endswith("until Adam review")

    bottlenecks = {item["area_key"]: item for item in handoff["top_bottlenecks"]}
    assert bottlenecks["prompt_pairs"]["action"]["task_human_id"] == "TASK_HANDOFF_PAIR"
    assert bottlenecks["prompt_pairs"]["policy"]["adam_review_required"] is True
    assert bottlenecks["photo_context"]["policy"]["truth_status_before_review"] == "no_claim"

    checklist = handoff["operator_checklist"]
    assert len(checklist) >= 3
    assert checklist[0]["checklist_id"] == "operator_checklist_001_prompt_pairs"
    assert checklist[0]["status"] == "actionable"
    assert checklist[0]["task_human_id"] == "TASK_HANDOFF_PAIR"
    assert checklist[0]["completion_signal"] == "candidate_count_decreases_or_blocker_worklist_changes"
    assert "Adam gold review" in checklist[0]["safety_boundary"]
    assert checklist[1]["area_key"] == "photo_context"
    assert checklist[1]["completion_signal"] == "needs_context_group_count_decreases_or_review_task_becomes_submit_ready"
    assert "no_claim" in checklist[1]["safety_boundary"]
    assert checklist[1]["retrieval_gap_query"] == "airplane in Maine"
    assert checklist[1]["retrieval_gap_candidate_count"] >= 1
    assert len(checklist[1]["retrieval_gap_slice_hash"]) == 64
    assert "Rotmil airplane in Maine" in checklist[1]["retrieval_gap_preview_titles"][0]
    assert checklist[-1]["area_key"] == "demo_generation"
    assert checklist[-1]["status"] == "blocked"
    assert "No fine-tuning API calls" in checklist[-1]["safety_boundary"]

    retrieval_gap_work = handoff["retrieval_gap_work"]
    assert retrieval_gap_work["slice_type"] == "retrieval_gap_review_slice"
    assert retrieval_gap_work["review_policy"] == "retrieval_gap_no_claim_until_adam_context"
    assert retrieval_gap_work["query"] == "airplane in Maine"
    assert retrieval_gap_work["gap_open"] is True
    assert retrieval_gap_work["truth_status"] == "no_claim"
    assert retrieval_gap_work["candidate_count"] >= 1
    assert retrieval_gap_work["reported_candidate_count"] >= 1
    assert retrieval_gap_work["items"][0]["not_memory_claim"] is True
    assert retrieval_gap_work["items"][0]["action"]["request"]["body"]["source_query"] == "airplane in Maine"

    artifact_summary = handoff["artifact_summary"]
    assert artifact_summary["artifact_count"] >= 10
    assert artifact_summary["all_hashes_match"] is True
    assert artifact_summary["mismatch_count"] == 0
    assert len(artifact_summary["manifest_content_sha256"]) == 64

    model_status = handoff["model_generation_status"]
    assert model_status["model_name"] == "gpt-5.5"
    assert model_status["reasoning_effort"] == "xhigh"
    assert model_status["outputs_truth_status"] == "model_generated"
    assert model_status["fine_tuning_api_calls_allowed"] is False
    assert set(model_status["blockers"]) == {
        "text_generation_live_calls_disabled",
        "openai_api_key_missing",
    }

    markdown = handoff["report_markdown"]
    assert markdown.startswith("# Morning Handoff")
    assert "Prompt pairs:" in markdown
    assert "No fine-tuning API calls in MVP." in markdown
    assert "model_generated" in markdown
    assert "no_claim" in markdown
    assert "## Retrieval Gap Work" in markdown
    assert "airplane in Maine" in markdown
    assert any(link["endpoint"].startswith("/api/downstream-readiness/artifact-manifest") for link in handoff["downstream_links"])
    assert any(link["endpoint"].startswith("/api/retrieval/gap-review-slice") for link in handoff["downstream_links"])

    contract = client.get("/api/runtime-contract").json()
    assert "/api/downstream-readiness/morning-handoff" in contract["required_response_fields"]


def test_prompt_pair_top_blocker_slice_exposes_reviewable_yaml_previews():
    client, engine = build_client()

    with Session(engine) as session:
        for index in range(1, 4):
            decisions = {
                "artifact_mode": "dpo",
                "system_prompt": "You are Charles Rotmil.",
                "prompt": f"How was the soup {index}?",
                "chosen": "soup was thin...\nnot much there",
                "rejected": "",
                "voice_mode": "mundane_text_message",
                "truth_status": "model_generated",
                "synthetic": True,
                "source_excerpt": "diner soup note",
                "context": "Needs a rejected answer before DPO export.",
            }
            compiled = compile_pair_export(decisions)
            session.add(
                Task(
                    human_id=f"TASK_BLOCKER_SLICE_{index:03d}",
                    task_type="gold_voice_edit",
                    target_type="prompt_pair",
                    target_id=f"prompt_pair_blocker_slice_{index}",
                    queue="prompt_pairs_needing_gold_edits",
                    input_payload={**decisions, "pair_index": index, "export_preview_yaml": compiled["yaml_preview"]},
                    created_by="test",
                )
            )
        session.commit()

    response = client.get("/api/prompt-pairs/top-blocker-slice", params={"limit": 2})

    assert response.status_code == 200
    blocker_slice = response.json()
    assert blocker_slice["slice_type"] == "prompt_pair_top_blocker_slice"
    assert blocker_slice["review_policy"] == "top_backend_blocker_review_slice_no_export_promotion"
    assert blocker_slice["does_not_promote_to_training_export"] is True
    assert blocker_slice["requires_adam_gold_edit"] is True
    assert blocker_slice["candidate_count"] == 3
    assert blocker_slice["reported_candidate_count"] == 2
    assert blocker_slice["completion_signal"] == "candidate_count_decreases_or_blocker_worklist_changes"
    assert len(blocker_slice["content_sha256"]) == 64
    assert any("Adam gold review" in boundary for boundary in blocker_slice["safety_boundaries"])

    first = blocker_slice["items"][0]
    assert first["task_human_id"] == "TASK_BLOCKER_SLICE_001"
    assert first["prompt"] == "How was the soup 1?"
    assert "soup was thin" in first["response_preview"]
    assert blocker_slice["blocker"] in first["backend_preflight"]["blockers"]
    assert first["backend_preflight"]["export_status"] == "candidate"
    assert first["backend_preflight"]["dataset_outcome"] == "Candidate dry-run only"
    assert "chosen:" in first["export_preview_yaml"]
    assert first["completion_criteria"][0].startswith("Resolve or explain")
    assert first["action"]["action_type"] == "open_held_prompt_pair_candidate"
    assert first["action"]["task_human_id"] == "TASK_BLOCKER_SLICE_001"

    session_plan_response = client.get("/api/prompt-pairs/top-blocker-review-session-plan", params={"limit": 2})
    assert session_plan_response.status_code == 200
    session_plan = session_plan_response.json()
    assert session_plan["plan_type"] == "prompt_pair_top_blocker_review_session_plan"
    assert session_plan["review_policy"] == "non_mutating_prompt_pair_batch_plan_no_export_promotion"
    assert session_plan["does_not_mutate_state"] is True
    assert session_plan["does_not_promote_to_training_export"] is True
    assert session_plan["requires_adam_gold_edit"] is True
    assert session_plan["blocker"] == blocker_slice["blocker"]
    assert session_plan["selected_count"] == 2
    assert session_plan["candidate_count"] == 3
    assert session_plan["selected_task_ids"] == [item["task_id"] for item in blocker_slice["items"]]
    assert session_plan["source_slice_content_sha256"] == blocker_slice["content_sha256"]
    assert session_plan["projected_task_delta"] == {
        "would_create_tasks": 0,
        "would_open_existing_tasks": 2,
        "raw_sources_mutated": False,
        "approved_exports_created": 0,
    }
    assert session_plan["field_plan"][0]["field"] in {"failure_modes", "context"}
    assert session_plan["items"][0]["task_human_id"] == "TASK_BLOCKER_SLICE_001"
    assert session_plan["items"][0]["current_blockers"] == first["backend_preflight"]["blockers"]
    assert session_plan["items"][0]["action"]["action_type"] == "open_held_prompt_pair_candidate"
    assert "does not create approved SFT/DPO rows" in " ".join(session_plan["safety_boundaries"])
    assert session_plan["completion_signal"] == "selected_prompt_pair_blocker_batch_submitted_then_candidate_count_or_worklist_changes"
    assert len(session_plan["content_sha256"]) == 64
    assert session_plan["export_preview_yaml"].startswith("prompt_pair_top_blocker_review_session_plan:")
    assert hashlib.sha256(session_plan["export_preview_yaml"].encode("utf-8")).hexdigest() == session_plan["export_preview_sha256"]

    session_plan_yaml_response = client.get("/api/prompt-pairs/top-blocker-review-session-plan/yaml", params={"limit": 2})
    assert session_plan_yaml_response.status_code == 200
    assert session_plan_yaml_response.headers["content-type"].startswith("text/yaml")
    assert "TASK_BLOCKER_SLICE_001" in session_plan_yaml_response.text
    assert hashlib.sha256(session_plan_yaml_response.text.encode("utf-8")).hexdigest() == session_plan["export_preview_sha256"]

    contract = client.get("/api/runtime-contract").json()
    assert "/api/prompt-pairs/top-blocker-slice" in contract["required_response_fields"]
    assert "/api/prompt-pairs/top-blocker-review-session-plan" in contract["required_response_fields"]
    assert "/api/prompt-pairs/dpo-rejected-reason-repair-pack" in contract["required_response_fields"]
    assert "/api/prompt-pairs/review-progress" in contract["required_response_fields"]

    progress_response = client.get("/api/prompt-pairs/review-progress")
    assert progress_response.status_code == 200
    progress = progress_response.json()
    assert progress["progress_type"] == "prompt_pair_review_progress"
    assert progress["review_policy"] == "non_mutating_prompt_pair_progress_projection"
    assert progress["does_not_mutate_state"] is True
    assert progress["does_not_promote_to_training_export"] is True
    assert progress["requires_adam_gold_edit"] is True
    assert progress["candidate_count"] == 3
    assert progress["top_blocker"] in {"dpo_rejected_empty", "dpo_rejected_reason_empty"}
    assert progress["top_blocker_count"] == 3
    assert progress["blocker_counts"][progress["top_blocker"]] == 3
    assert progress["blocker_counts"]["dpo_rejected_reason_empty"] == 3
    assert progress["candidate_worklist_count"] >= 1
    assert progress["completion_signal"] == "candidate_count_decreases_or_blocker_worklist_changes"
    assert progress["next_review_action"]["action_type"] == "open_prompt_pair_blocker"
    assert len(progress["content_sha256"]) == 64

    repair_response = client.get("/api/prompt-pairs/dpo-rejected-reason-repair-pack", params={"limit": 2})
    assert repair_response.status_code == 200
    repair_pack = repair_response.json()
    assert repair_pack["packet_type"] == "dpo_rejected_reason_repair_packet"
    assert repair_pack["review_policy"] == "repair_dpo_reason_only_no_training_export"
    assert repair_pack["does_not_promote_to_training_export"] is True
    assert repair_pack["requires_adam_gold_edit"] is True
    assert repair_pack["blocker"] == "dpo_rejected_reason_empty"
    assert repair_pack["total_candidate_count"] == 3
    assert repair_pack["reported_candidate_count"] == 2
    assert len(repair_pack["content_sha256"]) == 64
    assert len(repair_pack["export_preview_sha256"]) == 64
    assert repair_pack["export_preview_yaml"].startswith("dpo_rejected_reason_repair_packet:")
    assert "current_failure_modes: []" in repair_pack["export_preview_yaml"]
    assert "backend_blockers:" in repair_pack["export_preview_yaml"]
    repair_item = repair_pack["items"][0]
    assert repair_item["task_human_id"] == "TASK_BLOCKER_SLICE_001"
    assert repair_item["prompt"] == "How was the soup 1?"
    assert "soup was thin" in repair_item["chosen_preview"]
    assert "dpo_rejected_reason_empty" in repair_item["backend_preflight"]["blockers"]
    assert repair_item["repair_fields"] == ["failure_modes", "response_rubric.response_a", "rubric_summary.rejected_issue_count"]
    assert repair_item["repair_projection"]["does_not_mutate_task"] is True
    assert repair_item["repair_projection"]["input_patch"] == {"failure_modes": ["too_generic_not_charles_voice"]}
    assert "dpo_rejected_reason_empty" in repair_item["repair_projection"]["before_blockers"]
    assert "dpo_rejected_reason_empty" not in repair_item["repair_projection"]["after_blockers"]
    assert repair_item["repair_projection"]["target_blocker_cleared"] is True
    assert repair_item["repair_projection"]["still_requires_adam_gold_edit"] is True
    assert repair_item["completion_criteria"][0].startswith("`failure_modes` contains")
    assert repair_item["action"]["label"] == "Open DPO repair candidate"

    projection_response = client.get(
        "/api/prompt-pairs/dpo-rejected-reason-repair-projection",
        params={"task_id": "TASK_BLOCKER_SLICE_001", "failure_mode": "too_generic_not_charles_voice"},
    )
    assert projection_response.status_code == 200
    projection = projection_response.json()
    assert projection["projection_type"] == "dpo_rejected_reason_repair_projection"
    assert projection["review_policy"] == "non_mutating_single_candidate_projection"
    assert projection["does_not_mutate_task"] is True
    assert projection["does_not_promote_to_training_export"] is True
    assert projection["requires_adam_gold_edit"] is True
    assert projection["task_human_id"] == "TASK_BLOCKER_SLICE_001"
    assert projection["input_patch"] == {"failure_modes": ["too_generic_not_charles_voice"]}
    assert projection["before"]["failure_modes"] == []
    assert "dpo_rejected_reason_empty" in projection["before"]["blockers"]
    assert "dpo_rejected_reason_empty" not in projection["after"]["blockers"]
    assert projection["target_blocker_cleared"] is True
    assert projection["still_requires_adam_gold_edit"] is True
    assert projection["export_preview_changed"] is False
    assert projection["yaml_diff_preview"].startswith("--- before_dpo_repair.yaml")
    assert "+    - \"too_generic_not_charles_voice\"" in projection["yaml_diff_preview"]
    assert len(projection["content_sha256"]) == 64

    contract = client.get("/api/runtime-contract").json()
    assert "/api/prompt-pairs/dpo-rejected-reason-repair-projection" in contract["required_response_fields"]


def test_runtime_contract_includes_source_review_pair_generation_preview_fields():
    client, _engine = build_client()

    contract = client.get("/api/runtime-contract").json()
    required = contract["required_response_fields"]["/api/tasks/{task_id}/pair-generation/preview"]

    assert "does_not_mutate_state" in required
    assert "no_live_model_call" in required
    assert "projected_created_pair_count" in required
    assert "strategy_counts" in required
    assert "safety_boundaries" in required
    assert "content_sha256" in required


def test_pair_export_yaml_scalar_contract_handles_apostrophes_quotes_and_multiline_content():
    sft = compile_pair_export(
        {
            "artifact_mode": "sft",
            "system_prompt": "You are Charles Rotmil.",
            "prompt": "How's Portland today?",
            "content": "gray here...\nlight rain\n\ndad",
        }
    )

    assert "content: How's Portland today?" in sft["yaml_preview"]
    assert "content: |-" in sft["yaml_preview"]
    assert "       gray here..." in sft["yaml_preview"]

    dpo = compile_pair_export(
        {
            "artifact_mode": "dpo",
            "system_prompt": "You are Charles Rotmil.",
            "prompt": "He said \"how was the soup?\"",
            "chosen": "soup was thin...\nnot much there",
            "rejected": "The soup was \"bland\" and unsatisfying.",
        }
    )

    assert 'prompt: "He said \\"how was the soup?\\""' in dpo["yaml_preview"]
    assert "chosen: |-" in dpo["yaml_preview"]
    assert 'The soup was "bland" and unsatisfying.' in dpo["yaml_preview"]


def test_prompt_pair_audit_reports_200_plus_inspectable_pairs_with_samples_and_weak_spots():
    client, engine = build_client()

    voice_modes = [
        "father_to_adam",
        "logistical_note",
        "memoir_scene",
        "comic_observation",
        "photography_reflection",
        "philosophical_fragment",
    ]
    with Session(engine) as session:
        for index in range(1, 206):
            voice_mode = voice_modes[index % len(voice_modes)]
            decisions = {
                "artifact_mode": "sft",
                "system_prompt": "You are Charles Rotmil. Write naturally in his voice.",
                "prompt": f"Prompt {index}: Tell me something specific.",
                "content": f"response {index} line one\nresponse {index} line two\n\ndad",
                "voice_mode": voice_mode,
                "truth_status": "adam_expert_reconstruction",
                "synthetic": True,
                "context": f"context note {index}",
            }
            compiled = compile_pair_export(decisions)
            session.add(
                Task(
                    human_id=f"TASK_AUDIT_PAIR_{index:03d}",
                    task_type="gold_voice_edit",
                    target_type="prompt_pair",
                    target_id=f"prompt_pair_{index:03d}",
                    queue="prompt_pairs_needing_gold_edits",
                    input_payload={
                        **decisions,
                        "pair_index": index,
                        "source_title": "Audit fixture",
                        "source_excerpt": f"source excerpt {index}",
                        "source_task_id": f"source_task_{index:03d}",
                        "grounding_asset_id": f"asset_{index:03d}",
                        "export_preview_yaml": compiled["yaml_preview"],
                        "pair_generation_metadata": {
                            "strategy": "structured_yaml_messages",
                            "prompt_instructions_version": "charlesops_source_review_pair_generation_v1",
                            "live_model_call": False,
                            "source_text_sha256": f"sha-{index:03d}",
                        },
                    },
                    created_by="test",
                )
            )
        session.add(
            Task(
                human_id="TASK_AUDIT_BLOCKED_PAIR",
                task_type="gold_voice_edit",
                target_type="prompt_pair",
                target_id="prompt_pair_blocked",
                queue="prompt_pairs_needing_gold_edits",
                    input_payload={
                        "artifact_mode": "sft",
                        "pair_index": 206,
                        "prompt": "Blocked prompt",
                        "content": "blocked response with enough concrete words\n\ndad",
                        "voice_mode": "father_to_adam",
                    "truth_status": "adam_expert_reconstruction",
                    "synthetic": True,
                    "source_title": "Audit fixture",
                    "source_excerpt": "blocked source excerpt",
                    "rubric_summary": {"preferred_export_blocked": True},
                    "export_preview_yaml": "blocked: true",
                },
                created_by="test",
            )
        )
        session.commit()

    response = client.get("/api/prompt-pairs/audit", params={"sample_limit": 20})

    assert response.status_code == 200
    audit = response.json()
    assert audit["total_pairs"] == 206
    assert audit["inspectable_pair_count"] == 206
    assert audit["invalid_pair_count"] == 0
    assert audit["quality_counts"]["review_candidate"] == 205
    assert audit["quality_counts"]["blocked"] == 1
    assert audit["preflight_gate_counts"] == {"approved": 205, "candidate": 1}
    assert audit["preflight_blocker_counts"] == {"privacy_export_blocked": 1, "rubric_not_export_ready": 1}
    assert audit["preflight_mismatch_count"] == 0
    assert len(audit["next_review_actions"]) == 1
    next_action = audit["next_review_actions"][0]
    assert next_action["action_type"] == "open_held_prompt_pair_candidate"
    assert next_action["task_human_id"] == "TASK_AUDIT_BLOCKED_PAIR"
    assert next_action["pair_index"] == 206
    assert next_action["artifact_mode"] == "sft"
    assert next_action["export_status"] == "candidate"
    assert next_action["blockers"] == ["rubric_not_export_ready", "privacy_export_blocked"]
    blocker_actions = {action["blocker"]: action for action in audit["blocker_review_actions"]}
    assert set(blocker_actions) == {"rubric_not_export_ready", "privacy_export_blocked"}
    for blocker, action in blocker_actions.items():
        assert action["action_type"] == "open_prompt_pair_blocker"
        assert action["label"] == "Open blocker example"
        assert action["blocker_count"] == 1
        assert action["task_human_id"] == "TASK_AUDIT_BLOCKED_PAIR"
        assert action["pair_index"] == 206
        assert action["artifact_mode"] == "sft"
        assert action["export_status"] == "candidate"
        assert blocker in action["blockers"]
        assert action["reason"] == f"First held prompt pair with backend blocker `{blocker}`."
    assert audit["artifact_mode_counts"] == {"sft": 206}
    for mode in voice_modes:
        assert audit["voice_mode_counts"][mode] > 0
    assert audit["truth_status_counts"] == {"adam_expert_reconstruction": 206}
    assert audit["source_distribution"]["Audit fixture"] == 206
    assert audit["sample_count"] == 20
    assert audit["known_weak_spots"]

    held_response = client.get("/api/prompt-pairs/held-candidates", params={"limit": 10})
    assert held_response.status_code == 200
    held_pack = held_response.json()
    assert held_pack["pack_type"] == "prompt_pair_candidate_review_pack"
    assert held_pack["review_policy"] == "candidate_review_only_no_training_export"
    assert held_pack["does_not_promote_to_training_export"] is True
    assert held_pack["requires_adam_gold_edit"] is True
    assert held_pack["total_candidate_count"] == 1
    assert held_pack["reported_candidate_count"] == 1
    assert held_pack["blocker_counts"] == {"privacy_export_blocked": 1, "rubric_not_export_ready": 1}
    assert held_pack["worklist_count"] == 2
    assert len(held_pack["worklists"]) == 2
    worklists = {worklist["blocker"]: worklist for worklist in held_pack["worklists"]}
    assert set(worklists) == {"privacy_export_blocked", "rubric_not_export_ready"}
    for blocker, worklist in worklists.items():
        assert worklist["worklist_key"] == f"prompt_pair_blocker:{blocker}"
        assert worklist["candidate_count"] == 1
        assert worklist["reported_candidate_count"] == 1
        assert len(worklist["review_sequence_key"]) == 64
        assert worklist["review_policy"] == "resolve_blocker_then_submit_gold_edit"
        assert worklist["recommended_action"]["action_type"] == "open_prompt_pair_worklist"
        assert worklist["recommended_action"]["label"] == "Work this blocker next"
        assert worklist["recommended_action"]["task_human_id"] == "TASK_AUDIT_BLOCKED_PAIR"
        assert worklist["recommended_action"]["candidate_count"] == 1
        assert worklist["recommended_action"]["review_sequence_key"] == worklist["review_sequence_key"]
        assert worklist["candidate_previews"][0]["task_human_id"] == "TASK_AUDIT_BLOCKED_PAIR"
        assert worklist["candidate_previews"][0]["sequence_number"] == 1
        assert blocker in worklist["candidate_previews"][0]["blockers"]
    assert len(held_pack["content_sha256"]) == 64
    held_candidate = held_pack["candidates"][0]
    assert held_candidate["task_human_id"] == "TASK_AUDIT_BLOCKED_PAIR"
    assert held_candidate["export_status"] == "candidate"
    assert held_candidate["dataset_outcome"] == "Candidate dry-run only"
    assert held_candidate["action"]["action_type"] == "open_held_prompt_pair_candidate"

    sample = audit["samples"][0]
    assert sample["prompt"].startswith("Prompt 1:")
    assert sample["response"].endswith("\ndad")
    assert sample["voice_mode"] in voice_modes
    assert sample["source_excerpt"].startswith("source excerpt")
    assert sample["context"].startswith("context note")
    assert sample["export_preview_yaml"].startswith("- messages:")
    assert sample["source_task_id"].startswith("source_task_")
    assert sample["grounding_asset_id"].startswith("asset_")


def test_prompt_pair_preflight_export_gate_and_audit_catch_ui_mismatch():
    client, engine = build_client()

    approved = client.post(
        "/api/prompt-pairs/preflight-export-gate",
        json={
            "artifact_mode": "sft",
            "system_prompt": "You are Charles Rotmil. Write naturally in his voice.",
            "prompt": "How's Portland today?",
            "content": "gray here...\nlight rain\n\ndad",
            "rubric_summary": {"sft_ready": True, "preferred_export_blocked": False},
        },
    )
    assert approved.status_code == 200
    approved_body = approved.json()
    assert approved_body["export_ready"] is True
    assert approved_body["export_status"] == "approved"
    assert approved_body["dataset_outcome"] == "Approved JSONL after Submit"

    candidate = client.post(
        "/api/prompt-pairs/preflight-export-gate",
        json={
            "artifact_mode": "dpo",
            "system_prompt": "You are Charles Rotmil.",
            "prompt": "How was the soup?",
            "chosen": "thin soup...\nnot much there",
            "rejected": "The soup was bland.",
            "rubric_summary": {"sft_ready": True, "preferred_export_blocked": False},
            "failure_modes": [],
        },
    )
    assert candidate.status_code == 200
    candidate_body = candidate.json()
    assert candidate_body["export_ready"] is False
    assert candidate_body["export_status"] == "candidate"
    assert candidate_body["dataset_outcome"] == "Candidate dry-run only"
    assert candidate_body["blockers"] == ["dpo_rejected_reason_empty"]

    with Session(engine) as session:
        session.add(
            Task(
                human_id="TASK_UI_GATE_MISMATCH",
                task_type="gold_voice_edit",
                target_type="prompt_pair",
                target_id="prompt_pair_gate_mismatch",
                queue="prompt_pairs_needing_gold_edits",
                input_payload={
                    "artifact_mode": "sft",
                    "system_prompt": "You are Charles Rotmil. Write naturally in his voice.",
                    "prompt": "How's Portland today?",
                    "content": "gray here...\nlight rain\n\ndad",
                    "voice_mode": "mundane_text_message",
                    "truth_status": "adam_expert_reconstruction",
                    "rubric_summary": {"sft_ready": True, "preferred_export_blocked": False},
                    "export_gate_preview": {
                        "submit_outcome": "Will submit as review candidate",
                        "dataset_outcome": "Candidate dry-run only",
                        "blockers": ["made_up_blocker"],
                    },
                },
                created_by="test",
            )
        )
        session.commit()

    audit = client.get("/api/prompt-pairs/audit", params={"sample_limit": 5})
    assert audit.status_code == 200
    body = audit.json()
    assert body["preflight_gate_counts"] == {"approved": 1}
    assert body["preflight_mismatch_count"] == 1
    mismatch = body["preflight_mismatches"][0]
    assert mismatch["task_human_id"] == "TASK_UI_GATE_MISMATCH"
    assert set(mismatch["reasons"]) == {"submit_outcome_mismatch", "dataset_outcome_mismatch", "blockers_mismatch"}


def test_prompt_pair_audit_pack_returns_markdown_with_required_voice_modes_and_export_previews():
    client, engine = build_client()

    voice_modes = [
        "father_to_adam",
        "logistical_note",
        "memoir_scene",
        "comic_observation",
        "photography_reflection",
        "philosophical_fragment",
    ]
    with Session(engine) as session:
        for index in range(1, 211):
            voice_mode = voice_modes[index % len(voice_modes)]
            decisions = {
                "artifact_mode": "sft",
                "system_prompt": "You are Charles Rotmil. Write naturally in his voice.",
                "prompt": f"Prompt {index}: Tell me something specific.",
                "content": f"response {index} line one\nresponse {index} line two\n\ndad",
                "voice_mode": voice_mode,
                "truth_status": "adam_expert_reconstruction",
                "synthetic": True,
                "context": f"context note {index}",
            }
            compiled = compile_pair_export(decisions)
            session.add(
                Task(
                    human_id=f"TASK_AUDIT_PACK_PAIR_{index:03d}",
                    task_type="gold_voice_edit",
                    target_type="prompt_pair",
                    target_id=f"prompt_pair_pack_{index:03d}",
                    queue="prompt_pairs_needing_gold_edits",
                    input_payload={
                        **decisions,
                        "pair_index": index,
                        "source_title": "Audit pack fixture",
                        "source_excerpt": f"source excerpt {index}",
                        "source_task_id": f"source_task_{index:03d}",
                        "grounding_asset_id": f"asset_{index:03d}",
                        "export_preview_yaml": compiled["yaml_preview"],
                        "pair_generation_metadata": {
                            "strategy": "structured_yaml_messages",
                            "prompt_instructions_version": "charlesops_source_review_pair_generation_v1",
                            "live_model_call": False,
                            "source_text_sha256": f"pack-sha-{index:03d}",
                        },
                    },
                    created_by="test",
                )
            )
        session.commit()

    response = client.get("/api/prompt-pairs/audit-pack", params={"sample_limit": 200})

    assert response.status_code == 200
    pack = response.json()
    assert pack["pack_type"] == "prompt_pair_human_audit_pack"
    assert pack["total_pairs"] == 210
    assert pack["inspectable_pair_count"] == 210
    assert pack["invalid_pair_count"] == 0
    assert pack["sample_count"] == 200
    assert pack["sample_limit_cap"] >= 200
    assert pack["representative_requirements_met"] is True
    assert pack["missing_required_modes"] == []
    for mode in voice_modes:
        assert mode in pack["represented_modes"]

    first = pack["samples"][0]
    assert first["prompt"].startswith("Prompt")
    assert first["response"].endswith("\ndad")
    assert first["source_excerpt"].startswith("source excerpt")
    assert first["context"].startswith("context note")
    assert first["export_preview_yaml"].startswith("- messages:")
    assert first["quality_status"] == "review_candidate"
    assert first["boundary_status"] == "needs_review_before_export"
    assert first["backend_preflight"]["export_status"] == "approved"
    assert first["backend_preflight"]["dataset_outcome"] == "Approved JSONL after Submit"
    assert first["pair_generation_strategy"] == "structured_yaml_messages"
    assert first["pair_generation_metadata"]["prompt_instructions_version"] == "charlesops_source_review_pair_generation_v1"

    markdown = pack["markdown"]
    assert markdown.startswith("# CharlesOps Prompt Pair Human Audit Pack")
    assert pack["content_sha256"] == hashlib.sha256(markdown.encode("utf-8")).hexdigest()
    assert len(pack["content_sha256"]) == 64
    assert "## Known Weak Spots" in markdown
    assert "## Representative Samples" in markdown
    assert markdown.count("### Sample") == 200
    for required in [
        "**Prompt**",
        "**Response / Chosen**",
        "**Source Excerpt**",
        "**Context Note**",
        "**Export Preview**",
        "**Backend Preflight**",
        "**Pair Generation Provenance**",
    ]:
        assert required in markdown
    assert "Backend preflight: `approved`" in markdown
    assert "Generation strategy: `structured_yaml_messages`" in markdown
    assert "charlesops_source_review_pair_generation_v1" in markdown
    for mode in voice_modes:
        assert mode in markdown

    markdown_response = client.get("/api/prompt-pairs/audit-pack/markdown", params={"sample_limit": 200})
    assert markdown_response.status_code == 200
    assert markdown_response.headers["content-type"].startswith("text/markdown")
    assert "charlesops_prompt_pair_audit_pack_200.md" in markdown_response.headers["content-disposition"]
    assert markdown_response.text == markdown


def test_prompt_pair_reference_pack_returns_generation_context_jsonl_without_authenticity_claims():
    client, engine = build_client()

    voice_modes = [
        "father_to_adam",
        "logistical_note",
        "memoir_scene",
        "comic_observation",
        "photography_reflection",
        "philosophical_fragment",
    ]
    with Session(engine) as session:
        for index in range(1, 211):
            voice_mode = voice_modes[index % len(voice_modes)]
            decisions = {
                "artifact_mode": "sft",
                "system_prompt": "You are Charles Rotmil. Write naturally in his voice.",
                "prompt": f"Reference prompt {index}: Tell me something specific.",
                "content": f"reference response {index} line one\nreference response {index} line two\n\ndad",
                "voice_mode": voice_mode,
                "conversation_family": "adam_prompted_memory",
                "truth_status": "adam_expert_reconstruction",
                "synthetic": True,
                "context": f"reference context {index}",
            }
            compiled = compile_pair_export(decisions)
            session.add(
                Task(
                    human_id=f"TASK_REFERENCE_PACK_PAIR_{index:03d}",
                    task_type="gold_voice_edit",
                    target_type="prompt_pair",
                    target_id=f"prompt_pair_reference_{index:03d}",
                    queue="prompt_pairs_needing_gold_edits",
                    input_payload={
                        **decisions,
                        "pair_index": index,
                        "source_title": "Reference pack fixture",
                        "source_excerpt": f"source excerpt {index}",
                        "source_task_id": f"source_task_{index:03d}",
                        "grounding_asset_id": f"asset_{index:03d}",
                        "export_preview_yaml": compiled["yaml_preview"],
                    },
                    created_by="test",
                )
            )
        duplicate_decisions = {
            "artifact_mode": "sft",
            "system_prompt": "You are Charles Rotmil. Write naturally in his voice.",
            "prompt": "Reference prompt 1: Tell me something specific.",
            "content": "reference response 1 line one\nreference response 1 line two\n\ndad",
            "voice_mode": "father_to_adam",
            "conversation_family": "adam_prompted_memory",
            "truth_status": "adam_expert_reconstruction",
            "synthetic": True,
        }
        session.add(
            Task(
                human_id="TASK_REFERENCE_PACK_DUPLICATE",
                task_type="gold_voice_edit",
                target_type="prompt_pair",
                target_id="prompt_pair_reference_duplicate",
                queue="prompt_pairs_needing_gold_edits",
                input_payload=duplicate_decisions,
                created_by="test",
            )
        )
        session.add(
            Task(
                human_id="TASK_REFERENCE_PACK_BLOCKED",
                task_type="gold_voice_edit",
                target_type="prompt_pair",
                target_id="prompt_pair_reference_blocked",
                queue="prompt_pairs_needing_gold_edits",
                input_payload={
                    "artifact_mode": "sft",
                    "prompt": "Blocked prompt",
                    "content": "blocked response",
                    "voice_mode": "father_to_adam",
                    "truth_status": "adam_expert_reconstruction",
                    "rubric_summary": {"preferred_export_blocked": True},
                },
                created_by="test",
            )
        )
        session.commit()

        selected = select_prompt_pair_reference_examples(
            session=session,
            voice_mode="memoir_scene",
            conversation_family="adam_prompted_memory",
            limit=4,
        )
        assert len(selected) == 4
        assert selected[0]["metadata"]["voice_mode"] == "memoir_scene"
        assert selected[0]["metadata"]["does_not_certify_final_authenticity"] is True

    response = client.get("/api/prompt-pairs/reference-pack", params={"sample_limit": 200})

    assert response.status_code == 200
    pack = response.json()
    assert pack["pack_type"] == "prompt_pair_voice_reference_pack"
    assert pack["total_pairs"] == 212
    assert pack["referenceable_pair_count"] == 211
    assert pack["unique_reference_count"] == 210
    assert pack["duplicate_excluded_count"] == 1
    assert pack["sample_count"] == 200
    assert pack["ready_for_generation_context"] is True
    assert pack["missing_required_modes"] == []
    assert pack["safety_policy"] == {
        "does_not_certify_final_authenticity": True,
        "does_not_change_truth_status": True,
        "live_model_calls": False,
        "intended_use": "reference_examples_for_prompt_pair_drafting_and_human_review",
    }

    first = pack["records"][0]
    assert first["reference_id"].startswith("prompt-pair-reference:")
    assert first["messages"][0] == {
        "role": "system",
        "content": "You are Charles Rotmil. Write naturally in his voice.",
    }
    assert first["messages"][1]["role"] == "user"
    assert first["messages"][2]["role"] == "assistant"
    assert first["reference_use"] == "voice_context_for_model_drafting_and_human_review"
    assert first["boundary_status"] == "needs_review_before_export"
    assert first["source"]["source_task_id"].startswith("source_task_")
    assert "voice_mode:" in first["embedding_input_text"]
    assert "assistant:" in first["embedding_input_text"]

    message_keys = [
        str([(message["role"], message["content"]) for message in record["messages"]])
        for record in pack["records"]
    ]
    assert len(message_keys) == len(set(message_keys))

    jsonl_response = client.get("/api/prompt-pairs/reference-pack/jsonl", params={"sample_limit": 200})
    assert jsonl_response.status_code == 200
    assert jsonl_response.headers["content-type"].startswith("application/x-ndjson")
    assert "charlesops_prompt_pair_voice_reference_pack_200.jsonl" in jsonl_response.headers["content-disposition"]
    jsonl_records = [line for line in jsonl_response.text.splitlines() if line.strip()]
    assert len(jsonl_records) == 200
    assert [record["reference_id"] for record in map(json.loads, jsonl_records[:3])] == [
        item["reference_id"] for item in pack["records"][:3]
    ]

    markdown_response = client.get("/api/prompt-pairs/reference-pack/markdown", params={"sample_limit": 200})
    assert markdown_response.status_code == 200
    assert markdown_response.headers["content-type"].startswith("text/markdown")
    assert markdown_response.text.startswith("# CharlesOps Prompt Pair Voice Reference Pack")
    assert markdown_response.text.count("### Reference") == 200


def test_prompt_pair_audit_and_reference_pack_exclude_structural_sft_blockers():
    client, engine = build_client()

    with Session(engine) as session:
        good_decisions = {
            "artifact_mode": "sft",
            "system_prompt": "You are Charles Rotmil. Write naturally in his voice.",
            "prompt": "How's Portland today?",
            "content": "gray here...\nlight rain\nkeeps the trees happy\n\ndad",
            "voice_mode": "father_to_adam",
            "truth_status": "adam_expert_reconstruction",
            "synthetic": True,
            "source_title": "Structural guard fixture",
        }
        bad_decisions = {
            **good_decisions,
            "prompt": "Tell me about charles_sft.yaml",
        }
        session.add(
            Task(
                human_id="TASK_REFERENCE_STRUCTURAL_GOOD",
                task_type="gold_voice_edit",
                target_type="prompt_pair",
                target_id="prompt_pair_structural_good",
                queue="prompt_pairs_needing_gold_edits",
                input_payload={**good_decisions, "export_preview_yaml": compile_pair_export(good_decisions)["yaml_preview"]},
                created_by="test",
            )
        )
        session.add(
            Task(
                human_id="TASK_REFERENCE_STRUCTURAL_BAD",
                task_type="gold_voice_edit",
                target_type="prompt_pair",
                target_id="prompt_pair_structural_bad",
                queue="prompt_pairs_needing_gold_edits",
                input_payload={**bad_decisions, "export_preview_yaml": compile_pair_export(bad_decisions)["yaml_preview"]},
                created_by="test",
            )
        )
        session.commit()

    audit_response = client.get("/api/prompt-pairs/audit", params={"sample_limit": 2})
    assert audit_response.status_code == 200
    audit = audit_response.json()
    assert audit["total_pairs"] == 2
    assert audit["inspectable_pair_count"] == 1
    assert audit["invalid_pair_count"] == 1
    assert audit["invalid_pairs"][0]["reasons"] == ["sft_prompt_filename_placeholder"]

    reference_response = client.get("/api/prompt-pairs/reference-pack", params={"sample_limit": 10})
    assert reference_response.status_code == 200
    pack = reference_response.json()
    assert pack["total_pairs"] == 2
    assert pack["referenceable_pair_count"] == 1
    assert pack["unique_reference_count"] == 1
    assert pack["records"][0]["prompt"] == "How's Portland today?"
    assert "charles_sft.yaml" not in pack["jsonl"]


def test_prompt_pair_factory_uses_reference_pack_when_source_chunks_have_no_examples():
    _client, engine = build_client()

    with Session(engine) as session:
        for index in range(1, 10):
            decisions = {
                "artifact_mode": "sft",
                "system_prompt": "You are Charles Rotmil. Write naturally in his voice.",
                "prompt": f"Memoir reference prompt {index}",
                "content": f"memoir reference response {index}\nwith concrete rhythm\n\nlove\ndad",
                "voice_mode": "memoir_scene",
                "conversation_family": "adam_prompted_memory",
                "truth_status": "adam_expert_reconstruction",
                "synthetic": True,
                "context": f"reference context {index}",
            }
            session.add(
                Task(
                    human_id=f"TASK_REFERENCE_CONTEXT_{index:03d}",
                    task_type="gold_voice_edit",
                    target_type="prompt_pair",
                    target_id=f"prompt_pair_reference_context_{index:03d}",
                    queue="prompt_pairs_needing_gold_edits",
                    input_payload={**decisions, "pair_index": index},
                    created_by="test",
                )
            )
        candidate = Task(
            human_id="TASK_CANDIDATE_WITHOUT_CHUNK_REFERENCES",
            task_type="grounded_prompt_pair_candidate",
            target_type="segment",
            target_id="segment_without_reference_examples",
            queue="prompt_pair_factory",
            input_payload={
                "source_filename": "loose_memoir_note.txt",
                "preview_text": "Winter in Maine. The car held up. Miracle.",
                "source_use_mode": "summary_only",
                "quote_policy": "do_not_quote_or_export",
                "privacy_clearance": "family_private",
            },
            created_by="test",
        )
        session.add(candidate)
        session.flush()

        created = create_prompt_pair_review_task(
            session=session,
            candidate_task=candidate,
            decisions={
                "voice_mode": "memoir_scene",
                "conversation_family": "adam_prompted_memory",
                "truth_mode": "adam_expert_reconstruction",
                "no_live_model_call": True,
            },
            annotation_id="annotation_reference_context_fixture",
        )
        session.commit()

        review_task = session.get(Task, created["review_task_id"])
        prompt_spec = session.get(PromptSpec, review_task.input_payload["prompt_spec_id"])
        generation = session.get(Generation, review_task.input_payload["generation_id"])

        assert review_task.input_payload["reference_example_count"] == 8
        assert prompt_spec.metadata_json["reference_example_count"] == 8
        assert generation.model_parameters["no_live_model_call"] is True
        assert generation.model_parameters["source"] == "deterministic_scaffold"
        assert review_task.input_payload["prompt_pair_factory_generation_status"] == "scaffold_no_model_call"


def test_prompt_pair_voice_mode_backfill_splits_imported_default_mode_without_changing_text():
    client, engine = build_client()
    examples = [
        ("Tell me about the train to Vienna.", "we were on the train to vienna during the war...\nfather was there.", "memoir_scene"),
        ("What makes a good photograph?", "the camera is only part of it.\ncartier-bresson knew this.", "photography_reflection"),
        ("What do you think about Diogenes?", "diogenes threw away his cup.\nthat is freedom.", "philosophical_fragment"),
        ("Adam is overdue on chess.", "Over by two days\nHurry and move!", "logistical_note"),
        ("How was the soup?", "soup was thin...\npea soup with kielbasa was better.", "comic_observation"),
    ]
    with Session(engine) as session:
        for index, (prompt, content, _expected) in enumerate(examples, start=1):
            decisions = {
                "artifact_mode": "sft",
                "system_prompt": "You are Charles Rotmil.",
                "prompt": prompt,
                "content": content,
                "voice_mode": "father_to_adam",
                "truth_status": "adam_expert_reconstruction",
                "synthetic": True,
            }
            compiled = compile_pair_export(decisions)
            session.add(
                Task(
                    human_id=f"TASK_VOICE_BACKFILL_{index:03d}",
                    task_type="gold_voice_edit",
                    target_type="prompt_pair",
                    target_id=f"prompt_pair_backfill_{index:03d}",
                    queue="prompt_pairs_needing_gold_edits",
                    input_payload={**decisions, "pair_index": index, "export_preview_yaml": compiled["yaml_preview"]},
                    created_by="test",
                )
            )
        session.commit()

    dry_run = client.post("/api/prompt-pairs/backfill-voice-modes", params={"dry_run": "true"})
    assert dry_run.status_code == 200
    assert dry_run.json()["updated_count"] == len(examples)

    response = client.post("/api/prompt-pairs/backfill-voice-modes", params={"dry_run": "false"})
    assert response.status_code == 200
    payload = response.json()
    assert payload["updated_count"] == len(examples)
    for _prompt, _content, expected in examples:
        assert payload["after"][expected] == 1

    audit = client.get("/api/prompt-pairs/audit", params={"sample_limit": 5}).json()
    for _prompt, _content, expected in examples:
        assert audit["voice_mode_counts"][expected] == 1

    with Session(engine) as session:
        tasks = session.exec(select(Task).order_by(Task.created_at.asc())).all()
        for task, (prompt, content, expected) in zip(tasks, examples):
            assert task.input_payload["prompt"] == prompt
            assert task.input_payload["content"] == content
            assert task.input_payload["voice_mode"] == expected
            assert task.input_payload["voice_mode_source"] == "deterministic_classifier_v1"


def test_prompt_pair_voice_mode_classifier_respects_explicit_non_default_mode():
    assert (
        classify_prompt_pair_voice_mode(
            prompt="What happened in the war?",
            response="war and monastery",
            current_voice_mode="grief_memory",
        )
        == "grief_memory"
    )
