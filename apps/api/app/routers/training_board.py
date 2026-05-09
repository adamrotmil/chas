from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from app.db.session import get_session
from app.exports.jsonl import export_dry_run
from app.models import (
    Annotation,
    DPOPair,
    DatasetExport,
    DatasetExportItem,
    GoldVoiceExample,
    SFTCandidate,
    Task,
    TaskDraft,
    TaskReceipt,
)


router = APIRouter(prefix="/training-board", tags=["training-board"])

BOARD_COLUMNS = [
    ("todo", "To Do"),
    ("doing", "Doing"),
    ("needs_fix", "Needs Fix"),
    ("done", "Done"),
    ("exported", "Exported"),
]


def _string(value: Any, fallback: str = "") -> str:
    return value if isinstance(value, str) and value.strip() else fallback


def _list_strings(value: Any) -> List[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def _preview(value: Any, limit: int = 320) -> str:
    text = " ".join(str(value or "").split())
    return text if len(text) <= limit else f"{text[: limit - 3]}..."


def _iso(value: Optional[datetime]) -> Optional[str]:
    return value.isoformat() if value else None


def _messages_prompt(messages: List[Dict[str, str]]) -> str:
    for message in messages:
        if message.get("role") == "user" and _string(message.get("content")):
            return _string(message.get("content"))
    return ""


def _messages_content(messages: List[Dict[str, str]]) -> str:
    for message in reversed(messages):
        if message.get("role") == "assistant" and _string(message.get("content")):
            return _string(message.get("content"))
    return ""


def _task_artifact_mode(task: Task, decisions: Dict[str, Any]) -> str:
    payload = task.input_payload if isinstance(task.input_payload, dict) else {}
    return _string(decisions.get("artifact_mode")) or _string(payload.get("artifact_mode"), "sft")


def _provenance_labels(payload: Dict[str, Any]) -> List[str]:
    labels: List[str] = []
    metadata = payload.get("pair_generation_metadata")
    metadata = metadata if isinstance(metadata, dict) else {}
    strategy = _string(metadata.get("strategy")) or _string(payload.get("pair_generation_strategy"))
    if payload.get("live_model_call_used") is True or metadata.get("live_model_call") is True:
        labels.append("Live AI")
    if payload.get("no_live_model_call") is True or metadata.get("no_live_model_call") is True:
        labels.append("No model call")
    if "fallback" in strategy or "scaffold" in strategy:
        labels.append("Fallback")
    if metadata.get("source_text_sha256"):
        labels.append("Evidence-linked")
    return list(dict.fromkeys(labels))


def _drafts_by_task_id(session: Session) -> Dict[str, TaskDraft]:
    drafts = session.exec(select(TaskDraft).where(TaskDraft.user_id == "adam")).all()
    return {draft.task_id: draft for draft in drafts}


def _export_ids_by_source(session: Session, source_type: str) -> Dict[str, List[str]]:
    rows = session.exec(select(DatasetExportItem).where(DatasetExportItem.source_type == source_type)).all()
    export_ids_by_source: Dict[str, List[str]] = {}
    for row in rows:
        export_ids_by_source.setdefault(row.source_id, []).append(row.dataset_export_id)
    return export_ids_by_source


def _gold_rows_by_id(session: Session) -> Dict[str, GoldVoiceExample]:
    rows = session.exec(select(GoldVoiceExample)).all()
    return {row.id: row for row in rows}


def _annotations_by_id(session: Session, annotation_ids: Iterable[str]) -> Dict[str, Annotation]:
    ids = [item for item in dict.fromkeys(annotation_ids) if item]
    if not ids:
        return {}
    rows = session.exec(select(Annotation).where(Annotation.id.in_(ids))).all()
    return {row.id: row for row in rows}


def _receipts_by_annotation_id(session: Session, annotation_ids: Iterable[str]) -> Dict[str, TaskReceipt]:
    ids = [item for item in dict.fromkeys(annotation_ids) if item]
    if not ids:
        return {}
    rows = session.exec(select(TaskReceipt).where(TaskReceipt.annotation_id.in_(ids))).all()
    return {row.annotation_id: row for row in rows}


def _source_annotation_id(gold: Optional[GoldVoiceExample]) -> str:
    downstream = gold.downstream_use if gold and isinstance(gold.downstream_use, dict) else {}
    return _string(downstream.get("source_annotation_id"))


def _task_board_item(task: Task, draft: Optional[TaskDraft]) -> Dict[str, Any]:
    payload = task.input_payload if isinstance(task.input_payload, dict) else {}
    draft_decisions = draft.decisions if draft and isinstance(draft.decisions, dict) else {}
    decisions = {**payload, **draft_decisions}
    artifact_mode = _task_artifact_mode(task, decisions)
    column = "doing" if draft else "todo"
    prompt = _string(decisions.get("prompt"))
    content = _string(decisions.get("content")) or _string(decisions.get("adam_gold_edit"))
    chosen = _string(decisions.get("chosen")) or (content if artifact_mode == "dpo" else "")
    rejected = _string(decisions.get("rejected"))
    blockers = []
    if artifact_mode == "dpo" and not rejected:
        blockers.append("dpo_rejected_empty")
    return {
        "id": f"task:{task.id}",
        "kind": "task",
        "column": column,
        "taskId": task.id,
        "taskHumanId": task.human_id,
        "artifactMode": artifact_mode,
        "title": _preview(prompt or task.human_id, 90),
        "subtitle": "Draft in progress" if draft else "Needs Adam review",
        "prompt": prompt,
        "chosen": chosen,
        "rejected": rejected,
        "content": content,
        "sourceLabel": _string(payload.get("source")) or _string(payload.get("source_title")) or task.target_type,
        "exportStatus": "candidate",
        "gateStatus": "blocked" if blockers else "ready",
        "blockers": blockers,
        "labels": [artifact_mode.upper(), "Draft" if draft else "Ready", *_provenance_labels(decisions)],
        "updatedAt": _iso(draft.updated_at if draft else task.updated_at),
        "createdAt": _iso(task.created_at),
    }


def _sft_item(
    candidate: SFTCandidate,
    *,
    gold: Optional[GoldVoiceExample],
    annotation: Optional[Annotation],
    receipt: Optional[TaskReceipt],
    export_ids: List[str],
    export_included_gold_ids: set[str],
) -> Dict[str, Any]:
    messages = candidate.messages if isinstance(candidate.messages, list) else []
    quality_gate = candidate.quality_gate if isinstance(candidate.quality_gate, dict) else {}
    blockers = _list_strings(quality_gate.get("export_blockers"))
    exported = bool(export_ids)
    approved = candidate.export_status == "approved"
    column = "exported" if exported else "done" if approved and candidate.source_gold_voice_example_id in export_included_gold_ids else "needs_fix" if not approved or blockers else "done"
    return {
        "id": f"sft:{candidate.id}",
        "kind": "sft_candidate",
        "column": column,
        "taskId": annotation.task_id if annotation else None,
        "annotationId": annotation.id if annotation else None,
        "receiptId": receipt.id if receipt else None,
        "goldVoiceExampleId": candidate.source_gold_voice_example_id,
        "sftCandidateId": candidate.id,
        "datasetExportIds": export_ids,
        "artifactMode": "sft",
        "title": _preview(_messages_prompt(messages) or (gold.human_id if gold else candidate.id), 90),
        "subtitle": "Approved SFT" if approved else "SFT candidate needs fixes",
        "prompt": _messages_prompt(messages),
        "content": _messages_content(messages),
        "sourceLabel": gold.human_id if gold else candidate.source_gold_voice_example_id,
        "exportStatus": "exported" if exported else candidate.export_status,
        "gateStatus": "blocked" if blockers else "ready" if approved else "unknown",
        "blockers": blockers if blockers else ([] if approved else ["candidate_status_requires_review"]),
        "labels": ["SFT", candidate.export_status],
        "updatedAt": _iso(candidate.created_at),
        "createdAt": _iso(candidate.created_at),
        "completedAt": _iso(gold.approved_at) if gold else None,
    }


def _dpo_item(
    pair: DPOPair,
    *,
    gold: Optional[GoldVoiceExample],
    annotation: Optional[Annotation],
    receipt: Optional[TaskReceipt],
    export_ids: List[str],
    export_included_gold_ids: set[str],
) -> Dict[str, Any]:
    blockers = [] if pair.reason else ["dpo_rejected_reason_empty"]
    exported = bool(export_ids)
    approved = pair.export_status == "approved"
    column = "exported" if exported else "done" if approved and pair.source_gold_voice_example_id in export_included_gold_ids else "needs_fix" if not approved or blockers else "done"
    return {
        "id": f"dpo:{pair.id}",
        "kind": "dpo_pair",
        "column": column,
        "taskId": annotation.task_id if annotation else None,
        "annotationId": annotation.id if annotation else None,
        "receiptId": receipt.id if receipt else None,
        "goldVoiceExampleId": pair.source_gold_voice_example_id,
        "dpoPairId": pair.id,
        "datasetExportIds": export_ids,
        "artifactMode": "dpo",
        "title": _preview(pair.prompt or (gold.human_id if gold else pair.id), 90),
        "subtitle": "Approved DPO pair" if approved else "DPO pair needs fixes",
        "prompt": pair.prompt,
        "chosen": pair.chosen,
        "rejected": pair.rejected,
        "reason": pair.reason,
        "sourceLabel": gold.human_id if gold else pair.source_gold_voice_example_id,
        "exportStatus": "exported" if exported else pair.export_status,
        "gateStatus": "blocked" if blockers else "ready" if approved else "unknown",
        "blockers": blockers if blockers else ([] if approved else ["candidate_status_requires_review"]),
        "labels": ["DPO", pair.export_status],
        "updatedAt": _iso(pair.created_at),
        "createdAt": _iso(pair.created_at),
        "completedAt": _iso(gold.approved_at) if gold else None,
    }


def _exported_items(session: Session) -> List[Dict[str, Any]]:
    rows = session.exec(select(DatasetExport).order_by(DatasetExport.created_at.desc())).all()
    return [
        {
            "id": row.id,
            "humanId": row.human_id,
            "exportType": row.export_type,
            "version": row.version,
            "status": row.status,
            "itemCount": row.manifest.get("item_count") if isinstance(row.manifest, dict) else None,
            "createdAt": _iso(row.created_at),
        }
        for row in rows
    ]


def _board_projection(session: Session) -> Dict[str, Any]:
    drafts_by_task = _drafts_by_task_id(session)
    ready_tasks = session.exec(
        select(Task)
        .where(Task.task_type == "gold_voice_edit")
        .where(Task.status == "ready")
        .order_by(Task.priority.desc(), Task.created_at.asc())
    ).all()
    task_items = [_task_board_item(task, drafts_by_task.get(task.id)) for task in ready_tasks]

    gold_by_id = _gold_rows_by_id(session)
    annotation_ids = [_source_annotation_id(gold) for gold in gold_by_id.values()]
    annotations_by_id = _annotations_by_id(session, annotation_ids)
    receipts_by_annotation = _receipts_by_annotation_id(session, annotation_ids)
    sft_export_ids = _export_ids_by_source(session, "sft")
    dpo_export_ids = _export_ids_by_source(session, "dpo")
    try:
        sft_included_gold_ids = {
            _string(row.get("source_gold_voice_example_id"))
            for row in export_dry_run(session, "sft").get("included", [])
            if isinstance(row, dict)
        }
        dpo_included_gold_ids = {
            _string(row.get("source_gold_voice_example_id"))
            for row in export_dry_run(session, "dpo").get("included", [])
            if isinstance(row, dict)
        }
    except ValueError:
        sft_included_gold_ids = set()
        dpo_included_gold_ids = set()

    artifact_items: List[Dict[str, Any]] = []
    for candidate in session.exec(select(SFTCandidate).order_by(SFTCandidate.created_at.desc())).all():
        gold = gold_by_id.get(candidate.source_gold_voice_example_id)
        annotation_id = _source_annotation_id(gold)
        annotation = annotations_by_id.get(annotation_id)
        artifact_items.append(
            _sft_item(
                candidate,
                gold=gold,
                annotation=annotation,
                receipt=receipts_by_annotation.get(annotation_id),
                export_ids=sft_export_ids.get(candidate.source_gold_voice_example_id, []),
                export_included_gold_ids=sft_included_gold_ids,
            )
        )
    for pair in session.exec(select(DPOPair).order_by(DPOPair.created_at.desc())).all():
        gold = gold_by_id.get(pair.source_gold_voice_example_id)
        annotation_id = _source_annotation_id(gold)
        annotation = annotations_by_id.get(annotation_id)
        artifact_items.append(
            _dpo_item(
                pair,
                gold=gold,
                annotation=annotation,
                receipt=receipts_by_annotation.get(annotation_id),
                export_ids=dpo_export_ids.get(pair.source_gold_voice_example_id, []),
                export_included_gold_ids=dpo_included_gold_ids,
            )
        )

    items = [*task_items, *artifact_items]
    columns = []
    for column_id, label in BOARD_COLUMNS:
        column_items = [item for item in items if item.get("column") == column_id]
        columns.append({"id": column_id, "label": label, "count": len(column_items), "items": column_items[:60]})

    submitted_count = len(session.exec(select(Task).where(Task.task_type == "gold_voice_edit").where(Task.status == "submitted")).all())
    approved_sft = [item for item in artifact_items if item.get("kind") == "sft_candidate" and item.get("exportStatus") in {"approved", "exported"}]
    approved_dpo = [item for item in artifact_items if item.get("kind") == "dpo_pair" and item.get("exportStatus") in {"approved", "exported"}]
    counts = {
        "ready_tasks": len(ready_tasks),
        "submitted_tasks": submitted_count,
        "approved_sft": len(approved_sft),
        "approved_dpo": len(approved_dpo),
        "exported_sft": len([item for item in approved_sft if item.get("exportStatus") == "exported"]),
        "exported_dpo": len([item for item in approved_dpo if item.get("exportStatus") == "exported"]),
        "todo": len([item for item in items if item.get("column") == "todo"]),
        "doing": len([item for item in items if item.get("column") == "doing"]),
        "needs_fix": len([item for item in items if item.get("column") == "needs_fix"]),
        "done": len([item for item in items if item.get("column") == "done"]),
        "exported": len([item for item in items if item.get("column") == "exported"]),
    }
    return {
        "board_type": "training_artifact_board",
        "columns": columns,
        "counts": counts,
        "exports": _exported_items(session)[:20],
    }


@router.get("")
def get_training_board(session: Session = Depends(get_session)) -> Dict[str, Any]:
    return _board_projection(session)


@router.get("/items/{item_id:path}")
def get_training_board_item(item_id: str, session: Session = Depends(get_session)) -> Dict[str, Any]:
    board = _board_projection(session)
    for column in board["columns"]:
        for item in column["items"]:
            if item.get("id") == item_id or item.get("taskId") == item_id or item.get("dpoPairId") == item_id or item.get("sftCandidateId") == item_id:
                return item
    raise HTTPException(status_code=404, detail="Training board item not found.")
