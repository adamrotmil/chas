from __future__ import annotations

import hashlib
import json
from collections import Counter
from difflib import unified_diff
from typing import Any, Dict, List

from sqlmodel import Session, select

from app.models import Task
from app.services.pair_export import compile_pair_export, preflight_pair_export_gate, sft_export_blockers


REQUIRED_AUDIT_MODES = [
    "logistical_note",
    "father_to_adam",
    "memoir_scene",
    "comic_observation",
    "photography_reflection",
    "philosophical_fragment",
]
AUDIT_PACK_SAMPLE_LIMIT = 250
DEFAULT_SYSTEM_PROMPT = "You are Charles Rotmil. Write naturally in his voice."


def _string(value: Any, fallback: str = "") -> str:
    return value if isinstance(value, str) and value.strip() else fallback


def _response_text(payload: Dict[str, Any]) -> str:
    if _string(payload.get("artifact_mode"), "sft") == "dpo":
        return _string(payload.get("chosen"))
    return _string(payload.get("content")) or _string(payload.get("chosen")) or _string(payload.get("adam_gold_edit"))


def _structural_blockers(payload: Dict[str, Any]) -> List[str]:
    if _string(payload.get("artifact_mode"), "sft") == "dpo":
        return []
    return sft_export_blockers(
        _string(payload.get("system_prompt"), DEFAULT_SYSTEM_PROMPT),
        _string(payload.get("prompt")),
        _response_text(payload),
    )


def _quality_status(payload: Dict[str, Any]) -> str:
    if payload.get("candidate_requires_adam_gold_edit"):
        return "review_candidate"
    rubric_summary = payload.get("rubric_summary")
    if isinstance(rubric_summary, dict) and rubric_summary.get("preferred_export_blocked"):
        return "blocked"
    if isinstance(payload.get("export_flags"), dict) and any(payload["export_flags"].values()):
        return "exportable_candidate"
    return "review_candidate"


def _source_boundary_training_summary(payload: Dict[str, Any]) -> Dict[str, Any] | None:
    boundary = payload.get("boundary_snapshot")
    boundary = boundary if isinstance(boundary, dict) else {}
    source_photo_id = _string(payload.get("source_photo_id"))
    if not source_photo_id and not boundary:
        return None

    blocked_training_uses: List[str] = []
    if bool(source_photo_id) and boundary.get("usable_for_sft") is False:
        blocked_training_uses.append("sft")
    if bool(source_photo_id) and boundary.get("usable_for_dpo") is False:
        blocked_training_uses.append("dpo")
    if boundary.get("redaction_required") is True:
        blocked_training_uses.append("redaction_required")
    if str(boundary.get("privacy_level") or "") in {"sealed", "private_sensitive", "sensitive_living_people"}:
        blocked_training_uses.append(f"privacy_level={boundary.get('privacy_level')}")

    if not blocked_training_uses:
        return {
            "status": "no_source_boundary_training_block",
            "source_photo_id": source_photo_id or None,
            "privacy_level": boundary.get("privacy_level"),
            "usable_for_sft": boundary.get("usable_for_sft"),
            "usable_for_dpo": boundary.get("usable_for_dpo"),
            "usable_for_eval": boundary.get("usable_for_eval"),
            "reviewed_by": boundary.get("reviewed_by"),
            "blocked_training_uses": [],
            "remediation_options": [],
            "does_not_mutate_source": True,
        }

    return {
        "status": "source_boundary_blocks_training",
        "source_photo_id": source_photo_id or boundary.get("target_id"),
        "privacy_level": boundary.get("privacy_level"),
        "usable_for_sft": boundary.get("usable_for_sft"),
        "usable_for_dpo": boundary.get("usable_for_dpo"),
        "usable_for_eval": boundary.get("usable_for_eval"),
        "usable_for_voice_context": boundary.get("usable_for_voice_context"),
        "retrievable_in_chat": boundary.get("retrievable_in_chat"),
        "reviewed_by": boundary.get("reviewed_by"),
        "blocked_training_uses": _unique_strings(blocked_training_uses),
        "remediation_options": [
            "Keep this prompt pair as review-only context if the photo source should not train the model.",
            "If Adam clears the photo source for training, update the source boundary before Submit.",
            "Use eval or voice-context permissions separately from SFT/DPO permissions.",
        ],
        "does_not_mutate_source": True,
    }


def _ui_gate_mismatch(payload: Dict[str, Any], preflight: Dict[str, Any]) -> List[str]:
    preview = payload.get("export_gate_preview")
    if not isinstance(preview, dict):
        return []
    mismatches: List[str] = []
    if preview.get("submit_outcome") and preview.get("submit_outcome") != preflight["submit_outcome"]:
        mismatches.append("submit_outcome_mismatch")
    if preview.get("dataset_outcome") and preview.get("dataset_outcome") != preflight["dataset_outcome"]:
        mismatches.append("dataset_outcome_mismatch")
    preview_blockers = preview.get("blockers")
    if isinstance(preview_blockers, list) and sorted(map(str, preview_blockers)) != sorted(preflight["blockers"]):
        mismatches.append("blockers_mismatch")
    return mismatches


def _source_key(payload: Dict[str, Any]) -> str:
    return (
        _string(payload.get("source_title"))
        or _string(payload.get("source_filename"))
        or _string(payload.get("grounding_asset_id"))
        or "unknown_source"
    )


def _sample_tasks(tasks: List[Task], limit: int) -> List[Task]:
    if len(tasks) <= limit:
        return tasks
    if limit <= 1:
        return [tasks[0]]
    step = (len(tasks) - 1) / (limit - 1)
    indices = sorted({round(index * step) for index in range(limit)})
    return [tasks[index] for index in indices[:limit]]


