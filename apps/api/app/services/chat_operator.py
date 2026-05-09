from __future__ import annotations

import json
import base64
import hashlib
import logging
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlmodel import Session, select

from app.config import Settings, settings
from app.exports.jsonl import export_dry_run, to_jsonl
from app.models import AssetSnapshot, ChatAction, ChatActionResult, ChatSession, ChatTurn, Derivative, ObjectFile, Task, TaskDraft
from app.schemas import ChatMessage, ChatTurnRequest
from app.services.downstream_readiness import compile_downstream_bottleneck_queue
from app.services.model_generation import live_text_generation_ready
from app.services.operator_assistant import (
    _allowed_update_keys,
    _filter_field_updates,
    _required_missing_fields,
    _submit_requested,
)


MAX_HISTORY_MESSAGES = 10
MAX_CONTEXT_CHARS = 9000
MAX_CHAT_IMAGE_BYTES = 5 * 1024 * 1024
MAX_CHAT_FIELD_TEXT_CHARS = 6000
MAX_CHAT_FIELD_LIST_ITEMS = 25
MAX_CHAT_FIELD_OBJECT_KEYS = 50
MAX_DRAFT_PATCH_OPERATIONS = 8
logger = logging.getLogger(__name__)
CHAT_ACTION_CONTRACTS: Dict[str, Dict[str, Any]] = {
    "ask_question": {
        "effect": "conversation",
        "requires_confirmation": False,
        "description": "Ask Adam one concise follow-up question.",
    },
    "update_task_draft": {
        "effect": "task_draft",
        "requires_confirmation": False,
        "description": "Write validated field_updates to the reversible task draft.",
    },
    "preview_submit": {
        "effect": "submit_preview",
        "requires_confirmation": False,
        "description": "Prepare a non-mutating submit preview from the current draft.",
    },
    "preview_task_submission": {
        "effect": "submit_preview",
        "requires_confirmation": False,
        "description": "PRD synonym for preview_submit.",
    },
    "submit_task": {
        "effect": "confirmed_mutation",
        "requires_confirmation": True,
        "description": "Submit the previewed task payload through backend validation.",
    },
    "open_task": {
        "effect": "navigation",
        "requires_confirmation": False,
        "description": "Focus an existing task in the workbench UI.",
    },
    "focus_task": {
        "effect": "navigation",
        "requires_confirmation": False,
        "description": "PRD synonym for open_task.",
    },
    "skip_task": {
        "effect": "queue_navigation",
        "requires_confirmation": False,
        "description": "Move away from the current task without submitting it.",
    },
    "flag_task": {
        "effect": "task_draft",
        "requires_confirmation": False,
        "description": "Record a reversible task flag or blocker note in the draft.",
    },
    "create_memory_note": {
        "effect": "task_draft",
        "requires_confirmation": False,
        "description": "Stage Adam-provided memory context in the task draft.",
    },
    "create_photo_context": {
        "effect": "task_draft",
        "requires_confirmation": False,
        "description": "Stage structured photo context in the task draft.",
    },
    "update_photo_context": {
        "effect": "task_draft",
        "requires_confirmation": False,
        "description": "Update structured photo context fields in the task draft.",
    },
    "create_prompt_response_candidate": {
        "effect": "task_draft",
        "requires_confirmation": False,
        "description": "Stage a prompt-response candidate change in the task draft.",
    },
    "update_prompt_response_candidate": {
        "effect": "task_draft",
        "requires_confirmation": False,
        "description": "Update prompt-response candidate fields in the task draft.",
    },
    "update_dpo_pair": {
        "effect": "task_draft",
        "requires_confirmation": False,
        "description": "Stage chosen/rejected/rationale changes in the task draft.",
    },
    "mark_candidate_approved": {
        "effect": "confirmed_mutation",
        "requires_confirmation": True,
        "description": "Approve a candidate only through explicit confirmation.",
    },
    "mark_candidate_rejected": {
        "effect": "confirmed_mutation",
        "requires_confirmation": True,
        "description": "Reject a candidate only through explicit confirmation.",
    },
    "create_export_preview": {
        "effect": "export_preview",
        "requires_confirmation": False,
        "description": "Create a non-mutating export readiness or JSONL preview.",
    },
    "create_or_open_review_task": {
        "effect": "confirmed_mutation",
        "requires_confirmation": True,
        "description": "Create or open a review task from a retrieval-gap/photo/source cluster after explicit confirmation.",
    },
    "build_dataset_export": {
        "effect": "confirmed_mutation",
        "requires_confirmation": True,
        "description": "Build a dataset export record after dry-run confirmation.",
    },
}
ALLOWED_CHAT_ACTIONS = set(CHAT_ACTION_CONTRACTS)
CHAT_READ_TOOL_CONTRACTS: Dict[str, Dict[str, Any]] = {
    "inspect_active_task": {
        "description": "Read the active task summary, kind, missing required fields, and current intent.",
        "returns": "task summary, task kind, required decisions, missing fields, current user intent",
    },
    "inspect_object_contract": {
        "description": "Read the editable object contract before deciding what fields/actions to use.",
        "returns": "work surface, object contracts, allowed field updates, action contracts",
    },
    "inspect_source_material": {
        "description": "Read the task source payload and source associations without mutating anything.",
        "returns": "source refs, associated object ids, source material preview, safe payload excerpt",
    },
    "inspect_image_context": {
        "description": "Read image availability and photo context for photo-oriented tickets.",
        "returns": "image asset id, preview URL, local pixel availability, dimensions, status",
    },
    "inspect_current_draft": {
        "description": "Read the merged task decisions and reversible draft state before writing updates.",
        "returns": "current merged decisions, draft decisions, missing fields",
    },
    "retrieve_source_context": {
        "description": "Search reviewed memory/source embedding records for evidence related to the current ticket or Adam's latest query.",
        "returns": "boundary-filtered retrieval results, vector/lexical match metadata, and retrieval-gap next actions",
    },
    "inspect_evidence_corpus": {
        "description": "Inspect the unified reviewed evidence corpus across photos, source excerpts, and approved training voice records.",
        "returns": "corpus family counts, embedding status counts, reviewed records, held records, and safety boundaries without vector values",
    },
    "plan_ranked_evidence_clusters": {
        "description": "Plan from a ranked query over reviewed photo memories, source excerpts, and approved voice records, grouped into evidence clusters.",
        "returns": "boundary-filtered evidence clusters, top records, matched terms, planning hints, retrieval-gap workflow metadata, and safety boundaries without vector values or vector file pointers",
    },
    "inspect_work_queue_plan": {
        "description": "Inspect ready tickets, training-board columns, downstream bottlenecks, and route candidates before choosing the next task.",
        "returns": "route counts, top ready task candidates, training-board column summaries, bottleneck summary, recommended open-task target, and safety boundaries",
    },
    "preview_source_pair_generation": {
        "description": "Dry-run evidence-backed SFT/DPO prompt-pair generation for the active source review ticket without creating tasks. May use the live text model when ready.",
        "returns": "candidate and held pair counts, live/no-call status, source evidence policy, strategy counts, previews, and safety boundaries",
    },
}
ALLOWED_CHAT_READ_TOOLS = set(CHAT_READ_TOOL_CONTRACTS)
DRAFT_UPDATE_CHAT_ACTIONS = {
    "update_task_draft",
    "flag_task",
    "create_memory_note",
    "create_photo_context",
    "update_photo_context",
    "create_prompt_response_candidate",
    "update_prompt_response_candidate",
    "update_dpo_pair",
}
CONFIRMATION_REQUIRED_CHAT_ACTIONS = {
    action_type
    for action_type, contract in CHAT_ACTION_CONTRACTS.items()
    if bool(contract.get("requires_confirmation"))
}


class ChatPlanAction(BaseModel):
    model_config = ConfigDict(extra="ignore")

    type: str
    label: str = ""
    task_id: str = ""
    asset_id: str = ""
    group_key: str = ""
    source_query: str = ""
    candidate_match_quality: str = ""
    candidate_selection_reason: str = ""
    review_task_type: str = ""
    source_asset_id: str = ""
    source_photo_id: str = ""
    source_segment_id: str = ""
    source_title: str = ""
    requires_confirmation: bool = False


class ChatOperatorPlan(BaseModel):
    model_config = ConfigDict(extra="allow")

    assistant_message: str = ""
    work_surface: Dict[str, Any] = Field(default_factory=dict)
    active_task_id: str = ""
    next_question: str = ""
    needs_user_response: bool = True
    field_updates: Dict[str, Any] = Field(default_factory=dict)
    draft_patch: List[Dict[str, Any]] = Field(default_factory=list)
    notes_append: str = ""
    ready_to_submit: bool = False
    actions: List[ChatPlanAction] = Field(default_factory=list)
    confidence: str = ""
    uncertainties: List[Any] = Field(default_factory=list)
    evidence_refs: List[Any] = Field(default_factory=list)
    ui_hints: Dict[str, Any] = Field(default_factory=dict)
    status: str = ""
    error: Optional[str] = None


def _chat_reasoning_effort(app_settings: Settings) -> str:
    return _string(getattr(app_settings, "chat_reasoning_effort", None), "medium")


def _string(value: Any, fallback: str = "") -> str:
    return value if isinstance(value, str) and value.strip() else fallback


def _optional_int(value: Any) -> Optional[int]:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return None
    return None


def _value_from_mapping_or_attr(value: Any, key: str) -> Any:
    if isinstance(value, dict):
        return value.get(key)
    return getattr(value, key, None)


def _response_usage_observability(response: Any) -> Dict[str, Optional[int]]:
    usage = getattr(response, "usage", None)
    return {
        "input_token_count": _optional_int(_value_from_mapping_or_attr(usage, "input_tokens")),
        "output_token_count": _optional_int(_value_from_mapping_or_attr(usage, "output_tokens")),
    }


def _log_chat_event(event: str, **fields: Any) -> None:
    safe_fields = {
        key: value
        for key, value in fields.items()
        if value not in (None, "", [], {}) and key not in {"content", "prompt", "payload", "context_packet"}
    }
    logger.info(
        "chat_operator.%s",
        event,
        extra={"chat_event": event, **safe_fields},
    )


def _chat_action_contracts_for_context() -> List[Dict[str, Any]]:
    return [
        {
            "action_type": action_type,
            "effect": _string(contract.get("effect")),
            "requires_confirmation": bool(contract.get("requires_confirmation")),
            "description": _string(contract.get("description")),
        }
        for action_type, contract in sorted(CHAT_ACTION_CONTRACTS.items())
    ]


def _chat_read_tool_contracts_for_context() -> List[Dict[str, Any]]:
    return [
        {
            "tool_name": tool_name,
            "description": _string(contract.get("description")),
            "returns": _string(contract.get("returns")),
        }
        for tool_name, contract in sorted(CHAT_READ_TOOL_CONTRACTS.items())
    ]


def _chat_action_requires_confirmation(action_type: str, requested: bool = False) -> bool:
    return action_type in CONFIRMATION_REQUIRED_CHAT_ACTIONS or requested


def _truncate_text(value: Any, limit: int = 2500) -> str:
    if isinstance(value, str):
        text = value
    else:
        text = json.dumps(value, default=str, ensure_ascii=False)
    if len(text) <= limit:
        return text
    return text[: limit - 20].rstrip() + "\n[truncated]"


def _sanitize_chat_value(value: Any, *, depth: int = 0) -> Any:
    if depth > 4:
        return _truncate_text(value, 500)
    if isinstance(value, str):
        return _truncate_text(value, MAX_CHAT_FIELD_TEXT_CHARS)
    if isinstance(value, list):
        return [_sanitize_chat_value(item, depth=depth + 1) for item in value[:MAX_CHAT_FIELD_LIST_ITEMS]]
    if isinstance(value, dict):
        sanitized: Dict[str, Any] = {}
        for index, (key, item) in enumerate(value.items()):
            if index >= MAX_CHAT_FIELD_OBJECT_KEYS:
                break
            sanitized[str(key)[:120]] = _sanitize_chat_value(item, depth=depth + 1)
        return sanitized
    return value


def _sanitize_chat_field_updates(field_updates: Dict[str, Any]) -> Dict[str, Any]:
    return {key: _sanitize_chat_value(value) for key, value in field_updates.items()}


def _normalize_draft_patch(value: Any) -> List[Dict[str, Any]]:
    if not isinstance(value, list):
        return []
    normalized: List[Dict[str, Any]] = []
    allowed_ops = {"set", "clear", "copy", "move", "swap", "append"}
    for raw_operation in value[:MAX_DRAFT_PATCH_OPERATIONS]:
        if not isinstance(raw_operation, dict):
            continue
        operation_type = _string(raw_operation.get("op")) or _string(raw_operation.get("type"))
        operation_type = operation_type.strip().lower()
        if operation_type not in allowed_ops:
            continue
        operation: Dict[str, Any] = {"op": operation_type}
        field = _string(raw_operation.get("field"))
        source = _string(raw_operation.get("from")) or _string(raw_operation.get("source"))
        destination = _string(raw_operation.get("to")) or _string(raw_operation.get("target"))
        left = _string(raw_operation.get("left"))
        right = _string(raw_operation.get("right"))
        if field:
            operation["field"] = field
        if source:
            operation["from"] = source
        if destination:
            operation["to"] = destination
        if left:
            operation["left"] = left
        if right:
            operation["right"] = right
        if "value" in raw_operation:
            operation["value"] = _sanitize_chat_value(raw_operation.get("value"))
        reason = _string(raw_operation.get("reason"))
        if reason:
            operation["reason"] = _truncate_text(reason, 400)
        normalized.append(operation)
    return normalized


def _draft_patch_from_adam_message(
    *,
    task: Task,
    source_decisions: Dict[str, Any],
    request: ChatTurnRequest,
) -> List[Dict[str, Any]]:
    if _task_kind(task) != "prompt_response_review":
        return []
    text = request.message.lower()
    mentions_chosen = "chosen" in text or "preferred" in text
    mentions_rejected = "rejected" in text or "weaker" in text
    wants_move_or_copy = any(phrase in text for phrase in ("move", "copy", "take", "put it", "put the", "over to", "shift"))
    wants_swap = any(phrase in text for phrase in ("swap", "flip", "switch"))
    if wants_swap and mentions_chosen and mentions_rejected:
        return [
            {"op": "swap", "left": "chosen", "right": "rejected", "reason": "Adam asked to swap preferred and rejected sides."},
            {"op": "set", "field": "artifact_mode", "value": "dpo"},
        ]
    if not (mentions_chosen and mentions_rejected and wants_move_or_copy):
        return []
    source_field = "chosen"
    if not _string(source_decisions.get(source_field)):
        source_field = "content" if _string(source_decisions.get("content")) else "adam_gold_edit"
    operations: List[Dict[str, Any]] = [
        {
            "op": "copy",
            "from": source_field,
            "to": "rejected",
            "reason": "Adam asked to move the current preferred text to the rejected/weaker side.",
        },
        {"op": "clear", "field": "chosen"},
        {"op": "set", "field": "artifact_mode", "value": "dpo"},
    ]
    if _string(source_decisions.get("content")):
        operations.insert(2, {"op": "clear", "field": "content"})
    return operations


def _patch_blocked_result(operations: List[Dict[str, Any]], reason: str) -> Dict[str, Any]:
    return {
        "applied": False,
        "operations": operations,
        "field_updates": {},
        "field_diffs": [],
        "blocked_reason": reason,
    }


def _patch_field_allowed(field: str, allowed_fields: set[str]) -> bool:
    return bool(field and field in allowed_fields)


def _draft_patch_diff(
    *,
    task: Task,
    field: str,
    before: Any,
    after: Any,
    operation: str,
    source_field: Optional[str] = None,
) -> Dict[str, Any]:
    if before == after and operation != "clear":
        change_type = "unchanged"
    elif operation == "clear":
        change_type = "cleared"
    elif operation == "copy":
        change_type = "copied"
    elif operation == "move":
        change_type = "moved"
    elif operation == "swap":
        change_type = "swapped"
    elif operation == "append":
        change_type = "appended"
    elif _empty_like(after):
        change_type = "removed"
    elif _empty_like(before):
        change_type = "added"
    else:
        change_type = "set"
    row: Dict[str, Any] = {
        "field": field,
        "before": before,
        "after": after,
        "change_type": change_type,
        "patch_op": operation,
    }
    if source_field:
        row["source_field"] = source_field
    value_source = _field_update_source_for_task(task, field)
    if value_source:
        row["value_source"] = value_source
    return row


def _append_patch_value(existing: Any, value: Any) -> Any:
    if isinstance(existing, list):
        additions = value if isinstance(value, list) else [value]
        appended = list(existing)
        for item in additions:
            if item not in ("", None, [], {}) and item not in appended:
                appended.append(item)
        return appended
    existing_text = _string(existing)
    value_text = _string(value)
    if not existing_text:
        return value_text
    if not value_text:
        return existing_text
    return _append_context_note(existing_text, value_text)


def _resolve_draft_patch(
    *,
    task: Task,
    current_decisions: Dict[str, Any],
    operations: List[Dict[str, Any]],
    ready_to_submit: bool = False,
) -> Dict[str, Any]:
    if not operations:
        return {
            "applied": False,
            "operations": [],
            "field_updates": {},
            "field_diffs": [],
            "blocked_reason": "",
        }
    allowed_fields = _allowed_update_keys(task)
    working = dict(current_decisions)
    updates: Dict[str, Any] = {}
    diffs: List[Dict[str, Any]] = []
    effective_change = False

    def set_field(field: str, value: Any, operation: str, source_field: Optional[str] = None) -> Optional[str]:
        nonlocal effective_change
        if not _patch_field_allowed(field, allowed_fields):
            return f"'{field}' is not an editable field on this ticket."
        before = working.get(field)
        working[field] = value
        updates[field] = value
        if before != value:
            effective_change = True
        diffs.append(_draft_patch_diff(task=task, field=field, before=before, after=value, operation=operation, source_field=source_field))
        return None

    for operation in operations:
        operation_type = _string(operation.get("op")).lower()
        if operation_type == "set":
            field = _string(operation.get("field"))
            if "value" not in operation:
                return _patch_blocked_result(operations, f"The set operation for '{field or 'unknown'}' did not include a value.")
            reason = set_field(field, _sanitize_chat_value(operation.get("value")), "set")
            if reason:
                return _patch_blocked_result(operations, reason)
        elif operation_type == "clear":
            field = _string(operation.get("field"))
            reason = set_field(field, "", "clear")
            if reason:
                return _patch_blocked_result(operations, reason)
        elif operation_type in {"copy", "move"}:
            source_field = _string(operation.get("from"))
            destination_field = _string(operation.get("to"))
            if not source_field or source_field not in working:
                return _patch_blocked_result(operations, f"The source field '{source_field or 'unknown'}' is not available on this ticket.")
            source_value = working.get(source_field)
            if _empty_like(source_value):
                return _patch_blocked_result(operations, f"The source field '{source_field}' is empty, so there is nothing to {operation_type}.")
            reason = set_field(destination_field, source_value, operation_type, source_field=source_field)
            if reason:
                return _patch_blocked_result(operations, reason)
            if operation_type == "move":
                reason = set_field(source_field, "", "clear", source_field=source_field)
                if reason:
                    return _patch_blocked_result(operations, reason)
        elif operation_type == "swap":
            left = _string(operation.get("left"))
            right = _string(operation.get("right"))
            if not _patch_field_allowed(left, allowed_fields) or not _patch_field_allowed(right, allowed_fields):
                return _patch_blocked_result(operations, "Both swap fields must be editable fields on this ticket.")
            left_value = working.get(left)
            right_value = working.get(right)
            if _empty_like(left_value) and _empty_like(right_value):
                return _patch_blocked_result(operations, "Both swap fields are empty.")
            reason = set_field(left, right_value, "swap", source_field=right)
            if reason:
                return _patch_blocked_result(operations, reason)
            reason = set_field(right, left_value, "swap", source_field=left)
            if reason:
                return _patch_blocked_result(operations, reason)
        elif operation_type == "append":
            field = _string(operation.get("field"))
            value = _sanitize_chat_value(operation.get("value"))
            if _empty_like(value):
                return _patch_blocked_result(operations, f"The append operation for '{field or 'unknown'}' did not include a value.")
            if not _patch_field_allowed(field, allowed_fields):
                return _patch_blocked_result(operations, f"'{field}' is not an editable field on this ticket.")
            before = working.get(field)
            after = _append_patch_value(before, value)
            working[field] = after
            updates[field] = after
            if before != after:
                effective_change = True
            diffs.append(_draft_patch_diff(task=task, field=field, before=before, after=after, operation="append"))
        else:
            return _patch_blocked_result(operations, f"Unsupported draft patch operation '{operation_type or 'unknown'}'.")

    if _task_kind(task) == "prompt_response_review":
        final_mode = _artifact_mode(task, working)
        chosen = _string(working.get("chosen"))
        rejected = _string(working.get("rejected"))
        if final_mode == "dpo" and chosen and rejected and chosen.strip() == rejected.strip():
            return _patch_blocked_result(operations, "Chosen and Rejected would be identical after this patch.")
        if ready_to_submit:
            missing = _required_missing_fields(task, _normalize_prompt_pair_decision_state(task, working))
            if missing:
                return _patch_blocked_result(operations, f"The patch would leave required field(s) empty: {', '.join(missing)}.")

    return {
        "applied": bool(updates) and effective_change,
        "operations": operations,
        "field_updates": updates if effective_change else {},
        "field_diffs": diffs if effective_change else [],
        "blocked_reason": "" if updates and effective_change else "The patch did not change any editable fields.",
    }


def _patch_applied_message(patch_result: Dict[str, Any], *, apply_updates: bool) -> str:
    operations = patch_result.get("operations") if isinstance(patch_result.get("operations"), list) else []
    copied_chosen_to_rejected = any(
        isinstance(operation, dict)
        and operation.get("op") in {"copy", "move"}
        and operation.get("from") in {"chosen", "content", "adam_gold_edit"}
        and operation.get("to") == "rejected"
        for operation in operations
    )
    cleared_chosen = any(isinstance(operation, dict) and operation.get("op") == "clear" and operation.get("field") == "chosen" for operation in operations)
    if copied_chosen_to_rejected and cleared_chosen:
        prefix = "Applied" if apply_updates else "Previewed"
        return f"{prefix}: moved the current Chosen/Preferred text into Rejected. Chosen is now empty and ready for your replacement."
    return "Applied the draft patch to this ticket." if apply_updates else "Previewed the draft patch for this ticket."


def _patch_blocked_message(patch_result: Dict[str, Any]) -> str:
    reason = _string(patch_result.get("blocked_reason"), "The requested edit did not produce a valid draft patch.")
    return f"I understood the edit, but I did not change the draft. {reason}"


def _plan_contract_summary(plan: Dict[str, Any]) -> Dict[str, Any]:
    confidence = _string(plan.get("confidence"))
    uncertainties = plan.get("uncertainties") if isinstance(plan.get("uncertainties"), list) else []
    evidence_refs = plan.get("evidence_refs") if isinstance(plan.get("evidence_refs"), list) else []
    ui_hints = plan.get("ui_hints") if isinstance(plan.get("ui_hints"), dict) else {}
    rejected_actions = plan.get("rejected_actions") if isinstance(plan.get("rejected_actions"), list) else []
    tool_receipts = plan.get("tool_receipts") if isinstance(plan.get("tool_receipts"), list) else []
    tool_loop_used = bool(plan.get("tool_loop_used"))
    if not any([confidence, uncertainties, evidence_refs, ui_hints, rejected_actions, tool_receipts, tool_loop_used]):
        return {}
    summary = {
        "summary_type": "model_plan_contract",
        "active_task_id": _string(plan.get("active_task_id")),
        "needs_user_response": bool(plan.get("needs_user_response", True)),
        "confidence": confidence,
        "uncertainties": _sanitize_chat_value(uncertainties),
        "evidence_refs": _sanitize_chat_value(evidence_refs),
        "ui_hints": _sanitize_chat_value(ui_hints),
        "rejected_actions": _sanitize_chat_value(rejected_actions),
    }
    if tool_loop_used or tool_receipts:
        summary["tool_loop_used"] = tool_loop_used
        summary["tool_receipts"] = _sanitize_chat_value(tool_receipts)
    return summary


def _parse_json_object(text: str) -> Dict[str, Any]:
    try:
        parsed = json.loads(text)
        return parsed if isinstance(parsed, dict) else {}
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end == -1 or end <= start:
            return {}
        try:
            parsed = json.loads(text[start : end + 1])
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            return {}


