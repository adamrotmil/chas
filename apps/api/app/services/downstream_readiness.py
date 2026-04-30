from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, List
from urllib.parse import quote

from sqlmodel import Session, select

from app.config import Settings
from app.exports.jsonl import dpo_export_items, export_dry_run, sft_export_items, to_jsonl
from app.models import Task, utcnow
from app.services.demo_generation import compile_demo_generation_request_preview
from app.services.photo_context_progress import (
    build_photo_context_retrieval_gap_field_worklist,
    build_photo_context_retrieval_gap_payoff_preview,
    build_photo_context_session_progress_artifact,
)
from app.services.photo_context_review_pack import build_photo_context_review_pack, build_photo_context_review_session_plan
from app.services.photo_review_priority import build_photo_review_priority_summary
from app.services.prompt_pair_audit import (
    compile_dpo_rejected_reason_repair_packet,
    compile_prompt_pair_audit,
    compile_prompt_pair_audit_pack,
    compile_prompt_pair_review_progress,
    compile_prompt_pair_top_blocker_review_session_plan,
    compile_source_boundary_training_review_packet,
)
from app.services.prompt_pair_reference_pack import compile_prompt_pair_reference_pack
from app.services.pair_generation import (
    PAIR_GENERATION_PROMPT_INSTRUCTIONS_VERSION,
    preview_make_gold_tasks_from_review,
)
from app.services.context_packs import compile_photo_context_pack_readiness_audit
from app.services.retrieval import photo_memory_embedding_export, retrieval_gap_review_slice


def _generation_blockers(app_settings: Settings) -> List[str]:
    blockers = []
    if not app_settings.text_generation_live_calls_enabled:
        blockers.append("text_generation_live_calls_disabled")
    if not app_settings.openai_api_key:
        blockers.append("openai_api_key_missing")
    return blockers


def _int(value: Any) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return 0


def _action_from_prompt_pair(action: Dict[str, Any] | None) -> Dict[str, Any]:
    if not action:
        return {
            "action_type": "open_prompt_pair_queue",
            "label": "Open held prompt pair",
            "enabled": False,
            "disabled_reason": "no_specific_held_prompt_pair_action",
        }
    return {
        "action_type": action.get("action_type") or "open_held_prompt_pair_candidate",
        "label": "Open held prompt pair",
        "enabled": bool(action.get("task_id")),
        "task_id": action.get("task_id"),
        "task_human_id": action.get("task_human_id"),
        "queue": "prompt_pairs_needing_gold_edits",
        "reason": action.get("reason"),
    }


def _action_from_photo_context(group: Dict[str, Any] | None) -> Dict[str, Any]:
    action = group.get("primary_action") if isinstance(group, dict) and isinstance(group.get("primary_action"), dict) else {}
    if action.get("task_id"):
        return {
            "action_type": action.get("action_type") or "open_existing_photo_context_task",
            "label": action.get("label") or "Open context task",
            "enabled": True,
            "task_id": action.get("task_id"),
            "task_human_id": action.get("task_human_id"),
            "queue": action.get("queue") or "photo_assets_needing_context",
            "request": action.get("request"),
        }
    return {
        "action_type": "create_photo_context_review_session",
        "label": "Create top context tasks",
        "enabled": True,
        "queue": "photo_assets_needing_context",
        "request": {
            "endpoint": "/api/assets/photo-context-review-pack/review-session",
            "method": "POST",
            "params": {"scope": "family_private", "limit": 5, "dry_run": False},
        },
    }


def _action_from_vector(next_action: Dict[str, Any] | None) -> Dict[str, Any]:
    if not next_action:
        return {
            "action_type": "open_vector_review_queue",
            "label": "Open photo vector review",
            "enabled": False,
            "disabled_reason": "no_specific_vector_review_action",
        }
    return {
        "action_type": next_action.get("action_type") or "open_photo_vector_review",
        "label": "Open photo vector review",
        "enabled": bool(next_action.get("review_task_id") or next_action.get("task_id")),
        "task_id": next_action.get("review_task_id") or next_action.get("task_id"),
        "task_human_id": next_action.get("review_task_human_id") or next_action.get("task_human_id"),
        "queue": next_action.get("review_queue") or next_action.get("queue"),
        "reason": next_action.get("suggested_next_action") or next_action.get("reason"),
    }


def _stable_hash(payload: Dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str, separators=(",", ":")).encode("utf-8")).hexdigest()


