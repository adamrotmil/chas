from typing import Any, Dict, List, Optional

from sqlmodel import Session, select

from app.models import (
    AntiPattern,
    DPOPair,
    EvalCase,
    Generation,
    GenerationReview,
    GoldVoiceExample,
    PromptSpec,
    SFTCandidate,
    StyleRule,
    Task,
    utcnow,
)


SYSTEM_PROMPT = (
    "Write in Charles's selected voice mode. Use indirect tenderness, concrete objects, "
    "restraint, and practical endings. Do not claim generated text is archival."
)

RUBRIC_CRITERIA = [
    "voice_authenticity",
    "grounding_truth",
    "restraint",
    "concrete_detail",
    "prompt_fit",
    "privacy_export_safety",
]


def _human_id(prefix: str, count: int) -> str:
    return f"{prefix}_{count:06d}"


def _count(session: Session, model: Any) -> int:
    return len(session.exec(select(model)).all()) + 1


def _prompt_text(session: Session, generation: Optional[Generation], decisions: Dict[str, Any]) -> str:
    if decisions.get("prompt"):
        return str(decisions["prompt"])
    if generation and generation.prompt_spec_id:
        prompt_spec = session.get(PromptSpec, generation.prompt_spec_id)
        if prompt_spec:
            return prompt_spec.prompt_text
    return "Manual Charles voice prompt"


def _rubric_status_score(status: Any) -> int:
    if status == "major_issues":
        return 1
    if status == "minor_issues":
        return 3
    if status == "not_applicable":
        return 0
    return 5


def _rubric_issue_count(rubric: Dict[str, Any], *, status: str | None = None) -> int:
    count = 0
    for decision in rubric.values():
        if not isinstance(decision, dict):
            continue
        decision_status = decision.get("status")
        if status:
            count += 1 if decision_status == status else 0
        elif decision_status in {"minor_issues", "major_issues"}:
            count += 1
    return count


def _rubric_average_score(rubric: Dict[str, Any]) -> float | None:
    scores: List[int] = []
    for key in RUBRIC_CRITERIA:
        decision = rubric.get(key)
        if isinstance(decision, dict):
            status = decision.get("status")
            if status != "not_applicable":
                scores.append(_rubric_status_score(status))
    if not scores:
        return None
    return round(sum(scores) / len(scores), 2)


def _rubric_privacy_blocked(rubric: Dict[str, Any]) -> bool:
    decision = rubric.get("privacy_export_safety")
    return isinstance(decision, dict) and decision.get("status") == "major_issues"


def _derive_quality_summary(ratings: Dict[str, Any]) -> Dict[str, Any]:
    response_rubric = ratings.get("response_rubric")
    response_a = _rubric_side(response_rubric, "response_a")
    response_b = _rubric_side(response_rubric, "response_b")
    stored_summary = ratings.get("rubric_summary") if isinstance(ratings.get("rubric_summary"), dict) else {}
    response_b_major = _rubric_issue_count(response_b, status="major_issues")
    response_b_issue_count = _rubric_issue_count(response_b)
    privacy_blocked = bool(stored_summary.get("preferred_export_blocked")) or _rubric_privacy_blocked(response_b)

    required = ["voice_fidelity", "emotional_truth", "restraint", "non_parody"]
    numeric_gate_passed = all(int(ratings.get(key, 0) or 0) >= 4 for key in required)
    if response_b:
        sft_ready = response_b_major == 0 and not privacy_blocked
    elif "sft_ready" in stored_summary:
        sft_ready = bool(stored_summary.get("sft_ready"))
    else:
        sft_ready = numeric_gate_passed

    return {
        "response_a_issue_count": _rubric_issue_count(response_a),
        "response_a_major_issue_count": _rubric_issue_count(response_a, status="major_issues"),
        "response_a_score": _rubric_average_score(response_a),
        "response_b_issue_count": response_b_issue_count,
        "response_b_major_issue_count": response_b_major,
        "response_b_score": _rubric_average_score(response_b),
        "preferred_export_blocked": privacy_blocked,
        "numeric_gate_passed": numeric_gate_passed,
        "sft_ready": sft_ready,
        "dpo_reason_count": len([line for line in _rubric_notes(response_a).splitlines() if line.strip()]),
    }


def _rating_passes(ratings: Dict[str, Any]) -> bool:
    derived = ratings.get("derived_quality")
    if isinstance(derived, dict):
        return bool(derived.get("sft_ready")) and not bool(derived.get("preferred_export_blocked"))
    quality = _derive_quality_summary(ratings)
    return bool(quality["sft_ready"]) and not bool(quality["preferred_export_blocked"])


