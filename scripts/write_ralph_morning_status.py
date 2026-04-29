#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
from urllib.request import urlopen


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "updates" / "ralph_loop_2026-04-29_morning_status.md"
LATEST_CHECKPOINT = ROOT / "updates" / "ralph_loop_gate_checkpoint_latest.json"
LATEST_CHECKPOINT_MD = ROOT / "updates" / "ralph_loop_gate_checkpoint_latest.md"
PHASE_REPORT = ROOT / "updates" / "ralph_loop_2026-04-29_phase_report.md"
VISUAL_CHECKPOINT = ROOT / "updates" / "exports_readiness_operator_handoff_2026-04-29.png"
API_BASE = "http://localhost:8000/api"


def fetch_json(path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    url = f"{API_BASE}{path}"
    if params:
        url = f"{url}?{urlencode(params)}"
    with urlopen(url, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def checkpoint_summary() -> dict[str, Any]:
    if not LATEST_CHECKPOINT.exists():
        return {"path": str(LATEST_CHECKPOINT.relative_to(ROOT)), "passed": 0, "total": 0}
    data = json.loads(LATEST_CHECKPOINT.read_text(encoding="utf-8"))
    checks = data.get("checks") if isinstance(data.get("checks"), list) else []
    passed = sum(1 for check in checks if isinstance(check, dict) and check.get("passed") is True)
    return {
        "path": str(LATEST_CHECKPOINT.relative_to(ROOT)),
        "markdown_path": str(LATEST_CHECKPOINT_MD.relative_to(ROOT)),
        "passed": passed,
        "total": len(checks),
        "checkpoint_paths": data.get("checkpoint_paths", {}),
        "generated_at": data.get("generated_at"),
    }


def write_status(output: Path) -> None:
    handoff = fetch_json(
        "/downstream-readiness/morning-handoff",
        {
            "scope": "family_private",
            "prompt_sample_limit": 200,
            "vector_limit": 20,
            "bottleneck_limit": 4,
            "retrieval_gap_query": "airplane in Maine",
        },
    )
    bottlenecks = fetch_json("/downstream-readiness/bottlenecks")
    prompt_audit = fetch_json("/prompt-pairs/audit?sample_limit=1")
    photo_pack = fetch_json("/assets/photo-context-review-pack")
    checkpoint = checkpoint_summary()

    handoff_markdown = str(handoff.get("report_markdown") or "").strip()
    bottleneck_items = bottlenecks.get("items") if isinstance(bottlenecks.get("items"), list) else []
    ordered_areas = bottlenecks.get("ordered_area_keys") if isinstance(bottlenecks.get("ordered_area_keys"), list) else []
    prompt_blockers = prompt_audit.get("preflight_blocker_counts") if isinstance(prompt_audit.get("preflight_blocker_counts"), dict) else {}
    readiness_counts = prompt_audit.get("preflight_gate_counts") if isinstance(prompt_audit.get("preflight_gate_counts"), dict) else {}
    photo_manifest = photo_pack.get("manifest") if isinstance(photo_pack.get("manifest"), dict) else {}
    artifact_summary = handoff.get("artifact_summary") if isinstance(handoff.get("artifact_summary"), dict) else {}
    model_status = handoff.get("model_generation_status") if isinstance(handoff.get("model_generation_status"), dict) else {}
    retrieval_gap = handoff.get("retrieval_gap_work") if isinstance(handoff.get("retrieval_gap_work"), dict) else {}

    lines = [
        "# Ralph Loop Morning Status",
        "",
        f"Generated: {datetime.now(timezone.utc).isoformat()}",
        f"Live handoff content SHA-256: `{handoff.get('content_sha256', 'missing')}`",
        "",
        "## Latest Gate",
        "",
        f"- Checkpoint: `{checkpoint['path']}`",
        f"- Checkpoint Markdown: `{checkpoint['markdown_path']}`",
            f"- Checkpoint generated: `{checkpoint.get('generated_at') or 'unknown'}`",
            f"- Checks passed: {checkpoint['passed']} / {checkpoint['total']}",
            f"- Phase report: `{PHASE_REPORT.relative_to(ROOT)}`",
            f"- Visual checkpoint: `{VISUAL_CHECKPOINT.relative_to(ROOT)}`" if VISUAL_CHECKPOINT.exists() else "- Visual checkpoint: `not captured yet`",
            "",
        "## Bottleneck Order",
        "",
    ]
    for index, area in enumerate(ordered_areas, start=1):
        item = next((candidate for candidate in bottleneck_items if isinstance(candidate, dict) and candidate.get("area_key") == area), {})
        action = item.get("action") if isinstance(item.get("action"), dict) else {}
        lines.append(
            f"{index}. {str(area).replace('_', ' ').title()}: {item.get('count', 0)} item(s), action `{action.get('action_type', 'unknown')}`"
        )

    lines.extend(
        [
            "",
            "## Live Product Handoff",
            "",
            handoff_markdown or "_No handoff markdown returned by the API._",
            "",
            "",
            "## Prompt Pairs",
            "",
            f"- Approved-ready: {readiness_counts.get('approved', 0)}",
            f"- Candidate/held: {readiness_counts.get('candidate', 0)}",
            f"- Inspectable pairs: {prompt_audit.get('inspectable_pair_count', 0)}",
            f"- DPO rejected reason gaps: {prompt_blockers.get('dpo_rejected_reason_empty', 0)}",
            f"- Source-boundary training blocks: {prompt_blockers.get('source_boundary_blocks_training', 0)}",
            "",
            "## Photo Context",
            "",
            f"- Total photos: {photo_manifest.get('photo_count', 0)}",
            f"- Preview-ready photos: {photo_manifest.get('preview_ready_count', 0)}",
            f"- Photo groups needing context: {photo_manifest.get('needs_context_group_count', 0)}",
            f"- Photo assets needing context: {photo_manifest.get('needs_context_count', 0)}",
            f"- Photo groups needing draft review: {photo_manifest.get('held_for_adam_review_count', 0)}",
            f"- Reviewed vector-ready photos: {photo_manifest.get('reviewed_vector_ready_count', 0)}",
            "",
            "## Retrieval Gap",
            "",
            f"- Query: {retrieval_gap.get('query', 'unknown')}",
            f"- Status: {retrieval_gap.get('status', 'unknown')} / {retrieval_gap.get('truth_status', 'unknown')}",
            f"- Candidate count: {retrieval_gap.get('candidate_count', 0)}",
            f"- Slice hash: `{retrieval_gap.get('content_sha256', 'missing')}`",
            "",
            "## Downstream Artifacts",
            "",
            f"- Artifact count: {artifact_summary.get('artifact_count', 0)}",
            f"- Hash mismatches: {artifact_summary.get('mismatch_count', 'unknown')}",
            f"- Manifest hash: `{artifact_summary.get('manifest_content_sha256', 'missing')}`",
            f"- Audit hash: `{artifact_summary.get('audit_content_sha256', 'missing')}`",
            "",
            "## Model Generation Gate",
            "",
            f"- Model: `{model_status.get('model_name', 'unknown')}`",
            f"- Reasoning effort: `{model_status.get('reasoning_effort', 'unknown')}`",
            f"- Can generate now: `{model_status.get('can_generate', False)}`",
            f"- Blockers: {', '.join(str(blocker) for blocker in (model_status.get('blockers') or [])) or 'none'}",
            f"- Output truth status: `{model_status.get('outputs_truth_status', 'model_generated')}`",
            f"- Fine-tuning API calls allowed: `{model_status.get('fine_tuning_api_calls_allowed', False)}`",
            "",
            "## Verification Commands",
            "",
            "```bash",
            "docker compose exec -T api pytest -q",
            "npm run typecheck --prefix apps/web",
            "npx --prefix apps/web playwright test --config apps/web/playwright.config.ts",
            "python3 scripts/ralph_loop_gate.py --write-checkpoint --json",
            "git diff --check",
            "```",
            "",
            "## Safety Notes",
            "",
            "- No fine-tuning APIs were called.",
            "- Raw source files were not mutated.",
            "- Photo retrieval gaps remain no-claim until Adam-authored context is submitted.",
            "- Candidate prompt pairs remain out of approved training export until blockers are resolved.",
        ]
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Write a compact Ralph-loop morning status handoff.")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    write_status(args.output)
    print(args.output)


if __name__ == "__main__":
    main()
