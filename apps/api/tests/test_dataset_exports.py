import hashlib

from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app.db.session import get_session
from app.main import app
from app.models import Boundary, ContextPack, DPOPair, DatasetExportItem, EmbeddingRecord, GoldVoiceExample, SFTCandidate, Task


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


def add_gold_with_sft(session: Session, human_id: str, boundary_status: str, export_status: str = "approved") -> str:
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
        downstream_use={
            "sft": True,
            "synthetic": True,
            "artifact_mode": "sft",
            "context": "approved fixture context",
            "grounding_asset_id": "asset_fixture",
            "source_annotation_id": "annotation_fixture",
            "export_preview_yaml": "- messages:\n   - role: system\n     content: Write in Charles voice.",
        },
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
    return gold.id


def test_stored_export_jsonl_matches_manifest_hash_in_build_order():
    client, engine = build_client()
    with Session(engine) as session:
        first_gold_id = add_gold_with_sft(session, "GOLD_FIRST", "passed")
        first_gold = session.get(GoldVoiceExample, first_gold_id)
        first_gold.id = "z-source-gold"
        first_sft = session.exec(
            select(SFTCandidate).where(SFTCandidate.source_gold_voice_example_id == first_gold_id)
        ).first()
        first_sft.id = "sft-first"
        first_sft.source_gold_voice_example_id = first_gold.id

        second_gold_id = add_gold_with_sft(session, "GOLD_SECOND", "passed")
        second_gold = session.get(GoldVoiceExample, second_gold_id)
        second_gold.id = "a-source-gold"
        second_gold.adam_gold_edit = "porch light is still on. text me when you land."
        second_sft = session.exec(
            select(SFTCandidate).where(SFTCandidate.source_gold_voice_example_id == second_gold_id)
        ).first()
        second_sft.id = "sft-second"
        second_sft.source_gold_voice_example_id = second_gold.id
        second_sft.messages = [
            {"role": "system", "content": "Write in Charles voice."},
            {"role": "user", "content": "Say goodnight from the porch."},
            {"role": "assistant", "content": second_gold.adam_gold_edit},
        ]
        session.commit()

    export = client.post("/api/dataset-exports/build", json={"export_type": "sft", "version": "v-order"})
    assert export.status_code == 200
    body = export.json()
    manifest = body["manifest"]
    assert manifest["source_ids"] == ["z-source-gold", "a-source-gold"]

    stored_jsonl = client.get(f"/api/dataset-exports/{body['id']}/jsonl")
    assert stored_jsonl.status_code == 200
    assert hashlib.sha256(stored_jsonl.text.encode("utf-8")).hexdigest() == manifest["content_sha256"]
    assert stored_jsonl.text.splitlines()[0].find("z-source-gold") > -1
    assert stored_jsonl.text.splitlines()[1].find("a-source-gold") > -1


