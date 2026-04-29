from __future__ import annotations

from collections import Counter
import hashlib
import json
from typing import Any, Dict, List, Optional

from sqlmodel import Session, select

from app.models import Task
from app.services.pair_export import sft_export_blockers


REQUIRED_REFERENCE_MODES = [
    "logistical_note",
    "father_to_adam",
    "memoir_scene",
    "comic_observation",
    "photography_reflection",
    "philosophical_fragment",
]
REFERENCE_PACK_SAMPLE_LIMIT = 500
DEFAULT_SYSTEM_PROMPT = "You are Charles Rotmil. Write naturally in his voice."


def _string(value: Any, fallback: str = "") -> str:
    return value if isinstance(value, str) and value.strip() else fallback


def _response_text(payload: Dict[str, Any]) -> str:
    if _string(payload.get("artifact_mode"), "sft") == "dpo":
        return _string(payload.get("chosen"))
    return _string(payload.get("content")) or _string(payload.get("chosen")) or _string(payload.get("adam_gold_edit"))


def _quality_status(payload: Dict[str, Any]) -> str:
    if payload.get("candidate_requires_adam_gold_edit"):
        return "review_candidate"
    rubric_summary = payload.get("rubric_summary")
    if isinstance(rubric_summary, dict) and rubric_summary.get("preferred_export_blocked"):
        return "blocked"
    if isinstance(payload.get("export_flags"), dict) and any(payload["export_flags"].values()):
        return "exportable_candidate"
    return "review_candidate"


def _boundary_status(payload: Dict[str, Any], quality_status: str) -> str:
    if quality_status == "blocked":
        return "blocked"
    if payload.get("candidate_requires_adam_gold_edit"):
        return "needs_adam_review_before_export"
    return "needs_review_before_export"


def _source_title(payload: Dict[str, Any]) -> str:
    return (
        _string(payload.get("source_title"))
        or _string(payload.get("source_filename"))
        or _string(payload.get("grounding_asset_id"))
        or "unknown_source"
    )


def _conversation_family(payload: Dict[str, Any]) -> str:
    return _string(payload.get("conversation_family")) or _string(payload.get("family")) or "unknown"


def _messages(payload: Dict[str, Any]) -> List[Dict[str, str]]:
    system_prompt = _string(payload.get("system_prompt"), DEFAULT_SYSTEM_PROMPT)
    prompt = _string(payload.get("prompt"))
    response = _response_text(payload)
    if not prompt or not response:
        return []
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": prompt},
        {"role": "assistant", "content": response},
    ]


def _structural_blockers(payload: Dict[str, Any]) -> List[str]:
    if _string(payload.get("artifact_mode"), "sft") == "dpo":
        return []
    return sft_export_blockers(
        _string(payload.get("system_prompt"), DEFAULT_SYSTEM_PROMPT),
        _string(payload.get("prompt")),
        _response_text(payload),
    )


def _reference_key(payload: Dict[str, Any]) -> str:
    return json.dumps(_messages(payload), ensure_ascii=False, sort_keys=True)


def _task_is_referenceable(task: Task) -> bool:
    payload = task.input_payload or {}
    return bool(
        _string(payload.get("prompt"))
        and _response_text(payload)
        and _quality_status(payload) != "blocked"
        and not _structural_blockers(payload)
    )


def _sample_tasks(tasks: List[Task], limit: int) -> List[Task]:
    if len(tasks) <= limit:
        return tasks
    if limit <= 1:
        return [tasks[0]]
    step = (len(tasks) - 1) / (limit - 1)
    indices = sorted({round(index * step) for index in range(limit)})
    return [tasks[index] for index in indices[:limit]]


def _sample_reference_tasks(tasks: List[Task], limit: int) -> List[Task]:
    if limit <= 0:
        return []
    selected: List[Task] = []
    seen_ids: set[str] = set()
    for mode in REQUIRED_REFERENCE_MODES:
        task = next(
            (
                candidate
                for candidate in tasks
                if candidate.id not in seen_ids
                and _string((candidate.input_payload or {}).get("voice_mode")) == mode
            ),
            None,
        )
        if task:
            selected.append(task)
            seen_ids.add(task.id)
    for task in _sample_tasks(tasks, max(limit * 2, limit)):
        if len(selected) >= limit:
            break
        if task.id in seen_ids:
            continue
        selected.append(task)
        seen_ids.add(task.id)
    return selected[:limit]


