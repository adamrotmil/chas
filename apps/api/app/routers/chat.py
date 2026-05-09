from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from app.config import Settings, get_settings
from app.db.session import get_session
from app.models import Annotation, Asset, ChatAction, ChatActionResult, ChatSession, ChatTurn, Segment, Task
from app.routers.assets import create_photo_context_task_from_inventory
from app.routers.exports import build_dataset_export
from app.routers.tasks import submit_task
from app.schemas import (
    ChatActionCommandRequest,
    ChatAuditResponse,
    ChatActionPreviewResponse,
    ChatSessionCreate,
    ChatSessionListResponse,
    ChatSessionResponse,
    ChatTurnRequest,
    ChatTurnResponse,
    DatasetBuildRequest,
    PhotoContextTaskCreate,
    TaskSubmit,
)
from app.services.chat_operator import (
    build_chat_turn,
    chat_session_payload,
    chat_export_build_action_stale_reason,
    chat_review_task_action_stale_reason,
    chat_submit_action_stale_reason,
    dismiss_pending_chat_action,
    mark_chat_action_stale,
    mark_chat_export_build_action_executed,
    mark_chat_review_task_action_executed,
    mark_chat_submit_action_executed,
)


router = APIRouter(prefix="/chat", tags=["chat"])


def _count_rows(session: Session, model: Any) -> int:
    return len(session.exec(select(model)).all()) + 1


def _text(value: Any, fallback: str = "") -> str:
    return value if isinstance(value, str) and value.strip() else fallback


def _source_segment_for_review_payload(session: Session, payload: Dict[str, Any]) -> Segment:
    source_segment_id = _text(payload.get("source_segment_id"))
    if source_segment_id:
        segment = session.get(Segment, source_segment_id)
        if segment is None:
            raise HTTPException(status_code=409, detail="Source segment for review task no longer exists.")
        return segment
    source_asset_id = _text(payload.get("source_asset_id")) or _text(payload.get("asset_id"))
    if source_asset_id:
        segment = session.exec(
            select(Segment)
            .where(Segment.asset_id == source_asset_id)
            .order_by(Segment.created_at.asc())
        ).first()
        if segment:
            return segment
    raise HTTPException(status_code=409, detail="Source review task creation requires a source segment or source asset with extracted text.")


def _create_or_open_source_review_task_from_chat(payload: Dict[str, Any], session: Session) -> Dict[str, Any]:
    existing_task_id = _text(payload.get("task_id"))
    if existing_task_id:
        task = session.get(Task, existing_task_id)
        if task is None or task.status != "ready":
            raise HTTPException(status_code=409, detail="Source review task to open is no longer ready.")
        return {
            "created": False,
            "task_id": task.id,
            "task_human_id": task.human_id,
            "asset_id": (task.input_payload or {}).get("asset_id"),
            "asset_title": (task.input_payload or {}).get("source_title") or (task.input_payload or {}).get("asset_title") or task.human_id,
            "group_key": None,
            "reason": "existing_ready_source_review_task",
            "review_task_type": "source_review",
        }

    segment = _source_segment_for_review_payload(session, payload)
    existing = session.exec(
        select(Task)
        .where(Task.task_type.in_(["text_segment_review", "text_segment_boundary_review", "email_voice_sample"]))
        .where(Task.target_type == "segment")
        .where(Task.target_id == segment.id)
        .where(Task.status == "ready")
        .order_by(Task.priority.desc(), Task.created_at.asc())
    ).first()
    if existing:
        return {
            "created": False,
            "task_id": existing.id,
            "task_human_id": existing.human_id,
            "asset_id": segment.asset_id,
            "asset_title": (existing.input_payload or {}).get("source_title") or segment.title or existing.human_id,
            "group_key": None,
            "reason": "existing_ready_source_review_task",
            "review_task_type": "source_review",
        }

    asset = session.get(Asset, segment.asset_id)
    source_title = _text(payload.get("source_title")) or segment.title or (asset.title if asset else "") or (asset.original_filename if asset else "") or segment.human_id
    source_query = _text(payload.get("source_query"))
    task = Task(
        human_id=f"TASK_SOURCE_CLUSTER_{_count_rows(session, Task):06d}",
        task_type="text_segment_review",
        target_type="segment",
        target_id=segment.id,
        priority=76,
        queue="text_segments_needing_review",
        reason_created="Created from Chat source-cluster planning so Adam can review source context before downstream generation.",
        input_payload={
            "asset_id": segment.asset_id,
            "source_segment_id": segment.id,
            "source_title": source_title,
            "source_filename": asset.original_filename if asset else None,
            "preview_text": segment.text_content,
            "source_cluster_origin": {
                "query": source_query,
                "candidate_match_quality": _text(payload.get("candidate_match_quality"), "weak_evidence_match"),
                "selection_reason": _text(payload.get("candidate_selection_reason"), "chat_selected_source_cluster"),
                "truth_status": "no_claim",
                "not_memory_claim": True,
                "review_task_type": "source_review",
            },
        },
        required_decisions=[
            "source_genre",
            "authorship",
            "truth_status",
            "usable_for_voice_context",
            "usable_for_grounded_generation",
            "privacy_level",
            "ready_for_processing",
        ],
        created_by="chat_source_cluster",
    )
    session.add(task)
    session.commit()
    session.refresh(task)
    return {
        "created": True,
        "task_id": task.id,
        "task_human_id": task.human_id,
        "asset_id": segment.asset_id,
        "asset_title": source_title,
        "group_key": None,
        "reason": "created_source_review_task",
        "review_task_type": "source_review",
    }


