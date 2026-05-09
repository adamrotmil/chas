from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List

from sqlmodel import Session, select

from app.config import Settings, settings
from app.models import EmbeddingRecord, MetadataProfile, Task
from app.services.embeddings import live_embedding_ready
from app.services.model_generation import live_text_generation_ready
from app.services.vision import live_vision_ready


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _path(
    *,
    path_id: str,
    label: str,
    category: str,
    status: str,
    model_status: str,
    files: List[str],
    live_capability: str,
    env_gates: List[str],
    evidence: List[str],
    risks: List[str],
    next_action: str,
) -> Dict[str, Any]:
    return {
        "id": path_id,
        "label": label,
        "category": category,
        "status": status,
        "model_status": model_status,
        "live_capability": live_capability,
        "env_gates": env_gates,
        "files": files,
        "evidence": evidence,
        "risks": risks,
        "next_action": next_action,
    }


def _count_tasks(session: Session, task_type: str) -> int:
    return len(session.exec(select(Task).where(Task.task_type == task_type)).all())


def _true(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"true", "1", "yes"}
    return False


def _vision_scaffold_inventory(session: Session) -> Dict[str, int]:
    rows = session.exec(select(MetadataProfile).where(MetadataProfile.target_type == "asset")).all()
    profile_no_live_count = 0
    profile_live_count = 0
    for row in rows:
        raw = row.raw_profile if isinstance(row.raw_profile, dict) else {}
        quality = row.quality_signals if isinstance(row.quality_signals, dict) else {}
        if _true(raw.get("no_live_model_call")) or _true(quality.get("no_live_model_call")):
            profile_no_live_count += 1
        if _true(raw.get("live_model_call_used")) or _true(quality.get("live_model_call_used")):
            profile_live_count += 1

    ready_tasks = session.exec(
        select(Task)
        .where(Task.task_type == "vision_draft_review")
        .where(Task.status == "ready")
    ).all()
    task_no_live_count = 0
    task_live_count = 0
    for task in ready_tasks:
        payload = task.input_payload if isinstance(task.input_payload, dict) else {}
        if _true(payload.get("no_live_model_call")):
            task_no_live_count += 1
        if _true(payload.get("live_model_call_used")):
            task_live_count += 1
    return {
        "no_live_vision_profile_count": profile_no_live_count,
        "live_vision_profile_count": profile_live_count,
        "no_live_vision_ready_task_count": task_no_live_count,
        "live_vision_ready_task_count": task_live_count,
    }


def _embedding_status_counts(session: Session) -> Dict[str, int]:
    rows = session.exec(select(EmbeddingRecord).where(EmbeddingRecord.modality == "text")).all()
    counts: Dict[str, int] = {}
    for row in rows:
        counts[row.status] = counts.get(row.status, 0) + 1
    return counts