def _content_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _stable_json(value: Dict[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str, separators=(",", ":"))


def _yaml_scalar(value: Any) -> str:
    if value is True:
        return "true"
    if value is False:
        return "false"
    if value is None:
        return "null"
    if isinstance(value, (int, float)):
        return str(value)
    text = str(value)
    if not text:
        return '""'
    if all(ch.isalnum() or ch in " _./:-" for ch in text):
        return text
    return json.dumps(text, ensure_ascii=False)


def _artifact_item(
    *,
    artifact_key: str,
    label: str,
    artifact_family: str,
    format: str,
    source_endpoint: str,
    download_endpoint: str | None,
    content_sha256: str,
    record_count: int,
    eligibility: Dict[str, bool],
    policy: Dict[str, Any],
    preview_char_count: int = 0,
) -> Dict[str, Any]:
    return {
        "artifact_key": artifact_key,
        "label": label,
        "artifact_family": artifact_family,
        "format": format,
        "source_endpoint": source_endpoint,
        "download_endpoint": download_endpoint,
        "content_sha256": content_sha256,
        "record_count": record_count,
        "preview_char_count": preview_char_count,
        "eligibility": eligibility,
        "policy": policy,
    }


def _source_review_pair_preview_payload(session: Session) -> tuple[Dict[str, Any], str]:
    task = session.exec(
        select(Task)
        .where(Task.task_type.in_(["text_segment_review", "text_segment_boundary_review", "email_voice_sample"]))
        .where(Task.status == "ready")
        .order_by(Task.priority.desc(), Task.created_at.asc())
    ).first()
    if not task:
        payload = {
            "preview_type": "source_review_generate_pairs_preview",
            "review_policy": "dry_run_only_no_tasks_created_no_raw_source_mutation",
            "does_not_mutate_state": True,
            "no_live_model_call": True,
            "prompt_instructions_version": PAIR_GENERATION_PROMPT_INSTRUCTIONS_VERSION,
            "source_task_id": None,
            "source_task_human_id": None,
            "source_title": "",
            "source_text_sha256": None,
            "source_text_char_count": 0,
            "source_text_preview": "",
            "source_spans_supplied": False,
            "source_span_draft_count": 0,
            "source_section_count": 0,
            "candidate_pair_count": 0,
            "projected_created_pair_count": 0,
            "projected_held_pair_count": 0,
            "projected_held_source_section_count": 0,
            "strategy_counts": {},
            "primary_strategy": "none",
            "primary_strategy_label": "No ready source review task",
            "next_queue": None,
            "created_pairs_preview": [],
            "held_pairs_preview": [],
            "held_source_sections_preview": [],
            "completion_signal": "no_ready_source_review_task",
            "safety_boundaries": [
                "Preview does not create prompt specs, generations, context packs, annotations, or tasks.",
                "Submit still creates candidate Prompt Pair tickets requiring Adam gold review.",
                "Raw imported source files remain unchanged.",
            ],
        }
        payload["content_sha256"] = _stable_hash(payload)
        return payload, "/api/tasks/{task_id}/pair-generation/preview"

    payload = preview_make_gold_tasks_from_review(
        session=session,
        task=task,
        decisions={
            "generate_pairs_on_submit": "yes",
            "voice_mode": "father_to_adam",
            "synthetic": True,
        },
    )
    return payload, f"/api/tasks/{task.id}/pair-generation/preview"


def compile_downstream_artifact_manifest(
    *,
    session: Session,
    scope: str = "family_private",
    prompt_sample_limit: int = 200,
    vector_limit: int = 20,
    app_settings: Settings | None = None,
    include_handoff_artifact: bool = True,
    photo_session_query: str = "Old Orchard beach",
) -> Dict[str, Any]:
    prompt_limit = max(1, min(prompt_sample_limit, 500))
    safe_vector_limit = max(1, min(vector_limit, 1000))
    audit_pack = compile_prompt_pair_audit_pack(session=session, sample_limit=prompt_limit)
    prompt_review_progress = compile_prompt_pair_review_progress(session=session)
    prompt_session_plan = compile_prompt_pair_top_blocker_review_session_plan(session=session, limit=5)
    dpo_repair_pack = compile_dpo_rejected_reason_repair_packet(session=session, limit=25)
    source_boundary_pack = compile_source_boundary_training_review_packet(session=session, limit=25)
    reference_pack = compile_prompt_pair_reference_pack(session=session, sample_limit=prompt_limit)
    photo_pack = build_photo_context_review_pack(session=session, scope=scope, limit=safe_vector_limit)
    photo_session_plan = build_photo_context_review_session_plan(
        session=session,
        scope=scope,
        limit=5,
        source_query=photo_session_query,
    )
    photo_session_progress_artifact = build_photo_context_session_progress_artifact(
        session=session,
        scope=scope,
        limit=100,
    )
    retrieval_field_worklist = build_photo_context_retrieval_gap_field_worklist(
        session=session,
        scope=scope,
        limit=100,
    )
    retrieval_payoff_preview = build_photo_context_retrieval_gap_payoff_preview(
        session=session,
        scope=scope,
        limit=10,
    )
    photo_review_priority = build_photo_review_priority_summary(session=session, focus="fastest_vector", limit=10)
    photo_context_pack_audit = compile_photo_context_pack_readiness_audit(
        session=session,
        scope=scope,
        limit=50,
    )
    vector_export = photo_memory_embedding_export(session=session, scope=scope, limit=safe_vector_limit)
    vector_manifest = vector_export.get("manifest") if isinstance(vector_export.get("manifest"), dict) else {}
    sft_jsonl = to_jsonl(sft_export_items(session))
    dpo_jsonl = to_jsonl(dpo_export_items(session))
    sft_dry_run = export_dry_run(session, "sft", include_candidates=True)
    dpo_dry_run = export_dry_run(session, "dpo", include_candidates=True)
    source_preview, source_preview_endpoint = _source_review_pair_preview_payload(session)
    demo_request_preview = compile_demo_generation_request_preview(
        session=session,
        app_settings=app_settings or Settings(),
        limit=5,
    )
    prompt_review_progress_json = _stable_json(prompt_review_progress)
    photo_session_progress_json = _stable_json(photo_session_progress_artifact)
    photo_context_pack_audit_json = _stable_json(photo_context_pack_audit)
    source_preview_json = _stable_json(source_preview)

    review_only = {"training": False, "vector": False, "gallery": False, "human_review": True}
    items = [
        _artifact_item(
            artifact_key="prompt_pair_audit_markdown",
            label="Prompt pair audit Markdown",
            artifact_family="prompt_pair_review",
            format="markdown",
            source_endpoint=f"/api/prompt-pairs/audit-pack?sample_limit={prompt_limit}",
            download_endpoint=f"/api/prompt-pairs/audit-pack/markdown?sample_limit={prompt_limit}",
            content_sha256=audit_pack["content_sha256"],
            record_count=int(audit_pack.get("sample_count") or 0),
            preview_char_count=len(audit_pack.get("markdown") or ""),
            eligibility=review_only,
            policy={
                "does_not_certify_final_authenticity": True,
                "candidate_review_only": True,
                "source_truth_unchanged": True,
            },
        ),
        _artifact_item(
            artifact_key="prompt_pair_review_progress_json",
            label="Prompt pair review progress JSON",
            artifact_family="prompt_pair_review",
            format="json",
            source_endpoint="/api/prompt-pairs/review-progress",
            download_endpoint=None,
            content_sha256=_content_hash(prompt_review_progress_json),
            record_count=int(prompt_review_progress.get("candidate_count") or 0),
            preview_char_count=len(prompt_review_progress_json),
            eligibility=review_only,
            policy={
                "review_policy": prompt_review_progress.get("review_policy"),
                "does_not_mutate_state": prompt_review_progress.get("does_not_mutate_state") is True,
                "does_not_promote_to_training_export": prompt_review_progress.get("does_not_promote_to_training_export") is True,
                "requires_adam_gold_edit": prompt_review_progress.get("requires_adam_gold_edit") is True,
                "completion_signal": prompt_review_progress.get("completion_signal"),
                "progress_content_sha256": prompt_review_progress.get("content_sha256"),
                "top_blocker": prompt_review_progress.get("top_blocker"),
                "candidate_count": prompt_review_progress.get("candidate_count"),
                "approved_count": prompt_review_progress.get("approved_count"),
            },
        ),
        _artifact_item(
            artifact_key="prompt_pair_top_blocker_session_plan_yaml",
            label="Prompt pair top blocker session plan YAML",
            artifact_family="prompt_pair_review",
            format="yaml",
            source_endpoint="/api/prompt-pairs/top-blocker-review-session-plan?limit=5",
            download_endpoint="/api/prompt-pairs/top-blocker-review-session-plan/yaml?limit=5",
            content_sha256=str(
                prompt_session_plan.get("export_preview_sha256")
                or _content_hash(prompt_session_plan.get("export_preview_yaml") or "")
            ),
            record_count=int(prompt_session_plan.get("selected_count") or 0),
            preview_char_count=len(prompt_session_plan.get("export_preview_yaml") or ""),
            eligibility=review_only,
            policy={
                "review_policy": prompt_session_plan.get("review_policy"),
                "does_not_mutate_state": prompt_session_plan.get("does_not_mutate_state") is True,
                "does_not_promote_to_training_export": prompt_session_plan.get("does_not_promote_to_training_export") is True,
                "requires_adam_gold_edit": prompt_session_plan.get("requires_adam_gold_edit") is True,
                "completion_signal": prompt_session_plan.get("completion_signal"),
                "blocker": prompt_session_plan.get("blocker"),
                "selected_count": prompt_session_plan.get("selected_count"),
                "candidate_count": prompt_session_plan.get("candidate_count"),
                "content_sha256": prompt_session_plan.get("content_sha256"),
                "projected_task_delta": prompt_session_plan.get("projected_task_delta"),
            },
        ),
        _artifact_item(
            artifact_key="dpo_rejected_reason_repair_yaml",
            label="DPO rejected reason repair YAML",
            artifact_family="prompt_pair_repair",
            format="yaml",
            source_endpoint="/api/prompt-pairs/dpo-rejected-reason-repair-pack?limit=25",
            download_endpoint="/api/prompt-pairs/dpo-rejected-reason-repair-pack/yaml?limit=25",
            content_sha256=str(dpo_repair_pack.get("export_preview_sha256") or _content_hash(dpo_repair_pack.get("export_preview_yaml") or "")),
            record_count=int(dpo_repair_pack.get("reported_candidate_count") or 0),
            preview_char_count=len(dpo_repair_pack.get("export_preview_yaml") or ""),
            eligibility=review_only,
            policy={
                "blocker": dpo_repair_pack.get("blocker"),
                "does_not_promote_to_training_export": True,
                "requires_adam_gold_edit": True,
                "repair_packet": True,
            },
        ),
        _artifact_item(
            artifact_key="source_boundary_training_review_yaml",
            label="Source-boundary training review YAML",
            artifact_family="prompt_pair_repair",
            format="yaml",
            source_endpoint="/api/prompt-pairs/source-boundary-training-review-pack?limit=25",
            download_endpoint="/api/prompt-pairs/source-boundary-training-review-pack/yaml?limit=25",
            content_sha256=str(
                source_boundary_pack.get("export_preview_sha256")
                or _content_hash(source_boundary_pack.get("export_preview_yaml") or "")
            ),
            record_count=int(source_boundary_pack.get("reported_candidate_count") or 0),
            preview_char_count=len(source_boundary_pack.get("export_preview_yaml") or ""),
            eligibility=review_only,
            policy={
                "blocker": source_boundary_pack.get("blocker"),
                "does_not_mutate_source": source_boundary_pack.get("does_not_mutate_source") is True,
                "does_not_promote_to_training_export": source_boundary_pack.get("does_not_promote_to_training_export") is True,
                "requires_adam_boundary_review": source_boundary_pack.get("requires_adam_boundary_review") is True,
                "requires_adam_gold_edit": source_boundary_pack.get("requires_adam_gold_edit") is True,
                "completion_signal": source_boundary_pack.get("completion_signal"),
                "repair_packet": True,
            },
        ),
        _artifact_item(
            artifact_key="source_review_pair_generation_preview_json",
            label="Source Review Generate Pairs preview JSON",
            artifact_family="source_review_preview",
            format="json",
            source_endpoint=source_preview_endpoint,
            download_endpoint=None,
            content_sha256=_content_hash(source_preview_json),
            record_count=int(source_preview.get("projected_created_pair_count") or 0),
            preview_char_count=len(source_preview_json),
            eligibility=review_only,
            policy={
                "review_policy": source_preview.get("review_policy"),
                "does_not_mutate_state": source_preview.get("does_not_mutate_state") is True,
                "no_live_model_call": source_preview.get("no_live_model_call") is True,
                "submit_creates_candidate_prompt_pair_tasks": True,
                "completion_signal": source_preview.get("completion_signal"),
                "source_task_id": source_preview.get("source_task_id"),
                "source_task_human_id": source_preview.get("source_task_human_id"),
                "source_sections": source_preview.get("source_section_count"),
                "source_span_draft_count": source_preview.get("source_span_draft_count"),
                "strategy_counts": source_preview.get("strategy_counts"),
            },
        ),
        _artifact_item(
            artifact_key="demo_generation_request_preview_yaml",
            label="Demo generation request preview YAML",
            artifact_family="model_generation_preview",
            format="yaml",
            source_endpoint="/api/model-status/demo-generation-request-preview?limit=5",
            download_endpoint="/api/model-status/demo-generation-request-preview/yaml?limit=5",
            content_sha256=str(
                demo_request_preview.get("export_preview_sha256")
                or _content_hash(demo_request_preview.get("export_preview_yaml") or "")
            ),
            record_count=int(demo_request_preview.get("request_count") or 0),
            preview_char_count=len(demo_request_preview.get("export_preview_yaml") or ""),
            eligibility=review_only,
            policy={
                "review_policy": demo_request_preview.get("review_policy"),
                "does_not_mutate_state": demo_request_preview.get("does_not_mutate_state") is True,
                "no_live_model_call": demo_request_preview.get("no_live_model_call") is True,
                "no_generation_created": demo_request_preview.get("no_generation_created") is True,
                "does_not_promote_to_training_export": demo_request_preview.get("does_not_promote_to_training_export") is True,
                "model_name": demo_request_preview.get("model_name"),
                "reasoning_effort": demo_request_preview.get("reasoning_effort"),
                "store": demo_request_preview.get("store"),
                "request_count": demo_request_preview.get("request_count"),
                "preview_content_sha256": demo_request_preview.get("content_sha256"),
            },
        ),
        _artifact_item(
            artifact_key="prompt_pair_reference_jsonl",
            label="Prompt pair voice reference JSONL",
            artifact_family="prompt_pair_reference",
            format="jsonl",
            source_endpoint=f"/api/prompt-pairs/reference-pack?sample_limit={prompt_limit}",
            download_endpoint=f"/api/prompt-pairs/reference-pack/jsonl?sample_limit={prompt_limit}",
            content_sha256=reference_pack["content_sha256"],
            record_count=int(reference_pack.get("sample_count") or 0),
            preview_char_count=len(reference_pack.get("jsonl") or ""),
            eligibility={"training": False, "vector": True, "gallery": False, "human_review": True},
            policy=reference_pack.get("safety_policy") if isinstance(reference_pack.get("safety_policy"), dict) else {},
        ),
        _artifact_item(
            artifact_key="prompt_pair_reference_markdown",
            label="Prompt pair voice reference Markdown",
            artifact_family="prompt_pair_reference",
            format="markdown",
            source_endpoint=f"/api/prompt-pairs/reference-pack?sample_limit={prompt_limit}",
            download_endpoint=f"/api/prompt-pairs/reference-pack/markdown?sample_limit={prompt_limit}",
            content_sha256=_content_hash(reference_pack.get("markdown") or ""),
            record_count=int(reference_pack.get("sample_count") or 0),
            preview_char_count=len(reference_pack.get("markdown") or ""),
            eligibility=review_only,
            policy=reference_pack.get("safety_policy") if isinstance(reference_pack.get("safety_policy"), dict) else {},
        ),
        _artifact_item(
            artifact_key="dataset_sft_approved_jsonl",
            label="Approved SFT JSONL",
            artifact_family="training_dataset",
            format="jsonl",
            source_endpoint="/api/dataset-exports/dry-run?export_type=sft",
            download_endpoint="/api/dataset-exports/jsonl?export_type=sft",
            content_sha256=_content_hash(sft_jsonl),
            record_count=len(sft_export_items(session)),
            preview_char_count=len(sft_jsonl),
            eligibility={"training": True, "vector": False, "gallery": False, "human_review": True},
            policy={
                "approved_only": True,
                "candidate_items_excluded": True,
                "boundary_gate_required": True,
            },
        ),
        _artifact_item(
            artifact_key="dataset_dpo_approved_jsonl",
            label="Approved DPO JSONL",
            artifact_family="training_dataset",
            format="jsonl",
            source_endpoint="/api/dataset-exports/dry-run?export_type=dpo",
            download_endpoint="/api/dataset-exports/jsonl?export_type=dpo",
            content_sha256=_content_hash(dpo_jsonl),
            record_count=len(dpo_export_items(session)),
            preview_char_count=len(dpo_jsonl),
            eligibility={"training": True, "vector": False, "gallery": False, "human_review": True},
            policy={
                "approved_only": True,
                "candidate_items_excluded": True,
                "boundary_gate_required": True,
            },
        ),
        _artifact_item(
            artifact_key="dataset_sft_candidate_dry_run",
            label="SFT candidate dry-run JSON",
            artifact_family="training_review_dry_run",
            format="json",
            source_endpoint="/api/dataset-exports/dry-run?export_type=sft&include_candidates=true",
            download_endpoint=None,
            content_sha256=_content_hash(_stable_json(sft_dry_run)),
            record_count=int(sft_dry_run.get("included_count") or 0),
            preview_char_count=len(_stable_json(sft_dry_run)),
            eligibility=review_only,
            policy={
                "candidate_preview_only": True,
                "approved_training_build": False,
                "candidate_rows_missing_blockers": sft_dry_run.get("candidate_rows_missing_blockers"),
            },
        ),
        _artifact_item(
            artifact_key="dataset_dpo_candidate_dry_run",
            label="DPO candidate dry-run JSON",
            artifact_family="training_review_dry_run",
            format="json",
            source_endpoint="/api/dataset-exports/dry-run?export_type=dpo&include_candidates=true",
            download_endpoint=None,
            content_sha256=_content_hash(_stable_json(dpo_dry_run)),
            record_count=int(dpo_dry_run.get("included_count") or 0),
            preview_char_count=len(_stable_json(dpo_dry_run)),
            eligibility=review_only,
            policy={
                "candidate_preview_only": True,
                "approved_training_build": False,
                "candidate_rows_missing_blockers": dpo_dry_run.get("candidate_rows_missing_blockers"),
            },
        ),
        _artifact_item(
            artifact_key="photo_context_pack_readiness_json",
            label="Photo context-pack readiness JSON",
            artifact_family="photo_context_review",
            format="json",
            source_endpoint=f"/api/context-packs/photo-context-readiness-audit?scope={scope}&limit=50",
            download_endpoint=f"/api/context-packs/photo-context-readiness-audit?scope={scope}&limit=50",
            content_sha256=_content_hash(photo_context_pack_audit_json),
            record_count=int(photo_context_pack_audit.get("ready_context_pack_asset_count") or 0),
            preview_char_count=len(photo_context_pack_audit_json),
            eligibility=review_only,
            policy={
                "review_policy": photo_context_pack_audit.get("review_policy"),
                "does_not_mutate_state": photo_context_pack_audit.get("does_not_mutate_state") is True,
                "requires_boundary_clearance": photo_context_pack_audit.get("requires_boundary_clearance") is True,
                "uses_reviewed_photo_context": photo_context_pack_audit.get("uses_reviewed_photo_context") is True,
                "uses_linked_reviewed_memories": photo_context_pack_audit.get("uses_linked_reviewed_memories") is True,
                "excludes_system_inference_drafts": photo_context_pack_audit.get("excludes_system_inference_drafts") is True,
                "completion_signal": photo_context_pack_audit.get("completion_signal"),
                "audit_content_sha256": photo_context_pack_audit.get("content_sha256"),
                "ready_context_pack_asset_count": photo_context_pack_audit.get("ready_context_pack_asset_count"),
                "filename_only_fallback_count": photo_context_pack_audit.get("filename_only_fallback_count"),
                "system_inference_leak_count": photo_context_pack_audit.get("system_inference_leak_count"),
            },
        ),
        _artifact_item(
            artifact_key="photo_context_review_pack_yaml_preview",
            label="Photo context review pack YAML preview",
            artifact_family="photo_context_review",
            format="yaml",
            source_endpoint=f"/api/assets/photo-context-review-pack?scope={scope}&limit={safe_vector_limit}",
            download_endpoint=None,
            content_sha256=_content_hash(photo_pack.get("export_preview_yaml") or ""),
            record_count=int((photo_pack.get("manifest") or {}).get("photo_context_worklist_count") or 0),
            preview_char_count=len(photo_pack.get("export_preview_yaml") or ""),
            eligibility=review_only,
            policy={
                "pack_content_sha256": photo_pack["content_sha256"],
                "reviewed_only_by_default": True,
                "not_memory_claim_worklists": True,
                "ordinary_db_vector_storage": False,
            },
        ),
        _artifact_item(
            artifact_key="photo_context_review_session_plan_yaml",
            label="Photo context review session plan YAML",
            artifact_family="photo_context_review",
            format="yaml",
            source_endpoint=(
                f"/api/assets/photo-context-review-pack/review-session-plan?scope={scope}"
                f"&limit=5&source_query={quote(photo_session_query)}"
            ),
            download_endpoint=(
                f"/api/assets/photo-context-review-pack/review-session-plan/yaml?scope={scope}"
                f"&limit=5&source_query={quote(photo_session_query)}"
            ),
            content_sha256=str(photo_session_plan.get("export_preview_sha256") or _content_hash(photo_session_plan.get("export_preview_yaml") or "")),
            record_count=int(photo_session_plan.get("selected_count") or 0),
            preview_char_count=len(photo_session_plan.get("export_preview_yaml") or ""),
            eligibility=review_only,
            policy={
                "review_policy": photo_session_plan.get("review_policy"),
                "source_query": photo_session_plan.get("source_query"),
                "query_is_context_prioritization_only": True,
                "does_not_create_memory_claim": True,
                "requires_adam_context": True,
                "worklist_key": photo_session_plan.get("worklist_key"),
            },
        ),
        _artifact_item(
            artifact_key="photo_context_session_progress_json",
            label="Photo context session progress JSON",
            artifact_family="photo_context_review",
            format="json",
            source_endpoint=f"/api/assets/photo-context-review-pack/session-progress/artifact?scope={scope}&limit=100",
            download_endpoint=f"/api/assets/photo-context-review-pack/session-progress/artifact?scope={scope}&limit=100",
            content_sha256=_content_hash(photo_session_progress_json),
            record_count=int(photo_session_progress_artifact.get("reported_task_count") or 0),
            preview_char_count=len(photo_session_progress_json),
            eligibility=review_only,
            policy={
                "review_policy": photo_session_progress_artifact.get("review_policy"),
                "does_not_mutate_state": photo_session_progress_artifact.get("does_not_mutate_state") is True,
                "does_not_create_memory_claim": photo_session_progress_artifact.get("does_not_create_memory_claim") is True,
                "does_not_create_embedding_record": photo_session_progress_artifact.get("does_not_create_embedding_record") is True,
                "requires_adam_context": photo_session_progress_artifact.get("requires_adam_context") is True,
                "completion_signal": photo_session_progress_artifact.get("completion_signal"),
                "progress_content_sha256": photo_session_progress_artifact.get("source_progress_content_sha256"),
                "artifact_content_sha256": photo_session_progress_artifact.get("content_sha256"),
                "reported_task_count": photo_session_progress_artifact.get("reported_task_count"),
                "draft_count": photo_session_progress_artifact.get("draft_count"),
                "submit_ready_count": photo_session_progress_artifact.get("submit_ready_count"),
                "retrieval_gap_task_count": photo_session_progress_artifact.get("retrieval_gap_task_count"),
            },
        ),
        _artifact_item(
            artifact_key="photo_context_retrieval_gap_field_worklist_yaml",
            label="Photo retrieval-gap field worklist YAML",
            artifact_family="photo_context_review",
            format="yaml",
            source_endpoint=f"/api/assets/photo-context-review-pack/retrieval-gap-field-worklist?scope={scope}&limit=100",
            download_endpoint=f"/api/assets/photo-context-review-pack/retrieval-gap-field-worklist/yaml?scope={scope}&limit=100",
            content_sha256=str(
                retrieval_field_worklist.get("export_preview_sha256")
                or _content_hash(retrieval_field_worklist.get("export_preview_yaml") or "")
            ),
            record_count=int(retrieval_field_worklist.get("reported_item_count") or 0),
            preview_char_count=len(retrieval_field_worklist.get("export_preview_yaml") or ""),
            eligibility=review_only,
            policy={
                "review_policy": retrieval_field_worklist.get("review_policy"),
                "does_not_create_memory_claim": True,
                "requires_adam_context": True,
                "does_not_mutate_state": True,
                "completion_signal": retrieval_field_worklist.get("completion_signal"),
                "retrieval_gap_task_count": retrieval_field_worklist.get("retrieval_gap_task_count"),
                "missing_field_counts": retrieval_field_worklist.get("missing_field_counts"),
                "field_guidance_count": len(retrieval_field_worklist.get("field_guidance") or []),
                "has_field_guidance": bool(retrieval_field_worklist.get("field_guidance")),
            },
        ),
        _artifact_item(
            artifact_key="photo_context_retrieval_gap_payoff_preview_yaml",
            label="Photo retrieval-gap payoff preview YAML",
            artifact_family="photo_context_review",
            format="yaml",
            source_endpoint=f"/api/assets/photo-context-review-pack/retrieval-gap-payoff-preview?scope={scope}&limit=10",
            download_endpoint=f"/api/assets/photo-context-review-pack/retrieval-gap-payoff-preview/yaml?scope={scope}&limit=10",
            content_sha256=str(
                retrieval_payoff_preview.get("export_preview_sha256")
                or _content_hash(retrieval_payoff_preview.get("export_preview_yaml") or "")
            ),
            record_count=int(retrieval_payoff_preview.get("reported_item_count") or 0),
            preview_char_count=len(retrieval_payoff_preview.get("export_preview_yaml") or ""),
            eligibility=review_only,
            policy={
                "review_policy": retrieval_payoff_preview.get("review_policy"),
                "does_not_create_memory_claim": True,
                "uses_placeholders_for_missing_adam_context": True,
                "no_live_embedding_call": True,
                "source_worklist_content_sha256": retrieval_payoff_preview.get("source_worklist_content_sha256"),
            },
        ),
        _artifact_item(
            artifact_key="photo_review_priority_yaml",
            label="Photo review throughput priority YAML",
            artifact_family="photo_context_review",
            format="yaml",
            source_endpoint="/api/assets/photo-review-priority?focus=fastest_vector&limit=10",
            download_endpoint="/api/assets/photo-review-priority/yaml?focus=fastest_vector&limit=10",
            content_sha256=str(
                photo_review_priority.get("export_preview_sha256")
                or _content_hash(photo_review_priority.get("export_preview_yaml") or "")
            ),
            record_count=int(photo_review_priority.get("reported_count") or 0),
            preview_char_count=len(photo_review_priority.get("export_preview_yaml") or ""),
            eligibility=review_only,
            policy={
                "review_policy": photo_review_priority.get("review_policy"),
                "throughput_policy": photo_review_priority.get("throughput_policy"),
                "does_not_mutate_state": photo_review_priority.get("does_not_mutate_state") is True,
                "does_not_create_memory_claim": photo_review_priority.get("does_not_create_memory_claim") is True,
                "no_live_model_call": photo_review_priority.get("no_live_model_call") is True,
                "no_live_embedding_call": photo_review_priority.get("no_live_embedding_call") is True,
                "completion_signal": photo_review_priority.get("completion_signal"),
                "ranking_inputs": photo_review_priority.get("ranking_inputs"),
                "total_candidate_count": photo_review_priority.get("total_candidate_count"),
                "reported_count": photo_review_priority.get("reported_count"),
                "priority_content_sha256": photo_review_priority.get("content_sha256"),
            },
        ),
        _artifact_item(
            artifact_key="photo_vector_handoff_jsonl",
            label="Photo memory vector handoff JSONL",
            artifact_family="photo_vector_handoff",
            format="jsonl",
            source_endpoint=f"/api/retrieval/photo-memory-corpus/export?scope={scope}&limit={safe_vector_limit}",
            download_endpoint=f"/api/retrieval/photo-memory-corpus/export.jsonl?scope={scope}&limit={safe_vector_limit}",
            content_sha256=str(vector_manifest.get("content_sha256") or _content_hash(vector_export.get("jsonl") or "")),
            record_count=int(vector_manifest.get("record_count") or 0),
            preview_char_count=len(vector_export.get("jsonl") or ""),
            eligibility={"training": False, "vector": True, "gallery": False, "human_review": True},
            policy={
                "review_policy": vector_manifest.get("review_policy"),
                "vector_values_included": False,
                "live_embedding_call": False,
                "ordinary_db_vector_storage": False,
            },
        ),
        _artifact_item(
            artifact_key="photo_vector_handoff_manifest",
            label="Photo memory vector handoff manifest",
            artifact_family="photo_vector_handoff",
            format="json",
            source_endpoint=f"/api/retrieval/photo-memory-corpus/export.manifest?scope={scope}&limit={safe_vector_limit}",
            download_endpoint=f"/api/retrieval/photo-memory-corpus/export.manifest?scope={scope}&limit={safe_vector_limit}",
            content_sha256=_content_hash(_stable_json(vector_manifest)),
            record_count=int(vector_manifest.get("record_count") or 0),
            preview_char_count=len(_stable_json(vector_manifest)),
            eligibility=review_only,
            policy={
                "review_policy": vector_manifest.get("review_policy"),
                "manifest_for_vector_handoff": True,
                "ordinary_db_vector_storage": False,
            },
        ),
    ]
    if include_handoff_artifact:
        handoff_yaml = compile_morning_handoff_yaml(
            session=session,
            app_settings=app_settings or Settings(),
            scope=scope,
            prompt_sample_limit=prompt_limit,
            vector_limit=safe_vector_limit,
            bottleneck_limit=4,
            retrieval_gap_query=photo_session_query,
        )
        items.append(
            _artifact_item(
                artifact_key="morning_handoff_yaml",
                label="Morning handoff YAML",
                artifact_family="operator_handoff",
                format="yaml",
                source_endpoint=(
                    f"/api/downstream-readiness/morning-handoff?scope={scope}"
                    f"&prompt_sample_limit={prompt_limit}&vector_limit={safe_vector_limit}&bottleneck_limit=4"
                ),
                download_endpoint=(
                    f"/api/downstream-readiness/morning-handoff.yaml?scope={scope}"
                    f"&prompt_sample_limit={prompt_limit}&vector_limit={safe_vector_limit}&bottleneck_limit=4"
                ),
                content_sha256=_content_hash(handoff_yaml),
                record_count=1,
                preview_char_count=len(handoff_yaml),
                eligibility=review_only,
                policy={
                    "operator_packet": True,
                    "does_not_mutate_state": True,
                    "no_live_model_call": True,
                    "no_live_embedding_call": True,
                    "no_fine_tuning_api_calls_in_mvp": True,
                },
            )
        )
    manifest_payload = {
        "manifest_type": "downstream_artifact_manifest",
        "scope": scope,
        "generated_at": utcnow().isoformat().replace("+00:00", "Z"),
        "review_policy": "inspectable_outputs_no_build_side_effects",
        "does_not_mutate_state": True,
        "no_live_model_call": True,
        "no_live_embedding_call": True,
        "no_fine_tuning_api_calls_in_mvp": True,
        "artifact_count": len(items),
        "formats": sorted({item["format"] for item in items}),
        "artifact_families": sorted({item["artifact_family"] for item in items}),
        "items": items,
    }
    manifest_payload["content_sha256"] = _stable_hash({"items": items, "scope": scope})
    return manifest_payload


def compile_downstream_artifact_audit(
    *,
    session: Session,
    scope: str = "family_private",
    prompt_sample_limit: int = 200,
    vector_limit: int = 20,
    app_settings: Settings | None = None,
    include_handoff_artifact: bool = True,
    photo_session_query: str = "Old Orchard beach",
) -> Dict[str, Any]:
    prompt_limit = max(1, min(prompt_sample_limit, 500))
    safe_vector_limit = max(1, min(vector_limit, 1000))
    manifest = compile_downstream_artifact_manifest(
        session=session,
        scope=scope,
        prompt_sample_limit=prompt_limit,
        vector_limit=safe_vector_limit,
        app_settings=app_settings,
        include_handoff_artifact=include_handoff_artifact,
        photo_session_query=photo_session_query,
    )
    by_key = {item["artifact_key"]: item for item in manifest["items"]}
    audit_pack = compile_prompt_pair_audit_pack(session=session, sample_limit=prompt_limit)
    prompt_review_progress = compile_prompt_pair_review_progress(session=session)
    prompt_session_plan = compile_prompt_pair_top_blocker_review_session_plan(session=session, limit=5)
    dpo_repair_pack = compile_dpo_rejected_reason_repair_packet(session=session, limit=25)
    source_boundary_pack = compile_source_boundary_training_review_packet(session=session, limit=25)
    demo_request_preview = compile_demo_generation_request_preview(
        session=session,
        app_settings=app_settings or Settings(),
        limit=5,
    )
    reference_pack = compile_prompt_pair_reference_pack(session=session, sample_limit=prompt_limit)
    photo_pack = build_photo_context_review_pack(session=session, scope=scope, limit=safe_vector_limit)
    photo_session_plan = build_photo_context_review_session_plan(
        session=session,
        scope=scope,
        limit=5,
        source_query=photo_session_query,
    )
    photo_session_progress_artifact = build_photo_context_session_progress_artifact(
        session=session,
        scope=scope,
        limit=100,
    )
    retrieval_field_worklist = build_photo_context_retrieval_gap_field_worklist(
        session=session,
        scope=scope,
        limit=100,
    )
    retrieval_payoff_preview = build_photo_context_retrieval_gap_payoff_preview(
        session=session,
        scope=scope,
        limit=10,
    )
    photo_review_priority = build_photo_review_priority_summary(session=session, focus="fastest_vector", limit=10)
    photo_context_pack_audit = compile_photo_context_pack_readiness_audit(
        session=session,
        scope=scope,
        limit=50,
    )
    vector_export = photo_memory_embedding_export(session=session, scope=scope, limit=safe_vector_limit)
    vector_manifest = vector_export.get("manifest") if isinstance(vector_export.get("manifest"), dict) else {}
    source_preview, _source_preview_endpoint = _source_review_pair_preview_payload(session)
    artifact_bodies = {
        "prompt_pair_audit_markdown": audit_pack.get("markdown") or "",
        "prompt_pair_review_progress_json": _stable_json(prompt_review_progress),
        "prompt_pair_top_blocker_session_plan_yaml": prompt_session_plan.get("export_preview_yaml") or "",
        "dpo_rejected_reason_repair_yaml": dpo_repair_pack.get("export_preview_yaml") or "",
        "source_boundary_training_review_yaml": source_boundary_pack.get("export_preview_yaml") or "",
        "source_review_pair_generation_preview_json": _stable_json(source_preview),
        "demo_generation_request_preview_yaml": demo_request_preview.get("export_preview_yaml") or "",
        "prompt_pair_reference_jsonl": reference_pack.get("jsonl") or "",
        "prompt_pair_reference_markdown": reference_pack.get("markdown") or "",
        "dataset_sft_approved_jsonl": to_jsonl(sft_export_items(session)),
        "dataset_dpo_approved_jsonl": to_jsonl(dpo_export_items(session)),
        "dataset_sft_candidate_dry_run": _stable_json(export_dry_run(session, "sft", include_candidates=True)),
        "dataset_dpo_candidate_dry_run": _stable_json(export_dry_run(session, "dpo", include_candidates=True)),
        "photo_context_pack_readiness_json": _stable_json(photo_context_pack_audit),
        "photo_context_review_pack_yaml_preview": photo_pack.get("export_preview_yaml") or "",
        "photo_context_review_session_plan_yaml": photo_session_plan.get("export_preview_yaml") or "",
        "photo_context_session_progress_json": _stable_json(photo_session_progress_artifact),
        "photo_context_retrieval_gap_field_worklist_yaml": retrieval_field_worklist.get("export_preview_yaml") or "",
        "photo_context_retrieval_gap_payoff_preview_yaml": retrieval_payoff_preview.get("export_preview_yaml") or "",
        "photo_review_priority_yaml": photo_review_priority.get("export_preview_yaml") or "",
        "photo_vector_handoff_jsonl": vector_export.get("jsonl") or "",
        "photo_vector_handoff_manifest": _stable_json(vector_manifest),
    }
    if "morning_handoff_yaml" in by_key:
        artifact_bodies["morning_handoff_yaml"] = compile_morning_handoff_yaml(
            session=session,
            app_settings=app_settings or Settings(),
            scope=scope,
            prompt_sample_limit=prompt_limit,
            vector_limit=safe_vector_limit,
            bottleneck_limit=4,
        )
    checks = []
    for artifact_key, body in artifact_bodies.items():
        item = by_key.get(artifact_key) or {}
        recomputed_sha256 = _content_hash(body)
        declared_sha256 = str(item.get("content_sha256") or "")
        checks.append(
            {
                "artifact_key": artifact_key,
                "format": item.get("format"),
                "source_endpoint": item.get("source_endpoint"),
                "download_endpoint": item.get("download_endpoint"),
                "declared_sha256": declared_sha256,
                "recomputed_sha256": recomputed_sha256,
                "hash_matches": declared_sha256 == recomputed_sha256,
                "body_char_count": len(body),
                "policy": item.get("policy") if isinstance(item.get("policy"), dict) else {},
            }
        )
    mismatches = [check for check in checks if not check["hash_matches"]]
    audit_payload = {
        "audit_type": "downstream_artifact_hash_audit",
        "scope": scope,
        "generated_at": utcnow().isoformat().replace("+00:00", "Z"),
        "review_policy": "recompute_declared_manifest_hashes_without_export_build",
        "does_not_mutate_state": True,
        "no_live_model_call": True,
        "no_live_embedding_call": True,
        "no_fine_tuning_api_calls_in_mvp": True,
        "manifest_content_sha256": manifest["content_sha256"],
        "checked_count": len(checks),
        "mismatch_count": len(mismatches),
        "all_hashes_match": not mismatches,
        "checks": checks,
        "mismatches": mismatches,
    }
    audit_payload["content_sha256"] = _stable_hash({"checks": checks, "manifest": manifest["content_sha256"]})
    return audit_payload


def compile_morning_handoff(
    *,
    session: Session,
    app_settings: Settings,
    scope: str = "family_private",
    prompt_sample_limit: int = 200,
    vector_limit: int = 20,
    bottleneck_limit: int = 4,
    retrieval_gap_query: str = "Old Orchard beach",
) -> Dict[str, Any]:
    prompt_limit = max(1, min(prompt_sample_limit, 500))
    safe_vector_limit = max(1, min(vector_limit, 1000))
    safe_bottleneck_limit = max(1, min(bottleneck_limit, 10))
    queue = compile_downstream_bottleneck_queue(
        session=session,
        app_settings=app_settings,
        scope=scope,
        limit=safe_bottleneck_limit,
    )
    manifest = compile_downstream_artifact_manifest(
        session=session,
        scope=scope,
        prompt_sample_limit=prompt_limit,
        vector_limit=safe_vector_limit,
        app_settings=app_settings,
        include_handoff_artifact=False,
        photo_session_query=retrieval_gap_query,
    )
    audit = compile_downstream_artifact_audit(
        session=session,
        scope=scope,
        prompt_sample_limit=prompt_limit,
        vector_limit=safe_vector_limit,
        app_settings=app_settings,
        include_handoff_artifact=False,
        photo_session_query=retrieval_gap_query,
    )
    retrieval_gap_work = retrieval_gap_review_slice(
        session=session,
        query=retrieval_gap_query,
        scope=scope,
        limit=5,
    )
    source_summaries = queue.get("source_summaries") if isinstance(queue.get("source_summaries"), dict) else {}
    prompt_summary = source_summaries.get("prompt_pairs") if isinstance(source_summaries.get("prompt_pairs"), dict) else {}
    photo_summary = source_summaries.get("photo_context") if isinstance(source_summaries.get("photo_context"), dict) else {}
    vector_summary = source_summaries.get("vector_handoff") if isinstance(source_summaries.get("vector_handoff"), dict) else {}
    demo_summary = source_summaries.get("demo_generation") if isinstance(source_summaries.get("demo_generation"), dict) else {}
    gate_counts = prompt_summary.get("preflight_gate_counts") if isinstance(prompt_summary.get("preflight_gate_counts"), dict) else {}
    ordered_keys = queue.get("ordered_area_keys") if isinstance(queue.get("ordered_area_keys"), list) else []
    primary_key = str(ordered_keys[0]) if ordered_keys else "none"
    manifest_artifact_count = _int(manifest.get("artifact_count"))

    readiness_summary = [
        {
            "area_key": "prompt_pairs",
            "label": "Prompt pairs",
            "status": "needs_gold_review" if _int(gate_counts.get("candidate")) else "approved_or_empty",
            "metric": f"{_int(gate_counts.get('approved'))} approved / {_int(gate_counts.get('candidate'))} candidates",
            "truth_policy": "candidates require Adam gold edit before training export",
        },
        {
            "area_key": "photo_context",
            "label": "Photo context",
            "status": "needs_adam_context" if _int(photo_summary.get("needs_context_group_count")) else "context_ready_or_empty",
            "metric": f"{_int(photo_summary.get('needs_context_group_count'))} groups need context / {_int(photo_summary.get('held_for_adam_review_count'))} held drafts",
            "truth_policy": "photo backlog is no_claim until Adam-authored context exists",
        },
        {
            "area_key": "vector_handoff",
            "label": "Vector handoff",
            "status": "review_holds_remaining" if _int(vector_summary.get("excluded_count")) else "vector_ready",
            "metric": f"{_int(vector_summary.get('record_count'))} ready / {_int(vector_summary.get('excluded_count'))} held",
            "truth_policy": "reviewed-only by default; no live embedding call",
        },
        {
            "area_key": "demo_generation",
            "label": "Demo generation",
            "status": "ready" if demo_summary.get("can_generate") is True else "credential_gated",
            "metric": ", ".join(str(blocker) for blocker in (demo_summary.get("blockers") or [])) or "no blockers",
            "truth_policy": "demo outputs remain model_generated and excluded from training until Adam review",
        },
        {
            "area_key": "artifacts",
            "label": "Downstream artifacts",
            "status": "hash_audited" if audit.get("all_hashes_match") is True else "hash_mismatch",
            "metric": f"{manifest_artifact_count} artifacts + handoff / {audit.get('mismatch_count')} hash mismatches",
            "truth_policy": "manifest is inspectable output metadata, not a training API call",
        },
    ]

    top_bottlenecks = [
        {
            "area_key": item.get("area_key"),
            "area_label": item.get("area_label"),
            "priority_rank": item.get("priority_rank"),
            "severity": item.get("severity"),
            "count": item.get("count"),
            "summary": item.get("summary"),
            "next_action": item.get("next_action"),
            "action": item.get("action"),
            "policy": item.get("policy"),
        }
        for item in (queue.get("items") if isinstance(queue.get("items"), list) else [])
        if isinstance(item, dict)
    ]
    checklist_policy_by_area = {
        "prompt_pairs": {
            "completion_signal": "candidate_count_decreases_or_blocker_worklist_changes",
            "acceptance_test": "Open the held pair, resolve the export blocker, submit, and confirm the prompt-pair candidate count changes.",
            "safety_boundary": "Do not mark candidate text authentic until Adam gold review clears it.",
        },
        "photo_context": {
            "completion_signal": "needs_context_group_count_decreases_or_review_task_becomes_submit_ready",
            "acceptance_test": "Open or create the context task, add Adam-authored context, and confirm the photo context group leaves the no-claim backlog.",
            "safety_boundary": "Photo filename/title evidence remains no_claim until Adam context exists.",
        },
        "vector_handoff": {
            "completion_signal": "excluded_count_decreases_or_reviewed_vector_ready_count_increases",
            "acceptance_test": "Open the vector review task, clear Adam-review/boundary blockers, and confirm the vector handoff includes the record.",
            "safety_boundary": "No live embedding call is made by the checklist; only handoff text is prepared.",
        },
        "demo_generation": {
            "completion_signal": "text_generation_live_ready_becomes_true",
            "acceptance_test": "Add credentials and enable live text generation when ready; generated outputs remain model_generated.",
            "safety_boundary": "No fine-tuning API calls are allowed in MVP.",
        },
    }
    operator_checklist = []
    for index, item in enumerate(top_bottlenecks, start=1):
        area_key = str(item.get("area_key") or "unknown")
        policy = checklist_policy_by_area.get(
            area_key,
            {
                "completion_signal": "area_metric_changes",
                "acceptance_test": "Complete the recommended action and confirm the related readiness metric changes.",
                "safety_boundary": "Preserve source truth and boundary status.",
            },
        )
        action = item.get("action") if isinstance(item.get("action"), dict) else {}
        operator_checklist.append(
            {
                "checklist_id": f"operator_checklist_{index:03d}_{area_key}",
                "area_key": area_key,
                "label": item.get("area_label"),
                "priority_rank": item.get("priority_rank"),
                "count": item.get("count"),
                "status": "blocked" if action.get("enabled") is False else "actionable",
                "action_label": action.get("label"),
                "action_type": action.get("action_type"),
                "task_id": action.get("task_id"),
                "task_human_id": action.get("task_human_id"),
                "request": action.get("request") if isinstance(action.get("request"), dict) else None,
                "completion_signal": policy["completion_signal"],
                "acceptance_test": policy["acceptance_test"],
                "safety_boundary": policy["safety_boundary"],
                **(
                    {
                        "retrieval_gap_query": retrieval_gap_work.get("query"),
                        "retrieval_gap_candidate_count": retrieval_gap_work.get("candidate_count"),
                        "retrieval_gap_slice_hash": retrieval_gap_work.get("content_sha256"),
                        "retrieval_gap_preview_titles": [
                            candidate.get("display_title")
                            for candidate in retrieval_gap_work.get("items", [])
                            if isinstance(candidate, dict)
                        ][:5],
                    }
                    if area_key == "photo_context" and retrieval_gap_work.get("gap_open") is True
                    else {}
                ),
            }
        )
    artifact_summary = {
        "artifact_count": manifest.get("artifact_count"),
        "self_excluded_artifact_count": 1,
        "full_manifest_artifact_count": manifest_artifact_count + 1,
        "count_note": "Morning handoff summarizes the artifact manifest without counting the morning_handoff_yaml artifact itself.",
        "formats": manifest.get("formats"),
        "artifact_families": manifest.get("artifact_families"),
        "manifest_content_sha256": manifest.get("content_sha256"),
        "audit_content_sha256": audit.get("content_sha256"),
        "checked_count": audit.get("checked_count"),
        "mismatch_count": audit.get("mismatch_count"),
        "all_hashes_match": audit.get("all_hashes_match"),
    }
    downstream_links = [
        {
            "label": "Artifact manifest",
            "endpoint": (
                f"/api/downstream-readiness/artifact-manifest?scope={scope}&prompt_sample_limit={prompt_limit}"
                f"&vector_limit={safe_vector_limit}&photo_session_query={quote(retrieval_gap_query)}"
            ),
            "format": "json",
        },
        {
            "label": "Artifact hash audit",
            "endpoint": (
                f"/api/downstream-readiness/artifact-audit?scope={scope}&prompt_sample_limit={prompt_limit}"
                f"&vector_limit={safe_vector_limit}&photo_session_query={quote(retrieval_gap_query)}"
            ),
            "format": "json",
        },
        {
            "label": "Bottleneck queue",
            "endpoint": f"/api/downstream-readiness/bottlenecks?scope={scope}&limit={safe_bottleneck_limit}",
            "format": "json",
        },
        {
            "label": "Retrieval gap review slice",
            "endpoint": f"/api/retrieval/gap-review-slice?q={quote(retrieval_gap_query)}&scope={scope}&limit=5",
            "format": "json",
        },
        {
            "label": "Prompt pair audit Markdown",
            "endpoint": f"/api/prompt-pairs/audit-pack/markdown?sample_limit={prompt_limit}",
            "format": "markdown",
        },
    ]
    headline = (
        "No open bottlenecks are reported; artifacts remain hash-audited."
        if primary_key == "none"
        else f"{title_case_key(primary_key)} is the top bottleneck; artifacts are hash-audited."
    )
    report_lines = [
        "# Morning Handoff",
        "",
        headline,
        "",
        "## Readiness",
        *[f"- {item['label']}: {item['metric']} ({item['status']})." for item in readiness_summary],
        "",
        "## Next Actions",
        *[
            f"- {item['area_label']}: {item['next_action']}"
            for item in top_bottlenecks[:safe_bottleneck_limit]
        ],
        "",
        "## Retrieval Gap Work",
        f"- Query: {retrieval_gap_work.get('query')}",
        f"- Status: {retrieval_gap_work.get('status')} / {retrieval_gap_work.get('truth_status')}",
        f"- Candidates: {retrieval_gap_work.get('candidate_count')} total, {retrieval_gap_work.get('reported_candidate_count')} previewed.",
        f"- Completion: {retrieval_gap_work.get('completion_signal')}",
        "",
        "## Safety",
        "- No fine-tuning API calls in MVP.",
        "- No live model calls for this handoff.",
        "- Demo outputs, when enabled, remain model_generated until Adam review.",
        "- Photo backlog remains no_claim until Adam-authored context is submitted.",
    ]
    hash_payload = {
        "artifact_summary": artifact_summary,
        "downstream_links": downstream_links,
        "headline": headline,
        "readiness_summary": readiness_summary,
        "top_bottlenecks": top_bottlenecks,
        "operator_checklist": operator_checklist,
        "retrieval_gap_work": retrieval_gap_work,
    }
    handoff_payload = {
        "report_type": "morning_handoff",
        "scope": scope,
        "generated_at": utcnow().isoformat().replace("+00:00", "Z"),
        "headline": headline,
        "review_policy": "read_only_status_no_source_mutation",
        "does_not_mutate_state": True,
        "no_live_model_call": True,
        "no_live_embedding_call": True,
        "no_fine_tuning_api_calls_in_mvp": True,
        "primary_bottleneck_area_key": primary_key,
        "ordered_bottleneck_area_keys": ordered_keys,
        "readiness_summary": readiness_summary,
        "top_bottlenecks": top_bottlenecks,
        "operator_checklist": operator_checklist,
        "retrieval_gap_work": retrieval_gap_work,
        "artifact_summary": artifact_summary,
        "model_generation_status": {
            "can_generate": demo_summary.get("can_generate") is True,
            "blockers": demo_summary.get("blockers") or [],
            "model_name": demo_summary.get("model_name") or app_settings.text_generation_model,
            "reasoning_effort": demo_summary.get("reasoning_effort") or app_settings.text_generation_reasoning_effort,
            "outputs_truth_status": "model_generated",
            "fine_tuning_api_calls_allowed": False,
        },
        "downstream_links": downstream_links,
        "report_markdown": "\n".join(report_lines),
    }
    handoff_payload["content_sha256"] = _stable_hash(hash_payload)
    return handoff_payload


def compile_morning_handoff_yaml(
    *,
    session: Session,
    app_settings: Settings,
    scope: str = "family_private",
    prompt_sample_limit: int = 200,
    vector_limit: int = 20,
    bottleneck_limit: int = 4,
    retrieval_gap_query: str = "Old Orchard beach",
) -> str:
    handoff = compile_morning_handoff(
        session=session,
        app_settings=app_settings,
        scope=scope,
        prompt_sample_limit=prompt_sample_limit,
        vector_limit=vector_limit,
        bottleneck_limit=bottleneck_limit,
        retrieval_gap_query=retrieval_gap_query,
    )
    retrieval_gap_work = handoff.get("retrieval_gap_work") if isinstance(handoff.get("retrieval_gap_work"), dict) else {}
    lines = [
        "morning_handoff:",
        f"  report_type: {_yaml_scalar(handoff.get('report_type'))}",
        f"  scope: {_yaml_scalar(handoff.get('scope'))}",
        f"  content_sha256: {_yaml_scalar(handoff.get('content_sha256'))}",
        f"  headline: {_yaml_scalar(handoff.get('headline'))}",
        f"  review_policy: {_yaml_scalar(handoff.get('review_policy'))}",
        f"  does_not_mutate_state: {_yaml_scalar(handoff.get('does_not_mutate_state'))}",
        f"  no_live_model_call: {_yaml_scalar(handoff.get('no_live_model_call'))}",
        f"  no_live_embedding_call: {_yaml_scalar(handoff.get('no_live_embedding_call'))}",
        f"  no_fine_tuning_api_calls_in_mvp: {_yaml_scalar(handoff.get('no_fine_tuning_api_calls_in_mvp'))}",
        f"  primary_bottleneck_area_key: {_yaml_scalar(handoff.get('primary_bottleneck_area_key'))}",
        "  ordered_bottleneck_area_keys:",
    ]
    for area_key in handoff.get("ordered_bottleneck_area_keys") or []:
        lines.append(f"    - {_yaml_scalar(area_key)}")
    lines.extend(
        [
            "  retrieval_gap_work:",
            f"    query: {_yaml_scalar(retrieval_gap_work.get('query'))}",
            f"    review_policy: {_yaml_scalar(retrieval_gap_work.get('review_policy'))}",
            f"    truth_status: {_yaml_scalar(retrieval_gap_work.get('truth_status'))}",
            f"    candidate_count: {_yaml_scalar(retrieval_gap_work.get('candidate_count'))}",
            f"    reported_candidate_count: {_yaml_scalar(retrieval_gap_work.get('reported_candidate_count'))}",
            f"    content_sha256: {_yaml_scalar(retrieval_gap_work.get('content_sha256'))}",
            "    preview_titles:",
        ]
    )
    for item in (retrieval_gap_work.get("items") if isinstance(retrieval_gap_work.get("items"), list) else [])[:5]:
        if isinstance(item, dict):
            lines.append(f"      - {_yaml_scalar(item.get('display_title'))}")
    if not any(line.startswith("      - ") for line in lines[-5:]):
        lines.append("      []")
    lines.append("  readiness_summary:")
    for item in handoff.get("readiness_summary") or []:
        if not isinstance(item, dict):
            continue
        lines.extend(
            [
                f"    - area_key: {_yaml_scalar(item.get('area_key'))}",
                f"      status: {_yaml_scalar(item.get('status'))}",
                f"      metric: {_yaml_scalar(item.get('metric'))}",
                f"      truth_policy: {_yaml_scalar(item.get('truth_policy'))}",
            ]
        )
    lines.append("  operator_checklist:")
    for item in handoff.get("operator_checklist") or []:
        if not isinstance(item, dict):
            continue
        lines.extend(
            [
                f"    - checklist_id: {_yaml_scalar(item.get('checklist_id'))}",
                f"      area_key: {_yaml_scalar(item.get('area_key'))}",
                f"      status: {_yaml_scalar(item.get('status'))}",
                f"      completion_signal: {_yaml_scalar(item.get('completion_signal'))}",
                f"      safety_boundary: {_yaml_scalar(item.get('safety_boundary'))}",
            ]
        )
        if item.get("retrieval_gap_query"):
            lines.extend(
                [
                    f"      retrieval_gap_query: {_yaml_scalar(item.get('retrieval_gap_query'))}",
                    f"      retrieval_gap_candidate_count: {_yaml_scalar(item.get('retrieval_gap_candidate_count'))}",
                    f"      retrieval_gap_slice_hash: {_yaml_scalar(item.get('retrieval_gap_slice_hash'))}",
                ]
            )
    artifact_summary = handoff.get("artifact_summary") if isinstance(handoff.get("artifact_summary"), dict) else {}
    lines.extend(
        [
            "  artifact_summary:",
            f"    artifact_count: {_yaml_scalar(artifact_summary.get('artifact_count'))}",
            f"    all_hashes_match: {_yaml_scalar(artifact_summary.get('all_hashes_match'))}",
            f"    mismatch_count: {_yaml_scalar(artifact_summary.get('mismatch_count'))}",
            f"    manifest_content_sha256: {_yaml_scalar(artifact_summary.get('manifest_content_sha256'))}",
            "  report_markdown: |-",
        ]
    )
    for line in str(handoff.get("report_markdown") or "").splitlines():
        lines.append(f"    {line}")
    return "\n".join(lines) + "\n"


def title_case_key(value: str) -> str:
    return " ".join(part.capitalize() for part in value.split("_"))


def compile_downstream_bottleneck_queue(
    *,
    session: Session,
    app_settings: Settings,
    scope: str = "family_private",
    limit: int = 4,
) -> Dict[str, Any]:
    safe_limit = max(1, min(limit, 10))
    audit = compile_prompt_pair_audit(session=session, sample_limit=5)
    photo_pack = build_photo_context_review_pack(session=session, scope=scope, limit=20)
    vector_export = photo_memory_embedding_export(session=session, scope=scope, limit=20)
    vector_manifest = vector_export.get("manifest") if isinstance(vector_export.get("manifest"), dict) else {}
    blockers = _generation_blockers(app_settings)

    items: List[Dict[str, Any]] = []
    prompt_candidate_count = _int((audit.get("preflight_gate_counts") or {}).get("candidate"))
    prompt_action = next(
        (action for action in audit.get("next_review_actions", []) if isinstance(action, dict) and action.get("task_id")),
        None,
    )
    if prompt_candidate_count > 0:
        items.append(
            {
                "area_key": "prompt_pairs",
                "area_label": "Prompt Pairs",
                "priority_rank": 1,
                "severity": "high",
                "count": prompt_candidate_count,
                "summary": f"{prompt_candidate_count} prompt-pair candidates are still outside approved export.",
                "next_action": (prompt_action or {}).get("reason")
                or "Open a held pair and resolve backend preflight blockers.",
                "action": _action_from_prompt_pair(prompt_action),
                "source_metrics": {
                    "approved_count": _int((audit.get("preflight_gate_counts") or {}).get("approved")),
                    "candidate_count": prompt_candidate_count,
                    "invalid_pair_count": _int(audit.get("invalid_pair_count")),
                    "preflight_mismatch_count": _int(audit.get("preflight_mismatch_count")),
                },
                "policy": {
                    "training_export_status": "candidate_until_gold_clearance",
                    "adam_review_required": True,
                    "does_not_certify_final_authenticity": True,
                },
            }
        )

    photo_manifest = photo_pack.get("manifest") if isinstance(photo_pack.get("manifest"), dict) else {}
    needs_context_groups = photo_pack.get("needs_context_groups") if isinstance(photo_pack.get("needs_context_groups"), list) else []
    photo_group_count = _int(photo_manifest.get("needs_context_group_count"))
    if photo_group_count > 0:
        items.append(
            {
                "area_key": "photo_context",
                "area_label": "Photo Context",
                "priority_rank": 2,
                "severity": "high",
                "count": photo_group_count,
                "summary": f"{photo_group_count} photo groups still need Adam-authored context.",
                "next_action": "Create or open context tasks so photos can become reviewed memory records.",
                "action": _action_from_photo_context(needs_context_groups[0] if needs_context_groups else None),
                "source_metrics": {
                    "needs_context_group_count": photo_group_count,
                    "needs_context_count": _int(photo_manifest.get("needs_context_count")),
                    "held_for_adam_review_count": _int(photo_manifest.get("held_for_adam_review_count")),
                    "reviewed_vector_ready_count": _int(photo_manifest.get("reviewed_vector_ready_count")),
                },
                "policy": {
                    "truth_status_before_review": "no_claim",
                    "not_memory_claim_until_adam_context": True,
                    "not_sft_or_dpo_training_material": True,
                },
            }
        )

    vector_excluded_count = _int(vector_manifest.get("excluded_count"))
    next_vector_action = next(
        (
            action
            for action in vector_manifest.get("next_review_actions", [])
            if isinstance(action, dict) and (action.get("review_task_id") or action.get("task_id"))
        ),
        None,
    )
    if vector_excluded_count > 0:
        items.append(
            {
                "area_key": "vector_handoff",
                "area_label": "Vector Handoff",
                "priority_rank": 3,
                "severity": "medium",
                "count": vector_excluded_count,
                "summary": f"{vector_excluded_count} photo-memory records are held from vector handoff.",
                "next_action": (next_vector_action or {}).get("suggested_next_action")
                or "Open the fastest photo vector review task.",
                "action": _action_from_vector(next_vector_action),
                "source_metrics": {
                    "record_count": _int(vector_manifest.get("record_count")),
                    "excluded_count": vector_excluded_count,
                    "held_for_adam_review_count": _int(vector_manifest.get("held_for_adam_review_count")),
                    "boundary_excluded_count": _int(vector_manifest.get("boundary_excluded_count")),
                },
                "policy": {
                    "review_policy": "reviewed_only_by_default",
                    "system_inference_excluded_by_default": True,
                    "live_embedding_call": False,
                    "vector_values_included": False,
                },
            }
        )

    if blockers:
        items.append(
            {
                "area_key": "demo_generation",
                "area_label": "Demo Generation",
                "priority_rank": 4,
                "severity": "gated",
                "count": len(blockers),
                "summary": f"Live GPT-5.5 demo generation is blocked by {', '.join(blockers)}.",
                "next_action": "Add credentials and enable live text generation when ready; no fine-tuning API call is part of MVP.",
                "action": {
                    "action_type": "configure_text_generation_credentials",
                    "label": "Gated",
                    "enabled": False,
                    "disabled_reason": "blocked_missing_credentials_or_live_gate",
                },
                "source_metrics": {
                    "blockers": blockers,
                    "model_name": app_settings.text_generation_model,
                    "reasoning_effort": app_settings.text_generation_reasoning_effort,
                    "store": False,
                },
                "policy": {
                    "outputs_truth_status": "model_generated",
                    "adam_review_required": True,
                    "fine_tuning_api_calls_allowed": False,
                    "excluded_from_training_export": True,
                },
            }
        )

    ordered = sorted(items, key=lambda item: (item["priority_rank"], -int(item["count"])))[:safe_limit]
    queue_payload = {
        "queue_type": "downstream_bottleneck_queue",
        "scope": scope,
        "generated_at": utcnow().isoformat().replace("+00:00", "Z"),
        "review_policy": "ranked_operator_actions_no_source_mutation",
        "does_not_mutate_state": True,
        "no_live_model_call": True,
        "no_fine_tuning_api_calls_in_mvp": True,
        "priority_policy": "priority_rank_ascending_then_count_descending",
        "item_count": len(ordered),
        "ordered_area_keys": [item["area_key"] for item in ordered],
        "items": ordered,
        "source_summaries": {
            "prompt_pairs": {
                "total_pairs": _int(audit.get("total_pairs")),
                "preflight_gate_counts": audit.get("preflight_gate_counts") or {},
            },
            "photo_context": {
                "needs_context_group_count": photo_group_count,
                "held_for_adam_review_count": _int(photo_manifest.get("held_for_adam_review_count")),
            },
            "vector_handoff": {
                "record_count": _int(vector_manifest.get("record_count")),
                "excluded_count": vector_excluded_count,
                "next_review_action_count": len(vector_manifest.get("next_review_actions") or []),
            },
            "demo_generation": {
                "can_generate": not blockers,
                "blockers": blockers,
                "model_name": app_settings.text_generation_model,
                "reasoning_effort": app_settings.text_generation_reasoning_effort,
            },
        },
    }
    queue_payload["machine_verification"] = {
        "queue_sha256": _stable_hash({"items": ordered, "source_summaries": queue_payload["source_summaries"]}),
        "top_area_key": ordered[0]["area_key"] if ordered else None,
        "ordered_area_keys": queue_payload["ordered_area_keys"],
        "every_item_has_action": all(isinstance(item.get("action"), dict) and item["action"].get("action_type") for item in ordered),
    }
    return queue_payload
