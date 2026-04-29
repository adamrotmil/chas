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
from app.services.embeddings import upsert_embedding_record
from app.services.pair_export import compile_pair_export, sft_export_blockers
from app.services.voice_modes import upsert_voice_mode


DEFAULT_SYSTEM_PROMPT = "You are Charles Rotmil."

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


def _prompt_spec(session: Session, generation: Optional[Generation], prompt_spec_id: Optional[str]) -> Optional[PromptSpec]:
    if prompt_spec_id:
        prompt_spec = session.get(PromptSpec, prompt_spec_id)
        if prompt_spec:
            return prompt_spec
    if generation and generation.prompt_spec_id:
        return session.get(PromptSpec, generation.prompt_spec_id)
    return None


def _system_prompt(
    session: Session,
    *,
    generation: Optional[Generation],
    task: Task,
    decisions: Dict[str, Any],
    prompt_spec_id: Optional[str],
) -> str:
    if decisions.get("system_prompt"):
        return str(decisions["system_prompt"])
    if task.input_payload.get("system_prompt"):
        return str(task.input_payload["system_prompt"])
    prompt_spec = _prompt_spec(session, generation, prompt_spec_id)
    if prompt_spec and isinstance(prompt_spec.metadata_json, dict):
        prompt = prompt_spec.metadata_json.get("system_prompt")
        if isinstance(prompt, str) and prompt.strip():
            return prompt
    return DEFAULT_SYSTEM_PROMPT


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
        sft_ready = response_b_issue_count == 0 and not privacy_blocked
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


def _sft_messages(system_prompt: str, prompt: str, gold_text: str) -> List[Dict[str, str]]:
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": prompt},
        {"role": "assistant", "content": gold_text},
    ]


def _dpo_export_blockers(prompt: str, chosen: str, rejected: str, reasons: List[str]) -> List[str]:
    blockers: List[str] = []
    if not prompt.strip():
        blockers.append("dpo_prompt_empty")
    if not chosen.strip():
        blockers.append("dpo_chosen_empty")
    if not rejected.strip():
        blockers.append("dpo_rejected_empty")
    if chosen.strip() and rejected.strip() and chosen.strip() == rejected.strip():
        blockers.append("dpo_chosen_rejected_identical")
    if not reasons:
        blockers.append("dpo_missing_rejected_side_reason")
    return blockers