def _embedding_input_text(record: Dict[str, Any]) -> str:
    source = record["source"]
    return "\n".join(
        [
            f"reference_id: {record['reference_id']}",
            f"voice_mode: {record['voice_mode']}",
            f"conversation_family: {record['conversation_family']}",
            f"truth_status: {record['truth_status']}",
            f"synthetic: {str(record['synthetic']).lower()}",
            f"quality_status: {record['quality_status']}",
            f"boundary_status: {record['boundary_status']}",
            f"source_title: {source['title']}",
            f"user: {record['prompt']}",
            f"assistant: {record['response']}",
        ]
    )


def _task_record(task: Task, ordinal: int) -> Dict[str, Any]:
    payload = task.input_payload or {}
    quality_status = _quality_status(payload)
    record = {
        "reference_id": f"prompt-pair-reference:{task.id}",
        "sample_index": ordinal,
        "task_id": task.id,
        "task_human_id": task.human_id,
        "pair_index": payload.get("pair_index"),
        "artifact_mode": _string(payload.get("artifact_mode"), "sft"),
        "messages": _messages(payload),
        "system_prompt": _string(payload.get("system_prompt"), DEFAULT_SYSTEM_PROMPT),
        "prompt": _string(payload.get("prompt")),
        "response": _response_text(payload),
        "rejected_response": _string(payload.get("rejected")),
        "voice_mode": _string(payload.get("voice_mode"), "unknown"),
        "conversation_family": _conversation_family(payload),
        "truth_status": _string(payload.get("truth_status"), "unknown"),
        "synthetic": bool(payload.get("synthetic", True)),
        "quality_status": quality_status,
        "boundary_status": _boundary_status(payload, quality_status),
        "reference_use": "voice_context_for_model_drafting_and_human_review",
        "source": {
            "title": _source_title(payload),
            "source_task_id": payload.get("source_task_id") or payload.get("source_prompt_pair_task_id"),
            "grounding_asset_id": payload.get("grounding_asset_id"),
            "source_photo_id": payload.get("source_photo_id"),
            "source_photo_profile_id": payload.get("source_photo_profile_id"),
            "source_excerpt": _string(payload.get("source_excerpt")),
            "context": _string(payload.get("context")),
        },
        "rubric_summary": payload.get("rubric_summary") if isinstance(payload.get("rubric_summary"), dict) else {},
        "export_preview_yaml": _string(payload.get("export_preview_yaml")),
    }
    record["embedding_input_text"] = _embedding_input_text(record)
    return record


def _markdown_code(value: str, fence: str = "text", limit: int = 1200) -> str:
    text = value if len(value) <= limit else f"{value[:limit].rstrip()}\n...[truncated]"
    return f"```{fence}\n{text}\n```"


def _reference_markdown(pack: Dict[str, Any], records: List[Dict[str, Any]]) -> str:
    lines: List[str] = [
        "# CharlesOps Prompt Pair Voice Reference Pack",
        "",
        "This pack is a drafting reference corpus. It is not a final authenticity certificate and does not promote review candidates into archival truth.",
        "",
        "## Summary",
        "",
        f"- Total prompt-pair tickets: {pack['total_pairs']}",
        f"- Referenceable tickets: {pack['referenceable_pair_count']}",
        f"- Selected references: {len(records)}",
        f"- Duplicate candidates excluded: {pack['duplicate_excluded_count']}",
        f"- Voice modes: {pack['voice_mode_counts']}",
        "",
        "## Reference Samples",
        "",
    ]
    for record in records:
        lines.extend(
            [
                f"### Reference {record['sample_index']:03d} - {record['voice_mode']} / {record['artifact_mode'].upper()}",
                "",
                f"- Task: `{record['task_human_id']}`",
                f"- Truth status: `{record['truth_status']}`",
                f"- Synthetic: `{record['synthetic']}`",
                f"- Boundary status: `{record['boundary_status']}`",
                f"- Source: `{record['source']['title']}`",
                "",
                "**Messages**",
                "",
                _markdown_code(json.dumps(record["messages"], ensure_ascii=False, indent=2), "json", 1800),
                "",
                "**Embedding / Retrieval Text**",
                "",
                _markdown_code(record["embedding_input_text"], "text", 1400),
                "",
            ]
        )
    return "\n".join(lines).rstrip()


def _all_prompt_pair_tasks(session: Session) -> List[Task]:
    return session.exec(
        select(Task)
        .where(Task.task_type == "gold_voice_edit")
        .where(Task.queue == "prompt_pairs_needing_gold_edits")
        .order_by(Task.created_at.asc())
    ).all()


