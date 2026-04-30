#!/usr/bin/env python3
"""Live acceptance gate for CharlesOps Ralph-loop runs.

This is intentionally stricter than the ordinary unit test suite. Unit tests can
prove a local behavior is protected; this gate checks whether the live product
state has reached the next user-facing milestone. A Ralph loop should keep
working while this script exits nonzero, unless it hits a real blocker.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import runpy
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
PROMPT_PAIRS_VISUAL_CHECKPOINT = ROOT / "updates" / "prompt_pairs_work_queue_2026-04-29.png"
PROMPT_PAIRS_VISUAL_METADATA = ROOT / "updates" / "prompt_pairs_work_queue_2026-04-29.json"
PHOTO_CONTEXT_VISUAL_CHECKPOINT = ROOT / "updates" / "photo_context_workbench_2026-04-29.png"
PHOTO_CONTEXT_VISUAL_METADATA = ROOT / "updates" / "photo_context_workbench_2026-04-29.json"


@dataclass
class Check:
    name: str
    passed: bool
    detail: str
    evidence: dict[str, Any] = field(default_factory=dict)


def _url(base: str, path: str, params: dict[str, Any] | None = None) -> str:
    normalized = f"{base.rstrip('/')}/{path.lstrip('/')}"
    if params:
        normalized = f"{normalized}?{urllib.parse.urlencode(params)}"
    return normalized


def get_json(base: str, path: str, params: dict[str, Any] | None = None, timeout: float = 10) -> Any:
    request = urllib.request.Request(_url(base, path, params), headers={"Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        body = response.read().decode("utf-8")
    return json.loads(body)


def post_json(base: str, path: str, params: dict[str, Any] | None = None, timeout: float = 10) -> Any:
    request = urllib.request.Request(
        _url(base, path, params),
        data=b"{}",
        headers={"Accept": "application/json", "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        body = response.read().decode("utf-8")
    return json.loads(body)


def post_json_body(base: str, path: str, payload: dict[str, Any], timeout: float = 10) -> Any:
    request = urllib.request.Request(
        _url(base, path),
        data=json.dumps(payload).encode("utf-8"),
        headers={"Accept": "application/json", "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        body = response.read().decode("utf-8")
    return json.loads(body)


def get_bytes(base: str, path: str, timeout: float = 10) -> tuple[str, bytes]:
    request = urllib.request.Request(_url(base, path), headers={"Accept": "*/*"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.headers.get("content-type", ""), response.read()


def get_status(url: str, timeout: float = 10) -> int:
    request = urllib.request.Request(url, headers={"Accept": "text/html,application/json"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return int(response.status)


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def png_dimensions(path: Path) -> tuple[int, int]:
    data = path.read_bytes()[:24]
    if len(data) < 24 or data[:8] != b"\x89PNG\r\n\x1a\n" or data[12:16] != b"IHDR":
        raise ValueError("not a PNG file")
    return int.from_bytes(data[16:20], "big"), int.from_bytes(data[20:24], "big")


def safe_check(name: str, fn) -> Check:
    try:
        return fn()
    except urllib.error.HTTPError as exc:
        return Check(name, False, f"HTTP {exc.code}: {exc.reason}", {"url": getattr(exc, "url", "")})
    except Exception as exc:  # noqa: BLE001 - gate should report, not crash unclearly.
        return Check(name, False, f"{type(exc).__name__}: {exc}", {})


def expected_runtime_contract() -> dict[str, Any]:
    repo_root = Path(__file__).resolve().parents[1]
    contract_path = repo_root / "apps/api/app/runtime_contract.py"
    namespace = runpy.run_path(str(contract_path))
    contract = namespace.get("RUNTIME_CONTRACT")
    if not isinstance(contract, dict):
        raise RuntimeError("RUNTIME_CONTRACT missing from apps/api/app/runtime_contract.py")
    return {
        **contract,
        "runtime_contract_source_sha256": hashlib.sha256(contract_path.read_bytes()).hexdigest(),
    }


def command_check(name: str, command: list[str], *, timeout: float = 120) -> Check:
    repo_root = Path(__file__).resolve().parents[1]
    completed = subprocess.run(
        command,
        cwd=repo_root,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    output = "\n".join(part for part in [completed.stdout.strip(), completed.stderr.strip()] if part)
    return Check(
        name,
        completed.returncode == 0,
        "focused contract tests passed" if completed.returncode == 0 else "focused contract tests failed",
        {
            "command": " ".join(command),
            "returncode": completed.returncode,
            "output_tail": output[-2000:],
        },
    )


def summarize_dry_run(payload: dict[str, Any]) -> dict[str, Any]:
    included = payload.get("included") if isinstance(payload.get("included"), list) else []
    excluded = payload.get("excluded") if isinstance(payload.get("excluded"), list) else []
    return {
        "export_type": payload.get("export_type"),
        "mode": payload.get("mode"),
        "included_count": payload.get("included_count"),
        "excluded_count": payload.get("excluded_count"),
        "included_artifact_types": sorted({str(item.get("artifact_type")) for item in included[:1000]}),
        "excluded_reasons": sorted(
            {
                str(reason)
                for item in excluded[:1000]
                for reason in (item.get("reasons") or [])
            }
        ),
        "sample_included": [
            {
                "review_blockers": ((item.get("payload") or {}).get("metadata") or {}).get("review_blockers") or [],
                "artifact_type": item.get("artifact_type"),
                "artifact_id": item.get("artifact_id"),
                "export_status": item.get("export_status"),
                "voice_mode": ((item.get("payload") or {}).get("metadata") or {}).get("voice_mode")
                or (item.get("source") or {}).get("voice_mode"),
            }
            for item in included[:3]
        ],
    }


def training_payload_key(item: dict[str, Any]) -> str:
    payload = item.get("payload") if isinstance(item.get("payload"), dict) else {}
    if "messages" in payload:
        key_payload = {"messages": payload.get("messages") or []}
    else:
        key_payload = {
            "input": payload.get("input") or {},
            "preferred_output": payload.get("preferred_output") or "",
            "non_preferred_output": payload.get("non_preferred_output") or "",
        }
    return json.dumps(key_payload, ensure_ascii=False, sort_keys=True)


def included_duplicate_count(payload: dict[str, Any]) -> int:
    included = payload.get("included") if isinstance(payload.get("included"), list) else []
    seen: set[str] = set()
    duplicate_count = 0
    for item in included:
        key = training_payload_key(item)
        if key in seen:
            duplicate_count += 1
        else:
            seen.add(key)
    return duplicate_count


def candidate_rows_missing_blockers(payload: dict[str, Any]) -> list[str]:
    included = payload.get("included") if isinstance(payload.get("included"), list) else []
    missing: list[str] = []
    for item in included[:1000]:
        if item.get("export_status") not in {"candidate", "review_candidate"}:
            continue
        metadata = ((item.get("payload") or {}).get("metadata") or {})
        blockers = metadata.get("review_blockers")
        if not isinstance(blockers, list) or not blockers:
            missing.append(str(item.get("artifact_id") or item.get("artifact_type") or "unknown"))
    return missing


def dpo_candidate_rows_missing_issue_context(payload: dict[str, Any]) -> list[str]:
    included = payload.get("included") if isinstance(payload.get("included"), list) else []
    missing: list[str] = []
    for item in included[:1000]:
        if item.get("artifact_type") != "prompt_pair_dpo_review_candidate":
            continue
        item_id = str(item.get("artifact_id") or item.get("artifact_type") or "unknown")
        row_payload = item.get("payload") if isinstance(item.get("payload"), dict) else {}
        metadata = row_payload.get("metadata") if isinstance(row_payload.get("metadata"), dict) else {}
        reason = metadata.get("reason") if isinstance(metadata.get("reason"), list) else []
        chosen_summary = (
            metadata.get("chosen_issue_summary")
            if isinstance(metadata.get("chosen_issue_summary"), dict)
            else {}
        )
        rejected_summary = (
            metadata.get("rejected_issue_summary")
            if isinstance(metadata.get("rejected_issue_summary"), dict)
            else {}
        )
        policy = (
            metadata.get("candidate_review_policy")
            if isinstance(metadata.get("candidate_review_policy"), dict)
            else {}
        )
        rejected = str(row_payload.get("non_preferred_output") or "").strip()
        chosen = str(row_payload.get("preferred_output") or "").strip()
        explanatory_reason_count = len(
            [
                item
                for item in reason
                if isinstance(item, str) and ":" in item and len(item.strip()) >= 60
            ]
        )
        if not chosen or not rejected or chosen == rejected:
            missing.append(f"{item_id}: chosen/rejected text is empty or identical")
        if explanatory_reason_count < 1:
            missing.append(f"{item_id}: missing explanatory DPO reason")
        if int(chosen_summary.get("issue_count", 99)) != 0:
            missing.append(f"{item_id}: chosen side is not marked issue-free")
        if int(rejected_summary.get("issue_count", 0)) < 1:
            missing.append(f"{item_id}: rejected side lacks issue count")
        if rejected_summary.get("has_explanatory_notes") is not True:
            missing.append(f"{item_id}: rejected side lacks explanatory notes")
        if policy.get("adam_review_required") is not True:
            missing.append(f"{item_id}: Adam review policy missing")
        if policy.get("does_not_certify_final_authenticity") is not True:
            missing.append(f"{item_id}: final-authenticity disclaimer missing")
    return missing


def title_matches(asset: dict[str, Any], expected: str) -> bool:
    expected_lower = expected.lower()
    return any(
        str(asset.get(key) or "").lower() == expected_lower
        for key in ("title", "original_filename", "human_id")
    )


def run_gate(args: argparse.Namespace) -> list[Check]:
    checks: list[Check] = []

    checks.append(
        safe_check(
            "API health is reachable",
            lambda: Check(
                "API health is reachable",
                bool(get_json(args.api_base, "/health").get("ok")),
                "GET /health returned ok",
            ),
        )
    )

    def runtime_contract_is_current() -> Check:
        expected = expected_runtime_contract()
        actual = get_json(args.api_base, "/runtime-contract")
        failures = []
        if actual.get("contract_id") != expected.get("contract_id"):
            failures.append(
                f"runtime contract id mismatch: live={actual.get('contract_id')} source={expected.get('contract_id')}"
            )
        if actual.get("runtime_contract_source_sha256") != expected.get("runtime_contract_source_sha256"):
            failures.append("runtime contract source checksum mismatch; running API container may be stale")
        required_fields = expected.get("required_response_fields")
        if actual.get("required_response_fields") != required_fields:
            failures.append("live runtime contract required fields differ from source")
        if actual.get("no_fine_tuning_api_calls_in_mvp") is not True:
            failures.append("runtime contract must preserve no-fine-tuning MVP rule")
        return Check(
            "API runtime contract matches checked-out source",
            not failures,
            "; ".join(failures) if failures else "running API reports the current checked-out runtime contract",
            {
                "contract_id": actual.get("contract_id"),
                "runtime_contract_source_sha256": actual.get("runtime_contract_source_sha256"),
                "required_response_fields": actual.get("required_response_fields"),
            },
        )

    checks.append(safe_check("API runtime contract matches checked-out source", runtime_contract_is_current))

    def source_review_pair_generation_preview_contract() -> Check:
        contract = get_json(args.api_base, "/runtime-contract")
        required_fields = (
            (contract.get("required_response_fields") or {}).get("/api/tasks/{task_id}/pair-generation/preview")
            if isinstance(contract.get("required_response_fields"), dict)
            else []
        )
        tasks_before = get_json(args.api_base, "/tasks")
        source_tasks = [
            task
            for task in tasks_before
            if isinstance(task, dict)
            and task.get("status") == "ready"
            and task.get("task_type") in {"text_segment_review", "text_segment_boundary_review", "email_voice_sample"}
        ]
        failures = []
        if not source_tasks:
            failures.append("no ready source-review task available to preview")
            return Check(
                "Source Review pair generation preview is contract-checked",
                False,
                "; ".join(failures),
                {"ready_source_task_count": 0},
            )
        task = source_tasks[0]
        preview = post_json_body(
            args.api_base,
            f"/tasks/{task['id']}/pair-generation/preview",
            {"decisions": {"generate_pairs_on_submit": "yes", "voice_mode": "father_to_adam", "synthetic": True}},
            timeout=30,
        )
        tasks_after = get_json(args.api_base, "/tasks")
        missing_fields = [field for field in required_fields if field not in preview]
        if missing_fields:
            failures.append(f"preview missing runtime-contract fields: {missing_fields}")
        if preview.get("preview_type") != "source_review_generate_pairs_preview":
            failures.append("unexpected preview type")
        if preview.get("does_not_mutate_state") is not True:
            failures.append("preview must be non-mutating")
        if preview.get("no_live_model_call") is not True:
            failures.append("preview must avoid live model calls")
        if len(str(preview.get("content_sha256") or "")) != 64:
            failures.append("preview lacks stable content hash")
        if int(preview.get("candidate_pair_count") or 0) < int(preview.get("projected_created_pair_count") or 0):
            failures.append("candidate pair count is lower than projected created count")
        if int(preview.get("projected_created_pair_count") or 0) < 1:
            failures.append("preview should identify at least one creatable prompt-pair ticket in current source queue")
        safety_text = "\n".join(str(item) for item in preview.get("safety_boundaries") or [])
        if "does not create" not in safety_text or "Raw imported source files remain unchanged" not in safety_text:
            failures.append("preview safety boundaries must mention non-creation and raw-source preservation")
        before_ids = {task.get("id") for task in tasks_before if isinstance(task, dict)}
        after_ids = {task.get("id") for task in tasks_after if isinstance(task, dict)}
        if before_ids != after_ids:
            failures.append("preview mutated the task set")
        return Check(
            "Source Review pair generation preview is contract-checked",
            not failures,
            "; ".join(failures)
            if failures
            else "source-review Generate Pairs dry-run exposes required fields without mutating tasks",
            {
                "task_human_id": task.get("human_id"),
                "required_field_count": len(required_fields),
                "projected_created_pair_count": preview.get("projected_created_pair_count"),
                "candidate_pair_count": preview.get("candidate_pair_count"),
                "primary_strategy": preview.get("primary_strategy"),
                "content_sha256": preview.get("content_sha256"),
            },
        )

    checks.append(
        safe_check(
            "Source Review pair generation preview is contract-checked",
            source_review_pair_generation_preview_contract,
        )
    )

    checks.append(
        safe_check(
            "Production slice stabilization regressions are protected",
            lambda: command_check(
                "Production slice stabilization regressions are protected",
                [
                    "docker",
                    "compose",
                    "exec",
                    "-T",
                    "api",
                    "pytest",
                    "-q",
                    "tests/test_context_packs.py::test_context_pack_builder_excludes_missing_boundaries_by_default",
                    "tests/test_context_packs.py::test_real_photo_context_submit_feeds_context_pack_with_photo_memory_profile_shape",
                    "tests/test_task_submit.py::test_task_submit_rejects_non_ready_resubmission_without_duplicate_artifacts",
                    "tests/test_ralph_phase2_photo_spine.py::test_family_private_retrieval_excludes_sensitive_privacy_even_if_flags_are_wrong",
                    "tests/test_dataset_exports.py::test_approved_actual_rows_with_quality_or_structural_blockers_are_excluded",
                    "tests/test_ralph_phase3_prompt_pair_audit.py::test_prompt_pair_source_boundary_preflight_respects_artifact_mode_permissions",
                ],
                timeout=180,
            ),
        )
    )

    checks.append(
        safe_check(
            "Web app is reachable",
            lambda: Check(
                "Web app is reachable",
                get_status(args.web_base) == 200,
                f"GET {args.web_base} returned 200",
            ),
        )
    )

    checks.append(
        safe_check(
            "Web workbench typechecks",
            lambda: command_check(
                "Web workbench typechecks",
                ["npm", "run", "typecheck", "--prefix", "apps/web"],
                timeout=180,
            ),
        )
    )

    checks.append(
        safe_check(
            "Web readiness UI exposes demo gate, photo review, and retrieval actions",
            lambda: command_check(
                "Web readiness UI exposes demo gate, photo review, and retrieval actions",
                ["npx", "--prefix", "apps/web", "playwright", "test", "--config", "apps/web/playwright.config.ts"],
                timeout=180,
            ),
        )
    )

    def prompt_pairs_visual_checkpoint() -> Check:
        audit = get_json(args.api_base, "/prompt-pairs/audit", {"sample_limit": 1}, timeout=30)
        dpo_packet = get_json(args.api_base, "/prompt-pairs/dpo-rejected-reason-repair-pack", {"limit": 25}, timeout=30)
        failures: list[str] = []
        metadata: dict[str, Any] = {}
        width = 0
        height = 0
        screenshot_sha = ""
        if not PROMPT_PAIRS_VISUAL_CHECKPOINT.exists():
            failures.append("prompt-pairs visual checkpoint PNG is missing")
        else:
            try:
                width, height = png_dimensions(PROMPT_PAIRS_VISUAL_CHECKPOINT)
                if width < 1200 or height < 900:
                    failures.append(f"prompt-pairs visual checkpoint is too small: {width}x{height}")
                if PROMPT_PAIRS_VISUAL_CHECKPOINT.stat().st_size < 25_000:
                    failures.append("prompt-pairs visual checkpoint file is unexpectedly small")
                screenshot_sha = file_sha256(PROMPT_PAIRS_VISUAL_CHECKPOINT)
            except Exception as exc:  # noqa: BLE001 - gate should explain artifact corruption.
                failures.append(f"prompt-pairs visual checkpoint is not a valid PNG: {exc}")
        if not PROMPT_PAIRS_VISUAL_METADATA.exists():
            failures.append("prompt-pairs visual checkpoint metadata is missing")
        else:
            try:
                metadata = json.loads(PROMPT_PAIRS_VISUAL_METADATA.read_text(encoding="utf-8"))
            except json.JSONDecodeError as exc:
                failures.append(f"prompt-pairs visual checkpoint metadata is invalid JSON: {exc}")
        if metadata:
            if metadata.get("checkpoint_type") != "prompt_pairs_work_queue_visual_checkpoint":
                failures.append("prompt-pairs visual metadata has unexpected checkpoint_type")
            if metadata.get("screenshot_path") != str(PROMPT_PAIRS_VISUAL_CHECKPOINT.relative_to(ROOT)):
                failures.append("prompt-pairs visual metadata screenshot_path does not match checkpoint path")
            captured_at_raw = str(metadata.get("captured_at") or "")
            try:
                captured_at = datetime.fromisoformat(captured_at_raw.replace("Z", "+00:00"))
                age_seconds = (datetime.now(timezone.utc) - captured_at.astimezone(timezone.utc)).total_seconds()
                if age_seconds > 20 * 60:
                    failures.append(f"prompt-pairs visual checkpoint is stale: {int(age_seconds)} seconds old")
                if age_seconds < -60:
                    failures.append("prompt-pairs visual checkpoint timestamp is in the future")
            except ValueError:
                failures.append("prompt-pairs visual checkpoint metadata captured_at is malformed")
            for field in ["total_pairs", "inspectable_pair_count"]:
                if int(metadata.get(field) or 0) != int(audit.get(field) or 0):
                    failures.append(f"prompt-pairs visual metadata {field} does not match live audit")
            if metadata.get("preflight_gate_counts") != audit.get("preflight_gate_counts"):
                failures.append("prompt-pairs visual metadata gate counts do not match live audit")
            if metadata.get("preflight_blocker_counts") != audit.get("preflight_blocker_counts"):
                failures.append("prompt-pairs visual metadata blocker counts do not match live audit")
            if int(metadata.get("dpo_rejected_reason_total_candidate_count") or 0) != int(
                dpo_packet.get("total_candidate_count") or 0
            ):
                failures.append("prompt-pairs visual metadata DPO repair total does not match live packet")
            required_assertions = {
                "prompt_pair_filters_visible",
                "prompt_pair_readiness_counts_visible",
                "dpo_rejected_reason_repair_queue_visible",
                "prompt_pair_ticket_selected",
                "prompt_pair_export_gate_visible",
            }
            actual_assertions = set(metadata.get("ui_assertions") or [])
            missing_assertions = sorted(required_assertions - actual_assertions)
            if missing_assertions:
                failures.append(f"prompt-pairs visual metadata missing UI assertions: {missing_assertions}")
        return Check(
            "Prompt Pairs working surface has a fresh visual checkpoint",
            not failures,
            "; ".join(failures)
            if failures
            else "Prompt Pairs screenshot and sidecar match the live queue counts from this gate run",
            {
                "screenshot_path": str(PROMPT_PAIRS_VISUAL_CHECKPOINT.relative_to(ROOT)),
                "metadata_path": str(PROMPT_PAIRS_VISUAL_METADATA.relative_to(ROOT)),
                "width": width,
                "height": height,
                "screenshot_sha256": screenshot_sha,
                "metadata_captured_at": metadata.get("captured_at"),
                "preflight_gate_counts": metadata.get("preflight_gate_counts"),
                "preflight_blocker_counts": metadata.get("preflight_blocker_counts"),
            },
        )

    checks.append(
        safe_check(
            "Prompt Pairs working surface has a fresh visual checkpoint",
            prompt_pairs_visual_checkpoint,
        )
    )

    def photo_context_visual_checkpoint() -> Check:
        session_plan = get_json(
            args.api_base,
            "/assets/photo-context-review-pack/review-session-plan",
            {"scope": "family_private", "limit": 5, "source_query": "Old Orchard beach"},
            timeout=30,
        )
        session_progress = get_json(
            args.api_base,
            "/assets/photo-context-review-pack/session-progress",
            {"scope": "family_private", "limit": 100},
            timeout=30,
        )
        top_slice = get_json(
            args.api_base,
            "/assets/photo-context-review-pack/top-context-slice",
            {"scope": "family_private", "limit": 5},
            timeout=30,
        )
        failures: list[str] = []
        metadata: dict[str, Any] = {}
        width = 0
        height = 0
        screenshot_sha = ""
        if not PHOTO_CONTEXT_VISUAL_CHECKPOINT.exists():
            failures.append("photo-context visual checkpoint PNG is missing")
        else:
            try:
                width, height = png_dimensions(PHOTO_CONTEXT_VISUAL_CHECKPOINT)
                if width < 1200 or height < 900:
                    failures.append(f"photo-context visual checkpoint is too small: {width}x{height}")
                if PHOTO_CONTEXT_VISUAL_CHECKPOINT.stat().st_size < 25_000:
                    failures.append("photo-context visual checkpoint file is unexpectedly small")
                screenshot_sha = file_sha256(PHOTO_CONTEXT_VISUAL_CHECKPOINT)
            except Exception as exc:  # noqa: BLE001 - gate should explain artifact corruption.
                failures.append(f"photo-context visual checkpoint is not a valid PNG: {exc}")
        if not PHOTO_CONTEXT_VISUAL_METADATA.exists():
            failures.append("photo-context visual checkpoint metadata is missing")
        else:
            try:
                metadata = json.loads(PHOTO_CONTEXT_VISUAL_METADATA.read_text(encoding="utf-8"))
            except json.JSONDecodeError as exc:
                failures.append(f"photo-context visual checkpoint metadata is invalid JSON: {exc}")
        if metadata:
            if metadata.get("checkpoint_type") != "photo_context_workbench_visual_checkpoint":
                failures.append("photo-context visual metadata has unexpected checkpoint_type")
            if metadata.get("screenshot_path") != str(PHOTO_CONTEXT_VISUAL_CHECKPOINT.relative_to(ROOT)):
                failures.append("photo-context visual metadata screenshot_path does not match checkpoint path")
            captured_at_raw = str(metadata.get("captured_at") or "")
            try:
                captured_at = datetime.fromisoformat(captured_at_raw.replace("Z", "+00:00"))
                age_seconds = (datetime.now(timezone.utc) - captured_at.astimezone(timezone.utc)).total_seconds()
                if age_seconds > 20 * 60:
                    failures.append(f"photo-context visual checkpoint is stale: {int(age_seconds)} seconds old")
                if age_seconds < -60:
                    failures.append("photo-context visual checkpoint timestamp is in the future")
            except ValueError:
                failures.append("photo-context visual checkpoint metadata captured_at is malformed")
            if metadata.get("source_query") != session_plan.get("source_query"):
                failures.append("photo-context visual metadata source query does not match live session plan")
            if metadata.get("session_plan_content_sha256") != session_plan.get("content_sha256"):
                failures.append("photo-context visual metadata plan hash does not match live session plan")
            if metadata.get("session_progress_content_sha256") != session_progress.get("content_sha256"):
                failures.append("photo-context visual metadata progress hash does not match live session progress")
            if metadata.get("top_slice_content_sha256") != top_slice.get("content_sha256"):
                failures.append("photo-context visual metadata top-slice hash does not match live top slice")
            for metadata_field, live_field in [
                ("selected_count", session_plan.get("selected_count")),
                ("candidate_count", session_plan.get("candidate_count")),
                ("reported_task_count", session_progress.get("reported_task_count")),
                ("submit_ready_count", session_progress.get("submit_ready_count")),
                ("retrieval_gap_task_count", session_progress.get("retrieval_gap_task_count")),
                ("review_session_task_count", session_progress.get("review_session_task_count")),
                ("top_slice_candidate_count", top_slice.get("candidate_count")),
                ("top_slice_reported_candidate_count", top_slice.get("reported_candidate_count")),
            ]:
                if int(metadata.get(metadata_field) or 0) != int(live_field or 0):
                    failures.append(f"photo-context visual metadata {metadata_field} does not match live API")
            if not metadata.get("selected_task_title"):
                failures.append("photo-context visual metadata lacks selected task title")
            required_assertions = {
                "photo_preview_visible",
                "review_seed_visible_as_workflow_provenance",
                "completion_payoff_visible",
                "required_adam_fields_visible",
                "ready_submit_checklist_visible",
                "optional_search_note_not_required",
                "downstream_memory_preview_visible",
                "adam_review_prompt_says_photo_sparks_memories",
            }
            actual_assertions = set(metadata.get("ui_assertions") or [])
            missing_assertions = sorted(required_assertions - actual_assertions)
            if missing_assertions:
                failures.append(f"photo-context visual metadata missing UI assertions: {missing_assertions}")
        return Check(
            "Photo Context workbench has a fresh visual checkpoint",
            not failures,
            "; ".join(failures)
            if failures
            else "Photo Context screenshot and sidecar match live review seed, progress, and field hashes",
            {
                "screenshot_path": str(PHOTO_CONTEXT_VISUAL_CHECKPOINT.relative_to(ROOT)),
                "metadata_path": str(PHOTO_CONTEXT_VISUAL_METADATA.relative_to(ROOT)),
                "width": width,
                "height": height,
                "screenshot_sha256": screenshot_sha,
                "metadata_captured_at": metadata.get("captured_at"),
                "source_query": metadata.get("source_query"),
                "selected_task_title": metadata.get("selected_task_title"),
                "reported_task_count": metadata.get("reported_task_count"),
                "review_session_task_count": metadata.get("review_session_task_count"),
            },
        )

    checks.append(
        safe_check(
            "Photo Context workbench has a fresh visual checkpoint",
            photo_context_visual_checkpoint,
        )
    )

    def downstream_bottleneck_queue_readiness() -> Check:
        queue = get_json(args.api_base, "/downstream-readiness/bottlenecks", {"scope": "family_private", "limit": 4})
        items = queue.get("items") if isinstance(queue.get("items"), list) else []
        ordered_area_keys = queue.get("ordered_area_keys") if isinstance(queue.get("ordered_area_keys"), list) else []
        verification = queue.get("machine_verification") if isinstance(queue.get("machine_verification"), dict) else {}
        failures = []
        if queue.get("queue_type") != "downstream_bottleneck_queue":
            failures.append("unexpected downstream bottleneck queue type")
        if queue.get("review_policy") != "ranked_operator_actions_no_source_mutation":
            failures.append("bottleneck queue lacks no-source-mutation policy")
        if queue.get("does_not_mutate_state") is not True:
            failures.append("bottleneck queue must be read-only")
        if queue.get("no_live_model_call") is not True:
            failures.append("bottleneck queue must not call live models")
        if queue.get("no_fine_tuning_api_calls_in_mvp") is not True:
            failures.append("bottleneck queue must preserve no-fine-tuning MVP rule")
        if len(items) < 3:
            failures.append("bottleneck queue should expose prompt/photo/demo work")
        if ordered_area_keys != [item.get("area_key") for item in items]:
            failures.append("ordered_area_keys does not mirror item order")
        if verification.get("ordered_area_keys") != ordered_area_keys:
            failures.append("machine verification ordered keys do not mirror queue")
        if verification.get("every_item_has_action") is not True:
            failures.append("machine verification must confirm every item has an action")
        queue_hash = str(verification.get("queue_sha256") or "")
        if len(queue_hash) != 64 or not all(char in "0123456789abcdef" for char in queue_hash):
            failures.append("machine verification queue hash is missing or malformed")
        priority_ranks = [int(item.get("priority_rank", 99)) for item in items if isinstance(item, dict)]
        if priority_ranks != sorted(priority_ranks):
            failures.append("bottleneck items are not sorted by priority rank")
        if ordered_area_keys[:2] != ["prompt_pairs", "photo_context"]:
            failures.append("prompt-pair and photo-context work should be the first two bottlenecks")
        for required in ["prompt_pairs", "photo_context", "demo_generation"]:
            if required not in ordered_area_keys:
                failures.append(f"bottleneck queue lacks {required}")
        for item in items:
            if not isinstance(item, dict):
                failures.append("bottleneck item is malformed")
                continue
            action = item.get("action") if isinstance(item.get("action"), dict) else {}
            policy = item.get("policy") if isinstance(item.get("policy"), dict) else {}
            if not item.get("summary") or not item.get("next_action"):
                failures.append(f"{item.get('area_key')} lacks summary or next action")
            if not action.get("action_type") or not action.get("label"):
                failures.append(f"{item.get('area_key')} lacks concrete action type/label")
            if item.get("area_key") == "prompt_pairs":
                if policy.get("adam_review_required") is not True:
                    failures.append("prompt-pair bottleneck lacks Adam-review policy")
                if action.get("enabled") is not True or not action.get("task_id"):
                    failures.append("prompt-pair bottleneck lacks openable task")
            if item.get("area_key") == "photo_context":
                if policy.get("truth_status_before_review") != "no_claim":
                    failures.append("photo-context bottleneck lacks no-claim truth policy")
                if policy.get("not_memory_claim_until_adam_context") is not True:
                    failures.append("photo-context bottleneck lacks not-memory-claim policy")
            if item.get("area_key") == "vector_handoff":
                if policy.get("review_policy") != "reviewed_only_by_default":
                    failures.append("vector bottleneck lacks reviewed-only policy")
                if policy.get("live_embedding_call") is not False:
                    failures.append("vector bottleneck must not use live embedding calls")
            if item.get("area_key") == "demo_generation":
                if policy.get("outputs_truth_status") != "model_generated":
                    failures.append("demo bottleneck must keep outputs model_generated")
                if policy.get("fine_tuning_api_calls_allowed") is not False:
                    failures.append("demo bottleneck must block fine-tuning API calls")
        return Check(
            "Downstream bottleneck queue is API-verifiable",
            not failures,
            "; ".join(failures)
            if failures
            else "API ranks the next operator actions with policy, counts, and machine-verifiable ordering",
            {
                "ordered_area_keys": ordered_area_keys,
                "item_count": queue.get("item_count"),
                "queue_sha256": verification.get("queue_sha256"),
                "top_area_key": verification.get("top_area_key"),
                "sample_actions": [
                    {
                        "area_key": item.get("area_key"),
                        "count": item.get("count"),
                        "action_type": (item.get("action") or {}).get("action_type"),
                        "enabled": (item.get("action") or {}).get("enabled"),
                    }
                    for item in items[:4]
                    if isinstance(item, dict)
                ],
            },
        )

    checks.append(safe_check("Downstream bottleneck queue is API-verifiable", downstream_bottleneck_queue_readiness))

    def downstream_artifact_manifest() -> Check:
        manifest = get_json(
            args.api_base,
            "/downstream-readiness/artifact-manifest",
            {"scope": "family_private", "prompt_sample_limit": 200, "vector_limit": 20},
            timeout=30,
        )
        items = manifest.get("items") if isinstance(manifest.get("items"), list) else []
        by_key = {item.get("artifact_key"): item for item in items if isinstance(item, dict)}
        required_keys = {
            "prompt_pair_audit_markdown",
            "prompt_pair_review_progress_json",
            "prompt_pair_top_blocker_session_plan_yaml",
            "prompt_pair_reference_jsonl",
            "prompt_pair_reference_markdown",
            "dataset_sft_approved_jsonl",
            "dataset_dpo_approved_jsonl",
            "dataset_sft_candidate_dry_run",
            "dataset_dpo_candidate_dry_run",
            "photo_context_pack_readiness_json",
            "photo_context_review_pack_yaml_preview",
            "photo_context_review_session_plan_yaml",
            "photo_context_session_progress_json",
            "photo_context_retrieval_gap_field_worklist_yaml",
            "photo_context_retrieval_gap_payoff_preview_yaml",
            "photo_review_priority_yaml",
            "photo_vector_handoff_jsonl",
            "photo_vector_handoff_manifest",
            "morning_handoff_yaml",
            "dpo_rejected_reason_repair_yaml",
            "source_boundary_training_review_yaml",
            "source_review_pair_generation_preview_json",
            "demo_generation_request_preview_yaml",
        }
        failures = []
        if manifest.get("manifest_type") != "downstream_artifact_manifest":
            failures.append("unexpected downstream artifact manifest type")
        if manifest.get("review_policy") != "inspectable_outputs_no_build_side_effects":
            failures.append("artifact manifest lacks inspectable/no-side-effect policy")
        if manifest.get("does_not_mutate_state") is not True:
            failures.append("artifact manifest must be non-mutating")
        if manifest.get("no_fine_tuning_api_calls_in_mvp") is not True:
            failures.append("artifact manifest must explicitly block fine-tuning API calls")
        if int(manifest.get("artifact_count") or 0) != len(items) or len(items) < len(required_keys):
            failures.append("artifact count does not match required outputs")
        if len(str(manifest.get("content_sha256") or "")) != 64:
            failures.append("artifact manifest lacks stable content hash")
        missing = sorted(required_keys - set(by_key))
        if missing:
            failures.append(f"artifact manifest missing required outputs: {missing}")
        formats = set(manifest.get("formats") or [])
        if not {"jsonl", "markdown", "json", "yaml"}.issubset(formats):
            failures.append("artifact manifest lacks expected output formats")
        for item in items:
            eligibility = item.get("eligibility") if isinstance(item.get("eligibility"), dict) else {}
            if not str(item.get("source_endpoint") or "").startswith("/api/"):
                failures.append(f"{item.get('artifact_key')} lacks API source endpoint")
            if len(str(item.get("content_sha256") or "")) != 64:
                failures.append(f"{item.get('artifact_key')} lacks content hash")
            for flag in ["training", "vector", "gallery", "human_review"]:
                if flag not in eligibility:
                    failures.append(f"{item.get('artifact_key')} lacks eligibility flag `{flag}`")
            if not isinstance(item.get("policy"), dict):
                failures.append(f"{item.get('artifact_key')} lacks policy snapshot")
        if by_key.get("dataset_sft_candidate_dry_run", {}).get("eligibility", {}).get("training") is not False:
            failures.append("candidate SFT dry-run must not be training-eligible")
        if by_key.get("prompt_pair_review_progress_json", {}).get("artifact_family") != "prompt_pair_review":
            failures.append("prompt pair review progress artifact must be in prompt_pair_review family")
        if by_key.get("prompt_pair_review_progress_json", {}).get("format") != "json":
            failures.append("prompt pair review progress artifact must be JSON")
        if by_key.get("prompt_pair_review_progress_json", {}).get("source_endpoint") != "/api/prompt-pairs/review-progress":
            failures.append("prompt pair review progress artifact must source from review-progress endpoint")
        if by_key.get("prompt_pair_review_progress_json", {}).get("eligibility", {}).get("training") is not False:
            failures.append("prompt pair review progress artifact must not be training-eligible")
        progress_policy = by_key.get("prompt_pair_review_progress_json", {}).get("policy", {})
        if progress_policy.get("does_not_mutate_state") is not True:
            failures.append("prompt pair review progress artifact must be non-mutating")
        if progress_policy.get("does_not_promote_to_training_export") is not True:
            failures.append("prompt pair review progress artifact must not promote candidates to training export")
        if progress_policy.get("requires_adam_gold_edit") is not True:
            failures.append("prompt pair review progress artifact must require Adam gold edit")
        if len(str(progress_policy.get("progress_content_sha256") or "")) != 64:
            failures.append("prompt pair review progress artifact lacks domain progress hash")
        if by_key.get("prompt_pair_top_blocker_session_plan_yaml", {}).get("artifact_family") != "prompt_pair_review":
            failures.append("prompt pair blocker session artifact must be in prompt_pair_review family")
        if by_key.get("prompt_pair_top_blocker_session_plan_yaml", {}).get("format") != "yaml":
            failures.append("prompt pair blocker session artifact must be YAML")
        if by_key.get("prompt_pair_top_blocker_session_plan_yaml", {}).get("eligibility", {}).get("training") is not False:
            failures.append("prompt pair blocker session artifact must not be training-eligible")
        session_policy = by_key.get("prompt_pair_top_blocker_session_plan_yaml", {}).get("policy", {})
        if session_policy.get("does_not_mutate_state") is not True:
            failures.append("prompt pair blocker session artifact must be non-mutating")
        if session_policy.get("does_not_promote_to_training_export") is not True:
            failures.append("prompt pair blocker session artifact must not promote candidates to export")
        if session_policy.get("requires_adam_gold_edit") is not True:
            failures.append("prompt pair blocker session artifact must require Adam gold edit")
        session_delta = session_policy.get("projected_task_delta") if isinstance(session_policy.get("projected_task_delta"), dict) else {}
        if session_delta.get("approved_exports_created") != 0 or session_delta.get("raw_sources_mutated") is not False:
            failures.append("prompt pair blocker session artifact delta must preserve no-source-mutation/no-approved-export policy")
        if len(str(session_policy.get("content_sha256") or "")) != 64:
            failures.append("prompt pair blocker session artifact lacks domain plan hash")
        if by_key.get("photo_vector_handoff_jsonl", {}).get("eligibility", {}).get("vector") is not True:
            failures.append("photo vector handoff JSONL must be vector-eligible")
        if by_key.get("photo_context_pack_readiness_json", {}).get("artifact_family") != "photo_context_review":
            failures.append("photo context-pack readiness artifact must be in photo_context_review family")
        if by_key.get("photo_context_pack_readiness_json", {}).get("format") != "json":
            failures.append("photo context-pack readiness artifact must be JSON")
        photo_pack_audit_policy = by_key.get("photo_context_pack_readiness_json", {}).get("policy", {})
        if photo_pack_audit_policy.get("does_not_mutate_state") is not True:
            failures.append("photo context-pack readiness audit must be non-mutating")
        if photo_pack_audit_policy.get("requires_boundary_clearance") is not True:
            failures.append("photo context-pack readiness audit must require boundary clearance")
        if photo_pack_audit_policy.get("uses_reviewed_photo_context") is not True:
            failures.append("photo context-pack readiness audit must use reviewed photo context")
        if photo_pack_audit_policy.get("excludes_system_inference_drafts") is not True:
            failures.append("photo context-pack readiness audit must exclude system inference drafts")
        if int(photo_pack_audit_policy.get("system_inference_leak_count") or 0) != 0:
            failures.append("photo context-pack readiness audit found system inference leakage")
        if len(str(photo_pack_audit_policy.get("audit_content_sha256") or "")) != 64:
            failures.append("photo context-pack readiness audit lacks domain hash")
        if by_key.get("photo_context_review_pack_yaml_preview", {}).get("policy", {}).get("not_memory_claim_worklists") is not True:
            failures.append("photo context pack manifest must preserve not-memory-claim worklists")
        if by_key.get("photo_context_review_session_plan_yaml", {}).get("format") != "yaml":
            failures.append("photo context review session plan artifact must be YAML")
        if by_key.get("photo_context_review_session_plan_yaml", {}).get("policy", {}).get("query_is_context_prioritization_only") is not True:
            failures.append("photo context review session plan must preserve prioritization-only query policy")
        if by_key.get("photo_context_review_session_plan_yaml", {}).get("policy", {}).get("does_not_create_memory_claim") is not True:
            failures.append("photo context review session plan must not create memory claims")
        if by_key.get("photo_context_session_progress_json", {}).get("artifact_family") != "photo_context_review":
            failures.append("photo context progress artifact must be in photo_context_review family")
        if by_key.get("photo_context_session_progress_json", {}).get("format") != "json":
            failures.append("photo context progress artifact must be JSON")
        progress_policy = by_key.get("photo_context_session_progress_json", {}).get("policy", {})
        if progress_policy.get("does_not_mutate_state") is not True:
            failures.append("photo context progress artifact must be non-mutating")
        if progress_policy.get("does_not_create_memory_claim") is not True:
            failures.append("photo context progress artifact must not create memory claims")
        if progress_policy.get("does_not_create_embedding_record") is not True:
            failures.append("photo context progress artifact must not create embedding records")
        if progress_policy.get("requires_adam_context") is not True:
            failures.append("photo context progress artifact must require Adam context")
        if progress_policy.get("completion_signal") != "submit_ready_count_increases_or_retrieval_gap_missing_fields_decrease":
            failures.append("photo context progress artifact lacks completion signal")
        if len(str(progress_policy.get("progress_content_sha256") or "")) != 64:
            failures.append("photo context progress artifact lacks domain progress hash")
        if by_key.get("photo_context_retrieval_gap_field_worklist_yaml", {}).get("format") != "yaml":
            failures.append("retrieval-gap field worklist artifact must be YAML")
        if by_key.get("photo_context_retrieval_gap_field_worklist_yaml", {}).get("policy", {}).get("does_not_create_memory_claim") is not True:
            failures.append("retrieval-gap field worklist must not create memory claims")
        if by_key.get("photo_context_retrieval_gap_field_worklist_yaml", {}).get("policy", {}).get("requires_adam_context") is not True:
            failures.append("retrieval-gap field worklist must require Adam context")
        if by_key.get("photo_context_retrieval_gap_field_worklist_yaml", {}).get("policy", {}).get("has_field_guidance") is not True:
            failures.append("retrieval-gap field worklist must include field guidance")
        if int(by_key.get("photo_context_retrieval_gap_field_worklist_yaml", {}).get("policy", {}).get("field_guidance_count") or 0) < 1:
            failures.append("retrieval-gap field worklist field guidance count must be positive")
        if by_key.get("photo_context_retrieval_gap_payoff_preview_yaml", {}).get("format") != "yaml":
            failures.append("retrieval-gap payoff preview artifact must be YAML")
        if by_key.get("photo_context_retrieval_gap_payoff_preview_yaml", {}).get("policy", {}).get("does_not_create_memory_claim") is not True:
            failures.append("retrieval-gap payoff preview must not create memory claims")
        if by_key.get("photo_context_retrieval_gap_payoff_preview_yaml", {}).get("policy", {}).get("uses_placeholders_for_missing_adam_context") is not True:
            failures.append("retrieval-gap payoff preview must preserve Adam-context placeholders")
        if by_key.get("photo_review_priority_yaml", {}).get("format") != "yaml":
            failures.append("photo review priority artifact must be YAML")
        priority_policy = by_key.get("photo_review_priority_yaml", {}).get("policy", {})
        if priority_policy.get("throughput_policy") != "rank_by_fastest_review_path_then_missing_adam_fields_then_downstream_payoff":
            failures.append("photo review priority artifact lacks throughput policy")
        if priority_policy.get("does_not_create_memory_claim") is not True:
            failures.append("photo review priority artifact must not create memory claims")
        if priority_policy.get("no_live_embedding_call") is not True:
            failures.append("photo review priority artifact must not call embeddings")
        if priority_policy.get("completion_signal") != "open_top_photo_task_and_reduce_missing_adam_fields_or_submit_ready_count_increases":
            failures.append("photo review priority artifact lacks completion signal")
        if len(str(priority_policy.get("priority_content_sha256") or "")) != 64:
            failures.append("photo review priority artifact lacks domain hash")
        if by_key.get("morning_handoff_yaml", {}).get("artifact_family") != "operator_handoff":
            failures.append("morning handoff YAML artifact must be in operator_handoff family")
        if by_key.get("morning_handoff_yaml", {}).get("format") != "yaml":
            failures.append("morning handoff artifact must be YAML")
        if by_key.get("morning_handoff_yaml", {}).get("policy", {}).get("operator_packet") is not True:
            failures.append("morning handoff artifact lacks operator packet policy")
        if by_key.get("dpo_rejected_reason_repair_yaml", {}).get("artifact_family") != "prompt_pair_repair":
            failures.append("DPO rejected reason repair artifact must be in prompt_pair_repair family")
        if by_key.get("dpo_rejected_reason_repair_yaml", {}).get("policy", {}).get("blocker") != "dpo_rejected_reason_empty":
            failures.append("DPO repair artifact must target dpo_rejected_reason_empty")
        if by_key.get("source_boundary_training_review_yaml", {}).get("artifact_family") != "prompt_pair_repair":
            failures.append("source-boundary review artifact must be in prompt_pair_repair family")
        if by_key.get("source_boundary_training_review_yaml", {}).get("format") != "yaml":
            failures.append("source-boundary review artifact must be YAML")
        source_boundary_policy = by_key.get("source_boundary_training_review_yaml", {}).get("policy", {})
        if source_boundary_policy.get("blocker") != "source_boundary_blocks_training":
            failures.append("source-boundary review artifact must target source_boundary_blocks_training")
        if source_boundary_policy.get("does_not_mutate_source") is not True:
            failures.append("source-boundary review artifact must not mutate source asset boundaries")
        if source_boundary_policy.get("does_not_promote_to_training_export") is not True:
            failures.append("source-boundary review artifact must not promote training export")
        if source_boundary_policy.get("requires_adam_boundary_review") is not True:
            failures.append("source-boundary review artifact must require Adam boundary review")
        if by_key.get("source_review_pair_generation_preview_json", {}).get("artifact_family") != "source_review_preview":
            failures.append("Source Review pair generation preview artifact must be in source_review_preview family")
        if by_key.get("source_review_pair_generation_preview_json", {}).get("format") != "json":
            failures.append("Source Review pair generation preview artifact must be JSON")
        if by_key.get("source_review_pair_generation_preview_json", {}).get("policy", {}).get("does_not_mutate_state") is not True:
            failures.append("Source Review pair generation preview must be non-mutating")
        if by_key.get("source_review_pair_generation_preview_json", {}).get("policy", {}).get("no_live_model_call") is not True:
            failures.append("Source Review pair generation preview must avoid live model calls")
        if by_key.get("demo_generation_request_preview_yaml", {}).get("artifact_family") != "model_generation_preview":
            failures.append("demo generation request preview artifact must be in model_generation_preview family")
        if by_key.get("demo_generation_request_preview_yaml", {}).get("format") != "yaml":
            failures.append("demo generation request preview artifact must be YAML")
        demo_request_policy = by_key.get("demo_generation_request_preview_yaml", {}).get("policy", {})
        if demo_request_policy.get("no_live_model_call") is not True:
            failures.append("demo generation request preview must not call live models")
        if demo_request_policy.get("no_generation_created") is not True:
            failures.append("demo generation request preview must not create generations")
        if demo_request_policy.get("does_not_promote_to_training_export") is not True:
            failures.append("demo generation request preview must not promote training export")
        if demo_request_policy.get("model_name") != args.required_text_model:
            failures.append("demo generation request preview lost required model")
        if demo_request_policy.get("reasoning_effort") != args.required_text_reasoning:
            failures.append("demo generation request preview lost required reasoning effort")
        if demo_request_policy.get("store") is not False:
            failures.append("demo generation request preview must preserve store=false")
        return Check(
            "Downstream artifact manifest lists inspectable outputs",
            not failures,
            "; ".join(failures)
            if failures
            else "artifact manifest lists downstream outputs with hashes, formats, endpoints, and eligibility policy",
            {
                "artifact_count": manifest.get("artifact_count"),
                "formats": manifest.get("formats"),
                "artifact_families": manifest.get("artifact_families"),
                "content_sha256": manifest.get("content_sha256"),
                "sample_artifacts": list(by_key)[:6],
            },
        )

    checks.append(safe_check("Downstream artifact manifest lists inspectable outputs", downstream_artifact_manifest))

    def downstream_artifact_hash_audit() -> Check:
        audit = get_json(
            args.api_base,
            "/downstream-readiness/artifact-audit",
            {"scope": "family_private", "prompt_sample_limit": 200, "vector_limit": 20},
            timeout=30,
        )
        checks_payload = audit.get("checks") if isinstance(audit.get("checks"), list) else []
        failures = []
        if audit.get("audit_type") != "downstream_artifact_hash_audit":
            failures.append("unexpected downstream artifact audit type")
        if audit.get("review_policy") != "recompute_declared_manifest_hashes_without_export_build":
            failures.append("artifact audit lacks recompute/no-build policy")
        if audit.get("does_not_mutate_state") is not True:
            failures.append("artifact audit must be non-mutating")
        if audit.get("all_hashes_match") is not True or int(audit.get("mismatch_count") or 0) != 0:
            failures.append("artifact audit reports hash mismatches")
        if int(audit.get("checked_count") or 0) != len(checks_payload) or len(checks_payload) < 10:
            failures.append("artifact audit did not check every required output")
        if len(str(audit.get("manifest_content_sha256") or "")) != 64:
            failures.append("artifact audit lacks manifest hash")
        if len(str(audit.get("content_sha256") or "")) != 64:
            failures.append("artifact audit lacks stable audit hash")
        for check in checks_payload:
            if check.get("hash_matches") is not True:
                failures.append(f"{check.get('artifact_key')} hash mismatch")
            if check.get("declared_sha256") != check.get("recomputed_sha256"):
                failures.append(f"{check.get('artifact_key')} declared/recomputed hash differs")
            if not str(check.get("source_endpoint") or "").startswith("/api/"):
                failures.append(f"{check.get('artifact_key')} lacks API source endpoint")
        by_key = {check.get("artifact_key"): check for check in checks_payload if isinstance(check, dict)}
        if by_key.get("morning_handoff_yaml", {}).get("format") != "yaml":
            failures.append("artifact audit lacks morning handoff YAML check")
        if by_key.get("morning_handoff_yaml", {}).get("hash_matches") is not True:
            failures.append("morning handoff YAML hash mismatch")
        if by_key.get("dpo_rejected_reason_repair_yaml", {}).get("format") != "yaml":
            failures.append("artifact audit lacks DPO rejected reason repair YAML check")
        if by_key.get("dpo_rejected_reason_repair_yaml", {}).get("hash_matches") is not True:
            failures.append("DPO rejected reason repair YAML hash mismatch")
        if by_key.get("source_boundary_training_review_yaml", {}).get("format") != "yaml":
            failures.append("artifact audit lacks source-boundary training review YAML check")
        if by_key.get("source_boundary_training_review_yaml", {}).get("hash_matches") is not True:
            failures.append("source-boundary training review YAML hash mismatch")
        if by_key.get("source_boundary_training_review_yaml", {}).get("policy", {}).get("does_not_mutate_source") is not True:
            failures.append("source-boundary training review YAML must preserve no-source-mutation policy")
        if by_key.get("source_review_pair_generation_preview_json", {}).get("format") != "json":
            failures.append("artifact audit lacks Source Review pair generation preview JSON check")
        if by_key.get("source_review_pair_generation_preview_json", {}).get("hash_matches") is not True:
            failures.append("Source Review pair generation preview JSON hash mismatch")
        if by_key.get("demo_generation_request_preview_yaml", {}).get("format") != "yaml":
            failures.append("artifact audit lacks demo generation request preview YAML check")
        if by_key.get("demo_generation_request_preview_yaml", {}).get("hash_matches") is not True:
            failures.append("demo generation request preview YAML hash mismatch")
        if by_key.get("demo_generation_request_preview_yaml", {}).get("policy", {}).get("no_live_model_call") is not True:
            failures.append("demo generation request preview YAML must preserve no-live-model policy")
        if by_key.get("demo_generation_request_preview_yaml", {}).get("policy", {}).get("no_generation_created") is not True:
            failures.append("demo generation request preview YAML must be non-generating")
        if by_key.get("prompt_pair_review_progress_json", {}).get("format") != "json":
            failures.append("artifact audit lacks prompt pair review progress JSON check")
        if by_key.get("prompt_pair_review_progress_json", {}).get("hash_matches") is not True:
            failures.append("prompt pair review progress JSON hash mismatch")
        if by_key.get("prompt_pair_top_blocker_session_plan_yaml", {}).get("format") != "yaml":
            failures.append("artifact audit lacks prompt pair blocker session YAML check")
        if by_key.get("prompt_pair_top_blocker_session_plan_yaml", {}).get("hash_matches") is not True:
            failures.append("prompt pair blocker session plan YAML hash mismatch")
        if by_key.get("photo_context_pack_readiness_json", {}).get("format") != "json":
            failures.append("artifact audit lacks photo context-pack readiness JSON check")
        if by_key.get("photo_context_pack_readiness_json", {}).get("hash_matches") is not True:
            failures.append("photo context-pack readiness JSON hash mismatch")
        if by_key.get("photo_context_review_session_plan_yaml", {}).get("format") != "yaml":
            failures.append("artifact audit lacks photo context review session YAML check")
        if by_key.get("photo_context_review_session_plan_yaml", {}).get("hash_matches") is not True:
            failures.append("photo context review session YAML hash mismatch")
        if by_key.get("photo_context_session_progress_json", {}).get("format") != "json":
            failures.append("artifact audit lacks photo context session progress JSON check")
        if by_key.get("photo_context_session_progress_json", {}).get("hash_matches") is not True:
            failures.append("photo context session progress JSON hash mismatch")
        if by_key.get("photo_context_retrieval_gap_field_worklist_yaml", {}).get("format") != "yaml":
            failures.append("artifact audit lacks retrieval-gap field worklist YAML check")
        if by_key.get("photo_context_retrieval_gap_field_worklist_yaml", {}).get("hash_matches") is not True:
            failures.append("retrieval-gap field worklist YAML hash mismatch")
        if by_key.get("photo_context_retrieval_gap_payoff_preview_yaml", {}).get("format") != "yaml":
            failures.append("artifact audit lacks retrieval-gap payoff preview YAML check")
        if by_key.get("photo_context_retrieval_gap_payoff_preview_yaml", {}).get("hash_matches") is not True:
            failures.append("retrieval-gap payoff preview YAML hash mismatch")
        if by_key.get("photo_review_priority_yaml", {}).get("format") != "yaml":
            failures.append("artifact audit lacks photo review priority YAML check")
        if by_key.get("photo_review_priority_yaml", {}).get("hash_matches") is not True:
            failures.append("photo review priority YAML hash mismatch")
        if (
            by_key.get("photo_review_priority_yaml", {})
            .get("policy", {})
            .get("throughput_policy")
            != "rank_by_fastest_review_path_then_missing_adam_fields_then_downstream_payoff"
        ):
            failures.append("photo review priority YAML must preserve throughput policy")
        return Check(
            "Downstream artifact hash audit verifies manifest outputs",
            not failures,
            "; ".join(failures)
            if failures
            else "artifact audit recomputes declared artifact hashes and finds no mismatches",
            {
                "checked_count": audit.get("checked_count"),
                "mismatch_count": audit.get("mismatch_count"),
                "manifest_content_sha256": audit.get("manifest_content_sha256"),
                "content_sha256": audit.get("content_sha256"),
                "sample_artifacts": [check.get("artifact_key") for check in checks_payload[:6]],
            },
        )

    checks.append(safe_check("Downstream artifact hash audit verifies manifest outputs", downstream_artifact_hash_audit))

    def photo_context_pack_readiness_audit() -> Check:
        audit = get_json(
            args.api_base,
            "/context-packs/photo-context-readiness-audit",
            {"scope": "family_private", "limit": 50},
            timeout=30,
        )
        contract = get_json(args.api_base, "/runtime-contract")
        failures = []
        if audit.get("audit_type") != "photo_context_pack_readiness_audit":
            failures.append("unexpected photo context-pack audit type")
        if audit.get("review_policy") != "read_only_context_pack_fact_projection":
            failures.append("photo context-pack audit lacks read-only projection policy")
        if audit.get("does_not_mutate_state") is not True:
            failures.append("photo context-pack audit must be non-mutating")
        if audit.get("requires_boundary_clearance") is not True:
            failures.append("photo context-pack audit must require boundary clearance")
        if audit.get("uses_reviewed_photo_context") is not True:
            failures.append("photo context-pack audit must use reviewed photo context")
        if audit.get("excludes_system_inference_drafts") is not True:
            failures.append("photo context-pack audit must exclude system inference drafts")
        if int(audit.get("system_inference_leak_count") or 0) != 0:
            failures.append("photo context-pack audit found system-inference leakage")
        if len(str(audit.get("content_sha256") or "")) != 64:
            failures.append("photo context-pack audit lacks stable hash")
        if audit.get("completion_signal") != "reviewed_photo_context_assets_have_non_filename_context_or_are_boundary_blocked":
            failures.append("photo context-pack audit lacks completion signal")
        held_for_adam_review_count = int(audit.get("held_for_adam_review_count") or 0)
        next_review_actions = audit.get("next_review_actions") or []
        if held_for_adam_review_count > 0 and not next_review_actions:
            failures.append("held machine photo-memory drafts must surface next review actions")
        if held_for_adam_review_count > 0 and audit.get("readiness_status") not in {
            "needs_adam_review",
            "partially_ready_needs_adam_review",
        }:
            failures.append("photo context-pack audit readiness status must reflect held Adam review work")
        if next_review_actions:
            first_action = next_review_actions[0]
            if first_action.get("action_type") not in {
                "open_photo_memory_review_task",
                "create_photo_memory_review_task",
            }:
                failures.append("photo context-pack next review action lacks actionable photo-memory task type")
            if not first_action.get("source_photo_id") or not first_action.get("metadata_profile_id"):
                failures.append("photo context-pack next review action lacks source photo or profile id")
        contract_fields = (
            (contract.get("required_response_fields") or {}).get("/api/context-packs/photo-context-readiness-audit")
            if isinstance(contract.get("required_response_fields"), dict)
            else []
        )
        for field in [
            "readiness_status",
            "uses_reviewed_photo_context",
            "excludes_system_inference_drafts",
            "machine_draft_profile_count",
            "held_for_adam_review_count",
            "next_review_action_count",
            "next_review_actions",
            "system_inference_leak_count",
            "content_sha256",
        ]:
            if field not in contract_fields:
                failures.append(f"runtime contract lacks photo context-pack audit field {field}")
        return Check(
            "Photo context-pack readiness audit is machine-checkable",
            not failures,
            "; ".join(failures)
            if failures
            else "reviewed photo context-pack audit exposes boundary, truth-status, and leak checks",
            {
                "candidate_photo_asset_count": audit.get("candidate_photo_asset_count"),
                "ready_context_pack_asset_count": audit.get("ready_context_pack_asset_count"),
                "blocked_context_pack_asset_count": audit.get("blocked_context_pack_asset_count"),
                "readiness_status": audit.get("readiness_status"),
                "held_for_adam_review_count": audit.get("held_for_adam_review_count"),
                "next_review_action_count": audit.get("next_review_action_count"),
                "filename_only_fallback_count": audit.get("filename_only_fallback_count"),
                "system_inference_leak_count": audit.get("system_inference_leak_count"),
                "content_sha256": audit.get("content_sha256"),
            },
        )

    checks.append(safe_check("Photo context-pack readiness audit is machine-checkable", photo_context_pack_readiness_audit))

    def morning_handoff_status() -> Check:
        handoff = get_json(
            args.api_base,
            "/downstream-readiness/morning-handoff",
            {
                "scope": "family_private",
                "prompt_sample_limit": 200,
                "vector_limit": 20,
                "bottleneck_limit": 4,
                "retrieval_gap_query": args.honest_gap_query,
            },
            timeout=30,
        )
        summaries = handoff.get("readiness_summary") if isinstance(handoff.get("readiness_summary"), list) else []
        summary_by_key = {item.get("area_key"): item for item in summaries if isinstance(item, dict)}
        bottlenecks = handoff.get("top_bottlenecks") if isinstance(handoff.get("top_bottlenecks"), list) else []
        checklist = handoff.get("operator_checklist") if isinstance(handoff.get("operator_checklist"), list) else []
        ordered_keys = handoff.get("ordered_bottleneck_area_keys") if isinstance(handoff.get("ordered_bottleneck_area_keys"), list) else []
        artifact_summary = handoff.get("artifact_summary") if isinstance(handoff.get("artifact_summary"), dict) else {}
        model_status = handoff.get("model_generation_status") if isinstance(handoff.get("model_generation_status"), dict) else {}
        retrieval_gap_work = handoff.get("retrieval_gap_work") if isinstance(handoff.get("retrieval_gap_work"), dict) else {}
        markdown = str(handoff.get("report_markdown") or "")
        failures = []
        if handoff.get("report_type") != "morning_handoff":
            failures.append("unexpected morning handoff type")
        if handoff.get("review_policy") != "read_only_status_no_source_mutation":
            failures.append("handoff lacks read-only/source-mutation policy")
        if handoff.get("does_not_mutate_state") is not True:
            failures.append("handoff must be non-mutating")
        if handoff.get("no_live_model_call") is not True:
            failures.append("handoff must not call live models")
        if handoff.get("no_fine_tuning_api_calls_in_mvp") is not True:
            failures.append("handoff must preserve no-fine-tuning MVP rule")
        if handoff.get("primary_bottleneck_area_key") != (ordered_keys[0] if ordered_keys else "none"):
            failures.append("primary bottleneck does not match ordered bottleneck keys")
        if ordered_keys[:2] != ["prompt_pairs", "photo_context"]:
            failures.append("handoff should surface prompt pairs and photo context first")
        for required in ["prompt_pairs", "photo_context", "vector_handoff", "demo_generation", "artifacts"]:
            if required not in summary_by_key:
                failures.append(f"handoff readiness summary lacks {required}")
        if int(artifact_summary.get("artifact_count") or 0) < 10:
            failures.append("handoff artifact summary lacks required artifacts")
        if artifact_summary.get("all_hashes_match") is not True or int(artifact_summary.get("mismatch_count") or 0) != 0:
            failures.append("handoff artifact summary reports hash mismatches")
        if len(str(artifact_summary.get("manifest_content_sha256") or "")) != 64:
            failures.append("handoff artifact summary lacks manifest hash")
        if len(str(handoff.get("content_sha256") or "")) != 64:
            failures.append("handoff lacks stable content hash")
        if model_status.get("outputs_truth_status") != "model_generated":
            failures.append("handoff model status must keep demo outputs model_generated")
        if model_status.get("fine_tuning_api_calls_allowed") is not False:
            failures.append("handoff must block fine-tuning calls")
        if len(bottlenecks) < 3:
            failures.append("handoff lacks actionable bottleneck list")
        if len(checklist) != len(bottlenecks):
            failures.append("operator checklist does not mirror bottleneck count")
        if checklist:
            first = checklist[0] if isinstance(checklist[0], dict) else {}
            if first.get("area_key") != "prompt_pairs" or first.get("status") != "actionable":
                failures.append("first operator checklist item should be actionable prompt-pair work")
            if first.get("completion_signal") != "candidate_count_decreases_or_blocker_worklist_changes":
                failures.append("prompt-pair checklist lacks candidate-count completion signal")
            if "Adam gold review" not in str(first.get("safety_boundary") or ""):
                failures.append("prompt-pair checklist lacks Adam gold-review boundary")
        checklist_by_key = {item.get("area_key"): item for item in checklist if isinstance(item, dict)}
        photo_checklist = checklist_by_key.get("photo_context") or {}
        if "no_claim" not in str(photo_checklist.get("safety_boundary") or ""):
            failures.append("photo-context checklist lacks no_claim safety boundary")
        if retrieval_gap_work.get("slice_type") != "retrieval_gap_review_slice":
            failures.append("handoff lacks retrieval gap review slice")
        if retrieval_gap_work.get("query") != args.honest_gap_query:
            failures.append("handoff retrieval gap query does not match honest-gap query")
        if retrieval_gap_work.get("gap_open") is not True:
            failures.append("handoff retrieval gap work should be open for honest-gap query")
        if retrieval_gap_work.get("truth_status") != "no_claim":
            failures.append("handoff retrieval gap work must remain no_claim")
        if retrieval_gap_work.get("review_policy") != "retrieval_gap_no_claim_until_adam_context":
            failures.append("handoff retrieval gap work lacks no-claim review policy")
        if int(retrieval_gap_work.get("candidate_count") or 0) <= 0:
            failures.append("handoff retrieval gap work lacks candidate count")
        if len(str(retrieval_gap_work.get("content_sha256") or "")) != 64:
            failures.append("handoff retrieval gap work lacks hash")
        gap_items = retrieval_gap_work.get("items") if isinstance(retrieval_gap_work.get("items"), list) else []
        if not gap_items:
            failures.append("handoff retrieval gap work lacks preview items")
        if photo_checklist.get("retrieval_gap_query") != args.honest_gap_query:
            failures.append("photo-context checklist lacks retrieval gap query")
        if int(photo_checklist.get("retrieval_gap_candidate_count") or 0) != int(retrieval_gap_work.get("candidate_count") or 0):
            failures.append("photo-context checklist retrieval candidate count mismatches handoff slice")
        if photo_checklist.get("retrieval_gap_slice_hash") != retrieval_gap_work.get("content_sha256"):
            failures.append("photo-context checklist retrieval slice hash mismatches handoff slice")
        if not photo_checklist.get("retrieval_gap_preview_titles"):
            failures.append("photo-context checklist lacks retrieval gap preview titles")
        if (checklist_by_key.get("demo_generation") or {}).get("status") != "blocked":
            failures.append("demo-generation checklist should remain blocked while credentials are missing")
        if "No fine-tuning API calls" not in str((checklist_by_key.get("demo_generation") or {}).get("safety_boundary") or ""):
            failures.append("demo-generation checklist lacks no-fine-tuning safety boundary")
        for phrase in [
            "# Morning Handoff",
            "No fine-tuning API calls in MVP.",
            "model_generated",
            "no_claim",
            "## Retrieval Gap Work",
            args.honest_gap_query,
        ]:
            if phrase not in markdown:
                failures.append(f"handoff markdown lacks `{phrase}`")
        return Check(
            "Morning handoff summarizes current loop state",
            not failures,
            "; ".join(failures)
            if failures
            else "handoff names top bottlenecks, artifact hash status, and safety boundaries",
            {
                "primary_bottleneck_area_key": handoff.get("primary_bottleneck_area_key"),
                "ordered_bottleneck_area_keys": ordered_keys,
                "artifact_count": artifact_summary.get("artifact_count"),
                "artifact_hashes_match": artifact_summary.get("all_hashes_match"),
                "checklist_count": len(checklist),
                "retrieval_gap_query": retrieval_gap_work.get("query"),
                "retrieval_gap_candidate_count": retrieval_gap_work.get("candidate_count"),
                "retrieval_gap_hash": retrieval_gap_work.get("content_sha256"),
                "content_sha256": handoff.get("content_sha256"),
                "readiness_keys": [item.get("area_key") for item in summaries[:5] if isinstance(item, dict)],
            },
        )

    checks.append(safe_check("Morning handoff summarizes current loop state", morning_handoff_status))

    def prompt_pair_audit() -> Check:
        audit = get_json(args.api_base, "/prompt-pairs/audit", {"sample_limit": args.min_audit_samples})
        voice_modes = audit.get("voice_mode_counts") or {}
        failures: list[str] = []
        if audit.get("total_pairs", 0) < args.min_prompt_pairs:
            failures.append(f"needs at least {args.min_prompt_pairs} prompt pairs")
        if audit.get("inspectable_pair_count") != audit.get("total_pairs"):
            failures.append("not every prompt pair is inspectable")
        if audit.get("invalid_pair_count") != 0:
            failures.append("invalid prompt pairs remain")
        preflight_gate_counts = (
            audit.get("preflight_gate_counts") if isinstance(audit.get("preflight_gate_counts"), dict) else {}
        )
        preflight_total = sum(
            int(count)
            for count in preflight_gate_counts.values()
            if isinstance(count, int) or (isinstance(count, str) and count.isdigit())
        )
        if preflight_total != audit.get("total_pairs"):
            failures.append("preflight gate count does not cover every prompt pair")
        if audit.get("preflight_mismatch_count") != 0:
            failures.append("backend prompt-pair preflight disagrees with persisted UI export gate preview")
        if audit.get("sample_count", 0) < args.min_audit_samples:
            failures.append(f"needs at least {args.min_audit_samples} deterministic samples")
        if len(voice_modes) < args.min_voice_modes:
            failures.append(f"needs at least {args.min_voice_modes} voice modes, found {len(voice_modes)}")
        return Check(
            "Prompt-pair audit has broad inspectable proof set",
            not failures,
            "; ".join(failures) if failures else "prompt-pair audit meets live milestone threshold",
            {
                "total_pairs": audit.get("total_pairs"),
                "inspectable_pair_count": audit.get("inspectable_pair_count"),
                "invalid_pair_count": audit.get("invalid_pair_count"),
                "sample_count": audit.get("sample_count"),
                "voice_mode_counts": voice_modes,
                "quality_counts": audit.get("quality_counts"),
                "preflight_gate_counts": preflight_gate_counts,
                "preflight_mismatch_count": audit.get("preflight_mismatch_count"),
                "preflight_mismatches": audit.get("preflight_mismatches"),
            },
        )

    checks.append(safe_check("Prompt-pair audit has broad inspectable proof set", prompt_pair_audit))

    def held_prompt_pair_review_pack() -> Check:
        audit = get_json(args.api_base, "/prompt-pairs/audit", {"sample_limit": 5})
        pack = get_json(args.api_base, "/prompt-pairs/held-candidates", {"limit": 30})
        candidates = pack.get("candidates") if isinstance(pack.get("candidates"), list) else []
        worklists = pack.get("worklists") if isinstance(pack.get("worklists"), list) else []
        candidate_count = int((audit.get("preflight_gate_counts") or {}).get("candidate") or 0)
        failures = []
        if pack.get("pack_type") != "prompt_pair_candidate_review_pack":
            failures.append("unexpected held prompt-pair pack type")
        if pack.get("review_policy") != "candidate_review_only_no_training_export":
            failures.append("held prompt-pair pack lacks candidate-only policy")
        if pack.get("does_not_promote_to_training_export") is not True:
            failures.append("held prompt-pair pack must not promote candidates to training export")
        if pack.get("requires_adam_gold_edit") is not True:
            failures.append("held prompt-pair pack must require Adam gold edit")
        if int(pack.get("total_candidate_count") or 0) != candidate_count:
            failures.append("held prompt-pair count does not match audit candidate count")
        if candidate_count > 0 and not candidates:
            failures.append("held prompt-pair pack lacks candidate records")
        if len(str(pack.get("content_sha256") or "")) != 64:
            failures.append("held prompt-pair pack lacks stable content hash")
        if not isinstance(pack.get("blocker_counts"), dict):
            failures.append("held prompt-pair pack lacks blocker counts")
        if int(pack.get("worklist_count") or 0) != len(worklists):
            failures.append("held prompt-pair worklist count does not match worklist records")
        if candidate_count > 0 and not worklists:
            failures.append("held prompt-pair pack lacks blocker worklists")
        for candidate in candidates[:10]:
            action = candidate.get("action") if isinstance(candidate.get("action"), dict) else {}
            if candidate.get("export_status") != "candidate":
                failures.append(f"{candidate.get('task_human_id')} is not marked candidate")
            if candidate.get("dataset_outcome") != "Candidate dry-run only":
                failures.append(f"{candidate.get('task_human_id')} lacks candidate dry-run outcome")
            if not candidate.get("prompt") or not candidate.get("response_preview"):
                failures.append(f"{candidate.get('task_human_id')} lacks prompt/response preview")
            if action.get("action_type") != "open_held_prompt_pair_candidate" or not action.get("task_id"):
                failures.append(f"{candidate.get('task_human_id')} lacks open-held-pair action")
        for worklist in worklists[:10]:
            action = worklist.get("recommended_action") if isinstance(worklist.get("recommended_action"), dict) else {}
            previews = worklist.get("candidate_previews") if isinstance(worklist.get("candidate_previews"), list) else []
            if not str(worklist.get("worklist_key") or "").startswith("prompt_pair_blocker:"):
                failures.append("held prompt-pair worklist lacks stable blocker key")
            if len(str(worklist.get("review_sequence_key") or "")) != 64:
                failures.append(f"{worklist.get('worklist_key')} lacks stable sequence hash")
            if int(worklist.get("candidate_count") or 0) <= 0:
                failures.append(f"{worklist.get('worklist_key')} lacks candidates")
            if not previews:
                failures.append(f"{worklist.get('worklist_key')} lacks candidate previews")
            if action.get("action_type") != "open_prompt_pair_worklist" or not action.get("task_id"):
                failures.append(f"{worklist.get('worklist_key')} lacks worklist action")
        return Check(
            "Held prompt-pair review pack is actionable",
            not failures,
            "; ".join(failures)
            if failures
            else "held prompt-pair candidates expose blockers, worklists, previews, and open-ticket actions without export promotion",
            {
                "total_candidate_count": pack.get("total_candidate_count"),
                "reported_candidate_count": pack.get("reported_candidate_count"),
                "blocker_counts": pack.get("blocker_counts"),
                "worklist_count": pack.get("worklist_count"),
                "sample_worklists": [worklist.get("worklist_key") for worklist in worklists[:5]],
                "content_sha256": pack.get("content_sha256"),
                "sample_tasks": [candidate.get("task_human_id") for candidate in candidates[:5]],
            },
        )

    checks.append(safe_check("Held prompt-pair review pack is actionable", held_prompt_pair_review_pack))

    def prompt_pair_review_progress() -> Check:
        audit = get_json(args.api_base, "/prompt-pairs/audit", {"sample_limit": 5})
        contract = get_json(args.api_base, "/runtime-contract")
        required_fields = (
            (contract.get("required_response_fields") or {}).get("/api/prompt-pairs/review-progress")
            if isinstance(contract.get("required_response_fields"), dict)
            else []
        )
        tasks_before = get_json(args.api_base, "/tasks")
        progress = get_json(args.api_base, "/prompt-pairs/review-progress", timeout=30)
        tasks_after = get_json(args.api_base, "/tasks")
        gate_counts = audit.get("preflight_gate_counts") if isinstance(audit.get("preflight_gate_counts"), dict) else {}
        blocker_counts = audit.get("preflight_blocker_counts") if isinstance(audit.get("preflight_blocker_counts"), dict) else {}
        failures = []
        missing_fields = [field for field in required_fields if field not in progress]
        if missing_fields:
            failures.append(f"review progress missing runtime-contract fields: {missing_fields}")
        if progress.get("progress_type") != "prompt_pair_review_progress":
            failures.append("unexpected prompt-pair progress type")
        if progress.get("review_policy") != "non_mutating_prompt_pair_progress_projection":
            failures.append("review progress lacks projection policy")
        if progress.get("does_not_mutate_state") is not True:
            failures.append("review progress must be non-mutating")
        if progress.get("does_not_promote_to_training_export") is not True:
            failures.append("review progress must not promote candidates")
        if progress.get("requires_adam_gold_edit") is not True:
            failures.append("review progress must preserve Adam gold-review requirement")
        if int(progress.get("candidate_count") or 0) != int(gate_counts.get("candidate") or 0):
            failures.append("review progress candidate count does not match audit")
        if int(progress.get("approved_count") or 0) != int(gate_counts.get("approved") or 0):
            failures.append("review progress approved count does not match audit")
        if int(progress.get("total_inspectable_count") or 0) != int(audit.get("inspectable_pair_count") or 0):
            failures.append("review progress inspectable count does not match audit")
        if progress.get("blocker_counts") != blocker_counts:
            failures.append("review progress blocker counts do not match audit")
        if int(gate_counts.get("candidate") or 0) > 0 and not progress.get("top_blocker"):
            failures.append("review progress lacks top blocker while candidates remain")
        if progress.get("completion_signal") != "candidate_count_decreases_or_blocker_worklist_changes":
            failures.append("review progress has wrong completion signal")
        if len(str(progress.get("content_sha256") or "")) != 64:
            failures.append("review progress lacks stable content hash")
        before_ids = {task.get("id") for task in tasks_before if isinstance(task, dict)}
        after_ids = {task.get("id") for task in tasks_after if isinstance(task, dict)}
        if before_ids != after_ids:
            failures.append("review progress mutated the task set")
        return Check(
            "Prompt-pair review progress is machine-checkable",
            not failures,
            "; ".join(failures)
            if failures
            else "review-progress endpoint mirrors audit counts and preserves candidate-only policy",
            {
                "candidate_count": progress.get("candidate_count"),
                "approved_count": progress.get("approved_count"),
                "top_blocker": progress.get("top_blocker"),
                "top_blocker_count": progress.get("top_blocker_count"),
                "completion_signal": progress.get("completion_signal"),
                "content_sha256": progress.get("content_sha256"),
            },
        )

    checks.append(safe_check("Prompt-pair review progress is machine-checkable", prompt_pair_review_progress))

    def prompt_pair_top_blocker_slice() -> Check:
        blocker_slice = get_json(args.api_base, "/prompt-pairs/top-blocker-slice", {"limit": 5}, timeout=30)
        items = blocker_slice.get("items") if isinstance(blocker_slice.get("items"), list) else []
        failures = []
        if blocker_slice.get("slice_type") != "prompt_pair_top_blocker_slice":
            failures.append("unexpected prompt-pair top blocker slice type")
        if blocker_slice.get("review_policy") != "top_backend_blocker_review_slice_no_export_promotion":
            failures.append("top blocker slice lacks review-only policy")
        if blocker_slice.get("does_not_promote_to_training_export") is not True:
            failures.append("top blocker slice must not promote to training export")
        if blocker_slice.get("requires_adam_gold_edit") is not True:
            failures.append("top blocker slice must require Adam gold edit")
        if int(blocker_slice.get("candidate_count") or 0) < len(items):
            failures.append("top blocker candidate count is smaller than reported items")
        if int(blocker_slice.get("reported_candidate_count") or 0) != len(items):
            failures.append("top blocker reported count does not match items")
        if blocker_slice.get("completion_signal") != "candidate_count_decreases_or_blocker_worklist_changes":
            failures.append("top blocker slice lacks completion signal")
        if len(str(blocker_slice.get("content_sha256") or "")) != 64:
            failures.append("top blocker slice lacks stable content hash")
        if not any("Adam gold review" in str(boundary) for boundary in (blocker_slice.get("safety_boundaries") or [])):
            failures.append("top blocker slice lacks Adam-review safety boundary")
        if items:
            first = items[0]
            preflight = first.get("backend_preflight") if isinstance(first.get("backend_preflight"), dict) else {}
            if not first.get("task_id") or not first.get("task_human_id"):
                failures.append("top blocker item lacks task identity")
            if not first.get("prompt") or not first.get("response_preview"):
                failures.append("top blocker item lacks prompt/response preview")
            if not first.get("export_preview_yaml"):
                failures.append("top blocker item lacks YAML export preview")
            if preflight.get("export_status") != "candidate":
                failures.append("top blocker item is not held as candidate")
            if blocker_slice.get("blocker") not in (preflight.get("blockers") or []):
                failures.append("top blocker item preflight does not include slice blocker")
            action = first.get("action") if isinstance(first.get("action"), dict) else {}
            if action.get("action_type") != "open_held_prompt_pair_candidate" or not action.get("task_id"):
                failures.append("top blocker item lacks open-held-pair action")
        else:
            failures.append("top blocker slice has no items while live candidate queue should have held pairs")
        return Check(
            "Prompt-pair top blocker slice is inspectable",
            not failures,
            "; ".join(failures)
            if failures
            else "top prompt-pair blocker exposes task previews, YAML, preflight blockers, and completion criteria",
            {
                "blocker": blocker_slice.get("blocker"),
                "candidate_count": blocker_slice.get("candidate_count"),
                "reported_candidate_count": blocker_slice.get("reported_candidate_count"),
                "content_sha256": blocker_slice.get("content_sha256"),
                "sample_tasks": [item.get("task_human_id") for item in items[:5] if isinstance(item, dict)],
            },
        )

    checks.append(safe_check("Prompt-pair top blocker slice is inspectable", prompt_pair_top_blocker_slice))

    def prompt_pair_top_blocker_session_plan() -> Check:
        contract = get_json(args.api_base, "/runtime-contract")
        required_fields = (
            (contract.get("required_response_fields") or {}).get("/api/prompt-pairs/top-blocker-review-session-plan")
            if isinstance(contract.get("required_response_fields"), dict)
            else []
        )
        tasks_before = get_json(args.api_base, "/tasks")
        plan = get_json(args.api_base, "/prompt-pairs/top-blocker-review-session-plan", {"limit": 5}, timeout=30)
        tasks_after = get_json(args.api_base, "/tasks")
        items = plan.get("items") if isinstance(plan.get("items"), list) else []
        field_plan = plan.get("field_plan") if isinstance(plan.get("field_plan"), list) else []
        projected_delta = plan.get("projected_task_delta") if isinstance(plan.get("projected_task_delta"), dict) else {}
        yaml_preview = plan.get("export_preview_yaml") if isinstance(plan.get("export_preview_yaml"), str) else ""
        failures = []
        missing_fields = [field for field in required_fields if field not in plan]
        if missing_fields:
            failures.append(f"session plan missing runtime-contract fields: {missing_fields}")
        if plan.get("plan_type") != "prompt_pair_top_blocker_review_session_plan":
            failures.append("unexpected prompt-pair blocker session plan type")
        if plan.get("review_policy") != "non_mutating_prompt_pair_batch_plan_no_export_promotion":
            failures.append("session plan lacks non-mutating batch policy")
        if plan.get("does_not_mutate_state") is not True:
            failures.append("session plan must be non-mutating")
        if plan.get("does_not_promote_to_training_export") is not True:
            failures.append("session plan must not promote to training export")
        if plan.get("requires_adam_gold_edit") is not True:
            failures.append("session plan must require Adam gold edit")
        if int(plan.get("selected_count") or 0) != len(items):
            failures.append("session plan selected count does not match items")
        if int(plan.get("candidate_count") or 0) < len(items):
            failures.append("session plan candidate count is smaller than selected items")
        if not field_plan:
            failures.append("session plan lacks field prompts")
        if projected_delta.get("would_create_tasks") != 0 or projected_delta.get("approved_exports_created") != 0:
            failures.append("session plan should not create tasks or approved exports")
        if projected_delta.get("raw_sources_mutated") is not False:
            failures.append("session plan must not mutate raw sources")
        if plan.get("completion_signal") != "selected_prompt_pair_blocker_batch_submitted_then_candidate_count_or_worklist_changes":
            failures.append("session plan has wrong completion signal")
        if len(str(plan.get("content_sha256") or "")) != 64:
            failures.append("session plan lacks stable content hash")
        if hashlib.sha256(yaml_preview.encode("utf-8")).hexdigest() != plan.get("export_preview_sha256"):
            failures.append("session plan YAML hash mismatch")
        if not yaml_preview.startswith("prompt_pair_top_blocker_review_session_plan:"):
            failures.append("session plan lacks YAML preview")
        if items:
            first = items[0]
            action = first.get("action") if isinstance(first.get("action"), dict) else {}
            if not first.get("task_id") or not first.get("task_human_id"):
                failures.append("session plan item lacks task identity")
            if not first.get("prompt") or not first.get("current_blockers"):
                failures.append("session plan item lacks prompt/current blockers")
            if action.get("action_type") != "open_held_prompt_pair_candidate" or not action.get("task_id"):
                failures.append("session plan item lacks open-held-pair action")
        else:
            failures.append("session plan has no selected items while live candidate queue should have held pairs")
        before_ids = {task.get("id") for task in tasks_before if isinstance(task, dict)}
        after_ids = {task.get("id") for task in tasks_after if isinstance(task, dict)}
        if before_ids != after_ids:
            failures.append("session plan mutated the task set")
        return Check(
            "Prompt-pair top blocker session plan is actionable",
            not failures,
            "; ".join(failures)
            if failures
            else "top prompt-pair blocker session plan batches existing tickets without export promotion",
            {
                "blocker": plan.get("blocker"),
                "selected_count": plan.get("selected_count"),
                "candidate_count": plan.get("candidate_count"),
                "field_plan": [field.get("field") for field in field_plan[:5] if isinstance(field, dict)],
                "content_sha256": plan.get("content_sha256"),
                "export_preview_sha256": plan.get("export_preview_sha256"),
                "sample_tasks": [item.get("task_human_id") for item in items[:5] if isinstance(item, dict)],
            },
        )

    checks.append(safe_check("Prompt-pair top blocker session plan is actionable", prompt_pair_top_blocker_session_plan))

    def prompt_pair_source_boundary_blocker_slice() -> Check:
        pack = get_json(args.api_base, "/prompt-pairs/held-candidates", {"limit": 30}, timeout=30)
        blocker_counts = pack.get("blocker_counts") if isinstance(pack.get("blocker_counts"), dict) else {}
        source_boundary_count = int(blocker_counts.get("source_boundary_blocks_training") or 0)
        if source_boundary_count <= 0:
            return Check(
                "Prompt-pair source-boundary blocker slice is directly addressable",
                True,
                "no current source-boundary prompt-pair blockers to inspect",
                {"source_boundary_blocks_training": 0},
            )

        blocker_slice = get_json(
            args.api_base,
            "/prompt-pairs/top-blocker-slice",
            {"limit": 5, "blocker": "source_boundary_blocks_training"},
            timeout=30,
        )
        plan = get_json(
            args.api_base,
            "/prompt-pairs/top-blocker-review-session-plan",
            {"limit": 5, "blocker": "source_boundary_blocks_training"},
            timeout=30,
        )
        items = blocker_slice.get("items") if isinstance(blocker_slice.get("items"), list) else []
        plan_items = plan.get("items") if isinstance(plan.get("items"), list) else []
        field_plan = plan.get("field_plan") if isinstance(plan.get("field_plan"), list) else []
        yaml_preview = plan.get("export_preview_yaml") if isinstance(plan.get("export_preview_yaml"), str) else ""
        failures: list[str] = []
        if blocker_slice.get("selection_policy") != "requested_backend_blocker_exact_match":
            failures.append("source-boundary slice did not use requested-blocker selection")
        if blocker_slice.get("requested_blocker") != "source_boundary_blocks_training":
            failures.append("source-boundary slice lost requested blocker")
        if blocker_slice.get("blocker") != "source_boundary_blocks_training":
            failures.append("source-boundary slice returned the wrong blocker")
        if int(blocker_slice.get("candidate_count") or 0) != source_boundary_count:
            failures.append("source-boundary slice candidate count does not match held pack")
        if not items:
            failures.append("source-boundary slice lacks items")
        for item in items[:5]:
            summary = item.get("source_boundary_summary") if isinstance(item.get("source_boundary_summary"), dict) else {}
            if summary.get("status") != "source_boundary_blocks_training":
                failures.append(f"{item.get('task_human_id')} lacks source-boundary block summary")
            if not summary.get("source_photo_id"):
                failures.append(f"{item.get('task_human_id')} lacks source photo id in boundary summary")
            if "sft" not in (summary.get("blocked_training_uses") or []):
                failures.append(f"{item.get('task_human_id')} boundary summary does not explain SFT block")
            if "dpo" not in (summary.get("blocked_training_uses") or []):
                failures.append(f"{item.get('task_human_id')} boundary summary does not explain DPO block")
            if summary.get("does_not_mutate_source") is not True:
                failures.append(f"{item.get('task_human_id')} boundary summary lacks no-source-mutation flag")
            if not summary.get("remediation_options"):
                failures.append(f"{item.get('task_human_id')} boundary summary lacks remediation options")
        if plan.get("selection_policy") != "requested_backend_blocker_exact_match":
            failures.append("source-boundary session plan did not use requested-blocker selection")
        if plan.get("requested_blocker") != "source_boundary_blocks_training":
            failures.append("source-boundary session plan lost requested blocker")
        if int(plan.get("selected_count") or 0) != len(plan_items):
            failures.append("source-boundary session plan selected count does not match items")
        if not field_plan or field_plan[0].get("field") != "source_boundary":
            failures.append("source-boundary session plan does not prompt for source_boundary field")
        if "requested_blocker: \"source_boundary_blocks_training\"" not in yaml_preview:
            failures.append("source-boundary session plan YAML does not preserve requested blocker")
        if "source_boundary_summary:" not in yaml_preview or "blocked_training_uses:" not in yaml_preview:
            failures.append("source-boundary session plan YAML lacks boundary summary")
        return Check(
            "Prompt-pair source-boundary blocker slice is directly addressable",
            not failures,
            "; ".join(failures)
            if failures
            else "source-boundary prompt-pair blockers can be selected even when they are not the largest worklist",
            {
                "source_boundary_blocks_training": source_boundary_count,
                "selection_policy": blocker_slice.get("selection_policy"),
                "reported_candidate_count": blocker_slice.get("reported_candidate_count"),
                "session_selected_count": plan.get("selected_count"),
                "sample_tasks": [item.get("task_human_id") for item in items[:5] if isinstance(item, dict)],
            },
        )

    checks.append(
        safe_check(
            "Prompt-pair source-boundary blocker slice is directly addressable",
            prompt_pair_source_boundary_blocker_slice,
        )
    )

    def dpo_rejected_reason_repair_packet() -> Check:
        packet = get_json(args.api_base, "/prompt-pairs/dpo-rejected-reason-repair-pack", {"limit": 25}, timeout=30)
        items = packet.get("items") if isinstance(packet.get("items"), list) else []
        yaml_preview = packet.get("export_preview_yaml") if isinstance(packet.get("export_preview_yaml"), str) else ""
        failures = []
        if packet.get("packet_type") != "dpo_rejected_reason_repair_packet":
            failures.append("unexpected DPO repair packet type")
        if packet.get("review_policy") != "repair_dpo_reason_only_no_training_export":
            failures.append("DPO repair packet lacks review-only policy")
        if packet.get("does_not_promote_to_training_export") is not True:
            failures.append("DPO repair packet must not promote to training export")
        if packet.get("requires_adam_gold_edit") is not True:
            failures.append("DPO repair packet must require Adam gold edit")
        if packet.get("blocker") != "dpo_rejected_reason_empty":
            failures.append("DPO repair packet targets the wrong blocker")
        if int(packet.get("total_candidate_count") or 0) < 20:
            failures.append("DPO repair packet should expose the live repeated blocker backlog")
        if int(packet.get("reported_candidate_count") or 0) != len(items):
            failures.append("DPO repair reported count does not match items")
        if len(str(packet.get("content_sha256") or "")) != 64:
            failures.append("DPO repair packet lacks stable content hash")
        if len(str(packet.get("export_preview_sha256") or "")) != 64:
            failures.append("DPO repair packet lacks YAML export hash")
        if not yaml_preview.startswith("dpo_rejected_reason_repair_packet:"):
            failures.append("DPO repair packet lacks YAML preview")
        if "dpo_rejected_reason_empty" not in yaml_preview:
            failures.append("DPO repair YAML does not name the blocker")
        if "projected_after_export_status: \"candidate\"" not in yaml_preview:
            failures.append("DPO repair YAML must show rejected-reason repair still leaves a candidate")
        if "needs_adam_gold_edit" not in yaml_preview:
            failures.append("DPO repair YAML must show Adam gold edit remains as a blocker")
        if items:
            first = items[0]
            preflight = first.get("backend_preflight") if isinstance(first.get("backend_preflight"), dict) else {}
            projection = first.get("repair_projection") if isinstance(first.get("repair_projection"), dict) else {}
            suggested_modes = first.get("suggested_failure_modes") if isinstance(first.get("suggested_failure_modes"), list) else []
            suggested_issue = first.get("suggested_rejected_issue") if isinstance(first.get("suggested_rejected_issue"), dict) else {}
            single_projection = get_json(
                args.api_base,
                "/prompt-pairs/dpo-rejected-reason-repair-projection",
                {"task_id": first.get("task_id") or first.get("task_human_id")},
                timeout=30,
            )
            if first.get("artifact_mode") != "dpo":
                failures.append("DPO repair item is not a DPO artifact")
            if not first.get("prompt") or not first.get("chosen_preview"):
                failures.append("DPO repair item lacks prompt/chosen preview")
            if "dpo_rejected_reason_empty" not in (preflight.get("blockers") or []):
                failures.append("DPO repair item preflight does not expose rejected reason blocker")
            if "failure_modes" not in (first.get("repair_fields") or []):
                failures.append("DPO repair item does not tell the operator which field to repair")
            if not suggested_modes:
                failures.append("DPO repair item lacks suggested failure modes")
            if suggested_modes == ["too_generic_not_charles_voice"]:
                failures.append("DPO repair item still uses only a generic failure-mode scaffold")
            if not suggested_issue.get("note") or not suggested_issue.get("issue_tag"):
                failures.append("DPO repair item lacks a concrete rejected-side issue note")
            if projection.get("does_not_mutate_task") is not True:
                failures.append("DPO repair projection must be non-mutating")
            if projection.get("target_blocker_cleared") is not True:
                failures.append("DPO repair projection does not clear target blocker")
            if "dpo_rejected_reason_empty" not in (projection.get("before_blockers") or []):
                failures.append("DPO repair projection lacks before blocker")
            if "dpo_rejected_reason_empty" in (projection.get("after_blockers") or []):
                failures.append("DPO repair projection still has rejected reason blocker after patch")
            if projection.get("still_requires_adam_gold_edit") is not True:
                failures.append("DPO repair projection must keep Adam review requirement visible")
            if projection.get("after_export_status") != "candidate":
                failures.append("DPO repair projection must keep projected after-status as candidate")
            if projection.get("after_dataset_outcome") != "Candidate dry-run only":
                failures.append("DPO repair projection must keep projected dataset outcome as candidate dry-run")
            if "needs_adam_gold_edit" not in (projection.get("after_blockers") or []):
                failures.append("DPO repair projection must keep needs_adam_gold_edit after target blocker clears")
            if single_projection.get("projection_type") != "dpo_rejected_reason_repair_projection":
                failures.append("single DPO repair projection has unexpected type")
            if single_projection.get("does_not_mutate_task") is not True:
                failures.append("single DPO repair projection must be non-mutating")
            if single_projection.get("target_blocker_cleared") is not True:
                failures.append("single DPO repair projection must clear target blocker")
            single_before = single_projection.get("before") if isinstance(single_projection.get("before"), dict) else {}
            single_after = single_projection.get("after") if isinstance(single_projection.get("after"), dict) else {}
            if "dpo_rejected_reason_empty" not in (single_before.get("blockers") or []):
                failures.append("single DPO repair projection lacks before blocker")
            if "dpo_rejected_reason_empty" in (single_after.get("blockers") or []):
                failures.append("single DPO repair projection still has target blocker after patch")
            if single_after.get("export_status") != "candidate":
                failures.append("single DPO repair projection must keep after-status as candidate")
            if single_after.get("dataset_outcome") != "Candidate dry-run only":
                failures.append("single DPO repair projection must keep dataset outcome as candidate dry-run")
            if "needs_adam_gold_edit" not in (single_after.get("blockers") or []):
                failures.append("single DPO repair projection must keep Adam gold edit blocker")
            single_input_patch = (
                single_projection.get("input_patch") if isinstance(single_projection.get("input_patch"), dict) else {}
            )
            single_modes = single_input_patch.get("failure_modes") if isinstance(single_input_patch.get("failure_modes"), list) else []
            if single_modes == ["too_generic_not_charles_voice"]:
                failures.append("single DPO repair projection still uses only the generic scaffold")
            single_issue = (
                single_projection.get("suggested_rejected_issue")
                if isinstance(single_projection.get("suggested_rejected_issue"), dict)
                else {}
            )
            if not single_issue.get("note") or not single_issue.get("issue_tag"):
                failures.append("single DPO repair projection lacks suggested rejected-side issue note")
            if not str(single_projection.get("yaml_diff_preview") or "").startswith("--- before_dpo_repair.yaml"):
                failures.append("single DPO repair projection lacks exact YAML diff preview")
            if len(str(single_projection.get("content_sha256") or "")) != 64:
                failures.append("single DPO repair projection lacks content hash")
            action = first.get("action") if isinstance(first.get("action"), dict) else {}
            if action.get("action_type") != "open_held_prompt_pair_candidate" or not action.get("task_id"):
                failures.append("DPO repair item lacks open-ticket action")
        else:
            failures.append("DPO repair packet has no items")
        return Check(
            "DPO rejected-reason repair packet is actionable",
            not failures,
            "; ".join(failures)
            if failures
            else "DPO repair packet exposes rejected-side reason gaps with YAML, blockers, and open-ticket actions",
            {
                "total_candidate_count": packet.get("total_candidate_count"),
                "reported_candidate_count": packet.get("reported_candidate_count"),
                "content_sha256": packet.get("content_sha256"),
                "export_preview_sha256": packet.get("export_preview_sha256"),
                "first_suggested_failure_modes": items[0].get("suggested_failure_modes") if items else [],
                "sample_tasks": [item.get("task_human_id") for item in items[:5] if isinstance(item, dict)],
            },
        )

    checks.append(safe_check("DPO rejected-reason repair packet is actionable", dpo_rejected_reason_repair_packet))

    def human_audit_pack_readiness() -> Check:
        pack = get_json(
            args.api_base,
            "/prompt-pairs/audit-pack",
            {"sample_limit": args.min_human_audit_pack_samples},
            timeout=20,
        )
        samples = pack.get("samples") if isinstance(pack.get("samples"), list) else []
        markdown = pack.get("markdown") if isinstance(pack.get("markdown"), str) else ""
        failures = []
        if int(pack.get("sample_count", 0)) < args.min_human_audit_pack_samples:
            failures.append(
                f"needs {args.min_human_audit_pack_samples} human-audit samples, found {pack.get('sample_count', 0)}"
            )
        if markdown.count("### Sample") < args.min_human_audit_pack_samples:
            failures.append("markdown audit pack does not include one visible section per sample")
        if pack.get("invalid_pair_count") != 0:
            failures.append("audit pack contains invalid prompt pairs")
        if pack.get("representative_requirements_met") is not True:
            failures.append("audit pack does not meet representative mode requirements")
        if pack.get("missing_required_modes"):
            failures.append(f"missing modes: {pack.get('missing_required_modes')}")
        missing_export_previews = [
            sample.get("task_human_id")
            for sample in samples[: args.min_human_audit_pack_samples]
            if not sample.get("export_preview_yaml")
        ]
        if missing_export_previews:
            failures.append("some audit samples lack exact export preview YAML")
        return Check(
            "200-pair human audit pack is available",
            not failures,
            "; ".join(failures)
            if failures
            else "large human audit pack exposes exact prompt/response/export previews without final-authenticity claims",
            {
                "sample_count": pack.get("sample_count"),
                "markdown_sample_sections": markdown.count("### Sample"),
                "represented_modes": pack.get("represented_modes"),
                "markdown_chars": len(markdown),
                "sample_limit_cap": pack.get("sample_limit_cap"),
            },
        )

    checks.append(safe_check("200-pair human audit pack is available", human_audit_pack_readiness))

    def voice_reference_pack_readiness() -> Check:
        pack = get_json(
            args.api_base,
            "/prompt-pairs/reference-pack",
            {"sample_limit": args.min_voice_reference_pack_samples},
            timeout=20,
        )
        records = pack.get("records") if isinstance(pack.get("records"), list) else []
        jsonl = pack.get("jsonl") if isinstance(pack.get("jsonl"), str) else ""
        lines = [line for line in jsonl.splitlines() if line.strip()]
        parsed = []
        failures = []
        for line in lines:
            try:
                parsed.append(json.loads(line))
            except json.JSONDecodeError as exc:
                failures.append(f"invalid JSONL line: {exc}")
        if pack.get("pack_type") != "prompt_pair_voice_reference_pack":
            failures.append("unexpected reference pack type")
        if int(pack.get("sample_count", 0)) < args.min_voice_reference_pack_samples:
            failures.append(
                f"needs {args.min_voice_reference_pack_samples} reference examples, found {pack.get('sample_count', 0)}"
            )
        if len(parsed) != int(pack.get("sample_count", 0)):
            failures.append("JSONL line count does not match sample_count")
        if pack.get("content_sha256") != hashlib.sha256(jsonl.encode("utf-8")).hexdigest():
            failures.append("reference JSONL content hash mismatch")
        if pack.get("ready_for_generation_context") is not True:
            failures.append("reference pack is not ready for generation context")
        if pack.get("missing_required_modes"):
            failures.append(f"missing modes: {pack.get('missing_required_modes')}")
        safety = pack.get("safety_policy") if isinstance(pack.get("safety_policy"), dict) else {}
        if safety.get("does_not_certify_final_authenticity") is not True:
            failures.append("reference pack must explicitly avoid final-authenticity claims")
        message_keys = set()
        for record in records[: args.min_voice_reference_pack_samples]:
            messages = record.get("messages") if isinstance(record.get("messages"), list) else []
            if len(messages) != 3:
                failures.append("reference record does not expose system/user/assistant messages")
                continue
            if [message.get("role") for message in messages] != ["system", "user", "assistant"]:
                failures.append("reference message role order is not system/user/assistant")
            if not messages[1].get("content") or not messages[2].get("content"):
                failures.append("reference record has empty prompt or assistant response")
            key = json.dumps(messages, ensure_ascii=False, sort_keys=True)
            if key in message_keys:
                failures.append("reference pack includes duplicate prompt/response messages")
            message_keys.add(key)
            if not record.get("embedding_input_text"):
                failures.append("reference record lacks embedding/reference text")
            if record.get("reference_use") != "voice_context_for_model_drafting_and_human_review":
                failures.append("reference record has unexpected reference_use")
        return Check(
            "Prompt-pair voice reference pack feeds generation context",
            not failures,
            "; ".join(failures)
            if failures
            else "prompt-pair tickets compile into a stable reference corpus for future model drafting",
            {
                "sample_count": pack.get("sample_count"),
                "unique_reference_count": pack.get("unique_reference_count"),
                "duplicate_excluded_count": pack.get("duplicate_excluded_count"),
                "represented_modes": pack.get("represented_modes"),
                "content_sha256": pack.get("content_sha256"),
            },
        )

    checks.append(
        safe_check(
            "Prompt-pair voice reference pack feeds generation context",
            voice_reference_pack_readiness,
        )
    )

    def training_export_readiness() -> Check:
        sft = get_json(
            args.api_base,
            "/dataset-exports/dry-run",
            {"export_type": "sft", "include_candidates": "true"},
        )
        dpo = get_json(
            args.api_base,
            "/dataset-exports/dry-run",
            {"export_type": "dpo", "include_candidates": "true"},
        )
        total_reviewable = int(sft.get("included_count", 0)) + int(sft.get("excluded_count", 0))
        failures = []
        if total_reviewable < args.min_training_artifacts:
            failures.append(
                f"needs {args.min_training_artifacts} SFT artifacts in export dry-run, found {total_reviewable}"
            )
        if int(dpo.get("included_count", 0)) == 0 and int(dpo.get("excluded_count", 0)) == 0:
            failures.append("no DPO artifacts are represented yet")
        sft_duplicate_count = included_duplicate_count(sft)
        dpo_duplicate_count = included_duplicate_count(dpo)
        if sft_duplicate_count:
            failures.append(f"SFT dry-run still includes {sft_duplicate_count} duplicate training rows")
        if dpo_duplicate_count:
            failures.append(f"DPO dry-run still includes {dpo_duplicate_count} duplicate training rows")
        sft_missing_blockers = candidate_rows_missing_blockers(sft)
        dpo_missing_blockers = candidate_rows_missing_blockers(dpo)
        if sft_missing_blockers:
            failures.append(f"SFT candidate rows lack review blockers: {sft_missing_blockers[:3]}")
        if dpo_missing_blockers:
            failures.append(f"DPO candidate rows lack review blockers: {dpo_missing_blockers[:3]}")
        dpo_missing_issue_context = dpo_candidate_rows_missing_issue_context(dpo)
        if dpo_missing_issue_context:
            failures.append(f"DPO candidate rows lack chosen/rejected issue context: {dpo_missing_issue_context[:3]}")
        return Check(
            "Training export dry-runs expose reviewable artifacts",
            not failures,
            "; ".join(failures) if failures else "dataset export dry-runs expose reviewable SFT/DPO artifacts",
            {
                "sft": {
                    **summarize_dry_run(sft),
                    "included_duplicate_count": sft_duplicate_count,
                    "candidate_rows_missing_blockers": len(sft_missing_blockers),
                },
                "dpo": {
                    **summarize_dry_run(dpo),
                    "included_duplicate_count": dpo_duplicate_count,
                    "candidate_rows_missing_blockers": len(dpo_missing_blockers),
                    "candidate_rows_missing_issue_context": len(dpo_missing_issue_context),
                },
            },
        )

    checks.append(safe_check("Training export dry-runs expose reviewable artifacts", training_export_readiness))

    checks.append(
        safe_check(
            "Dataset export build creates exact retrievable JSONL",
            lambda: command_check(
                "Dataset export build creates exact retrievable JSONL",
                [
                    "docker",
                    "compose",
                    "exec",
                    "-T",
                    "api",
                    "pytest",
                    "-q",
                    "tests/test_dataset_exports.py::test_export_dry_run_excludes_boundary_blocked_and_candidate_items",
                    "tests/test_dataset_exports.py::test_candidate_export_dry_run_preserves_prompt_pair_provenance_backstage",
                    "tests/test_ralph_phase1_training_spine.py::test_sft_export_guard_blocks_filename_placeholder_prompt_even_with_clean_rubric",
                    "tests/test_ralph_phase1_training_spine.py::test_dpo_export_guard_blocks_identical_or_unexplained_rejected_response",
                    "tests/test_ralph_phase3_prompt_pair_audit.py::test_prompt_pair_audit_and_reference_pack_exclude_structural_sft_blockers",
                ],
            ),
        )
    )

    checks.append(
        safe_check(
            "Prompt-pair submit receipts explain export artifact status",
            lambda: command_check(
                "Prompt-pair submit receipts explain export artifact status",
                [
                    "docker",
                    "compose",
                    "exec",
                    "-T",
                    "api",
                    "pytest",
                    "-q",
                    "tests/test_task_submit.py::test_gold_voice_submission_creates_annotation_and_training_artifacts",
                    "tests/test_task_submit.py::test_gold_voice_response_b_minor_issue_stays_candidate_until_resolved",
                    "tests/test_task_submit.py::test_unified_dpo_gold_submission_creates_dpo_only_artifact",
                ],
            ),
        )
    )

    def text_model_status() -> Check:
        payload = get_json(args.api_base, "/model-status")
        requirements = (
            payload.get("credential_requirements")
            if isinstance(payload.get("credential_requirements"), dict)
            else {}
        )
        required_env = {
            item.get("name"): item
            for item in requirements.get("required_env", [])
            if isinstance(item, dict) and item.get("name")
        }
        failures = []
        if payload.get("text_generation_model") != args.required_text_model:
            failures.append(f"text model should be {args.required_text_model}")
        if payload.get("text_generation_reasoning_effort") != args.required_text_reasoning:
            failures.append(f"reasoning effort should be {args.required_text_reasoning}")
        if payload.get("fine_tuning_enabled_in_mvp") is not False:
            failures.append("fine-tuning must remain disabled in MVP")
        if requirements.get("api") != "responses":
            failures.append("credential requirements must target the Responses API")
        if requirements.get("model_name") != args.required_text_model:
            failures.append("credential requirements lost text generation model")
        if requirements.get("reasoning_effort") != args.required_text_reasoning:
            failures.append("credential requirements lost reasoning effort")
        if "OPENAI_API_KEY" not in required_env:
            failures.append("credential requirements must include OPENAI_API_KEY")
        elif required_env["OPENAI_API_KEY"].get("secret") is not True:
            failures.append("OPENAI_API_KEY requirement must be marked secret")
        if "TEXT_GENERATION_LIVE_CALLS_ENABLED" not in required_env:
            failures.append("credential requirements must include TEXT_GENERATION_LIVE_CALLS_ENABLED")
        elif required_env["TEXT_GENERATION_LIVE_CALLS_ENABLED"].get("required_value") != "true":
            failures.append("live-call opt-in requirement must state required_value=true")
        requirement_safety = (
            requirements.get("safety_policy")
            if isinstance(requirements.get("safety_policy"), dict)
            else {}
        )
        if requirement_safety.get("fine_tuning_api_calls_allowed") is not False:
            failures.append("credential requirements must preserve no-fine-tuning policy")
        return Check(
            "Text generation model configuration is visible and gated",
            not failures,
            "; ".join(failures) if failures else "text-generation status exposes model, reasoning, and live-call gate",
            {
                "text_generation_model": payload.get("text_generation_model"),
                "text_generation_reasoning_effort": payload.get("text_generation_reasoning_effort"),
                "text_generation_live_calls_enabled": payload.get("text_generation_live_calls_enabled"),
                "openai_api_key_configured": payload.get("openai_api_key_configured"),
                "text_generation_live_ready": payload.get("text_generation_live_ready"),
                "fine_tuning_enabled_in_mvp": payload.get("fine_tuning_enabled_in_mvp"),
                "required_env": sorted(required_env),
            },
        )

    checks.append(safe_check("Text generation model configuration is visible and gated", text_model_status))

    def demo_generation_readiness() -> Check:
        payload = get_json(args.api_base, "/model-status/demo-readiness", {"limit": args.min_demo_prompts})
        prompts = payload.get("held_out_prompts") if isinstance(payload.get("held_out_prompts"), list) else []
        blockers = payload.get("blockers") if isinstance(payload.get("blockers"), list) else []
        requirements = (
            payload.get("credential_requirements")
            if isinstance(payload.get("credential_requirements"), dict)
            else {}
        )
        plan = payload.get("generation_input_plan") if isinstance(payload.get("generation_input_plan"), dict) else {}
        plan_requirements = (
            plan.get("credential_requirements")
            if isinstance(plan.get("credential_requirements"), dict)
            else {}
        )
        failures = []
        if payload.get("demo_type") != "charles_voice_model_demo":
            failures.append("unexpected demo readiness type")
        if payload.get("model_name") != args.required_text_model:
            failures.append(f"demo model should be {args.required_text_model}")
        if payload.get("reasoning_effort") != args.required_text_reasoning:
            failures.append(f"demo reasoning should be {args.required_text_reasoning}")
        if len(prompts) < args.min_demo_prompts:
            failures.append(f"needs {args.min_demo_prompts} held-out demo prompts, found {len(prompts)}")
        safety = payload.get("safety_policy") if isinstance(payload.get("safety_policy"), dict) else {}
        if safety.get("outputs_truth_status") != "model_generated" or safety.get("adam_review_required") is not True:
            failures.append("demo safety policy must keep outputs model-generated and Adam-reviewed")
        if payload.get("can_generate") is False and not blockers:
            failures.append("blocked demo readiness must state blockers")
        if requirements.get("api") != "responses" or plan_requirements.get("api") != "responses":
            failures.append("demo readiness must expose Responses API credential requirements")
        if (requirements.get("safety_policy") or {}).get("fine_tuning_api_calls_allowed") is not False:
            failures.append("demo credential requirements must block fine-tuning calls")
        if (plan_requirements.get("safety_policy") or {}).get("fine_tuning_api_calls_allowed") is not False:
            failures.append("demo input plan credential requirements must block fine-tuning calls")
        return Check(
            "Model demo generation is honestly gated",
            not failures,
            "; ".join(failures)
            if failures
            else "demo generation exposes held-out prompts and credentials/live-call blocker without creating training truth",
            {
                "status": payload.get("status"),
                "can_generate": payload.get("can_generate"),
                "blockers": blockers,
                "held_out_prompt_count": len(prompts),
                "credential_requirement_api": requirements.get("api"),
                "sample_prompts": [item.get("prompt") for item in prompts[:3]],
            },
        )

    checks.append(safe_check("Model demo generation is honestly gated", demo_generation_readiness))

    def demo_generation_request_preview() -> Check:
        payload = get_json(args.api_base, "/model-status/demo-generation-request-preview", {"limit": args.min_demo_prompts})
        requests = payload.get("requests") if isinstance(payload.get("requests"), list) else []
        contract = get_json(args.api_base, "/runtime-contract")
        contract_fields = (contract.get("required_response_fields") or {}).get(
            "/api/model-status/demo-generation-request-preview",
            [],
        )
        failures = []
        if payload.get("preview_type") != "charles_voice_model_demo_generation_request_preview":
            failures.append("unexpected demo request preview type")
        if payload.get("does_not_mutate_state") is not True:
            failures.append("demo request preview must be non-mutating")
        if payload.get("no_live_model_call") is not True:
            failures.append("demo request preview must avoid live model calls")
        if payload.get("no_generation_created") is not True:
            failures.append("demo request preview must not create generation rows")
        if payload.get("does_not_promote_to_training_export") is not True:
            failures.append("demo request preview must not promote training export")
        if payload.get("model_name") != args.required_text_model:
            failures.append(f"preview model should be {args.required_text_model}")
        if payload.get("reasoning_effort") != args.required_text_reasoning:
            failures.append(f"preview reasoning should be {args.required_text_reasoning}")
        if payload.get("store") is not False:
            failures.append("preview must preserve Responses API store=false")
        if len(requests) < args.min_demo_prompts:
            failures.append(f"needs {args.min_demo_prompts} request previews, found {len(requests)}")
        if len(str(payload.get("content_sha256") or "")) != 64:
            failures.append("preview lacks stable content hash")
        if len(str(payload.get("export_preview_sha256") or "")) != 64:
            failures.append("preview lacks YAML hash")
        if "export_preview_yaml" not in payload or "request_body_json: |-" not in str(payload.get("export_preview_yaml") or ""):
            failures.append("preview YAML must include exact request body JSON blocks")
        if not contract_fields:
            failures.append("runtime contract lacks demo request preview endpoint")
        for request in requests[: args.min_demo_prompts]:
            body = request.get("request_body") if isinstance(request.get("request_body"), dict) else {}
            safety = request.get("safety_checks") if isinstance(request.get("safety_checks"), dict) else {}
            if body.get("model") != args.required_text_model:
                failures.append("request body lost required model")
            if (body.get("reasoning") or {}).get("effort") != args.required_text_reasoning:
                failures.append("request body lost required reasoning effort")
            if body.get("store") is not False:
                failures.append("request body must use store=false")
            if safety.get("held_out_answer_excluded_from_request") is not True:
                failures.append("held-out answer leaked into request preview")
            if safety.get("rejected_response_excluded_from_request") is not True:
                failures.append("rejected DPO response leaked into request preview")
            if safety.get("fine_tuning_api_calls_allowed") is not False:
                failures.append("request safety policy must block fine-tuning APIs")
        return Check(
            "Model demo request preview is exact and non-mutating",
            not failures,
            "; ".join(failures)
            if failures
            else "demo generation has inspectable no-live Responses API request bodies before credentials are enabled",
            {
                "request_count": payload.get("request_count"),
                "content_sha256": payload.get("content_sha256"),
                "export_preview_sha256": payload.get("export_preview_sha256"),
                "sample_request_hashes": [request.get("request_body_sha256") for request in requests[:3]],
            },
        )

    checks.append(safe_check("Model demo request preview is exact and non-mutating", demo_generation_request_preview))

    checks.append(
        safe_check(
            "Model demo generations stay model-generated and outside training truth",
            lambda: command_check(
                "Model demo generations stay model-generated and outside training truth",
                [
                    "docker",
                    "compose",
                    "exec",
                    "-T",
                    "api",
                    "pytest",
                    "-q",
                    "tests/test_ralph_phase1_training_spine.py::test_demo_generation_readiness_lists_held_out_prompts_and_honest_credential_blocker",
                    "tests/test_ralph_phase1_training_spine.py::test_demo_generation_endpoint_stores_model_generated_outputs_without_training_truth",
                ],
            ),
        )
    )

    checks.append(
        safe_check(
            "Natural text intake creates singleton Prompt Pair tickets",
            lambda: command_check(
                "Natural text intake creates singleton Prompt Pair tickets",
                [
                    "docker",
                    "compose",
                    "exec",
                    "-T",
                    "api",
                    "pytest",
                    "-q",
                    "tests/test_ralph_phase1_training_spine.py::test_plain_text_extraction_prefers_natural_sections_over_single_arbitrary_chunk",
                    "tests/test_ralph_phase1_training_spine.py::test_docx_extraction_uses_natural_sections_with_exact_locators",
                    "tests/test_ralph_phase1_training_spine.py::test_eml_extraction_uses_body_natural_sections_not_headers",
                    "tests/test_ralph_phase1_training_spine.py::test_source_review_generate_pairs_from_natural_sections_creates_singleton_prompt_pair_tasks",
                    "tests/test_ralph_phase1_training_spine.py::test_natural_section_generation_holds_split_sections_and_blocks_contextless_export",
                ],
            ),
        )
    )

    checks.append(
        safe_check(
            "Source-review fallback pair generation records model/no-live metadata",
            lambda: command_check(
                "Source-review fallback pair generation records model/no-live metadata",
                [
                    "docker",
                    "compose",
                    "exec",
                    "-T",
                    "api",
                    "pytest",
                    "-q",
                    "tests/test_ralph_phase1_training_spine.py::test_source_review_fallback_pair_records_generation_metadata_without_archival_claim",
                ],
            ),
        )
    )

    def photo_preview_readiness() -> Check:
        photos = get_json(args.api_base, "/assets", {"asset_type": "photo"})
        mirrored = [
            asset
            for asset in photos
            if asset.get("import_status") == "mirrored" or asset.get("processing_status") == "image_preview_ready"
        ]
        preview_ready = [asset for asset in photos if asset.get("processing_status") == "image_preview_ready"]
        failures = []
        if len(mirrored) < args.min_mirrored_photos:
            failures.append(f"needs {args.min_mirrored_photos} mirrored photos, found {len(mirrored)}")
        if len(preview_ready) < args.min_mirrored_photos:
            failures.append(f"needs {args.min_mirrored_photos} preview-ready photos, found {len(preview_ready)}")

        checked_previews = []
        for required_title in args.required_photo_preview:
            asset = next((item for item in photos if title_matches(item, required_title)), None)
            if not asset:
                failures.append(f"missing required photo asset {required_title!r}")
                continue
            content_type, body = get_bytes(args.api_base, f"/assets/{asset['id']}/preview")
            checked_previews.append(
                {
                    "title": required_title,
                    "asset_id": asset["id"],
                    "content_type": content_type,
                    "bytes": len(body),
                }
            )
            if not content_type.startswith("image/") or len(body) < 1024:
                failures.append(f"preview for {required_title!r} did not return real image bytes")
        return Check(
            "Mirrored photos have reliable live previews",
            not failures,
            "; ".join(failures) if failures else "mirrored photo previews are live and image-backed",
            {
                "photo_count": len(photos),
                "mirrored_count": len(mirrored),
                "preview_ready_count": len(preview_ready),
                "checked_previews": checked_previews,
            },
        )

    checks.append(safe_check("Mirrored photos have reliable live previews", photo_preview_readiness))

    def photo_review_inventory_readiness() -> Check:
        inventory = get_json(args.api_base, "/assets/photo-review-inventory", {"limit": 100})
        groups = inventory.get("groups") if isinstance(inventory.get("groups"), list) else []
        duplicate_groups = (
            inventory.get("duplicate_groups") if isinstance(inventory.get("duplicate_groups"), list) else []
        )
        failures = []
        if inventory.get("inventory_type") != "photo_review_inventory":
            failures.append("unexpected photo review inventory type")
        if int(inventory.get("preview_ready_count", 0)) < args.min_mirrored_photos:
            failures.append("inventory preview-ready count is below mirrored-photo threshold")
        if int(inventory.get("needs_context_count", 0)) <= 0:
            failures.append("inventory should expose remaining preview-ready photos needing context")
        if int(inventory.get("needs_context_group_count", 0)) <= 0:
            failures.append("inventory should expose canonical photo groups needing context")
        if int(inventory.get("duplicate_group_count", 0)) <= 0:
            failures.append("inventory should expose duplicate/copy variant groups")
        if not groups:
            failures.append("inventory groups are missing")
        for group in duplicate_groups[:5]:
            variants = group.get("variants") if isinstance(group.get("variants"), list) else []
            if int(group.get("asset_count", 0)) < 2:
                failures.append("duplicate group has fewer than two assets")
            if not group.get("canonical_asset_id"):
                failures.append("duplicate group lacks canonical asset")
            if not any(variant.get("is_copy_variant") for variant in variants):
                failures.append("duplicate group does not identify copy variants")
        return Check(
            "Photo review inventory exposes context gaps and duplicate groups",
            not failures,
            "; ".join(failures) if failures else "photo inventory summarizes review gaps without creating low-quality memories",
            {
                "photo_count": inventory.get("photo_count"),
                "preview_ready_count": inventory.get("preview_ready_count"),
                "profile_count": inventory.get("profile_count"),
                "needs_context_count": inventory.get("needs_context_count"),
                "needs_context_group_count": inventory.get("needs_context_group_count"),
                "duplicate_group_count": inventory.get("duplicate_group_count"),
                "sample_groups": [
                    {
                        "display_title": group.get("display_title"),
                        "asset_count": group.get("asset_count"),
                        "needs_context_count": group.get("needs_context_count"),
                    }
                    for group in groups[:5]
                ],
            },
        )

    checks.append(
        safe_check(
            "Photo review inventory exposes context gaps and duplicate groups",
            photo_review_inventory_readiness,
        )
    )

    def photo_context_review_pack_readiness() -> Check:
        pack = get_json(args.api_base, "/assets/photo-context-review-pack", {"scope": "family_private", "limit": 100})
        progress = get_json(
            args.api_base,
            "/assets/photo-context-review-pack/session-progress",
            {"scope": "family_private", "limit": 100},
        )
        progress_artifact = get_json(
            args.api_base,
            "/assets/photo-context-review-pack/session-progress/artifact",
            {"scope": "family_private", "limit": 100},
        )
        contract = get_json(args.api_base, "/runtime-contract")
        field_worklist = get_json(
            args.api_base,
            "/assets/photo-context-review-pack/retrieval-gap-field-worklist",
            {"scope": "family_private", "limit": 100},
        )
        payoff_preview = get_json(
            args.api_base,
            "/assets/photo-context-review-pack/retrieval-gap-payoff-preview",
            {"scope": "family_private", "limit": 10},
        )
        dry_session = post_json(
            args.api_base,
            "/assets/photo-context-review-pack/review-session",
            {"scope": "family_private", "limit": 3, "dry_run": "true", "source_query": args.honest_gap_query},
        )
        manifest = pack.get("manifest") if isinstance(pack.get("manifest"), dict) else {}
        no_claim_groups = (
            pack.get("needs_context_groups") if isinstance(pack.get("needs_context_groups"), list) else []
        )
        held_drafts = pack.get("machine_drafts_held") if isinstance(pack.get("machine_drafts_held"), list) else []
        vector_ready = pack.get("reviewed_vector_ready") if isinstance(pack.get("reviewed_vector_ready"), list) else []
        gallery_items = pack.get("gallery_preview_items") if isinstance(pack.get("gallery_preview_items"), list) else []
        review_worklists = pack.get("review_worklists") if isinstance(pack.get("review_worklists"), list) else []
        failures = []
        if pack.get("pack_type") != "photo_context_review_pack":
            failures.append("unexpected photo context review pack type")
        if pack.get("review_policy") != "reviewed_only_by_default":
            failures.append("photo context pack must use reviewed-only policy")
        if int(manifest.get("preview_ready_count", 0)) < args.min_mirrored_photos:
            failures.append("photo context pack preview-ready count is below mirrored-photo threshold")
        if int(manifest.get("needs_context_group_count", 0)) <= 0:
            failures.append("photo context pack should expose no-claim groups needing Adam context")
        if int(manifest.get("held_for_adam_review_count", 0)) <= 0:
            failures.append("photo context pack should expose machine drafts held for Adam review")
        if int(manifest.get("vector_policy_violation_count", 0)) != 0:
            failures.append("reviewed vector-ready pack includes policy violations")
        vector_policy = manifest.get("vector_policy") if isinstance(manifest.get("vector_policy"), dict) else {}
        if vector_policy.get("system_inference_excluded_by_default") is not True:
            failures.append("photo context pack must explicitly exclude system inference from default vector handoff")
        if vector_policy.get("ordinary_db_vector_storage") is not False:
            failures.append("photo context pack must not imply ordinary DB vector storage")
        if not isinstance(pack.get("export_preview_yaml"), str) or "photo_context_review_pack:" not in pack.get("export_preview_yaml", ""):
            failures.append("photo context pack lacks exact YAML export preview")
        if int(manifest.get("photo_context_worklist_count") or 0) != len(review_worklists):
            failures.append("photo context worklist count does not match worklist records")
        if int(manifest.get("needs_context_group_count", 0)) > 0 and not any(
            worklist.get("worklist_key") == "photo_context:no_claim_needs_context" for worklist in review_worklists
        ):
            failures.append("photo context pack lacks no-claim context worklist")
        if int(manifest.get("held_for_adam_review_count", 0)) > 0 and not any(
            worklist.get("worklist_key") == "photo_context:machine_draft_needs_adam_review"
            for worklist in review_worklists
        ):
            failures.append("photo context pack lacks held machine draft worklist")
        for worklist in review_worklists[:5]:
            previews = worklist.get("candidate_previews") if isinstance(worklist.get("candidate_previews"), list) else []
            action = worklist.get("recommended_action") if isinstance(worklist.get("recommended_action"), dict) else {}
            if not str(worklist.get("worklist_key") or "").startswith("photo_context:"):
                failures.append("photo context worklist lacks stable namespaced key")
            if len(str(worklist.get("review_sequence_key") or "")) != 64:
                failures.append(f"{worklist.get('worklist_key')} lacks stable sequence hash")
            if worklist.get("not_memory_claim") is not True:
                failures.append(f"{worklist.get('worklist_key')} should be marked not-memory-claim")
            if int(worklist.get("candidate_count") or 0) <= 0 or not previews:
                failures.append(f"{worklist.get('worklist_key')} lacks candidate previews")
            if not action.get("action_type"):
                failures.append(f"{worklist.get('worklist_key')} lacks recommended action")
        if progress.get("progress_type") != "photo_context_session_progress":
            failures.append("photo context session progress has unexpected type")
        if progress.get("review_policy") != "drafts_projected_without_mutation":
            failures.append("photo context progress must declare projection-only review policy")
        if progress.get("does_not_mutate_state") is not True:
            failures.append("photo context progress must be non-mutating")
        if progress.get("does_not_create_memory_claim") is not True:
            failures.append("photo context progress must not create memory claims")
        if progress.get("does_not_create_embedding_record") is not True:
            failures.append("photo context progress must not create embedding records")
        if progress.get("requires_adam_context") is not True:
            failures.append("photo context progress must require Adam context")
        if progress.get("completion_signal") != "submit_ready_count_increases_or_retrieval_gap_missing_fields_decrease":
            failures.append("photo context progress lacks reviewable completion signal")
        if len(str(progress.get("content_sha256") or "")) != 64:
            failures.append("photo context progress lacks stable content hash")
        progress_boundaries = progress.get("safety_boundaries") if isinstance(progress.get("safety_boundaries"), list) else []
        if not any("not a memory claim" in str(boundary) for boundary in progress_boundaries):
            failures.append("photo context progress lacks no-memory-claim safety boundary")
        if not any("embedding" in str(boundary).lower() for boundary in progress_boundaries):
            failures.append("photo context progress lacks no-embedding safety boundary")
        contract_fields = (
            (contract.get("required_response_fields") or {}).get("/api/assets/photo-context-review-pack/session-progress")
            if isinstance(contract.get("required_response_fields"), dict)
            else []
        )
        for field in [
            "does_not_create_memory_claim",
            "does_not_create_embedding_record",
            "completion_signal",
            "content_sha256",
        ]:
            if field not in contract_fields:
                failures.append(f"runtime contract lacks photo context progress field {field}")
        if int(progress.get("total_context_task_count") or 0) <= 0:
            failures.append("photo context progress should expose created/open context tasks")
        if not isinstance(progress.get("status_counts"), dict):
            failures.append("photo context progress lacks status counts")
        if not isinstance(progress.get("blocked_reason_counts"), dict):
            failures.append("photo context progress lacks blocker counts")
        provenance_policy = progress.get("provenance_policy") if isinstance(progress.get("provenance_policy"), dict) else {}
        if provenance_policy.get("retrieval_gap_origin_is_not_memory_claim") is not True:
            failures.append("photo context progress must mark retrieval-gap origins as not-memory-claim")
        if provenance_policy.get("review_session_origin_is_not_memory_claim") is not True:
            failures.append("photo context progress must mark review-session origins as not-memory-claim")
        if provenance_policy.get("query_is_context_prioritization_only") is not True:
            failures.append("photo context progress must preserve query-as-prioritization policy")
        if provenance_policy.get("vector_ready_requires_submit") is not True:
            failures.append("photo context progress must require submit before vector readiness")
        progress_items = progress.get("items") if isinstance(progress.get("items"), list) else []
        session_origin_items = [
            item
            for item in progress_items
            if isinstance(item, dict) and isinstance(item.get("review_session_origin"), dict)
        ]
        for item in progress_items[:10]:
            retrieval_origin = item.get("retrieval_gap_origin") if isinstance(item.get("retrieval_gap_origin"), dict) else {}
            review_origin = item.get("review_session_origin") if isinstance(item.get("review_session_origin"), dict) else {}
            provenance_boundary = item.get("provenance_boundary") if isinstance(item.get("provenance_boundary"), dict) else {}
            if retrieval_origin:
                if retrieval_origin.get("truth_status") != "no_claim" or retrieval_origin.get("not_memory_claim") is not True:
                    failures.append("photo context progress item retrieval origin lacks no-claim boundary")
                if provenance_boundary.get("retrieval_origin_not_memory_claim") is not True:
                    failures.append("photo context progress item provenance boundary lost retrieval no-claim flag")
            if review_origin:
                if review_origin.get("not_memory_claim") is not True:
                    failures.append("photo context progress item review-session origin lacks not-memory-claim")
                if review_origin.get("query_is_context_prioritization_only") is not True:
                    failures.append("photo context progress item review-session origin lost query policy")
                if not review_origin.get("candidate_match_quality") or not review_origin.get("candidate_selection_reason"):
                    failures.append("photo context progress item review-session origin lacks candidate basis")
                if provenance_boundary.get("review_session_origin_not_memory_claim") is not True:
                    failures.append("photo context progress item provenance boundary lost review-session no-claim flag")
        if int(progress.get("review_session_task_count") or 0) <= 0:
            failures.append("photo context progress should expose at least one review-session-origin task after browser proof")
        if not session_origin_items and int(progress.get("review_session_task_count") or 0) > 0:
            failures.append("photo context progress review-session count is not represented in returned items")
        if progress_artifact.get("artifact_type") != "photo_context_session_progress_artifact":
            failures.append("photo context progress artifact has unexpected type")
        if progress_artifact.get("source_progress_content_sha256") != progress.get("content_sha256"):
            failures.append("photo context progress artifact does not point at source progress hash")
        if progress_artifact.get("does_not_create_memory_claim") is not True:
            failures.append("photo context progress artifact must not create memory claims")
        if progress_artifact.get("does_not_create_embedding_record") is not True:
            failures.append("photo context progress artifact must not create embedding records")
        if progress_artifact.get("provenance_policy") != provenance_policy:
            failures.append("photo context progress artifact provenance policy diverges from progress endpoint")
        artifact_items = progress_artifact.get("items") if isinstance(progress_artifact.get("items"), list) else []
        if not any(isinstance(item, dict) and isinstance(item.get("review_session_origin"), dict) for item in artifact_items):
            failures.append("photo context progress artifact lacks review-session origin samples")
        if field_worklist.get("worklist_type") != "photo_context_retrieval_gap_field_worklist":
            failures.append("retrieval-gap field worklist has unexpected type")
        if field_worklist.get("review_policy") != "retrieval_gap_missing_fields_no_memory_claim_until_adam_context":
            failures.append("retrieval-gap field worklist lacks no-claim review policy")
        if field_worklist.get("does_not_mutate_state") is not True:
            failures.append("retrieval-gap field worklist must be non-mutating")
        if field_worklist.get("does_not_create_memory_claim") is not True:
            failures.append("retrieval-gap field worklist must not create memory claims")
        if field_worklist.get("requires_adam_context") is not True:
            failures.append("retrieval-gap field worklist must require Adam context")
        if len(str(field_worklist.get("content_sha256") or "")) != 64:
            failures.append("retrieval-gap field worklist lacks content hash")
        if len(str(field_worklist.get("export_preview_sha256") or "")) != 64:
            failures.append("retrieval-gap field worklist lacks YAML hash")
        if "photo_context_retrieval_gap_field_worklist:" not in str(field_worklist.get("export_preview_yaml") or ""):
            failures.append("retrieval-gap field worklist lacks exact YAML preview")
        if int(field_worklist.get("retrieval_gap_task_count") or 0) != int(progress.get("retrieval_gap_task_count") or 0):
            failures.append("retrieval-gap field worklist task count disagrees with session progress")
        field_items = field_worklist.get("items") if isinstance(field_worklist.get("items"), list) else []
        if int(field_worklist.get("reported_item_count") or 0) != len(field_items):
            failures.append("retrieval-gap field worklist item count is inconsistent")
        for item in field_items[:5]:
            if item.get("truth_status") != "no_claim" or item.get("not_memory_claim") is not True:
                failures.append("retrieval-gap field worklist item lacks no-claim truth boundary")
            if not item.get("missing_fields"):
                failures.append("retrieval-gap field worklist item lacks missing fields")
            if not item.get("completion_signal"):
                failures.append("retrieval-gap field worklist item lacks completion signal")
        if payoff_preview.get("preview_type") != "photo_context_retrieval_gap_payoff_preview":
            failures.append("retrieval-gap payoff preview has unexpected type")
        if payoff_preview.get("review_policy") != "read_only_payoff_preview_no_generated_memory_claims":
            failures.append("retrieval-gap payoff preview lacks no-generated-memory policy")
        if payoff_preview.get("does_not_mutate_state") is not True:
            failures.append("retrieval-gap payoff preview must be non-mutating")
        if payoff_preview.get("does_not_create_memory_claim") is not True:
            failures.append("retrieval-gap payoff preview must not create memory claims")
        if payoff_preview.get("uses_placeholders_for_missing_adam_context") is not True:
            failures.append("retrieval-gap payoff preview must use placeholders for missing context")
        if payoff_preview.get("source_worklist_content_sha256") != field_worklist.get("content_sha256"):
            failures.append("retrieval-gap payoff preview does not point at the field worklist hash")
        if len(str(payoff_preview.get("content_sha256") or "")) != 64:
            failures.append("retrieval-gap payoff preview lacks content hash")
        if "photo_context_retrieval_gap_payoff_preview:" not in str(payoff_preview.get("export_preview_yaml") or ""):
            failures.append("retrieval-gap payoff preview lacks exact YAML preview")
        payoff_items = payoff_preview.get("items") if isinstance(payoff_preview.get("items"), list) else []
        if not payoff_items:
            failures.append("retrieval-gap payoff preview lacks items")
        for item in payoff_items[:5]:
            if item.get("truth_status_before_completion") != "no_claim":
                failures.append("retrieval-gap payoff preview item should start as no_claim")
            if item.get("does_not_create_memory_claim") is not True:
                failures.append("retrieval-gap payoff preview item lacks no-memory-claim flag")
            if "[requires Adam:" not in str(item.get("vector_text_template") or ""):
                failures.append("retrieval-gap payoff preview item lacks Adam placeholder template")
            if "reviewed_only_vector_handoff_record" not in (item.get("unlocked_records") or []):
                failures.append("retrieval-gap payoff preview item lacks vector handoff unlock")
        for group in no_claim_groups[:5]:
            if group.get("truth_status") != "no_claim" or group.get("not_memory_claim") is not True:
                failures.append("no-claim photo group lacks truth/no-memory boundary")
            if group.get("evidence_source") != "title_filename_only":
                failures.append("no-claim photo group should be title/filename evidence only")
            if not group.get("canonical_asset_id") or not group.get("thumbnail_url"):
                failures.append("no-claim photo group lacks previewable canonical asset")
            action = group.get("primary_action") if isinstance(group.get("primary_action"), dict) else {}
            if action.get("action_type") not in {"create_photo_context_task", "open_existing_photo_context_task"}:
                failures.append("no-claim photo group lacks context task action")
        for draft in held_drafts[:5]:
            if draft.get("truth_status") != "system_inference":
                failures.append("held machine draft should remain system_inference")
            if draft.get("requires_adam_review") is not True:
                failures.append("held machine draft lacks Adam-review flag")
            if draft.get("does_not_certify_final_memory") is not True:
                failures.append("held machine draft lacks final-memory disclaimer")
            if not draft.get("task_id"):
                failures.append("held machine draft lacks review task link")
        unsafe_vector_truth = [
            item
            for item in vector_ready
            if item.get("truth_status") in {"system_inference", "model_generated"}
            or (item.get("boundary_snapshot") or {}).get("reviewed_by") != "adam"
        ]
        if unsafe_vector_truth:
            failures.append("reviewed vector-ready list contains unreviewed/system truth")
        if not gallery_items:
            failures.append("photo context pack should include gallery preview items")
        if dry_session.get("session_type") != "photo_context_review_session":
            failures.append("photo context review session dry-run has unexpected type")
        if dry_session.get("selection_policy") != "from_photo_context_review_session_plan":
            failures.append("photo context review session dry-run must consume the review-session plan")
        if len(str(dry_session.get("plan_content_sha256") or "")) != 64:
            failures.append("photo context review session dry-run lacks plan content hash")
        if not isinstance(dry_session.get("selected_item_keys"), list):
            failures.append("photo context review session dry-run lacks selected item keys")
        delta = dry_session.get("projected_task_delta") if isinstance(dry_session.get("projected_task_delta"), dict) else {}
        if delta.get("dry_run_does_not_mutate") is not True or int(delta.get("mutation_count", 99)) != 0:
            failures.append("photo context review session dry-run lacks no-mutation task delta")
        if dry_session.get("dry_run") is not True or int(dry_session.get("created_count", 99)) != 0:
            failures.append("photo context review session dry-run must not create tasks")
        session_items = dry_session.get("items") if isinstance(dry_session.get("items"), list) else []
        if not session_items:
            failures.append("photo context review session dry-run should select review items")
        if dry_session.get("selected_item_keys") != [
            item.get("plan_item_key") for item in session_items if isinstance(item, dict)
        ]:
            failures.append("photo context review session selected keys must match plan item keys")
        for item in session_items[:3]:
            if item.get("truth_status") != "no_claim" or item.get("not_memory_claim") is not True:
                failures.append("photo context review session item lacks no-claim boundary")
            query_origin = item.get("query_origin") if isinstance(item.get("query_origin"), dict) else {}
            if query_origin.get("query_is_context_prioritization_only") is not True:
                failures.append("photo context review session item lacks prioritization-only query provenance")
            if item.get("action_type") not in {
                "would_create_photo_context_task",
                "open_existing_photo_context_task",
            }:
                failures.append("photo context review session item lacks a safe review action")
        return Check(
            "Photo context review pack previews Adam work queue and vector-safe records",
            not failures,
            "; ".join(failures)
            if failures
            else "photo context pack exposes no-claim gaps, held machine drafts, and reviewed vector handoff preview",
            {
                "photo_count": manifest.get("photo_count"),
                "preview_ready_count": manifest.get("preview_ready_count"),
                "needs_context_group_count": manifest.get("needs_context_group_count"),
                "held_for_adam_review_count": manifest.get("held_for_adam_review_count"),
                "reviewed_vector_ready_count": manifest.get("reviewed_vector_ready_count"),
                "gallery_preview_item_count": manifest.get("gallery_preview_item_count"),
                "photo_context_worklist_count": manifest.get("photo_context_worklist_count"),
                "content_sha256": pack.get("content_sha256"),
                "sample_worklists": [worklist.get("worklist_key") for worklist in review_worklists[:5]],
                "sample_no_claim_titles": [group.get("display_title") for group in no_claim_groups[:3]],
                "sample_held_titles": [draft.get("source_photo_title") for draft in held_drafts[:3]],
                "dry_run_session": {
                    "selected_count": dry_session.get("selected_count"),
                    "created_count": dry_session.get("created_count"),
                    "existing_count": dry_session.get("existing_count"),
                    "review_policy": dry_session.get("review_policy"),
                },
                "session_progress": {
                    "total_context_task_count": progress.get("total_context_task_count"),
                    "draft_count": progress.get("draft_count"),
                    "submit_ready_count": progress.get("submit_ready_count"),
                    "status_counts": progress.get("status_counts"),
                    "blocked_reason_counts": progress.get("blocked_reason_counts"),
                    "retrieval_gap_task_count": progress.get("retrieval_gap_task_count"),
                    "retrieval_gap_missing_field_counts": progress.get("retrieval_gap_missing_field_counts"),
                    "completion_signal": progress.get("completion_signal"),
                    "content_sha256": progress.get("content_sha256"),
                },
                "retrieval_field_worklist": {
                    "reported_item_count": field_worklist.get("reported_item_count"),
                    "missing_field_total": field_worklist.get("missing_field_total"),
                    "content_sha256": field_worklist.get("content_sha256"),
                    "export_preview_sha256": field_worklist.get("export_preview_sha256"),
                },
                "retrieval_payoff_preview": {
                    "reported_item_count": payoff_preview.get("reported_item_count"),
                    "unlockable_vector_record_count": payoff_preview.get("unlockable_vector_record_count"),
                    "content_sha256": payoff_preview.get("content_sha256"),
                    "source_worklist_content_sha256": payoff_preview.get("source_worklist_content_sha256"),
                },
            },
        )

    checks.append(
        safe_check(
            "Photo context review pack previews Adam work queue and vector-safe records",
            photo_context_review_pack_readiness,
        )
    )

    def photo_context_top_slice_readiness() -> Check:
        top_slice = get_json(
            args.api_base,
            "/assets/photo-context-review-pack/top-context-slice",
            {"scope": "family_private", "limit": 5},
            timeout=30,
        )
        items = top_slice.get("items") if isinstance(top_slice.get("items"), list) else []
        failures = []
        if top_slice.get("slice_type") != "photo_context_top_slice":
            failures.append("unexpected photo context top slice type")
        if top_slice.get("review_policy") != "top_photo_context_slice_no_memory_claim":
            failures.append("photo context top slice lacks no-claim review policy")
        if top_slice.get("does_not_create_memory_claim") is not True:
            failures.append("photo context top slice must not create memory claims")
        if top_slice.get("requires_adam_context") is not True:
            failures.append("photo context top slice must require Adam context")
        if top_slice.get("worklist_key") != "photo_context:no_claim_needs_context":
            failures.append("photo context top slice should expose no-claim context worklist first")
        if int(top_slice.get("candidate_count") or 0) < len(items):
            failures.append("photo context top slice candidate count is smaller than reported items")
        if int(top_slice.get("reported_candidate_count") or 0) != len(items):
            failures.append("photo context top slice reported count does not match items")
        if top_slice.get("completion_signal") != "needs_context_group_count_decreases_or_review_task_becomes_submit_ready":
            failures.append("photo context top slice lacks completion signal")
        if len(str(top_slice.get("content_sha256") or "")) != 64:
            failures.append("photo context top slice lacks stable content hash")
        if not any("no_claim" in str(boundary) for boundary in (top_slice.get("safety_boundaries") or [])):
            failures.append("photo context top slice lacks no_claim safety boundary")
        if items:
            first = items[0]
            action = first.get("action") if isinstance(first.get("action"), dict) else {}
            fields = first.get("suggested_context_fields") if isinstance(first.get("suggested_context_fields"), list) else []
            if first.get("truth_status") != "no_claim" or first.get("not_memory_claim") is not True:
                failures.append("photo context top item lacks no-claim truth boundary")
            if not first.get("source_photo_id") or not first.get("preview_url") or not first.get("thumbnail_url"):
                failures.append("photo context top item lacks previewable photo links")
            for required_field in ["visible_facts", "invisible_context", "meaning", "uncertainty"]:
                if required_field not in fields:
                    failures.append(f"photo context top item lacks suggested field {required_field}")
            if action.get("action_type") not in {"create_photo_context_task", "open_existing_photo_context_task"}:
                failures.append("photo context top item lacks context task action")
            criteria = first.get("completion_criteria") if isinstance(first.get("completion_criteria"), list) else []
            if not any("Adam-authored" in str(item) for item in criteria):
                failures.append("photo context top item lacks Adam-authored completion criterion")
        else:
            failures.append("photo context top slice has no items while live no-claim queue should have groups")
        return Check(
            "Photo context top slice is inspectable",
            not failures,
            "; ".join(failures)
            if failures
            else "top photo context slice exposes preview URLs, no-claim policy, suggested fields, and completion criteria",
            {
                "worklist_key": top_slice.get("worklist_key"),
                "candidate_count": top_slice.get("candidate_count"),
                "reported_candidate_count": top_slice.get("reported_candidate_count"),
                "content_sha256": top_slice.get("content_sha256"),
                "sample_titles": [item.get("display_title") for item in items[:5] if isinstance(item, dict)],
            },
        )

    checks.append(
        safe_check(
            "Photo context top slice is inspectable",
            photo_context_top_slice_readiness,
        )
    )

    def photo_context_review_session_plan_readiness() -> Check:
        source_query = args.honest_gap_query
        plan = get_json(
            args.api_base,
            "/assets/photo-context-review-pack/review-session-plan",
            {"scope": "family_private", "limit": 5, "source_query": source_query},
            timeout=30,
        )
        items = plan.get("items") if isinstance(plan.get("items"), list) else []
        field_plan = plan.get("field_plan") if isinstance(plan.get("field_plan"), list) else []
        field_names = {field.get("field") for field in field_plan if isinstance(field, dict)}
        failures = []
        if plan.get("plan_type") != "photo_context_review_session_plan":
            failures.append("unexpected photo context review session plan type")
        if plan.get("review_policy") != "query_aware_photo_context_session_plan_no_mutation":
            failures.append("photo context session plan lacks query-aware no-mutation policy")
        if plan.get("does_not_mutate_state") is not True:
            failures.append("photo context session plan must be non-mutating")
        if plan.get("does_not_create_memory_claim") is not True:
            failures.append("photo context session plan must not create memory claims")
        if plan.get("requires_adam_context") is not True:
            failures.append("photo context session plan must require Adam context")
        if plan.get("source_query") != source_query:
            failures.append("photo context session plan lost the source query")
        if int(plan.get("selected_count") or 0) != len(items):
            failures.append("photo context session plan selected count does not match items")
        if int(plan.get("candidate_count") or 0) < len(items):
            failures.append("photo context session plan candidate count is smaller than items")
        if len(str(plan.get("content_sha256") or "")) != 64:
            failures.append("photo context session plan lacks stable content hash")
        if not str(plan.get("export_preview_yaml") or "").startswith("photo_context_review_session_plan:"):
            failures.append("photo context session plan lacks YAML export preview")
        if len(str(plan.get("export_preview_sha256") or "")) != 64:
            failures.append("photo context session plan lacks YAML export hash")
        if not any("prioritization" in str(boundary).lower() for boundary in (plan.get("safety_boundaries") or [])):
            failures.append("photo context session plan must state that query context is prioritization only")
        for required_field in ["visible_facts", "invisible_context", "meaning", "uncertainty"]:
            if required_field not in field_names:
                failures.append(f"photo context session plan field plan lacks {required_field}")
        if items:
            first = items[0]
            query_origin = first.get("query_origin") if isinstance(first.get("query_origin"), dict) else {}
            action = first.get("action") if isinstance(first.get("action"), dict) else {}
            action_request = action.get("request") if isinstance(action.get("request"), dict) else {}
            action_body = action_request.get("body") if isinstance(action_request.get("body"), dict) else {}
            query_provenance = action.get("query_provenance") if isinstance(action.get("query_provenance"), dict) else {}
            criteria = first.get("completion_criteria") if isinstance(first.get("completion_criteria"), list) else []
            if first.get("truth_status") != "no_claim" or first.get("not_memory_claim") is not True:
                failures.append("photo context session item lacks no-claim boundary")
            if query_origin.get("source_query") != source_query:
                failures.append("photo context session item lacks query origin")
            if query_origin.get("query_is_context_prioritization_only") is not True:
                failures.append("photo context session item does not mark query as prioritization-only")
            if action.get("action_type") not in {"create_photo_context_task", "open_existing_photo_context_task"}:
                failures.append("photo context session item lacks create/open context action")
            if query_provenance.get("source_query") != source_query:
                failures.append("photo context session action lacks source-query provenance")
            if query_provenance.get("query_is_context_prioritization_only") is not True:
                failures.append("photo context session action must mark query as prioritization-only")
            if query_provenance.get("not_memory_claim") is not True:
                failures.append("photo context session action must remain not-memory-claim")
            if query_provenance.get("candidate_match_quality") != "backlog_only":
                failures.append("photo context session action must distinguish backlog selection from visual evidence")
            if query_provenance.get("candidate_selection_reason") != "selected_from_photo_context_review_session_plan":
                failures.append("photo context session action lacks candidate selection reason")
            if action.get("action_type") == "create_photo_context_task":
                if action_body.get("source_query") != source_query:
                    failures.append("photo context create action body does not preserve source query")
                if action_body.get("query_is_context_prioritization_only") is not True:
                    failures.append("photo context create action body must mark query as prioritization-only")
                if action_body.get("not_memory_claim") is not True:
                    failures.append("photo context create action body must remain not-memory-claim")
                if action_body.get("candidate_match_quality") != "backlog_only":
                    failures.append("photo context create action body must distinguish backlog selection from visual evidence")
                if action_body.get("candidate_selection_reason") != "selected_from_photo_context_review_session_plan":
                    failures.append("photo context create action body lacks candidate selection reason")
            if not any("Adam-authored" in str(item) for item in criteria):
                failures.append("photo context session item lacks Adam-authored completion criterion")
        else:
            failures.append("photo context session plan has no items while live no-claim queue should have groups")
        return Check(
            "Photo context review session plan is no-claim and actionable",
            not failures,
            "; ".join(failures)
            if failures
            else "session plan preserves query as prioritization context and points each no-claim group to Adam-authored context work",
            {
                "source_query": plan.get("source_query"),
                "selected_count": plan.get("selected_count"),
                "candidate_count": plan.get("candidate_count"),
                "content_sha256": plan.get("content_sha256"),
                "export_preview_sha256": plan.get("export_preview_sha256"),
                "action_counts": plan.get("dry_run_action_counts"),
                "sample_titles": [item.get("display_title") for item in items[:5] if isinstance(item, dict)],
            },
        )

    checks.append(
        safe_check(
            "Photo context review session plan is no-claim and actionable",
            photo_context_review_session_plan_readiness,
        )
    )

    def gallery_preview_readiness() -> Check:
        gallery = get_json(
            args.api_base,
            "/gallery/reviewed-photos",
            {"scope": "family_private", "include_drafts": "true", "limit": 8},
        )
        items = gallery.get("items") if isinstance(gallery.get("items"), list) else []
        failures = []
        if gallery.get("gallery_type") != "reviewed_photo_gallery":
            failures.append("unexpected gallery response type")
        if gallery.get("review_policy") != "reviewed_only_by_default":
            failures.append("gallery must default to reviewed-only policy")
        if not items:
            failures.append("gallery preview should expose at least one draft/reviewed item")
        for item in items[:5]:
            if not item.get("source_photo_id"):
                failures.append("gallery item lacks source photo id")
            if not item.get("thumbnail_url") or not item.get("preview_url"):
                failures.append("gallery item lacks preview URLs")
            if "requires_adam_review" not in item:
                failures.append("gallery item lacks Adam-review status")
            if item.get("requires_adam_review") and not item.get("review_task_id"):
                failures.append("draft gallery item lacks review task link")
            if not isinstance(item.get("boundary_snapshot"), dict):
                failures.append("gallery item lacks boundary snapshot")
        return Check(
            "Gallery preview is boundary-aware and review-labeled",
            not failures,
            "; ".join(failures) if failures else "gallery preview exposes photo items with boundary and review labels",
            {
                "item_count": gallery.get("item_count"),
                "reviewed_item_count": gallery.get("reviewed_item_count"),
                "draft_item_count": gallery.get("draft_item_count"),
                "hidden_draft_count": gallery.get("hidden_draft_count"),
                "sample_titles": [item.get("title") for item in items[:3]],
                "draft_review_task_count": len(
                    [item for item in items if item.get("requires_adam_review") and item.get("review_task_id")]
                ),
            },
        )

    checks.append(safe_check("Gallery preview is boundary-aware and review-labeled", gallery_preview_readiness))

    checks.append(
        safe_check(
            "Gallery endpoint defaults to reviewed photos and can preview drafts",
            lambda: command_check(
                "Gallery endpoint defaults to reviewed photos and can preview drafts",
                [
                    "docker",
                    "compose",
                    "exec",
                    "-T",
                    "api",
                    "pytest",
                    "-q",
                    "tests/test_ralph_phase2_photo_spine.py::test_gallery_review_endpoint_defaults_to_reviewed_and_can_preview_drafts",
                ],
            ),
        )
    )

    checks.append(
        safe_check(
            "Photo inventory context tasks promote Adam answers",
            lambda: command_check(
                "Photo inventory context tasks promote Adam answers",
                [
                    "docker",
                    "compose",
                    "exec",
                    "-T",
                    "api",
                    "pytest",
                    "-q",
                    "tests/test_ralph_phase2_photo_spine.py::test_photo_review_inventory_groups_copy_variants_and_counts_context_gap",
                    "tests/test_ralph_phase2_photo_spine.py::test_photo_context_task_created_from_retrieval_gap_preserves_query_origin",
                    "tests/test_ralph_phase2_photo_spine.py::test_photo_context_question_answers_become_searchable_memory_and_embedding_text",
                ],
            ),
        )
    )

    checks.append(
        safe_check(
            "Photo context submit projection and receipts are auditable",
            lambda: command_check(
                "Photo context submit projection and receipts are auditable",
                [
                    "docker",
                    "compose",
                    "exec",
                    "-T",
                    "api",
                    "pytest",
                    "-q",
                    "tests/test_ralph_phase2_photo_spine.py::test_photo_context_submit_projection_is_non_mutating_and_matches_downstream_readiness",
                    "tests/test_ralph_phase2_photo_spine.py::test_photo_context_submit_receipt_carries_projection_hash_and_payload_preview",
                    "tests/test_ralph_phase2_photo_spine.py::test_photo_context_submit_projection_reports_boundary_and_context_holds_without_mutation",
                ],
            ),
        )
    )

    checks.append(
        safe_check(
            "Photo context session progress summarizes drafts and blockers",
            lambda: command_check(
                "Photo context session progress summarizes drafts and blockers",
                [
                    "docker",
                    "compose",
                    "exec",
                    "-T",
                    "api",
                    "pytest",
                    "-q",
                    "tests/test_ralph_phase2_photo_spine.py::test_photo_context_session_progress_summarizes_drafts_and_projection_blockers_without_mutation",
                ],
            ),
        )
    )

    def photo_memory_readiness() -> Check:
        profiles = get_json(args.api_base, "/metadata-profiles")
        memories = get_json(args.api_base, "/memories")
        photo_profiles = [
            profile
            for profile in profiles
            if profile.get("target_type") == "asset"
            and str(profile.get("profile_type") or "").startswith("photo")
        ]
        photo_memories = [
            memory
            for memory in memories
            if "photo" in json.dumps(memory, sort_keys=True).lower()
            or "asset" in json.dumps(memory, sort_keys=True).lower()
        ]
        failures = []
        if len(photo_profiles) < args.min_photo_profiles:
            failures.append(f"needs {args.min_photo_profiles} reviewed photo profiles, found {len(photo_profiles)}")
        if len(photo_memories) < args.min_photo_memories:
            failures.append(f"needs {args.min_photo_memories} photo-linked memories, found {len(photo_memories)}")
        return Check(
            "Reviewed photos have memory/profile records",
            not failures,
            "; ".join(failures) if failures else "photo profiles and memories meet milestone threshold",
            {
                "metadata_profile_count": len(profiles),
                "photo_profile_count": len(photo_profiles),
                "memory_count": len(memories),
                "photo_memory_count": len(photo_memories),
            },
        )

    checks.append(safe_check("Reviewed photos have memory/profile records", photo_memory_readiness))

    def photo_review_task_readiness() -> Check:
        tasks = get_json(args.api_base, "/tasks")
        photo_tasks = [
            task
            for task in tasks
            if task.get("status") == "ready"
            and task.get("task_type") == "vision_draft_review"
            and (task.get("input_payload") or {}).get("source_photo_memory_draft") is True
        ]
        failures = []
        if len(photo_tasks) < args.min_photo_review_tasks:
            failures.append(
                f"needs {args.min_photo_review_tasks} ready photo-memory review tasks, found {len(photo_tasks)}"
            )
        missing_preview_links = [
            task.get("human_id")
            for task in photo_tasks
            if not (task.get("input_payload") or {}).get("asset_id")
        ]
        if missing_preview_links:
            failures.append("some photo-memory review tasks do not point back to an asset preview")
        return Check(
            "Photo memory drafts are reviewable tasks",
            not failures,
            "; ".join(failures) if failures else "machine photo-memory drafts have ready human-review tickets",
            {
                "review_task_count": len(photo_tasks),
                "sample_titles": [
                    (task.get("input_payload") or {}).get("asset_title")
                    for task in photo_tasks[:5]
                ],
            },
        )

    checks.append(safe_check("Photo memory drafts are reviewable tasks", photo_review_task_readiness))

    def photo_priority_summary_readiness() -> Check:
        summary = get_json(args.api_base, "/assets/photo-review-priority", {"focus": "fastest_vector", "limit": 10})
        items = summary.get("items") if isinstance(summary.get("items"), list) else []
        failures = []
        if summary.get("summary_type") != "photo_review_priority":
            failures.append("unexpected photo priority summary type")
        if summary.get("review_policy") != "prioritization_only_no_memory_claim_until_submit":
            failures.append("photo priority summary lacks no-claim review policy")
        if summary.get("throughput_policy") != "rank_by_fastest_review_path_then_missing_adam_fields_then_downstream_payoff":
            failures.append("photo priority summary lacks throughput ranking policy")
        if summary.get("does_not_mutate_state") is not True:
            failures.append("photo priority summary must be non-mutating")
        if summary.get("does_not_create_memory_claim") is not True:
            failures.append("photo priority summary must not create memory claims")
        if summary.get("no_live_model_call") is not True:
            failures.append("photo priority summary must not call live models")
        if summary.get("no_live_embedding_call") is not True:
            failures.append("photo priority summary must not call live embeddings")
        if not summary.get("completion_signal"):
            failures.append("photo priority summary lacks completion signal")
        if not summary.get("content_sha256"):
            failures.append("photo priority summary lacks stable content hash")
        if "photo_review_priority:" not in str(summary.get("export_preview_yaml") or ""):
            failures.append("photo priority summary lacks YAML export preview")
        if not summary.get("export_preview_sha256"):
            failures.append("photo priority summary lacks YAML export hash")
        if int(summary.get("reported_count") or 0) <= 0:
            failures.append("photo priority summary has no reported review tasks")
        ranks = [int(item.get("rank", 99)) for item in items if isinstance(item, dict)]
        if ranks != sorted(ranks):
            failures.append("photo priority items are not rank sorted")
        if not any(item.get("path_label") == "Fastest vector path" for item in items if isinstance(item, dict)):
            failures.append("photo priority summary lacks fastest vector path item")
        for item in items[:5]:
            if not isinstance(item, dict):
                continue
            if item.get("not_memory_claim") is not True:
                failures.append(f"{item.get('task_human_id')} lacks no-memory-claim flag")
            if item.get("preview_ready") is not True:
                failures.append(f"{item.get('task_human_id')} lacks preview-ready ranking input")
            if int(item.get("missing_adam_field_count") or 0) <= 0:
                failures.append(f"{item.get('task_human_id')} lacks missing Adam field count")
            if int(item.get("downstream_payoff_score") or 0) <= 0:
                failures.append(f"{item.get('task_human_id')} lacks downstream payoff score")
            ranking_inputs = item.get("ranking_inputs") if isinstance(item.get("ranking_inputs"), dict) else {}
            for required_input in ["path_rank", "preview_ready", "missing_adam_field_count", "downstream_payoff_score"]:
                if required_input not in ranking_inputs:
                    failures.append(f"{item.get('task_human_id')} lacks ranking input {required_input}")
            if "No memory claim yet" not in (item.get("safeguards") or []):
                failures.append(f"{item.get('task_human_id')} lacks no-memory-claim safeguard")
            if not item.get("missing_fields"):
                failures.append(f"{item.get('task_human_id')} lacks missing field explanation")
            if not item.get("truth_status_before_review"):
                failures.append(f"{item.get('task_human_id')} lacks truth status before review")
            if not item.get("source_photo_id") or not item.get("source_photo_title"):
                failures.append(f"{item.get('task_human_id')} lacks source photo identity")
        return Check(
            "Photo priority summary is no-claim and actionable",
            not failures,
            "; ".join(failures)
            if failures
            else "photo priority summary ranks fastest review work with missing fields and no-claim safeguards",
            {
                "reported_count": summary.get("reported_count"),
                "total_candidate_count": summary.get("total_candidate_count"),
                "sample_paths": [item.get("path_label") for item in items[:5] if isinstance(item, dict)],
                "sample_tasks": [item.get("task_human_id") for item in items[:5] if isinstance(item, dict)],
                "content_sha256": summary.get("content_sha256"),
            },
        )

    checks.append(safe_check("Photo priority summary is no-claim and actionable", photo_priority_summary_readiness))

    checks.append(
        safe_check(
            "Photo priority summary orders review work without memory claims",
            lambda: command_check(
                "Photo priority summary orders review work without memory claims",
                [
                    "docker",
                    "compose",
                    "exec",
                    "-T",
                    "api",
                    "pytest",
                    "-q",
                    "tests/test_ralph_phase2_photo_spine.py::test_photo_review_priority_summary_orders_fastest_paths_and_preserves_no_claim_policy",
                ],
            ),
        )
    )

    checks.append(
        safe_check(
            "Photo memory draft generation is idempotent and review-safe",
            lambda: command_check(
                "Photo memory draft generation is idempotent and review-safe",
                [
                    "docker",
                    "compose",
                    "exec",
                    "-T",
                    "api",
                    "pytest",
                    "-q",
                    "tests/test_ralph_phase2_photo_spine.py::test_machine_photo_memory_drafts_create_profiles_memories_embeddings_and_retrieval",
                    "tests/test_ralph_phase2_photo_spine.py::test_machine_photo_memory_review_promotes_adam_context_over_system_inference",
                    "tests/test_ralph_phase2_photo_spine.py::test_sealed_photo_review_receipt_reports_boundary_exclusion_from_vector_handoff",
                    "tests/test_ralph_phase2_photo_spine.py::test_machine_photo_memory_drafts_do_not_overwrite_adam_reviewed_photo_profiles",
                    "tests/test_ralph_phase2_photo_spine.py::test_photo_memory_prompt_pair_candidates_link_photo_profile_boundary_and_embedding_text",
                    "tests/test_ralph_phase2_photo_spine.py::test_reviewed_photo_memory_demo_readiness_is_truthful_before_and_after_adam_review",
                ],
            ),
        )
    )

    def photo_prompt_pair_readiness() -> Check:
        tasks = get_json(args.api_base, "/tasks")
        photo_pair_tasks = [
            task
            for task in tasks
            if task.get("status") == "ready"
            and task.get("task_type") == "gold_voice_edit"
            and (task.get("input_payload") or {}).get("source_photo_profile_id")
        ]
        failures = []
        if len(photo_pair_tasks) < args.min_photo_prompt_pair_candidates:
            failures.append(
                f"needs {args.min_photo_prompt_pair_candidates} photo-grounded Prompt Pair tickets, found {len(photo_pair_tasks)}"
            )
        for task in photo_pair_tasks[: args.min_photo_prompt_pair_candidates]:
            payload = task.get("input_payload") or {}
            prompt = str(payload.get("prompt") or "")
            if not payload.get("source_photo_id") or not payload.get("source_photo_profile_id"):
                failures.append(f"{task.get('human_id')} lacks source photo/profile provenance")
            if not payload.get("boundary_snapshot"):
                failures.append(f"{task.get('human_id')} lacks boundary snapshot")
            if not payload.get("embedding_input_text"):
                failures.append(f"{task.get('human_id')} lacks embedding input text")
            if payload.get("truth_status") == "archival_source":
                failures.append(f"{task.get('human_id')} incorrectly uses archival_source truth")
            if prompt.lower().endswith((".jpg", ".jpg.", ".jpeg", ".jpeg.", ".png", ".png.")):
                failures.append(f"{task.get('human_id')} uses filename fallback prompt")
            if prompt.lower().startswith("tell me about ") and "photo" not in prompt.lower():
                failures.append(f"{task.get('human_id')} prompt is too generic: {prompt}")
            retrieval_origin = payload.get("retrieval_gap_origin")
            if isinstance(retrieval_origin, dict) and retrieval_origin:
                if retrieval_origin.get("truth_status") != "no_claim":
                    failures.append(f"{task.get('human_id')} retrieval origin must carry no_claim truth")
                if retrieval_origin.get("not_memory_claim") is not True:
                    failures.append(f"{task.get('human_id')} retrieval origin must be marked not_memory_claim")
        return Check(
            "Photo memory records create grounded Prompt Pair tickets",
            not failures,
            "; ".join(failures) if failures else "photo memories produce review-gated prompt-pair candidates with provenance",
            {
                "photo_prompt_pair_count": len(photo_pair_tasks),
                "sample_prompts": [
                    {
                        "human_id": task.get("human_id"),
                        "prompt": (task.get("input_payload") or {}).get("prompt"),
                        "truth_status": (task.get("input_payload") or {}).get("truth_status"),
                        "source_photo_id": (task.get("input_payload") or {}).get("source_photo_id"),
                    }
                    for task in photo_pair_tasks[:5]
                ],
            },
        )

    checks.append(
        safe_check(
            "Photo memory records create grounded Prompt Pair tickets",
            photo_prompt_pair_readiness,
        )
    )

    def photo_embedding_corpus_readiness() -> Check:
        corpus = get_json(
            args.api_base,
            "/retrieval/photo-memory-corpus",
            {"scope": "family_private", "limit": args.min_photo_embedding_records},
        )
        records = corpus.get("records") if isinstance(corpus.get("records"), list) else []
        next_review_actions = (
            corpus.get("next_review_actions") if isinstance(corpus.get("next_review_actions"), list) else []
        )
        failures = []
        if corpus.get("corpus_type") != "photo_memory_embedding_text":
            failures.append("unexpected corpus type")
        if corpus.get("review_policy") != "reviewed_only_by_default":
            failures.append("photo-memory corpus must be reviewed-only by default")
        if corpus.get("include_machine_drafts") is not False:
            failures.append("photo-memory corpus default must not include machine drafts")
        if corpus.get("preview_only") is not False:
            failures.append("photo-memory corpus default must not be preview-only")
        if corpus.get("not_for_downstream_vector_store") is not False:
            failures.append("photo-memory corpus default must be allowed for downstream vector handoff when records exist")
        if int(corpus.get("record_count", 0)) < args.min_photo_embedding_records and int(corpus.get("excluded_count", 0)) <= 0:
            failures.append(
                "needs reviewed photo-memory embedding records or explicit machine-draft exclusions"
            )
        if int(corpus.get("record_count", 0)) == 0 and int(corpus.get("excluded_count", 0)) > 0:
            if not next_review_actions:
                failures.append("empty reviewed corpus must expose next_review_actions")
            if any(
                action.get("review_status") == "held_for_adam_review" and not action.get("review_task_id")
                for action in next_review_actions
            ):
                failures.append("held corpus review action lacks review_task_id")
        source_photo_ids = [
            record.get("source_photo_id")
            for record in records
            if record.get("source_photo_id")
        ]
        if len(source_photo_ids) != len(set(source_photo_ids)):
            failures.append("photo-memory corpus includes duplicate records for the same source photo")
        if any(not record.get("source_photo_id") for record in records):
            failures.append("some corpus records are not linked to source photos")
        if any(not record.get("input_text") for record in records):
            failures.append("some corpus records lack embedding input text")
        if any(not record.get("inclusion_reason") for record in records):
            failures.append("some corpus records lack inclusion reason")
        if any(not isinstance(record.get("inclusion_trace"), list) or not record.get("inclusion_trace") for record in records):
            failures.append("some corpus records lack inclusion trace")
        if any(record.get("target_type") != "memory" for record in records):
            failures.append("photo-memory corpus should hand off canonical memory records, not duplicate profile rows")
        if any(record.get("truth_status") in {"system_inference", "model_generated"} for record in records):
            failures.append("photo-memory corpus default includes unreviewed machine truth")
        for required_field in [
            "retrieval_origin_record_count",
            "retrieval_origin_no_claim_count",
            "next_review_actions",
        ]:
            if required_field not in corpus:
                failures.append(f"photo-memory corpus runtime contract missing {required_field}")
        retrieval_origin_records = [
            record
            for record in records
            if isinstance(record.get("retrieval_gap_origin"), dict) and record["retrieval_gap_origin"].get("query")
        ]
        if int(corpus.get("retrieval_origin_record_count") or 0) != len(retrieval_origin_records):
            failures.append("photo-memory corpus retrieval-origin count does not match records")
        if int(corpus.get("retrieval_origin_no_claim_count") or 0) != len(
            [
                record
                for record in retrieval_origin_records
                if record["retrieval_gap_origin"].get("truth_status") == "no_claim"
                and record["retrieval_gap_origin"].get("not_memory_claim") is True
            ]
        ):
            failures.append("photo-memory corpus no-claim retrieval-origin count does not match records")
        return Check(
            "Photo memory corpus is embedding-ready",
            not failures,
            "; ".join(failures) if failures else "photo-memory corpus exposes reviewed-only, boundary-filtered embedding inputs",
            {
                "corpus_type": corpus.get("corpus_type"),
                "record_count": corpus.get("record_count"),
                "excluded_count": corpus.get("excluded_count"),
                "review_policy": corpus.get("review_policy"),
                "retrieval_origin_record_count": corpus.get("retrieval_origin_record_count"),
                "retrieval_origin_no_claim_count": corpus.get("retrieval_origin_no_claim_count"),
                "next_review_action_count": len(next_review_actions),
                "sample_titles": [record.get("title") for record in records[:5]],
            },
        )

    checks.append(safe_check("Photo memory corpus is embedding-ready", photo_embedding_corpus_readiness))

    def photo_vector_handoff_readiness() -> Check:
        export = get_json(
            args.api_base,
            "/retrieval/photo-memory-corpus/export",
            {"scope": "family_private", "limit": args.min_photo_embedding_records},
        )
        repeat = get_json(
            args.api_base,
            "/retrieval/photo-memory-corpus/export",
            {"scope": "family_private", "limit": args.min_photo_embedding_records},
        )
        draft_preview = get_json(
            args.api_base,
            "/retrieval/photo-memory-corpus/export",
            {"scope": "family_private", "limit": args.min_photo_embedding_records, "include_machine_drafts": "true"},
        )
        manifest = export.get("manifest") if isinstance(export.get("manifest"), dict) else {}
        preview_manifest = draft_preview.get("manifest") if isinstance(draft_preview.get("manifest"), dict) else {}
        excluded = export.get("excluded") if isinstance(export.get("excluded"), list) else []
        next_review_actions = (
            manifest.get("next_review_actions") if isinstance(manifest.get("next_review_actions"), list) else []
        )
        jsonl = export.get("jsonl") if isinstance(export.get("jsonl"), str) else ""
        lines = [line for line in jsonl.splitlines() if line.strip()]
        parsed = []
        failures = []
        for line in lines:
            try:
                parsed.append(json.loads(line))
            except json.JSONDecodeError as exc:
                failures.append(f"invalid JSONL line: {exc}")
        if export != repeat:
            failures.append("vector handoff export is not stable across identical requests")
        if export.get("export_type") != "photo_memory_vector_handoff":
            failures.append("unexpected vector handoff export type")
        if export.get("format") != "jsonl":
            failures.append("vector handoff should be JSONL")
        if manifest.get("review_policy") != "reviewed_only_by_default":
            failures.append("vector handoff must be reviewed-only by default")
        for required_field in [
            "retrieval_origin_record_count",
            "retrieval_origin_no_claim_count",
            "next_review_actions",
        ]:
            if required_field not in manifest:
                failures.append(f"vector handoff manifest runtime contract missing {required_field}")
        if manifest.get("include_machine_drafts") is not False:
            failures.append("vector handoff default must not include machine drafts")
        if manifest.get("preview_only") is not False:
            failures.append("vector handoff default must not be preview-only")
        if manifest.get("not_for_downstream_vector_store") is not False:
            failures.append("vector handoff default must be downstream-eligible when records exist")
        if int(preview_manifest.get("record_count") or 0) > 0:
            if preview_manifest.get("include_machine_drafts") is not True:
                failures.append("machine-draft vector preview must declare include_machine_drafts=true")
            if preview_manifest.get("preview_only") is not True:
                failures.append("machine-draft vector preview must declare preview_only=true")
            if preview_manifest.get("not_for_downstream_vector_store") is not True:
                failures.append("machine-draft vector preview must not be marked production-vector-store ready")
            if int(preview_manifest.get("machine_draft_preview_record_count") or 0) != int(
                preview_manifest.get("record_count") or 0
            ):
                failures.append("machine-draft vector preview must count draft preview rows separately")
        if len(parsed) < args.min_photo_embedding_records and int(manifest.get("excluded_count") or 0) <= 0:
            failures.append("needs reviewed JSONL records or explicit machine-draft exclusions")
        if int(manifest.get("excluded_count") or 0) != len(excluded):
            failures.append("manifest excluded_count does not match excluded record list")
        if export.get("next_review_actions") != next_review_actions:
            failures.append("top-level next_review_actions must mirror manifest next_review_actions")
        if int(manifest.get("record_count") or 0) == 0 and int(manifest.get("excluded_count") or 0) > 0:
            if not next_review_actions:
                failures.append("empty vector handoff must expose next_review_actions")
            if any(
                action.get("review_status") == "held_for_adam_review" and not action.get("review_task_id")
                for action in next_review_actions
            ):
                failures.append("held vector review action lacks review_task_id")
        if int(manifest.get("reviewed_ready_count") or 0) != len(parsed):
            failures.append("manifest reviewed_ready_count does not match default JSONL reviewed records")
        retrieval_origin_records = [
            item
            for item in parsed
            if isinstance((item.get("metadata") or {}).get("retrieval_gap_origin"), dict)
            and ((item.get("metadata") or {}).get("retrieval_gap_origin") or {}).get("query")
        ]
        if int(manifest.get("retrieval_origin_record_count") or 0) != len(retrieval_origin_records):
            failures.append("manifest retrieval_origin_record_count does not match JSONL retrieval-origin records")
        if int(manifest.get("retrieval_origin_no_claim_count") or 0) != len(
            [
                item
                for item in retrieval_origin_records
                if ((item.get("metadata") or {}).get("retrieval_gap_origin") or {}).get("truth_status") == "no_claim"
                and ((item.get("metadata") or {}).get("retrieval_gap_origin") or {}).get("not_memory_claim") is True
            ]
        ):
            failures.append("manifest retrieval_origin_no_claim_count does not match no-claim retrieval-origin records")
        if int(manifest.get("held_for_adam_review_count") or 0) != len(
            [item for item in excluded if item.get("review_status") == "held_for_adam_review"]
        ):
            failures.append("manifest held_for_adam_review_count does not match held exclusions")
        if int(manifest.get("boundary_excluded_count") or 0) != len(
            [item for item in excluded if item.get("review_status") == "excluded_by_boundary"]
        ):
            failures.append("manifest boundary_excluded_count does not match boundary exclusions")
        for held in excluded[:5]:
            reasons = held.get("reasons") if isinstance(held.get("reasons"), list) else []
            if not held.get("source_photo_id") or not held.get("source_photo_title"):
                failures.append("held vector record lacks source photo identity")
            if not held.get("title"):
                failures.append("held vector record lacks memory/title label")
            if not reasons:
                failures.append("held vector record lacks exclusion reasons")
            if "requires_adam_review" in reasons:
                if held.get("review_status") != "held_for_adam_review":
                    failures.append("Adam-review hold lacks held_for_adam_review status")
                if held.get("review_queue") != "vision_drafts_needing_review":
                    failures.append("Adam-review hold lacks review queue")
                if not held.get("review_task_id") or not held.get("review_task_human_id"):
                    failures.append("Adam-review hold lacks exact review task reference")
                requirements = (
                    held.get("promotion_requirements")
                    if isinstance(held.get("promotion_requirements"), dict)
                    else {}
                )
                required_decisions = (
                    requirements.get("required_decisions")
                    if isinstance(requirements.get("required_decisions"), list)
                    else []
                )
                reviewed_requirements = (
                    requirements.get("reviewed_record_requirements")
                    if isinstance(requirements.get("reviewed_record_requirements"), dict)
                    else {}
                )
                for required_decision in ["adam_context_note", "question_answers", "privacy_level", "ready_for_downstream"]:
                    if required_decision not in required_decisions:
                        failures.append(f"Adam-review hold promotion requirements lack {required_decision}")
                if reviewed_requirements.get("metadata_source") != "photo_memory_review":
                    failures.append("Adam-review hold lacks reviewed metadata-source requirement")
                if reviewed_requirements.get("boundary_reviewed_by") != "adam":
                    failures.append("Adam-review hold lacks Adam boundary-review requirement")
                if not str(held.get("suggested_next_action") or "").startswith("Open the photo memory review task"):
                    failures.append("Adam-review hold lacks actionable next step")
                if held.get("truth_status") not in {"system_inference", "model_generated"}:
                    failures.append("Adam-review hold lacks machine truth status")
                if held.get("boundary_reviewed_by") != "system_draft":
                    failures.append("Adam-review hold lacks system_draft boundary provenance")
            if "boundary_not_allowed_for_scope" in reasons:
                if held.get("review_status") != "excluded_by_boundary":
                    failures.append("boundary hold lacks excluded_by_boundary status")
                if not str(held.get("suggested_next_action") or "").startswith("Adjust boundary clearance"):
                    failures.append("boundary hold lacks actionable next step")
        if manifest.get("record_count") != len(parsed):
            failures.append("manifest record_count does not match JSONL line count")
        if manifest.get("source_photo_count") != len(
            {((item.get("metadata") or {}).get("source_photo_id")) for item in parsed}
        ):
            failures.append("manifest source_photo_count does not match unique JSONL source photos")
        if manifest.get("content_sha256") != hashlib.sha256(jsonl.encode("utf-8")).hexdigest():
            failures.append("manifest content hash does not match JSONL")
        if manifest.get("vector_values_included") is not False or manifest.get("live_embedding_call") is not False:
            failures.append("vector handoff must not include vectors or live embedding calls in MVP")
        if (manifest.get("dedupe_policy_snapshot") or {}).get("one_record_per_source_photo") is not True:
            failures.append("vector handoff must declare one-record-per-source-photo dedupe policy")
        source_photo_ids = [
            (item.get("metadata") or {}).get("source_photo_id")
            for item in parsed
            if (item.get("metadata") or {}).get("source_photo_id")
        ]
        if len(source_photo_ids) != len(set(source_photo_ids)):
            failures.append("vector handoff JSONL includes duplicate source_photo_id records")
        for item in parsed[: args.min_photo_embedding_records]:
            metadata = item.get("metadata") or {}
            embedding_plan = item.get("embedding_plan") or {}
            text = str(item.get("text") or "")
            inclusion_trace = metadata.get("inclusion_trace")
            if not item.get("id", "").startswith("photo-memory:"):
                failures.append("JSONL record id does not use photo-memory namespace")
            if not text:
                failures.append("JSONL record lacks embedding text")
            if not item.get("inclusion_reason") or item.get("inclusion_reason") != metadata.get("inclusion_reason"):
                failures.append("JSONL record lacks mirrored inclusion reason")
            if not isinstance(inclusion_trace, list) or not inclusion_trace:
                failures.append("JSONL metadata lacks inclusion trace")
            elif "dedupe=one_record_per_source_photo" not in inclusion_trace:
                failures.append("JSONL inclusion trace lacks dedupe rationale")
            if "boundary_privacy_level:" not in text or "boundary_retrievable_in_chat:" not in text:
                failures.append("JSONL embedding text lacks compact boundary summary")
            if not metadata.get("source_photo_id"):
                failures.append("JSONL record lacks source_photo_id")
            if metadata.get("target_type") != "memory":
                failures.append("JSONL handoff should use canonical memory records")
            if not metadata.get("boundary_snapshot"):
                failures.append("JSONL record lacks boundary snapshot")
            if metadata.get("truth_status") in {"system_inference", "model_generated"}:
                failures.append("JSONL handoff includes unreviewed machine truth")
            if metadata.get("source") == "photo_memory_machine_draft":
                failures.append("JSONL handoff includes machine-draft photo memory")
            retrieval_origin = metadata.get("retrieval_gap_origin")
            if isinstance(retrieval_origin, dict) and retrieval_origin:
                if retrieval_origin.get("truth_status") != "no_claim":
                    failures.append("JSONL retrieval origin must carry no_claim truth")
                if retrieval_origin.get("not_memory_claim") is not True:
                    failures.append("JSONL retrieval origin must be marked not_memory_claim")
            if "vector" in item:
                failures.append("JSONL record includes inline vector values")
            if embedding_plan.get("live_embedding_call") is not False:
                failures.append("JSONL embedding plan does not explicitly disable live calls")
            if embedding_plan.get("vector_values_included") is not False:
                failures.append("JSONL embedding plan does not mark vector values absent")
        return Check(
            "Photo vector handoff export is stable and boundary-aware",
            not failures,
            "; ".join(failures) if failures else "photo-memory embedding JSONL handoff has manifest, provenance, and no inline vectors",
            {
                "record_count": manifest.get("record_count"),
                "excluded_count": manifest.get("excluded_count"),
                "content_sha256": manifest.get("content_sha256"),
                "draft_preview_record_count": preview_manifest.get("record_count"),
                "draft_preview_only": preview_manifest.get("preview_only"),
                "reviewed_ready_count": manifest.get("reviewed_ready_count"),
                "retrieval_origin_record_count": manifest.get("retrieval_origin_record_count"),
                "retrieval_origin_no_claim_count": manifest.get("retrieval_origin_no_claim_count"),
                "next_review_action_count": len(next_review_actions),
                "held_for_adam_review_count": manifest.get("held_for_adam_review_count"),
                "boundary_excluded_count": manifest.get("boundary_excluded_count"),
                "sample_ids": [item.get("id") for item in parsed[:3]],
                "sample_held": [
                    {
                        "source_photo_title": item.get("source_photo_title"),
                        "review_task_human_id": item.get("review_task_human_id"),
                        "review_status": item.get("review_status"),
                        "reasons": item.get("reasons"),
                    }
                    for item in excluded[:3]
                ],
            },
        )

    checks.append(
        safe_check(
            "Photo vector handoff export is stable and boundary-aware",
            photo_vector_handoff_readiness,
        )
    )

    def reviewed_photo_demo_readiness() -> Check:
        payload = get_json(
            args.api_base,
            "/retrieval/photo-memory-corpus/reviewed-demo-readiness",
            {"scope": "family_private", "limit": 5},
        )
        failures = []
        safety = payload.get("safety_policy") if isinstance(payload.get("safety_policy"), dict) else {}
        sample_records = (
            payload.get("sample_reviewed_records")
            if isinstance(payload.get("sample_reviewed_records"), list)
            else []
        )
        candidate_actions = (
            payload.get("candidate_actions") if isinstance(payload.get("candidate_actions"), list) else []
        )
        if payload.get("demo_type") != "reviewed_photo_memory_demo_readiness":
            failures.append("unexpected demo-readiness payload type")
        if safety.get("does_not_fabricate_adam_memory") is not True:
            failures.append("demo readiness must explicitly avoid fabricated Adam memory")
        if safety.get("does_not_mutate_state") is not True:
            failures.append("demo readiness endpoint must be read-only")
        if safety.get("no_live_embedding_call") is not True:
            failures.append("demo readiness endpoint must not call live embeddings")
        if safety.get("no_fine_tuning_api_call") is not True:
            failures.append("demo readiness endpoint must not call fine-tuning APIs")
        if payload.get("can_show_reviewed_vector_memory"):
            if payload.get("status") != "ready":
                failures.append("ready reviewed-photo demo should use status=ready")
            if int(payload.get("reviewed_vector_ready_count") or 0) <= 0:
                failures.append("ready reviewed-photo demo lacks reviewed-vector-ready count")
            if safety.get("outputs_truth_status") != "reviewed_photo_memory_records_only":
                failures.append("ready reviewed-photo demo lacks reviewed-output truth policy")
            if not sample_records:
                failures.append("ready reviewed-photo demo lacks sample reviewed records")
            for record in sample_records[:3]:
                if record.get("truth_status") in {"system_inference", "model_generated"}:
                    failures.append("reviewed-photo demo sample includes machine truth")
                if record.get("review_status") != "reviewed_vector_ready":
                    failures.append("reviewed-photo demo sample lacks reviewed_vector_ready status")
                if not record.get("inclusion_reason"):
                    failures.append("reviewed-photo demo sample lacks inclusion reason")
                trace = record.get("inclusion_trace") if isinstance(record.get("inclusion_trace"), list) else []
                if "dedupe=one_record_per_source_photo" not in trace:
                    failures.append("reviewed-photo demo sample lacks dedupe trace")
                if record.get("vector_values_included") is not False:
                    failures.append("reviewed-photo demo sample must not include vector values")
                if record.get("live_embedding_call") is not False:
                    failures.append("reviewed-photo demo sample must not use live embedding calls")
        else:
            if payload.get("status") != "needs_adam_review":
                failures.append("blocked reviewed-photo demo should use status=needs_adam_review")
            if "no_reviewed_vector_ready_photo_memory" not in (payload.get("blockers") or []):
                failures.append("blocked reviewed-photo demo lacks no-reviewed-memory blocker")
            if safety.get("outputs_truth_status") != "no_claim_until_adam_context_submission":
                failures.append("blocked reviewed-photo demo must use no-claim output truth policy")
            if sample_records:
                failures.append("blocked reviewed-photo demo should not expose reviewed sample records")
            if not candidate_actions:
                failures.append("blocked reviewed-photo demo lacks candidate review actions")
            for action in candidate_actions[:3]:
                if action.get("action_type") not in {
                    "open_photo_context_task",
                    "open_photo_memory_review_task",
                    "resolve_boundary_clearance",
                }:
                    failures.append(f"review action has unclear type: {action.get('action_type')}")
                if action.get("action_type") in {"open_photo_context_task", "open_photo_memory_review_task"}:
                    if not (action.get("task_id") or action.get("review_task_id")):
                        failures.append("open-review action lacks task id")
                if action.get("truth_status_before_review") == "no_claim" and action.get("not_memory_claim") is not True:
                    failures.append("no-claim review action must be marked not_memory_claim")
        return Check(
            "Reviewed photo-memory demo readiness is truthful",
            not failures,
            "; ".join(failures)
            if failures
            else "reviewed-photo demo is either ready with reviewed records or blocked with exact Adam-review actions",
            {
                "status": payload.get("status"),
                "reviewed_vector_ready_count": payload.get("reviewed_vector_ready_count"),
                "candidate_action_count": len(candidate_actions),
                "blockers": payload.get("blockers"),
                "sample_titles": [record.get("title") for record in sample_records[:3]],
            },
        )

    checks.append(safe_check("Reviewed photo-memory demo readiness is truthful", reviewed_photo_demo_readiness))

    def photo_retrieval_readiness() -> Check:
        query_results = []
        failures = []
        for query in args.required_retrieval_query:
            payload = get_json(
                args.api_base,
                "/retrieval/search",
                {"q": query, "scope": "family_private", "limit": 3},
            )
            results = payload.get("results") or []
            query_results.append(
                {
                    "query": query,
                    "result_count": len(results),
                    "top_result": results[0] if results else None,
                }
            )
            if not results:
                failures.append(f"query {query!r} returned no photo memory results")
            elif not results[0].get("source_photo_id"):
                failures.append(f"top result for {query!r} lacks source_photo_id")
            elif results[0].get("target_type") != "memory":
                failures.append(f"top result for {query!r} should be the canonical memory row")
            elif not isinstance(results[0].get("review_policy"), dict):
                failures.append(f"top result for {query!r} lacks review policy")
            else:
                policy = results[0].get("review_policy") or {}
                truth_status = results[0].get("truth_status")
                if truth_status in {"system_inference", "model_generated"} and policy.get("requires_adam_review") is not True:
                    failures.append(f"machine-generated top result for {query!r} must require Adam review")
                if policy.get("requires_adam_review") is True and policy.get("does_not_certify_final_memory") is not True:
                    failures.append(f"review-required top result for {query!r} must avoid final-memory certification")
                retrieval_origin = results[0].get("retrieval_gap_origin")
                if isinstance(retrieval_origin, dict) and retrieval_origin:
                    if retrieval_origin.get("truth_status") != "no_claim":
                        failures.append(f"retrieval origin for {query!r} must carry no_claim truth")
                    if retrieval_origin.get("not_memory_claim") is not True:
                        failures.append(f"retrieval origin for {query!r} must be marked not_memory_claim")
            source_photo_ids = [
                result.get("source_photo_id")
                for result in results
                if result.get("source_photo_id")
            ]
            if len(source_photo_ids) != len(set(source_photo_ids)):
                failures.append(f"query {query!r} returned duplicate source photos in top results")
            policy = payload.get("result_dedupe_policy") if isinstance(payload.get("result_dedupe_policy"), dict) else {}
            if policy.get("one_result_per_source_photo") is not True:
                failures.append(f"query {query!r} does not declare one-result-per-source-photo policy")
        return Check(
            "Photo semantic retrieval returns meaningful memory results",
            not failures,
            "; ".join(failures) if failures else "required photo-memory retrieval queries return linked results",
            {"queries": query_results},
        )

    checks.append(safe_check("Photo semantic retrieval returns meaningful memory results", photo_retrieval_readiness))

    def honest_photo_gap_readiness() -> Check:
        query = args.honest_gap_query
        payload = get_json(
            args.api_base,
            "/retrieval/search",
            {"q": query, "scope": "family_private", "limit": 3},
        )
        results = payload.get("results") or []
        failures = []
        if results:
            top = results[0]
            if not top.get("source_photo_id"):
                failures.append("resolved retrieval result lacks source_photo_id")
            if top.get("target_type") != "memory":
                failures.append("resolved retrieval result is not canonical memory row")
            policy = top.get("review_policy") if isinstance(top.get("review_policy"), dict) else {}
            if top.get("truth_status") in {"system_inference", "model_generated"} and policy.get("requires_adam_review") is not True:
                failures.append("machine-resolved result lacks Adam-review requirement")
        else:
            gap = payload.get("retrieval_gap") if isinstance(payload.get("retrieval_gap"), dict) else {}
            if gap.get("truth_status") != "no_claim":
                failures.append("no-result retrieval gap must use truth_status=no_claim")
            if gap.get("workflow") != "photo_context_review":
                failures.append("no-result retrieval gap must point to photo_context_review")
            if gap.get("next_queue") != "photo_assets_needing_context":
                failures.append("no-result retrieval gap must point to photo_assets_needing_context")
            if int(gap.get("photo_groups_needing_context_count") or 0) <= 0:
                failures.append("no-result retrieval gap lacks candidate photo groups")
            if not gap.get("sample_context_groups"):
                failures.append("no-result retrieval gap lacks sample context groups")
            if gap.get("candidate_group_selection_policy") != "reviewable_evidence_overlap_then_backlog_sample":
                failures.append("no-result retrieval gap lacks explicit candidate selection policy")
            if gap.get("sample_groups_are_not_memory_claims") is not True:
                failures.append("no-result retrieval gap must mark sample groups as non-memory claims")
            if "vision_drafts_needing_review" not in (gap.get("next_queues") or []):
                failures.append("no-result retrieval gap should expose draft-review queue as a possible next queue")
            candidate_count = int(gap.get("candidate_photo_group_count") or 0)
            weak_candidate_count = int(gap.get("weak_evidence_candidate_count") or 0)
            backlog_candidate_count = int(gap.get("backlog_only_candidate_count") or 0)
            if candidate_count != weak_candidate_count + backlog_candidate_count:
                failures.append("retrieval gap weak/backlog candidate counts do not sum to total candidate groups")
            if weak_candidate_count < 0 or backlog_candidate_count < 0:
                failures.append("retrieval gap weak/backlog candidate counts cannot be negative")
            sample_groups = gap.get("sample_context_groups") if isinstance(gap.get("sample_context_groups"), list) else []
            if sample_groups and sample_groups[0].get("candidate_media_kind") == "design_or_document_image":
                failures.append("top retrieval-gap backlog candidate is a design/document image instead of a photo-like asset")
            if sample_groups and weak_candidate_count > 0 and sample_groups[0].get("candidate_match_quality") != "weak_evidence_match":
                failures.append("retrieval gap reports weak evidence but does not rank weak-evidence samples first")
            for group in sample_groups[:5]:
                if not isinstance(group, dict):
                    failures.append("no-result retrieval gap includes a malformed sample group")
                    continue
                if group.get("candidate_media_kind") not in {
                    "photograph_like",
                    "design_or_document_image",
                    "image_asset_unknown_kind",
                }:
                    failures.append(f"sample group lacks explicit candidate media kind: {group.get('display_title')}")
                reason = group.get("selection_reason")
                if reason not in {"reviewable_evidence_overlap", "backlog_sample_no_semantic_match"}:
                    failures.append(f"sample group lacks explicit selection_reason: {group.get('display_title')}")
                if reason == "reviewable_evidence_overlap" and not group.get("matched_query_terms"):
                    failures.append(f"title-overlap sample lacks matched_query_terms: {group.get('display_title')}")
                if group.get("candidate_match_quality") not in {"weak_evidence_match", "backlog_only"}:
                    failures.append(f"sample group lacks explicit candidate_match_quality: {group.get('display_title')}")
                if group.get("candidate_match_quality") == "weak_evidence_match" and not group.get("matched_query_terms"):
                    failures.append(f"weak-evidence candidate lacks matched terms: {group.get('display_title')}")
                if group.get("candidate_match_quality") == "backlog_only" and group.get("matched_query_terms"):
                    failures.append(f"backlog-only candidate unexpectedly has matched terms: {group.get('display_title')}")
                evidence = group.get("candidate_evidence") if isinstance(group.get("candidate_evidence"), dict) else {}
                primary_action = group.get("primary_action") if isinstance(group.get("primary_action"), dict) else {}
                if primary_action.get("action_type") not in {
                    "create_photo_context_task",
                    "open_existing_photo_context_task",
                    "open_existing_draft_review_task",
                }:
                    failures.append(f"sample group lacks a concrete primary action: {group.get('display_title')}")
                if not primary_action.get("label") or not primary_action.get("queue"):
                    failures.append(f"sample group primary action lacks label/queue: {group.get('display_title')}")
                if primary_action.get("action_type") == "create_photo_context_task":
                    request = primary_action.get("request") if isinstance(primary_action.get("request"), dict) else {}
                    request_body = request.get("body") if isinstance(request.get("body"), dict) else {}
                    if request_body.get("source_query") != query:
                        failures.append(f"create-photo-context action lacks retrieval source query: {group.get('display_title')}")
                    if request_body.get("candidate_match_quality") != group.get("candidate_match_quality"):
                        failures.append(f"create-photo-context action lacks candidate match quality: {group.get('display_title')}")
                    if request_body.get("candidate_selection_reason") != group.get("selection_reason"):
                        failures.append(f"create-photo-context action lacks candidate selection reason: {group.get('display_title')}")
                if evidence.get("not_memory_claim") is not True:
                    failures.append(f"sample group candidate evidence must be marked non-memory: {group.get('display_title')}")
                if evidence.get("evidence_source") not in {"title_filename_only", "machine_photo_memory_draft"}:
                    failures.append(f"sample group candidate evidence lacks source type: {group.get('display_title')}")
                if evidence.get("candidate_media_kind") != group.get("candidate_media_kind"):
                    failures.append(f"sample group candidate media kind is inconsistent: {group.get('display_title')}")
                if not evidence.get("source_fields"):
                    failures.append(f"sample group candidate evidence lacks source fields: {group.get('display_title')}")
                if group.get("candidate_status") == "machine_draft_needs_adam_review":
                    if group.get("candidate_queue") != "vision_drafts_needing_review":
                        failures.append("machine draft gap candidate lacks draft-review queue")
                    if primary_action.get("action_type") != "open_existing_draft_review_task":
                        failures.append("machine draft gap candidate must open its existing draft-review task")
                    if not primary_action.get("task_id") or not primary_action.get("task_human_id"):
                        failures.append("machine draft gap candidate primary action lacks exact task reference")
                    if evidence.get("requires_adam_review") is not True:
                        failures.append("machine draft gap candidate lacks Adam-review requirement")
                    if evidence.get("does_not_certify_final_memory") is not True:
                        failures.append("machine draft gap candidate lacks final-memory disclaimer")
                    if evidence.get("truth_status") not in {"system_inference", "model_generated"}:
                        failures.append("machine draft gap candidate lacks machine-truth provenance")
                    if not str(evidence.get("suggested_next_action") or "").startswith("Open the existing photo memory draft review task"):
                        failures.append("machine draft gap candidate lacks actionable review-task next step")
                if group.get("candidate_status") == "needs_photo_context":
                    if group.get("candidate_queue") != "photo_assets_needing_context":
                        failures.append("unprofiled gap candidate lacks photo-context queue")
                    if primary_action.get("action_type") not in {
                        "create_photo_context_task",
                        "open_existing_photo_context_task",
                    }:
                        failures.append("unprofiled gap candidate must create/open a photo context task")
                    if evidence.get("truth_status") != "no_claim":
                        failures.append("unprofiled gap candidate must use truth_status=no_claim")
        return Check(
            "Photo retrieval no-claim gaps are honest and actionable",
            not failures,
            "; ".join(failures)
            if failures
            else "query either resolves to a reviewed/flagged memory or returns a no-claim photo-context gap",
            {
                "query": query,
                "result_count": len(results),
                "top_result": results[0] if results else None,
                "retrieval_gap": payload.get("retrieval_gap") if not results else None,
            },
        )

    checks.append(safe_check("Photo retrieval no-claim gaps are honest and actionable", honest_photo_gap_readiness))

    def retrieval_gap_review_slice_readiness() -> Check:
        query = args.honest_gap_query
        review_slice = get_json(
            args.api_base,
            "/retrieval/gap-review-slice",
            {"q": query, "scope": "family_private", "limit": 5},
            timeout=30,
        )
        items = review_slice.get("items") if isinstance(review_slice.get("items"), list) else []
        failures = []
        if review_slice.get("slice_type") != "retrieval_gap_review_slice":
            failures.append("unexpected retrieval gap slice type")
        if review_slice.get("query") != query:
            failures.append("retrieval gap slice does not preserve source query")
        if review_slice.get("gap_open") is not True:
            failures.append("honest-gap query should expose an open review slice")
        if review_slice.get("truth_status") != "no_claim":
            failures.append("retrieval gap slice must use no_claim truth status")
        if review_slice.get("review_policy") != "retrieval_gap_no_claim_until_adam_context":
            failures.append("retrieval gap slice lacks no-claim review policy")
        if review_slice.get("does_not_create_memory_claim") is not True:
            failures.append("retrieval gap slice must not create memory claims")
        if review_slice.get("requires_adam_context") is not True:
            failures.append("retrieval gap slice must require Adam context")
        if review_slice.get("workflow") != "photo_context_review":
            failures.append("retrieval gap slice should route to photo_context_review")
        if review_slice.get("candidate_group_selection_policy") != "reviewable_evidence_overlap_then_backlog_sample":
            failures.append("retrieval gap slice lacks selection policy")
        if int(review_slice.get("candidate_count") or 0) <= 0:
            failures.append("retrieval gap slice lacks candidate groups")
        if int(review_slice.get("reported_candidate_count") or 0) != len(items):
            failures.append("retrieval gap slice reported count does not match items")
        weak_count = int(review_slice.get("weak_evidence_candidate_count") or 0)
        backlog_count = int(review_slice.get("backlog_only_candidate_count") or 0)
        candidate_count = int(review_slice.get("candidate_count") or 0)
        if weak_count + backlog_count != candidate_count:
            failures.append("retrieval gap slice weak/backlog counts do not sum to candidate count")
        if review_slice.get("completion_signal") != "retrieval_query_returns_boundary_cleared_memory_or_context_task_submit_ready":
            failures.append("retrieval gap slice lacks completion signal")
        if len(str(review_slice.get("content_sha256") or "")) != 64:
            failures.append("retrieval gap slice lacks stable content hash")
        if not any("no_claim" in str(boundary) for boundary in (review_slice.get("safety_boundaries") or [])):
            failures.append("retrieval gap slice lacks no_claim safety boundary")
        if not items:
            failures.append("retrieval gap slice lacks review items")
        for item in items[:5]:
            if not isinstance(item, dict):
                failures.append("retrieval gap slice contains malformed item")
                continue
            if item.get("query") != query:
                failures.append("retrieval gap item does not preserve source query")
            if item.get("retrieval_gap_truth_status") != "no_claim":
                failures.append("retrieval gap item lacks no_claim retrieval provenance")
            if item.get("not_memory_claim") is not True:
                failures.append("retrieval gap item must be non-memory claim")
            if not item.get("source_photo_id") or not item.get("preview_url") or not item.get("thumbnail_url"):
                failures.append("retrieval gap item lacks previewable source photo")
            if item.get("candidate_match_quality") not in {"weak_evidence_match", "backlog_only"}:
                failures.append("retrieval gap item lacks match quality")
            if item.get("selection_reason") not in {"reviewable_evidence_overlap", "backlog_sample_no_semantic_match"}:
                failures.append("retrieval gap item lacks selection reason")
            evidence = item.get("candidate_evidence") if isinstance(item.get("candidate_evidence"), dict) else {}
            if evidence.get("not_memory_claim") is not True:
                failures.append("retrieval gap item candidate evidence must be non-memory")
            if evidence.get("evidence_source") not in {"title_filename_only", "machine_photo_memory_draft"}:
                failures.append("retrieval gap item candidate evidence lacks source type")
            action = item.get("action") if isinstance(item.get("action"), dict) else {}
            if action.get("action_type") not in {
                "create_photo_context_task",
                "open_existing_photo_context_task",
                "open_existing_draft_review_task",
            }:
                failures.append("retrieval gap item lacks concrete action")
            if action.get("action_type") == "create_photo_context_task":
                request = action.get("request") if isinstance(action.get("request"), dict) else {}
                body = request.get("body") if isinstance(request.get("body"), dict) else {}
                if body.get("source_query") != query:
                    failures.append("retrieval gap create action loses source query")
                if body.get("candidate_match_quality") != item.get("candidate_match_quality"):
                    failures.append("retrieval gap create action loses match quality")
            fields = item.get("suggested_context_fields") if isinstance(item.get("suggested_context_fields"), list) else []
            for field in ["visible_facts", "invisible_context", "meaning", "uncertainty"]:
                if field not in fields:
                    failures.append(f"retrieval gap item lacks suggested context field {field}")
            criteria = item.get("completion_criteria") if isinstance(item.get("completion_criteria"), list) else []
            if not any("Adam-authored context" in str(criterion) for criterion in criteria):
                failures.append("retrieval gap item lacks Adam-authored completion criterion")
        return Check(
            "Retrieval gap review slice is no-claim and actionable",
            not failures,
            "; ".join(failures)
            if failures
            else "retrieval-gap query has a first-class no-claim review slice with previews and query provenance",
            {
                "query": query,
                "candidate_count": review_slice.get("candidate_count"),
                "reported_candidate_count": review_slice.get("reported_candidate_count"),
                "weak_evidence_candidate_count": review_slice.get("weak_evidence_candidate_count"),
                "backlog_only_candidate_count": review_slice.get("backlog_only_candidate_count"),
                "content_sha256": review_slice.get("content_sha256"),
                "sample_titles": [item.get("display_title") for item in items[:5] if isinstance(item, dict)],
            },
        )

    checks.append(
        safe_check(
            "Retrieval gap review slice is no-claim and actionable",
            retrieval_gap_review_slice_readiness,
        )
    )
    return checks


def print_markdown(checks: list[Check]) -> None:
    failed = [check for check in checks if not check.passed]
    print("# Ralph Loop Live Acceptance Gate")
    print()
    print(f"Status: {'PASS' if not failed else 'FAIL'}")
    print()
    for check in checks:
        marker = "PASS" if check.passed else "FAIL"
        print(f"## {marker}: {check.name}")
        print()
        print(check.detail)
        if check.evidence:
            print()
            print("```json")
            print(json.dumps(check.evidence, indent=2, sort_keys=True))
            print("```")
        print()


def checkpoint_payload(checks: list[Check]) -> dict[str, Any]:
    failed = [check for check in checks if not check.passed]
    return {
        "checkpoint_type": "charlesops_ralph_loop_gate_checkpoint",
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "status": "pass" if not failed else "fail",
        "passed_count": len(checks) - len(failed),
        "failed_count": len(failed),
        "check_count": len(checks),
        "failed_checks": [
            {"name": check.name, "detail": check.detail, "evidence": check.evidence}
            for check in failed
        ],
        "checks": [check.__dict__ for check in checks],
    }


def checkpoint_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# CharlesOps Ralph Loop Gate Checkpoint",
        "",
        f"Generated: `{payload['generated_at']}`",
        f"Status: `{payload['status']}`",
        f"Checks: `{payload['passed_count']}` passed / `{payload['failed_count']}` failed / `{payload['check_count']}` total",
        "",
    ]
    failed_checks = payload.get("failed_checks") if isinstance(payload.get("failed_checks"), list) else []
    if failed_checks:
        lines.extend(["## Failed Checks", ""])
        for failure in failed_checks:
            lines.extend([f"### {failure.get('name')}", "", str(failure.get("detail") or ""), ""])
    lines.extend(["## Check Summary", ""])
    checks = payload.get("checks") if isinstance(payload.get("checks"), list) else []
    for check in checks:
        marker = "PASS" if check.get("passed") else "FAIL"
        lines.append(f"- `{marker}` {check.get('name')}: {check.get('detail')}")
    lines.append("")
    return "\n".join(lines).rstrip()


def write_checkpoint(checks: list[Check], checkpoint_dir: Path) -> dict[str, str]:
    checkpoint_dir.mkdir(parents=True, exist_ok=True)
    payload = checkpoint_payload(checks)
    stamp = payload["generated_at"].replace(":", "").replace("-", "").replace(".", "_")
    json_path = checkpoint_dir / f"ralph_loop_gate_checkpoint_{stamp}.json"
    markdown_path = checkpoint_dir / f"ralph_loop_gate_checkpoint_{stamp}.md"
    latest_json_path = checkpoint_dir / "ralph_loop_gate_checkpoint_latest.json"
    latest_markdown_path = checkpoint_dir / "ralph_loop_gate_checkpoint_latest.md"
    json_text = json.dumps(payload, indent=2, sort_keys=True)
    markdown_text = checkpoint_markdown(payload)
    for path, text in [
        (json_path, json_text),
        (latest_json_path, json_text),
        (markdown_path, markdown_text),
        (latest_markdown_path, markdown_text),
    ]:
        path.write_text(text + "\n", encoding="utf-8")
    return {
        "json_path": str(json_path),
        "markdown_path": str(markdown_path),
        "latest_json_path": str(latest_json_path),
        "latest_markdown_path": str(latest_markdown_path),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the CharlesOps Ralph-loop live acceptance gate.")
    parser.add_argument("--api-base", default="http://localhost:8000/api")
    parser.add_argument("--web-base", default="http://localhost:3003/")
    parser.add_argument("--min-prompt-pairs", type=int, default=200)
    parser.add_argument("--min-audit-samples", type=int, default=20)
    parser.add_argument("--min-voice-modes", type=int, default=4)
    parser.add_argument("--min-training-artifacts", type=int, default=200)
    parser.add_argument("--min-human-audit-pack-samples", type=int, default=200)
    parser.add_argument("--min-voice-reference-pack-samples", type=int, default=200)
    parser.add_argument("--required-text-model", default="gpt-5.5")
    parser.add_argument("--required-text-reasoning", default="xhigh")
    parser.add_argument("--min-demo-prompts", type=int, default=5)
    parser.add_argument("--min-mirrored-photos", type=int, default=80)
    parser.add_argument("--min-photo-profiles", type=int, default=5)
    parser.add_argument("--min-photo-memories", type=int, default=5)
    parser.add_argument("--min-photo-review-tasks", type=int, default=5)
    parser.add_argument("--min-photo-prompt-pair-candidates", type=int, default=3)
    parser.add_argument("--min-photo-embedding-records", type=int, default=5)
    parser.add_argument(
        "--required-photo-preview",
        action="append",
        default=["Rotmil 2021 I.jpg", "Rotmil Honors VIII.jpg"],
    )
    parser.add_argument(
        "--required-retrieval-query",
        action="append",
        default=["Japanese flute", "honors ceremony", "Adam flowers"],
    )
    parser.add_argument("--honest-gap-query", default="Old Orchard beach")
    parser.add_argument("--write-checkpoint", action="store_true", help="Write JSON and Markdown checkpoint artifacts.")
    parser.add_argument("--checkpoint-dir", default="updates", help="Directory for checkpoint artifacts.")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON instead of Markdown.")
    args = parser.parse_args()

    checks = run_gate(args)
    failed = [check for check in checks if not check.passed]
    checkpoint_paths: dict[str, str] | None = None
    if args.write_checkpoint:
        repo_root = Path(__file__).resolve().parents[1]
        checkpoint_paths = write_checkpoint(checks, repo_root / args.checkpoint_dir)
    if args.json:
        payload: Any = [check.__dict__ for check in checks]
        if checkpoint_paths:
            payload = {"checks": payload, "checkpoint_paths": checkpoint_paths}
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print_markdown(checks)
        if checkpoint_paths:
            print("## Checkpoint Artifacts")
            print()
            for label, path in checkpoint_paths.items():
                print(f"- `{label}`: `{path}`")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
