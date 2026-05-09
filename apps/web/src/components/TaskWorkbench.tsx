"use client";

import Link from "next/link";
import {
  CheckCircle2,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  ClipboardList,
  FileText,
  Flag,
  Gauge,
  Image,
  Mail,
  Save,
  ShieldCheck,
  SkipForward,
  Sparkles,
  TextCursorInput,
  Trash2
} from "lucide-react";
import { FormEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  createEntity,
  createVoiceMode,
  getEvidenceCorpus,
  getAssetPreviewUrl,
  getAssetTextChunks,
  getDpoRejectedReasonRepairProjection,
  getEntities,
  getOperatorAssistantSuggestion,
  getTaskDraft,
  getVoiceModes,
  preflightPromptPairExportGate,
  previewPhotoContextSubmitProjection,
  previewSourcePairGeneration,
  saveTaskDraft
} from "@/lib/api";
import { maturityLabel, readinessBadgesForTask } from "@/lib/readiness";
import type {
  Asset,
  DpoRejectedReasonRepairProjection,
  EvidenceCorpusResponse,
  Entity,
  PhotoContextSubmitProjection,
  OperatorAssistantSuggestion,
  PromptPairPreflightExportGate,
  Segment,
  SourcePairGenerationPreview,
  SourceSpanDraft,
  Task,
  VoiceMode
} from "@/lib/types";

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
type PromptPairEditorMode = "plain" | "yaml";
type SourceUseMode =
  | "verbatim_preferred"
  | "grounded_synthesis_allowed"
  | "context_only"
  | "exclude";
type OperatorChatMessage = {
  role: "assistant" | "user" | "system";
  content: string;
  detail?: string;
};

function operatorMessagesFromDecisions(decisions: Decisions): OperatorChatMessage[] {
  const value = decisions.operator_assistant_log;
  if (!Array.isArray(value)) {
    return [];
  }
  return value
    .map((entry) => {
      if (!entry || typeof entry !== "object") {
        return null;
      }
      const record = entry as Record<string, unknown>;
      const role = record.role === "assistant" || record.role === "user" || record.role === "system" ? record.role : "system";
      const content = typeof record.content === "string" ? record.content.trim() : "";
      const detail = typeof record.detail === "string" ? record.detail.trim() : "";
      if (!content) {
        return null;
      }
      return {
        role,
        content,
        ...(detail ? { detail } : {})
      } satisfies OperatorChatMessage;
    })
    .filter((entry): entry is OperatorChatMessage => entry !== null)
    .slice(-8);
}

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

function isGeneratePairsTask(task: Task): boolean {
  return ["text_segment_review", "text_segment_boundary_review", "email_voice_sample"].includes(task.task_type);
}

function isPromptPairCandidateTask(task: Task): boolean {
  return ["gold_voice_edit", "grounded_prompt_pair_candidate"].includes(task.task_type);
}

function promptPairApprovalBlocker(task: Task, decisions: Decisions): string {
  if (!isPromptPairCandidateTask(task)) {
    return "";
  }
  const input = task.input_payload;
  const artifactMode = decisionString(decisions, "artifact_mode", payloadString(input.artifact_mode, "sft")).toLowerCase();
  const prompt = decisionString(decisions, "prompt", payloadString(input.prompt)).trim();
  const content = (
    decisionString(decisions, "content", payloadString(input.content)) ||
    decisionString(decisions, "adam_gold_edit", payloadString(input.adam_gold_edit))
  ).trim();
  const chosen = (
    decisionString(decisions, "chosen", payloadString(input.chosen)) ||
    decisionString(decisions, "adam_gold_edit", payloadString(input.adam_gold_edit)) ||
    content
  ).trim();
  const rejected = (
    decisionString(decisions, "rejected", payloadString(input.rejected)) ||
    decisionString(decisions, "model_draft", payloadString(input.model_draft))
  ).trim();
  const responseRubric = payloadRecord(decisions.response_rubric);
  const responseA = payloadRecord(responseRubric.response_a);
  const voiceAuthenticity = payloadRecord(responseA.voice_authenticity);
  const rejectedReasonNote = recordString(voiceAuthenticity, "notes").trim();
  const rejectedReasonStatus = recordString(voiceAuthenticity, "status");
  const failureModes = decisionStringList(
    decisions,
    "failure_modes",
    Array.isArray(input.failure_modes) ? input.failure_modes.map(String).filter(Boolean) : []
  );
  const hasRejectedReason =
    failureModes.length > 0 ||
    rejectedReasonNote.length > 0 ||
    ["minor_issues", "major_issues"].includes(rejectedReasonStatus);
  const gatePreview = payloadRecord(decisions.export_gate_preview);
  const gateBlockers = Array.isArray(gatePreview.blockers) ? gatePreview.blockers.map(String).filter(Boolean) : [];
  const unresolvedGateBlocker = gateBlockers.find((blocker) => {
    if (blocker === "server_preflight_pending") {
      return false;
    }
    if (blocker === "dpo_rejected_reason_empty" && hasRejectedReason) {
      return false;
    }
    return true;
  });

  if (!prompt) {
    return "Prompt is required.";
  }
  if (artifactMode === "dpo") {
    if (!chosen) {
      return "Chosen response is required.";
    }
    if (!rejected) {
      return "Rejected response is required.";
    }
    if (!hasRejectedReason) {
      return "Rejected reason is required next to Rejected.";
    }
  } else if (!content) {
    return "Answer is required.";
  }
  if (unresolvedGateBlocker === "source_boundary_blocks_training") {
    return "Source boundary review must clear before approval.";
  }
  if (unresolvedGateBlocker) {
    return `${labelFromKey(unresolvedGateBlocker)} must clear before approval.`;
  }
  return "";
}

