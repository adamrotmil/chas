#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional


DEFAULT_API_BASE = "http://localhost:8000/api"


def _json_request(method: str, url: str, payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any] | List[Dict[str, Any]]:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={"Accept": "application/json", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"{method} {url} failed with HTTP {exc.code}: {body}") from exc


def _url(base: str, path: str, params: Optional[Dict[str, str]] = None) -> str:
    url = f"{base.rstrip('/')}/{path.lstrip('/')}"
    if params:
        url = f"{url}?{urllib.parse.urlencode(params)}"
    return url


def _select_smoke_task(tasks: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    preferred_types = ["photo_context", "vision_draft_review", "gold_voice_edit", "text_segment_review"]
    for task_type in preferred_types:
        for task in tasks:
            if task.get("task_type") == task_type:
                return task
    return tasks[0] if tasks else None


def run_smoke(api_base: str) -> Dict[str, Any]:
    model_status = _json_request("GET", _url(api_base, "/model-status"))
    if not isinstance(model_status, dict):
        raise RuntimeError("/model-status did not return an object")
    if model_status.get("text_generation_live_ready") is not True:
        return {
            "status": "skipped",
            "reason": "text_generation_live_ready_false",
            "model_status": {
                "text_generation_model": model_status.get("text_generation_model"),
                "text_generation_reasoning_effort": model_status.get("text_generation_reasoning_effort"),
                "text_generation_live_calls_enabled": model_status.get("text_generation_live_calls_enabled"),
                "openai_api_key_configured": model_status.get("openai_api_key_configured"),
            },
        }

    audit = _json_request("GET", _url(api_base, "/ai-spine/audit"))
    if not isinstance(audit, dict):
        raise RuntimeError("/ai-spine/audit did not return an object")
    if audit.get("summary", {}).get("text_generation_ready") is not True:
        return {"status": "failed", "reason": "ai_spine_audit_disagrees_with_model_status"}

    tasks = _json_request("GET", _url(api_base, "/tasks", {"status": "ready"}))
    if not isinstance(tasks, list):
        raise RuntimeError("/tasks?status=ready did not return a list")
    task = _select_smoke_task(tasks)
    if task is None:
        return {"status": "skipped", "reason": "no_ready_task"}

    chat_response = _json_request(
        "POST",
        _url(api_base, "/chat/turn"),
        {
            "task_id": task["id"],
            "message": "Live smoke check: inspect this work item, ask Adam one next useful question, and do not submit or export anything.",
            "mode": "chat",
            "user_id": "adam",
            "history": [],
            "draft_decisions": {},
            "apply_updates": False,
        },
    )
    if not isinstance(chat_response, dict):
        raise RuntimeError("/chat/turn did not return an object")

    failures = []
    if chat_response.get("live_model_call_used") is not True:
        failures.append("chat turn did not report live_model_call_used")
    if chat_response.get("submitted_annotation") is not None:
        failures.append("chat turn submitted an annotation")
    if chat_response.get("built_export") is not None:
        failures.append("chat turn built an export")
    if not str(chat_response.get("assistant_message") or chat_response.get("next_question") or "").strip():
        failures.append("chat turn returned no assistant text")

    return {
        "status": "failed" if failures else "passed",
        "failures": failures,
        "ai_spine": {
            "text_generation_ready": audit.get("summary", {}).get("text_generation_ready"),
            "vision_live_ready": audit.get("summary", {}).get("vision_live_ready"),
            "live_path_count": audit.get("summary", {}).get("live_path_count"),
            "scaffold_or_fallback_path_count": audit.get("summary", {}).get("scaffold_or_fallback_path_count"),
        },
        "task": {
            "id": task.get("id"),
            "human_id": task.get("human_id"),
            "task_type": task.get("task_type"),
        },
        "chat_response": {
            "status": chat_response.get("status"),
            "session_id": chat_response.get("session_id"),
            "turn_id": chat_response.get("turn_id"),
            "model_name": chat_response.get("model_name"),
            "reasoning_effort": chat_response.get("reasoning_effort"),
            "live_model_call_used": chat_response.get("live_model_call_used"),
            "ready_to_submit": chat_response.get("ready_to_submit"),
        },
        "manual_checks": [
            "Assistant speaks to Adam as reviewer, not as Charles.",
            "Assistant asks or proposes one useful next step.",
            "No final submit/export side effect occurred.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Opt-in live AI smoke test for the CharlesOps AI spine.")
    parser.add_argument("--api-base", default=os.environ.get("API_BASE", DEFAULT_API_BASE))
    parser.add_argument("--force", action="store_true", help="Run even when RUN_LIVE_AI_SMOKE is not true.")
    args = parser.parse_args()

    if not args.force and os.environ.get("RUN_LIVE_AI_SMOKE") != "true":
        print(
            json.dumps(
                {
                    "status": "skipped",
                    "reason": "set RUN_LIVE_AI_SMOKE=true or pass --force to run live provider checks",
                },
                indent=2,
            )
        )
        return 0

    result = run_smoke(args.api_base)
    print(json.dumps(result, indent=2))
    return 1 if result.get("status") == "failed" else 0


if __name__ == "__main__":
    sys.exit(main())
