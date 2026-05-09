import logging

from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app.config import Settings, get_settings
from app.db.session import get_session
from app.main import app
from app.models import (
    Annotation,
    Asset,
    AssetSnapshot,
    ChatAction,
    ChatActionResult,
    ChatSession,
    ChatTurn,
    ContextPack,
    Derivative,
    DPOPair,
    DatasetExport,
    DatasetExportItem,
    EmbeddingRecord,
    GoldVoiceExample,
    MetadataProfile,
    ObjectFile,
    SFTCandidate,
    Segment,
    Task,
    TaskDraft,
)
from app.schemas import ChatMessage, ChatTurnRequest
from app.services.chat_operator import (
    _context_packet_for_turn,
    _image_data_url_for_task,
    _live_chat_plan,
    _next_downstream_candidate_task,
    chat_review_task_action_stale_reason,
)
from app.services.pair_export import compile_pair_export
from app.services.pair_generation import preview_make_gold_tasks_from_review


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
        chat_require_live_model=False,
    )
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


def add_photo_context_task(session: Session) -> str:
    task = Task(
        human_id="TASK_CHAT_PHOTO",
        task_type="photo_context",
        target_type="asset",
        target_id="asset-chat-photo",
        queue="photo_assets_needing_context",
        input_payload={
            "asset_title": "Beach photo",
            "suggested_questions": ["Who is here?", "What should the system remember?"],
        },
        created_by="test",
    )
    session.add(task)
    session.commit()
    return task.id


def add_photo_context_task_with_local_image(session: Session, storage_root) -> str:
    asset = Asset(
        human_id="ASSET_CHAT_PHOTO_IMAGE",
        asset_type="photo",
        title="Local chat photo",
        mime_type="image/png",
        processing_status="image_preview_ready",
    )
    session.add(asset)
    session.flush()
    object_key = "chat-test/photo-preview.png"
    image_path = storage_root / object_key
    image_path.parent.mkdir(parents=True, exist_ok=True)
    image_path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        b"\x00\x00\x00\rIHDR"
        b"\x00\x00\x00\x01\x00\x00\x00\x01"
        b"\x08\x06\x00\x00\x00"
        b"\x1f\x15\xc4\x89"
        b"\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    object_file = ObjectFile(
        storage_provider="local",
        object_key=object_key,
        uri=f"local://{object_key}",
        content_type="image/png",
        byte_size=image_path.stat().st_size,
    )
    session.add(object_file)
    session.flush()
    snapshot = AssetSnapshot(
        asset_id=asset.id,
        snapshot_type="source_mirror",
        version=1,
        object_file_id=object_file.id,
    )
    session.add(snapshot)
    session.flush()
    session.add(
        Derivative(
            asset_id=asset.id,
            source_snapshot_id=snapshot.id,
            derivative_type="image_preview",
            object_file_id=object_file.id,
            status="ready",
            metadata_json={"variant": "display"},
        )
    )
    task = Task(
        human_id="TASK_CHAT_PHOTO_IMAGE",
        task_type="photo_context",
        target_type="asset",
        target_id=asset.id,
        queue="photo_assets_needing_context",
        input_payload={"asset_id": asset.id, "asset_title": "Local chat photo"},
        created_by="test",
    )
    session.add(task)
    session.commit()
    return task.id


def add_reviewable_photo_asset(session: Session) -> str:
    asset = Asset(
        human_id="ASSET_CHAT_RETRIEVAL_GAP_PHOTO",
        asset_type="photo",
        title="Retrieval gap breakfast photo",
        mime_type="image/jpeg",
        processing_status="image_preview_ready",
    )
    session.add(asset)
    session.commit()
    return asset.id


def add_source_review_task(session: Session) -> str:
    asset = Asset(
        human_id="ASSET_CHAT_SOURCE",
        asset_type="text",
        title="Journal excerpt",
        mime_type="text/plain",
    )
    session.add(asset)
    session.flush()
    segment = Segment(
        human_id="SEG_CHAT_SOURCE",
        asset_id=asset.id,
        segment_type="text_preview",
        title="Journal excerpt",
        text_content="A short journal excerpt for source review.",
    )
    session.add(segment)
    session.flush()
    task = Task(
        human_id="TASK_CHAT_SOURCE",
        task_type="text_segment_review",
        target_type="segment",
        target_id=segment.id,
        queue="text_segments_needing_review",
        priority=73,
        reason_created="Review this source excerpt for voice usefulness and downstream boundaries.",
        input_payload={
            "asset_id": asset.id,
            "source_title": "Journal excerpt",
            "source_filename": "journal.txt",
            "preview_text": "A short journal excerpt for source review.",
            "review_instructions": ["Identify authorship.", "Decide whether it can generate prompt pairs."],
        },
        created_by="test",
    )
    session.add(task)
    session.commit()
    return task.id


def add_reviewable_source_segment_without_task(session: Session) -> tuple[str, str]:
    asset = Asset(
        human_id="ASSET_CHAT_SOURCE_CLUSTER",
        asset_type="text",
        title="Source cluster journal",
        mime_type="text/plain",
    )
    session.add(asset)
    session.flush()
    segment = Segment(
        human_id="SEG_CHAT_SOURCE_CLUSTER",
        asset_id=asset.id,
        segment_type="text_chunk",
        title="Cooking source cluster",
        text_content="Cooking felt different when it was for Adam and the family.",
    )
    session.add(segment)
    session.commit()
    return asset.id, segment.id


def add_complete_gold_task(session: Session) -> str:
    task = Task(
        human_id="TASK_CHAT_DPO_READY",
        task_type="gold_voice_edit",
        target_type="prompt_pair",
        target_id="pair-chat-ready",
        queue="prompt_pairs_needing_gold_edits",
        input_payload={
            "artifact_mode": "sft",
            "system_prompt": "You are Charles Rotmil. Write naturally in his voice.",
            "prompt": "How was the beach?",
            "content": "light first. always the light.\n\nlove\ndad",
            "chosen": "light first. always the light.\n\nlove\ndad",
            "voice_mode": "photography_reflection",
            "truth_status": "adam_expert_reconstruction",
            "synthetic": True,
            "export_flags": {"sft": True, "dpo": False, "eval": False, "anti_pattern": False, "style_rule": False},
            "ratings": {
                "voice_fidelity": 5,
                "emotional_truth": 5,
                "restraint": 5,
                "non_parody": 5,
            },
        },
        created_by="test",
    )
    session.add(task)
    session.commit()
    return task.id


def add_dpo_review_task(session: Session) -> str:
    task = Task(
        human_id="TASK_CHAT_DPO_REVIEW",
        task_type="gold_voice_edit",
        target_type="prompt_pair",
        target_id="pair-chat-review",
        queue="prompt_pairs_needing_gold_edits",
        input_payload={
            "artifact_mode": "dpo",
            "system_prompt": "You are Charles Rotmil. Write naturally in his voice.",
            "prompt": "How did you learn to cook?",
            "chosen": "mostly by watching and ruining a few pans.\n\nlove\ndad",
            "rejected": "I learned to cook from recipes and practice.",
            "voice_mode": "father_to_adam",
            "truth_status": "adam_expert_reconstruction",
            "synthetic": True,
            "failure_modes": [],
        },
        created_by="test",
    )
    session.add(task)
    session.commit()
    return task.id


def add_approved_sft_export_artifact(session: Session) -> str:
    context = ContextPack(
        human_id="CTX_CHAT_SFT_EXPORT",
        user_intent="gold_voice_generation",
        requested_voice_mode="father_to_adam",
        truth_mode="adam_expert_reconstruction",
        boundaries_snapshot={"boundary_status": "passed"},
    )
    session.add(context)
    session.flush()
    gold = GoldVoiceExample(
        human_id="GOLD_CHAT_SFT_EXPORT",
        context_pack_id=context.id,
        voice_mode="father_to_adam",
        truth_status="adam_expert_reconstruction",
        adam_gold_edit="rain on the porch. small mercy.\n\nlove\ndad",
        downstream_use={"sft": True, "synthetic": True, "artifact_mode": "sft"},
        ratings={"response_rubric": {"response_b": {"privacy_export_safety": {"status": "no_issues"}}}},
    )
    session.add(gold)
    session.flush()
    session.add(
        SFTCandidate(
            source_gold_voice_example_id=gold.id,
            messages=[
                {"role": "system", "content": "You are Charles Rotmil. Write naturally in his voice."},
                {"role": "user", "content": "What was the porch like?"},
                {"role": "assistant", "content": gold.adam_gold_edit},
            ],
            export_status="approved",
        )
    )
    session.add(
        Task(
            human_id="TASK_CHAT_SFT_CANDIDATE_NOT_APPROVED",
            task_type="gold_voice_edit",
            target_type="prompt_pair",
            target_id="prompt_pair_sft_candidate_not_approved",
            queue="prompt_pairs_needing_gold_edits",
            input_payload={
                "artifact_mode": "sft",
                "system_prompt": "You are Charles Rotmil.",
                "prompt": "Candidate prompt?",
                "content": "candidate response\n\ndad",
                "voice_mode": "father_to_adam",
                "truth_status": "adam_expert_reconstruction",
                "synthetic": True,
            },
            created_by="test",
        )
    )
    session.commit()
    return gold.id


def add_approved_dpo_export_artifact(session: Session) -> str:
    context = ContextPack(
        human_id="CTX_CHAT_DPO_EXPORT",
        user_intent="gold_voice_generation",
        requested_voice_mode="father_to_adam",
        truth_mode="adam_expert_reconstruction",
        boundaries_snapshot={"boundary_status": "passed"},
    )
    session.add(context)
    session.flush()
    gold = GoldVoiceExample(
        human_id="GOLD_CHAT_DPO_EXPORT",
        context_pack_id=context.id,
        voice_mode="father_to_adam",
        truth_status="adam_expert_reconstruction",
        adam_gold_edit="mostly watching, then burning onions until I learned.\n\nlove\ndad",
        downstream_use={"dpo": True, "synthetic": True, "artifact_mode": "dpo"},
        ratings={"response_rubric": {"response_b": {"privacy_export_safety": {"status": "no_issues"}}}},
    )
    session.add(gold)
    session.flush()
    session.add(
        DPOPair(
            source_gold_voice_example_id=gold.id,
            prompt="How did you learn to cook?",
            chosen="mostly watching, then burning onions until I learned.\n\nlove\ndad",
            rejected="I learned to cook from recipes and practice.",
            reason=["rejected_too_generic_not_charles_voice"],
            export_status="approved",
        )
    )
    session.add(
        Task(
            human_id="TASK_CHAT_DPO_CANDIDATE_NOT_APPROVED",
            task_type="gold_voice_edit",
            target_type="prompt_pair",
            target_id="prompt_pair_dpo_candidate_not_approved",
            queue="prompt_pairs_needing_gold_edits",
            input_payload={
                "artifact_mode": "dpo",
                "system_prompt": "You are Charles Rotmil.",
                "prompt": "Candidate DPO prompt?",
                "chosen": "candidate chosen\n\ndad",
                "rejected": "candidate rejected",
                "voice_mode": "father_to_adam",
                "truth_status": "adam_expert_reconstruction",
                "synthetic": True,
                "failure_modes": ["candidate_still_needs_adam_review"],
            },
            created_by="test",
        )
    )
    session.commit()
    return gold.id


def add_prompt_pair_export_blocker_task(session: Session) -> str:
    decisions = {
        "artifact_mode": "sft",
        "system_prompt": "You are Charles Rotmil. Write naturally in his voice.",
        "prompt": "How is Portland today?",
        "content": "gray here...\nlight rain\n\nlove\ndad",
        "voice_mode": "mundane_text_message",
        "truth_status": "adam_expert_reconstruction",
        "rubric_summary": {"preferred_export_blocked": True},
    }
    compiled = compile_pair_export(decisions)
    task = Task(
        human_id="TASK_CHAT_TOP_EXPORT_BLOCKER",
        task_type="gold_voice_edit",
        target_type="prompt_pair",
        target_id="prompt_pair_chat_top_blocker",
        queue="prompt_pairs_needing_gold_edits",
        input_payload={**decisions, "export_preview_yaml": compiled["yaml_preview"]},
        created_by="test",
    )
    session.add(task)
    session.commit()
    return task.id