def test_export_dry_run_excludes_boundary_blocked_and_candidate_items():
    client, engine = build_client()
    with Session(engine) as session:
        approved_gold_id = add_gold_with_sft(session, "GOLD_APPROVED", "passed")
        duplicate_gold_id = add_gold_with_sft(session, "GOLD_APPROVED_DUPLICATE", "passed")
        add_gold_with_sft(session, "GOLD_BLOCKED", "blocked")
        add_gold_with_sft(session, "GOLD_CANDIDATE", "passed", export_status="candidate")
        session.commit()

    dry_run = client.get("/api/dataset-exports/dry-run?export_type=sft")
    assert dry_run.status_code == 200
    body = dry_run.json()
    assert body["included_count"] == 1
    assert body["excluded_count"] == 3
    assert body["included"][0]["source"]["gold_human_id"] == "GOLD_APPROVED"
    assert body["included"][0]["source"]["context_boundary_status"] == "passed"
    metadata = body["included"][0]["payload"]["metadata"]
    assert metadata["voice_mode"] == "father_to_adam"
    assert metadata["synthetic"] is True
    assert metadata["artifact_mode"] == "sft"
    assert metadata["context"] == "approved fixture context"
    assert metadata["grounding_asset_id"] == "asset_fixture"
    assert metadata["source_annotation_id"] == "annotation_fixture"
    assert metadata["export_preview_yaml"].startswith("- messages:")
    reasons = [reason for item in body["excluded"] for reason in item["reasons"]]
    assert "context_pack_boundary_blocked" in reasons
    assert "artifact_status_is_candidate" in reasons
    assert "duplicate_export_payload" in reasons
    duplicate = next(item for item in body["excluded"] if item["reasons"] == ["duplicate_export_payload"])
    assert duplicate["source_gold_voice_example_id"] == duplicate_gold_id
    assert duplicate["duplicate_of_artifact_id"] == body["included"][0]["artifact_id"]

    jsonl = client.get("/api/dataset-exports/jsonl?export_type=sft")
    assert jsonl.status_code == 200
    assert jsonl.text.count("\n") == 1

    export = client.post("/api/dataset-exports/build", json={"export_type": "sft", "version": "v-test"})
    assert export.status_code == 200
    manifest = export.json()["manifest"]
    export_id = export.json()["id"]
    assert manifest["export_type"] == "sft"
    assert manifest["version"] == "v-test"
    assert manifest["split"] == "train"
    assert manifest["format"] == "jsonl"
    assert manifest["generated_at"].endswith("Z")
    assert manifest["item_count"] == 1
    assert manifest["included_count"] == 1
    assert manifest["excluded_count"] == 3
    assert manifest["filters"] == {
        "export_type": "sft",
        "include_candidates": False,
        "status": "approved_only",
        "split": "train",
    }
    assert manifest["split_policy_snapshot"] == {
        "requested_split": "train",
        "holdout_eval_split_configured": False,
        "explicit_holdout_status": "not_configured",
        "notes": (
            "MVP dataset builds only the requested approved split. "
            "Held-out demo prompts are tracked separately by /api/model-status/demo-readiness."
        ),
    }
    assert manifest["source_ids"] == [approved_gold_id]
    assert manifest["artifact_ids"]
    assert manifest["stable_item_keys"] == [f"sft_candidate:{manifest['artifact_ids'][0]}"]
    assert manifest["content_sha256"]
    assert manifest["excluded_reasons"] == [
        "artifact_status_is_candidate",
        "context_pack_boundary_blocked",
        "duplicate_export_payload",
    ]
    assert manifest["boundary_policy_snapshot"] == {
        "blocked_context_boundaries_excluded": True,
        "export_requires_boundary_gate": True,
        "private_or_sensitive_items_require_explicit_clearance": True,
    }
    assert manifest["quality_policy_snapshot"] == {
        "candidate_items_excluded_from_build": True,
        "requires_approved_artifact_status": True,
        "response_b_major_privacy_issue_blocks_export": True,
    }
    assert manifest["dry_run"]["excluded_count"] == 3

    with Session(engine) as session:
        items = session.exec(select(DatasetExportItem).where(DatasetExportItem.dataset_export_id == export_id)).all()
        assert len(items) == 1
        assert items[0].source_id == approved_gold_id
        assert items[0].boundary_snapshot["context_boundary_status"] == "passed"
        assert items[0].boundary_snapshot["boundary_gate_passed"] is True
        assert items[0].quality_snapshot["status"] == "approved"
        assert items[0].quality_snapshot["quality_gate_passed"] is True

    stored_jsonl = client.get(f"/api/dataset-exports/{export_id}/jsonl")
    assert stored_jsonl.status_code == 200
    assert stored_jsonl.headers["content-type"].startswith("application/x-ndjson")
    assert stored_jsonl.text == jsonl.text

    second_export = client.post("/api/dataset-exports/build", json={"export_type": "sft", "version": "v-test"})
    assert second_export.status_code == 200
    second_manifest = second_export.json()["manifest"]
    for stable_key in [
        "item_count",
        "included_count",
        "excluded_count",
        "source_ids",
        "artifact_ids",
        "stable_item_keys",
        "content_sha256",
        "excluded_reasons",
    ]:
        assert second_manifest[stable_key] == manifest[stable_key]


