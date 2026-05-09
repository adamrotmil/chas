import json

from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select
from fastapi.testclient import TestClient

from app.db.session import get_session
from app.main import app
from app.models import (
    AntiPattern,
    Annotation,
    Asset,
    Boundary,
    ContextPack,
    DPOPair,
    EmbeddingRecord,
    Entity,
    Generation,
    GoldVoiceExample,
    MetadataProfile,
    PromptSpec,
    SFTCandidate,
    Segment,
    SourceSpanAnnotation,
    Task,
    TaskDraft,
    TaskReceipt,
    VoiceMode,
)
from app.services.model_generation import TextDraftResult


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
    assert body["creates_or_updates"]["embedding_record_id"]
    assert body["creates_or_updates"]["task_receipt_id"]
    assert body["creates_or_updates"]["receipt"]["downstream_status"] == "export_ready"
    assert body["creates_or_updates"]["receipt"]["next_queue"] == "dataset_exports"
    assert body["creates_or_updates"]["receipt"]["export_artifact"]["artifact_modes"] == ["sft", "dpo"]
    assert body["creates_or_updates"]["receipt"]["export_artifact"]["statuses"] == {"sft": "approved", "dpo": "approved"}
    assert body["creates_or_updates"]["receipt"]["export_artifact"]["export_ready"] is True
    assert body["creates_or_updates"]["receipt"]["export_artifact"]["review_blockers"] == []
    assert body["creates_or_updates"]["receipt"]["export_artifact"]["checks"]["sft_has_system_user_assistant"] is True
    assert body["creates_or_updates"]["receipt"]["export_artifact"]["checks"]["dpo_chosen_rejected_distinct"] is True

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
        embedding = session.get(EmbeddingRecord, body["creates_or_updates"]["embedding_record_id"])
        assert embedding is not None
        assert embedding.embedding_type == "gold_voice_text"
        assert embedding.status == "ready_for_embedding"
        receipt = session.get(TaskReceipt, body["creates_or_updates"]["task_receipt_id"])
        assert receipt is not None
        assert receipt.downstream_status == "export_ready"
        assert receipt.summary["outcomes"]

    sft = client.get("/api/dataset-exports/jsonl?export_type=sft")
    dpo = client.get("/api/dataset-exports/jsonl?export_type=dpo")
    assert sft.status_code == 200
    assert "messages" in sft.text
    sft_payload = json.loads(sft.text)
    assert sft_payload["messages"][0] == {"role": "system", "content": "You are Charles Rotmil."}
    assert sft_payload["messages"][1] == {"role": "user", "content": "Write Adam a note after Maine."}
    assert dpo.status_code == 200
    assert "preferred_output" in dpo.text
    dpo_payload = json.loads(dpo.text)
    assert dpo_payload["input"]["messages"][0] == {"role": "system", "content": "You are Charles Rotmil."}


def test_task_submit_rejects_non_ready_resubmission_without_duplicate_artifacts():
    client, engine = build_client()
    with Session(engine) as session:
        asset = Asset(
            human_id="ASSET_RESUBMIT_GUARD",
            asset_type="text",
            title="Resubmit guard source",
            import_status="mirrored",
        )
        session.add(asset)
        session.flush()
        task = Task(
            human_id="TASK_RESUBMIT_GUARD",
            task_type="asset_triage",
            target_type="asset",
            target_id=asset.id,
            queue="asset_triage",
            input_payload={},
            created_by="test",
        )
        session.add(task)
        session.commit()
        task_id = task.id

    first = client.post(
        f"/api/tasks/{task_id}/submit",
        json={
            "decisions": {
                "process_next": "yes",
                "source_type": "personal_archive",
                "privacy_level": "family_private",
            }
        },
    )
    assert first.status_code == 200

    with Session(engine) as session:
        annotation_count = len(session.exec(select(Annotation)).all())
        receipt_count = len(session.exec(select(TaskReceipt)).all())
        boundary_count = len(session.exec(select(Boundary)).all())
        task = session.get(Task, task_id)
        assert task is not None
        assert task.status == "submitted"

    second = client.post(
        f"/api/tasks/{task_id}/submit",
        json={
            "decisions": {
                "process_next": "yes",
                "source_type": "personal_archive",
                "privacy_level": "family_private",
            }
        },
    )
    assert second.status_code == 409
    assert second.json()["detail"] == "Task is not ready for submit"

    with Session(engine) as session:
        assert len(session.exec(select(Annotation)).all()) == annotation_count
        assert len(session.exec(select(TaskReceipt)).all()) == receipt_count
        assert len(session.exec(select(Boundary)).all()) == boundary_count