def test_chat_turn_draft_first_updates_task_draft_without_submit(caplog):
    caplog.set_level(logging.INFO, logger="app.services.chat_operator")
    client, engine = build_client()
    with Session(engine) as session:
        task_id = add_photo_context_task(session)

    response = client.post(
        "/api/chat/turn",
        json={"task_id": task_id, "message": "It shows Charles standing by the water in a coat."},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["active_task"]["id"] == task_id
    assert body["ready_to_submit"] is False
    assert body["submitted_annotation"] is None
    assert body["session_id"]
    assert body["turn_id"]
    assert body["context_packet_hash"]
    assert body["safety_policy"]["draft_first"] is True
    assert "visual_description_correction" in body["field_updates"]
    diff = next(item for item in body["field_diffs"] if item["field"] == "visual_description_correction")
    assert diff["change_type"] == "added"
    assert diff["before"] is None
    assert "Charles" in diff["after"]

    with Session(engine) as session:
        task = session.get(Task, task_id)
        draft = session.exec(select(TaskDraft).where(TaskDraft.task_id == task_id)).first()
        chat_session = session.get(ChatSession, body["session_id"])
        turns = session.exec(select(ChatTurn).where(ChatTurn.session_id == body["session_id"]).order_by(ChatTurn.created_at.asc())).all()
        draft_action = session.exec(
            select(ChatAction).where(ChatAction.session_id == body["session_id"]).where(ChatAction.action_type == "update_task_draft")
        ).first()
        assert task.status == "ready"
        assert draft is not None
        assert "Charles" in draft.decisions["visual_description_correction"]
        assert "water" in draft.decisions["visual_description_correction"]
        assert chat_session is not None
        assert chat_session.active_task_id == task_id
        assert [turn.role for turn in turns] == ["user", "assistant"]
        assert turns[1].context_packet_hash == body["context_packet_hash"]
        assert draft_action is not None
        assert draft_action.status == "executed"
        assert draft_action.requires_confirmation is False
        assert draft_action.validated_payload_json["field_diffs"][0]["field"] == "visual_description_correction"
        result = session.exec(select(ChatActionResult).where(ChatActionResult.action_id == draft_action.id)).first()
        assert result is not None
        assert result.object_type == "task_draft"
        assert result.after_json["decisions"]["visual_description_correction"] == draft.decisions["visual_description_correction"]
    event_names = [getattr(record, "chat_event", None) for record in caplog.records]
    assert "context_packet_built" in event_names
    assert "turn_received" in event_names
    assert "structured_response_validated" in event_names
    assert "action_proposed" in event_names


def test_chat_photo_answer_extracts_structured_context_fields():
    client, engine = build_client()
    with Session(engine) as session:
        task_id = add_photo_context_task(session)

    response = client.post(
        "/api/chat/turn",
        json={
            "task_id": task_id,
            "message": (
                "Visible: Charles and Adam standing by the water in coats. "
                "Place: Old Orchard Beach. Date: 1984. Event: family beach trip. "
                "Context: Dad cared about the light there and this should be remembered as a family memory. "
                "Privacy: family private. Ready for downstream: yes. "
                "Not sure whether Cathryn took the photo."
            ),
        },
    )

    assert response.status_code == 200
    body = response.json()
    updates = body["field_updates"]
    assert updates["visual_description_correction"] == "Charles and Adam standing by the water in coats"
    assert updates["visible_people"] == ["Charles", "Adam"]
    assert updates["place"] == "Old Orchard Beach"
    assert updates["places"] == ["Old Orchard Beach"]
    assert updates["date_or_range"] == "1984"
    assert updates["date_confidence"] == "adam_estimate"
    assert updates["event"] == "family beach trip"
    assert updates["privacy_level"] == "family_private"
    assert updates["ready_for_downstream"] == "yes"
    assert "Dad cared about the light" in updates["adam_context_note"]
    assert any("Cathryn took the photo" in item for item in updates["open_questions"])
    diff_sources = {item["field"]: item.get("value_source") for item in body["field_diffs"]}
    assert diff_sources["visual_description_correction"] == "adam_confirmed_fact"
    assert diff_sources["adam_context_note"] == "adam_provided_memory"
    assert diff_sources["open_questions"] == "adam_confirmed_uncertainty"
    assert "prepare this ticket for submit" in body["next_question"]
    with Session(engine) as session:
        draft = session.exec(select(TaskDraft).where(TaskDraft.task_id == task_id)).first()
        assert draft.decisions["privacy_level"] == "family_private"
        assert draft.decisions["ready_for_downstream"] == "yes"


def test_chat_photo_answer_keeps_boundary_followup_when_missing_privacy():
    client, engine = build_client()
    with Session(engine) as session:
        task_id = add_photo_context_task(session)

    response = client.post(
        "/api/chat/turn",
        json={
            "task_id": task_id,
            "message": "It shows Charles near the kitchen table in 1979. Context: this was after a family dinner.",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["field_updates"]["date_or_range"] == "1979"
    assert "privacy_level" not in body["field_updates"]
    assert body["ready_to_submit"] is False
    assert "boundary" in body["next_question"].lower()


def test_chat_photo_exclusion_records_privacy_boundary_without_submit():
    client, engine = build_client()
    with Session(engine) as session:
        task_id = add_photo_context_task(session)

    response = client.post(
        "/api/chat/turn",
        json={
            "task_id": task_id,
            "message": "Exclude this photo from downstream and keep it private. Context: it has sensitive family detail.",
        },
    )

    assert response.status_code == 200
    body = response.json()
    updates = body["field_updates"]
    assert updates["privacy_level"] == "private_sensitive"
    assert updates["ready_for_downstream"] == "no"
    assert updates["gallery_eligibility"] == "excluded"
    assert updates["privacy_sensitivity"] == "high"
    assert "Adam exclusion note" in updates["privacy_notes"]
    assert body["ready_to_submit"] is False
    diff_sources = {item["field"]: item.get("value_source") for item in body["field_diffs"]}
    assert diff_sources["privacy_notes"] == "adam_confirmed_fact"
    with Session(engine) as session:
        draft = session.exec(select(TaskDraft).where(TaskDraft.task_id == task_id)).first()
        assert draft.decisions["ready_for_downstream"] == "no"
        assert draft.decisions["gallery_eligibility"] == "excluded"


def test_chat_photo_context_can_preview_and_confirm_submit():
    client, engine = build_client()
    with Session(engine) as session:
        task_id = add_photo_context_task(session)

    context_turn = client.post(
        "/api/chat/turn",
        json={
            "task_id": task_id,
            "message": (
                "Visible: Charles and Adam standing by the water in coats. "
                "Place: Old Orchard Beach. Date: 1984. Event: family beach trip. "
                "Context: Dad cared about the light there and this should be remembered as a family memory. "
                "Not sure whether Cathryn took the photo. Privacy: family private. Ready for downstream: yes."
            ),
        },
    )
    assert context_turn.status_code == 200
    context_body = context_turn.json()
    assert context_body["ready_to_submit"] is False

    preview = client.post(
        "/api/chat/turn",
        json={"task_id": task_id, "session_id": context_body["session_id"], "message": "ready"},
    )

    assert preview.status_code == 200
    preview_body = preview.json()
    assert preview_body["ready_to_submit"] is True
    assert preview_body["field_updates"] == {}
    assert preview_body["submit_payload"]["task_id"] == task_id
    submit_action_id = next(action["id"] for action in preview_body["actions"] if action["type"] == "submit_task")
    with Session(engine) as session:
        assert session.get(Task, task_id).status == "ready"
        assert session.exec(select(Annotation)).first() is None

    submitted = client.post(
        "/api/chat/turn",
        json={
            "task_id": task_id,
            "session_id": preview_body["session_id"],
            "message": "ready",
            "confirm_submit": True,
            "confirm_action_id": submit_action_id,
        },
    )

    assert submitted.status_code == 200
    body = submitted.json()
    assert body["submitted_annotation"]["task_id"] == task_id
    assert body["submitted_annotation"]["decisions"]["privacy_level"] == "family_private"
    assert body["submitted_annotation"]["decisions"]["ready_for_downstream"] == "yes"
    with Session(engine) as session:
        task = session.get(Task, task_id)
        annotation = session.exec(select(Annotation).where(Annotation.task_id == task_id)).first()
        assert task.status == "submitted"
        assert annotation is not None
        assert annotation.decisions["place"] == "Old Orchard Beach"
        provenance = annotation.decisions["chat_provenance"]
        assert provenance["chat_session_id"] == context_body["session_id"]
        assert provenance["preview_turn_id"] == preview_body["turn_id"]
        assert provenance["confirmation_turn_id"] == body["turn_id"]
        assert provenance["task_id"] == task_id
        assert provenance["source_refs"]["target_id"] == "asset-chat-photo"
        assert provenance["field_provenance"]["visual_description_correction"]["source"] == "adam_confirmed_fact"
        assert provenance["field_provenance"]["visible_people"]["source"] == "adam_confirmed_fact"
        assert provenance["field_provenance"]["adam_context_note"]["source"] == "adam_provided_memory"
        assert provenance["field_provenance"]["open_questions"]["source"] == "adam_confirmed_uncertainty"
        result = session.exec(select(ChatActionResult).where(ChatActionResult.action_id == submit_action_id)).first()
        assert result is not None
        assert result.object_type == "annotation"


def test_chat_photo_context_packet_marks_image_availability(tmp_path):
    _, engine = build_client()
    with Session(engine) as session:
        task_id = add_photo_context_task_with_local_image(session, tmp_path)
        task = session.get(Task, task_id)
        assert task is not None
        packet = _context_packet_for_turn(
            session=session,
            task=task,
            current_decisions={},
            draft_decisions={},
            missing_fields=[],
            request=ChatTurnRequest(message="What should we ask about this photo?"),
            app_settings=Settings(storage_root=str(tmp_path)),
            task_selection={},
        )
        data_url = _image_data_url_for_task(session, task, Settings(storage_root=str(tmp_path)))

    assert packet["image_context"]["asset_id"]
    assert packet["associated_object_ids"]["asset_ids"] == [task.target_id]
    assert packet["image_context"]["image_url"].startswith("/api/assets/")
    assert packet["image_context"]["image_pixels_available"] is True
    assert packet["image_context"]["width"] == 1
    assert packet["image_context"]["height"] == 1
    assert packet["image_context"]["reason"] == "ready"
    assert data_url is not None
    assert data_url.startswith("data:image/png;base64,")


def test_chat_context_packet_includes_source_refs_material_and_recent_chat():
    _, engine = build_client()
    with Session(engine) as session:
        task_id = add_source_review_task(session)
        task = session.get(Task, task_id)
        assert task is not None
        packet = _context_packet_for_turn(
            session=session,
            task=task,
            current_decisions={"source_genre": "journal"},
            draft_decisions={"source_genre": "journal"},
            missing_fields=[],
            request=ChatTurnRequest(
                message="Use this for voice context.",
                session_id="chat-session-test",
                history=[
                    ChatMessage(role="assistant", content="What is this source?"),
                    ChatMessage(role="user", content="It is a journal excerpt."),
                ],
            ),
            app_settings=Settings(),
            task_selection={"selection_reason": "selected_ticket"},
        )

    assert packet["source_refs"]["target_type"] == "segment"
    assert packet["source_refs"]["target_id"] == task.target_id
    assert packet["source_refs"]["asset_id"] == task.input_payload["asset_id"]
    assert packet["associated_object_ids"]["asset_ids"] == [task.input_payload["asset_id"]]
    assert packet["associated_object_ids"]["source_excerpt_ids"] == [task.target_id]
    assert packet["associated_object_ids"]["prompt_response_ids"] == []
    assert packet["active_task"]["priority"] == 73
    assert "Review this source excerpt" in packet["active_task"]["instructions"][0]
    assert "Identify authorship." in packet["active_task"]["instructions"]
    assert packet["work_surface"]["kind"] == "source_review"
    assert packet["source_material_preview"]["source_title"] == "Journal excerpt"
    assert packet["source_material_preview"]["preview_text"] == "A short journal excerpt for source review."
    assert packet["recent_chat"][-1] == {"role": "user", "content": "It is a journal excerpt."}
    assert packet["current_draft"]["decisions"] == {"source_genre": "journal"}
    assert packet["current_draft"]["field_count"] == 1
    assert packet["current_user_intent"]["submit_requested"] is False
    assert packet["current_user_intent"]["requested_route"] is None
    assert packet["provenance_refs"]["session_id"] == "chat-session-test"
    assert packet["provenance_refs"]["target_id"] == task.target_id
    assert "update_photo_context" in packet["allowed_actions"]
    read_tools = {item["tool_name"]: item for item in packet["read_tool_contracts"]}
    assert read_tools["plan_ranked_evidence_clusters"]["returns"].endswith("without vector values or vector file pointers")
    assert "training-board column summaries" in read_tools["inspect_work_queue_plan"]["returns"]
    action_contracts = {item["action_type"]: item for item in packet["action_contracts"]}
    assert action_contracts["update_task_draft"]["effect"] == "task_draft"
    assert action_contracts["build_dataset_export"]["requires_confirmation"] is True
    assert action_contracts["preview_task_submission"]["effect"] == "submit_preview"


def test_chat_context_packet_includes_prompt_response_association():
    _, engine = build_client()
    with Session(engine) as session:
        task_id = add_complete_gold_task(session)
        task = session.get(Task, task_id)
        assert task is not None
        packet = _context_packet_for_turn(
            session=session,
            task=task,
            current_decisions=task.input_payload,
            draft_decisions={},
            missing_fields=[],
            request=ChatTurnRequest(message="Let's fix this SFT response."),
            app_settings=Settings(),
            task_selection={},
        )

    assert packet["associated_object_ids"]["asset_ids"] == []
    assert packet["associated_object_ids"]["source_excerpt_ids"] == []
    assert packet["associated_object_ids"]["prompt_response_ids"] == [task.target_id]
    assert packet["work_surface"]["field_contract"]["accepted_response_field"] == "content"
    assert packet["work_surface"]["field_contract"]["rejected_response_field"] == "rejected"
    prompt_contract = next(contract for contract in packet["object_contracts"] if contract["object_type"] == "prompt_response_candidate")
    assert prompt_contract["artifact_mode"] == "sft"
    assert prompt_contract["field_aliases"]["accepted_response"] == "content"
    assert prompt_contract["field_aliases"]["original_draft"] == "rejected"
    assert prompt_contract["submit_mapping"]["dpo.chosen"] == "content"
    assert prompt_contract["submit_mapping"]["dpo.rejected"] == "rejected"


def test_live_chat_plan_attaches_image_input_for_mirrored_photo(tmp_path, monkeypatch):
    _, engine = build_client()
    captured = {}

    class FakeResponses:
        def create(self, **kwargs):
            captured.update(kwargs)
            return type(
                "FakeResponse",
                (),
                {
                    "id": "resp_chat_image_test",
                    "usage": {"input_tokens": 42, "output_tokens": 17},
                    "output_text": (
                        '{"assistant_message":"I can see the photo context packet.",'
                        '"next_question":"Who is pictured?",'
                        '"field_updates":{},'
                        '"actions":[{"type":"ask_question","label":"Who is pictured?","requires_confirmation":false}],'
                        '"ready_to_submit":false}'
                    )
                },
            )()

    class FakeOpenAI:
        def __init__(self, **kwargs):
            self.responses = FakeResponses()

    monkeypatch.setattr("openai.OpenAI", FakeOpenAI)
    with Session(engine) as session:
        task_id = add_photo_context_task_with_local_image(session, tmp_path)
        task = session.get(Task, task_id)
        assert task is not None
        plan = _live_chat_plan(
            session=session,
            task=task,
            current_decisions={},
            missing_fields=["visual_description_correction"],
            request=ChatTurnRequest(message="What should we ask about this photo?"),
            app_settings=Settings(
                storage_root=str(tmp_path),
                openai_api_key="test-key",
                text_generation_live_calls_enabled=True,
            ),
        )

    user_content = captured["input"][1]["content"]
    assert plan["status"] == "live_model_call"
    assert plan["_observability"]["model_response_id"] == "resp_chat_image_test"
    assert plan["_observability"]["input_token_count"] == 42
    assert plan["_observability"]["output_token_count"] == 17
    assert plan["_observability"]["latency_ms"] >= 0
    assert plan["_observability"]["image_pixels_included"] is True
    assert isinstance(user_content, list)
    assert "draft_updates" in user_content[0]["text"]
    assert "proposed_actions" in user_content[0]["text"]
    assert any(item["type"] == "input_image" and item["image_url"].startswith("data:image/png;base64,") for item in user_content)


def test_live_chat_plan_executes_read_tools_before_final_plan(monkeypatch):
    _, engine = build_client()
    captured_inputs = []

    class FakeResponses:
        def create(self, **kwargs):
            captured_inputs.append(kwargs["input"])
            if len(captured_inputs) == 1:
                return type(
                    "FakeResponse",
                    (),
                    {
                        "id": "resp_chat_tool_request",
                        "usage": {"input_tokens": 100, "output_tokens": 20},
                        "output_text": (
                            '{"tool_requests":[{"tool_name":"inspect_object_contract",'
                            '"reason":"Need the editable field contract before acting."}]}'
                        ),
                    },
                )()
            return type(
                "FakeResponse",
                (),
                {
                    "id": "resp_chat_tool_final",
                    "usage": {"input_tokens": 80, "output_tokens": 30},
                    "output_text": (
                        '{"assistant_message":"I inspected the field contract and will ask for the next DPO choice.",'
                        '"next_question":"What should the new chosen response say?",'
                        '"field_updates":{},'
                        '"actions":[{"type":"ask_question","label":"What should the new chosen response say?","requires_confirmation":false}],'
                        '"ready_to_submit":false,'
                        '"confidence":"medium",'
                        '"evidence_refs":[{"tool_name":"inspect_object_contract"}]}'
                    ),
                },
            )()

    class FakeOpenAI:
        def __init__(self, **kwargs):
            self.responses = FakeResponses()

    monkeypatch.setattr("openai.OpenAI", FakeOpenAI)
    with Session(engine) as session:
        task_id = add_dpo_review_task(session)
        task = session.get(Task, task_id)
        assert task is not None
        plan = _live_chat_plan(
            session=session,
            task=task,
            current_decisions=task.input_payload,
            missing_fields=[],
            request=ChatTurnRequest(message="How should I think about this pair?"),
            app_settings=Settings(openai_api_key="test-key", text_generation_live_calls_enabled=True),
        )

    assert len(captured_inputs) == 2
    assert "Available read-only tools" in captured_inputs[0][1]["content"]
    assert "Read-only tool receipts" in captured_inputs[1][1]["content"]
    assert "accepted_response_field" in captured_inputs[1][1]["content"]
    assert plan["status"] == "live_model_call"
    assert plan["tool_loop_used"] is True
    assert plan["tool_requests"][0]["tool_name"] == "inspect_object_contract"
    assert plan["tool_receipts"][0]["status"] == "completed"
    assert plan["tool_receipts"][0]["result"]["work_surface"]["field_contract"]["accepted_response_field"] == "chosen"
    assert plan["_observability"]["model_response_id"] == "resp_chat_tool_final"
    assert plan["_observability"]["first_model_response_id"] == "resp_chat_tool_request"
    assert plan["_observability"]["input_token_count"] == 180
    assert plan["_observability"]["output_token_count"] == 50
    assert plan["_observability"]["tool_loop_used"] is True
    assert plan["_observability"]["tool_names"] == ["inspect_object_contract"]


def test_live_chat_plan_retrieves_source_context_before_final_plan(monkeypatch):
    _, engine = build_client()
    captured_inputs = []

    class FakeResponses:
        def create(self, **kwargs):
            captured_inputs.append(kwargs["input"])
            if len(captured_inputs) == 1:
                return type(
                    "FakeResponse",
                    (),
                    {
                        "id": "resp_chat_retrieval_request",
                        "usage": {"input_tokens": 55, "output_tokens": 12},
                        "output_text": (
                            '{"tool_requests":[{"tool_name":"retrieve_source_context",'
                            '"query":"Market Street breakfast","scope":"family_private","limit":3,'
                            '"reason":"Need reviewed memory evidence before asking Adam."}]}'
                        ),
                    },
                )()
            return type(
                "FakeResponse",
                (),
                {
                    "id": "resp_chat_retrieval_final",
                    "usage": {"input_tokens": 65, "output_tokens": 18},
                    "output_text": (
                        '{"assistant_message":"I found related reviewed context and will ask one follow-up.",'
                        '"next_question":"Does this ticket connect to the Market Street breakfast memory?",'
                        '"field_updates":{},'
                        '"actions":[{"type":"ask_question","label":"Does this ticket connect to the Market Street breakfast memory?","requires_confirmation":false}],'
                        '"ready_to_submit":false,'
                        '"confidence":"medium"}'
                    ),
                },
            )()

    class FakeOpenAI:
        def __init__(self, **kwargs):
            self.responses = FakeResponses()

    monkeypatch.setattr("openai.OpenAI", FakeOpenAI)
    with Session(engine) as session:
        task_id = add_source_review_task(session)
        task = session.get(Task, task_id)
        assert task is not None
        session.add(
            EmbeddingRecord(
                target_type="memory",
                target_id="memory-market-breakfast",
                embedding_type="memory_text",
                modality="text",
                model_name="pending_text_embedding",
                input_checksum="checksum-market-breakfast",
                input_text="Market Street breakfast with brie, coffee, and family memory context.",
                input_preview="Market Street breakfast with brie, coffee, and family memory context.",
                status="ready_for_embedding",
                truth_status="adam_memory",
                boundary_snapshot={
                    "boundary_status": "reviewed",
                    "privacy_level": "family_private",
                    "retrievable_in_chat": True,
                    "searchable": True,
                    "reviewed_by": "adam",
                },
                metadata_json={"source": "photo_memory_review"},
            )
        )
        session.commit()
        plan = _live_chat_plan(
            session=session,
            task=task,
            current_decisions={},
            missing_fields=[],
            request=ChatTurnRequest(message="Find related context for this source."),
            app_settings=Settings(
                openai_api_key="test-key",
                text_generation_live_calls_enabled=True,
                embedding_live_calls_enabled=False,
            ),
        )

    final_prompt = captured_inputs[1][1]["content"]
    assert "Read-only tool receipts" in final_prompt
    assert "Market Street breakfast with brie" in final_prompt
    assert plan["tool_receipts"][0]["tool_name"] == "retrieve_source_context"
    assert plan["tool_receipts"][0]["result"]["results"][0]["truth_status"] == "adam_memory"
    assert plan["_observability"]["tool_names"] == ["retrieve_source_context"]


def test_live_chat_plan_can_inspect_evidence_corpus_before_final_plan(monkeypatch):
    _, engine = build_client()
    captured_inputs = []

    class FakeResponses:
        def create(self, **kwargs):
            captured_inputs.append(kwargs["input"])
            if len(captured_inputs) == 1:
                return type(
                    "FakeResponse",
                    (),
                    {
                        "id": "resp_chat_corpus_request",
                        "usage": {"input_tokens": 70, "output_tokens": 10},
                        "output_text": (
                            '{"tool_requests":[{"tool_name":"inspect_evidence_corpus",'
                            '"scope":"family_private","limit":5,'
                            '"reason":"Need the reviewed evidence inventory before choosing the next question."}]}'
                        ),
                    },
                )()
            return type(
                "FakeResponse",
                (),
                {
                    "id": "resp_chat_corpus_final",
                    "usage": {"input_tokens": 90, "output_tokens": 24},
                    "output_text": (
                        '{"assistant_message":"I checked the reviewed evidence corpus and found one approved voice source.",'
                        '"next_question":"Should this ticket use the approved cooking voice source as evidence?",'
                        '"field_updates":{},'
                        '"actions":[{"type":"ask_question","label":"Should this ticket use the approved cooking voice source as evidence?","requires_confirmation":false}],'
                        '"ready_to_submit":false,'
                        '"confidence":"medium",'
                        '"evidence_refs":[{"tool_name":"inspect_evidence_corpus","record_count":1}]}'
                    ),
                },
            )()

    class FakeOpenAI:
        def __init__(self, **kwargs):
            self.responses = FakeResponses()

    monkeypatch.setattr("openai.OpenAI", FakeOpenAI)
    with Session(engine) as session:
        task_id = add_source_review_task(session)
        task = session.get(Task, task_id)
        assert task is not None
        session.add(
            EmbeddingRecord(
                target_type="gold_voice",
                target_id="gold-cooking-voice",
                embedding_type="gold_voice_text",
                modality="text",
                model_name="pending_text_embedding",
                input_checksum="checksum-gold-cooking",
                input_text="Approved cooking voice evidence from Adam-reviewed training data.",
                input_preview="Approved cooking voice evidence from Adam-reviewed training data.",
                status="ready_for_embedding",
                truth_status="adam_expert_reconstruction",
                metadata_json={"source": "gold_voice_edit"},
            )
        )
        session.add(
            EmbeddingRecord(
                target_type="memory",
                target_id="machine-photo-draft",
                embedding_type="memory_text",
                modality="text",
                model_name="pending_text_embedding",
                input_checksum="checksum-machine-photo",
                input_text="Unreviewed machine draft that must not be used as truth.",
                input_preview="Unreviewed machine draft that must not be used as truth.",
                status="ready_for_embedding",
                truth_status="system_inference",
                metadata_json={"source": "photo_memory_machine_draft"},
            )
        )
        session.commit()
        plan = _live_chat_plan(
            session=session,
            task=task,
            current_decisions={},
            missing_fields=[],
            request=ChatTurnRequest(message="What evidence do we have for this ticket?"),
            app_settings=Settings(openai_api_key="test-key", text_generation_live_calls_enabled=True),
        )

    final_prompt = captured_inputs[1][1]["content"]
    receipt = plan["tool_receipts"][0]
    assert "inspect_evidence_corpus" in captured_inputs[0][1]["content"]
    assert "Read-only tool receipts" in final_prompt
    assert "Approved cooking voice evidence" in final_prompt
    assert "Unreviewed machine draft" in final_prompt
    assert receipt["tool_name"] == "inspect_evidence_corpus"
    assert receipt["result"]["corpus_type"] == "unified_evidence_embedding_corpus"
    assert receipt["result"]["record_count"] == 1
    assert receipt["result"]["excluded_count"] == 1
    assert receipt["result"]["records"][0]["index_policy"]["default_retrieval_candidate"] is True
    assert receipt["result"]["excluded"][0]["index_policy"]["default_retrieval_candidate"] is False
    assert "vector_values" not in receipt["result"]["records"][0]
    assert plan["_observability"]["tool_names"] == ["inspect_evidence_corpus"]


def test_live_chat_plan_can_plan_ranked_evidence_clusters_before_final_plan(monkeypatch):
    _, engine = build_client()
    captured_inputs = []

    class FakeResponses:
        def create(self, **kwargs):
            captured_inputs.append(kwargs["input"])
            if len(captured_inputs) == 1:
                return type(
                    "FakeResponse",
                    (),
                    {
                        "id": "resp_chat_cluster_request",
                        "usage": {"input_tokens": 82, "output_tokens": 16},
                        "output_text": (
                            '{"tool_requests":[{"tool_name":"plan_ranked_evidence_clusters",'
                            '"query":"cooking breakfast","scope":"family_private","limit":4,"per_cluster_limit":2,'
                            '"reason":"Need coherent reviewed evidence clusters before choosing the next question."}]}'
                        ),
                    },
                )()
            return type(
                "FakeResponse",
                (),
                {
                    "id": "resp_chat_cluster_final",
                    "usage": {"input_tokens": 110, "output_tokens": 26},
                    "output_text": (
                        '{"assistant_message":"I found a cooking-source cluster and will focus the next question there.",'
                        '"next_question":"Should this cooking source cluster drive the next prompt-pair candidate?",'
                        '"field_updates":{},'
                        '"actions":[{"type":"ask_question","label":"Should this cooking source cluster drive the next prompt-pair candidate?","requires_confirmation":false}],'
                        '"ready_to_submit":false,'
                        '"confidence":"medium",'
                        '"evidence_refs":[{"tool_name":"plan_ranked_evidence_clusters","cluster_key":"source_asset:test"}]}'
                    ),
                },
            )()

    class FakeOpenAI:
        def __init__(self, **kwargs):
            self.responses = FakeResponses()

    monkeypatch.setattr("openai.OpenAI", FakeOpenAI)
    with Session(engine) as session:
        task_id = add_source_review_task(session)
        task = session.get(Task, task_id)
        assert task is not None
        source_asset_id = task.input_payload["asset_id"]
        session.add(
            EmbeddingRecord(
                target_type="segment",
                target_id="segment-chat-cluster-1",
                embedding_type="retrieval_text",
                modality="text",
                model_name="text-embedding-3-small",
                input_checksum="checksum-chat-cluster-1",
                input_text="Cooking breakfast with coffee and brie in a reviewed source excerpt.",
                input_preview="Cooking breakfast with coffee and brie",
                status="embedded",
                vector_uri="local://embedding_vectors/chat-cluster-secret-1.json",
                vector_dims=3,
                provider_record_id="provider-chat-cluster-secret-1",
                truth_status="archival_source",
                metadata_json={"source": "source_review", "source_asset_id": source_asset_id, "source_segment_id": "segment-chat-cluster-1"},
            )
        )
        session.add(
            EmbeddingRecord(
                target_type="segment",
                target_id="segment-chat-cluster-2",
                embedding_type="retrieval_text",
                modality="text",
                model_name="text-embedding-3-small",
                input_checksum="checksum-chat-cluster-2",
                input_text="Breakfast and hunger shaped how the cooking voice should sound.",
                input_preview="Breakfast and hunger shaped the cooking voice",
                status="embedded",
                vector_uri="local://embedding_vectors/chat-cluster-secret-2.json",
                vector_dims=3,
                provider_record_id="provider-chat-cluster-secret-2",
                truth_status="archival_source",
                metadata_json={"source": "source_review", "source_asset_id": source_asset_id, "source_segment_id": "segment-chat-cluster-2"},
            )
        )
        session.commit()
        plan = _live_chat_plan(
            session=session,
            task=task,
            current_decisions={},
            missing_fields=[],
            request=ChatTurnRequest(message="Plan the evidence before asking me."),
            app_settings=Settings(
                openai_api_key="test-key",
                text_generation_live_calls_enabled=True,
                embedding_live_calls_enabled=False,
            ),
        )

    final_prompt = captured_inputs[1][1]["content"]
    receipt = plan["tool_receipts"][0]
    assert "plan_ranked_evidence_clusters" in captured_inputs[0][1]["content"]
    assert "Read-only tool receipts" in final_prompt
    assert "ranked_evidence_cluster_plan" in final_prompt
    assert "Cooking breakfast with coffee and brie" in final_prompt
    assert "chat-cluster-secret" not in final_prompt
    assert "provider-chat-cluster-secret" not in final_prompt
    assert receipt["tool_name"] == "plan_ranked_evidence_clusters"
    assert receipt["result"]["cluster_count"] == 1
    assert receipt["result"]["clusters"][0]["cluster_key"] == f"source_asset:{source_asset_id}"
    assert receipt["result"]["clusters"][0]["record_count"] == 2
    assert "document cluster" in receipt["result"]["clusters"][0]["planning_hint"]
    assert_forbidden_vector_keys_absent(receipt["result"])
    assert plan["_observability"]["tool_names"] == ["plan_ranked_evidence_clusters"]


def test_chat_can_inspect_work_queue_and_open_model_selected_ready_task(monkeypatch):
    client, engine = build_client()
    target_task_id = ""
    captured_inputs = []
    app.dependency_overrides[get_settings] = lambda: Settings(
        openai_api_key="test-key",
        text_generation_live_calls_enabled=True,
        chat_require_live_model=False,
    )

    class FakeResponses:
        def create(self, **kwargs):
            captured_inputs.append(kwargs["input"])
            if len(captured_inputs) == 1:
                return type(
                    "FakeResponse",
                    (),
                    {
                        "id": "resp_chat_queue_request",
                        "usage": {"input_tokens": 90, "output_tokens": 15},
                        "output_text": (
                            '{"tool_requests":[{"tool_name":"inspect_work_queue_plan",'
                            '"route":"dpo_review","limit":5,'
                            '"reason":"Need the board and ready DPO backlog before selecting a ticket."}]}'
                        ),
                    },
                )()
            return type(
                "FakeResponse",
                (),
                {
                    "id": "resp_chat_queue_final",
                    "usage": {"input_tokens": 130, "output_tokens": 32},
                    "output_text": (
                        '{"assistant_message":"I inspected the work queue and opened the highest-priority DPO ticket.",'
                        '"active_task_id":"' + target_task_id + '",'
                        '"next_question":"What should we decide about the chosen and rejected responses?",'
                        '"field_updates":{},'
                        '"actions":[{"type":"open_task","label":"Open selected DPO ticket","task_id":"' + target_task_id + '","requires_confirmation":false},'
                        '{"type":"ask_question","label":"What should we decide about the chosen and rejected responses?","requires_confirmation":false}],'
                        '"ready_to_submit":false,'
                        '"confidence":"medium",'
                        '"evidence_refs":[{"tool_name":"inspect_work_queue_plan","selected_task_id":"' + target_task_id + '"}]}'
                    ),
                },
            )()

    class FakeOpenAI:
        def __init__(self, **kwargs):
            self.responses = FakeResponses()

    monkeypatch.setattr("openai.OpenAI", FakeOpenAI)
    with Session(engine) as session:
        photo_task_id = add_photo_context_task(session)
        dpo_task_id = add_dpo_review_task(session)
        target_task_id = dpo_task_id

    response = client.post(
        "/api/chat/turn",
        json={"task_id": photo_task_id, "message": "Use the board to pick the next best ticket."},
    )

    assert response.status_code == 200
    body = response.json()
    assert "inspect_work_queue_plan" in captured_inputs[0][1]["content"]
    assert "work_queue_plan" in captured_inputs[1][1]["content"]
    assert dpo_task_id in captured_inputs[1][1]["content"]
    assert body["live_model_call_used"] is True
    assert body["active_task"]["id"] == dpo_task_id
    assert body["task_selection"]["selection_reason"] == "model_selected_open_task"
    assert body["task_selection"]["previous_task_id"] == photo_task_id
    assert body["task_selection"]["selected_task_id"] == dpo_task_id
    assert body["work_surface"]["kind"] == "prompt_response_review"
    assert body["field_updates"] == {}
    assert body["work_summary"]["tool_loop_used"] is True
    receipt = body["work_summary"]["tool_receipts"][0]
    assert receipt["tool_name"] == "inspect_work_queue_plan"
    assert receipt["result"]["ready_task_counts_by_route"]["dpo_review"] == 1
    assert receipt["result"]["recommended_open_task"]["task_id"] == dpo_task_id
    open_action = next(action for action in body["actions"] if action["type"] == "open_task")
    assert open_action["status"] == "executed"
    assert open_action["task_id"] == dpo_task_id
    with Session(engine) as session:
        chat_session = session.get(ChatSession, body["session_id"])
        action = session.get(ChatAction, open_action["id"])
        assert chat_session.active_task_id == dpo_task_id
        assert action.task_id == dpo_task_id
        assert action.status == "executed"
        assert action.validated_payload_json["target_task_id"] == dpo_task_id
        assert session.exec(select(TaskDraft)).all() == []


def test_chat_review_task_creation_requires_confirmation_and_records_task_receipt(monkeypatch):
    client, engine = build_client()
    app.dependency_overrides[get_settings] = lambda: Settings(
        openai_api_key="test-key",
        text_generation_live_calls_enabled=True,
        chat_require_live_model=False,
    )
    with Session(engine) as session:
        source_task_id = add_source_review_task(session)
        asset_id = add_reviewable_photo_asset(session)
        before_photo_context_count = len(session.exec(select(Task).where(Task.task_type == "photo_context")).all())

    monkeypatch.setattr("app.services.chat_operator.live_text_generation_ready", lambda app_settings: True)
    monkeypatch.setattr(
        "app.services.chat_operator._live_chat_plan",
        lambda **kwargs: {
            "assistant_message": "I can create a photo context review task from that retrieval-gap candidate.",
            "next_question": "Confirm before I create the review task?",
            "field_updates": {},
            "actions": [
                {
                    "type": "create_or_open_review_task",
                    "label": "Create photo context review task",
                    "review_task_type": "photo_context",
                    "asset_id": asset_id,
                    "source_query": "breakfast photo",
                    "candidate_match_quality": "weak_evidence_match",
                    "candidate_selection_reason": "chat_selected_retrieval_gap_cluster",
                    "requires_confirmation": True,
                }
            ],
            "ready_to_submit": False,
            "confidence": "medium",
        },
    )

    preview_turn = client.post(
        "/api/chat/turn",
        json={"task_id": source_task_id, "message": "Create a review task for that photo candidate."},
    )

    assert preview_turn.status_code == 200
    preview_body = preview_turn.json()
    pending_action = next(action for action in preview_body["actions"] if action["type"] == "create_or_open_review_task")
    assert pending_action["status"] == "pending_confirmation"
    assert pending_action["requires_confirmation"] is True
    assert preview_body["created_review_task"] is None
    with Session(engine) as session:
        assert len(session.exec(select(Task).where(Task.task_type == "photo_context")).all()) == before_photo_context_count
        action = session.get(ChatAction, pending_action["id"])
        assert action is not None
        assert action.status == "pending_confirmation"
        payload = action.validated_payload_json["review_task_creation_payload"]
        assert payload["asset_id"] == asset_id
        assert payload["source_query"] == "breakfast photo"
        assert payload["does_not_create_memory_claim"] is True

    action_preview = client.post(
        f"/api/chat/actions/{pending_action['id']}/preview",
        json={"session_id": preview_body["session_id"], "user_id": "adam"},
    )
    assert action_preview.status_code == 200
    assert action_preview.json()["can_confirm"] is True
    assert action_preview.json()["preview_payload"]["review_task_creation_payload"]["asset_id"] == asset_id

    confirmed = client.post(
        f"/api/chat/actions/{pending_action['id']}/confirm",
        json={"session_id": preview_body["session_id"], "user_id": "adam", "message": "confirm"},
    )

    assert confirmed.status_code == 200
    body = confirmed.json()
    created = body["created_review_task"]
    assert body["status"] == "review_task_creation_executed"
    assert created["created"] is True
    assert created["asset_id"] == asset_id
    assert body["active_task"]["id"] == created["task_id"]
    assert body["task_selection"]["selection_reason"] == "confirmed_review_task_creation"
    assert body["task_selection"]["review_task_created"] is True
    assert any(action["type"] == "create_or_open_review_task" and action["status"] == "executed" for action in body["actions"])
    with Session(engine) as session:
        tasks = session.exec(select(Task).where(Task.task_type == "photo_context")).all()
        assert len(tasks) == before_photo_context_count + 1
        task = session.get(Task, created["task_id"])
        assert task is not None
        assert task.input_payload["retrieval_gap_origin"]["query"] == "breakfast photo"
        assert task.input_payload["retrieval_gap_origin"]["truth_status"] == "no_claim"
        action = session.get(ChatAction, pending_action["id"])
        result = session.exec(select(ChatActionResult).where(ChatActionResult.action_id == pending_action["id"])).first()
        chat_session = session.get(ChatSession, body["session_id"])
        assert action.status == "executed"
        assert action.requires_confirmation is False
        assert action.task_id == created["task_id"]
        assert result is not None
        assert result.object_type == "task"
        assert result.object_id == created["task_id"]
        assert chat_session.active_task_id == created["task_id"]


def test_chat_photo_cluster_review_task_creation_accepts_source_photo_id(monkeypatch):
    client, engine = build_client()
    app.dependency_overrides[get_settings] = lambda: Settings(
        openai_api_key="test-key",
        text_generation_live_calls_enabled=True,
        chat_require_live_model=False,
    )
    with Session(engine) as session:
        source_task_id = add_source_review_task(session)
        asset_id = add_reviewable_photo_asset(session)

    monkeypatch.setattr("app.services.chat_operator.live_text_generation_ready", lambda app_settings: True)
    monkeypatch.setattr(
        "app.services.chat_operator._live_chat_plan",
        lambda **kwargs: {
            "assistant_message": "I can create a photo context review task from that photo cluster.",
            "next_question": "Confirm before I create the review task?",
            "field_updates": {},
            "actions": [
                {
                    "type": "create_or_open_review_task",
                    "label": "Create photo context review task",
                    "review_task_type": "photo_context",
                    "source_photo_id": asset_id,
                    "source_query": "family beach photo",
                    "candidate_match_quality": "weak_evidence_match",
                    "candidate_selection_reason": "chat_selected_photo_cluster",
                    "requires_confirmation": True,
                }
            ],
            "ready_to_submit": False,
            "confidence": "medium",
        },
    )

    preview_turn = client.post(
        "/api/chat/turn",
        json={"task_id": source_task_id, "message": "Create a review task for that photo evidence cluster."},
    )

    assert preview_turn.status_code == 200
    preview_body = preview_turn.json()
    pending_action = next(action for action in preview_body["actions"] if action["type"] == "create_or_open_review_task")
    with Session(engine) as session:
        action = session.get(ChatAction, pending_action["id"])
        payload = action.validated_payload_json["review_task_creation_payload"]
        assert payload["source_photo_id"] == asset_id
        assert payload["asset_id"] == asset_id
        assert payload["source_asset_id"] == asset_id
        assert chat_review_task_action_stale_reason(session=session, pending_action=action) is None

    confirmed = client.post(
        f"/api/chat/actions/{pending_action['id']}/confirm",
        json={"session_id": preview_body["session_id"], "user_id": "adam", "message": "confirm"},
    )

    assert confirmed.status_code == 200
    body = confirmed.json()
    created = body["created_review_task"]
    assert body["status"] == "review_task_creation_executed"
    assert created["asset_id"] == asset_id
    assert body["assistant_message"].endswith("from that evidence cluster.")


def test_chat_source_review_task_creation_requires_confirmation_and_records_task_receipt(monkeypatch):
    client, engine = build_client()
    app.dependency_overrides[get_settings] = lambda: Settings(
        openai_api_key="test-key",
        text_generation_live_calls_enabled=True,
        chat_require_live_model=False,
    )
    with Session(engine) as session:
        active_task_id = add_photo_context_task(session)
        source_asset_id, source_segment_id = add_reviewable_source_segment_without_task(session)
        before_source_review_count = len(session.exec(select(Task).where(Task.task_type == "text_segment_review")).all())

    monkeypatch.setattr("app.services.chat_operator.live_text_generation_ready", lambda app_settings: True)
    monkeypatch.setattr(
        "app.services.chat_operator._live_chat_plan",
        lambda **kwargs: {
            "assistant_message": "I can create a source review task from that source cluster.",
            "next_question": "Confirm before I create the source review task?",
            "field_updates": {},
            "actions": [
                {
                    "type": "create_or_open_review_task",
                    "label": "Create source review task",
                    "review_task_type": "source_review",
                    "source_asset_id": source_asset_id,
                    "source_segment_id": source_segment_id,
                    "source_title": "Cooking source cluster",
                    "source_query": "cooking source cluster",
                    "candidate_match_quality": "weak_evidence_match",
                    "candidate_selection_reason": "chat_selected_source_cluster",
                    "requires_confirmation": True,
                }
            ],
            "ready_to_submit": False,
            "confidence": "medium",
        },
    )

    preview_turn = client.post(
        "/api/chat/turn",
        json={"task_id": active_task_id, "message": "Create a review task for that source cluster."},
    )

    assert preview_turn.status_code == 200
    preview_body = preview_turn.json()
    pending_action = next(action for action in preview_body["actions"] if action["type"] == "create_or_open_review_task")
    assert pending_action["status"] == "pending_confirmation"
    assert pending_action["requires_confirmation"] is True
    assert preview_body["created_review_task"] is None
    with Session(engine) as session:
        assert len(session.exec(select(Task).where(Task.task_type == "text_segment_review")).all()) == before_source_review_count
        action = session.get(ChatAction, pending_action["id"])
        assert action is not None
        assert action.status == "pending_confirmation"
        payload = action.validated_payload_json["review_task_creation_payload"]
        assert payload["review_task_type"] == "source_review"
        assert payload["source_asset_id"] == source_asset_id
        assert payload["source_segment_id"] == source_segment_id
        assert payload["source_query"] == "cooking source cluster"
        assert payload["does_not_create_memory_claim"] is True

    action_preview = client.post(
        f"/api/chat/actions/{pending_action['id']}/preview",
        json={"session_id": preview_body["session_id"], "user_id": "adam"},
    )
    assert action_preview.status_code == 200
    preview_payload = action_preview.json()["preview_payload"]["review_task_creation_payload"]
    assert action_preview.json()["can_confirm"] is True
    assert preview_payload["review_task_type"] == "source_review"
    assert preview_payload["source_segment_id"] == source_segment_id

    confirmed = client.post(
        f"/api/chat/actions/{pending_action['id']}/confirm",
        json={"session_id": preview_body["session_id"], "user_id": "adam", "message": "confirm"},
    )

    assert confirmed.status_code == 200
    body = confirmed.json()
    created = body["created_review_task"]
    assert body["status"] == "review_task_creation_executed"
    assert created["created"] is True
    assert created["asset_id"] == source_asset_id
    assert body["active_task"]["id"] == created["task_id"]
    assert body["task_selection"]["selection_reason"] == "confirmed_review_task_creation"
    assert body["task_selection"]["review_task_created"] is True
    assert body["work_surface"]["kind"] == "source_review"
    assert any(action["type"] == "create_or_open_review_task" and action["status"] == "executed" for action in body["actions"])
    with Session(engine) as session:
        tasks = session.exec(select(Task).where(Task.task_type == "text_segment_review")).all()
        assert len(tasks) == before_source_review_count + 1
        task = session.get(Task, created["task_id"])
        assert task is not None
        assert task.target_type == "segment"
        assert task.target_id == source_segment_id
        assert task.input_payload["source_segment_id"] == source_segment_id
        assert task.input_payload["source_cluster_origin"]["query"] == "cooking source cluster"
        assert task.input_payload["source_cluster_origin"]["truth_status"] == "no_claim"
        assert task.input_payload["source_cluster_origin"]["not_memory_claim"] is True
        action = session.get(ChatAction, pending_action["id"])
        result = session.exec(select(ChatActionResult).where(ChatActionResult.action_id == pending_action["id"])).first()
        chat_session = session.get(ChatSession, body["session_id"])
        assert action.status == "executed"
        assert action.requires_confirmation is False
        assert action.task_id == created["task_id"]
        assert result is not None
        assert result.object_type == "task"
        assert result.object_id == created["task_id"]
        assert chat_session.active_task_id == created["task_id"]


def test_chat_source_review_task_creation_opens_existing_task_without_duplicate(monkeypatch):
    client, engine = build_client()
    app.dependency_overrides[get_settings] = lambda: Settings(
        openai_api_key="test-key",
        text_generation_live_calls_enabled=True,
        chat_require_live_model=False,
    )
    with Session(engine) as session:
        active_task_id = add_photo_context_task(session)
        existing_task_id = add_source_review_task(session)
        existing_task = session.get(Task, existing_task_id)
        assert existing_task is not None
        source_segment_id = existing_task.target_id
        before_source_review_count = len(session.exec(select(Task).where(Task.task_type == "text_segment_review")).all())

    monkeypatch.setattr("app.services.chat_operator.live_text_generation_ready", lambda app_settings: True)
    monkeypatch.setattr(
        "app.services.chat_operator._live_chat_plan",
        lambda **kwargs: {
            "assistant_message": "I found an existing source review task for that source cluster.",
            "next_question": "Confirm before I open it?",
            "field_updates": {},
            "actions": [
                {
                    "type": "create_or_open_review_task",
                    "label": "Open existing source review task",
                    "review_task_type": "source_review",
                    "source_segment_id": source_segment_id,
                    "source_query": "journal source cluster",
                    "candidate_match_quality": "existing_ready_task",
                    "candidate_selection_reason": "chat_selected_source_cluster",
                    "requires_confirmation": True,
                }
            ],
            "ready_to_submit": False,
            "confidence": "medium",
        },
    )

    preview_turn = client.post(
        "/api/chat/turn",
        json={"task_id": active_task_id, "message": "Open or create the source review task for that cluster."},
    )
    assert preview_turn.status_code == 200
    pending_action = next(action for action in preview_turn.json()["actions"] if action["type"] == "create_or_open_review_task")

    confirmed = client.post(
        f"/api/chat/actions/{pending_action['id']}/confirm",
        json={"session_id": preview_turn.json()["session_id"], "user_id": "adam", "message": "confirm"},
    )

    assert confirmed.status_code == 200
    body = confirmed.json()
    created = body["created_review_task"]
    assert created["created"] is False
    assert created["task_id"] == existing_task_id
    assert body["active_task"]["id"] == existing_task_id
    assert body["task_selection"]["review_task_created"] is False
    with Session(engine) as session:
        tasks = session.exec(select(Task).where(Task.task_type == "text_segment_review")).all()
        assert len(tasks) == before_source_review_count
        result = session.exec(select(ChatActionResult).where(ChatActionResult.action_id == pending_action["id"])).first()
        assert result is not None
        assert result.object_id == existing_task_id


def test_live_chat_plan_can_preview_source_pair_generation_before_final_plan(monkeypatch):
    _, engine = build_client()
    captured_inputs = []

    class FakeResponses:
        def create(self, **kwargs):
            captured_inputs.append(kwargs["input"])
            if len(captured_inputs) == 1:
                return type(
                    "FakeResponse",
                    (),
                    {
                        "id": "resp_chat_pair_preview_request",
                        "usage": {"input_tokens": 90, "output_tokens": 14},
                        "output_text": (
                            '{"tool_requests":[{"tool_name":"preview_source_pair_generation",'
                            '"reason":"Need candidate counts and evidence policy before suggesting pair creation."}]}'
                        ),
                    },
                )()
            return type(
                "FakeResponse",
                (),
                {
                    "id": "resp_chat_pair_preview_final",
                    "usage": {"input_tokens": 120, "output_tokens": 28},
                    "output_text": (
                        '{"assistant_message":"I previewed source pair generation and found one evidence-backed candidate.",'
                        '"next_question":"Should I use this source span to create a prompt-pair ticket for Adam review?",'
                        '"field_updates":{},'
                        '"actions":[{"type":"ask_question","label":"Should I use this source span to create a prompt-pair ticket for Adam review?","requires_confirmation":false}],'
                        '"ready_to_submit":false,'
                        '"confidence":"medium",'
                        '"evidence_refs":[{"tool_name":"preview_source_pair_generation","projected_created_pair_count":1}]}'
                    ),
                },
            )()

    class FakeOpenAI:
        def __init__(self, **kwargs):
            self.responses = FakeResponses()

    monkeypatch.setattr("openai.OpenAI", FakeOpenAI)
    with Session(engine) as session:
        task_id = add_source_review_task(session)
        task = session.get(Task, task_id)
        assert task is not None
        plan = _live_chat_plan(
            session=session,
            task=task,
            current_decisions={
                "voice_mode": "father_to_adam",
                "context": "Adam marked this journal passage as usable voice evidence.",
                "source_spans": [
                    {"span_type": "prompt", "text": "What did the train sound like?"},
                    {
                        "span_type": "response",
                        "text": "It was a dark iron sound, and it stayed in the room after the train was gone.",
                    },
                ],
            },
            missing_fields=[],
            request=ChatTurnRequest(message="Can this source become training data?"),
            app_settings=Settings(openai_api_key="test-key", text_generation_live_calls_enabled=True),
        )

    final_prompt = captured_inputs[1][1]["content"]
    receipt = plan["tool_receipts"][0]
    assert "preview_source_pair_generation" in captured_inputs[0][1]["content"]
    assert "Read-only tool receipts" in final_prompt
    assert "source_review_generate_pairs_preview" in final_prompt
    assert "candidate_pairs_require_source_segment_chunk_span_or_excerpt_hash" in final_prompt
    assert receipt["tool_name"] == "preview_source_pair_generation"
    assert receipt["result"]["does_not_mutate_state"] is True
    assert receipt["result"]["projected_created_pair_count"] == 1
    assert receipt["result"]["projected_held_pair_count"] == 0
    assert receipt["result"]["projected_evidence_linked_pair_count"] == 1
    assert receipt["result"]["created_pairs_preview"][0]["source_evidence_status"] == "evidence_linked"
    assert plan["_observability"]["tool_names"] == ["preview_source_pair_generation"]


def test_source_pair_generation_preview_can_use_live_model_without_mutation(monkeypatch):
    _, engine = build_client()
    captured_inputs = []

    class FakeResponses:
        def create(self, **kwargs):
            captured_inputs.append(kwargs["input"])
            return type(
                "FakeResponse",
                (),
                {
                    "id": "resp_pair_generation_preview",
                    "usage": {"input_tokens": 100, "output_tokens": 40},
                    "output_text": (
                        '[{"artifact_mode":"sft",'
                        '"prompt":"What did the train sound like?",'
                        '"content":"It was a dark iron sound, and it stayed in the room after the train was gone.",'
                        '"voice_mode":"father_to_adam",'
                        '"synthetic":true,'
                        '"context":"Adam is reviewing this as source-grounded voice evidence."}]'
                    ),
                },
            )()

    class FakeOpenAI:
        def __init__(self, **kwargs):
            self.responses = FakeResponses()

    monkeypatch.setattr("openai.OpenAI", FakeOpenAI)
    with Session(engine) as session:
        task_id = add_source_review_task(session)
        task = session.get(Task, task_id)
        assert task is not None
        before_task_count = len(session.exec(select(Task)).all())
        preview = preview_make_gold_tasks_from_review(
            session=session,
            task=task,
            decisions={"voice_mode": "father_to_adam", "context": "Adam is reviewing this source."},
            app_settings=Settings(openai_api_key="test-key", text_generation_live_calls_enabled=True),
            allow_live_model=True,
        )
        after_task_count = len(session.exec(select(Task)).all())

    assert captured_inputs
    assert preview["does_not_mutate_state"] is True
    assert preview["live_model_call_used"] is True
    assert preview["no_live_model_call"] is False
    assert preview["strategy_counts"] == {"live_model_pair_generation": 1}
    assert preview["projected_created_pair_count"] == 1
    assert preview["projected_evidence_linked_pair_count"] == 1
    assert preview["created_pairs_preview"][0]["strategy"] == "live_model_pair_generation"
    assert preview["created_pairs_preview"][0]["source_evidence_status"] == "evidence_linked"
    assert before_task_count == after_task_count


def test_live_chat_plan_filters_actions_to_allowed_draft_fields(monkeypatch):
    client, engine = build_client()
    with Session(engine) as session:
        task_id = add_photo_context_task(session)

    monkeypatch.setattr("app.services.chat_operator.live_text_generation_ready", lambda app_settings: True)
    monkeypatch.setattr(
        "app.services.chat_operator._live_chat_plan",
        lambda **kwargs: {
            "assistant_message": "I captured the visible fact. What privacy level should this have?",
            "next_question": "What privacy level should this have?",
            "field_updates": {
                "visual_description_correction": "Charles is by the water.",
                "delete_everything": True,
            },
            "actions": [{"type": "update_task_draft", "label": "Update draft", "requires_confirmation": False}],
            "ready_to_submit": False,
            "_observability": {
                "input_token_count": 123,
                "output_token_count": 45,
                "latency_ms": 678,
                "model_response_id": "resp_live_chat_test",
                "image_pixels_included": False,
            },
        },
    )

    response = client.post("/api/chat/turn", json={"task_id": task_id, "message": "Charles is by the water."})

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "live_model_call"
    assert body["live_model_call_used"] is True
    assert body["field_updates"] == {"visual_description_correction": "Charles is by the water."}
    with Session(engine) as session:
        draft = session.exec(select(TaskDraft).where(TaskDraft.task_id == task_id)).first()
        assistant_turn = session.exec(select(ChatTurn).where(ChatTurn.task_id == task_id).where(ChatTurn.role == "assistant")).first()
        assert draft.decisions == {"visual_description_correction": "Charles is by the water."}
        assert assistant_turn is not None
        assert assistant_turn.input_token_count == 123
        assert assistant_turn.output_token_count == 45
        assert assistant_turn.latency_ms == 678
        assert assistant_turn.metadata_json["model_response_id"] == "resp_live_chat_test"


def test_chat_response_summarizes_live_tool_receipts(monkeypatch):
    client, engine = build_client()
    with Session(engine) as session:
        task_id = add_dpo_review_task(session)

    monkeypatch.setattr("app.services.chat_operator.live_text_generation_ready", lambda app_settings: True)
    monkeypatch.setattr(
        "app.services.chat_operator._live_chat_plan",
        lambda **kwargs: {
            "assistant_message": "I inspected the DPO contract before deciding.",
            "next_question": "What should the new chosen response say?",
            "field_updates": {},
            "actions": [
                {
                    "type": "ask_question",
                    "label": "What should the new chosen response say?",
                    "requires_confirmation": False,
                }
            ],
            "ready_to_submit": False,
            "confidence": "medium",
            "tool_loop_used": True,
            "tool_receipts": [
                {
                    "tool_name": "inspect_object_contract",
                    "status": "completed",
                    "result": {"work_surface": {"kind": "prompt_response_review"}},
                }
            ],
            "_observability": {
                "input_token_count": 21,
                "output_token_count": 12,
                "latency_ms": 34,
                "model_response_id": "resp_tool_summary",
                "tool_loop_used": True,
                "tool_names": ["inspect_object_contract"],
            },
        },
    )

    response = client.post("/api/chat/turn", json={"task_id": task_id, "message": "Look at the DPO schema first."})

    assert response.status_code == 200
    body = response.json()
    assert body["live_model_call_used"] is True
    assert body["work_summary"]["summary_type"] == "model_plan_contract"
    assert body["work_summary"]["tool_loop_used"] is True
    assert body["work_summary"]["tool_receipts"][0]["tool_name"] == "inspect_object_contract"
    with Session(engine) as session:
        assistant_turn = session.exec(select(ChatTurn).where(ChatTurn.task_id == task_id).where(ChatTurn.role == "assistant")).first()
        assert assistant_turn is not None
        assert assistant_turn.metadata_json["tool_loop_used"] is True
        assert assistant_turn.metadata_json["tool_names"] == ["inspect_object_contract"]
        assert assistant_turn.metadata_json["plan_contract"]["tool_loop_used"] is True


def test_chat_sanitizes_long_model_field_updates_and_array_lengths(monkeypatch):
    client, engine = build_client()
    with Session(engine) as session:
        task_id = add_photo_context_task(session)

    long_description = "Charles by the water. " * 400
    too_many_people = [f"Person {index}" for index in range(40)]
    monkeypatch.setattr("app.services.chat_operator.live_text_generation_ready", lambda app_settings: True)
    monkeypatch.setattr(
        "app.services.chat_operator._live_chat_plan",
        lambda **kwargs: {
            "assistant_message": "I captured the visible facts.",
            "next_question": "What boundary should this have?",
            "field_updates": {
                "visual_description_correction": long_description,
                "visible_people": too_many_people,
            },
            "actions": [{"type": "update_task_draft", "label": "Update draft", "requires_confirmation": False}],
            "ready_to_submit": False,
        },
    )

    response = client.post("/api/chat/turn", json={"task_id": task_id, "message": "Capture this."})

    assert response.status_code == 200
    body = response.json()
    assert len(body["field_updates"]["visual_description_correction"]) <= 6000
    assert body["field_updates"]["visual_description_correction"].endswith("[truncated]")
    assert body["field_updates"]["visible_people"] == too_many_people[:25]
    with Session(engine) as session:
        draft = session.exec(select(TaskDraft).where(TaskDraft.task_id == task_id)).first()
        assert draft.decisions["visual_description_correction"] == body["field_updates"]["visual_description_correction"]
        assert draft.decisions["visible_people"] == too_many_people[:25]


def test_chat_accepts_prd_style_model_plan_contract(monkeypatch, caplog):
    caplog.set_level(logging.INFO, logger="app.services.chat_operator")
    client, engine = build_client()
    with Session(engine) as session:
        task_id = add_photo_context_task(session)

    monkeypatch.setattr("app.services.chat_operator.live_text_generation_ready", lambda app_settings: True)
    monkeypatch.setattr(
        "app.services.chat_operator._live_chat_plan",
        lambda **kwargs: {
            "assistant_message": "I captured that visible correction.",
            "next_question": "What boundary should this photo have?",
            "work_surface": {"kind": "photo_review"},
            "active_task_id": task_id,
            "needs_user_response": True,
            "draft_updates": {
                "visual_description_correction": "Charles is standing near the water.",
            },
            "proposed_actions": [
                {"action_type": "update_task_draft", "label": "Capture visible correction", "requires_confirmation": False},
                {"action_type": "delete_everything", "label": "Invalid action", "requires_confirmation": True},
            ],
            "confidence": "medium",
            "uncertainties": ["Identity still needs Adam confirmation."],
            "evidence_refs": [{"type": "task", "id": task_id}],
            "ui_hints": {"preview": "field_diff"},
            "ready_to_submit": False,
        },
    )

    response = client.post("/api/chat/turn", json={"task_id": task_id, "message": "It is Charles near water."})

    assert response.status_code == 200
    body = response.json()
    assert body["field_updates"] == {"visual_description_correction": "Charles is standing near the water."}
    assert any(action["type"] == "update_task_draft" for action in body["actions"])
    assert all(action["type"] != "delete_everything" for action in body["actions"])
    assert "delete_everything" in body["error"]
    assert body["work_summary"]["summary_type"] == "model_plan_contract"
    assert body["work_summary"]["confidence"] == "medium"
    assert body["work_summary"]["uncertainties"] == ["Identity still needs Adam confirmation."]
    assert body["work_summary"]["evidence_refs"] == [{"type": "task", "id": task_id}]
    assert body["work_summary"]["ui_hints"] == {"preview": "field_diff"}
    assert body["work_summary"]["rejected_actions"][0]["type"] == "delete_everything"
    assert any(getattr(record, "chat_event", None) == "action_rejected" for record in caplog.records)
    with Session(engine) as session:
        draft = session.exec(select(TaskDraft).where(TaskDraft.task_id == task_id)).first()
        assistant_turn = session.exec(select(ChatTurn).where(ChatTurn.task_id == task_id).where(ChatTurn.role == "assistant")).first()
        assert draft.decisions["visual_description_correction"] == "Charles is standing near the water."
        assert assistant_turn.metadata_json["plan_contract"]["confidence"] == "medium"


def test_chat_records_semantic_photo_update_action_as_draft_write(monkeypatch):
    client, engine = build_client()
    with Session(engine) as session:
        task_id = add_photo_context_task(session)

    monkeypatch.setattr("app.services.chat_operator.live_text_generation_ready", lambda app_settings: True)
    monkeypatch.setattr(
        "app.services.chat_operator._live_chat_plan",
        lambda **kwargs: {
            "assistant_message": "I staged that photo context in the draft.",
            "next_question": "What boundary should this photo have?",
            "draft_updates": {
                "visual_description_correction": "Charles is standing near the water.",
                "adam_context_note": "Adam photo context: This was a family beach day.",
            },
            "proposed_actions": [
                {"action_type": "update_photo_context", "label": "Update photo context draft", "requires_confirmation": False}
            ],
            "ready_to_submit": False,
        },
    )

    response = client.post("/api/chat/turn", json={"task_id": task_id, "message": "This was a family beach day."})

    assert response.status_code == 200
    body = response.json()
    assert [action["type"] for action in body["actions"] if action["type"] == "update_task_draft"] == []
    semantic_action = next(action for action in body["actions"] if action["type"] == "update_photo_context")
    assert semantic_action["status"] == "executed"
    with Session(engine) as session:
        draft = session.exec(select(TaskDraft).where(TaskDraft.task_id == task_id)).first()
        chat_action = session.get(ChatAction, semantic_action["id"])
        result = session.exec(select(ChatActionResult).where(ChatActionResult.action_id == semantic_action["id"])).first()
        assert draft.decisions["visual_description_correction"] == "Charles is standing near the water."
        assert chat_action.action_type == "update_photo_context"
        assert chat_action.validated_payload_json["semantic_action_type"] == "update_photo_context"
        assert result.object_type == "task_draft"
        assert result.after_json["decisions"]["adam_context_note"] == "Adam photo context: This was a family beach day."


def test_chat_drops_draft_update_action_without_validated_field_updates(monkeypatch):
    client, engine = build_client()
    with Session(engine) as session:
        task_id = add_photo_context_task(session)

    monkeypatch.setattr("app.services.chat_operator.live_text_generation_ready", lambda app_settings: True)
    monkeypatch.setattr(
        "app.services.chat_operator._live_chat_plan",
        lambda **kwargs: {
            "assistant_message": "What boundary should this photo have?",
            "next_question": "What boundary should this photo have?",
            "field_updates": {},
            "actions": [{"type": "update_task_draft", "label": "Update draft", "requires_confirmation": False}],
            "ready_to_submit": False,
        },
    )

    response = client.post("/api/chat/turn", json={"task_id": task_id, "message": "Maybe."})

    assert response.status_code == 200
    body = response.json()
    assert [action["type"] for action in body["actions"]] == ["ask_question"]
    with Session(engine) as session:
        draft_actions = session.exec(
            select(ChatAction).where(ChatAction.task_id == task_id).where(ChatAction.action_type == "update_task_draft")
        ).all()
        assert draft_actions == []


def test_chat_sanitizes_unconfirmed_model_action_claim(monkeypatch):
    client, engine = build_client()
    with Session(engine) as session:
        task_id = add_complete_gold_task(session)

    monkeypatch.setattr("app.services.chat_operator.live_text_generation_ready", lambda app_settings: True)
    monkeypatch.setattr(
        "app.services.chat_operator._live_chat_plan",
        lambda **kwargs: {
            "assistant_message": "Submitted. I moved the ticket forward.",
            "next_question": "",
            "draft_updates": {},
            "proposed_actions": [{"action_type": "submit_task", "label": "Submit ticket", "requires_confirmation": True}],
            "ready_to_submit": True,
        },
    )

    response = client.post("/api/chat/turn", json={"task_id": task_id, "message": "ready"})

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "sanitized_unconfirmed_action_claim"
    assert "Submitted" not in body["assistant_message"]
    assert "Confirm" in body["assistant_message"]
    assert body["submitted_annotation"] is None
    assert any(action["type"] == "submit_task" and action["status"] == "pending_confirmation" for action in body["actions"])
    with Session(engine) as session:
        assert session.get(Task, task_id).status == "ready"
        assert session.exec(select(Annotation)).first() is None


def test_chat_normalizes_mark_candidate_approved_to_confirmable_submit(monkeypatch):
    client, engine = build_client()
    with Session(engine) as session:
        task_id = add_complete_gold_task(session)

    monkeypatch.setattr("app.services.chat_operator.live_text_generation_ready", lambda app_settings: True)
    monkeypatch.setattr(
        "app.services.chat_operator._live_chat_plan",
        lambda **kwargs: {
            "assistant_message": "I think this approved candidate is ready for submit.",
            "next_question": "",
            "draft_updates": {},
            "proposed_actions": [
                {"action_type": "mark_candidate_approved", "label": "Approve candidate", "requires_confirmation": True}
            ],
            "ready_to_submit": True,
        },
    )

    response = client.post("/api/chat/turn", json={"task_id": task_id, "message": "Approve this candidate."})

    assert response.status_code == 200
    body = response.json()
    assert all(action["type"] != "mark_candidate_approved" for action in body["actions"])
    submit_action = next(action for action in body["actions"] if action["type"] == "submit_task")
    assert submit_action["requires_confirmation"] is True
    assert submit_action["status"] == "pending_confirmation"

    preview = client.post(
        f"/api/chat/actions/{submit_action['id']}/preview",
        json={"session_id": body["session_id"], "user_id": "adam"},
    )

    assert preview.status_code == 200
    assert preview.json()["can_confirm"] is True
    assert preview.json()["preview_payload"]["submit_payload"]["task_id"] == task_id


def test_chat_normalizes_mark_candidate_rejected_to_draft_update(monkeypatch):
    client, engine = build_client()
    with Session(engine) as session:
        task_id = add_dpo_review_task(session)

    monkeypatch.setattr("app.services.chat_operator.live_text_generation_ready", lambda app_settings: True)
    monkeypatch.setattr(
        "app.services.chat_operator._live_chat_plan",
        lambda **kwargs: {
            "assistant_message": "I staged the reject-pair rationale in the draft.",
            "next_question": "Should we create a better chosen response from scratch?",
            "draft_updates": {
                "operator_candidate_triage_intent": "reject_pair",
                "failure_modes": ["both_candidates_unusable"],
                "context": "Adam rejected both sides as unusable.",
            },
            "proposed_actions": [
                {"action_type": "mark_candidate_rejected", "label": "Reject pair", "requires_confirmation": True}
            ],
            "ready_to_submit": False,
        },
    )

    response = client.post("/api/chat/turn", json={"task_id": task_id, "message": "Reject both; neither sounds right."})

    assert response.status_code == 200
    body = response.json()
    assert all(action["type"] != "mark_candidate_rejected" for action in body["actions"])
    draft_action = next(action for action in body["actions"] if action["type"] == "update_task_draft")
    assert draft_action["status"] == "executed"
    with Session(engine) as session:
        draft = session.exec(select(TaskDraft).where(TaskDraft.task_id == task_id)).first()
        assert draft.decisions["operator_candidate_triage_intent"] == "reject_pair"
        assert "both_candidates_unusable" in draft.decisions["failure_modes"]


def test_chat_session_can_be_reloaded_from_api():
    client, engine = build_client()
    with Session(engine) as session:
        task_id = add_photo_context_task(session)

    turn = client.post(
        "/api/chat/turn",
        json={"task_id": task_id, "message": "This is Charles near the water."},
    )
    assert turn.status_code == 200
    session_id = turn.json()["session_id"]

    restored = client.get(f"/api/chat/sessions/{session_id}")

    assert restored.status_code == 200
    body = restored.json()
    assert body["session"]["id"] == session_id
    assert body["session"]["active_task_id"] == task_id
    assert [item["role"] for item in body["turns"]] == ["user", "assistant"]
    assert any(action["action_type"] == "update_task_draft" for action in body["actions"])
    assert body["latest_response"]["session_id"] == session_id
    assert body["latest_response"]["active_task"]["id"] == task_id
    assert body["latest_response"]["work_surface"]["kind"] == "photo_review"
    assert "visual_description_correction" in body["latest_response"]["draft_decisions"]
    assert body["latest_response"]["field_diffs"][0]["field"] == "visual_description_correction"


def test_chat_live_turn_hydrates_recent_history_from_session_without_client_history(monkeypatch):
    client, engine = build_client()
    captured = {}
    with Session(engine) as session:
        task_id = add_photo_context_task(session)

    first = client.post(
        "/api/chat/turn",
        json={"task_id": task_id, "message": "This is Charles near the water."},
    )
    assert first.status_code == 200
    session_id = first.json()["session_id"]

    monkeypatch.setattr("app.services.chat_operator.live_text_generation_ready", lambda app_settings: True)

    def fake_live_plan(**kwargs):
        captured["history"] = [(item.role, item.content) for item in kwargs["request"].history]
        return {
            "assistant_message": "I used the prior session context.",
            "next_question": "What boundary should this photo have?",
            "field_updates": {},
            "actions": [{"type": "ask_question", "label": "Ask boundary", "requires_confirmation": False}],
            "ready_to_submit": False,
        }

    monkeypatch.setattr("app.services.chat_operator._live_chat_plan", fake_live_plan)

    second = client.post(
        "/api/chat/turn",
        json={"task_id": task_id, "session_id": session_id, "message": "What should we ask next?", "history": []},
    )

    assert second.status_code == 200
    assert captured["history"][0] == ("user", "This is Charles near the water.")
    assert captured["history"][1][0] == "assistant"
    assert "photo note" in captured["history"][1][1] or "photo context" in captured["history"][1][1]


def test_chat_sessions_can_be_created_and_listed():
    client, engine = build_client()
    with Session(engine) as session:
        task_id = add_photo_context_task(session)

    created = client.post(
        "/api/chat/sessions",
        json={"user_id": "adam", "mode": "chat", "active_task_id": task_id, "title": "Fresh review"},
    )

    assert created.status_code == 200
    body = created.json()
    session_id = body["session"]["id"]
    assert body["session"]["active_task_id"] == task_id
    assert body["session"]["title"] == "Fresh review"
    assert body["turns"] == []
    assert body["actions"] == []
    assert body["latest_response"] is None

    listed = client.get("/api/chat/sessions?user_id=adam")

    assert listed.status_code == 200
    sessions = listed.json()["sessions"]
    assert any(item["id"] == session_id and item["active_task_id"] == task_id for item in sessions)


def test_chat_session_create_rejects_unknown_active_task():
    client, _ = build_client()

    created = client.post(
        "/api/chat/sessions",
        json={"user_id": "adam", "mode": "chat", "active_task_id": "missing-task"},
    )

    assert created.status_code == 404
    assert created.json()["detail"] == "Active task not found."


def test_chat_routes_to_requested_dpo_pair_from_selected_photo():
    client, engine = build_client()
    with Session(engine) as session:
        photo_task_id = add_photo_context_task(session)
        dpo_task_id = add_dpo_review_task(session)

    response = client.post(
        "/api/chat/turn",
        json={"task_id": photo_task_id, "message": "Show me the DPO pairs."},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["active_task"]["id"] == dpo_task_id
    assert body["task_selection"]["requested_route"] == "dpo_review"
    assert body["task_selection"]["selection_reason"] == "routed_from_chat_intent"
    assert body["field_updates"] == {}
    assert "chosen and rejected responses" in body["next_question"]
    with Session(engine) as session:
        chat_session = session.get(ChatSession, body["session_id"])
        assert chat_session.active_task_id == dpo_task_id


def test_chat_routes_to_source_review_from_natural_language():
    client, engine = build_client()
    with Session(engine) as session:
        source_task_id = add_source_review_task(session)
        add_photo_context_task(session)

    response = client.post("/api/chat/turn", json={"message": "Let's work on source excerpts."})

    assert response.status_code == 200
    body = response.json()
    assert body["active_task"]["id"] == source_task_id
    assert body["task_selection"]["requested_route"] == "source_review"
    assert body["task_selection"]["selection_reason"] == "routed_from_chat_intent"
    assert "source excerpt" in body["next_question"]


def test_chat_source_review_answer_extracts_structured_downstream_fields():
    client, engine = build_client()
    with Session(engine) as session:
        task_id = add_source_review_task(session)

    response = client.post(
        "/api/chat/turn",
        json={
            "task_id": task_id,
            "message": (
                "This is a journal excerpt with Charles voice. Charles wrote it. "
                "Truth status: adam expert reconstruction. It is family private and ready for processing. "
                "Use it for voice context and grounded generation; generate pairs. "
                "Context: it captures the cadence around family travel. Date: 1986. "
                "Not sure whether the exact town is right."
            ),
        },
    )

    assert response.status_code == 200
    body = response.json()
    updates = body["field_updates"]
    assert updates["source_genre"] == "journal"
    assert updates["authorship"] == "charles"
    assert updates["truth_status"] == "adam_expert_reconstruction"
    assert updates["voice_presence"] == "charles_voice"
    assert updates["usable_for_voice_context"] == "yes"
    assert updates["usable_for_grounded_generation"] == "yes"
    assert updates["generate_pairs_on_submit"] == "yes"
    assert updates["prompt_pair_potential"] == "high"
    assert updates["privacy_level"] == "family_private"
    assert updates["ready_for_processing"] == "yes"
    assert updates["date_or_range"] == "1986"
    assert "family travel" in updates["adam_context_note"]
    assert any("exact town" in question for question in updates["open_questions"])
    assert "source-review structure" in body["assistant_message"]
    with Session(engine) as session:
        draft = session.exec(select(TaskDraft).where(TaskDraft.task_id == task_id)).first()
        assert draft.decisions["generate_pairs_on_submit"] == "yes"
        assert draft.decisions["privacy_level"] == "family_private"


def test_chat_source_review_can_preview_confirm_and_preserve_source_excerpt_id():
    client, engine = build_client()
    with Session(engine) as session:
        task_id = add_source_review_task(session)
        source_segment_id = session.get(Task, task_id).target_id

    review = client.post(
        "/api/chat/turn",
        json={
            "task_id": task_id,
            "message": (
                "This is a journal excerpt with Charles voice. Charles wrote it. "
                "Truth status: archival source. It is family private and ready for processing. "
                "Use it for voice context and grounded generation; generate pairs. "
                "Context: it captures the cadence around family travel."
            ),
        },
    )
    assert review.status_code == 200
    review_body = review.json()
    assert review_body["ready_to_submit"] is False

    preview = client.post(
        "/api/chat/turn",
        json={"task_id": task_id, "session_id": review_body["session_id"], "message": "ready"},
    )
    assert preview.status_code == 200
    preview_body = preview.json()
    assert preview_body["ready_to_submit"] is True
    assert preview_body["field_updates"] == {}
    submit_action_id = next(action["id"] for action in preview_body["actions"] if action["type"] == "submit_task")

    submitted = client.post(
        "/api/chat/turn",
        json={
            "task_id": task_id,
            "session_id": preview_body["session_id"],
            "message": "ready",
            "confirm_submit": True,
            "confirm_action_id": submit_action_id,
        },
    )

    assert submitted.status_code == 200
    body = submitted.json()
    assert body["submitted_annotation"]["task_id"] == task_id
    with Session(engine) as session:
        annotation = session.exec(select(Annotation).where(Annotation.task_id == task_id)).first()
        profile = session.exec(select(MetadataProfile).where(MetadataProfile.target_id == source_segment_id)).first()
        assert annotation is not None
        assert annotation.target_id == source_segment_id
        assert annotation.creates_or_updates["reviewed_segment_id"] == source_segment_id
        provenance = annotation.decisions["chat_provenance"]
        assert provenance["chat_session_id"] == review_body["session_id"]
        assert provenance["preview_turn_id"] == preview_body["turn_id"]
        assert provenance["confirmation_turn_id"] == body["turn_id"]
        assert provenance["source_refs"]["target_type"] == "segment"
        assert provenance["source_refs"]["target_id"] == source_segment_id
        assert profile is not None
        assert profile.source_annotation_id == annotation.id
        assert profile.target_id == source_segment_id


def test_chat_submit_confirmation_opens_next_same_route_task_with_receipt():
    client, engine = build_client()
    with Session(engine) as session:
        task_id = add_source_review_task(session)
        next_task_id = add_source_review_task(session)

    review = client.post(
        "/api/chat/turn",
        json={
            "task_id": task_id,
            "message": (
                "This is a journal excerpt with Charles voice. Charles wrote it. "
                "Truth status: archival source. It is family private and ready for processing. "
                "Use it for voice context and grounded generation. "
                "Context: it captures family travel cadence."
            ),
        },
    )
    assert review.status_code == 200
    preview = client.post(
        "/api/chat/turn",
        json={"task_id": task_id, "session_id": review.json()["session_id"], "message": "ready"},
    )
    assert preview.status_code == 200
    preview_body = preview.json()
    submit_action_id = next(action["id"] for action in preview_body["actions"] if action["type"] == "submit_task")

    submitted = client.post(
        "/api/chat/turn",
        json={
            "task_id": task_id,
            "session_id": preview_body["session_id"],
            "message": "ready",
            "confirm_submit": True,
            "confirm_action_id": submit_action_id,
        },
    )

    assert submitted.status_code == 200
    body = submitted.json()
    assert body["submitted_annotation"]["task_id"] == task_id
    assert body["ready_to_submit"] is False
    assert body["submit_payload"] is None
    assert body["active_task"]["id"] == next_task_id
    assert body["task_selection"]["selection_reason"] == "batch_continuation_after_submit"
    assert body["task_selection"]["previous_task_id"] == task_id
    assert body["task_selection"]["selected_task_id"] == next_task_id
    assert body["batch_continuation"]["continued"] is True
    assert body["batch_continuation"]["submitted_task_id"] == task_id
    assert body["batch_continuation"]["next_task_id"] == next_task_id
    assert body["work_surface"]["kind"] == "source_review"
    open_action = next(action for action in body["actions"] if action["type"] == "open_task")
    assert open_action["status"] == "executed"
    assert open_action["task_id"] == next_task_id
    with Session(engine) as session:
        assert session.get(Task, task_id).status == "submitted"
        assert session.get(Task, next_task_id).status == "ready"
        chat_session = session.get(ChatSession, body["session_id"])
        assert chat_session.active_task_id == next_task_id
        continuation_result = session.exec(select(ChatActionResult).where(ChatActionResult.action_id == open_action["id"])).first()
        assert continuation_result is not None
        assert continuation_result.object_type == "task"
        assert continuation_result.object_id == next_task_id


def test_chat_submit_confirmation_opens_generated_training_candidate_before_same_route_task():
    client, engine = build_client()
    with Session(engine) as session:
        task_id = add_source_review_task(session)
        same_route_next_task_id = add_source_review_task(session)

    review = client.post(
        "/api/chat/turn",
        json={
            "task_id": task_id,
            "message": (
                "This is a journal excerpt with Charles voice. Charles wrote it. "
                "Truth status: archival source. It is family private and ready for processing. "
                "Use it for voice context and grounded generation; generate pairs. "
                "Context: it captures the cadence around family travel."
            ),
        },
    )
    assert review.status_code == 200
    preview = client.post(
        "/api/chat/turn",
        json={"task_id": task_id, "session_id": review.json()["session_id"], "message": "ready"},
    )
    assert preview.status_code == 200
    preview_body = preview.json()
    submit_action_id = next(action["id"] for action in preview_body["actions"] if action["type"] == "submit_task")

    submitted = client.post(
        "/api/chat/turn",
        json={
            "task_id": task_id,
            "session_id": preview_body["session_id"],
            "message": "ready",
            "confirm_submit": True,
            "confirm_action_id": submit_action_id,
        },
    )

    assert submitted.status_code == 200
    body = submitted.json()
    generated_task_ids = body["submitted_annotation"]["creates_or_updates"]["make_gold_task_ids"]
    assert generated_task_ids
    assert body["active_task"]["id"] == generated_task_ids[0]
    assert body["active_task"]["id"] != same_route_next_task_id
    assert body["batch_continuation"]["type"] == "downstream_candidate_continuation"
    assert body["batch_continuation"]["reason"] == "opened_downstream_candidate_task"
    assert body["batch_continuation"]["next_task_id"] == generated_task_ids[0]
    assert body["work_surface"]["kind"] == "prompt_response_review"
    open_action = next(action for action in body["actions"] if action["type"] == "open_task")
    assert open_action["status"] == "executed"
    assert open_action["task_id"] == generated_task_ids[0]
    with Session(engine) as session:
        generated_task = session.get(Task, generated_task_ids[0])
        assert generated_task is not None
        assert generated_task.task_type == "gold_voice_edit"
        assert generated_task.status == "ready"
        assert session.get(Task, same_route_next_task_id).status == "ready"
        chat_session = session.get(ChatSession, body["session_id"])
        assert chat_session.active_task_id == generated_task_ids[0]


def test_downstream_candidate_handoff_prefers_evidence_linked_candidate_over_creation_order():
    _, engine = build_client()
    with Session(engine) as session:
        weak_task = Task(
            human_id="TASK_WEAK_GENERATED_PAIR",
            task_type="gold_voice_edit",
            target_type="prompt_pair",
            target_id="weak-pair",
            queue="prompt_pairs_needing_gold_edits",
            priority=95,
            input_payload={
                "artifact_mode": "sft",
                "prompt": "Weak prompt",
                "content": "Weak candidate",
                "source_evidence_refs": [],
                "source_evidence_status": "missing_source_evidence_ref",
                "pair_generation_metadata": {"evidence_gate": {"passed": False}},
            },
            created_by="test",
        )
        strong_task = Task(
            human_id="TASK_STRONG_GENERATED_PAIR",
            task_type="gold_voice_edit",
            target_type="prompt_pair",
            target_id="strong-pair",
            queue="prompt_pairs_needing_gold_edits",
            priority=50,
            input_payload={
                "artifact_mode": "dpo",
                "prompt": "Strong prompt",
                "chosen": "Strong chosen",
                "rejected": "Weak rejected",
                "source_evidence_refs": [{"target_id": "segment-1"}, {"target_id": "segment-2"}],
                "source_evidence_status": "evidence_linked",
                "ranked_evidence_packet": {"record_count": 2},
                "pair_generation_metadata": {"evidence_gate": {"passed": True}},
            },
            created_by="test",
        )
        session.add(weak_task)
        session.add(strong_task)
        session.flush()
        annotation = Annotation(
            task_id="source-task",
            target_type="segment",
            target_id="segment-source",
            annotation_type="text_segment_review",
            decisions={},
            creates_or_updates={"make_gold_task_ids": [weak_task.id, strong_task.id]},
        )
        session.add(annotation)
        session.commit()

        selected = _next_downstream_candidate_task(session=session, annotation=annotation)

    assert selected is not None
    assert selected.id == strong_task.id


def test_chat_next_photo_skips_current_photo_ticket():
    client, engine = build_client()
    with Session(engine) as session:
        first_photo_id = add_photo_context_task(session)
        second_photo_id = add_photo_context_task(session)

    response = client.post("/api/chat/turn", json={"task_id": first_photo_id, "message": "Next photo."})

    assert response.status_code == 200
    body = response.json()
    assert body["active_task"]["id"] == second_photo_id
    assert body["task_selection"]["requested_route"] == "photo_review"
    assert body["task_selection"]["avoided_task_id"] == first_photo_id
    assert body["field_updates"] == {}


def test_chat_skip_persists_skipped_task_ids_within_session():
    client, engine = build_client()
    with Session(engine) as session:
        first_photo_id = add_photo_context_task(session)
        second_photo_id = add_photo_context_task(session)

    skipped = client.post("/api/chat/turn", json={"task_id": first_photo_id, "message": "Skip this photo."})
    assert skipped.status_code == 200
    skipped_body = skipped.json()
    assert skipped_body["active_task"]["id"] == second_photo_id
    assert skipped_body["task_selection"]["newly_skipped_task_id"] == first_photo_id

    no_repeat = client.post(
        "/api/chat/turn",
        json={
            "task_id": second_photo_id,
            "session_id": skipped_body["session_id"],
            "message": "Show another photo.",
        },
    )
    assert no_repeat.status_code == 200
    body = no_repeat.json()
    assert body["status"] == "no_ready_task"
    assert body["task_selection"]["requested_route"] == "photo_review"
    assert body["task_selection"]["newly_skipped_task_id"] is None
    assert set(body["task_selection"]["avoided_task_ids"]) == {first_photo_id, second_photo_id}
    with Session(engine) as session:
        chat_session = session.get(ChatSession, skipped_body["session_id"])
        assert first_photo_id in chat_session.metadata_json["skipped_task_ids"]


def test_chat_go_back_returns_previous_task_from_session_history():
    client, engine = build_client()
    with Session(engine) as session:
        photo_task_id = add_photo_context_task(session)
        dpo_task_id = add_dpo_review_task(session)

    first = client.post("/api/chat/turn", json={"task_id": photo_task_id, "message": "This is Charles by the water."})
    assert first.status_code == 200
    session_id = first.json()["session_id"]

    routed = client.post(
        "/api/chat/turn",
        json={"task_id": photo_task_id, "session_id": session_id, "message": "Show me the DPO pairs."},
    )
    assert routed.status_code == 200
    assert routed.json()["active_task"]["id"] == dpo_task_id

    back = client.post(
        "/api/chat/turn",
        json={"task_id": dpo_task_id, "session_id": session_id, "message": "Go back to the previous ticket."},
    )

    assert back.status_code == 200
    body = back.json()
    assert body["active_task"]["id"] == photo_task_id
    assert body["task_selection"]["selection_reason"] == "previous_task_from_chat_history"
    with Session(engine) as session:
        chat_session = session.get(ChatSession, session_id)
        assert chat_session.metadata_json["task_history"][-1] == photo_task_id


def test_chat_reports_no_ready_task_for_requested_empty_route():
    client, _engine = build_client()

    response = client.post("/api/chat/turn", json={"message": "Show me DPO pairs."})

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "no_ready_task"
    assert body["active_task"] == {}
    assert body["task_selection"]["requested_route"] == "dpo_review"
    assert body["task_selection"]["matched_count"] == 0
    assert "ready DPO pairs ticket" in body["assistant_message"]


def test_chat_export_readiness_uses_bottleneck_summary_not_ticket_routing():
    client, engine = build_client()
    with Session(engine) as session:
        add_photo_context_task(session)
        add_dpo_review_task(session)

    response = client.post("/api/chat/turn", json={"message": "What is blocked for export readiness?"})

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "export_readiness_summary"
    assert body["active_task"] == {}
    assert body["task_selection"]["requested_route"] == "export_readiness"
    assert body["task_selection"]["selection_reason"] == "export_readiness_summary"
    assert body["work_summary"]["summary_type"] == "export_readiness"
    assert body["work_summary"]["does_not_mutate_state"] is True
    assert body["work_summary"]["no_live_model_call"] is True
    assert "Export readiness" in body["assistant_message"]
    with Session(engine) as session:
        chat_session = session.get(ChatSession, body["session_id"])
        assert chat_session.active_task_id is None


def test_chat_can_focus_top_export_blocker_ticket_from_natural_language():
    client, engine = build_client()
    with Session(engine) as session:
        task_id = add_prompt_pair_export_blocker_task(session)

    response = client.post("/api/chat/turn", json={"message": "Open the top export blocker."})

    assert response.status_code == 200
    body = response.json()
    assert body["active_task"]["id"] == task_id
    assert body["task_selection"]["requested_route"] == "export_blocker"
    assert body["task_selection"]["selection_reason"] == "top_export_blocker_task"
    assert body["task_selection"]["top_blocker"]["area_key"] == "prompt_pairs"
    assert body["field_updates"] == {}
    assert "draft response" in body["next_question"]
    with Session(engine) as session:
        chat_session = session.get(ChatSession, body["session_id"])
        assert chat_session.active_task_id == task_id


def test_chat_sft_export_preview_uses_approved_only_dry_run_without_mutation():
    client, engine = build_client()
    with Session(engine) as session:
        source_gold_id = add_approved_sft_export_artifact(session)

    response = client.post("/api/chat/turn", json={"message": "Preview the SFT export JSONL."})

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "export_preview_summary"
    assert body["active_task"] == {}
    assert body["task_selection"]["requested_route"] == "export_preview"
    assert body["task_selection"]["selection_reason"] == "export_preview_summary"
    assert body["work_summary"]["summary_type"] == "export_preview"
    assert body["work_summary"]["export_type"] == "sft"
    assert body["work_summary"]["does_not_mutate_state"] is True
    assert body["work_summary"]["no_live_model_call"] is True
    assert body["work_summary"]["included_count"] == 1
    assert body["work_summary"]["excluded_count"] == 0
    assert body["actions"] == []
    assert body["ready_to_submit"] is False
    preview = body["work_summary"]["previews"][0]
    assert preview["include_candidates"] is False
    assert preview["included_count"] == 1
    assert preview["preview_rows"][0]["source_id"] == source_gold_id
    assert "Candidate prompt?" not in preview["jsonl_preview"]
    assert "No export was built" in body["assistant_message"]
    with Session(engine) as session:
        assert session.exec(select(DatasetExport)).all() == []
        chat_session = session.get(ChatSession, body["session_id"])
        assert chat_session.active_task_id is None
        assistant_turn = session.get(ChatTurn, body["turn_id"])
        assert assistant_turn.metadata_json["work_summary"]["export_type"] == "sft"


def test_chat_dpo_export_preview_does_not_route_to_dpo_review_task():
    client, engine = build_client()
    with Session(engine) as session:
        source_gold_id = add_approved_dpo_export_artifact(session)
        dpo_task_id = add_dpo_review_task(session)

    response = client.post("/api/chat/turn", json={"task_id": dpo_task_id, "message": "Preview DPO export dry run."})

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "export_preview_summary"
    assert body["active_task"] == {}
    assert body["work_summary"]["export_type"] == "dpo"
    assert body["work_summary"]["included_count"] == 1
    preview = body["work_summary"]["previews"][0]
    assert preview["preview_rows"][0]["source_id"] == source_gold_id
    assert "Candidate DPO prompt?" not in preview["jsonl_preview"]
    assert "approved row" in body["assistant_message"]
    with Session(engine) as session:
        assert session.exec(select(DatasetExport)).all() == []
        chat_session = session.get(ChatSession, body["session_id"])
        assert chat_session.active_task_id is None


def test_training_board_projects_todo_doing_done_needs_fix_and_exported():
    client, engine = build_client()
    with Session(engine) as session:
        todo_task_id = add_complete_gold_task(session)
        doing_task_id = add_dpo_review_task(session)
        session.add(TaskDraft(task_id=doing_task_id, user_id="adam", decisions={"context": "Adam is actively editing this pair."}))
        sft_gold_id = add_approved_sft_export_artifact(session)
        dpo_gold_id = add_approved_dpo_export_artifact(session)
        dpo_pair = session.exec(select(DPOPair).where(DPOPair.source_gold_voice_example_id == dpo_gold_id)).first()
        export = DatasetExport(
            human_id="EXPORT_DPO_TEST_0001",
            export_type="dpo",
            version="v-test",
            manifest={"item_count": 1},
        )
        session.add(export)
        session.flush()
        session.add(
            DatasetExportItem(
                dataset_export_id=export.id,
                source_type="dpo",
                source_id=dpo_gold_id,
                payload={"test": True},
                boundary_snapshot={"boundary_gate_passed": True},
                quality_snapshot={"status": "approved"},
            )
        )
        candidate_gold = GoldVoiceExample(
            human_id="GOLD_CHAT_DPO_CANDIDATE_BOARD",
            voice_mode="father_to_adam",
            truth_status="adam_expert_reconstruction",
            adam_gold_edit="candidate gold",
            downstream_use={"dpo": True, "artifact_mode": "dpo"},
            ratings={},
        )
        session.add(candidate_gold)
        session.flush()
        candidate_pair = DPOPair(
            source_gold_voice_example_id=candidate_gold.id,
            prompt="Candidate prompt?",
            chosen="candidate chosen",
            rejected="candidate rejected",
            reason=[],
            export_status="candidate",
        )
        session.add(candidate_pair)
        session.commit()
        dpo_pair_id = dpo_pair.id
        candidate_pair_id = candidate_pair.id

    response = client.get("/api/training-board")

    assert response.status_code == 200
    body = response.json()
    columns = {column["id"]: column["items"] for column in body["columns"]}
    assert any(item["taskId"] == todo_task_id for item in columns["todo"])
    assert any(item["taskId"] == doing_task_id for item in columns["doing"])
    assert any(item.get("goldVoiceExampleId") == sft_gold_id and item["kind"] == "sft_candidate" for item in columns["done"])
    assert any(item.get("goldVoiceExampleId") == dpo_gold_id and item["kind"] == "dpo_pair" for item in columns["exported"])
    assert any(item.get("dpoPairId") == candidate_pair_id and item["kind"] == "dpo_pair" for item in columns["needs_fix"])
    assert body["counts"]["ready_tasks"] >= 2
    assert body["counts"]["approved_sft"] >= 1
    assert body["counts"]["approved_dpo"] >= 1
    assert body["counts"]["exported_dpo"] >= 1

    detail = client.get(f"/api/training-board/items/dpo:{dpo_pair_id}")
    assert detail.status_code == 200
    assert detail.json()["datasetExportIds"]


def test_chat_export_without_preview_still_reports_readiness():
    client, engine = build_client()
    with Session(engine) as session:
        add_approved_sft_export_artifact(session)

    response = client.post("/api/chat/turn", json={"message": "What is blocked for export readiness?"})

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "export_readiness_summary"
    assert body["work_summary"]["summary_type"] == "export_readiness"


def test_chat_export_build_requires_confirmation_then_uses_existing_build_path():
    client, engine = build_client()
    with Session(engine) as session:
        add_approved_sft_export_artifact(session)

    preview = client.post("/api/chat/turn", json={"message": "Build the SFT export."})

    assert preview.status_code == 200
    preview_body = preview.json()
    assert preview_body["status"] == "export_build_confirmation_required"
    assert preview_body["work_summary"]["summary_type"] == "export_build_confirmation"
    assert preview_body["export_build_payload"]["export_type"] == "sft"
    assert preview_body["export_build_payload"]["include_candidates"] is False
    assert preview_body["built_export"] is None
    build_action_id = next(action["id"] for action in preview_body["actions"] if action["type"] == "build_dataset_export")
    with Session(engine) as session:
        assert session.exec(select(DatasetExport)).all() == []
        action = session.get(ChatAction, build_action_id)
        assert action.status == "pending_confirmation"
        assert action.requires_confirmation is True

    confirmed = client.post(
        "/api/chat/turn",
        json={
            "session_id": preview_body["session_id"],
            "message": "confirm",
            "confirm_action": True,
            "confirm_action_id": build_action_id,
        },
    )

    assert confirmed.status_code == 200
    body = confirmed.json()
    assert body["status"] == "export_build_confirmed"
    assert body["built_export"]["export_type"] == "sft"
    assert body["built_export"]["manifest"]["item_count"] == 1
    assert any(action["type"] == "build_dataset_export" and action["status"] == "executed" for action in body["actions"])
    with Session(engine) as session:
        exports = session.exec(select(DatasetExport)).all()
        assert len(exports) == 1
        executed_action = session.get(ChatAction, build_action_id)
        assert executed_action.status == "executed"
        result = session.exec(select(ChatActionResult).where(ChatActionResult.action_id == build_action_id)).first()
        assert result is not None
        assert result.object_type == "dataset_export"
        assert result.object_id == exports[0].id


def test_chat_action_dismiss_endpoint_dismisses_pending_export_build():
    client, engine = build_client()
    with Session(engine) as session:
        add_approved_sft_export_artifact(session)

    preview = client.post("/api/chat/turn", json={"message": "Build the SFT export."})
    assert preview.status_code == 200
    preview_body = preview.json()
    build_action_id = next(action["id"] for action in preview_body["actions"] if action["type"] == "build_dataset_export")

    dismissed = client.post(
        f"/api/chat/actions/{build_action_id}/dismiss",
        json={"session_id": preview_body["session_id"], "message": "not yet"},
    )

    assert dismissed.status_code == 200
    body = dismissed.json()
    assert body["status"] == "action_dismissed"
    assert any(action["id"] == build_action_id and action["status"] == "dismissed" for action in body["actions"])
    with Session(engine) as session:
        assert session.exec(select(DatasetExport)).all() == []
        action = session.get(ChatAction, build_action_id)
        assert action is not None
        assert action.status == "dismissed"
        result = session.exec(select(ChatActionResult).where(ChatActionResult.action_id == build_action_id)).first()
        assert result is not None
        assert result.object_type == "chat_action_dismissal"


def test_chat_rejects_stale_or_invalid_export_build_confirmation():
    client, engine = build_client()
    with Session(engine) as session:
        add_approved_sft_export_artifact(session)

    preview = client.post("/api/chat/turn", json={"message": "Build the SFT export."})
    assert preview.status_code == 200
    preview_body = preview.json()

    stale = client.post(
        "/api/chat/turn",
        json={
            "session_id": preview_body["session_id"],
            "message": "confirm",
            "confirm_action": True,
            "confirm_action_id": "missing-action",
        },
    )

    assert stale.status_code == 409
    assert stale.json()["detail"] == "Chat action confirmation is stale or invalid."
    with Session(engine) as session:
        assert session.exec(select(DatasetExport)).all() == []


def test_chat_rejects_export_build_confirmation_when_dry_run_changed():
    client, engine = build_client()
    with Session(engine) as session:
        add_approved_sft_export_artifact(session)

    preview = client.post("/api/chat/turn", json={"message": "Build the SFT export."})
    assert preview.status_code == 200
    preview_body = preview.json()
    build_action_id = next(action["id"] for action in preview_body["actions"] if action["type"] == "build_dataset_export")
    with Session(engine) as session:
        add_approved_sft_export_artifact(session)

    stale = client.post(
        "/api/chat/turn",
        json={
            "session_id": preview_body["session_id"],
            "message": "confirm",
            "confirm_action": True,
            "confirm_action_id": build_action_id,
        },
    )

    assert stale.status_code == 409
    assert "Refresh the preview before confirming" in stale.json()["detail"]
    with Session(engine) as session:
        assert session.exec(select(DatasetExport)).all() == []
        action = session.get(ChatAction, build_action_id)
        assert action is not None
        assert action.status == "stale"
        assert action.requires_confirmation is False
        assert "dry run changed" in action.error_message


def test_chat_sft_explicit_rewrite_updates_content_with_review_context():
    client, engine = build_client()
    with Session(engine) as session:
        task_id = add_complete_gold_task(session)

    response = client.post(
        "/api/chat/turn",
        json={"task_id": task_id, "message": "Replace with: Light first. Always the light.\n\nlove\ndad"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["field_updates"]["content"] == "Light first. Always the light.\n\nlove\ndad"
    assert "chosen" not in body["field_updates"]
    assert body["field_updates"]["rejected"] == "light first. always the light.\n\nlove\ndad"
    assert body["field_updates"]["export_flags"]["sft"] is True
    assert body["field_updates"]["export_flags"]["dpo"] is True
    assert "original_candidate_replaced_by_adam_gold_edit" in body["field_updates"]["failure_modes"]
    assert body["field_updates"]["operator_candidate_triage_intent"] == "keep_with_adam_rewrite"
    assert "Adam replacement note" in body["field_updates"]["context"]
    assert "Preference preservation" in body["field_updates"]["context"]
    assert body["work_surface"]["field_contract"]["accepted_response_field"] == "content"
    assert body["work_surface"]["field_contract"]["rejected_response_field"] == "rejected"
    assert body["ready_to_submit"] is False
    with Session(engine) as session:
        draft = session.exec(select(TaskDraft).where(TaskDraft.task_id == task_id)).first()
        assert draft.decisions["content"] == "Light first. Always the light.\n\nlove\ndad"
        assert draft.decisions["rejected"] == "light first. always the light.\n\nlove\ndad"
        assert draft.decisions["export_flags"]["dpo"] is True


def test_chat_sft_live_rewrite_normalizes_chosen_to_content_and_rejects_original(monkeypatch):
    client, engine = build_client()
    with Session(engine) as session:
        task_id = add_complete_gold_task(session)

    monkeypatch.setattr("app.services.chat_operator.live_text_generation_ready", lambda app_settings: True)
    monkeypatch.setattr(
        "app.services.chat_operator._live_chat_plan",
        lambda **kwargs: {
            "assistant_message": "I will apply that as the accepted SFT answer.",
            "next_question": "Does this version feel ready?",
            "field_updates": {
                "content": "Light first. Always the light.\n\nlove\ndad",
                "chosen": "Light first. Always the light.\n\nlove\ndad",
                "context": "Adam supplied an exact replacement.",
            },
            "actions": [{"type": "update_task_draft", "label": "Apply rewrite", "requires_confirmation": False}],
            "ready_to_submit": False,
        },
    )

    response = client.post(
        "/api/chat/turn",
        json={"task_id": task_id, "message": "Use my new answer as the gold answer."},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["field_updates"]["content"] == "Light first. Always the light.\n\nlove\ndad"
    assert "chosen" not in body["field_updates"]
    assert body["field_updates"]["rejected"] == "light first. always the light.\n\nlove\ndad"
    assert body["field_updates"]["export_flags"]["dpo"] is True
    assert "original_candidate_replaced_by_adam_gold_edit" in body["field_updates"]["failure_modes"]


def test_chat_sft_critique_records_rewrite_guidance_not_source_answer():
    client, engine = build_client()
    with Session(engine) as session:
        task_id = add_complete_gold_task(session)

    response = client.post(
        "/api/chat/turn",
        json={"task_id": task_id, "message": "The first sentence is too generic. Keep the cooking detail but make it less explanatory."},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["field_updates"]["operator_candidate_triage_intent"] == "needs_rewrite"
    assert "candidate_too_generic" in body["field_updates"]["failure_modes"]
    assert "too_explanatory_not_charles_voice" in body["field_updates"]["failure_modes"]
    assert "Adam SFT critique" in body["field_updates"]["context"]
    assert "How was the beach?" not in body["next_question"]


def test_chat_dpo_flip_swaps_chosen_and_rejected_with_rationale():
    client, engine = build_client()
    with Session(engine) as session:
        task_id = add_dpo_review_task(session)
        task = session.get(Task, task_id)
        original_chosen = task.input_payload["chosen"]
        original_rejected = task.input_payload["rejected"]

    response = client.post(
        "/api/chat/turn",
        json={"task_id": task_id, "message": "Swap them. The rejected is better; the first is too generic."},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["field_updates"]["chosen"] == original_rejected
    assert body["field_updates"]["rejected"] == original_chosen
    assert body["work_surface"]["field_contract"]["accepted_response_field"] == "chosen"
    assert body["work_surface"]["field_contract"]["rejected_response_field"] == "rejected"
    assert "previous_chosen_was_weaker" in body["field_updates"]["failure_modes"] or "rejected_too_generic_not_charles_voice" in body["field_updates"]["failure_modes"]
    assert "Adam preference correction" in body["field_updates"]["context"]
    with Session(engine) as session:
        draft = session.exec(select(TaskDraft).where(TaskDraft.task_id == task_id)).first()
        assert draft.decisions["chosen"] == original_rejected
        assert draft.decisions["rejected"] == original_chosen


def test_chat_patch_moves_chosen_to_rejected_and_clears_chosen():
    client, engine = build_client()
    with Session(engine) as session:
        task_id = add_complete_gold_task(session)
        task = session.get(Task, task_id)
        original_chosen = task.input_payload["chosen"]

    response = client.post(
        "/api/chat/turn",
        json={
            "task_id": task_id,
            "message": (
                'Take the text from "Chosen/Preferred" and move it over to "Rejected". '
                "I will then give you a new response for chosen."
            ),
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["patch_result"]["applied"] is True
    assert body["field_updates"]["rejected"] == original_chosen
    assert body["field_updates"]["chosen"] == ""
    assert body["field_updates"]["content"] == ""
    assert body["field_updates"]["artifact_mode"] == "dpo"
    assert body["draft_decisions"]["artifact_mode"] == "dpo"
    assert body["draft_decisions"]["rejected"] == original_chosen
    assert body["draft_decisions"]["chosen"] == ""
    assert body["ready_to_submit"] is False
    assert "moved the current Chosen/Preferred text into Rejected" in body["assistant_message"]
    assert body["next_question"] == "What should the new chosen response say?"
    diff_by_field = {item["field"]: item for item in body["field_diffs"]}
    assert diff_by_field["rejected"]["change_type"] == "copied"
    assert diff_by_field["rejected"]["source_field"] == "chosen"
    assert diff_by_field["chosen"]["change_type"] == "cleared"

    with Session(engine) as session:
        draft = session.exec(select(TaskDraft).where(TaskDraft.task_id == task_id)).first()
        assert draft is not None
        assert draft.decisions["artifact_mode"] == "dpo"
        assert draft.decisions["chosen"] == ""
        assert draft.decisions["rejected"] == original_chosen
        action = session.exec(select(ChatAction).where(ChatAction.task_id == task_id).where(ChatAction.action_type == "update_task_draft")).first()
        assert action is not None
        assert action.status == "executed"
        assert action.validated_payload_json["patch_result"]["applied"] is True
        result = session.exec(select(ChatActionResult).where(ChatActionResult.action_id == action.id)).first()
        assert result is not None
        assert result.after_json["patch_result"]["applied"] is True


def test_chat_sanitizes_live_prose_when_no_draft_mutation_happened(monkeypatch):
    client, engine = build_client()
    with Session(engine) as session:
        task_id = add_dpo_review_task(session)

    monkeypatch.setattr("app.services.chat_operator.live_text_generation_ready", lambda app_settings: True)
    monkeypatch.setattr(
        "app.services.chat_operator._live_chat_plan",
        lambda **kwargs: {
            "assistant_message": "I moved the current chosen response into rejected.",
            "next_question": "What should the new chosen say?",
            "field_updates": {},
            "actions": [{"type": "update_task_draft", "label": "Move text", "requires_confirmation": False}],
            "ready_to_submit": False,
        },
    )

    response = client.post("/api/chat/turn", json={"task_id": task_id, "message": "Please think about this pair."})

    assert response.status_code == 200
    body = response.json()
    assert body["field_updates"] == {}
    assert body["patch_result"]["applied"] is False
    assert "did not change the draft" in body["assistant_message"]
    assert not any(action["type"] == "update_task_draft" for action in body["actions"])
    with Session(engine) as session:
        assert session.exec(select(TaskDraft).where(TaskDraft.task_id == task_id)).first() is None


def test_chat_require_live_model_blocks_deterministic_fallback_when_not_ready():
    client, engine = build_client()
    app.dependency_overrides[get_settings] = lambda: Settings(
        openai_api_key="",
        text_generation_live_calls_enabled=False,
        chat_require_live_model=True,
    )
    with Session(engine) as session:
        task_id = add_dpo_review_task(session)

    response = client.post("/api/chat/turn", json={"task_id": task_id, "message": "It's not quite the right voice yet."})

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "live_model_required_not_ready"
    assert body["model_ready"] is False
    assert body["live_model_call_used"] is False
    assert body["field_updates"] == {}
    assert body["actions"] == []
    assert "Live AI is required" in body["assistant_message"]
    with Session(engine) as session:
        assert session.exec(select(TaskDraft).where(TaskDraft.task_id == task_id)).first() is None


def test_chat_require_live_model_blocks_provider_error_fallback(monkeypatch):
    client, engine = build_client()
    app.dependency_overrides[get_settings] = lambda: Settings(
        openai_api_key="test-key",
        text_generation_live_calls_enabled=True,
        chat_require_live_model=True,
    )
    with Session(engine) as session:
        task_id = add_dpo_review_task(session)

    def fail_live_plan(**kwargs):
        raise RuntimeError("provider unavailable")

    monkeypatch.setattr("app.services.chat_operator._live_chat_plan", fail_live_plan)

    response = client.post("/api/chat/turn", json={"task_id": task_id, "message": "It's not quite the right voice yet."})

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "live_error_blocked"
    assert body["model_ready"] is True
    assert body["live_model_call_used"] is False
    assert body["field_updates"] == {}
    assert body["actions"] == []
    assert "did not use a deterministic fallback" in body["assistant_message"]
    with Session(engine) as session:
        assert session.exec(select(TaskDraft).where(TaskDraft.task_id == task_id)).first() is None


def test_chat_patch_rejects_unknown_fields(monkeypatch):
    client, engine = build_client()
    with Session(engine) as session:
        task_id = add_dpo_review_task(session)

    monkeypatch.setattr("app.services.chat_operator.live_text_generation_ready", lambda app_settings: True)
    monkeypatch.setattr(
        "app.services.chat_operator._live_chat_plan",
        lambda **kwargs: {
            "assistant_message": "I updated the hidden field.",
            "next_question": "What should we do next?",
            "field_updates": {},
            "draft_patch": [{"op": "set", "field": "hidden_field", "value": "nope"}],
            "actions": [{"type": "update_task_draft", "label": "Update hidden field", "requires_confirmation": False}],
            "ready_to_submit": False,
        },
    )

    response = client.post("/api/chat/turn", json={"task_id": task_id, "message": "Set the hidden field."})

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "draft_patch_blocked"
    assert body["patch_result"]["applied"] is False
    assert "not an editable field" in body["patch_result"]["blocked_reason"]
    assert "did not change the draft" in body["assistant_message"]
    assert not any(action["type"] == "update_task_draft" for action in body["actions"])
    with Session(engine) as session:
        assert session.exec(select(TaskDraft).where(TaskDraft.task_id == task_id)).first() is None


def test_chat_patch_rejects_no_op_changes(monkeypatch):
    client, engine = build_client()
    with Session(engine) as session:
        task_id = add_dpo_review_task(session)
        task = session.get(Task, task_id)
        existing_chosen = task.input_payload["chosen"]

    monkeypatch.setattr("app.services.chat_operator.live_text_generation_ready", lambda app_settings: True)
    monkeypatch.setattr(
        "app.services.chat_operator._live_chat_plan",
        lambda **kwargs: {
            "assistant_message": "I updated chosen.",
            "next_question": "What should we do next?",
            "field_updates": {},
            "draft_patch": [{"op": "set", "field": "chosen", "value": existing_chosen}],
            "actions": [{"type": "update_task_draft", "label": "Update chosen", "requires_confirmation": False}],
            "ready_to_submit": False,
        },
    )

    response = client.post("/api/chat/turn", json={"task_id": task_id, "message": "Set chosen to the current chosen."})

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "draft_patch_blocked"
    assert body["patch_result"]["applied"] is False
    assert body["patch_result"]["blocked_reason"] == "The patch did not change any editable fields."
    assert body["field_updates"] == {}
    assert "did not change the draft" in body["assistant_message"]
    with Session(engine) as session:
        assert session.exec(select(TaskDraft).where(TaskDraft.task_id == task_id)).first() is None


def test_chat_patch_swap_uses_authoritative_backend_state(monkeypatch):
    client, engine = build_client()
    with Session(engine) as session:
        task_id = add_dpo_review_task(session)
        task = session.get(Task, task_id)
        original_chosen = task.input_payload["chosen"]
        original_rejected = task.input_payload["rejected"]

    monkeypatch.setattr("app.services.chat_operator.live_text_generation_ready", lambda app_settings: True)
    monkeypatch.setattr(
        "app.services.chat_operator._live_chat_plan",
        lambda **kwargs: {
            "assistant_message": "I swapped chosen and rejected.",
            "next_question": "Does that preference now look right?",
            "field_updates": {},
            "draft_patch": [{"op": "swap", "left": "chosen", "right": "rejected"}],
            "actions": [{"type": "update_task_draft", "label": "Swap chosen and rejected", "requires_confirmation": False}],
            "ready_to_submit": False,
        },
    )

    response = client.post("/api/chat/turn", json={"task_id": task_id, "message": "Swap the two responses."})

    assert response.status_code == 200
    body = response.json()
    assert body["patch_result"]["applied"] is True
    assert body["field_updates"]["chosen"] == original_rejected
    assert body["field_updates"]["rejected"] == original_chosen
    assert {item["field"]: item["change_type"] for item in body["field_diffs"]} == {
        "chosen": "swapped",
        "rejected": "swapped",
    }
    with Session(engine) as session:
        draft = session.exec(select(TaskDraft).where(TaskDraft.task_id == task_id)).first()
        assert draft is not None
        assert draft.decisions["chosen"] == original_rejected
        assert draft.decisions["rejected"] == original_chosen


def test_chat_moves_current_chosen_to_rejected_from_adam_instruction():
    client, engine = build_client()
    with Session(engine) as session:
        task_id = add_dpo_review_task(session)
        task = session.get(Task, task_id)
        original_chosen = task.input_payload["chosen"]

    response = client.post(
        "/api/chat/turn",
        json={
            "task_id": task_id,
            "message": "Take the text from Chosen/Preferred and move it over to Rejected. I will then give you a new response for chosen.",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["patch_result"]["applied"] is True
    assert body["field_updates"]["chosen"] == ""
    assert body["field_updates"]["rejected"] == original_chosen
    assert body["assistant_message"] == "Applied: moved the current Chosen/Preferred text into Rejected. Chosen is now empty and ready for your replacement."
    assert body["next_question"] == "What should the new chosen response say?"
    with Session(engine) as session:
        draft = session.exec(select(TaskDraft).where(TaskDraft.task_id == task_id)).first()
        assert draft is not None
        assert draft.decisions["chosen"] == ""
        assert draft.decisions["rejected"] == original_chosen


def test_chat_sanitizes_live_draft_edit_claim_with_no_executable_patch(monkeypatch):
    client, engine = build_client()
    with Session(engine) as session:
        task_id = add_dpo_review_task(session)

    monkeypatch.setattr("app.services.chat_operator.live_text_generation_ready", lambda app_settings: True)
    monkeypatch.setattr(
        "app.services.chat_operator._live_chat_plan",
        lambda **kwargs: {
            "assistant_message": "Got it, Adam — I’ll move the current Chosen/Preferred text into Rejected.",
            "next_question": "What should the replacement chosen response say?",
            "field_updates": {},
            "draft_patch": [],
            "actions": [{"type": "ask_question", "label": "What should the replacement chosen response say?", "requires_confirmation": False}],
            "ready_to_submit": False,
        },
    )

    response = client.post("/api/chat/turn", json={"task_id": task_id, "message": "It needs rework."})

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "sanitized_unapplied_draft_edit_claim"
    assert body["field_updates"] == {}
    assert body["draft_patch"] == []
    assert "did not change the draft" in body["assistant_message"]
    with Session(engine) as session:
        assert session.exec(select(TaskDraft).where(TaskDraft.task_id == task_id)).first() is None


def test_chat_dpo_critique_records_failure_modes_without_swapping():
    client, engine = build_client()
    with Session(engine) as session:
        task_id = add_dpo_review_task(session)

    response = client.post(
        "/api/chat/turn",
        json={"task_id": task_id, "message": "Chosen is stronger. Rejected is too formal and lacks specific memory detail."},
    )

    assert response.status_code == 200
    body = response.json()
    assert "too_formal_not_charles_voice" in body["field_updates"]["failure_modes"]
    assert "needs_more_specific_memory_detail" in body["field_updates"]["failure_modes"]
    assert "Adam DPO critique" in body["field_updates"]["context"]
    assert "chosen" not in body["field_updates"]
    assert "rejected" not in body["field_updates"]


def test_chat_dpo_both_bad_marks_reject_pair_triage_intent():
    client, engine = build_client()
    with Session(engine) as session:
        task_id = add_dpo_review_task(session)

    response = client.post(
        "/api/chat/turn",
        json={"task_id": task_id, "message": "Both are bad. Neither works; they are too generic and too formal."},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["field_updates"]["operator_candidate_triage_intent"] == "reject_pair"
    assert "rejected_too_generic_not_charles_voice" in body["field_updates"]["failure_modes"]
    assert "too_formal_not_charles_voice" in body["field_updates"]["failure_modes"]
    assert "Adam DPO reject-pair decision" in body["field_updates"]["context"]
    assert "chosen" not in body["field_updates"]
    assert "rejected" not in body["field_updates"]


def test_chat_never_asks_adam_to_answer_the_source_prompt(monkeypatch):
    client, engine = build_client()
    with Session(engine) as session:
        task_id = add_dpo_review_task(session)

    monkeypatch.setattr("app.services.chat_operator.live_text_generation_ready", lambda app_settings: True)
    monkeypatch.setattr(
        "app.services.chat_operator._live_chat_plan",
        lambda **kwargs: {
            "assistant_message": "How did you learn to cook?",
            "next_question": "How did you learn to cook?",
            "field_updates": {},
            "actions": [{"type": "ask_question", "label": "How did you learn to cook?", "requires_confirmation": False}],
            "ready_to_submit": False,
        },
    )

    response = client.post("/api/chat/turn", json={"task_id": task_id, "message": ""})

    assert response.status_code == 200
    body = response.json()
    assert body["live_model_call_used"] is True
    assert body["status"] == "sanitized_source_prompt_question"
    assert body["next_question"] != "How did you learn to cook?"
    assert "How did you learn to cook" not in body["assistant_message"]
    assert "How did you learn to cook" not in body["actions"][0]["label"]
    assert "chosen and rejected responses" in body["next_question"]


def test_invalid_live_chat_plan_shape_falls_back_without_actions_leaking(monkeypatch):
    client, engine = build_client()
    with Session(engine) as session:
        task_id = add_photo_context_task(session)

    monkeypatch.setattr("app.services.chat_operator.live_text_generation_ready", lambda app_settings: True)
    monkeypatch.setattr(
        "app.services.chat_operator._live_chat_plan",
        lambda **kwargs: {
            "assistant_message": 123,
            "next_question": ["not", "a", "question"],
            "field_updates": "not a dict",
            "actions": [{"type": "delete_everything", "label": "Delete", "requires_confirmation": False}],
            "ready_to_submit": "no",
        },
    )

    response = client.post("/api/chat/turn", json={"task_id": task_id, "message": "Look at this."})

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "invalid_model_plan_fallback"
    assert body["field_updates"] == {}
    assert body["ready_to_submit"] is False
    assert all(action["type"] != "delete_everything" for action in body["actions"])
    assert body["next_question"] == "I’m showing you this photo. What is visibly present, and who can you identify with confidence?"
    assert "Invalid chat plan shape" in body["error"]


def test_live_chat_plan_missing_required_fields_falls_back(monkeypatch):
    client, engine = build_client()
    with Session(engine) as session:
        task_id = add_photo_context_task(session)

    monkeypatch.setattr("app.services.chat_operator.live_text_generation_ready", lambda app_settings: True)
    monkeypatch.setattr(
        "app.services.chat_operator._live_chat_plan",
        lambda **kwargs: {
            "assistant_message": "Partial response only.",
            "draft_updates": {"visual_description_correction": "Charles is by the water."},
        },
    )

    response = client.post("/api/chat/turn", json={"task_id": task_id, "message": "Look at this."})

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "invalid_model_plan_fallback"
    assert body["field_updates"] == {}
    assert "missing required field" in body["error"]
    assert body["next_question"] == "I’m showing you this photo. What is visibly present, and who can you identify with confidence?"


def test_chat_confirm_submit_uses_existing_task_submit_path():
    client, engine = build_client()
    with Session(engine) as session:
        task_id = add_complete_gold_task(session)

    preview = client.post("/api/chat/turn", json={"task_id": task_id, "message": "ready"})
    assert preview.status_code == 200
    preview_body = preview.json()
    assert preview_body["ready_to_submit"] is True
    assert preview_body["field_updates"] == {}
    submit_action_id = next(action["id"] for action in preview_body["actions"] if action["type"] == "submit_task")
    with Session(engine) as session:
        assert session.get(Task, task_id).status == "ready"
        assert session.exec(select(Annotation)).first() is None
        submit_action = session.get(ChatAction, submit_action_id)
        assert submit_action is not None
        assert submit_action.status == "pending_confirmation"
        assert submit_action.requires_confirmation is True
    restored_preview = client.get(f"/api/chat/sessions/{preview_body['session_id']}")
    assert restored_preview.status_code == 200
    restored_latest = restored_preview.json()["latest_response"]
    assert restored_latest["ready_to_submit"] is True
    assert restored_latest["submit_payload"]["task_id"] == task_id
    assert any(action["id"] == submit_action_id and action["status"] == "pending_confirmation" for action in restored_latest["actions"])

    submitted = client.post(
        "/api/chat/turn",
        json={
            "task_id": task_id,
            "session_id": preview_body["session_id"],
            "message": "ready",
            "confirm_submit": True,
            "confirm_action_id": submit_action_id,
        },
    )

    assert submitted.status_code == 200
    body = submitted.json()
    assert body["submitted_annotation"]["task_id"] == task_id
    assert any(action["type"] == "submit_task" and action["status"] == "executed" for action in body["actions"])
    with Session(engine) as session:
        assert session.get(Task, task_id).status == "submitted"
        annotation = session.exec(select(Annotation)).first()
        assert annotation is not None
        provenance = annotation.decisions["chat_provenance"]
        assert provenance["chat_session_id"] == preview_body["session_id"]
        assert provenance["preview_turn_id"] == preview_body["turn_id"]
        assert provenance["confirmation_turn_id"] == body["turn_id"]
        assert provenance["chat_action_id"] == submit_action_id
        assert provenance["task_id"] == task_id
        assert provenance["context_packet_hash"]
        assert provenance["source_refs"]["target_id"] == "pair-chat-ready"
        assert provenance["field_provenance"]["content"]["source"] == "final_approval"
        assert provenance["field_provenance"]["export_flags"]["source"] == "backend_export_policy"
        assert annotation.creates_or_updates["chat_provenance"]["chat_action_id"] == submit_action_id
        executed_actions = session.exec(
            select(ChatAction).where(ChatAction.task_id == task_id).where(ChatAction.action_type == "submit_task")
        ).all()
        assert any(action.status == "executed" for action in executed_actions)
        executed_action = next(action for action in executed_actions if action.status == "executed")
        assert executed_action.id == submit_action_id
        result = session.exec(select(ChatActionResult).where(ChatActionResult.action_id == executed_action.id)).first()
        assert result is not None
        assert result.object_type == "annotation"
        assert result.after_json["task_id"] == task_id
        assert result.after_json["decisions"]["chat_provenance"]["chat_action_id"] == submit_action_id
        gold = session.exec(select(GoldVoiceExample)).first()
        sft = session.exec(select(SFTCandidate)).first()
        assert gold is not None
        assert gold.downstream_use["source_annotation_id"] == annotation.id
        assert sft is not None
        assert sft.source_gold_voice_example_id == gold.id
        assert sft.quality_gate["source_annotation_id"] == annotation.id
        assert sft.export_status == "approved"


def test_chat_action_preview_endpoint_exposes_pending_submit_contract():
    client, engine = build_client()
    with Session(engine) as session:
        task_id = add_complete_gold_task(session)

    preview = client.post("/api/chat/turn", json={"task_id": task_id, "message": "ready"})
    assert preview.status_code == 200
    preview_body = preview.json()
    submit_action_id = next(action["id"] for action in preview_body["actions"] if action["type"] == "submit_task")

    action_preview = client.post(
        f"/api/chat/actions/{submit_action_id}/preview",
        json={"session_id": preview_body["session_id"]},
    )

    assert action_preview.status_code == 200
    body = action_preview.json()
    assert body["can_confirm"] is True
    assert body["stale_reason"] is None
    assert body["action"]["id"] == submit_action_id
    assert body["action"]["action_type"] == "submit_task"
    assert body["preview_payload"]["submit_payload"]["task_id"] == task_id
    assert body["preview_payload"]["submit_payload"]["decisions"]["content"] == "light first. always the light.\n\nlove\ndad"
    assert body["preview_payload"]["context_packet_hash"]


def test_chat_action_confirm_endpoint_submits_pending_task():
    client, engine = build_client()
    with Session(engine) as session:
        task_id = add_complete_gold_task(session)

    preview = client.post("/api/chat/turn", json={"task_id": task_id, "message": "ready"})
    assert preview.status_code == 200
    preview_body = preview.json()
    submit_action_id = next(action["id"] for action in preview_body["actions"] if action["type"] == "submit_task")

    submitted = client.post(
        f"/api/chat/actions/{submit_action_id}/confirm",
        json={"session_id": preview_body["session_id"], "message": "confirm"},
    )

    assert submitted.status_code == 200
    body = submitted.json()
    assert body["submitted_annotation"]["task_id"] == task_id
    assert any(action["type"] == "submit_task" and action["status"] == "executed" for action in body["actions"])
    with Session(engine) as session:
        assert session.get(Task, task_id).status == "submitted"
        annotation = session.exec(select(Annotation).where(Annotation.task_id == task_id)).first()
        assert annotation is not None
        assert annotation.decisions["chat_provenance"]["chat_action_id"] == submit_action_id
        action = session.get(ChatAction, submit_action_id)
        assert action is not None
        assert action.status == "executed"
        result = session.exec(select(ChatActionResult).where(ChatActionResult.action_id == submit_action_id)).first()
        assert result is not None
        assert result.object_type == "annotation"


def test_chat_action_confirm_endpoint_rejects_stale_submit():
    client, engine = build_client()
    with Session(engine) as session:
        task_id = add_complete_gold_task(session)

    preview = client.post("/api/chat/turn", json={"task_id": task_id, "message": "ready"})
    assert preview.status_code == 200
    preview_body = preview.json()
    submit_action_id = next(action["id"] for action in preview_body["actions"] if action["type"] == "submit_task")
    with Session(engine) as session:
        draft = session.exec(select(TaskDraft).where(TaskDraft.task_id == task_id).where(TaskDraft.user_id == "adam")).first()
        if draft is None:
            draft = TaskDraft(task_id=task_id, user_id="adam")
        draft.decisions = {"content": "changed after action preview\n\nlove\ndad"}
        session.add(draft)
        session.commit()

    stale = client.post(
        f"/api/chat/actions/{submit_action_id}/confirm",
        json={"session_id": preview_body["session_id"], "message": "confirm"},
    )

    assert stale.status_code == 409
    assert "Refresh the preview before confirming" in stale.json()["detail"]
    with Session(engine) as session:
        assert session.get(Task, task_id).status == "ready"
        assert session.exec(select(Annotation)).first() is None
        action = session.get(ChatAction, submit_action_id)
        assert action is not None
        assert action.status == "stale"
        assert "draft changed" in action.error_message


def test_chat_sft_rewrite_submit_creates_dpo_pair_with_original_as_rejected():
    client, engine = build_client()
    with Session(engine) as session:
        task_id = add_complete_gold_task(session)
        original = session.get(Task, task_id).input_payload["content"]

    rewrite = client.post(
        "/api/chat/turn",
        json={"task_id": task_id, "message": "Replace with: Light first. Always the light.\n\nlove\ndad"},
    )
    assert rewrite.status_code == 200
    rewrite_body = rewrite.json()

    preview = client.post(
        "/api/chat/turn",
        json={"task_id": task_id, "session_id": rewrite_body["session_id"], "message": "ready"},
    )
    assert preview.status_code == 200
    preview_body = preview.json()
    submit_action_id = next(action["id"] for action in preview_body["actions"] if action["type"] == "submit_task")

    submitted = client.post(
        "/api/chat/turn",
        json={
            "task_id": task_id,
            "session_id": preview_body["session_id"],
            "message": "ready",
            "confirm_submit": True,
            "confirm_action_id": submit_action_id,
        },
    )

    assert submitted.status_code == 200
    with Session(engine) as session:
        annotation = session.exec(select(Annotation).where(Annotation.task_id == task_id)).first()
        sft = session.exec(select(SFTCandidate)).first()
        dpo = session.exec(select(DPOPair)).first()
        assert annotation is not None
        assert annotation.decisions["content"] == "Light first. Always the light.\n\nlove\ndad"
        assert annotation.decisions["rejected"] == original
        assert annotation.decisions["export_flags"]["dpo"] is True
        assert sft is not None
        assert sft.messages[-1]["content"] == "Light first. Always the light.\n\nlove\ndad"
        assert dpo is not None
        assert dpo.chosen == "Light first. Always the light.\n\nlove\ndad"
        assert dpo.rejected == original
        assert "original_candidate_replaced_by_adam_gold_edit" in dpo.reason


def test_chat_repairs_stale_sft_draft_with_chosen_instead_of_rejected():
    client, engine = build_client()
    with Session(engine) as session:
        task_id = add_complete_gold_task(session)
        original = session.get(Task, task_id).input_payload["content"]
        session.add(
            TaskDraft(
                task_id=task_id,
                user_id="adam",
                decisions={
                    "content": "Light first. Always the light.\n\nlove\ndad",
                    "chosen": "Light first. Always the light.\n\nlove\ndad",
                    "rejected": "",
                },
            )
        )
        session.commit()

    preview = client.post("/api/chat/turn", json={"task_id": task_id, "message": "ready"})

    assert preview.status_code == 200
    body = preview.json()
    assert body["ready_to_submit"] is True
    assert body["draft_decisions"]["content"] == "Light first. Always the light.\n\nlove\ndad"
    assert body["draft_decisions"]["rejected"] == original
    assert "chosen" not in body["draft_decisions"]
    assert body["submit_payload"]["decisions"]["content"] == "Light first. Always the light.\n\nlove\ndad"
    assert body["submit_payload"]["decisions"]["rejected"] == original
    assert "chosen" not in body["submit_payload"]["decisions"]
    assert body["submit_payload"]["decisions"]["export_flags"]["dpo"] is True
    assert "original_candidate_replaced_by_adam_gold_edit" in body["submit_payload"]["decisions"]["failure_modes"]
    with Session(engine) as session:
        draft = session.exec(select(TaskDraft).where(TaskDraft.task_id == task_id)).first()
        assert draft is not None
        assert draft.decisions["rejected"] == original
        assert "chosen" not in draft.decisions


def test_chat_dpo_review_can_preview_confirm_and_preserve_rationale():
    client, engine = build_client()
    with Session(engine) as session:
        task_id = add_dpo_review_task(session)

    critique = client.post(
        "/api/chat/turn",
        json={"task_id": task_id, "message": "The chosen response is better. The rejected answer is too generic and too formal."},
    )
    assert critique.status_code == 200
    critique_body = critique.json()
    assert "too_formal_not_charles_voice" in critique_body["field_updates"]["failure_modes"]

    preview = client.post(
        "/api/chat/turn",
        json={"task_id": task_id, "session_id": critique_body["session_id"], "message": "ready"},
    )
    assert preview.status_code == 200
    preview_body = preview.json()
    assert preview_body["ready_to_submit"] is True
    assert preview_body["field_updates"] == {}
    assert "Adam DPO critique" in preview_body["submit_payload"]["decisions"]["context"]
    submit_action_id = next(action["id"] for action in preview_body["actions"] if action["type"] == "submit_task")

    submitted = client.post(
        "/api/chat/turn",
        json={
            "task_id": task_id,
            "session_id": preview_body["session_id"],
            "message": "ready",
            "confirm_submit": True,
            "confirm_action_id": submit_action_id,
        },
    )

    assert submitted.status_code == 200
    body = submitted.json()
    assert body["submitted_annotation"]["task_id"] == task_id
    with Session(engine) as session:
        task = session.get(Task, task_id)
        annotation = session.exec(select(Annotation).where(Annotation.task_id == task_id)).first()
        dpo = session.exec(select(DPOPair)).first()
        gold = session.exec(select(GoldVoiceExample)).first()
        assert task.status == "submitted"
        assert annotation is not None
        provenance = annotation.decisions["chat_provenance"]
        assert provenance["chat_session_id"] == critique_body["session_id"]
        assert provenance["preview_turn_id"] == preview_body["turn_id"]
        assert provenance["confirmation_turn_id"] == body["turn_id"]
        assert provenance["chat_action_id"] == submit_action_id
        assert provenance["task_id"] == task_id
        assert any(diff["field"] == "failure_modes" for diff in provenance["decision_diffs"])
        assert gold is not None
        assert gold.downstream_use["source_annotation_id"] == annotation.id
        assert dpo is not None
        assert dpo.source_gold_voice_example_id == gold.id
        assert "too_formal_not_charles_voice" in dpo.reason
        assert "rejected_too_generic_not_charles_voice" in dpo.reason
        assert "Adam DPO critique" in annotation.decisions["context"]


def test_chat_audit_endpoint_links_task_to_session_actions_and_provenance():
    client, engine = build_client()
    with Session(engine) as session:
        task_id = add_dpo_review_task(session)

    critique = client.post(
        "/api/chat/turn",
        json={"task_id": task_id, "message": "The chosen response is better. The rejected answer is too generic and too formal."},
    )
    assert critique.status_code == 200
    critique_body = critique.json()
    preview = client.post(
        "/api/chat/turn",
        json={"task_id": task_id, "session_id": critique_body["session_id"], "message": "ready"},
    )
    assert preview.status_code == 200
    preview_body = preview.json()
    submit_action_id = next(action["id"] for action in preview_body["actions"] if action["type"] == "submit_task")

    pending_audit = client.get(
        "/api/chat/audit",
        params={"task_id": task_id, "session_id": critique_body["session_id"]},
    )
    assert pending_audit.status_code == 200
    pending_body = pending_audit.json()
    assert pending_body["audit_type"] == "chat_workbench_audit"
    assert pending_body["task_id"] == task_id
    assert pending_body["session_id"] == critique_body["session_id"]
    assert pending_body["turn_count"] >= 4
    assert pending_body["action_status_counts"]["pending_confirmation"] == 1
    assert "pending_confirmation" in pending_body["quality_gaps"]
    assert any(action["id"] == submit_action_id and action["context_packet_hash"] for action in pending_body["recent_actions"])

    submitted = client.post(
        f"/api/chat/actions/{submit_action_id}/confirm",
        json={"session_id": critique_body["session_id"], "message": "confirm"},
    )
    assert submitted.status_code == 200

    audit = client.get(
        "/api/chat/audit",
        params={"task_id": task_id, "session_id": critique_body["session_id"]},
    )

    assert audit.status_code == 200
    body = audit.json()
    assert body["action_status_counts"]["executed"] >= 1
    assert body["result_count"] >= 1
    assert "pending_confirmation" not in body["quality_gaps"]
    assert "submitted_annotation_missing_chat_provenance" not in body["quality_gaps"]
    provenance = body["provenance_links"][0]
    assert provenance["chat_session_id"] == critique_body["session_id"]
    assert provenance["chat_action_id"] == submit_action_id
    assert provenance["source_refs"]["target_id"] == "pair-chat-review"
    assert body["quality_signals"]["field_source_counts"]["adam_critique"] >= 1


def test_chat_rejects_stale_or_invalid_submit_confirmation():
    client, engine = build_client()
    with Session(engine) as session:
        task_id = add_complete_gold_task(session)

    preview = client.post("/api/chat/turn", json={"task_id": task_id, "message": "ready"})
    assert preview.status_code == 200
    preview_body = preview.json()

    stale = client.post(
        "/api/chat/turn",
        json={
            "task_id": task_id,
            "session_id": preview_body["session_id"],
            "message": "ready",
            "confirm_submit": True,
            "confirm_action_id": "missing-action",
        },
    )

    assert stale.status_code == 409
    assert stale.json()["detail"] == "Chat submit confirmation is stale or invalid."
    with Session(engine) as session:
        assert session.get(Task, task_id).status == "ready"
        assert session.exec(select(Annotation)).first() is None


def test_chat_rejects_submit_confirmation_when_previewed_draft_changed():
    client, engine = build_client()
    with Session(engine) as session:
        task_id = add_complete_gold_task(session)

    preview = client.post("/api/chat/turn", json={"task_id": task_id, "message": "ready"})
    assert preview.status_code == 200
    preview_body = preview.json()
    submit_action_id = next(action["id"] for action in preview_body["actions"] if action["type"] == "submit_task")
    with Session(engine) as session:
        draft = session.exec(select(TaskDraft).where(TaskDraft.task_id == task_id).where(TaskDraft.user_id == "adam")).first()
        if draft is None:
            draft = TaskDraft(task_id=task_id, user_id="adam")
        draft.decisions = {"content": "changed after preview\n\nlove\ndad"}
        draft.notes = "late manual edit"
        session.add(draft)
        session.commit()

    stale = client.post(
        "/api/chat/turn",
        json={
            "task_id": task_id,
            "session_id": preview_body["session_id"],
            "message": "ready",
            "confirm_submit": True,
            "confirm_action_id": submit_action_id,
        },
    )

    assert stale.status_code == 409
    assert "Refresh the preview before confirming" in stale.json()["detail"]
    with Session(engine) as session:
        assert session.get(Task, task_id).status == "ready"
        assert session.exec(select(Annotation)).first() is None
        action = session.get(ChatAction, submit_action_id)
        assert action is not None
        assert action.status == "stale"
        assert action.requires_confirmation is False
        assert "draft changed" in action.error_message


def test_chat_can_dismiss_pending_submit_without_mutating_task():
    client, engine = build_client()
    with Session(engine) as session:
        task_id = add_complete_gold_task(session)

    preview = client.post("/api/chat/turn", json={"task_id": task_id, "message": "ready"})
    assert preview.status_code == 200
    preview_body = preview.json()
    submit_action_id = next(action["id"] for action in preview_body["actions"] if action["type"] == "submit_task")

    dismissed = client.post(
        "/api/chat/turn",
        json={
            "task_id": task_id,
            "session_id": preview_body["session_id"],
            "message": "dismiss this for now",
            "dismiss_action": True,
            "confirm_action_id": submit_action_id,
        },
    )

    assert dismissed.status_code == 200
    body = dismissed.json()
    assert body["status"] == "action_dismissed"
    assert body["ready_to_submit"] is False
    assert body["work_summary"]["summary_type"] == "action_dismissed"
    assert any(action["id"] == submit_action_id and action["status"] == "dismissed" for action in body["actions"])
    with Session(engine) as session:
        assert session.get(Task, task_id).status == "ready"
        assert session.exec(select(Annotation)).first() is None
        dismissed_action = session.get(ChatAction, submit_action_id)
        assert dismissed_action is not None
        assert dismissed_action.status == "dismissed"
        assert dismissed_action.requires_confirmation is False
        result = session.exec(select(ChatActionResult).where(ChatActionResult.action_id == submit_action_id)).first()
        assert result is not None
        assert result.object_type == "chat_action_dismissal"
        assert result.after_json["status"] == "dismissed"


def test_chat_rejects_stale_or_invalid_action_dismissal():
    client, engine = build_client()
    with Session(engine) as session:
        task_id = add_complete_gold_task(session)

    preview = client.post("/api/chat/turn", json={"task_id": task_id, "message": "ready"})
    assert preview.status_code == 200
    preview_body = preview.json()

    dismissed = client.post(
        "/api/chat/turn",
        json={
            "task_id": task_id,
            "session_id": preview_body["session_id"],
            "message": "dismiss",
            "dismiss_action": True,
            "confirm_action_id": "missing-action",
        },
    )

    assert dismissed.status_code == 409
    assert dismissed.json()["detail"] == "Chat action dismissal is stale or invalid."
    with Session(engine) as session:
        assert session.get(Task, task_id).status == "ready"
        assert session.exec(select(Annotation)).first() is None
