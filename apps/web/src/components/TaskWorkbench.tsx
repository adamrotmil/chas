"use client";

import Link from "next/link";
import {
  CheckCircle2,
  ChevronLeft,
  ChevronRight,
  ClipboardList,
  Copy,
  Flag,
  Gauge,
  Image,
  Mail,
  RotateCcw,
  Save,
  ShieldCheck,
  SkipForward,
  Sparkles,
  TextCursorInput
} from "lucide-react";
import { FormEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { createEntity, getAssetPreviewUrl, getAssetTextChunks, getEntities, getTaskDraft, saveTaskDraft } from "@/lib/api";
import { maturityLabel, readinessBadgesForTask } from "@/lib/readiness";
import type { Asset, Entity, Segment, Task } from "@/lib/types";

type Decisions = Record<string, unknown>;
type RubricIssueStatus = "no_issues" | "minor_issues" | "major_issues" | "not_applicable";
type RubricDecision = {
  status: RubricIssueStatus;
  notes: string;
  issue_tags: string[];
};
type ChunkSelection = {
  chunk_scope: string;
  selected_chunk_ids: string[];
  active_chunk_id?: string;
  selected_chunk_count: number;
};
type SourceUseMode =
  | "verbatim_preferred"
  | "grounded_synthesis_allowed"
  | "context_only"
  | "exclude";

function sameChunkSelection(left: ChunkSelection, right: ChunkSelection): boolean {
  return (
    left.chunk_scope === right.chunk_scope &&
    left.active_chunk_id === right.active_chunk_id &&
    left.selected_chunk_count === right.selected_chunk_count &&
    left.selected_chunk_ids.length === right.selected_chunk_ids.length &&
    left.selected_chunk_ids.every((id, index) => id === right.selected_chunk_ids[index])
  );
}

function sameDecisionRecord(left: Decisions, right: Decisions): boolean {
  const leftKeys = Object.keys(left);
  const rightKeys = Object.keys(right);
  return leftKeys.length === rightKeys.length && leftKeys.every((key) => Object.is(left[key], right[key]));
}

interface TaskWorkbenchProps {
  task: Task;
  asset?: Asset;
  queuePosition: number;
  queueTotal: number;
  qualityScore: number;
  completedThisSession: number;
  memoriesCount: number;
  goldExamplesCount: number;
  assetsCount: number;
  onSubmit: (decisions: Decisions, notes?: string) => Promise<void>;
  onSkip: () => Promise<void>;
  onFlag: () => Promise<void>;
  onPrevious: () => void;
  onNext: () => void;
}

const taskLabels: Record<string, { label: string; icon: React.ReactNode }> = {
  asset_triage: { label: "Asset Triage", icon: <ClipboardList size={18} /> },
  photo_context: { label: "Photo Context", icon: <Image size={18} /> },
  text_segment_review: { label: "Source Review", icon: <TextCursorInput size={18} /> },
  text_segment_boundary_review: { label: "Segment Boundary Review", icon: <TextCursorInput size={18} /> },
  boundary_review: { label: "Privacy Review", icon: <ShieldCheck size={18} /> },
  email_voice_sample: { label: "Email Voice Sample", icon: <Mail size={18} /> },
  vision_draft_review: { label: "Vision Draft Review", icon: <Image size={18} /> },
  grounded_prompt_pair_candidate: { label: "Prompt Pair Factory", icon: <ClipboardList size={18} /> },
  gold_voice_edit: { label: "Gold Voice Edit", icon: <Sparkles size={18} /> }
};

const NEW_PERSON_VALUE = "__new_person__";
const INSPECTOR_RESIZE_STEP = 16;
const inspectorBounds = { min: 320, max: 640 };
const sourceUseModeOptions: { value: SourceUseMode; label: string; hint: string }[] = [
  {
    value: "verbatim_preferred",
    label: "Can quote/cite source",
    hint: "Use exact source language when Adam approves quoting it."
  },
  {
    value: "grounded_synthesis_allowed",
    label: "Can ground synthesis",
    hint: "Use facts or memories from this source to draft new prompt/response pairs."
  },
  {
    value: "context_only",
    label: "Context only",
    hint: "Useful for retrieval/background, but not as quote or generated response material."
  },
  {
    value: "exclude",
    label: "Exclude for now",
    hint: "Keep archived, but do not move downstream."
  }
];
const rubricIssueStatuses: { value: RubricIssueStatus; label: string }[] = [
  { value: "no_issues", label: "No issues" },
  { value: "minor_issues", label: "Minor issues" },
  { value: "major_issues", label: "Major issues" },
  { value: "not_applicable", label: "Not applicable" }
];

const goldReviewRubric = [
  {
    key: "voice_authenticity",
    label: "Voice authenticity",
    question: "Does this sound like Charles in this mode?",
    ratingKeys: ["voice_fidelity", "non_parody"],
    issueTags: ["not_charles_voice", "too_generic", "wrong_register", "overwritten_voice"]
  },
  {
    key: "grounding_truth",
    label: "Grounding / truth",
    question: "Is it faithful to the source and labeled truth status?",
    ratingKeys: ["grounding"],
    issueTags: ["invented_fact", "unsupported_inference", "wrong_truth_status", "source_mismatch"]
  },
  {
    key: "restraint",
    label: "Restraint",
    question: "Is it over-explained, sentimental, therapy-like, or too polished?",
    ratingKeys: ["restraint"],
    issueTags: ["too_sentimental", "too_therapy_like", "overexplained", "too_polished"]
  },
  {
    key: "concrete_detail",
    label: "Concrete detail",
    question: "Does it preserve specific lived/source details?",
    ratingKeys: ["concrete_detail", "emotional_truth"],
    issueTags: ["lost_specificity", "generic_detail", "missing_source_detail", "vague"]
  },
  {
    key: "prompt_fit",
    label: "Prompt fit",
    question: "Does it answer the actual prompt?",
    ratingKeys: ["mode_match"],
    issueTags: ["ignored_prompt", "wrong_shape", "too_long", "too_short"]
  },
  {
    key: "privacy_export_safety",
    label: "Privacy / export safety",
    question: "Is this safe to use downstream?",
    ratingKeys: ["privacy_export_safety"],
    issueTags: ["privacy_risk", "needs_redaction", "living_person_sensitive", "do_not_export"]
  }
] as const;

type GoldRubricKey = (typeof goldReviewRubric)[number]["key"];
type GoldRubricState = Record<GoldRubricKey, RubricDecision>;
type ResponseRubricState = {
  response_a: GoldRubricState;
  response_b: GoldRubricState;
};

const decisionPromptLabels: Record<string, string> = {
  source_genre: "What kind of document it is",
  authorship: "Who made it",
  creator_entity_ids: "Which person record made it",
  authorship_note: "How the creator relates to Charles or this source",
  fictionality_status: "Whether it is factual, fictional, mixed, memory, inference, or generated",
  truth_status: "Where its truth comes from",
  voice_presence: "Whether Charles's voice is present",
  adam_context_note: "Why Adam thinks it matters",
  privacy_level: "How private this source is",
  privacy_notes: "Why this privacy decision is right",
  ready_for_processing: "Whether this source should move to segmentation",
  vision_accuracy: "Whether the vision draft is accurate",
  accepted_visual_description: "Adam-reviewed visual description",
  accepted_tags: "Adam-reviewed visual tags",
  question_answers: "Answers to vision follow-up questions",
  ready_for_downstream: "Whether this vision metadata can move downstream",
  ocr_review_status: "Whether OCR/handwriting text is present and usable",
  corrected_ocr_text: "Adam-corrected OCR or handwriting text",
  ocr_truth_status: "Where the OCR/transcript truth comes from",
  segment_boundary_status: "Whether the selected chunks are usable boundaries",
  source_use_mode: "How selected source material may be used",
  source_use_modes: "Allowed source uses",
  usable_for_verbatim_quote: "Whether reviewed source text may be quoted",
  quote_policy: "Quote, redaction, or background-use policy",
  redaction_instructions: "What needs to be removed or generalized before use",
  privacy_clearance: "Privacy clearance for local generation and later export",
  boundary_rationale: "Privacy note",
  usable_for_voice_context: "Whether it can be used for voice context",
  usable_for_grounded_generation: "Whether it can ground generated responses",
  usable_for_sft: "Whether it can be used for SFT",
  usable_for_dpo: "Whether it can be used for DPO",
  charles_voice_presence: "Whether Charles's voice is actually present",
  charles_email_role: "Where Charles appears in the thread",
  other_voice_roles: "Who else is speaking",
  context_use: "How this source should be used",
  authenticity_value: "How authentic the signal is",
  voice_density: "Charles voice signal",
  charles_voice_signal: "Charles voice signal",
  notable_voice_evidence: "Notable voice evidence",
  prompt_intent: "What kind of prompt/response pair to make",
  source_chunks_to_use: "Which reviewed source chunks to use",
  chunk_adjustment_requested: "Whether the chunk should be split, merged, approved, or held",
  segmentation_notes: "What should change about the segmentation",
  whole_source_context_mode: "How the whole source remains available",
  ready_for_prompt_pair_factory: "Whether approved chunks can move to Prompt Pair Factory",
  target_response_shape: "What shape the response should take",
  boundary_clearance_needed: "What privacy check is needed before export",
  prompt_text: "Prompt text for the candidate pair",
  model_draft: "Draft rejected/pre-edit side",
  adam_gold_edit: "What Adam changed into the preferred version",
  response_rubric: "Response A and B issue comparison",
  rubric_summary: "Rubric-derived export readiness",
  ratings: "Rubric-derived quality signals",
  failure_modes: "Rubric-derived rejected-side failure modes",
  export_flags: "Which downstream examples to create"
};

function payloadString(value: unknown, fallback = ""): string {
  return typeof value === "string" ? value : fallback;
}

function labelFromKey(value: string): string {
  return value
    .split("_")
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(" ");
}

function promptFromDecisionKey(value: string): string {
  return decisionPromptLabels[value] ?? labelFromKey(value);
}

function taskDisplayTitle(task: Task): string {
  const payload = task.input_payload;
  for (const key of ["source_filename", "source_title", "asset_title", "title", "segment_title", "prompt"]) {
    const value = payload[key];
    if (typeof value === "string" && value.trim()) {
      return value;
    }
  }
  return task.human_id;
}

function locatorNumber(locator: Record<string, unknown>, key: string, fallback = 0): number {
  const value = locator[key];
  return typeof value === "number" ? value : fallback;
}

function payloadArray(value: unknown): string[] {
  return Array.isArray(value) ? value.map(String) : [];
}

function parseList(value: string): string[] {
  return value
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
}

function uniqueValues(values: string[]): string[] {
  return Array.from(new Set(values.filter(Boolean)));
}

function formatMetadataValue(value: unknown, fallback = "Not answered"): string {
  if (Array.isArray(value)) {
    return value.length > 0 ? value.map(String).join(", ") : fallback;
  }
  if (typeof value === "boolean") {
    return value ? "Yes" : "No";
  }
  if (typeof value === "number") {
    return String(value);
  }
  if (typeof value === "string") {
    return value.trim() ? labelFromKey(value) : fallback;
  }
  if (value && typeof value === "object") {
    return JSON.stringify(value);
  }
  return fallback;
}

function formatFreeTextValue(value: unknown, fallback = "Not answered"): string {
  if (Array.isArray(value)) {
    return value.length > 0 ? value.map(String).join(", ") : fallback;
  }
  if (typeof value === "string") {
    return value.trim() || fallback;
  }
  return formatMetadataValue(value, fallback);
}

function sourceReviewDigestItems(decisions: Decisions) {
  return [
    { label: "Segment title", value: formatFreeTextValue(decisions.segment_title) },
    { label: "Document kind", value: formatMetadataValue(decisions.source_genre) },
    { label: "Creator", value: formatFreeTextValue(decisions.creator_name || decisions.authorship) },
    { label: "Authorship note", value: formatFreeTextValue(decisions.authorship_note) },
    { label: "Truth source", value: formatMetadataValue(decisions.truth_status) },
    { label: "Factual or fictional", value: formatMetadataValue(decisions.fictionality_status) },
    { label: "Charles voice", value: formatMetadataValue(decisions.voice_presence) },
    { label: "Who it is about", value: formatFreeTextValue(decisions.people) },
    { label: "Where it is about", value: formatFreeTextValue(decisions.places) },
    { label: "When", value: formatFreeTextValue(decisions.date_or_range) },
    { label: "Why it matters", value: formatFreeTextValue(decisions.adam_context_note) },
    { label: "Privacy", value: formatMetadataValue(decisions.privacy_level) },
    { label: "Ready for segmentation", value: formatMetadataValue(decisions.ready_for_processing) }
  ];
}

function visionDigestItems(decisions: Decisions) {
  return [
    { label: "Vision accuracy", value: formatMetadataValue(decisions.vision_accuracy) },
    { label: "Description", value: formatFreeTextValue(decisions.accepted_visual_description) },
    { label: "People", value: formatFreeTextValue(decisions.people) },
    { label: "Places", value: formatFreeTextValue(decisions.places) },
    { label: "When", value: formatFreeTextValue(decisions.date_or_range) },
    { label: "Tags", value: formatFreeTextValue(decisions.accepted_tags) },
    { label: "OCR status", value: formatMetadataValue(decisions.ocr_review_status) },
    { label: "Privacy", value: formatMetadataValue(decisions.privacy_level) },
    { label: "Ready downstream", value: formatMetadataValue(decisions.ready_for_downstream) },
    { label: "Why it matters", value: formatFreeTextValue(decisions.adam_context_note) }
  ];
}

function segmentBoundaryDigestItems(decisions: Decisions) {
  const selectedChunkCount = typeof decisions.selected_chunk_count === "number" ? decisions.selected_chunk_count : 0;
  const factoryReady =
    selectedChunkCount > 0 && decisions.ready_for_prompt_pair_factory === "yes" ? "yes" : "no";
  return [
    { label: "Boundary status", value: formatMetadataValue(decisions.segment_boundary_status) },
    { label: "Selected chunks", value: formatMetadataValue(selectedChunkCount) },
    { label: "Chunk scope", value: formatMetadataValue(decisions.chunk_scope) },
    { label: "Allowed uses", value: formatMetadataValue(decisions.source_use_modes || decisions.source_use_mode) },
    { label: "Quote policy", value: formatMetadataValue(decisions.quote_policy) },
    { label: "Prompt-pair material", value: formatMetadataValue(decisions.prompt_pair_decision || decisions.prompt_pair_potential) },
    { label: "Prompt factory ready", value: formatMetadataValue(factoryReady) },
    { label: "Privacy clearance", value: formatMetadataValue(decisions.privacy_clearance) },
    { label: "Privacy", value: formatMetadataValue(decisions.privacy_level) },
    { label: "Redaction", value: formatMetadataValue(decisions.redaction_required) },
    { label: "Segmentation note", value: formatFreeTextValue(decisions.segmentation_notes) }
  ];
}

function genericDecisionDigestItems(decisions: Decisions) {
  return Object.entries(decisions)
    .slice(0, 12)
    .map(([key, value]) => ({
      label: promptFromDecisionKey(key),
      value: formatFreeTextValue(value)
    }));
}

function isRubricIssueStatus(value: unknown): value is RubricIssueStatus {
  return rubricIssueStatuses.some((option) => option.value === value);
}

function emptyGoldRubricState(): GoldRubricState {
  const state = {} as GoldRubricState;
  goldReviewRubric.forEach((criterion) => {
    state[criterion.key] = {
      status: "no_issues",
      notes: "",
      issue_tags: []
    };
  });
  return state;
}

function readRubricDecision(value: unknown): RubricDecision | null {
  if (!value || typeof value !== "object") {
    return null;
  }
  const record = value as Record<string, unknown>;
  return {
    status: isRubricIssueStatus(record.status) ? record.status : "no_issues",
    notes: typeof record.notes === "string" ? record.notes : "",
    issue_tags: payloadArray(record.issue_tags)
  };
}

function applyStoredRubric(rubric: GoldRubricState, storedRubric: Record<string, unknown> | null): boolean {
  if (!storedRubric) {
    return false;
  }
  let found = false;
  goldReviewRubric.forEach((criterion) => {
    const storedDecision = readRubricDecision(storedRubric[criterion.key]);
    if (storedDecision) {
      rubric[criterion.key] = storedDecision;
      found = true;
    }
  });
  return found;
}

function goldRubricFromStored(value: unknown): GoldRubricState | null {
  if (!value || typeof value !== "object") {
    return null;
  }
  const rubric = emptyGoldRubricState();
  return applyStoredRubric(rubric, value as Record<string, unknown>) ? rubric : null;
}

function goldRubricFromDecisions(decisions: Decisions, ratings: Record<string, unknown>, failureModes: string[]): GoldRubricState {
  const rubric = emptyGoldRubricState();
  const storedRubric = decisions.response_rubric && typeof decisions.response_rubric === "object"
    ? (decisions.response_rubric as Record<string, unknown>).response_a
    : ratings.response_rubric && typeof ratings.response_rubric === "object"
      ? (ratings.response_rubric as Record<string, unknown>).response_a
      : null;

  if (applyStoredRubric(rubric, storedRubric && typeof storedRubric === "object" ? (storedRubric as Record<string, unknown>) : null)) {
    return rubric;
  }

  if (failureModes.length > 0) {
    goldReviewRubric.forEach((criterion) => {
      const matchingTags = failureModes.filter((mode) => (criterion.issueTags as readonly string[]).includes(mode));
      if (matchingTags.length > 0) {
        rubric[criterion.key] = {
          status: "minor_issues",
          notes: "",
          issue_tags: matchingTags
        };
      }
    });
  }

  return rubric;
}

function responseRubricFromDecisions(
  decisions: Decisions,
  ratings: Record<string, unknown>,
  failureModes: string[]
): ResponseRubricState {
  const storedResponseRubric =
    decisions.response_rubric && typeof decisions.response_rubric === "object"
      ? (decisions.response_rubric as Record<string, unknown>)
      : ratings.response_rubric && typeof ratings.response_rubric === "object"
        ? (ratings.response_rubric as Record<string, unknown>)
        : null;
  const storedResponseA = storedResponseRubric ? goldRubricFromStored(storedResponseRubric.response_a) : null;
  const storedResponseB = storedResponseRubric ? goldRubricFromStored(storedResponseRubric.response_b) : null;

  return {
    response_a: storedResponseA ?? goldRubricFromDecisions(decisions, ratings, failureModes),
    response_b: storedResponseB ?? emptyGoldRubricState()
  };
}

function rubricStatusScore(status: RubricIssueStatus): number {
  if (status === "major_issues") {
    return 1;
  }
  if (status === "minor_issues") {
    return 3;
  }
  if (status === "not_applicable") {
    return 0;
  }
  return 5;
}

function deriveRubricRatings(rubric: GoldRubricState): Record<string, number> {
  return goldReviewRubric.reduce<Record<string, number>>((nextRatings, criterion) => {
    const score = rubricStatusScore(rubric[criterion.key].status);
    criterion.ratingKeys.forEach((ratingKey) => {
      nextRatings[ratingKey] = score;
    });
    return nextRatings;
  }, {});
}

function deriveFailureModes(rubric: GoldRubricState): string[] {
  return uniqueValues(
    goldReviewRubric.map((criterion) => {
      const decision = rubric[criterion.key];
      if (decision.status !== "minor_issues" && decision.status !== "major_issues") {
        return "";
      }
      const note = decision.notes.trim();
      return note ? `${criterion.label}: ${note}` : `${criterion.label}: ${labelFromKey(decision.status)}`;
    })
  );
}

function deriveRubricSummary(rubric: GoldRubricState) {
  const issueCriteria = goldReviewRubric.filter((criterion) => {
    const status = rubric[criterion.key].status;
    return status === "minor_issues" || status === "major_issues";
  });
  const majorIssueCriteria = issueCriteria.filter((criterion) => rubric[criterion.key].status === "major_issues");
  const privacyStatus = rubric.privacy_export_safety.status;
  return {
    issue_count: issueCriteria.length,
    major_issue_count: majorIssueCriteria.length,
    has_major_issues: majorIssueCriteria.length > 0,
    privacy_export_blocked: privacyStatus === "major_issues",
    sft_ready: majorIssueCriteria.length === 0 && privacyStatus !== "major_issues",
    dpo_reason_count: deriveFailureModes(rubric).length
  };
}

function deriveResponseRubricSummary(responseA: GoldRubricState, responseB: GoldRubricState) {
  const responseASummary = deriveRubricSummary(responseA);
  const responseBSummary = deriveRubricSummary(responseB);
  const responseAFailureModes = deriveFailureModes(responseA);
  const responseBFailureModes = deriveFailureModes(responseB);
  return {
    response_a: responseASummary,
    response_b: responseBSummary,
    rejected_issue_count: responseASummary.issue_count,
    preferred_issue_count: responseBSummary.issue_count,
    preferred_major_issue_count: responseBSummary.major_issue_count,
    preferred_export_blocked: responseBSummary.privacy_export_blocked,
    sft_ready: responseBSummary.sft_ready,
    dpo_reason_count: responseAFailureModes.length,
    preferred_failure_mode_count: responseBFailureModes.length
  };
}

function rubricNotesSummary(rubric: GoldRubricState): string {
  return goldReviewRubric
    .map((criterion) => {
      const decision = rubric[criterion.key];
      if ((decision.status !== "minor_issues" && decision.status !== "major_issues") || !decision.notes.trim()) {
        return "";
      }
      return `${criterion.label}: ${decision.notes.trim()}`;
    })
    .filter(Boolean)
    .join("\n");
}

function decisionString(decisions: Decisions, key: string, fallback = ""): string {
  const value = decisions[key];
  return typeof value === "string" ? value : fallback;
}

function decisionNumber(decisions: Decisions, key: string, fallback: number): number {
  const value = decisions[key];
  return typeof value === "number" ? value : fallback;
}

function decisionListText(decisions: Decisions, key: string, fallback = ""): string {
  const value = decisions[key];
  return Array.isArray(value) ? value.map(String).join(", ") : fallback;
}

function decisionStringList(decisions: Decisions, key: string, fallback: string[] = []): string[] {
  const value = decisions[key];
  return Array.isArray(value) ? value.map(String).filter(Boolean) : fallback;
}

function decisionBoolean(decisions: Decisions, key: string, fallback: boolean): boolean {
  const value = decisions[key];
  if (typeof value === "boolean") {
    return value;
  }
  if (typeof value === "string") {
    return value.toLowerCase() === "yes" || value.toLowerCase() === "true";
  }
  return fallback;
}

function isSourceUseMode(value: string): value is SourceUseMode {
  return sourceUseModeOptions.some((option) => option.value === value);
}

function normalizeSourceUseModes(values: string[]): SourceUseMode[] {
  const normalized = uniqueValues(values).filter(isSourceUseMode);
  if (normalized.includes("exclude")) {
    return ["exclude"];
  }
  return normalized.length > 0 ? normalized : ["verbatim_preferred", "grounded_synthesis_allowed"];
}

function primarySourceUseMode(values: SourceUseMode[]): SourceUseMode {
  if (values.includes("exclude")) {
    return "exclude";
  }
  if (values.includes("grounded_synthesis_allowed")) {
    return "grounded_synthesis_allowed";
  }
  if (values.includes("verbatim_preferred")) {
    return "verbatim_preferred";
  }
  return "context_only";
}

function promptPairDecisionFromPotential(value: string): string {
  if (value === "high" || value === "medium") {
    return "yes";
  }
  if (value === "low") {
    return "later";
  }
  return "no";
}

function promptPairPotentialFromDecision(value: string): string {
  if (value === "yes") {
    return "high";
  }
  if (value === "later") {
    return "low";
  }
  return "none";
}

function clamp(value: number, min: number, max: number): number {
  return Math.min(Math.max(value, min), max);
}

function entityOptionLabel(entity: Entity): string {
  const relationships = [entity.relationship_to_charles, entity.relationship_to_adam].filter(Boolean).join(" / ");
  return relationships ? `${entity.canonical_name} (${relationships})` : entity.canonical_name;
}

function Field({ label, hint, children }: { label: string; hint?: string; children: React.ReactNode }) {
  return (
    <label className="field">
      <span className="field-label">{label}</span>
      {hint ? <small>{hint}</small> : null}
      {children}
    </label>
  );
}

function tooltip(text: string): { title: string } {
  return { title: text };
}

function formatDraftTime(value: string | null): string {
  if (!value) {
    return "";
  }
  return new Intl.DateTimeFormat(undefined, {
    hour: "numeric",
    minute: "2-digit",
    second: "2-digit"
  }).format(new Date(value));
}

function LinePreview({ text, className = "" }: { text: string; className?: string }) {
  const lines = text.split(/\r?\n/);
  return (
    <div className={["line-preview", className].filter(Boolean).join(" ")}>
      {lines.map((line, index) => (
        <div className="line-row" key={`${index}-${line.slice(0, 12)}`}>
          <span>{index + 1}</span>
          <code>{line || " "}</code>
        </div>
      ))}
    </div>
  );
}

function FormHint({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="form-hint">
      <strong>{title}</strong>
      <p>{children}</p>
    </div>
  );
}

function MetadataValueList({
  title,
  items
}: {
  title: string;
  items: { label: string; value: string }[];
}) {
  return (
    <section className="metadata-value-list">
      <span>{title}</span>
      {items.map((item) => (
        <div key={item.label}>
          <strong>{item.label}</strong>
          <p>{item.value}</p>
        </div>
      ))}
    </section>
  );
}

function TextArea({
  value,
  onChange,
  rows = 4
}: {
  value: string;
  onChange: (value: string) => void;
  rows?: number;
}) {
  return <textarea rows={rows} value={value} onChange={(event) => onChange(event.target.value)} />;
}

function Select({
  value,
  onChange,
  options
}: {
  value: string;
  onChange: (value: string) => void;
  options: string[];
}) {
  return (
    <select value={value} onChange={(event) => onChange(event.target.value)}>
      {options.map((option) => (
        <option key={option} value={option}>
          {labelFromKey(option)}
        </option>
      ))}
    </select>
  );
}

function SourcePreview({ task }: { task: Task }) {
  const previewText =
    payloadString(task.input_payload.preview_text) ||
    payloadString(task.input_payload.source_excerpt) ||
    payloadString(task.input_payload.text);
  if (!previewText) {
    return null;
  }
  const emailHeaders =
    task.input_payload.email_headers && typeof task.input_payload.email_headers === "object"
      ? (task.input_payload.email_headers as Record<string, unknown>)
      : null;

  return (
    <section className={emailHeaders ? "source-text has-email" : "source-text"}>
      <div className="source-text-header">
        <span>Source text</span>
        <strong>
          {payloadString(task.input_payload.source_filename) ||
            payloadString(task.input_payload.source_title) ||
            payloadString(task.input_payload.asset_title)}
        </strong>
      </div>
      {emailHeaders ? (
        <div className="source-text-email">
          {payloadString(emailHeaders.subject) ? <span>Subject: {payloadString(emailHeaders.subject)}</span> : null}
          {payloadString(emailHeaders.from) ? <span>From: {payloadString(emailHeaders.from)}</span> : null}
          {payloadString(emailHeaders.to) ? <span>To: {payloadString(emailHeaders.to)}</span> : null}
          {payloadString(emailHeaders.date) ? <span>Date: {payloadString(emailHeaders.date)}</span> : null}
        </div>
      ) : null}
      <LinePreview text={previewText} className="source-line-preview" />
      {typeof task.input_payload.chunk_count === "number" || typeof task.input_payload.total_chars === "number" ? (
        <div className="source-text-meta">
          {typeof task.input_payload.chunk_count === "number" ? <span>{task.input_payload.chunk_count} chunks</span> : null}
          {typeof task.input_payload.total_chars === "number" ? <span>{task.input_payload.total_chars} chars extracted</span> : null}
          {task.input_payload.truncated ? <span>preview capped</span> : null}
        </div>
      ) : null}
    </section>
  );
}

function PhotoAssetPreview({ task }: { task: Task }) {
  const assetId = payloadString(task.input_payload.asset_id) || (task.target_type === "asset" ? task.target_id : "");
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    setFailed(false);
  }, [assetId, task.id]);

  if (!assetId) {
    return null;
  }

  const title =
    payloadString(task.input_payload.source_filename) ||
    payloadString(task.input_payload.asset_title) ||
    payloadString(task.input_payload.title) ||
    "Photo source";

  return (
    <section className="photo-preview-panel">
      <div className="photo-preview-header">
        <span>Photo preview</span>
        <strong>{title}</strong>
      </div>
      <div className="photo-preview-stage">
        {failed ? (
          <div className="photo-preview-empty">
            <Image size={24} />
            <span>Mirrored image preview is not available for this source yet.</span>
          </div>
        ) : (
          <img src={getAssetPreviewUrl(assetId)} alt={title} onError={() => setFailed(true)} />
        )}
      </div>
    </section>
  );
}

