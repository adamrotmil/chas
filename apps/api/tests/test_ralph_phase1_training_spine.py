import hashlib
import json
import zipfile
import yaml
from pathlib import Path

from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select
from fastapi.testclient import TestClient

from app.config import Settings, get_settings
from app.db.session import get_session
from app.main import app
from app.models import Asset, Annotation, ContextPack, DPOPair, EmbeddingRecord, Generation, GoldVoiceExample, PromptSpec, SFTCandidate, Segment, SourceSpanAnnotation, Task
from app.services.pair_export import compile_pair_export
from app.services.pair_generation import preview_make_gold_tasks_from_review
from app.services.model_generation import TextDraftResult
from app.services.text_extraction import extract_text_from_file


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
    app.dependency_overrides[get_settings] = lambda: Settings(
        openai_api_key="",
        text_generation_live_calls_enabled=False,
        vision_live_calls_enabled=False,
    )
    return TestClient(app), engine


def _mixed_yaml_fixture() -> str:
    examples = []
    for index in range(1, 21):
        examples.append(
            {
                "voice_mode": "father_to_adam",
                "synthetic": True,
                "messages": [
                    {"role": "system", "content": "You are Charles Rotmil. Write naturally in his voice."},
                    {"role": "user", "content": f"Question {index}: How is Portland?"},
                    {
                        "role": "assistant",
                        "content": f"answer {index} line one\nanswer {index} line two\n\ndad",
                    },
                ],
            }
        )
    for index in range(1, 6):
        examples.append(
            {
                "voice_mode": "comic_observation",
                "synthetic": True,
                "system": "You are Charles Rotmil.",
                "prompt": f"DPO prompt {index}: How was the soup?",
                "chosen": f"soup {index} was thin...\ntasted like nothing\n\ndad",
                "rejected": f"The soup {index} was bland and unsatisfying.",
            }
        )
    return yaml.safe_dump(examples, allow_unicode=True, sort_keys=False)


def _write_docx_fixture(path: Path, paragraphs: list[str]) -> None:
    def paragraph_xml(text: str) -> str:
        return f"<w:p><w:r><w:t>{text}</w:t></w:r></w:p>"

    document_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        f"<w:body>{''.join(paragraph_xml(paragraph) for paragraph in paragraphs)}</w:body>"
        "</w:document>"
    )
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(
            "[Content_Types].xml",
            (
                '<?xml version="1.0" encoding="UTF-8"?>'
                '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                '<Default Extension="xml" ContentType="application/xml"/>'
                '<Override PartName="/word/document.xml" '
                'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
                "</Types>"
            ),
        )
        archive.writestr("word/document.xml", document_xml)


def test_model_status_exposes_gpt_55_medium_without_enabling_live_calls_or_fine_tuning():
    client, _engine = build_client()

    response = client.get("/api/model-status")

    assert response.status_code == 200
    body = response.json()
    assert body["text_generation_model"] == "gpt-5.5"
    assert body["text_generation_reasoning_effort"] == "medium"
    assert body["text_generation_live_calls_enabled"] is False
    assert body["text_generation_live_ready"] is False
    assert body["fine_tuning_enabled_in_mvp"] is False
    assert "openai_api_key" not in body
    requirements = body["credential_requirements"]
    assert requirements["requirements_type"] == "text_generation_credentials"
    assert requirements["api"] == "responses"
    assert requirements["model_name"] == "gpt-5.5"
    assert requirements["reasoning_effort"] == "medium"
    required_env = {item["name"]: item for item in requirements["required_env"]}
    assert required_env["OPENAI_API_KEY"]["configured"] is False
    assert required_env["OPENAI_API_KEY"]["secret"] is True
    assert required_env["TEXT_GENERATION_LIVE_CALLS_ENABLED"]["required_value"] == "true"
    assert requirements["env_file_policy"]["secret_env_files_ignored"] is True
    assert requirements["env_file_policy"]["ignored_patterns"] == [".env", ".env.*"]
    assert requirements["env_file_policy"]["tracked_template"] == ".env.example"
    assert requirements["env_file_policy"]["never_return_secret_values"] is True
    assert requirements["safety_policy"]["fine_tuning_api_calls_allowed"] is False


def test_demo_generation_readiness_lists_held_out_prompts_and_honest_credential_blocker():
    client, engine = build_client()
    with Session(engine) as session:
        for index in range(1, 7):
            session.add(
                Task(
                    human_id=f"TASK_DEMO_HELD_OUT_{index}",
                    task_type="gold_voice_edit",
                    target_type="prompt_pair",
                    target_id=f"prompt_pair_{index}",
                    queue="prompt_pairs_needing_gold_edits",
                    input_payload={
                        "artifact_mode": "sft",
                        "system_prompt": "You are Charles Rotmil.",
                        "prompt": f"Held out prompt {index}?",
                        "content": f"held out response {index}\n\ndad",
                        "voice_mode": "father_to_adam" if index < 4 else "memoir_scene",
                        "truth_status": "adam_expert_reconstruction",
                        "synthetic": True,
                        "source_title": "held-out fixture",
                    },
                    created_by="test",
                )
            )
        session.commit()

    response = client.get("/api/model-status/demo-readiness", params={"limit": 5})

    assert response.status_code == 200
    body = response.json()
    assert body["demo_type"] == "charles_voice_model_demo"
    assert body["status"] == "blocked_missing_credentials_or_live_gate"
    assert body["model_name"] == "gpt-5.5"
    assert body["reasoning_effort"] == "medium"
    assert body["can_generate"] is False
    assert body["blockers"] == ["text_generation_live_calls_disabled", "openai_api_key_missing"]
    assert body["safety_policy"] == {
        "outputs_truth_status": "model_generated",
        "adam_review_required": True,
        "never_training_truth_without_review": True,
        "fine_tuning_api_calls_allowed": False,
    }
    assert len(body["held_out_prompts"]) == 5
    assert [item["prompt"] for item in body["held_out_prompts"]] == [f"Held out prompt {index}?" for index in range(1, 6)]
    assert all(item["excluded_from_training_export"] is True for item in body["held_out_prompts"])
    assert all(item["prompt_sha256"] == hashlib.sha256(item["prompt"].encode("utf-8")).hexdigest() for item in body["held_out_prompts"])
    plan = body["generation_input_plan"]
    assert plan["api"] == "responses"
    assert plan["model_name"] == "gpt-5.5"
    assert plan["reasoning_effort"] == "medium"
    assert plan["credential_requirements"]["required_env"][0]["name"] == "OPENAI_API_KEY"
    assert plan["store"] is False
    assert plan["live_generation_ready"] is False
    assert plan["live_generation_blockers"] == body["blockers"]
    assert len(plan["reference_pack_content_sha256"]) == 64
    assert plan["reference_pack_sample_count"] >= 5
    assert len(plan["held_out_prompt_set_sha256"]) == 64
    assert plan["held_out_prompt_count"] == 5
    assert [item["prompt"] for item in plan["held_out_prompts"]] == [f"Held out prompt {index}?" for index in range(1, 6)]
    assert all(item["excluded_from_training_export"] is True for item in plan["held_out_prompts"])
    requirements = body["credential_requirements"]
    assert requirements["required_env"][0]["configured"] is False
    assert requirements["required_env"][1]["name"] == "TEXT_GENERATION_LIVE_CALLS_ENABLED"
    assert requirements["safety_policy"]["fine_tuning_api_calls_allowed"] is False

    with Session(engine) as session:
        assert session.exec(select(Generation)).all() == []