interface TaskWorkbenchProps {
  task: Task;
  asset?: Asset;
  queuePosition: number;
  queueTotal: number;
  completedThisSession: number;
  memoriesCount: number;
  goldExamplesCount: number;
  assetsCount: number;
  assets: Asset[];
  photoPreviewAccessToken?: string;
  onSubmit: (decisions: Decisions, notes?: string) => Promise<void>;
  onSkip: () => Promise<void>;
  onFlag: () => Promise<void>;
  onDeleteCandidate?: (reason?: string) => Promise<void>;
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
  gold_voice_edit: { label: "Prompt Pair", icon: <Sparkles size={18} /> }
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
  chunk_quality_profile: "Quality/provenance split for selected chunks",
  ready_reference_chunk_range: "Chunk indices that can move forward as reference-ready",
  needs_adam_edit_chunk_range: "Chunk indices that require Adam edit before pairing",
  ready_reference_truth_status: "Truth status for reference-ready chunks",
  needs_adam_edit_truth_status: "Truth status for chunks needing Adam edit",
  chunk_quality_notes: "Notes about the quality/provenance split",
  pairing_gate: "How Pair Factory should treat the selected chunks",
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

function promptPairBlockerAction(blocker: string): string {
  const actions: Record<string, string> = {
    dpo_rejected_reason_empty: "Add a rejected-side Minor or Major issue note with plain-language DPO context.",
    needs_adam_gold_edit: "Adam confirms this pair as gold before it can become an approved training row.",
    source_boundary_blocks_training: "Review the source boundary and allow SFT/DPO only if safe.",
    boundary_review_required: "Resolve boundary clearance before export.",
    rejected_truth_status_model_generated_requires_review: "Adam reviews the model-generated rejected side before export.",
    privacy_export_blocked: "Keep private or sealed material out of training export.",
    rubric_not_export_ready: "Resolve rubric issues or keep this item as a candidate.",
    server_preflight_pending: "Wait for backend preflight before deciding export status.",
    server_preflight_unavailable: "Retry backend preflight before submitting export-sensitive changes."
  };
  return actions[blocker] ?? "Resolve this blocker in the editor before treating the row as approved.";
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

function updateText(value: unknown): string {
  if (Array.isArray(value)) {
    return value.map(String).filter(Boolean).join(", ");
  }
  if (typeof value === "boolean") {
    return value ? "yes" : "no";
  }
  if (typeof value === "number") {
    return String(value);
  }
  return typeof value === "string" ? value : "";
}

function updateBooleanYesNo(value: unknown, fallback: "yes" | "no" = "yes"): "yes" | "no" {
  if (typeof value === "boolean") {
    return value ? "yes" : "no";
  }
  if (typeof value === "string") {
    return value.toLowerCase() === "no" || value.toLowerCase() === "false" ? "no" : "yes";
  }
  return fallback;
}

function fieldUpdatesFromSuggestion(suggestion: OperatorAssistantSuggestion | null): Decisions {
  const updates = suggestion?.field_updates;
  return updates && typeof updates === "object" && !Array.isArray(updates) ? updates : {};
}

function submitRecommendationStatus(suggestion: OperatorAssistantSuggestion | null): string {
  const recommendation = suggestion?.submit_recommendation;
  if (!recommendation?.requested) {
    return "";
  }
  if (recommendation.ready) {
    return recommendation.reason || "Assistant thinks this item is ready to submit.";
  }
  const missing = recommendation.missing_fields?.map(promptFromDecisionKey).join(", ");
  return [recommendation.reason, missing ? `Still needed: ${missing}` : ""].filter(Boolean).join(" ");
}

function questionAnswersHaveMemoryContext(questionAnswers: Record<string, string>): boolean {
  const memoryQuestionIds = new Set(["why_it_matters", "why_this_photo_matters", "meaning", "invisible_context"]);
  return Object.entries(questionAnswers).some(([key, value]) => memoryQuestionIds.has(key) && value.trim().length > 0);
}

function reviewedPhotoTruthStatus({
  taskType,
  description,
  adamContextNote,
  invisibleContext,
  questionAnswers,
  visionAccuracy
}: {
  taskType: string;
  description: string;
  adamContextNote: string;
  invisibleContext?: string;
  questionAnswers: Record<string, string>;
  visionAccuracy?: string;
}): string {
  if (taskType === "photo_context") {
    return adamContextNote.trim() || invisibleContext?.trim() || questionAnswersHaveMemoryContext(questionAnswers)
      ? "adam_memory"
      : "adam_inference";
  }
  if (adamContextNote.trim() || invisibleContext?.trim() || questionAnswersHaveMemoryContext(questionAnswers)) {
    return "adam_memory";
  }
  if (description.trim() && visionAccuracy !== "rejected") {
    return "adam_inference";
  }
  return "system_inference";
}

function photoReviewConsequences({
  privacyLevel,
  readyForDownstream,
  galleryEligibility,
  truthStatus
}: {
  privacyLevel: string;
  readyForDownstream: string;
  galleryEligibility: string;
  truthStatus: string;
}): Array<{ label: string; value: string; tone: "good" | "warning" | "neutral" }> {
  const ready = readyForDownstream === "yes";
  const sealed = privacyLevel === "sealed";
  const sensitive = ["private_sensitive", "sensitive_living_people"].includes(privacyLevel);
  const publicGallery = ready && privacyLevel === "public_candidate" && galleryEligibility === "public_candidate";
  const familyGallery = ready && !sealed && galleryEligibility === "family_private" && privacyLevel === "family_private";
  return [
    {
      label: "Truth label",
      value: labelFromKey(truthStatus),
      tone: truthStatus === "adam_memory" ? "good" : truthStatus === "system_inference" ? "warning" : "neutral"
    },
    {
      label: "Vector handoff",
      value: ready && !sealed && !sensitive ? "Eligible after submit" : ready && sealed ? "Excluded by boundary" : "Held until cleared",
      tone: ready && !sealed && !sensitive ? "good" : "warning"
    },
    {
      label: "Gallery",
      value: publicGallery ? "Public candidate" : familyGallery ? "Family gallery" : ready && sealed ? "Hidden" : "Held or context-only",
      tone: publicGallery || familyGallery ? "good" : "warning"
    },
    {
      label: "Training",
      value: "Not SFT/DPO material",
      tone: "neutral"
    }
  ];
}

type PhotoPromotionChecklistItem = {
  key: string;
  label: string;
  status: string;
  reason: string;
  tone: "good" | "warning" | "neutral";
};

function checklistTone(status: string): "good" | "warning" | "neutral" {
  if (["complete", "eligible_reviewed_record", "eligible"].includes(status)) {
    return "good";
  }
  if (["missing", "excluded_by_boundary", "held_pending_downstream_clearance", "held_missing_memory_context"].includes(status)) {
    return "warning";
  }
  return "neutral";
}

function localPhotoPromotionChecklist({
  description,
  adamContextNote,
  invisibleContext,
  questionAnswers,
  privacyLevel,
  readyForDownstream,
  ocrReviewStatus,
  vectorStatus
}: {
  description: string;
  adamContextNote: string;
  invisibleContext: string;
  questionAnswers: Record<string, string>;
  privacyLevel: string;
  readyForDownstream: string;
  ocrReviewStatus: string;
  vectorStatus: string;
}): PhotoPromotionChecklistItem[] {
  const hasDescription = description.trim().length > 0;
  const hasAdamContext =
    adamContextNote.trim().length > 0 ||
    invisibleContext.trim().length > 0 ||
    questionAnswersHaveMemoryContext(questionAnswers);
  const hasPrivacy = privacyLevel.trim().length > 0;
  const hasDownstreamChoice = ["yes", "later", "no"].includes(readyForDownstream);
  const hasOcrStatus = ocrReviewStatus.trim().length > 0;
  const hasMemoryText = hasDescription || hasAdamContext;
  const sensitive = ["sealed", "private_sensitive", "sensitive_living_people"].includes(privacyLevel);
  const localVectorStatus =
    vectorStatus ||
    (!hasMemoryText
      ? "held_missing_memory_context"
      : readyForDownstream !== "yes"
        ? "held_pending_downstream_clearance"
        : sensitive
          ? "excluded_by_boundary"
          : "eligible_reviewed_record");

  return [
    {
      key: "visual_description_correction",
      label: "Reviewed visual description",
      status: hasDescription ? "complete" : "missing",
      reason: "Needed so retrieval and gallery surfaces describe visible pixels in Adam-reviewed language.",
      tone: checklistTone(hasDescription ? "complete" : "missing")
    },
    {
      key: "adam_context",
      label: "Adam context or answers",
      status: hasAdamContext ? "complete" : "missing",
      reason: "Needed to promote this from image description into Adam memory rather than inference.",
      tone: checklistTone(hasAdamContext ? "complete" : "missing")
    },
    {
      key: "privacy_level",
      label: "Privacy level",
      status: hasPrivacy ? "complete" : "missing",
      reason: "Every downstream photo record needs an explicit boundary before retrieval or export.",
      tone: checklistTone(hasPrivacy ? "complete" : "missing")
    },
    {
      key: "ready_for_downstream",
      label: "Downstream choice",
      status: hasDownstreamChoice ? "complete" : "missing",
      reason: "Submit should record whether this can move to retrieval, gallery, and embedding handoff now.",
      tone: checklistTone(hasDownstreamChoice ? "complete" : "missing")
    },
    {
      key: "ocr_review_status",
      label: "OCR or handwriting status",
      status: hasOcrStatus ? "complete" : "missing",
      reason: "The review should say whether visible text is absent, machine-drafted, accepted, or corrected.",
      tone: checklistTone(hasOcrStatus ? "complete" : "missing")
    },
    {
      key: "vector_handoff_status",
      label: "Vector handoff status",
      status: localVectorStatus,
      reason: "Default vector handoff requires Adam-reviewed text, downstream clearance, and a non-sealed boundary.",
      tone: checklistTone(localVectorStatus)
    }
  ];
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

function recordString(record: Record<string, unknown> | undefined, key: string, fallback = ""): string {
  const value = record?.[key];
  return typeof value === "string" && value.trim() ? value : fallback;
}

function payloadRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value) ? (value as Record<string, unknown>) : {};
}

function payloadRecords(value: unknown): Record<string, unknown>[] {
  return Array.isArray(value)
    ? value.filter((item): item is Record<string, unknown> => Boolean(item) && typeof item === "object" && !Array.isArray(item))
    : [];
}

function recordBoolean(record: Record<string, unknown> | undefined, key: string): boolean {
  return record?.[key] === true;
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

function promptPairDigestItems(decisions: Decisions) {
  const exportFlags = decisions.export_flags && typeof decisions.export_flags === "object"
    ? Object.entries(decisions.export_flags as Record<string, unknown>)
        .filter(([, enabled]) => enabled === true)
        .map(([key]) => labelFromKey(key))
    : [];
  return [
    { label: "Artifact", value: formatMetadataValue(decisions.artifact_mode) },
    { label: "Editor", value: formatMetadataValue(decisions.editor_mode) },
    { label: "Voice mode", value: formatMetadataValue(decisions.voice_mode) },
    { label: "Truth status", value: formatMetadataValue(decisions.truth_status || decisions.truth_mode) },
    { label: "Synthetic", value: formatMetadataValue(decisions.synthetic) },
    { label: "Prompt", value: formatFreeTextValue(decisions.prompt) },
    { label: "Export flags", value: formatFreeTextValue(exportFlags) }
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

function Field({ label, hint, focusKey, children }: { label: string; hint?: string; focusKey?: string; children: React.ReactNode }) {
  return (
    <label className="field" data-focus-key={focusKey}>
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

function ReviewAccordionPanel({
  title,
  detail,
  defaultOpen = true,
  children
}: {
  title: string;
  detail?: string;
  defaultOpen?: boolean;
  children: React.ReactNode;
}) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <section className="review-accordion-panel" data-open={open ? "true" : "false"}>
      <header className="review-accordion-header">
        <button
          type="button"
          aria-expanded={open}
          aria-label={`${open ? "Collapse" : "Expand"} ${title}`}
          onClick={() => setOpen((current) => !current)}
        >
          <ChevronDown size={15} />
        </button>
        <div>
          <span>{title}</span>
          {detail ? <strong>{detail}</strong> : null}
        </div>
      </header>
      {open ? <div className="review-accordion-body">{children}</div> : null}
    </section>
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

function OperatorAssistantPanel({
  suggestion,
  status,
  messages,
  answer,
  applyStatus,
  onAnswerChange,
  onSend,
  onShowField
}: {
  suggestion: OperatorAssistantSuggestion | null;
  status: string;
  messages: OperatorChatMessage[];
  answer: string;
  applyStatus: string;
  onAnswerChange: (value: string) => void;
  onSend: () => void;
  onShowField?: () => void;
}) {
  const visibleMessages =
    messages.length > 0
      ? messages
      : suggestion
        ? [{ role: "assistant" as const, content: suggestion.next_question, detail: suggestion.target_label }]
        : [{ role: "assistant" as const, content: "Looking at the current draft and choosing the next useful review question." }];
  return (
    <section className="operator-assistant-panel" aria-label="Operator assistant">
      <header>
        <div>
          <span>Operator assistant</span>
          <strong>{suggestion?.target_label ?? "Next best question"}</strong>
        </div>
        <em>{status}</em>
      </header>
      <div className="operator-chat-thread" aria-label="Operator chat transcript">
        {visibleMessages.slice(-8).map((message, index) => (
          <article key={`${message.role}-${index}-${message.content.slice(0, 16)}`} data-role={message.role}>
            <span>{message.role === "assistant" ? "Assistant" : message.role === "user" ? "You" : "Applied"}</span>
            <p>{message.content}</p>
            {message.detail ? <small>{message.detail}</small> : null}
          </article>
        ))}
      </div>
      {suggestion?.rationale ? <small>{suggestion.rationale}</small> : null}
      {suggestion?.field_update_summary ? <small>{suggestion.field_update_summary}</small> : null}
      {submitRecommendationStatus(suggestion) ? <small>{submitRecommendationStatus(suggestion)}</small> : null}
      <TextArea rows={4} value={answer} onChange={onAnswerChange} />
      <div>
        <button type="button" onClick={onSend} disabled={!suggestion}>
          Send & apply
        </button>
        {suggestion && onShowField ? (
          <button type="button" onClick={onShowField}>
            Show field
          </button>
        ) : null}
        <small>
          {applyStatus || "Neutral helper only. It does not write as Charles, mutate source files, or approve downstream export."}
        </small>
        {messages.length > 0 ? <small aria-label="Draft evidence receipt">Draft evidence saved with this review.</small> : null}
      </div>
    </section>
  );
}

function LineNumberedTextArea({
  value,
  onChange,
  rows = 12,
  className = ""
}: {
  value: string;
  onChange: (value: string) => void;
  rows?: number;
  className?: string;
}) {
  const gutterRef = useRef<HTMLDivElement>(null);
  const lines = value.split(/\r?\n/);
  const lineCount = Math.max(1, lines.length);

  function replaceSelection(textarea: HTMLTextAreaElement, insertText: string, selectionStart: number, selectionEnd: number) {
    const nextValue = `${value.slice(0, selectionStart)}${insertText}${value.slice(selectionEnd)}`;
    const nextCursor = selectionStart + insertText.length;
    onChange(nextValue);
    window.requestAnimationFrame(() => {
      textarea.setSelectionRange(nextCursor, nextCursor);
    });
  }

  function indentationBefore(index: number): string {
    const lineStart = value.lastIndexOf("\n", Math.max(0, index - 1)) + 1;
    const currentLinePrefix = value.slice(lineStart, index);
    const currentIndent = currentLinePrefix.match(/^[ \t]*/)?.[0] ?? "";
    if (currentIndent || currentLinePrefix.trim()) {
      return currentIndent;
    }
    const previousLineEnd = Math.max(0, lineStart - 1);
    const previousLineStart = value.lastIndexOf("\n", Math.max(0, previousLineEnd - 1)) + 1;
    const previousLine = value.slice(previousLineStart, previousLineEnd);
    return previousLine.match(/^[ \t]*/)?.[0] ?? "";
  }

  function handleKeyDown(event: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === "Tab") {
      event.preventDefault();
      const textarea = event.currentTarget;
      const start = textarea.selectionStart;
      const end = textarea.selectionEnd;
      if (event.shiftKey) {
        const lineStart = value.lastIndexOf("\n", Math.max(0, start - 1)) + 1;
        const removable = value.slice(lineStart, lineStart + 2) === "  " ? 2 : value.slice(lineStart, lineStart + 1) === "\t" ? 1 : 0;
        if (removable > 0) {
          const nextValue = `${value.slice(0, lineStart)}${value.slice(lineStart + removable)}`;
          const nextCursor = Math.max(lineStart, start - removable);
          onChange(nextValue);
          window.requestAnimationFrame(() => textarea.setSelectionRange(nextCursor, Math.max(nextCursor, end - removable)));
        }
        return;
      }
      replaceSelection(textarea, "  ", start, end);
      return;
    }

    if (event.key === "Enter") {
      event.preventDefault();
      const textarea = event.currentTarget;
      const start = textarea.selectionStart;
      replaceSelection(textarea, `\n${indentationBefore(start)}`, start, textarea.selectionEnd);
    }
  }

  return (
    <div className={["line-editor", className].filter(Boolean).join(" ")}>
      <div className="line-editor-gutter" ref={gutterRef} aria-hidden="true">
        {Array.from({ length: lineCount }, (_, index) => (
          <span key={index}>{index + 1}</span>
        ))}
      </div>
      <textarea
        rows={rows}
        spellCheck={false}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        onKeyDown={handleKeyDown}
        onScroll={(event) => {
          if (gutterRef.current) {
            gutterRef.current.scrollTop = event.currentTarget.scrollTop;
          }
        }}
      />
    </div>
  );
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

function indentBlock(text: string, spaces: number): string {
  const indent = " ".repeat(spaces);
  const lines = text.split(/\r?\n/);
  return (lines.length > 0 ? lines : [""]).map((line) => (line ? `${indent}${line}` : indent.trimEnd())).join("\n");
}

function yamlScalar(value: string, blockIndent = 4): string {
  const trimmed = value.trim();
  if (!trimmed) {
    return "\"\"";
  }
  if (trimmed.includes("\n")) {
    return `|-\n${indentBlock(trimmed, blockIndent)}`;
  }
  if (/[:#[\]{}]|^\s|'\s|"|^[-?]|[&*!|>%@`]/.test(trimmed)) {
    return `"${trimmed.replace(/\\/g, "\\\\").replace(/"/g, "\\\"")}"`;
  }
  return trimmed;
}

function buildPairYaml({
  artifactMode,
  systemPrompt,
  prompt,
  content,
  chosen,
  rejected
}: {
  artifactMode: "sft" | "dpo";
  systemPrompt: string;
  prompt: string;
  content: string;
  chosen: string;
  rejected: string;
}): string {
  if (artifactMode === "dpo") {
    return [
      `- system: ${yamlScalar(systemPrompt, 4)}`,
      `  prompt: ${yamlScalar(prompt, 4)}`,
      "  chosen: |-",
      indentBlock(chosen, 4),
      "  rejected: |-",
      indentBlock(rejected, 4)
    ].join("\n");
  }
  return [
    "- messages:",
    "   - role: system",
    `     content: ${yamlScalar(systemPrompt, 7)}`,
    "   - role: user",
    `     content: ${yamlScalar(prompt, 7)}`,
    "   - role: assistant",
    "     content: |-",
    indentBlock(content, 7)
  ].join("\n");
}

function normalizePreviewYaml(value: unknown): string {
  return typeof value === "string" ? value.replace(/\r\n/g, "\n").replace(/\r/g, "\n").trim() : "";
}

function unquoteYamlScalar(value: string): string {
  const trimmed = value.trim();
  if (trimmed.length >= 2 && trimmed[0] === trimmed[trimmed.length - 1] && ["\"", "'"].includes(trimmed[0])) {
    return trimmed.slice(1, -1).replace(/\\"/g, "\"").replace(/\\\\/g, "\\");
  }
  return trimmed;
}

function dedentYamlBlock(lines: string[]): string {
  const indents = lines.filter((line) => line.trim()).map((line) => line.length - line.trimStart().length);
  const indent = indents.length > 0 ? Math.min(...indents) : 0;
  return lines.map((line) => (line.length >= indent ? line.slice(indent) : "")).join("\n").replace(/\s+$/g, "");
}

function parseSftYamlEditor(value: string): { systemPrompt: string; prompt: string; content: string } | null {
  const lines = value.replace(/\r\n/g, "\n").replace(/\r/g, "\n").split("\n");
  const messages: { role: string; content: string }[] = [];
  const rolePattern = /^(\s*)-\s+role:\s*(.+?)\s*$/;
  const contentPattern = /^\s*content:\s*(.*)$/;

  for (let index = 0; index < lines.length; index += 1) {
    const roleMatch = lines[index].match(rolePattern);
    if (!roleMatch) {
      continue;
    }
    const roleIndent = roleMatch[1].length;
    const role = unquoteYamlScalar(roleMatch[2]);
    const messageLines: string[] = [];
    index += 1;
    while (index < lines.length) {
      const nextRole = lines[index].match(rolePattern);
      if (nextRole && nextRole[1].length <= roleIndent) {
        index -= 1;
        break;
      }
      messageLines.push(lines[index]);
      index += 1;
    }

    let content = "";
    for (let messageIndex = 0; messageIndex < messageLines.length; messageIndex += 1) {
      const contentMatch = messageLines[messageIndex].match(contentPattern);
      if (!contentMatch) {
        continue;
      }
      const scalar = contentMatch[1].trim();
      if (["|", "|-", "|+", ">", ">-", ">+"].includes(scalar)) {
        content = dedentYamlBlock(messageLines.slice(messageIndex + 1));
      } else {
        content = unquoteYamlScalar(scalar);
      }
      break;
    }
    if (role && content) {
      messages.push({ role, content });
    }
  }

  const systemPrompt = messages.find((message) => message.role === "system")?.content ?? "";
  const prompt = messages.find((message) => message.role === "user")?.content ?? "";
  const content = messages.find((message) => message.role === "assistant")?.content ?? "";
  return prompt && content ? { systemPrompt, prompt, content } : null;
}

function parseDpoYamlEditor(value: string): { systemPrompt: string; prompt: string; chosen: string; rejected: string } | null {
  const lines = value.replace(/\r\n/g, "\n").replace(/\r/g, "\n").split("\n");
  const entries: Partial<Record<"system" | "prompt" | "chosen" | "rejected", string>> = {};
  const keyPattern = /^(\s*)(?:-\s*)?(system|prompt|chosen|rejected):\s*(.*)$/;

  for (let index = 0; index < lines.length; index += 1) {
    const match = lines[index].match(keyPattern);
    if (!match || match[1].length > 2) {
      continue;
    }
    const key = match[2] as "system" | "prompt" | "chosen" | "rejected";
    const scalar = match[3].trim();
    if (["|", "|-", "|+", ">", ">-", ">+"].includes(scalar)) {
      const blockLines: string[] = [];
      index += 1;
      while (index < lines.length) {
        const nextKey = lines[index].match(keyPattern);
        if (nextKey && nextKey[1].length <= 2) {
          index -= 1;
          break;
        }
        blockLines.push(lines[index]);
        index += 1;
      }
      entries[key] = dedentYamlBlock(blockLines);
    } else {
      entries[key] = unquoteYamlScalar(scalar);
    }
  }

  if (Object.keys(entries).length === 0) {
    return null;
  }

  return {
    systemPrompt: entries.system ?? "",
    prompt: entries.prompt ?? "",
    chosen: entries.chosen ?? "",
    rejected: entries.rejected ?? ""
  };
}

function defaultSystemPromptForMode(artifactMode: "sft" | "dpo"): string {
  return artifactMode === "dpo"
    ? "You are Charles Rotmil."
    : "You are Charles Rotmil. Write naturally in his voice.";
}

function assetOptionLabel(asset: Asset): string {
  return asset.title || asset.original_filename || asset.human_id;
}

function validArtifactMode(value: string): "sft" | "dpo" {
  return value === "dpo" ? "dpo" : "sft";
}

function validEditorMode(value: string): PromptPairEditorMode {
  return value === "yaml" ? "yaml" : "plain";
}

function spansFromDecision(value: unknown): SourceSpanDraft[] {
  if (!Array.isArray(value)) {
    return [];
  }
  return value
    .filter((item): item is Record<string, unknown> => Boolean(item) && typeof item === "object")
    .map((item, index) => ({
      id: typeof item.id === "string" ? item.id : `span_${index}_${Date.now()}`,
      start_char: typeof item.start_char === "number" ? item.start_char : 0,
      end_char: typeof item.end_char === "number" ? item.end_char : 0,
      text: typeof item.text === "string" ? item.text : typeof item.selected_text === "string" ? item.selected_text : "",
      span_type: (item.span_type === "prompt" || item.span_type === "response" ? item.span_type : "context") as SourceSpanDraft["span_type"],
      speaker: typeof item.speaker === "string" ? item.speaker : "",
      code: typeof item.code === "string" ? item.code : "",
      notes: typeof item.notes === "string" ? item.notes : ""
    }))
    .filter((span) => span.text.trim() && span.end_char > span.start_char);
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
          <span>preview: {previewText.length} chars</span>
          {typeof task.input_payload.chunk_count === "number" ? <span>{task.input_payload.chunk_count} chunks</span> : null}
          {payloadString(task.input_payload.chunking_strategy) ? (
            <span>{labelFromKey(payloadString(task.input_payload.chunking_strategy))}</span>
          ) : null}
          {typeof task.input_payload.total_chars === "number" ? <span>{task.input_payload.total_chars} chars extracted</span> : null}
          {typeof task.input_payload.total_chars === "number" && task.input_payload.total_chars > previewText.length ? (
            <span>full text in chunks below</span>
          ) : null}
          {task.input_payload.truncated ? <span>source capped</span> : null}
        </div>
      ) : null}
    </section>
  );
}

function sourceTextForCoding(task: Task): string {
  return (
    payloadString(task.input_payload.preview_text) ||
    payloadString(task.input_payload.source_excerpt) ||
    payloadString(task.input_payload.text)
  );
}

function SourceSpanCoder({
  task,
  spans,
  onChange
}: {
  task: Task;
  spans: SourceSpanDraft[];
  onChange: (spans: SourceSpanDraft[]) => void;
}) {
  const text = sourceTextForCoding(task);
  const preRef = useRef<HTMLPreElement | null>(null);
  const [selection, setSelection] = useState<{ start: number; end: number; text: string } | null>(null);
  const [spanType, setSpanType] = useState<SourceSpanDraft["span_type"]>("response");
  const [speaker, setSpeaker] = useState("");
  const [code, setCode] = useState("");
  const [spanNotes, setSpanNotes] = useState("");

  if (!text) {
    return null;
  }

  function captureSelection() {
    const selected = window.getSelection();
    const node = preRef.current;
    if (!selected || selected.rangeCount === 0 || !node) {
      return;
    }
    const range = selected.getRangeAt(0);
    if (!node.contains(range.commonAncestorContainer)) {
      return;
    }
    const selectedText = range.toString();
    if (!selectedText.trim()) {
      return;
    }
    const before = document.createRange();
    before.selectNodeContents(node);
    before.setEnd(range.startContainer, range.startOffset);
    const start = before.toString().length;
    setSelection({ start, end: start + selectedText.length, text: selectedText });
  }

  function addSpan() {
    if (!selection) {
      return;
    }
    const next: SourceSpanDraft = {
      id: `span_${selection.start}_${selection.end}_${Date.now()}`,
      start_char: selection.start,
      end_char: selection.end,
      text: selection.text,
      span_type: spanType,
      speaker,
      code,
      notes: spanNotes
    };
    onChange([...spans, next].sort((left, right) => left.start_char - right.start_char));
    setSelection(null);
    setCode("");
    setSpanNotes("");
  }

  function removeSpan(id: string) {
    onChange(spans.filter((span) => span.id !== id));
  }

  return (
    <section className="source-span-coder">
      <div className="source-span-header">
        <div>
          <span>Source coding</span>
          <strong>Highlight text to tag Prompt, Response, or Context</strong>
        </div>
        <em>{spans.length} span{spans.length === 1 ? "" : "s"}</em>
      </div>
      <pre ref={preRef} className="source-coding-text" onMouseUp={captureSelection} onKeyUp={captureSelection}>
        {text}
      </pre>
      <div className="source-span-controls">
        <Field label="Tag">
          <select value={spanType} onChange={(event) => setSpanType(event.target.value as SourceSpanDraft["span_type"])}>
            <option value="prompt">Prompt</option>
            <option value="response">Response</option>
            <option value="context">Context</option>
          </select>
        </Field>
        <Field label="Speaker">
          <input value={speaker} onChange={(event) => setSpeaker(event.target.value)} placeholder="Charles, Adam, Cathryn..." />
        </Field>
        <Field label="Coding">
          <input value={code} onChange={(event) => setCode(event.target.value)} placeholder="freeform tag or note" />
        </Field>
        <Field label="Notes">
          <input value={spanNotes} onChange={(event) => setSpanNotes(event.target.value)} />
        </Field>
        <button type="button" className="secondary-action" onClick={addSpan} disabled={!selection}>
          Add Span
        </button>
      </div>
      {selection ? (
        <div className="selection-preview">
          <span>
            Selected chars {selection.start}-{selection.end}
          </span>
          <p>{selection.text}</p>
        </div>
      ) : null}
      {spans.length > 0 ? (
        <div className="span-list">
          {spans.map((span) => (
            <div key={span.id} className="span-chip">
              <strong>{labelFromKey(span.span_type)}</strong>
              <span>{span.speaker || "speaker unset"}</span>
              <p>{span.text}</p>
              {span.code ? <em>{span.code}</em> : null}
              <button type="button" onClick={() => removeSpan(span.id)}>
                Remove
              </button>
            </div>
          ))}
        </div>
      ) : null}
    </section>
  );
}

function isPhotoLikeTask(task: Task, asset?: Asset): boolean {
  const taskSourceType = payloadString(task.input_payload.source_type) || payloadString(task.input_payload.asset_type);
  const mimeType = payloadString(task.input_payload.mime_type) || asset?.mime_type || "";
  const filename = (
    payloadString(task.input_payload.source_filename) ||
    payloadString(task.input_payload.asset_title) ||
    payloadString(task.input_payload.title) ||
    asset?.original_filename ||
    asset?.title ||
    ""
  ).toLowerCase();
  return (
    task.task_type === "photo_context" ||
    task.task_type === "vision_draft_review" ||
    ["photo", "image", "scan"].includes(taskSourceType) ||
    asset?.asset_type === "photo" ||
    mimeType.startsWith("image/") ||
    /\.(jpg|jpeg|png|gif|webp|heic|tif|tiff)$/i.test(filename)
  );
}

function SourcePairGenerationPreviewPanel({
  preview,
  status
}: {
  preview: SourcePairGenerationPreview | null;
  status: string;
}) {
  const strategyEntries = preview ? Object.entries(preview.strategy_counts) : [];
  const firstPair = preview?.created_pairs_preview[0] ?? preview?.held_pairs_preview[0];

  return (
    <section className="source-pair-generation-preview" aria-label="Generate Pairs preview">
      <header>
        <div>
          <span>What should it generate?</span>
          <strong>
            {preview
              ? `${preview.projected_created_pair_count} item${preview.projected_created_pair_count === 1 ? "" : "s"} projected`
              : status || "Preparing preview"}
          </strong>
        </div>
        <em>{preview?.completion_signal ? labelFromKey(preview.completion_signal) : status || "dry run"}</em>
      </header>
      {preview ? (
        <>
          <div className="source-pair-preview-grid">
            <div>
              <span>Pair source</span>
              <strong>{preview.primary_strategy_label}</strong>
              <small>{strategyEntries.map(([strategy, count]) => `${count} ${labelFromKey(strategy)}`).join(" / ") || "No pairs"}</small>
            </div>
            <div>
              <span>Items after click</span>
              <strong>
                {preview.projected_created_pair_count} create / {preview.projected_held_pair_count} held
              </strong>
              <small>{preview.next_queue ? labelFromKey(preview.next_queue) : "No next queue yet"}</small>
            </div>
            <div>
              <span>Source sections</span>
              <strong>
                {preview.source_section_count} seen / {preview.projected_held_source_section_count} unpaired
              </strong>
              <small>{preview.source_text_char_count} source chars</small>
            </div>
            <div>
              <span>Annotations</span>
              <strong>
                {preview.source_span_draft_count} span{preview.source_span_draft_count === 1 ? "" : "s"}
              </strong>
              <small>{preview.source_spans_supplied ? "Prompt/response coding included" : "No span coding yet"}</small>
            </div>
            <div>
              <span>Ranked evidence</span>
              <strong>{preview.ranked_evidence_record_count ?? 0} corpus refs</strong>
              <small>{preview.ranked_evidence_vector_query_used ? "Vector query used" : "Lexical preview"}</small>
            </div>
            <div>
              <span>Safety</span>
              <strong>{preview.does_not_mutate_state ? "Non-mutating dry run" : "Review mutation risk"}</strong>
              <small>{preview.no_live_model_call ? "No live model call" : "May call live model"}</small>
            </div>
          </div>
          {firstPair ? (
            <div className="source-pair-example-preview" aria-label="First generated pair preview">
              <span>First item preview</span>
              <strong>
                {firstPair.artifact_mode.toUpperCase()} Pair {String(firstPair.pair_index).padStart(3, "0")}
              </strong>
              <p>{firstPair.prompt_preview}</p>
              <small>
                {firstPair.reason ? `Held: ${labelFromKey(firstPair.reason)}` : firstPair.strategy_label}
                {firstPair.source_chunk_index ? ` / chunk ${firstPair.source_chunk_index}` : ""}
              </small>
            </div>
          ) : (
            <p className="quiet">No creatable prompt/response pair found yet.</p>
          )}
          <ul className="source-pair-safety-list">
            {preview.safety_boundaries.map((boundary) => (
              <li key={boundary}>{boundary.replace(/\btickets\b/gi, "items").replace(/\bticket\b/gi, "item")}</li>
            ))}
          </ul>
        </>
      ) : (
        <p className="quiet">{status || "Generation preview will appear here before you click Generate."}</p>
      )}
    </section>
  );
}

function SourceEvidenceCorpusPanel({
  corpus,
  loading,
  error,
  selectedIds,
  onToggle
}: {
  corpus: EvidenceCorpusResponse | null;
  loading: boolean;
  error: string | null;
  selectedIds: string[];
  onToggle: (embeddingRecordId: string) => void;
}) {
  if (!corpus && !loading && !error) {
    return null;
  }
  const familyCounts = Object.entries(corpus?.corpus_family_counts ?? {})
    .sort(([, left], [, right]) => right - left)
    .slice(0, 4);
  const records = corpus?.records ?? [];
  return (
    <details className="source-evidence-corpus" aria-label="Unified evidence corpus picker">
      <summary>
        <span>
          <FileText size={14} />
          Evidence attached
        </span>
        <strong>
          {loading && !corpus
            ? "Loading reviewed sources"
            : `${selectedIds.length || records.length} source${(selectedIds.length || records.length) === 1 ? "" : "s"}`}
        </strong>
      </summary>
      <header>
        <div>
          <span>
            <FileText size={14} />
            Reviewed sources
          </span>
          <strong>{loading && !corpus ? "Loading reviewed sources" : `${corpus?.record_count ?? 0} reviewed sources`}</strong>
        </div>
        <div>
          <em>{corpus?.excluded_count ?? 0} held</em>
          <em>{corpus?.vector_ready_count ?? 0} vectors</em>
          <em>{selectedIds.length} selected</em>
        </div>
      </header>
      {error ? <p className="quiet">{error}</p> : null}
      {familyCounts.length > 0 ? (
        <div className="source-evidence-families">
          {familyCounts.map(([family, count]) => (
            <span key={family}>
              {labelFromKey(family)} <strong>{count}</strong>
            </span>
          ))}
        </div>
      ) : null}
      {records.length > 0 ? (
        <div className="source-evidence-records">
          {records.slice(0, 5).map((record) => {
            const selected = selectedIds.includes(record.embedding_record_id);
            return (
              <button
                type="button"
                key={record.embedding_record_id}
                className={selected ? "selected" : ""}
                onClick={() => onToggle(record.embedding_record_id)}
                aria-pressed={selected}
              >
                <em>{labelFromKey(record.corpus_family)}</em>
                <strong>{record.title || labelFromKey(record.corpus_family)}</strong>
                <span>{record.input_preview}</span>
              </button>
            );
          })}
        </div>
      ) : (
        <p className="quiet">Reviewed source matches will appear here once available.</p>
      )}
    </details>
  );
}

function PhotoAssetPreview({
  task,
  asset,
  previewAccessToken
}: {
  task: Task;
  asset?: Asset;
  previewAccessToken?: string;
}) {
  const assetId = payloadString(task.input_payload.asset_id) || (task.target_type === "asset" ? task.target_id : "");
  const [failed, setFailed] = useState(false);
  const [variant, setVariant] = useState<"display" | "thumbnail" | "original">("display");

  useEffect(() => {
    setFailed(false);
    setVariant("display");
  }, [assetId, task.id, previewAccessToken]);

  if (!assetId) {
    return null;
  }

  const title =
    payloadString(task.input_payload.source_filename) ||
    payloadString(task.input_payload.asset_title) ||
    payloadString(task.input_payload.title) ||
    asset?.title ||
    asset?.original_filename ||
    "Photo source";
  const driveWebView = payloadString(task.input_payload.drive_web_view_link);
  const driveThumbnail = payloadString(task.input_payload.drive_thumbnail_link);
  const mirrorStatus = payloadString(task.input_payload.mirror_status);
  const statusRows = [
    asset?.import_status ? `Import: ${labelFromKey(asset.import_status)}` : "",
    asset?.processing_status ? `Processing: ${labelFromKey(asset.processing_status)}` : "",
    mirrorStatus ? `Mirror: ${labelFromKey(mirrorStatus)}` : "",
    driveThumbnail ? "Drive thumbnail metadata is present" : "",
    driveWebView ? "Drive source link is present" : ""
  ].filter(Boolean);

  return (
    <section className="photo-preview-panel">
      <div className="photo-preview-header">
        <div>
          <span>Photo preview</span>
          <strong>{title}</strong>
        </div>
        <div className="photo-preview-tools" aria-label="Preview variant">
          {(["display", "thumbnail", "original"] as const).map((option) => (
            <button
              key={option}
              type="button"
              className={variant === option ? "active" : ""}
              onClick={() => {
                setVariant(option);
                setFailed(false);
              }}
              title={`Built: request the ${option} asset preview variant from the API.`}
            >
              {labelFromKey(option)}
            </button>
          ))}
        </div>
      </div>
      <div className="photo-preview-stage">
        {failed ? (
          <div className="photo-preview-empty">
            <Image size={24} />
            <strong>Preview not available yet</strong>
            <span>
              This is still useful as a metadata/photo-memory task. Mirror the source or inspect the dossier when you need pixels.
            </span>
            {statusRows.length > 0 ? (
              <div className="photo-preview-status">
                {statusRows.map((row) => (
                  <small key={row}>{row}</small>
                ))}
              </div>
            ) : null}
            <button type="button" onClick={() => setFailed(false)}>
              Retry
            </button>
            {driveWebView ? (
              <Link href={driveWebView} target="_blank" rel="noreferrer">
                Open source
              </Link>
            ) : null}
          </div>
        ) : (
          <img src={getAssetPreviewUrl(assetId, variant, previewAccessToken)} alt={title} onError={() => setFailed(true)} />
        )}
      </div>
    </section>
  );
}

function PhotoGroupContextCard({ task }: { task: Task }) {
  const payload = task.input_payload;
  const groupKey = payloadString(payload.photo_group_key);
  const canonicalAssetId = payloadString(payload.canonical_asset_id) || payloadString(payload.asset_id);
  const variants = Array.isArray(payload.group_variants)
    ? (payload.group_variants as Record<string, unknown>[])
    : [];
  const retrievalOrigin = payload.retrieval_gap_origin && typeof payload.retrieval_gap_origin === "object"
    ? (payload.retrieval_gap_origin as Record<string, unknown>)
    : {};
  const retrievalReview = payload.retrieval_gap_review && typeof payload.retrieval_gap_review === "object"
    ? (payload.retrieval_gap_review as Record<string, unknown>)
    : {};
  const reviewSessionOrigin = payload.review_session_origin && typeof payload.review_session_origin === "object"
    ? (payload.review_session_origin as Record<string, unknown>)
    : {};
  const retrievalReviewFields = Array.isArray(retrievalReview.required_fields)
    ? (retrievalReview.required_fields as Record<string, unknown>[])
    : [];
  const retrievalQuery = payloadString(retrievalOrigin.query);
  const retrievalQuality = payloadString(retrievalOrigin.candidate_match_quality);
  const isBacklogOnlyReviewSeed = retrievalQuality === "backlog_only"
    || payloadString(retrievalOrigin.selection_reason) === "backlog_sample_no_semantic_match";
  const queryContextLabel = isBacklogOnlyReviewSeed ? "Review seed" : "Search seed";
  const displayRetrievalReviewFields = isBacklogOnlyReviewSeed
    ? retrievalReviewFields.filter((field) => recordString(field, "field_key") !== "retrieval_query_relevance")
    : retrievalReviewFields;
  const sessionSequence = Number(reviewSessionOrigin.sequence_number || 0);
  const sessionSelectedCount = Number(reviewSessionOrigin.selected_count || 0);
  const sessionCompletionSignal = payloadString(reviewSessionOrigin.completion_signal);
  const sessionPlanHash = payloadString(reviewSessionOrigin.plan_content_sha256);
  const sessionMatchQuality = payloadString(reviewSessionOrigin.candidate_match_quality, retrievalQuality || "backlog_only");
  const sessionSelectionReason = payloadString(
    reviewSessionOrigin.candidate_selection_reason,
    payloadString(retrievalOrigin.selection_reason, "selected_from_photo_context_review_session_plan")
  );
  if (!groupKey && variants.length === 0) {
    return null;
  }
  return (
    <section className="photo-group-card" aria-label="Photo group context">
      <header>
        <div>
          <span>Photo group</span>
          <strong>{groupKey || "single photo"}</strong>
        </div>
        <em>{variants.length || 1} variant{(variants.length || 1) === 1 ? "" : "s"}</em>
      </header>
      <div className="photo-group-summary">
        {canonicalAssetId ? (
          <span>
            Canonical
            <strong>{canonicalAssetId.slice(0, 8)}</strong>
          </span>
        ) : null}
        {payload.source_photo_inventory === true ? <span>Created from inventory</span> : null}
        {retrievalQuery ? (
          <span>
            {queryContextLabel}
            <strong>{retrievalQuery}</strong>
            {retrievalQuality ? <em>{labelFromKey(retrievalQuality)}</em> : null}
            {isBacklogOnlyReviewSeed ? <small>workflow provenance only</small> : null}
          </span>
        ) : null}
      </div>
      {Object.keys(reviewSessionOrigin).length > 0 ? (
        <div className="review-session-position-strip" aria-label="Review session position">
          <span>
            <em>Session item</em>
            <strong>
              {sessionSequence > 0 && sessionSelectedCount > 0
                ? `${sessionSequence} / ${sessionSelectedCount}`
                : "session queue"}
            </strong>
          </span>
          <span>
            <em>{queryContextLabel}</em>
            <strong>{payloadString(reviewSessionOrigin.source_query, retrievalQuery || "not set")}</strong>
          </span>
          <span>
            <em>Selection basis</em>
            <strong>{labelFromKey(sessionMatchQuality)}</strong>
          </span>
          <span>
            <em>Selection reason</em>
            <strong>{labelFromKey(sessionSelectionReason)}</strong>
          </span>
          {sessionCompletionSignal ? (
            <span>
              <em>Completion signal</em>
              <strong>{labelFromKey(sessionCompletionSignal)}</strong>
            </span>
          ) : null}
          {sessionPlanHash ? (
            <span>
              <em>Plan hash</em>
              <strong>{sessionPlanHash.slice(0, 12)}</strong>
            </span>
          ) : null}
          <small>{payloadString(reviewSessionOrigin.review_policy, "query-aware no-claim review session")}</small>
        </div>
      ) : null}
      {retrievalQuery ? (
        <div className="retrieval-gap-task-plan" aria-label="Retrieval gap task plan">
          <span>
            <strong>Adam context required</strong>
            <em>{recordString(retrievalReview, "review_policy", "retrieval_gap_no_claim_until_adam_context")}</em>
          </span>
          {displayRetrievalReviewFields.length > 0 ? (
            <small>
              Review before downstream use:{" "}
              {displayRetrievalReviewFields
                .map((field) => recordString(field, "label", recordString(field, "field_key")))
                .filter(Boolean)
                .join(", ")}
            </small>
          ) : null}
        </div>
      ) : null}
      {variants.length > 0 ? (
        <div className="photo-variant-list">
          {variants.slice(0, 8).map((variant, index) => {
            const assetId = payloadString(variant.asset_id, `variant-${index + 1}`);
            const title = payloadString(variant.title, `Variant ${index + 1}`);
            const isCanonical = canonicalAssetId && assetId === canonicalAssetId;
            return (
              <div key={`${assetId}-${index}`} className={isCanonical ? "canonical" : ""}>
                <strong>{title}</strong>
                <span>{payloadString(variant.processing_status, "unknown")}</span>
                {variant.is_copy_variant === true ? <em>copy</em> : null}
                {isCanonical ? <em>canonical</em> : null}
              </div>
            );
          })}
        </div>
      ) : null}
    </section>
  );
}

function PhotoPromptPairSourceCard({
  task,
  asset,
  previewAccessToken
}: {
  task: Task;
  asset?: Asset;
  previewAccessToken?: string;
}) {
  const payload = task.input_payload;
  const sourcePhotoId = payloadString(payload.source_photo_id);
  if (!sourcePhotoId) {
    return null;
  }
  const boundary = payload.boundary_snapshot && typeof payload.boundary_snapshot === "object"
    ? (payload.boundary_snapshot as Record<string, unknown>)
    : {};
  const title =
    asset?.title ||
    asset?.original_filename ||
    payloadString(payload.source_title) ||
    payloadString(payload.asset_title) ||
    "Source photo";
  const profileStatus = payloadString(payload.source_profile_status, "unknown");
  const truthStatus = payloadString(payload.source_truth_status, payloadString(payload.truth_status, "unknown"));
  const variantLabel = payloadString(payload.photo_pair_variant_label);
  const variantKey = payloadString(payload.photo_pair_variant_key);
  const generationBatchId = payloadString(payload.photo_pair_generation_batch_id);
  const privacyLevel = typeof boundary.privacy_level === "string" ? boundary.privacy_level : "unreviewed";
  const sftAllowed = boundary.usable_for_sft === true;
  const retrievalOrigin = payload.retrieval_gap_origin && typeof payload.retrieval_gap_origin === "object"
    ? (payload.retrieval_gap_origin as Record<string, unknown>)
    : {};
  const retrievalQuery = payloadString(retrievalOrigin.query);
  const retrievalQuality = payloadString(retrievalOrigin.candidate_match_quality);

  return (
    <section className="photo-pair-source-card">
      <div className="photo-pair-thumb">
        <img src={getAssetPreviewUrl(sourcePhotoId, "thumbnail", previewAccessToken)} alt={title} />
      </div>
      <div className="photo-pair-source-details">
        <span>Photo grounding source</span>
        <strong>{title}</strong>
        <div>
          {variantLabel ? <em>{variantLabel}</em> : null}
          {generationBatchId ? <em>{generationBatchId}</em> : null}
          <em>{labelFromKey(profileStatus)}</em>
          <em>{labelFromKey(truthStatus)}</em>
          <em>{labelFromKey(privacyLevel)}</em>
          <em data-tone={sftAllowed ? "good" : "warning"}>{sftAllowed ? "SFT allowed" : "SFT held"}</em>
        </div>
        {variantKey ? (
          <p className="source-card-note">
            Generated as the <strong>{variantLabel || labelFromKey(variantKey)}</strong> candidate from this reviewed photo. Keep the best
            variants, edit them hard, and delete the weak ones.
          </p>
        ) : null}
        {retrievalQuery ? (
          <p className="source-card-note">
            Review seed: <strong>{retrievalQuery}</strong>
            {retrievalQuality ? ` (${labelFromKey(retrievalQuality)})` : ""}. This is workflow provenance, not a memory claim.
          </p>
        ) : null}
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

type ChunkQualityTone = "ready" | "edit" | "neutral";

function segmentMetadataString(segment: Segment, key: string, fallback = ""): string {
  const value = segment.metadata_json[key];
  return typeof value === "string" ? value : fallback;
}

function segmentMetadataBoolean(segment: Segment, key: string): boolean {
  return segment.metadata_json[key] === true;
}

function chunkDisplayLabel(segment: Segment, fallbackIndex: number): string {
  const chunkIndex = locatorNumber(segment.locator, "chunk_index", fallbackIndex);
  if (segment.locator.kind === "natural_section" || segmentMetadataString(segment, "chunking_strategy") === "natural_section") {
    return `Section ${chunkIndex}`;
  }
  return `Chunk ${chunkIndex}`;
}

function chunkReviewHint(segment: Segment): { label: string; shortLabel: string; tone: ChunkQualityTone } | null {
  const hint = segmentMetadataString(segment, "section_review_hint");
  if (!hint) {
    return null;
  }
  if (hint === "needs_context") {
    return { label: "Needs context", shortLabel: "Context", tone: "edit" };
  }
  if (hint === "needs_split") {
    return { label: "Needs split", shortLabel: "Split", tone: "edit" };
  }
  return { label: labelFromKey(hint), shortLabel: "Natural", tone: "neutral" };
}

function chunkQualityFor(segment: Segment, readyIds: Set<string>, editIds: Set<string>): {
  label: string;
  shortLabel: string;
  tone: ChunkQualityTone;
} {
  const metadataStatus = segmentMetadataString(segment, "chunk_quality_status");
  if (metadataStatus === "pairing_ready_reference" || readyIds.has(segment.id)) {
    return { label: "Reference ready", shortLabel: "Ready", tone: "ready" };
  }
  if (metadataStatus === "needs_adam_edit" || editIds.has(segment.id)) {
    return { label: "Needs Adam edit", shortLabel: "Edit", tone: "edit" };
  }
  if (segment.source_truth_status === "model_generated") {
    return { label: "Model generated", shortLabel: "Model", tone: "edit" };
  }
  if (metadataStatus) {
    return { label: labelFromKey(metadataStatus), shortLabel: labelFromKey(metadataStatus), tone: "neutral" };
  }
  return { label: "Reviewed", shortLabel: "Reviewed", tone: "neutral" };
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
  const textExtractionDerivativeId = payloadString(task.input_payload.text_extraction_derivative_id);
  const [chunks, setChunks] = useState<Segment[]>([]);
  const [activeId, setActiveId] = useState(initialSelection.active_chunk_id ?? "");
  const [selectedIds, setSelectedIds] = useState<string[]>(initialSelection.selected_chunk_ids);
  const [error, setError] = useState("");
  const readyPayloadIds = useMemo(() => new Set(payloadArray(task.input_payload.pairing_ready_chunk_ids)), [
    task.input_payload.pairing_ready_chunk_ids
  ]);
  const editPayloadIds = useMemo(() => new Set(payloadArray(task.input_payload.needs_adam_edit_chunk_ids)), [
    task.input_payload.needs_adam_edit_chunk_ids
  ]);
  const activeChunk = chunks.find((chunk) => chunk.id === activeId) ?? chunks[0];
  const activeQuality = activeChunk ? chunkQualityFor(activeChunk, readyPayloadIds, editPayloadIds) : null;
  const qualitySummary = useMemo(() => {
    let ready = 0;
    let edit = 0;
    for (const chunk of chunks) {
      const quality = chunkQualityFor(chunk, readyPayloadIds, editPayloadIds);
      if (quality.tone === "ready") {
        ready += 1;
      } else if (quality.tone === "edit") {
        edit += 1;
      }
    }
    return { ready, edit, other: Math.max(0, chunks.length - ready - edit) };
  }, [chunks, editPayloadIds, readyPayloadIds]);

  useEffect(() => {
    setChunks([]);
    setActiveId(initialSelection.active_chunk_id ?? "");
    setSelectedIds(initialSelection.selected_chunk_ids);
    setError("");
    if (!assetId) {
      return;
    }

    let cancelled = false;
    getAssetTextChunks(assetId, textExtractionDerivativeId || undefined)
      .then((nextChunks) => {
        if (cancelled) {
          return;
        }
        const shouldDefaultSelect =
          task.task_type === "text_segment_boundary_review" && initialSelection.selected_chunk_ids.length === 0;
        const nextSelectedIds = shouldDefaultSelect ? nextChunks.map((chunk) => chunk.id) : initialSelection.selected_chunk_ids;
        setChunks(nextChunks);
        setActiveId(initialSelection.active_chunk_id ?? nextChunks[0]?.id ?? "");
        setSelectedIds(nextSelectedIds);
      })
      .catch((caught: unknown) => {
        if (!cancelled) {
          setError(caught instanceof Error ? caught.message : "Unable to load chunks.");
        }
      });

    return () => {
      cancelled = true;
    };
  }, [assetId, initialSelection.active_chunk_id, initialSelection.selected_chunk_ids, task.id, task.task_type, textExtractionDerivativeId]);

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
          <strong>
            {selectedIds.length} selected / {chunks.length} available
          </strong>
        </div>
        {qualitySummary.ready > 0 || qualitySummary.edit > 0 ? (
          <div className="chunk-quality-summary" aria-label="Chunk quality summary">
            {qualitySummary.ready > 0 ? <span data-tone="ready">{qualitySummary.ready} reference-ready</span> : null}
            {qualitySummary.edit > 0 ? <span data-tone="edit">{qualitySummary.edit} need Adam edit</span> : null}
            {qualitySummary.other > 0 ? <span data-tone="neutral">{qualitySummary.other} other</span> : null}
          </div>
        ) : null}
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
              const quality = chunkQualityFor(chunk, readyPayloadIds, editPayloadIds);
              const reviewHint = chunkReviewHint(chunk);
              const displayLabel = chunkDisplayLabel(chunk, index + 1);
              const className = [
                "chunk-row",
                `quality-${quality.tone}`,
                reviewHint?.tone === "edit" ? "quality-edit" : "",
                chunk.id === activeChunk?.id ? "active" : "",
                selected ? "selected" : ""
              ]
                .filter(Boolean)
                .join(" ");
              return (
                <div className={className} key={chunk.id}>
                  <button type="button" onClick={() => setActiveId(chunk.id)} title={quality.label}>
                    <span>{displayLabel}</span>
                    <small>{[quality.shortLabel, reviewHint?.shortLabel].filter(Boolean).join(" / ")}</small>
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
                <span>{chunkDisplayLabel(activeChunk, 1)}</span>
                {activeQuality ? <span className="chunk-quality-pill" data-tone={activeQuality.tone}>{activeQuality.label}</span> : null}
                {activeChunk.locator.kind === "natural_section" || segmentMetadataBoolean(activeChunk, "natural_boundary") ? (
                  <span className="chunk-quality-pill" data-tone="ready">Natural boundary</span>
                ) : null}
                {chunkReviewHint(activeChunk) ? (
                  <span className="chunk-quality-pill" data-tone={chunkReviewHint(activeChunk)?.tone}>
                    {chunkReviewHint(activeChunk)?.label}
                  </span>
                ) : null}
                <span>{labelFromKey(activeChunk.source_truth_status)}</span>
                {activeChunk.locator.kind === "prompt_pair_example" ? (
                  <span>prompt-pair example</span>
                ) : (
                  <span>
                    chars {locatorNumber(activeChunk.locator, "char_start")}-
                    {locatorNumber(activeChunk.locator, "char_end")}
                  </span>
                )}
              </div>
              {segmentMetadataString(activeChunk, "chunk_quality_notes") ? (
                <p className="chunk-quality-note">{segmentMetadataString(activeChunk, "chunk_quality_notes")}</p>
              ) : null}
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

function PhotoMemoryReviewForm({
  task,
  initialDecisions,
  onChange,
  onOperatorSubmit
}: {
  task: Task;
  initialDecisions: Decisions;
  onChange: (value: Decisions) => void;
  onOperatorSubmit?: (decisionsOverride?: Decisions) => Promise<void>;
}) {
  const payload = task.input_payload;
  const draft = payload.vision_draft && typeof payload.vision_draft === "object"
    ? (payload.vision_draft as Record<string, unknown>)
    : {};
  const machineDraftDefaults = {
    description: payloadString(draft.visual_summary),
    visiblePeople: [...payloadArray(payload.machine_guess_people), ...payloadArray(draft.visible_people)].join(", "),
    place: payloadString(payload.machine_guess_place) || payloadArray(draft.places).join(", "),
    dateRange: payloadString(draft.time_period_guess, "unknown"),
    tags: [...payloadArray(draft.objects), ...payloadArray(draft.themes)].join(", "),
    objects: payloadArray(draft.objects).join(", "),
    ocrText: payloadString(draft.handwriting_text) || payloadString(draft.ocr_text)
  };
  const hasMachineDraftDefaults = Object.values(machineDraftDefaults).some((value) => value.trim() && value !== "unknown");
  const questions = Array.isArray(payload.suggested_questions) ? (payload.suggested_questions as Record<string, unknown>[]) : [];
  const initialQuestionAnswers =
    initialDecisions.question_answers && typeof initialDecisions.question_answers === "object"
      ? (initialDecisions.question_answers as Record<string, unknown>)
      : {};
  const [visionAccuracy, setVisionAccuracy] = useState(decisionString(initialDecisions, "vision_accuracy", "not_applicable"));
  const [description, setDescription] = useState(
    decisionString(
      initialDecisions,
      "accepted_visual_description",
      decisionString(initialDecisions, "visual_description_correction", machineDraftDefaults.description)
    )
  );
  const [visiblePeople, setVisiblePeople] = useState(
    decisionListText(
      initialDecisions,
      "visible_people",
      decisionListText(initialDecisions, "people", machineDraftDefaults.visiblePeople)
    )
  );
  const [absentPeople, setAbsentPeople] = useState(decisionListText(initialDecisions, "absent_but_relevant_people"));
  const [place, setPlace] = useState(
    decisionString(
      initialDecisions,
      "place",
      decisionListText(initialDecisions, "places", machineDraftDefaults.place)
    )
  );
  const [dateRange, setDateRange] = useState(
    decisionString(initialDecisions, "date_or_range", machineDraftDefaults.dateRange)
  );
  const [dateConfidence, setDateConfidence] = useState(decisionString(initialDecisions, "date_confidence", "unknown"));
  const [event, setEvent] = useState(decisionString(initialDecisions, "event", "unknown"));
  const [tags, setTags] = useState(
    decisionListText(initialDecisions, "accepted_tags", machineDraftDefaults.tags)
  );
  const [objects, setObjects] = useState(decisionListText(initialDecisions, "concrete_objects", machineDraftDefaults.objects));
  const [rejectedInferences, setRejectedInferences] = useState(decisionListText(initialDecisions, "rejected_system_inferences"));
  const [openQuestions, setOpenQuestions] = useState(decisionListText(initialDecisions, "open_questions"));
  const [questionAnswers, setQuestionAnswers] = useState<Record<string, string>>(() =>
    Object.fromEntries(Object.entries(initialQuestionAnswers).map(([key, value]) => [key, String(value ?? "")]))
  );
  const [adamContextNote, setAdamContextNote] = useState(decisionString(initialDecisions, "adam_context_note"));
  const [invisibleContext, setInvisibleContext] = useState(decisionString(initialDecisions, "invisible_context_note"));
  const [memoryPotential, setMemoryPotential] = useState(decisionNumber(initialDecisions, "memory_potential", 4));
  const [privacySensitivity, setPrivacySensitivity] = useState(decisionNumber(initialDecisions, "privacy_sensitivity", 2));
  const [privacyLevel, setPrivacyLevel] = useState(decisionString(initialDecisions, "privacy_level", "family_private"));
  const [privacyNotes, setPrivacyNotes] = useState(decisionString(initialDecisions, "privacy_notes"));
  const [readyForDownstream, setReadyForDownstream] = useState(decisionString(initialDecisions, "ready_for_downstream", "later"));
  const [galleryEligibility, setGalleryEligibility] = useState(decisionString(initialDecisions, "gallery_eligibility", "family_private"));
  const [ocrReviewStatus, setOcrReviewStatus] = useState(decisionString(initialDecisions, "ocr_review_status", "not_present"));
  const [ocrTruthStatus, setOcrTruthStatus] = useState(decisionString(initialDecisions, "ocr_truth_status", "system_inference"));
  const [correctedOcrText, setCorrectedOcrText] = useState(
    decisionString(initialDecisions, "corrected_ocr_text", machineDraftDefaults.ocrText)
  );
  const [projection, setProjection] = useState<PhotoContextSubmitProjection | null>(null);
  const [projectionStatus, setProjectionStatus] = useState(
    task.task_type === "photo_context" ? "Backend projection pending" : "Local preview"
  );
  const [copyReviewPromptStatus, setCopyReviewPromptStatus] = useState("");
  const [adamReviewPasteText, setAdamReviewPasteText] = useState("");
  const [adamReviewPasteStatus, setAdamReviewPasteStatus] = useState("Paste numbered answers from Adam, then apply.");
  const [operatorSuggestion, setOperatorSuggestion] = useState<OperatorAssistantSuggestion | null>(null);
  const [operatorStatus, setOperatorStatus] = useState("Assistant loading");
  const [operatorAnswer, setOperatorAnswer] = useState("");
  const [operatorApplyStatus, setOperatorApplyStatus] = useState("");
  const [operatorMessages, setOperatorMessages] = useState<OperatorChatMessage[]>(() => operatorMessagesFromDecisions(initialDecisions));
  const downstreamTruthStatus = reviewedPhotoTruthStatus({
    taskType: task.task_type,
    description,
    adamContextNote,
    invisibleContext,
    questionAnswers,
    visionAccuracy
  });
  const downstreamConsequences = photoReviewConsequences({
    privacyLevel,
    readyForDownstream,
    galleryEligibility,
    truthStatus: downstreamTruthStatus
  });
  const answeredQuestionPreview = Object.entries(questionAnswers)
    .filter(([, value]) => String(value ?? "").trim())
    .map(([key, value]) => `${promptFromDecisionKey(key)}: ${String(value).trim()}`);
  const downstreamSearchText = [
    description ? `Visual description: ${description}` : "",
    visiblePeople ? `People: ${parseList(visiblePeople).join(", ")}` : "",
    place ? `Place: ${place}` : "",
    dateRange && dateRange !== "unknown" ? `Date: ${dateRange}` : "",
    event && event !== "unknown" ? `Event: ${event}` : "",
    tags ? `Tags and themes: ${parseList(tags).join(", ")}` : "",
    objects ? `Visible objects: ${parseList(objects).join(", ")}` : "",
    adamContextNote ? `Adam context: ${adamContextNote}` : "",
    invisibleContext ? `Invisible context: ${invisibleContext}` : "",
    answeredQuestionPreview.length ? `Adam answers: ${answeredQuestionPreview.join(" | ")}` : "",
    openQuestions ? `Open questions: ${parseList(openQuestions).join(", ")}` : ""
  ].filter(Boolean).join("\n");

  const currentDecisions = useMemo<Decisions>(() => {
    const people = parseList(visiblePeople);
    const places = parseList(place);
    const acceptedTags = parseList(tags);
    return {
      vision_accuracy: visionAccuracy,
      accepted_visual_description: description,
      visual_description_correction: description,
      people,
      visible_people: people,
      absent_but_relevant_people: parseList(absentPeople),
      places,
      place,
      date_or_range: dateRange,
      date_confidence: dateConfidence,
      event,
      accepted_tags: acceptedTags,
      themes: acceptedTags,
      concrete_objects: parseList(objects),
      rejected_system_inferences: parseList(rejectedInferences),
      open_questions: parseList(openQuestions),
      question_answers: questionAnswers,
      adam_context_note: adamContextNote,
      invisible_context_note: invisibleContext,
      memory_potential: memoryPotential,
      privacy_sensitivity: privacySensitivity,
      privacy_level: privacyLevel,
      privacy_notes: privacyNotes,
      ready_for_downstream: readyForDownstream,
      gallery_eligibility: galleryEligibility,
      ocr_review_status: ocrReviewStatus,
      ocr_truth_status: ocrTruthStatus,
      corrected_ocr_text: correctedOcrText,
      source_genre: payloadString(payload.asset_type, "photo"),
      downstream_search_text_preview: downstreamSearchText,
      truth_status: downstreamTruthStatus,
      voice_presence: "absent",
      operator_assistant_log: operatorMessages
    };
  }, [
    absentPeople,
    adamContextNote,
    correctedOcrText,
    dateConfidence,
    dateRange,
    description,
    event,
    galleryEligibility,
    invisibleContext,
    memoryPotential,
    objects,
    ocrReviewStatus,
    ocrTruthStatus,
    onChange,
    openQuestions,
    operatorMessages,
    place,
    privacyLevel,
    privacyNotes,
    privacySensitivity,
    questionAnswers,
    readyForDownstream,
    rejectedInferences,
    tags,
    downstreamSearchText,
    downstreamTruthStatus,
    task.task_type,
    payload.asset_type,
    visiblePeople,
    visionAccuracy
  ]);

  useEffect(() => {
    onChange(currentDecisions);
  }, [currentDecisions, onChange]);

  useEffect(() => {
    let cancelled = false;
    setOperatorStatus("Finding next best question");
    const timeout = window.setTimeout(() => {
      getOperatorAssistantSuggestion(task.id, currentDecisions)
        .then((suggestion) => {
          if (!cancelled) {
            setOperatorSuggestion(suggestion);
            setOperatorStatus(suggestion.live_model_call_used ? "Model-assisted" : "Deterministic helper");
          }
        })
        .catch((caught: unknown) => {
          if (!cancelled) {
            setOperatorSuggestion(null);
            setOperatorStatus(caught instanceof Error ? `Assistant unavailable: ${caught.message}` : "Assistant unavailable");
          }
        });
    }, 350);
    return () => {
      cancelled = true;
      window.clearTimeout(timeout);
    };
  }, [currentDecisions, task.id]);

  useEffect(() => {
    if (task.task_type !== "photo_context") {
      setProjection(null);
      setProjectionStatus("Local preview");
      return;
    }
    let cancelled = false;
    setProjectionStatus("Updating backend projection");
    const timeout = window.setTimeout(() => {
      previewPhotoContextSubmitProjection(task.id, currentDecisions)
        .then((nextProjection) => {
          if (!cancelled) {
            setProjection(nextProjection);
            setProjectionStatus(nextProjection.supported ? "Backend projection ready" : "Projection unavailable");
          }
        })
        .catch((caught: unknown) => {
          if (!cancelled) {
            setProjection(null);
            setProjectionStatus(caught instanceof Error ? `Projection failed: ${caught.message}` : "Projection failed");
          }
        });
    }, 450);
    return () => {
      cancelled = true;
      window.clearTimeout(timeout);
    };
  }, [currentDecisions, task.id, task.task_type]);

  const metadataProjection = projection?.metadata_profile;
  const vectorProjection = projection?.memory_embedding_vector_handoff;
  const galleryProjection = projection?.gallery;
  const memoryProjection = projection?.memory;
  const projectionVectorStatus = recordString(vectorProjection, "status");
  const retrievalOrigin = payload.retrieval_gap_origin && typeof payload.retrieval_gap_origin === "object"
    ? (payload.retrieval_gap_origin as Record<string, unknown>)
    : {};
  const retrievalQuery = payloadString(retrievalOrigin.query);
  const retrievalQuality = payloadString(retrievalOrigin.candidate_match_quality);
  const retrievalSelectionReason = payloadString(retrievalOrigin.selection_reason);
  const isBacklogOnlyReviewSeed = retrievalQuality === "backlog_only" || retrievalSelectionReason === "backlog_sample_no_semantic_match";
  const retrievalQueryLabel = isBacklogOnlyReviewSeed ? "Review session seed" : "Search seed";
  const reviewQuestions = isBacklogOnlyReviewSeed
    ? questions.filter((question, index) => payloadString(question.id, `question_${index + 1}`) !== "retrieval_query_relevance")
    : questions;
  const retrievalReview = payload.retrieval_gap_review && typeof payload.retrieval_gap_review === "object"
    ? (payload.retrieval_gap_review as Record<string, unknown>)
    : {};
  const reviewSessionOrigin = payload.review_session_origin && typeof payload.review_session_origin === "object"
    ? (payload.review_session_origin as Record<string, unknown>)
    : {};
  const retrievalReviewFields = Array.isArray(retrievalReview.required_fields)
    ? (retrievalReview.required_fields as Record<string, unknown>[])
    : [];
  const retrievalIncompleteFields = projection?.field_requirements?.length
    ? projection.field_requirements
        .filter((item) => recordString(item, "status") !== "complete")
        .map((item) => recordString(item, "label", recordString(item, "field_key")))
    : retrievalReviewFields
        .filter((field) => !isBacklogOnlyReviewSeed || recordString(field, "field_key") !== "retrieval_query_relevance")
        .map((field) => recordString(field, "label", recordString(field, "field_key")))
        .filter(Boolean);
  const retrievalQueryAnswer = String(questionAnswers.retrieval_query_relevance ?? "").trim();
  const taskPayoffTemplate = retrievalQuery
    ? [
        `Photo memory: ${payloadString(payload.asset_title, payloadString(payload.title, "Untitled photo"))}`,
        `${retrievalQueryLabel}: ${retrievalQuery}`,
        `Visible facts: ${description.trim() || "[requires Adam: reviewed visible facts]"}`,
        `Memory associations: ${adamContextNote.trim() || invisibleContext.trim() || "[requires Adam: what this photo brings up]"}`,
        `Search connection: ${
          retrievalQueryAnswer
            || (isBacklogOnlyReviewSeed
              ? "[optional: only answer if this photo truly connects to the review seed]"
              : "[requires Adam: if this search seed is truly related, explain how; otherwise mark unrelated or uncertain]")
        }`,
        `Adam context: ${invisibleContext.trim() || adamContextNote.trim() || "[requires Adam: invisible memory context]"}`,
        `Uncertainty: ${openQuestions.trim() || "[requires Adam: explicit uncertainty/open questions]"}`,
        `Boundary: ${privacyLevel || "[requires Adam: boundary and retrieval permission]"}`
      ].join("\n")
    : "";
  const promotionChecklist = projection?.field_requirements?.length
    ? [
        ...projection.field_requirements.map((item) => {
          const fieldKey = recordString(item, "field_key", "field");
          const status = recordString(item, "status", "missing");
          return {
            key: fieldKey,
            label: recordString(item, "label", fieldKey),
            status,
            reason: recordString(item, "reason"),
            tone: checklistTone(status)
          };
        }),
        {
          key: "vector_handoff_status",
          label: "Vector handoff status",
          status: projectionVectorStatus || "unknown",
          reason: recordString(vectorProjection, "reason", "Default vector handoff requires Adam-reviewed context, clearance, and boundary."),
          tone: checklistTone(projectionVectorStatus || "unknown")
        }
      ]
    : localPhotoPromotionChecklist({
        description,
        adamContextNote,
        invisibleContext,
        questionAnswers,
        privacyLevel,
        readyForDownstream,
        ocrReviewStatus,
        vectorStatus: ""
      });
  const promotionCompleteCount = promotionChecklist.filter((item) => item.tone === "good").length;
  const promotionHeldCount = Math.max(0, promotionChecklist.length - promotionCompleteCount);
  const sessionRequirementRows = projection?.field_requirements?.length
    ? projection.field_requirements
    : retrievalReviewFields
        .filter((field) => !isBacklogOnlyReviewSeed || recordString(field, "field_key") !== "retrieval_query_relevance")
        .map((field) => ({
          field_key: recordString(field, "field_key"),
          label: recordString(field, "label", recordString(field, "field_key")),
          status: "missing"
        }));
  const sessionRequirementCompleteCount = sessionRequirementRows.filter(
    (item) => recordString(item, "status") === "complete"
  ).length;
  const sessionRequirementTotal = sessionRequirementRows.length;
  const sessionBlockers = projection?.blocked_reasons ?? [];
  const sessionMetricImpact =
    projectionVectorStatus === "eligible_reviewed_record"
      ? "Would move session completion metric on submit"
      : sessionBlockers.length
        ? "Session metric waits for blockers"
        : "Session metric waits for backend projection";
  const sessionPositionText = `${recordString(reviewSessionOrigin, "sequence_number", "?")} / ${recordString(
    reviewSessionOrigin,
    "selected_count",
    "?"
  )}`;
  const adamFocusItems = [
    {
      key: "reviewed_visual_description",
      label: "Reviewed visual description",
      status: description.trim() ? "complete" : "missing",
      detail: "Visible facts Adam confirms or corrects.",
      unlocks: ["photo_memory_text_record", "gallery/retrieval description"]
    },
    ...(retrievalQuery && !isBacklogOnlyReviewSeed
      ? [
          {
            key: "retrieval_query_relevance",
            label: "Search connection",
            status: retrievalQueryAnswer ? "complete" : "missing",
            detail: `If this photo genuinely connects to "${retrievalQuery}", say how. Otherwise mark it unrelated or uncertain.`,
            unlocks: ["retrieval_search_candidate_for_query", "reviewed-only query provenance"]
          }
        ]
      : []),
    {
      key: "why_it_matters",
      label: "Memory it brings up",
      status: adamContextNote.trim() ? "complete" : "missing",
      detail: "The memory, story, relationship, or association this photo sparks for Adam.",
      unlocks: ["Adam-authored memory meaning", "photo memory summary"]
    },
    {
      key: "invisible_context",
      label: "Invisible context",
      status: invisibleContext.trim() ? "complete" : "missing",
      detail: "People, meaning, or circumstances not visible in the pixels.",
      unlocks: ["photo_memory_metadata_profile", "context-pack evidence"]
    },
    {
      key: "open_questions",
      label: "Open questions",
      status: openQuestions.trim() ? "complete" : "missing",
      detail: "Uncertainty to preserve instead of smoothing over.",
      unlocks: ["uncertainty field", "non-invented retrieval record"]
    }
  ];
  const adamFocusCompleteCount = adamFocusItems.filter((item) => item.status === "complete").length;
  const firstIncompleteAdamFocus = adamFocusItems.find((item) => item.status !== "complete");
  const adamFocusMetricText = (status: string) =>
    status === "complete" ? "Ready for session metric on submit" : "Blocks session metric until answered";
  const missingAdamFocusItems = adamFocusItems.filter((item) => item.status !== "complete");
  const adamAnswerTemplateText = (missingAdamFocusItems.length ? missingAdamFocusItems : adamFocusItems)
    .map((item, index) => `${index + 1}. ${item.label}:\n`)
    .join("\n");
  const adamReviewPromptText = [
    `Photo: ${payloadString(payload.asset_title, payloadString(payload.title, "Untitled photo"))}`,
    retrievalQuery
      ? `${retrievalQueryLabel}: ${retrievalQuery}${isBacklogOnlyReviewSeed ? " (workflow provenance only; not a question Adam must answer)" : ""}`
      : "Review session seed: none",
    "",
    "Please answer only from Adam's memory or direct observation. Do not invent or smooth over uncertainty.",
    "This is a review prompt, not generated memory text. Let the photo spark memories; do not force it to match the review seed.",
    "",
    ...adamFocusItems.map((item, index) => `${index + 1}. ${item.label}: ${item.detail}`)
  ].join("\n");
  const projectionConsequences = projection?.supported
    ? [
        {
          label: "Truth label",
          value: labelFromKey(recordString(metadataProjection, "truth_status_after", downstreamTruthStatus)),
          tone: recordString(metadataProjection, "truth_status_after") === "adam_memory" ? "good" : "neutral"
        },
        {
          label: "Vector handoff",
          value: labelFromKey(projectionVectorStatus || "unknown"),
          tone: projectionVectorStatus === "eligible_reviewed_record" ? "good" : "warning"
        },
        {
          label: "Gallery",
          value: recordBoolean(galleryProjection, "hidden_by_boundary")
            ? "Hidden by boundary"
            : labelFromKey(recordString(galleryProjection, "scope_after", "Held or context-only")),
          tone: recordBoolean(galleryProjection, "hidden_by_boundary") ? "warning" : "good"
        },
        {
          label: "Memory",
          value: recordBoolean(memoryProjection, "would_create")
            ? "Will create"
            : recordBoolean(memoryProjection, "would_update")
              ? "Will update"
              : "Not created",
          tone: recordBoolean(memoryProjection, "would_create") || recordBoolean(memoryProjection, "would_update") ? "good" : "warning"
        },
        {
          label: "Training",
          value: "Not SFT/DPO material",
          tone: "neutral"
        }
      ]
    : downstreamConsequences;
  const projectionSearchText = recordString(projection?.profile_embedding, "input_preview") || downstreamSearchText;
  const vectorProjectionReason = recordString(
    vectorProjection,
    "reason",
    "Submit stores reviewed photo context without making SFT/DPO training material."
  );
  const submitOutcomePreview = (() => {
    if (task.task_type !== "photo_context") {
      return {
        label: "Saves reviewed photo annotation",
        detail: "Vision draft review keeps machine help separate until a photo-context projection is available."
      };
    }
    if (!projection) {
      return {
        label: "Backend projection pending",
        detail: "Waiting to confirm whether Submit creates memory, holds context, or blocks vector handoff."
      };
    }
    if (!projection.supported) {
      return {
        label: "Saves review without vector projection",
        detail: "This task is not currently eligible for backend photo-context projection."
      };
    }
    if (projectionVectorStatus === "eligible_reviewed_record") {
      return {
        label: "Creates vector-safe memory record",
        detail: "Reviewed-only handoff; no live embedding call; no ordinary DB vector storage."
      };
    }
    if (projectionVectorStatus === "excluded_by_boundary") {
      return {
        label: "Saves review but excludes vector handoff",
        detail: vectorProjectionReason
      };
    }
    if (projectionVectorStatus === "held_pending_downstream_clearance") {
      return {
        label: "Saves held photo context",
        detail: "Adam context is preserved, but retrieval and vector handoff wait for downstream clearance."
      };
    }
    if (projectionVectorStatus === "held_missing_memory_context") {
      return {
        label: "Needs context before memory export",
        detail: "Submit can save progress, but the vector memory record stays held until required context is complete."
      };
    }
    return {
      label: labelFromKey(projection.submit_readiness || projectionVectorStatus || "review saved"),
      detail: projection.blocked_reasons.length
        ? `Held or blocked: ${projection.blocked_reasons.map(labelFromKey).join(", ")}.`
        : vectorProjectionReason
    };
  })();

  function updateQuestionAnswer(questionId: string, value: string) {
    setQuestionAnswers((current) => ({ ...current, [questionId]: value }));
  }

  function restoreMachineDraftDefaults() {
    setDescription(machineDraftDefaults.description);
    setVisiblePeople(machineDraftDefaults.visiblePeople);
    setPlace(machineDraftDefaults.place);
    setDateRange(machineDraftDefaults.dateRange);
    setTags(machineDraftDefaults.tags);
    setObjects(machineDraftDefaults.objects);
    setCorrectedOcrText(machineDraftDefaults.ocrText);
  }

  function setRetrievalReadyDefaults() {
    setPrivacyLevel("family_private");
    setReadyForDownstream("yes");
    setGalleryEligibility("family_private");
    if (!correctedOcrText.trim()) {
      setOcrReviewStatus("not_present");
    }
  }

  function applySessionSafeDefaults() {
    setRetrievalReadyDefaults();
  }

  function focusPhotoContextField(fieldKey: string) {
    const field = document.querySelector<HTMLElement>(`[data-focus-key="${fieldKey}"]`);
    const target = field?.querySelector<HTMLElement>("textarea, input, select, button");
    const focusTarget = target ?? field;
    focusTarget?.scrollIntoView({ block: "center", behavior: "smooth" });
    window.setTimeout(() => focusTarget?.focus(), 150);
  }

  async function copyAdamReviewPrompt() {
    try {
      await navigator.clipboard.writeText(adamReviewPromptText);
      setCopyReviewPromptStatus("Copied review prompt");
    } catch {
      setCopyReviewPromptStatus("Prompt preview is ready to select");
    }
  }

  function startAdamAnswerTemplate() {
    setAdamReviewPasteText(adamAnswerTemplateText);
    setAdamReviewPasteStatus(
      `Template ready for ${missingAdamFocusItems.length || adamFocusItems.length} Adam field${
        (missingAdamFocusItems.length || adamFocusItems.length) === 1 ? "" : "s"
      }. Replace the blank lines with Adam's answers.`
    );
  }

  function applyAdamReviewAnswers() {
    const matches = Array.from(adamReviewPasteText.matchAll(/(?:^|\n)\s*(\d+)\.\s*([^:\n]+):?\s*/g));
    const answers = new Map<string, string>();

    for (let index = 0; index < matches.length; index += 1) {
      const match = matches[index];
      const nextMatch = matches[index + 1];
      const label = String(match[2] ?? "").trim().toLowerCase();
      const answer = adamReviewPasteText
        .slice((match.index ?? 0) + match[0].length, nextMatch?.index ?? adamReviewPasteText.length)
        .trim();
      const focusItem = adamFocusItems.find((item) => label.startsWith(item.label.toLowerCase()));
      if (focusItem && answer && answer !== focusItem.detail) {
        answers.set(focusItem.key, answer);
      }
    }

    if (answers.has("reviewed_visual_description")) {
      setDescription(answers.get("reviewed_visual_description") ?? "");
    }
    if (answers.has("retrieval_query_relevance")) {
      const retrievalAnswer = answers.get("retrieval_query_relevance") ?? "";
      setQuestionAnswers((current) => {
        const nextAnswers: Record<string, string> = { ...current, retrieval_query_relevance: retrievalAnswer };
        questions.forEach((question, index) => {
          const id = payloadString(question.id, `question_${index + 1}`);
          const questionText = payloadString(question.question).toLowerCase();
          if (id.includes("retrieval") || id.includes("query") || questionText.includes("retrieval") || questionText.includes("query")) {
            nextAnswers[id] = retrievalAnswer;
          }
        });
        return nextAnswers;
      });
    }
    if (answers.has("why_it_matters")) {
      setAdamContextNote(answers.get("why_it_matters") ?? "");
    }
    if (answers.has("invisible_context")) {
      setInvisibleContext(answers.get("invisible_context") ?? "");
    }
    if (answers.has("open_questions")) {
      setOpenQuestions(answers.get("open_questions") ?? "");
    }

    setAdamReviewPasteStatus(
      answers.size
        ? `Applied ${answers.size} Adam answer${answers.size === 1 ? "" : "s"} to review fields.`
        : "No changed Adam answers found; keep the numbered labels and replace the prompt text with answers."
    );
  }

  function applyPhotoOperatorFieldUpdates(updates: Decisions): string[] {
    const applied: string[] = [];
    const setIfPresent = (key: string, setter: (value: string) => void) => {
      if (Object.prototype.hasOwnProperty.call(updates, key)) {
        const value = updateText(updates[key]);
        if (value.trim()) {
          setter(value);
          applied.push(promptFromDecisionKey(key));
        }
      }
    };

    setIfPresent("visual_description_correction", setDescription);
    setIfPresent("accepted_visual_description", setDescription);
    setIfPresent("adam_context_note", setAdamContextNote);
    setIfPresent("invisible_context_note", setInvisibleContext);
    setIfPresent("open_questions", setOpenQuestions);
    setIfPresent("privacy_notes", setPrivacyNotes);
    setIfPresent("visible_people", setVisiblePeople);
    setIfPresent("people", setVisiblePeople);
    setIfPresent("absent_but_relevant_people", setAbsentPeople);
    setIfPresent("place", setPlace);
    setIfPresent("places", setPlace);
    setIfPresent("date_or_range", setDateRange);
    setIfPresent("date_confidence", setDateConfidence);
    setIfPresent("event", setEvent);
    setIfPresent("accepted_tags", setTags);
    setIfPresent("themes", setTags);
    setIfPresent("concrete_objects", setObjects);
    setIfPresent("rejected_system_inferences", setRejectedInferences);
    setIfPresent("privacy_level", setPrivacyLevel);
    setIfPresent("ready_for_downstream", setReadyForDownstream);
    setIfPresent("gallery_eligibility", setGalleryEligibility);

    if (Object.prototype.hasOwnProperty.call(updates, "memory_potential")) {
      const value = Number(updates.memory_potential);
      if (Number.isFinite(value)) {
        setMemoryPotential(value);
        applied.push(promptFromDecisionKey("memory_potential"));
      }
    }
    if (Object.prototype.hasOwnProperty.call(updates, "privacy_sensitivity")) {
      const value = Number(updates.privacy_sensitivity);
      if (Number.isFinite(value)) {
        setPrivacySensitivity(value);
        applied.push(promptFromDecisionKey("privacy_sensitivity"));
      }
    }
    if (updates.question_answers && typeof updates.question_answers === "object" && !Array.isArray(updates.question_answers)) {
      setQuestionAnswers((current) => ({
        ...current,
        ...Object.fromEntries(Object.entries(updates.question_answers as Record<string, unknown>).map(([key, value]) => [key, updateText(value)]))
      }));
      applied.push(promptFromDecisionKey("question_answers"));
    }
    return applied;
  }

  async function applyOperatorAnswer() {
    const answer = operatorAnswer.trim();
    if (!answer || !operatorSuggestion) {
      setOperatorApplyStatus("Write an answer first, then apply it.");
      return;
    }
    setOperatorApplyStatus("Asking operator model to parse this.");
    let suggestion = operatorSuggestion;
    try {
      suggestion = await getOperatorAssistantSuggestion(task.id, currentDecisions, answer);
      setOperatorSuggestion(suggestion);
      setOperatorStatus(suggestion.live_model_call_used ? "Model-assisted" : "Deterministic helper");
    } catch (caught) {
      setOperatorApplyStatus(caught instanceof Error ? `Assistant parse failed: ${caught.message}` : "Assistant parse failed");
    }
    const updates = fieldUpdatesFromSuggestion(suggestion);
    let appliedFields = applyPhotoOperatorFieldUpdates(updates);
    if (appliedFields.length === 0) {
      const target = suggestion.target_decision_key;
      if (target === "visual_description_correction" || target === "accepted_visual_description") {
        setDescription(answer);
      } else if (target === "adam_context_note") {
        setAdamContextNote(answer);
      } else if (target === "invisible_context_note") {
        setInvisibleContext(answer);
      } else if (target === "open_questions") {
        setOpenQuestions(answer);
      } else if (target === "privacy_notes" || target === "session_notes") {
        setPrivacyNotes(answer);
      } else if (target === "retrieval_query_relevance") {
        updateQuestionAnswer("retrieval_query_relevance", answer);
      } else {
        setInvisibleContext((current) => [current, answer].filter(Boolean).join("\n\n"));
      }
      appliedFields = [suggestion.target_label];
    }
    const submitRecommendation = suggestion.submit_recommendation;
    const appliedMessage = submitRecommendation?.requested
      ? submitRecommendation.ready
        ? "Assistant says this item is ready and is submitting it."
        : `Assistant says more review is needed before submit: ${submitRecommendation.missing_fields.map(promptFromDecisionKey).join(", ") || "missing fields"}`
      : `Applied to ${appliedFields.join(", ")}.`;
    setOperatorMessages((current) =>
      [
        ...current,
        { role: "assistant" as const, content: operatorSuggestion.next_question, detail: operatorSuggestion.target_label },
        { role: "user" as const, content: answer },
        { role: "system" as const, content: appliedMessage }
      ].slice(-8)
    );
    setOperatorApplyStatus(appliedMessage);
    setOperatorAnswer("");
    window.setTimeout(() => focusPhotoContextField(suggestion.target_decision_key), 100);
    if (submitRecommendation?.requested && submitRecommendation.ready && onOperatorSubmit) {
      await onOperatorSubmit({ ...currentDecisions, ...updates });
    }
  }

  function holdForLater() {
    setReadyForDownstream("later");
    setGalleryEligibility("none");
  }

  function keepSealed() {
    setPrivacyLevel("sealed");
    setReadyForDownstream("no");
    setGalleryEligibility("none");
  }

  return (
    <div className="form-grid source-question-grid photo-memory-grid">
      <ReviewAccordionPanel title="Photo memory review" detail="Visible facts, Adam memory, boundaries, and downstream handoff">
        <FormHint title="Photo memory review">
          Describe what is visible separately from what Adam knows. This creates searchable photo metadata, memory links, gallery eligibility, and embedding inputs without treating system guesses as source truth.
        </FormHint>
        <OperatorAssistantPanel
          suggestion={operatorSuggestion}
          status={operatorStatus}
          messages={operatorMessages}
          answer={operatorAnswer}
          applyStatus={operatorApplyStatus}
          onAnswerChange={setOperatorAnswer}
          onSend={() => void applyOperatorAnswer()}
          onShowField={operatorSuggestion ? () => focusPhotoContextField(operatorSuggestion.target_decision_key) : undefined}
        />
      {task.task_type === "photo_context" ? (
        <section className="photo-context-completion-payoff" aria-label="Photo context completion payoff">
          <header>
            <div>
              <span>Completion payoff</span>
              <strong>{submitOutcomePreview.label}</strong>
            </div>
            <em>{projectionStatus}</em>
          </header>
          <p>{submitOutcomePreview.detail}</p>
          <div className="photo-context-payoff-grid" aria-label="Completion payoff gates">
            <span data-tone={projectionVectorStatus === "eligible_reviewed_record" ? "good" : "warning"}>
              <em>Vector handoff</em>
              <strong>{labelFromKey(projectionVectorStatus || "backend_projection_pending")}</strong>
            </span>
            <span data-tone={adamFocusCompleteCount === adamFocusItems.length ? "good" : "warning"}>
              <em>Adam fields</em>
              <strong>
                {adamFocusCompleteCount} / {adamFocusItems.length} answered
              </strong>
            </span>
            <span data-tone={retrievalQuery ? "warning" : "neutral"}>
              <em>{retrievalQueryLabel}</em>
              <strong>{retrievalQuery || "No retrieval gap"}</strong>
            </span>
            <span data-tone={Object.keys(reviewSessionOrigin).length ? "warning" : "neutral"}>
              <em>Session item</em>
              <strong>{Object.keys(reviewSessionOrigin).length ? sessionPositionText : "Not in session"}</strong>
            </span>
            <span data-tone={projectionVectorStatus === "eligible_reviewed_record" ? "good" : "warning"}>
              <em>Session metric</em>
              <strong>{sessionMetricImpact}</strong>
            </span>
          </div>
          <div className="photo-context-payoff-actions">
            {firstIncompleteAdamFocus ? (
              <button type="button" onClick={() => focusPhotoContextField(firstIncompleteAdamFocus.key)}>
                Focus first missing: {firstIncompleteAdamFocus.label}
              </button>
            ) : (
              <span>Adam-required fields complete in the current draft.</span>
            )}
          </div>
          <div className="photo-context-missing-field-list" aria-label="Photo context missing field jump list">
            {adamFocusItems.map((item) => (
              <button key={item.key} type="button" data-status={item.status} onClick={() => focusPhotoContextField(item.key)}>
                <em>{item.status === "complete" ? "Complete" : "Needs Adam"}</em>
                <strong>{item.label}</strong>
                <small>{item.detail}</small>
                <small className="photo-context-unlock-note">Unlocks: {item.unlocks.join(", ")}</small>
                <small className="photo-context-metric-note">{adamFocusMetricText(item.status)}</small>
              </button>
            ))}
          </div>
          <small>
            Adam context gates downstream use.{" "}
            {retrievalIncompleteFields.length
              ? `Needs: ${retrievalIncompleteFields.slice(0, 3).join(", ")}`
              : "Required context is complete in the current projection."}
          </small>
        </section>
      ) : null}
      {hasMachineDraftDefaults ? (
        <details className="machine-draft-defaults" aria-label="Machine draft defaults">
          <summary>Model observations</summary>
          <header>
            <div>
              <span>Model observations</span>
              <strong>Visible-field scaffold only</strong>
            </div>
            <button type="button" onClick={restoreMachineDraftDefaults}>
              Restore visible defaults
            </button>
          </header>
          <p>
            These values come from a machine draft. They speed up visible description review but are not Adam memory until corrected, contextualized, and submitted.
          </p>
          <div>
            {machineDraftDefaults.description ? (
              <span>
                <em>Description</em>
                {machineDraftDefaults.description}
              </span>
            ) : null}
            {machineDraftDefaults.visiblePeople ? (
              <span>
                <em>People</em>
                {machineDraftDefaults.visiblePeople}
              </span>
            ) : null}
            {machineDraftDefaults.place ? (
              <span>
                <em>Place</em>
                {machineDraftDefaults.place}
              </span>
            ) : null}
          </div>
        </details>
      ) : null}
      <div className="photo-review-group-heading">Visible</div>
      <Field label="Is the machine/scaffold description accurate?">
        <Select
          value={visionAccuracy}
          onChange={setVisionAccuracy}
          options={["no_issues", "minor_issues", "major_issues", "not_applicable"]}
        />
      </Field>
      <Field
        label="Reviewed visual description"
        hint="What retrieval and gallery views should say about the visible image."
        focusKey="reviewed_visual_description"
      >
        <TextArea rows={5} value={description} onChange={setDescription} />
      </Field>
      <Field label="Who is visible or represented?">
        <input value={visiblePeople} onChange={(event) => setVisiblePeople(event.target.value)} />
      </Field>
      <Field label="Who matters but is not visible?">
        <input value={absentPeople} onChange={(event) => setAbsentPeople(event.target.value)} />
      </Field>
      <Field label="Where is this?">
        <input value={place} onChange={(event) => setPlace(event.target.value)} />
      </Field>
      <div className="field-pair">
        <Field label="When is this from or about?">
          <input value={dateRange} onChange={(event) => setDateRange(event.target.value)} />
        </Field>
        <Field label="Date confidence">
          <Select value={dateConfidence} onChange={setDateConfidence} options={["exact", "year", "decade", "unknown"]} />
        </Field>
      </div>
      <Field label="Event or moment">
        <input value={event} onChange={(event) => setEvent(event.target.value)} />
      </Field>
      <Field label="Tags and themes" hint="People, places, objects, and themes that should become searchable metadata.">
        <input value={tags} onChange={(event) => setTags(event.target.value)} />
      </Field>
      <Field label="Concrete visible objects">
        <input value={objects} onChange={(event) => setObjects(event.target.value)} />
      </Field>
      <Field label="What did the system get wrong?">
        <input value={rejectedInferences} onChange={(event) => setRejectedInferences(event.target.value)} />
      </Field>
      <Field
        label="Open questions for later"
        hint="Unresolved details that should stay marked as uncertain in retrieval records."
        focusKey="open_questions"
      >
        <input value={openQuestions} onChange={(event) => setOpenQuestions(event.target.value)} />
      </Field>
      <div className="photo-review-group-heading">Adam memory</div>
      <Field label="Memory this photo brings up" hint="Write the story, relationship, or association the image evokes." focusKey="why_it_matters">
        <TextArea rows={4} value={adamContextNote} onChange={setAdamContextNote} />
      </Field>
      <Field label="Invisible context" hint="What a viewer could not know from the pixels alone." focusKey="invisible_context">
        <TextArea rows={5} value={invisibleContext} onChange={setInvisibleContext} />
      </Field>
      {retrievalQuery ? (
        <Field
          label={isBacklogOnlyReviewSeed ? "Optional search connection" : "Search connection"}
          hint={
            isBacklogOnlyReviewSeed
              ? `This review was opened from the "${retrievalQuery}" search seed. Treat that as workflow provenance only; write the memory the photo sparks above, and leave this blank unless the connection is genuinely useful.`
              : `This search seed only explains why the photo was surfaced. If the photo genuinely connects, write how in Adam's words; otherwise say it is unrelated or uncertain.`
          }
          focusKey="retrieval_query_relevance"
        >
          <TextArea rows={3} value={retrievalQueryAnswer} onChange={(value) => updateQuestionAnswer("retrieval_query_relevance", value)} />
        </Field>
      ) : null}
      <section className="photo-memory-output-preview" aria-label="Downstream memory preview">
        <header>
          <div>
            <span>Downstream memory preview</span>
            <strong>{projection?.supported ? "Backend submit projection" : "Search text draft"}</strong>
          </div>
          <em>{projectionStatus}</em>
        </header>
        <section className="photo-context-submit-preview" aria-label="Photo context submit outcome preview">
          <span>On Submit</span>
          <strong>{submitOutcomePreview.label}</strong>
          <em>{submitOutcomePreview.detail}</em>
        </section>
        <div className="photo-memory-consequence-grid" aria-label="Submit consequence preview">
          {projectionConsequences.map((item) => (
            <span key={item.label} data-tone={item.tone}>
              <em>{item.label}</em>
              <strong>{item.value}</strong>
            </span>
          ))}
        </div>
        <section className="photo-memory-promotion-checklist" aria-label="Promotion checklist">
          <div>
            <span>Promotion checklist</span>
            <small>Fields that decide whether this photo becomes reviewed memory, held context, or boundary-excluded material.</small>
          </div>
          <div className="photo-promotion-progress" aria-label="Promotion progress">
            <span data-tone="good">
              <strong>{promotionCompleteCount}</strong>
              <em>complete</em>
            </span>
            <span data-tone={promotionHeldCount > 0 ? "warning" : "good"}>
              <strong>{promotionHeldCount}</strong>
              <em>held</em>
            </span>
          </div>
          <div className="photo-memory-consequence-grid">
            {promotionChecklist.map((item) => (
              <span key={item.key} data-tone={item.tone} title={item.reason}>
                <em>{item.label}</em>
                <strong>{labelFromKey(item.status || "unknown")}</strong>
              </span>
            ))}
          </div>
        </section>
        {Object.keys(reviewSessionOrigin).length > 0 ? (
          <section className="session-progress-impact-panel" aria-label="Session progress impact">
            <header>
              <div>
                <span>Session progress impact</span>
                <strong>Item {sessionPositionText}</strong>
              </div>
              <em>Held until submit</em>
            </header>
            <div className="photo-memory-consequence-grid">
              <span data-tone={sessionRequirementTotal > 0 && sessionRequirementCompleteCount === sessionRequirementTotal ? "good" : "warning"}>
                <em>Fields complete</em>
                <strong>
                  {sessionRequirementCompleteCount} / {sessionRequirementTotal || retrievalReviewFields.length || 0}
                </strong>
              </span>
              <span data-tone={sessionBlockers.length ? "warning" : "good"}>
                <em>Remaining blockers</em>
                <strong>{sessionBlockers.length ? sessionBlockers.map(labelFromKey).join(", ") : "None projected"}</strong>
              </span>
              <span data-tone={projectionVectorStatus === "eligible_reviewed_record" ? "good" : "warning"}>
                <em>Session completion metric</em>
                <strong>{sessionMetricImpact}</strong>
              </span>
            </div>
            <small>{recordString(reviewSessionOrigin, "completion_signal", "create_or_open_context_tasks_then_submit_adam_context_until_needs_context_count_decreases")}</small>
            <div className="session-safe-assist" aria-label="Session safe defaults assist">
              <button type="button" onClick={applySessionSafeDefaults}>
                Apply session-safe defaults
              </button>
              <small>Sets boundary/downstream controls only; Adam description, meaning, and optional search notes stay untouched.</small>
            </div>
          </section>
        ) : null}
        {retrievalQuery ? (
          <section className="retrieval-payoff-panel" aria-label="Task retrieval payoff preview">
            <div>
              <span>Retrieval payoff preview</span>
              <strong>Adam-authored context only</strong>
              <small>{recordString(retrievalReview, "review_policy", "retrieval_gap_no_claim_until_adam_context")}</small>
            </div>
            <div className="photo-memory-consequence-grid">
              <span data-tone="warning">
                <em>{retrievalQueryLabel}</em>
                <strong>{retrievalQuery}</strong>
              </span>
              <span data-tone={projectionVectorStatus === "eligible_reviewed_record" ? "good" : "warning"}>
                <em>After completion</em>
                <strong>reviewed_only_vector_handoff_record</strong>
              </span>
              <span data-tone={retrievalIncompleteFields.length ? "warning" : "good"}>
                <em>Still needed</em>
                <strong>{retrievalIncompleteFields.slice(0, 3).join(", ") || "Ready for submit projection"}</strong>
              </span>
            </div>
            <pre>{taskPayoffTemplate}</pre>
          </section>
        ) : null}
        <LinePreview
          text={projectionSearchText || "Add visual description or Adam context to create retrieval-ready memory text."}
          className="memory-output-line-preview"
        />
        {projection?.export_preview_yaml ? (
          <details className="photo-review-yaml">
            <summary>Submit payload preview</summary>
            <pre>{projection.export_preview_yaml}</pre>
          </details>
        ) : null}
        {projection?.blocked_reasons.length ? (
          <small>Held or blocked: {projection.blocked_reasons.map(labelFromKey).join(", ")}</small>
        ) : null}
        <small>
          Preview only. Submit stores the reviewed annotation and keeps boundary/truth status separate from model or archival claims.
        </small>
      </section>
      {reviewQuestions.length > 0 ? (
        <div className="dynamic-question-stack">
          <FormHint title="Questions for Adam">
            Answer one guided question at a time. Other model-suggested questions stay available under More questions.
          </FormHint>
          {reviewQuestions.slice(0, 1).map((question, index) => {
            const id = payloadString(question.id, `question_${index + 1}`);
            return (
              <Field
                key={id}
                label={payloadString(question.question, `Question ${index + 1}`)}
                hint={payloadString(question.reason)}
              >
                <TextArea rows={3} value={questionAnswers[id] ?? ""} onChange={(value) => updateQuestionAnswer(id, value)} />
              </Field>
            );
          })}
          {reviewQuestions.length > 1 ? (
            <details className="photo-review-details">
              <summary>More questions</summary>
              {reviewQuestions.slice(1).map((question, index) => {
                const id = payloadString(question.id, `question_${index + 2}`);
                return (
                  <Field
                    key={id}
                    label={payloadString(question.question, `Question ${index + 2}`)}
                    hint={payloadString(question.reason)}
                  >
                    <TextArea rows={3} value={questionAnswers[id] ?? ""} onChange={(value) => updateQuestionAnswer(id, value)} />
                  </Field>
                );
              })}
            </details>
          ) : null}
        </div>
      ) : null}
      <section className="adam-required-focus-drawer" aria-label="Required Adam fields focus">
        <header>
          <div>
            <span>Required Adam fields</span>
            <strong>
              {adamFocusCompleteCount} / {adamFocusItems.length} answered
            </strong>
          </div>
          <em>No generated memory text here</em>
        </header>
        <div>
          {adamFocusItems.map((item) => (
            <span key={item.key} data-tone={item.status === "complete" ? "good" : "warning"}>
              <em>{item.status === "complete" ? "Complete" : "Needs Adam"}</em>
              <strong>{item.label}</strong>
              <small>{item.detail}</small>
              <small className="photo-context-unlock-note">Unlocks: {item.unlocks.join(", ")}</small>
              <small className="photo-context-metric-note">{adamFocusMetricText(item.status)}</small>
            </span>
          ))}
        </div>
        <section className="ready-submit-checklist" aria-label="Current photo ready-to-submit checklist">
          <header>
            <span>Ready-to-submit checklist</span>
            <strong>{missingAdamFocusItems.length ? `${missingAdamFocusItems.length} Adam field(s) still blocking` : "Adam fields ready"}</strong>
          </header>
          <ol>
            {adamFocusItems.map((item) => (
              <li key={`submit-${item.key}`} data-status={item.status}>
                <span>{item.status === "complete" ? "Complete" : "Blocks submit"}</span>
                <strong>{item.label}</strong>
                <em>{item.unlocks.join(", ")}</em>
              </li>
            ))}
          </ol>
          <small>
            Vector handoff: {labelFromKey(projectionVectorStatus || "backend_projection_pending")} / Submit:{" "}
            {submitOutcomePreview.label}
          </small>
        </section>
        <div className="copy-review-prompt" aria-label="Copy Adam review prompt">
          <button type="button" onClick={() => void copyAdamReviewPrompt()}>
            Copy review prompt
          </button>
          <span>{copyReviewPromptStatus || "Plain-language prompt, no generated memory claims"}</span>
          <details>
            <summary>Prompt preview</summary>
            <pre>{adamReviewPromptText}</pre>
          </details>
        </div>
        <div className="paste-review-answers" aria-label="Adam answer paste parser">
          <Field label="Paste Adam answers" hint="Uses the numbered labels from the copied prompt. It only fills Adam-authored review fields.">
            <TextArea rows={5} value={adamReviewPasteText} onChange={setAdamReviewPasteText} />
          </Field>
          <div>
            <button type="button" onClick={startAdamAnswerTemplate}>
              Start answer template
            </button>
            <button type="button" onClick={applyAdamReviewAnswers}>
              Apply Adam answers
            </button>
            <small>{adamReviewPasteStatus}</small>
          </div>
        </div>
      </section>
      <div className="field-pair">
        <Rating label="Memory potential" value={memoryPotential} onChange={setMemoryPotential} />
        <Rating label="Privacy sensitivity" value={privacySensitivity} onChange={setPrivacySensitivity} />
      </div>
      <div className="photo-review-group-heading">Boundary</div>
      <section className="reviewed-memory-readiness-controls" aria-label="Reviewed memory readiness controls">
        <header>
          <div>
            <span>Reviewed memory readiness</span>
            <strong>Boundary and downstream shortcuts</strong>
          </div>
        </header>
        <p>
          These shortcuts only adjust boundary, gallery, and downstream choices. Adam context or answers are still required before this becomes reviewed memory truth.
        </p>
        <div>
          <button type="button" onClick={setRetrievalReadyDefaults}>
            Set retrieval-ready defaults
          </button>
          <button type="button" onClick={holdForLater}>
            Hold for later
          </button>
          <button type="button" onClick={keepSealed}>
            Keep sealed
          </button>
        </div>
      </section>
      <FormHint title="Privacy and downstream use">
        Search, chat retrieval, gallery use, and generated context all depend on these boundary choices.
      </FormHint>
      <div className="field-pair">
        <Field label="Privacy level">
          <Select
            value={privacyLevel}
            onChange={setPrivacyLevel}
            options={["public_safe", "family_private", "private_sensitive", "sensitive_living_people", "sealed"]}
          />
        </Field>
        <Field label="Ready downstream">
          <Select value={readyForDownstream} onChange={setReadyForDownstream} options={["yes", "later", "no"]} />
        </Field>
      </div>
      <Field label="Gallery eligibility">
        <Select value={galleryEligibility} onChange={setGalleryEligibility} options={["none", "family_private", "public_candidate"]} />
      </Field>
      <Field label="Privacy notes">
        <TextArea rows={4} value={privacyNotes} onChange={setPrivacyNotes} />
      </Field>
      <FormHint title="OCR or handwriting">
        If the image contains text, keep the transcription as its own source artifact with a truth label.
      </FormHint>
      <div className="field-pair">
        <Field label="OCR status">
          <Select
            value={ocrReviewStatus}
            onChange={setOcrReviewStatus}
            options={["not_present", "machine_draft_needs_review", "accepted_as_transcription", "adam_corrected"]}
          />
        </Field>
        <Field label="OCR truth">
          <Select
            value={ocrTruthStatus}
            onChange={setOcrTruthStatus}
            options={["system_inference", "archival_source", "adam_expert_reconstruction", "adam_inference"]}
          />
        </Field>
      </div>
      {ocrReviewStatus !== "not_present" ? (
        <Field label="Corrected OCR or handwriting text">
          <TextArea rows={6} value={correctedOcrText} onChange={setCorrectedOcrText} />
        </Field>
      ) : null}
      </ReviewAccordionPanel>
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
      <ReviewAccordionPanel title="Photo context" detail="People, place, time, and invisible context">
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
      </ReviewAccordionPanel>
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
      truth_status: reviewedPhotoTruthStatus({
        taskType: task.task_type,
        description,
        adamContextNote,
        questionAnswers,
        visionAccuracy
      }),
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
    task.task_type,
    task.input_payload.asset_type,
    visionAccuracy
  ]);

  function updateQuestionAnswer(questionId: string, value: string) {
    setQuestionAnswers((current) => ({ ...current, [questionId]: value }));
  }

  return (
    <div className="form-grid source-question-grid">
      <ReviewAccordionPanel title="Vision draft" detail="Machine scaffold review and Adam corrections">
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
      </ReviewAccordionPanel>
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
  const [privacyLevel, setPrivacyLevel] = useState(decisionString(initialDecisions, "privacy_level", "public_safe"));
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
      <div className="source-review-group-heading">What is this source?</div>
      <Field label="What should we call this segment?" hint="A short human-readable title for item cards and retrieval.">
        <input value={title} onChange={(event) => setTitle(event.target.value)} />
      </Field>
      <Field label="What kind of document is it?" hint="Used for filtering and future retrieval.">
        <Select
          value={sourceGenre}
          onChange={setSourceGenre}
          options={[
            "document",
            "training_pair_corpus",
            "prompt_pair_collection",
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
      <Field label="Why does Adam think it matters?" hint="This is search/context detail, not training target text by itself.">
        <TextArea rows={5} value={adamContextNote} onChange={setAdamContextNote} />
      </Field>
      <div className="source-review-group-heading">Can it be used?</div>
      <Field label="Can this source move forward?" hint="Yes creates the next review step before prompt-pair work.">
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
        <Toggle label="Living-person sensitive material" checked={livingPersonSensitive} onChange={setLivingPersonSensitive} />
        <Toggle label="Redaction required" checked={redactionRequired} onChange={setRedactionRequired} />
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
    decisionString(initialDecisions, "privacy_level", payloadString(task.input_payload.privacy_level, "public_safe"))
  );
  const [privacyNotes, setPrivacyNotes] = useState(
    decisionString(initialDecisions, "privacy_notes", decisionString(initialDecisions, "boundary_rationale"))
  );
  const [segmentationNotes, setSegmentationNotes] = useState(
    decisionString(initialDecisions, "segmentation_notes")
  );
  const [chunkQualityProfile, setChunkQualityProfile] = useState(
    decisionString(
      initialDecisions,
      "chunk_quality_profile",
      payloadString(task.input_payload.chunk_quality_profile, "uniform_reviewed")
    )
  );
  const [readyReferenceRange, setReadyReferenceRange] = useState(
    decisionString(
      initialDecisions,
      "ready_reference_chunk_range",
      payloadString(task.input_payload.ready_reference_chunk_range)
    )
  );
  const [needsAdamEditRange, setNeedsAdamEditRange] = useState(
    decisionString(
      initialDecisions,
      "needs_adam_edit_chunk_range",
      payloadString(task.input_payload.needs_adam_edit_chunk_range)
    )
  );
  const [readyReferenceTruthStatus, setReadyReferenceTruthStatus] = useState(
    decisionString(
      initialDecisions,
      "ready_reference_truth_status",
      payloadString(task.input_payload.ready_reference_truth_status, payloadString(task.input_payload.truth_status, "interpretive_synthesis"))
    )
  );
  const [needsAdamEditTruthStatus, setNeedsAdamEditTruthStatus] = useState(
    decisionString(
      initialDecisions,
      "needs_adam_edit_truth_status",
      payloadString(task.input_payload.needs_adam_edit_truth_status, "model_generated")
    )
  );
  const [chunkQualityNotes, setChunkQualityNotes] = useState(
    decisionString(
      initialDecisions,
      "chunk_quality_notes",
      payloadString(task.input_payload.chunk_quality_notes)
    )
  );
  const [redactionInstructions, setRedactionInstructions] = useState(
    decisionString(initialDecisions, "redaction_instructions")
  );
  const [redactionRequired, setRedactionRequired] = useState(decisionBoolean(initialDecisions, "redaction_required", false));
  const [useForSft, setUseForSft] = useState(decisionBoolean(initialDecisions, "usable_for_sft", false));
  const [useForDpo, setUseForDpo] = useState(decisionBoolean(initialDecisions, "usable_for_dpo", false));

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
    const pairingGate = needsAdamEditRange.trim()
      ? readyReferenceRange.trim()
        ? "route_ready_chunks_only_hold_needs_edit"
        : "requires_adam_edit_before_pairing"
      : "ready_for_pairing";
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
      chunk_quality_profile: chunkQualityProfile,
      ready_reference_chunk_range: readyReferenceRange,
      pairing_ready_chunk_range: readyReferenceRange,
      needs_adam_edit_chunk_range: needsAdamEditRange,
      ready_reference_truth_status: readyReferenceTruthStatus,
      needs_adam_edit_truth_status: needsAdamEditTruthStatus,
      chunk_quality_notes: chunkQualityNotes,
      pairing_gate: pairingGate,
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
      usable_for_sft: canUseAsContext && useForSft ? "yes" : "no",
      usable_for_dpo: canUseAsContext && useForDpo ? "yes" : "no",
      ready_for_prompt_pair_factory: shouldGeneratePromptPair ? "yes" : "no"
    });
  }, [
    boundaryStatus,
    chunkQualityNotes,
    chunkQualityProfile,
    needsAdamEditRange,
    needsAdamEditTruthStatus,
    onChange,
    privacyClearance,
    privacyLevel,
    privacyNotes,
    promptPairDecision,
    readyReferenceRange,
    readyReferenceTruthStatus,
    redactionInstructions,
    redactionRequired,
    segmentationNotes,
    sourceUseModes,
    useForDpo,
    useForSft
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
      <Field label="Quality split for Pair Factory" hint="Use this when a source contains both reference-ready and generated/edit-needed chunks.">
        <Select
          value={chunkQualityProfile}
          onChange={setChunkQualityProfile}
          options={[
            "uniform_reviewed",
            "mixed_reference_and_synthetic_needs_edit",
            "all_needs_adam_edit",
            "do_not_pair_until_reviewed"
          ]}
        />
      </Field>
      <div className="field-pair">
        <Field label="Reference-ready chunk range" hint="Example: 1-206. These can be routed into Pair Factory as usable reference material.">
          <input value={readyReferenceRange} onChange={(event) => setReadyReferenceRange(event.target.value)} />
        </Field>
        <Field label="Needs Adam edit range" hint="Example: 207-391. These stay visible but are gated before pairing/export.">
          <input value={needsAdamEditRange} onChange={(event) => setNeedsAdamEditRange(event.target.value)} />
        </Field>
      </div>
      <div className="field-pair">
        <Field label="Ready-range truth status">
          <Select
            value={readyReferenceTruthStatus}
            onChange={setReadyReferenceTruthStatus}
            options={["interpretive_synthesis", "adam_expert_reconstruction", "archival_source", "spoken_source", "adam_memory"]}
          />
        </Field>
        <Field label="Needs-edit truth status">
          <Select
            value={needsAdamEditTruthStatus}
            onChange={setNeedsAdamEditTruthStatus}
            options={["model_generated", "system_inference", "interpretive_synthesis", "adam_expert_reconstruction"]}
          />
        </Field>
      </div>
      <Field label="Quality split notes" hint="This travels into the prompt-pair candidate and gold-edit task.">
        <TextArea rows={3} value={chunkQualityNotes} onChange={setChunkQualityNotes} />
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
        <Toggle label="usable_for_sft" checked={useForSft} onChange={setUseForSft} />
        <Toggle label="usable_for_dpo" checked={useForDpo} onChange={setUseForDpo} />
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
  const [conversationFamily, setConversationFamily] = useState(
    decisionString(initialDecisions, "conversation_family", payloadString(payload.conversation_family, "adam_prompted_memory"))
  );
  const [systemPrompt, setSystemPrompt] = useState(
    decisionString(initialDecisions, "system_prompt", payloadString(payload.system_prompt, "You are Charles Rotmil."))
  );
  const [targetResponseShape, setTargetResponseShape] = useState(
    decisionString(initialDecisions, "target_response_shape", "short_voice_response")
  );
  const [promptText, setPromptText] = useState(decisionString(initialDecisions, "prompt_text"));
  const [modelDraft, setModelDraft] = useState(decisionString(initialDecisions, "model_draft"));
  const payloadNoLiveModelCall =
    typeof payload.no_live_model_call === "boolean"
      ? payload.no_live_model_call
      : typeof payload.no_live_model_call === "string"
        ? payload.no_live_model_call !== "false"
        : true;
  const [noLiveModelCall, setNoLiveModelCall] = useState(
    decisionBoolean(initialDecisions, "no_live_model_call", payloadNoLiveModelCall)
  );
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
      conversation_family: conversationFamily,
      system_prompt: systemPrompt,
      target_response_shape: targetResponseShape,
      prompt_text: promptText,
      model_draft: modelDraft,
      boundary_clearance_needed: boundaryClearance,
      factory_notes: factoryNotes,
      source_chunks_to_use: sourceChunksToUse,
      no_live_model_call: noLiveModelCall
    });
  }, [boundaryClearance, conversationFamily, factoryNotes, initialDecisions.selected_chunk_ids, modelDraft, noLiveModelCall, onChange, payload.no_live_model_call, payload.selected_chunk_ids, promptIntent, promptText, systemPrompt, targetResponseShape, truthMode, voiceMode]);

  return (
    <div className="form-grid">
      <FormHint title="Prompt Pair Factory">
        Configure what kind of prompt pair this source should become. This stage creates the review item where Adam edits, compares, and approves export artifacts.
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
      <Field label="Conversation family">
        <Select
          value={conversationFamily}
          onChange={setConversationFamily}
          options={[
            "verbatim_email_reply",
            "adam_prompted_memory",
            "source_based_story_recall",
            "mundane_text_message",
            "ps_digression",
            "nb_digression",
            "long_literary_source_excerpt",
            "multi_turn_thread"
          ]}
        />
      </Field>
      <Field label="Exported system message" hint="Keep this minimal. Provenance, boundaries, and source rules stay backstage.">
        <TextArea value={systemPrompt} onChange={setSystemPrompt} rows={2} />
      </Field>
      <Field label="What shape should the response have?">
        <Select
          value={targetResponseShape}
          onChange={setTargetResponseShape}
          options={["short_voice_response", "short_email_reply", "longer_letter", "memoir_paragraph", "archive_answer", "eval_prompt"]}
        />
      </Field>
      <Field
        label="User message"
        hint="Optional. Leave blank and the backend will create a natural user prompt from the selected source."
      >
        <TextArea value={promptText} onChange={setPromptText} rows={5} />
      </Field>
      <Field label="Draft rejected/pre-edit side" hint="Optional. Leave blank to create a model draft when live calls are enabled, otherwise a backstage scaffold.">
        <TextArea value={modelDraft} onChange={setModelDraft} rows={5} />
      </Field>
      <Toggle label="no_live_model_call" checked={noLiveModelCall} onChange={setNoLiveModelCall} />
      <Field label="What privacy check is needed before export?">
        <Select
          value={boundaryClearance}
          onChange={setBoundaryClearance}
          options={["review_before_export", "source_boundary_clear", "needs_redaction", "do_not_export"]}
        />
      </Field>
      <Field label="Factory notes" hint="Why this source should produce prompt pairs, or what Adam should watch for in review.">
        <TextArea value={factoryNotes} onChange={setFactoryNotes} rows={4} />
      </Field>
    </div>
  );
}

function GoldVoiceEditForm({
  task,
  initialDecisions,
  assets,
  photoPreviewAccessToken,
  onChange,
  onOperatorSubmit
}: {
  task: Task;
  assets: Asset[];
  photoPreviewAccessToken?: string;
  initialDecisions: Decisions;
  onChange: (value: Decisions) => void;
  onOperatorSubmit?: (decisionsOverride?: Decisions) => Promise<void>;
}) {
  const payload = task.input_payload;
  const initialRatings =
    initialDecisions.ratings && typeof initialDecisions.ratings === "object"
      ? (initialDecisions.ratings as Record<string, unknown>)
      : {};
  const defaultRatings = { ...((payload.ratings ?? {}) as Record<string, unknown>), ...initialRatings };
  const payloadArtifactMode = validArtifactMode(payloadString(payload.artifact_mode, "sft"));
  const initialArtifactModeSource = decisionString(initialDecisions, "artifact_mode_source");
  const initialMode =
    initialArtifactModeSource === "manual" || initialArtifactModeSource === "assistant"
      ? validArtifactMode(decisionString(initialDecisions, "artifact_mode", payloadArtifactMode))
      : payloadArtifactMode;
  const initialSystemPrompt = decisionString(
    initialDecisions,
    "system_prompt",
    payloadString(payload.system_prompt, defaultSystemPromptForMode(initialMode))
  );
  const initialSynthetic =
    typeof initialDecisions.synthetic === "boolean"
      ? initialDecisions.synthetic
      : typeof payload.synthetic === "boolean"
        ? payload.synthetic
        : true;
  const initialChosen =
    decisionString(initialDecisions, "chosen", payloadString(payload.chosen)) ||
    decisionString(initialDecisions, "adam_gold_edit", payloadString(payload.adam_gold_edit));
  const initialContent =
    decisionString(initialDecisions, "content", payloadString(payload.content)) ||
    decisionString(initialDecisions, "adam_gold_edit", payloadString(payload.adam_gold_edit)) ||
    initialChosen ||
    payloadString(payload.model_draft);
  const initialRejected =
    decisionString(initialDecisions, "rejected", payloadString(payload.rejected)) ||
    decisionString(initialDecisions, "model_draft", payloadString(payload.model_draft, ""));
  const initialEditorModeSource = decisionString(initialDecisions, "editor_mode_source");
  const initialEditorMode: PromptPairEditorMode =
    initialEditorModeSource === "manual" || initialEditorModeSource === "assistant"
      ? validEditorMode(decisionString(initialDecisions, "editor_mode", "plain"))
      : "plain";
  const [prompt, setPrompt] = useState(decisionString(initialDecisions, "prompt", payloadString(payload.prompt, "")));
  const [artifactMode, setArtifactMode] = useState<"sft" | "dpo">(initialMode);
  const [artifactModeSource, setArtifactModeSource] = useState(initialArtifactModeSource || "payload");
  const [editorMode, setEditorMode] = useState<PromptPairEditorMode>(initialEditorMode);
  const [editorModeSource, setEditorModeSource] = useState(initialEditorModeSource || "default_plain");
  const [voiceMode, setVoiceMode] = useState(decisionString(initialDecisions, "voice_mode", payloadString(payload.voice_mode, "father_to_adam")));
  const [voiceModes, setVoiceModes] = useState<VoiceMode[]>([]);
  const [addingVoiceMode, setAddingVoiceMode] = useState(false);
  const [newVoiceModeLabel, setNewVoiceModeLabel] = useState("");
  const [synthetic, setSynthetic] = useState<"yes" | "no">(initialSynthetic ? "yes" : "no");
  const [groundingAssetId, setGroundingAssetId] = useState(
    decisionString(initialDecisions, "grounding_asset_id", payloadString(payload.grounding_asset_id, payloadString(payload.asset_id)))
  );
  const [context, setContext] = useState(decisionString(initialDecisions, "context", payloadString(payload.context)));
  const [content, setContent] = useState(initialContent);
  const [chosen, setChosen] = useState(initialChosen || initialContent);
  const [rejected, setRejected] = useState(initialRejected);
  const [systemPrompt, setSystemPrompt] = useState(initialSystemPrompt);
  const [serverExportGate, setServerExportGate] = useState<PromptPairPreflightExportGate | null>(null);
  const [serverExportGateStatus, setServerExportGateStatus] = useState<"pending" | "ready" | "error">("pending");
  const [dpoRepairProjection, setDpoRepairProjection] = useState<DpoRejectedReasonRepairProjection | null>(null);
  const [dpoRepairProjectionStatus, setDpoRepairProjectionStatus] = useState<"idle" | "pending" | "ready" | "error">("idle");
  const [operatorSuggestion, setOperatorSuggestion] = useState<OperatorAssistantSuggestion | null>(null);
  const [operatorStatus, setOperatorStatus] = useState("Assistant loading");
  const [operatorAnswer, setOperatorAnswer] = useState("");
  const [operatorApplyStatus, setOperatorApplyStatus] = useState("");
  const [operatorMessages, setOperatorMessages] = useState<OperatorChatMessage[]>(() => operatorMessagesFromDecisions(initialDecisions));
  const [operatorCandidateTriageIntent, setOperatorCandidateTriageIntent] = useState(
    decisionString(initialDecisions, "operator_candidate_triage_intent")
  );
  const [sftYamlDraft, setSftYamlDraft] = useState(() =>
    buildPairYaml({
      artifactMode: "sft",
      systemPrompt: initialSystemPrompt,
      prompt: decisionString(initialDecisions, "prompt", payloadString(payload.prompt, "")),
      content: initialContent,
      chosen: initialChosen || initialContent,
      rejected: ""
    })
  );
  const [dpoYamlDraft, setDpoYamlDraft] = useState(() =>
    buildPairYaml({
      artifactMode: "dpo",
      systemPrompt: initialSystemPrompt,
      prompt: decisionString(initialDecisions, "prompt", payloadString(payload.prompt, "")),
      content: initialContent,
      chosen: initialChosen || initialContent,
      rejected: initialRejected
    })
  );
  const yamlEditSourceRef = useRef(false);
  const initialFailureModes = parseList(decisionListText(initialDecisions, "failure_modes", payloadArray(payload.failure_modes).join(", ")));
  const [responseRubric, setResponseRubric] = useState<ResponseRubricState>(() =>
    responseRubricFromDecisions(initialDecisions, defaultRatings, initialFailureModes)
  );
  const payloadTruthStatus = payloadString(payload.truth_status);
  const preservesSourceTruth =
    Boolean(payload.source_photo_profile_id) || Boolean(payload.candidate_requires_adam_gold_edit);
  const effectiveTruthStatus =
    preservesSourceTruth && payloadTruthStatus
      ? payloadTruthStatus
      : synthetic === "yes"
        ? "adam_expert_reconstruction"
        : payloadString(payload.truth_status, "archival_source");
  const boundarySnapshot = useMemo(
    () =>
      payload.boundary_snapshot && typeof payload.boundary_snapshot === "object"
        ? (payload.boundary_snapshot as Record<string, unknown>)
        : {},
    [payload.boundary_snapshot]
  );
  const sourcePhotoId = payloadString(payload.source_photo_id);
  const boundarySftBlocked = Boolean(sourcePhotoId) && boundarySnapshot.usable_for_sft === false;
  const sourceExcerpt = payloadString(payload.source_excerpt);
  const sourceExcerptTitle = payloadString(payload.source_title, "Original reviewed chunk");
  const sourceEvidenceRefs = payloadRecords(payload.source_evidence_refs);
  const rankedEvidencePacket = payloadRecord(payload.ranked_evidence_packet);
  const rankedEvidenceRecords = payloadRecords(rankedEvidencePacket.records);
  const pairGenerationMetadata = payloadRecord(payload.pair_generation_metadata);
  const evidenceGate = payloadRecord(pairGenerationMetadata.evidence_gate);
  const sourceEvidenceStatus = payloadString(payload.source_evidence_status, recordString(evidenceGate, "status", "unknown"));
  const sourceExcerptHash = payloadString(payload.source_excerpt_sha256);
  const generationStrategy = recordString(pairGenerationMetadata, "strategy", payloadString(payload.photo_pair_generation_strategy, "unknown"));
  const generationEvidenceVisible =
    sourceEvidenceRefs.length > 0 || rankedEvidenceRecords.length > 0 || sourceExcerptHash || Object.keys(pairGenerationMetadata).length > 0;
  const responseARubric = responseRubric.response_a;
  const responseBRubric = responseRubric.response_b;
  const rubricRatings = useMemo(() => deriveRubricRatings(responseBRubric), [responseBRubric]);
  const failureModes = useMemo(() => (artifactMode === "dpo" ? deriveFailureModes(responseARubric) : []), [artifactMode, responseARubric]);
  const preferredFailureModes = useMemo(() => deriveFailureModes(responseBRubric), [responseBRubric]);
  const rubricSummary = useMemo(
    () => deriveResponseRubricSummary(responseARubric, responseBRubric),
    [responseARubric, responseBRubric]
  );
  const privacyExportBlocked = rubricSummary.preferred_export_blocked;
  const effectiveExportFlags = useMemo(
    () =>
      privacyExportBlocked || boundarySftBlocked
        ? { sft: false, dpo: false, eval: false, anti_pattern: false, style_rule: false }
        : artifactMode === "dpo"
          ? { sft: false, dpo: true, eval: false, anti_pattern: false, style_rule: false }
          : { sft: true, dpo: false, eval: false, anti_pattern: false, style_rule: false },
    [artifactMode, boundarySftBlocked, privacyExportBlocked]
  );
  const exportPreviewYaml = useMemo(
    () =>
      buildPairYaml({
        artifactMode,
        systemPrompt,
        prompt,
        content,
        chosen,
        rejected
      }),
    [artifactMode, chosen, content, prompt, rejected, systemPrompt]
  );
  const preflightPayload = useMemo<Record<string, unknown>>(
    () => ({
      artifact_mode: artifactMode,
      system_prompt: systemPrompt,
      prompt,
      voice_mode: voiceMode,
      synthetic: synthetic === "yes",
      truth_status: effectiveTruthStatus,
      grounding_asset_id: groundingAssetId,
      context,
      content,
      chosen: artifactMode === "dpo" ? chosen : content,
      rejected: artifactMode === "dpo" ? rejected : "",
      rubric_summary: rubricSummary,
      failure_modes: failureModes,
      preferred_failure_modes: preferredFailureModes,
      source_photo_id: sourcePhotoId,
      boundary_snapshot: boundarySnapshot
    }),
    [
      artifactMode,
      boundarySnapshot,
      chosen,
      content,
      context,
      effectiveTruthStatus,
      failureModes,
      groundingAssetId,
      preferredFailureModes,
      prompt,
      rejected,
      rubricSummary,
      sourcePhotoId,
      synthetic,
      systemPrompt,
      voiceMode
    ]
  );
  const operatorAssistantDecisions = useMemo<Record<string, unknown>>(
    () => ({
      ...preflightPayload,
      editor_mode: editorMode,
      response_rubric: artifactMode === "dpo" ? responseRubric : { response_b: responseBRubric },
      export_flags: effectiveExportFlags,
      candidate_requires_adam_gold_edit: payload.candidate_requires_adam_gold_edit,
      photo_pair_variant_key: payload.photo_pair_variant_key,
      photo_pair_variant_label: payload.photo_pair_variant_label
    }),
    [
      artifactMode,
      editorMode,
      effectiveExportFlags,
      payload.candidate_requires_adam_gold_edit,
      payload.photo_pair_variant_key,
      payload.photo_pair_variant_label,
      preflightPayload,
      responseBRubric,
      responseRubric
    ]
  );
  const promptPairExportReady = serverExportGate?.export_ready ?? false;
  const promptPairGateBlockers =
    serverExportGate?.blockers ??
    (serverExportGateStatus === "error" ? ["server_preflight_unavailable"] : ["server_preflight_pending"]);
  const promptPairGateOutcome =
    serverExportGate?.submit_outcome ??
    (serverExportGateStatus === "error" ? "Backend preflight unavailable" : "Checking backend preflight");
  const promptPairDatasetOutcome =
    serverExportGate?.dataset_outcome ??
    (serverExportGateStatus === "error" ? "Cannot confirm export status" : "Awaiting server gate");
  const promptPairHeldExplanation = promptPairExportReady
    ? ""
    : promptPairGateBlockers.length > 0
      ? `${promptPairGateBlockers.map(labelFromKey).join(", ")} keeps this item in candidate dry-run until resolved.`
      : "Backend preflight has not returned a blocker yet.";
  const candidateWorkdownBlockers = promptPairGateBlockers.map((blocker) => ({
    key: blocker,
    label: labelFromKey(blocker),
    action: promptPairBlockerAction(blocker)
  }));
  const sourceBoundaryBlockedUses = useMemo(() => {
    const blockedUses: string[] = [];
    if (sourcePhotoId && boundarySnapshot.usable_for_sft === false) {
      blockedUses.push("sft");
    }
    if (sourcePhotoId && boundarySnapshot.usable_for_dpo === false) {
      blockedUses.push("dpo");
    }
    if (boundarySnapshot.redaction_required === true) {
      blockedUses.push("redaction_required");
    }
    const privacyLevel = String(boundarySnapshot.privacy_level ?? "");
    if (["sealed", "private_sensitive", "sensitive_living_people"].includes(privacyLevel)) {
      blockedUses.push(`privacy_level=${privacyLevel}`);
    }
    return uniqueValues(blockedUses);
  }, [boundarySnapshot, sourcePhotoId]);
  const sourceBoundaryFocusVisible =
    promptPairGateBlockers.includes("source_boundary_blocks_training") &&
    (sourcePhotoId || Object.keys(boundarySnapshot).length > 0);
  const needsDpoRejectedReason =
    artifactMode === "dpo" && (failureModes.length === 0 || promptPairGateBlockers.includes("dpo_rejected_reason_empty"));
  const currentPromptPairBlocker = promptPairExportReady ? "" : promptPairGateBlockers[0] ?? "";
  const rejectedReasonNote = responseARubric.voice_authenticity?.notes ?? "";
  const dpoRepairInputPatch =
    dpoRepairProjection?.input_patch && typeof dpoRepairProjection.input_patch === "object"
      ? dpoRepairProjection.input_patch
      : {};
  const dpoRepairInputPatchModes =
    Array.isArray(dpoRepairInputPatch.failure_modes)
      ? dpoRepairInputPatch.failure_modes.map(String).filter(Boolean)
      : [];
  const dpoRepairSuggestedFailureModes =
    dpoRepairInputPatchModes.length > 0 ? dpoRepairInputPatchModes : dpoRepairProjection?.after?.failure_modes ?? [];
  const dpoRepairSuggestedFailureMode = dpoRepairSuggestedFailureModes[0] ?? "";
  const displayExportPreviewYaml = serverExportGate?.yaml_preview || exportPreviewYaml;
  const submitReceiptPreview =
    serverExportGateStatus === "pending"
      ? "Submit preview pending backend preflight"
      : promptPairExportReady
        ? `Creates approved ${artifactMode.toUpperCase()} artifact`
        : `Creates ${artifactMode.toUpperCase()} review candidate`;
  const submitReceiptPreviewDetail =
    serverExportGateStatus === "pending"
      ? "Waiting for backend preflight before predicting the receipt."
      : promptPairExportReady
        ? "Approved artifacts are eligible for final JSONL export after Submit."
        : "Candidate artifacts keep their blockers and stay out of approved training export.";
  const exportPreviewIntegrity = useMemo(() => {
    if (serverExportGateStatus === "pending") {
      return { status: "pending", label: "Checking backend sync" };
    }
    if (serverExportGateStatus === "error" || !serverExportGate) {
      return { status: "warning", label: "Backend sync unavailable" };
    }
    return normalizePreviewYaml(serverExportGate.yaml_preview) === normalizePreviewYaml(exportPreviewYaml)
      ? { status: "synced", label: "Backend synchronized" }
      : { status: "warning", label: "Backend preview differs" };
  }, [exportPreviewYaml, serverExportGate, serverExportGateStatus]);

  useEffect(() => {
    if (editorMode === "yaml" && yamlEditSourceRef.current) {
      yamlEditSourceRef.current = false;
      return;
    }
    if (artifactMode === "sft") {
      setSftYamlDraft(displayExportPreviewYaml);
    } else {
      setDpoYamlDraft(displayExportPreviewYaml);
    }
  }, [artifactMode, displayExportPreviewYaml, editorMode]);

  useEffect(() => {
    let cancelled = false;
    setServerExportGate(null);
    setServerExportGateStatus("pending");
    const timeout = window.setTimeout(() => {
      preflightPromptPairExportGate(preflightPayload)
        .then((gate) => {
          if (cancelled) {
            return;
          }
          setServerExportGate(gate);
          setServerExportGateStatus("ready");
        })
        .catch(() => {
          if (cancelled) {
            return;
          }
          setServerExportGate(null);
          setServerExportGateStatus("error");
        });
    }, 150);
    return () => {
      cancelled = true;
      window.clearTimeout(timeout);
    };
  }, [preflightPayload]);

  useEffect(() => {
    let cancelled = false;
    setOperatorStatus("Finding next best question");
    const timeout = window.setTimeout(() => {
      getOperatorAssistantSuggestion(task.id, operatorAssistantDecisions)
        .then((suggestion) => {
          if (!cancelled) {
            setOperatorSuggestion(suggestion);
            setOperatorStatus(suggestion.live_model_call_used ? "Model-assisted" : "Deterministic helper");
          }
        })
        .catch((caught: unknown) => {
          if (!cancelled) {
            setOperatorSuggestion(null);
            setOperatorStatus(caught instanceof Error ? `Assistant unavailable: ${caught.message}` : "Assistant unavailable");
          }
        });
    }, 350);
    return () => {
      cancelled = true;
      window.clearTimeout(timeout);
    };
  }, [operatorAssistantDecisions, task.id]);

  useEffect(() => {
    if (artifactMode !== "dpo" || !needsDpoRejectedReason) {
      setDpoRepairProjection(null);
      setDpoRepairProjectionStatus("idle");
      return;
    }
    let cancelled = false;
    setDpoRepairProjection(null);
    setDpoRepairProjectionStatus("pending");
    getDpoRejectedReasonRepairProjection(task.id)
      .then((projection) => {
        if (!cancelled) {
          setDpoRepairProjection(projection);
          setDpoRepairProjectionStatus("ready");
        }
      })
      .catch(() => {
        if (!cancelled) {
          setDpoRepairProjection(null);
          setDpoRepairProjectionStatus("error");
        }
      });
    return () => {
      cancelled = true;
    };
  }, [artifactMode, needsDpoRejectedReason, task.id]);

  useEffect(() => {
    getVoiceModes()
      .then(setVoiceModes)
      .catch(() => {
        setVoiceModes([]);
      });
  }, []);

  useEffect(() => {
    const response_rubric =
      artifactMode === "dpo"
        ? responseRubric
        : {
            response_a: emptyGoldRubricState(),
            response_b: responseBRubric
          };
    onChange({
      artifact_mode: artifactMode,
      artifact_mode_source: artifactModeSource,
      editor_mode: editorMode,
      editor_mode_source: editorModeSource,
      prompt,
      system_prompt: systemPrompt,
      voice_mode: voiceMode,
      synthetic: synthetic === "yes",
      truth_status: effectiveTruthStatus,
      truth_mode: effectiveTruthStatus,
      grounding_asset_id: groundingAssetId,
      context,
      context_pack_id: payloadString(payload.context_pack_id),
      prompt_spec_id: payloadString(payload.prompt_spec_id),
      generation_id: payloadString(payload.generation_id),
      content,
      chosen: artifactMode === "dpo" ? chosen : content,
      rejected: artifactMode === "dpo" ? rejected : "",
      model_draft: artifactMode === "dpo" ? rejected : "",
      adam_gold_edit: artifactMode === "dpo" ? chosen : content,
      response_rubric,
      rubric_summary: rubricSummary,
      ratings: rubricRatings,
      failure_modes: failureModes,
      preferred_failure_modes: preferredFailureModes,
      operator_assistant_log: operatorMessages,
      operator_candidate_triage_intent: operatorCandidateTriageIntent,
      ...(serverExportGate
        ? {
            export_gate_preview: {
              submit_outcome: serverExportGate.submit_outcome,
              dataset_outcome: serverExportGate.dataset_outcome,
              blockers: serverExportGate.blockers,
              source: "backend_preflight"
            }
          }
        : {}),
      export_flags: effectiveExportFlags,
      export_preview_yaml: displayExportPreviewYaml
    });
  }, [artifactMode, artifactModeSource, chosen, content, context, displayExportPreviewYaml, editorMode, editorModeSource, effectiveExportFlags, effectiveTruthStatus, failureModes, groundingAssetId, onChange, operatorCandidateTriageIntent, operatorMessages, payload.context_pack_id, payload.generation_id, payload.prompt_spec_id, preferredFailureModes, prompt, rejected, responseBRubric, responseRubric, rubricRatings, rubricSummary, serverExportGate, synthetic, systemPrompt, voiceMode]);

  function updateRubricDecision(responseKey: keyof ResponseRubricState, key: GoldRubricKey, decision: RubricDecision) {
    setResponseRubric((current) => ({
      ...current,
      [responseKey]: {
        ...current[responseKey],
        [key]: decision
      }
    }));
  }

  async function handleCreateVoiceMode() {
    const label = newVoiceModeLabel.trim();
    if (!label) {
      return;
    }
    const created = await createVoiceMode({ label, family: "adam_defined" });
    setVoiceModes((current) => [...current.filter((mode) => mode.slug !== created.slug), created]);
    setVoiceMode(created.slug);
    setNewVoiceModeLabel("");
    setAddingVoiceMode(false);
  }

  function handleArtifactModeChange(nextMode: "sft" | "dpo") {
    setArtifactModeSource("manual");
    setArtifactMode(nextMode);
  }

  function handleEditorModeChange(nextMode: PromptPairEditorMode) {
    if (nextMode === "yaml") {
      if (artifactMode === "sft") {
        setSftYamlDraft(exportPreviewYaml);
      } else {
        setDpoYamlDraft(exportPreviewYaml);
      }
    }
    setEditorModeSource("manual");
    setEditorMode(nextMode);
  }

  function handleSftYamlDraftChange(value: string) {
    yamlEditSourceRef.current = true;
    setSftYamlDraft(value);
    const parsed = parseSftYamlEditor(value);
    if (!parsed) {
      return;
    }
    setSystemPrompt(parsed.systemPrompt || defaultSystemPromptForMode("sft"));
    setPrompt(parsed.prompt);
    setContent(parsed.content);
  }

  function handleDpoYamlDraftChange(value: string) {
    yamlEditSourceRef.current = true;
    setDpoYamlDraft(value);
    const parsed = parseDpoYamlEditor(value);
    if (!parsed) {
      return;
    }
    setSystemPrompt(parsed.systemPrompt || defaultSystemPromptForMode("dpo"));
    setPrompt(parsed.prompt);
    setChosen(parsed.chosen);
    setRejected(parsed.rejected);
  }

  function applyDpoRejectedReasonScaffold() {
    const currentDecision = responseRubric.response_a.voice_authenticity;
    const suggestedFailureMode = dpoRepairSuggestedFailureMode || "too_generic_not_charles_voice";
    const suggestedIssue = dpoRepairProjection?.suggested_rejected_issue;
    const suggestedIssueTag = suggestedIssue?.issue_tag || suggestedFailureMode;
    updateRubricDecision("response_a", "voice_authenticity", {
      ...currentDecision,
      status: "minor_issues",
      notes:
        currentDecision.notes.trim() ||
        suggestedIssue?.note ||
        `Rejected response needs Adam's concrete note for ${labelFromKey(suggestedFailureMode)}: explain why it is less Charles-like than Chosen. Replace this scaffold with the actual failure.`,
      issue_tags: uniqueValues([...currentDecision.issue_tags, "not_charles_voice", suggestedFailureMode, suggestedIssueTag])
    });
  }

  function handleRejectedReasonChange(value: string) {
    const currentDecision = responseRubric.response_a.voice_authenticity;
    updateRubricDecision("response_a", "voice_authenticity", {
      ...currentDecision,
      status: value.trim() ? "minor_issues" : "no_issues",
      notes: value,
      issue_tags: value.trim() ? uniqueValues([...currentDecision.issue_tags, "not_charles_voice"]) : []
    });
  }

  function applyPromptPairOperatorFieldUpdates(updates: Decisions): string[] {
    const applied: string[] = [];
    const setIfPresent = (key: string, setter: (value: string) => void) => {
      if (Object.prototype.hasOwnProperty.call(updates, key)) {
        const value = updateText(updates[key]);
        if (value.trim()) {
          setter(value);
          applied.push(promptFromDecisionKey(key));
        }
      }
    };

    setIfPresent("prompt", setPrompt);
    setIfPresent("content", (value) => {
      setContent(value);
      if (artifactMode !== "dpo") {
        setChosen(value);
      }
    });
    setIfPresent("chosen", setChosen);
    setIfPresent("rejected", setRejected);
    setIfPresent("context", (value) => setContext((current) => [current, value].filter(Boolean).join("\n\n")));
    setIfPresent("system_prompt", setSystemPrompt);
    setIfPresent("voice_mode", setVoiceMode);
    setIfPresent("truth_status", () => undefined);
    setIfPresent("truth_mode", () => undefined);
    setIfPresent("grounding_asset_id", setGroundingAssetId);
    setIfPresent("operator_candidate_triage_intent", setOperatorCandidateTriageIntent);

    if (updates.artifact_mode === "sft" || updates.artifact_mode === "dpo") {
      setArtifactMode(updates.artifact_mode);
      setArtifactModeSource("assistant");
      applied.push(promptFromDecisionKey("artifact_mode"));
    }
    if (updates.editor_mode === "plain" || updates.editor_mode === "yaml") {
      setEditorMode(updates.editor_mode);
      setEditorModeSource("assistant");
      applied.push(promptFromDecisionKey("editor_mode"));
    }
    if (Object.prototype.hasOwnProperty.call(updates, "synthetic")) {
      setSynthetic(updateBooleanYesNo(updates.synthetic));
      applied.push(promptFromDecisionKey("synthetic"));
    }
    return applied;
  }

  async function applyPromptPairOperatorAnswer() {
    const answer = operatorAnswer.trim();
    if (!answer || !operatorSuggestion) {
      setOperatorApplyStatus("Write an answer first, then apply it.");
      return;
    }
    setOperatorApplyStatus("Asking operator model to parse this.");
    let suggestion = operatorSuggestion;
    try {
      suggestion = await getOperatorAssistantSuggestion(task.id, operatorAssistantDecisions, answer);
      setOperatorSuggestion(suggestion);
      setOperatorStatus(suggestion.live_model_call_used ? "Model-assisted" : "Deterministic helper");
    } catch (caught) {
      setOperatorApplyStatus(caught instanceof Error ? `Assistant parse failed: ${caught.message}` : "Assistant parse failed");
    }
    const updates = fieldUpdatesFromSuggestion(suggestion);
    let appliedFields = applyPromptPairOperatorFieldUpdates(updates);
    const target = suggestion.target_decision_key;
    const deleteIntent = /\b(delete|remove|reject|discard|not worth keeping|do not keep)\b/i.test(answer);
    if (appliedFields.length === 0) {
      if (target === "prompt") {
        setPrompt(answer);
      } else if (target === "content") {
        setContent(answer);
        if (artifactMode !== "dpo") {
          setChosen(answer);
        }
      } else if (target === "chosen") {
        setChosen(answer);
      } else if (target === "rejected") {
        setRejected(answer);
      } else if (target === "system_prompt") {
        setSystemPrompt(answer);
      } else {
        setContext((current) => [current, answer].filter(Boolean).join("\n\n"));
      }
      appliedFields = [suggestion.target_label];
    }
    if (deleteIntent) {
      setOperatorCandidateTriageIntent("delete_candidate");
    }
    const submitRecommendation = suggestion.submit_recommendation;
    const appliedMessage = submitRecommendation?.requested
      ? submitRecommendation.ready
        ? "Assistant says this item is ready and is submitting it."
        : `Assistant says more review is needed before submit: ${submitRecommendation.missing_fields.map(promptFromDecisionKey).join(", ") || "missing fields"}`
      : deleteIntent
      ? "Delete intent noted. Use Delete candidate to remove this item from the active review worklist while preserving the audit record."
      : `Applied to ${appliedFields.join(", ")}.`;
    setOperatorMessages((current) =>
      [
        ...current,
        { role: "assistant" as const, content: operatorSuggestion.next_question, detail: operatorSuggestion.target_label },
        { role: "user" as const, content: answer },
        { role: "system" as const, content: appliedMessage }
      ].slice(-8)
    );
    setOperatorApplyStatus(appliedMessage);
    setOperatorAnswer("");
    if (submitRecommendation?.requested && submitRecommendation.ready && onOperatorSubmit) {
      await onOperatorSubmit({ ...operatorAssistantDecisions, ...updates });
    }
  }

  return (
    <div className="gold-grid training-artifact-grid">
      <section className="training-editor-intro" aria-label="Training artifact editor">
        <div>
          <span>{artifactMode.toUpperCase()} training row</span>
          <strong>{prompt || "Untitled prompt"}</strong>
          <p>
            {promptPairExportReady ? "Ready" : currentPromptPairBlocker ? `Needs edit: ${labelFromKey(currentPromptPairBlocker)}` : "Candidate"}
          </p>
        </div>
        <div className="prompt-pair-mode-bar">
          <div className="mode-control">
            <span>Artifact</span>
            <div className="segmented-control" aria-label="Training artifact mode">
              <button type="button" className={artifactMode === "sft" ? "active" : ""} onClick={() => handleArtifactModeChange("sft")}>
                SFT
              </button>
              <button type="button" className={artifactMode === "dpo" ? "active" : ""} onClick={() => handleArtifactModeChange("dpo")}>
                DPO
              </button>
            </div>
          </div>
          <span className="plain-editing-chip">Plain editor</span>
        </div>
      </section>
      <PhotoPromptPairSourceCard
        task={task}
        asset={assets.find((candidate) => candidate.id === (payloadString(payload.source_photo_id) || groundingAssetId))}
        previewAccessToken={photoPreviewAccessToken}
      />
      {sourceExcerpt ? (
        <details className="training-support-drawer">
          <summary>
            <span>Source evidence</span>
            <em>{sourceExcerptTitle}</em>
          </summary>
          <section className="prompt-pair-source-card">
            <div>
              <span>Source excerpt</span>
              <strong>{sourceExcerptTitle}</strong>
            </div>
            <LinePreview text={sourceExcerpt} />
          </section>
        </details>
      ) : null}
      {generationEvidenceVisible ? (
        <details className="training-support-drawer">
          <summary>
            <span>Generation evidence</span>
            <em>{labelFromKey(sourceEvidenceStatus)}</em>
          </summary>
          <section className="prompt-pair-generation-evidence" aria-label="Generated candidate evidence quality">
            <dl>
              <div>
                <dt>Evidence gate</dt>
                <dd>{evidenceGate.passed === true ? "Passed" : labelFromKey(recordString(evidenceGate, "reason", sourceEvidenceStatus))}</dd>
              </div>
              <div>
                <dt>Source refs</dt>
                <dd>{sourceEvidenceRefs.length}</dd>
              </div>
              <div>
                <dt>Ranked refs</dt>
                <dd>
                  {rankedEvidenceRecords.length ||
                    (typeof rankedEvidencePacket.record_count === "number" ? rankedEvidencePacket.record_count : payloadString(rankedEvidencePacket.record_count, "0"))}
                </dd>
              </div>
              <div>
                <dt>Strategy</dt>
                <dd>{labelFromKey(generationStrategy)}</dd>
              </div>
            </dl>
            {sourceExcerptHash ? (
              <div className="prompt-pair-evidence-hash">
                <span>Excerpt hash</span>
                <code>{sourceExcerptHash.slice(0, 16)}</code>
              </div>
            ) : null}
            {sourceEvidenceRefs.length > 0 ? (
              <div className="prompt-pair-evidence-list" aria-label="Source evidence references">
                {sourceEvidenceRefs.slice(0, 4).map((ref, index) => (
                  <span key={`${recordString(ref, "target_id", "ref")}-${index}`}>
                    {recordString(ref, "target_type", "source")} / {recordString(ref, "target_id", `ref-${index + 1}`)}
                  </span>
                ))}
              </div>
            ) : null}
            {rankedEvidenceRecords.length > 0 ? (
              <div className="prompt-pair-evidence-list" aria-label="Ranked evidence records">
                {rankedEvidenceRecords.slice(0, 3).map((record, index) => (
                  <span key={`${recordString(record, "target_id", "ranked")}-${index}`}>
                    {recordString(record, "title", recordString(record, "target_id", `ranked-${index + 1}`))}
                  </span>
                ))}
              </div>
            ) : null}
          </section>
        </details>
      ) : null}
      <details className="training-support-drawer training-assistant-drawer">
        <summary>
          <span>Review assistant</span>
          <em>{operatorStatus}</em>
        </summary>
      <OperatorAssistantPanel
        suggestion={operatorSuggestion}
        status={operatorStatus}
        messages={operatorMessages}
        answer={operatorAnswer}
        applyStatus={operatorApplyStatus}
        onAnswerChange={setOperatorAnswer}
        onSend={() => void applyPromptPairOperatorAnswer()}
      />
      </details>
      <details className="training-support-drawer training-metadata-drawer">
        <summary>
          <span>Details</span>
          <em>{labelFromKey(voiceMode)} / {synthetic === "yes" ? "Synthetic" : "Source-authored"}</em>
        </summary>
      <div className="prompt-grid">
        <Field label="Voice Mode">
          <select
            value={addingVoiceMode ? "__add_new__" : voiceMode}
            onChange={(event) => {
              if (event.target.value === "__add_new__") {
                setAddingVoiceMode(true);
                return;
              }
              setAddingVoiceMode(false);
              setVoiceMode(event.target.value);
            }}
          >
            {voiceModes.length === 0 ? <option value={voiceMode}>{labelFromKey(voiceMode)}</option> : null}
            {voiceModes.map((mode) => (
              <option key={mode.slug} value={mode.slug}>
                {mode.label}
              </option>
            ))}
            <option value="__add_new__">+ Add New</option>
          </select>
        </Field>
        <Field label="Synthetic">
          <select value={synthetic} onChange={(event) => setSynthetic(event.target.value === "no" ? "no" : "yes")}>
            <option value="yes">Yes</option>
            <option value="no">No</option>
          </select>
        </Field>
        <Field label="Grounding Source" hint="Optional imported asset that should act as RAG/source context.">
          <select value={groundingAssetId} onChange={(event) => setGroundingAssetId(event.target.value)}>
            <option value="">None</option>
            {assets.map((asset) => (
              <option key={asset.id} value={asset.id}>
                {assetOptionLabel(asset)}
              </option>
            ))}
          </select>
        </Field>
        {addingVoiceMode ? (
          <Field label="New Voice Mode">
            <div className="inline-create-row">
              <input value={newVoiceModeLabel} onChange={(event) => setNewVoiceModeLabel(event.target.value)} />
              <button type="button" onClick={() => void handleCreateVoiceMode()}>
                Add
              </button>
            </div>
          </Field>
        ) : null}
        <Field label="Context" hint="Freeform context for smart models, reviewers, and future RAG pack builders.">
          <TextArea value={context} onChange={setContext} rows={5} />
        </Field>
      </div>
      </details>
      <Field label="Prompt" hint="The user-facing prompt this row trains against.">
        <textarea rows={4} value={prompt} required onChange={(event) => setPrompt(event.target.value)} />
      </Field>
      {sourceBoundaryFocusVisible ? (
        <section className="source-boundary-training-focus" aria-label="Source boundary training focus aid">
          <header>
            <div>
              <span>Source boundary</span>
              <strong>Source boundary blocks training</strong>
            </div>
            <em>Pair Submit is non-mutating</em>
          </header>
          <p>
            This prompt pair stays candidate material until Adam decides whether the source asset can train SFT/DPO. Submit here saves
            review progress only; it does not mutate the imported source, source boundary, or approved training export.
          </p>
          <div className="source-boundary-grid" aria-label="Source boundary permission snapshot">
            <span>
              <em>Source photo</em>
              <strong>{sourcePhotoId || "Not linked"}</strong>
            </span>
            <span>
              <em>Privacy</em>
              <strong>{formatMetadataValue(boundarySnapshot.privacy_level, "Unknown")}</strong>
            </span>
            <span>
              <em>Usable for SFT</em>
              <strong>{formatMetadataValue(boundarySnapshot.usable_for_sft, "Unknown")}</strong>
            </span>
            <span>
              <em>Usable for DPO</em>
              <strong>{formatMetadataValue(boundarySnapshot.usable_for_dpo, "Unknown")}</strong>
            </span>
            <span>
              <em>Reviewed by</em>
              <strong>{formatMetadataValue(boundarySnapshot.reviewed_by, "Unreviewed")}</strong>
            </span>
            <span>
              <em>Blocked uses</em>
              <strong>{sourceBoundaryBlockedUses.map(labelFromKey).join(", ") || "None projected"}</strong>
            </span>
          </div>
          <ul>
            <li>Keep this prompt pair as review-only context if the source should not train the model.</li>
            <li>If Adam clears the source for training, update the source boundary first, then return to this pair.</li>
            <li>Voice-context, eval, SFT, and DPO permissions remain separate boundary decisions.</li>
          </ul>
        </section>
      ) : null}
      {artifactMode === "sft" ? (
        <>
          {editorMode === "yaml" ? (
            <Field label="SFT YAML" hint="Exported message structure.">
              <LineNumberedTextArea className="prompt-pair-yaml-editor" value={sftYamlDraft} onChange={handleSftYamlDraftChange} rows={22} />
            </Field>
          ) : (
            <Field label="Content" hint="Plain assistant response editor. Prompt is above; the YAML preview below shows the exact export.">
              <LineNumberedTextArea className="prompt-pair-plain-editor" value={content} onChange={setContent} rows={18} />
            </Field>
          )}
          <details className="training-review-drawer">
            <summary>
              <span>Issue rubric</span>
              <em>{preferredFailureModes.length === 0 ? "No issues marked" : `${preferredFailureModes.length} issue(s)`}</em>
            </summary>
            <FormHint title="Issue rubric">
              Mark issues only if this SFT content still needs work before export.
            </FormHint>
            <section className="response-rubric-column single-rubric-column">
              <div className="response-rubric-heading">
                <strong>Content</strong>
                <span>{preferredFailureModes.length === 0 ? "No issues marked" : `${preferredFailureModes.length} issue(s)`}</span>
              </div>
              <div className="rubric-stack">
                {goldReviewRubric.map((criterion) => (
                  <RubricIssueCard
                    key={criterion.key}
                    criterion={criterion}
                    decision={responseBRubric[criterion.key]}
                    noteLabel="What still needs work?"
                    noteHint="Use plain language; this stays with the draft until resolved."
                    onChange={(decision) => updateRubricDecision("response_b", criterion.key, decision)}
                  />
                ))}
              </div>
            </section>
          </details>
        </>
      ) : (
        <>
          {editorMode === "yaml" ? (
            <Field label="DPO YAML" hint="Exported chosen/rejected structure.">
              <LineNumberedTextArea className="prompt-pair-yaml-editor" value={dpoYamlDraft} onChange={handleDpoYamlDraftChange} rows={22} />
            </Field>
          ) : (
            <div className="voice-compare-grid">
              <Field label="Chosen" hint="Preferred response. This is the side you want the model to learn.">
                <LineNumberedTextArea value={chosen} onChange={setChosen} rows={16} />
              </Field>
              <div className="rejected-with-reason">
                <Field label="Rejected" hint="Less authentic or lower-quality response.">
                  <LineNumberedTextArea value={rejected} onChange={setRejected} rows={12} />
                </Field>
                <Field label="Rejected reason" hint="Required DPO comparison note. Explain why Rejected is weaker.">
                  <textarea
                    rows={4}
                    value={rejectedReasonNote}
                    required={artifactMode === "dpo"}
                    onChange={(event) => handleRejectedReasonChange(event.target.value)}
                  />
                </Field>
              </div>
            </div>
          )}
          <details className="training-review-drawer" open={needsDpoRejectedReason}>
            <summary>
              <span>Issue rubric</span>
              <em>
                {failureModes.length} rejected reason{failureModes.length === 1 ? "" : "s"} / {preferredFailureModes.length} chosen issue
                {preferredFailureModes.length === 1 ? "" : "s"}
              </em>
            </summary>
            {needsDpoRejectedReason ? (
              <section className="dpo-rejected-reason-focus" aria-label="DPO rejected reason focus aid">
                <div>
                  <span>DPO rejected reason</span>
                  <strong>Rejected side needs a concrete issue note</strong>
                  <p>
                    Add a Minor or Major issue under the Rejected rubric. The note becomes the DPO reason; it is a comparison note, not a new memory claim.
                  </p>
                </div>
                <div className="dpo-repair-inline-projection" aria-label="DPO rejected reason repair projection">
                  <span>Repair projection</span>
                  {dpoRepairProjectionStatus === "pending" ? (
                    <strong>Loading non-mutating YAML delta</strong>
                  ) : dpoRepairProjectionStatus === "error" ? (
                    <strong>Projection unavailable; rubric scaffold still works</strong>
                  ) : dpoRepairProjection?.found ? (
                    <>
                      <strong>Top rejected-side gap: {labelFromKey(dpoRepairSuggestedFailureMode || "dpo rejected reason empty")}</strong>
                      <p>
                        Before: {dpoRepairProjection.before.blockers.map(labelFromKey).join(", ") || "No blockers"} / After:{" "}
                        {dpoRepairProjection.after.blockers.map(labelFromKey).join(", ") || "No blockers"}.
                        {dpoRepairProjection.target_blocker_cleared ? " Rejected-reason blocker clears." : " Rejected-reason blocker remains."}
                      </p>
                      {dpoRepairProjection.suggested_rejected_issue?.note ? <p>{dpoRepairProjection.suggested_rejected_issue.note}</p> : null}
                      <small>
                        Non-mutating projection. Adam gold review still required. Hash {dpoRepairProjection.content_sha256.slice(0, 16)}.
                      </small>
                      <details>
                        <summary>YAML delta preview</summary>
                        <pre>{dpoRepairProjection.yaml_diff_preview}</pre>
                      </details>
                      <div className="dpo-repair-outcome-preview" aria-label="DPO repair session outcome preview">
                        <span>Session outcome preview</span>
                        <dl>
                          <div>
                            <dt>Would clear</dt>
                            <dd>{dpoRepairProjection.cleared_blockers.map(labelFromKey).join(", ") || "No blockers projected to clear"}</dd>
                          </div>
                          <div>
                            <dt>Still remains</dt>
                            <dd>{dpoRepairProjection.after.blockers.map(labelFromKey).join(", ") || "No blockers projected"}</dd>
                          </div>
                          <div>
                            <dt>Projected status</dt>
                            <dd>{labelFromKey(dpoRepairProjection.after.export_status)}</dd>
                          </div>
                          <div>
                            <dt>Dataset outcome</dt>
                            <dd>{dpoRepairProjection.after.dataset_outcome}</dd>
                          </div>
                        </dl>
                        <p>
                          Submit would save this as review-candidate material only. No approved DPO row is created until Adam completes gold review.
                        </p>
                      </div>
                    </>
                  ) : (
                    <strong>No matching backend repair projection for this item yet</strong>
                  )}
                </div>
                <button type="button" onClick={applyDpoRejectedReasonScaffold}>
                  Apply projected review-note scaffold
                </button>
              </section>
            ) : null}
            <FormHint title="Issue rubric">
              Use the same rubric on both responses. The rejected side can carry Minor Issues or Major Issues plus context explaining why.
            </FormHint>
            <div className="response-rubric-grid">
              <section className="response-rubric-column">
                <div className="response-rubric-heading">
                  <strong>Chosen</strong>
                  <span>Preferred</span>
                </div>
                <div className="rubric-stack">
                  {goldReviewRubric.map((criterion) => (
                    <RubricIssueCard
                      key={criterion.key}
                      criterion={criterion}
                      decision={responseBRubric[criterion.key]}
                      noteLabel="Any remaining issue in Chosen?"
                      noteHint="Usually this should be No issues before submit."
                      onChange={(decision) => updateRubricDecision("response_b", criterion.key, decision)}
                    />
                  ))}
                </div>
              </section>
              <section className="response-rubric-column">
                <div className="response-rubric-heading">
                  <strong>Rejected</strong>
                  <span>Comparison target</span>
                </div>
                <div className="rubric-stack">
                  {goldReviewRubric.map((criterion) => (
                    <RubricIssueCard
                      key={criterion.key}
                      criterion={criterion}
                      decision={responseARubric[criterion.key]}
                      noteLabel="What was wrong with Rejected?"
                      noteHint="This explanatory context becomes the DPO reason."
                      onChange={(decision) => updateRubricDecision("response_a", criterion.key, decision)}
                    />
                  ))}
                </div>
              </section>
            </div>
          </details>
        </>
      )}
      <section
        className="prompt-pair-export-gate"
        aria-label="Prompt pair export gate"
        aria-busy={serverExportGateStatus === "pending"}
        data-ready={promptPairExportReady ? "true" : "false"}
        data-source={serverExportGateStatus === "ready" ? "backend" : "pending"}
      >
        <div>
          <span>Gate source</span>
          <strong>
            {serverExportGateStatus === "ready"
              ? "Backend preflight"
              : serverExportGateStatus === "error"
                ? "Backend preflight unavailable"
                : "Checking backend preflight"}
          </strong>
        </div>
        <div>
          <span>Submit outcome</span>
          <strong>{promptPairGateOutcome}</strong>
        </div>
        <div>
          <span>Dataset outcome</span>
          <strong>{promptPairDatasetOutcome}</strong>
        </div>
        <div>
          <span>Gate notes</span>
          <strong>{promptPairGateBlockers.length ? `${promptPairGateBlockers.length} blocker(s)` : "No blockers"}</strong>
        </div>
        {promptPairGateBlockers.length > 0 ? (
          <div className="prompt-pair-export-blockers">
            {promptPairGateBlockers.slice(0, 4).map((blocker) => (
              <em key={blocker}>{labelFromKey(blocker)}</em>
            ))}
          </div>
        ) : null}
        {promptPairHeldExplanation ? (
          <div className="prompt-pair-held-explanation" aria-label="Prompt pair held explanation">
            <span>Why held?</span>
            <strong>{promptPairHeldExplanation}</strong>
          </div>
        ) : null}
        <div className="prompt-pair-submit-preview" aria-label="Prompt pair submit receipt preview">
          <span>On Submit</span>
          <strong>{submitReceiptPreview}</strong>
          <em>{submitReceiptPreviewDetail}</em>
        </div>
      </section>
      {!promptPairExportReady ? (
        <details className="training-review-drawer prompt-pair-candidate-drawer">
          <summary>
            <span>Candidate workdown</span>
            <em>
              {candidateWorkdownBlockers.length} blocker{candidateWorkdownBlockers.length === 1 ? "" : "s"}
            </em>
          </summary>
          <section className="prompt-pair-candidate-workdown" aria-label="Prompt pair candidate workdown">
            <header>
              <div>
                <span>Candidate workdown</span>
                <strong>
                  {candidateWorkdownBlockers.length} blocker{candidateWorkdownBlockers.length === 1 ? "" : "s"}{" "}
                  {candidateWorkdownBlockers.length === 1 ? "remains" : "remain"}
                </strong>
              </div>
              <em>Not approved training export</em>
            </header>
            <p>Submit saves review progress as candidate material. It does not create an approved SFT/DPO row until backend blockers clear.</p>
            <ol>
              {candidateWorkdownBlockers.map((blocker) => (
                <li key={blocker.key}>
                  <strong>{blocker.label}</strong>
                  <span>{blocker.action}</span>
                </li>
              ))}
            </ol>
          </section>
        </details>
      ) : null}
      <section className="gold-outcome-strip" aria-label="Gold edit downstream outcomes">
        <div>
          <span>Export Artifact</span>
          <strong>
            {privacyExportBlocked
              ? "Held until privacy issue is resolved"
              : boundarySftBlocked
                ? "Held until source boundary allows training"
                : artifactMode.toUpperCase()}
          </strong>
        </div>
        <div>
          <span data-enabled="true">Gold voice</span>
          {Object.entries(effectiveExportFlags).map(([key, enabled]) => (
            <span key={key} data-enabled={enabled ? "true" : "false"}>
              {labelFromKey(key)}
            </span>
          ))}
        </div>
      </section>
      <div className="rubric-summary">
        <span className={promptPairExportReady ? "ready" : "needs-work"}>
          {promptPairExportReady ? "Chosen/content ready" : "Resolve boundary, rubric, or structure issues before export"}
        </span>
        {artifactMode === "dpo" ? <span>Rejected: {failureModes.length} DPO reason{failureModes.length === 1 ? "" : "s"}</span> : null}
        <span>Chosen/content: {preferredFailureModes.length} remaining issue{preferredFailureModes.length === 1 ? "" : "s"}</span>
        {promptPairGateBlockers.map((blocker: string) => (
          <span key={blocker} className="blocked">
            {labelFromKey(blocker)}
          </span>
        ))}
        {privacyExportBlocked ? <span className="blocked">Privacy block active</span> : null}
      </div>
      <details className="training-review-drawer export-preview-drawer">
        <summary>
          <span>Export YAML preview</span>
          <em>{exportPreviewIntegrity.label}</em>
        </summary>
        <section className="export-preview-card">
          <div className="export-preview-header">
            <span>Export Artifacts</span>
            <strong>YAML preview</strong>
            <em
              className="export-preview-integrity"
              aria-label="Export preview integrity"
              data-status={exportPreviewIntegrity.status}
            >
              {exportPreviewIntegrity.label}
            </em>
          </div>
          <LinePreview text={displayExportPreviewYaml} className="export-line-preview" />
        </section>
      </details>
    </div>
  );
}

export function TaskWorkbench({
  task,
  asset,
  queuePosition,
  queueTotal,
  completedThisSession,
  memoriesCount,
  goldExamplesCount,
  assetsCount,
  assets,
  photoPreviewAccessToken,
  onSubmit,
  onSkip,
  onFlag,
  onDeleteCandidate,
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
  const [sourceSpans, setSourceSpans] = useState<SourceSpanDraft[]>([]);
  const [sourcePairPreview, setSourcePairPreview] = useState<SourcePairGenerationPreview | null>(null);
  const [sourcePairPreviewStatus, setSourcePairPreviewStatus] = useState("");
  const [evidenceCorpus, setEvidenceCorpus] = useState<EvidenceCorpusResponse | null>(null);
  const [evidenceCorpusLoading, setEvidenceCorpusLoading] = useState(false);
  const [evidenceCorpusError, setEvidenceCorpusError] = useState<string | null>(null);
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
    setSourceSpans([]);
    setSourcePairPreview(null);
    setSourcePairPreviewStatus("");
    setEvidenceCorpus(null);
    setEvidenceCorpusError(null);
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
        setSourceSpans(spansFromDecision(nextDecisions.source_spans));
        setDraftUpdatedAt(draft?.updated_at ?? null);
        setDraftStatus(draft ? "Draft restored" : "No draft yet");
        lastSavedDraftRef.current = JSON.stringify({
          decisions: { ...nextDecisions, ...nextSelection, source_spans: spansFromDecision(nextDecisions.source_spans) },
          notes: draft?.notes ?? ""
        });
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
    () => ({ ...decisions, ...chunkSelection, ...textEdits, source_spans: sourceSpans }),
    [chunkSelection, decisions, sourceSpans, textEdits]
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

  useEffect(() => {
    if (!draftLoaded || !isGeneratePairsTask(task)) {
      setEvidenceCorpus(null);
      setEvidenceCorpusError(null);
      setEvidenceCorpusLoading(false);
      return;
    }
    let cancelled = false;
    setEvidenceCorpusLoading(true);
    setEvidenceCorpusError(null);
    getEvidenceCorpus("family_private", 12)
      .then((corpus) => {
        if (!cancelled) {
          setEvidenceCorpus(corpus);
        }
      })
      .catch((caught: unknown) => {
        if (!cancelled) {
          setEvidenceCorpus(null);
          setEvidenceCorpusError(caught instanceof Error ? caught.message : "Could not load evidence corpus.");
        }
      })
      .finally(() => {
        if (!cancelled) {
          setEvidenceCorpusLoading(false);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [draftLoaded, task.id, task.task_type]);

  useEffect(() => {
    if (!draftLoaded || !isGeneratePairsTask(task)) {
      setSourcePairPreview(null);
      setSourcePairPreviewStatus("");
      return;
    }
    let cancelled = false;
    setSourcePairPreviewStatus("Updating generation preview");
    const timeout = window.setTimeout(() => {
      previewSourcePairGeneration(task.id, { ...autosaveDecisions, generate_pairs_on_submit: "yes" })
        .then((preview) => {
          if (cancelled) {
            return;
          }
          setSourcePairPreview(preview);
          setSourcePairPreviewStatus("Preview ready");
        })
        .catch((caught: unknown) => {
          if (!cancelled) {
            setSourcePairPreview(null);
            setSourcePairPreviewStatus(caught instanceof Error ? `Preview failed: ${caught.message}` : "Preview failed");
          }
        });
    }, 500);

    return () => {
      cancelled = true;
      window.clearTimeout(timeout);
    };
  }, [autosaveDecisions, draftLoaded, task]);

  async function submitCurrentTask(decisionsOverride?: Decisions) {
    setBusy(true);
    try {
      const submitDecisions = isGeneratePairsTask(task)
        ? { ...(decisionsOverride ?? autosaveDecisions), generate_pairs_on_submit: "yes" }
        : decisionsOverride ?? autosaveDecisions;
      await onSubmit(submitDecisions, notes);
    } finally {
      setBusy(false);
    }
  }

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    await submitCurrentTask();
  }

  async function handleDeleteCandidate() {
    if (!onDeleteCandidate) {
      return;
    }
    const confirmed = window.confirm(
      "Delete this prompt-pair candidate from the active review worklist? A review record will be kept."
    );
    if (!confirmed) {
      return;
    }
    setBusy(true);
    try {
      await onDeleteCandidate("Rejected from Prompt Pairs editor");
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

  const handleSourceSpansChange = useCallback((nextSpans: SourceSpanDraft[]) => {
    setSourceSpans(nextSpans);
  }, []);

  const selectedEvidenceRecordIds = useMemo(
    () =>
      Array.isArray(decisions.supplemental_evidence_record_ids)
        ? decisions.supplemental_evidence_record_ids.map(String).filter(Boolean)
        : [],
    [decisions.supplemental_evidence_record_ids]
  );

  const handleEvidenceRecordToggle = useCallback((embeddingRecordId: string) => {
    setDecisions((current) => {
      const currentIds = Array.isArray(current.supplemental_evidence_record_ids)
        ? current.supplemental_evidence_record_ids.map(String).filter(Boolean)
        : [];
      const nextIds = currentIds.includes(embeddingRecordId)
        ? currentIds.filter((id) => id !== embeddingRecordId)
        : [...currentIds, embeddingRecordId];
      return { ...current, supplemental_evidence_record_ids: nextIds };
    });
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
      case "vision_draft_review":
        return (
          <PhotoMemoryReviewForm
            task={task}
            initialDecisions={draftDecisions}
            onChange={handleDecisionChange}
            onOperatorSubmit={submitCurrentTask}
          />
        );
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
        return (
          <GoldVoiceEditForm
            task={task}
            assets={assets}
            photoPreviewAccessToken={photoPreviewAccessToken}
            initialDecisions={draftDecisions}
            onChange={handleDecisionChange}
            onOperatorSubmit={submitCurrentTask}
          />
        );
      default:
        return (
          <Field label="Review data">
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
  const formInCanvas = isPromptPairCandidateTask(task);
  const sourceReviewInCanvas = ["text_segment_review", "photo_context", "vision_draft_review"].includes(task.task_type);
  const segmentationInCanvas = task.task_type === "text_segment_boundary_review";
  const formInCenter = formInCanvas || sourceReviewInCanvas || segmentationInCanvas;
  const showSourceReviewCanvas = !formInCanvas;
  const showPhotoPreview = isPhotoLikeTask(task, asset);
  const showChunkBrowser =
    showSourceReviewCanvas &&
    ["text_segment_boundary_review", "grounded_prompt_pair_candidate"].includes(task.task_type);
  const showEditableExtraction = false;
  const reviewCanvasClass = [
    "review-canvas",
    formInCanvas ? "editor-workspace" : "preview-workspace",
    sourceReviewInCanvas ? "has-questionnaire" : "",
    segmentationInCanvas ? "has-segmentation" : ""
  ]
    .filter(Boolean)
    .join(" ");
  const reviewGridClass = formInCanvas ? "review-grid training-review-grid quiet-review-grid" : "review-grid";
  const effectiveInspectorWidth = formInCanvas ? Math.min(inspectorWidth, 320) : inspectorWidth;
  const draftMetadataItems = task.task_type === "vision_draft_review" || task.task_type === "photo_context"
    ? visionDigestItems(autosaveDecisions)
    : sourceReviewInCanvas
    ? sourceReviewDigestItems(autosaveDecisions)
    : segmentationInCanvas
    ? segmentBoundaryDigestItems(autosaveDecisions)
    : formInCanvas
    ? promptPairDigestItems(autosaveDecisions)
    : genericDecisionDigestItems(autosaveDecisions);
  const approvalBlocker = promptPairApprovalBlocker(task, autosaveDecisions);
  const primaryActionDisabled = busy || Boolean(approvalBlocker);

  return (
    <form className={formInCanvas ? "workbench quiet-review" : "workbench"} onSubmit={handleSubmit}>
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
            <Link className="dossier-action-link" href={`/assets/${asset.id}`} {...tooltip("Built: open the source dossier with provenance, mirror snapshots, derivatives, boundaries, and review history.")}>
              Dossier
            </Link>
          ) : null}
          <div className="quality-score">
            <strong>{readinessBadges[0]?.label ?? "Ready"}</strong>
            <span>Readiness</span>
          </div>
          <select
            value={reviewStatus}
            onChange={(event) => setReviewStatus(event.target.value)}
            aria-label="Review status"
            {...tooltip("Local review status selector for the current session. Submit still saves a durable review record.")}
          >
            <option value="needs_review">Needs Review</option>
            <option value="needs_context">Needs Context</option>
            <option value="draft">Draft</option>
            <option value="approved">Approved</option>
            <option value="blocked">Blocked</option>
          </select>
          <div className="queue-stepper" aria-label="Worklist position">
            <button
              type="button"
              onClick={onPrevious}
              disabled={queuePosition <= 1}
              aria-label="Previous task"
              {...tooltip("Built: move to the previous item in the current filtered worklist.")}
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
              {...tooltip("Built: move to the next item in the current filtered worklist.")}
            >
              <ChevronRight size={16} />
            </button>
          </div>
        </div>
      </header>

      <div
        className={reviewGridClass}
        style={{ "--inspector-width": `${effectiveInspectorWidth}px` } as React.CSSProperties}
      >
        <section className={reviewCanvasClass} aria-label="Source and derived review surface">
          {formInCanvas ? <section className="canvas-form-panel">{form}</section> : null}
          {showSourceReviewCanvas ? (
            <>
              {showPhotoPreview ? (
                <PhotoAssetPreview task={task} asset={asset} previewAccessToken={photoPreviewAccessToken} />
              ) : (
                <SourcePreview task={task} />
              )}
              {showPhotoPreview ? <PhotoGroupContextCard task={task} /> : null}
              {isGeneratePairsTask(task) ? (
                <>
                  <SourceEvidenceCorpusPanel
                    corpus={evidenceCorpus}
                    loading={evidenceCorpusLoading}
                    error={evidenceCorpusError}
                    selectedIds={selectedEvidenceRecordIds}
                    onToggle={handleEvidenceRecordToggle}
                  />
                  <SourcePairGenerationPreviewPanel preview={sourcePairPreview} status={sourcePairPreviewStatus} />
                  <SourceSpanCoder task={task} spans={sourceSpans} onChange={handleSourceSpansChange} />
                </>
              ) : null}
              {showChunkBrowser ? (
                <ChunkBrowser task={task} initialSelection={initialChunkSelection} onChange={handleChunkChange} />
              ) : null}
              {sourceReviewInCanvas || segmentationInCanvas ? <section className="canvas-form-panel source-questionnaire-panel">{form}</section> : null}
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
                    ? "Built: compact readout of item details and current labels."
                    : tab === "annotations"
                      ? "Built: session notes and the current draft review data."
                      : "Built: task status, autosave state, and session counters."
                )}
              >
                {tab === "metadata" ? "Info" : tab === "annotations" ? "Notes" : "History"}
              </button>
            ))}
          </nav>

          {inspectorTab === "metadata" ? (
            <div className="inspector-panel">
              <MetadataValueList
                title="Item details"
                items={[
                  { label: "Area", value: labelFromKey(task.queue) },
                  { label: "Source", value: taskSource },
                  { label: "Kind", value: descriptor.label },
                  { label: "Maturity", value: maturityLabel(asset?.maturity_level) },
                  { label: "Import", value: asset?.import_status ? labelFromKey(asset.import_status) : "Unknown" },
                  { label: "Processing", value: asset?.processing_status ? labelFromKey(asset.processing_status) : "Unknown" },
                  { label: "Confidence", value: "Unreviewed" }
                ]}
              />
              <section className="preview-band">
                <div>
                  <span>Debug target</span>
                  <strong>
                    {task.target_type} / {task.target_id.slice(0, 8)}
                  </strong>
                </div>
                <div>
                  <span>Reason</span>
                  <p>{task.reason_created}</p>
                </div>
                <div>
                  <span>Needed</span>
                  <p>{task.required_decisions.map(promptFromDecisionKey).join(", ")}</p>
                </div>
              </section>
              <section className="decision-surface">
                {formInCenter ? (
                  <>
                    <MetadataValueList
                      title={
                        task.task_type === "vision_draft_review" || task.task_type === "photo_context"
                          ? "Current photo labels"
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
                        Prompt and response fields are in the center editor so the comparison has enough room.
                      </FormHint>
                    ) : task.task_type === "vision_draft_review" || task.task_type === "photo_context" ? (
                      <FormHint title="Photo questions">
                        Answer the photo-memory questions in the center pane below the image; this rail stays as a compact details readout.
                      </FormHint>
                    ) : task.task_type === "text_segment_boundary_review" ? (
                      <FormHint title="Segmentation questions">
                        Select and inspect chunks in the center pane; this rail stays as a compact readout of the current boundary, use, and privacy decisions.
                      </FormHint>
                    ) : (
                      <FormHint title="Source questions">
                        Answer the review questions in the center pane below the source text; this rail stays as a compact details readout.
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
                <span>Current draft</span>
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
        <button type="button" onClick={onSkip} disabled={busy} {...tooltip("Built: mark this item skipped and move on without submitting a review record.")}>
          <SkipForward size={16} />
          Skip
        </button>
        <button type="button" onClick={onFlag} disabled={busy} {...tooltip("Built: put this task on sensitive hold for later review.")}>
          <Flag size={16} />
          Flag
        </button>
        {isPromptPairCandidateTask(task) && onDeleteCandidate ? (
          <button
            className="danger-action"
            type="button"
            onClick={() => void handleDeleteCandidate()}
            disabled={busy}
            {...tooltip("Built: reject/delete this prompt-pair candidate from the active worklist while preserving a review record.")}
          >
            <Trash2 size={16} />
            Delete candidate
          </button>
        ) : null}
        {approvalBlocker ? <p className="submit-blocker" role="status">Approve needs: {approvalBlocker}</p> : null}
        <button className="primary-action" type="submit" disabled={primaryActionDisabled} {...tooltip("Built: submit the item, save a review record, and trigger any downstream records for this workflow.")}>
          <Save size={16} />
          {isGeneratePairsTask(task) ? (busy ? "Generating" : "Generate") : busy ? "Submitting" : formInCanvas ? "Approve" : "Submit"}
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