function EditableExtraction({
  task,
  activeChunk,
  initialCleanedText,
  onChange
}: {
  task: Task;
  activeChunk?: Segment;
  initialCleanedText?: string;
  onChange: (value: Decisions) => void;
}) {
  const previewText =
    payloadString(task.input_payload.preview_text) ||
    payloadString(task.input_payload.source_excerpt) ||
    payloadString(task.input_payload.text);
  const activeChunkId = activeChunk?.id ?? "";
  const [cleanedText, setCleanedText] = useState(initialCleanedText || activeChunk?.text_content || previewText);

  useEffect(() => {
    setCleanedText(initialCleanedText || activeChunk?.text_content || previewText);
  }, [activeChunkId, activeChunk?.text_content, initialCleanedText, previewText, task.id]);

  useEffect(() => {
    onChange({
      cleaned_text: cleanedText,
      cleaned_text_scope: activeChunk ? "active_chunk" : "preview",
      cleaned_text_chunk_id: activeChunk?.id ?? null,
      extraction_edit_notes: cleanedText === (activeChunk?.text_content || previewText) ? "unchanged" : "edited"
    });
  }, [activeChunk, cleanedText, onChange, previewText]);

  if (!previewText && !activeChunk) {
    return null;
  }

  return (
    <section className="editable-extraction">
      <div>
        <span>Derived working version</span>
        <strong>{activeChunk ? "Active chunk" : "Preview copy"}</strong>
      </div>
      <TextArea value={cleanedText} onChange={setCleanedText} rows={8} />
      <div className="editor-foot">
        <span>{cleanedText.length} chars</span>
        <span>{cleanedText === (activeChunk?.text_content || previewText) ? "Unchanged" : "Edited"}</span>
      </div>
    </section>
  );
}

