import json
from typing import Any, Dict, Iterable, List

from sqlmodel import Session, select

from app.models import ContextPack, DPOPair, GoldVoiceExample, SFTCandidate


def to_jsonl(items: Iterable[Dict[str, Any]]) -> str:
    rows = [json.dumps(item, ensure_ascii=False) for item in items]
    return "\n".join(rows) + ("\n" if rows else "")


def _sft_payload(candidate: SFTCandidate) -> Dict[str, Any]:
    return {
        "messages": candidate.messages,
        "metadata": {
            "source_gold_voice_example_id": candidate.source_gold_voice_example_id,
            "truth_status": "adam_expert_reconstruction",
        },
    }


def _dpo_payload(pair: DPOPair) -> Dict[str, Any]:
    return {
        "input": {
            "messages": [
                {
                    "role": "system",
                    "content": "Write in Charles's selected voice mode. Do not claim generated text is archival.",
                },
                {"role": "user", "content": pair.prompt},
            ]
        },
        "preferred_output": pair.chosen,
        "non_preferred_output": pair.rejected,
        "metadata": {
            "source_gold_voice_example_id": pair.source_gold_voice_example_id,
            "reason": pair.reason,
        },
    }


def _gold_for(session: Session, gold_id: str) -> GoldVoiceExample | None:
    return session.get(GoldVoiceExample, gold_id)


def _context_for(session: Session, gold: GoldVoiceExample | None) -> ContextPack | None:
    if not gold or not gold.context_pack_id:
        return None
    return session.get(ContextPack, gold.context_pack_id)


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


def _exclusion_reasons(
    *,
    session: Session,
    export_type: str,
    export_status: str,
    source_gold_voice_example_id: str,
    include_candidates: bool,
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

    return reasons


def export_dry_run(session: Session, export_type: str, *, include_candidates: bool = False) -> Dict[str, Any]:
    if export_type == "sft":
        artifacts = session.exec(select(SFTCandidate)).all()
        rows = [
            {
                "artifact_type": "sft_candidate",
                "artifact_id": artifact.id,
                "source_gold_voice_example_id": artifact.source_gold_voice_example_id,
                "export_status": artifact.export_status,
                "payload": _sft_payload(artifact),
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
                "payload": _dpo_payload(artifact),
            }
            for artifact in artifacts
        ]
    else:
        raise ValueError("export_type must be sft or dpo")

    included: List[Dict[str, Any]] = []
    excluded: List[Dict[str, Any]] = []
    for row in rows:
        reasons = _exclusion_reasons(
            session=session,
            export_type=export_type,
            export_status=str(row["export_status"]),
            source_gold_voice_example_id=str(row["source_gold_voice_example_id"]),
            include_candidates=include_candidates,
        )
        if reasons:
            excluded.append({**row, "reasons": reasons})
        else:
            included.append(row)

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
