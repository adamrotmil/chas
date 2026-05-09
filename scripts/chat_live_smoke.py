#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.parse
import urllib.request
from typing import Any, Dict, Iterable, List, Optional


DEFAULT_API_BASE = "http://localhost:8000/api"
SMOKE_ORDER = ["photo", "sft", "dpo", "ambiguous"]


def _json_request(method: str, url: str, payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=90) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"{method} {url} failed with HTTP {exc.code}: {body}") from exc


def _url(base: str, path: str, params: Optional[Dict[str, str]] = None) -> str:
    url = f"{base.rstrip('/')}/{path.lstrip('/')}"
    if params:
        url = f"{url}?{urllib.parse.urlencode(params)}"
    return url


def _task_payload(task: Dict[str, Any]) -> Dict[str, Any]:
    payload = task.get("input_payload")
    return payload if isinstance(payload, dict) else {}


def _artifact_mode(task: Dict[str, Any]) -> str:
    return str(_task_payload(task).get("artifact_mode") or "sft")


def _find_task(tasks: Iterable[Dict[str, Any]], smoke: str) -> Optional[Dict[str, Any]]:
    for task in tasks:
        task_type = str(task.get("task_type") or "")
        if smoke in {"photo", "ambiguous"} and task_type in {"photo_context", "vision_draft_review"}:
            return task
        if smoke == "sft" and task_type in {"gold_voice_edit", "grounded_prompt_pair_candidate"} and _artifact_mode(task) != "dpo":
            return task
        if smoke == "dpo" and task_type in {"gold_voice_edit", "grounded_prompt_pair_candidate"} and _artifact_mode(task) == "dpo":
            return task
    return None


def _chat_turn(base: str, task: Dict[str, Any], message: str) -> Dict[str, Any]:
    return _json_request(
        "POST",
        _url(base, "/chat/turn"),
        {
            "task_id": task["id"],
            "message": message,
            "mode": "chat",
            "user_id": "adam",
            "history": [],
            "draft_decisions": {},
            "apply_updates": False,
        },
    )


def _response_text(response: Dict[str, Any]) -> str:
    return "\n".join(
        str(value or "")
        for value in [response.get("assistant_message"), response.get("next_question")]
        if str(value or "").strip()
    )


def _action_types(response: Dict[str, Any]) -> List[str]:
    actions = response.get("actions")
    if not isinstance(actions, list):
        return []
    return [str(action.get("type") or "") for action in actions if isinstance(action, dict)]


def _check_response(smoke: str, task: Dict[str, Any], response: Dict[str, Any]) -> List[str]:
    failures: List[str] = []
    text = _response_text(response)
    prompt = str(_task_payload(task).get("prompt") or "").strip()
    if response.get("live_model_call_used") is not True:
        failures.append("live_model_call_used was not true")
    if response.get("submitted_annotation"):
        failures.append("smoke response submitted an annotation")
    if "build_dataset_export" in _action_types(response):
        failures.append("smoke response proposed an export build")
    if smoke in {"photo", "ambiguous", "sft"} and "?" not in text:
        failures.append("assistant did not ask a question")
    if smoke == "ambiguous" and response.get("ready_to_submit") is True:
        failures.append("ambiguous answer was marked ready to submit")
    next_question = str(response.get("next_question") or "")
    if smoke == "sft" and prompt and prompt.lower() in next_question.lower():
        failures.append("assistant repeated the source prompt as the question to Adam")
    if smoke == "dpo" and not (response.get("field_updates") or _action_types(response)):
        failures.append("DPO smoke did not produce field updates or a structured action")
    return failures


def run_smoke(base: str, smoke: str, tasks: List[Dict[str, Any]]) -> Dict[str, Any]:
    task = _find_task(tasks, smoke)
    if task is None:
        return {"smoke": smoke, "status": "skipped", "reason": "no matching ready task"}
    messages = {
        "photo": "Look at this photo work item and ask Adam one useful context question. Do not submit anything.",
        "sft": "Start this SFT review. Ask Adam what to critique or revise; do not ask Adam to answer the source prompt.",
        "dpo": "The rejected side is better than the chosen side. Preview that preference correction and preserve why; do not submit.",
        "ambiguous": "Maybe, not sure.",
    }
    response = _chat_turn(base, task, messages[smoke])
    failures = _check_response(smoke, task, response)
    return {
        "smoke": smoke,
        "status": "failed" if failures else "passed",
        "failures": failures,
        "task": {
            "id": task.get("id"),
            "human_id": task.get("human_id"),
            "task_type": task.get("task_type"),
            "artifact_mode": _artifact_mode(task),
        },
        "response": {
            "status": response.get("status"),
            "session_id": response.get("session_id"),
            "turn_id": response.get("turn_id"),
            "live_model_call_used": response.get("live_model_call_used"),
            "ready_to_submit": response.get("ready_to_submit"),
            "assistant_message": response.get("assistant_message"),
            "next_question": response.get("next_question"),
            "field_update_keys": sorted((response.get("field_updates") or {}).keys()),
            "action_types": _action_types(response),
        },
        "manual_checks": [
            "Question is addressed to Adam as reviewer, not to Charles.",
            "No final submit/export happened.",
            "Uncertainty is preserved instead of converted into fact.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run opt-in live model smoke checks for the Chat workbench.")
    parser.add_argument("--api-base", default=os.environ.get("CHAT_API_BASE", DEFAULT_API_BASE))
    parser.add_argument("--smoke", choices=[*SMOKE_ORDER, "all"], default="all")
    parser.add_argument("--require-ready", action="store_true", help="Fail when live model credentials/gate are not ready.")
    args = parser.parse_args()

    status = _json_request("GET", _url(args.api_base, "/model-status"))
    if status.get("text_generation_live_ready") is not True:
        result = {
            "status": "skipped",
            "reason": "live model is not ready",
            "model_status": {
                "text_generation_model": status.get("text_generation_model"),
                "text_generation_live_calls_enabled": status.get("text_generation_live_calls_enabled"),
                "openai_api_key_configured": status.get("openai_api_key_configured"),
            },
        }
        print(json.dumps(result, indent=2))
        return 1 if args.require_ready else 0

    tasks = _json_request("GET", _url(args.api_base, "/tasks", {"status": "ready"}))
    if not isinstance(tasks, list):
        raise RuntimeError("/tasks?status=ready did not return a list")
    smoke_names = SMOKE_ORDER if args.smoke == "all" else [args.smoke]
    results = [run_smoke(args.api_base, smoke, tasks) for smoke in smoke_names]
    failed = [result for result in results if result["status"] == "failed"]
    print(json.dumps({"status": "failed" if failed else "passed", "results": results}, indent=2))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