def test_gold_voice_response_b_privacy_issue_blocks_export_readiness():
    client, engine = build_client()

    with Session(engine) as session:
        prompt = PromptSpec(
            human_id="PROMPT_PRIVACY",
            prompt_type="gold_voice_edit",
            voice_mode="father_to_adam",
            truth_mode="adam_expert_reconstruction",
            prompt_text="Write from a private letter.",
        )
        context = ContextPack(
            human_id="CTX_PRIVACY",
            user_intent="gold_voice_generation",
            requested_voice_mode="father_to_adam",
            truth_mode="adam_expert_reconstruction",
            boundaries_snapshot={"boundary_status": "passed"},
        )
        session.add(prompt)
        session.add(context)
        session.flush()
        generation = Generation(
            prompt_spec_id=prompt.id,
            context_pack_id=context.id,
            model_name="manual_test",
            output_text="A private person was named directly.",
        )
        session.add(generation)
        session.flush()
        task = Task(
            human_id="TASK_PRIVACY_GOLD",
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
                "prompt": "Write from a private letter.",
                "voice_mode": "father_to_adam",
                "truth_mode": "adam_expert_reconstruction",
                "model_draft": "A private person was named directly.",
                "adam_gold_edit": "call me when the street gets quiet.",
                "response_rubric": {
                    "response_a": {
                        "privacy_export_safety": {
                            "status": "major_issues",
                            "notes": "The rejected side names a private person.",
                            "issue_tags": [],
                        }
                    },
                    "response_b": {
                        "privacy_export_safety": {
                            "status": "major_issues",
                            "notes": "Still needs redaction before export.",
                            "issue_tags": [],
                        }
                    },
                },
                "rubric_summary": {
                    "sft_ready": False,
                    "preferred_export_blocked": True,
                    "preferred_major_issue_count": 1,
                },
                "export_flags": {"sft": True, "dpo": True, "eval": True, "anti_pattern": True, "style_rule": True},
            }
        },
    )

    assert response.status_code == 200

    with Session(engine) as session:
        gold = session.exec(select(GoldVoiceExample)).first()
        assert gold
        assert gold.ratings["derived_quality"]["preferred_export_blocked"] is True
        assert gold.ratings["derived_quality"]["sft_ready"] is False
        sft = session.exec(select(SFTCandidate)).first()
        assert sft
        assert sft.export_status == "candidate"
        assert sft.quality_gate["export_ready"] is False
        dpo_pair = session.exec(select(DPOPair)).first()
        assert dpo_pair
        assert dpo_pair.export_status == "candidate"

    dry_run = client.get("/api/dataset-exports/dry-run?export_type=sft&include_candidates=true")
    assert dry_run.status_code == 200
    excluded = dry_run.json()["excluded"]
    assert excluded
    assert "response_b_privacy_export_safety_block" in excluded[0]["reasons"]