def _execute_chat_turn(
    *,
    payload: ChatTurnRequest,
    session: Session,
    app_settings: Settings,
) -> dict:
    if payload.dismiss_action:
        if not payload.confirm_action_id or not payload.session_id:
            raise HTTPException(status_code=409, detail="A pending chat action is required for dismissal.")
        pending_action = session.get(ChatAction, payload.confirm_action_id)
        if (
            pending_action is None
            or pending_action.session_id != payload.session_id
            or pending_action.status != "pending_confirmation"
            or not pending_action.requires_confirmation
        ):
            raise HTTPException(status_code=409, detail="Chat action dismissal is stale or invalid.")
        return dismiss_pending_chat_action(session=session, request=payload, app_settings=app_settings)
    if payload.confirm_submit:
        if not payload.confirm_action_id or not payload.session_id:
            raise HTTPException(status_code=409, detail="A pending chat submit action is required for confirmation.")
        pending_action = session.get(ChatAction, payload.confirm_action_id)
        if (
            pending_action is None
            or pending_action.session_id != payload.session_id
            or pending_action.action_type != "submit_task"
            or pending_action.status != "pending_confirmation"
            or not pending_action.requires_confirmation
        ):
            raise HTTPException(status_code=409, detail="Chat submit confirmation is stale or invalid.")
        stale_reason = chat_submit_action_stale_reason(session=session, pending_action=pending_action, user_id=payload.user_id)
        if stale_reason:
            mark_chat_action_stale(session=session, pending_action=pending_action, reason=stale_reason)
            raise HTTPException(status_code=409, detail=f"Chat submit confirmation is stale. {stale_reason} Refresh the preview before confirming.")
    if payload.confirm_action and not payload.confirm_submit:
        if not payload.confirm_action_id or not payload.session_id:
            raise HTTPException(status_code=409, detail="A pending chat action is required for confirmation.")
        pending_action = session.get(ChatAction, payload.confirm_action_id)
        if (
            pending_action is None
            or pending_action.session_id != payload.session_id
            or pending_action.action_type not in {"build_dataset_export", "create_or_open_review_task"}
            or pending_action.status != "pending_confirmation"
            or not pending_action.requires_confirmation
        ):
            raise HTTPException(status_code=409, detail="Chat action confirmation is stale or invalid.")
        stale_reason = (
            chat_export_build_action_stale_reason(session=session, pending_action=pending_action)
            if pending_action.action_type == "build_dataset_export"
            else chat_review_task_action_stale_reason(session=session, pending_action=pending_action)
        )
        if stale_reason:
            mark_chat_action_stale(session=session, pending_action=pending_action, reason=stale_reason)
            raise HTTPException(status_code=409, detail=f"Chat action confirmation is stale. {stale_reason} Refresh the preview before confirming.")
    response = build_chat_turn(session=session, request=payload, app_settings=app_settings)
    if payload.confirm_submit:
        submit_payload = response.get("submit_payload")
        if not response.get("ready_to_submit") or not isinstance(submit_payload, dict):
            raise HTTPException(status_code=409, detail="Chat turn is not ready to submit.")
        annotation = submit_task(
            str(submit_payload["task_id"]),
            TaskSubmit(
                annotation_type=None,
                decisions=submit_payload.get("decisions") if isinstance(submit_payload.get("decisions"), dict) else {},
                notes=submit_payload.get("notes") if isinstance(submit_payload.get("notes"), str) else None,
            ),
            session,
            app_settings,
        )
        response = mark_chat_submit_action_executed(session=session, response=response, annotation=annotation)
        session.refresh(annotation)
        annotation_payload = annotation.model_dump(mode="json")
        submitted_actions = response.get("actions", [])
        if not any(isinstance(action, dict) and action.get("type") == "submit_task" and action.get("status") == "executed" for action in submitted_actions):
            submitted_actions = [
                *submitted_actions,
                {"type": "submit_task", "label": "Submitted ticket", "requires_confirmation": False, "status": "executed"},
            ]
        batch_continuation = response.get("batch_continuation") if isinstance(response.get("batch_continuation"), dict) else {}
        next_task_human_id = _text(batch_continuation.get("next_task_human_id")) if batch_continuation.get("continued") else ""
        response = {
            **response,
            "assistant_message": (
                f"Submitted. I moved that ticket forward, saved the resulting records, and opened {next_task_human_id} as the next item in this batch."
                if next_task_human_id
                else "Submitted. I moved that ticket forward and saved the resulting records."
            ),
            "submitted_annotation": annotation_payload,
            "actions": submitted_actions,
        }
    if payload.confirm_action and not payload.confirm_submit:
        pending_action = session.get(ChatAction, payload.confirm_action_id) if payload.confirm_action_id else None
        action_type = pending_action.action_type if pending_action else ""
        if action_type == "create_or_open_review_task":
            review_task_creation_payload = response.get("review_task_creation_payload")
            if not isinstance(review_task_creation_payload, dict):
                raise HTTPException(status_code=409, detail="Chat action is not ready to create a review task.")
            review_task_type = str(review_task_creation_payload.get("review_task_type") or "photo_context")
            if review_task_type == "photo_context":
                photo_asset_id = (
                    review_task_creation_payload.get("asset_id")
                    if isinstance(review_task_creation_payload.get("asset_id"), str)
                    else review_task_creation_payload.get("source_photo_id")
                    if isinstance(review_task_creation_payload.get("source_photo_id"), str)
                    else None
                )
                created = create_photo_context_task_from_inventory(
                    PhotoContextTaskCreate(
                        asset_id=photo_asset_id,
                        group_key=review_task_creation_payload.get("group_key") if isinstance(review_task_creation_payload.get("group_key"), str) else None,
                        use_canonical=True,
                        source_query=review_task_creation_payload.get("source_query") if isinstance(review_task_creation_payload.get("source_query"), str) else None,
                        candidate_match_quality=review_task_creation_payload.get("candidate_match_quality")
                        if isinstance(review_task_creation_payload.get("candidate_match_quality"), str)
                        else None,
                        candidate_selection_reason=review_task_creation_payload.get("candidate_selection_reason")
                        if isinstance(review_task_creation_payload.get("candidate_selection_reason"), str)
                        else None,
                    ),
                    session=session,
                )
            elif review_task_type == "source_review":
                created = _create_or_open_source_review_task_from_chat(review_task_creation_payload, session)
            else:
                raise HTTPException(status_code=409, detail=f"Review task type '{review_task_type}' is not supported yet.")
            response = mark_chat_review_task_action_executed(session=session, response=response, created_task=created)
            response = {
                **response,
                "assistant_message": (
                    f"Created {_text(created.get('task_human_id') if isinstance(created, dict) else created.task_human_id)} from that evidence cluster."
                    if bool(created.get("created") if isinstance(created, dict) else created.created)
                    else f"Opened existing review task {_text(created.get('task_human_id') if isinstance(created, dict) else created.task_human_id)} for that evidence cluster."
                ),
            }
            return response
        export_build_payload = response.get("export_build_payload")
        if not isinstance(export_build_payload, dict):
            raise HTTPException(status_code=409, detail="Chat action is not ready to execute.")
        dataset_export = build_dataset_export(
            DatasetBuildRequest(
                export_type=str(export_build_payload.get("export_type") or ""),
                version=str(export_build_payload.get("version") or "v0"),
                split=str(export_build_payload.get("split") or "train"),
            ),
            session,
        )
        response = mark_chat_export_build_action_executed(
            session=session,
            response=response,
            dataset_export=dataset_export,
        )
        executed_actions = response.get("actions", [])
        if not any(isinstance(action, dict) and action.get("type") == "build_dataset_export" and action.get("status") == "executed" for action in executed_actions):
            executed_actions = [
                *executed_actions,
                {"type": "build_dataset_export", "label": "Built export", "requires_confirmation": False, "status": "executed"},
            ]
        response = {
            **response,
            "assistant_message": (
                f"Built {dataset_export.export_type.upper()} export {dataset_export.human_id} "
                f"with {dataset_export.manifest.get('item_count') if isinstance(dataset_export.manifest, dict) else 0} row(s)."
            ),
            "built_export": dataset_export.model_dump(mode="json"),
            "actions": executed_actions,
        }
    return response


