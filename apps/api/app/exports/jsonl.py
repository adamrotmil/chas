import json
from typing import Any, Dict, Iterable, List

from sqlmodel import Session, select

from app.models import ContextPack, DPOPair, GoldVoiceExample, PromptSpec, SFTCandidate, Task, TaskReceipt
from app.services.pair_export import dpo_export_blockers, sft_export_blockers, source_section_export_blockers


DEFAULT_SYSTEM_PROMPT = "You are Charles Rotmil."
RUBRIC_CRITERIA = [
    "voice_authenticity",
    "grounding_truth",
    "restraint",
    "concrete_detail",
    "prompt_fit",
    "privacy_export_safety",
]


def to_jsonl(items: Iterable[Dict[str, Any]]) -> str:
    rows = [json.dumps(item, ensure_ascii=False) for item in items]
    return "\n".join(rows) + ("\n" if rows else "")


def _gold_export_metadata(session: Session, gold_id: str, export_status: str) -> Dict[str, Any]:
    gold = session.get(GoldVoiceExample, gold_id)
    downstream_use = gold.downstream_use if gold and isinstance(gold.downstream_use, dict) else {}
    context = _context_for(session, gold)
    return {
        "source_gold_voice_example_id": gold_id,
        "truth_status": gold.truth_status if gold else "adam_expert_reconstruction",
        "voice_mode": gold.voice_mode if gold else None,
        "synthetic": downstream_use.get("synthetic"),
        "artifact_mode": downstream_use.get("artifact_mode"),
        "quality_status": export_status,
        "context": downstream_use.get("context"),
        "grounding_asset_id": downstream_use.get("grounding_asset_id"),
        "source_annotation_id": downstream_use.get("source_annotation_id"),
        "export_preview_yaml": downstream_use.get("export_preview_yaml"),
        "boundary_snapshot": context.boundaries_snapshot if context else downstream_use.get("boundary_snapshot"),
    }


def _sft_payload(session: Session, candidate: SFTCandidate) -> Dict[str, Any]:
    metadata = _gold_export_metadata(session, candidate.source_gold_voice_example_id, candidate.export_status)
    quality_gate = candidate.quality_gate if isinstance(candidate.quality_gate, dict) else {}
    review_blockers = _list_strings(quality_gate.get("export_blockers"))
    if candidate.export_status != "approved" and not review_blockers:
        review_blockers.append("candidate_status_requires_review")
    metadata["quality_gate"] = quality_gate
    metadata["review_blockers"] = review_blockers
    return {
        "messages": candidate.messages,
        "metadata": metadata,
    }


def _system_prompt_for_gold(session: Session, gold_id: str) -> str:
    gold = session.get(GoldVoiceExample, gold_id)
    if gold and gold.prompt_spec_id:
        prompt_spec = session.get(PromptSpec, gold.prompt_spec_id)
        if prompt_spec and isinstance(prompt_spec.metadata_json, dict):
            prompt = prompt_spec.metadata_json.get("system_prompt")
            if isinstance(prompt, str) and prompt.strip():
                return prompt
    sft = session.exec(select(SFTCandidate).where(SFTCandidate.source_gold_voice_example_id == gold_id)).first()
    if sft and sft.messages:
        first = sft.messages[0]
        if first.get("role") == "system" and first.get("content"):
            return first["content"]
    return DEFAULT_SYSTEM_PROMPT


def _dpo_payload(session: Session, pair: DPOPair) -> Dict[str, Any]:
    return {
        "input": {
            "messages": [
                {
                    "role": "system",
                    "content": _system_prompt_for_gold(session, pair.source_gold_voice_example_id),
                },
                {"role": "user", "content": pair.prompt},
            ]
        },
        "preferred_output": pair.chosen,
        "non_preferred_output": pair.rejected,
        "metadata": {
            **_gold_export_metadata(session, pair.source_gold_voice_example_id, pair.export_status),
            "reason": pair.reason,
        },
    }


def _prompt_pair_response(payload: Dict[str, Any]) -> str:
    if payload.get("artifact_mode") == "dpo":
        return str(payload.get("chosen") or "")
    return str(payload.get("content") or payload.get("chosen") or payload.get("adam_gold_edit") or "")