function ChunkBrowser({
  task,
  initialSelection,
  onChange
}: {
  task: Task;
  initialSelection: ChunkSelection;
  onChange: (selection: ChunkSelection, activeChunk?: Segment) => void;
}) {
  const assetId = payloadString(task.input_payload.asset_id);
  const [chunks, setChunks] = useState<Segment[]>([]);
  const [activeId, setActiveId] = useState(initialSelection.active_chunk_id ?? "");
  const [selectedIds, setSelectedIds] = useState<string[]>(initialSelection.selected_chunk_ids);
  const [error, setError] = useState("");
  const activeChunk = chunks.find((chunk) => chunk.id === activeId) ?? chunks[0];

  useEffect(() => {
    setChunks([]);
    setActiveId(initialSelection.active_chunk_id ?? "");
    setSelectedIds(initialSelection.selected_chunk_ids);
    setError("");
    if (!assetId) {
      return;
    }

    let cancelled = false;
    getAssetTextChunks(assetId)
      .then((nextChunks) => {
        if (cancelled) {
          return;
        }
        setChunks(nextChunks);
        setActiveId(initialSelection.active_chunk_id ?? nextChunks[0]?.id ?? "");
      })
      .catch((caught: unknown) => {
        if (!cancelled) {
          setError(caught instanceof Error ? caught.message : "Unable to load chunks.");
        }
      });

    return () => {
      cancelled = true;
    };
  }, [assetId, initialSelection.active_chunk_id, initialSelection.selected_chunk_ids, task.id]);

  useEffect(() => {
    onChange({
      chunk_scope: selectedIds.length > 0 ? "selected_chunks" : "preview_only",
      selected_chunk_ids: selectedIds,
      active_chunk_id: activeChunk?.id,
      selected_chunk_count: selectedIds.length
    }, activeChunk);
  }, [activeChunk, onChange, selectedIds]);

  if (!assetId || (chunks.length === 0 && !error)) {
    return null;
  }

  function toggleChunk(chunkId: string) {
    setSelectedIds((current) =>
      current.includes(chunkId) ? current.filter((id) => id !== chunkId) : [...current, chunkId]
    );
  }

  return (
    <section className="chunk-browser">
      <div className="chunk-browser-header">
        <div>
          <span>Extracted chunks</span>
          <strong>{chunks.length} available</strong>
        </div>
        <div className="chunk-actions">
          <button type="button" onClick={() => setSelectedIds(chunks.map((chunk) => chunk.id))} disabled={chunks.length === 0}>
            Select all
          </button>
          <button type="button" onClick={() => setSelectedIds([])} disabled={selectedIds.length === 0}>
            Clear
          </button>
        </div>
      </div>
      {error ? <p className="quiet">{error}</p> : null}
      {chunks.length > 0 ? (
        <div className="chunk-workspace">
          <div className="chunk-list" aria-label="Extracted text chunks">
            {chunks.map((chunk, index) => {
              const chunkIndex = locatorNumber(chunk.locator, "chunk_index", index + 1);
              const selected = selectedIds.includes(chunk.id);
              const className = ["chunk-row", chunk.id === activeChunk?.id ? "active" : "", selected ? "selected" : ""]
                .filter(Boolean)
                .join(" ");
              return (
                <div className={className} key={chunk.id}>
                  <button type="button" onClick={() => setActiveId(chunk.id)}>
                    Chunk {chunkIndex}
                  </button>
                  <input
                    type="checkbox"
                    checked={selected}
                    onChange={() => toggleChunk(chunk.id)}
                    aria-label={`Select chunk ${chunkIndex}`}
                  />
                </div>
              );
            })}
          </div>
          {activeChunk ? (
            <div className="chunk-detail">
              <div className="chunk-detail-meta">
                <span>Chunk {locatorNumber(activeChunk.locator, "chunk_index", 1)}</span>
                <span>
                  chars {locatorNumber(activeChunk.locator, "char_start")}-
                  {locatorNumber(activeChunk.locator, "char_end")}
                </span>
              </div>
              <LinePreview text={activeChunk.text_content ?? ""} className="chunk-line-preview" />
            </div>
          ) : null}
        </div>
      ) : null}
    </section>
  );
}

function Toggle({
  label,
  checked,
  onChange,
  disabled = false
}: {
  label: string;
  checked: boolean;
  onChange: (checked: boolean) => void;
  disabled?: boolean;
}) {
  return (
    <label className="toggle">
      <input type="checkbox" checked={checked} disabled={disabled} onChange={(event) => onChange(event.target.checked)} />
      <span>{labelFromKey(label)}</span>
    </label>
  );
}

function Rating({
  label,
  value,
  onChange
}: {
  label: string;
  value: number;
  onChange: (value: number) => void;
}) {
  return (
    <label className="rating">
      <span>{labelFromKey(label)}</span>
      <input
        type="range"
        min={1}
        max={5}
        value={value}
        onChange={(event) => onChange(Number(event.target.value))}
      />
      <strong>{value}</strong>
    </label>
  );
}

function RubricIssueCard({
  criterion,
  decision,
  noteLabel,
  noteHint,
  onChange
}: {
  criterion: (typeof goldReviewRubric)[number];
  decision: RubricDecision;
  noteLabel: string;
  noteHint: string;
  onChange: (decision: RubricDecision) => void;
}) {
  const needsIssueDetail = decision.status === "minor_issues" || decision.status === "major_issues";

  function updateStatus(status: RubricIssueStatus) {
    onChange({
      ...decision,
      status,
      issue_tags: []
    });
  }

  return (
    <section className="rubric-card">
      <div className="rubric-card-header">
        <div>
          <strong>{criterion.label}</strong>
          <p>{criterion.question}</p>
        </div>
        <span>{labelFromKey(decision.status)}</span>
      </div>
      <div className="rubric-options">
        {rubricIssueStatuses.map((option) => (
          <button
            type="button"
            key={option.value}
            className={decision.status === option.value ? "active" : ""}
            onClick={() => updateStatus(option.value)}
          >
            {option.label}
          </button>
        ))}
      </div>
      {needsIssueDetail ? (
        <div className="rubric-issue-detail">
          <Field label={noteLabel} hint={noteHint}>
            <TextArea value={decision.notes} onChange={(notes) => onChange({ ...decision, notes })} rows={3} />
          </Field>
        </div>
      ) : null}
    </section>
  );
}

function AssetTriageForm({
  task,
  initialDecisions,
  onChange
}: {
  task: Task;
  initialDecisions: Decisions;
  onChange: (value: Decisions) => void;
}) {
  const payload = task.input_payload;
  const [sourceType, setSourceType] = useState(decisionString(initialDecisions, "source_type", payloadString(payload.source_type, "unknown")));
  const [importance, setImportance] = useState(decisionString(initialDecisions, "importance", "medium"));
  const [privacy, setPrivacy] = useState(decisionString(initialDecisions, "initial_privacy_level", "unreviewed"));
  const [processNext, setProcessNext] = useState(decisionString(initialDecisions, "process_next", "yes"));
  const [triageNotes, setTriageNotes] = useState(decisionString(initialDecisions, "notes"));

  useEffect(() => {
    onChange({
      source_type: sourceType,
      importance,
      initial_privacy_level: privacy,
      process_next: processNext,
      notes: triageNotes
    });
  }, [sourceType, importance, privacy, processNext, triageNotes, onChange]);

  return (
    <div className="form-grid">
      <Field label="Source type">
        <Select
          value={sourceType}
          onChange={setSourceType}
          options={["email", "journal", "memoir", "photo", "audio", "scan", "document", "unknown"]}
        />
      </Field>
      <Field label="Importance">
        <Select value={importance} onChange={setImportance} options={["low", "medium", "high", "sacred"]} />
      </Field>
      <Field label="Initial privacy">
        <Select value={privacy} onChange={setPrivacy} options={["unreviewed", "family_private", "sensitive", "sealed"]} />
      </Field>
      <Field label="Process next">
        <Select value={processNext} onChange={setProcessNext} options={["yes", "no", "later"]} />
      </Field>
      <Field label="Notes">
        <TextArea value={triageNotes} onChange={setTriageNotes} />
      </Field>
    </div>
  );
}

function PhotoContextForm({
  task,
  initialDecisions,
  onChange
}: {
  task: Task;
  initialDecisions: Decisions;
  onChange: (value: Decisions) => void;
}) {
  const payload = task.input_payload;
  const [visiblePeople, setVisiblePeople] = useState(
    decisionListText(initialDecisions, "visible_people", payloadArray(payload.machine_guess_people).join(", "))
  );
  const [absentPeople, setAbsentPeople] = useState(decisionListText(initialDecisions, "absent_but_relevant_people"));
  const [place, setPlace] = useState(decisionString(initialDecisions, "place", payloadString(payload.machine_guess_place, "unknown")));
  const [dateRange, setDateRange] = useState(decisionString(initialDecisions, "date_or_range", "unknown"));
  const [dateConfidence, setDateConfidence] = useState(decisionString(initialDecisions, "date_confidence", "unknown"));
  const [event, setEvent] = useState(decisionString(initialDecisions, "event", "unknown"));
  const [description, setDescription] = useState(decisionString(initialDecisions, "visual_description_correction"));
  const [invisibleContext, setInvisibleContext] = useState(decisionString(initialDecisions, "invisible_context_note"));
  const [memoryPotential, setMemoryPotential] = useState(decisionNumber(initialDecisions, "memory_potential", 4));
  const [privacySensitivity, setPrivacySensitivity] = useState(decisionNumber(initialDecisions, "privacy_sensitivity", 2));
  const [galleryEligibility, setGalleryEligibility] = useState(decisionString(initialDecisions, "gallery_eligibility", "family_private"));

  useEffect(() => {
    onChange({
      visible_people: parseList(visiblePeople),
      absent_but_relevant_people: parseList(absentPeople),
      place,
      date_or_range: dateRange,
      date_confidence: dateConfidence,
      event,
      visual_description_correction: description,
      invisible_context_note: invisibleContext,
      memory_potential: memoryPotential,
      privacy_sensitivity: privacySensitivity,
      gallery_eligibility: galleryEligibility,
      link_to_memory: "existing"
    });
  }, [
    absentPeople,
    dateConfidence,
    dateRange,
    description,
    event,
    galleryEligibility,
    invisibleContext,
    memoryPotential,
    onChange,
    place,
    privacySensitivity,
    visiblePeople
  ]);

  return (
    <div className="form-grid">
      <FormHint title="Photo context">
        Add the who, where, when, and the invisible context that a stranger would miss from the image alone.
      </FormHint>
      <Field label="Who is visible?">
        <input value={visiblePeople} onChange={(event) => setVisiblePeople(event.target.value)} />
      </Field>
      <Field label="Who matters but is not visible?">
        <input value={absentPeople} onChange={(event) => setAbsentPeople(event.target.value)} />
      </Field>
      <Field label="Where is this?">
        <input value={place} onChange={(event) => setPlace(event.target.value)} />
      </Field>
      <Field label="When is it from?">
        <input value={dateRange} onChange={(event) => setDateRange(event.target.value)} />
      </Field>
      <Field label="How sure is the date?">
        <Select value={dateConfidence} onChange={setDateConfidence} options={["exact", "year", "decade", "unknown"]} />
      </Field>
      <Field label="What event or moment is this?">
        <input value={event} onChange={(event) => setEvent(event.target.value)} />
      </Field>
      <Field label="What should the visual description say?">
        <TextArea value={description} onChange={setDescription} />
      </Field>
      <Field label="What context is not visible?">
        <TextArea rows={5} value={invisibleContext} onChange={setInvisibleContext} />
      </Field>
      <Rating label="Memory potential" value={memoryPotential} onChange={setMemoryPotential} />
      <Rating label="Privacy sensitivity" value={privacySensitivity} onChange={setPrivacySensitivity} />
      <Field label="Gallery eligibility">
        <Select value={galleryEligibility} onChange={setGalleryEligibility} options={["none", "family_private", "public_candidate"]} />
      </Field>
    </div>
  );
}