def _chat_action_or_404(session: Session, action_id: str) -> ChatAction:
    action = session.get(ChatAction, action_id)
    if action is None:
        raise HTTPException(status_code=404, detail="Chat action not found.")
    return action


def _action_session_id(action: ChatAction, requested_session_id: Optional[str]) -> str:
    if requested_session_id and requested_session_id != action.session_id:
        raise HTTPException(status_code=409, detail="Chat action session mismatch.")
    return action.session_id


def _action_preview_payload(action: ChatAction) -> Dict[str, Any]:
    payload = action.validated_payload_json if isinstance(action.validated_payload_json, dict) else {}
    preview: Dict[str, Any] = {"validated_payload": payload}
    for key in (
        "submit_payload",
        "export_build_payload",
        "review_task_creation_payload",
        "field_diffs",
        "field_updates",
        "draft_patch",
        "patch_result",
        "context_packet_hash",
    ):
        if key in payload:
            preview[key] = payload[key]
    return preview


def _action_stale_reason(session: Session, action: ChatAction, user_id: str) -> Optional[str]:
    if action.status != "pending_confirmation" or not action.requires_confirmation:
        return "Chat action is not pending confirmation."
    if action.action_type == "submit_task":
        return chat_submit_action_stale_reason(session=session, pending_action=action, user_id=user_id)
    if action.action_type == "build_dataset_export":
        return chat_export_build_action_stale_reason(session=session, pending_action=action)
    if action.action_type == "create_or_open_review_task":
        return chat_review_task_action_stale_reason(session=session, pending_action=action)
    return f"Chat action type '{action.action_type}' cannot be confirmed directly."