def test_demo_generation_request_preview_exposes_exact_no_live_payload_without_leaking_answers():
    client, engine = build_client()
    with Session(engine) as session:
        session.add(
            Task(
                human_id="TASK_DEMO_REQUEST_PREVIEW_SFT",
                task_type="gold_voice_edit",
                target_type="prompt_pair",
                target_id="prompt_pair_preview_sft",
                queue="prompt_pairs_needing_gold_edits",
                input_payload={
                    "artifact_mode": "sft",
                    "system_prompt": "You are Charles Rotmil.",
                    "prompt": "How was the light in Portland?",
                    "content": "HELD OUT ANSWER SHOULD NOT BE IN REQUEST",
                    "voice_mode": "photography_reflection",
                    "conversation_family": "father_to_adam",
                    "truth_status": "adam_expert_reconstruction",
                    "synthetic": True,
                    "source_title": "preview fixture",
                    "source_excerpt": "The harbor light was sharp and cold.",
                    "context": "Adam wants a model draft for later gold editing.",
                },
                created_by="test",
            )
        )
        session.add(
            Task(
                human_id="TASK_DEMO_REQUEST_PREVIEW_DPO",
                task_type="gold_voice_edit",
                target_type="prompt_pair",
                target_id="prompt_pair_preview_dpo",
                queue="prompt_pairs_needing_gold_edits",
                input_payload={
                    "artifact_mode": "dpo",
                    "system_prompt": "You are Charles Rotmil.",
                    "prompt": "How was the soup?",
                    "chosen": "CHOSEN HELD OUT ANSWER SHOULD NOT BE IN REQUEST",
                    "rejected": "REJECTED ANSWER SHOULD NOT BE IN REQUEST",
                    "voice_mode": "comic_observation",
                    "conversation_family": "verbatim_email_reply",
                    "truth_status": "adam_expert_reconstruction",
                    "synthetic": True,
                    "source_title": "soup fixture",
                    "source_excerpt": "The dinner had oily chicken soup.",
                    "context": "Use only as grounding, not as the answer.",
                },
                created_by="test",
            )
        )
        session.commit()

    response = client.get("/api/model-status/demo-generation-request-preview", params={"limit": 2})

    assert response.status_code == 200
    body = response.json()
    assert body["preview_type"] == "charles_voice_model_demo_generation_request_preview"
    assert body["review_policy"] == "dry_run_only_no_live_model_call_no_generation_created"
    assert body["does_not_mutate_state"] is True
    assert body["no_live_model_call"] is True
    assert body["no_generation_created"] is True
    assert body["does_not_promote_to_training_export"] is True
    assert body["api"] == "responses"
    assert body["model_name"] == "gpt-5.5"
    assert body["reasoning_effort"] == "medium"
    assert body["store"] is False
    assert body["request_count"] == 2
    assert len(body["content_sha256"]) == 64
    assert hashlib.sha256(body["export_preview_yaml"].encode("utf-8")).hexdigest() == body["export_preview_sha256"]
    assert body["export_preview_yaml"].startswith("demo_generation_request_preview:")
    assert "request_body_json: |-" in body["export_preview_yaml"]
    assert "HELD OUT ANSWER SHOULD NOT BE IN REQUEST" not in body["export_preview_yaml"]
    assert "REJECTED ANSWER SHOULD NOT BE IN REQUEST" not in body["export_preview_yaml"]

    first = body["requests"][0]
    first_request_body = first["request_body"]
    assert first_request_body["model"] == "gpt-5.5"
    assert first_request_body["reasoning"] == {"effort": "medium"}
    assert first_request_body["store"] is False
    assert first_request_body["max_output_tokens"] == 1800
    assert [message["role"] for message in first_request_body["input"]] == ["developer", "user"]
    assert "How was the light in Portland?" in first_request_body["input"][1]["content"]
    assert "The harbor light was sharp and cold." in first_request_body["input"][1]["content"]
    assert "HELD OUT ANSWER SHOULD NOT BE IN REQUEST" not in first["request_body_json"]
    assert first["safety_checks"]["held_out_answer_excluded_from_request"] is True
    assert first["safety_checks"]["no_live_model_call"] is True
    assert first["safety_checks"]["store_false"] is True
    compact_request_body = json.dumps(first_request_body, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    assert hashlib.sha256(compact_request_body.encode("utf-8")).hexdigest() == first["request_body_sha256"]
    assert "_held_out_response_text" not in first

    second = body["requests"][1]
    assert second["artifact_mode"] == "dpo"
    assert second["safety_checks"]["held_out_answer_excluded_from_request"] is True
    assert second["safety_checks"]["rejected_response_excluded_from_request"] is True
    assert "CHOSEN HELD OUT ANSWER SHOULD NOT BE IN REQUEST" not in second["request_body_json"]
    assert "REJECTED ANSWER SHOULD NOT BE IN REQUEST" not in second["request_body_json"]

    yaml_response = client.get("/api/model-status/demo-generation-request-preview/yaml", params={"limit": 2})
    assert yaml_response.status_code == 200
    assert yaml_response.headers["content-type"].startswith("text/yaml")
    assert yaml_response.text == body["export_preview_yaml"]

    contract = client.get("/api/runtime-contract").json()
    assert "/api/model-status/demo-generation-request-preview" in contract["required_response_fields"]

    with Session(engine) as session:
        assert session.exec(select(Generation)).all() == []
        assert session.exec(select(PromptSpec)).all() == []
        assert session.exec(select(ContextPack)).all() == []
        assert session.exec(select(GoldVoiceExample)).all() == []


def test_demo_generation_endpoint_stores_model_generated_outputs_without_training_truth(monkeypatch):
    client, engine = build_client()
    captured = {}

    def fake_generate_text_draft(request, *, no_live_model_call, app_settings):
        captured.setdefault("requests", []).append(
            {
                "no_live_model_call": no_live_model_call,
                "model": app_settings.text_generation_model,
                "reasoning": app_settings.text_generation_reasoning_effort,
                "prompt": request.user_prompt,
                "source_text": request.source_text,
                "reference_count": len(request.reference_examples),
            }
        )
        return TextDraftResult(
            output_text=f"demo response for {request.user_prompt}\n\nlove\ndad",
            generation_status="live_model_call",
            model_name=app_settings.text_generation_model,
            model_parameters={
                "api": "responses",
                "reasoning": {"effort": app_settings.text_generation_reasoning_effort},
                "no_live_model_call": False,
            },
        )

    monkeypatch.setattr("app.routers.model_status.generate_text_draft", fake_generate_text_draft)
    app.dependency_overrides[get_settings] = lambda: Settings(
        openai_api_key="sk-test",
        text_generation_live_calls_enabled=True,
    )

    with Session(engine) as session:
        for index in range(1, 7):
            session.add(
                Task(
                    human_id=f"TASK_DEMO_LIVE_{index}",
                    task_type="gold_voice_edit",
                    target_type="prompt_pair",
                    target_id=f"prompt_pair_live_{index}",
                    queue="prompt_pairs_needing_gold_edits",
                    input_payload={
                        "artifact_mode": "sft",
                        "system_prompt": "You are Charles Rotmil.",
                        "prompt": f"Held out live prompt {index}?",
                        "content": f"HELD OUT ANSWER {index} SHOULD NOT BE SENT AS SOURCE",
                        "voice_mode": "father_to_adam",
                        "conversation_family": "mundane_text_message",
                        "truth_status": "adam_expert_reconstruction",
                        "synthetic": True,
                        "source_title": "held-out live fixture",
                        "source_excerpt": f"source detail {index}",
                        "context": f"context detail {index}",
                    },
                    created_by="test",
                )
            )
        session.commit()

    try:
        response = client.post("/api/model-status/demo-generations", json={"limit": 2})
    finally:
        app.dependency_overrides.pop(get_settings, None)

    assert response.status_code == 200
    body = response.json()
    assert body["demo_type"] == "charles_voice_model_demo_generation_batch"
    assert body["status"] == "created_model_generated_demo_outputs"
    assert body["created_count"] == 2
    assert body["credential_requirements"]["required_env"][0]["configured"] is True
    assert body["credential_requirements"]["required_env"][1]["configured"] is True
    assert body["safety_policy"]["outputs_truth_status"] == "model_generated"
    assert body["safety_policy"]["never_training_truth_without_review"] is True
    assert len(captured["requests"]) == 2
    assert all(item["no_live_model_call"] is False for item in captured["requests"])
    assert all(item["model"] == "gpt-5.5" for item in captured["requests"])
    assert all(item["reasoning"] == "medium" for item in captured["requests"])
    assert all("HELD OUT ANSWER" not in item["source_text"] for item in captured["requests"])

    with Session(engine) as session:
        generations = session.exec(select(Generation)).all()
        prompt_specs = session.exec(select(PromptSpec)).all()
        context_packs = session.exec(select(ContextPack)).all()
        assert len(generations) == 2
        assert len(prompt_specs) == 2
        assert len(context_packs) == 2
        assert all(prompt.truth_mode == "model_generated" for prompt in prompt_specs)
        assert all(prompt.prompt_type == "charles_voice_demo_generation" for prompt in prompt_specs)
        assert all(context.truth_mode == "model_generated" for context in context_packs)
        assert all(context.boundaries_snapshot["excluded_from_training_export"] is True for context in context_packs)
        assert all(generation.model_name == "gpt-5.5" for generation in generations)
        assert all(generation.model_parameters["truth_status"] == "model_generated" for generation in generations)
        assert all(generation.model_parameters["adam_review_required"] is True for generation in generations)
        assert all(generation.model_parameters["excluded_from_training_export"] is True for generation in generations)
        assert session.exec(select(GoldVoiceExample)).all() == []
        assert session.exec(select(SFTCandidate)).all() == []
        assert session.exec(select(DPOPair)).all() == []


def test_plain_text_extraction_prefers_natural_sections_over_single_arbitrary_chunk(tmp_path: Path):
    sections = [
        "Email 1:\nHi Tom\nHow the hell are you?\nNo word in a while.\nCharles",
        "Memoir 1:\nWinter in Maine.\nOld Orchard. Waves a mile high.\nThe car held up. Miracle.",
        "Note 1:\nAirport is about 15 minutes from my house.\nWe can decide then what to do.",
        "Fragment 1:\nThe light first. always the light.\nWet sand, silver, almost liquid.",
        "Email 2:\nSure I will make madeleines I told them.\nI need to revise that interview.",
        "Memoir 2:\nPhiladelphia. the distillery.\nThe machines grinding. The bosses not caring.",
        "Note 2:\nChess over by two days.\nHurry and move!",
        "Note 3:\nchess?",
    ]
    source = "\n\n".join(sections)
    path = tmp_path / "mixed_notes.txt"
    path.write_text(source)

    result = extract_text_from_file(path, filename="mixed_notes.txt", content_type="text/plain", asset_type="document")

    assert result.status == "extracted"
    assert result.parser == "plain_text"
    assert result.metadata["chunking_strategy"] == "natural_section"
    assert result.metadata["structured_chunk_count"] == 8
    assert len(result.structured_chunks) == 8
    previous_end = -1
    for index, chunk in enumerate(result.structured_chunks, start=1):
        assert chunk.locator["kind"] == "natural_section"
        assert chunk.locator["chunk_index"] == index
        assert chunk.locator["char_start"] == result.text.index(sections[index - 1])
        assert result.text[chunk.locator["char_start"] : chunk.locator["char_end"]] == chunk.text
        assert chunk.text == sections[index - 1]
        assert chunk.text[:40] == sections[index - 1][:40]
        assert chunk.text[-40:] == sections[index - 1][-40:]
        assert chunk.locator["char_start"] > previous_end
        previous_end = chunk.locator["char_end"]
        assert chunk.metadata["chunking_strategy"] == "natural_section"
        assert chunk.metadata["natural_boundary"] is True

    assert "Memoir 1:" not in result.structured_chunks[0].text
    assert result.structured_chunks[-1].metadata["section_review_hint"] == "needs_context"


def test_docx_extraction_uses_natural_sections_with_exact_locators(tmp_path: Path):
    paragraphs = [
        "Email 1:",
        "Hi Tom. How the hell are you? No word in a while.",
        "I sent the story treatment and I am waiting to hear. Charles.",
        "Memoir 1:",
        "Winter in Maine. Old Orchard. Waves a mile high.",
        "The car held up. Miracle. Another survival episode.",
        "Note 1:",
        "Airport is about 15 minutes from my house.",
        "We can decide then what to do when he gets here.",
    ]
    path = tmp_path / "charles_sections.docx"
    _write_docx_fixture(path, paragraphs)

    result = extract_text_from_file(
        path,
        filename="charles_sections.docx",
        content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        asset_type="document",
    )

    expected_sections = [
        "\n\n".join(paragraphs[0:3]),
        "\n\n".join(paragraphs[3:6]),
        "\n\n".join(paragraphs[6:9]),
    ]
    assert result.status == "extracted"
    assert result.parser == "docx"
    assert result.metadata["chunking_strategy"] == "natural_section"
    assert result.metadata["structured_chunk_count"] == 3
    assert [chunk.text for chunk in result.structured_chunks] == expected_sections
    for index, chunk in enumerate(result.structured_chunks, start=1):
        expected = expected_sections[index - 1]
        assert chunk.locator["kind"] == "natural_section"
        assert chunk.locator["chunk_index"] == index
        assert result.text[chunk.locator["char_start"] : chunk.locator["char_end"]] == expected
        assert chunk.metadata["natural_boundary"] is True
        assert chunk.metadata["section_review_hint"] == "complete_thought"
    assert "Memoir 1:" not in result.structured_chunks[0].text
    assert "Note 1:" not in result.structured_chunks[1].text


def test_eml_extraction_uses_body_natural_sections_not_headers(tmp_path: Path):
    body_sections = [
        (
            "Email 1:\n"
            "Hi Adam\n"
            "The house is too quiet now after your visit.\n"
            "I keep looking around like something is still moving.\n"
            "Charles"
        ),
        (
            "Email 2:\n"
            "Hi Dad\n"
            "I made it home and the train was almost on time.\n"
            "The visit stayed with me the whole way back.\n"
            "Adam"
        ),
    ]
    source_email = (
        b"From: Charles <charles@example.com>\n"
        b"To: Adam <adam@example.com>\n"
        b"Subject: Re: visit\n"
        b"Date: Thu, 2 Apr 2026 10:00:00 -0400\n"
        b"Content-Type: text/plain; charset=utf-8\n"
        b"\n"
        + "\n\n".join(body_sections).encode("utf-8")
    )
    path = tmp_path / "thread.eml"
    path.write_bytes(source_email)

    result = extract_text_from_file(path, filename="thread.eml", content_type="message/rfc822", asset_type="document")

    assert result.status == "extracted"
    assert result.parser == "eml"
    assert result.metadata["email_headers"]["subject"] == "Re: visit"
    assert result.metadata["chunking_strategy"] == "natural_section"
    assert result.metadata["structured_chunk_count"] == 2
    assert [chunk.text for chunk in result.structured_chunks] == body_sections
    assert "Subject: Re: visit" in result.text
    assert all("Subject: Re: visit" not in chunk.text for chunk in result.structured_chunks)
    previous_end = result.text.index(body_sections[0]) - 1
    for index, chunk in enumerate(result.structured_chunks, start=1):
        expected = body_sections[index - 1]
        assert chunk.locator["kind"] == "natural_section"
        assert chunk.locator["chunk_index"] == index
        assert chunk.locator["char_start"] == result.text.index(expected)
        assert result.text[chunk.locator["char_start"] : chunk.locator["char_end"]] == expected
        assert chunk.locator["char_start"] > previous_end
        previous_end = chunk.locator["char_end"]
        assert chunk.metadata["natural_boundary"] is True
        assert chunk.metadata["section_review_hint"] == "complete_thought"


def test_source_review_generate_pairs_from_natural_sections_creates_singleton_prompt_pair_tasks():
    client, engine = build_client()
    sections = [
        "Email 1:\nHi Tom\nHow the hell are you?\nNo word in a while.\nCharles",
        "Memoir 1:\nWinter in Maine.\nOld Orchard. Waves a mile high.\nThe car held up. Miracle.",
        "Note 1:\nchess?",
    ]
    source_text = "\n\n".join(sections)

    with Session(engine) as session:
        asset = Asset(
            human_id="ASSET_NATURAL_SECTIONS",
            asset_type="text",
            title="mixed_notes.txt",
            original_filename="mixed_notes.txt",
            mime_type="text/plain",
        )
        session.add(asset)
        session.flush()
        preview = Segment(
            human_id="SEG_NATURAL_SECTIONS_PREVIEW",
            asset_id=asset.id,
            segment_type="text_preview",
            title="mixed_notes.txt preview",
            text_content=source_text,
            metadata_json={"chunking_strategy": "natural_section", "chunk_count": len(sections)},
        )
        session.add(preview)
        session.flush()
        chunks = []
        cursor = 0
        for index, section in enumerate(sections, start=1):
            start = source_text.index(section, cursor)
            end = start + len(section)
            cursor = end
            chunks.append(
                Segment(
                    human_id=f"SEG_NATURAL_SECTION_{index:03d}",
                    asset_id=asset.id,
                    segment_type="text_chunk",
                    title=section.split("\n", 1)[0].rstrip(":"),
                    text_content=section,
                    locator={"kind": "natural_section", "chunk_index": index, "char_start": start, "char_end": end},
                    metadata_json={
                        "chunking_strategy": "natural_section",
                        "natural_boundary": True,
                        "chunk_index": index,
                        "section_review_hint": "needs_context" if index == 3 else "complete_thought",
                    },
                )
            )
        session.add_all(chunks)
        session.flush()
        task = Task(
            human_id="TASK_NATURAL_SECTION_REVIEW",
            task_type="text_segment_review",
            target_type="segment",
            target_id=preview.id,
            queue="text_segments_needing_review",
            input_payload={
                "asset_id": asset.id,
                "source_filename": "mixed_notes.txt",
                "preview_text": source_text,
                "chunk_count": len(sections),
                "chunking_strategy": "natural_section",
            },
            created_by="text_extraction",
        )
        session.add(task)
        session.add(
            EmbeddingRecord(
                id="embedding-reviewed-context-001",
                target_type="gold_voice",
                target_id="gold-reviewed-context-001",
                embedding_type="gold_voice_text",
                modality="text",
                model_name="text-embedding-3-small",
                input_checksum="reviewed-context-checksum",
                input_text="Reviewed Charles voice evidence about writing to Tom with no word in a while.",
                input_preview="Reviewed Charles voice evidence about writing to Tom.",
                status="embedded",
                vector_uri="local://embedding_vectors/reviewed-context-001.json",
                vector_dims=3,
                truth_status="adam_expert_reconstruction",
                metadata_json={"source": "gold_voice_edit"},
            )
        )
        session.commit()
        task_id = task.id
        chunk_ids = [chunk.id for chunk in chunks]

    response = client.post(
        f"/api/tasks/{task_id}/submit",
        json={
            "decisions": {
                "source_genre": "notes",
                "authorship": "charles",
                "truth_status": "archival_source",
                "voice_presence": "charles_voice",
                "ready_for_processing": "yes",
                "privacy_level": "family_private",
                "usable_for_voice_context": "yes",
                "usable_for_grounded_generation": "yes",
                "generate_pairs_on_submit": "yes",
                "voice_mode": "father_to_adam",
                "synthetic": True,
                "context": "Natural-section fixture.",
            }
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["creates_or_updates"]["generated_pair_count"] == 3
    run = body["creates_or_updates"]["pair_generation_run"]
    receipt_run = body["creates_or_updates"]["receipt"]["pair_generation_run"]
    assert run["run_type"] == "source_review_generate_pairs"
    assert run["created_pair_count"] == 3
    assert run["held_pair_count"] == 0
    assert run["held_source_section_count"] == 0
    assert run["source_section_count"] == 3
    assert run["strategy_counts"] == {"natural_section": 3}
    assert run["next_queue"] == "prompt_pairs_needing_gold_edits"
    assert receipt_run["created_pair_count"] == 3

    with Session(engine) as session:
        tasks = session.exec(
            select(Task).where(Task.task_type == "gold_voice_edit").order_by(Task.created_at.asc())
        ).all()
        assert len(tasks) == 3
        assert [task.input_payload["source_segment_id"] for task in tasks] == chunk_ids
        assert [task.input_payload["source_chunk_index"] for task in tasks] == [1, 2, 3]
        assert tasks[0].input_payload["prompt"] == "What were you writing to Tom about?"
        assert tasks[0].input_payload["content"] == "Hi Tom\nHow the hell are you?\nNo word in a while.\nCharles"
        assert tasks[1].input_payload["prompt"] == "Tell me about Winter in Maine."
        assert tasks[1].input_payload["content"].startswith("Winter in Maine.")
        assert tasks[2].input_payload["prompt"] == "chess?"
        assert tasks[2].input_payload["content"] == "chess?"
        assert "Tell me about mixed_notes.txt" not in "\n".join(task.input_payload["prompt"] for task in tasks)
        assert "section_review_hint: needs_context" in tasks[2].input_payload["context"]
        assert tasks[0].input_payload["source_excerpt"] == sections[0]


def test_natural_section_generation_holds_split_sections_and_blocks_contextless_export():
    client, engine = build_client()
    sections = [
        "Email 1:\nHi Tom\nHow the hell are you?\nNo word in a while.\nCharles",
        "Memoir 1:\nWinter in Maine.\n" + "\n".join(f"Scene line {index}." for index in range(1, 12)),
        "Note 1:\nchess?",
    ]
    source_text = "\n\n".join(sections)

    with Session(engine) as session:
        asset = Asset(
            human_id="ASSET_NATURAL_SECTION_GATES",
            asset_type="text",
            title="natural section gates.txt",
            original_filename="natural_section_gates.txt",
            mime_type="text/plain",
        )
        session.add(asset)
        session.flush()
        preview = Segment(
            human_id="SEG_NATURAL_SECTION_GATES_PREVIEW",
            asset_id=asset.id,
            segment_type="text_preview",
            title="Natural section gates preview",
            text_content=source_text,
            metadata_json={"chunking_strategy": "natural_section", "chunk_count": len(sections)},
        )
        session.add(preview)
        session.flush()
        chunks = []
        cursor = 0
        hints = ["complete_thought", "needs_split", "needs_context"]
        for index, section in enumerate(sections, start=1):
            start = source_text.index(section, cursor)
            end = start + len(section)
            cursor = end
            chunks.append(
                Segment(
                    human_id=f"SEG_NATURAL_SECTION_GATE_{index:03d}",
                    asset_id=asset.id,
                    segment_type="text_chunk",
                    title=section.split("\n", 1)[0].rstrip(":"),
                    text_content=section,
                    locator={"kind": "natural_section", "chunk_index": index, "char_start": start, "char_end": end},
                    metadata_json={
                        "chunking_strategy": "natural_section",
                        "natural_boundary": True,
                        "chunk_index": index,
                        "section_review_hint": hints[index - 1],
                    },
                )
            )
        session.add_all(chunks)
        session.flush()
        task = Task(
            human_id="TASK_NATURAL_SECTION_GATES_REVIEW",
            task_type="text_segment_review",
            target_type="segment",
            target_id=preview.id,
            queue="text_segments_needing_review",
            input_payload={
                "asset_id": asset.id,
                "source_filename": "natural_section_gates.txt",
                "preview_text": source_text,
                "chunk_count": len(sections),
                "chunking_strategy": "natural_section",
            },
            created_by="text_extraction",
        )
        session.add(task)
        session.add(
            EmbeddingRecord(
                id="embedding-reviewed-context-001",
                target_type="gold_voice",
                target_id="gold-reviewed-context-001",
                embedding_type="gold_voice_text",
                modality="text",
                model_name="text-embedding-3-small",
                input_checksum="reviewed-context-preview-checksum",
                input_text="Reviewed Charles voice evidence about writing to Tom with no word in a while.",
                input_preview="Reviewed Charles voice evidence about writing to Tom.",
                status="embedded",
                vector_uri="local://embedding_vectors/reviewed-context-001.json",
                vector_dims=3,
                truth_status="adam_expert_reconstruction",
                metadata_json={"source": "gold_voice_edit"},
            )
        )
        session.commit()
        task_id = task.id

    response = client.post(
        f"/api/tasks/{task_id}/submit",
        json={
            "decisions": {
                "source_review_status": "reviewed",
                "generate_pairs_on_submit": "yes",
                "voice_mode": "father_to_adam",
                "synthetic": True,
                "context": "Natural section gates fixture.",
            }
        },
    )

    assert response.status_code == 200
    body = response.json()
    run = body["creates_or_updates"]["pair_generation_run"]
    assert body["creates_or_updates"]["generated_pair_count"] == 2
    assert run["candidate_pair_count"] == 2
    assert run["created_pair_count"] == 2
    assert run["source_section_count"] == 3
    assert run["held_source_section_count"] == 1
    assert run["held_source_sections"][0]["chunk_index"] == 2
    assert run["held_source_sections"][0]["section_review_hint"] == "needs_split"
    assert run["held_source_sections"][0]["reason"] == "source_section_needs_split"

    with Session(engine) as session:
        tickets = session.exec(
            select(Task).where(Task.task_type == "gold_voice_edit").order_by(Task.created_at.asc())
        ).all()
        assert len(tickets) == 2
        assert [ticket.input_payload["source_chunk_index"] for ticket in tickets] == [1, 3]
        contextless_payload = tickets[1].input_payload
        assert contextless_payload["source_section_review_hint"] == "needs_context"
        assert contextless_payload["pair_generation_metadata"]["source_section_review_hint"] == "needs_context"
        contextless_task_id = tickets[1].id

    clean_rubric = {
        "response_b": {
            "privacy_export_safety": {"status": "no_issues", "notes": "", "issue_tags": []},
            "voice_authenticity": {"status": "no_issues", "notes": "", "issue_tags": []},
            "grounding_truth": {"status": "no_issues", "notes": "", "issue_tags": []},
            "restraint": {"status": "no_issues", "notes": "", "issue_tags": []},
            "concrete_detail": {"status": "no_issues", "notes": "", "issue_tags": []},
            "prompt_fit": {"status": "no_issues", "notes": "", "issue_tags": []},
        }
    }
    blocked_submit = client.post(
        f"/api/tasks/{contextless_task_id}/submit",
        json={
            "decisions": {
                **contextless_payload,
                "response_rubric": clean_rubric,
                "rubric_summary": {"sft_ready": True},
            }
        },
    )
    assert blocked_submit.status_code == 200

    with Session(engine) as session:
        sft = session.exec(select(SFTCandidate)).one()
        assert sft.export_status == "candidate"
        assert sft.quality_gate["export_ready"] is False
        assert "source_section_needs_context" in sft.quality_gate["export_blockers"]


def test_source_review_pair_generation_preview_is_non_mutating_and_matches_natural_sections():
    client, engine = build_client()
    sections = [
        "Email 1:\nHi Tom\nHow the hell are you?\nNo word in a while.\nCharles",
        "Memoir 1:\nWinter in Maine.\nOld Orchard. Waves a mile high.\nThe car held up. Miracle.",
        "Note 1:\nchess?",
    ]
    source_text = "\n\n".join(sections)

    with Session(engine) as session:
        asset = Asset(
            human_id="ASSET_NATURAL_SECTIONS_PREVIEW_ONLY",
            asset_type="text",
            title="mixed_notes_preview.txt",
            original_filename="mixed_notes_preview.txt",
            mime_type="text/plain",
        )
        session.add(asset)
        session.flush()
        preview = Segment(
            human_id="SEG_NATURAL_SECTIONS_PREVIEW_ONLY",
            asset_id=asset.id,
            segment_type="text_preview",
            title="mixed_notes_preview.txt preview",
            text_content=source_text,
            metadata_json={"chunking_strategy": "natural_section", "chunk_count": len(sections)},
        )
        session.add(preview)
        session.flush()
        chunks = []
        cursor = 0
        for index, section in enumerate(sections, start=1):
            start = source_text.index(section, cursor)
            end = start + len(section)
            cursor = end
            chunks.append(
                Segment(
                    human_id=f"SEG_NATURAL_SECTION_PREVIEW_ONLY_{index:03d}",
                    asset_id=asset.id,
                    segment_type="text_chunk",
                    title=section.split("\n", 1)[0].rstrip(":"),
                    text_content=section,
                    locator={"kind": "natural_section", "chunk_index": index, "char_start": start, "char_end": end},
                    metadata_json={
                        "chunking_strategy": "natural_section",
                        "natural_boundary": True,
                        "chunk_index": index,
                    },
                )
            )
        session.add_all(chunks)
        session.flush()
        task = Task(
            human_id="TASK_NATURAL_SECTION_PREVIEW_ONLY",
            task_type="text_segment_review",
            target_type="segment",
            target_id=preview.id,
            queue="text_segments_needing_review",
            input_payload={
                "asset_id": asset.id,
                "source_filename": "mixed_notes_preview.txt",
                "preview_text": source_text,
                "chunk_count": len(sections),
                "chunking_strategy": "natural_section",
            },
            created_by="text_extraction",
        )
        session.add(task)
        session.add(
            EmbeddingRecord(
                id="embedding-reviewed-context-001",
                target_type="gold_voice",
                target_id="gold-reviewed-context-001",
                embedding_type="gold_voice_text",
                modality="text",
                model_name="text-embedding-3-small",
                input_checksum="reviewed-context-preview-only-checksum",
                input_text="Reviewed Charles voice evidence about writing to Tom with no word in a while.",
                input_preview="Reviewed Charles voice evidence about writing to Tom.",
                status="embedded",
                vector_uri="local://embedding_vectors/reviewed-context-001.json",
                vector_dims=3,
                truth_status="adam_expert_reconstruction",
                metadata_json={"source": "gold_voice_edit"},
                boundary_snapshot={
                    "privacy_level": "family_private",
                    "searchable": True,
                    "retrievable_in_chat": True,
                    "reviewed_by": "adam",
                },
            )
        )
        session.commit()
        task_id = task.id

    preview_response = client.post(
        f"/api/tasks/{task_id}/pair-generation/preview",
        json={
            "decisions": {
                "source_genre": "notes",
                "authorship": "charles",
                "truth_status": "archival_source",
                "voice_presence": "charles_voice",
                "generate_pairs_on_submit": "yes",
                "voice_mode": "father_to_adam",
                "synthetic": True,
                "context": "Non-mutating preview fixture.",
                "source_spans": [
                    {
                        "start_char": 0,
                        "end_char": 7,
                        "text": "Email 1",
                        "span_type": "context",
                        "speaker": "Adam",
                        "code": "fixture_note",
                    }
                ],
                "supplemental_evidence_record_ids": ["embedding-reviewed-context-001"],
            }
        },
    )

    assert preview_response.status_code == 200
    body = preview_response.json()
    assert body["preview_type"] == "source_review_generate_pairs_preview"
    assert body["does_not_mutate_state"] is True
    assert body["no_live_model_call"] is True
    assert body["projected_created_pair_count"] == 3
    assert body["projected_held_pair_count"] == 0
    assert body["source_section_count"] == 3
    assert body["source_spans_supplied"] is True
    assert body["source_span_draft_count"] == 1
    assert body["ranked_evidence_record_count"] == 1
    assert body["ranked_evidence_vector_query_used"] is False
    assert body["ranked_evidence_packet"]["records"][0]["embedding_record_id"] == "embedding-reviewed-context-001"
    assert body["strategy_counts"] == {"natural_section": 3}
    assert body["primary_strategy_label"] == "Natural source sections"
    assert body["next_queue"] == "prompt_pairs_needing_gold_edits"
    assert body["completion_signal"] == "generate_pairs_creates_singleton_prompt_pair_tickets"
    assert len(body["content_sha256"]) == 64
    assert body["created_pairs_preview"][0]["prompt_preview"] == "What were you writing to Tom about?"
    assert {
        "type": "evidence_corpus_record",
        "embedding_record_id": "embedding-reviewed-context-001",
    } in body["created_pairs_preview"][0]["source_evidence_refs"]
    assert any(
        ref.get("type") == "retrieval_ranked_evidence_record"
        and ref.get("embedding_record_id") == "embedding-reviewed-context-001"
        for ref in body["created_pairs_preview"][0]["source_evidence_refs"]
    )
    assert body["created_pairs_preview"][1]["source_chunk_index"] == 2

    with Session(engine) as session:
        assert len(session.exec(select(Task)).all()) == 1
        assert session.exec(select(PromptSpec)).all() == []
        assert session.exec(select(ContextPack)).all() == []
        assert session.exec(select(Generation)).all() == []
        assert session.exec(select(Annotation)).all() == []


def test_source_review_pair_generation_can_use_vector_ranked_evidence_packet(monkeypatch, tmp_path):
    _client, engine = build_client()

    monkeypatch.setattr("app.services.retrieval.embed_query_text", lambda **kwargs: [0.1, 0.2, 0.3])
    monkeypatch.setattr("app.services.retrieval.load_embedding_vector", lambda record, app_settings: [0.1, 0.2, 0.3])

    source_text = "Memoir 1:\nWinter in Maine. Old Orchard. Waves a mile high."
    with Session(engine) as session:
        asset = Asset(
            human_id="ASSET_VECTOR_RANKED_SOURCE",
            asset_type="text",
            title="old_orchard_notes.txt",
            original_filename="old_orchard_notes.txt",
            mime_type="text/plain",
        )
        session.add(asset)
        session.flush()
        segment = Segment(
            human_id="SEG_VECTOR_RANKED_SOURCE",
            asset_id=asset.id,
            segment_type="text_chunk",
            title="Old Orchard note",
            text_content=source_text,
            locator={"kind": "natural_section", "chunk_index": 1},
            metadata_json={"chunking_strategy": "natural_section", "chunk_index": 1},
        )
        session.add(segment)
        session.flush()
        task = Task(
            human_id="TASK_VECTOR_RANKED_SOURCE",
            task_type="text_segment_review",
            target_type="segment",
            target_id=segment.id,
            queue="text_segments_needing_review",
            input_payload={
                "asset_id": asset.id,
                "source_filename": "old_orchard_notes.txt",
                "preview_text": source_text,
            },
            created_by="test",
        )
        session.add(task)
        session.add(
            EmbeddingRecord(
                id="embedding-old-orchard-reviewed",
                target_type="memory",
                target_id="memory-old-orchard-reviewed",
                embedding_type="memory_text",
                modality="text",
                model_name="text-embedding-3-small",
                input_checksum="old-orchard-reviewed-checksum",
                input_text="Reviewed memory context about Old Orchard waves and winter in Maine.",
                input_preview="Reviewed memory context about Old Orchard waves.",
                status="embedded",
                vector_uri=str(tmp_path / "old-orchard.json"),
                vector_dims=3,
                truth_status="adam_memory",
                metadata_json={"source": "photo_memory_review"},
                boundary_snapshot={
                    "privacy_level": "family_private",
                    "searchable": True,
                    "retrievable_in_chat": True,
                    "reviewed_by": "adam",
                },
            )
        )
        session.commit()

        body = preview_make_gold_tasks_from_review(
            session=session,
            task=task,
            decisions={
                "generate_pairs_on_submit": "yes",
                "voice_mode": "father_to_adam",
                "synthetic": True,
                "context": "Use reviewed memory as supporting evidence.",
            },
            allow_live_model=True,
            app_settings=Settings(
                openai_api_key="test-key",
                embedding_live_calls_enabled=True,
                text_generation_live_calls_enabled=False,
                storage_root=str(tmp_path),
            ),
        )

    assert body["ranked_evidence_record_count"] == 1
    assert body["ranked_evidence_vector_query_used"] is True
    assert body["ranked_evidence_packet"]["retrieval_strategy"] == "boundary_filtered_vector_similarity_with_lexical_fallback"
    assert body["created_pairs_preview"][0]["source_evidence_status"] == "evidence_linked"
    assert any(
        ref.get("type") == "retrieval_ranked_evidence_record"
        and ref.get("embedding_record_id") == "embedding-old-orchard-reviewed"
        for ref in body["created_pairs_preview"][0]["source_evidence_refs"]
    )


def test_source_review_fallback_pair_records_generation_metadata_without_archival_claim():
    client, engine = build_client()
    source_text = "Gray morning in Portland.\nLight rain on the harbor, no drama, just weather."

    with Session(engine) as session:
        asset = Asset(
            human_id="ASSET_FALLBACK_SOURCE",
            asset_type="text",
            title="loose_source.txt",
            original_filename="loose_source.txt",
            mime_type="text/plain",
        )
        session.add(asset)
        session.flush()
        preview = Segment(
            human_id="SEG_FALLBACK_SOURCE_PREVIEW",
            asset_id=asset.id,
            segment_type="text_preview",
            title="Loose source preview",
            text_content=source_text,
        )
        session.add(preview)
        session.flush()
        task = Task(
            human_id="TASK_FALLBACK_SOURCE_REVIEW",
            task_type="text_segment_review",
            target_type="segment",
            target_id=preview.id,
            queue="text_segments_needing_review",
            input_payload={
                "asset_id": asset.id,
                "source_filename": "loose_source.txt",
                "preview_text": source_text,
            },
            created_by="test",
        )
        session.add(task)
        session.commit()
        task_id = task.id

    response = client.post(
        f"/api/tasks/{task_id}/submit",
        json={
            "decisions": {
                "source_review_status": "reviewed",
                "generate_pairs_on_submit": "yes",
                "voice_mode": "mundane_text_message",
                "synthetic": True,
                "context": "Fallback metadata fixture.",
            }
        },
    )

    assert response.status_code == 200
    assert response.json()["creates_or_updates"]["generated_pair_count"] == 1

    with Session(engine) as session:
        ticket = session.exec(select(Task).where(Task.task_type == "gold_voice_edit")).one()
        payload = ticket.input_payload
        metadata = payload["pair_generation_metadata"]
        prompt_spec = session.get(PromptSpec, payload["prompt_spec_id"])

        assert payload["prompt"] == "Tell me about Gray morning in Portland."
        assert payload["content"] == source_text
        assert payload["truth_status"] == "adam_expert_reconstruction"
        assert payload["truth_status"] != "archival_source"
        assert payload["candidate_requires_adam_gold_edit"] is True
        assert metadata["prompt_instructions_version"] == "charlesops_source_review_pair_generation_v1"
        assert metadata["strategy"] == "deterministic_fallback_source_text"
        assert metadata["model_name"] == "gpt-5.5"
        assert metadata["reasoning_effort"] == "medium"
        assert metadata["live_model_call"] is False
        assert metadata["no_live_model_call"] is True
        assert metadata["source_title"] == "loose_source.txt"
        assert metadata["source_text_char_count"] == len(source_text)
        assert metadata["source_text_preview"] == source_text
        assert metadata["voice_mode"] == "mundane_text_message"
        assert metadata["candidate_requires_adam_review"] is True
        assert prompt_spec is not None
        assert prompt_spec.metadata_json["pair_generation_metadata"] == metadata
        assert session.exec(select(Generation)).all() == []


def test_source_review_generate_pairs_from_mixed_yaml_fixture_creates_exact_prompt_pair_tickets():
    client, engine = build_client()
    source_text = _mixed_yaml_fixture()

    with Session(engine) as session:
        asset = Asset(
            human_id="ASSET_RALPH_MIXED_YAML",
            asset_type="text",
            title="Mixed SFT and DPO prompt pairs",
            mime_type="application/x-yaml",
        )
        session.add(asset)
        session.flush()
        preview = Segment(
            human_id="SEG_RALPH_MIXED_YAML_PREVIEW",
            asset_id=asset.id,
            segment_type="text_preview",
            title="Mixed SFT and DPO prompt pairs preview",
            text_content=source_text,
        )
        session.add(preview)
        session.flush()
        task = Task(
            human_id="TASK_RALPH_MIXED_YAML_REVIEW",
            task_type="text_segment_review",
            target_type="segment",
            target_id=preview.id,
            queue="source_review",
            input_payload={
                "asset_id": asset.id,
                "segment_id": preview.id,
                "source_filename": "mixed_prompt_pairs.yml",
                "source_title": "Mixed SFT and DPO prompt pairs",
                "preview_text": source_text[:4000],
            },
            created_by="test",
        )
        session.add(task)
        session.commit()
        task_id = task.id
        asset_id = asset.id

    response = client.post(
        f"/api/tasks/{task_id}/submit",
        json={
            "decisions": {
                "source_text": source_text,
                "source_review_status": "reviewed",
                "generate_pairs_on_submit": "yes",
                "voice_mode": "father_to_adam",
                "synthetic": True,
                "context": "Strict mixed YAML intake fixture.",
            },
            "notes": "Generate exact Prompt Pair tickets.",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["creates_or_updates"]["generated_pair_count"] == 25

    with Session(engine) as session:
        tickets = session.exec(
            select(Task).where(Task.task_type == "gold_voice_edit").order_by(Task.created_at.asc())
        ).all()
        prompt_specs = session.exec(select(PromptSpec).order_by(PromptSpec.created_at.asc())).all()

        assert len(tickets) == 25
        assert len(prompt_specs) == 25
        assert len({ticket.input_payload["pair_index"] for ticket in tickets}) == 25

        for ordinal, ticket in enumerate(tickets, start=1):
            payload = ticket.input_payload
            assert payload["pair_index"] == ordinal
            assert payload["source_task_id"] == task_id
            assert payload["source_review_annotation_id"]
            assert payload["grounding_asset_id"] == asset_id
            assert payload["source_excerpt"].strip()
            assert "Tell me about mixed_prompt_pairs.yml" not in payload["prompt"]
            assert payload["prompt"] != "Tell me about this."

        first = tickets[0].input_payload
        assert first["artifact_mode"] == "sft"
        assert first["system_prompt"] == "You are Charles Rotmil. Write naturally in his voice."
        assert first["prompt"] == "Question 1: How is Portland?"
        assert first["content"] == "answer 1 line one\nanswer 1 line two\n\ndad"
        assert first["truth_status"] == "adam_expert_reconstruction"
        assert first["synthetic"] is True

        twentieth = tickets[19].input_payload
        assert twentieth["artifact_mode"] == "sft"
        assert twentieth["prompt"] == "Question 20: How is Portland?"
        assert twentieth["content"] == "answer 20 line one\nanswer 20 line two\n\ndad"

        first_dpo = tickets[20].input_payload
        assert first_dpo["artifact_mode"] == "dpo"
        assert first_dpo["system_prompt"] == "You are Charles Rotmil."
        assert first_dpo["voice_mode"] == "comic_observation"
        assert first_dpo["prompt"] == "DPO prompt 1: How was the soup?"
        assert first_dpo["chosen"] == "soup 1 was thin...\ntasted like nothing\n\ndad"
        assert first_dpo["rejected"] == "The soup 1 was bland and unsatisfying."
        assert first_dpo["truth_status"] == "adam_expert_reconstruction"


def test_sft_yaml_preview_matches_nested_message_shape_without_trailing_blank_line():
    compiled = compile_pair_export(
        {
            "artifact_mode": "sft",
            "system_prompt": "You are Charles Rotmil. Write naturally in his voice.",
            "prompt": "Line one\nLine two",
            "content": "gray here...\nlight rain\nkeeps the trees happy",
            "voice_mode": "father_to_adam",
            "synthetic": True,
        }
    )

    expected = "\n".join(
        [
            "- messages:",
            "   - role: system",
            "     content: You are Charles Rotmil. Write naturally in his voice.",
            "   - role: user",
            "     content: |-",
            "       Line one",
            "       Line two",
            "   - role: assistant",
            "     content: |-",
            "       gray here...",
            "       light rain",
            "       keeps the trees happy",
        ]
    )
    assert compiled["yaml_preview"] == expected
    assert yaml.safe_load(compiled["yaml_preview"]) == yaml.safe_load(expected)
    assert not compiled["yaml_preview"].endswith("\n")


def test_dpo_yaml_preview_matches_chosen_rejected_shape_without_trailing_blank_line():
    compiled = compile_pair_export(
        {
            "artifact_mode": "dpo",
            "system_prompt": "You are Charles Rotmil.",
            "prompt": "How was the soup?",
            "chosen": "soup was thin...\ntasted like nothing",
            "rejected": "The soup was bland and unsatisfying.",
            "voice_mode": "comic_observation",
            "synthetic": True,
        }
    )

    expected = "\n".join(
        [
            "- system: You are Charles Rotmil.",
            "  prompt: How was the soup?",
            "  chosen: |-",
            "    soup was thin...",
            "    tasted like nothing",
            "  rejected: |-",
            "    The soup was bland and unsatisfying.",
        ]
    )
    assert compiled["yaml_preview"] == expected
    assert yaml.safe_load(compiled["yaml_preview"]) == yaml.safe_load(expected)
    assert not compiled["yaml_preview"].endswith("\n")


def test_submitted_sft_and_dpo_artifacts_match_export_preview_structure():
    client, engine = build_client()

    with Session(engine) as session:
        sft_task = Task(
            human_id="TASK_RALPH_SFT_EXPORT",
            task_type="gold_voice_edit",
            target_type="prompt_pair",
            target_id="prompt_pair_sft",
            queue="prompt_pairs_needing_gold_edits",
            input_payload={"artifact_mode": "sft", "truth_status": "adam_expert_reconstruction"},
            created_by="test",
        )
        dpo_task = Task(
            human_id="TASK_RALPH_DPO_EXPORT",
            task_type="gold_voice_edit",
            target_type="prompt_pair",
            target_id="prompt_pair_dpo",
            queue="prompt_pairs_needing_gold_edits",
            input_payload={"artifact_mode": "dpo", "truth_status": "adam_expert_reconstruction"},
            created_by="test",
        )
        session.add(sft_task)
        session.add(dpo_task)
        session.commit()
        sft_task_id = sft_task.id
        dpo_task_id = dpo_task.id

    sft_decisions = {
        "artifact_mode": "sft",
        "system_prompt": "You are Charles Rotmil. Write naturally in his voice.",
        "prompt": "How's Portland today?",
        "content": "gray here...\nlight rain\nkeeps the trees happy\n\ndad",
        "voice_mode": "father_to_adam",
        "synthetic": True,
        "response_rubric": {
            "response_b": {
                "privacy_export_safety": {"status": "no_issues", "notes": "", "issue_tags": []},
                "voice_authenticity": {"status": "no_issues", "notes": "", "issue_tags": []},
            }
        },
    }
    expected_sft_preview = compile_pair_export(sft_decisions)["yaml_preview"]
    sft_response = client.post(
        f"/api/tasks/{sft_task_id}/submit",
        json={"decisions": {**sft_decisions, "export_preview_yaml": expected_sft_preview}},
    )
    assert sft_response.status_code == 200

    dpo_decisions = {
        "artifact_mode": "dpo",
        "system_prompt": "You are Charles Rotmil.",
        "prompt": "How was the soup?",
        "chosen": "soup was thin...\ntasted like nothing\n\ndad",
        "rejected": "The soup was bland and unsatisfying.",
        "voice_mode": "comic_observation",
        "synthetic": True,
        "response_rubric": {
            "response_a": {
                "voice_authenticity": {
                    "status": "minor_issues",
                    "notes": "Rejected is too generic and explanatory.",
                    "issue_tags": ["too_generic"],
                }
            },
            "response_b": {
                "privacy_export_safety": {"status": "no_issues", "notes": "", "issue_tags": []},
                "voice_authenticity": {"status": "no_issues", "notes": "", "issue_tags": []},
            },
        },
    }
    expected_dpo_preview = compile_pair_export(dpo_decisions)["yaml_preview"]
    dpo_response = client.post(
        f"/api/tasks/{dpo_task_id}/submit",
        json={"decisions": {**dpo_decisions, "export_preview_yaml": expected_dpo_preview}},
    )
    assert dpo_response.status_code == 200

    with Session(engine) as session:
        gold_examples = session.exec(select(GoldVoiceExample).order_by(GoldVoiceExample.created_at.asc())).all()
        assert len(gold_examples) == 2

        sft = session.exec(select(SFTCandidate)).one()
        sft_gold = session.get(GoldVoiceExample, sft.source_gold_voice_example_id)
        assert sft.messages == [
            {"role": "system", "content": "You are Charles Rotmil. Write naturally in his voice."},
            {"role": "user", "content": "How's Portland today?"},
            {"role": "assistant", "content": "gray here...\nlight rain\nkeeps the trees happy\n\ndad"},
        ]
        assert sft.quality_gate["export_preview_yaml"] == expected_sft_preview
        assert sft_gold.downstream_use["export_preview_yaml"] == expected_sft_preview
        assert yaml.safe_load(sft.quality_gate["export_preview_yaml"])[0]["messages"] == sft.messages

        dpo = session.exec(select(DPOPair)).one()
        dpo_gold = session.get(GoldVoiceExample, dpo.source_gold_voice_example_id)
        assert dpo.prompt == "How was the soup?"
        assert dpo.chosen == "soup was thin...\ntasted like nothing\n\ndad"
        assert dpo.rejected == "The soup was bland and unsatisfying."
        assert dpo.chosen != dpo.rejected
        assert dpo.reason == ["voice_authenticity: Rejected is too generic and explanatory."]
        assert dpo.export_status == "approved"
        assert dpo_gold.downstream_use["export_preview_yaml"] == expected_dpo_preview
        parsed_dpo = yaml.safe_load(dpo_gold.downstream_use["export_preview_yaml"])[0]
        assert parsed_dpo == {
            "system": "You are Charles Rotmil.",
            "prompt": dpo.prompt,
            "chosen": dpo.chosen,
            "rejected": dpo.rejected,
        }


def test_dpo_export_guard_blocks_identical_or_unexplained_rejected_response():
    client, engine = build_client()
    with Session(engine) as session:
        task = Task(
            human_id="TASK_RALPH_DPO_INVALID_EXPORT",
            task_type="gold_voice_edit",
            target_type="prompt_pair",
            target_id="prompt_pair_dpo_invalid",
            queue="prompt_pairs_needing_gold_edits",
            input_payload={"artifact_mode": "dpo", "truth_status": "adam_expert_reconstruction"},
            created_by="test",
        )
        session.add(task)
        session.commit()
        task_id = task.id

    decisions = {
        "artifact_mode": "dpo",
        "system_prompt": "You are Charles Rotmil.",
        "prompt": "How was the soup?",
        "chosen": "soup was thin...\ntasted like nothing\n\ndad",
        "rejected": "soup was thin...\ntasted like nothing\n\ndad",
        "voice_mode": "comic_observation",
        "synthetic": True,
        "response_rubric": {
            "response_b": {
                "privacy_export_safety": {"status": "no_issues", "notes": "", "issue_tags": []},
                "voice_authenticity": {"status": "no_issues", "notes": "", "issue_tags": []},
            }
        },
    }
    response = client.post(f"/api/tasks/{task_id}/submit", json={"decisions": decisions})
    assert response.status_code == 200

    with Session(engine) as session:
        dpo = session.exec(select(DPOPair)).one()
        assert dpo.export_status == "candidate"
        assert "dpo_chosen_rejected_identical" in dpo.reason
        assert "dpo_missing_rejected_side_reason" in dpo.reason

    dry_run = client.get("/api/dataset-exports/dry-run?export_type=dpo")
    assert dry_run.status_code == 200
    body = dry_run.json()
    assert body["included_count"] == 0
    assert body["excluded_count"] == 1
    assert body["excluded"][0]["reasons"] == ["artifact_status_is_candidate"]
    assert body["excluded"][0]["payload"]["preferred_output"] == body["excluded"][0]["payload"]["non_preferred_output"]
    assert "dpo_chosen_rejected_identical" in body["excluded"][0]["payload"]["metadata"]["reason"]


def test_sft_export_guard_blocks_filename_placeholder_prompt_even_with_clean_rubric():
    client, engine = build_client()
    with Session(engine) as session:
        task = Task(
            human_id="TASK_RALPH_SFT_PLACEHOLDER_EXPORT",
            task_type="gold_voice_edit",
            target_type="prompt_pair",
            target_id="prompt_pair_sft_placeholder",
            queue="prompt_pairs_needing_gold_edits",
            input_payload={"artifact_mode": "sft", "truth_status": "adam_expert_reconstruction"},
            created_by="test",
        )
        session.add(task)
        session.commit()
        task_id = task.id

    decisions = {
        "artifact_mode": "sft",
        "system_prompt": "You are Charles Rotmil. Write naturally in his voice.",
        "prompt": "Tell me about charles_sft.yaml",
        "content": "gray here...\nlight rain\nkeeps the trees happy\n\ndad",
        "voice_mode": "father_to_adam",
        "synthetic": True,
        "response_rubric": {
            "response_b": {
                "privacy_export_safety": {"status": "no_issues", "notes": "", "issue_tags": []},
                "voice_authenticity": {"status": "no_issues", "notes": "", "issue_tags": []},
                "grounding_truth": {"status": "no_issues", "notes": "", "issue_tags": []},
                "restraint": {"status": "no_issues", "notes": "", "issue_tags": []},
                "concrete_detail": {"status": "no_issues", "notes": "", "issue_tags": []},
                "prompt_fit": {"status": "no_issues", "notes": "", "issue_tags": []},
            }
        },
    }
    response = client.post(f"/api/tasks/{task_id}/submit", json={"decisions": decisions})
    assert response.status_code == 200

    with Session(engine) as session:
        sft = session.exec(select(SFTCandidate)).one()
        assert sft.export_status == "candidate"
        assert sft.quality_gate["export_ready"] is False
        assert sft.quality_gate["export_blockers"] == ["sft_prompt_filename_placeholder"]

    approved_dry_run = client.get("/api/dataset-exports/dry-run?export_type=sft")
    assert approved_dry_run.status_code == 200
    approved_body = approved_dry_run.json()
    assert approved_body["included_count"] == 0
    assert approved_body["excluded_count"] == 1
    assert approved_body["excluded"][0]["reasons"] == ["artifact_status_is_candidate"]
    assert approved_body["excluded"][0]["payload"]["metadata"]["review_blockers"] == [
        "sft_prompt_filename_placeholder"
    ]


def test_source_review_prompt_response_spans_create_pair_and_preserve_coding_context():
    client, engine = build_client()
    source_text = "\n".join(
        [
            "Adam asks: How's Portland today?",
            "Charles replies:",
            "gray here...",
            "light rain",
            "keeps the trees happy",
            "",
            "dad",
        ]
    )
    prompt_text = "How's Portland today?"
    response_text = "gray here...\nlight rain\nkeeps the trees happy\n\ndad"
    prompt_start = source_text.index(prompt_text)
    response_start = source_text.index("gray here")

    with Session(engine) as session:
        asset = Asset(
            human_id="ASSET_RALPH_SPAN_SOURCE",
            asset_type="text",
            title="Span coded source",
            mime_type="text/plain",
        )
        session.add(asset)
        session.flush()
        preview = Segment(
            human_id="SEG_RALPH_SPAN_PREVIEW",
            asset_id=asset.id,
            segment_type="text_preview",
            title="Span coded source preview",
            text_content=source_text,
        )
        session.add(preview)
        session.flush()
        task = Task(
            human_id="TASK_RALPH_SPAN_REVIEW",
            task_type="text_segment_review",
            target_type="segment",
            target_id=preview.id,
            queue="source_review",
            input_payload={"asset_id": asset.id, "segment_id": preview.id, "preview_text": source_text},
            created_by="test",
        )
        session.add(task)
        session.commit()
        task_id = task.id
        asset_id = asset.id
        segment_id = preview.id

    response = client.post(
        f"/api/tasks/{task_id}/submit",
        json={
            "decisions": {
                "source_text": source_text,
                "generate_pairs_on_submit": "yes",
                "voice_mode": "father_to_adam",
                "synthetic": True,
                "source_spans": [
                    {
                        "start_char": prompt_start,
                        "end_char": prompt_start + len(prompt_text),
                        "text": prompt_text,
                        "span_type": "prompt",
                        "speaker": "Adam",
                        "code": "clean prompt",
                        "notes": "Use exactly as the user side.",
                    },
                    {
                        "start_char": response_start,
                        "end_char": response_start + len(response_text),
                        "text": response_text,
                        "span_type": "response",
                        "speaker": "Charles",
                        "code": "voice-ready response",
                        "notes": "Keep closing and line breaks.",
                    },
                ],
            }
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["creates_or_updates"]["generated_pair_count"] == 1

    with Session(engine) as session:
        spans = session.exec(select(SourceSpanAnnotation).order_by(SourceSpanAnnotation.created_at.asc())).all()
        assert len(spans) == 2
        assert [span.span_type for span in spans] == ["prompt", "response"]
        assert spans[0].speaker == "Adam"
        assert spans[1].speaker == "Charles"
        assert spans[0].source_asset_id == asset_id
        assert spans[0].source_segment_id == segment_id

        ticket = session.get(Task, body["creates_or_updates"]["make_gold_task_ids"][0])
        payload = ticket.input_payload
        assert payload["artifact_mode"] == "sft"
        assert payload["prompt"] == prompt_text
        assert payload["content"] == response_text
        assert payload["source_span_annotation_ids"] == [span.id for span in spans]
        assert "clean prompt" in payload["context"]
        assert "voice-ready response" in payload["context"]
        assert "Keep closing and line breaks." in payload["context"]
        assert payload["grounding_asset_id"] == asset_id
        assert payload["source_task_id"] == task_id