function VisionDraftReviewForm({
  task,
  initialDecisions,
  onChange
}: {
  task: Task;
  initialDecisions: Decisions;
  onChange: (value: Decisions) => void;
}) {
  const draft = task.input_payload.vision_draft && typeof task.input_payload.vision_draft === "object"
    ? (task.input_payload.vision_draft as Record<string, unknown>)
    : {};
  const questions = Array.isArray(task.input_payload.suggested_questions)
    ? (task.input_payload.suggested_questions as Record<string, unknown>[])
    : [];
  const initialQuestionAnswers =
    initialDecisions.question_answers && typeof initialDecisions.question_answers === "object"
      ? (initialDecisions.question_answers as Record<string, unknown>)
      : {};
  const [visionAccuracy, setVisionAccuracy] = useState(decisionString(initialDecisions, "vision_accuracy", "not_applicable"));
  const [description, setDescription] = useState(
    decisionString(initialDecisions, "accepted_visual_description", payloadString(draft.visual_summary))
  );
  const [people, setPeople] = useState(
    decisionListText(initialDecisions, "people", payloadArray(draft.visible_people).join(", "))
  );
  const [places, setPlaces] = useState(
    decisionListText(initialDecisions, "places", payloadArray(draft.places).join(", "))
  );
  const [dateRange, setDateRange] = useState(
    decisionString(initialDecisions, "date_or_range", payloadString(draft.time_period_guess, "unknown"))
  );
  const [tags, setTags] = useState(
    decisionListText(
      initialDecisions,
      "accepted_tags",
      [...payloadArray(draft.objects), ...payloadArray(draft.themes)].join(", ")
    )
  );
  const [objects, setObjects] = useState(decisionListText(initialDecisions, "concrete_objects", payloadArray(draft.objects).join(", ")));
  const [rejectedInferences, setRejectedInferences] = useState(decisionListText(initialDecisions, "rejected_system_inferences"));
  const [questionAnswers, setQuestionAnswers] = useState<Record<string, string>>(() =>
    Object.fromEntries(Object.entries(initialQuestionAnswers).map(([key, value]) => [key, String(value ?? "")]))
  );
  const [adamContextNote, setAdamContextNote] = useState(decisionString(initialDecisions, "adam_context_note"));
  const [privacyLevel, setPrivacyLevel] = useState(decisionString(initialDecisions, "privacy_level", "family_private"));
  const [privacyNotes, setPrivacyNotes] = useState(decisionString(initialDecisions, "privacy_notes"));
  const [readyForDownstream, setReadyForDownstream] = useState(decisionString(initialDecisions, "ready_for_downstream", "later"));
  const [ocrReviewStatus, setOcrReviewStatus] = useState(decisionString(initialDecisions, "ocr_review_status", "not_present"));
  const [ocrTruthStatus, setOcrTruthStatus] = useState(decisionString(initialDecisions, "ocr_truth_status", "system_inference"));
  const [correctedOcrText, setCorrectedOcrText] = useState(
    decisionString(initialDecisions, "corrected_ocr_text", payloadString(draft.handwriting_text) || payloadString(draft.ocr_text))
  );

  useEffect(() => {
    onChange({
      vision_accuracy: visionAccuracy,
      accepted_visual_description: description,
      people: parseList(people),
      places: parseList(places),
      date_or_range: dateRange,
      accepted_tags: parseList(tags),
      themes: parseList(tags),
      concrete_objects: parseList(objects),
      rejected_system_inferences: parseList(rejectedInferences),
      question_answers: questionAnswers,
      adam_context_note: adamContextNote,
      privacy_level: privacyLevel,
      privacy_notes: privacyNotes,
      ready_for_downstream: readyForDownstream,
      ocr_review_status: ocrReviewStatus,
      ocr_truth_status: ocrTruthStatus,
      corrected_ocr_text: correctedOcrText,
      source_genre: payloadString(task.input_payload.asset_type, "photo"),
      truth_status: "system_inference",
      voice_presence: "absent"
    });
  }, [
    adamContextNote,
    correctedOcrText,
    dateRange,
    description,
    objects,
    ocrReviewStatus,
    ocrTruthStatus,
    onChange,
    people,
    places,
    privacyLevel,
    privacyNotes,
    questionAnswers,
    readyForDownstream,
    rejectedInferences,
    tags,
    task.input_payload.asset_type,
    visionAccuracy
  ]);

  function updateQuestionAnswer(questionId: string, value: string) {
    setQuestionAnswers((current) => ({ ...current, [questionId]: value }));
  }

  return (
    <div className="form-grid source-question-grid">
      <FormHint title="Vision draft">
        Treat this as machine help, not truth. Accept what is useful, correct what is wrong, answer the follow-up questions, and set privacy before downstream use.
      </FormHint>
      <Field label="Is the vision draft accurate?" hint="No live model call has been made for scaffold drafts; use not applicable until a real draft exists.">
        <Select
          value={visionAccuracy}
          onChange={setVisionAccuracy}
          options={["no_issues", "minor_issues", "major_issues", "not_applicable"]}
        />
      </Field>
      <Field label="What should the visual description say?" hint="Adam-reviewed description; this is what retrieval and gallery surfaces should use.">
        <TextArea rows={5} value={description} onChange={setDescription} />
      </Field>
      <Field label="Who is visible or represented?">
        <input value={people} onChange={(event) => setPeople(event.target.value)} />
      </Field>
      <Field label="Where is this?">
        <input value={places} onChange={(event) => setPlaces(event.target.value)} />
      </Field>
      <Field label="When is this from or about?">
        <input value={dateRange} onChange={(event) => setDateRange(event.target.value)} />
      </Field>
      <Field label="What tags should stick?" hint="People/objects/themes that should become searchable embedding metadata.">
        <input value={tags} onChange={(event) => setTags(event.target.value)} />
      </Field>
      <Field label="Concrete visible objects">
        <input value={objects} onChange={(event) => setObjects(event.target.value)} />
      </Field>
      <Field label="What did the system get wrong?" hint="Comma-separated rejected inferences or bad tags.">
        <input value={rejectedInferences} onChange={(event) => setRejectedInferences(event.target.value)} />
      </Field>
      {questions.length > 0 ? (
        <div className="dynamic-question-stack">
          <FormHint title="Questions for Adam">
            These are generated or scaffolded prompts. Your answers are stored as Adam-provided context, separate from system inference.
          </FormHint>
          {questions.map((question, index) => {
            const id = payloadString(question.id, `question_${index + 1}`);
            return (
              <Field
                key={id}
                label={payloadString(question.question, `Question ${index + 1}`)}
                hint={payloadString(question.reason)}
              >
                <TextArea
                  rows={3}
                  value={questionAnswers[id] ?? ""}
                  onChange={(value) => updateQuestionAnswer(id, value)}
                />
              </Field>
            );
          })}
        </div>
      ) : null}
      <Field label="Why does Adam think it matters?">
        <TextArea rows={4} value={adamContextNote} onChange={setAdamContextNote} />
      </Field>
      <Field label="Is there OCR or handwriting text?">
        <Select
          value={ocrReviewStatus}
          onChange={setOcrReviewStatus}
          options={["not_present", "machine_draft_needs_review", "accepted_as_transcription", "adam_corrected"]}
        />
      </Field>
      <Field label="Where does the OCR/transcript truth come from?">
        <Select
          value={ocrTruthStatus}
          onChange={setOcrTruthStatus}
          options={["system_inference", "archival_source", "adam_expert_reconstruction", "adam_inference"]}
        />
      </Field>
      {ocrReviewStatus !== "not_present" ? (
        <Field label="Corrected OCR or handwriting text">
          <TextArea rows={6} value={correctedOcrText} onChange={setCorrectedOcrText} />
        </Field>
      ) : null}
      <FormHint title="Privacy">
        Vision tags and OCR can reveal sensitive people, places, and handwriting. Keep downstream use gated until this is reviewed.
      </FormHint>
      <Field label="How private is this source?">
        <Select
          value={privacyLevel}
          onChange={setPrivacyLevel}
          options={["public_safe", "family_private", "private_sensitive", "sensitive_living_people", "sealed"]}
        />
      </Field>
      <Field label="Can this move downstream?">
        <Select value={readyForDownstream} onChange={setReadyForDownstream} options={["yes", "later", "no"]} />
      </Field>
      <Field label="Why is this privacy/use decision right?">
        <TextArea rows={4} value={privacyNotes} onChange={setPrivacyNotes} />
      </Field>
    </div>
  );
}

function TextSegmentReviewForm({
  task,
  initialDecisions,
  onChange
}: {
  task: Task;
  initialDecisions: Decisions;
  onChange: (value: Decisions) => void;
}) {
  const payload = task.input_payload;
  const initialCreatorIds = Array.isArray(initialDecisions.creator_entity_ids)
    ? initialDecisions.creator_entity_ids.map(String)
    : [];
  const initialCreatorName = decisionString(initialDecisions, "creator_name");
  const [title, setTitle] = useState(decisionString(initialDecisions, "segment_title", payloadString(payload.segment_title, "")));
  const [sourceGenre, setSourceGenre] = useState(decisionString(initialDecisions, "source_genre", "document"));
  const [authorship, setAuthorship] = useState(decisionString(initialDecisions, "authorship", "unknown"));
  const [entities, setEntities] = useState<Entity[]>([]);
  const [creatorSelection, setCreatorSelection] = useState(initialCreatorIds[0] ?? (initialCreatorName ? NEW_PERSON_VALUE : ""));
  const [newPersonName, setNewPersonName] = useState(initialCreatorName);
  const [newPersonRelationshipToCharles, setNewPersonRelationshipToCharles] = useState(
    decisionString(initialDecisions, "creator_relationship_to_charles")
  );
  const [newPersonRelationshipToAdam, setNewPersonRelationshipToAdam] = useState(
    decisionString(initialDecisions, "creator_relationship_to_adam")
  );
  const [newPersonDescription, setNewPersonDescription] = useState("");
  const [newPersonConfidence, setNewPersonConfidence] = useState(decisionString(initialDecisions, "creator_confidence", "medium"));
  const [entityError, setEntityError] = useState("");
  const [entityBusy, setEntityBusy] = useState(false);
  const [authorshipNote, setAuthorshipNote] = useState(decisionString(initialDecisions, "authorship_note"));
  const [fictionalityStatus, setFictionalityStatus] = useState(decisionString(initialDecisions, "fictionality_status", "unknown"));
  const [truthStatus, setTruthStatus] = useState(decisionString(initialDecisions, "truth_status", "archival_source"));
  const [voicePresence, setVoicePresence] = useState(decisionString(initialDecisions, "voice_presence", "unknown"));
  const [people, setPeople] = useState(decisionListText(initialDecisions, "people"));
  const [places, setPlaces] = useState(decisionListText(initialDecisions, "places"));
  const [dateRange, setDateRange] = useState(decisionString(initialDecisions, "date_or_range", "unknown"));
  const [adamContextNote, setAdamContextNote] = useState(decisionString(initialDecisions, "adam_context_note"));
  const [readyForProcessing, setReadyForProcessing] = useState(
    decisionString(initialDecisions, "ready_for_processing", "yes")
  );
  const [privacyLevel, setPrivacyLevel] = useState(decisionString(initialDecisions, "privacy_level", "family_private"));
  const [livingPersonSensitive, setLivingPersonSensitive] = useState(
    decisionBoolean(initialDecisions, "contains_living_person_sensitive_material", false)
  );
  const [redactionRequired, setRedactionRequired] = useState(decisionBoolean(initialDecisions, "redaction_required", false));
  const [privacyNotes, setPrivacyNotes] = useState(
    decisionString(initialDecisions, "privacy_notes", decisionString(initialDecisions, "boundary_rationale"))
  );
  const selectedCreator = entities.find((entity) => entity.id === creatorSelection);
  const creatingPerson = creatorSelection === NEW_PERSON_VALUE;
  const creatorName = selectedCreator?.canonical_name || (creatingPerson ? newPersonName.trim() : "");
  const creatorRelationshipToCharles =
    selectedCreator?.relationship_to_charles || (creatingPerson ? newPersonRelationshipToCharles.trim() : "");
  const creatorRelationshipToAdam =
    selectedCreator?.relationship_to_adam || (creatingPerson ? newPersonRelationshipToAdam.trim() : "");

  useEffect(() => {
    let cancelled = false;
    getEntities("person")
      .then((nextEntities) => {
        if (!cancelled) {
          setEntities(nextEntities);
        }
      })
      .catch((caught: unknown) => {
        if (!cancelled) {
          setEntityError(caught instanceof Error ? caught.message : "Unable to load people.");
        }
      });

    return () => {
      cancelled = true;
    };
  }, [task.id]);

  useEffect(() => {
    const canProcess = readyForProcessing === "yes";
    onChange({
      segment_title: title,
      source_genre: sourceGenre,
      authorship,
      creator_entity_ids: selectedCreator ? [selectedCreator.id] : [],
      creator_name: creatorName,
      creator_relationship_to_charles: creatorRelationshipToCharles,
      creator_relationship_to_adam: creatorRelationshipToAdam,
      creator_confidence: creatingPerson ? newPersonConfidence : selectedCreator?.confidence,
      authorship_note: authorshipNote,
      fictionality_status: fictionalityStatus,
      people: parseList(people),
      places: parseList(places),
      date_or_range: dateRange,
      truth_status: truthStatus,
      voice_presence: voicePresence,
      adam_context_note: adamContextNote,
      ready_for_processing: readyForProcessing,
      privacy_level: privacyLevel,
      privacy_notes: privacyNotes,
      contains_living_person_sensitive_material: livingPersonSensitive ? "yes" : "no",
      redaction_required: redactionRequired ? "yes" : "no",
      usable_for_voice_context: canProcess ? "yes" : "no",
      usable_for_grounded_generation: canProcess ? "yes" : "no"
    });
  }, [
    adamContextNote,
    authorship,
    authorshipNote,
    creatorName,
    creatorSelection,
    creatorRelationshipToAdam,
    creatorRelationshipToCharles,
    creatingPerson,
    dateRange,
    fictionalityStatus,
    livingPersonSensitive,
    onChange,
    people,
    places,
    privacyLevel,
    privacyNotes,
    readyForProcessing,
    redactionRequired,
    selectedCreator?.confidence,
    newPersonConfidence,
    sourceGenre,
    title,
    truthStatus,
    voicePresence
  ]);

  async function handleCreatePerson() {
    const canonicalName = newPersonName.trim();
    if (!canonicalName) {
      setEntityError("Add a name before creating a person.");
      return;
    }
    setEntityBusy(true);
    setEntityError("");
    try {
      const entity = await createEntity({
        entity_type: "person",
        canonical_name: canonicalName,
        description: newPersonDescription.trim() || null,
        relationship_to_charles: newPersonRelationshipToCharles.trim() || null,
        relationship_to_adam: newPersonRelationshipToAdam.trim() || null,
        confidence: newPersonConfidence
      });
      setEntities((current) => [...current, entity].sort((left, right) => left.canonical_name.localeCompare(right.canonical_name)));
      setCreatorSelection(entity.id);
    } catch (caught) {
      setEntityError(caught instanceof Error ? caught.message : "Unable to create person.");
    } finally {
      setEntityBusy(false);
    }
  }

  return (
    <div className="form-grid source-question-grid">
      <FormHint title="Raw source material">
        Annotate what it is, who made it, what kind of truth it carries, who/where/when it is about, why Adam thinks it matters, and whether it should move into processing.
      </FormHint>
      <Field label="What should we call this segment?" hint="A short human-readable title for queue cards and retrieval.">
        <input value={title} onChange={(event) => setTitle(event.target.value)} />
      </Field>
      <Field label="What kind of document is it?" hint="The backend stores this as source_genre.">
        <Select
          value={sourceGenre}
          onChange={setSourceGenre}
          options={[
            "document",
            "letter",
            "novel_draft",
            "essay",
            "memoir_fragment",
            "notes",
            "article_clipping",
            "legal_or_financial",
            "unknown"
          ]}
        />
      </Field>
      <Field label="Who made it?" hint="Select a person record, or add one when the creator is not in the list yet.">
        <select value={creatorSelection} onChange={(event) => setCreatorSelection(event.target.value)}>
          <option value="">Unknown or not yet defined</option>
          {entities.map((entity) => (
            <option key={entity.id} value={entity.id}>
              {entityOptionLabel(entity)}
            </option>
          ))}
          <option value={NEW_PERSON_VALUE}>Add a person...</option>
        </select>
      </Field>
      <Field label="How should authorship be categorized?" hint="This coarse value helps filtering; the person record keeps the actual name and relationship.">
        <Select value={authorship} onChange={setAuthorship} options={["charles", "adam", "third_party", "mixed", "unknown"]} />
      </Field>
      {selectedCreator ? (
        <div className="entity-context">
          <strong>{selectedCreator.canonical_name}</strong>
          <span>
            Charles: {selectedCreator.relationship_to_charles || "unknown"} / Adam:{" "}
            {selectedCreator.relationship_to_adam || "unknown"}
          </span>
          {selectedCreator.description ? <p>{selectedCreator.description}</p> : null}
        </div>
      ) : null}
      {creatingPerson ? (
        <div className="person-create-panel">
          <Field label="Person name">
            <input value={newPersonName} onChange={(event) => setNewPersonName(event.target.value)} />
          </Field>
          <Field label="Relationship to Charles">
            <input
              value={newPersonRelationshipToCharles}
              onChange={(event) => setNewPersonRelationshipToCharles(event.target.value)}
            />
          </Field>
          <Field label="Relationship to Adam">
            <input
              value={newPersonRelationshipToAdam}
              onChange={(event) => setNewPersonRelationshipToAdam(event.target.value)}
            />
          </Field>
          <Field label="Confidence">
            <Select value={newPersonConfidence} onChange={setNewPersonConfidence} options={["high", "medium", "low"]} />
          </Field>
          <Field label="Who are they?">
            <TextArea rows={3} value={newPersonDescription} onChange={setNewPersonDescription} />
          </Field>
          <div className="inline-actions">
            <button type="button" onClick={handleCreatePerson} disabled={entityBusy}>
              {entityBusy ? "Adding" : "Add person"}
            </button>
            {entityError ? <span>{entityError}</span> : null}
          </div>
        </div>
      ) : entityError ? (
        <p className="quiet entity-error">{entityError}</p>
      ) : null}
      <Field label="What should we remember about authorship?" hint="For example: Cathryn wrote this poem; Charles read it, saved it, or responded to it.">
        <TextArea rows={3} value={authorshipNote} onChange={setAuthorshipNote} />
      </Field>
      <Field label="Is it factual, fictional, or mixed?" hint="This separates a novel draft from a letter, memory, or factual source.">
        <Select
          value={fictionalityStatus}
          onChange={setFictionalityStatus}
          options={["factual", "fiction", "fictionalized_from_life", "mixed", "unknown"]}
        />
      </Field>
      <Field label="Where does its truth come from?" hint="Archival source, Adam memory, inference, generated text, or reconstruction.">
        <Select
          value={truthStatus}
          onChange={setTruthStatus}
          options={[
            "archival_source",
            "spoken_source",
            "adam_memory",
            "adam_inference",
            "system_inference",
            "model_generated",
            "adam_expert_reconstruction",
            "interpretive_synthesis"
          ]}
        />
      </Field>
      <Field label="Is Charles's voice actually present?" hint="Primary means this is directly useful as Charles voice evidence.">
        <Select
          value={voicePresence}
          onChange={setVoicePresence}
          options={["primary", "partial", "context_only", "absent", "unknown"]}
        />
      </Field>
      <Field label="Who is it about?" hint="Comma-separated people or entities.">
        <input value={people} onChange={(event) => setPeople(event.target.value)} />
      </Field>
      <Field label="Where is it about?" hint="Comma-separated places, if known.">
        <input value={places} onChange={(event) => setPlaces(event.target.value)} />
      </Field>
      <Field label="When is it from or about?" hint="Use a year, date range, or unknown.">
        <input value={dateRange} onChange={(event) => setDateRange(event.target.value)} />
      </Field>
      <Field label="Why does Adam think it matters?" hint="This is retrieval/context metadata, not training target text by itself.">
        <TextArea rows={5} value={adamContextNote} onChange={setAdamContextNote} />
      </Field>
      <Field label="Should this move to segmentation?" hint="Yes creates a separate chunk/privacy processing task before any prompt-pair work.">
        <Select value={readyForProcessing} onChange={setReadyForProcessing} options={["yes", "later", "no"]} />
      </Field>
      <FormHint title="Privacy">
        Keep this simple for source review. Later tasks decide exact prompt-pair and export use.
      </FormHint>
      <Field label="How private is this source?">
        <Select
          value={privacyLevel}
          onChange={setPrivacyLevel}
          options={["public_safe", "family_private", "private_sensitive", "sensitive_living_people", "sealed"]}
        />
      </Field>
      <div className="toggle-grid">
        <Toggle label="contains_living_person_sensitive_material" checked={livingPersonSensitive} onChange={setLivingPersonSensitive} />
        <Toggle label="redaction_required" checked={redactionRequired} onChange={setRedactionRequired} />
      </div>
      <Field label="Why is this privacy decision right?" hint="Note sensitivity, uncertainty, or why this should stay local.">
        <TextArea value={privacyNotes} onChange={setPrivacyNotes} />
      </Field>
    </div>
  );
}