def _unique_rows_by_id(rows: list[Any]) -> list[Any]:
    seen: set[str] = set()
    unique: list[Any] = []
    for row in rows:
        row_id = getattr(row, "id", None)
        if not isinstance(row_id, str) or row_id in seen:
            continue
        seen.add(row_id)
        unique.append(row)
    return unique


def _preview_text(value: Any, limit: int = 220) -> str:
    text = value if isinstance(value, str) else ""
    text = " ".join(text.split())
    return text if len(text) <= limit else f"{text[: limit - 3]}..."


def _action_payload(action: ChatAction) -> Dict[str, Any]:
    payload = action.validated_payload_json if isinstance(action.validated_payload_json, dict) else {}
    proposed = action.proposed_payload_json if isinstance(action.proposed_payload_json, dict) else {}
    return payload or proposed


def _chat_session_audit_row(row: ChatSession) -> Dict[str, Any]:
    metadata = row.metadata_json if isinstance(row.metadata_json, dict) else {}
    return {
        "id": row.id,
        "status": row.status,
        "active_task_id": row.active_task_id,
        "mode": row.mode,
        "title": row.title,
        "last_model": row.last_model,
        "last_context_packet_hash": metadata.get("last_context_packet_hash"),
        "last_task_kind": metadata.get("last_task_kind"),
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def _chat_turn_audit_row(row: ChatTurn) -> Dict[str, Any]:
    metadata = row.metadata_json if isinstance(row.metadata_json, dict) else {}
    return {
        "id": row.id,
        "session_id": row.session_id,
        "task_id": row.task_id,
        "role": row.role,
        "content_preview": _preview_text(row.content),
        "model_name": row.model_name,
        "context_packet_hash": row.context_packet_hash,
        "status": metadata.get("status"),
        "live_model_call_used": metadata.get("live_model_call_used"),
        "model_response_id": metadata.get("model_response_id"),
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def _chat_action_audit_row(row: ChatAction, result_counts: Dict[str, int]) -> Dict[str, Any]:
    payload = _action_payload(row)
    field_updates = payload.get("field_updates") if isinstance(payload.get("field_updates"), dict) else {}
    field_diffs = payload.get("field_diffs") if isinstance(payload.get("field_diffs"), list) else []
    return {
        "id": row.id,
        "session_id": row.session_id,
        "turn_id": row.turn_id,
        "task_id": row.task_id,
        "action_type": row.action_type,
        "status": row.status,
        "requires_confirmation": row.requires_confirmation,
        "confirmed_by_user_at": row.confirmed_by_user_at.isoformat() if row.confirmed_by_user_at else None,
        "executed_at": row.executed_at.isoformat() if row.executed_at else None,
        "error_message": row.error_message,
        "context_packet_hash": payload.get("context_packet_hash"),
        "field_update_count": len(field_updates),
        "field_diff_count": len(field_diffs),
        "result_count": result_counts.get(row.id, 0),
    }


def _chat_result_audit_row(row: ChatActionResult) -> Dict[str, Any]:
    return {
        "id": row.id,
        "action_id": row.action_id,
        "object_type": row.object_type,
        "object_id": row.object_id,
        "before_keys": sorted(row.before_json.keys()) if isinstance(row.before_json, dict) else [],
        "after_keys": sorted(row.after_json.keys()) if isinstance(row.after_json, dict) else [],
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def _annotation_chat_provenance(annotation: Annotation) -> Optional[Dict[str, Any]]:
    decisions = annotation.decisions if isinstance(annotation.decisions, dict) else {}
    creates_or_updates = annotation.creates_or_updates if isinstance(annotation.creates_or_updates, dict) else {}
    provenance = decisions.get("chat_provenance") if isinstance(decisions.get("chat_provenance"), dict) else None
    if provenance is None:
        provenance = creates_or_updates.get("chat_provenance") if isinstance(creates_or_updates.get("chat_provenance"), dict) else None
    return provenance


def _provenance_link_rows(annotations: list[Annotation]) -> list[Dict[str, Any]]:
    links: list[Dict[str, Any]] = []
    for annotation in annotations:
        provenance = _annotation_chat_provenance(annotation)
        if not provenance:
            continue
        links.append(
            {
                "annotation_id": annotation.id,
                "task_id": annotation.task_id,
                "target_type": annotation.target_type,
                "target_id": annotation.target_id,
                "chat_session_id": provenance.get("chat_session_id"),
                "preview_turn_id": provenance.get("preview_turn_id"),
                "confirmation_turn_id": provenance.get("confirmation_turn_id"),
                "chat_action_id": provenance.get("chat_action_id"),
                "context_packet_hash": provenance.get("context_packet_hash"),
                "source_refs": provenance.get("source_refs") if isinstance(provenance.get("source_refs"), dict) else {},
            }
        )
    return links


def _chat_audit_quality_gaps(
    *,
    sessions: list[ChatSession],
    turns: list[ChatTurn],
    actions: list[ChatAction],
    results: list[ChatActionResult],
    annotations: list[Annotation],
    provenance_links: list[Dict[str, Any]],
    task_id: Optional[str],
) -> list[str]:
    gaps: list[str] = []
    if not sessions:
        gaps.append("no_chat_session")
    if not turns:
        gaps.append("no_chat_turns")
    if turns and not any(turn.context_packet_hash for turn in turns):
        gaps.append("missing_context_packet_hash")
    if not actions:
        gaps.append("no_chat_actions")
    if any(action.status == "pending_confirmation" for action in actions):
        gaps.append("pending_confirmation")
    if any(action.status in {"failed", "stale"} for action in actions):
        gaps.append("failed_or_stale_actions")
    executed_actions = [action for action in actions if action.status == "executed"]
    if executed_actions and not results:
        gaps.append("executed_action_missing_result")
    if task_id and annotations and not provenance_links:
        gaps.append("submitted_annotation_missing_chat_provenance")
    return gaps


def _chat_audit_quality_signals(
    *,
    turns: list[ChatTurn],
    actions: list[ChatAction],
    annotations: list[Annotation],
) -> Dict[str, Any]:
    action_status_counts: Dict[str, int] = {}
    for action in actions:
        action_status_counts[action.status] = action_status_counts.get(action.status, 0) + 1
    field_source_counts: Dict[str, int] = {}
    for annotation in annotations:
        provenance = _annotation_chat_provenance(annotation)
        field_provenance = provenance.get("field_provenance") if isinstance(provenance, dict) and isinstance(provenance.get("field_provenance"), dict) else {}
        for details in field_provenance.values():
            if isinstance(details, dict):
                source = details.get("source")
                if isinstance(source, str) and source:
                    field_source_counts[source] = field_source_counts.get(source, 0) + 1
    return {
        "action_status_counts": action_status_counts,
        "field_source_counts": field_source_counts,
        "live_model_turn_count": sum(1 for turn in turns if isinstance(turn.metadata_json, dict) and turn.metadata_json.get("live_model_call_used") is True),
        "confirmed_action_count": sum(1 for action in actions if action.confirmed_by_user_at is not None),
        "executed_action_count": sum(1 for action in actions if action.status == "executed"),
    }


@router.get("/audit", response_model=ChatAuditResponse)
def get_chat_audit(
    task_id: Optional[str] = None,
    session_id: Optional[str] = None,
    limit: int = 20,
    session: Session = Depends(get_session),
) -> dict:
    bounded_limit = min(max(limit, 1), 100)
    if task_id and session.get(Task, task_id) is None:
        raise HTTPException(status_code=404, detail="Task not found.")
    requested_session: Optional[ChatSession] = None
    if session_id:
        requested_session = session.get(ChatSession, session_id)
        if requested_session is None:
            raise HTTPException(status_code=404, detail="Chat session not found.")

    audit_sessions: list[ChatSession] = [requested_session] if requested_session else []
    task_turns: list[ChatTurn] = []
    task_actions: list[ChatAction] = []
    if task_id:
        audit_sessions.extend(
            session.exec(
                select(ChatSession)
                .where(ChatSession.active_task_id == task_id)
                .order_by(ChatSession.updated_at.desc())
                .limit(bounded_limit)
            ).all()
        )
        task_turns = session.exec(
            select(ChatTurn)
            .where(ChatTurn.task_id == task_id)
            .order_by(ChatTurn.created_at.desc())
            .limit(bounded_limit)
        ).all()
        task_actions = session.exec(
            select(ChatAction)
            .where(ChatAction.task_id == task_id)
            .order_by(ChatAction.created_at.desc())
            .limit(bounded_limit)
        ).all()

    session_ids = {row.id for row in audit_sessions if row is not None}
    session_ids.update(row.session_id for row in task_turns)
    session_ids.update(row.session_id for row in task_actions)
    if not session_ids and not task_id:
        audit_sessions = session.exec(select(ChatSession).order_by(ChatSession.updated_at.desc()).limit(bounded_limit)).all()
        session_ids.update(row.id for row in audit_sessions)
    elif session_ids:
        audit_sessions.extend(session.exec(select(ChatSession).where(ChatSession.id.in_(session_ids))).all())

    audit_sessions = _unique_rows_by_id(audit_sessions)
    session_ids = {row.id for row in audit_sessions}

    turns = list(task_turns)
    actions = list(task_actions)
    if session_ids:
        turns.extend(
            session.exec(
                select(ChatTurn)
                .where(ChatTurn.session_id.in_(session_ids))
                .order_by(ChatTurn.created_at.desc())
                .limit(bounded_limit)
            ).all()
        )
        actions.extend(
            session.exec(
                select(ChatAction)
                .where(ChatAction.session_id.in_(session_ids))
                .order_by(ChatAction.created_at.desc())
                .limit(bounded_limit)
            ).all()
        )
    turns = _unique_rows_by_id(turns)[:bounded_limit]
    actions = _unique_rows_by_id(actions)[:bounded_limit]

    action_ids = [action.id for action in actions]
    results: list[ChatActionResult] = []
    if action_ids:
        results = session.exec(
            select(ChatActionResult)
            .where(ChatActionResult.action_id.in_(action_ids))
            .order_by(ChatActionResult.created_at.desc())
            .limit(bounded_limit)
        ).all()
    result_counts: Dict[str, int] = {}
    for result in results:
        result_counts[result.action_id] = result_counts.get(result.action_id, 0) + 1

    annotations: list[Annotation] = []
    if task_id:
        annotations = session.exec(
            select(Annotation)
            .where(Annotation.task_id == task_id)
            .order_by(Annotation.created_at.desc())
            .limit(bounded_limit)
        ).all()
    provenance_links = _provenance_link_rows(annotations)
    quality_signals = _chat_audit_quality_signals(turns=turns, actions=actions, annotations=annotations)
    action_status_counts = quality_signals["action_status_counts"]
    latest_context_packet_hash = next((turn.context_packet_hash for turn in turns if turn.context_packet_hash), None)
    return {
        "audit_type": "chat_workbench_audit",
        "task_id": task_id,
        "session_id": session_id,
        "session_count": len(audit_sessions),
        "turn_count": len(turns),
        "action_count": len(actions),
        "result_count": len(results),
        "action_status_counts": action_status_counts,
        "latest_context_packet_hash": latest_context_packet_hash,
        "quality_gaps": _chat_audit_quality_gaps(
            sessions=audit_sessions,
            turns=turns,
            actions=actions,
            results=results,
            annotations=annotations,
            provenance_links=provenance_links,
            task_id=task_id,
        ),
        "quality_signals": quality_signals,
        "sessions": [_chat_session_audit_row(row) for row in audit_sessions],
        "recent_turns": [_chat_turn_audit_row(row) for row in turns],
        "recent_actions": [_chat_action_audit_row(row, result_counts) for row in actions],
        "recent_results": [_chat_result_audit_row(row) for row in results],
        "provenance_links": provenance_links,
    }


@router.get("/sessions", response_model=ChatSessionListResponse)
def list_chat_sessions(
    user_id: str = "adam",
    limit: int = 20,
    session: Session = Depends(get_session),
) -> dict:
    bounded_limit = min(max(limit, 1), 100)
    rows = session.exec(
        select(ChatSession)
        .where(ChatSession.user_id == user_id)
        .order_by(ChatSession.updated_at.desc())
        .limit(bounded_limit)
    ).all()
    return {"sessions": [row.model_dump(mode="json") for row in rows]}


@router.post("/sessions", response_model=ChatSessionResponse)
def create_chat_session(
    payload: ChatSessionCreate,
    session: Session = Depends(get_session),
) -> dict:
    if payload.active_task_id and session.get(Task, payload.active_task_id) is None:
        raise HTTPException(status_code=404, detail="Active task not found.")
    chat_session = ChatSession(
        user_id=payload.user_id,
        mode=payload.mode,
        active_task_id=payload.active_task_id,
        title=payload.title,
        metadata_json={"created_from": "chat_sessions_endpoint"},
    )
    session.add(chat_session)
    session.commit()
    session.refresh(chat_session)
    restored = chat_session_payload(session, chat_session.id)
    if restored is None:
        raise HTTPException(status_code=500, detail="Chat session was created but could not be loaded.")
    return restored


@router.post("/turn", response_model=ChatTurnResponse)
def create_chat_turn(
    payload: ChatTurnRequest,
    session: Session = Depends(get_session),
    app_settings: Settings = Depends(get_settings),
) -> dict:
    return _execute_chat_turn(payload=payload, session=session, app_settings=app_settings)


@router.post("/actions/{action_id}/preview", response_model=ChatActionPreviewResponse)
def preview_chat_action(
    action_id: str,
    payload: Optional[ChatActionCommandRequest] = None,
    session: Session = Depends(get_session),
) -> dict:
    command = payload or ChatActionCommandRequest()
    action = _chat_action_or_404(session, action_id)
    _action_session_id(action, command.session_id)
    stale_reason = _action_stale_reason(session, action, command.user_id)
    return {
        "action": action.model_dump(mode="json"),
        "preview_payload": _action_preview_payload(action),
        "stale_reason": stale_reason,
        "can_confirm": stale_reason is None and action.action_type in {"submit_task", "build_dataset_export", "create_or_open_review_task"},
    }


@router.post("/actions/{action_id}/confirm", response_model=ChatTurnResponse)
def confirm_chat_action(
    action_id: str,
    payload: Optional[ChatActionCommandRequest] = None,
    session: Session = Depends(get_session),
    app_settings: Settings = Depends(get_settings),
) -> dict:
    command = payload or ChatActionCommandRequest()
    action = _chat_action_or_404(session, action_id)
    session_id = _action_session_id(action, command.session_id)
    if action.action_type == "submit_task":
        turn_payload = ChatTurnRequest(
            message=command.message or "confirm",
            session_id=session_id,
            task_id=action.task_id,
            mode=command.mode,
            confirm_submit=True,
            confirm_action_id=action.id,
            user_id=command.user_id,
        )
    elif action.action_type == "build_dataset_export":
        turn_payload = ChatTurnRequest(
            message=command.message or "confirm",
            session_id=session_id,
            mode=command.mode,
            confirm_action=True,
            confirm_action_id=action.id,
            user_id=command.user_id,
        )
    elif action.action_type == "create_or_open_review_task":
        turn_payload = ChatTurnRequest(
            message=command.message or "confirm",
            session_id=session_id,
            mode=command.mode,
            confirm_action=True,
            confirm_action_id=action.id,
            user_id=command.user_id,
        )
    else:
        raise HTTPException(status_code=409, detail=f"Chat action type '{action.action_type}' cannot be confirmed directly.")
    return _execute_chat_turn(payload=turn_payload, session=session, app_settings=app_settings)


@router.post("/actions/{action_id}/dismiss", response_model=ChatTurnResponse)
def dismiss_chat_action(
    action_id: str,
    payload: Optional[ChatActionCommandRequest] = None,
    session: Session = Depends(get_session),
    app_settings: Settings = Depends(get_settings),
) -> dict:
    command = payload or ChatActionCommandRequest(message="dismiss")
    action = _chat_action_or_404(session, action_id)
    session_id = _action_session_id(action, command.session_id)
    turn_payload = ChatTurnRequest(
        message=command.message or "dismiss",
        session_id=session_id,
        task_id=action.task_id,
        mode=command.mode,
        dismiss_action=True,
        confirm_action_id=action.id,
        user_id=command.user_id,
    )
    return _execute_chat_turn(payload=turn_payload, session=session, app_settings=app_settings)


@router.get("/sessions/{session_id}", response_model=ChatSessionResponse)
def get_chat_session(
    session_id: str,
    session: Session = Depends(get_session),
) -> dict:
    payload = chat_session_payload(session, session_id)
    if payload is None:
        raise HTTPException(status_code=404, detail="Chat session not found.")
    return payload