def test_gold_voice_response_b_minor_issue_stays_candidate_until_resolved():
    client, engine = build_client()

    with Session(engine) as session:
        task = Task(
            human_id="TASK_MINOR_ISSUE_GOLD",
            task_type="gold_voice_edit",
            target_type="prompt_pair",
            target_id="manual_sft",
            queue="prompt_pairs_needing_gold_edits",
            input_payload={"artifact_mode": "sft", "truth_status": "adam_expert_reconstruction"},
        )
        session.add(task)
        session.commit()
        task_id = task.id

    response = client.post(
        f"/api/tasks/{task_id}/submit",
        json={
            "decisions": {
                "artifact_mode": "sft",
                "system_prompt": "You are Charles Rotmil.",
                "prompt": "How's Portland today?",
                "content": "gray here...\nlight rain\n\nlove\ndad",
                "voice_mode": "mundane_text_message",
                "synthetic": False,
                "response_rubric": {
                    "response_b": {
                        "voice_authenticity": {
                            "status": "minor_issues",
                            "notes": "Almost right, but closing needs review.",
                            "issue_tags": ["closing_needs_review"],
                        },
                        "privacy_export_safety": {
                            "status": "no_issues",
                            "notes": "",
                            "issue_tags": [],
                        },
                    }
                },
                "rubric_summary": {
                    "sft_ready": False,
                    "preferred_issue_count": 1,
                    "preferred_major_issue_count": 0,
                },
                "export_flags": {"sft": True, "dpo": False, "eval": False, "anti_pattern": False, "style_rule": False},
            }
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["creates_or_updates"]["receipt"]["downstream_status"] == "candidate"
    assert body["creates_or_updates"]["receipt"]["next_queue"] == "prompt_pairs_needing_gold_edits"
    assert body["creates_or_updates"]["receipt"]["export_artifact"]["artifact_modes"] == ["sft"]
    assert body["creates_or_updates"]["receipt"]["export_artifact"]["statuses"] == {"sft": "candidate"}
    assert body["creates_or_updates"]["receipt"]["export_artifact"]["export_ready"] is False
    assert body["creates_or_updates"]["receipt"]["export_artifact"]["review_blockers"] == ["sft_export_status=candidate"]

    with Session(engine) as session:
        gold = session.exec(select(GoldVoiceExample)).first()
        sft = session.exec(select(SFTCandidate)).first()
        assert gold is not None
        assert sft is not None
        assert gold.ratings["derived_quality"]["response_b_issue_count"] == 1
        assert gold.ratings["derived_quality"]["response_b_major_issue_count"] == 0
        assert gold.ratings["derived_quality"]["sft_ready"] is False
        assert sft.export_status == "candidate"
        assert sft.quality_gate["export_ready"] is False

    approved_only = client.get("/api/dataset-exports/dry-run?export_type=sft")
    assert approved_only.status_code == 200
    assert approved_only.json()["included_count"] == 0
    assert approved_only.json()["excluded"][0]["reasons"] == ["artifact_status_is_candidate"]


def test_voice_modes_endpoint_persists_custom_modes():
    client, engine = build_client()

    initial = client.get("/api/voice-modes")
    assert initial.status_code == 200
    assert any(mode["slug"] == "father_to_adam" for mode in initial.json())

    created = client.post("/api/voice-modes", json={"label": "Market Street Morning", "family": "adam_defined"})
    assert created.status_code == 200
    assert created.json()["slug"] == "market_street_morning"

    with Session(engine) as session:
        mode = session.exec(select(VoiceMode).where(VoiceMode.slug == "market_street_morning")).first()
        assert mode is not None
        assert mode.label == "Market Street Morning"


def test_unified_dpo_gold_submission_creates_dpo_only_artifact():
    client, engine = build_client()

    with Session(engine) as session:
        task = Task(
            human_id="TASK_UNIFIED_DPO",
            task_type="gold_voice_edit",
            target_type="prompt_pair",
            target_id="manual",
            queue="prompt_pairs_needing_gold_edits",
            input_payload={"artifact_mode": "dpo", "voice_mode": "father_to_adam"},
        )
        session.add(task)
        session.commit()
        task_id = task.id

    response = client.post(
        f"/api/tasks/{task_id}/submit",
        json={
            "decisions": {
                "artifact_mode": "dpo",
                "voice_mode": "father_to_adam",
                "synthetic": True,
                "prompt": "How was the soup?",
                "chosen": "soup was thin...\ntasted like nothing\n\nlove\ndad",
                "rejected": "The soup was bland and unsatisfying.",
                "context": "Rejected is too generic and polished.",
                "response_rubric": {
                    "response_a": {
                        "voice_authenticity": {
                            "status": "minor_issues",
                            "notes": "Too generic and essay-like.",
                            "issue_tags": [],
                        }
                    },
                    "response_b": {
                        "voice_authenticity": {
                            "status": "no_issues",
                            "notes": "",
                            "issue_tags": [],
                        }
                    },
                },
            }
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["creates_or_updates"]["dpo_pair_id"]
    assert "sft_candidate_id" not in body["creates_or_updates"]
    assert body["creates_or_updates"]["receipt"]["downstream_status"] == "export_ready"
    assert body["creates_or_updates"]["receipt"]["export_artifact"]["artifact_modes"] == ["dpo"]
    assert body["creates_or_updates"]["receipt"]["export_artifact"]["statuses"] == {"dpo": "approved"}
    assert body["creates_or_updates"]["receipt"]["export_artifact"]["checks"]["dpo_reason_count"] == 1
    assert body["creates_or_updates"]["receipt"]["export_artifact"]["checks"]["dpo_has_prompt_chosen_rejected"] is True

    with Session(engine) as session:
        assert session.exec(select(SFTCandidate)).first() is None
        dpo = session.exec(select(DPOPair)).first()
        gold = session.exec(select(GoldVoiceExample)).first()
        assert dpo is not None
        assert dpo.prompt == "How was the soup?"
        assert dpo.chosen.startswith("soup was thin")
        assert dpo.reason == ["voice_authenticity: Too generic and essay-like."]
        assert gold is not None
        assert gold.downstream_use["artifact_mode"] == "dpo"
        assert "chosen: |" in gold.downstream_use["export_preview_yaml"]


def test_source_review_generate_pairs_from_yaml_creates_spans_and_make_gold_tasks():
    client, engine = build_client()
    source_yaml = """- messages:
   - role: system
     content: You are Charles Rotmil. Write naturally in his voice.
   - role: user
     content: How's Portland today?
   - role: assistant
     content: |
       gray here...
       light rain
       keeps the trees happy

       love
       dad
"""

    with Session(engine) as session:
        asset = Asset(
            human_id="ASSET_PAIR_SOURCE",
            asset_type="text",
            title="Prompt pairs.yml",
            mime_type="text/yaml",
        )
        session.add(asset)
        session.flush()
        segment = Segment(
            human_id="SEG_PAIR_SOURCE",
            asset_id=asset.id,
            segment_type="text_preview",
            title="Prompt pair source",
            text_content=source_yaml,
        )
        session.add(segment)
        session.flush()
        source_segment_id = segment.id
        task = Task(
            human_id="TASK_PAIR_SOURCE_REVIEW",
            task_type="text_segment_review",
            target_type="segment",
            target_id=segment.id,
            queue="text_segments_needing_review",
            input_payload={"asset_id": asset.id, "source_filename": "prompt_pairs.yml", "preview_text": source_yaml},
            created_by="text_extraction",
        )
        session.add(task)
        session.commit()
        task_id = task.id

    response = client.post(
        f"/api/tasks/{task_id}/submit",
        json={
            "decisions": {
                "source_genre": "prompt_pair_yaml",
                "authorship": "adam",
                "fictionality_status": "mixed",
                "truth_status": "adam_expert_reconstruction",
                "voice_presence": "charles_voice",
                "ready_for_processing": "yes",
                "privacy_level": "family_private",
                "usable_for_voice_context": "yes",
                "usable_for_grounded_generation": "yes",
                "generate_pairs_on_submit": "yes",
                "source_spans": [
                    {
                        "start_char": 95,
                        "end_char": 117,
                        "text": "How's Portland today?",
                        "span_type": "prompt",
                        "speaker": "Adam",
                        "code": "clean prompt",
                    }
                ],
            }
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["creates_or_updates"]["make_gold_task_ids"]
    assert body["creates_or_updates"]["source_span_annotation_ids"]

    with Session(engine) as session:
        span = session.exec(select(SourceSpanAnnotation)).first()
        assert span is not None
        assert span.span_type == "prompt"
        make_gold_task = session.get(Task, body["creates_or_updates"]["make_gold_task_ids"][0])
        assert make_gold_task is not None
        assert make_gold_task.task_type == "gold_voice_edit"
        assert make_gold_task.input_payload["artifact_mode"] == "sft"
        assert make_gold_task.input_payload["prompt"] == "How's Portland today?"
        assert "gray here" in make_gold_task.input_payload["content"]
        assert "messages:" in make_gold_task.input_payload["export_preview_yaml"]
        assert make_gold_task.input_payload["source_segment_id"] == source_segment_id
        assert len(make_gold_task.input_payload["source_excerpt_sha256"]) == 64
        assert make_gold_task.input_payload["source_evidence_status"] == "evidence_linked"
        assert make_gold_task.input_payload["source_evidence_refs"][0]["type"] == "source_segment"
        evidence_gate = make_gold_task.input_payload["pair_generation_metadata"]["evidence_gate"]
        assert evidence_gate == {"passed": True, "blockers": []}


def test_source_review_generate_pairs_from_structured_chunks_creates_singleton_prompt_pair_tasks():
    client, engine = build_client()
    preview_text = "- messages:\n  - role: system\n    content: You are Charles Rotmil.\n"

    with Session(engine) as session:
        asset = Asset(
            human_id="ASSET_STRUCTURED_PROMPT_PAIRS",
            asset_type="text",
            title="charles_sft.yaml",
            original_filename="charles_sft.yaml",
            mime_type="application/x-yaml",
        )
        session.add(asset)
        session.flush()
        preview = Segment(
            human_id="SEG_STRUCTURED_PROMPT_PAIR_PREVIEW",
            asset_id=asset.id,
            segment_type="text_preview",
            title="charles_sft.yaml preview",
            text_content=preview_text,
        )
        session.add(preview)
        session.flush()
        chunks = [
            Segment(
                human_id="SEG_STRUCTURED_PROMPT_PAIR_001",
                asset_id=asset.id,
                segment_type="text_chunk",
                title="Example 1: How's Portland today?",
                text_content=(
                    "Example 1\n\n"
                    "system:\nYou are Charles Rotmil.\n\n"
                    "user:\nHow's Portland today?\n\n"
                    "assistant:\ngray here...\nlight rain\nkeeps the trees happy\nwent for a walk\nocean hiding behind fog"
                ),
                locator={"kind": "prompt_pair_example", "chunk_index": 1},
                metadata_json={
                    "chunking_strategy": "prompt_pair_yaml",
                    "prompt_pair_example_index": 1,
                    "chunk_index": 1,
                    "structured_messages": [
                        {"role": "system", "content": "You are Charles Rotmil."},
                        {"role": "user", "content": "How's Portland today?"},
                        {
                            "role": "assistant",
                            "content": "gray here...\nlight rain\nkeeps the trees happy\nwent for a walk\nocean hiding behind fog",
                        },
                    ],
                },
            ),
            Segment(
                human_id="SEG_STRUCTURED_PROMPT_PAIR_002",
                asset_id=asset.id,
                segment_type="text_chunk",
                title="Example 2: Do you feel like getting coffee?",
                text_content=(
                    "Example 2\n\n"
                    "system:\nYou are Charles Rotmil. Write naturally in his voice.\n\n"
                    "user:\nDo you feel like getting coffee?\n\n"
                    "assistant:\nsure... yeah.\nCoffee Me Up down the street?\n\nlove\ndad"
                ),
                locator={"kind": "prompt_pair_example", "chunk_index": 2},
                metadata_json={
                    "chunking_strategy": "prompt_pair_yaml",
                    "prompt_pair_example_index": 2,
                    "chunk_index": 2,
                    "structured_messages": [
                        {"role": "system", "content": "You are Charles Rotmil. Write naturally in his voice."},
                        {"role": "user", "content": "Do you feel like getting coffee?"},
                        {"role": "assistant", "content": "sure... yeah.\nCoffee Me Up down the street?\n\nlove\ndad"},
                    ],
                },
            ),
            Segment(
                human_id="SEG_STRUCTURED_PROMPT_PAIR_003_HELD",
                asset_id=asset.id,
                segment_type="text_chunk",
                title="Example 3: held for missing assistant",
                text_content="Example 3\n\nuser:\nWhat was missing here?\n\nassistant:\n",
                locator={"kind": "prompt_pair_example", "chunk_index": 3},
                metadata_json={
                    "chunking_strategy": "prompt_pair_yaml",
                    "prompt_pair_example_index": 3,
                    "chunk_index": 3,
                    "section_review_hint": "missing assistant response",
                },
            ),
        ]
        session.add_all(chunks)
        session.flush()
        task = Task(
            human_id="TASK_STRUCTURED_PROMPT_PAIR_REVIEW",
            task_type="text_segment_review",
            target_type="segment",
            target_id=preview.id,
            queue="text_segments_needing_review",
            input_payload={
                "asset_id": asset.id,
                "source_filename": "charles_sft.yaml",
                "preview_text": preview.text_content,
                "chunk_count": 3,
            },
            created_by="text_extraction",
        )
        session.add(task)
        session.commit()
        task_id = task.id

    response = client.post(
        f"/api/tasks/{task_id}/submit",
        json={
            "decisions": {
                "source_genre": "prompt_pair_yaml",
                "authorship": "adam",
                "fictionality_status": "mixed",
                "truth_status": "adam_expert_reconstruction",
                "voice_presence": "charles_voice",
                "ready_for_processing": "yes",
                "privacy_level": "family_private",
                "usable_for_voice_context": "yes",
                "usable_for_grounded_generation": "yes",
                "generate_pairs_on_submit": "yes",
                "source_text": preview_text,
            }
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["creates_or_updates"]["generated_pair_count"] == 2
    run = body["creates_or_updates"]["pair_generation_run"]
    assert run["candidate_pair_count"] == 2
    assert run["created_pair_count"] == 2
    assert run["held_pair_count"] == 0
    assert run["evidence_linked_pair_count"] == 2
    assert run["missing_evidence_pair_count"] == 0
    assert run["source_section_count"] == 3
    assert run["held_source_section_count"] == 1
    assert run["held_source_sections"][0]["chunk_index"] == 3
    assert run["held_source_sections"][0]["reason"] == "no_prompt_pair_created_from_this_section"
    assert run["strategy_counts"] == {"structured_chunk_metadata": 2}
    assert body["creates_or_updates"]["receipt"]["pair_generation_run"]["held_source_section_count"] == 1

    with Session(engine) as session:
        tasks = session.exec(
            select(Task).where(Task.task_type == "gold_voice_edit").order_by(Task.created_at.asc())
        ).all()
        assert len(tasks) == 2
        assert tasks[0].input_payload["prompt"] == "How's Portland today?"
        assert tasks[0].input_payload["system_prompt"] == "You are Charles Rotmil."
        assert tasks[0].input_payload["content"] == (
            "gray here...\nlight rain\nkeeps the trees happy\nwent for a walk\nocean hiding behind fog"
        )
        assert tasks[0].input_payload["source_excerpt"].startswith("Example 1")
        assert len(tasks[0].input_payload["source_excerpt_sha256"]) == 64
        assert tasks[0].input_payload["source_evidence_status"] == "evidence_linked"
        assert tasks[0].input_payload["pair_generation_metadata"]["evidence_gate"]["passed"] is True
        assert tasks[0].input_payload["source_prompt_pair_example_index"] == 1
        assert tasks[1].input_payload["prompt"] == "Do you feel like getting coffee?"
        assert tasks[1].input_payload["content"] == "sure... yeah.\nCoffee Me Up down the street?\n\nlove\ndad"


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


def test_boundary_review_defaults_to_all_chunks_for_prompt_candidate():
    client, engine = build_client()

    with Session(engine) as session:
        asset = Asset(
            human_id="ASSET_BOUNDARY_DEFAULT_CHUNKS",
            asset_type="text",
            title="Reviewed draft",
            mime_type="text/plain",
        )
        session.add(asset)
        session.flush()
        preview = Segment(
            human_id="SEG_BOUNDARY_DEFAULT_PREVIEW",
            asset_id=asset.id,
            segment_type="text_preview",
            title="Reviewed draft preview",
            text_content="A reviewed source with two useful chunks.",
        )
        first_chunk = Segment(
            human_id="SEG_BOUNDARY_DEFAULT_CHUNK_1",
            asset_id=asset.id,
            segment_type="text_chunk",
            title="Reviewed draft chunk 1",
            text_content="The first useful chunk.",
            locator={"chunk_index": 1, "char_start": 0, "char_end": 23},
        )
        second_chunk = Segment(
            human_id="SEG_BOUNDARY_DEFAULT_CHUNK_2",
            asset_id=asset.id,
            segment_type="text_chunk",
            title="Reviewed draft chunk 2",
            text_content="The second useful chunk.",
            locator={"chunk_index": 2, "char_start": 24, "char_end": 48},
        )
        session.add(preview)
        session.add(first_chunk)
        session.add(second_chunk)
        session.flush()
        task = Task(
            human_id="TASK_BOUNDARY_DEFAULT_CHUNKS",
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
        first_chunk_id = first_chunk.id
        second_chunk_id = second_chunk.id

    response = client.post(
        f"/api/tasks/{task_id}/submit",
        json={
            "decisions": {
                "segment_boundary_status": "approved_chunks",
                "chunk_scope": "preview_only",
                "source_use_modes": ["verbatim_preferred", "grounded_synthesis_allowed"],
                "source_use_mode": "grounded_synthesis_allowed",
                "prompt_pair_decision": "yes",
                "prompt_pair_potential": "high",
                "quote_policy": "source_quote_allowed_after_boundary_review",
                "privacy_clearance": "ok_for_local_generation",
            },
            "notes": "Approve the reviewed chunk set.",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["creates_or_updates"]["reviewed_chunk_ids"] == [first_chunk_id, second_chunk_id]
    assert body["creates_or_updates"]["prompt_pair_candidate_task_id"]
    assert body["creates_or_updates"]["segment_boundary_review"]["chunk_scope"] == "all_chunks_defaulted"
    assert body["creates_or_updates"]["segment_boundary_review"]["chunk_selection_defaulted"] == "yes"

    with Session(engine) as session:
        candidate = session.get(Task, body["creates_or_updates"]["prompt_pair_candidate_task_id"])

        assert candidate is not None
        assert candidate.input_payload["selected_chunk_ids"] == [first_chunk_id, second_chunk_id]


def test_boundary_review_default_chunks_are_scoped_to_latest_extraction():
    client, engine = build_client()

    with Session(engine) as session:
        asset = Asset(
            human_id="ASSET_BOUNDARY_SCOPED_DEFAULT",
            asset_type="text",
            title="Reprocessed prompt pairs",
            mime_type="application/x-yaml",
        )
        session.add(asset)
        session.flush()
        preview = Segment(
            human_id="SEG_BOUNDARY_SCOPED_PREVIEW",
            asset_id=asset.id,
            segment_type="text_preview",
            title="Reprocessed prompt pairs preview",
            text_content="A reprocessed source with natural prompt-pair chunks.",
            locator={"text_extraction_derivative_id": "DERIV_NEW"},
            metadata_json={"text_extraction_derivative_id": "DERIV_NEW"},
        )
        old_chunk = Segment(
            human_id="SEG_BOUNDARY_SCOPED_OLD_CHUNK",
            asset_id=asset.id,
            segment_type="text_chunk",
            title="Old arbitrary chunk",
            text_content="Old chunk should not be selected.",
            locator={"chunk_index": 1, "char_start": 0, "char_end": 30},
        )
        new_chunk = Segment(
            human_id="SEG_BOUNDARY_SCOPED_NEW_CHUNK",
            asset_id=asset.id,
            segment_type="text_chunk",
            title="Example 1: Hi Dad",
            text_content="New prompt-pair chunk should be selected.",
            locator={"kind": "prompt_pair_example", "chunk_index": 1, "text_extraction_derivative_id": "DERIV_NEW"},
            metadata_json={"text_extraction_derivative_id": "DERIV_NEW"},
        )
        session.add(preview)
        session.add(old_chunk)
        session.add(new_chunk)
        session.flush()
        task = Task(
            human_id="TASK_BOUNDARY_SCOPED_DEFAULT_CHUNKS",
            task_type="text_segment_boundary_review",
            target_type="segment",
            target_id=preview.id,
            queue="text_segments_needing_boundary_review",
            input_payload={
                "asset_id": asset.id,
                "segment_id": preview.id,
                "text_extraction_derivative_id": "DERIV_NEW",
                "chunking_strategy": "prompt_pair_yaml",
                "source_filename": "charles_sft.yaml",
            },
            created_by="source_review",
        )
        session.add(task)
        session.commit()
        task_id = task.id
        new_chunk_id = new_chunk.id

    response = client.post(
        f"/api/tasks/{task_id}/submit",
        json={
            "decisions": {
                "segment_boundary_status": "approved_chunks",
                "chunk_scope": "preview_only",
                "source_use_modes": ["grounded_synthesis_allowed"],
                "source_use_mode": "grounded_synthesis_allowed",
                "prompt_pair_decision": "yes",
                "prompt_pair_potential": "high",
                "privacy_clearance": "ok_for_local_generation",
            },
            "notes": "Approve the latest extraction chunk set.",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["creates_or_updates"]["reviewed_chunk_ids"] == [new_chunk_id]


def test_boundary_review_marks_prompt_pair_quality_ranges():
    client, engine = build_client()

    with Session(engine) as session:
        asset = Asset(
            human_id="ASSET_BOUNDARY_QUALITY_RANGES",
            asset_type="text",
            title="Prompt pair corpus",
            mime_type="application/x-yaml",
        )
        session.add(asset)
        session.flush()
        preview = Segment(
            human_id="SEG_BOUNDARY_QUALITY_PREVIEW",
            asset_id=asset.id,
            segment_type="text_preview",
            title="Prompt pair corpus preview",
            text_content="Four prompt-pair examples.",
            metadata_json={"text_extraction_derivative_id": "DERIV_QUALITY"},
        )
        chunks = [
            Segment(
                human_id=f"SEG_BOUNDARY_QUALITY_CHUNK_{index}",
                asset_id=asset.id,
                segment_type="text_chunk",
                title=f"Example {index}",
                text_content=f"Example {index} text",
                locator={"kind": "prompt_pair_example", "chunk_index": index, "text_extraction_derivative_id": "DERIV_QUALITY"},
                metadata_json={"text_extraction_derivative_id": "DERIV_QUALITY"},
            )
            for index in range(1, 5)
        ]
        session.add(preview)
        for chunk in chunks:
            session.add(chunk)
        session.flush()
        task = Task(
            human_id="TASK_BOUNDARY_QUALITY_RANGES",
            task_type="text_segment_boundary_review",
            target_type="segment",
            target_id=preview.id,
            queue="text_segments_needing_boundary_review",
            input_payload={
                "asset_id": asset.id,
                "segment_id": preview.id,
                "text_extraction_derivative_id": "DERIV_QUALITY",
                "chunking_strategy": "prompt_pair_yaml",
                "source_filename": "charles_sft.yaml",
            },
            created_by="source_review",
        )
        session.add(task)
        session.commit()
        task_id = task.id
        chunk_ids = [chunk.id for chunk in chunks]

    response = client.post(
        f"/api/tasks/{task_id}/submit",
        json={
            "decisions": {
                "segment_boundary_status": "approved_chunks",
                "selected_chunk_ids": chunk_ids,
                "chunk_scope": "selected_chunks",
                "source_use_modes": ["grounded_synthesis_allowed"],
                "source_use_mode": "grounded_synthesis_allowed",
                "prompt_pair_decision": "yes",
                "prompt_pair_potential": "high",
                "privacy_clearance": "ok_for_local_generation",
                "chunk_quality_profile": "mixed_reference_and_synthetic_needs_edit",
                "ready_reference_chunk_range": "1-2",
                "needs_adam_edit_chunk_range": "3-4",
                "ready_reference_truth_status": "interpretive_synthesis",
                "needs_adam_edit_truth_status": "model_generated",
                "chunk_quality_notes": "Later examples are synthetic drafts and need Adam editing.",
            },
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["creates_or_updates"]["segment_boundary_review"]["pairing_ready_chunk_ids"] == chunk_ids[:2]
    assert body["creates_or_updates"]["segment_boundary_review"]["needs_adam_edit_chunk_ids"] == chunk_ids[2:]

    with Session(engine) as session:
        candidate = session.get(Task, body["creates_or_updates"]["prompt_pair_candidate_task_id"])
        ready_chunk = session.get(Segment, chunk_ids[0])
        edit_chunk = session.get(Segment, chunk_ids[2])

        assert candidate is not None
        assert candidate.input_payload["pairing_ready_chunk_ids"] == chunk_ids[:2]
        assert candidate.input_payload["needs_adam_edit_chunk_ids"] == chunk_ids[2:]
        assert candidate.input_payload["text_extraction_derivative_id"] == "DERIV_QUALITY"
        assert candidate.input_payload["chunking_strategy"] == "prompt_pair_yaml"
        assert candidate.input_payload["pairing_gate"] == "route_ready_chunks_only_hold_needs_edit"
        assert ready_chunk.metadata_json["chunk_quality_status"] == "pairing_ready_reference"
        assert ready_chunk.source_truth_status == "interpretive_synthesis"
        assert edit_chunk.metadata_json["chunk_quality_status"] == "needs_adam_edit"
        assert edit_chunk.metadata_json["pairing_gate"] == "requires_adam_edit_before_pairing"
        assert edit_chunk.source_truth_status == "model_generated"


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


def test_prompt_pair_candidate_submission_creates_natural_gold_edit_task():
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
                "conversation_family": "verbatim_email_reply",
                "system_prompt": "You are Charles Rotmil. Write naturally in his voice.",
                "boundary_clearance_needed": "review_before_export",
            },
            "notes": "Create a prompt pair draft.",
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
        assert review_task.input_payload["system_prompt"] == "You are Charles Rotmil. Write naturally in his voice."
        assert review_task.input_payload["prompt"] == "Write back about this memory."
        assert "Using the reviewed source material" not in review_task.input_payload["prompt"]
        assert "[stub draft" not in review_task.input_payload["model_draft"]
        assert review_task.input_payload["conversation_family"] == "verbatim_email_reply"
        assert review_task.input_payload["source_excerpt"].startswith("The cup is still")
        assert generation.model_name == "charlesops_scaffold_no_model_call"
        assert generation.model_parameters["no_live_model_call"] is True
        assert prompt.prompt_type == "grounded_prompt_pair"
        assert prompt.prompt_text == "Write back about this memory."
        assert prompt.metadata_json["system_prompt"] == "You are Charles Rotmil. Write naturally in his voice."
        assert prompt.metadata_json["conversation_family"] == "verbatim_email_reply"


def test_prompt_pair_candidate_submission_can_use_live_text_generation_gate(monkeypatch):
    client, engine = build_client()
    captured = {}

    def fake_generate_text_draft(request, *, no_live_model_call):
        captured["no_live_model_call"] = no_live_model_call
        captured["system_prompt"] = request.system_prompt
        captured["user_prompt"] = request.user_prompt
        captured["source_text"] = request.source_text
        return TextDraftResult(
            output_text="gray here...\nlight rain\nkeeps the trees happy",
            generation_status="live_model_call",
            model_name="gpt-5.5",
            model_parameters={
                "api": "responses",
                "reasoning": {"effort": "medium"},
                "no_live_model_call": False,
            },
        )

    monkeypatch.setattr("app.services.prompt_pairs.generate_text_draft", fake_generate_text_draft)

    with Session(engine) as session:
        asset = Asset(
            human_id="ASSET_PROMPT_PAIR_LIVE",
            asset_type="text",
            title="Portland today",
            mime_type="text/plain",
        )
        session.add(asset)
        session.flush()
        segment = Segment(
            human_id="SEG_PROMPT_PAIR_LIVE",
            asset_id=asset.id,
            segment_type="text_preview",
            title="Portland weather note",
            text_content="gray here. light rain. keeps the trees happy.",
        )
        ready_chunk = Segment(
            human_id="SEG_PROMPT_PAIR_LIVE_READY",
            asset_id=asset.id,
            segment_type="text_chunk",
            title="Ready chunk",
            text_content="ready reference chunk only",
            locator={"chunk_index": 1},
        )
        needs_edit_chunk = Segment(
            human_id="SEG_PROMPT_PAIR_LIVE_NEEDS_EDIT",
            asset_id=asset.id,
            segment_type="text_chunk",
            title="Needs edit chunk",
            text_content="synthetic chunk should wait",
            locator={"chunk_index": 2},
        )
        session.add(segment)
        session.add(ready_chunk)
        session.add(needs_edit_chunk)
        session.flush()
        task = Task(
            human_id="TASK_PROMPT_PAIR_LIVE",
            task_type="grounded_prompt_pair_candidate",
            target_type="segment",
            target_id=segment.id,
            queue="grounded_prompt_pairs_needing_drafts",
            input_payload={
                "segment_id": segment.id,
                "asset_id": asset.id,
                "selected_chunk_ids": [ready_chunk.id, needs_edit_chunk.id],
                "pairing_ready_chunk_ids": [ready_chunk.id],
                "needs_adam_edit_chunk_ids": [needs_edit_chunk.id],
                "chunk_quality_profile": "mixed_reference_and_synthetic_needs_edit",
                "pairing_gate": "route_ready_chunks_only_hold_needs_edit",
                "source_review_annotation_id": "ann_live_source_review",
            },
            required_decisions=["prompt_intent", "target_response_shape", "boundary_clearance_needed"],
            created_by="source_review",
        )
        session.add(task)
        session.commit()
        task_id = task.id

    response = client.post(
        f"/api/tasks/{task_id}/submit",
        json={
            "decisions": {
                "prompt_intent": "grounded_voice_response",
                "voice_mode": "father_to_adam",
                "truth_mode": "adam_expert_reconstruction",
                "conversation_family": "mundane_text_message",
                "target_response_shape": "short_voice_response",
                "prompt_text": "How's Portland today?",
                "no_live_model_call": False,
                "boundary_clearance_needed": "source_boundary_clear",
            },
        },
    )

    assert response.status_code == 200
    body = response.json()
    with Session(engine) as session:
        generation = session.get(Generation, body["creates_or_updates"]["generation_id"])
        review_task = session.get(Task, body["creates_or_updates"]["review_task_id"])
        assert captured["no_live_model_call"] is False
        assert captured["system_prompt"] == "You are Charles Rotmil."
        assert captured["user_prompt"] == "How's Portland today?"
        assert captured["source_text"] == "ready reference chunk only"
        assert generation.model_name == "gpt-5.5"
        assert generation.model_parameters["reasoning"]["effort"] == "medium"
        assert generation.model_parameters["no_live_model_call"] is False
        assert review_task.input_payload["prompt_pair_factory_no_model_call"] is False
        assert review_task.input_payload["prompt_pair_factory_generation_status"] == "live_model_call"
        assert review_task.input_payload["pairing_gate"] == "route_ready_chunks_only_hold_needs_edit"