function TextSegmentBoundaryReviewForm({
  task,
  initialDecisions,
  onChange
}: {
  task: Task;
  initialDecisions: Decisions;
  onChange: (value: Decisions) => void;
}) {
  const [boundaryStatus, setBoundaryStatus] = useState(
    decisionString(initialDecisions, "segment_boundary_status", "approved_chunks")
  );
  const [sourceUseModes, setSourceUseModes] = useState<SourceUseMode[]>(() => {
    const storedModes = decisionStringList(initialDecisions, "source_use_modes");
    const storedMode = decisionString(initialDecisions, "source_use_mode");
    return normalizeSourceUseModes(storedModes.length > 0 ? storedModes : storedMode ? [storedMode] : []);
  });
  const [promptPairDecision, setPromptPairDecision] = useState(
    decisionString(
      initialDecisions,
      "prompt_pair_decision",
      promptPairDecisionFromPotential(decisionString(initialDecisions, "prompt_pair_potential", "high"))
    )
  );
  const [privacyClearance, setPrivacyClearance] = useState(
    decisionString(initialDecisions, "privacy_clearance", "ok_for_local_generation")
  );
  const [privacyLevel, setPrivacyLevel] = useState(
    decisionString(initialDecisions, "privacy_level", payloadString(task.input_payload.privacy_level, "family_private"))
  );
  const [privacyNotes, setPrivacyNotes] = useState(
    decisionString(initialDecisions, "privacy_notes", decisionString(initialDecisions, "boundary_rationale"))
  );
  const [segmentationNotes, setSegmentationNotes] = useState(
    decisionString(initialDecisions, "segmentation_notes")
  );
  const [redactionInstructions, setRedactionInstructions] = useState(
    decisionString(initialDecisions, "redaction_instructions")
  );
  const [redactionRequired, setRedactionRequired] = useState(decisionBoolean(initialDecisions, "redaction_required", false));

  useEffect(() => {
    const boundaryReady = boundaryStatus === "approved_chunks";
    const primaryUseMode = primarySourceUseMode(sourceUseModes);
    const canQuote =
      boundaryReady && sourceUseModes.includes("verbatim_preferred") && privacyClearance !== "do_not_export";
    const canGround =
      boundaryReady && sourceUseModes.includes("grounded_synthesis_allowed") && privacyClearance !== "do_not_export";
    const canUseAsContext = boundaryReady && !sourceUseModes.includes("exclude") && privacyClearance !== "do_not_export";
    const shouldGeneratePromptPair =
      promptPairDecision !== "no" && (canQuote || canGround) && privacyClearance !== "do_not_export";
    const effectiveRedactionRequired = redactionRequired || privacyClearance === "needs_redaction";
    const quotePolicy = privacyClearance === "do_not_export"
      ? "do_not_quote_or_export"
      : privacyClearance === "background_or_off_record"
        ? "background_only_not_quotable"
        : effectiveRedactionRequired
          ? "redacted_or_generalized_before_quote"
          : canQuote
            ? "source_quote_allowed_after_boundary_review"
            : "not_quotable";
    onChange({
      segment_boundary_status: boundaryStatus,
      chunk_adjustment_requested: boundaryStatus,
      source_use_mode: primaryUseMode,
      source_use_modes: sourceUseModes,
      prompt_pair_decision: promptPairDecision,
      prompt_pair_potential: promptPairPotentialFromDecision(promptPairDecision),
      privacy_clearance: privacyClearance,
      privacy_level: privacyLevel,
      privacy_notes: privacyNotes,
      boundary_rationale: privacyNotes,
      segmentation_notes: segmentationNotes,
      redaction_instructions: redactionInstructions,
      whole_source_context_mode: "retain_full_mirrored_source_and_reviewed_chunks",
      quote_policy: quotePolicy,
      redaction_required: effectiveRedactionRequired ? "yes" : "no",
      usable_for_verbatim_quote: canQuote ? "yes" : "no",
      usable_for_voice_context: canUseAsContext ? "yes" : "no",
      usable_for_grounded_generation: canGround ? "yes" : "no",
      ready_for_prompt_pair_factory: shouldGeneratePromptPair ? "yes" : "no"
    });
  }, [
    boundaryStatus,
    onChange,
    privacyClearance,
    privacyLevel,
    privacyNotes,
    promptPairDecision,
    redactionInstructions,
    redactionRequired,
    segmentationNotes,
    sourceUseModes
  ]);

  function toggleSourceUseMode(mode: SourceUseMode) {
    setSourceUseModes((current) => {
      const next = current.includes(mode) ? current.filter((item) => item !== mode) : [...current, mode];
      if (mode === "exclude" && !current.includes("exclude")) {
        return ["exclude"];
      }
      return normalizeSourceUseModes(next.filter((item) => item !== "exclude"));
    });
  }

  return (
    <div className="form-grid source-question-grid segmentation-question-grid">
      <FormHint title="Segment boundary review">
        Work one chunk at a time. Approve selected chunks only when they are coherent enough to ground prompt/response candidates without losing the whole-source context.
      </FormHint>
      <FormHint title="Chunk sizing">
        If a chunk is too long or contains several different moments, choose needs split. If it is too short or lacks setup, choose needs merge. The full mirrored source remains attached for retrieval and long-context use.
      </FormHint>
      <Field label="What should happen with this chunk set?" hint="Approved chunks may move to Prompt Pair Factory. Split/merge keeps the source in segmentation work.">
        <Select
          value={boundaryStatus}
          onChange={setBoundaryStatus}
          options={["approved_chunks", "needs_split", "needs_merge", "exclude_for_now"]}
        />
      </Field>
      <Field label="How may this source be used?" hint="Choose every use that applies. Quoting and grounded synthesis are intentionally separate.">
        <div className="use-mode-grid">
          {sourceUseModeOptions.map((option) => (
            <label className="use-mode-option" key={option.value}>
              <input
                type="checkbox"
                checked={sourceUseModes.includes(option.value)}
                onChange={() => toggleSourceUseMode(option.value)}
              />
              <span>
                <strong>{option.label}</strong>
                <small>{option.hint}</small>
              </span>
            </label>
          ))}
        </div>
      </Field>
      <Field label="Should this become prompt/response material?" hint="Yes is the normal path. Use later/no only when the source should not feed Pair Factory yet.">
        <Select value={promptPairDecision} onChange={setPromptPairDecision} options={["yes", "later", "no"]} />
      </Field>
      <Field label="Privacy clearance" hint="Needs redaction means local use is OK, but names/details need review before quoting or export. Background/off-record means context can help retrieval or synthesis, but it should not be quoted.">
        <Select
          value={privacyClearance}
          onChange={setPrivacyClearance}
          options={["ok_for_local_generation", "needs_redaction", "background_or_off_record", "review_before_export", "do_not_export"]}
        />
      </Field>
      <Field label="How private is this source?">
        <Select
          value={privacyLevel}
          onChange={setPrivacyLevel}
          options={["public_safe", "family_private", "private_sensitive", "sensitive_living_people", "sealed"]}
        />
      </Field>
      <div className="toggle-grid">
        <Toggle label="redaction_required" checked={redactionRequired} onChange={setRedactionRequired} />
      </div>
      <Field label="What should be redacted or generalized?" hint="For example: replace a named person with a role, remove identifying details, or keep only on-background context.">
        <TextArea rows={4} value={redactionInstructions} onChange={setRedactionInstructions} />
      </Field>
      <Field label="What should change about the segmentation?" hint="Use this for split/merge instructions, missing context, or why a chunk should not move forward yet.">
        <TextArea rows={4} value={segmentationNotes} onChange={setSegmentationNotes} />
      </Field>
      <Field label="Why is this privacy decision right?" hint="This travels with the source and blocks export when needed.">
        <TextArea rows={5} value={privacyNotes} onChange={setPrivacyNotes} />
      </Field>
    </div>
  );
}

function BoundaryReviewForm({
  initialDecisions,
  onChange
}: {
  initialDecisions: Decisions;
  onChange: (value: Decisions) => void;
}) {
  const [privacyLevel, setPrivacyLevel] = useState(decisionString(initialDecisions, "privacy_level", "family_private"));
  const [flags, setFlags] = useState({
    searchable: decisionBoolean(initialDecisions, "searchable", true),
    retrievable_in_chat: decisionBoolean(initialDecisions, "retrievable_in_chat", true),
    quotable: decisionBoolean(initialDecisions, "quotable", false),
    summarizable: decisionBoolean(initialDecisions, "summarizable", true),
    usable_for_voice_context: decisionBoolean(initialDecisions, "usable_for_voice_context", true),
    usable_for_sft: decisionBoolean(initialDecisions, "usable_for_sft", false),
    usable_for_dpo: decisionBoolean(initialDecisions, "usable_for_dpo", false),
    usable_for_eval: decisionBoolean(initialDecisions, "usable_for_eval", true),
    usable_for_gallery_public: decisionBoolean(initialDecisions, "usable_for_gallery_public", false),
    usable_for_gallery_family: decisionBoolean(initialDecisions, "usable_for_gallery_family", true),
    usable_for_simulation: decisionBoolean(initialDecisions, "usable_for_simulation", true),
    contains_living_person_sensitive_material: decisionBoolean(
      initialDecisions,
      "contains_living_person_sensitive_material",
      false
    ),
    redaction_required: decisionBoolean(initialDecisions, "redaction_required", false)
  });
  const [notes, setNotes] = useState(decisionString(initialDecisions, "notes"));

  useEffect(() => {
    onChange({ privacy_level: privacyLevel, ...flags, notes });
  }, [flags, notes, onChange, privacyLevel]);

  return (
    <div className="form-grid">
      <FormHint title="Privacy decision">
        Decide whether this item can be searched, quoted, used for voice, used for training, or kept out of downstream flows.
      </FormHint>
      <Field label="How private is this?">
        <Select
          value={privacyLevel}
          onChange={setPrivacyLevel}
          options={["public_safe", "family_private", "sensitive_living_people", "intimate", "sealed"]}
        />
      </Field>
      <div className="toggle-grid">
        {Object.entries(flags).map(([key, checked]) => (
          <Toggle
            key={key}
            label={key}
            checked={checked}
            onChange={(value) => setFlags((current) => ({ ...current, [key]: value }))}
          />
        ))}
      </div>
      <Field label="Why is this privacy decision right?">
        <TextArea value={notes} onChange={setNotes} />
      </Field>
    </div>
  );
}