def test_approved_actual_rows_with_quality_or_structural_blockers_are_excluded():
    client, engine = build_client()
    with Session(engine) as session:
        blocked_sft_gold_id = add_gold_with_sft(session, "GOLD_APPROVED_BUT_QUALITY_BLOCKED", "passed")
        sft_candidate = session.exec(
            select(SFTCandidate).where(SFTCandidate.source_gold_voice_example_id == blocked_sft_gold_id)
        ).one()
        sft_candidate.quality_gate = {"export_blockers": ["manual_quality_hold"]}
        sft_candidate.export_status = "approved"
        session.add(sft_candidate)

        context = ContextPack(
            human_id="CTX_DPO_APPROVED_BUT_BLOCKED",
            user_intent="gold_voice_generation",
            requested_voice_mode="father_to_adam",
            truth_mode="adam_expert_reconstruction",
            boundaries_snapshot={"boundary_status": "passed"},
        )
        session.add(context)
        session.flush()
        dpo_gold = GoldVoiceExample(
            human_id="GOLD_DPO_APPROVED_BUT_BLOCKED",
            context_pack_id=context.id,
            voice_mode="father_to_adam",
            truth_status="adam_expert_reconstruction",
            adam_gold_edit="soup was thin...\n\ndad",
            downstream_use={"dpo": True, "artifact_mode": "dpo"},
            ratings={"response_rubric": {"response_b": {"privacy_export_safety": {"status": "no_issues"}}}},
        )
        session.add(dpo_gold)
        session.flush()
        session.add(
            DPOPair(
                source_gold_voice_example_id=dpo_gold.id,
                prompt="How was the soup?",
                chosen="soup was thin...\n\ndad",
                rejected="The soup was bland.",
                reason=[],
                export_status="approved",
            )
        )
        session.commit()

    sft = client.get("/api/dataset-exports/dry-run?export_type=sft")
    assert sft.status_code == 200
    sft_body = sft.json()
    assert sft_body["included_count"] == 0
    sft_reasons = [reason for item in sft_body["excluded"] for reason in item["reasons"]]
    assert "manual_quality_hold" in sft_reasons

    dpo = client.get("/api/dataset-exports/dry-run?export_type=dpo")
    assert dpo.status_code == 200
    dpo_body = dpo.json()
    assert dpo_body["included_count"] == 0
    dpo_reasons = [reason for item in dpo_body["excluded"] for reason in item["reasons"]]
    assert "dpo_rejected_reason_empty" in dpo_reasons

    sft_jsonl = client.get("/api/dataset-exports/jsonl?export_type=sft")
    dpo_jsonl = client.get("/api/dataset-exports/jsonl?export_type=dpo")
    assert sft_jsonl.status_code == 200
    assert dpo_jsonl.status_code == 200
    assert sft_jsonl.text == ""
    assert dpo_jsonl.text == ""


def test_sft_export_requires_source_boundary_when_context_marks_boundary_review_required():
    client, engine = build_client()
    with Session(engine) as session:
        source_task = Task(
            human_id="TASK_SOURCE_NEEDS_BOUNDARY",
            task_type="text_segment_review",
            target_type="segment",
            target_id="segment-source-1",
            queue="text_segments_needing_review",
            reason_created="fixture",
        )
        session.add(source_task)
        session.flush()
        gold_id = add_gold_with_sft(session, "GOLD_SOURCE_BOUNDARY_REQUIRED", "passed")
        gold = session.get(GoldVoiceExample, gold_id)
        context = session.get(ContextPack, gold.context_pack_id)
        context.boundaries_snapshot = {
            "requires_boundary_review_before_export": True,
            "source_task_id": source_task.id,
            "source_title": "fixture.yaml",
        }
        session.add(context)
        session.commit()

    blocked = client.get("/api/dataset-exports/dry-run?export_type=sft").json()
    assert blocked["included_count"] == 0
    blocked_reasons = [reason for item in blocked["excluded"] for reason in item["reasons"]]
    assert "source_boundary_review_required" in blocked_reasons

    with Session(engine) as session:
        session.add(
            Boundary(
                target_type="segment",
                target_id="segment-source-1",
                privacy_level="public_safe",
                searchable=True,
                retrievable_in_chat=True,
                summarizable=True,
                usable_for_voice_context=True,
                usable_for_sft=True,
                usable_for_dpo=False,
                usable_for_eval=True,
                redaction_required=False,
                reviewed_by="adam",
            )
        )
        session.commit()

    unblocked = client.get("/api/dataset-exports/dry-run?export_type=sft").json()
    assert unblocked["included_count"] == 1
    assert unblocked["excluded_count"] == 0
    included = unblocked["included"][0]
    assert included["source"]["context_boundary_gate_status"] == "passed"
    assert included["source"]["context_boundary_gate_reasons"] == []
    assert included["source"]["source_boundary_id"]
    boundary_gate = included["payload"]["metadata"]["boundary_gate"]
    assert boundary_gate["status"] == "passed"
    assert boundary_gate["reasons"] == []
    assert boundary_gate["source_boundary_usable_for_sft"] is True