def upsert_gold_voice_artifacts(
    session: Session,
    task: Task,
    decisions: Dict[str, Any],
    annotation_id: str,
) -> Dict[str, str]:
    unified_mode = bool(
        decisions.get("artifact_mode")
        or decisions.get("content")
        or decisions.get("chosen")
        or decisions.get("rejected")
        or "synthetic" in decisions
    )
    generation_id = decisions.get("generation_id") or task.input_payload.get("generation_id")
    generation = session.get(Generation, generation_id) if generation_id else None
    prompt_spec_id = decisions.get("prompt_spec_id") or task.input_payload.get("prompt_spec_id")
    context_pack_id = decisions.get("context_pack_id") or task.input_payload.get("context_pack_id")

    if generation:
        prompt_spec_id = prompt_spec_id or generation.prompt_spec_id
        context_pack_id = context_pack_id or generation.context_pack_id

    fallback_truth_status = str(task.input_payload.get("truth_status") or "archival_source")
    compiled_export = compile_pair_export(
        {**task.input_payload, **decisions},
        fallback_truth_status=fallback_truth_status,
    ) if unified_mode else None

    prompt = str(compiled_export["prompt"]) if compiled_export else _prompt_text(session, generation, decisions)
    system_prompt = str(compiled_export["system_prompt"]) if compiled_export else _system_prompt(
        session,
        generation=generation,
        task=task,
        decisions=decisions,
        prompt_spec_id=prompt_spec_id,
    )
    if compiled_export:
        model_draft = str(compiled_export.get("rejected") or "")
        gold_text = str(compiled_export.get("chosen") or compiled_export.get("content") or "")
        voice_mode = str(compiled_export["voice_mode"])
        truth_mode = str(compiled_export["truth_status"])
    else:
        model_draft = decisions.get("model_draft") or (generation.output_text if generation else "")
        gold_text = decisions.get("adam_gold_edit") or decisions.get("gold_edit") or ""
        voice_mode = decisions.get("voice_mode") or task.input_payload.get("voice_mode") or "father_to_adam"
        truth_mode = decisions.get("truth_mode") or task.input_payload.get("truth_mode") or "generative_reconstruction"
    if isinstance(voice_mode, str) and voice_mode.strip():
        upsert_voice_mode(session, label=voice_mode.replace("_", " ").title(), slug=voice_mode, family="gold_edit")
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
    export_flags = decisions.get("export_flags") or (
        compiled_export["export_flags"]
        if compiled_export
        else {
            "sft": True,
            "dpo": True,
            "eval": True,
            "anti_pattern": True,
            "style_rule": True,
        }
    )

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
    gold.truth_status = str(truth_mode) if unified_mode else "adam_expert_reconstruction"
    gold.adam_gold_edit = gold_text
    gold.ratings = ratings
    gold.failure_modes = failure_modes
    gold.downstream_use = {
        **export_flags,
        "artifact_mode": compiled_export.get("artifact_mode") if compiled_export else "legacy_gold_voice_edit",
        "synthetic": compiled_export.get("synthetic") if compiled_export else True,
        "context": compiled_export.get("context") if compiled_export else decisions.get("context"),
        "grounding_asset_id": compiled_export.get("grounding_asset_id") if compiled_export else decisions.get("grounding_asset_id"),
        "export_preview_yaml": compiled_export.get("yaml_preview") if compiled_export else decisions.get("export_preview_yaml"),
        "source_annotation_id": annotation_id,
    }
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
        sft_blockers = sft_export_blockers(system_prompt, prompt, gold_text)
        sft_export_status = "candidate" if sft_blockers else export_status
        sft = _first_or_none(
            session,
            select(SFTCandidate).where(SFTCandidate.source_gold_voice_example_id == gold.id),
        )
        if not sft:
            sft = SFTCandidate(source_gold_voice_example_id=gold.id)
            session.add(sft)
        sft.messages = compiled_export.get("sft_messages") if compiled_export and compiled_export.get("sft_messages") else _sft_messages(system_prompt, prompt, gold_text)
        sft.quality_gate = {
            "approved_by": "adam",
            "min_voice_fidelity_met": _rating_passes(ratings),
            "boundaries_checked": True,
            "no_archival_misattribution": True,
            "system_prompt": system_prompt,
            "conversation_family": task.input_payload.get("conversation_family"),
            "rubric_summary": rubric_summary or {},
            "derived_quality": quality_summary,
            "export_ready": sft_export_status == "approved",
            "export_blockers": sft_blockers,
            "source_annotation_id": annotation_id,
            "artifact_mode": compiled_export.get("artifact_mode") if compiled_export else "legacy_gold_voice_edit",
            "export_preview_yaml": compiled_export.get("yaml_preview") if compiled_export else decisions.get("export_preview_yaml"),
        }
        sft.export_status = sft_export_status
        session.add(sft)
        created["sft_candidate_id"] = sft.id

    if export_flags.get("dpo"):
        dpo_blockers = _dpo_export_blockers(prompt, gold_text, model_draft, failure_modes)
        dpo_export_status = "candidate" if dpo_blockers else export_status
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
        dpo.reason = [*failure_modes, *dpo_blockers]
        dpo.export_status = dpo_export_status
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

    embedding = upsert_embedding_record(
        session=session,
        target_type="gold_voice_example",
        target_id=gold.id,
        input_text="\n\n".join(
            [
                f"voice_mode: {voice_mode}",
                f"truth_status: {gold.truth_status}",
                f"user: {prompt}",
                f"assistant: {gold_text}",
            ]
        ),
        modality="text",
        embedding_type="gold_voice_text",
        truth_status=gold.truth_status,
        boundary_snapshot={"context_pack_id": context_pack_id, "downstream_use": export_flags},
        metadata={"source": "gold_voice_edit", "source_annotation_id": annotation_id},
        created_by="gold_voice_edit",
    )
    if embedding:
        created["embedding_record_id"] = embedding.id

    return created
