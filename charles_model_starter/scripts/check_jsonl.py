#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List


EMAIL_RE = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)
NAME_RE = re.compile(r"\b(?:Charles|Adam|Cathryn|Julia|Michele|Colette|Bernie|Agn[eè]s|Adrienne|Hunter|Noor)\b")


def _text(row: Dict[str, Any], keys: List[str]) -> str:
    return "\n".join(str(row.get(key) or "") for key in keys)


def _issue(issues: List[Dict[str, str]], line: int, severity: str, field: str, code: str, message: str) -> None:
    issues.append({"line": str(line), "severity": severity, "field": field, "code": code, "message": message})


def validate_row(row: Dict[str, Any], line: int, row_type: str, seen: set[str]) -> List[Dict[str, str]]:
    issues: List[Dict[str, str]] = []
    row_id = str(row.get("id") or "").strip()
    if not row_id:
        _issue(issues, line, "error", "id", "id_missing", "Row id is required.")
    elif row_id in seen:
        _issue(issues, line, "error", "id", "duplicate_id", f"Duplicate id {row_id}.")
    seen.add(row_id)

    if row_type == "sft":
        for field in ["instruction", "response"]:
            if not str(row.get(field) or "").strip():
                _issue(issues, line, "error", field, f"{field}_empty", f"SFT {field} is required.")
        if len(str(row.get("response") or "").strip()) < 40:
            _issue(issues, line, "warning", "response", "response_unusually_short", "Response is unusually short for voice training.")
        pii_tags = row.get("pii_tags")
        text = _text(row, ["instruction", "response", "provenance", "notes"])
        if (EMAIL_RE.search(text) or NAME_RE.search(text)) and not pii_tags:
            _issue(issues, line, "warning", "pii_tags", "pii_tags_empty", "Possible names/emails appear but pii_tags is empty.")
    else:
        for field in ["prompt", "chosen", "rejected"]:
            if not str(row.get(field) or "").strip():
                _issue(issues, line, "error", field, f"{field}_empty", f"DPO {field} is required.")
        chosen = str(row.get("chosen") or "").strip()
        rejected = str(row.get("rejected") or "").strip()
        if chosen and rejected and chosen == rejected:
            _issue(issues, line, "error", "rejected", "chosen_rejected_identical", "Chosen and rejected must be different.")
        if len(chosen) < 40:
            _issue(issues, line, "warning", "chosen", "chosen_unusually_short", "Chosen response is unusually short.")
    return issues


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate Charles model JSONL artifacts.")
    parser.add_argument("path", type=Path)
    parser.add_argument("--type", choices=["sft", "dpo"], required=True)
    args = parser.parse_args()

    issues: List[Dict[str, str]] = []
    seen: set[str] = set()
    checked = 0
    with args.path.open("r", encoding="utf-8") as handle:
        for line_number, raw_line in enumerate(handle, start=1):
            if not raw_line.strip():
                continue
            try:
                row = json.loads(raw_line)
            except json.JSONDecodeError as exc:
                _issue(issues, line_number, "error", "json", "invalid_json", str(exc))
                continue
            if not isinstance(row, dict):
                _issue(issues, line_number, "error", "json", "row_not_object", "Each JSONL row must be an object.")
                continue
            checked += 1
            issues.extend(validate_row(row, line_number, args.type, seen))

    errors = [issue for issue in issues if issue["severity"] == "error"]
    warnings = [issue for issue in issues if issue["severity"] == "warning"]
    print(f"checked={checked} errors={len(errors)} warnings={len(warnings)}")
    for issue in issues:
        print(f"{issue['severity'].upper()} line {issue['line']} {issue['field']} {issue['code']}: {issue['message']}")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