function EmailVoiceSampleForm({
  task,
  initialDecisions,
  onChange
}: {
  task: Task;
  initialDecisions: Decisions;
  onChange: (value: Decisions) => void;
}) {
  const headers =
    task.input_payload.email_headers && typeof task.input_payload.email_headers === "object"
      ? (task.input_payload.email_headers as Record<string, unknown>)
      : {};
  const initialPresence = decisionString(initialDecisions, "charles_voice_presence", "unclear");
  const normalizedPresence =
    initialPresence === "primary" ? "charles_authored" : initialPresence === "partial" ? "charles_quoted" : initialPresence;
  const [voiceMode, setVoiceMode] = useState(decisionString(initialDecisions, "voice_mode", "father_to_adam"));
  const [charlesVoicePresence, setCharlesVoicePresence] = useState(normalizedPresence);
  const [charlesRole, setCharlesRole] = useState(decisionString(initialDecisions, "charles_email_role", "unknown"));
  const [otherVoices, setOtherVoices] = useState(decisionListText(initialDecisions, "other_voice_roles", "Adam, other correspondents"));
  const [contextUse, setContextUse] = useState(decisionString(initialDecisions, "context_use", "conversation_context"));
  const [quotedMaterial, setQuotedMaterial] = useState(decisionBoolean(initialDecisions, "quoted_or_forwarded_material_present", true));
  const [authenticity, setAuthenticity] = useState(decisionNumber(initialDecisions, "authenticity_value", 4));
  const [voiceSignal, setVoiceSignal] = useState(decisionString(initialDecisions, "charles_voice_signal", "medium"));
  const [evidence, setEvidence] = useState(decisionListText(initialDecisions, "notable_voice_evidence"));
  const [voiceContext, setVoiceContext] = useState(decisionBoolean(initialDecisions, "usable_for_voice_context", true));
  const [groundedGeneration, setGroundedGeneration] = useState(
    decisionBoolean(initialDecisions, "usable_for_grounded_generation", true)
  );
  const [sft, setSft] = useState(decisionBoolean(initialDecisions, "usable_for_sft", false));
  const [dpo, setDpo] = useState(decisionBoolean(initialDecisions, "usable_for_dpo", false));
  const [why, setWhy] = useState(decisionString(initialDecisions, "why_it_matters"));
  const [privacyNotes, setPrivacyNotes] = useState(
    decisionString(initialDecisions, "privacy_notes", decisionString(initialDecisions, "boundary_rationale"))
  );
  const directCharlesVoice = ["charles_authored", "charles_quoted", "primary", "partial"].includes(charlesVoicePresence);

  useEffect(() => {
    onChange({
      voice_mode: directCharlesVoice ? voiceMode : "",
      charles_voice_presence: charlesVoicePresence,
      charles_email_role: charlesRole,
      other_voice_roles: parseList(otherVoices),
      context_use: contextUse,
      quoted_or_forwarded_material_present: quotedMaterial ? "yes" : "no",
      email_subject: payloadString(headers.subject),
      email_from: payloadString(headers.from),
      email_to: payloadString(headers.to),
      email_date: payloadString(headers.date),
      authenticity_value: authenticity,
      voice_density: directCharlesVoice ? voiceSignal : "none",
      charles_voice_signal: directCharlesVoice ? voiceSignal : "none",
      recurring_phrases: directCharlesVoice ? parseList(evidence) : [],
      notable_voice_evidence: directCharlesVoice ? parseList(evidence) : [],
      usable_for_voice_context: voiceContext ? "yes" : "no",
      usable_for_grounded_generation: groundedGeneration ? "yes" : "no",
      usable_for_sft: directCharlesVoice && sft ? "yes" : "no",
      usable_for_dpo: directCharlesVoice && dpo ? "yes" : "no",
      why_it_matters: why,
      privacy_notes: privacyNotes
    });
  }, [
    authenticity,
    charlesRole,
    charlesVoicePresence,
    contextUse,
    directCharlesVoice,
    dpo,
    evidence,
    groundedGeneration,
    headers.date,
    headers.from,
    headers.subject,
    headers.to,
    onChange,
    otherVoices,
    privacyNotes,
    quotedMaterial,
    sft,
    voiceContext,
    voiceMode,
    voiceSignal,
    why
  ]);

  return (
    <div className="form-grid">
      <FormHint title="Email voice sample">
        Emails can contain multiple voices. Start by marking whether Charles is actually speaking; if not, this becomes context for retrieval or future grounded prompt pairs, not direct voice training data.
      </FormHint>
      <Field label="Is Charles's voice actually present?" hint="This decides whether we treat the email as voice evidence or as source/context.">
        <Select
          value={charlesVoicePresence}
          onChange={setCharlesVoicePresence}
          options={["charles_authored", "charles_quoted", "recipient_only", "mentioned_only", "no_charles_voice", "unclear"]}
        />
      </Field>
      <Field label="Where does Charles appear in the thread?" hint="Sender, recipient, quoted author, mentioned person, mixed, or unknown.">
        <Select
          value={charlesRole}
          onChange={setCharlesRole}
          options={["sender", "recipient", "quoted_author", "mentioned", "mixed", "unknown"]}
        />
      </Field>
      {directCharlesVoice ? (
        <Field label="What mode is Charles speaking in?" hint="Only needed when Charles is actually speaking or quoted.">
          <Select
            value={voiceMode}
            onChange={setVoiceMode}
            options={[
              "casual_email",
              "father_to_adam",
              "argument",
              "comic_observation",
              "grief_memory",
              "logistical_note",
              "other"
            ]}
          />
        </Field>
      ) : null}
      <Field label="Who else is speaking?" hint="Comma-separated people or roles in the email thread.">
        <input value={otherVoices} onChange={(event) => setOtherVoices(event.target.value)} />
      </Field>
      <Field label="How should this email be used?" hint="Voice sample, conversation context, factual context, prompt/response context, or exclude.">
        <Select
          value={contextUse}
          onChange={setContextUse}
          options={["charles_voice_sample", "conversation_context", "factual_context", "prompt_response_context", "exclude"]}
        />
      </Field>
      <Rating label="Authenticity" value={authenticity} onChange={setAuthenticity} />
      {directCharlesVoice ? (
        <>
          <Field label="Charles voice signal" hint="How strong the direct Charles voice evidence is.">
            <Select value={voiceSignal} onChange={setVoiceSignal} options={["high", "medium", "low", "none"]} />
          </Field>
          <Field label="Notable voice evidence" hint="Optional: closings, habits, exact phrasing, or verbal signatures worth finding again.">
            <input value={evidence} onChange={(event) => setEvidence(event.target.value)} />
          </Field>
        </>
      ) : (
        <FormHint title="Context mode">
          Charles is not speaking here, so focus on who is speaking, what this tells us, how it relates to Charles, and whether it can ground future prompt pairs.
        </FormHint>
      )}
      <FormHint title="Downstream use">
        Decide whether this email can be used as voice context, source context, prompt/response grounding, or training material.
      </FormHint>
      <div className="toggle-grid">
        <Toggle label="quoted_or_forwarded_material" checked={quotedMaterial} onChange={setQuotedMaterial} />
        <Toggle label="usable_for_voice_context" checked={voiceContext} onChange={setVoiceContext} />
        <Toggle label="usable_for_grounded_generation" checked={groundedGeneration} onChange={setGroundedGeneration} />
        {directCharlesVoice ? (
          <>
            <Toggle label="usable_for_sft" checked={sft} onChange={setSft} />
            <Toggle label="usable_for_dpo" checked={dpo} onChange={setDpo} />
          </>
        ) : null}
      </div>
      <Field label="Why does Adam think it matters?" hint="Context value, voice value, or why the thread should be handled carefully.">
        <TextArea value={why} onChange={setWhy} />
      </Field>
      <Field label="Why is this privacy/use decision OK?">
        <TextArea value={privacyNotes} onChange={setPrivacyNotes} />
      </Field>
    </div>
  );
}

function GroundedPromptPairCandidateForm({
  task,
  initialDecisions,
  onChange
}: {
  task: Task;
  initialDecisions: Decisions;
  onChange: (value: Decisions) => void;
}) {
  const payload = task.input_payload;
  const [promptIntent, setPromptIntent] = useState(decisionString(initialDecisions, "prompt_intent", "grounded_voice_response"));
  const [voiceMode, setVoiceMode] = useState(decisionString(initialDecisions, "voice_mode", payloadString(payload.voice_training_role, "father_to_adam")));
  const [truthMode, setTruthMode] = useState(
    decisionString(initialDecisions, "truth_mode", "adam_expert_reconstruction")
  );
  const [targetResponseShape, setTargetResponseShape] = useState(
    decisionString(initialDecisions, "target_response_shape", "short_voice_response")
  );
  const [promptText, setPromptText] = useState(decisionString(initialDecisions, "prompt_text"));
  const [modelDraft, setModelDraft] = useState(decisionString(initialDecisions, "model_draft"));
  const [boundaryClearance, setBoundaryClearance] = useState(
    decisionString(initialDecisions, "boundary_clearance_needed", "review_before_export")
  );
  const [factoryNotes, setFactoryNotes] = useState(decisionString(initialDecisions, "factory_notes"));

  useEffect(() => {
    const sourceChunksToUse = Array.isArray(initialDecisions.selected_chunk_ids)
      ? initialDecisions.selected_chunk_ids
      : Array.isArray(payload.selected_chunk_ids)
        ? payload.selected_chunk_ids
        : [];
    onChange({
      prompt_intent: promptIntent,
      voice_mode: voiceMode,
      truth_mode: truthMode,
      target_response_shape: targetResponseShape,
      prompt_text: promptText,
      model_draft: modelDraft,
      boundary_clearance_needed: boundaryClearance,
      factory_notes: factoryNotes,
      source_chunks_to_use: sourceChunksToUse,
      no_live_model_call: true
    });
  }, [boundaryClearance, factoryNotes, initialDecisions.selected_chunk_ids, modelDraft, onChange, payload.selected_chunk_ids, promptIntent, promptText, targetResponseShape, truthMode, voiceMode]);

  return (
    <div className="form-grid">
      <FormHint title="Prompt Pair Factory">
        Configure what kind of prompt pair this source should become. This stage creates the draft review task; the Gold Edit stage is where Adam rewrites, compares, and approves export artifacts.
      </FormHint>
      <Field label="What kind of prompt/response pair should this become?">
        <Select
          value={promptIntent}
          onChange={setPromptIntent}
          options={[
            "grounded_voice_response",
            "email_reply_candidate",
            "memory_scene_candidate",
            "factual_archive_answer",
            "style_eval_case",
            "anti_pattern_probe"
          ]}
        />
      </Field>
      <Field label="Which voice mode should the draft aim for?">
        <Select
          value={voiceMode}
          onChange={setVoiceMode}
          options={[
            "casual_email",
            "father_to_adam",
            "memoir_scene",
            "argument",
            "comic_observation",
            "grief_memory",
            "photography_reflection",
            "philosophical_fragment",
            "spoken_interview",
            "logistical_note"
          ]}
        />
      </Field>
      <Field label="What truth label should the candidate carry?">
        <Select
          value={truthMode}
          onChange={setTruthMode}
          options={["adam_expert_reconstruction", "interpretive_synthesis", "model_generated"]}
        />
      </Field>
      <Field label="What shape should the response have?">
        <Select
          value={targetResponseShape}
          onChange={setTargetResponseShape}
          options={["short_voice_response", "short_email_reply", "longer_letter", "memoir_paragraph", "archive_answer", "eval_prompt"]}
        />
      </Field>
      <Field
        label="Prompt text"
        hint="Optional. Leave blank and the backend will create a conservative grounded prompt from the selected source."
      >
        <TextArea value={promptText} onChange={setPromptText} rows={5} />
      </Field>
      <Field label="Draft rejected/pre-edit side" hint="Optional. Leave blank to create a deterministic stub for Adam to rewrite.">
        <TextArea value={modelDraft} onChange={setModelDraft} rows={5} />
      </Field>
      <Field label="What privacy check is needed before export?">
        <Select
          value={boundaryClearance}
          onChange={setBoundaryClearance}
          options={["review_before_export", "source_boundary_clear", "needs_redaction", "do_not_export"]}
        />
      </Field>
      <Field label="Factory notes" hint="Why this source should produce prompt pairs, or what Adam should watch for in the gold edit.">
        <TextArea value={factoryNotes} onChange={setFactoryNotes} rows={4} />
      </Field>
    </div>
  );
}