def compile_ai_spine_audit(
    *,
    session: Session,
    app_settings: Settings = settings,
) -> Dict[str, Any]:
    text_ready = live_text_generation_ready(app_settings)
    vision_gate_enabled = bool(app_settings.vision_live_calls_enabled)
    vision_ready = live_vision_ready(app_settings)
    embedding_ready = live_embedding_ready(app_settings)
    api_key_configured = bool(app_settings.openai_api_key)
    vision_scaffold_inventory = _vision_scaffold_inventory(session)
    no_live_vision_ready_task_count = vision_scaffold_inventory["no_live_vision_ready_task_count"]
    embedding_status_counts = _embedding_status_counts(session)
    embedded_text_record_count = embedding_status_counts.get("embedded", 0)
    ready_for_embedding_count = embedding_status_counts.get("ready_for_embedding", 0)
    vector_ready = embedding_ready and embedded_text_record_count > 0
    vision_review_task_count = _count_tasks(session, "vision_draft_review")
    prompt_pair_task_count = _count_tasks(session, "gold_voice_edit")
    source_review_task_count = sum(
        _count_tasks(session, task_type)
        for task_type in ("text_segment_review", "text_segment_boundary_review", "email_voice_sample")
    )
    photo_review_task_count = sum(
        _count_tasks(session, task_type)
        for task_type in ("photo_context", "vision_draft_review")
    )
    chat_fallback_policy = (
        "Strict-live chat is enabled; deterministic chat fallback is blocked when live calls are unavailable or fail."
        if app_settings.chat_require_live_model
        else "Falls back to deterministic plans when live calls are disabled or fail."
    )
    vision_backlog_risks = (
        [f"{no_live_vision_ready_task_count} ready vision review task(s) still carry no_live_model_call scaffold payloads."]
        if no_live_vision_ready_task_count
        else []
    )

    paths = [
        _path(
            path_id="chat_operator",
            label="Chat workbench operator",
            category="chat",
            status="live_ready" if text_ready else "blocked" if app_settings.chat_require_live_model else "fallback",
            model_status="live_model_available" if text_ready else "live_required_but_blocked" if app_settings.chat_require_live_model else "deterministic_fallback",
            live_capability="available" if text_ready else "blocked_by_env",
            env_gates=["OPENAI_API_KEY", "TEXT_GENERATION_LIVE_CALLS_ENABLED", "TEXT_GENERATION_MODEL", "CHAT_REQUIRE_LIVE_MODEL"],
            files=["apps/api/app/services/chat_operator.py", "apps/web/src/components/ChatWorkbench.tsx"],
            evidence=[
                "Calls OpenAI Responses API from _live_chat_plan when live_text_generation_ready is true.",
                "Can perform a bounded read-only tool pass over task schema, source material, image context, current draft, unified corpus inventory, and ranked evidence clusters before returning the final action plan.",
                "The plan_ranked_evidence_clusters tool groups reviewed photo memories, source excerpts, and approved voice records without exposing raw vectors or vector file pointers.",
                "The inspect_work_queue_plan tool lets Chat inspect ready ticket routes, training-board columns, and bottleneck state, then open a validated existing ready task with an open_task receipt.",
                "The create_or_open_review_task action can create or open a photo_context review task from a retrieval-gap photo cluster only after explicit confirmation, and records a task receipt.",
                "The create_or_open_review_task action can also create or open a source_review task from a source cluster only after explicit confirmation, and records a task receipt without creating a memory claim.",
                "After a confirmed submit, Chat can continue the same-route batch by opening the next ready ticket and recording an open_task receipt.",
                "When submit creates downstream source/photo prompt-pair candidate tasks, Chat opens the first generated candidate before falling back to same-route continuation.",
                "Generated candidate handoff is ranked by evidence quality and artifact-mode balance rather than raw creation order.",
                "The Chat UI renders ranked evidence clusters for the active ticket and can send a bounded review-cluster request back through Chat, keeping task creation behind backend validation.",
                "Draft-edit claims are sanitized unless the backend receives executable field_updates or draft_patch operations and records the resulting TaskDraft/action receipts.",
                chat_fallback_policy,
            ],
            risks=[
                "Cluster-to-ticket creation, downstream candidate handoff, same-route continuation, and generated-candidate evidence are now visible, but the full cluster-to-export workflow still needs end-to-end QA across real data.",
                "Chat still depends on Adam approvals between ticket submits, so bulk progress must be verified as a guided workflow rather than assumed automation.",
            ],
            next_action="QA the full Chat-led path from ranked evidence cluster to review task to generated candidate to approved export.",
        ),
        _path(
            path_id="operator_assistant",
            label="Task form operator assistant",
            category="chat",
            status="live_ready" if text_ready else "fallback",
            model_status="live_model_available" if text_ready else "deterministic_fallback",
            live_capability="available" if text_ready else "blocked_by_env",
            env_gates=["OPENAI_API_KEY", "TEXT_GENERATION_LIVE_CALLS_ENABLED"],
            files=["apps/api/app/services/operator_assistant.py", "apps/api/app/routers/tasks.py"],
            evidence=[
                "Calls OpenAI Responses API from _live_operator_response when live text generation is ready.",
                "Filters model field updates through allowed task fields.",
            ],
            risks=[
                "Still behaves like a form assistant, not the central intelligence layer.",
            ],
            next_action="Fold this into the AI workbench agent tool contract.",
        ),
        _path(
            path_id="text_draft_generation",
            label="Voice text draft generation",
            category="text_generation",
            status="live_ready" if text_ready else "scaffold",
            model_status="live_model_available" if text_ready else "scaffold_no_model_call",
            live_capability="available" if text_ready else "blocked_by_env",
            env_gates=["OPENAI_API_KEY", "TEXT_GENERATION_LIVE_CALLS_ENABLED"],
            files=["apps/api/app/services/model_generation.py", "apps/api/app/services/demo_generation.py"],
            evidence=[
                "generate_text_draft can call OpenAI Responses API.",
                "scaffold_voice_draft is used when live calls are disabled or explicitly bypassed.",
            ],
            risks=[
                "Scaffold text can look plausible unless the UI labels it clearly.",
                "Drafts are not yet systematically tied to retrieval evidence packets.",
            ],
            next_action="Require provenance badges and evidence refs before draft content can become approved training data.",
        ),
        _path(
            path_id="source_pair_generation",
            label="Source-to-prompt-pair generation",
            category="training_generation",
            status="live_ready" if text_ready else "fallback",
            model_status="live_model_available" if text_ready else "deterministic_pair_fallback",
            live_capability="available" if text_ready else "blocked_by_env",
            env_gates=["OPENAI_API_KEY", "TEXT_GENERATION_LIVE_CALLS_ENABLED"],
            files=["apps/api/app/services/pair_generation.py", "apps/api/app/routers/tasks.py"],
            evidence=[
                "_llm_pair_generation uses OpenAI when text generation is ready.",
                "Generated candidate pairs carry source_evidence_refs, source_excerpt_sha256, and an evidence_gate before task creation.",
                "Source review generation now attaches ranked evidence packets and can use live vector-query retrieval on submit/live paths.",
                "Generated prompt-pair review UI shows evidence gate status, source refs, ranked refs, generation strategy, and source excerpt hash while Adam edits the candidate.",
                "Chat now surfaces ranked source/photo/voice clusters for the active ticket and can request a source/photo review task from a cluster without turning it into a memory claim.",
                "Span/rule fallback paths still create candidate pairs, but only as Adam-review candidates with evidence metadata.",
            ],
            risks=[
                "Cluster-level source/photo work is now visible, but the handoff from cluster review action to generated candidate batch needs real-data QA.",
                "Generated candidate evidence is visible in the editor, but the product still needs QA that every exportable pair preserves its cited evidence through batch review.",
            ],
            next_action="Verify the cluster -> review task -> candidate generation -> approved export path with real long-document and photo-memory inputs.",
        ),
        _path(
            path_id="vision_pipeline",
            label="Photo and scan vision pipeline",
            category="vision",
            status="live_ready" if vision_ready else "scaffold",
            model_status="live_model_available" if vision_ready else "live_vision_blocked",
            live_capability="available" if vision_ready else "blocked_by_env",
            env_gates=["VISION_LIVE_CALLS_ENABLED", "VISION_MODEL", "OPENAI_API_KEY"],
            files=["apps/api/app/services/vision.py", "apps/api/app/routers/vision.py"],
            evidence=[
                "Vision schema and review tasks exist.",
                "create_vision_draft_batch can call a live vision model only when the vision gate and API key are configured.",
                f"Current ready vision task inventory: {vision_scaffold_inventory['live_vision_ready_task_count']} live-upgraded, {no_live_vision_ready_task_count} no-call scaffold.",
            ],
            risks=[
                *vision_backlog_risks,
                "Model photo observations remain unreviewed system_inference until Adam reviews them.",
                "Vision calls require local mirrored image pixels; missing mirrors still block live analysis.",
            ],
            next_action="Run live vision only for selected private assets, then route every result through Adam review before retrieval/export.",
        ),
        _path(
            path_id="semantic_memory",
            label="Embeddings and conceptual retrieval",
            category="retrieval",
            status="live_ready" if embedding_ready else "partial_scaffold",
            model_status="live_embedding_available" if embedding_ready else "provider_pending",
            live_capability="available" if embedding_ready else "partial",
            env_gates=["OPENAI_API_KEY", "EMBEDDING_LIVE_CALLS_ENABLED", "EMBEDDING_MODEL"],
            files=[
                "apps/api/app/services/embeddings.py",
                "apps/api/app/routers/retrieval.py",
                "apps/api/app/services/retrieval.py",
                "apps/api/app/services/context_packs.py",
            ],
            evidence=[
                "Embedding records and retrieval-oriented context packs exist.",
                "Live embedding batches can write OpenAI vector values to local vector files and keep pointers in EmbeddingRecord rows.",
                "/api/retrieval/evidence-corpus exposes one manifest across photo memory, voice references, approved training voice, and source context records.",
                "/api/retrieval/evidence-clusters and Chat's plan_ranked_evidence_clusters tool group boundary-filtered records into planning clusters without raw vectors.",
                "Chat renders ranked evidence clusters from /api/retrieval/evidence-clusters and includes a review-cluster control that re-enters the validated Chat action flow.",
                "Chat, source review, and export dry-runs now surface the unified evidence corpus instead of treating evidence as isolated per-screen metadata.",
                "Source-to-SFT/DPO generation now uses ranked evidence packets and stores those packets on generated review tasks, context packs, prompt specs, and receipts.",
                f"Current text embedding inventory: {embedded_text_record_count} embedded, {ready_for_embedding_count} ready for embedding.",
            ],
            risks=[
                (
                    "Some text embedding records are still waiting for live vectorization."
                    if ready_for_embedding_count
                    else "Vectorized retrieval and cluster UI are available; remaining risk is end-to-end QA of cluster-driven work across real data."
                ),
                "Large-document and photo-memory clusters are inspectable, can become review tickets, and can hand off ranked generated candidates; remaining risk is verifying provenance through approval and export.",
            ],
            next_action="Run end-to-end QA for source/photo candidate evidence refs, ranking reasons, review receipts, and export eligibility.",
        ),
    ]

    risks: List[Dict[str, Any]] = []
    for path in paths:
        severity = "high" if path["id"] == "vision_pipeline" and not vision_ready else "medium" if path["risks"] else "low"
        if path["status"] in {"scaffold", "partial_scaffold", "fallback"}:
            severity = "high" if path["id"] in {"vision_pipeline", "semantic_memory"} else "medium"
        for risk in path["risks"]:
            risks.append(
                {
                    "path_id": path["id"],
                    "severity": severity,
                    "risk": risk,
                    "next_action": path["next_action"],
                }
            )

    summary = {
        "text_generation_ready": text_ready,
        "openai_api_key_configured": api_key_configured,
        "text_generation_live_calls_enabled": bool(app_settings.text_generation_live_calls_enabled),
        "chat_require_live_model": bool(app_settings.chat_require_live_model),
        "vision_live_calls_enabled": vision_gate_enabled,
        "vision_live_ready": vision_ready,
        "embedding_live_calls_enabled": bool(app_settings.embedding_live_calls_enabled),
        "embedding_live_ready": embedding_ready,
        "embedded_text_record_count": embedded_text_record_count,
        "ready_for_embedding_count": ready_for_embedding_count,
        "vector_ready": vector_ready,
        "live_path_count": len([path for path in paths if path["status"] == "live_ready"]),
        "scaffold_or_fallback_path_count": len([path for path in paths if path["status"] in {"scaffold", "partial_scaffold", "fallback"}]),
        "highest_risk": (
            "vision_pipeline_not_live"
            if not vision_ready
            else "semantic_memory_not_live"
            if not embedding_ready
            else "vision_scaffold_backlog"
            if no_live_vision_ready_task_count
            else "embedding_backlog_not_vectorized"
            if ready_for_embedding_count
            else "workflow_qa_unverified"
        ),
        "recommended_next_step": "Wire reviewed memory embeddings."
        if not embedding_ready
        else "Run live vision for remaining scaffolded ready review tasks."
        if no_live_vision_ready_task_count
        else "Run remaining embedding batches."
        if ready_for_embedding_count
        else "QA the full evidence-cluster workflow from Chat to review task to generated candidate to approved export.",
    }

    return {
        "audit_type": "ai_spine_audit",
        "generated_at": _now_iso(),
        "summary": summary,
        "providers": {
            "text_generation": {
                "model": app_settings.text_generation_model,
                "reasoning_effort": app_settings.text_generation_reasoning_effort,
                "live_calls_enabled": bool(app_settings.text_generation_live_calls_enabled),
                "api_key_configured": api_key_configured,
                "ready": text_ready,
            },
            "chat": {
                "model": app_settings.text_generation_model,
                "reasoning_effort": getattr(app_settings, "chat_reasoning_effort", app_settings.text_generation_reasoning_effort),
                "require_live_model": bool(app_settings.chat_require_live_model),
                "ready": text_ready,
                "reason_not_ready": None if text_ready else "live_chat_required_but_model_not_ready" if app_settings.chat_require_live_model else "text_generation_live_gate_or_api_key_missing",
            },
            "vision": {
                "model": app_settings.vision_model,
                "live_calls_enabled": vision_gate_enabled,
                "api_key_configured": api_key_configured,
                "ready": vision_ready,
                "reason_not_ready": None if vision_ready else "vision_live_gate_or_api_key_missing",
                **vision_scaffold_inventory,
            },
            "embeddings": {
                "model": app_settings.embedding_model,
                "live_calls_enabled": bool(app_settings.embedding_live_calls_enabled),
                "api_key_configured": api_key_configured,
                "ready": embedding_ready,
                "reason_not_ready": None if embedding_ready else "embedding_live_gate_or_api_key_missing",
                "embedded_text_record_count": embedded_text_record_count,
                "ready_for_embedding_count": ready_for_embedding_count,
                "vector_ready": vector_ready,
            },
        },
        "counts": {
            "prompt_pair_task_count": prompt_pair_task_count,
            "source_review_task_count": source_review_task_count,
            "photo_review_task_count": photo_review_task_count,
            "vision_review_task_count": vision_review_task_count,
            **vision_scaffold_inventory,
            "embedded_text_record_count": embedded_text_record_count,
            "ready_for_embedding_count": ready_for_embedding_count,
        },
        "paths": paths,
        "risks": risks,
        "recommended_next_actions": [
            "Expose this audit in the global workbench chrome.",
            "Add live/scaffold/fallback provenance badges to generated content.",
            "Add an opt-in live AI smoke script that records model response IDs without mutating production data.",
            "Run safe live vision analysis as system_inference for selected photo batches.",
            "Require evidence refs for generated SFT/DPO candidates before approval/export.",
            "Make Chat's planned mutations visible as applied receipts, blocked patches, or pending confirmations every time.",
            "Add retrieval-cluster planning so large documents are reviewed as coherent evidence groups rather than one flat task.",
        ],
        "safety_policy": {
            "never_return_secret_values": True,
            "model_outputs_are_not_truth_until_reviewed": True,
            "scaffold_outputs_must_be_labeled": True,
            "exports_should_exclude_unreviewed_scaffolds": True,
            "submit_and_export_require_confirmation": True,
        },
    }