def _json_hash(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, default=str, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _normalize_model_plan_contract(raw_plan: Dict[str, Any]) -> Dict[str, Any]:
    normalized = dict(raw_plan)
    draft_updates = normalized.get("draft_updates")
    if "field_updates" not in normalized and isinstance(draft_updates, dict):
        normalized["field_updates"] = draft_updates

    draft_patch = normalized.get("draft_patch")
    patch_operations = normalized.get("patch_operations")
    if "draft_patch" not in normalized and isinstance(patch_operations, list):
        normalized["draft_patch"] = patch_operations
    elif isinstance(draft_patch, dict):
        normalized["draft_patch"] = [draft_patch]

    proposed_actions = normalized.get("proposed_actions")
    if "actions" not in normalized and isinstance(proposed_actions, list):
        actions: List[Dict[str, Any]] = []
        for action in proposed_actions:
            if not isinstance(action, dict):
                continue
            action_type = _string(action.get("type")) or _string(action.get("action_type"))
            if not action_type:
                continue
            actions.append(
                {
                    "type": action_type,
                    "label": _string(action.get("label"), action_type.replace("_", " ")),
                    "task_id": _string(action.get("task_id")) or _string(action.get("target_task_id")),
                    "requires_confirmation": bool(action.get("requires_confirmation")),
                }
            )
        normalized["actions"] = actions
    return normalized


def _validate_chat_plan(raw_plan: Dict[str, Any], *, fallback_status: str) -> Dict[str, Any]:
    raw_plan = _normalize_model_plan_contract(raw_plan)
    observability = raw_plan.get("_observability") if isinstance(raw_plan.get("_observability"), dict) else {}
    required_keys = {"assistant_message", "next_question", "ready_to_submit", "actions"}
    missing_keys = sorted(key for key in required_keys if key not in raw_plan)
    if missing_keys:
        return {
            "status": "invalid_model_plan_fallback",
            "assistant_message": "",
            "next_question": "",
            "field_updates": {},
            "draft_patch": [],
            "notes_append": "",
            "ready_to_submit": False,
            "actions": [],
            "error": f"Invalid chat plan shape: missing required field(s): {', '.join(missing_keys)}",
        }
    try:
        plan = ChatOperatorPlan.model_validate(raw_plan)
    except ValidationError as exc:
        return {
            "status": "invalid_model_plan_fallback",
            "assistant_message": "",
            "next_question": "",
            "field_updates": {},
            "draft_patch": [],
            "notes_append": "",
            "ready_to_submit": False,
            "actions": [],
            "error": f"Invalid chat plan shape: {exc.errors()[0]['type']}",
        }
    data = plan.model_dump()
    data["status"] = _string(data.get("status"), fallback_status)
    validated_actions: List[Dict[str, Any]] = []
    rejected_actions: List[Dict[str, str]] = []
    for action in plan.actions:
        action_data = action.model_dump()
        action_type = _string(action_data.get("type"))
        if action_type not in ALLOWED_CHAT_ACTIONS:
            rejected_actions.append(
                {
                    "type": action_type or "unknown",
                    "label": _string(action_data.get("label")),
                    "reason": "unsupported_chat_action_type",
                }
            )
            continue
        action_data["requires_confirmation"] = _chat_action_requires_confirmation(
            action_type,
            bool(action_data.get("requires_confirmation")),
        )
        validated_actions.append(action_data)
    data["actions"] = validated_actions
    if rejected_actions:
        data["rejected_actions"] = rejected_actions
        prefix = _string(data.get("error"))
        rejected_types = ", ".join(item["type"] for item in rejected_actions)
        data["error"] = f"{prefix + ' ' if prefix else ''}Rejected unsupported chat action(s): {rejected_types}."
    for passthrough_key in ("tool_loop_used", "tool_requests", "tool_receipts"):
        if passthrough_key in raw_plan and passthrough_key not in data:
            data[passthrough_key] = raw_plan[passthrough_key]
    if observability:
        data["_observability"] = observability
    return data


def _chat_session_title(task: Optional[Task]) -> str:
    if task is None:
        return "CharlesOps chat"
    summary = _task_summary(task)
    title = _string(summary.get("title"), task.human_id)
    return title[:180]


def _resolve_chat_session(
    *,
    session: Session,
    request: ChatTurnRequest,
    task: Optional[Task],
    app_settings: Settings,
) -> ChatSession:
    chat_session = session.get(ChatSession, request.session_id) if request.session_id else None
    now = datetime.now(timezone.utc)
    if chat_session is None:
        chat_session = ChatSession(
            user_id=request.user_id,
            active_task_id=task.id if task else None,
            mode=request.mode or "chat",
            title=_chat_session_title(task),
            last_model=app_settings.text_generation_model,
            metadata_json={"created_by": "chat_turn", "workbench_surface": "chat"},
        )
    else:
        chat_session.user_id = request.user_id or chat_session.user_id
        chat_session.active_task_id = task.id if task else chat_session.active_task_id
        chat_session.mode = request.mode or chat_session.mode
        chat_session.title = chat_session.title or _chat_session_title(task)
        chat_session.last_model = app_settings.text_generation_model
        chat_session.updated_at = now
    session.add(chat_session)
    session.flush()
    return chat_session


def _record_chat_turn(
    *,
    session: Session,
    chat_session: ChatSession,
    task: Optional[Task],
    role: str,
    content: str,
    model_name: Optional[str] = None,
    input_token_count: Optional[int] = None,
    output_token_count: Optional[int] = None,
    latency_ms: Optional[int] = None,
    context_packet_hash: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> ChatTurn:
    turn = ChatTurn(
        session_id=chat_session.id,
        task_id=task.id if task else None,
        role=role,
        content=content,
        model_name=model_name,
        input_token_count=input_token_count,
        output_token_count=output_token_count,
        latency_ms=latency_ms,
        context_packet_hash=context_packet_hash,
        metadata_json=metadata or {},
    )
    session.add(turn)
    session.flush()
    return turn


def _stored_turn_dict(turn: ChatTurn) -> Dict[str, Any]:
    return turn.model_dump(mode="json")


def _stored_action_dict(action: ChatAction) -> Dict[str, Any]:
    return action.model_dump(mode="json")


def _action_response_from_record(action: ChatAction) -> Dict[str, Any]:
    metadata = action.metadata_json if isinstance(action.metadata_json, dict) else {}
    return {
        "id": action.id,
        "type": action.action_type,
        "label": _string(metadata.get("label"), action.action_type.replace("_", " ")),
        "requires_confirmation": action.requires_confirmation,
        "status": action.status,
    }


def chat_session_payload(session: Session, session_id: str) -> Optional[Dict[str, Any]]:
    chat_session = session.get(ChatSession, session_id)
    if chat_session is None:
        return None
    turns = session.exec(
        select(ChatTurn).where(ChatTurn.session_id == chat_session.id).order_by(ChatTurn.created_at.asc())
    ).all()
    actions = session.exec(
        select(ChatAction).where(ChatAction.session_id == chat_session.id).order_by(ChatAction.created_at.asc())
    ).all()
    assistant_turns = [turn for turn in turns if turn.role == "assistant"]
    latest_assistant = assistant_turns[-1] if assistant_turns else None
    active_task = session.get(Task, chat_session.active_task_id) if chat_session.active_task_id else None
    draft = _task_draft(session, active_task.id, chat_session.user_id) if active_task else None
    latest_actions = [
        action
        for action in actions
        if (latest_assistant and action.turn_id == latest_assistant.id) or action.status == "pending_confirmation"
    ]
    pending_submit = next((action for action in reversed(latest_actions) if action.action_type == "submit_task" and action.status == "pending_confirmation"), None)
    pending_export_build = next((action for action in reversed(latest_actions) if action.action_type == "build_dataset_export" and action.status == "pending_confirmation"), None)
    latest_update = next((action for action in reversed(latest_actions) if action.action_type == "update_task_draft"), None)
    submit_payload = (
        pending_submit.validated_payload_json.get("submit_payload")
        if pending_submit and isinstance(pending_submit.validated_payload_json, dict)
        else None
    )
    export_build_payload = (
        pending_export_build.validated_payload_json.get("export_build_payload")
        if pending_export_build and isinstance(pending_export_build.validated_payload_json, dict)
        else None
    )
    field_updates = (
        latest_update.validated_payload_json.get("field_updates")
        if latest_update and isinstance(latest_update.validated_payload_json, dict)
        else {}
    )
    field_diffs = (
        latest_update.validated_payload_json.get("field_diffs")
        if latest_update and isinstance(latest_update.validated_payload_json, dict)
        else []
    )
    draft_patch = (
        latest_update.validated_payload_json.get("draft_patch")
        if latest_update and isinstance(latest_update.validated_payload_json, dict)
        else []
    )
    patch_result = (
        latest_update.validated_payload_json.get("patch_result")
        if latest_update and isinstance(latest_update.validated_payload_json, dict)
        else {}
    )
    latest_metadata = latest_assistant.metadata_json if latest_assistant and isinstance(latest_assistant.metadata_json, dict) else {}
    restored_decisions = {
        **(active_task.input_payload if active_task and isinstance(active_task.input_payload, dict) else {}),
        **(draft.decisions if draft and isinstance(draft.decisions, dict) else {}),
    }
    restored_work_surface = latest_metadata.get("work_surface") if isinstance(latest_metadata.get("work_surface"), dict) else {}
    if not restored_work_surface and active_task is not None:
        restored_work_surface = _task_work_surface(active_task, restored_decisions)
    latest_response = None
    if latest_assistant:
        latest_response = {
            "assistant_type": "chat_operator",
            "status": _string(latest_metadata.get("status"), "restored_session"),
            "session_id": chat_session.id,
            "turn_id": latest_assistant.id,
            "context_packet_hash": latest_assistant.context_packet_hash,
            "assistant_message": latest_assistant.content,
            "next_question": None,
            "model_name": chat_session.last_model or latest_assistant.model_name or "",
            "reasoning_effort": "medium",
            "model_ready": False,
            "live_model_call_used": bool(latest_metadata.get("live_model_call_used")),
            "active_task": _task_summary(active_task) if active_task else {},
            "task_selection": latest_metadata.get("task_selection") if isinstance(latest_metadata.get("task_selection"), dict) else {},
            "work_surface": restored_work_surface if isinstance(restored_work_surface, dict) else {},
            "work_summary": latest_metadata.get("work_summary") if isinstance(latest_metadata.get("work_summary"), dict) else {},
            "actions": [_action_response_from_record(action) for action in latest_actions],
            "field_updates": field_updates if isinstance(field_updates, dict) else {},
            "field_diffs": field_diffs if isinstance(field_diffs, list) else [],
            "draft_patch": draft_patch if isinstance(draft_patch, list) else [],
            "patch_result": patch_result if isinstance(patch_result, dict) else {},
            "draft_decisions": draft.decisions if draft and isinstance(draft.decisions, dict) else {},
            "draft": _draft_to_dict(draft),
            "ready_to_submit": pending_submit is not None,
            "submit_payload": submit_payload if isinstance(submit_payload, dict) else None,
            "export_build_payload": export_build_payload if isinstance(export_build_payload, dict) else None,
            "batch_continuation": latest_metadata.get("batch_continuation") if isinstance(latest_metadata.get("batch_continuation"), dict) else None,
            "built_export": None,
            "submitted_annotation": None,
            "safety_policy": _safety_policy(),
            "error": latest_metadata.get("error") if isinstance(latest_metadata.get("error"), str) else None,
        }
    return {
        "session": chat_session.model_dump(mode="json"),
        "turns": [_stored_turn_dict(turn) for turn in turns],
        "actions": [_stored_action_dict(action) for action in actions],
        "latest_response": latest_response,
    }


def _chat_submit_requested(text: str) -> bool:
    normalized = text.strip().lower()
    if normalized in {"ready", "done", "looks ready", "submit", "send it"}:
        return True
    return _submit_requested(text)


def _normalize_intent_text(*values: str) -> str:
    return " ".join(value.strip().lower() for value in values if value and value.strip())


def _route_from_mode(mode: str) -> Optional[str]:
    normalized = mode.strip().lower().replace("-", "_")
    aliases = {
        "photo": "photo_review",
        "photos": "photo_review",
        "photo_review": "photo_review",
        "dpo": "dpo_review",
        "dpo_review": "dpo_review",
        "preference": "dpo_review",
        "preferences": "dpo_review",
        "sft": "sft_review",
        "sft_review": "sft_review",
        "voice": "sft_review",
        "prompt": "prompt_response_review",
        "prompt_response": "prompt_response_review",
        "prompt_response_review": "prompt_response_review",
        "source": "source_review",
        "sources": "source_review",
        "source_review": "source_review",
        "excerpt": "source_review",
        "excerpts": "source_review",
        "export": "export_readiness",
        "export_readiness": "export_readiness",
        "export_preview": "export_preview",
        "export_blocker": "export_blocker",
        "blocker": "export_blocker",
        "blockers": "export_readiness",
    }
    return aliases.get(normalized)


def _route_from_message(message: str) -> Optional[str]:
    text = _normalize_intent_text(message)
    if not text:
        return None
    if _open_export_blocker_requested(message):
        return "export_blocker"
    if any(phrase in text for phrase in ("work on photos", "show me photos", "photo tickets", "photo context", "work on photo", "next photo")):
        return "photo_review"
    if any(phrase in text for phrase in ("dpo", "preference pair", "preference pairs", "chosen and rejected", "chosen/rejected")):
        return "dpo_review"
    if any(phrase in text for phrase in ("sft", "voice example", "voice examples", "gold response", "prompt response", "training example")):
        return "sft_review"
    if any(phrase in text for phrase in ("source excerpt", "source excerpts", "journal", "document", "documents", "source review")):
        return "source_review"
    if any(phrase in text for phrase in ("export blocker", "export blockers", "ready to export", "export readiness", "what is blocked")):
        return "export_readiness"
    return None


def _next_task_requested(message: str) -> bool:
    text = _normalize_intent_text(message)
    if not text:
        return False
    return any(
        phrase in text
        for phrase in (
            "next ticket",
            "next task",
            "next one",
            "next photo",
            "next dpo",
            "next sft",
            "next source",
            "another ticket",
            "another task",
            "another photo",
            "another dpo",
            "another sft",
            "another source",
            "show another",
            "different ticket",
            "skip this",
            "skip this one",
        )
    )


def _skip_current_requested(message: str) -> bool:
    text = _normalize_intent_text(message)
    return any(phrase in text for phrase in ("skip", "skip this", "skip this one", "not this one"))


def _go_back_requested(message: str) -> bool:
    text = _normalize_intent_text(message)
    return any(phrase in text for phrase in ("go back", "back to previous", "previous ticket", "last ticket"))


def _route_for_task(task: Optional[Task]) -> Optional[str]:
    if task is None:
        return None
    kind = _task_kind(task)
    if kind == "prompt_response_review":
        return "dpo_review" if _artifact_mode(task, {}) == "dpo" else "sft_review"
    return kind


def _requested_task_route(request: ChatTurnRequest, selected_task: Optional[Task]) -> Optional[str]:
    return _route_from_mode(request.mode) or _route_from_message(request.message) or (
        _route_for_task(selected_task) if _next_task_requested(request.message) else None
    )


def _open_export_blocker_requested(message: str) -> bool:
    text = _normalize_intent_text(message)
    if not text:
        return False
    has_open_intent = any(phrase in text for phrase in ("open", "focus", "work on", "show me", "take me to", "start on"))
    has_blocker = "blocker" in text or "blocked" in text or "bottleneck" in text
    return has_open_intent and has_blocker


def _task_matches_route(task: Task, route: str) -> bool:
    kind = _task_kind(task)
    if route == "photo_review":
        return kind == "photo_review"
    if route == "dpo_review":
        return kind == "prompt_response_review" and _artifact_mode(task, {}) == "dpo"
    if route == "sft_review":
        return kind == "prompt_response_review" and _artifact_mode(task, {}) != "dpo"
    if route == "prompt_response_review":
        return kind == "prompt_response_review"
    if route == "source_review":
        return kind == "source_review"
    if route == "export_readiness":
        queue = (task.queue or "").lower()
        payload = task.input_payload or {}
        blockers = payload.get("blockers")
        return "export" in queue or "blocker" in queue or bool(blockers)
    if route == "export_blocker":
        return _task_matches_route(task, "export_readiness")
    return False


def _route_label(route: Optional[str]) -> str:
    labels = {
        "photo_review": "photo tickets",
        "dpo_review": "DPO pairs",
        "sft_review": "SFT voice examples",
        "prompt_response_review": "prompt-response reviews",
        "source_review": "source excerpts",
        "export_readiness": "export blockers",
        "export_preview": "export preview",
        "export_blocker": "export blockers",
    }
    return labels.get(route or "", "ready tickets")


def _chat_session_metadata_for_request(session: Session, request: ChatTurnRequest) -> Dict[str, Any]:
    if not request.session_id:
        return {}
    chat_session = session.get(ChatSession, request.session_id)
    if chat_session is None or not isinstance(chat_session.metadata_json, dict):
        return {}
    return chat_session.metadata_json


def _metadata_task_history(metadata: Dict[str, Any]) -> List[str]:
    value = metadata.get("task_history")
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if isinstance(item, str) and item]


def _metadata_skipped_task_ids(metadata: Dict[str, Any]) -> List[str]:
    value = metadata.get("skipped_task_ids")
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if isinstance(item, str) and item]


def _append_context_note(existing: Any, note: str) -> str:
    current = _string(existing)
    if not current:
        return note
    if note in current:
        return current
    return f"{current}\n\n{note}"


def _unique_strings(values: List[str]) -> List[str]:
    seen: set[str] = set()
    result: List[str] = []
    for value in values:
        cleaned = value.strip(" ,.;:\n\t")
        key = cleaned.lower()
        if cleaned and key not in seen:
            seen.add(key)
            result.append(cleaned)
    return result


def _split_listish(value: str) -> List[str]:
    normalized = value.replace(" and ", ", ")
    return _unique_strings([item.strip() for item in normalized.split(",") if item.strip()])


def _labeled_value(message: str, labels: List[str]) -> str:
    label_pattern = "|".join(re.escape(label) for label in labels)
    match = re.search(
        rf"(?:^|[\n.;])\s*(?:{label_pattern})\s*:\s*([^\n.;]+)",
        message,
        flags=re.IGNORECASE,
    )
    return match.group(1).strip() if match else ""


def _sentence_with(message: str, needles: List[str]) -> str:
    parts = [part.strip() for part in re.split(r"(?<=[.!?])\s+|\n+", message) if part.strip()]
    for part in parts:
        lower = part.lower()
        if any(needle in lower for needle in needles):
            return part.strip(" .")
    return ""


def _extract_privacy_level(message: str) -> str:
    text = message.lower()
    explicit = _labeled_value(message, ["privacy", "boundary", "privacy level"])
    if explicit:
        text = explicit.lower()
    if "sealed" in text:
        return "sealed"
    if "sensitive" in text or "private sensitive" in text:
        return "private_sensitive"
    if "family private" in text or "family only" in text:
        return "family_private"
    if "public candidate" in text or "public" in text:
        return "public_candidate"
    return ""


def _extract_ready_for_downstream(message: str) -> str:
    explicit = _labeled_value(message, ["ready", "ready for downstream", "downstream"])
    text = (explicit or message).lower()
    if any(phrase in text for phrase in ("not ready", "do not use", "don't use", "hold", "exclude")):
        return "no"
    if any(phrase in text for phrase in ("ready", "yes", "ok to use", "okay to use", "can use", "use it")):
        return "yes"
    return ""


def _photo_exclusion_requested(message: str) -> bool:
    text = message.lower()
    return any(
        phrase in text
        for phrase in (
            "exclude this photo",
            "exclude the photo",
            "do not use this photo",
            "don't use this photo",
            "dont use this photo",
            "not for training",
            "not for downstream",
            "not for export",
            "not for gallery",
            "hold this photo",
            "keep this photo private",
            "keep it private",
        )
    )


def _extract_photo_people(message: str) -> List[str]:
    explicit = _labeled_value(message, ["people", "person", "who", "visible people"])
    if explicit:
        return _split_listish(explicit)
    known_names = ["Charles", "Adam", "Cathryn", "Ralph", "Dad", "Mom"]
    return [name for name in known_names if re.search(rf"\b{re.escape(name)}\b", message)]


def _extract_photo_place(message: str) -> str:
    explicit = _labeled_value(message, ["place", "where", "location"])
    if explicit:
        return explicit
    text = message.lower()
    if "old orchard" in text:
        return "Old Orchard Beach"
    match = re.search(r"\b(?:at|in|near)\s+([A-Z][A-Za-z]*(?:\s+[A-Z][A-Za-z]*){0,3})", message)
    return match.group(1).strip() if match else ""


def _extract_photo_date(message: str) -> str:
    explicit = _labeled_value(message, ["date", "when", "year"])
    if explicit:
        return explicit
    year = re.search(r"\b(?:19|20)\d{2}\b", message)
    if year:
        return year.group(0)
    month = re.search(
        r"\b(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+(?:19|20)?\d{0,4}\b",
        message,
    )
    return month.group(0).strip() if month else ""


def _extract_photo_event(message: str) -> str:
    explicit = _labeled_value(message, ["event", "occasion"])
    if explicit:
        return explicit
    text = message.lower()
    for keyword, label in [
        ("birthday", "birthday"),
        ("wedding", "wedding"),
        ("thanksgiving", "Thanksgiving"),
        ("beach trip", "beach trip"),
        ("vacation", "vacation"),
        ("family trip", "family trip"),
    ]:
        if keyword in text:
            return label
    return ""


def _extract_open_questions(message: str) -> List[str]:
    explicit = _labeled_value(message, ["open question", "open questions", "uncertainty", "uncertain", "not sure"])
    questions = _split_listish(explicit) if explicit else []
    uncertainty_sentence = _sentence_with(message, ["not sure", "uncertain", "maybe", "i don't know", "i do not know"])
    if uncertainty_sentence:
        questions.append(uncertainty_sentence)
    return _unique_strings(questions)


