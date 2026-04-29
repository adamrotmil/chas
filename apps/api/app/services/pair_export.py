from __future__ import annotations

import re
from typing import Any, Dict, List, Literal, Optional


DEFAULT_SYSTEM_PROMPT = "You are Charles Rotmil."
NATURAL_SYSTEM_PROMPT = "You are Charles Rotmil. Write naturally in his voice."
FILENAME_PROMPT_RE = re.compile(
    r"^tell me about\s+[^?\n]+\.(?:ya?ml|jsonl?|txt|md|docx?|pdf|jpe?g|png|gif|tiff?|psd|heic|csv|eml|mbox|rtf)\.?$",
    re.IGNORECASE,
)

ArtifactMode = Literal["sft", "dpo"]


def _string(value: Any, fallback: str = "") -> str:
    return value if isinstance(value, str) and value.strip() else fallback


def _bool(value: Any, fallback: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"yes", "true", "1", "synthetic"}:
            return True
        if lowered in {"no", "false", "0", "archival"}:
            return False
    return fallback


def _artifact_mode(decisions: Dict[str, Any]) -> ArtifactMode:
    mode = _string(decisions.get("artifact_mode"), "sft").lower()
    return "dpo" if mode == "dpo" else "sft"


def system_prompt_for_mode(mode: ArtifactMode, decisions: Dict[str, Any]) -> str:
    explicit = _string(decisions.get("system_prompt"))
    if explicit:
        return explicit
    if mode == "dpo":
        return DEFAULT_SYSTEM_PROMPT
    return NATURAL_SYSTEM_PROMPT


def truth_status_for_synthetic(decisions: Dict[str, Any], fallback: str = "archival_source") -> str:
    explicit = _string(decisions.get("truth_status"))
    if explicit:
        return explicit
    synthetic = _bool(decisions.get("synthetic"), True)
    return "adam_expert_reconstruction" if synthetic else fallback


def _indent_block(text: str, spaces: int = 4) -> str:
    indent = " " * spaces
    lines = text.splitlines() or [""]
    return "\n".join(f"{indent}{line}" if line else indent.rstrip() for line in lines)


def _yaml_scalar(value: str, block_indent: int = 4) -> str:
    value = value.strip()
    if not value:
        return '""'
    if "\n" in value:
        return "|-\n" + _indent_block(value, block_indent)
    if re.search(r"[:#\[\]{}]|^\s|'\s|\"|^[-?]|[&*!|>%@`]", value):
        return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return value


def sft_messages(system_prompt: str, prompt: str, content: str) -> List[Dict[str, str]]:
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": prompt},
        {"role": "assistant", "content": content},
    ]


def sft_yaml(system_prompt: str, prompt: str, content: str) -> str:
    return "\n".join(
        [
            "- messages:",
            "   - role: system",
            f"     content: {_yaml_scalar(system_prompt, 7)}",
            "   - role: user",
            f"     content: {_yaml_scalar(prompt, 7)}",
            "   - role: assistant",
            "     content: |-",
            _indent_block(content, 7),
        ]
    )


def dpo_yaml(system_prompt: str, prompt: str, chosen: str, rejected: str) -> str:
    return "\n".join(
        [
            f"- system: {_yaml_scalar(system_prompt, 4)}",
            f"  prompt: {_yaml_scalar(prompt, 4)}",
            "  chosen: |-",
            _indent_block(chosen, 4),
            "  rejected: |-",
            _indent_block(rejected, 4),
        ]
    )


def sft_export_blockers(system_prompt: str, prompt: str, content: str) -> List[str]:
    blockers: List[str] = []
    normalized_prompt = prompt.strip()
    normalized_content = content.strip()
    lowered_prompt = normalized_prompt.lower()
    if not system_prompt.strip():
        blockers.append("sft_system_prompt_empty")
    if not normalized_prompt:
        blockers.append("sft_prompt_empty")
    if lowered_prompt in {"tell me about this.", "tell me about this", "manual charles voice prompt"}:
        blockers.append("sft_prompt_placeholder")
    if FILENAME_PROMPT_RE.match(normalized_prompt):
        blockers.append("sft_prompt_filename_placeholder")
    if not normalized_content:
        blockers.append("sft_assistant_content_empty")
    if normalized_prompt and normalized_content and normalized_prompt == normalized_content:
        blockers.append("sft_prompt_response_identical")
    return blockers


def dpo_export_blockers(prompt: str, chosen: str, rejected: str, failure_modes: List[str]) -> List[str]:
    blockers: List[str] = []
    normalized_prompt = prompt.strip()
    normalized_chosen = chosen.strip()
    normalized_rejected = rejected.strip()
    if not normalized_prompt:
        blockers.append("dpo_prompt_empty")
    if not normalized_chosen:
        blockers.append("dpo_chosen_empty")
    if not normalized_rejected:
        blockers.append("dpo_rejected_empty")
    if normalized_chosen and normalized_rejected and normalized_chosen == normalized_rejected:
        blockers.append("dpo_chosen_rejected_identical")
    if not failure_modes:
        blockers.append("dpo_rejected_reason_empty")
    return blockers