def test_candidate_export_dry_run_includes_prompt_pair_review_tasks_only_when_requested():
    client, engine = build_client()
    with Session(engine) as session:
        session.add(
            Task(
                human_id="TASK_EXPORTABLE_PROMPT_PAIR",
                task_type="gold_voice_edit",
                target_type="prompt_pair",
                target_id="prompt_pair_1",
                queue="prompt_pairs_needing_gold_edits",
                input_payload={
                    "artifact_mode": "sft",
                    "system_prompt": "You are Charles Rotmil.",
                    "prompt": "How's Portland today?",
                    "content": "gray here...\nlight rain\n\ndad",
                    "voice_mode": "mundane_text_message",
                    "truth_status": "adam_expert_reconstruction",
                    "synthetic": True,
                    "source_title": "SFT fixture",
                    "grounding_asset_id": "asset_1",
                },
                created_by="test",
            )
        )
        session.commit()

    approved_only = client.get("/api/dataset-exports/dry-run?export_type=sft")
    assert approved_only.status_code == 200
    assert approved_only.json()["included_count"] == 0

    candidate_allowed = client.get("/api/dataset-exports/dry-run?export_type=sft&include_candidates=true")
    assert candidate_allowed.status_code == 200
    body = candidate_allowed.json()
    assert body["included_count"] == 1
    item = body["included"][0]
    assert item["artifact_type"] == "prompt_pair_sft_review_candidate"
    assert item["export_status"] == "review_candidate"
    assert item["source_gold_voice_example_id"] is None
    assert item["payload"]["messages"] == [
        {"role": "system", "content": "You are Charles Rotmil."},
        {"role": "user", "content": "How's Portland today?"},
        {"role": "assistant", "content": "gray here...\nlight rain\n\ndad"},
    ]
    assert item["payload"]["metadata"]["voice_mode"] == "mundane_text_message"
    assert item["payload"]["metadata"]["review_blockers"] == ["needs_adam_gold_edit"]


def test_candidate_export_dry_run_preserves_prompt_pair_provenance_backstage():
    client, engine = build_client()
    with Session(engine) as session:
        session.add(
            Task(
                human_id="TASK_PROMPT_PAIR_WITH_PROVENANCE",
                task_type="gold_voice_edit",
                target_type="prompt_pair",
                target_id="prompt_pair_with_provenance",
                queue="prompt_pairs_needing_gold_edits",
                input_payload={
                    "artifact_mode": "sft",
                    "system_prompt": "You are Charles Rotmil.",
                    "prompt": "What were you writing to Tom about?",
                    "content": "Hi Tom\nHow the hell are you?\nNo word in a while.\n\nCharles",
                    "voice_mode": "verbatim_email_reply",
                    "truth_status": "adam_expert_reconstruction",
                    "synthetic": True,
                    "source_title": "thread.eml",
                    "grounding_asset_id": "asset_email_1",
                    "source_segment_id": "segment_email_001",
                    "source_chunk_index": 2,
                    "source_prompt_pair_example_index": 12,
                    "source_section_review_hint": "complete_thought",
                    "source_excerpt": "Email 1:\nHi Tom\nHow the hell are you?\nNo word in a while.\nCharles",
                    "source_photo_id": "photo_memory_anchor_1",
                    "photo_context_profile_id": "profile_photo_1",
                    "photo_memory_id": "memory_photo_1",
                    "boundary_snapshot": {
                        "privacy_level": "family_private",
                        "usable_for_sft": False,
                        "usable_for_dpo": False,
                        "reviewed_by": "adam",
                    },
                    "pair_generation_metadata": {
                        "strategy": "natural_section",
                        "model_name": "gpt-5.5",
                        "reasoning_effort": "medium",
                        "no_live_model_call": True,
                    },
                    "export_preview_yaml": "- messages:\n  - role: system\n    content: You are Charles Rotmil.\n",
                    "context": "Imported email thread; provenance should stay in metadata.",
                },
                created_by="test",
            )
        )
        session.commit()

    response = client.get("/api/dataset-exports/dry-run?export_type=sft&include_candidates=true")

    assert response.status_code == 200
    body = response.json()
    assert body["included_count"] == 1
    payload = body["included"][0]["payload"]
    assert payload["messages"] == [
        {"role": "system", "content": "You are Charles Rotmil."},
        {"role": "user", "content": "What were you writing to Tom about?"},
        {"role": "assistant", "content": "Hi Tom\nHow the hell are you?\nNo word in a while.\n\nCharles"},
    ]
    metadata = payload["metadata"]
    assert metadata["source_segment_id"] == "segment_email_001"
    assert metadata["source_chunk_index"] == 2
    assert metadata["source_prompt_pair_example_index"] == 12
    assert metadata["source_section_review_hint"] == "complete_thought"
    assert metadata["source_excerpt"].startswith("Email 1:")
    assert metadata["source_photo_id"] == "photo_memory_anchor_1"
    assert metadata["photo_context_profile_id"] == "profile_photo_1"
    assert metadata["photo_memory_id"] == "memory_photo_1"
    assert metadata["boundary_snapshot"]["privacy_level"] == "family_private"
    assert metadata["pair_generation_metadata"] == {
        "strategy": "natural_section",
        "model_name": "gpt-5.5",
        "reasoning_effort": "medium",
        "no_live_model_call": True,
    }
    assert "Imported email thread" in metadata["context"]
    assert "source_segment_id" not in payload["messages"][2]["content"]
    assert "boundary_snapshot" not in payload["messages"][2]["content"]
    assert "pair_generation_metadata" not in payload["messages"][2]["content"]