def _photo_context_review_plan(
    *,
    task: Task,
    current_decisions: Dict[str, Any],
    request: ChatTurnRequest,
    status: str,
    error: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    if _task_kind(task) != "photo_review":
        return None
    message = request.message.strip()
    if not message or _chat_submit_requested(message):
        return None

    field_updates: Dict[str, Any] = {}
    if _photo_exclusion_requested(message):
        field_updates.update(
            {
                "privacy_level": "private",
                "ready_for_downstream": "no",
                "gallery_eligibility": "excluded",
                "privacy_sensitivity": "high",
                "privacy_notes": _append_context_note(
                    current_decisions.get("privacy_notes"),
                    f"Adam exclusion note: {message}",
                ),
            }
        )

    visible = _labeled_value(message, ["visible", "visible facts", "what is visible", "description"])
    if not visible:
        visible = _sentence_with(message, ["this is", "shows", "visible", "standing", "sitting", "wearing", "pictured", "near"])
    if visible and not _string(current_decisions.get("visual_description_correction")):
        field_updates["visual_description_correction"] = visible

    people = _extract_photo_people(visible or message)
    if people:
        existing_people = current_decisions.get("visible_people") if isinstance(current_decisions.get("visible_people"), list) else []
        field_updates["visible_people"] = _unique_strings([*existing_people, *people])

    place = _extract_photo_place(message)
    if place:
        field_updates["place"] = place
        field_updates["places"] = _unique_strings([place])

    date_or_range = _extract_photo_date(message)
    if date_or_range:
        field_updates["date_or_range"] = date_or_range
        if "date_confidence" not in current_decisions:
            field_updates["date_confidence"] = "adam_estimate"

    event = _extract_photo_event(message)
    if event:
        field_updates["event"] = event

    context = _labeled_value(message, ["context", "memory", "meaning", "why it matters", "story"])
    if not context:
        context = message
    field_updates["adam_context_note"] = _append_context_note(
        current_decisions.get("adam_context_note"),
        f"Adam photo context: {context}",
    )

    open_questions = _extract_open_questions(message)
    if open_questions:
        existing_questions = current_decisions.get("open_questions") if isinstance(current_decisions.get("open_questions"), list) else []
        field_updates["open_questions"] = _unique_strings([*existing_questions, *open_questions])

    privacy_level = _extract_privacy_level(message)
    if privacy_level:
        field_updates["privacy_level"] = privacy_level

    ready_for_downstream = _extract_ready_for_downstream(message)
    if ready_for_downstream:
        field_updates["ready_for_downstream"] = ready_for_downstream

    field_updates = _filter_field_updates(task, field_updates)
    if not field_updates:
        return None

    merged = {**current_decisions, **field_updates}
    missing_after = _required_missing_fields(task, merged)
    if "privacy_level" in missing_after:
        next_question = "What boundary should this photo have before it is searchable, retrievable, or used downstream?"
    elif "ready_for_downstream" in missing_after:
        next_question = "Should this photo context be ready for downstream retrieval and memory use, or should it stay held?"
    elif "adam_context_note" in missing_after:
        next_question = "What do you know about this photo beyond the pixels, such as where it was taken or why it matters?"
    elif missing_after:
        next_question = _fallback_next_question(task, merged, missing_after)
    else:
        next_question = "I have the core photo context. Should I prepare this ticket for submit, or is there another uncertainty to preserve?"

    return {
        "status": status,
        "assistant_message": "I split that photo note into visible facts, memory context, people/place/date cues, and boundary fields where I could.",
        "next_question": next_question,
        "field_updates": field_updates,
        "notes_append": "",
        "ready_to_submit": False,
        "actions": [
            {
                "type": "update_task_draft",
                "label": "Capture structured photo context",
                "requires_confirmation": False,
            },
            {"type": "ask_question", "label": next_question, "requires_confirmation": False},
        ],
        "error": error,
    }


def _explicit_rewrite_text(message: str) -> str:
    markers = [
        "replace with:",
        "rewrite to:",
        "rewrite it to:",
        "use this:",
        "make it:",
        "final should be:",
        "say this:",
    ]
    lower = message.lower()
    for marker in markers:
        index = lower.find(marker)
        if index == -1:
            continue
        candidate = message[index + len(marker) :].strip().strip('"').strip("'").strip()
        return candidate if len(candidate) >= 8 else ""
    return ""


def _critique_failure_modes(message: str, *, rejected_side: bool = False) -> List[str]:
    text = message.lower()
    modes: List[str] = []
    checks = [
        ("generic", "rejected_too_generic_not_charles_voice" if rejected_side else "candidate_too_generic"),
        ("too polished", "too_polished_not_charles_voice"),
        ("polished", "too_polished_not_charles_voice"),
        ("too formal", "too_formal_not_charles_voice"),
        ("formal", "too_formal_not_charles_voice"),
        ("explanatory", "too_explanatory_not_charles_voice"),
        ("too sentimental", "too_sentimental"),
        ("sentimental", "too_sentimental"),
        ("missing detail", "missing_specific_detail"),
        ("specific", "needs_more_specific_memory_detail"),
        ("memory", "needs_more_specific_memory_detail"),
        ("too long", "too_long"),
        ("too short", "too_short"),
        ("wrong", "wrong_voice_or_fact"),
    ]
    for needle, mode in checks:
        if needle in text and mode not in modes:
            modes.append(mode)
    return modes


def _prompt_pair_review_plan(
    *,
    task: Task,
    current_decisions: Dict[str, Any],
    request: ChatTurnRequest,
    status: str,
    error: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    if _task_kind(task) != "prompt_response_review":
        return None
    message = request.message.strip()
    if not message or _chat_submit_requested(message):
        return None

    artifact_mode = _artifact_mode(task, current_decisions)
    text = message.lower()
    replacement = _explicit_rewrite_text(message)
    field_updates: Dict[str, Any] = {}
    draft_patch = _draft_patch_from_adam_message(
        task=task,
        source_decisions={**(task.input_payload or {}), **current_decisions},
        request=request,
    )
    next_question = _fallback_next_question(task, current_decisions)
    assistant_message = ""
    actions: List[Dict[str, Any]] = []

    if draft_patch:
        assistant_message = "I can apply that as a structured draft patch."
        next_question = "What should the new chosen response say?"
    elif artifact_mode == "dpo":
        chosen = _string(current_decisions.get("chosen"))
        rejected = _string(current_decisions.get("rejected")) or _string(current_decisions.get("model_draft"))
        wants_flip = any(phrase in text for phrase in ("flip them", "swap them", "rejected is better", "second is better", "use the rejected", "prefer rejected"))
        both_bad = any(
            phrase in text
            for phrase in (
                "both bad",
                "both are bad",
                "neither works",
                "neither is good",
                "reject both",
                "discard both",
                "delete both",
                "both unusable",
            )
        )
        if wants_flip and chosen and rejected:
            field_updates["chosen"] = rejected
            field_updates["rejected"] = chosen
            field_updates["context"] = _append_context_note(
                current_decisions.get("context"),
                f"Adam preference correction: {message}",
            )
            field_updates["failure_modes"] = _critique_failure_modes(message, rejected_side=True) or ["previous_chosen_was_weaker"]
            assistant_message = "I flipped the preferred and weaker sides in the draft and preserved your preference rationale."
            next_question = "Does the new chosen side now sound like the stronger Charles response, or should I revise it further?"
        elif replacement:
            field_updates["chosen"] = replacement
            field_updates["context"] = _append_context_note(
                current_decisions.get("context"),
                f"Adam chose replacement preferred response: {message}",
            )
            assistant_message = "I replaced the chosen side in the draft and kept your rationale attached."
            next_question = "What should the rejected side teach the model not to do?"
        elif both_bad:
            modes = _critique_failure_modes(message, rejected_side=True) or ["both_candidates_unusable"]
            existing_modes = current_decisions.get("failure_modes") if isinstance(current_decisions.get("failure_modes"), list) else []
            field_updates["failure_modes"] = list(dict.fromkeys([*existing_modes, *modes]))
            field_updates["operator_candidate_triage_intent"] = "reject_pair"
            field_updates["context"] = _append_context_note(
                current_decisions.get("context"),
                f"Adam DPO reject-pair decision: {message}",
            )
            assistant_message = "I marked this DPO pair as a reject-pair candidate and saved your rationale."
            next_question = "Should we create a fresh chosen response from scratch, or move to another pair?"
        else:
            modes = _critique_failure_modes(message, rejected_side=True)
            if modes:
                existing_modes = current_decisions.get("failure_modes") if isinstance(current_decisions.get("failure_modes"), list) else []
                field_updates["failure_modes"] = list(dict.fromkeys([*existing_modes, *modes]))
            field_updates["context"] = _append_context_note(
                current_decisions.get("context"),
                f"Adam DPO critique: {message}",
            )
            assistant_message = "I saved that as DPO review rationale and marked the rejected-side issue signals I could infer."
            next_question = "Should the chosen response stay as-is, or do you want to rewrite the chosen side before approval?"
    else:
        if replacement:
            field_updates["content"] = replacement
            field_updates["context"] = _append_context_note(
                current_decisions.get("context"),
                f"Adam replacement note: {message}",
            )
            field_updates["operator_candidate_triage_intent"] = "keep_with_adam_rewrite"
            assistant_message = "I replaced the draft response with your revised version."
            next_question = "Does this version now sound ready, or is there one more voice adjustment?"
        else:
            modes = _critique_failure_modes(message)
            if modes:
                field_updates["failure_modes"] = modes
            field_updates["context"] = _append_context_note(
                current_decisions.get("context"),
                f"Adam SFT critique: {message}",
            )
            field_updates["operator_candidate_triage_intent"] = "needs_rewrite"
            assistant_message = "I saved that critique as rewrite guidance for this SFT candidate."
            next_question = "What exact wording should replace the draft response, or should I ask the live model to propose a rewrite?"

    field_updates = _filter_field_updates(task, field_updates)
    field_updates = _normalize_prompt_pair_field_updates(
        task=task,
        current_decisions=current_decisions,
        field_updates=field_updates,
    )
    if field_updates:
        actions.append(
            {
                "type": "update_task_draft",
                "label": "Capture prompt-response review edits",
                "requires_confirmation": False,
            }
        )
    elif draft_patch:
        actions.append(
            {
                "type": "update_task_draft",
                "label": "Apply structured draft patch",
                "requires_confirmation": False,
            }
        )
    actions.append({"type": "ask_question", "label": next_question, "requires_confirmation": False})
    return {
        "status": status,
        "assistant_message": assistant_message,
        "next_question": next_question,
        "field_updates": field_updates,
        "draft_patch": draft_patch,
        "notes_append": "",
        "ready_to_submit": False,
        "actions": actions,
        "error": error,
    }


def _prompt_pair_original_response(task: Task) -> str:
    payload = task.input_payload or {}
    return (
        _string(payload.get("content"))
        or _string(payload.get("adam_gold_edit"))
        or _string(payload.get("chosen"))
        or _string(payload.get("model_draft"))
    )


def _original_prompt_pair_candidate(decisions: Dict[str, Any]) -> str:
    return (
        _string(decisions.get("content"))
        or _string(decisions.get("chosen"))
        or _string(decisions.get("adam_gold_edit"))
        or _string(decisions.get("model_draft"))
    )


def _export_flags_with_preference_pair(decisions: Dict[str, Any]) -> Dict[str, bool]:
    current = decisions.get("export_flags")
    flags = dict(current) if isinstance(current, dict) else {}
    return {
        "sft": bool(flags.get("sft", True)),
        "dpo": True,
        "eval": bool(flags.get("eval", False)),
        "anti_pattern": bool(flags.get("anti_pattern", False)),
        "style_rule": bool(flags.get("style_rule", False)),
    }


def _normalize_prompt_pair_field_updates(
    *,
    task: Task,
    current_decisions: Dict[str, Any],
    field_updates: Dict[str, Any],
) -> Dict[str, Any]:
    if _task_kind(task) != "prompt_response_review" or not field_updates:
        return field_updates
    normalized = dict(field_updates)
    artifact_mode = _artifact_mode(task, current_decisions)
    if artifact_mode == "dpo":
        content = _string(normalized.pop("content", ""))
        if content and not _string(normalized.get("chosen")):
            normalized["chosen"] = content
        return normalized

    chosen = _string(normalized.pop("chosen", ""))
    if chosen and not _string(normalized.get("content")):
        normalized["content"] = chosen

    accepted = _string(normalized.get("content"))
    if not accepted:
        return normalized

    original = _prompt_pair_original_response(task) or _original_prompt_pair_candidate(current_decisions)
    if not original or original.strip() == accepted.strip():
        return normalized

    existing_rejected = _string(current_decisions.get("rejected")) or _string(normalized.get("rejected"))
    if not existing_rejected or existing_rejected.strip() == accepted.strip():
        normalized["rejected"] = original

    existing_modes = current_decisions.get("failure_modes") if isinstance(current_decisions.get("failure_modes"), list) else []
    update_modes = normalized.get("failure_modes") if isinstance(normalized.get("failure_modes"), list) else []
    normalized["failure_modes"] = list(
        dict.fromkeys(
            [
                *[str(mode) for mode in existing_modes if str(mode).strip()],
                *[str(mode) for mode in update_modes if str(mode).strip()],
                "original_candidate_replaced_by_adam_gold_edit",
            ]
        )
    )
    normalized["context"] = _append_context_note(
        normalized.get("context") or current_decisions.get("context"),
        "Preference preservation: Adam's revised SFT answer is the accepted response; the previous draft is retained as the rejected side.",
    )
    normalized["export_flags"] = _export_flags_with_preference_pair({**current_decisions, **normalized})
    return normalized


def _normalize_prompt_pair_decision_state(task: Task, decisions: Dict[str, Any]) -> Dict[str, Any]:
    if _task_kind(task) != "prompt_response_review" or not decisions:
        return decisions
    normalized = dict(decisions)
    artifact_mode = _artifact_mode(task, normalized)
    if artifact_mode == "dpo":
        content = _string(normalized.pop("content", ""))
        if content and not _string(normalized.get("chosen")):
            normalized["chosen"] = content
        return normalized

    accepted = (
        _string(normalized.get("content"))
        or _string(normalized.get("adam_gold_edit"))
        or _string(normalized.get("chosen"))
    )
    if accepted and not _string(normalized.get("content")):
        normalized["content"] = accepted
    normalized.pop("chosen", None)

    original = _prompt_pair_original_response(task)
    if not accepted or not original or accepted.strip() == original.strip():
        return normalized

    rejected = _string(normalized.get("rejected"))
    if not rejected or rejected.strip() == accepted.strip():
        normalized["rejected"] = original

    existing_modes = normalized.get("failure_modes") if isinstance(normalized.get("failure_modes"), list) else []
    normalized["failure_modes"] = list(
        dict.fromkeys(
            [
                *[str(mode) for mode in existing_modes if str(mode).strip()],
                "original_candidate_replaced_by_adam_gold_edit",
            ]
        )
    )
    normalized["context"] = _append_context_note(
        normalized.get("context"),
        "Preference preservation: Adam's revised SFT answer is the accepted response; the previous draft is retained as the rejected side.",
    )
    normalized["export_flags"] = _export_flags_with_preference_pair(normalized)
    return normalized


def _source_genre_from_message(message: str) -> str:
    explicit = _labeled_value(message, ["source genre", "genre", "source type", "document type"])
    if explicit:
        return explicit.lower().replace(" ", "_")
    text = message.lower()
    for needle, genre in [
        ("prompt pair yaml", "prompt_pair_yaml"),
        ("sft yaml", "prompt_pair_yaml"),
        ("yaml", "prompt_pair_yaml"),
        ("email", "email"),
        ("letter", "letter"),
        ("journal", "journal"),
        ("diary", "journal"),
        ("novel", "novel_draft"),
        ("memoir", "memoir_fragment"),
        ("essay", "essay"),
        ("notes", "notes"),
    ]:
        if needle in text:
            return genre
    return ""


def _source_authorship_from_message(message: str) -> tuple[str, str]:
    explicit = _labeled_value(message, ["authorship", "author", "writer", "written by"])
    text = (explicit or message).lower()
    if "charles wrote" in text or "written by charles" in text or "by charles" in text or explicit.lower() == "charles":
        return "charles", explicit or "Adam identified Charles as the source author."
    if "adam wrote" in text or "written by adam" in text or "by adam" in text or explicit.lower() == "adam":
        return "adam", explicit or "Adam identified himself as the source author."
    if "cathryn" in text or "third party" in text or "not charles" in text:
        return "third_party", explicit or "Adam identified this as third-party or not Charles-authored source material."
    return "", ""


def _source_truth_status_from_message(message: str) -> str:
    explicit = _labeled_value(message, ["truth status", "truth", "fictionality"])
    text = (explicit or message).lower()
    if "fiction" in text or "novel" in text:
        return "archival_source"
    if "reconstruction" in text or "adam expert" in text:
        return "adam_expert_reconstruction"
    if "archival" in text or "source fact" in text or "real document" in text:
        return "archival_source"
    if "mixed" in text:
        return "mixed"
    return ""


def _yes_no_from_message(message: str, positive_needles: List[str], negative_needles: Optional[List[str]] = None) -> str:
    text = message.lower()
    if negative_needles and any(needle in text for needle in negative_needles):
        return "no"
    if any(needle in text for needle in positive_needles):
        return "yes"
    return ""


def _source_review_plan(
    *,
    task: Task,
    current_decisions: Dict[str, Any],
    request: ChatTurnRequest,
    status: str,
    error: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    if _task_kind(task) != "source_review":
        return None
    message = request.message.strip()
    if not message or _chat_submit_requested(message):
        return None

    field_updates: Dict[str, Any] = {}
    source_genre = _source_genre_from_message(message)
    if source_genre:
        field_updates["source_genre"] = source_genre

    authorship, authorship_note = _source_authorship_from_message(message)
    if authorship:
        field_updates["authorship"] = authorship
    if authorship_note:
        field_updates["authorship_note"] = authorship_note

    truth_status = _source_truth_status_from_message(message)
    if truth_status:
        field_updates["truth_status"] = truth_status
        if truth_status == "mixed":
            field_updates["fictionality_status"] = "mixed"
        elif truth_status == "archival_source" and any(needle in message.lower() for needle in ("fiction", "novel")):
            field_updates["fictionality_status"] = "fiction"

    text = message.lower()
    if "charles voice" in text or "good voice source" in text or "voice sample" in text:
        field_updates["voice_presence"] = "charles_voice"
        field_updates["usable_for_voice_context"] = "yes"
    elif "context only" in text or "not charles voice" in text or "not a voice source" in text:
        field_updates["voice_presence"] = "context_only"

    ready = _yes_no_from_message(
        message,
        ["ready for processing", "ready to process", "process this", "use this source", "usable source"],
        ["not ready", "hold this", "exclude this", "do not process", "don't process"],
    )
    if ready:
        field_updates["ready_for_processing"] = ready

    privacy_level = _extract_privacy_level(message)
    if privacy_level:
        field_updates["privacy_level"] = privacy_level

    grounded = _yes_no_from_message(
        message,
        ["grounded generation", "grounded prompt", "prompt seed", "make prompt", "generate prompt", "generate pairs"],
        ["not for grounded", "do not generate", "don't generate"],
    )
    if grounded:
        field_updates["usable_for_grounded_generation"] = grounded

    if _yes_no_from_message(message, ["voice context", "good voice source", "voice sample"], ["not for voice context", "not a voice source"]):
        field_updates["usable_for_voice_context"] = _yes_no_from_message(
            message,
            ["voice context", "good voice source", "voice sample"],
            ["not for voice context", "not a voice source"],
        )

    generate_pairs = _yes_no_from_message(
        message,
        ["generate pairs", "make prompt pairs", "create prompt pairs", "prompt pair factory"],
        ["do not generate pairs", "don't generate pairs", "no prompt pairs"],
    )
    if generate_pairs:
        field_updates["generate_pairs_on_submit"] = generate_pairs
        field_updates["prompt_pair_potential"] = "high" if generate_pairs == "yes" else "none"
        field_updates["ready_for_prompt_pair_factory"] = generate_pairs

    if "needs split" in text or "split this" in text:
        field_updates["source_section_review_hint"] = "needs_split"
    elif "needs context" in text or "needs more context" in text:
        field_updates["source_section_review_hint"] = "needs_context"

    summary = _labeled_value(message, ["summary", "important", "what is important"])
    if summary:
        field_updates["summary"] = summary

    context = _labeled_value(message, ["context", "why it matters", "note", "meaning"])
    if not context:
        context = message
    field_updates["adam_context_note"] = _append_context_note(
        current_decisions.get("adam_context_note"),
        f"Adam source review: {context}",
    )

    open_questions = _extract_open_questions(message)
    if open_questions:
        existing_questions = current_decisions.get("open_questions") if isinstance(current_decisions.get("open_questions"), list) else []
        field_updates["open_questions"] = _unique_strings([*existing_questions, *open_questions])

    date_or_range = _extract_photo_date(message)
    if date_or_range:
        field_updates["date_or_range"] = date_or_range
        if "date_confidence" not in current_decisions:
            field_updates["date_confidence"] = "adam_estimate"

    place = _extract_photo_place(message)
    if place:
        existing_places = current_decisions.get("places") if isinstance(current_decisions.get("places"), list) else []
        field_updates["places"] = _unique_strings([*existing_places, place])

    field_updates = _filter_field_updates(task, field_updates)
    if not field_updates:
        return None

    next_question = "Should this source generate prompt-pair candidates now, or should it stay as context only?"
    if field_updates.get("generate_pairs_on_submit") == "yes":
        next_question = "Before submit, is there any boundary, privacy, or section split issue that should block pair generation?"
    elif field_updates.get("privacy_level"):
        next_question = "Is this source mainly voice evidence, factual context, or both?"

    return {
        "status": status,
        "assistant_message": "I captured that as source-review structure: source type, usefulness, boundary, and downstream-use fields where I could.",
        "next_question": next_question,
        "field_updates": field_updates,
        "notes_append": "",
        "ready_to_submit": False,
        "actions": [
            {
                "type": "update_task_draft",
                "label": "Capture structured source review",
                "requires_confirmation": False,
            },
            {"type": "ask_question", "label": next_question, "requires_confirmation": False},
        ],
        "error": error,
    }


def _task_summary(task: Task) -> Dict[str, Any]:
    payload = task.input_payload or {}
    title = (
        _string(payload.get("asset_title"))
        or _string(payload.get("source_title"))
        or _string(payload.get("source_filename"))
        or _string(payload.get("prompt"))
        or task.human_id
    )
    return {
        "id": task.id,
        "human_id": task.human_id,
        "task_type": task.task_type,
        "queue": task.queue,
        "status": task.status,
        "priority": task.priority,
        "title": title,
        "instructions": _task_instructions(task),
        "prompt": _truncate_text(payload.get("prompt") or "", 300),
        "artifact_mode": payload.get("artifact_mode"),
        "voice_mode": payload.get("voice_mode"),
        "target_type": task.target_type,
        "target_id": task.target_id,
    }


def _task_instructions(task: Task) -> List[str]:
    payload = task.input_payload or {}
    instructions: List[str] = []
    for value in (
        task.reason_created,
        payload.get("instructions"),
        payload.get("task_instructions"),
        payload.get("review_instructions"),
        payload.get("completion_criteria"),
    ):
        if isinstance(value, str) and value.strip():
            instructions.append(_truncate_text(value.strip(), 500))
        elif isinstance(value, list):
            instructions.extend(_truncate_text(item, 500) for item in value if isinstance(item, str) and item.strip())
    return list(dict.fromkeys(instructions))[:10]


def _task_kind(task: Task) -> str:
    if task.task_type in {"photo_context", "vision_draft_review"}:
        return "photo_review"
    if task.task_type in {"gold_voice_edit", "grounded_prompt_pair_candidate"}:
        return "prompt_response_review"
    if task.task_type in {"text_segment_review", "text_segment_boundary_review", "email_voice_sample"}:
        return "source_review"
    return "general_review"


def _task_image_asset_id(task: Task) -> str:
    payload = task.input_payload or {}
    if _task_kind(task) == "prompt_response_review":
        return _string(payload.get("source_photo_id")) or _string(payload.get("grounding_asset_id"))
    return _string(payload.get("asset_id")) or (task.target_id if task.target_type == "asset" else "")


def _latest_image_derivative(session: Session, asset_id: str, variant: str) -> Optional[Derivative]:
    derivatives = session.exec(
        select(Derivative)
        .where(Derivative.asset_id == asset_id)
        .where(Derivative.derivative_type == "image_preview")
        .where(Derivative.status == "ready")
    ).all()
    matches = [item for item in derivatives if item.metadata_json.get("variant") == variant]
    return sorted(matches, key=lambda item: item.created_at, reverse=True)[0] if matches else None


def _object_file_local_path(object_file: ObjectFile, app_settings: Settings) -> Optional[Path]:
    storage_root = Path(app_settings.storage_root).resolve()
    if object_file.storage_provider == "local":
        path = (storage_root / object_file.object_key).resolve()
    elif object_file.storage_provider == "gcs":
        cache_key = object_file.metadata_json.get("local_preview_cache_key")
        if not isinstance(cache_key, str) or not cache_key.strip():
            cache_key = "/".join(["preview_cache/gcs", object_file.object_key])
        path = (storage_root / cache_key).resolve()
    else:
        return None
    if not path.is_relative_to(storage_root) or not path.is_file():
        return None
    return path


def _image_dimensions_from_metadata(metadata: Any) -> Dict[str, Optional[int]]:
    if not isinstance(metadata, dict):
        return {"width": None, "height": None}
    width = metadata.get("width") or metadata.get("image_width")
    height = metadata.get("height") or metadata.get("image_height")
    return {
        "width": width if isinstance(width, int) and width > 0 else None,
        "height": height if isinstance(height, int) and height > 0 else None,
    }


def _png_dimensions(data: bytes) -> Dict[str, Optional[int]]:
    if len(data) < 24 or not data.startswith(b"\x89PNG\r\n\x1a\n"):
        return {"width": None, "height": None}
    return {"width": int.from_bytes(data[16:20], "big"), "height": int.from_bytes(data[20:24], "big")}


def _jpeg_dimensions(data: bytes) -> Dict[str, Optional[int]]:
    if len(data) < 4 or not data.startswith(b"\xff\xd8"):
        return {"width": None, "height": None}
    index = 2
    while index + 9 < len(data):
        if data[index] != 0xFF:
            index += 1
            continue
        marker = data[index + 1]
        index += 2
        while marker == 0xFF and index < len(data):
            marker = data[index]
            index += 1
        if marker in {0xD8, 0xD9}:
            continue
        if index + 2 > len(data):
            break
        segment_length = int.from_bytes(data[index : index + 2], "big")
        if segment_length < 2 or index + segment_length > len(data):
            break
        if marker in {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF} and segment_length >= 7:
            height = int.from_bytes(data[index + 3 : index + 5], "big")
            width = int.from_bytes(data[index + 5 : index + 7], "big")
            return {"width": width, "height": height}
        index += segment_length
    return {"width": None, "height": None}


def _image_dimensions(path: Path, content_type: str, metadata: Any = None) -> Dict[str, Optional[int]]:
    dimensions = _image_dimensions_from_metadata(metadata)
    if dimensions["width"] and dimensions["height"]:
        return dimensions
    try:
        data = path.read_bytes()[:64 * 1024]
    except OSError:
        return dimensions
    lower_content_type = content_type.lower()
    if lower_content_type == "image/png" or data.startswith(b"\x89PNG\r\n\x1a\n"):
        return _png_dimensions(data)
    if lower_content_type in {"image/jpeg", "image/jpg"} or data.startswith(b"\xff\xd8"):
        return _jpeg_dimensions(data)
    return dimensions


def _image_object_file_for_task(session: Session, task: Task) -> Optional[ObjectFile]:
    asset_id = _task_image_asset_id(task)
    if not asset_id:
        return None

    object_file: Optional[ObjectFile] = None
    for variant in ("display", "thumbnail"):
        derivative = _latest_image_derivative(session, asset_id, variant)
        if derivative and derivative.object_file_id:
            object_file = session.get(ObjectFile, derivative.object_file_id)
            if object_file:
                break

    if object_file is None:
        snapshot = session.exec(
            select(AssetSnapshot)
            .where(AssetSnapshot.asset_id == asset_id)
            .where(AssetSnapshot.snapshot_type == "source_mirror")
            .order_by(AssetSnapshot.version.desc())
        ).first()
        if snapshot and snapshot.object_file_id:
            object_file = session.get(ObjectFile, snapshot.object_file_id)

    if object_file is None:
        return None
    return object_file


def _image_context_for_task(session: Session, task: Task, app_settings: Settings) -> Dict[str, Any]:
    asset_id = _task_image_asset_id(task)
    context: Dict[str, Any] = {
        "asset_id": asset_id or None,
        "image_url": f"/api/assets/{asset_id}/preview?variant=display" if asset_id else None,
        "image_pixels_available": False,
        "image_pixels_included": False,
        "reason": "no_image_asset" if not asset_id else "not_checked",
    }
    if not asset_id:
        return context
    object_file = _image_object_file_for_task(session, task)
    if object_file is None:
        return {**context, "reason": "no_mirrored_image_file"}
    content_type = object_file.content_type or ""
    if not content_type.startswith("image/"):
        return {**context, "content_type": content_type, "reason": "not_an_image"}
    path = _object_file_local_path(object_file, app_settings)
    if path is None:
        return {**context, "content_type": content_type, "object_file_id": object_file.id, "reason": "local_preview_unavailable"}
    byte_size = path.stat().st_size
    if byte_size > MAX_CHAT_IMAGE_BYTES:
        return {
            **context,
            "content_type": content_type,
            "object_file_id": object_file.id,
            "byte_size": byte_size,
            "reason": "image_too_large",
        }
    dimensions = _image_dimensions(path, content_type, object_file.metadata_json)
    return {
        **context,
        "image_pixels_available": True,
        "content_type": content_type,
        "object_file_id": object_file.id,
        "byte_size": byte_size,
        "width": dimensions["width"],
        "height": dimensions["height"],
        "reason": "ready",
    }


def _image_data_url_for_task(session: Session, task: Task, app_settings: Settings) -> Optional[str]:
    object_file = _image_object_file_for_task(session, task)
    if object_file is None:
        return None
    content_type = object_file.content_type or ""
    if not content_type.startswith("image/"):
        return None
    path = _object_file_local_path(object_file, app_settings)
    if path is None or path.stat().st_size > MAX_CHAT_IMAGE_BYTES:
        return None
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{content_type};base64,{encoded}"


def _artifact_mode(task: Task, decisions: Dict[str, Any]) -> str:
    return _string(decisions.get("artifact_mode")) or _string((task.input_payload or {}).get("artifact_mode"), "sft")


def _prompt_pair_field_contract(task: Task, decisions: Dict[str, Any]) -> Dict[str, Any]:
    artifact_mode = _artifact_mode(task, decisions)
    if artifact_mode == "dpo":
        return {
            "contract_type": "prompt_pair_dpo",
            "prompt_field": "prompt",
            "accepted_response_field": "chosen",
            "rejected_response_field": "rejected",
            "review_note_field": "context",
            "field_rules": [
                "chosen is the accepted/preferred Charles-style answer",
                "rejected is the weaker answer that teaches what to avoid",
                "content is not a DPO field; if supplied, the backend maps it to chosen",
                "submit requires explicit Adam confirmation",
            ],
        }
    return {
        "contract_type": "prompt_pair_sft_with_optional_preference_evidence",
        "prompt_field": "prompt",
        "accepted_response_field": "content",
        "rejected_response_field": "rejected",
        "derived_response_field": "chosen",
        "review_note_field": "context",
        "field_rules": [
            "content is the accepted SFT gold answer",
            "chosen is derived from content for export compatibility and should not be written directly in SFT mode",
            "when Adam replaces the draft response, preserve the previous draft as rejected preference evidence",
            "if accepted content and rejected original are both present and distinct, the submit path may create both SFT and DPO artifacts",
            "submit requires explicit Adam confirmation",
        ],
    }


def _prompt_pair_object_contract(task: Task, decisions: Dict[str, Any]) -> Dict[str, Any]:
    artifact_mode = _artifact_mode(task, decisions)
    if artifact_mode == "dpo":
        return {
            "object_type": "prompt_response_candidate",
            "schema_version": "prompt_pair_contract_v1",
            "artifact_mode": "dpo",
            "canonical_fields": {
                "prompt": "source prompt Adam is reviewing",
                "chosen": "accepted/preferred Charles-style answer",
                "rejected": "weaker/non-preferred answer",
                "context": "Adam preference rationale and review notes",
                "failure_modes": "why the rejected side is worse or unsafe",
            },
            "field_aliases": {
                "accepted_response": "chosen",
                "preferred_response": "chosen",
                "rejected_response": "rejected",
                "non_preferred_response": "rejected",
            },
            "submit_mapping": {
                "dpo.prompt": "prompt",
                "dpo.chosen": "chosen",
                "dpo.rejected": "rejected",
                "dpo.reason": "failure_modes",
            },
            "rules": [
                "Do not write content for DPO; if a model supplies content, the backend maps it to chosen.",
                "Never ask Adam to answer the prompt as Charles; ask Adam to judge or edit the pair.",
                "Submit only after explicit Adam confirmation.",
            ],
        }
    return {
        "object_type": "prompt_response_candidate",
        "schema_version": "prompt_pair_contract_v1",
        "artifact_mode": "sft",
        "canonical_fields": {
            "prompt": "source prompt Adam is reviewing",
            "content": "accepted SFT gold answer supplied or approved by Adam",
            "rejected": "original weaker draft preserved as preference evidence when Adam rewrites content",
            "context": "Adam review notes and rationale",
            "failure_modes": "why the original draft was weaker when a rewrite happens",
        },
        "field_aliases": {
            "accepted_response": "content",
            "gold_response": "content",
            "preferred_response": "content",
            "original_draft": "rejected",
            "rejected_response": "rejected",
        },
        "submit_mapping": {
            "sft.messages.assistant": "content",
            "dpo.chosen": "content",
            "dpo.rejected": "rejected",
            "dpo.reason": "failure_modes",
        },
        "rules": [
            "For SFT, write Adam's accepted replacement to content, never chosen.",
            "If content replaces the original draft, preserve the original draft in rejected.",
            "Chosen is derived from content only for export compatibility and should not be stored as a draft field.",
            "Submit only after explicit Adam confirmation.",
        ],
    }


def _object_contracts_for_task(task: Task, decisions: Dict[str, Any]) -> List[Dict[str, Any]]:
    kind = _task_kind(task)
    contracts: List[Dict[str, Any]] = [
        {
            "object_type": "task",
            "schema_version": "task_contract_v1",
            "task_kind": kind,
            "task_type": task.task_type,
            "target_type": task.target_type,
            "target_id": task.target_id,
            "rules": [
                "A chat turn works on the active task unless Adam explicitly asks to route elsewhere.",
                "Draft updates are reversible until Adam confirms submit.",
            ],
        }
    ]
    if kind == "prompt_response_review":
        contracts.append(_prompt_pair_object_contract(task, decisions))
    elif kind == "photo_review":
        contracts.append(
            {
                "object_type": "photo_context",
                "schema_version": "photo_context_contract_v1",
                "canonical_fields": {
                    "visual_description_correction": "visible facts Adam confirms or corrects",
                    "visible_people": "people visible in the pixels",
                    "adam_context_note": "Adam memory or meaning not inferable from pixels alone",
                    "open_questions": "uncertainties to preserve",
                    "privacy_level": "downstream boundary",
                },
                "rules": [
                    "Keep visible facts separate from Adam memory.",
                    "Do not turn machine guesses into confirmed identity without Adam confirmation.",
                ],
            }
        )
    elif kind == "source_review":
        contracts.append(
            {
                "object_type": "source_excerpt",
                "schema_version": "source_review_contract_v1",
                "canonical_fields": {
                    "source_genre": "document type",
                    "authorship": "who wrote the source",
                    "voice_presence": "whether Charles voice is present",
                    "privacy_level": "downstream boundary",
                    "generate_pairs_on_submit": "whether prompt pairs should be produced",
                },
                "rules": [
                    "Do not assume authorship.",
                    "Keep source classification separate from generated training examples.",
                ],
            }
        )
    return contracts


def _task_work_surface(task: Task, decisions: Dict[str, Any]) -> Dict[str, Any]:
    payload = task.input_payload or {}
    kind = _task_kind(task)
    if kind == "photo_review":
        return {
            "kind": kind,
            "adam_role": "Adam is identifying visible facts, people, place, event, memory associations, uncertainty, and boundaries.",
            "ask_style": (
                "Ask Adam one concrete question about the displayed photo. Prefer questions like who/where/when/why-it-matters, "
                "but keep visible facts separate from Adam memory and uncertainty."
            ),
            "visible_or_machine_context": {
                "asset_title": payload.get("asset_title") or payload.get("title") or payload.get("source_filename"),
                "machine_guess_people": payload.get("machine_guess_people"),
                "machine_guess_objects": payload.get("machine_guess_objects") or payload.get("objects"),
                "machine_tags": payload.get("machine_tags") or payload.get("tags"),
                "visual_summary": payload.get("visual_summary") or payload.get("description"),
                "suggested_questions": payload.get("suggested_questions"),
                "retrieval_gap_origin": payload.get("retrieval_gap_origin"),
            },
        }
    if kind == "prompt_response_review":
        artifact_mode = _artifact_mode(task, decisions)
        return {
            "kind": kind,
            "artifact_mode": artifact_mode,
            "adam_role": "Adam is reviewing a training-data candidate, not answering the candidate prompt.",
            "critical_rule": (
                "The task payload's prompt is source material shown to Adam for review. Never ask Adam to answer that prompt. "
                "Ask Adam to judge or edit the prompt and response pair."
            ),
            "field_contract": _prompt_pair_field_contract(task, decisions),
            "object_contract": _prompt_pair_object_contract(task, decisions),
            "ask_style": (
                "If DPO, show the prompt plus chosen/rejected responses and ask what is stronger, weaker, generic, wrong, or missing. "
                "If SFT, show the prompt plus draft response and ask how the response should be edited before it becomes gold."
            ),
            "review_material": {
                "candidate_prompt": payload.get("prompt"),
                "draft_response": payload.get("content") or payload.get("adam_gold_edit"),
                "chosen_response": payload.get("chosen"),
                "rejected_response": payload.get("rejected") or payload.get("model_draft"),
                "context": payload.get("context"),
                "source_excerpt": payload.get("source_excerpt"),
                "source_photo_title": payload.get("source_photo_title"),
                "failure_modes": payload.get("failure_modes"),
                "response_rubric": payload.get("response_rubric"),
            },
        }
    if kind == "source_review":
        return {
            "kind": kind,
            "adam_role": "Adam is reviewing source text boundaries, voice usefulness, privacy, and whether prompt pairs should be generated.",
            "ask_style": "Ask one question about source boundaries, voice presence, context, privacy, or downstream use.",
            "source_material": {
                "source_title": payload.get("source_title") or payload.get("source_filename"),
                "preview_text": payload.get("preview_text") or payload.get("source_excerpt") or payload.get("content"),
                "chunking_strategy": payload.get("chunking_strategy"),
            },
        }
    return {
        "kind": kind,
        "adam_role": "Adam is reviewing the active ticket.",
        "ask_style": "Ask one concise question about the next decision needed to move this ticket forward.",
    }


def _fallback_next_question(task: Task, decisions: Dict[str, Any], missing_fields: Optional[List[str]] = None) -> str:
    missing = missing_fields or _required_missing_fields(task, decisions)
    kind = _task_kind(task)
    if kind == "photo_review":
        if "visual_description_correction" in missing:
            return "I’m showing you this photo. What is visibly present, and who can you identify with confidence?"
        if "adam_context_note" in missing:
            return "What do you know about this photo beyond the pixels, such as where it was taken or why it matters?"
        if "privacy_level" in missing:
            return "What boundary should this photo have before it is searchable, retrievable, or used downstream?"
        return "What uncertainty should stay attached to this photo instead of being turned into a claim?"
    if kind == "prompt_response_review":
        artifact_mode = _artifact_mode(task, decisions)
        if artifact_mode == "dpo":
            return "I’m showing you the prompt plus chosen and rejected responses. What feels stronger, weaker, generic, wrong, or missing?"
        return "I’m showing you the prompt and draft response. How does the response sound, and what should we rewrite before it becomes gold?"
    if kind == "source_review":
        return "I’m showing you this source excerpt. What should we decide about its boundary, context, or usefulness for prompt-pair generation?"
    return "What is the next useful decision for this ticket?"


def _normalized_question_text(value: str) -> str:
    return " ".join(value.strip().strip('"').strip("'").lower().split())


def _looks_like_source_prompt_reuse(task: Task, text: Any) -> bool:
    if _task_kind(task) != "prompt_response_review":
        return False
    source_prompt = _string((task.input_payload or {}).get("prompt"))
    candidate = _string(text)
    if not source_prompt or not candidate:
        return False
    source_norm = _normalized_question_text(source_prompt)
    candidate_norm = _normalized_question_text(candidate)
    if not source_norm or not candidate_norm:
        return False
    if candidate_norm == source_norm:
        return True
    return source_norm in candidate_norm and len(candidate_norm) <= len(source_norm) + 90


def _looks_like_unconfirmed_action_claim(text: Any) -> bool:
    candidate = _string(text).lower()
    if not candidate:
        return False
    return bool(
        re.search(
            r"\b(submitted|approved|deleted|built|created|executed)\b|moved (?:that|this|the) ticket forward",
            candidate,
        )
    )


def _looks_like_draft_edit_claim(text: Any) -> bool:
    candidate = _string(text).lower()
    if not candidate:
        return False
    return bool(
        re.search(
            r"\bi(?:'ll|’ll| will| am going to|m going to)\s+(?:move|copy|clear|swap|replace|update|apply|set)\b"
            r"|\bi(?: have| just)?\s*(?:moved|copied|cleared|swapped|replaced|updated|applied|set)\b",
            candidate,
        )
    )


def _is_strict_live_blocked_plan(plan: Dict[str, Any]) -> bool:
    return _string(plan.get("status")) in {"live_model_required_not_ready", "live_error_blocked"}


def _sanitize_adam_facing_plan(task: Task, decisions: Dict[str, Any], missing_fields: List[str], plan: Dict[str, Any]) -> Dict[str, Any]:
    sanitized = dict(plan)
    if _is_strict_live_blocked_plan(sanitized):
        return sanitized
    replacement = _fallback_next_question(task, decisions, missing_fields)
    source_prompt_reused = False
    for key in ("next_question", "assistant_message"):
        if _looks_like_source_prompt_reuse(task, sanitized.get(key)):
            sanitized[key] = replacement
            source_prompt_reused = True
    if isinstance(sanitized.get("actions"), list):
        cleaned_actions: List[Dict[str, Any]] = []
        for action in sanitized["actions"]:
            if not isinstance(action, dict):
                continue
            cleaned_action = dict(action)
            if _looks_like_source_prompt_reuse(task, cleaned_action.get("label")):
                cleaned_action["label"] = replacement
                source_prompt_reused = True
            cleaned_actions.append(cleaned_action)
        sanitized["actions"] = cleaned_actions
    if _task_kind(task) == "prompt_response_review":
        question = _string(sanitized.get("next_question"))
        if not question:
            sanitized["next_question"] = replacement
        message = _string(sanitized.get("assistant_message"))
        if not message:
            sanitized["assistant_message"] = sanitized["next_question"]
        if source_prompt_reused:
            sanitized["status"] = "sanitized_source_prompt_question"
            sanitized["source_prompt_question_sanitized"] = True
    if _looks_like_unconfirmed_action_claim(sanitized.get("assistant_message")):
        sanitized["assistant_message"] = (
            "I think this ticket is ready. Confirm when you want me to submit it."
            if bool(sanitized.get("ready_to_submit"))
            else sanitized.get("next_question") or replacement
        )
        sanitized["status"] = "sanitized_unconfirmed_action_claim"
        sanitized["unconfirmed_action_claim_sanitized"] = True
    if _task_kind(task) == "photo_review" and not _string(sanitized.get("next_question")) and not sanitized.get("ready_to_submit"):
        sanitized["next_question"] = replacement
        sanitized["assistant_message"] = _string(sanitized.get("assistant_message"), replacement)
    return sanitized


def _top_export_blocker_task(
    *,
    session: Session,
    request: ChatTurnRequest,
    app_settings: Settings,
) -> tuple[Optional[Task], Dict[str, Any]]:
    queue = compile_downstream_bottleneck_queue(
        session=session,
        app_settings=app_settings,
        scope="family_private",
        limit=5,
    )
    selection: Dict[str, Any] = {
        "requested_route": "export_blocker",
        "requested_route_label": _route_label("export_blocker"),
        "selection_reason": "no_matching_route_task",
        "fallback_used": False,
        "matched_count": 0,
        "source_queue_type": queue.get("queue_type"),
        "ordered_area_keys": queue.get("ordered_area_keys") or [],
    }
    items = queue.get("items") if isinstance(queue.get("items"), list) else []
    for item in items:
        if not isinstance(item, dict):
            continue
        action = item.get("action") if isinstance(item.get("action"), dict) else {}
        task_id = _string(action.get("task_id"))
        if not task_id:
            continue
        task = session.get(Task, task_id)
        if task is None or task.status != "ready":
            continue
        selection.update(
            {
                "selection_reason": "top_export_blocker_task",
                "matched_count": 1,
                "selected_task_id": task.id,
                "selected_task_human_id": task.human_id,
                "top_blocker": {
                    "area_key": item.get("area_key"),
                    "area_label": item.get("area_label"),
                    "summary": item.get("summary"),
                    "next_action": item.get("next_action"),
                    "action": action,
                },
            }
        )
        return task, selection
    selected_task = session.get(Task, request.task_id) if request.task_id else None
    if selected_task and selected_task.status == "ready":
        selection.update(
            {
                "selection_reason": "no_top_blocker_task_fallback_selected_ticket",
                "fallback_used": True,
                "selected_task_id": selected_task.id,
                "selected_task_human_id": selected_task.human_id,
            }
        )
        return selected_task, selection
    return None, selection


def _task_or_selected(session: Session, request: ChatTurnRequest) -> tuple[Optional[Task], Dict[str, Any]]:
    selected_task = session.get(Task, request.task_id) if request.task_id else None
    session_metadata = _chat_session_metadata_for_request(session, request)
    skipped_task_ids = _metadata_skipped_task_ids(session_metadata)
    skipped_set = set(skipped_task_ids)
    if _go_back_requested(request.message):
        history = _metadata_task_history(session_metadata)
        for task_id in reversed(history[:-1] if request.task_id and history[-1:] == [request.task_id] else history):
            if task_id == request.task_id:
                continue
            task = session.get(Task, task_id)
            if task and task.status == "ready":
                return task, {
                    "requested_route": "previous_task",
                    "requested_route_label": "previous ticket",
                    "selection_reason": "previous_task_from_chat_history",
                    "selected_task_id": task.id,
                    "selected_task_human_id": task.human_id,
                    "fallback_used": False,
                    "task_history": history,
                }
    requested_route = _requested_task_route(request, selected_task)
    skip_current = bool(request.task_id and _skip_current_requested(request.message))
    avoid_task_id = request.task_id if requested_route and _next_task_requested(request.message) else None
    avoid_task_ids = set(skipped_set)
    if avoid_task_id:
        avoid_task_ids.add(avoid_task_id)
    selection: Dict[str, Any] = {
        "requested_route": requested_route,
        "requested_route_label": _route_label(requested_route),
        "selection_reason": "selected_ticket",
        "avoided_task_id": avoid_task_id,
        "avoided_task_ids": sorted(avoid_task_ids),
        "newly_skipped_task_id": request.task_id if skip_current else None,
        "fallback_used": False,
    }
    if requested_route:
        candidates = session.exec(
            select(Task)
            .where(Task.status == "ready")
            .order_by(Task.priority.desc(), Task.created_at.asc())
        ).all()
        matching = [task for task in candidates if task.id not in avoid_task_ids and _task_matches_route(task, requested_route)]
        if matching:
            task = matching[0]
            selection["selection_reason"] = "routed_from_chat_intent"
            selection["matched_count"] = len(matching)
            selection["selected_task_id"] = task.id
            selection["selected_task_human_id"] = task.human_id
            return task, selection
        selection["selection_reason"] = "no_matching_route_task"
        selection["matched_count"] = 0
        if selected_task and selected_task.status == "ready" and selected_task.id not in avoid_task_ids:
            selection["fallback_used"] = True
            selection["selected_task_id"] = selected_task.id
            selection["selected_task_human_id"] = selected_task.human_id
            return selected_task, selection
        return None, selection
    if selected_task:
        selection["selected_task_id"] = selected_task.id
        selection["selected_task_human_id"] = selected_task.human_id
        return selected_task, selection
    task = session.exec(
        select(Task)
        .where(Task.status == "ready")
        .order_by(Task.priority.desc(), Task.created_at.asc())
    ).first()
    if task:
        selection["selection_reason"] = "highest_priority_ready_task"
        selection["selected_task_id"] = task.id
        selection["selected_task_human_id"] = task.human_id
    else:
        selection["selection_reason"] = "no_ready_task"
    return task, selection


def _task_draft(session: Session, task_id: str, user_id: str = "adam") -> Optional[TaskDraft]:
    return session.exec(
        select(TaskDraft).where(TaskDraft.task_id == task_id).where(TaskDraft.user_id == user_id)
    ).first()


def _safe_payload(task: Task) -> Dict[str, Any]:
    payload = task.input_payload or {}
    allowed_keys = {
        "asset_title",
        "source_title",
        "source_filename",
        "prompt",
        "content",
        "chosen",
        "rejected",
        "artifact_mode",
        "voice_mode",
        "truth_status",
        "system_prompt",
        "source_excerpt",
        "candidate_requires_adam_gold_edit",
        "source_photo_title",
        "photo_pair_variant_label",
        "retrieval_gap_origin",
        "suggested_questions",
        "required_decisions",
        "boundary_snapshot",
        "source_section_review_hint",
        "source_photo_id",
        "asset_id",
        "title",
        "description",
        "visual_summary",
        "machine_guess_people",
        "machine_guess_objects",
        "machine_tags",
        "tags",
        "objects",
        "context",
        "response_rubric",
        "failure_modes",
        "model_draft",
        "adam_gold_edit",
    }
    return {key: payload.get(key) for key in allowed_keys if key in payload}


def _history_for_prompt(history: List[ChatMessage]) -> str:
    rows: List[str] = []
    for item in history[-MAX_HISTORY_MESSAGES:]:
        role = item.role if item.role in {"user", "assistant"} else "user"
        content = _string(item.content)
        if content:
            rows.append(f"{role}: {content}")
    return "\n".join(rows) or "[no prior chat in this session]"


def _chat_prompt(
    *,
    task: Task,
    current_decisions: Dict[str, Any],
    missing_fields: List[str],
    request: ChatTurnRequest,
) -> str:
    allowed = sorted(_allowed_update_keys(task))
    payload = _safe_payload(task)
    work_surface = _task_work_surface(task, current_decisions)
    return "\n\n".join(
        [
            "You are the CharlesOps Chat operator. You help Adam complete one review ticket at a time.",
            "You are not Charles Rotmil and must not imitate Charles in your assistant message.",
            "You are speaking to Adam. Always address Adam as the reviewer/operator.",
            "Use Adam's latest reply intelligently: infer which form fields, rubric choices, notes, or boundary decisions it should update.",
            "Ask exactly one concise follow-up question unless the ticket is ready to apply or submit.",
            "Do not submit, skip, flag, or delete anything yourself. You may only request those actions through the JSON action plan.",
            "Preserve uncertainty. Do not turn machine inference into Adam memory or archival truth.",
            "Only write fields from the allowed field list. Ignore requested fields outside that list.",
            "If this is a prompt/response ticket, the candidate prompt is source material to review. Never ask Adam to answer that prompt.",
            "For prompt/response tickets, ask Adam how the prompt, chosen/content response, rejected response, rubric, or voice should change.",
            "For SFT prompt/response tickets, write Adam's accepted replacement to content, not chosen. Preserve the prior draft response as rejected preference evidence when Adam rewrites it.",
            "For DPO prompt/response tickets, chosen is accepted/preferred and rejected is weaker. If you accidentally produce content for DPO, the backend maps it to chosen.",
            "For editor operations like move, copy, clear, swap, or append, emit draft_patch operations. Do not merely promise the edit in prose.",
            'Supported draft_patch operations: {"op":"copy","from":"chosen","to":"rejected"}, {"op":"clear","field":"chosen"}, {"op":"set","field":"artifact_mode","value":"dpo"}, {"op":"swap","left":"chosen","right":"rejected"}, {"op":"append","field":"context","value":"note"}.',
            "For photo tickets, ask Adam about the displayed photo: visible facts, identity, place, date, story, uncertainty, and boundaries.",
            "If Adam says ready/submit and required fields are complete, set ready_to_submit=true and include a submit_task action requiring confirmation.",
            "If Adam gives usable information, include update_task_draft with the smallest useful field_updates.",
            "You may request read-only context tools before a final plan if you need to inspect schema, source material, draft state, or image context.",
            'A tool request must be JSON only: {"tool_requests":[{"tool_name":"inspect_object_contract","reason":"Need editable field contract"}]}.',
            'For retrieval, include the search query when useful: {"tool_requests":[{"tool_name":"retrieve_source_context","query":"cooking memory","scope":"family_private","limit":5}]}.',
            'For a broader inventory of reviewed evidence, request: {"tool_requests":[{"tool_name":"inspect_evidence_corpus","scope":"family_private","limit":10}]}.',
            'For broad source/photo/voice planning, request ranked clusters before asking Adam: {"tool_requests":[{"tool_name":"plan_ranked_evidence_clusters","query":"cooking memory","scope":"family_private","limit":5,"per_cluster_limit":2}]}.',
            'Before choosing or opening another ticket, inspect the work queues: {"tool_requests":[{"tool_name":"inspect_work_queue_plan","route":"dpo_review","limit":5,"reason":"Need the board/backlog before selecting a ticket"}]}.',
            'For source review tickets, preview candidate generation before suggesting pair creation: {"tool_requests":[{"tool_name":"preview_source_pair_generation","reason":"Need evidence-backed SFT/DPO candidate counts"}]}.',
            "Use reviewed/default corpus records as evidence. Treat excluded or unreviewed corpus records only as review backlog, not truth.",
            "Use ranked evidence clusters to choose one coherent next question or ticket, not to invent facts. Preserve cluster/record refs in evidence_refs when they influence a draft.",
            "If you choose a different existing ticket, include an open_task action with task_id. Do not include draft updates in the same plan as a cross-ticket open_task.",
            "If retrieval-gap/photo cluster work needs a missing review ticket, include a create_or_open_review_task action with review_task_type='photo_context', asset_id, source_photo_id, or group_key plus source_query, candidate_match_quality, and candidate_selection_reason. For source clusters, use review_task_type='source_review' with source_segment_id or source_asset_id plus source_query. This action requires confirmation and must not be combined with draft updates.",
            "After tool receipts are provided, return the final action-plan JSON only. Never claim a draft edit was applied unless field_updates or draft_patch contains the edit.",
            "Return one valid JSON object. No Markdown.",
            f"Task:\n{json.dumps(_task_summary(task), ensure_ascii=False)}",
            f"Work surface:\n{json.dumps(work_surface, ensure_ascii=False)}",
            f"Object contracts:\n{json.dumps(_object_contracts_for_task(task, current_decisions), ensure_ascii=False)}",
            f"Allowed field updates:\n{json.dumps(allowed, ensure_ascii=False)}",
            f"Allowed action contracts:\n{json.dumps(_chat_action_contracts_for_context(), ensure_ascii=False)}",
            f"Available read-only tools:\n{json.dumps(_chat_read_tool_contracts_for_context(), ensure_ascii=False)}",
            "Current merged decisions:\n" + _truncate_text(current_decisions, MAX_CONTEXT_CHARS),
            "Current missing required fields:\n" + json.dumps(missing_fields, ensure_ascii=False),
            "Task payload excerpt:\n" + _truncate_text(payload, MAX_CONTEXT_CHARS),
            "Recent chat:\n" + _history_for_prompt(request.history),
            "Latest Adam message:\n" + (request.message.strip() or "[empty]"),
            (
                "Return exactly this JSON shape: "
                '{"assistant_message":"string","work_surface":{},"active_task_id":"string",'
                '"next_question":"string or empty","needs_user_response":true,'
                '"draft_updates":{},"draft_patch":[],"notes_append":"string or empty","ready_to_submit":false,'
                f'"proposed_actions":[{{"action_type":"one of: {", ".join(sorted(ALLOWED_CHAT_ACTIONS))}",'
                '"label":"string","requires_confirmation":false}],'
                '"confidence":"low|medium|high","uncertainties":[],"evidence_refs":[],"ui_hints":{}}'
            ),
        ]
    )


def _fallback_plan(
    *,
    task: Task,
    current_decisions: Dict[str, Any],
    missing_fields: List[str],
    request: ChatTurnRequest,
    app_settings: Settings,
    status: str,
    error: Optional[str] = None,
    suppress_latest_answer: bool = False,
) -> Dict[str, Any]:
    from app.services.operator_assistant import operator_assistant_suggestion

    photo_plan = _photo_context_review_plan(
        task=task,
        current_decisions=current_decisions,
        request=request,
        status=status,
        error=error,
    )
    if photo_plan and not suppress_latest_answer:
        return photo_plan

    prompt_pair_plan = _prompt_pair_review_plan(
        task=task,
        current_decisions=current_decisions,
        request=request,
        status=status,
        error=error,
    )
    if prompt_pair_plan and not suppress_latest_answer:
        return prompt_pair_plan

    source_plan = _source_review_plan(
        task=task,
        current_decisions=current_decisions,
        request=request,
        status=status,
        error=error,
    )
    if source_plan and not suppress_latest_answer:
        return source_plan

    fallback_settings = app_settings.model_copy(
        update={"openai_api_key": "", "text_generation_live_calls_enabled": False}
    )
    latest_user_answer = "" if suppress_latest_answer else request.message
    requested_submit = _chat_submit_requested(latest_user_answer)
    suggestion = operator_assistant_suggestion(
        task=task,
        decisions=current_decisions,
        latest_user_answer=latest_user_answer,
        app_settings=fallback_settings,
    )
    field_updates = {} if requested_submit else _filter_field_updates(task, suggestion.get("field_updates"))
    ready_to_submit = requested_submit and not _required_missing_fields(task, current_decisions, field_updates)
    question = (
        _fallback_next_question(task, current_decisions, missing_fields)
        if suppress_latest_answer
        else _string(suggestion.get("next_question"), "What should we record for this ticket?")
    )
    actions: List[Dict[str, Any]] = []
    if field_updates:
        actions.append(
            {
                "type": "update_task_draft",
                "label": _string(suggestion.get("field_update_summary"), "Update the active task draft"),
                "requires_confirmation": False,
            }
        )
    if ready_to_submit:
        actions.append({"type": "submit_task", "label": "Submit this ticket", "requires_confirmation": True})
    else:
        actions.append({"type": "ask_question", "label": question, "requires_confirmation": False})
    assistant_message = (
        "I recorded that in the draft. " if field_updates else ""
    ) + (
        "I think this is ready to submit. Confirm when you want me to submit it."
        if ready_to_submit
        else question
    )
    return {
        "status": status,
        "assistant_message": assistant_message,
        "next_question": "" if ready_to_submit else question,
        "field_updates": field_updates,
        "notes_append": "",
        "ready_to_submit": ready_to_submit,
        "actions": actions,
        "error": error,
    }


def _live_required_blocked_plan(*, status: str, app_settings: Settings, error: Optional[str] = None) -> Dict[str, Any]:
    missing_setup = (
        "Live AI is required for Chat, but the live model is not ready. "
        "Set OPENAI_API_KEY and TEXT_GENERATION_LIVE_CALLS_ENABLED=true, then restart the API."
    )
    provider_error = (
        "Live AI is required for Chat, but the live model call failed. "
        "I did not use a deterministic fallback or change the ticket."
    )
    assistant_message = provider_error if error else missing_setup
    return {
        "status": status,
        "assistant_message": assistant_message,
        "next_question": "",
        "field_updates": {},
        "draft_patch": [],
        "notes_append": "",
        "ready_to_submit": False,
        "actions": [],
        "error": error or (
            "live_chat_required_not_ready:"
            f" model={app_settings.text_generation_model};"
            f" live_calls_enabled={bool(app_settings.text_generation_live_calls_enabled)};"
            f" api_key_configured={bool(app_settings.openai_api_key)}"
        ),
        "confidence": "low",
        "uncertainties": ["Chat strict-live mode blocks deterministic fallback output."],
        "evidence_refs": [],
        "ui_hints": {"blocked_by": "live_model_required"},
    }


def _normalize_chat_read_tool_requests(value: Any) -> List[Dict[str, str]]:
    raw_requests = value if isinstance(value, list) else []
    normalized: List[Dict[str, str]] = []
    seen: set[str] = set()
    for item in raw_requests:
        if not isinstance(item, dict):
            continue
        tool_name = _string(item.get("tool_name")) or _string(item.get("name")) or _string(item.get("tool"))
        if tool_name not in ALLOWED_CHAT_READ_TOOLS or tool_name in seen:
            continue
        normalized.append(
            {
                "tool_name": tool_name,
                "reason": _truncate_text(_string(item.get("reason")), 240),
                "query": _truncate_text(_string(item.get("query")), 240),
                "route": _truncate_text(_string(item.get("route")), 80),
                "scope": _string(item.get("scope"), "family_private"),
                "limit": str(_optional_int(item.get("limit")) or ""),
                "per_cluster_limit": str(_optional_int(item.get("per_cluster_limit")) or ""),
            }
        )
        seen.add(tool_name)
        if len(normalized) >= 4:
            break
    return normalized


def _safe_queue_task_item(task: Task) -> Dict[str, Any]:
    payload = task.input_payload if isinstance(task.input_payload, dict) else {}
    title = (
        _string(payload.get("asset_title"))
        or _string(payload.get("source_title"))
        or _string(payload.get("source_filename"))
        or _string(payload.get("prompt"))
        or task.human_id
    )
    return {
        "task_id": task.id,
        "task_human_id": task.human_id,
        "task_type": task.task_type,
        "route": _route_for_task(task),
        "queue": task.queue,
        "priority": task.priority,
        "target_type": task.target_type,
        "target_id": task.target_id,
        "title": _truncate_text(title, 180),
        "artifact_mode": _artifact_mode(task, payload) if _task_kind(task) == "prompt_response_review" else None,
        "voice_mode": payload.get("voice_mode"),
        "prompt_preview": _truncate_text(payload.get("prompt") or "", 240),
        "source_title": payload.get("source_title"),
        "asset_title": payload.get("asset_title"),
        "required_decisions": task.required_decisions or [],
    }


def _safe_board_item(item: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": item.get("id"),
        "kind": item.get("kind"),
        "column": item.get("column"),
        "task_id": item.get("taskId"),
        "task_human_id": item.get("taskHumanId"),
        "artifact_mode": item.get("artifactMode"),
        "title": _truncate_text(item.get("title") or "", 160),
        "subtitle": _truncate_text(item.get("subtitle") or "", 160),
        "source_label": _truncate_text(item.get("sourceLabel") or "", 160),
        "export_status": item.get("exportStatus"),
        "gate_status": item.get("gateStatus"),
        "blockers": item.get("blockers") if isinstance(item.get("blockers"), list) else [],
        "labels": item.get("labels") if isinstance(item.get("labels"), list) else [],
    }


def _work_queue_plan(
    *,
    session: Session,
    request: ChatTurnRequest,
    selected_task: Task,
    task_selection: Dict[str, Any],
    app_settings: Settings,
    route: str,
    limit: int,
) -> Dict[str, Any]:
    safe_limit = max(1, min(limit, 10))
    routes = ["photo_review", "source_review", "sft_review", "dpo_review", "prompt_response_review", "export_readiness"]
    ready_tasks = session.exec(
        select(Task)
        .where(Task.status == "ready")
        .order_by(Task.priority.desc(), Task.created_at.asc())
    ).all()
    counts_by_route = {
        route_name: len([task for task in ready_tasks if _task_matches_route(task, route_name)])
        for route_name in routes
    }
    requested_route = route if route in routes else _requested_task_route(request, selected_task) or _route_for_task(selected_task) or ""
    route_candidates = [
        _safe_queue_task_item(task)
        for task in ready_tasks
        if not requested_route or _task_matches_route(task, requested_route)
    ][:safe_limit]
    top_ready_tasks = [_safe_queue_task_item(task) for task in ready_tasks[:safe_limit]]
    recommended = route_candidates[0] if route_candidates else top_ready_tasks[0] if top_ready_tasks else None

    try:
        from app.routers.training_board import _board_projection

        board = _board_projection(session)
        board_columns = []
        raw_columns = board.get("columns") if isinstance(board.get("columns"), list) else []
        for column in raw_columns:
            if not isinstance(column, dict):
                continue
            items = column.get("items") if isinstance(column.get("items"), list) else []
            board_columns.append(
                {
                    "id": column.get("id"),
                    "label": column.get("label"),
                    "count": column.get("count"),
                    "items": [_safe_board_item(item) for item in items[: min(5, safe_limit)] if isinstance(item, dict)],
                }
            )
        training_board = {
            "board_type": board.get("board_type"),
            "counts": board.get("counts") if isinstance(board.get("counts"), dict) else {},
            "columns": board_columns,
        }
    except Exception as exc:  # pragma: no cover - queue planning should not break chat if board projection fails.
        training_board = {
            "board_type": "training_artifact_board",
            "error": f"{type(exc).__name__}: {_truncate_text(str(exc), 240)}",
            "counts": {},
            "columns": [],
        }

    bottleneck_queue = compile_downstream_bottleneck_queue(
        session=session,
        app_settings=app_settings,
        scope="family_private",
        limit=min(5, safe_limit),
    )
    bottleneck_items = bottleneck_queue.get("items") if isinstance(bottleneck_queue.get("items"), list) else []
    return {
        "plan_type": "work_queue_plan",
        "requested_route": requested_route,
        "requested_route_label": _route_label(requested_route),
        "current_task": _safe_queue_task_item(selected_task),
        "task_selection": task_selection,
        "ready_task_count": len(ready_tasks),
        "ready_task_counts_by_route": counts_by_route,
        "route_candidates": route_candidates,
        "top_ready_tasks": top_ready_tasks,
        "recommended_open_task": recommended,
        "training_board": training_board,
        "downstream_bottleneck": {
            "queue_type": bottleneck_queue.get("queue_type"),
            "item_count": bottleneck_queue.get("item_count"),
            "ordered_area_keys": bottleneck_queue.get("ordered_area_keys") if isinstance(bottleneck_queue.get("ordered_area_keys"), list) else [],
            "top_items": [
                {
                    "area_key": item.get("area_key"),
                    "area_label": item.get("area_label"),
                    "summary": _truncate_text(item.get("summary") or "", 280),
                    "next_action": _truncate_text(item.get("next_action") or "", 220),
                    "action": item.get("action") if isinstance(item.get("action"), dict) else {},
                }
                for item in bottleneck_items[: min(5, safe_limit)]
                if isinstance(item, dict)
            ],
        },
        "safety_boundaries": [
            "Read-only work-queue planning payload; it does not submit, skip, delete, or export anything.",
            "Only existing ready task ids may be opened by a later open_task action.",
            "A cross-ticket open_task action must not be combined with draft field updates.",
        ],
    }


def _execute_chat_read_tool(
    *,
    session: Session,
    task: Task,
    current_decisions: Dict[str, Any],
    draft_decisions: Dict[str, Any],
    missing_fields: List[str],
    request: ChatTurnRequest,
    app_settings: Settings,
    tool_name: str,
    tool_request: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    if tool_name == "inspect_active_task":
        return {
            "active_task": _task_summary(task),
            "task_kind": _task_kind(task),
            "required_decisions": task.required_decisions or [],
            "missing_fields": missing_fields,
            "current_user_intent": _detected_user_intent(request, {}),
        }
    if tool_name == "inspect_object_contract":
        return {
            "work_surface": _task_work_surface(task, current_decisions),
            "object_contracts": _object_contracts_for_task(task, current_decisions),
            "allowed_field_updates": sorted(_allowed_update_keys(task)),
            "action_contracts": _chat_action_contracts_for_context(),
        }
    if tool_name == "inspect_source_material":
        return {
            "source_refs": _chat_source_refs_for_task(task),
            "associated_object_ids": _associated_object_ids_for_task(task),
            "source_material_preview": _source_material_preview(task, current_decisions),
            "safe_payload_excerpt": _safe_payload(task),
        }
    if tool_name == "inspect_image_context":
        image_context = _image_context_for_task(session, task, app_settings)
        return {
            **image_context,
            "image_pixels_included_if_live_call": bool(
                image_context.get("image_pixels_available") and live_text_generation_ready(app_settings)
            ),
        }
    if tool_name == "inspect_current_draft":
        return {
            "current_merged_decisions": current_decisions,
            "draft_decisions": draft_decisions,
            "missing_fields": missing_fields,
        }
    if tool_name == "retrieve_source_context":
        from app.services.retrieval import search_embedding_records

        payload = task.input_payload or {}
        query = (
            _string((tool_request or {}).get("query"))
            or _string(request.message)
            or _string(payload.get("prompt"))
            or _string(payload.get("source_title"))
            or _string(payload.get("asset_title"))
            or _string(task.human_id)
        )
        scope = _string((tool_request or {}).get("scope"), "family_private")
        if scope not in {"public", "family_private", "private"}:
            scope = "family_private"
        limit = _optional_int((tool_request or {}).get("limit")) or 5
        return search_embedding_records(
            session=session,
            query=query,
            scope=scope,
            limit=max(1, min(limit, 10)),
            app_settings=app_settings,
        )
    if tool_name == "inspect_evidence_corpus":
        from app.services.retrieval import unified_evidence_corpus

        scope = _string((tool_request or {}).get("scope"), "family_private")
        if scope not in {"public", "family_private", "private"}:
            scope = "family_private"
        limit = _optional_int((tool_request or {}).get("limit")) or 10
        return unified_evidence_corpus(
            session=session,
            scope=scope,
            limit=max(1, min(limit, 25)),
            include_unreviewed=False,
        )
    if tool_name == "plan_ranked_evidence_clusters":
        from app.services.retrieval import ranked_evidence_clusters

        payload = task.input_payload or {}
        query = (
            _string((tool_request or {}).get("query"))
            or _string(request.message)
            or _string(payload.get("prompt"))
            or _string(payload.get("source_title"))
            or _string(payload.get("asset_title"))
            or _string(payload.get("preview_text"))
            or _string(task.human_id)
        )
        scope = _string((tool_request or {}).get("scope"), "family_private")
        if scope not in {"public", "family_private", "private"}:
            scope = "family_private"
        limit = _optional_int((tool_request or {}).get("limit")) or 6
        per_cluster_limit = _optional_int((tool_request or {}).get("per_cluster_limit")) or 3
        return ranked_evidence_clusters(
            session=session,
            query=query,
            scope=scope,
            limit=max(1, min(limit, 10)),
            per_cluster_limit=max(1, min(per_cluster_limit, 5)),
            app_settings=app_settings,
        )
    if tool_name == "inspect_work_queue_plan":
        requested_route = _string((tool_request or {}).get("route"))
        if requested_route not in {
            "photo_review",
            "source_review",
            "sft_review",
            "dpo_review",
            "prompt_response_review",
            "export_readiness",
        }:
            requested_route = _requested_task_route(request, task) or _route_for_task(task) or ""
        limit = _optional_int((tool_request or {}).get("limit")) or 5
        return _work_queue_plan(
            session=session,
            request=request,
            selected_task=task,
            task_selection={
                "requested_route": requested_route,
                "requested_route_label": _route_label(requested_route),
                "selection_reason": "chat_read_tool_work_queue_plan",
                "selected_task_id": task.id,
                "selected_task_human_id": task.human_id,
            },
            app_settings=app_settings,
            route=requested_route,
            limit=limit,
        )
    if tool_name == "preview_source_pair_generation":
        from app.services.pair_generation import preview_make_gold_tasks_from_review

        if task.task_type not in {"text_segment_review", "text_segment_boundary_review", "email_voice_sample"}:
            return {
                "preview_type": "source_review_generate_pairs_preview",
                "status": "unsupported_task_type",
                "task_type": task.task_type,
                "does_not_mutate_state": True,
                "message": "Pair-generation preview is only available for source review tickets.",
            }
        decisions = {**current_decisions, **draft_decisions}
        return preview_make_gold_tasks_from_review(
            session=session,
            task=task,
            decisions=decisions,
            app_settings=app_settings,
            allow_live_model=live_text_generation_ready(app_settings),
        )
    raise ValueError(f"Unsupported chat read tool: {tool_name}")


def _execute_chat_read_tools(
    *,
    session: Session,
    task: Task,
    current_decisions: Dict[str, Any],
    draft_decisions: Dict[str, Any],
    missing_fields: List[str],
    request: ChatTurnRequest,
    app_settings: Settings,
    tool_requests: List[Dict[str, str]],
) -> List[Dict[str, Any]]:
    receipts: List[Dict[str, Any]] = []
    for item in tool_requests:
        tool_name = item["tool_name"]
        try:
            result = _execute_chat_read_tool(
                session=session,
                task=task,
                current_decisions=current_decisions,
                draft_decisions=draft_decisions,
                missing_fields=missing_fields,
                request=request,
                app_settings=app_settings,
                tool_name=tool_name,
                tool_request=item,
            )
            receipts.append(
                {
                    "tool_name": tool_name,
                    "reason": item.get("reason", ""),
                    "status": "completed",
                    "result": _sanitize_chat_value(result),
                }
            )
        except Exception as exc:  # pragma: no cover - defensive, individual tools should not fail the chat turn.
            receipts.append(
                {
                    "tool_name": tool_name,
                    "reason": item.get("reason", ""),
                    "status": "failed",
                    "error": f"{type(exc).__name__}: {_truncate_text(str(exc), 300)}",
                }
            )
    return receipts


def _combine_chat_response_usage(*responses: Any) -> Dict[str, Optional[int]]:
    input_total = 0
    output_total = 0
    saw_input = False
    saw_output = False
    for response in responses:
        usage = _response_usage_observability(response)
        input_count = usage.get("input_token_count")
        output_count = usage.get("output_token_count")
        if input_count is not None:
            input_total += input_count
            saw_input = True
        if output_count is not None:
            output_total += output_count
            saw_output = True
    return {
        "input_token_count": input_total if saw_input else None,
        "output_token_count": output_total if saw_output else None,
    }


def _live_chat_plan(
    *,
    session: Session,
    task: Task,
    current_decisions: Dict[str, Any],
    missing_fields: List[str],
    request: ChatTurnRequest,
    app_settings: Settings,
    draft_decisions: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    from openai import OpenAI

    client = OpenAI(
        api_key=app_settings.openai_api_key,
        project=app_settings.openai_project_id or None,
        timeout=180,
    )
    prompt = _chat_prompt(
        task=task,
        current_decisions=current_decisions,
        missing_fields=missing_fields,
        request=request,
    )
    image_data_url = _image_data_url_for_task(session, task, app_settings)
    developer_content = (
        "You are a tool-using operator for CharlesOps. Return one JSON object only. "
        "Draft-first, one question at a time, explicit confirmation before submit. "
        "If you need more task/schema/source context, first return tool_requests only; "
        "after tool receipts, return the final action plan only."
    )

    def response_user_content(text: str) -> Any:
        if not image_data_url:
            return text
        return [
            {"type": "input_text", "text": text},
            {"type": "input_image", "image_url": image_data_url},
        ]

    def create_response(text: str, *, max_output_tokens: int) -> Any:
        return client.responses.create(
            model=app_settings.text_generation_model,
            reasoning={"effort": _chat_reasoning_effort(app_settings)},
            input=[
                {
                    "role": "developer",
                    "content": developer_content,
                },
                {
                    "role": "user",
                    "content": response_user_content(text),
                },
            ],
            max_output_tokens=max_output_tokens,
            store=False,
        )

    started = time.perf_counter()
    response = create_response(prompt, max_output_tokens=1600)
    parsed = _parse_json_object(_string(getattr(response, "output_text", None)))
    if not parsed:
        raise ValueError("Chat model returned no parseable JSON object.")
    tool_requests = _normalize_chat_read_tool_requests(parsed.get("tool_requests"))
    tool_receipts: List[Dict[str, Any]] = []
    final_response = response
    if tool_requests:
        tool_receipts = _execute_chat_read_tools(
            session=session,
            task=task,
            current_decisions=current_decisions,
            draft_decisions=draft_decisions or {},
            missing_fields=missing_fields,
            request=request,
            app_settings=app_settings,
            tool_requests=tool_requests,
        )
        final_prompt = "\n\n".join(
            [
                prompt,
                "Read-only tool receipts:\n" + _truncate_text(tool_receipts, MAX_CONTEXT_CHARS),
                (
                    "Now return the final action-plan JSON only. Do not return more tool_requests. "
                    "If you will edit the ticket, include exact field_updates or draft_patch operations."
                ),
            ]
        )
        final_response = create_response(final_prompt, max_output_tokens=1800)
        parsed = _parse_json_object(_string(getattr(final_response, "output_text", None)))
        if not parsed:
            raise ValueError("Chat model returned no parseable JSON object after tool receipts.")
        parsed["tool_loop_used"] = True
        parsed["tool_requests"] = tool_requests
        parsed["tool_receipts"] = tool_receipts
    latency_ms = int((time.perf_counter() - started) * 1000)
    parsed["status"] = "live_model_call"
    usage = _combine_chat_response_usage(response, final_response) if final_response is not response else _response_usage_observability(response)
    parsed["_observability"] = {
        **usage,
        "latency_ms": latency_ms,
        "model_response_id": _string(getattr(final_response, "id", None)),
        "first_model_response_id": _string(getattr(response, "id", None)),
        "tool_loop_used": bool(tool_receipts),
        "tool_request_count": len(tool_requests),
        "tool_names": [item["tool_name"] for item in tool_requests],
        "image_pixels_included": bool(image_data_url),
    }
    return parsed


def _normalize_actions(actions: Any, *, ready_to_submit: bool, has_updates: bool, next_question: str) -> List[Dict[str, Any]]:
    normalized: List[Dict[str, Any]] = []
    if isinstance(actions, list):
        for action in actions:
            if not isinstance(action, dict):
                continue
            action_type = _string(action.get("type"))
            if action_type not in ALLOWED_CHAT_ACTIONS:
                continue
            if action_type in DRAFT_UPDATE_CHAT_ACTIONS and not has_updates:
                continue
            if action_type in {"preview_submit", "preview_task_submission", "submit_task"} and not ready_to_submit:
                continue
            if action_type == "mark_candidate_approved":
                if not ready_to_submit:
                    continue
                action_type = "submit_task"
            elif action_type == "mark_candidate_rejected":
                if not has_updates:
                    continue
                action_type = "update_task_draft"
            elif action_type == "preview_task_submission":
                action_type = "preview_submit"
            elif action_type == "focus_task":
                action_type = "open_task"
            if action_type in {"open_task", "create_or_open_review_task"} and has_updates:
                continue
            requires_confirmation = _chat_action_requires_confirmation(action_type, bool(action.get("requires_confirmation")))
            normalized_action = {
                "type": action_type,
                "label": _string(action.get("label"), action_type.replace("_", " ")),
                "requires_confirmation": requires_confirmation,
            }
            task_id = _string(action.get("task_id")) or _string(action.get("target_task_id"))
            if action_type == "open_task" and task_id:
                normalized_action["task_id"] = task_id
            if action_type == "create_or_open_review_task":
                for key in (
                    "task_id",
                    "asset_id",
                    "group_key",
                    "source_query",
                    "candidate_match_quality",
                    "candidate_selection_reason",
                    "review_task_type",
                    "source_asset_id",
                    "source_photo_id",
                    "source_segment_id",
                    "source_title",
                ):
                    value = _string(action.get(key))
                    if value:
                        normalized_action[key] = value
            normalized.append(normalized_action)
    if has_updates and not any(action.get("type") in DRAFT_UPDATE_CHAT_ACTIONS for action in normalized):
        normalized.insert(0, {"type": "update_task_draft", "label": "Update the active task draft", "requires_confirmation": False})
    if ready_to_submit and not any(action.get("type") == "submit_task" for action in normalized):
        normalized.append({"type": "submit_task", "label": "Submit this ticket", "requires_confirmation": True})
    if not ready_to_submit and next_question and not any(action.get("type") == "ask_question" for action in normalized):
        normalized.append({"type": "ask_question", "label": next_question, "requires_confirmation": False})
    return normalized


def _draft_to_dict(draft: TaskDraft | None) -> Optional[Dict[str, Any]]:
    return draft.model_dump(mode="json") if draft else None


def _recent_chat_context(history: List[ChatMessage]) -> List[Dict[str, str]]:
    rows: List[Dict[str, str]] = []
    for item in history[-MAX_HISTORY_MESSAGES:]:
        role = item.role if item.role in {"user", "assistant"} else "user"
        content = _string(item.content)
        if content:
            rows.append({"role": role, "content": _truncate_text(content, 500)})
    return rows


def _session_history_for_turn(
    *,
    session: Session,
    chat_session: ChatSession,
    client_history: List[ChatMessage],
) -> List[ChatMessage]:
    stored_turns = session.exec(
        select(ChatTurn)
        .where(ChatTurn.session_id == chat_session.id)
        .where(ChatTurn.role.in_(["user", "assistant"]))
        .order_by(ChatTurn.created_at.asc())
    ).all()
    rows: List[ChatMessage] = [
        ChatMessage(role=turn.role, content=turn.content)
        for turn in stored_turns
        if turn.role in {"user", "assistant"} and _string(turn.content)
    ]
    seen = {(item.role, item.content) for item in rows}
    for item in client_history:
        role = item.role if item.role in {"user", "assistant"} else "user"
        content = _string(item.content)
        if not content or (role, content) in seen:
            continue
        rows.append(ChatMessage(role=role, content=content))
        seen.add((role, content))
    return rows[-MAX_HISTORY_MESSAGES:]


def _source_material_preview(task: Task, current_decisions: Dict[str, Any]) -> Dict[str, Any]:
    payload = task.input_payload or {}
    merged = {**payload, **current_decisions}
    return {
        key: merged.get(key)
        for key in (
            "asset_title",
            "source_title",
            "source_filename",
            "prompt",
            "content",
            "chosen",
            "rejected",
            "preview_text",
            "source_excerpt",
            "visual_summary",
            "description",
        )
        if merged.get(key) not in (None, "", [], {})
    }


def _detected_user_intent(request: ChatTurnRequest, task_selection: Dict[str, Any]) -> Dict[str, Any]:
    requested_route = _string(task_selection.get("requested_route")) or _route_from_mode(request.mode) or _route_from_message(request.message)
    return {
        "requested_route": requested_route or None,
        "submit_requested": _chat_submit_requested(request.message),
        "next_task_requested": _next_task_requested(request.message),
        "skip_current_requested": _skip_current_requested(request.message),
        "go_back_requested": _go_back_requested(request.message),
        "export_blocker_requested": _open_export_blocker_requested(request.message),
    }


def _context_packet_for_turn(
    *,
    session: Session,
    task: Task,
    current_decisions: Dict[str, Any],
    draft_decisions: Dict[str, Any],
    missing_fields: List[str],
    request: ChatTurnRequest,
    app_settings: Settings,
    task_selection: Dict[str, Any],
) -> Dict[str, Any]:
    image_context = _image_context_for_task(session, task, app_settings)
    image_context = {
        **image_context,
        "image_pixels_included_if_live_call": bool(
            image_context.get("image_pixels_available") and live_text_generation_ready(app_settings)
        ),
    }
    return {
        "active_task": _task_summary(task),
        "task_kind": _task_kind(task),
        "work_surface": _task_work_surface(task, current_decisions),
        "object_contracts": _object_contracts_for_task(task, current_decisions),
        "source_refs": _chat_source_refs_for_task(task),
        "associated_object_ids": _associated_object_ids_for_task(task),
        "source_material_preview": _source_material_preview(task, current_decisions),
        "recent_chat": _recent_chat_context(request.history),
        "current_draft": {
            "decisions": draft_decisions,
            "field_count": len(draft_decisions),
        },
        "provenance_refs": {
            "task_id": task.id,
            "task_human_id": task.human_id,
            "target_type": task.target_type,
            "target_id": task.target_id,
            "session_id": request.session_id,
        },
        "required_decisions": task.required_decisions or [],
        "missing_fields": missing_fields,
        "allowed_field_updates": sorted(_allowed_update_keys(task)),
        "allowed_actions": sorted(ALLOWED_CHAT_ACTIONS),
        "action_contracts": _chat_action_contracts_for_context(),
        "read_tool_contracts": _chat_read_tool_contracts_for_context(),
        "current_user_intent": _detected_user_intent(request, task_selection),
        "task_selection": task_selection,
        "draft_decisions": draft_decisions,
        "image_context": image_context,
        "request": {
            "mode": request.mode,
            "apply_updates": request.apply_updates,
            "confirm_submit": request.confirm_submit,
            "confirm_action_id": request.confirm_action_id,
            "user_id": request.user_id,
        },
    }


def _action_payload_for_record(
    *,
    action: Dict[str, Any],
    task: Task,
    field_updates: Dict[str, Any],
    field_diffs: List[Dict[str, Any]],
    draft_patch: List[Dict[str, Any]],
    patch_result: Dict[str, Any],
    submit_payload: Optional[Dict[str, Any]],
    next_question: Optional[str],
    context_packet_hash: str,
) -> Dict[str, Any]:
    action_type = _string(action.get("type"))
    if action_type in DRAFT_UPDATE_CHAT_ACTIONS:
        return {
            "task_id": task.id,
            "semantic_action_type": action_type,
            "field_updates": field_updates,
            "field_diffs": field_diffs,
            "draft_patch": draft_patch,
            "patch_result": patch_result,
            "context_packet_hash": context_packet_hash,
        }
    if action_type in {"preview_submit", "preview_task_submission", "submit_task", "mark_candidate_approved", "mark_candidate_rejected"}:
        return {"task_id": task.id, "submit_payload": submit_payload, "field_diffs": field_diffs, "context_packet_hash": context_packet_hash}
    if action_type == "ask_question":
        return {"task_id": task.id, "question": next_question or action.get("label"), "context_packet_hash": context_packet_hash}
    if action_type == "open_task":
        return {
            "task_id": task.id,
            "target_task_id": action.get("task_id") or task.id,
            "label": action.get("label"),
            "context_packet_hash": context_packet_hash,
        }
    if action_type == "create_or_open_review_task":
        review_task_type = _string(action.get("review_task_type"), "photo_context")
        source_photo_id = _string(action.get("source_photo_id"))
        asset_id = _string(action.get("asset_id")) or source_photo_id
        return {
            "task_id": task.id,
            "review_task_creation_payload": {
                "review_task_type": review_task_type,
                "asset_id": asset_id,
                "source_photo_id": source_photo_id,
                "group_key": _string(action.get("group_key")),
                "task_id": _string(action.get("task_id")),
                "source_query": _string(action.get("source_query")),
                "candidate_match_quality": _string(action.get("candidate_match_quality"), "backlog_only"),
                "candidate_selection_reason": _string(action.get("candidate_selection_reason"), "chat_selected_retrieval_gap_cluster"),
                "source_asset_id": _string(action.get("source_asset_id")) or asset_id,
                "source_segment_id": _string(action.get("source_segment_id")),
                "source_title": _string(action.get("source_title")),
                "requires_confirmation": True,
                "does_not_create_memory_claim": True,
            },
            "label": action.get("label"),
            "context_packet_hash": context_packet_hash,
        }
    return {"task_id": task.id, "label": action.get("label"), "context_packet_hash": context_packet_hash}


def _empty_like(value: Any) -> bool:
    return value is None or value == "" or value == [] or value == {}


def _field_update_source_for_task(task: Optional[Task], field: str) -> str:
    if task is None:
        return ""
    kind = _task_kind(task)
    if kind == "photo_review":
        if field in {"adam_context_note", "retrieval_cues", "event_summary", "memory_caption", "emotional_salience"}:
            return "adam_provided_memory"
        if field in {"open_questions", "uncertainties", "uncertainty_notes"}:
            return "adam_confirmed_uncertainty"
        if field in {"machine_guess_people", "machine_guess_objects", "machine_tags", "visual_summary"}:
            return "model_visual_inference"
        if field in {"asset_id", "source_photo_id", "source_photo_title", "asset_title"}:
            return "database_derived_association"
        return "adam_confirmed_fact"
    if kind == "prompt_response_review":
        if field == "prompt":
            return "source_prompt"
        if field in {"context", "failure_modes", "operator_candidate_triage_intent"}:
            return "adam_critique"
        if field in {"content", "chosen", "rejected"}:
            return "assistant_rewrite_or_adam_edit"
        if field == "export_flags":
            return "backend_export_policy"
        return "assistant_rewrite_or_review_metadata"
    if kind == "source_review":
        return "adam_source_review"
    return "adam_review"


def _field_diffs(before: Dict[str, Any], updates: Dict[str, Any], *, task: Optional[Task] = None) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for key, after_value in updates.items():
        existed = key in before
        before_value = before.get(key)
        if before_value == after_value:
            change_type = "unchanged"
        elif _empty_like(after_value):
            change_type = "removed"
        elif not existed or _empty_like(before_value):
            change_type = "added"
        else:
            change_type = "changed"
        rows.append(
            {
                "field": key,
                "before": before_value,
                "after": after_value,
                "change_type": change_type,
            }
        )
        value_source = _field_update_source_for_task(task, key)
        if value_source:
            rows[-1]["value_source"] = value_source
    return rows


def _export_preview_types_from_request(request: ChatTurnRequest) -> List[str]:
    text = _normalize_intent_text(request.mode, request.message)
    if not text:
        return []
    preview_requested = ("preview" in text and ("export" in text or "jsonl" in text)) or any(
        phrase in text
        for phrase in (
            "export preview",
            "preview export",
            "preview the export",
            "preview sft export",
            "preview dpo export",
            "dry run",
            "dry-run",
            "what would be included",
            "what would go into",
            "show jsonl",
            "jsonl preview",
        )
    )
    if not preview_requested:
        return []
    export_context = "export" in text or "jsonl" in text or "dry run" in text or "dry-run" in text
    if not export_context:
        return []
    requested: List[str] = []
    if any(phrase in text for phrase in ("sft", "supervised", "fine tuning", "fine-tuning", "voice example", "voice examples")):
        requested.append("sft")
    if any(phrase in text for phrase in ("dpo", "preference", "chosen", "rejected")):
        requested.append("dpo")
    return requested or ["sft", "dpo"]


def _export_preview_include_candidates(request: ChatTurnRequest) -> bool:
    text = _normalize_intent_text(request.message)
    return any(phrase in text for phrase in ("include candidates", "candidate preview", "candidate dry run", "with candidates"))


def _export_build_type_from_request(request: ChatTurnRequest) -> str:
    text = _normalize_intent_text(request.mode, request.message)
    if not text:
        return ""
    if "preview" in text or "dry run" in text or "dry-run" in text or "readiness" in text or "blocked" in text or "blocker" in text:
        return ""
    build_requested = any(
        phrase in text
        for phrase in (
            "build export",
            "build the export",
            "build the sft export",
            "build the dpo export",
            "build sft export",
            "build dpo export",
            "create export",
            "generate export",
            "make export",
            "export sft",
            "export dpo",
            "build jsonl",
            "generate jsonl",
        )
    )
    if not build_requested:
        return ""
    if any(phrase in text for phrase in ("sft", "supervised", "fine tuning", "fine-tuning", "voice example", "voice examples")):
        return "sft"
    if any(phrase in text for phrase in ("dpo", "preference", "chosen", "rejected")):
        return "dpo"
    return ""


def _count_exclusion_reasons(rows: List[Dict[str, Any]]) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for row in rows:
        reasons = row.get("reasons") if isinstance(row, dict) else None
        if not isinstance(reasons, list):
            continue
        for reason in reasons:
            key = str(reason).strip()
            if key:
                counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items(), key=lambda item: (-item[1], item[0])))


def _payload_preview(payload: Dict[str, Any], export_type: str) -> Dict[str, Any]:
    if export_type == "dpo":
        input_payload = payload.get("input") if isinstance(payload.get("input"), dict) else {}
        messages = input_payload.get("messages") if isinstance(input_payload.get("messages"), list) else []
        user_message = next(
            (message.get("content") for message in messages if isinstance(message, dict) and message.get("role") == "user"),
            "",
        )
        return {
            "prompt": _truncate_text(user_message, 240),
            "preferred_output": _truncate_text(payload.get("preferred_output") or "", 300),
            "non_preferred_output": _truncate_text(payload.get("non_preferred_output") or "", 300),
        }
    messages = payload.get("messages") if isinstance(payload.get("messages"), list) else []
    user_message = next(
        (message.get("content") for message in messages if isinstance(message, dict) and message.get("role") == "user"),
        "",
    )
    assistant_message = next(
        (message.get("content") for message in messages if isinstance(message, dict) and message.get("role") == "assistant"),
        "",
    )
    return {
        "prompt": _truncate_text(user_message, 240),
        "assistant_response": _truncate_text(assistant_message, 300),
    }


def _export_preview_for_type(session: Session, export_type: str, *, include_candidates: bool) -> Dict[str, Any]:
    dry_run = export_dry_run(session, export_type, include_candidates=include_candidates)
    included = dry_run.get("included") if isinstance(dry_run.get("included"), list) else []
    excluded = dry_run.get("excluded") if isinstance(dry_run.get("excluded"), list) else []
    payloads = [row.get("payload") for row in included if isinstance(row, dict) and isinstance(row.get("payload"), dict)]
    jsonl_lines = [line for line in to_jsonl(payloads[:3]).splitlines() if line.strip()]
    preview_rows: List[Dict[str, Any]] = []
    for row in included[:3]:
        if not isinstance(row, dict):
            continue
        source = row.get("source") if isinstance(row.get("source"), dict) else {}
        payload = row.get("payload") if isinstance(row.get("payload"), dict) else {}
        metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
        preview_rows.append(
            {
                "artifact_type": row.get("artifact_type"),
                "artifact_id": row.get("artifact_id"),
                "source_id": row.get("source_gold_voice_example_id") or source.get("task_id"),
                "source_label": source.get("gold_human_id") or source.get("task_human_id") or row.get("artifact_id"),
                "voice_mode": source.get("voice_mode") or metadata.get("voice_mode"),
                "truth_status": source.get("truth_status") or metadata.get("truth_status"),
                "payload_preview": _payload_preview(payload, export_type),
            }
        )
    reason_counts = _count_exclusion_reasons(excluded)
    top_reason = next(iter(reason_counts), None)
    return {
        "export_type": export_type,
        "mode": dry_run.get("mode"),
        "include_candidates": include_candidates,
        "included_count": int(dry_run.get("included_count") or 0),
        "excluded_count": int(dry_run.get("excluded_count") or 0),
        "excluded_reason_counts": reason_counts,
        "top_exclusion_reason": top_reason,
        "preview_rows": preview_rows,
        "jsonl_preview": "\n".join(jsonl_lines),
        "jsonl_preview_line_count": len(jsonl_lines),
        "dry_run_endpoint": f"/api/dataset-exports/dry-run?export_type={export_type}&include_candidates={str(include_candidates).lower()}",
        "download_endpoint": f"/api/dataset-exports/jsonl?export_type={export_type}",
    }


def _export_preview_hash(preview: Dict[str, Any]) -> str:
    return _json_hash(
        {
            "export_type": preview.get("export_type"),
            "include_candidates": preview.get("include_candidates"),
            "included_count": preview.get("included_count"),
            "excluded_count": preview.get("excluded_count"),
            "excluded_reason_counts": preview.get("excluded_reason_counts"),
            "preview_rows": preview.get("preview_rows"),
            "jsonl_preview": preview.get("jsonl_preview"),
        }
    )


def _export_preview_message(work_summary: Dict[str, Any]) -> str:
    previews = work_summary.get("previews") if isinstance(work_summary.get("previews"), list) else []
    if not previews:
        return "I could not build an export preview from the current dataset state. No export was built."
    pieces: List[str] = []
    for preview in previews:
        if not isinstance(preview, dict):
            continue
        export_type = _string(preview.get("export_type"), "export").upper()
        included_count = int(preview.get("included_count") or 0)
        excluded_count = int(preview.get("excluded_count") or 0)
        top_reason = _string(preview.get("top_exclusion_reason"))
        blocker = f"; top exclusion: {top_reason}" if top_reason else ""
        pieces.append(f"{export_type}: {included_count} approved row(s) included, {excluded_count} item(s) excluded{blocker}")
    summary = "; ".join(pieces)
    return f"Export preview is a dry run. {summary}. No export was built or stored."


def _build_export_preview_turn(
    *,
    session: Session,
    request: ChatTurnRequest,
    app_settings: Settings,
    export_types: List[str],
) -> Dict[str, Any]:
    include_candidates = _export_preview_include_candidates(request)
    chat_session = _resolve_chat_session(
        session=session,
        request=request,
        task=None,
        app_settings=app_settings,
    )
    previews = [
        _export_preview_for_type(session, export_type, include_candidates=include_candidates)
        for export_type in export_types
        if export_type in {"sft", "dpo"}
    ]
    work_summary = {
        "summary_type": "export_preview",
        "export_type": previews[0]["export_type"] if len(previews) == 1 else "both",
        "export_types": [preview["export_type"] for preview in previews],
        "include_candidates": include_candidates,
        "included_count": sum(int(preview.get("included_count") or 0) for preview in previews),
        "excluded_count": sum(int(preview.get("excluded_count") or 0) for preview in previews),
        "previews": previews,
        "does_not_mutate_state": True,
        "no_live_model_call": True,
    }
    task_selection = {
        "requested_route": "export_preview",
        "requested_route_label": _route_label("export_preview"),
        "selection_reason": "export_preview_summary",
        "selected_task_id": None,
        "export_types": work_summary["export_types"],
        "include_candidates": include_candidates,
    }
    context_packet = {
        "active_task": None,
        "request": {"mode": request.mode, "user_id": request.user_id},
        "status": "export_preview_summary",
        "task_selection": task_selection,
        "work_summary": work_summary,
    }
    context_packet_hash = _json_hash(context_packet)
    _record_chat_turn(
        session=session,
        chat_session=chat_session,
        task=None,
        role="user",
        content=request.message,
        context_packet_hash=context_packet_hash,
        metadata={"mode": request.mode, "task_selection": task_selection},
    )
    assistant_message = _export_preview_message(work_summary)
    assistant_turn = _record_chat_turn(
        session=session,
        chat_session=chat_session,
        task=None,
        role="assistant",
        content=assistant_message,
        model_name=app_settings.text_generation_model,
        context_packet_hash=context_packet_hash,
        metadata={
            "status": "export_preview_summary",
            "task_selection": task_selection,
            "work_summary": work_summary,
            "live_model_call_used": False,
        },
    )
    chat_session.active_task_id = None
    chat_session.updated_at = datetime.now(timezone.utc)
    chat_session.metadata_json = _updated_session_metadata(
        current_metadata=chat_session.metadata_json,
        task=None,
        status="export_preview_summary",
        context_packet_hash=context_packet_hash,
        task_selection=task_selection,
    )
    session.add(chat_session)
    session.commit()
    return {
        "status": "export_preview_summary",
        "session_id": chat_session.id,
        "turn_id": assistant_turn.id,
        "context_packet_hash": context_packet_hash,
        "assistant_message": assistant_message,
        "next_question": None,
        "model_name": app_settings.text_generation_model,
        "reasoning_effort": _chat_reasoning_effort(app_settings),
        "model_ready": live_text_generation_ready(app_settings),
        "live_model_call_used": False,
        "active_task": {},
        "task_selection": task_selection,
        "work_surface": {"kind": "export_preview"},
        "work_summary": work_summary,
        "actions": [],
        "field_updates": {},
        "draft_decisions": {},
        "draft": None,
        "ready_to_submit": False,
        "submit_payload": None,
        "safety_policy": _safety_policy(),
    }


def _build_export_build_version(export_type: str) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    return f"chat-{export_type}-{stamp}"


def _build_export_build_preview_turn(
    *,
    session: Session,
    request: ChatTurnRequest,
    app_settings: Settings,
    export_type: str,
) -> Dict[str, Any]:
    chat_session = _resolve_chat_session(
        session=session,
        request=request,
        task=None,
        app_settings=app_settings,
    )
    preview = _export_preview_for_type(session, export_type, include_candidates=False)
    export_build_payload = {
        "export_type": export_type,
        "version": _build_export_build_version(export_type),
        "split": "train",
        "include_candidates": False,
        "approved_only": True,
        "included_count": preview["included_count"],
        "excluded_count": preview["excluded_count"],
        "dry_run_hash": _export_preview_hash(preview),
        "dry_run_endpoint": preview["dry_run_endpoint"],
    }
    work_summary = {
        "summary_type": "export_build_confirmation",
        "export_type": export_type,
        "include_candidates": False,
        "included_count": preview["included_count"],
        "excluded_count": preview["excluded_count"],
        "previews": [preview],
        "does_not_mutate_state": True,
        "requires_confirmation": True,
    }
    task_selection = {
        "requested_route": "export_build",
        "requested_route_label": "export build",
        "selection_reason": "export_build_confirmation_required",
        "selected_task_id": None,
        "export_type": export_type,
        "include_candidates": False,
    }
    context_packet = {
        "active_task": None,
        "request": {"mode": request.mode, "user_id": request.user_id},
        "status": "export_build_confirmation_required",
        "task_selection": task_selection,
        "work_summary": work_summary,
        "export_build_payload": export_build_payload,
    }
    context_packet_hash = _json_hash(context_packet)
    _record_chat_turn(
        session=session,
        chat_session=chat_session,
        task=None,
        role="user",
        content=request.message,
        context_packet_hash=context_packet_hash,
        metadata={"mode": request.mode, "task_selection": task_selection},
    )
    assistant_message = (
        f"I can build the approved-only {export_type.upper()} export with {preview['included_count']} row(s) "
        f"and {preview['excluded_count']} excluded item(s). Confirm before I create the dataset export record."
    )
    assistant_turn = _record_chat_turn(
        session=session,
        chat_session=chat_session,
        task=None,
        role="assistant",
        content=assistant_message,
        model_name=app_settings.text_generation_model,
        context_packet_hash=context_packet_hash,
        metadata={
            "status": "export_build_confirmation_required",
            "task_selection": task_selection,
            "work_summary": work_summary,
            "live_model_call_used": False,
        },
    )
    chat_action = ChatAction(
        session_id=chat_session.id,
        turn_id=assistant_turn.id,
        task_id=None,
        action_type="build_dataset_export",
        status="pending_confirmation",
        proposed_payload_json={
            "export_build_payload": export_build_payload,
            "context_packet_hash": context_packet_hash,
        },
        validated_payload_json={
            "export_build_payload": export_build_payload,
            "context_packet_hash": context_packet_hash,
        },
        requires_confirmation=True,
        metadata_json={"source": "chat_operator", "label": f"Build {export_type.upper()} export", "preview_turn_id": assistant_turn.id},
    )
    session.add(chat_action)
    session.flush()
    chat_session.active_task_id = None
    chat_session.updated_at = datetime.now(timezone.utc)
    chat_session.metadata_json = _updated_session_metadata(
        current_metadata=chat_session.metadata_json,
        task=None,
        status="export_build_confirmation_required",
        context_packet_hash=context_packet_hash,
        task_selection=task_selection,
    )
    session.add(chat_session)
    session.commit()
    return {
        "status": "export_build_confirmation_required",
        "session_id": chat_session.id,
        "turn_id": assistant_turn.id,
        "context_packet_hash": context_packet_hash,
        "assistant_message": assistant_message,
        "next_question": None,
        "model_name": app_settings.text_generation_model,
        "reasoning_effort": _chat_reasoning_effort(app_settings),
        "model_ready": live_text_generation_ready(app_settings),
        "live_model_call_used": False,
        "active_task": {},
        "task_selection": task_selection,
        "work_surface": {"kind": "export_build"},
        "work_summary": work_summary,
        "actions": [
            {
                "type": "build_dataset_export",
                "label": f"Build {export_type.upper()} export",
                "requires_confirmation": True,
                "id": chat_action.id,
                "status": chat_action.status,
            }
        ],
        "field_updates": {},
        "draft_decisions": {},
        "draft": None,
        "ready_to_submit": False,
        "submit_payload": None,
        "export_build_payload": export_build_payload,
        "built_export": None,
        "safety_policy": _safety_policy(),
    }


def _build_pending_action_confirmation_turn(
    *,
    session: Session,
    request: ChatTurnRequest,
    app_settings: Settings,
) -> Dict[str, Any]:
    pending_action = session.get(ChatAction, request.confirm_action_id) if request.confirm_action_id else None
    if pending_action is None or pending_action.action_type not in {"build_dataset_export", "create_or_open_review_task"}:
        raise ValueError("Unsupported chat action confirmation.")
    chat_session = session.get(ChatSession, pending_action.session_id)
    if chat_session is None:
        raise ValueError("Chat session not found for pending action.")
    payload = pending_action.validated_payload_json if isinstance(pending_action.validated_payload_json, dict) else {}
    if pending_action.action_type == "create_or_open_review_task":
        review_task_creation_payload = payload.get("review_task_creation_payload") if isinstance(payload.get("review_task_creation_payload"), dict) else {}
        review_task_type = _string(review_task_creation_payload.get("review_task_type"), "photo_context")
        task_selection = {
            "requested_route": "create_or_open_review_task",
            "requested_route_label": "review task creation",
            "selection_reason": "pending_review_task_creation_confirmed",
            "selected_task_id": pending_action.task_id,
            "review_task_type": review_task_type,
            "confirmed_action_id": pending_action.id,
        }
        work_summary = {
            "summary_type": "review_task_creation_confirmation",
            "review_task_type": review_task_type,
            "source_query": review_task_creation_payload.get("source_query"),
            "candidate_match_quality": review_task_creation_payload.get("candidate_match_quality"),
            "does_not_mutate_state": False,
            "requires_confirmation": True,
            "confirmed_action_id": pending_action.id,
        }
        context_packet = {
            "active_task": None,
            "request": {
                "mode": request.mode,
                "user_id": request.user_id,
                "confirm_action": request.confirm_action,
                "confirm_action_id": request.confirm_action_id,
            },
            "status": "review_task_creation_confirmed",
            "task_selection": task_selection,
            "work_summary": work_summary,
            "review_task_creation_payload": review_task_creation_payload,
        }
        context_packet_hash = _json_hash(context_packet)
        _record_chat_turn(
            session=session,
            chat_session=chat_session,
            task=None,
            role="user",
            content=request.message,
            context_packet_hash=context_packet_hash,
            metadata={"mode": request.mode, "confirm_action": True, "confirm_action_id": request.confirm_action_id},
        )
        assistant_message = "Confirmed. I am creating or opening the review task from that evidence cluster now."
        assistant_turn = _record_chat_turn(
            session=session,
            chat_session=chat_session,
            task=None,
            role="assistant",
            content=assistant_message,
            model_name=app_settings.text_generation_model,
            context_packet_hash=context_packet_hash,
            metadata={
                "status": "review_task_creation_confirmed",
                "task_selection": task_selection,
                "work_summary": work_summary,
                "live_model_call_used": False,
            },
        )
        existing_metadata = pending_action.metadata_json if isinstance(pending_action.metadata_json, dict) else {}
        preview_turn_id = _string(existing_metadata.get("preview_turn_id")) or pending_action.turn_id
        pending_action.turn_id = assistant_turn.id
        pending_action.status = "pending_confirmation"
        pending_action.metadata_json = {
            **existing_metadata,
            "preview_turn_id": preview_turn_id,
            "confirmed_from_turn_id": assistant_turn.id,
        }
        session.add(pending_action)
        chat_session.updated_at = datetime.now(timezone.utc)
        chat_session.metadata_json = _updated_session_metadata(
            current_metadata=chat_session.metadata_json,
            task=None,
            status="review_task_creation_confirmed",
            context_packet_hash=context_packet_hash,
            task_selection=task_selection,
        )
        session.add(chat_session)
        session.commit()
        return {
            "status": "review_task_creation_confirmed",
            "session_id": chat_session.id,
            "turn_id": assistant_turn.id,
            "context_packet_hash": context_packet_hash,
            "assistant_message": assistant_message,
            "next_question": None,
            "model_name": app_settings.text_generation_model,
            "reasoning_effort": _chat_reasoning_effort(app_settings),
            "model_ready": live_text_generation_ready(app_settings),
            "live_model_call_used": False,
            "active_task": {},
            "task_selection": task_selection,
            "work_surface": {"kind": "review_task_creation"},
            "work_summary": work_summary,
            "actions": [
                {
                    "type": "create_or_open_review_task",
                    "label": _string(existing_metadata.get("label"), "Create or open review task"),
                    "requires_confirmation": True,
                    "id": pending_action.id,
                    "status": pending_action.status,
                }
            ],
            "field_updates": {},
            "draft_decisions": {},
            "draft": None,
            "ready_to_submit": False,
            "submit_payload": None,
            "review_task_creation_payload": review_task_creation_payload,
            "created_review_task": None,
            "safety_policy": _safety_policy(),
        }

    export_build_payload = payload.get("export_build_payload") if isinstance(payload.get("export_build_payload"), dict) else {}
    export_type = _string(export_build_payload.get("export_type"), "export")
    work_summary = {
        "summary_type": "export_build_confirmed",
        "export_type": export_type,
        "include_candidates": False,
        "included_count": export_build_payload.get("included_count"),
        "excluded_count": export_build_payload.get("excluded_count"),
        "does_not_mutate_state": False,
        "confirmed_action_id": pending_action.id,
    }
    task_selection = {
        "requested_route": "export_build",
        "requested_route_label": "export build",
        "selection_reason": "pending_export_build_confirmed",
        "selected_task_id": None,
        "export_type": export_type,
        "confirmed_action_id": pending_action.id,
    }
    context_packet = {
        "active_task": None,
        "request": {
            "mode": request.mode,
            "user_id": request.user_id,
            "confirm_action": request.confirm_action,
            "confirm_action_id": request.confirm_action_id,
        },
        "status": "export_build_confirmed",
        "task_selection": task_selection,
        "work_summary": work_summary,
        "export_build_payload": export_build_payload,
    }
    context_packet_hash = _json_hash(context_packet)
    _record_chat_turn(
        session=session,
        chat_session=chat_session,
        task=None,
        role="user",
        content=request.message,
        context_packet_hash=context_packet_hash,
        metadata={"mode": request.mode, "confirm_action": True, "confirm_action_id": request.confirm_action_id},
    )
    assistant_message = f"Confirmed. I am building the approved-only {export_type.upper()} export now."
    assistant_turn = _record_chat_turn(
        session=session,
        chat_session=chat_session,
        task=None,
        role="assistant",
        content=assistant_message,
        model_name=app_settings.text_generation_model,
        context_packet_hash=context_packet_hash,
        metadata={
            "status": "export_build_confirmed",
            "task_selection": task_selection,
            "work_summary": work_summary,
            "live_model_call_used": False,
        },
    )
    existing_metadata = pending_action.metadata_json if isinstance(pending_action.metadata_json, dict) else {}
    preview_turn_id = _string(existing_metadata.get("preview_turn_id")) or pending_action.turn_id
    pending_action.turn_id = assistant_turn.id
    pending_action.status = "pending_confirmation"
    pending_action.metadata_json = {
        **existing_metadata,
        "preview_turn_id": preview_turn_id,
        "confirmed_from_turn_id": assistant_turn.id,
    }
    session.add(pending_action)
    _log_chat_event(
        "action_confirmed",
        session_id=pending_action.session_id,
        turn_id=assistant_turn.id,
        action_id=pending_action.id,
        action_type=pending_action.action_type,
    )
    chat_session.active_task_id = None
    chat_session.updated_at = datetime.now(timezone.utc)
    chat_session.metadata_json = _updated_session_metadata(
        current_metadata=chat_session.metadata_json,
        task=None,
        status="export_build_confirmed",
        context_packet_hash=context_packet_hash,
        task_selection=task_selection,
    )
    session.add(chat_session)
    session.commit()
    return {
        "status": "export_build_confirmed",
        "session_id": chat_session.id,
        "turn_id": assistant_turn.id,
        "context_packet_hash": context_packet_hash,
        "assistant_message": assistant_message,
        "next_question": None,
        "model_name": app_settings.text_generation_model,
        "reasoning_effort": _chat_reasoning_effort(app_settings),
        "model_ready": live_text_generation_ready(app_settings),
        "live_model_call_used": False,
        "active_task": {},
        "task_selection": task_selection,
        "work_surface": {"kind": "export_build"},
        "work_summary": work_summary,
        "actions": [
            {
                "type": "build_dataset_export",
                "label": f"Build {export_type.upper()} export",
                "requires_confirmation": True,
                "id": pending_action.id,
                "status": pending_action.status,
            }
        ],
        "field_updates": {},
        "draft_decisions": {},
        "draft": None,
        "ready_to_submit": False,
        "submit_payload": None,
        "export_build_payload": export_build_payload,
        "built_export": None,
        "safety_policy": _safety_policy(),
    }


def _build_pending_submit_confirmation_turn(
    *,
    session: Session,
    request: ChatTurnRequest,
    app_settings: Settings,
) -> Dict[str, Any]:
    pending_action = session.get(ChatAction, request.confirm_action_id) if request.confirm_action_id else None
    if pending_action is None or pending_action.action_type != "submit_task":
        raise ValueError("Unsupported chat submit confirmation.")
    chat_session = session.get(ChatSession, pending_action.session_id)
    if chat_session is None:
        raise ValueError("Chat session not found for pending submit action.")
    task = session.get(Task, pending_action.task_id) if pending_action.task_id else None
    if task is None:
        raise ValueError("Task not found for pending submit action.")
    payload = pending_action.validated_payload_json if isinstance(pending_action.validated_payload_json, dict) else {}
    submit_payload = payload.get("submit_payload") if isinstance(payload.get("submit_payload"), dict) else {}
    field_diffs = payload.get("field_diffs") if isinstance(payload.get("field_diffs"), list) else []
    task_selection = {
        "requested_route": "submit_task",
        "requested_route_label": "submit ticket",
        "selection_reason": "pending_submit_confirmed",
        "selected_task_id": task.id,
        "selected_task_human_id": task.human_id,
        "confirmed_action_id": pending_action.id,
    }
    work_summary = {
        "summary_type": "submit_confirmation",
        "task_id": task.id,
        "task_human_id": task.human_id,
        "does_not_mutate_state": False,
        "confirmed_action_id": pending_action.id,
    }
    work_surface = _task_work_surface(
        task,
        submit_payload.get("decisions") if isinstance(submit_payload.get("decisions"), dict) else {},
    )
    context_packet = {
        "active_task": _task_summary(task),
        "work_surface": work_surface,
        "request": {
            "mode": request.mode,
            "user_id": request.user_id,
            "confirm_submit": request.confirm_submit,
            "confirm_action_id": request.confirm_action_id,
        },
        "status": "submit_confirmed",
        "task_selection": task_selection,
        "work_summary": work_summary,
        "submit_payload": submit_payload,
    }
    context_packet_hash = _json_hash(context_packet)
    _record_chat_turn(
        session=session,
        chat_session=chat_session,
        task=task,
        role="user",
        content=request.message or "ready",
        context_packet_hash=context_packet_hash,
        metadata={"mode": request.mode, "confirm_submit": True, "confirm_action_id": request.confirm_action_id},
    )
    assistant_message = "Confirmed. I am submitting the previewed ticket payload now."
    assistant_turn = _record_chat_turn(
        session=session,
        chat_session=chat_session,
        task=task,
        role="assistant",
        content=assistant_message,
        model_name=app_settings.text_generation_model,
        context_packet_hash=context_packet_hash,
        metadata={
            "status": "submit_confirmed",
            "task_selection": task_selection,
            "work_surface": work_surface,
            "work_summary": work_summary,
            "live_model_call_used": False,
        },
    )
    existing_metadata = pending_action.metadata_json if isinstance(pending_action.metadata_json, dict) else {}
    preview_turn_id = _string(existing_metadata.get("preview_turn_id")) or pending_action.turn_id
    pending_action.turn_id = assistant_turn.id
    pending_action.status = "pending_confirmation"
    pending_action.metadata_json = {
        **existing_metadata,
        "preview_turn_id": preview_turn_id,
        "confirmed_from_turn_id": assistant_turn.id,
    }
    session.add(pending_action)
    _log_chat_event(
        "action_confirmed",
        session_id=pending_action.session_id,
        turn_id=assistant_turn.id,
        task_id=task.id,
        action_id=pending_action.id,
        action_type=pending_action.action_type,
    )
    chat_session.active_task_id = task.id
    chat_session.updated_at = datetime.now(timezone.utc)
    chat_session.metadata_json = _updated_session_metadata(
        current_metadata=chat_session.metadata_json,
        task=task,
        status="submit_confirmed",
        context_packet_hash=context_packet_hash,
        task_selection=task_selection,
        task_kind=_task_kind(task),
    )
    session.add(chat_session)
    session.commit()
    return {
        "status": "submit_confirmed",
        "session_id": chat_session.id,
        "turn_id": assistant_turn.id,
        "context_packet_hash": context_packet_hash,
        "assistant_message": assistant_message,
        "next_question": None,
        "model_name": app_settings.text_generation_model,
        "reasoning_effort": _chat_reasoning_effort(app_settings),
        "model_ready": live_text_generation_ready(app_settings),
        "live_model_call_used": False,
        "active_task": _task_summary(task),
        "task_selection": task_selection,
        "work_surface": work_surface,
        "work_summary": work_summary,
        "actions": [
            {
                "type": "submit_task",
                "label": "Submit this ticket",
                "requires_confirmation": True,
                "id": pending_action.id,
                "status": pending_action.status,
            }
        ],
        "field_updates": {},
        "field_diffs": field_diffs,
        "draft_decisions": submit_payload.get("decisions") if isinstance(submit_payload.get("decisions"), dict) else {},
        "draft": None,
        "ready_to_submit": True,
        "submit_payload": submit_payload,
        "export_build_payload": None,
        "built_export": None,
        "safety_policy": _safety_policy(),
    }


def _export_readiness_message(queue: Dict[str, Any]) -> str:
    items = queue.get("items") if isinstance(queue.get("items"), list) else []
    source_summaries = queue.get("source_summaries") if isinstance(queue.get("source_summaries"), dict) else {}
    prompt_pairs = source_summaries.get("prompt_pairs") if isinstance(source_summaries.get("prompt_pairs"), dict) else {}
    gate_counts = prompt_pairs.get("preflight_gate_counts") if isinstance(prompt_pairs.get("preflight_gate_counts"), dict) else {}
    approved_count = int(gate_counts.get("approved") or 0)
    candidate_count = int(gate_counts.get("candidate") or 0)
    if not items:
        return (
            "Export readiness looks clear from the current bottleneck queue. "
            f"I see {approved_count} approved prompt-pair item(s) and {candidate_count} candidate item(s)."
        )
    top = items[0] if isinstance(items[0], dict) else {}
    top_label = _string(top.get("area_label"), "the top blocker")
    top_summary = _string(top.get("summary"), "There is still review work blocking downstream readiness.")
    next_action = _string(top.get("next_action"))
    tail = f" Next: {next_action}" if next_action else ""
    return (
        f"Export readiness has {len(items)} active bottleneck area(s). "
        f"The top blocker is {top_label}: {top_summary}{tail}"
    )


def _build_export_readiness_turn(
    *,
    session: Session,
    request: ChatTurnRequest,
    app_settings: Settings,
    task_selection: Dict[str, Any],
) -> Dict[str, Any]:
    chat_session = _resolve_chat_session(
        session=session,
        request=request,
        task=None,
        app_settings=app_settings,
    )
    queue = compile_downstream_bottleneck_queue(
        session=session,
        app_settings=app_settings,
        scope="family_private",
        limit=5,
    )
    work_summary = {
        "summary_type": "export_readiness",
        "queue_type": queue.get("queue_type"),
        "scope": queue.get("scope"),
        "item_count": queue.get("item_count"),
        "ordered_area_keys": queue.get("ordered_area_keys") or [],
        "source_summaries": queue.get("source_summaries") or {},
        "top_item": (queue.get("items") or [None])[0] if isinstance(queue.get("items"), list) and queue.get("items") else None,
        "does_not_mutate_state": queue.get("does_not_mutate_state") is True,
        "no_live_model_call": queue.get("no_live_model_call") is True,
    }
    task_selection = {
        **task_selection,
        "selection_reason": "export_readiness_summary",
        "export_readiness": {
            "item_count": work_summary["item_count"],
            "ordered_area_keys": work_summary["ordered_area_keys"],
        },
    }
    context_packet = {
        "active_task": None,
        "request": {"mode": request.mode, "user_id": request.user_id},
        "status": "export_readiness_summary",
        "task_selection": task_selection,
        "work_summary": work_summary,
    }
    context_packet_hash = _json_hash(context_packet)
    _record_chat_turn(
        session=session,
        chat_session=chat_session,
        task=None,
        role="user",
        content=request.message,
        context_packet_hash=context_packet_hash,
        metadata={"mode": request.mode, "task_selection": task_selection},
    )
    assistant_message = _export_readiness_message(queue)
    assistant_turn = _record_chat_turn(
        session=session,
        chat_session=chat_session,
        task=None,
        role="assistant",
        content=assistant_message,
        model_name=app_settings.text_generation_model,
        context_packet_hash=context_packet_hash,
        metadata={
            "status": "export_readiness_summary",
            "task_selection": task_selection,
            "work_summary": work_summary,
            "live_model_call_used": False,
        },
    )
    chat_session.active_task_id = None
    chat_session.updated_at = datetime.now(timezone.utc)
    chat_session.metadata_json = _updated_session_metadata(
        current_metadata=chat_session.metadata_json,
        task=None,
        status="export_readiness_summary",
        context_packet_hash=context_packet_hash,
        task_selection=task_selection,
    )
    session.add(chat_session)
    session.commit()
    return {
        "status": "export_readiness_summary",
        "session_id": chat_session.id,
        "turn_id": assistant_turn.id,
        "context_packet_hash": context_packet_hash,
        "assistant_message": assistant_message,
        "next_question": None,
        "model_name": app_settings.text_generation_model,
        "reasoning_effort": _chat_reasoning_effort(app_settings),
        "model_ready": live_text_generation_ready(app_settings),
        "live_model_call_used": False,
        "active_task": {},
        "task_selection": task_selection,
        "work_surface": {"kind": "export_readiness"},
        "work_summary": work_summary,
        "actions": [],
        "field_updates": {},
        "draft_decisions": {},
        "draft": None,
        "ready_to_submit": False,
        "submit_payload": None,
        "safety_policy": _safety_policy(),
    }


def _persist_chat_actions(
    *,
    session: Session,
    chat_session: ChatSession,
    task: Task,
    assistant_turn: ChatTurn,
    actions: List[Dict[str, Any]],
    field_updates: Dict[str, Any],
    field_diffs: List[Dict[str, Any]],
    draft_patch: List[Dict[str, Any]],
    patch_result: Dict[str, Any],
    saved_draft: Optional[TaskDraft],
    before_draft: Optional[Dict[str, Any]],
    submit_payload: Optional[Dict[str, Any]],
    next_question: Optional[str],
    context_packet_hash: str,
    apply_updates: bool,
    confirm_action_id: Optional[str] = None,
) -> List[Dict[str, Any]]:
    response_actions: List[Dict[str, Any]] = []
    now = datetime.now(timezone.utc)
    for action in actions:
        action_type = _string(action.get("type"))
        requires_confirmation = bool(action.get("requires_confirmation"))
        status = "pending_confirmation" if requires_confirmation else "recorded"
        executed_at: Optional[datetime] = None
        if action_type in DRAFT_UPDATE_CHAT_ACTIONS:
            if field_updates:
                status = "executed" if apply_updates and saved_draft else "previewed"
                executed_at = now if status == "executed" else None
        elif action_type == "ask_question":
            status = "recorded"
            executed_at = now
        elif action_type == "open_task":
            status = "executed"
            executed_at = now

        proposed_payload = _action_payload_for_record(
            action=action,
            task=task,
            field_updates=field_updates,
            field_diffs=field_diffs,
            draft_patch=draft_patch,
            patch_result=patch_result,
            submit_payload=submit_payload,
            next_question=next_question,
            context_packet_hash=context_packet_hash,
        )
        existing_action = session.get(ChatAction, confirm_action_id) if action_type == "submit_task" and confirm_action_id else None
        if existing_action and existing_action.action_type == "submit_task" and existing_action.session_id == chat_session.id:
            chat_action = existing_action
            existing_metadata = chat_action.metadata_json if isinstance(chat_action.metadata_json, dict) else {}
            preview_turn_id = _string(existing_metadata.get("preview_turn_id")) or chat_action.turn_id
            chat_action.turn_id = assistant_turn.id
            chat_action.task_id = task.id
            chat_action.status = "pending_confirmation"
            chat_action.proposed_payload_json = proposed_payload
            chat_action.validated_payload_json = proposed_payload
            chat_action.requires_confirmation = True
            chat_action.metadata_json = {
                **existing_metadata,
                "label": action.get("label"),
                "preview_turn_id": preview_turn_id,
                "confirmed_from_turn_id": assistant_turn.id,
            }
        else:
            chat_action = ChatAction(
                session_id=chat_session.id,
                turn_id=assistant_turn.id,
                task_id=task.id,
                action_type=action_type,
                status=status,
                proposed_payload_json=proposed_payload,
                validated_payload_json=proposed_payload,
                requires_confirmation=requires_confirmation,
                executed_at=executed_at,
                metadata_json={"source": "chat_operator", "label": action.get("label"), "preview_turn_id": assistant_turn.id},
            )
        session.add(chat_action)
        session.flush()
        if action_type in DRAFT_UPDATE_CHAT_ACTIONS and field_updates:
            session.add(
                ChatActionResult(
                    action_id=chat_action.id,
                    object_type="task_draft",
                    object_id=saved_draft.id if saved_draft else None,
                    before_json=before_draft or {},
                    after_json={
                        **(_draft_to_dict(saved_draft) or {"decisions": field_updates}),
                        **({"patch_result": patch_result} if patch_result else {}),
                    },
                )
            )
        response_actions.append({**action, "id": chat_action.id, "status": chat_action.status})
    return response_actions


def _chat_source_refs_for_task(task: Optional[Task]) -> Dict[str, Any]:
    if task is None:
        return {}
    payload = task.input_payload if isinstance(task.input_payload, dict) else {}
    refs: Dict[str, Any] = {
        "target_type": task.target_type,
        "target_id": task.target_id,
        "task_human_id": task.human_id,
    }
    for key in (
        "asset_id",
        "source_photo_id",
        "grounding_asset_id",
        "source_segment_id",
        "source_document_id",
        "source_chunk_id",
        "prompt_pair_id",
        "context_pack_id",
    ):
        value = payload.get(key)
        if value:
            refs[key] = value
    return refs


def _associated_object_ids_for_task(task: Task) -> Dict[str, List[str]]:
    payload = task.input_payload if isinstance(task.input_payload, dict) else {}
    asset_ids: List[str] = []
    source_excerpt_ids: List[str] = []
    prompt_response_ids: List[str] = []
    context_pack_ids: List[str] = []

    if task.target_type == "asset":
        asset_ids.append(task.target_id)
    if task.target_type in {"segment", "source_excerpt", "source_chunk"}:
        source_excerpt_ids.append(task.target_id)
    if task.target_type in {"prompt_pair", "sft_candidate", "dpo_pair"}:
        prompt_response_ids.append(task.target_id)

    for key in ("asset_id", "source_photo_id", "grounding_asset_id"):
        value = _string(payload.get(key))
        if value:
            asset_ids.append(value)
    for key in ("source_segment_id", "source_excerpt_id", "source_document_id", "source_chunk_id"):
        value = _string(payload.get(key))
        if value:
            source_excerpt_ids.append(value)
    for key in ("prompt_pair_id", "sft_candidate_id", "dpo_pair_id"):
        value = _string(payload.get(key))
        if value:
            prompt_response_ids.append(value)
    value = _string(payload.get("context_pack_id"))
    if value:
        context_pack_ids.append(value)

    return {
        "asset_ids": _unique_strings(asset_ids),
        "source_excerpt_ids": _unique_strings(source_excerpt_ids),
        "prompt_response_ids": _unique_strings(prompt_response_ids),
        "context_pack_ids": _unique_strings(context_pack_ids),
    }


def _submit_chat_provenance(
    *,
    session: Session,
    chat_action: ChatAction,
    response: Dict[str, Any],
    confirmed_at: datetime,
) -> Dict[str, Any]:
    payload = chat_action.validated_payload_json if isinstance(chat_action.validated_payload_json, dict) else {}
    submit_payload = payload.get("submit_payload") if isinstance(payload.get("submit_payload"), dict) else {}
    task = session.get(Task, chat_action.task_id) if chat_action.task_id else None
    base_decisions = task.input_payload if task and isinstance(task.input_payload, dict) else {}
    preview_decisions = submit_payload.get("decisions") if isinstance(submit_payload.get("decisions"), dict) else {}
    changed_decisions = {
        key: value
        for key, value in preview_decisions.items()
        if base_decisions.get(key) != value
    }
    metadata = chat_action.metadata_json if isinstance(chat_action.metadata_json, dict) else {}
    return {
        "source": "chat_operator",
        "chat_session_id": chat_action.session_id,
        "preview_turn_id": _string(metadata.get("preview_turn_id")) or chat_action.turn_id,
        "confirmation_turn_id": _string(metadata.get("confirmed_from_turn_id")) or chat_action.turn_id,
        "chat_action_id": chat_action.id,
        "task_id": chat_action.task_id,
        "task_human_id": task.human_id if task else None,
        "model_name": _string(response.get("model_name")),
        "context_packet_hash": _string(payload.get("context_packet_hash")),
        "confirmed_by_user_at": confirmed_at.isoformat(),
        "source_refs": _chat_source_refs_for_task(task),
        "field_diffs": payload.get("field_diffs") if isinstance(payload.get("field_diffs"), list) else [],
        "decision_diffs": _field_diffs(base_decisions, changed_decisions, task=task),
        "field_provenance": _field_provenance_for_chat_submit(task=task, submitted_decisions=preview_decisions),
    }


def _field_provenance_for_chat_submit(*, task: Optional[Task], submitted_decisions: Dict[str, Any]) -> Dict[str, Dict[str, str]]:
    if task is None:
        return {}
    kind = _task_kind(task)
    provenance: Dict[str, Dict[str, str]] = {}
    for field in submitted_decisions:
        if kind == "photo_review":
            if field in {"adam_context_note", "retrieval_cues", "event_summary", "memory_caption", "emotional_salience"}:
                source = "adam_provided_memory"
            elif field in {"open_questions", "uncertainties", "uncertainty_notes"}:
                source = "adam_confirmed_uncertainty"
            elif field in {"machine_guess_people", "machine_guess_objects", "machine_tags", "visual_summary"}:
                source = "model_visual_inference"
            elif field in {"asset_id", "source_photo_id", "source_photo_title", "asset_title"}:
                source = "database_derived_association"
            else:
                source = "adam_confirmed_fact"
        elif kind == "prompt_response_review":
            if field == "prompt":
                source = "source_prompt"
            elif field in {"context", "failure_modes", "operator_candidate_triage_intent"}:
                source = "adam_critique"
            elif field in {"content", "chosen", "rejected"}:
                source = "final_approval"
            elif field == "export_flags":
                source = "backend_export_policy"
            else:
                source = "assistant_rewrite_or_review_metadata"
        elif kind == "source_review":
            source = "adam_source_review"
        else:
            source = "adam_review"
        provenance[field] = {"source": source, "task_kind": kind}
    return provenance


def _next_ready_task_for_batch(*, session: Session, submitted_task: Task) -> Optional[Task]:
    submitted_route = _route_for_task(submitted_task)
    if not submitted_route:
        return None
    ready_tasks = session.exec(
        select(Task)
        .where(Task.status == "ready")
        .where(Task.id != submitted_task.id)
        .order_by(Task.priority.desc(), Task.created_at.asc())
    ).all()
    route_matches = [task for task in ready_tasks if _task_matches_route(task, submitted_route)]
    if not route_matches:
        return None
    same_queue = [task for task in route_matches if task.queue == submitted_task.queue]
    return (same_queue or route_matches)[0]


def _task_ids_from_submit_outputs(annotation: Any) -> List[str]:
    outputs = annotation.creates_or_updates if isinstance(getattr(annotation, "creates_or_updates", None), dict) else {}
    ids: List[str] = []
    for key in ("make_gold_task_ids", "photo_prompt_pair_task_ids"):
        values = outputs.get(key)
        if isinstance(values, list):
            ids.extend(value for value in values if isinstance(value, str) and value)
    photo_generation = outputs.get("photo_prompt_pair_generation")
    if isinstance(photo_generation, dict):
        values = photo_generation.get("created_task_ids")
        if isinstance(values, list):
            ids.extend(value for value in values if isinstance(value, str) and value)
        for candidate in photo_generation.get("candidates", []) if isinstance(photo_generation.get("candidates"), list) else []:
            if not isinstance(candidate, dict):
                continue
            for key in ("created_task_id", "existing_task_id"):
                value = candidate.get(key)
                if isinstance(value, str) and value:
                    ids.append(value)
    return _unique_strings(ids)


def _next_downstream_candidate_task(*, session: Session, annotation: Any) -> Optional[Task]:
    candidates = [
        task
        for task_id in _task_ids_from_submit_outputs(annotation)
        for task in [session.get(Task, task_id)]
        if task is not None and task.status == "ready"
    ]
    if not candidates:
        return None
    mode_counts: Dict[str, int] = {}
    for task in candidates:
        mode = _artifact_mode(task, task.input_payload if isinstance(task.input_payload, dict) else {})
        mode_counts[mode] = mode_counts.get(mode, 0) + 1
    min_mode_count = min(mode_counts.values()) if mode_counts else 0

    def priority(task: Task) -> tuple[int, int, float]:
        payload = task.input_payload if isinstance(task.input_payload, dict) else {}
        metadata = payload.get("pair_generation_metadata") if isinstance(payload.get("pair_generation_metadata"), dict) else {}
        evidence_gate = metadata.get("evidence_gate") if isinstance(metadata.get("evidence_gate"), dict) else {}
        refs = payload.get("source_evidence_refs") if isinstance(payload.get("source_evidence_refs"), list) else []
        ranked_packet = payload.get("ranked_evidence_packet") if isinstance(payload.get("ranked_evidence_packet"), dict) else {}
        mode = _artifact_mode(task, payload)
        score = 0
        if evidence_gate.get("passed") is True:
            score += 1000
        if payload.get("source_evidence_status") == "evidence_linked":
            score += 500
        score += min(len(refs), 10) * 20
        score += min(_optional_int(ranked_packet.get("record_count")) or 0, 10) * 5
        if mode_counts.get(mode, 0) == min_mode_count:
            score += 25
        return (score, task.priority, -task.created_at.timestamp())

    return max(candidates, key=priority)


def _batch_continuation_payload(*, submitted_task: Task, next_task: Optional[Task], reason: str = "opened_next_ready_same_route_task") -> Dict[str, Any]:
    submitted_route = _route_for_task(submitted_task)
    payload: Dict[str, Any] = {
        "type": "downstream_candidate_continuation" if reason == "opened_downstream_candidate_task" else "same_route_batch_continuation",
        "route": submitted_route,
        "route_label": _route_label(submitted_route),
        "submitted_task_id": submitted_task.id,
        "submitted_task_human_id": submitted_task.human_id,
        "submitted_task_status": submitted_task.status,
    }
    if next_task is None:
        return {
            **payload,
            "continued": False,
            "reason": "no_ready_same_route_task",
            "next_task_id": None,
        }
    return {
        **payload,
        "continued": True,
        "reason": reason,
        "next_task_id": next_task.id,
        "next_task_human_id": next_task.human_id,
        "next_task_route": _route_for_task(next_task),
        "next_task": _task_summary(next_task),
        "selection_policy": "evidence_quality_then_artifact_mode_balance" if reason == "opened_downstream_candidate_task" else "same_route_priority_then_created_at",
    }


def mark_chat_submit_action_executed(*, session: Session, response: Dict[str, Any], annotation: Any) -> Dict[str, Any]:
    actions = response.get("actions") if isinstance(response.get("actions"), list) else []
    submit_action_id = None
    for action in actions:
        if isinstance(action, dict) and action.get("type") == "submit_task" and isinstance(action.get("id"), str):
            submit_action_id = action["id"]
            break
    if not submit_action_id:
        return response

    chat_action = session.get(ChatAction, submit_action_id)
    if chat_action is None:
        return response
    now = datetime.now(timezone.utc)
    before_payload = chat_action.validated_payload_json if isinstance(chat_action.validated_payload_json, dict) else {}
    task = session.get(Task, chat_action.task_id) if chat_action.task_id else None
    chat_action.status = "executed"
    chat_action.requires_confirmation = False
    chat_action.confirmed_by_user_at = now
    chat_action.executed_at = now
    provenance = _submit_chat_provenance(
        session=session,
        chat_action=chat_action,
        response=response,
        confirmed_at=now,
    )
    annotation.decisions = {
        **(annotation.decisions if isinstance(annotation.decisions, dict) else {}),
        "chat_provenance": provenance,
    }
    annotation.creates_or_updates = {
        **(annotation.creates_or_updates if isinstance(annotation.creates_or_updates, dict) else {}),
        "chat_provenance": provenance,
    }
    session.add(chat_action)
    session.add(annotation)
    session.add(
        ChatActionResult(
            action_id=chat_action.id,
            object_type="annotation",
            object_id=annotation.id,
            before_json=before_payload,
            after_json=annotation.model_dump(mode="json"),
        )
    )
    downstream_task = _next_downstream_candidate_task(session=session, annotation=annotation)
    next_task = downstream_task or (_next_ready_task_for_batch(session=session, submitted_task=task) if task is not None else None)
    continuation_reason = "opened_downstream_candidate_task" if downstream_task is not None else "opened_next_ready_same_route_task"
    batch_continuation = _batch_continuation_payload(submitted_task=task, next_task=next_task, reason=continuation_reason) if task is not None else None
    continuation_action: Optional[ChatAction] = None
    chat_session = session.get(ChatSession, chat_action.session_id)
    if next_task is not None:
        context_packet_hash = _string(before_payload.get("context_packet_hash"))
        continuation_action = ChatAction(
            session_id=chat_action.session_id,
            turn_id=chat_action.turn_id,
            task_id=next_task.id,
            action_type="open_task",
            status="executed",
            proposed_payload_json={
                "task_id": task.id if task else "",
                "target_task_id": next_task.id,
                "label": "Open next ticket in batch",
                "context_packet_hash": context_packet_hash,
                "batch_continuation": batch_continuation,
            },
            validated_payload_json={
                "task_id": task.id if task else "",
                "target_task_id": next_task.id,
                "label": "Open next ticket in batch",
                "context_packet_hash": context_packet_hash,
                "batch_continuation": batch_continuation,
            },
            requires_confirmation=False,
            executed_at=now,
            metadata_json={"source": "chat_operator", "label": "Open next ticket in batch", "preview_turn_id": chat_action.turn_id},
        )
        session.add(continuation_action)
        session.flush()
        session.add(
            ChatActionResult(
                action_id=continuation_action.id,
                object_type="task",
                object_id=next_task.id,
                before_json={"submitted_task": task.model_dump(mode="json") if task else {}},
                after_json={"active_task": next_task.model_dump(mode="json"), "batch_continuation": batch_continuation},
            )
        )
    if chat_session is not None:
        active_task = next_task or task
        chat_session.active_task_id = active_task.id if active_task else None
        chat_session.updated_at = now
        task_selection = response.get("task_selection") if isinstance(response.get("task_selection"), dict) else {}
        if next_task is not None:
            task_selection = {
                **task_selection,
                "selection_reason": "batch_continuation_after_submit",
                "previous_task_id": task.id if task else None,
                "previous_task_human_id": task.human_id if task else None,
                "selected_task_id": next_task.id,
                "selected_task_human_id": next_task.human_id,
                "selected_route": _route_for_task(next_task),
            }
        chat_session.metadata_json = _updated_session_metadata(
            current_metadata=chat_session.metadata_json,
            task=active_task,
            status="submit_executed",
            context_packet_hash=_string(before_payload.get("context_packet_hash")),
            task_selection=task_selection,
            task_kind=_task_kind(active_task) if active_task else "",
        )
        if batch_continuation:
            chat_session.metadata_json = {
                **(chat_session.metadata_json if isinstance(chat_session.metadata_json, dict) else {}),
                "batch_continuation": batch_continuation,
            }
        session.add(chat_session)
    _log_chat_event(
        "action_executed",
        session_id=chat_action.session_id,
        task_id=chat_action.task_id,
        action_id=chat_action.id,
        action_type=chat_action.action_type,
        object_type="annotation",
        object_id=annotation.id,
    )
    session.commit()
    updated_actions = []
    for action in actions:
        if isinstance(action, dict) and action.get("id") == chat_action.id:
            updated_actions.append(
                {
                    **action,
                    "label": "Submitted ticket",
                    "requires_confirmation": False,
                    "status": "executed",
                }
        )
        else:
            updated_actions.append(action)
    if continuation_action is not None and next_task is not None:
        updated_actions.append(
            {
                "type": "open_task",
                "label": "Opened next ticket in batch",
                "requires_confirmation": False,
                "status": "executed",
                "task_id": next_task.id,
                "id": continuation_action.id,
            }
        )
    response_update: Dict[str, Any] = {
        **response,
        "actions": updated_actions,
        "ready_to_submit": False,
        "submit_payload": None,
    }
    if batch_continuation:
        response_update["batch_continuation"] = batch_continuation
    if next_task is not None:
        next_draft = _task_draft(session, next_task.id)
        next_decisions = next_draft.decisions if next_draft and isinstance(next_draft.decisions, dict) else {}
        merged_next_decisions = _normalize_prompt_pair_decision_state(next_task, {**(next_task.input_payload or {}), **next_decisions})
        response_update = {
            **response_update,
            "active_task": _task_summary(next_task),
            "task_selection": {
                **(response.get("task_selection") if isinstance(response.get("task_selection"), dict) else {}),
                "selection_reason": "batch_continuation_after_submit",
                "previous_task_id": task.id if task else None,
                "previous_task_human_id": task.human_id if task else None,
                "selected_task_id": next_task.id,
                "selected_task_human_id": next_task.human_id,
                "selected_route": _route_for_task(next_task),
            },
            "work_surface": _task_work_surface(next_task, merged_next_decisions),
            "draft_decisions": merged_next_decisions,
            "draft": _draft_to_dict(next_draft),
            "next_question": _fallback_next_question(next_task, merged_next_decisions),
        }
    return response_update


def chat_submit_action_stale_reason(*, session: Session, pending_action: ChatAction, user_id: str) -> Optional[str]:
    payload = pending_action.validated_payload_json if isinstance(pending_action.validated_payload_json, dict) else {}
    submit_payload = payload.get("submit_payload") if isinstance(payload.get("submit_payload"), dict) else None
    if submit_payload is None:
        return "Pending submit action has no validated submit payload."
    task_id = _string(submit_payload.get("task_id")) or pending_action.task_id
    task = session.get(Task, task_id) if task_id else None
    if task is None:
        return "The task for this submit preview no longer exists."
    if task.status != "ready":
        return "The task is no longer ready for submit."
    draft = _task_draft(session, task.id, user_id)
    draft_decisions = _normalize_prompt_pair_decision_state(
        task,
        draft.decisions if draft and isinstance(draft.decisions, dict) else {},
    )
    current_decisions = _normalize_prompt_pair_decision_state(task, {**(task.input_payload or {}), **draft_decisions})
    current_notes = draft.notes if draft else None
    preview_decisions = submit_payload.get("decisions") if isinstance(submit_payload.get("decisions"), dict) else {}
    preview_notes = submit_payload.get("notes") if isinstance(submit_payload.get("notes"), str) else None
    if preview_decisions != current_decisions or preview_notes != current_notes:
        return "The task draft changed after this submit preview was created."
    return None


def mark_chat_action_stale(*, session: Session, pending_action: ChatAction, reason: str) -> None:
    pending_action.status = "stale"
    pending_action.requires_confirmation = False
    pending_action.error_message = reason
    pending_action.metadata_json = {
        **(pending_action.metadata_json if isinstance(pending_action.metadata_json, dict) else {}),
        "stale_reason": reason,
        "stale_at": datetime.now(timezone.utc).isoformat(),
    }
    session.add(pending_action)
    _log_chat_event(
        "action_failed",
        session_id=pending_action.session_id,
        task_id=pending_action.task_id,
        action_id=pending_action.id,
        action_type=pending_action.action_type,
        reason=reason,
    )
    session.commit()


def mark_chat_export_build_action_executed(*, session: Session, response: Dict[str, Any], dataset_export: Any) -> Dict[str, Any]:
    actions = response.get("actions") if isinstance(response.get("actions"), list) else []
    export_action_id = None
    for action in actions:
        if isinstance(action, dict) and action.get("type") == "build_dataset_export" and isinstance(action.get("id"), str):
            export_action_id = action["id"]
            break
    if not export_action_id:
        return response

    chat_action = session.get(ChatAction, export_action_id)
    if chat_action is None:
        return response
    now = datetime.now(timezone.utc)
    before_payload = chat_action.validated_payload_json if isinstance(chat_action.validated_payload_json, dict) else {}
    chat_action.status = "executed"
    chat_action.requires_confirmation = False
    chat_action.confirmed_by_user_at = now
    chat_action.executed_at = now
    session.add(chat_action)
    session.add(
        ChatActionResult(
            action_id=chat_action.id,
            object_type="dataset_export",
            object_id=dataset_export.id,
            before_json=before_payload,
            after_json=dataset_export.model_dump(mode="json"),
        )
    )
    _log_chat_event(
        "action_executed",
        session_id=chat_action.session_id,
        task_id=chat_action.task_id,
        action_id=chat_action.id,
        action_type=chat_action.action_type,
        object_type="dataset_export",
        object_id=dataset_export.id,
    )
    session.commit()
    updated_actions = []
    for action in actions:
        if isinstance(action, dict) and action.get("id") == chat_action.id:
            updated_actions.append(
                {
                    **action,
                    "label": "Built export",
                    "requires_confirmation": False,
                    "status": "executed",
                }
            )
        else:
            updated_actions.append(action)
    return {
        **response,
        "actions": updated_actions,
        "built_export": dataset_export.model_dump(mode="json"),
    }


def chat_review_task_action_stale_reason(*, session: Session, pending_action: ChatAction) -> Optional[str]:
    payload = pending_action.validated_payload_json if isinstance(pending_action.validated_payload_json, dict) else {}
    review_payload = payload.get("review_task_creation_payload") if isinstance(payload.get("review_task_creation_payload"), dict) else None
    if review_payload is None:
        return "Pending review-task action has no validated review task payload."
    review_task_type = _string(review_payload.get("review_task_type"), "photo_context")
    if review_task_type not in {"photo_context", "source_review"}:
        return f"Review task type '{review_task_type}' is not supported yet."
    task_id = _string(review_payload.get("task_id"))
    if task_id:
        task = session.get(Task, task_id)
        if task is None:
            return "The review task to open no longer exists."
        if task.status != "ready":
            return "The review task to open is no longer ready."
        return None
    if review_task_type == "source_review":
        source_segment_id = _string(review_payload.get("source_segment_id"))
        source_asset_id = _string(review_payload.get("source_asset_id")) or _string(review_payload.get("asset_id"))
        if not source_segment_id and not source_asset_id:
            return "Pending source review-task action must include a source_segment_id or source_asset_id."
        if source_segment_id:
            from app.models import Segment

            segment = session.get(Segment, source_segment_id)
            if segment is None:
                return "The source segment no longer exists."
        return None
    asset_id = _string(review_payload.get("asset_id")) or _string(review_payload.get("source_photo_id"))
    group_key = _string(review_payload.get("group_key"))
    if not asset_id and not group_key:
        return "Pending review-task action must include an asset_id, group_key, or task_id."
    if asset_id:
        from app.models import Asset

        asset = session.get(Asset, asset_id)
        if asset is None:
            return "The source photo asset no longer exists."
        if asset.processing_status != "image_preview_ready":
            return "The source photo no longer has a ready preview."
    return None


def _creation_value(created_task: Any, key: str, fallback: Any = None) -> Any:
    if isinstance(created_task, dict):
        return created_task.get(key, fallback)
    return getattr(created_task, key, fallback)


def _creation_dump(created_task: Any) -> Dict[str, Any]:
    if isinstance(created_task, dict):
        return created_task
    dump = getattr(created_task, "model_dump", None)
    if callable(dump):
        return dump(mode="json")
    return {
        "created": bool(_creation_value(created_task, "created")),
        "task_id": _creation_value(created_task, "task_id"),
        "task_human_id": _creation_value(created_task, "task_human_id"),
    }


def mark_chat_review_task_action_executed(*, session: Session, response: Dict[str, Any], created_task: Any) -> Dict[str, Any]:
    actions = response.get("actions") if isinstance(response.get("actions"), list) else []
    review_action_id = None
    for action in actions:
        if isinstance(action, dict) and action.get("type") == "create_or_open_review_task" and isinstance(action.get("id"), str):
            review_action_id = action["id"]
            break
    if not review_action_id:
        return response

    chat_action = session.get(ChatAction, review_action_id)
    if chat_action is None:
        return response
    created_task_id = _string(_creation_value(created_task, "task_id"))
    task = session.get(Task, created_task_id)
    if task is None:
        return response
    now = datetime.now(timezone.utc)
    before_payload = chat_action.validated_payload_json if isinstance(chat_action.validated_payload_json, dict) else {}
    chat_action.status = "executed"
    chat_action.task_id = task.id
    chat_action.requires_confirmation = False
    chat_action.confirmed_by_user_at = now
    chat_action.executed_at = now
    session.add(chat_action)
    session.add(
        ChatActionResult(
            action_id=chat_action.id,
            object_type="task",
            object_id=task.id,
            before_json=before_payload,
            after_json={
                "task": task.model_dump(mode="json"),
                "review_task_creation": _creation_dump(created_task),
            },
        )
    )
    chat_session = session.get(ChatSession, chat_action.session_id)
    if chat_session is not None:
        task_selection = response.get("task_selection") if isinstance(response.get("task_selection"), dict) else {}
        task_selection = {
            **task_selection,
            "selection_reason": "confirmed_review_task_creation",
            "selected_task_id": task.id,
            "selected_task_human_id": task.human_id,
            "review_task_created": bool(_creation_value(created_task, "created")),
        }
        chat_session.active_task_id = task.id
        chat_session.updated_at = now
        chat_session.metadata_json = _updated_session_metadata(
            current_metadata=chat_session.metadata_json,
            task=task,
            status="review_task_creation_executed",
            context_packet_hash=_string(response.get("context_packet_hash")),
            task_selection=task_selection,
            task_kind=_task_kind(task),
        )
        session.add(chat_session)
    _log_chat_event(
        "action_executed",
        session_id=chat_action.session_id,
        task_id=task.id,
        action_id=chat_action.id,
        action_type=chat_action.action_type,
        object_type="task",
        object_id=task.id,
    )
    session.commit()
    updated_actions = []
    for action in actions:
        if isinstance(action, dict) and action.get("id") == chat_action.id:
            updated_actions.append(
                {
                    **action,
                    "label": "Created review task" if _creation_value(created_task, "created") else "Opened existing review task",
                    "requires_confirmation": False,
                    "status": "executed",
                    "task_id": task.id,
                }
            )
        else:
            updated_actions.append(action)
    return {
        **response,
        "status": "review_task_creation_executed",
        "active_task": _task_summary(task),
        "task_selection": {
            **(response.get("task_selection") if isinstance(response.get("task_selection"), dict) else {}),
            "selection_reason": "confirmed_review_task_creation",
            "selected_task_id": task.id,
            "selected_task_human_id": task.human_id,
            "review_task_created": bool(_creation_value(created_task, "created")),
        },
        "work_surface": _task_work_surface(task, task.input_payload if isinstance(task.input_payload, dict) else {}),
        "actions": updated_actions,
        "created_review_task": _creation_dump(created_task),
    }


def chat_export_build_action_stale_reason(*, session: Session, pending_action: ChatAction) -> Optional[str]:
    payload = pending_action.validated_payload_json if isinstance(pending_action.validated_payload_json, dict) else {}
    export_build_payload = payload.get("export_build_payload") if isinstance(payload.get("export_build_payload"), dict) else None
    if export_build_payload is None:
        return "Pending export build action has no validated build payload."
    export_type = _string(export_build_payload.get("export_type"))
    if export_type not in {"sft", "dpo"}:
        return "Pending export build action has an unsupported export type."
    current_preview = _export_preview_for_type(session, export_type, include_candidates=False)
    current_hash = _export_preview_hash(current_preview)
    preview_hash = _string(export_build_payload.get("dry_run_hash"))
    if preview_hash and preview_hash != current_hash:
        return "The approved export dry run changed after this build preview was created."
    if int(export_build_payload.get("included_count") or 0) != int(current_preview.get("included_count") or 0):
        return "The approved export included row count changed after this build preview was created."
    if int(export_build_payload.get("excluded_count") or 0) != int(current_preview.get("excluded_count") or 0):
        return "The approved export exclusion count changed after this build preview was created."
    return None


def dismiss_pending_chat_action(*, session: Session, request: ChatTurnRequest, app_settings: Settings) -> Dict[str, Any]:
    pending_action = session.get(ChatAction, request.confirm_action_id) if request.confirm_action_id else None
    if (
        pending_action is None
        or pending_action.session_id != request.session_id
        or pending_action.status != "pending_confirmation"
        or not pending_action.requires_confirmation
    ):
        raise ValueError("Chat action dismissal is stale or invalid.")
    chat_session = session.get(ChatSession, pending_action.session_id)
    if chat_session is None:
        raise ValueError("Chat session not found for pending action.")

    task = session.get(Task, pending_action.task_id) if pending_action.task_id else None
    metadata = pending_action.metadata_json if isinstance(pending_action.metadata_json, dict) else {}
    action_label = _string(metadata.get("label"), pending_action.action_type.replace("_", " "))
    payload = pending_action.validated_payload_json if isinstance(pending_action.validated_payload_json, dict) else {}
    task_selection = {
        "requested_route": "dismiss_action",
        "requested_route_label": "dismiss action",
        "selection_reason": "pending_action_dismissed",
        "selected_task_id": task.id if task else None,
        "dismissed_action_id": pending_action.id,
        "dismissed_action_type": pending_action.action_type,
    }
    work_summary = {
        "summary_type": "action_dismissed",
        "action_type": pending_action.action_type,
        "action_label": action_label,
        "dismissed_action_id": pending_action.id,
        "does_not_mutate_state": True,
    }
    draft = _task_draft(session, task.id, chat_session.user_id) if task else None
    work_surface = (
        _task_work_surface(
            task,
            {
                **(task.input_payload if task and isinstance(task.input_payload, dict) else {}),
                **(draft.decisions if draft and isinstance(draft.decisions, dict) else {}),
            },
        )
        if task
        else {}
    )
    context_packet = {
        "active_task": _task_summary(task) if task else None,
        "work_surface": work_surface,
        "request": {
            "mode": request.mode,
            "user_id": request.user_id,
            "dismiss_action": request.dismiss_action,
            "confirm_action_id": request.confirm_action_id,
        },
        "status": "action_dismissed",
        "task_selection": task_selection,
        "work_summary": work_summary,
        "dismissed_action_payload": payload,
    }
    context_packet_hash = _json_hash(context_packet)
    _record_chat_turn(
        session=session,
        chat_session=chat_session,
        task=task,
        role="user",
        content=request.message or "dismiss",
        context_packet_hash=context_packet_hash,
        metadata={"mode": request.mode, "dismiss_action": True, "confirm_action_id": request.confirm_action_id},
    )
    assistant_message = f"Dismissed {action_label}. I did not apply that action."
    assistant_turn = _record_chat_turn(
        session=session,
        chat_session=chat_session,
        task=task,
        role="assistant",
        content=assistant_message,
        model_name=app_settings.text_generation_model,
        context_packet_hash=context_packet_hash,
        metadata={
            "status": "action_dismissed",
            "task_selection": task_selection,
            "work_surface": work_surface,
            "work_summary": work_summary,
            "live_model_call_used": False,
        },
    )
    now = datetime.now(timezone.utc)
    pending_action.turn_id = assistant_turn.id
    pending_action.status = "dismissed"
    pending_action.requires_confirmation = False
    pending_action.metadata_json = {
        **metadata,
        "dismissed_by_user_at": now.isoformat(),
        "dismissed_from_turn_id": assistant_turn.id,
    }
    session.add(pending_action)
    session.add(
        ChatActionResult(
            action_id=pending_action.id,
            object_type="chat_action_dismissal",
            object_id=pending_action.id,
            before_json=payload,
            after_json={
                "status": "dismissed",
                "dismissed_action_id": pending_action.id,
                "dismissed_action_type": pending_action.action_type,
                "dismissed_by_user_at": now.isoformat(),
                "reason": request.message,
            },
        )
    )
    _log_chat_event(
        "action_dismissed",
        session_id=pending_action.session_id,
        task_id=pending_action.task_id,
        action_id=pending_action.id,
        action_type=pending_action.action_type,
    )
    chat_session.active_task_id = task.id if task else None
    chat_session.updated_at = now
    chat_session.metadata_json = _updated_session_metadata(
        current_metadata=chat_session.metadata_json,
        task=task,
        status="action_dismissed",
        context_packet_hash=context_packet_hash,
        task_selection=task_selection,
    )
    session.add(chat_session)
    session.commit()
    return {
        "status": "action_dismissed",
        "session_id": chat_session.id,
        "turn_id": assistant_turn.id,
        "context_packet_hash": context_packet_hash,
        "assistant_message": assistant_message,
        "next_question": None,
        "model_name": app_settings.text_generation_model,
        "reasoning_effort": _chat_reasoning_effort(app_settings),
        "model_ready": live_text_generation_ready(app_settings),
        "live_model_call_used": False,
        "active_task": _task_summary(task) if task else {},
        "task_selection": task_selection,
        "work_surface": work_surface,
        "work_summary": work_summary,
        "actions": [
            {
                "type": pending_action.action_type,
                "label": action_label,
                "requires_confirmation": False,
                "id": pending_action.id,
                "status": "dismissed",
            }
        ],
        "field_updates": {},
        "field_diffs": [],
        "draft_decisions": draft.decisions if draft and isinstance(draft.decisions, dict) else {},
        "draft": _draft_to_dict(draft),
        "ready_to_submit": False,
        "submit_payload": None,
        "export_build_payload": None,
        "built_export": None,
        "safety_policy": _safety_policy(),
    }


def _updated_session_metadata(
    *,
    current_metadata: Any,
    task: Optional[Task],
    status: str,
    context_packet_hash: str,
    task_selection: Dict[str, Any],
    task_kind: Optional[str] = None,
) -> Dict[str, Any]:
    metadata = current_metadata if isinstance(current_metadata, dict) else {}
    history = _metadata_task_history(metadata)
    if task is not None:
        history = [task_id for task_id in history if task_id != task.id]
        history.append(task.id)
        history = history[-25:]
    skipped = _metadata_skipped_task_ids(metadata)
    newly_skipped = _string(task_selection.get("newly_skipped_task_id"))
    if newly_skipped and newly_skipped not in skipped:
        skipped.append(newly_skipped)
        skipped = skipped[-50:]
    updated = {
        **metadata,
        "last_context_packet_hash": context_packet_hash,
        "last_status": status,
        "last_task_selection": task_selection,
        "task_history": history,
        "skipped_task_ids": skipped,
    }
    if task_kind:
        updated["last_task_kind"] = task_kind
    return updated


def _model_selected_open_task(
    *,
    session: Session,
    current_task: Task,
    actions: List[Dict[str, Any]],
    has_updates: bool,
    draft_patch: List[Dict[str, Any]],
    ready_to_submit: bool,
) -> Optional[Task]:
    if has_updates or draft_patch or ready_to_submit:
        return None
    open_action = next(
        (
            action
            for action in actions
            if isinstance(action, dict)
            and action.get("type") == "open_task"
            and _string(action.get("task_id"))
        ),
        None,
    )
    if not open_action:
        return None
    target_id = _string(open_action.get("task_id"))
    if target_id == current_task.id:
        return None
    target = session.get(Task, target_id)
    if target is None or target.status != "ready":
        return None
    return target


def build_chat_turn(
    *,
    session: Session,
    request: ChatTurnRequest,
    app_settings: Settings = settings,
) -> Dict[str, Any]:
    if request.confirm_submit:
        return _build_pending_submit_confirmation_turn(
            session=session,
            request=request,
            app_settings=app_settings,
        )

    if request.confirm_action and not request.confirm_submit:
        return _build_pending_action_confirmation_turn(
            session=session,
            request=request,
            app_settings=app_settings,
        )

    export_build_type = _export_build_type_from_request(request)
    if export_build_type:
        return _build_export_build_preview_turn(
            session=session,
            request=request,
            app_settings=app_settings,
            export_type=export_build_type,
        )

    export_preview_types = _export_preview_types_from_request(request)
    if export_preview_types:
        return _build_export_preview_turn(
            session=session,
            request=request,
            app_settings=app_settings,
            export_types=export_preview_types,
        )

    if _open_export_blocker_requested(request.message):
        task, task_selection = _top_export_blocker_task(
            session=session,
            request=request,
            app_settings=app_settings,
        )
    else:
        task, task_selection = _task_or_selected(session, request)
    if task_selection.get("requested_route") == "export_readiness":
        return _build_export_readiness_turn(
            session=session,
            request=request,
            app_settings=app_settings,
            task_selection=task_selection,
        )
    chat_session = _resolve_chat_session(
        session=session,
        request=request,
        task=task,
        app_settings=app_settings,
    )
    if task is None:
        no_task_message = (
            f"I do not see a ready {_route_label(task_selection.get('requested_route'))} ticket to work on yet."
            if task_selection.get("requested_route")
            else "I do not see a ready ticket to work on yet."
        )
        context_packet = {
            "active_task": None,
            "request": {"mode": request.mode, "user_id": request.user_id},
            "status": "no_ready_task",
            "task_selection": task_selection,
        }
        context_packet_hash = _json_hash(context_packet)
        _record_chat_turn(
            session=session,
            chat_session=chat_session,
            task=None,
            role="user",
            content=request.message,
            context_packet_hash=context_packet_hash,
            metadata={"mode": request.mode},
        )
        assistant_turn = _record_chat_turn(
            session=session,
            chat_session=chat_session,
            task=None,
            role="assistant",
            content=no_task_message,
            model_name=app_settings.text_generation_model,
            context_packet_hash=context_packet_hash,
            metadata={"status": "no_ready_task", "task_selection": task_selection},
        )
        chat_session.metadata_json = _updated_session_metadata(
            current_metadata=chat_session.metadata_json,
            task=None,
            status="no_ready_task",
            context_packet_hash=context_packet_hash,
            task_selection=task_selection,
        )
        session.add(chat_session)
        session.commit()
        return {
            "status": "no_ready_task",
            "session_id": chat_session.id,
            "turn_id": assistant_turn.id,
            "context_packet_hash": context_packet_hash,
            "assistant_message": no_task_message,
            "next_question": None,
            "model_name": app_settings.text_generation_model,
            "reasoning_effort": _chat_reasoning_effort(app_settings),
            "model_ready": live_text_generation_ready(app_settings),
            "live_model_call_used": False,
            "active_task": {},
            "task_selection": task_selection,
            "work_surface": {},
            "work_summary": {},
            "actions": [],
            "field_updates": {},
            "draft_decisions": {},
            "draft": None,
            "ready_to_submit": False,
            "submit_payload": None,
            "safety_policy": _safety_policy(),
        }

    existing_draft = _task_draft(session, task.id, request.user_id)
    existing_decisions = existing_draft.decisions if existing_draft and isinstance(existing_draft.decisions, dict) else {}
    incoming_decisions = request.draft_decisions if isinstance(request.draft_decisions, dict) else {}
    raw_draft_decisions = {**existing_decisions, **incoming_decisions}
    draft_decisions = _normalize_prompt_pair_decision_state(task, raw_draft_decisions)
    contract_repair_needed = draft_decisions != raw_draft_decisions
    raw_current_decisions = {**(task.input_payload or {}), **raw_draft_decisions}
    current_decisions = _normalize_prompt_pair_decision_state(task, {**(task.input_payload or {}), **draft_decisions})
    missing_fields = _required_missing_fields(task, current_decisions)
    context_request = request.model_copy(
        update={"history": _session_history_for_turn(session=session, chat_session=chat_session, client_history=request.history)}
    )
    context_packet = _context_packet_for_turn(
        session=session,
        task=task,
        current_decisions=current_decisions,
        draft_decisions=draft_decisions,
        missing_fields=missing_fields,
        request=context_request,
        app_settings=app_settings,
        task_selection=task_selection,
    )
    context_packet_hash = _json_hash(context_packet)
    _log_chat_event(
        "context_packet_built",
        session_id=chat_session.id,
        task_id=task.id,
        task_human_id=task.human_id,
        context_packet_hash=context_packet_hash,
        task_kind=_task_kind(task),
    )
    user_turn = _record_chat_turn(
        session=session,
        chat_session=chat_session,
        task=task,
        role="user",
        content=request.message,
        context_packet_hash=context_packet_hash,
        metadata={
            "mode": request.mode,
            "apply_updates": request.apply_updates,
            "confirm_submit": request.confirm_submit,
            "confirm_action_id": request.confirm_action_id,
        },
    )
    _log_chat_event(
        "turn_received",
        session_id=chat_session.id,
        turn_id=user_turn.id,
        task_id=task.id,
        task_human_id=task.human_id,
        context_packet_hash=context_packet_hash,
    )
    model_ready = live_text_generation_ready(app_settings)
    suppress_latest_answer = (
        bool(task_selection.get("requested_route"))
        and not _chat_submit_requested(request.message)
        and (not request.task_id or request.task_id != task.id)
    )

    status = "deterministic_no_model_call"
    live_model_call_used = False
    error: Optional[str] = None
    strict_live_chat = bool(app_settings.chat_require_live_model)
    if model_ready:
        try:
            _log_chat_event(
                "model_call_started",
                session_id=chat_session.id,
                task_id=task.id,
                task_human_id=task.human_id,
                model_name=app_settings.text_generation_model,
                context_packet_hash=context_packet_hash,
            )
            plan = _live_chat_plan(
                session=session,
                task=task,
                current_decisions=current_decisions,
                missing_fields=missing_fields,
                request=context_request,
                app_settings=app_settings,
                draft_decisions=draft_decisions,
            )
            status = "live_model_call"
            live_model_call_used = True
            observability = plan.get("_observability") if isinstance(plan.get("_observability"), dict) else {}
            _log_chat_event(
                "model_call_completed",
                session_id=chat_session.id,
                task_id=task.id,
                task_human_id=task.human_id,
                model_name=app_settings.text_generation_model,
                model_response_id=observability.get("model_response_id"),
                input_token_count=observability.get("input_token_count"),
                output_token_count=observability.get("output_token_count"),
                latency_ms=observability.get("latency_ms"),
            )
        except Exception as exc:  # pragma: no cover - provider/network failures fall back into normal review mode.
            error = f"{type(exc).__name__}: {exc}"
            _log_chat_event(
                "model_call_failed",
                session_id=chat_session.id,
                task_id=task.id,
                task_human_id=task.human_id,
                model_name=app_settings.text_generation_model,
                error_type=type(exc).__name__,
            )
            if strict_live_chat:
                plan = _live_required_blocked_plan(
                    status="live_error_blocked",
                    app_settings=app_settings,
                    error=error,
                )
                status = "live_error_blocked"
            else:
                plan = _fallback_plan(
                    task=task,
                    current_decisions=current_decisions,
                    missing_fields=missing_fields,
                    request=context_request,
                    app_settings=app_settings,
                    status="live_error_fallback",
                    error=error,
                    suppress_latest_answer=suppress_latest_answer,
                )
                status = "live_error_fallback"
    else:
        if strict_live_chat:
            plan = _live_required_blocked_plan(
                status="live_model_required_not_ready",
                app_settings=app_settings,
            )
            status = "live_model_required_not_ready"
        else:
            plan = _fallback_plan(
                task=task,
                current_decisions=current_decisions,
                missing_fields=missing_fields,
                request=context_request,
                app_settings=app_settings,
                status=status,
                suppress_latest_answer=suppress_latest_answer,
            )

    plan = _validate_chat_plan(plan, fallback_status=status)
    if plan.get("status") == "invalid_model_plan_fallback":
        _log_chat_event(
            "structured_response_validation_failed",
            session_id=chat_session.id,
            task_id=task.id,
            task_human_id=task.human_id,
            error=plan.get("error"),
        )
    else:
        _log_chat_event(
            "structured_response_validated",
            session_id=chat_session.id,
            task_id=task.id,
            task_human_id=task.human_id,
            status=plan.get("status"),
        )
    rejected_actions = plan.get("rejected_actions") if isinstance(plan.get("rejected_actions"), list) else []
    for rejected_action in rejected_actions:
        if isinstance(rejected_action, dict):
            _log_chat_event(
                "action_rejected",
                session_id=chat_session.id,
                task_id=task.id,
                task_human_id=task.human_id,
                action_type=rejected_action.get("type"),
                reason=rejected_action.get("reason"),
            )
    plan = _sanitize_adam_facing_plan(task, current_decisions, missing_fields, plan)
    status = _string(plan.get("status"), status)
    draft_patch = _normalize_draft_patch(plan.get("draft_patch"))
    if not draft_patch:
        draft_patch = _draft_patch_from_adam_message(task=task, source_decisions=raw_current_decisions, request=context_request)
    field_updates = _filter_field_updates(task, plan.get("field_updates"))
    field_updates = _normalize_prompt_pair_field_updates(
        task=task,
        current_decisions=current_decisions,
        field_updates=field_updates,
    )
    field_updates = _sanitize_chat_field_updates(field_updates)
    non_patch_field_diffs = _field_diffs(current_decisions, field_updates, task=task)
    patch_result = _resolve_draft_patch(
        task=task,
        current_decisions={**raw_current_decisions, **field_updates},
        operations=draft_patch,
        ready_to_submit=bool(plan.get("ready_to_submit")),
    )
    patch_applied = bool(patch_result.get("applied"))
    if patch_applied:
        patch_updates = patch_result.get("field_updates") if isinstance(patch_result.get("field_updates"), dict) else {}
        field_updates = {**field_updates, **patch_updates}
        field_diffs = [
            *non_patch_field_diffs,
            *(patch_result.get("field_diffs") if isinstance(patch_result.get("field_diffs"), list) else []),
        ]
    else:
        field_diffs = non_patch_field_diffs
    next_decisions = _normalize_prompt_pair_decision_state(task, {**draft_decisions, **field_updates})
    merged_for_submit = _normalize_prompt_pair_decision_state(task, {**(task.input_payload or {}), **next_decisions})
    missing_after_updates = _required_missing_fields(task, merged_for_submit)
    ready_to_submit = bool(plan.get("ready_to_submit")) and not missing_after_updates
    if _chat_submit_requested(request.message) and not missing_after_updates:
        ready_to_submit = True

    notes = request.notes if request.notes is not None else (existing_draft.notes if existing_draft else None)
    notes_append = _string(plan.get("notes_append"))
    if notes_append:
        notes = f"{notes}\n{notes_append}".strip() if notes else notes_append

    saved_draft: Optional[TaskDraft] = existing_draft
    before_draft_payload = _draft_to_dict(existing_draft)
    if request.apply_updates and (field_updates or notes_append or incoming_decisions or contract_repair_needed):
        if saved_draft is None:
            saved_draft = TaskDraft(task_id=task.id, user_id=request.user_id)
        saved_draft.decisions = next_decisions
        saved_draft.notes = notes
        saved_draft.updated_at = datetime.now(timezone.utc)
        session.add(saved_draft)
        session.commit()
        session.refresh(saved_draft)

    next_question = _string(plan.get("next_question"))
    assistant_message = _string(plan.get("assistant_message"))
    if patch_applied:
        assistant_message = _patch_applied_message(patch_result, apply_updates=request.apply_updates)
        if any(
            isinstance(operation, dict)
            and operation.get("op") == "clear"
            and operation.get("field") == "chosen"
            for operation in draft_patch
        ):
            next_question = "What should the new chosen response say?"
    elif draft_patch and _string(patch_result.get("blocked_reason")):
        assistant_message = _patch_blocked_message(patch_result)
        status = "draft_patch_blocked"
        next_question = next_question or _fallback_next_question(task, current_decisions)
    elif not field_updates and _looks_like_draft_edit_claim(assistant_message):
        assistant_message = "I did not change the draft because no valid draft update or patch was produced. What exact field should I change?"
        status = "sanitized_unapplied_draft_edit_claim"
        next_question = "What exact field should I change?"
    if not assistant_message:
        assistant_message = (
            "I think this ticket is ready. Confirm submit when you want me to move it forward."
            if ready_to_submit
            else next_question or "What should we record for this ticket?"
        )

    actions = _normalize_actions(
        plan.get("actions"),
        ready_to_submit=ready_to_submit,
        has_updates=bool(field_updates),
        next_question=next_question,
    )
    opened_task = _model_selected_open_task(
        session=session,
        current_task=task,
        actions=actions,
        has_updates=bool(field_updates),
        draft_patch=draft_patch,
        ready_to_submit=ready_to_submit,
    )
    response_task = opened_task or task
    response_decisions = current_decisions
    response_draft: Optional[TaskDraft] = saved_draft
    response_work_surface = context_packet.get("work_surface") if isinstance(context_packet.get("work_surface"), dict) else {}
    if opened_task is not None:
        response_draft = _task_draft(session, opened_task.id, request.user_id)
        opened_draft_decisions = response_draft.decisions if response_draft and isinstance(response_draft.decisions, dict) else {}
        response_decisions = _normalize_prompt_pair_decision_state(opened_task, {**(opened_task.input_payload or {}), **opened_draft_decisions})
        response_work_surface = _task_work_surface(opened_task, response_decisions)
        task_selection = {
            **task_selection,
            "selection_reason": "model_selected_open_task",
            "previous_task_id": task.id,
            "previous_task_human_id": task.human_id,
            "selected_task_id": opened_task.id,
            "selected_task_human_id": opened_task.human_id,
            "selected_route": _route_for_task(opened_task),
        }
        if not next_question:
            next_question = _fallback_next_question(opened_task, response_decisions)
        if not assistant_message:
            assistant_message = f"I opened {opened_task.human_id}. {next_question}"
    submit_payload = (
        {"task_id": task.id, "decisions": merged_for_submit, "notes": notes}
        if ready_to_submit
        else None
    )
    model_observability = plan.get("_observability") if isinstance(plan.get("_observability"), dict) else {}
    plan_contract_summary = _plan_contract_summary(plan)
    assistant_turn = _record_chat_turn(
        session=session,
        chat_session=chat_session,
        task=response_task,
        role="assistant",
        content=assistant_message,
        model_name=app_settings.text_generation_model,
        input_token_count=_optional_int(model_observability.get("input_token_count")),
        output_token_count=_optional_int(model_observability.get("output_token_count")),
        latency_ms=_optional_int(model_observability.get("latency_ms")),
        context_packet_hash=context_packet_hash,
        metadata={
            "status": status,
            "live_model_call_used": live_model_call_used,
            "ready_to_submit": ready_to_submit,
            "field_update_keys": sorted(field_updates.keys()),
            "draft_patch": draft_patch,
            "patch_result": patch_result,
            "error": error or _string(plan.get("error")),
            "task_selection": task_selection,
            "work_surface": response_work_surface,
            "model_response_id": model_observability.get("model_response_id"),
            "image_pixels_included": model_observability.get("image_pixels_included"),
            "tool_loop_used": model_observability.get("tool_loop_used"),
            "tool_names": model_observability.get("tool_names"),
            "rejected_actions": rejected_actions,
            "plan_contract": plan_contract_summary,
        },
    )
    response_actions = _persist_chat_actions(
        session=session,
        chat_session=chat_session,
        task=response_task,
        assistant_turn=assistant_turn,
        actions=actions,
        field_updates=field_updates,
        field_diffs=field_diffs,
        draft_patch=draft_patch,
        patch_result=patch_result,
        saved_draft=saved_draft,
        before_draft=before_draft_payload,
        submit_payload=submit_payload,
        next_question=next_question or None,
        context_packet_hash=context_packet_hash,
        apply_updates=request.apply_updates,
        confirm_action_id=request.confirm_action_id,
    )
    for action in response_actions:
        if isinstance(action, dict):
            _log_chat_event(
                "action_proposed",
                session_id=chat_session.id,
                turn_id=assistant_turn.id,
                task_id=task.id,
                action_id=action.get("id"),
                action_type=action.get("type"),
                action_status=action.get("status"),
                requires_confirmation=action.get("requires_confirmation"),
            )
    chat_session.active_task_id = response_task.id
    chat_session.last_model = app_settings.text_generation_model
    chat_session.updated_at = datetime.now(timezone.utc)
    chat_session.metadata_json = _updated_session_metadata(
        current_metadata=chat_session.metadata_json,
        task=response_task,
        status=status,
        context_packet_hash=context_packet_hash,
        task_selection=task_selection,
        task_kind=_task_kind(response_task),
    )
    session.add(chat_session)
    session.commit()

    return {
        "status": status,
        "session_id": chat_session.id,
        "turn_id": assistant_turn.id,
        "context_packet_hash": context_packet_hash,
        "assistant_message": assistant_message,
        "next_question": next_question or None,
        "model_name": app_settings.text_generation_model,
        "reasoning_effort": _chat_reasoning_effort(app_settings),
        "model_ready": model_ready,
        "live_model_call_used": live_model_call_used,
        "active_task": _task_summary(response_task),
        "task_selection": task_selection,
        "work_surface": response_work_surface,
        "work_summary": plan_contract_summary,
        "actions": response_actions,
        "field_updates": field_updates,
        "field_diffs": field_diffs,
        "draft_patch": draft_patch,
        "patch_result": patch_result,
        "draft_decisions": response_decisions if opened_task is not None else next_decisions,
        "draft": _draft_to_dict(response_draft),
        "ready_to_submit": ready_to_submit,
        "submit_payload": submit_payload,
        "safety_policy": _safety_policy(),
        **({"error": error or _string(plan.get("error"))} if error or _string(plan.get("error")) else {}),
    }


def _safety_policy() -> Dict[str, Any]:
    return {
        "draft_first": True,
        "explicit_confirmation_before_submit": True,
        "allowed_actions_are_validated": True,
        "does_not_mutate_source": True,
        "keeps_truth_boundaries": True,
        "no_secret_values_returned": True,
    }