def _list(value: Any) -> List[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item).strip()]


def _rubric_summary(decisions: Dict[str, Any]) -> Dict[str, Any]:
    summary = decisions.get("rubric_summary")
    return summary if isinstance(summary, dict) else {}


def preflight_pair_export_gate(decisions: Dict[str, Any]) -> Dict[str, Any]:
    compiled = compile_pair_export(decisions)
    mode = compiled["artifact_mode"]
    rubric_summary = _rubric_summary(decisions)
    boundary_snapshot = decisions.get("boundary_snapshot")
    boundary_snapshot = boundary_snapshot if isinstance(boundary_snapshot, dict) else {}
    boundary_sft_blocked = bool(decisions.get("source_photo_id")) and boundary_snapshot.get("usable_for_sft") is False
    preferred_export_blocked = bool(rubric_summary.get("preferred_export_blocked"))
    sft_ready = rubric_summary.get("sft_ready")
    if sft_ready is None:
        sft_ready = not preferred_export_blocked
    blockers: List[str] = []
    if mode == "dpo":
        blockers.extend(
            dpo_export_blockers(
                compiled["prompt"],
                compiled["chosen"],
                compiled["rejected"],
                _list(decisions.get("failure_modes")),
            )
        )
    else:
        blockers.extend(sft_export_blockers(compiled["system_prompt"], compiled["prompt"], compiled["content"]))
    if not bool(sft_ready):
        blockers.append("rubric_not_export_ready")
    blockers.extend(f"chosen_issue: {mode}" for mode in _list(decisions.get("preferred_failure_modes")))
    if preferred_export_blocked:
        blockers.append("privacy_export_blocked")
    if boundary_sft_blocked:
        blockers.append("source_boundary_blocks_training")
    blockers = list(dict.fromkeys(blockers))
    export_ready = not blockers
    return {
        "artifact_mode": mode,
        "export_ready": export_ready,
        "export_status": "approved" if export_ready else "candidate",
        "submit_outcome": f"Will submit approved {mode.upper()}" if export_ready else "Will submit as review candidate",
        "dataset_outcome": "Approved JSONL after Submit" if export_ready else "Candidate dry-run only",
        "blockers": blockers,
        "yaml_preview": compiled["yaml_preview"],
    }


def compile_pair_export(
    decisions: Dict[str, Any],
    *,
    fallback_truth_status: str = "archival_source",
) -> Dict[str, Any]:
    mode = _artifact_mode(decisions)
    voice_mode = _string(decisions.get("voice_mode"), "father_to_adam")
    prompt = _string(decisions.get("prompt")) or _string(decisions.get("prompt_text")) or "Tell me about this."
    system_prompt = system_prompt_for_mode(mode, decisions)
    synthetic = _bool(decisions.get("synthetic"), True)
    truth_status = truth_status_for_synthetic(
        {**decisions, "synthetic": synthetic},
        fallback=fallback_truth_status,
    )
    context = _string(decisions.get("context"))
    grounding_asset_id = _string(decisions.get("grounding_asset_id")) or None

    if mode == "dpo":
        chosen = _string(decisions.get("chosen")) or _string(decisions.get("adam_gold_edit"))
        rejected = _string(decisions.get("rejected")) or _string(decisions.get("model_draft"))
        yaml_preview = dpo_yaml(system_prompt, prompt, chosen, rejected)
        return {
            "artifact_mode": "dpo",
            "voice_mode": voice_mode,
            "synthetic": synthetic,
            "truth_status": truth_status,
            "system_prompt": system_prompt,
            "prompt": prompt,
            "chosen": chosen,
            "rejected": rejected,
            "context": context,
            "grounding_asset_id": grounding_asset_id,
            "yaml_preview": yaml_preview,
            "dpo_payload": {
                "system": system_prompt,
                "prompt": prompt,
                "chosen": chosen,
                "rejected": rejected,
            },
            "export_flags": {"sft": False, "dpo": True, "eval": False, "anti_pattern": False, "style_rule": False},
        }

    content = _string(decisions.get("content")) or _string(decisions.get("adam_gold_edit")) or _string(
        decisions.get("chosen")
    )
    yaml_preview = sft_yaml(system_prompt, prompt, content)
    return {
        "artifact_mode": "sft",
        "voice_mode": voice_mode,
        "synthetic": synthetic,
        "truth_status": truth_status,
        "system_prompt": system_prompt,
        "prompt": prompt,
        "content": content,
        "chosen": content,
        "rejected": _string(decisions.get("rejected")) or _string(decisions.get("model_draft")),
        "context": context,
        "grounding_asset_id": grounding_asset_id,
        "yaml_preview": yaml_preview,
        "sft_messages": sft_messages(system_prompt, prompt, content),
        "export_flags": {"sft": True, "dpo": False, "eval": False, "anti_pattern": False, "style_rule": False},
    }