def _list_strings(value: Any) -> List[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def _rubric_side(response_rubric: Any, side: str) -> Dict[str, Any]:
    if not isinstance(response_rubric, dict):
        return {}
    value = response_rubric.get(side)
    return value if isinstance(value, dict) else {}


def _fallback_dpo_response_rubric(reason: List[str]) -> Dict[str, Any]:
    chosen = {
        key: {
            "status": "no_issues",
            "notes": "Preferred candidate side; Adam review is still required before export.",
            "issue_tags": [],
        }
        for key in RUBRIC_CRITERIA
    }
    rejected = {
        key: {
            "status": "no_issues",
            "notes": "No specific issue marked for this criterion in the legacy DPO candidate.",
            "issue_tags": [],
        }
        for key in RUBRIC_CRITERIA
    }
    rejected["voice_authenticity"] = {
        "status": "minor_issues",
        "notes": reason[0] if reason else "Rejected side needs Adam review for Charles voice authenticity.",
        "issue_tags": ["too_generic", "not_charles_voice"],
    }
    if len(reason) > 1:
        rejected["concrete_detail"] = {
            "status": "minor_issues",
            "notes": reason[1],
            "issue_tags": ["lost_specificity", "generic_detail"],
        }
    return {
        "response_a": rejected,
        "response_b": chosen,
        "rubric_source": "export_fallback_from_dpo_reason_requires_adam_review",
    }


def _dpo_reason(payload: Dict[str, Any]) -> List[str]:
    reason = _list_strings(payload.get("dpo_reason")) or _list_strings(payload.get("failure_modes"))
    if reason:
        expanded = {
            "synthetic_rejected_response_needs_adam_review": (
                "review_status: Rejected was synthesized as a comparison target and requires Adam review before export."
            ),
            "generic_rejected_response_lacks_charles_voice": (
                "voice_authenticity: Rejected is generic explanatory prose rather than Charles' cadence, concrete aside, and intimate sign-off."
            ),
        }
        return [expanded.get(item, item) for item in reason]
    response_rubric = payload.get("response_rubric")
    rejected = _rubric_side(response_rubric, "response_a")
    derived: List[str] = []
    for key, decision in rejected.items():
        if not isinstance(decision, dict):
            continue
        if decision.get("status") not in {"minor_issues", "major_issues"}:
            continue
        note = str(decision.get("notes") or "").strip()
        if note:
            derived.append(f"{key}: {note}")
    return derived


def _dpo_response_rubric(payload: Dict[str, Any], reason: List[str]) -> Dict[str, Any]:
    rubric = payload.get("response_rubric")
    if isinstance(rubric, dict) and _rubric_side(rubric, "response_a") and _rubric_side(rubric, "response_b"):
        return rubric
    return _fallback_dpo_response_rubric(reason)


def _rubric_issue_summary(rubric: Dict[str, Any]) -> Dict[str, Any]:
    statuses: Dict[str, str] = {}
    issue_tags: List[str] = []
    notes: List[str] = []
    issue_count = 0
    major_issue_count = 0
    for key in RUBRIC_CRITERIA:
        decision = rubric.get(key) if isinstance(rubric, dict) else None
        if not isinstance(decision, dict):
            continue
        status = str(decision.get("status") or "no_issues")
        statuses[key] = status
        if status in {"minor_issues", "major_issues"}:
            issue_count += 1
            if status == "major_issues":
                major_issue_count += 1
            note = str(decision.get("notes") or "").strip()
            if note:
                notes.append(f"{key}: {note}")
            tags = decision.get("issue_tags")
            if isinstance(tags, list):
                issue_tags.extend(str(tag) for tag in tags if str(tag).strip())
    return {
        "criteria_count": len(statuses),
        "issue_count": issue_count,
        "major_issue_count": major_issue_count,
        "statuses": statuses,
        "issue_tags": sorted(set(issue_tags)),
        "notes": notes,
        "has_explanatory_notes": bool(notes),
    }


def _candidate_review_blockers(payload: Dict[str, Any], export_type: str) -> List[str]:
    blockers = ["needs_adam_gold_edit"]
    if payload.get("candidate_requires_adam_gold_edit"):
        blockers.append("candidate_marked_for_adam_gold_edit")
    if payload.get("no_live_model_call") or payload.get("prompt_pair_factory_no_model_call"):
        blockers.append("scaffolded_without_live_model_call")
    blockers.extend(source_section_export_blockers(payload))
    truth_status = str(payload.get("truth_status") or "")
    if truth_status in {"system_inference", "model_generated", "adam_inference"}:
        blockers.append(f"truth_status_{truth_status}_requires_review")
    boundary = payload.get("boundary_snapshot") if isinstance(payload.get("boundary_snapshot"), dict) else {}
    if export_type == "sft":
        system_prompt = str(payload.get("system_prompt") or DEFAULT_SYSTEM_PROMPT)
        prompt = str(payload.get("prompt") or "")
        content = _prompt_pair_response(payload)
        blockers.extend(sft_export_blockers(system_prompt, prompt, content))
        if boundary.get("usable_for_sft") is False:
            blockers.append("boundary_holds_sft")
    if export_type == "dpo" and boundary.get("usable_for_dpo") is False:
        blockers.append("boundary_holds_dpo")
    export_flags = payload.get("export_flags") if isinstance(payload.get("export_flags"), dict) else {}
    if export_flags.get(export_type) is False:
        blockers.append(f"export_flag_{export_type}_false")
    if export_type == "dpo":
        reason = _dpo_reason(payload)
        response_rubric = _dpo_response_rubric(payload, reason)
        rejected_summary = _rubric_issue_summary(_rubric_side(response_rubric, "response_a"))
        rejected_truth_status = str(payload.get("rejected_truth_status") or "")
        if rejected_truth_status in {"model_generated", "system_inference", "adam_inference"}:
            blockers.append(f"rejected_truth_status_{rejected_truth_status}_requires_review")
        if not reason:
            blockers.append("missing_dpo_reason")
        if rejected_summary["issue_count"] == 0 or not rejected_summary["has_explanatory_notes"]:
            blockers.append("missing_rejected_issue_context")
    return list(dict.fromkeys(blockers))


def _prompt_pair_sft_payload(task: Task) -> Dict[str, Any]:
    payload = task.input_payload or {}
    return {
        "messages": [
            {"role": "system", "content": str(payload.get("system_prompt") or DEFAULT_SYSTEM_PROMPT)},
            {"role": "user", "content": str(payload.get("prompt") or "")},
            {"role": "assistant", "content": _prompt_pair_response(payload)},
        ],
        "metadata": {
            "source_task_id": task.id,
            "source_task_human_id": task.human_id,
            "source_prompt_spec_id": payload.get("prompt_spec_id"),
            "source_context_pack_id": payload.get("context_pack_id"),
            "truth_status": payload.get("truth_status"),
            "voice_mode": payload.get("voice_mode"),
            "synthetic": payload.get("synthetic"),
            "quality_status": "review_candidate",
            "artifact_mode": payload.get("artifact_mode") or "sft",
            "source_title": payload.get("source_title"),
            "grounding_asset_id": payload.get("grounding_asset_id"),
            "review_blockers": _candidate_review_blockers(payload, "sft"),
            "source_segment_id": payload.get("source_segment_id"),
            "source_chunk_index": payload.get("source_chunk_index"),
            "source_prompt_pair_example_index": payload.get("source_prompt_pair_example_index"),
            "source_section_review_hint": payload.get("source_section_review_hint"),
            "source_excerpt": payload.get("source_excerpt"),
            "source_photo_id": payload.get("source_photo_id"),
            "photo_context_profile_id": payload.get("photo_context_profile_id"),
            "photo_memory_id": payload.get("photo_memory_id"),
            "boundary_snapshot": payload.get("boundary_snapshot"),
            "pair_generation_metadata": payload.get("pair_generation_metadata"),
            "export_preview_yaml": payload.get("export_preview_yaml"),
            "context": payload.get("context"),
        },
    }


def _prompt_pair_dpo_payload(task: Task) -> Dict[str, Any]:
    payload = task.input_payload or {}
    reason = _dpo_reason(payload)
    response_rubric = _dpo_response_rubric(payload, reason)
    chosen_summary = _rubric_issue_summary(_rubric_side(response_rubric, "response_b"))
    rejected_summary = _rubric_issue_summary(_rubric_side(response_rubric, "response_a"))
    return {
        "input": {
            "messages": [
                {"role": "system", "content": str(payload.get("system_prompt") or DEFAULT_SYSTEM_PROMPT)},
                {"role": "user", "content": str(payload.get("prompt") or "")},
            ]
        },
        "preferred_output": str(payload.get("chosen") or ""),
        "non_preferred_output": str(payload.get("rejected") or ""),
        "metadata": {
            "source_task_id": task.id,
            "source_task_human_id": task.human_id,
            "source_prompt_spec_id": payload.get("prompt_spec_id"),
            "source_context_pack_id": payload.get("context_pack_id"),
            "truth_status": payload.get("truth_status"),
            "voice_mode": payload.get("voice_mode"),
            "synthetic": payload.get("synthetic"),
            "quality_status": "review_candidate",
            "artifact_mode": "dpo",
            "source_title": payload.get("source_title"),
            "grounding_asset_id": payload.get("grounding_asset_id"),
            "reason": reason,
            "response_rubric": response_rubric,
            "rubric_summary": payload.get("rubric_summary") or {},
            "chosen_issue_summary": chosen_summary,
            "rejected_issue_summary": rejected_summary,
            "rejected_truth_status": payload.get("rejected_truth_status"),
            "candidate_review_policy": {
                "adam_review_required": True,
                "does_not_certify_final_authenticity": True,
                "chosen_side_is_preferred_candidate": True,
                "rejected_side_may_be_model_generated": payload.get("rejected_truth_status") == "model_generated",
            },
            "review_blockers": _candidate_review_blockers(payload, "dpo"),
            "source_segment_id": payload.get("source_segment_id"),
            "source_chunk_index": payload.get("source_chunk_index"),
            "source_prompt_pair_example_index": payload.get("source_prompt_pair_example_index"),
            "source_section_review_hint": payload.get("source_section_review_hint"),
            "source_excerpt": payload.get("source_excerpt"),
            "source_photo_id": payload.get("source_photo_id"),
            "photo_context_profile_id": payload.get("photo_context_profile_id"),
            "photo_memory_id": payload.get("photo_memory_id"),
            "boundary_snapshot": payload.get("boundary_snapshot"),
            "pair_generation_metadata": payload.get("pair_generation_metadata"),
            "export_preview_yaml": payload.get("export_preview_yaml"),
            "context": payload.get("context"),
        },
    }


def _prompt_pair_candidate_rows(session: Session, export_type: str) -> List[Dict[str, Any]]:
    tasks = session.exec(
        select(Task)
        .where(Task.task_type == "gold_voice_edit")
        .where(Task.queue == "prompt_pairs_needing_gold_edits")
        .where(Task.status == "ready")
        .order_by(Task.created_at.asc())
    ).all()
    rows: List[Dict[str, Any]] = []
    for task in tasks:
        payload = task.input_payload or {}
        artifact_mode = str(payload.get("artifact_mode") or "sft")
        if export_type == "sft" and artifact_mode == "sft":
            prompt = str(payload.get("prompt") or "").strip()
            response = _prompt_pair_response(payload).strip()
            if not prompt or not response:
                continue
            rows.append(
                {
                    "artifact_type": "prompt_pair_sft_review_candidate",
                    "artifact_id": task.id,
                    "source_gold_voice_example_id": None,
                    "export_status": "review_candidate",
                    "payload": _prompt_pair_sft_payload(task),
                    "source": {
                        "task_id": task.id,
                        "task_human_id": task.human_id,
                        "voice_mode": payload.get("voice_mode"),
                        "truth_status": payload.get("truth_status"),
                        "source_title": payload.get("source_title"),
                        "review_state": "needs_adam_gold_edit",
                    },
                }
            )
        elif export_type == "dpo" and artifact_mode == "dpo":
            prompt = str(payload.get("prompt") or "").strip()
            chosen = str(payload.get("chosen") or "").strip()
            rejected = str(payload.get("rejected") or "").strip()
            if not prompt or not chosen or not rejected or chosen == rejected:
                continue
            rows.append(
                {
                    "artifact_type": "prompt_pair_dpo_review_candidate",
                    "artifact_id": task.id,
                    "source_gold_voice_example_id": None,
                    "export_status": "review_candidate",
                    "payload": _prompt_pair_dpo_payload(task),
                    "source": {
                        "task_id": task.id,
                        "task_human_id": task.human_id,
                        "voice_mode": payload.get("voice_mode"),
                        "truth_status": payload.get("truth_status"),
                        "source_title": payload.get("source_title"),
                        "review_state": "needs_adam_gold_edit",
                    },
                }
            )
    return rows


def _training_payload_key(row: Dict[str, Any]) -> str:
    payload = row.get("payload") or {}
    if "messages" in payload:
        key_payload = {"messages": payload.get("messages") or []}
    else:
        key_payload = {
            "input": payload.get("input") or {},
            "preferred_output": payload.get("preferred_output") or "",
            "non_preferred_output": payload.get("non_preferred_output") or "",
        }
    return json.dumps(key_payload, ensure_ascii=False, sort_keys=True)


def _split_duplicate_training_rows(rows: List[Dict[str, Any]]) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    seen: Dict[str, str] = {}
    unique: List[Dict[str, Any]] = []
    duplicates: List[Dict[str, Any]] = []
    for row in rows:
        key = _training_payload_key(row)
        first_artifact_id = seen.get(key)
        if first_artifact_id:
            duplicates.append(
                {
                    **row,
                    "duplicate_of_artifact_id": first_artifact_id,
                    "reasons": ["duplicate_export_payload"],
                }
            )
            continue
        seen[key] = str(row.get("artifact_id"))
        unique.append(row)
    return unique, duplicates


def _gold_for(session: Session, gold_id: str) -> GoldVoiceExample | None:
    return session.get(GoldVoiceExample, gold_id)


def _context_for(session: Session, gold: GoldVoiceExample | None) -> ContextPack | None:
    if not gold or not gold.context_pack_id:
        return None
    return session.get(ContextPack, gold.context_pack_id)


def _source_summary(gold: GoldVoiceExample | None, context: ContextPack | None) -> Dict[str, Any]:
    if not gold:
        return {}
    return {
        "gold_voice_example_id": gold.id,
        "gold_human_id": gold.human_id,
        "voice_mode": gold.voice_mode,
        "truth_status": gold.truth_status,
        "context_pack_id": context.id if context else gold.context_pack_id,
        "context_human_id": context.human_id if context else None,
        "context_boundary_status": context.boundaries_snapshot.get("boundary_status") if context else None,
    }


def _receipt_for_gold(session: Session, gold_id: str) -> TaskReceipt | None:
    receipts = session.exec(select(TaskReceipt).where(TaskReceipt.task_type == "gold_voice_edit")).all()
    for receipt in receipts:
        if receipt.created_or_updated.get("gold_voice_example_id") == gold_id:
            return receipt
    return None


def _response_b_privacy_blocked(gold: GoldVoiceExample | None) -> bool:
    if not gold:
        return True
    ratings = gold.ratings or {}
    rubric_summary = ratings.get("rubric_summary")
    if isinstance(rubric_summary, dict) and rubric_summary.get("preferred_export_blocked"):
        return True
    response_rubric = ratings.get("response_rubric")
    if not isinstance(response_rubric, dict):
        return False
    response_b = response_rubric.get("response_b")
    if not isinstance(response_b, dict):
        return False
    privacy = response_b.get("privacy_export_safety")
    return isinstance(privacy, dict) and privacy.get("status") == "major_issues"


def _message_content(payload: Dict[str, Any], role: str) -> str:
    messages = payload.get("messages")
    if not isinstance(messages, list):
        return ""
    for message in messages:
        if not isinstance(message, dict):
            continue
        if message.get("role") == role:
            return str(message.get("content") or "")
    return ""


def _actual_sft_blockers(payload: Dict[str, Any]) -> List[str]:
    metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
    reasons = _list_strings(metadata.get("review_blockers"))
    reasons.extend(
        sft_export_blockers(
            _message_content(payload, "system"),
            _message_content(payload, "user"),
            _message_content(payload, "assistant"),
        )
    )
    return list(dict.fromkeys(reasons))


def _actual_dpo_blockers(payload: Dict[str, Any]) -> List[str]:
    input_payload = payload.get("input") if isinstance(payload.get("input"), dict) else {}
    metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
    prompt = _message_content(input_payload, "user")
    reasons = dpo_export_blockers(
        prompt,
        str(payload.get("preferred_output") or ""),
        str(payload.get("non_preferred_output") or ""),
        _list_strings(metadata.get("reason")),
    )
    return list(dict.fromkeys(reasons))


def _exclusion_reasons(
    *,
    session: Session,
    export_type: str,
    export_status: str,
    source_gold_voice_example_id: str,
    include_candidates: bool,
    payload: Dict[str, Any],
) -> List[str]:
    reasons: List[str] = []
    gold = _gold_for(session, source_gold_voice_example_id)
    context = _context_for(session, gold)

    if not gold:
        reasons.append("missing_gold_voice_example")
    elif gold.downstream_use and gold.downstream_use.get(export_type) is False:
        reasons.append(f"gold_downstream_use_blocks_{export_type}")

    if export_status != "approved" and not include_candidates:
        reasons.append(f"artifact_status_is_{export_status}")

    if _response_b_privacy_blocked(gold):
        reasons.append("response_b_privacy_export_safety_block")

    if context and context.boundaries_snapshot.get("boundary_status") == "blocked":
        reasons.append("context_pack_boundary_blocked")

    if export_status == "approved" and export_type == "sft":
        reasons.extend(_actual_sft_blockers(payload))
    elif export_status == "approved" and export_type == "dpo":
        reasons.extend(_actual_dpo_blockers(payload))

    return list(dict.fromkeys(reasons))


def export_dry_run(session: Session, export_type: str, *, include_candidates: bool = False) -> Dict[str, Any]:
    if export_type == "sft":
        artifacts = session.exec(select(SFTCandidate)).all()
        rows = [
            {
                "artifact_type": "sft_candidate",
                "artifact_id": artifact.id,
                "source_gold_voice_example_id": artifact.source_gold_voice_example_id,
                "export_status": artifact.export_status,
                "payload": _sft_payload(session, artifact),
            }
            for artifact in artifacts
        ]
    elif export_type == "dpo":
        artifacts = session.exec(select(DPOPair)).all()
        rows = [
            {
                "artifact_type": "dpo_pair",
                "artifact_id": artifact.id,
                "source_gold_voice_example_id": artifact.source_gold_voice_example_id,
                "export_status": artifact.export_status,
                "payload": _dpo_payload(session, artifact),
            }
            for artifact in artifacts
        ]
    else:
        raise ValueError("export_type must be sft or dpo")

    included: List[Dict[str, Any]] = []
    excluded: List[Dict[str, Any]] = []
    for row in rows:
        gold = _gold_for(session, str(row["source_gold_voice_example_id"]))
        context = _context_for(session, gold)
        receipt = _receipt_for_gold(session, str(row["source_gold_voice_example_id"]))
        row = {
            **row,
            "source": {
                **_source_summary(gold, context),
                "task_receipt_id": receipt.id if receipt else None,
                "task_receipt_human_id": receipt.human_id if receipt else None,
                "receipt_downstream_status": receipt.downstream_status if receipt else None,
                "receipt_boundary_status": receipt.boundary_status if receipt else None,
            },
        }
        reasons = _exclusion_reasons(
            session=session,
            export_type=export_type,
            export_status=str(row["export_status"]),
            source_gold_voice_example_id=str(row["source_gold_voice_example_id"]),
            include_candidates=include_candidates,
            payload=row["payload"] if isinstance(row.get("payload"), dict) else {},
        )
        if reasons:
            excluded.append({**row, "reasons": reasons})
        else:
            included.append(row)

    if include_candidates:
        included.extend(_prompt_pair_candidate_rows(session, export_type))

    included, duplicate_rows = _split_duplicate_training_rows(included)
    excluded.extend(duplicate_rows)

    return {
        "export_type": export_type,
        "mode": "candidate_allowed" if include_candidates else "approved_only",
        "included_count": len(included),
        "excluded_count": len(excluded),
        "included": included,
        "excluded": excluded,
    }


def sft_export_items(session: Session) -> List[Dict[str, Any]]:
    return [item["payload"] for item in export_dry_run(session, "sft")["included"]]


def dpo_export_items(session: Session) -> List[Dict[str, Any]]:
    return [item["payload"] for item in export_dry_run(session, "dpo")["included"]]