function GoldVoiceEditForm({
  task,
  initialDecisions,
  onChange
}: {
  task: Task;
  initialDecisions: Decisions;
  onChange: (value: Decisions) => void;
}) {
  const payload = task.input_payload;
  const initialRatings =
    initialDecisions.ratings && typeof initialDecisions.ratings === "object"
      ? (initialDecisions.ratings as Record<string, unknown>)
      : {};
  const defaultRatings = { ...((payload.ratings ?? {}) as Record<string, unknown>), ...initialRatings };
  const [prompt, setPrompt] = useState(decisionString(initialDecisions, "prompt", payloadString(payload.prompt, "")));
  const [voiceMode, setVoiceMode] = useState(decisionString(initialDecisions, "voice_mode", payloadString(payload.voice_mode, "father_to_adam")));
  const [truthMode, setTruthMode] = useState(
    decisionString(initialDecisions, "truth_mode", payloadString(payload.truth_mode, "generative_reconstruction"))
  );
  const [modelDraft, setModelDraft] = useState(decisionString(initialDecisions, "model_draft", payloadString(payload.model_draft, "")));
  const [goldEdit, setGoldEdit] = useState(decisionString(initialDecisions, "adam_gold_edit", payloadString(payload.adam_gold_edit, "")));
  const [authenticityRationale, setAuthenticityRationale] = useState(decisionString(initialDecisions, "authenticity_rationale"));
  const initialFailureModes = parseList(decisionListText(initialDecisions, "failure_modes", payloadArray(payload.failure_modes).join(", ")));
  const [responseRubric, setResponseRubric] = useState<ResponseRubricState>(() =>
    responseRubricFromDecisions(initialDecisions, defaultRatings, initialFailureModes)
  );
  const initialExportFlags =
    initialDecisions.export_flags && typeof initialDecisions.export_flags === "object"
      ? (initialDecisions.export_flags as Record<string, unknown>)
      : {};
  const [exportFlags, setExportFlags] = useState({
    sft: typeof initialExportFlags.sft === "boolean" ? initialExportFlags.sft : true,
    dpo: typeof initialExportFlags.dpo === "boolean" ? initialExportFlags.dpo : true,
    eval: typeof initialExportFlags.eval === "boolean" ? initialExportFlags.eval : true,
    anti_pattern:
      typeof initialExportFlags.anti_pattern === "boolean" ? initialExportFlags.anti_pattern : initialFailureModes.length > 0,
    style_rule: typeof initialExportFlags.style_rule === "boolean" ? initialExportFlags.style_rule : true
  });
  const isPromptPairDraft = Boolean(payload.prompt_pair_factory_no_model_call || payload.source_prompt_pair_task_id);
  const sourceExcerpt = payloadString(payload.source_excerpt);
  const responseARubric = responseRubric.response_a;
  const responseBRubric = responseRubric.response_b;
  const rubricRatings = useMemo(() => deriveRubricRatings(responseBRubric), [responseBRubric]);
  const failureModes = useMemo(() => deriveFailureModes(responseARubric), [responseARubric]);
  const preferredFailureModes = useMemo(() => deriveFailureModes(responseBRubric), [responseBRubric]);
  const rubricSummary = useMemo(
    () => deriveResponseRubricSummary(responseARubric, responseBRubric),
    [responseARubric, responseBRubric]
  );
  const rubricNotes = useMemo(
    () => [rubricNotesSummary(responseARubric), rubricNotesSummary(responseBRubric)].filter(Boolean).join("\n\n"),
    [responseARubric, responseBRubric]
  );
  const privacyExportBlocked = rubricSummary.preferred_export_blocked;
  const effectiveExportFlags = useMemo(
    () =>
      privacyExportBlocked
        ? {
            sft: false,
            dpo: false,
            eval: false,
            anti_pattern: false,
            style_rule: false
          }
        : {
            ...exportFlags,
            anti_pattern: exportFlags.anti_pattern && failureModes.length > 0
          },
    [exportFlags, failureModes.length, privacyExportBlocked]
  );

  useEffect(() => {
    onChange({
      prompt,
      voice_mode: voiceMode,
      truth_mode: truthMode,
      context_pack_id: payloadString(payload.context_pack_id),
      prompt_spec_id: payloadString(payload.prompt_spec_id),
      generation_id: payloadString(payload.generation_id),
      model_draft: modelDraft,
      adam_gold_edit: goldEdit,
      authenticity_rationale: authenticityRationale || rubricNotes,
      response_rubric: responseRubric,
      rubric_summary: rubricSummary,
      ratings: rubricRatings,
      failure_modes: failureModes,
      preferred_failure_modes: preferredFailureModes,
      export_flags: effectiveExportFlags
    });
  }, [authenticityRationale, effectiveExportFlags, failureModes, goldEdit, modelDraft, onChange, payload.context_pack_id, payload.generation_id, payload.prompt_spec_id, preferredFailureModes, prompt, responseARubric, responseBRubric, responseRubric, rubricNotes, rubricRatings, rubricSummary, truthMode, voiceMode]);

  function updateRubricDecision(responseKey: keyof ResponseRubricState, key: GoldRubricKey, decision: RubricDecision) {
    setResponseRubric((current) => ({
      ...current,
      [responseKey]: {
        ...current[responseKey],
        [key]: decision
      }
    }));
  }

  return (
    <div className="gold-grid">
      <FormHint title={isPromptPairDraft ? "Gold edit review" : "Generated/model output review"}>
        This is the acceptance step: compare the draft with Adam's preferred version, explain the nuanced differences in prose, then decide whether the preferred version is ready for SFT, DPO, eval, style-rule, and anti-pattern records.
      </FormHint>
      {sourceExcerpt ? (
        <section className="prompt-pair-source-card">
          <div>
            <span>Grounding source</span>
            <strong>{payloadString(payload.source_title, "Reviewed source")}</strong>
          </div>
          <LinePreview text={sourceExcerpt} />
        </section>
      ) : null}
      <div className="prompt-grid">
        <Field label="What was the model asked to do?">
          <TextArea value={prompt} onChange={setPrompt} rows={5} />
        </Field>
        <Field label="Which voice mode was requested?">
          <Select
            value={voiceMode}
            onChange={setVoiceMode}
            options={[
              "casual_email",
              "father_to_adam",
              "memoir_scene",
              "argument",
              "comic_observation",
              "grief_memory",
              "photography_reflection",
              "philosophical_fragment",
              "spoken_interview",
              "logistical_note"
            ]}
          />
        </Field>
        <Field label="What kind of reconstruction is this?">
          <Select value={truthMode} onChange={setTruthMode} options={["generative_reconstruction", "simulation", "interpretive", "adam_expert_reconstruction"]} />
        </Field>
      </div>
      <div className="voice-compare-grid">
        <Field label={isPromptPairDraft ? "Draft candidate" : "What did the model write?"} hint="This becomes the rejected side if exported as DPO.">
          <TextArea value={modelDraft} onChange={setModelDraft} rows={14} />
        </Field>
        <Field label="What did Adam change it into?" hint="This is the preferred version and the SFT assistant target.">
          <TextArea value={goldEdit} onChange={setGoldEdit} rows={14} />
        </Field>
      </div>
      <Field label="Why is the preferred version more authentic?" hint="Name the specific voice, restraint, detail, or truth difference.">
        <TextArea value={authenticityRationale} onChange={setAuthenticityRationale} rows={4} />
      </Field>
      <FormHint title="Issue rubric">
        Mark issues on the same axes for Response A and Response B. When something is wrong, describe it in your own words; those notes become the DPO rationale and anti-pattern explanation.
      </FormHint>
      <div className="response-rubric-grid">
        <section className="response-rubric-column">
          <div className="response-rubric-heading">
            <strong>Response A</strong>
            <span>Rejected/model draft</span>
          </div>
          <div className="rubric-stack">
            {goldReviewRubric.map((criterion) => (
              <RubricIssueCard
                key={criterion.key}
                criterion={criterion}
                decision={responseARubric[criterion.key]}
                noteLabel="What was wrong with Response A?"
                noteHint="This note becomes the DPO rejection reason and anti-pattern explanation."
                onChange={(decision) => updateRubricDecision("response_a", criterion.key, decision)}
              />
            ))}
          </div>
        </section>
        <section className="response-rubric-column">
          <div className="response-rubric-heading">
            <strong>Response B</strong>
            <span>Preferred/Adam edit</span>
          </div>
          <div className="rubric-stack">
            {goldReviewRubric.map((criterion) => (
              <RubricIssueCard
                key={criterion.key}
                criterion={criterion}
                decision={responseBRubric[criterion.key]}
                noteLabel="What still needs work in Response B?"
                noteHint="Only add a note if the preferred version still has an issue before export."
                onChange={(decision) => updateRubricDecision("response_b", criterion.key, decision)}
              />
            ))}
          </div>
        </section>
      </div>
      <FormHint title="Export artifacts">
        Choose which downstream records this edit should create. Major Response B privacy/export safety issues block downstream exports until resolved.
      </FormHint>
      <div className="rubric-summary">
        <span className={rubricSummary.sft_ready ? "ready" : "needs-work"}>
          {rubricSummary.sft_ready ? "Response B ready: no major issues" : "Response B held: major issue present"}
        </span>
        <span>Response A: {failureModes.length} DPO reason{failureModes.length === 1 ? "" : "s"}</span>
        <span>Response B: {preferredFailureModes.length} remaining issue{preferredFailureModes.length === 1 ? "" : "s"}</span>
        {privacyExportBlocked ? <span className="blocked">Privacy block active</span> : null}
      </div>
      <div className="toggle-grid">
        {Object.entries(exportFlags).map(([key, checked]) => (
          <Toggle
            key={key}
            label={key}
            checked={privacyExportBlocked ? false : checked}
            disabled={privacyExportBlocked}
            onChange={(value) => setExportFlags((current) => ({ ...current, [key]: value }))}
          />
        ))}
      </div>
    </div>
  );
}

