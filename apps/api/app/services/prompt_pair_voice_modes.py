from __future__ import annotations

from collections import Counter
from typing import Any, Dict, List

from sqlmodel import Session, select

from app.models import Task, utcnow
from app.services.pair_export import compile_pair_export


DEFAULT_IMPORTED_MODE = "father_to_adam"


def _text(*values: Any) -> str:
    return "\n".join(str(value) for value in values if isinstance(value, str) and value.strip()).lower()


def classify_prompt_pair_voice_mode(
    *,
    prompt: str = "",
    response: str = "",
    context: str = "",
    current_voice_mode: str = "",
) -> str:
    """Deterministically infer a useful review bucket for imported prompt pairs.

    This is not an authenticity judgment. It is a triage label so Adam can filter
    a large imported SFT file by the kind of Charles voice being exemplified.
    Explicit non-default user labels always win.
    """

    if current_voice_mode and current_voice_mode != DEFAULT_IMPORTED_MODE:
        return current_voice_mode

    combined = _text(prompt, response, context)
    prompt_l = (prompt or "").lower()
    response_l = (response or "").lower()
    line_count = len([line for line in response.splitlines() if line.strip()])

    if any(marker in prompt_l for marker in ["cathryn:", "liz ", "agnes", "agnès", "jack:", "ruth:", "tom lennon:"]):
        return "verbatim_email_reply"
    if any(marker in combined for marker in ["http://", "https://"]):
        return "verbatim_email_reply"
    if "n.b." in combined or "n.b. " in combined:
        return "nb_digression"
    if "p.s." in combined or "\nps " in combined or "\nps." in combined:
        return "ps_digression"
    if any(term in prompt_l for term in ["airport", "flight", "chess", "address", "meet me", "notary", "package while"]):
        return "logistical_note"
    if any(term in prompt_l for term in ["photograph", "photo", "pictures", "taking pictures"]):
        return "photography_reflection"
    if any(
        term in combined
        for term in [
            "diogenes",
            "schopenhauer",
            "god",
            "black hole",
            "universe",
            "andromeda",
            "plato",
            "camus",
            "mystery",
        ]
    ):
        return "philosophical_fragment"
    if any(
        term in combined
        for term in [
            "war",
            "gestapo",
            "monastery",
            "guadalajara",
            "mexico",
            "vienna",
            "baptist mission",
            "los angeles",
            "hitchhiked",
            "new orleans",
            "border",
            "draft",
            "korean",
            "bat mitzvah",
            "old orchard",
            "phoenix",
            "laredo",
            "montezuma",
        ]
    ):
        return "memoir_scene"
    if any(term in combined for term in ["camera", "photo", "photograph", "photographer", "nikon", "cartier-bresson", "gq"]):
        return "photography_reflection"
    if any(
        term in combined
        for term in ["karaoke", "couscous", "latkes", "soup", "kielbasa", "dentures", "bullshit", "pea soup"]
    ):
        return "comic_observation"
    if any(term in combined for term in ["chess", "airport", "flight", "meet me", "address", "notary"]):
        return "logistical_note"
    if line_count <= 8 and any(term in combined for term in ["dad", "love", "coffee", "portland", "weather", "walk"]):
        return "mundane_text_message"
    if line_count >= 22:
        return "source_based_story_recall"
    return DEFAULT_IMPORTED_MODE


def _response_from_payload(payload: Dict[str, Any]) -> str:
    if payload.get("artifact_mode") == "dpo":
        return str(payload.get("chosen") or "")
    return str(payload.get("content") or payload.get("chosen") or payload.get("adam_gold_edit") or "")


def backfill_prompt_pair_voice_modes(session: Session, *, dry_run: bool = False) -> Dict[str, Any]:
    tasks = session.exec(
        select(Task)
        .where(Task.task_type == "gold_voice_edit")
        .where(Task.queue == "prompt_pairs_needing_gold_edits")
        .order_by(Task.created_at.asc())
    ).all()
    updates: List[Dict[str, Any]] = []
    before = Counter()
    after = Counter()

    for task in tasks:
        payload = dict(task.input_payload or {})
        current = str(payload.get("voice_mode") or DEFAULT_IMPORTED_MODE)
        before[current] += 1
        inferred = classify_prompt_pair_voice_mode(
            prompt=str(payload.get("prompt") or ""),
            response=_response_from_payload(payload),
            context=str(payload.get("context") or payload.get("source_excerpt") or ""),
            current_voice_mode=current,
        )
        after[inferred] += 1
        if inferred == current:
            continue
        updates.append(
            {
                "task_id": task.id,
                "human_id": task.human_id,
                "pair_index": payload.get("pair_index"),
                "from": current,
                "to": inferred,
                "prompt": str(payload.get("prompt") or "")[:160],
            }
        )
        if dry_run:
            continue
        payload["voice_mode"] = inferred
        payload["voice_mode_source"] = "deterministic_classifier_v1"
        payload["voice_mode_previous"] = current
        compiled = compile_pair_export(payload, fallback_truth_status=str(payload.get("truth_status") or "archival_source"))
        payload["export_preview_yaml"] = compiled["yaml_preview"]
        task.input_payload = payload
        task.updated_at = utcnow()
        session.add(task)

    if not dry_run:
        session.commit()

    return {
        "dry_run": dry_run,
        "task_count": len(tasks),
        "updated_count": len(updates),
        "before": dict(sorted(before.items())),
        "after": dict(sorted(after.items())),
        "updates": updates[:100],
    }