def _rubric_side(response_rubric: Any, side: str) -> Dict[str, Any]:
    if not isinstance(response_rubric, dict):
        return {}
    value = response_rubric.get(side)
    return value if isinstance(value, dict) else {}


def _rubric_notes(rubric: Any) -> str:
    if not isinstance(rubric, dict):
        return ""
    notes: List[str] = []
    for key, decision in rubric.items():
        if not isinstance(decision, dict):
            continue
        status = decision.get("status")
        note = str(decision.get("notes") or "").strip()
        if status in {"minor_issues", "major_issues"} and note:
            notes.append(f"{key}: {note}")
    return "\n".join(notes)


def _first_or_none(session: Session, statement: Any) -> Any:
    return session.exec(statement).first()


def _sft_messages(prompt: str, gold_text: str) -> List[Dict[str, str]]:
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": prompt},
        {"role": "assistant", "content": gold_text},
    ]


def upsert_gold_voice_artifacts(
    session: Session,
    task: Task,
    decisions: Dict[str, Any],
    annotation_id: str,
) -> Dict[str, str]:
    generation_id = decisions.get("generation_id") or task.input_payload.get("generation_id")
    generation = session.get(Generation, generation_id) if generation_id else None
    prompt_spec_id = decisions.get("prompt_spec_id") or task.input_payload.get("prompt_spec_id")
    context_pack_id = decisions.get("context_pack_id") or task.input_payload.get("context_pack_id")

    if generation:
        prompt_spec_id = prompt_spec_id or generation.prompt_spec_id
        context_pack_id = context_pack_id or generation.context_pack_id

    prompt = _prompt_text(session, generation, decisions)
    model_draft = decisions.get("model_draft") or (generation.output_text if generation else "")
    gold_text = decisions.get("adam_gold_edit") or decisions.get("gold_edit") or ""
    voice_mode = decisions.get("voice_mode") or task.input_payload.get("voice_mode") or "father_to_adam"
    truth_mode = decisions.get("truth_mode") or task.input_payload.get("truth_mode") or "generative_reconstruction"
    raw_ratings = decisions.get("ratings") or {}
    ratings = dict(raw_ratings) if isinstance(raw_ratings, dict) else {}
    response_rubric = decisions.get("response_rubric") or ratings.get("response_rubric")
    response_a_rubric = _rubric_side(response_rubric, "response_a")
    rubric_summary = decisions.get("rubric_summary") or ratings.get("rubric_summary")
    if response_rubric:
        ratings["response_rubric"] = response_rubric
    if rubric_summary:
        ratings["rubric_summary"] = rubric_summary
    ratings["derived_quality"] = _derive_quality_summary(ratings)

    raw_failure_modes = decisions.get("failure_modes") or []
    failure_modes = [str(mode) for mode in raw_failure_modes] if isinstance(raw_failure_modes, list) else []
    issue_notes = _rubric_notes(response_a_rubric)
    if not failure_modes and issue_notes:
        failure_modes = [note for note in issue_notes.splitlines() if note.strip()]
    export_flags = decisions.get("export_flags") or {
        "sft": True,
        "dpo": True,
        "eval": True,
        "anti_pattern": True,
        "style_rule": True,
    }

    if generation_id:
        gold = _first_or_none(
            session,
            select(GoldVoiceExample).where(GoldVoiceExample.generation_id == generation_id),
        )
    else:
        gold = None

    if not gold:
        gold = GoldVoiceExample(
            human_id=_human_id("CR_GOLD_VOICE", _count(session, GoldVoiceExample)),
            generation_id=generation_id,
            prompt_spec_id=prompt_spec_id,
            context_pack_id=context_pack_id,
            voice_mode=voice_mode,
            adam_gold_edit=gold_text,
        )
        session.add(gold)

    gold.prompt_spec_id = prompt_spec_id
    gold.context_pack_id = context_pack_id
    gold.voice_mode = voice_mode
    gold.truth_status = "adam_expert_reconstruction"
    gold.adam_gold_edit = gold_text
    gold.ratings = ratings
    gold.failure_modes = failure_modes
    gold.downstream_use = export_flags
    gold.approved_by = "adam"
    gold.approved_at = utcnow()
    session.add(gold)
    session.flush()

    created: Dict[str, str] = {"gold_voice_example_id": gold.id}

    if generation_id:
        review = GenerationReview(
            generation_id=generation_id,
            reviewer_id="adam",
            ratings=ratings,
            failure_modes=failure_modes,
            notes=f"Created from annotation {annotation_id}",
        )
        session.add(review)
        created["generation_review_id"] = review.id

    quality_summary = ratings["derived_quality"]
    export_status = "approved" if _rating_passes(ratings) else "candidate"

    if export_flags.get("sft"):
        sft = _first_or_none(
            session,
            select(SFTCandidate).where(SFTCandidate.source_gold_voice_example_id == gold.id),
        )
        if not sft:
            sft = SFTCandidate(source_gold_voice_example_id=gold.id)
            session.add(sft)
        sft.messages = _sft_messages(prompt, gold_text)
        sft.quality_gate = {
            "approved_by": "adam",
            "min_voice_fidelity_met": _rating_passes(ratings),
            "boundaries_checked": True,
            "no_archival_misattribution": True,
            "rubric_summary": rubric_summary or {},
            "derived_quality": quality_summary,
            "export_ready": export_status == "approved",
            "source_annotation_id": annotation_id,
        }
        sft.export_status = export_status
        session.add(sft)
        created["sft_candidate_id"] = sft.id

    if export_flags.get("dpo"):
        dpo = _first_or_none(
            session,
            select(DPOPair).where(DPOPair.source_gold_voice_example_id == gold.id),
        )
        if not dpo:
            dpo = DPOPair(
                source_gold_voice_example_id=gold.id,
                prompt=prompt,
                chosen=gold_text,
                rejected=model_draft,
            )
            session.add(dpo)
        dpo.prompt = prompt
        dpo.chosen = gold_text
        dpo.rejected = model_draft
        dpo.reason = failure_modes
        dpo.export_status = export_status
        session.add(dpo)
        created["dpo_pair_id"] = dpo.id

    if export_flags.get("eval"):
        eval_case = _first_or_none(
            session,
            select(EvalCase).where(EvalCase.gold_reference_id == gold.id),
        )
        if not eval_case:
            eval_case = EvalCase(
                human_id=_human_id("EVAL", _count(session, EvalCase)),
                prompt=prompt,
                gold_reference_id=gold.id,
            )
            session.add(eval_case)
        eval_case.prompt = prompt
        eval_case.voice_mode = voice_mode
        eval_case.truth_mode = truth_mode
        eval_case.success_criteria = {
            "voice_fidelity_min": 4,
            "emotional_truth_min": 4,
            "non_parody_min": 4,
            "must_include": ["concrete object carrying emotion"],
            "must_avoid": failure_modes,
            "response_b_must_have_no_major_issues": True,
            "privacy_export_safety_must_pass": True,
            "derived_quality": quality_summary,
        }
        eval_case.status = export_status
        session.add(eval_case)
        created["eval_case_id"] = eval_case.id

    if export_flags.get("anti_pattern"):
        anti_name = "reviewer_described_issue" if issue_notes else failure_modes[0] if failure_modes else "near_miss_draft"
        anti = _first_or_none(
            session,
            select(AntiPattern).where(AntiPattern.source_gold_voice_example_id == gold.id),
        )
        if not anti:
            anti = AntiPattern(
                human_id=_human_id("ANTI", _count(session, AntiPattern)),
                name=anti_name,
                why_wrong="Adam marked this draft as a useful example of what to avoid.",
                source_gold_voice_example_id=gold.id,
            )
            session.add(anti)
        anti.name = anti_name
        anti.voice_mode = voice_mode
        anti.examples = [model_draft] if model_draft else []
        if issue_notes:
            anti.why_wrong = issue_notes
        elif failure_modes:
            anti.why_wrong = ", ".join(failure_modes)
        anti.status = export_status
        session.add(anti)
        created["anti_pattern_id"] = anti.id

    if export_flags.get("style_rule"):
        style_rule = _first_or_none(
            session,
            select(StyleRule).where(StyleRule.source_gold_voice_example_id == gold.id),
        )
        if not style_rule:
            style_rule = StyleRule(
                human_id=_human_id("STYLE", _count(session, StyleRule)),
                voice_mode=voice_mode,
                rule="Let an ordinary physical object carry the feeling before naming emotion.",
                source_gold_voice_example_id=gold.id,
            )
            session.add(style_rule)
        style_rule.rationale = "Derived from Adam's gold edit and failure-mode diagnosis."
        style_rule.status = export_status
        session.add(style_rule)
        created["style_rule_id"] = style_rule.id

    return created