export function TaskWorkbench({
  task,
  asset,
  queuePosition,
  queueTotal,
  qualityScore,
  completedThisSession,
  memoriesCount,
  goldExamplesCount,
  assetsCount,
  onSubmit,
  onSkip,
  onFlag,
  onPrevious,
  onNext
}: TaskWorkbenchProps) {
  const [draftLoaded, setDraftLoaded] = useState(false);
  const [draftDecisions, setDraftDecisions] = useState<Decisions>({});
  const [inspectorTab, setInspectorTab] = useState<"metadata" | "annotations" | "history">("metadata");
  const [inspectorWidth, setInspectorWidth] = useState(440);
  const [reviewStatus, setReviewStatus] = useState("needs_review");
  const [decisions, setDecisions] = useState<Decisions>({});
  const [chunkSelection, setChunkSelection] = useState<ChunkSelection>({
    chunk_scope: "preview_only",
    selected_chunk_ids: [],
    selected_chunk_count: 0
  });
  const [activeChunk, setActiveChunk] = useState<Segment | undefined>();
  const [textEdits, setTextEdits] = useState<Decisions>({});
  const [notes, setNotes] = useState("");
  const [draftStatus, setDraftStatus] = useState("Loading draft");
  const [draftUpdatedAt, setDraftUpdatedAt] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const lastSavedDraftRef = useRef("");
  const autosaveReadyRef = useRef(false);
  const descriptor = taskLabels[task.task_type] ?? { label: task.task_type, icon: <Gauge size={18} /> };
  const readinessBadges = readinessBadgesForTask(task, asset);

  useEffect(() => {
    let cancelled = false;
    setDraftLoaded(false);
    setDraftDecisions({});
    setDecisions({});
    setNotes("");
    setChunkSelection({ chunk_scope: "preview_only", selected_chunk_ids: [], selected_chunk_count: 0 });
    setActiveChunk(undefined);
    setTextEdits({});
    setDraftStatus("Loading draft");
    setDraftUpdatedAt(null);
    lastSavedDraftRef.current = "";
    autosaveReadyRef.current = false;

    getTaskDraft(task.id)
      .then((draft) => {
        if (cancelled) {
          return;
        }
        const nextDecisions = draft?.decisions ?? {};
        const draftChunkIds = Array.isArray(nextDecisions.selected_chunk_ids)
          ? nextDecisions.selected_chunk_ids.map(String)
          : [];
        const payloadChunkIds =
          draftChunkIds.length === 0 && Array.isArray(task.input_payload.selected_chunk_ids)
            ? task.input_payload.selected_chunk_ids.map(String)
            : [];
        const selectedChunkIds = draftChunkIds.length > 0 ? draftChunkIds : payloadChunkIds;
        const nextSelection = {
          chunk_scope: decisionString(nextDecisions, "chunk_scope", selectedChunkIds.length > 0 ? "selected_chunks" : "preview_only"),
          selected_chunk_ids: selectedChunkIds,
          active_chunk_id: decisionString(nextDecisions, "active_chunk_id") || undefined,
          selected_chunk_count: selectedChunkIds.length
        };
        setDraftDecisions(nextDecisions);
        setDecisions(nextDecisions);
        setNotes(draft?.notes ?? "");
        setChunkSelection(nextSelection);
        setDraftUpdatedAt(draft?.updated_at ?? null);
        setDraftStatus(draft ? "Draft restored" : "No draft yet");
        lastSavedDraftRef.current = JSON.stringify({ decisions: { ...nextDecisions, ...nextSelection }, notes: draft?.notes ?? "" });
      })
      .catch((caught: unknown) => {
        if (!cancelled) {
          setDraftStatus(caught instanceof Error ? `Draft load failed: ${caught.message}` : "Draft load failed");
        }
      })
      .finally(() => {
        if (!cancelled) {
          setDraftLoaded(true);
        }
      });

    return () => {
      cancelled = true;
    };
  }, [task.id, task.input_payload.selected_chunk_ids]);

  const autosaveDecisions = useMemo(
    () => ({ ...decisions, ...chunkSelection, ...textEdits }),
    [chunkSelection, decisions, textEdits]
  );

  useEffect(() => {
    if (!draftLoaded || busy) {
      return;
    }
    const serialized = JSON.stringify({ decisions: autosaveDecisions, notes });
    if (!autosaveReadyRef.current) {
      autosaveReadyRef.current = true;
      lastSavedDraftRef.current = serialized;
      return;
    }
    if (serialized === lastSavedDraftRef.current) {
      return;
    }

    setDraftStatus("Saving draft");
    const timeout = window.setTimeout(() => {
      saveTaskDraft(task.id, autosaveDecisions, notes)
        .then((draft) => {
          lastSavedDraftRef.current = serialized;
          setDraftUpdatedAt(draft.updated_at);
          setDraftStatus("Draft saved");
        })
        .catch((caught: unknown) => {
          setDraftStatus(caught instanceof Error ? `Draft save failed: ${caught.message}` : "Draft save failed");
        });
    }, 1000);

    return () => {
      window.clearTimeout(timeout);
    };
  }, [autosaveDecisions, busy, draftLoaded, notes, task.id]);

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    try {
      await onSubmit(autosaveDecisions, notes);
    } finally {
      setBusy(false);
    }
  }

  const handleChunkChange = useCallback((selection: ChunkSelection, chunk?: Segment) => {
    setChunkSelection((current) => (sameChunkSelection(current, selection) ? current : selection));
    setActiveChunk((current) => (current?.id === chunk?.id ? current : chunk));
  }, []);

  const handleTextEditChange = useCallback((value: Decisions) => {
    setTextEdits((current) => (sameDecisionRecord(current, value) ? current : value));
  }, []);

  const handleDecisionChange = useCallback((value: Decisions) => {
    setDecisions((current) => (sameDecisionRecord(current, value) ? current : value));
  }, []);

  const resizeInspector = useCallback((nextWidth: number) => {
    setInspectorWidth(clamp(nextWidth, inspectorBounds.min, inspectorBounds.max));
  }, []);

  function startInspectorResize(event: React.PointerEvent<HTMLDivElement>) {
    event.preventDefault();
    const startX = event.clientX;
    const startWidth = inspectorWidth;
    document.body.classList.add("is-column-resizing");

    function handleMove(moveEvent: PointerEvent) {
      resizeInspector(startWidth - (moveEvent.clientX - startX));
    }

    function handleEnd() {
      document.body.classList.remove("is-column-resizing");
      window.removeEventListener("pointermove", handleMove);
      window.removeEventListener("pointerup", handleEnd);
      window.removeEventListener("pointercancel", handleEnd);
    }

    window.addEventListener("pointermove", handleMove);
    window.addEventListener("pointerup", handleEnd);
    window.addEventListener("pointercancel", handleEnd);
  }

  function handleInspectorResizeKey(event: React.KeyboardEvent<HTMLDivElement>) {
    if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") {
      return;
    }
    event.preventDefault();
    resizeInspector(inspectorWidth + (event.key === "ArrowLeft" ? INSPECTOR_RESIZE_STEP : -INSPECTOR_RESIZE_STEP));
  }

  const initialChunkSelection = useMemo<ChunkSelection>(() => {
    const draftChunkIds = Array.isArray(draftDecisions.selected_chunk_ids)
      ? draftDecisions.selected_chunk_ids.map(String)
      : [];
    const payloadChunkIds =
      draftChunkIds.length === 0 && Array.isArray(task.input_payload.selected_chunk_ids)
        ? task.input_payload.selected_chunk_ids.map(String)
        : [];
    const selectedChunkIds = draftChunkIds.length > 0 ? draftChunkIds : payloadChunkIds;
    return {
      chunk_scope: decisionString(draftDecisions, "chunk_scope", selectedChunkIds.length > 0 ? "selected_chunks" : "preview_only"),
      selected_chunk_ids: selectedChunkIds,
      active_chunk_id: decisionString(draftDecisions, "active_chunk_id") || undefined,
      selected_chunk_count: selectedChunkIds.length
    };
  }, [draftDecisions, task.input_payload.selected_chunk_ids]);

  if (!draftLoaded) {
    return (
      <div className="workbench loading-workbench">
        <Gauge size={18} />
        <span>{draftStatus}</span>
      </div>
    );
  }

  const form = (() => {
    switch (task.task_type) {
      case "asset_triage":
        return <AssetTriageForm task={task} initialDecisions={draftDecisions} onChange={handleDecisionChange} />;
      case "photo_context":
        return <PhotoContextForm task={task} initialDecisions={draftDecisions} onChange={handleDecisionChange} />;
      case "vision_draft_review":
        return <VisionDraftReviewForm task={task} initialDecisions={draftDecisions} onChange={handleDecisionChange} />;
      case "text_segment_review":
        return <TextSegmentReviewForm task={task} initialDecisions={draftDecisions} onChange={handleDecisionChange} />;
      case "text_segment_boundary_review":
        return <TextSegmentBoundaryReviewForm task={task} initialDecisions={draftDecisions} onChange={handleDecisionChange} />;
      case "boundary_review":
        return <BoundaryReviewForm initialDecisions={draftDecisions} onChange={handleDecisionChange} />;
      case "email_voice_sample":
        return <EmailVoiceSampleForm task={task} initialDecisions={draftDecisions} onChange={handleDecisionChange} />;
      case "grounded_prompt_pair_candidate":
        return <GroundedPromptPairCandidateForm task={task} initialDecisions={draftDecisions} onChange={handleDecisionChange} />;
      case "gold_voice_edit":
        return <GoldVoiceEditForm task={task} initialDecisions={draftDecisions} onChange={handleDecisionChange} />;
      default:
        return (
          <Field label="Decision payload">
            <TextArea
              value={JSON.stringify(decisions, null, 2)}
              onChange={(value) => {
                try {
                  setDecisions(JSON.parse(value) as Decisions);
                } catch {
                  setDecisions({ raw: value });
                }
              }}
              rows={10}
            />
          </Field>
        );
    }
  })();
  const taskSource =
    payloadString(task.input_payload.source_filename) ||
    payloadString(task.input_payload.source_title) ||
    payloadString(task.input_payload.asset_title) ||
    task.target_id;
  const formInCanvas = task.task_type === "gold_voice_edit";
  const sourceReviewInCanvas = ["text_segment_review", "vision_draft_review"].includes(task.task_type);
  const segmentationInCanvas = task.task_type === "text_segment_boundary_review";
  const formInCenter = formInCanvas || sourceReviewInCanvas || segmentationInCanvas;
  const showSourceReviewCanvas = !formInCanvas;
  const taskSourceType = payloadString(task.input_payload.source_type) || payloadString(task.input_payload.asset_type);
  const showPhotoPreview =
    task.task_type === "photo_context" || task.task_type === "vision_draft_review" || taskSourceType === "photo";
  const showChunkBrowser =
    showSourceReviewCanvas && ["text_segment_boundary_review", "grounded_prompt_pair_candidate"].includes(task.task_type);
  const showEditableExtraction = false;
  const reviewCanvasClass = [
    "review-canvas",
    formInCanvas ? "editor-workspace" : "preview-workspace",
    sourceReviewInCanvas ? "has-questionnaire" : "",
    segmentationInCanvas ? "has-segmentation" : ""
  ]
    .filter(Boolean)
    .join(" ");
  const draftMetadataItems = task.task_type === "vision_draft_review"
    ? visionDigestItems(autosaveDecisions)
    : sourceReviewInCanvas
    ? sourceReviewDigestItems(autosaveDecisions)
    : segmentationInCanvas
    ? segmentBoundaryDigestItems(autosaveDecisions)
    : genericDecisionDigestItems(autosaveDecisions);

  return (
    <form className="workbench" onSubmit={handleSubmit}>
      <header className="workbench-header">
        <div>
          <div className="task-type">
            {descriptor.icon}
            <span>{descriptor.label}</span>
          </div>
          <h2>{taskDisplayTitle(task)}</h2>
          {readinessBadges.length > 0 ? (
            <div className="readiness-strip" aria-label="Maturity and readiness">
              {readinessBadges.map((badge) => (
                <span key={badge.label} data-tone={badge.tone} title={badge.tooltip}>
                  {badge.label}
                </span>
              ))}
            </div>
          ) : null}
        </div>
        <div className="task-meta">
          {asset ? (
            <Link className="dossier-action-link" href={`/assets/${asset.id}`} {...tooltip("Built: open the asset dossier with provenance, mirror snapshots, derivatives, boundaries, tasks, and annotations.")}>
              Dossier
            </Link>
          ) : null}
          <div className="quality-score">
            <strong>{qualityScore}</strong>
            <span>Quality score</span>
          </div>
          <select
            value={reviewStatus}
            onChange={(event) => setReviewStatus(event.target.value)}
            aria-label="Review status"
            {...tooltip("Local task status selector for the current review session. Submit still creates the durable annotation.")}
          >
            <option value="needs_review">Needs Review</option>
            <option value="needs_context">Needs Context</option>
            <option value="draft">Draft</option>
            <option value="approved">Approved</option>
            <option value="blocked">Blocked</option>
          </select>
          <div className="queue-stepper" aria-label="Queue position">
            <button
              type="button"
              onClick={onPrevious}
              disabled={queuePosition <= 1}
              aria-label="Previous task"
              {...tooltip("Built: move to the previous task in the current filtered queue.")}
            >
              <ChevronLeft size={16} />
            </button>
            <span>
              {queuePosition} / {queueTotal}
            </span>
            <button
              type="button"
              onClick={onNext}
              disabled={queuePosition >= queueTotal}
              aria-label="Next task"
              {...tooltip("Built: move to the next task in the current filtered queue.")}
            >
              <ChevronRight size={16} />
            </button>
          </div>
        </div>
      </header>

      <div
        className="review-grid"
        style={{ "--inspector-width": `${inspectorWidth}px` } as React.CSSProperties}
      >
        <section className={reviewCanvasClass} aria-label="Source and derived review surface">
          {formInCanvas ? <section className="canvas-form-panel">{form}</section> : null}
          {showSourceReviewCanvas ? (
            <>
              {showPhotoPreview ? <PhotoAssetPreview task={task} /> : <SourcePreview task={task} />}
              {segmentationInCanvas ? (
                <ChunkBrowser task={task} initialSelection={initialChunkSelection} onChange={handleChunkChange} />
              ) : null}
              {sourceReviewInCanvas || segmentationInCanvas ? <section className="canvas-form-panel source-questionnaire-panel">{form}</section> : null}
              {!segmentationInCanvas && showChunkBrowser ? (
                <ChunkBrowser task={task} initialSelection={initialChunkSelection} onChange={handleChunkChange} />
              ) : null}
              {showEditableExtraction ? (
                <EditableExtraction
                  task={task}
                  activeChunk={activeChunk}
                  initialCleanedText={decisionString(draftDecisions, "cleaned_text")}
                  onChange={handleTextEditChange}
                />
              ) : null}
            </>
          ) : null}
        </section>

        <div
          className="column-resizer inspector-column-resizer"
          role="separator"
          aria-label="Resize inspector column"
          aria-orientation="vertical"
          aria-valuemin={inspectorBounds.min}
          aria-valuemax={inspectorBounds.max}
          aria-valuenow={inspectorWidth}
          tabIndex={0}
          onPointerDown={startInspectorResize}
          onKeyDown={handleInspectorResizeKey}
        />

        <aside className="inspector" aria-label="Task inspector">
          <nav className="inspector-tabs" aria-label="Inspector tabs">
            {(["metadata", "annotations", "history"] as const).map((tab) => (
              <button
                key={tab}
                type="button"
                className={inspectorTab === tab ? "active" : ""}
                onClick={() => setInspectorTab(tab)}
                {...tooltip(
                  tab === "metadata"
                    ? "Built: compact readout of task metadata and current labels."
                    : tab === "annotations"
                      ? "Built: session notes and current draft decision payload."
                      : "Built: task status, autosave state, and session counters."
                )}
              >
                {labelFromKey(tab)}
              </button>
            ))}
          </nav>

          {inspectorTab === "metadata" ? (
            <div className="inspector-panel">
              <MetadataValueList
                title="Task metadata"
                items={[
                  { label: "Collection", value: labelFromKey(task.queue) },
                  { label: "Source", value: taskSource },
                  { label: "Type", value: descriptor.label },
                  { label: "Maturity", value: maturityLabel(asset?.maturity_level) },
                  { label: "Import", value: asset?.import_status ? labelFromKey(asset.import_status) : "Unknown" },
                  { label: "Processing", value: asset?.processing_status ? labelFromKey(asset.processing_status) : "Unknown" },
                  { label: "Confidence", value: "Unreviewed" }
                ]}
              />
              <section className="preview-band">
                <div>
                  <span>Target</span>
                  <strong>
                    {task.target_type} / {task.target_id.slice(0, 8)}
                  </strong>
                </div>
                <div>
                  <span>Reason</span>
                  <p>{task.reason_created}</p>
                </div>
                <div>
                  <span>Required</span>
                  <p>{task.required_decisions.map(promptFromDecisionKey).join(", ")}</p>
                </div>
              </section>
              <section className="decision-surface">
                {formInCenter ? (
                  <>
                    <MetadataValueList
                      title={
                        task.task_type === "vision_draft_review"
                          ? "Current vision labels"
                          : sourceReviewInCanvas
                          ? "Current source labels"
                          : segmentationInCanvas
                          ? "Current segmentation labels"
                          : "Current review labels"
                      }
                      items={draftMetadataItems}
                    />
                    {formInCanvas ? (
                      <FormHint title="Main editor">
                        Prompt, rejected draft, preferred version, rubric, and export flags are in the center editor so the comparison has enough room.
                      </FormHint>
                    ) : task.task_type === "vision_draft_review" ? (
                      <FormHint title="Vision questions">
                        Answer the vision review questions in the center pane below the image; this rail stays as a compact metadata readout.
                      </FormHint>
                    ) : task.task_type === "text_segment_boundary_review" ? (
                      <FormHint title="Segmentation questions">
                        Select and inspect chunks in the center pane; this rail stays as a compact readout of the current boundary, use, and privacy decisions.
                      </FormHint>
                    ) : (
                      <FormHint title="Source questions">
                        Answer the review questions in the center pane below the source text; this rail stays as a compact metadata readout.
                      </FormHint>
                    )}
                  </>
                ) : (
                  form
                )}
              </section>
            </div>
          ) : null}

          {inspectorTab === "annotations" ? (
            <div className="inspector-panel">
              <Field label="Session notes" hint="Working notes for this review session only; these are not exported as training target text.">
                <TextArea value={notes} onChange={setNotes} rows={5} />
              </Field>
              <section className="decision-summary">
                <span>Current draft decisions</span>
                {Object.entries(autosaveDecisions).slice(0, 12).map(([key, value]) => (
                  <div key={key}>
                    <strong>{promptFromDecisionKey(key)}</strong>
                    <p>{Array.isArray(value) ? value.join(", ") : typeof value === "object" ? JSON.stringify(value) : String(value)}</p>
                  </div>
                ))}
              </section>
            </div>
          ) : null}

          {inspectorTab === "history" ? (
            <div className="inspector-panel">
              <section className="history-stack">
                <div>
                  <span>Task status</span>
                  <strong>{labelFromKey(task.status)}</strong>
                </div>
                <div>
                  <span>Draft state</span>
                  <strong>{draftStatus}</strong>
                </div>
                <div>
                  <span>Last autosave</span>
                  <strong>{formatDraftTime(draftUpdatedAt) || "Not saved yet"}</strong>
                </div>
                <div>
                  <span>Session submissions</span>
                  <strong>{completedThisSession}</strong>
                </div>
                <div>
                  <span>Archive graph</span>
                  <strong>
                    {assetsCount} assets / {memoriesCount} memories / {goldExamplesCount} gold edits
                  </strong>
                </div>
              </section>
            </div>
          ) : null}
        </aside>
      </div>

      <footer className="workbench-actions">
        <button type="button" onClick={onSkip} disabled={busy} {...tooltip("Built: mark this task skipped and move on without submitting a review annotation.")}>
          <SkipForward size={16} />
          Skip
        </button>
        <button type="button" onClick={onFlag} disabled={busy} {...tooltip("Built: put this task on sensitive hold for later review.")}>
          <Flag size={16} />
          Flag
        </button>
        <span {...tooltip("Planned: duplicate or fork this task/review into a related task.")}>
          <button type="button" disabled>
            <Copy size={16} />
            Duplicate
          </button>
        </span>
        <span {...tooltip("Planned: reset the current local draft back to the last saved task state.")}>
          <button type="button" disabled>
            <RotateCcw size={16} />
            Reset
          </button>
        </span>
        <button className="primary-action" type="submit" disabled={busy} {...tooltip("Built: submit the task, create a durable annotation, and trigger any downstream records for this workflow.")}>
          <Save size={16} />
          {busy ? "Submitting" : "Submit"}
        </button>
        <span className="status-chip" {...tooltip("Status: current form is idle, busy, or recently autosaved.")}>
          <CheckCircle2 size={14} />
          {draftStatus === "Draft saved" ? "autosaved" : busy ? "busy" : "ready"}
        </span>
        <span className="status-chip draft-chip" {...tooltip("Status: last draft autosave time for this task.")}>
          {formatDraftTime(draftUpdatedAt) || draftStatus}
        </span>
      </footer>
    </form>
  );
}