def _sample_tasks_for_audit_pack(tasks: List[Task], limit: int) -> List[Task]:
    if limit <= 0:
        return []
    selected: List[Task] = []
    seen_ids: set[str] = set()
    for mode in REQUIRED_AUDIT_MODES:
        task = next(
            (
                candidate
                for candidate in tasks
                if candidate.id not in seen_ids
                and _string((candidate.input_payload or {}).get("voice_mode")) == mode
                and _string((candidate.input_payload or {}).get("prompt"))
                and _response_text(candidate.input_payload or {})
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
        payload = task.input_payload or {}
        if not _string(payload.get("prompt")) or not _response_text(payload):
            continue
        selected.append(task)
        seen_ids.add(task.id)
    return selected[:limit]


def _truncate(value: str, limit: int = 1200) -> str:
    if len(value) <= limit:
        return value
    return f"{value[:limit].rstrip()}\n...[truncated]"


def _list_strings(value: Any) -> List[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item).strip()]


def _unique_strings(values: List[str]) -> List[str]:
    unique: List[str] = []
    seen: set[str] = set()
    for value in values:
        text = value.strip()
        if not text or text in seen:
            continue
        unique.append(text)
        seen.add(text)
    return unique


def _suggest_dpo_failure_modes(payload: Dict[str, Any], compiled: Dict[str, Any]) -> List[str]:
    voice_mode = _string(payload.get("voice_mode")).lower()
    chosen = _string(compiled.get("chosen")).lower()
    rejected = _string(compiled.get("rejected")).lower()
    suggestions: List[str] = []

    if not rejected.strip():
        suggestions.append("rejected_response_missing")
    if "straightforward response" in rejected or "explains the situation clearly" in rejected:
        suggestions.append("rejected_explains_instead_of_speaking_as_charles")
    if "\n" in chosen and "\n" not in rejected:
        suggestions.append("rejected_missing_charles_line_break_cadence")
    if chosen.rstrip().endswith("dad") and "dad" not in rejected:
        suggestions.append("rejected_lacks_intimate_dad_signoff")

    if voice_mode in {"memoir_scene", "source_based_story_recall"}:
        suggestions.append("rejected_collapses_scene_into_summary")
    elif voice_mode == "photography_reflection":
        suggestions.append("rejected_lacks_concrete_visual_attention")
    elif voice_mode == "comic_observation":
        suggestions.append("rejected_lacks_sideways_comic_observation")
    elif voice_mode == "philosophical_fragment":
        suggestions.append("rejected_lacks_specific_philosophical_turn")
    elif voice_mode in {"mundane_text_message", "logistical_note"}:
        suggestions.append("rejected_too_formal_for_text_message")
    elif voice_mode == "verbatim_email_reply":
        suggestions.append("rejected_not_email_like_enough")

    suggestions.append("too_generic_not_charles_voice")
    return _unique_strings(suggestions)[:3]


def _suggest_dpo_rejected_issue_note(failure_modes: List[str], voice_mode: str) -> Dict[str, Any]:
    first_mode = failure_modes[0] if failure_modes else "too_generic_not_charles_voice"
    mode_notes = {
        "rejected_response_missing": "Rejected is empty, so Adam cannot teach the model what lower-quality alternative to avoid yet.",
        "rejected_explains_instead_of_speaking_as_charles": "Rejected explains the situation from the outside instead of inhabiting Charles' clipped, concrete, first-person cadence.",
        "rejected_missing_charles_line_break_cadence": "Rejected flattens the response into explanatory prose and loses the line breaks, pauses, and small turns that carry Charles' voice.",
        "rejected_lacks_intimate_dad_signoff": "Rejected misses the intimate family-note ending that helps the chosen response land as Charles writing to Adam.",
        "rejected_collapses_scene_into_summary": "Rejected summarizes the scene instead of letting concrete details, memory jumps, and Charles' associative motion do the work.",
        "rejected_lacks_concrete_visual_attention": "Rejected does not notice light, faces, objects, or the photographic surface closely enough to sound like Charles.",
        "rejected_lacks_sideways_comic_observation": "Rejected misses the sideways joke or absurd observational turn that makes the chosen response feel alive.",
        "rejected_lacks_specific_philosophical_turn": "Rejected states an idea too generally and lacks Charles' specific, lived philosophical pivot.",
        "rejected_too_formal_for_text_message": "Rejected is too polished and explanatory for Charles' quick practical note mode.",
        "rejected_not_email_like_enough": "Rejected does not preserve the loose, direct, slightly digressive email cadence.",
        "too_generic_not_charles_voice": "Rejected is generic and does not preserve enough of Charles' cadence, concrete detail, restraint, or odd angle of attention.",
    }
    return {
        "severity": "minor_issues",
        "rubric_target": "response_a",
        "issue_tag": first_mode,
        "voice_mode": voice_mode,
        "note": mode_notes.get(first_mode, mode_notes["too_generic_not_charles_voice"]),
    }


def _indent_yaml_block(value: str, spaces: int = 4) -> str:
    indent = " " * spaces
    lines = value.splitlines() or [""]
    return "\n".join(f"{indent}{line}" if line else indent.rstrip() for line in lines)


def _yaml_line_scalar(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return '""'
    return json.dumps(text, ensure_ascii=False)


def _task_sample(task: Task, ordinal: int) -> Dict[str, Any]:
    payload = task.input_payload or {}
    quality_status = _quality_status(payload)
    preflight = preflight_pair_export_gate(payload)
    generation_metadata = payload.get("pair_generation_metadata")
    generation_metadata = generation_metadata if isinstance(generation_metadata, dict) else {}
    return {
        "sample_index": ordinal,
        "task_id": task.id,
        "task_human_id": task.human_id,
        "pair_index": payload.get("pair_index"),
        "artifact_mode": _string(payload.get("artifact_mode"), "sft"),
        "voice_mode": _string(payload.get("voice_mode"), "unknown"),
        "truth_status": _string(payload.get("truth_status"), "unknown"),
        "synthetic": bool(payload.get("synthetic", True)),
        "quality_status": quality_status,
        "boundary_status": "blocked" if quality_status == "blocked" else "needs_review_before_export",
        "source_title": _source_key(payload),
        "source_task_id": payload.get("source_task_id"),
        "grounding_asset_id": payload.get("grounding_asset_id"),
        "source_photo_id": payload.get("source_photo_id"),
        "prompt": _string(payload.get("prompt")),
        "response": _response_text(payload),
        "source_excerpt": _string(payload.get("source_excerpt")),
        "context": _string(payload.get("context")),
        "export_preview_yaml": _string(payload.get("export_preview_yaml")),
        "backend_preflight": {
            "export_status": preflight["export_status"],
            "submit_outcome": preflight["submit_outcome"],
            "dataset_outcome": preflight["dataset_outcome"],
            "blockers": preflight["blockers"],
        },
        "pair_generation_strategy": _string(generation_metadata.get("strategy"), "unknown"),
        "pair_generation_metadata": generation_metadata,
    }


def _markdown_code(value: str, fence: str = "text", limit: int = 1200) -> str:
    return f"```{fence}\n{_truncate(value, limit)}\n```"


def _audit_pack_markdown(audit: Dict[str, Any], samples: List[Dict[str, Any]]) -> str:
    lines: List[str] = [
        "# CharlesOps Prompt Pair Human Audit Pack",
        "",
        "This pack is for human review. It proves structure, provenance, and inspectability; it does not prove final Charles authenticity.",
        "",
        "## Summary",
        "",
        f"- Total pairs: {audit['total_pairs']}",
        f"- Inspectable pairs: {audit['inspectable_pair_count']}",
        f"- Invalid pairs: {audit['invalid_pair_count']}",
        f"- Sample count: {len(samples)}",
        f"- Quality counts: {audit['quality_counts']}",
        f"- Voice modes: {audit['voice_mode_counts']}",
        "",
        "## Known Weak Spots",
        "",
    ]
    lines.extend(f"- {item}" for item in audit["known_weak_spots"])
    lines.extend(["", "## Representative Samples", ""])
    for sample in samples:
        title = f"Sample {sample['sample_index']:02d} - {sample['voice_mode']} / {sample['artifact_mode'].upper()}"
        backend_preflight = sample["backend_preflight"]
        generation_metadata = sample["pair_generation_metadata"] or {"strategy": sample["pair_generation_strategy"]}
        lines.extend(
            [
                f"### {title}",
                "",
                f"- Task: `{sample['task_human_id']}`",
                f"- Pair index: `{sample['pair_index']}`",
                f"- Truth status: `{sample['truth_status']}`",
                f"- Synthetic: `{sample['synthetic']}`",
                f"- Quality status: `{sample['quality_status']}`",
                f"- Boundary status: `{sample['boundary_status']}`",
                f"- Backend preflight: `{backend_preflight['export_status']}`",
                f"- Generation strategy: `{sample['pair_generation_strategy']}`",
                f"- Source: `{sample['source_title']}`",
                "",
                "**Prompt**",
                "",
                _markdown_code(sample["prompt"], "text", 800),
                "",
                "**Response / Chosen**",
                "",
                _markdown_code(sample["response"], "text", 1400),
                "",
                "**Source Excerpt**",
                "",
                _markdown_code(sample["source_excerpt"], "text", 1200),
                "",
                "**Context Note**",
                "",
                _markdown_code(sample["context"], "text", 900),
                "",
                "**Export Preview**",
                "",
                _markdown_code(sample["export_preview_yaml"], "yaml", 1400),
                "",
                "**Backend Preflight**",
                "",
                _markdown_code(json.dumps(backend_preflight, indent=2, sort_keys=True), "json", 900),
                "",
                "**Pair Generation Provenance**",
                "",
                _markdown_code(json.dumps(generation_metadata, indent=2, sort_keys=True), "json", 1200),
                "",
            ]
        )
    return "\n".join(lines).rstrip()


def compile_prompt_pair_audit(session: Session, *, sample_limit: int = 20) -> Dict[str, Any]:
    tasks = session.exec(
        select(Task)
        .where(Task.task_type == "gold_voice_edit")
        .where(Task.queue == "prompt_pairs_needing_gold_edits")
        .order_by(Task.created_at.asc())
    ).all()
    artifact_modes = Counter()
    voice_modes = Counter()
    truth_statuses = Counter()
    sources = Counter()
    quality = Counter()
    preflight_gate_counts = Counter()
    preflight_blocker_counts = Counter()
    invalid: List[Dict[str, Any]] = []
    preflight_mismatches: List[Dict[str, Any]] = []
    next_review_actions: List[Dict[str, Any]] = []
    blocker_review_actions: List[Dict[str, Any]] = []
    seen_blocker_actions = set()

    for task in tasks:
        payload = task.input_payload or {}
        preflight = preflight_pair_export_gate(payload)
        prompt = _string(payload.get("prompt"))
        response = _response_text(payload)
        artifact_modes[_string(payload.get("artifact_mode"), "sft")] += 1
        voice_modes[_string(payload.get("voice_mode"), "unknown")] += 1
        truth_statuses[_string(payload.get("truth_status"), "unknown")] += 1
        sources[_source_key(payload)] += 1
        quality[_quality_status(payload)] += 1
        preflight_gate_counts[preflight["export_status"]] += 1
        for blocker in preflight["blockers"]:
            preflight_blocker_counts[blocker] += 1
            if blocker not in seen_blocker_actions:
                seen_blocker_actions.add(blocker)
                blocker_review_actions.append(
                    {
                        "action_type": "open_prompt_pair_blocker",
                        "label": "Open blocker example",
                        "blocker": blocker,
                        "blocker_count": 0,
                        "task_id": task.id,
                        "task_human_id": task.human_id,
                        "pair_index": payload.get("pair_index"),
                        "artifact_mode": _string(payload.get("artifact_mode"), "sft"),
                        "voice_mode": _string(payload.get("voice_mode"), "unknown"),
                        "export_status": preflight["export_status"],
                        "blockers": preflight["blockers"],
                        "reason": f"First held prompt pair with backend blocker `{blocker}`.",
                    }
                )
        if preflight["export_status"] == "candidate" and not any(
            action.get("action_type") == "open_held_prompt_pair_candidate" for action in next_review_actions
        ):
            next_review_actions.append(
                {
                    "action_type": "open_held_prompt_pair_candidate",
                    "label": "Open held candidate",
                    "task_id": task.id,
                    "task_human_id": task.human_id,
                    "pair_index": payload.get("pair_index"),
                    "artifact_mode": _string(payload.get("artifact_mode"), "sft"),
                    "voice_mode": _string(payload.get("voice_mode"), "unknown"),
                    "export_status": preflight["export_status"],
                    "blockers": preflight["blockers"],
                    "reason": "Backend preflight keeps this prompt pair in candidate dry-run until blockers are resolved.",
                }
            )
        mismatch_reasons = _ui_gate_mismatch(payload, preflight)
        if mismatch_reasons:
            preflight_mismatches.append(
                {
                    "task_id": task.id,
                    "task_human_id": task.human_id,
                    "pair_index": payload.get("pair_index"),
                    "reasons": mismatch_reasons,
                    "backend_preflight": {
                        "submit_outcome": preflight["submit_outcome"],
                        "dataset_outcome": preflight["dataset_outcome"],
                        "blockers": preflight["blockers"],
                    },
                    "ui_preview": payload.get("export_gate_preview"),
                }
            )
        reasons = []
        if not prompt:
            reasons.append("empty_prompt")
        if not response:
            reasons.append("empty_response")
        reasons.extend(_structural_blockers(payload))
        if reasons:
            invalid.append({"task_id": task.id, "pair_index": payload.get("pair_index"), "reasons": list(dict.fromkeys(reasons))})

    samples = []
    for task in _sample_tasks(tasks, max(1, min(sample_limit, 50))):
        payload = task.input_payload or {}
        samples.append(
            {
                "task_id": task.id,
                "pair_index": payload.get("pair_index"),
                "artifact_mode": _string(payload.get("artifact_mode"), "sft"),
                "voice_mode": _string(payload.get("voice_mode"), "unknown"),
                "truth_status": _string(payload.get("truth_status"), "unknown"),
                "synthetic": bool(payload.get("synthetic", True)),
                "prompt": _string(payload.get("prompt")),
                "response": _response_text(payload),
                "source_excerpt": _string(payload.get("source_excerpt")),
                "context": _string(payload.get("context")),
                "quality_status": _quality_status(payload),
                "boundary_status": "blocked"
                if _quality_status(payload) == "blocked"
                else "needs_review_before_export",
                "export_preview_yaml": _string(payload.get("export_preview_yaml")),
                "source_task_id": payload.get("source_task_id"),
                "grounding_asset_id": payload.get("grounding_asset_id"),
            }
        )

    for action in blocker_review_actions:
        blocker = action.get("blocker")
        if isinstance(blocker, str):
            action["blocker_count"] = preflight_blocker_counts[blocker]

    return {
        "total_pairs": len(tasks),
        "inspectable_pair_count": len(tasks) - len(invalid),
        "invalid_pair_count": len(invalid),
        "invalid_pairs": invalid,
        "quality_counts": dict(sorted(quality.items())),
        "preflight_gate_counts": dict(sorted(preflight_gate_counts.items())),
        "preflight_blocker_counts": dict(sorted(preflight_blocker_counts.items())),
        "preflight_mismatch_count": len(preflight_mismatches),
        "preflight_mismatches": preflight_mismatches[:20],
        "next_review_actions": next_review_actions,
        "blocker_review_actions": blocker_review_actions,
        "artifact_mode_counts": dict(sorted(artifact_modes.items())),
        "voice_mode_counts": dict(sorted(voice_modes.items())),
        "truth_status_counts": dict(sorted(truth_statuses.items())),
        "source_distribution": dict(sources.most_common(20)),
        "sample_count": len(samples),
        "samples": samples,
        "known_weak_spots": [
            "Automated audit proves structure and provenance, not Charles authenticity.",
            "Prompt pairs remain candidates until Adam review or source-verbatim validation.",
        ],
    }


def _held_candidate_record(task: Task) -> Dict[str, Any]:
    payload = task.input_payload or {}
    preflight = preflight_pair_export_gate(payload)
    response = _response_text(payload)
    source_boundary_summary = _source_boundary_training_summary(payload)
    return {
        "task_id": task.id,
        "task_human_id": task.human_id,
        "pair_index": payload.get("pair_index"),
        "artifact_mode": _string(payload.get("artifact_mode"), "sft"),
        "voice_mode": _string(payload.get("voice_mode"), "unknown"),
        "truth_status": _string(payload.get("truth_status"), "unknown"),
        "synthetic": bool(payload.get("synthetic", True)),
        "source_title": _source_key(payload),
        "source_task_id": payload.get("source_task_id"),
        "source_photo_id": payload.get("source_photo_id"),
        "prompt": _string(payload.get("prompt")),
        "response_preview": _truncate(response, 420),
        "response_char_count": len(response),
        "blockers": preflight["blockers"],
        "blocker_count": len(preflight["blockers"]),
        "export_status": preflight["export_status"],
        "dataset_outcome": preflight["dataset_outcome"],
        "submit_outcome": preflight["submit_outcome"],
        "quality_status": _quality_status(payload),
        "source_boundary_summary": source_boundary_summary,
        "action": {
            "action_type": "open_held_prompt_pair_candidate",
            "label": "Open held prompt pair",
            "task_id": task.id,
            "task_human_id": task.human_id,
            "queue": task.queue,
        },
    }


def _pair_index_sort_value(value: Any) -> tuple[int, str]:
    if isinstance(value, int):
        return (value, str(value))
    if isinstance(value, str) and value.isdigit():
        return (int(value), value)
    return (10**9, str(value or ""))


def _candidate_sort_key(record: Dict[str, Any]) -> tuple[tuple[int, str], str]:
    return (_pair_index_sort_value(record.get("pair_index")), str(record.get("task_human_id") or record.get("task_id") or ""))


def _held_worklist_preview(record: Dict[str, Any], sequence_number: int) -> Dict[str, Any]:
    preview = {
        "sequence_number": sequence_number,
        "task_id": record["task_id"],
        "task_human_id": record["task_human_id"],
        "pair_index": record.get("pair_index"),
        "voice_mode": record["voice_mode"],
        "artifact_mode": record["artifact_mode"],
        "prompt": record["prompt"],
        "blockers": record["blockers"],
        "action": record["action"],
    }
    if record.get("source_boundary_summary"):
        preview["source_boundary_summary"] = record["source_boundary_summary"]
    return preview


def _compile_held_candidate_worklists(held_records: List[Dict[str, Any]], *, preview_limit: int = 10) -> List[Dict[str, Any]]:
    grouped: Dict[str, List[Dict[str, Any]]] = {}
    for record in held_records:
        blockers = record["blockers"] or ["candidate_without_backend_blocker"]
        for blocker in blockers:
            grouped.setdefault(blocker, []).append(record)

    worklists = []
    for blocker, records in sorted(grouped.items(), key=lambda item: (-len(item[1]), item[0])):
        sorted_records = sorted(records, key=_candidate_sort_key)
        stable_payload = {
            "blocker": blocker,
            "candidate_task_ids": [record["task_id"] for record in sorted_records],
            "candidate_pair_indices": [record.get("pair_index") for record in sorted_records],
        }
        review_sequence_key = hashlib.sha256(
            json.dumps(stable_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        first = sorted_records[0]
        worklists.append(
            {
                "worklist_key": f"prompt_pair_blocker:{blocker}",
                "title": f"{blocker.replace('_', ' ').title()} candidates",
                "blocker": blocker,
                "candidate_count": len(sorted_records),
                "reported_candidate_count": min(len(sorted_records), preview_limit),
                "sequence_start": first.get("pair_index"),
                "sequence_end": sorted_records[-1].get("pair_index"),
                "review_sequence_key": review_sequence_key,
                "review_policy": "resolve_blocker_then_submit_gold_edit",
                "recommended_action": {
                    "action_type": "open_prompt_pair_worklist",
                    "label": "Work this blocker next",
                    "blocker": blocker,
                    "task_id": first["task_id"],
                    "task_human_id": first["task_human_id"],
                    "candidate_count": len(sorted_records),
                    "review_sequence_key": review_sequence_key,
                    "reason": f"Start with the earliest held prompt pair carrying `{blocker}`.",
                },
                "candidate_previews": [
                    _held_worklist_preview(record, sequence_number)
                    for sequence_number, record in enumerate(sorted_records[:preview_limit], start=1)
                ],
            }
        )
    return worklists


def compile_prompt_pair_candidate_review_pack(session: Session, *, limit: int = 30) -> Dict[str, Any]:
    safe_limit = max(1, min(limit, 100))
    tasks = session.exec(
        select(Task)
        .where(Task.task_type == "gold_voice_edit")
        .where(Task.queue == "prompt_pairs_needing_gold_edits")
        .order_by(Task.created_at.asc())
    ).all()
    held_records = []
    blocker_counts: Counter[str] = Counter()
    mode_counts: Counter[str] = Counter()
    artifact_mode_counts: Counter[str] = Counter()
    for task in tasks:
        record = _held_candidate_record(task)
        if record["export_status"] != "candidate":
            continue
        held_records.append(record)
        mode_counts[record["voice_mode"]] += 1
        artifact_mode_counts[record["artifact_mode"]] += 1
        for blocker in record["blockers"]:
            blocker_counts[blocker] += 1

    reported = held_records[:safe_limit]
    worklists = _compile_held_candidate_worklists(held_records)
    stable_payload = {
        "reported_candidates": reported,
        "blocker_counts": dict(sorted(blocker_counts.items())),
        "voice_mode_counts": dict(sorted(mode_counts.items())),
        "worklists": worklists,
    }
    return {
        "pack_type": "prompt_pair_candidate_review_pack",
        "review_policy": "candidate_review_only_no_training_export",
        "does_not_promote_to_training_export": True,
        "requires_adam_gold_edit": True,
        "total_candidate_count": len(held_records),
        "reported_candidate_count": len(reported),
        "limit": safe_limit,
        "blocker_counts": dict(sorted(blocker_counts.items())),
        "voice_mode_counts": dict(sorted(mode_counts.items())),
        "artifact_mode_counts": dict(sorted(artifact_mode_counts.items())),
        "worklist_count": len(worklists),
        "worklists": worklists,
        "batch_review_guidance": [
            "Open each held pair and resolve backend blockers before approved export.",
            "Keep candidates marked as review material until Adam submits a clean gold edit.",
            "Use blocker counts to work repeated rubric/privacy issues in batches.",
        ],
        "candidates": reported,
        "content_sha256": hashlib.sha256(
            json.dumps(stable_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest(),
    }


def compile_prompt_pair_review_progress(session: Session) -> Dict[str, Any]:
    audit = compile_prompt_pair_audit(session=session, sample_limit=1)
    pack = compile_prompt_pair_candidate_review_pack(session=session, limit=5)
    gate_counts = audit.get("preflight_gate_counts") if isinstance(audit.get("preflight_gate_counts"), dict) else {}
    blocker_counts = audit.get("preflight_blocker_counts") if isinstance(audit.get("preflight_blocker_counts"), dict) else {}
    blocker_actions = audit.get("blocker_review_actions") if isinstance(audit.get("blocker_review_actions"), list) else []
    next_actions = audit.get("next_review_actions") if isinstance(audit.get("next_review_actions"), list) else []
    ordered_blockers = sorted(((str(key), int(value)) for key, value in blocker_counts.items()), key=lambda item: (-item[1], item[0]))
    top_blocker, top_blocker_count = ordered_blockers[0] if ordered_blockers else (None, 0)
    next_action = next(
        (action for action in blocker_actions if isinstance(action, dict) and action.get("blocker") == top_blocker),
        next((action for action in next_actions if isinstance(action, dict)), None),
    )
    stable_payload = {
        "gate_counts": dict(sorted(gate_counts.items())),
        "blocker_counts": dict(sorted(blocker_counts.items())),
        "top_blocker": top_blocker,
        "candidate_worklist_count": pack.get("worklist_count", 0),
        "candidate_count": int(gate_counts.get("candidate", 0)),
        "approved_count": int(gate_counts.get("approved", 0)),
    }
    progress = {
        "progress_type": "prompt_pair_review_progress",
        "review_policy": "non_mutating_prompt_pair_progress_projection",
        "does_not_mutate_state": True,
        "does_not_promote_to_training_export": True,
        "requires_adam_gold_edit": True,
        "approved_count": int(gate_counts.get("approved", 0)),
        "candidate_count": int(gate_counts.get("candidate", 0)),
        "total_inspectable_count": int(audit.get("inspectable_pair_count", 0)),
        "invalid_pair_count": int(audit.get("invalid_pair_count", 0)),
        "preflight_mismatch_count": int(audit.get("preflight_mismatch_count", 0)),
        "blocker_counts": dict(sorted(blocker_counts.items())),
        "candidate_worklist_count": int(pack.get("worklist_count", 0)),
        "top_blocker": top_blocker,
        "top_blocker_count": top_blocker_count,
        "next_review_action": next_action,
        "completion_signal": "candidate_count_decreases_or_blocker_worklist_changes",
        "safety_boundaries": [
            "Progress counts are read-only and do not promote candidates into approved training export.",
            "Candidate rows still require Adam gold review and backend preflight clearance.",
            "A passing progress check proves workflow movement, not Charles authenticity.",
        ],
    }
    progress["content_sha256"] = hashlib.sha256(
        json.dumps(stable_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return progress


def _select_prompt_pair_worklist(
    worklists: List[Dict[str, Any]],
    *,
    blocker: str | None = None,
) -> tuple[Dict[str, Any] | None, str, str | None]:
    requested_blocker = blocker.strip() if isinstance(blocker, str) and blocker.strip() else None
    if requested_blocker:
        return (
            next((worklist for worklist in worklists if worklist.get("blocker") == requested_blocker), None),
            "requested_backend_blocker_exact_match",
            requested_blocker,
        )
    return (
        worklists[0] if worklists else None,
        "largest_backend_blocker_first",
        None,
    )


def compile_prompt_pair_top_blocker_slice(
    session: Session,
    *,
    limit: int = 5,
    blocker: str | None = None,
) -> Dict[str, Any]:
    safe_limit = max(1, min(limit, 25))
    pack = compile_prompt_pair_candidate_review_pack(session=session, limit=100)
    worklists = pack.get("worklists") if isinstance(pack.get("worklists"), list) else []
    top_worklist, selection_policy, requested_blocker = _select_prompt_pair_worklist(worklists, blocker=blocker)
    if not isinstance(top_worklist, dict):
        stable_payload = {"blocker": requested_blocker, "requested_blocker": requested_blocker, "items": []}
        return {
            "slice_type": "prompt_pair_top_blocker_slice",
            "review_policy": "top_backend_blocker_review_slice_no_export_promotion",
            "does_not_promote_to_training_export": True,
            "requires_adam_gold_edit": True,
            "selection_policy": selection_policy,
            "requested_blocker": requested_blocker,
            "blocker": requested_blocker,
            "title": f"No {requested_blocker.replace('_', ' ').title()} candidates"
            if requested_blocker
            else None,
            "candidate_count": 0,
            "reported_candidate_count": 0,
            "completion_signal": "candidate_count_decreases_or_blocker_worklist_changes",
            "safety_boundaries": [
                "Do not mark candidate text authentic until Adam gold review clears it.",
                "Do not promote any candidate row to training export from this read-only slice.",
            ],
            "recommended_action": None,
            "items": [],
            "content_sha256": hashlib.sha256(
                json.dumps(stable_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
            ).hexdigest(),
        }

    task_ids = [
        str(preview.get("task_id"))
        for preview in top_worklist.get("candidate_previews", [])
        if isinstance(preview, dict) and preview.get("task_id")
    ][:safe_limit]
    tasks_by_id = {
        task.id: task
        for task in session.exec(select(Task).where(Task.id.in_(task_ids))).all()
    }
    items = []
    for sequence_number, task_id in enumerate(task_ids, start=1):
        task = tasks_by_id.get(task_id)
        if not task:
            continue
        payload = task.input_payload or {}
        preflight = preflight_pair_export_gate(payload)
        response = _response_text(payload)
        items.append(
            {
                "sequence_number": sequence_number,
                "task_id": task.id,
                "task_human_id": task.human_id,
                "pair_index": payload.get("pair_index"),
                "artifact_mode": _string(payload.get("artifact_mode"), "sft"),
                "voice_mode": _string(payload.get("voice_mode"), "unknown"),
                "truth_status": _string(payload.get("truth_status"), "unknown"),
                "synthetic": bool(payload.get("synthetic", True)),
                "prompt": _string(payload.get("prompt")),
                "response_preview": _truncate(response, 520),
                "source_excerpt_preview": _truncate(_string(payload.get("source_excerpt")), 520),
                "context_preview": _truncate(_string(payload.get("context")), 360),
                "source_boundary_summary": _source_boundary_training_summary(payload),
                "export_preview_yaml": _string(payload.get("export_preview_yaml")) or preflight["yaml_preview"],
                "backend_preflight": {
                    "export_status": preflight["export_status"],
                    "submit_outcome": preflight["submit_outcome"],
                    "dataset_outcome": preflight["dataset_outcome"],
                    "blockers": preflight["blockers"],
                },
                "completion_criteria": [
                    "Resolve or explain the listed backend blocker in the prompt-pair editor.",
                    "Submit only when the pair is Adam-reviewed or intentionally remains a review candidate.",
                    "Confirm the candidate count or blocker worklist changes after submit.",
                ],
                "action": {
                    "action_type": "open_held_prompt_pair_candidate",
                    "label": "Open held pair",
                    "task_id": task.id,
                    "task_human_id": task.human_id,
                    "queue": task.queue,
                },
            }
        )

    stable_payload = {
        "blocker": top_worklist.get("blocker"),
        "requested_blocker": requested_blocker,
        "selection_policy": selection_policy,
        "review_sequence_key": top_worklist.get("review_sequence_key"),
        "items": items,
    }
    return {
        "slice_type": "prompt_pair_top_blocker_slice",
        "review_policy": "top_backend_blocker_review_slice_no_export_promotion",
        "does_not_promote_to_training_export": True,
        "requires_adam_gold_edit": True,
        "selection_policy": selection_policy,
        "requested_blocker": requested_blocker,
        "blocker": top_worklist.get("blocker"),
        "title": top_worklist.get("title"),
        "candidate_count": top_worklist.get("candidate_count"),
        "reported_candidate_count": len(items),
        "review_sequence_key": top_worklist.get("review_sequence_key"),
        "completion_signal": "candidate_count_decreases_or_blocker_worklist_changes",
        "safety_boundaries": [
            "Do not mark candidate text authentic until Adam gold review clears it.",
            "Do not promote any candidate row to training export from this read-only slice.",
        ],
        "recommended_action": top_worklist.get("recommended_action"),
        "items": items,
        "content_sha256": hashlib.sha256(
            json.dumps(stable_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest(),
    }


def _prompt_pair_session_field_plan(blocker: str | None) -> List[Dict[str, Any]]:
    if blocker == "dpo_rejected_reason_empty":
        return [
            {
                "field": "failure_modes",
                "prompt": "Name the concrete reason the rejected response is worse than the chosen Charles response.",
                "truth_status_after_submit": "adam_expert_reconstruction",
            },
            {
                "field": "rejected_rubric",
                "prompt": "Add plain-language context explaining why the rejected side has issues.",
                "truth_status_after_submit": "adam_expert_reconstruction",
            },
        ]
    if blocker == "source_boundary_blocks_training":
        return [
            {
                "field": "source_boundary",
                "prompt": "Decide whether the source can be used for SFT/DPO, or keep it as review-only context.",
                "truth_status_after_submit": "adam_expert_reconstruction",
            },
            {
                "field": "context",
                "prompt": "Explain any privacy, sensitivity, or source-truth reason this pair should remain held.",
                "truth_status_after_submit": "adam_expert_reconstruction",
            },
        ]
    return [
        {
            "field": "context",
            "prompt": "Explain what needs to change before this pair can move closer to approved export.",
            "truth_status_after_submit": "adam_expert_reconstruction",
        }
    ]


def _top_blocker_review_session_plan_yaml(plan: Dict[str, Any]) -> str:
    lines = [
        "prompt_pair_top_blocker_review_session_plan:",
        f"  plan_type: {_yaml_line_scalar(plan.get('plan_type'))}",
        f"  review_policy: {_yaml_line_scalar(plan.get('review_policy'))}",
        f"  selection_policy: {_yaml_line_scalar(plan.get('selection_policy'))}",
        f"  requested_blocker: {_yaml_line_scalar(plan.get('requested_blocker'))}",
        f"  blocker: {_yaml_line_scalar(plan.get('blocker'))}",
        f"  selected_count: {_yaml_line_scalar(plan.get('selected_count'))}",
        f"  candidate_count: {_yaml_line_scalar(plan.get('candidate_count'))}",
        f"  content_sha256: {_yaml_line_scalar(plan.get('content_sha256'))}",
        "  safety:",
        f"    does_not_mutate_state: {_yaml_line_scalar(plan.get('does_not_mutate_state'))}",
        f"    does_not_promote_to_training_export: {_yaml_line_scalar(plan.get('does_not_promote_to_training_export'))}",
        f"    requires_adam_gold_edit: {_yaml_line_scalar(plan.get('requires_adam_gold_edit'))}",
        "  completion_signal: " + _yaml_line_scalar(plan.get("completion_signal")),
        "  field_plan:",
    ]
    for field in plan.get("field_plan", []):
        lines.extend(
            [
                f"    - field: {_yaml_line_scalar(field.get('field'))}",
                f"      prompt: {_yaml_line_scalar(field.get('prompt'))}",
                f"      truth_status_after_submit: {_yaml_line_scalar(field.get('truth_status_after_submit'))}",
            ]
        )
    lines.append("  selected_items:")
    for item in plan.get("items", []):
        lines.extend(
            [
                f"    - sequence_number: {_yaml_line_scalar(item.get('sequence_number'))}",
                f"      task_human_id: {_yaml_line_scalar(item.get('task_human_id'))}",
                f"      pair_index: {_yaml_line_scalar(item.get('pair_index'))}",
                f"      artifact_mode: {_yaml_line_scalar(item.get('artifact_mode'))}",
                f"      voice_mode: {_yaml_line_scalar(item.get('voice_mode'))}",
                f"      prompt: {_yaml_line_scalar(item.get('prompt'))}",
                "      blockers:",
            ]
        )
        for blocker in item.get("current_blockers", []):
            lines.append(f"        - {_yaml_line_scalar(blocker)}")
        source_boundary_summary = item.get("source_boundary_summary") if isinstance(item.get("source_boundary_summary"), dict) else {}
        if source_boundary_summary:
            lines.extend(
                [
                    "      source_boundary_summary:",
                    f"        status: {_yaml_line_scalar(source_boundary_summary.get('status'))}",
                    f"        privacy_level: {_yaml_line_scalar(source_boundary_summary.get('privacy_level'))}",
                    f"        usable_for_sft: {_yaml_line_scalar(source_boundary_summary.get('usable_for_sft'))}",
                    f"        usable_for_dpo: {_yaml_line_scalar(source_boundary_summary.get('usable_for_dpo'))}",
                    "        blocked_training_uses:",
                ]
            )
            for blocked_use in source_boundary_summary.get("blocked_training_uses") or []:
                lines.append(f"          - {_yaml_line_scalar(blocked_use)}")
        lines.extend(
            [
                f"      action: {_yaml_line_scalar((item.get('action') or {}).get('action_type'))}",
                f"      completion_criteria: {_yaml_line_scalar('; '.join(item.get('completion_criteria', [])[:2]))}",
            ]
        )
    return "\n".join(lines) + "\n"


def _repair_projection_after_gate(after: Dict[str, Any]) -> Dict[str, Any]:
    blockers = [str(blocker) for blocker in after.get("blockers") or [] if str(blocker).strip()]
    if "needs_adam_gold_edit" not in blockers:
        blockers.append("needs_adam_gold_edit")
    return {
        "export_status": "candidate",
        "dataset_outcome": "Candidate dry-run only",
        "blockers": blockers,
    }


def compile_prompt_pair_top_blocker_review_session_plan(
    session: Session,
    *,
    limit: int = 5,
    blocker: str | None = None,
) -> Dict[str, Any]:
    safe_limit = max(1, min(limit, 25))
    blocker_slice = compile_prompt_pair_top_blocker_slice(session=session, limit=safe_limit, blocker=blocker)
    blocker = blocker_slice.get("blocker")
    items = []
    for item in blocker_slice.get("items", []):
        backend_preflight = item.get("backend_preflight") if isinstance(item.get("backend_preflight"), dict) else {}
        items.append(
            {
                "sequence_number": item.get("sequence_number"),
                "task_id": item.get("task_id"),
                "task_human_id": item.get("task_human_id"),
                "pair_index": item.get("pair_index"),
                "artifact_mode": item.get("artifact_mode"),
                "voice_mode": item.get("voice_mode"),
                "blocker": blocker,
                "prompt": item.get("prompt"),
                "current_blockers": backend_preflight.get("blockers") if isinstance(backend_preflight.get("blockers"), list) else [],
                "source_boundary_summary": item.get("source_boundary_summary") if isinstance(item.get("source_boundary_summary"), dict) else None,
                "completion_criteria": item.get("completion_criteria") if isinstance(item.get("completion_criteria"), list) else [],
                "action": item.get("action") if isinstance(item.get("action"), dict) else {},
            }
        )
    selected_task_ids = [str(item.get("task_id")) for item in items if item.get("task_id")]
    field_plan = _prompt_pair_session_field_plan(str(blocker) if blocker else None)
    stable_payload = {
        "blocker": blocker,
        "requested_blocker": blocker_slice.get("requested_blocker"),
        "selection_policy": blocker_slice.get("selection_policy"),
        "selected_task_ids": selected_task_ids,
        "field_plan": field_plan,
        "slice_content_sha256": blocker_slice.get("content_sha256"),
    }
    plan = {
        "plan_type": "prompt_pair_top_blocker_review_session_plan",
        "review_policy": "non_mutating_prompt_pair_batch_plan_no_export_promotion",
        "does_not_mutate_state": True,
        "does_not_promote_to_training_export": True,
        "requires_adam_gold_edit": True,
        "selection_policy": blocker_slice.get("selection_policy"),
        "requested_blocker": blocker_slice.get("requested_blocker"),
        "blocker": blocker,
        "title": blocker_slice.get("title"),
        "selected_count": len(items),
        "candidate_count": int(blocker_slice.get("candidate_count") or 0),
        "selected_task_ids": selected_task_ids,
        "review_sequence_key": blocker_slice.get("review_sequence_key"),
        "source_slice_content_sha256": blocker_slice.get("content_sha256"),
        "completion_signal": "selected_prompt_pair_blocker_batch_submitted_then_candidate_count_or_worklist_changes",
        "projected_task_delta": {
            "would_create_tasks": 0,
            "would_open_existing_tasks": len(items),
            "raw_sources_mutated": False,
            "approved_exports_created": 0,
        },
        "field_plan": field_plan,
        "safety_boundaries": [
            "This plan opens existing prompt-pair review tickets only.",
            "It does not create approved SFT/DPO rows or mutate raw source files.",
            "Completion requires Adam gold edit review and a changed blocker count or worklist hash.",
        ],
        "items": items,
    }
    plan["content_sha256"] = hashlib.sha256(
        json.dumps(stable_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    export_preview_yaml = _top_blocker_review_session_plan_yaml(plan)
    plan["export_preview_yaml"] = export_preview_yaml
    plan["export_preview_sha256"] = hashlib.sha256(export_preview_yaml.encode("utf-8")).hexdigest()
    return plan


def _dpo_reason_repair_item(task: Task, sequence_number: int) -> Dict[str, Any]:
    payload = task.input_payload or {}
    compiled = compile_pair_export(payload)
    preflight = preflight_pair_export_gate(payload)
    current_failure_modes = _list_strings(payload.get("failure_modes"))
    suggested_failure_modes = _suggest_dpo_failure_modes(payload, compiled)
    suggested_rejected_issue = _suggest_dpo_rejected_issue_note(
        suggested_failure_modes,
        _string(payload.get("voice_mode"), "unknown"),
    )
    repaired_preflight = preflight_pair_export_gate({**payload, "failure_modes": suggested_failure_modes})
    projected_after = _repair_projection_after_gate(repaired_preflight)
    before_blockers = list(preflight["blockers"])
    after_blockers = list(projected_after["blockers"])
    response_rubric = payload.get("response_rubric") if isinstance(payload.get("response_rubric"), dict) else {}
    rejected_rubric = response_rubric.get("response_a") if isinstance(response_rubric.get("response_a"), dict) else {}
    return {
        "sequence_number": sequence_number,
        "task_id": task.id,
        "task_human_id": task.human_id,
        "pair_index": payload.get("pair_index"),
        "artifact_mode": "dpo",
        "voice_mode": _string(payload.get("voice_mode"), "unknown"),
        "truth_status": _string(payload.get("truth_status"), "unknown"),
        "rejected_truth_status": _string(payload.get("rejected_truth_status"), "model_generated"),
        "synthetic": bool(payload.get("synthetic", True)),
        "source_title": _source_key(payload),
        "prompt": compiled["prompt"],
        "chosen_preview": _truncate(compiled["chosen"], 900),
        "rejected_preview": _truncate(compiled["rejected"], 900),
        "current_failure_modes": current_failure_modes,
        "rejected_rubric": rejected_rubric,
        "backend_preflight": {
            "export_status": preflight["export_status"],
            "dataset_outcome": preflight["dataset_outcome"],
            "blockers": preflight["blockers"],
        },
        "repair_fields": ["failure_modes", "response_rubric.response_a", "rubric_summary.rejected_issue_count"],
        "suggested_failure_modes": suggested_failure_modes,
        "suggested_rejected_issue": suggested_rejected_issue,
        "repair_guidance": (
            "Add at least one plain-language failure mode or rejected-side rubric issue explaining why "
            "the rejected response is worse than the chosen response."
        ),
        "repair_projection": {
            "projection_type": "non_mutating_dpo_reason_patch",
            "does_not_mutate_task": True,
            "input_patch": {"failure_modes": suggested_failure_modes},
            "before_blockers": before_blockers,
            "after_blockers": after_blockers,
            "cleared_blockers": [blocker for blocker in before_blockers if blocker not in after_blockers],
            "target_blocker_cleared": "dpo_rejected_reason_empty" in before_blockers
            and "dpo_rejected_reason_empty" not in after_blockers,
            "after_export_status": projected_after["export_status"],
            "after_dataset_outcome": projected_after["dataset_outcome"],
            "still_requires_adam_gold_edit": True,
            "note": "This projection only tests the rejected-side reason field; it does not certify Charles authenticity.",
        },
        "completion_criteria": [
            "`failure_modes` contains at least one concrete reason, or rejected-side rubric notes generate one.",
            "Backend preflight no longer reports `dpo_rejected_reason_empty`.",
            "Pair remains review_candidate until Adam confirms the chosen side is gold.",
        ],
        "action": {
            "action_type": "open_held_prompt_pair_candidate",
            "label": "Open DPO repair candidate",
            "task_id": task.id,
            "task_human_id": task.human_id,
            "queue": task.queue,
        },
    }


def _repair_projection_yaml(
    *,
    task: Task,
    before_blockers: List[str],
    after_blockers: List[str],
    before_export_status: str,
    after_export_status: str,
    current_failure_modes: List[str],
    suggested_failure_modes: List[str],
) -> Dict[str, str]:
    def render_doc(label: str, failure_modes: List[str], blockers: List[str], export_status: str) -> str:
        lines = [
            "dpo_rejected_reason_repair_projection:",
            f"  state: {_yaml_line_scalar(label)}",
            f"  task_human_id: {_yaml_line_scalar(task.human_id)}",
            f"  export_status: {_yaml_line_scalar(export_status)}",
            "  failure_modes:",
        ]
        if failure_modes:
            lines.extend(f"    - {_yaml_line_scalar(mode)}" for mode in failure_modes)
        else:
            lines.append("    []")
        lines.append("  blockers:")
        if blockers:
            lines.extend(f"    - {_yaml_line_scalar(blocker)}" for blocker in blockers)
        else:
            lines.append("    []")
        return "\n".join(lines) + "\n"

    before_yaml = render_doc("before", current_failure_modes, before_blockers, before_export_status)
    after_yaml = render_doc("after", suggested_failure_modes, after_blockers, after_export_status)
    diff = "\n".join(
        unified_diff(
            before_yaml.splitlines(),
            after_yaml.splitlines(),
            fromfile="before_dpo_repair.yaml",
            tofile="after_dpo_repair.yaml",
            lineterm="",
        )
    )
    return {"before_yaml": before_yaml, "after_yaml": after_yaml, "yaml_diff_preview": diff + "\n"}


DEFAULT_DPO_REPAIR_FAILURE_MODE = "too_generic_not_charles_voice"


def compile_dpo_rejected_reason_repair_projection(
    session: Session,
    *,
    task_id: str | None = None,
    failure_mode: str = DEFAULT_DPO_REPAIR_FAILURE_MODE,
) -> Dict[str, Any]:
    tasks = session.exec(
        select(Task)
        .where(Task.task_type == "gold_voice_edit")
        .where(Task.status == "ready")
        .where(Task.queue == "prompt_pairs_needing_gold_edits")
        .order_by(Task.priority.desc(), Task.created_at.asc())
    ).all()
    selected_task = None
    for task in tasks:
        if task_id and task.id != task_id and task.human_id != task_id:
            continue
        payload = task.input_payload or {}
        if _string(payload.get("artifact_mode"), "sft") != "dpo":
            continue
        preflight = preflight_pair_export_gate(payload)
        if "dpo_rejected_reason_empty" not in preflight["blockers"]:
            continue
        selected_task = task
        break
    if selected_task is None:
        return {
            "projection_type": "dpo_rejected_reason_repair_projection",
            "review_policy": "non_mutating_single_candidate_projection",
            "does_not_mutate_task": True,
            "found": False,
            "reason": "no_matching_dpo_rejected_reason_candidate",
        }

    payload = selected_task.input_payload or {}
    compiled = compile_pair_export(payload)
    before = preflight_pair_export_gate(payload)
    current_failure_modes = _list_strings(payload.get("failure_modes"))
    suggested_failure_modes = (
        _suggest_dpo_failure_modes(payload, compiled)
        if failure_mode == DEFAULT_DPO_REPAIR_FAILURE_MODE
        else [failure_mode]
    )
    suggested_rejected_issue = _suggest_dpo_rejected_issue_note(
        suggested_failure_modes,
        _string(payload.get("voice_mode"), "unknown"),
    )
    repaired_payload = {**payload, "failure_modes": suggested_failure_modes}
    after = preflight_pair_export_gate(repaired_payload)
    projected_after = _repair_projection_after_gate(after)
    before_blockers = list(before["blockers"])
    after_blockers = list(projected_after["blockers"])
    yaml_projection = _repair_projection_yaml(
        task=selected_task,
        before_blockers=before_blockers,
        after_blockers=after_blockers,
        before_export_status=before["export_status"],
        after_export_status=projected_after["export_status"],
        current_failure_modes=current_failure_modes,
        suggested_failure_modes=suggested_failure_modes,
    )
    stable_payload = {
        "task_id": selected_task.id,
        "input_patch": {"failure_modes": suggested_failure_modes},
        "before_blockers": before_blockers,
        "after_blockers": after_blockers,
        "yaml_diff_preview": yaml_projection["yaml_diff_preview"],
        "suggested_rejected_issue": suggested_rejected_issue,
    }
    return {
        "projection_type": "dpo_rejected_reason_repair_projection",
        "review_policy": "non_mutating_single_candidate_projection",
        "does_not_mutate_task": True,
        "does_not_promote_to_training_export": True,
        "requires_adam_gold_edit": True,
        "found": True,
        "task_id": selected_task.id,
        "task_human_id": selected_task.human_id,
        "voice_mode": _string(payload.get("voice_mode"), "unknown"),
        "source_title": _source_key(payload),
        "prompt": compiled["prompt"],
        "chosen_preview": _truncate(compiled["chosen"], 900),
        "rejected_preview": _truncate(compiled["rejected"], 900),
        "input_patch": {"failure_modes": suggested_failure_modes},
        "suggested_rejected_issue": suggested_rejected_issue,
        "before": {
            "failure_modes": current_failure_modes,
            "export_status": before["export_status"],
            "dataset_outcome": before["dataset_outcome"],
            "blockers": before_blockers,
        },
        "after": {
            "failure_modes": suggested_failure_modes,
            "export_status": projected_after["export_status"],
            "dataset_outcome": projected_after["dataset_outcome"],
            "blockers": after_blockers,
        },
        "cleared_blockers": [blocker for blocker in before_blockers if blocker not in after_blockers],
        "target_blocker_cleared": "dpo_rejected_reason_empty" in before_blockers
        and "dpo_rejected_reason_empty" not in after_blockers,
        "still_requires_adam_gold_edit": True,
        "export_preview_before": before["yaml_preview"],
        "export_preview_after": after["yaml_preview"],
        "export_preview_changed": before["yaml_preview"] != after["yaml_preview"],
        **yaml_projection,
        "content_sha256": hashlib.sha256(
            json.dumps(stable_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest(),
    }


def _dpo_repair_packet_yaml(packet: Dict[str, Any]) -> str:
    lines = [
        "dpo_rejected_reason_repair_packet:",
        f"  review_policy: {_yaml_line_scalar(packet.get('review_policy'))}",
        f"  blocker: {_yaml_line_scalar(packet.get('blocker'))}",
        f"  total_candidate_count: {int(packet.get('total_candidate_count') or 0)}",
        f"  reported_candidate_count: {int(packet.get('reported_candidate_count') or 0)}",
        f"  completion_signal: {_yaml_line_scalar(packet.get('completion_signal'))}",
        "  safety_boundaries:",
    ]
    for boundary in packet.get("safety_boundaries") or []:
        lines.append(f"    - {_yaml_line_scalar(boundary)}")
    lines.append("  items:")
    for item in packet.get("items") or []:
        if not isinstance(item, dict):
            continue
        lines.extend(
            [
                f"    - sequence_number: {int(item.get('sequence_number') or 0)}",
                f"      task_human_id: {_yaml_line_scalar(item.get('task_human_id'))}",
                f"      pair_index: {_yaml_line_scalar(item.get('pair_index'))}",
                f"      voice_mode: {_yaml_line_scalar(item.get('voice_mode'))}",
                f"      prompt: {_yaml_line_scalar(item.get('prompt'))}",
                "      chosen_preview: |-",
                _indent_yaml_block(str(item.get("chosen_preview") or ""), 8),
                "      rejected_preview: |-",
                _indent_yaml_block(str(item.get("rejected_preview") or ""), 8),
                "      current_failure_modes:",
            ]
        )
        failure_modes = item.get("current_failure_modes") if isinstance(item.get("current_failure_modes"), list) else []
        if failure_modes:
            for mode in failure_modes:
                lines.append(f"        - {_yaml_line_scalar(mode)}")
        else:
            lines[-1] = "      current_failure_modes: []"
        lines.append("      suggested_failure_modes:")
        suggested_modes = item.get("suggested_failure_modes") if isinstance(item.get("suggested_failure_modes"), list) else []
        if suggested_modes:
            for mode in suggested_modes:
                lines.append(f"        - {_yaml_line_scalar(mode)}")
        else:
            lines[-1] = "      suggested_failure_modes: []"
        suggested_issue = item.get("suggested_rejected_issue") if isinstance(item.get("suggested_rejected_issue"), dict) else {}
        lines.extend(
            [
                "      suggested_rejected_issue:",
                f"        severity: {_yaml_line_scalar(suggested_issue.get('severity'))}",
                f"        rubric_target: {_yaml_line_scalar(suggested_issue.get('rubric_target'))}",
                f"        issue_tag: {_yaml_line_scalar(suggested_issue.get('issue_tag'))}",
                "        note: |-",
                _indent_yaml_block(str(suggested_issue.get("note") or ""), 10),
            ]
        )
        lines.extend(
            [
                "      backend_blockers:",
            ]
        )
        blockers = (item.get("backend_preflight") or {}).get("blockers") if isinstance(item.get("backend_preflight"), dict) else []
        if blockers:
            for blocker in blockers:
                lines.append(f"        - {_yaml_line_scalar(blocker)}")
        else:
            lines[-1] = "      backend_blockers: []"
        lines.extend(
            [
                f"      repair_guidance: {_yaml_line_scalar(item.get('repair_guidance'))}",
                f"      projected_target_blocker_cleared: {str((item.get('repair_projection') or {}).get('target_blocker_cleared') is True).lower()}",
                f"      projected_after_export_status: {_yaml_line_scalar((item.get('repair_projection') or {}).get('after_export_status'))}",
                f"      projected_after_dataset_outcome: {_yaml_line_scalar((item.get('repair_projection') or {}).get('after_dataset_outcome'))}",
                "      projected_after_blockers:",
            ]
        )
        after_blockers = (item.get("repair_projection") or {}).get("after_blockers")
        if isinstance(after_blockers, list) and after_blockers:
            for blocker in after_blockers:
                lines.append(f"        - {_yaml_line_scalar(blocker)}")
        else:
            lines[-1] = "      projected_after_blockers: []"
        lines.extend(
            [
                "      completion_criteria:",
            ]
        )
        for criterion in item.get("completion_criteria") or []:
            lines.append(f"        - {_yaml_line_scalar(criterion)}")
    return "\n".join(lines) + "\n"


def compile_dpo_rejected_reason_repair_packet(session: Session, *, limit: int = 25) -> Dict[str, Any]:
    safe_limit = max(1, min(limit, 100))
    tasks = session.exec(
        select(Task)
        .where(Task.task_type == "gold_voice_edit")
        .where(Task.queue == "prompt_pairs_needing_gold_edits")
        .order_by(Task.created_at.asc())
    ).all()
    matching_tasks = []
    for task in tasks:
        payload = task.input_payload or {}
        if _string(payload.get("artifact_mode"), "sft") != "dpo":
            continue
        preflight = preflight_pair_export_gate(payload)
        if "dpo_rejected_reason_empty" not in preflight["blockers"]:
            continue
        matching_tasks.append(task)

    items = [_dpo_reason_repair_item(task, index) for index, task in enumerate(matching_tasks[:safe_limit], start=1)]
    stable_payload = {
        "blocker": "dpo_rejected_reason_empty",
        "candidate_task_ids": [task.id for task in matching_tasks],
        "reported_items": items,
    }
    packet = {
        "packet_type": "dpo_rejected_reason_repair_packet",
        "review_policy": "repair_dpo_reason_only_no_training_export",
        "does_not_promote_to_training_export": True,
        "requires_adam_gold_edit": True,
        "blocker": "dpo_rejected_reason_empty",
        "total_candidate_count": len(matching_tasks),
        "reported_candidate_count": len(items),
        "limit": safe_limit,
        "completion_signal": "dpo_rejected_reason_empty_count_decreases_after_repair",
        "repair_fields": ["failure_modes", "response_rubric.response_a", "rubric_summary.rejected_issue_count"],
        "safety_boundaries": [
            "Do not promote repaired DPO candidates to approved training export until Adam reviews the chosen side.",
            "Rejected-side reasons describe model or draft failure modes; they are not new memory claims.",
            "This read-only packet does not mutate prompt-pair tasks.",
        ],
        "items": items,
    }
    packet["content_sha256"] = hashlib.sha256(
        json.dumps(stable_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    packet["export_preview_yaml"] = _dpo_repair_packet_yaml(packet)
    packet["export_preview_sha256"] = hashlib.sha256(packet["export_preview_yaml"].encode("utf-8")).hexdigest()
    return packet


def _source_boundary_review_item(task: Task, sequence_number: int) -> Dict[str, Any]:
    payload = task.input_payload or {}
    preflight = preflight_pair_export_gate(payload)
    artifact_mode = _string(payload.get("artifact_mode"), "sft")
    boundary = payload.get("boundary_snapshot") if isinstance(payload.get("boundary_snapshot"), dict) else {}
    summary = _source_boundary_training_summary(payload) or {}
    permission_field = "usable_for_dpo" if artifact_mode == "dpo" else "usable_for_sft"
    return {
        "sequence_number": sequence_number,
        "task_id": task.id,
        "task_human_id": task.human_id,
        "pair_index": payload.get("pair_index"),
        "artifact_mode": artifact_mode,
        "voice_mode": _string(payload.get("voice_mode"), "unknown"),
        "truth_status": _string(payload.get("truth_status"), "unknown"),
        "synthetic": bool(payload.get("synthetic", True)),
        "source_title": _source_key(payload),
        "source_photo_id": _string(payload.get("source_photo_id")),
        "prompt": _string(payload.get("prompt")),
        "response_preview": _truncate(_response_text(payload), 720),
        "source_excerpt_preview": _truncate(_string(payload.get("source_excerpt")), 520),
        "source_boundary_summary": summary,
        "blocking_permission_field": permission_field,
        "blocking_permission_value": boundary.get(permission_field),
        "backend_preflight": {
            "export_status": preflight["export_status"],
            "dataset_outcome": preflight["dataset_outcome"],
            "blockers": preflight["blockers"],
        },
        "review_decision_fields": [
            "boundary_snapshot.usable_for_sft",
            "boundary_snapshot.usable_for_dpo",
            "context",
            "rubric_summary.preferred_export_blocked",
        ],
        "remediation_options": summary.get("remediation_options") if isinstance(summary.get("remediation_options"), list) else [],
        "completion_criteria": [
            f"Confirm whether `{permission_field}` should remain false for this source.",
            "If Adam clears the source for training, update the source boundary before submitting the pair.",
            "If not cleared, keep the pair as review-only context and preserve the blocker.",
        ],
        "action": {
            "action_type": "open_held_prompt_pair_candidate",
            "label": "Open source-boundary candidate",
            "task_id": task.id,
            "task_human_id": task.human_id,
            "queue": task.queue,
        },
    }


def _source_boundary_review_packet_yaml(packet: Dict[str, Any]) -> str:
    lines = [
        "source_boundary_training_review_packet:",
        f"  review_policy: {_yaml_line_scalar(packet.get('review_policy'))}",
        f"  blocker: {_yaml_line_scalar(packet.get('blocker'))}",
        f"  total_candidate_count: {int(packet.get('total_candidate_count') or 0)}",
        f"  reported_candidate_count: {int(packet.get('reported_candidate_count') or 0)}",
        f"  completion_signal: {_yaml_line_scalar(packet.get('completion_signal'))}",
        "  safety_boundaries:",
    ]
    for boundary in packet.get("safety_boundaries") or []:
        lines.append(f"    - {_yaml_line_scalar(boundary)}")
    lines.append("  items:")
    for item in packet.get("items") or []:
        if not isinstance(item, dict):
            continue
        lines.extend(
            [
                f"    - sequence_number: {int(item.get('sequence_number') or 0)}",
                f"      task_human_id: {_yaml_line_scalar(item.get('task_human_id'))}",
                f"      pair_index: {_yaml_line_scalar(item.get('pair_index'))}",
                f"      artifact_mode: {_yaml_line_scalar(item.get('artifact_mode'))}",
                f"      voice_mode: {_yaml_line_scalar(item.get('voice_mode'))}",
                f"      source_photo_id: {_yaml_line_scalar(item.get('source_photo_id'))}",
                f"      blocking_permission_field: {_yaml_line_scalar(item.get('blocking_permission_field'))}",
                f"      blocking_permission_value: {_yaml_line_scalar(item.get('blocking_permission_value'))}",
                f"      prompt: {_yaml_line_scalar(item.get('prompt'))}",
                "      response_preview: |-",
                _indent_yaml_block(str(item.get("response_preview") or ""), 8),
                "      backend_blockers:",
            ]
        )
        blockers = (item.get("backend_preflight") or {}).get("blockers") if isinstance(item.get("backend_preflight"), dict) else []
        if blockers:
            for blocker in blockers:
                lines.append(f"        - {_yaml_line_scalar(blocker)}")
        else:
            lines[-1] = "      backend_blockers: []"
        summary = item.get("source_boundary_summary") if isinstance(item.get("source_boundary_summary"), dict) else {}
        lines.extend(
            [
                "      source_boundary_summary:",
                f"        status: {_yaml_line_scalar(summary.get('status'))}",
                f"        privacy_level: {_yaml_line_scalar(summary.get('privacy_level'))}",
                f"        usable_for_sft: {_yaml_line_scalar(summary.get('usable_for_sft'))}",
                f"        usable_for_dpo: {_yaml_line_scalar(summary.get('usable_for_dpo'))}",
                f"        usable_for_eval: {_yaml_line_scalar(summary.get('usable_for_eval'))}",
                f"        reviewed_by: {_yaml_line_scalar(summary.get('reviewed_by'))}",
                "        blocked_training_uses:",
            ]
        )
        blocked_uses = summary.get("blocked_training_uses") if isinstance(summary.get("blocked_training_uses"), list) else []
        if blocked_uses:
            for blocked_use in blocked_uses:
                lines.append(f"          - {_yaml_line_scalar(blocked_use)}")
        else:
            lines[-1] = "        blocked_training_uses: []"
        lines.append("      remediation_options:")
        remediation_options = item.get("remediation_options") if isinstance(item.get("remediation_options"), list) else []
        if remediation_options:
            for option in remediation_options:
                lines.append(f"        - {_yaml_line_scalar(option)}")
        else:
            lines[-1] = "      remediation_options: []"
        lines.append("      completion_criteria:")
        for criterion in item.get("completion_criteria") or []:
            lines.append(f"        - {_yaml_line_scalar(criterion)}")
    return "\n".join(lines) + "\n"


def compile_source_boundary_training_review_packet(session: Session, *, limit: int = 25) -> Dict[str, Any]:
    safe_limit = max(1, min(limit, 100))
    tasks = session.exec(
        select(Task)
        .where(Task.task_type == "gold_voice_edit")
        .where(Task.queue == "prompt_pairs_needing_gold_edits")
        .order_by(Task.created_at.asc())
    ).all()
    matching_tasks = []
    for task in tasks:
        preflight = preflight_pair_export_gate(task.input_payload or {})
        if "source_boundary_blocks_training" in preflight["blockers"]:
            matching_tasks.append(task)

    items = [_source_boundary_review_item(task, index) for index, task in enumerate(matching_tasks[:safe_limit], start=1)]
    stable_payload = {
        "blocker": "source_boundary_blocks_training",
        "candidate_task_ids": [task.id for task in matching_tasks],
        "reported_items": items,
    }
    packet = {
        "packet_type": "source_boundary_training_review_packet",
        "review_policy": "review_source_boundary_training_permission_no_source_mutation",
        "does_not_mutate_task": True,
        "does_not_mutate_source": True,
        "does_not_promote_to_training_export": True,
        "requires_adam_boundary_review": True,
        "requires_adam_gold_edit": True,
        "blocker": "source_boundary_blocks_training",
        "total_candidate_count": len(matching_tasks),
        "reported_candidate_count": len(items),
        "limit": safe_limit,
        "completion_signal": "source_boundary_blocks_training_count_decreases_or_review_only_decision_recorded",
        "safety_boundaries": [
            "This packet is read-only and does not change source asset permissions.",
            "Photo-derived prompt pairs remain training-blocked until Adam explicitly clears the source boundary.",
            "Boundary review is separate from judging whether the Charles voice edit is gold.",
        ],
        "items": items,
    }
    packet["content_sha256"] = hashlib.sha256(
        json.dumps(stable_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    packet["export_preview_yaml"] = _source_boundary_review_packet_yaml(packet)
    packet["export_preview_sha256"] = hashlib.sha256(packet["export_preview_yaml"].encode("utf-8")).hexdigest()
    return packet


def compile_prompt_pair_audit_pack(session: Session, *, sample_limit: int = 20) -> Dict[str, Any]:
    audit = compile_prompt_pair_audit(session=session, sample_limit=sample_limit)
    tasks = session.exec(
        select(Task)
        .where(Task.task_type == "gold_voice_edit")
        .where(Task.queue == "prompt_pairs_needing_gold_edits")
        .order_by(Task.created_at.asc())
    ).all()
    capped_sample_limit = max(1, min(sample_limit, AUDIT_PACK_SAMPLE_LIMIT))
    sampled_tasks = _sample_tasks_for_audit_pack(tasks, capped_sample_limit)
    samples = [_task_sample(task, index) for index, task in enumerate(sampled_tasks, start=1)]
    represented_modes = sorted({sample["voice_mode"] for sample in samples})
    missing_modes = [mode for mode in REQUIRED_AUDIT_MODES if mode not in represented_modes]
    markdown = _audit_pack_markdown(audit, samples)
    content_sha256 = hashlib.sha256(markdown.encode("utf-8")).hexdigest()
    return {
        "pack_type": "prompt_pair_human_audit_pack",
        "total_pairs": audit["total_pairs"],
        "inspectable_pair_count": audit["inspectable_pair_count"],
        "invalid_pair_count": audit["invalid_pair_count"],
        "quality_counts": audit["quality_counts"],
        "voice_mode_counts": audit["voice_mode_counts"],
        "sample_count": len(samples),
        "sample_limit_cap": AUDIT_PACK_SAMPLE_LIMIT,
        "required_modes": REQUIRED_AUDIT_MODES,
        "represented_modes": represented_modes,
        "missing_required_modes": missing_modes,
        "representative_requirements_met": len(samples) >= min(sample_limit, len(tasks)) and not missing_modes,
        "known_weak_spots": audit["known_weak_spots"],
        "samples": samples,
        "markdown": markdown,
        "content_sha256": content_sha256,
    }