def test_approved_sft_export_preserves_reviewed_prompt_pair_provenance_backstage():
    client, engine = build_client()
    with Session(engine) as session:
        gold_id = add_gold_with_sft(session, "GOLD_APPROVED_PROVENANCE", "passed")
        gold = session.get(GoldVoiceExample, gold_id)
        gold.downstream_use = {
            **gold.downstream_use,
            "source_segment_id": "segment_reviewed_001",
            "source_chunk_index": 4,
            "source_prompt_pair_example_index": 9,
            "source_section_review_hint": "complete_thought",
            "source_excerpt": "Reviewed source excerpt kept in metadata only.",
            "source_photo_id": "photo_reviewed_anchor",
            "photo_context_profile_id": "profile_reviewed_anchor",
            "photo_memory_id": "memory_reviewed_anchor",
            "pair_generation_metadata": {
                "strategy": "natural_section",
                "source_text_sha256": "abc123",
                "no_live_model_call": True,
            },
        }
        session.commit()

    response = client.get("/api/dataset-exports/dry-run?export_type=sft")

    assert response.status_code == 200
    body = response.json()
    assert body["included_count"] == 1
    payload = body["included"][0]["payload"]
    metadata = payload["metadata"]
    assert metadata["source_segment_id"] == "segment_reviewed_001"
    assert metadata["source_chunk_index"] == 4
    assert metadata["source_prompt_pair_example_index"] == 9
    assert metadata["source_section_review_hint"] == "complete_thought"
    assert metadata["source_photo_id"] == "photo_reviewed_anchor"
    assert metadata["photo_context_profile_id"] == "profile_reviewed_anchor"
    assert metadata["photo_memory_id"] == "memory_reviewed_anchor"
    assert metadata["pair_generation_metadata"]["source_text_sha256"] == "abc123"
    assert "source_segment_id" not in payload["messages"][2]["content"]
    assert "pair_generation_metadata" not in payload["messages"][2]["content"]


