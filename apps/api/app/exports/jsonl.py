import json
from typing import Any, Dict, Iterable, List

from sqlmodel import Session, select

from app.models import DPOPair, SFTCandidate


def to_jsonl(items: Iterable[Dict[str, Any]]) -> str:
    rows = [json.dumps(item, ensure_ascii=False) for item in items]
    return "\n".join(rows) + ("\n" if rows else "")


def sft_export_items(session: Session) -> List[Dict[str, Any]]:
    candidates = session.exec(
        select(SFTCandidate).where(SFTCandidate.export_status == "approved")
    ).all()
    return [
        {
            "messages": candidate.messages,
            "metadata": {
                "source_gold_voice_example_id": candidate.source_gold_voice_example_id,
                "truth_status": "adam_expert_reconstruction",
            },
        }
        for candidate in candidates
    ]


def dpo_export_items(session: Session) -> List[Dict[str, Any]]:
    pairs = session.exec(select(DPOPair).where(DPOPair.export_status == "approved")).all()
    return [
        {
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
        for pair in pairs
    ]