def _dedupe_reference_tasks(tasks: List[Task]) -> tuple[List[Task], int]:
    seen: set[str] = set()
    unique: List[Task] = []
    duplicate_count = 0
    for task in tasks:
        key = _reference_key(task.input_payload or {})
        if key in seen:
            duplicate_count += 1
            continue
        seen.add(key)
        unique.append(task)
    return unique, duplicate_count


def compile_prompt_pair_reference_pack(session: Session, *, sample_limit: int = 200) -> Dict[str, Any]:
    tasks = _all_prompt_pair_tasks(session)
    referenceable = [task for task in tasks if _task_is_referenceable(task)]
    unique_referenceable, duplicate_count = _dedupe_reference_tasks(referenceable)
    capped_limit = max(1, min(sample_limit, REFERENCE_PACK_SAMPLE_LIMIT))
    selected = _sample_reference_tasks(unique_referenceable, capped_limit)
    records = [_task_record(task, index) for index, task in enumerate(selected, start=1)]
    represented_modes = sorted({record["voice_mode"] for record in records})
    missing_modes = [mode for mode in REQUIRED_REFERENCE_MODES if mode not in represented_modes]
    voice_mode_counts = Counter(_string((task.input_payload or {}).get("voice_mode"), "unknown") for task in unique_referenceable)
    quality_counts = Counter(_quality_status(task.input_payload or {}) for task in unique_referenceable)
    jsonl = "\n".join(
        json.dumps(record, ensure_ascii=False, sort_keys=True)
        for record in records
    )
    if jsonl:
        jsonl += "\n"
    pack: Dict[str, Any] = {
        "pack_type": "prompt_pair_voice_reference_pack",
        "total_pairs": len(tasks),
        "referenceable_pair_count": len(referenceable),
        "unique_reference_count": len(unique_referenceable),
        "duplicate_excluded_count": duplicate_count,
        "sample_count": len(records),
        "sample_limit_cap": REFERENCE_PACK_SAMPLE_LIMIT,
        "required_modes": REQUIRED_REFERENCE_MODES,
        "represented_modes": represented_modes,
        "missing_required_modes": missing_modes,
        "ready_for_generation_context": len(records) >= min(capped_limit, len(unique_referenceable)) and not missing_modes,
        "voice_mode_counts": dict(sorted(voice_mode_counts.items())),
        "quality_counts": dict(sorted(quality_counts.items())),
        "safety_policy": {
            "does_not_certify_final_authenticity": True,
            "does_not_change_truth_status": True,
            "live_model_calls": False,
            "intended_use": "reference_examples_for_prompt_pair_drafting_and_human_review",
        },
        "records": records,
        "jsonl": jsonl,
        "content_sha256": hashlib.sha256(jsonl.encode("utf-8")).hexdigest(),
    }
    pack["markdown"] = _reference_markdown(pack, records)
    return pack


def select_prompt_pair_reference_examples(
    *,
    session: Session,
    voice_mode: Optional[str] = None,
    conversation_family: Optional[str] = None,
    limit: int = 8,
) -> List[Dict[str, Any]]:
    tasks = [task for task in _all_prompt_pair_tasks(session) if _task_is_referenceable(task)]
    unique_tasks, _duplicate_count = _dedupe_reference_tasks(tasks)

    def score(task: Task) -> tuple[int, int, str]:
        payload = task.input_payload or {}
        mode_match = 0 if voice_mode and _string(payload.get("voice_mode")) == voice_mode else 1
        family_match = 0 if conversation_family and _conversation_family(payload) == conversation_family else 1
        return (mode_match, family_match, str(payload.get("pair_index") or task.created_at))

    selected = sorted(unique_tasks, key=score)[: max(0, limit)]
    return [
        {
            "messages": _messages(task.input_payload or {}),
            "metadata": {
                "reference_id": f"prompt-pair-reference:{task.id}",
                "source": "prompt_pair_review_task",
                "voice_mode": _string((task.input_payload or {}).get("voice_mode"), "unknown"),
                "conversation_family": _conversation_family(task.input_payload or {}),
                "truth_status": _string((task.input_payload or {}).get("truth_status"), "unknown"),
                "quality_status": _quality_status(task.input_payload or {}),
                "boundary_status": _boundary_status(task.input_payload or {}, _quality_status(task.input_payload or {})),
                "does_not_certify_final_authenticity": True,
                "task_id": task.id,
            },
        }
        for task in selected
    ]