def test_export_dry_run_and_build_include_unified_evidence_corpus_snapshot():
    client, engine = build_client()
    with Session(engine) as session:
        gold_id = add_gold_with_sft(session, "GOLD_APPROVED_EVIDENCE_SNAPSHOT", "passed")
        session.add(
            EmbeddingRecord(
                target_type="gold_voice",
                target_id=gold_id,
                embedding_type="gold_voice_text",
                modality="text",
                model_name="text-embedding-3-small",
                input_checksum="evidence-snapshot-checksum",
                input_text="Reviewed Charles voice example for export evidence.",
                input_preview="Reviewed Charles voice example for export evidence.",
                status="embedded",
                vector_uri="local://embedding_vectors/evidence-snapshot.json",
                vector_dims=1536,
                truth_status="adam_expert_reconstruction",
                metadata_json={"source": "gold_voice_edit"},
            )
        )
        session.commit()

    response = client.get("/api/dataset-exports/dry-run?export_type=sft")

    assert response.status_code == 200
    body = response.json()
    snapshot = body["evidence_corpus_snapshot"]
    assert snapshot["corpus_type"] == "unified_evidence_embedding_corpus"
    assert snapshot["record_count"] == 1
    assert snapshot["vector_ready_count"] == 1
    assert snapshot["ready_for_embedding_count"] == 0
    assert snapshot["safety"]["vector_values_in_exports"] is False
    assert snapshot["records"][0]["corpus_family"] == "approved_training_voice"
    assert snapshot["records"][0]["vector_uri"] == "local://embedding_vectors/evidence-snapshot.json"

    built = client.post("/api/dataset-exports/build", json={"export_type": "sft", "version": "v-test", "split": "train"})
    assert built.status_code == 200
    manifest_snapshot = built.json()["manifest"]["evidence_corpus_snapshot"]
    assert manifest_snapshot["record_count"] == 1
    assert manifest_snapshot["records"][0]["embedding_record_id"] == snapshot["records"][0]["embedding_record_id"]


def test_synthetic_dpo_candidates_are_durable_and_visible_to_dpo_dry_run():
    client, engine = build_client()
    with Session(engine) as session:
        for index in range(1, 4):
            session.add(
                Task(
                    human_id=f"TASK_SFT_FOR_DPO_{index}",
                    task_type="gold_voice_edit",
                    target_type="prompt_pair",
                    target_id=f"prompt_pair_{index}",
                    queue="prompt_pairs_needing_gold_edits",
                    input_payload={
                        "artifact_mode": "sft",
                        "system_prompt": "You are Charles Rotmil.",
                        "prompt": f"Prompt {index}?",
                        "content": f"charles response {index}\n\ndad",
                        "voice_mode": "father_to_adam",
                        "truth_status": "adam_expert_reconstruction",
                        "synthetic": True,
                    },
                    created_by="test",
                )
            )
        session.commit()

    dry_run = client.post("/api/prompt-pairs/synthesize-dpo-candidates", params={"limit": 2, "dry_run": "true"})
    assert dry_run.status_code == 200
    assert dry_run.json()["created_count"] == 2
    with Session(engine) as session:
        tasks = session.exec(select(Task)).all()
        assert not any((task.input_payload or {}).get("artifact_mode") == "dpo" for task in tasks)

    created = client.post("/api/prompt-pairs/synthesize-dpo-candidates", params={"limit": 2, "dry_run": "false"})
    assert created.status_code == 200
    assert created.json()["created_count"] == 2

    dpo = client.get("/api/dataset-exports/dry-run?export_type=dpo&include_candidates=true")
    assert dpo.status_code == 200
    body = dpo.json()
    assert body["included_count"] == 2
    first = body["included"][0]
    assert first["artifact_type"] == "prompt_pair_dpo_review_candidate"
    assert first["payload"]["preferred_output"].startswith("charles response")
    assert "straightforward response" in first["payload"]["non_preferred_output"]
    assert first["payload"]["preferred_output"] != first["payload"]["non_preferred_output"]
    metadata = first["payload"]["metadata"]
    assert any("voice_authenticity:" in reason for reason in metadata["reason"])
    assert metadata["candidate_review_policy"] == {
        "adam_review_required": True,
        "does_not_certify_final_authenticity": True,
        "chosen_side_is_preferred_candidate": True,
        "rejected_side_may_be_model_generated": True,
    }
    assert metadata["rejected_truth_status"] == "model_generated"
    assert metadata["chosen_issue_summary"]["issue_count"] == 0
    assert metadata["rejected_issue_summary"]["issue_count"] >= 2
    assert metadata["rejected_issue_summary"]["has_explanatory_notes"] is True
    assert metadata["response_rubric"]["rubric_source"] == "system_suggested_dpo_scaffold_requires_adam_review"
    assert "needs_adam_gold_edit" in first["payload"]["metadata"]["review_blockers"]
    assert "rejected_truth_status_model_generated_requires_review" in metadata["review_blockers"]

    second_run = client.post("/api/prompt-pairs/synthesize-dpo-candidates", params={"limit": 5, "dry_run": "false"})
    assert second_run.status_code == 200
    assert second_run.json()["created_count"] == 1
