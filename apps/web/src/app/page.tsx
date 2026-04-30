"use client";

import {
  Archive,
  CheckCircle2,
  ChevronDown,
  Clock3,
  ClipboardList,
  Database,
  Download,
  FileText,
  FolderArchive,
  Image,
  Inbox,
  RefreshCw,
  Search,
  ShieldCheck,
  Sparkles
} from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  createPhotoPromptPairCandidates,
  createVisionDraftBatch,
  deletePromptPairCandidate,
  flagTask,
  getAssets,
  getAssetPreviewUrl,
  getGoldVoiceExamples,
  getMemories,
  getPhotoContextSessionProgress,
  getPhotoReviewPriority,
  getDpoRejectedReasonRepairPacket,
  getPromptPairAudit,
  getPromptPairReviewProgress,
  getTasks,
  skipTask,
  submitTask
} from "@/lib/api";
import type { Annotation, Asset, AssetUploadResponse, DpoRejectedReasonRepairPacket, GoldVoiceExample, Memory, PhotoContextSessionProgress, PhotoPromptPairCandidateResponse, PhotoReviewPriorityItem, PhotoReviewPrioritySummary, PromptPairAudit, PromptPairReviewProgress, Task } from "@/lib/types";
import { ArtifactUpload } from "@/components/ArtifactUpload";
import { ExportDryRunPanel } from "@/components/ExportDryRunPanel";
import { GoogleDriveImport } from "@/components/GoogleDriveImport";
import { TaskWorkbench } from "@/components/TaskWorkbench";
import { assetIdForTask, readinessBadgesForTask } from "@/lib/readiness";

type NavMode = "intake" | "review" | "make_gold" | "exports";
type CollectionId = "all" | "photos" | "text" | "gold" | "needs_boundary";
type ShellColumn = "sidebar" | "queue";
type PhotoTaskFocus = "all" | "fastest_vector";
type PhotoPromotionDryRun = {
  pathLabel: string;
  taskLabel: string;
  whyFirst: string;
  projectedOutcome: string;
  submitOutcomeBadge: string;
  submitOutcomeLabel: string;
  submitOutcomeDetail: string;
  vectorHandoffPreviewStatus: string;
  missingFields: string[];
  safeguards: string[];
};
type PromptPairFilters = {
  voiceMode: string;
  artifactMode: string;
  qualityStatus: string;
  syntheticStatus: string;
  sourceKind: string;
};
type PhotoContactSheetGroup = {
  groupKey: string;
  canonical: Asset;
  variants: Asset[];
  relatedTask?: Task;
  title: string;
};
type PhotoPromptPairBatchGroup = {
  batchId: string;
  sourceTitle: string;
  sourcePhotoId: string;
  count: number;
  firstTaskId: string;
  firstPrompt: string;
  variantLabels: string[];
  updatedAt: string;
};

type NavItem = { id: NavMode; label: string; icon: React.ReactNode; tooltip: string };
type CollectionItem = { id: CollectionId; label: string; icon: React.ReactNode; tooltip: string };

const topNav: NavItem[] = [
  { id: "intake", label: "Intake", icon: <Inbox size={15} />, tooltip: "Import local or Drive artifacts and start the first triage task." },
  {
    id: "review",
    label: "Review",
    icon: <CheckCircle2 size={15} />,
    tooltip: "Review sources, segments, photos, OCR, boundaries, and privacy before anything moves downstream."
  },
  {
    id: "make_gold",
    label: "Prompt Pairs",
    icon: <Sparkles size={15} />,
    tooltip: "Review each generated SFT or DPO prompt pair as a singleton downstream artifact."
  },
  {
    id: "exports",
    label: "Exports",
    icon: <FolderArchive size={15} />,
    tooltip: "Inspect export dry-runs and build JSONL only from boundary-cleared artifacts."
  }
];

const sideNav: NavItem[] = [
  ...topNav
];

const collectionDefs: CollectionItem[] = [
  { id: "all", label: "All", icon: <Database size={15} />, tooltip: "Show every ready task in this workflow stage." },
  { id: "photos", label: "Photos", icon: <Image size={15} />, tooltip: "Photo, scan, and vision-memory review tasks." },
  { id: "text", label: "Text", icon: <FileText size={15} />, tooltip: "Documents, source text, email, OCR, and segmentation tasks." },
  { id: "gold", label: "Pairs", icon: <Download size={15} />, tooltip: "Prompt-pair tickets waiting for review." },
  { id: "needs_boundary", label: "Needs Boundary", icon: <ShieldCheck size={15} />, tooltip: "Anything waiting on privacy, quote, retrieval, or export clearance." }
];

const RESIZE_STEP = 16;
const shellColumnBounds: Record<ShellColumn, { min: number; max: number }> = {
  sidebar: { min: 172, max: 340 },
  queue: { min: 260, max: 520 }
};

const defaultPromptPairFilters: PromptPairFilters = {
  voiceMode: "all",
  artifactMode: "all",
  qualityStatus: "all",
  syntheticStatus: "all",
  sourceKind: "all"
};
const defaultPhotoTaskFocus: PhotoTaskFocus = "all";

function clamp(value: number, min: number, max: number): number {
  return Math.min(Math.max(value, min), max);
}

function queueLabel(queue: string): string {
  return queue
    .split("_")
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(" ");
}

function promptPairBlockerActionLabel(blocker?: string | null): string {
  if (blocker === "dpo_rejected_reason_empty") {
    return "Write rejected reason";
  }
  if (blocker === "source_boundary_blocks_training") {
    return "Review source boundary";
  }
  if (blocker) {
    return `Work ${queueLabel(blocker)}`;
  }
  return "Work held candidate";
}

function payloadStringList(value: unknown): string[] {
  return Array.isArray(value) ? value.map(String).filter(Boolean) : [];
}

function responseRubricHasRejectedIssue(value: unknown): boolean {
  if (!value || typeof value !== "object") {
    return false;
  }
  const responseA = (value as { response_a?: unknown }).response_a;
  if (!responseA || typeof responseA !== "object") {
    return false;
  }
  return Object.values(responseA as Record<string, unknown>).some((decision) => {
    if (!decision || typeof decision !== "object") {
      return false;
    }
    const status = (decision as { status?: unknown }).status;
    return status === "minor_issues" || status === "major_issues";
  });
}

function promptPairReadinessDelta(task: Task): { label: string; detail: string; tone: "good" | "warning" | "danger" | "accent" } | null {
  if (task.task_type !== "gold_voice_edit") {
    return null;
  }
  const payload = task.input_payload;
  const artifactMode = typeof payload.artifact_mode === "string" ? payload.artifact_mode : "";
  const failureModes = payloadStringList(payload.failure_modes);
  const boundarySnapshot = payload.boundary_snapshot && typeof payload.boundary_snapshot === "object"
    ? (payload.boundary_snapshot as Record<string, unknown>)
    : {};
  const sourceBoundaryBlocksTraining = Boolean(payload.source_photo_id) && boundarySnapshot.usable_for_sft === false;
  const hasRejectedReason = failureModes.length > 0 || responseRubricHasRejectedIssue(payload.response_rubric);

  if (artifactMode === "dpo" && !hasRejectedReason) {
    return {
      label: "Likely clears rejected reason",
      detail: "Add rejected-side issue; Dpo Rejected Reason Empty should clear, Adam gold edit remains.",
      tone: "warning"
    };
  }
  if (sourceBoundaryBlocksTraining) {
    return {
      label: "Source boundary blocks training",
      detail: "Review source boundary before this can enter SFT/DPO export.",
      tone: "danger"
    };
  }
  if (payload.candidate_requires_adam_gold_edit === true || payload.truth_status === "model_generated") {
    return {
      label: "Needs Adam gold edit",
      detail: "Opening this ticket can improve the draft, but it remains candidate-only until Adam confirms gold.",
      tone: "accent"
    };
  }
  return {
    label: "Approved-ready signal",
    detail: "No local blocker signal on the queue row; backend preflight still verifies inside the editor.",
    tone: "good"
  };
}

function sourceReviewGenerationDelta(task: Task): { label: string; detail: string; tone: "good" | "warning" | "accent" } | null {
  if (!["text_segment_review", "text_segment_boundary_review", "email_voice_sample"].includes(task.task_type)) {
    return null;
  }
  const chunkingStrategy = payloadString(task.input_payload.chunking_strategy);
  const chunkCount = typeof task.input_payload.chunk_count === "number" ? task.input_payload.chunk_count : null;
  const countLabel = chunkCount === null ? "source text" : `${chunkCount} chunk${chunkCount === 1 ? "" : "s"}`;
  if (chunkingStrategy === "prompt_pair_yaml") {
    return {
      label: "YAML prompt-pair source",
      detail: `${countLabel}; editor dry-run previews singleton tickets before Generate Pairs.`,
      tone: "good"
    };
  }
  if (chunkingStrategy === "natural_section") {
    return {
      label: "Natural-section source",
      detail: `${countLabel}; editor dry-run previews one ticket per complete section.`,
      tone: "good"
    };
  }
  if (chunkCount && chunkCount > 1) {
    return {
      label: "Chunked source review",
      detail: `${countLabel}; editor dry-run shows which chunks become prompt-pair tickets.`,
      tone: "accent"
    };
  }
  return {
    label: "Generate Pairs dry-run available",
    detail: "Open this source to preview ticket count, strategy, spans, and safety before clicking.",
    tone: "warning"
  };
}

function filterLabel(value: string): string {
  if (value === "all") {
    return "All";
  }
  if (value === "true") {
    return "Synthetic";
  }
  if (value === "false") {
    return "Source-derived";
  }
  return queueLabel(value);
}

function payloadString(value: unknown, fallback = ""): string {
  return typeof value === "string" && value.trim() ? value.trim() : fallback;
}

function taskTypeLabel(taskType: string): string {
  const labels: Record<string, string> = {
    text_segment_review: "Source Review",
    text_segment_boundary_review: "Segment Boundary Review",
    boundary_review: "Privacy Review",
    grounded_prompt_pair_candidate: "Prompt Pair Factory",
    gold_voice_edit: "Prompt Pair",
    vision_draft_review: "Vision Draft Review",
    email_voice_sample: "Email Voice Sample",
    photo_context: "Photo Context"
  };
  if (labels[taskType]) {
    return labels[taskType];
  }
  return taskType
    .split("_")
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(" ");
}

function modeLabel(mode: NavMode): string {
  const found = sideNav.find((item) => item.id === mode) ?? topNav.find((item) => item.id === mode);
  return found?.label ?? queueLabel(mode);
}

function isPromptPairTask(task: Task): boolean {
  return (
    task.task_type === "grounded_prompt_pair_candidate" ||
    task.queue.includes("prompt_pair") ||
    task.queue.includes("prompt_pairs") ||
    typeof task.input_payload.source_prompt_pair_task_id === "string"
  );
}

function promptPairValue(task: Task, key: string): string {
  const value = task.input_payload[key];
  return typeof value === "string" && value.trim() ? value.trim() : "";
}

function promptPairQualityStatus(task: Task): string {
  return (
    promptPairValue(task, "quality_status") ||
    promptPairValue(task, "export_status") ||
    (task.input_payload.candidate_requires_adam_gold_edit === true ? "review_candidate" : "")
  );
}

function promptPairSourceKind(task: Task): string {
  const payload = task.input_payload;
  if (typeof payload.source_photo_id === "string") {
    return "photo";
  }
  const sourceTitle = [
    promptPairValue(task, "source_title"),
    promptPairValue(task, "source_filename"),
    promptPairValue(task, "asset_title")
  ]
    .join(" ")
    .toLowerCase();
  if (/\.(yml|yaml)\b/.test(sourceTitle)) {
    return "yaml";
  }
  if (/\.(doc|docx)\b/.test(sourceTitle)) {
    return "word_doc";
  }
  if (/\.(eml|msg|mbox)\b/.test(sourceTitle)) {
    return "email";
  }
  return promptPairValue(task, "source_type") || "other";
}

function photoPairGenerationBatchId(task: Task): string {
  return promptPairValue(task, "photo_pair_generation_batch_id");
}

function photoPairSourceTitle(task: Task): string {
  return (
    promptPairValue(task, "source_title") ||
    promptPairValue(task, "asset_title") ||
    promptPairValue(task, "source_filename") ||
    promptPairValue(task, "source_photo_id") ||
    "Reviewed photo"
  );
}

function taskMatchesPromptPairFilters(task: Task, filters: PromptPairFilters): boolean {
  if (filters.voiceMode !== "all" && promptPairValue(task, "voice_mode") !== filters.voiceMode) {
    return false;
  }
  if (filters.artifactMode !== "all" && promptPairValue(task, "artifact_mode") !== filters.artifactMode) {
    return false;
  }
  if (filters.qualityStatus !== "all" && promptPairQualityStatus(task) !== filters.qualityStatus) {
    return false;
  }
  if (filters.syntheticStatus !== "all" && String(task.input_payload.synthetic === true) !== filters.syntheticStatus) {
    return false;
  }
  if (filters.sourceKind !== "all" && promptPairSourceKind(task) !== filters.sourceKind) {
    return false;
  }
  return true;
}

function uniqueSorted(values: string[]): string[] {
  return Array.from(new Set(values.filter(Boolean))).sort((left, right) => left.localeCompare(right));
}

function promptPairOrdinalLabel(task: Task): string {
  const value = task.input_payload.pair_index ?? task.input_payload.source_prompt_pair_example_index;
  if (typeof value === "string" && value.startsWith("photo-")) {
    const suffix = value.replace("photo-", "");
    return `Photo ${suffix.padStart(3, "0")}`;
  }
  const index = typeof value === "number" ? value : typeof value === "string" ? Number.parseInt(value, 10) : NaN;
  return Number.isFinite(index) && index > 0 ? `Pair ${String(index).padStart(3, "0")}` : "";
}

function taskTitle(task: Task): string {
  const payload = task.input_payload;
  const ordinal = task.task_type === "gold_voice_edit" ? promptPairOrdinalLabel(task) : "";
  const artifactMode = typeof payload.artifact_mode === "string" ? payload.artifact_mode.toUpperCase() : "";
  if (ordinal && typeof payload.prompt === "string" && payload.prompt.trim()) {
    return `${artifactMode ? `${artifactMode} ` : ""}${ordinal}: ${payload.prompt}`;
  }
  for (const key of ["source_filename", "source_title", "asset_title", "title", "segment_title", "prompt"]) {
    const value = payload[key];
    if (typeof value === "string" && value.trim()) {
      return value;
    }
  }
  return task.human_id;
}

function taskSubtitle(task: Task): string {
  const payload = task.input_payload;
  const ordinal = task.task_type === "gold_voice_edit" ? promptPairOrdinalLabel(task) : "";
  const artifactMode = typeof payload.artifact_mode === "string" ? payload.artifact_mode.toUpperCase() : null;
  const sourceTitle = typeof payload.source_title === "string" ? payload.source_title : null;
  const parts = task.task_type === "gold_voice_edit"
    ? [
        ordinal || null,
        artifactMode,
        typeof payload.source_photo_id === "string" ? "Photo grounded" : null,
        typeof payload.photo_pair_variant_label === "string" ? payload.photo_pair_variant_label : null,
        sourceTitle,
        typeof payload.source_prompt_pair_example_index === "number" ? `source example ${payload.source_prompt_pair_example_index}` : null
      ].filter(Boolean)
    : [
    typeof payload.preview_text === "string" ? payload.preview_text.slice(0, 88) : null,
    typeof payload.prompt_intent === "string" ? payload.prompt_intent : null,
    typeof payload.target_response_shape === "string" ? payload.target_response_shape : null,
    typeof payload.source_type === "string" ? payload.source_type : null,
    typeof payload.extraction_parser === "string" ? payload.extraction_parser : null,
    typeof payload.chunk_count === "number" ? `${payload.chunk_count} chunks` : null,
    task.created_by && task.created_by !== "seed" ? task.created_by : null
  ].filter(Boolean);
  return parts.length > 0 ? parts.join(" / ") : task.queue;
}

function taskSortRank(task: Task): number {
  return task.created_by === "seed" ? 1 : 0;
}

function photoPromotionRank(task: Task): number {
  if (task.task_type === "vision_draft_review" && task.input_payload.source_photo_memory_draft === true) {
    return 0;
  }
  if (task.task_type === "photo_context" && typeof task.input_payload.retrieval_gap_origin === "object") {
    return 1;
  }
  if (task.task_type === "photo_context") {
    return 2;
  }
  if (task.task_type === "vision_draft_review") {
    return 3;
  }
  return 99;
}

function photoPriorityBadge(task: Task) {
  const rank = photoPromotionRank(task);
  if (rank === 0) {
    return {
      label: "Fastest vector path",
      tone: "good" as const,
      tooltip: "Machine draft already exists; Adam review can promote it to a reviewed vector-ready memory."
    };
  }
  if (rank === 1) {
    return {
      label: "Retrieval context path",
      tone: "accent" as const,
      tooltip: "This photo-context task came from a retrieval gap and can create reviewed memory after Adam context."
    };
  }
  if (rank === 2) {
    return {
      label: "Context path",
      tone: "info" as const,
      tooltip: "Adam context can create the first reviewed photo-memory record for this image."
    };
  }
  if (rank === 3) {
    return {
      label: "Photo review path",
      tone: "warning" as const,
      tooltip: "A photo review is available, but it may need more context before vector handoff."
    };
  }
  return null;
}

function photoAssetTitle(asset: Asset): string {
  return asset.title || asset.original_filename || asset.human_id;
}

function photoContactGroupKey(asset: Asset): string {
  const stem = photoAssetTitle(asset)
    .replace(/\.[^.\\/]+$/, "")
    .toLowerCase()
    .replace(/\s+-\s+copy(?:\s+-\s+copy)*/g, "")
    .replace(/\s*\(\d+\)\s*/g, " ")
    .replace(/\bcopy\b/g, "")
    .replace(/[^a-z0-9]+/g, " ")
    .replace(/\s+/g, " ")
    .trim();
  return stem || asset.id;
}

function isPhotoCopyVariant(asset: Asset): boolean {
  const title = photoAssetTitle(asset).toLowerCase();
  return title.includes("copy") || /\(\d+\)/.test(title);
}

function canonicalPhotoAsset(assets: Asset[]): Asset {
  return [...assets].sort((left, right) => {
    const leftCopy = isPhotoCopyVariant(left) ? 1 : 0;
    const rightCopy = isPhotoCopyVariant(right) ? 1 : 0;
    return leftCopy - rightCopy || photoAssetTitle(left).length - photoAssetTitle(right).length || photoAssetTitle(left).localeCompare(photoAssetTitle(right));
  })[0];
}

function photoPromotionDryRun(task?: Task | null): PhotoPromotionDryRun | null {
  if (!task) {
    return null;
  }
  const badge = photoPriorityBadge(task);
  if (!badge) {
    return null;
  }
  const rank = photoPromotionRank(task);
  const retrievalOrigin = task.input_payload.retrieval_gap_origin;
  const retrievalQuery =
    retrievalOrigin && typeof retrievalOrigin === "object" && "query" in retrievalOrigin
      ? payloadString((retrievalOrigin as Record<string, unknown>).query)
      : "";

  if (rank === 0) {
    return {
      pathLabel: badge.label,
      taskLabel: taskTitle(task),
      whyFirst: "A machine draft already supplies visible-image scaffolding, so Adam can focus on corrections, meaning, and boundaries.",
      projectedOutcome: "Held until Adam adds context and sets downstream clearance; then eligible for reviewed photo memory and vector handoff.",
      submitOutcomeBadge: "On submit: vector-safe memory",
      submitOutcomeLabel: "Creates vector-safe memory after Adam review",
      submitOutcomeDetail: "Completing Adam context, downstream clearance, and boundary review can promote the draft into reviewed-only memory/vector handoff.",
      vectorHandoffPreviewStatus: "held_until_adam_context",
      missingFields: [
        "Adam context or answers",
        "Downstream choice: set Yes for retrieval",
        "Boundary review for family/public use"
      ],
      safeguards: ["No memory claim yet", "No vector write before submit", "Not SFT/DPO training material"]
    };
  }

  if (rank === 1) {
    return {
      pathLabel: badge.label,
      taskLabel: taskTitle(task),
      whyFirst: retrievalQuery
        ? `This was created from the retrieval gap “${retrievalQuery},” so completing it directly improves future recall.`
        : "This was created from a retrieval gap, so completing it directly improves future recall.",
      projectedOutcome: "Adam-authored context can create reviewed memory text, boundary settings, and embedding-ready handoff records.",
      submitOutcomeBadge: "On submit: closes retrieval gap",
      submitOutcomeLabel: "Creates reviewed context for this retrieval gap",
      submitOutcomeDetail: "Adam-authored answers can become searchable memory text and embedding-ready handoff records without making a training example.",
      vectorHandoffPreviewStatus: "eligible_after_required_context",
      missingFields: [
        "Reviewed visual description",
        "Adam context or answers",
        "Downstream choice: set Yes for retrieval",
        "Boundary review for family/public use"
      ],
      safeguards: ["No memory claim yet", "Filename/title evidence only until reviewed", "Not SFT/DPO training material"]
    };
  }

  return {
    pathLabel: badge.label,
    taskLabel: taskTitle(task),
    whyFirst: "This task can add missing photo context and boundaries, but it may need more Adam-authored detail before retrieval use.",
    projectedOutcome: "Likely held as photo context until reviewed memory text and downstream clearance are present.",
    submitOutcomeBadge: "On submit: context hold",
    submitOutcomeLabel: "Saves photo context until memory is complete",
    submitOutcomeDetail: "The review creates durable context, then waits for Adam-authored memory detail and downstream clearance before vector handoff.",
    vectorHandoffPreviewStatus: "held_until_required_context",
    missingFields: ["Reviewed visual description", "Adam context or answers", "Downstream choice: set Yes for retrieval"],
    safeguards: ["No memory claim yet", "No vector write before submit", "Not SFT/DPO training material"]
  };
}

function photoPromotionDryRunFromPriorityItem(item?: PhotoReviewPriorityItem | null): PhotoPromotionDryRun | null {
  if (!item) {
    return null;
  }
  return {
    pathLabel: item.path_label,
    taskLabel: item.source_photo_title || item.task_human_id,
    whyFirst: item.why_first,
    projectedOutcome: item.projected_outcome,
    submitOutcomeBadge: item.submit_outcome_badge || "On submit: context review",
    submitOutcomeLabel: item.submit_outcome_label || item.projected_outcome,
    submitOutcomeDetail: item.submit_outcome_detail || "Submit stores durable review context without making a training example.",
    vectorHandoffPreviewStatus: item.vector_handoff_preview_status || "unknown",
    missingFields: item.missing_fields,
    safeguards: item.safeguards
  };
}

function photoPriorityItemForTask(summary: PhotoReviewPrioritySummary | null, task: Task): PhotoReviewPriorityItem | null {
  return summary?.items.find((item) => item.task_id === task.id) ?? null;
}

function photoSubmitOutcomeBadge(priorityItem?: PhotoReviewPriorityItem | null) {
  if (!priorityItem?.submit_outcome_badge) {
    return null;
  }
  return {
    label: priorityItem.submit_outcome_badge,
    tone: priorityItem.vector_handoff_preview_status?.includes("eligible") ? "good" as const : "accent" as const,
    tooltip: priorityItem.submit_outcome_detail || priorityItem.projected_outcome
  };
}

function photoRowReadinessDelta(
  task: Task,
  priorityItem?: PhotoReviewPriorityItem | null
): { label: string; detail: string; tone: "good" | "warning" | "danger" | "accent" | "info" } | null {
  const dryRun = photoPromotionDryRunFromPriorityItem(priorityItem) ?? photoPromotionDryRun(task);
  if (!dryRun) {
    return null;
  }
  const nextField = dryRun.missingFields[0] || "Ready for submit projection";
  const tone = dryRun.vectorHandoffPreviewStatus.includes("eligible")
    ? "good"
    : dryRun.pathLabel === "Fastest vector path"
      ? "accent"
      : dryRun.pathLabel === "Retrieval context path"
        ? "warning"
        : "info";
  return {
    label: dryRun.pathLabel,
    detail: `Next: ${nextField}. ${dryRun.submitOutcomeBadge}.`,
    tone
  };
}

function taskMatchesPhotoFocus(task: Task, focus: PhotoTaskFocus): boolean {
  if (focus === "all") {
    return true;
  }
  return photoPromotionRank(task) < 3;
}

function sourceType(task: Task): string {
  const payload = task.input_payload;
  if (typeof payload.source_type === "string") {
    return payload.source_type;
  }
  if (typeof payload.asset_type === "string") {
    return payload.asset_type;
  }
  if (typeof payload.drive_candidate_kind === "string") {
    return payload.drive_candidate_kind;
  }
  return "";
}

function sourceFilename(task: Task): string {
  const payload = task.input_payload;
  for (const key of ["source_filename", "drive_name", "title", "asset_title"]) {
    const value = payload[key];
    if (typeof value === "string" && value.trim()) {
      return value.toLowerCase();
    }
  }
  return "";
}

function taskMatchesCollection(task: Task, collection: CollectionId): boolean {
  if (collection === "all") {
    return true;
  }

  const type = sourceType(task);
  const filename = sourceFilename(task);
  const mimeType = typeof task.input_payload.mime_type === "string" ? task.input_payload.mime_type : "";
  const needsBoundary =
    task.task_type === "boundary_review" ||
    task.task_type === "text_segment_boundary_review" ||
    task.queue.includes("boundary") ||
    task.queue.includes("privacy") ||
    ["needs_redaction", "review_before_export", "do_not_export"].includes(
      typeof task.input_payload.privacy_clearance === "string" ? task.input_payload.privacy_clearance : ""
    ) ||
    ["needs_redaction", "review_before_export", "do_not_export"].includes(
      typeof task.input_payload.boundary_clearance_needed === "string" ? task.input_payload.boundary_clearance_needed : ""
    );
  switch (collection) {
    case "photos":
      return (
        task.task_type === "photo_context" ||
        task.task_type === "vision_draft_review" ||
        typeof task.input_payload.source_photo_id === "string" ||
        ["photo", "image", "scan"].includes(type) ||
        mimeType.startsWith("image/") ||
        /\.(jpg|jpeg|png|gif|webp|heic|tif|tiff)$/i.test(filename)
      );
    case "text":
      return (
        !isPromptPairTask(task) &&
        !["photo", "image"].includes(type) &&
        (["text_segment_review", "text_segment_boundary_review", "email_voice_sample"].includes(task.task_type) ||
          ["document", "text", "pdf", "scan", "journal", "email"].includes(type) ||
          /\.(doc|docx|txt|rtf|pdf|yml|yaml|eml|msg|mbox)$/i.test(filename))
      );
    case "gold":
      return task.task_type === "gold_voice_edit";
    case "needs_boundary":
      return needsBoundary;
    default:
      return true;
  }
}

function taskMatchesMode(task: Task, mode: NavMode): boolean {
  switch (mode) {
    case "intake":
      return task.task_type === "asset_triage";
    case "review":
      return (
        [
          "text_segment_review",
          "text_segment_boundary_review",
          "boundary_review",
          "email_voice_sample",
          "photo_context",
          "vision_draft_review"
        ].includes(task.task_type) ||
        task.queue.includes("boundary") ||
        task.queue.includes("privacy")
      );
    case "make_gold":
      return task.task_type === "gold_voice_edit";
    case "exports":
      return task.task_type.includes("export") || task.queue.includes("export");
    default:
      return true;
  }
}

function modeUsesCollectionFilter(mode: NavMode): boolean {
  return mode !== "exports";
}

function defaultCollectionForMode(mode: NavMode): CollectionId {
  return "all";
}

function tooltip(text: string): { title: string } {
  return { title: text };
}

function nextModeFromQueue(queue?: string | null): NavMode | null {
  if (!queue) {
    return null;
  }
  if (queue.includes("dataset") || queue.includes("export")) {
    return "exports";
  }
  if (queue.includes("prompt") || queue.includes("gold")) {
    return "make_gold";
  }
  if (queue.includes("vision") || queue.includes("boundary") || queue.includes("source") || queue.includes("text")) {
    return "review";
  }
  return null;
}

function formatRelativeTime(value: string): string {
  const timestamp = new Date(value).getTime();
  if (!Number.isFinite(timestamp)) {
    return "";
  }
  const minutes = Math.max(1, Math.round((Date.now() - timestamp) / 60000));
  if (minutes < 60) {
    return `${minutes}m ago`;
  }
  const hours = Math.round(minutes / 60);
  if (hours < 48) {
    return `${hours}h ago`;
  }
  return `${Math.round(hours / 24)}d ago`;
}

function annotationReceipt(annotation: Pick<Annotation, "creates_or_updates"> | null) {
  const receipt = annotation?.creates_or_updates?.receipt;
  return receipt && typeof receipt === "object" ? (receipt as Record<string, unknown>) : null;
}

function receiptString(receipt: Record<string, unknown> | null, key: string): string {
  const value = receipt?.[key];
  return typeof value === "string" ? value : "";
}

function receiptList(receipt: Record<string, unknown> | null, key: string): string[] {
  const value = receipt?.[key];
  return Array.isArray(value) ? value.map(String).filter(Boolean) : [];
}

function receiptOutcomes(receipt: Record<string, unknown> | null): { label: string; id: string }[] {
  const value = receipt?.outcomes;
  if (!Array.isArray(value)) {
    return [];
  }
  return value.flatMap((item) => {
    if (!item || typeof item !== "object") {
      return [];
    }
    const record = item as Record<string, unknown>;
    const label = typeof record.label === "string" ? record.label : "";
    const id = typeof record.id === "string" ? record.id : "";
    return label ? [{ label, id }] : [];
  });
}

function receiptExportArtifact(receipt: Record<string, unknown> | null): Record<string, unknown> | null {
  const value = receipt?.export_artifact;
  return value && typeof value === "object" ? (value as Record<string, unknown>) : null;
}

function receiptPairGenerationRun(receipt: Record<string, unknown> | null): Record<string, unknown> | null {
  const value = receipt?.pair_generation_run;
  return value && typeof value === "object" ? (value as Record<string, unknown>) : null;
}

function receiptSubmitProjection(receipt: Record<string, unknown> | null): Record<string, unknown> | null {
  const value = receipt?.submit_projection;
  return value && typeof value === "object" ? (value as Record<string, unknown>) : null;
}

function receiptNumber(record: Record<string, unknown> | null, key: string): number {
  const value = record?.[key];
  return typeof value === "number" && Number.isFinite(value) ? value : 0;
}

function receiptBoolean(record: Record<string, unknown> | null, key: string): boolean {
  return record?.[key] === true;
}

function receiptRecord(record: Record<string, unknown> | null, key: string): Record<string, unknown> {
  const value = record?.[key];
  return value && typeof value === "object" && !Array.isArray(value) ? (value as Record<string, unknown>) : {};
}

function annotationOutputString(annotation: Annotation | null, key: string): string {
  const value = annotation?.creates_or_updates?.[key];
  return typeof value === "string" ? value : "";
}

function annotationPhotoPromptPairBatch(annotation: Annotation | null): PhotoPromptPairCandidateResponse | null {
  const value = annotation?.creates_or_updates?.photo_prompt_pair_generation;
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return null;
  }
  const record = value as Partial<PhotoPromptPairCandidateResponse>;
  return Array.isArray(record.candidates) ? (record as PhotoPromptPairCandidateResponse) : null;
}

function submittedPhotoAssetId(annotation: Annotation | null): string {
  if (!annotation) {
    return "";
  }
  return annotation.target_type === "asset" && typeof annotation.target_id === "string"
    ? annotation.target_id
    : annotationOutputString(annotation, "source_photo_id");
}

function isPhotoSubmitAnnotation(annotation: Annotation | null): boolean {
  if (!annotation) {
    return false;
  }
  return (
    annotation.annotation_type === "photo_context" ||
    annotation.annotation_type === "vision_draft_review" ||
    Boolean(submittedPhotoAssetId(annotation)) ||
    Boolean(annotationOutputString(annotation, "metadata_profile_id")) ||
    Boolean(annotationOutputString(annotation, "memory_embedding_record_id")) ||
    Boolean(annotationOutputString(annotation, "vector_handoff_record_id"))
  );
}

function exportArtifactModes(exportArtifact: Record<string, unknown> | null): string[] {
  const value = exportArtifact?.artifact_modes;
  return Array.isArray(value) ? value.map(String).filter(Boolean) : [];
}

function exportArtifactStatuses(exportArtifact: Record<string, unknown> | null): string {
  const statuses = exportArtifact?.statuses;
  if (!statuses || typeof statuses !== "object") {
    return "";
  }
  return Object.entries(statuses as Record<string, unknown>)
    .map(([mode, status]) => `${mode.toUpperCase()}: ${queueLabel(String(status))}`)
    .join(" / ");
}

function SubmitReceiptBanner({ annotation }: { annotation: Annotation | null }) {
  const receipt = annotationReceipt(annotation);
  if (!receipt) {
    return null;
  }
  const outcomes = receiptOutcomes(receipt);
  const exportArtifact = receiptExportArtifact(receipt);
  const pairGenerationRun = receiptPairGenerationRun(receipt);
  const submitProjection = receiptSubmitProjection(receipt);
  const reviewSessionOrigin = receiptRecord(receipt, "review_session_origin");
  const hasReviewSessionOrigin = Object.keys(reviewSessionOrigin).length > 0;
  const artifactModes = exportArtifactModes(exportArtifact);
  const artifactStatuses = exportArtifactStatuses(exportArtifact);
  const artifactBlockers = receiptList(exportArtifact, "review_blockers");
  const exportReady = exportArtifact?.export_ready === true;
  const blockedReasons = receiptList(receipt, "blocked_reasons");
  const nextAction = receiptString(receipt, "next_action_label");
  const downstreamStatus = receiptString(receipt, "downstream_status") || "recorded";
  const boundaryStatus = receiptString(receipt, "boundary_status") || "unknown";
  const vectorStatus = receiptString(receipt, "vector_handoff_status");
  const vectorReason = receiptString(receipt, "vector_handoff_reason");
  const vectorRecordId = receiptString(receipt, "vector_handoff_record_id");
  const assetDossierHref =
    annotation?.target_type === "asset" && typeof annotation.target_id === "string" && annotation.target_id
      ? `/assets/${annotation.target_id}`
      : "";
  const submitProjectionHash = receiptString(submitProjection, "content_sha256");
  const submitProjectionReadiness = receiptString(submitProjection, "submit_readiness");
  const submitProjectionVector = receiptString(submitProjection, "vector_handoff_status");
  const noLiveEmbeddingCall = receiptBoolean(submitProjection, "no_live_embedding_call");
  const ordinaryDbVectorStorage = receiptBoolean(submitProjection, "ordinary_db_vector_storage");
  const reviewSessionPlanHash = receiptString(reviewSessionOrigin, "plan_content_sha256");
  const reviewSessionQuery = receiptString(reviewSessionOrigin, "source_query");
  const reviewSessionSequence = receiptNumber(reviewSessionOrigin, "sequence_number") || receiptString(reviewSessionOrigin, "sequence_number") || "?";
  const reviewSessionSelectedCount = receiptNumber(reviewSessionOrigin, "selected_count") || receiptString(reviewSessionOrigin, "selected_count") || "?";
  const pairStrategyCounts = receiptRecord(pairGenerationRun, "strategy_counts");
  const pairStrategySummary = Object.entries(pairStrategyCounts)
    .map(([strategy, count]) => `${queueLabel(strategy)}: ${String(count)}`)
    .join(" / ");

  return (
    <section className="submit-receipt-banner" aria-label="Last submit receipt">
      <div className="receipt-main">
        <span>Submitted</span>
        <strong>{nextAction || "Durable annotations were recorded"}</strong>
        <p>
          Boundary: {queueLabel(boundaryStatus)} / Downstream: {queueLabel(downstreamStatus)}
          {vectorStatus ? ` / Vector: ${queueLabel(vectorStatus)}` : ""}
        </p>
        {vectorReason ? <p>{vectorReason}</p> : null}
      </div>
      {outcomes.length > 0 ? (
        <div className="receipt-outcomes" aria-label="Created or updated records">
          {outcomes.slice(0, 8).map((outcome) => (
            <span key={`${outcome.label}-${outcome.id}`}>
              {outcome.label}
              {outcome.id ? <em>{outcome.id.slice(0, 8)}</em> : null}
            </span>
          ))}
        </div>
      ) : null}
      {exportArtifact ? (
        <div className="receipt-export-artifact" data-ready={exportReady ? "true" : "false"} aria-label="Training export receipt">
          <span>{artifactModes.length ? artifactModes.map((mode) => mode.toUpperCase()).join(" + ") : "Gold voice"}</span>
          <strong>{artifactStatuses || (exportReady ? "Export Ready" : "Recorded")}</strong>
          {artifactBlockers.length > 0 ? <em>{artifactBlockers.join(", ")}</em> : <em>{exportReady ? "Ready for approved export" : "Held for review"}</em>}
        </div>
      ) : null}
      {pairGenerationRun ? (
        <div className="receipt-pair-generation" aria-label="Pair generation receipt">
          <span>Pair generation run</span>
          <strong>
            {receiptNumber(pairGenerationRun, "created_pair_count")} created / {receiptNumber(pairGenerationRun, "held_pair_count")} held
          </strong>
          <em>
            {pairStrategySummary || "No strategy counts"} / {receiptNumber(pairGenerationRun, "source_section_count")} source section(s) considered
          </em>
        </div>
      ) : null}
      {vectorStatus || submitProjectionVector ? (
        <div className="receipt-vector-handoff" data-status={vectorStatus || submitProjectionVector} aria-label="Vector handoff receipt">
          <span>Vector handoff</span>
          <strong>{queueLabel(vectorStatus || submitProjectionVector || "recorded")}</strong>
          <em>
            {vectorRecordId ? `Record ${vectorRecordId.slice(0, 8)}` : "Reviewed-only handoff preview"}
            {noLiveEmbeddingCall ? " / no live embedding call" : ""}
            {ordinaryDbVectorStorage ? " / ordinary DB vector storage" : ""}
          </em>
          {vectorReason ? <p>{vectorReason}</p> : null}
          {assetDossierHref ? (
            <a href={assetDossierHref} className="receipt-dossier-link">
              Open asset dossier
            </a>
          ) : null}
        </div>
      ) : null}
      {hasReviewSessionOrigin ? (
        <div className="receipt-review-session" aria-label="Review session completion receipt">
          <span>Review session item</span>
          <strong>
            Item {reviewSessionSequence} / {reviewSessionSelectedCount}
          </strong>
          <em>
            {reviewSessionQuery ? `Query: ${reviewSessionQuery}` : "Photo-context session queue"}
            {reviewSessionPlanHash ? ` / plan ${reviewSessionPlanHash.slice(0, 8)}` : ""}
          </em>
          <p>No-claim gap moved toward vector-safe memory readiness.</p>
        </div>
      ) : null}
      {submitProjection ? (
        <details className="receipt-submit-projection" aria-label="Photo context submit projection receipt">
          <summary>
            <span>Photo context submit projection</span>
            <strong>{submitProjectionReadiness ? queueLabel(submitProjectionReadiness) : "Recorded"}</strong>
          </summary>
          <p>
            Hash: <code>{submitProjectionHash ? submitProjectionHash.slice(0, 16) : "missing"}</code>
            {submitProjectionVector ? ` / Vector: ${queueLabel(submitProjectionVector)}` : ""}
          </p>
          {typeof submitProjection.export_preview_yaml === "string" ? (
            <pre>{submitProjection.export_preview_yaml}</pre>
          ) : null}
        </details>
      ) : null}
      {blockedReasons.length > 0 ? (
        <div className="receipt-blockers">
          {blockedReasons.map((reason) => (
            <span key={reason}>{reason}</span>
          ))}
        </div>
      ) : null}
    </section>
  );
}

function SubmittedResultPanel({
  annotation,
  photoPairStatus,
  photoPairBatch,
  onViewExports,
  onCreatePhotoPromptPair,
  onOpenPhotoPromptPair
}: {
  annotation: Annotation | null;
  photoPairStatus?: string | null;
  photoPairBatch?: PhotoPromptPairCandidateResponse | null;
  onViewExports: () => void;
  onCreatePhotoPromptPair: () => void | Promise<void>;
  onOpenPhotoPromptPair: (taskId: string) => void;
}) {
  const receipt = annotationReceipt(annotation);
  if (!receipt) {
    return null;
  }
  const isPhoto = isPhotoSubmitAnnotation(annotation);
  const assetId = submittedPhotoAssetId(annotation);
  const outputs = [
    ["Metadata profile", annotationOutputString(annotation, "metadata_profile_id")],
    ["Boundary", annotationOutputString(annotation, "boundary_id")],
    ["Memory", annotationOutputString(annotation, "memory_id")],
    ["Graph link", annotationOutputString(annotation, "graph_edge_id")],
    ["Gallery item", annotationOutputString(annotation, "gallery_item_id")],
    ["Profile embedding", annotationOutputString(annotation, "embedding_record_id")],
    ["Memory embedding", annotationOutputString(annotation, "memory_embedding_record_id") || receiptString(receipt, "vector_handoff_record_id")]
  ].filter(([, value]) => value);
  const vectorStatus = receiptString(receipt, "vector_handoff_status");
  const vectorReason = receiptString(receipt, "vector_handoff_reason");
  const nextAction = receiptString(receipt, "next_action_label") || "Pick the next ready task";
  const receiptPhotoPairBatch = annotationPhotoPromptPairBatch(annotation);
  const effectivePhotoPairBatch = photoPairBatch ?? receiptPhotoPairBatch;
  const photoPairBatchId = effectivePhotoPairBatch?.generation_batch_id || effectivePhotoPairBatch?.generation_batch_ids?.[0] || "";
  const photoPairButtonLabel = effectivePhotoPairBatch ? "Open/recheck 5 prompt-pair candidates" : "Create 5 prompt-pair candidates";

  return (
    <section className="submitted-result-panel" aria-label="Submitted result landing">
      <header>
        <div>
          <span>Where it went</span>
          <strong>This task is now submitted, so it left the ready queue.</strong>
          <p>
            The review was saved as durable records. You can inspect the IDs here, open the source dossier, or move into Exports to see
            aggregate downstream readiness.
          </p>
        </div>
        <button type="button" onClick={onViewExports}>
          View Exports
        </button>
      </header>
      {outputs.length > 0 ? (
        <div className="submitted-output-grid" aria-label="Submitted output records">
          {outputs.map(([label, value]) => (
            <span key={label}>
              <em>{label}</em>
              <strong>{String(value).slice(0, 12)}</strong>
            </span>
          ))}
        </div>
      ) : null}
      {isPhoto ? (
        <div className="submitted-next-step" aria-label="Photo submit next steps">
          <div>
            <span>Photo path</span>
            <strong>{vectorStatus ? `Vector: ${queueLabel(vectorStatus)}` : nextAction}</strong>
            <p>
              {effectivePhotoPairBatch
                ? "Photo review produced retrieval, gallery, memory, embedding context, and five review-gated prompt-pair candidates. The candidates are not training truth until Adam edits and approves them."
                : "Photo review produces retrieval, gallery, memory, and embedding-ready context first. You can create review-gated prompt-pair candidates from that source material when ready."}
            </p>
            {vectorReason ? <p>{vectorReason}</p> : null}
            {photoPairStatus ? <em>{photoPairStatus}</em> : null}
          </div>
          <div className="submitted-next-actions">
            {assetId ? (
              <a href={`/assets/${assetId}`}>
                Open asset dossier
              </a>
            ) : null}
            <button type="button" onClick={() => void onCreatePhotoPromptPair()}>
              {photoPairButtonLabel}
            </button>
          </div>
          {effectivePhotoPairBatch && effectivePhotoPairBatch.candidates.length > 0 ? (
            <div className="photo-pair-handoff-list" aria-label="Photo prompt-pair candidate handoff">
              <span>
                {effectivePhotoPairBatch.created_task_ids.length > 0 ? "Created" : "Opened"} {effectivePhotoPairBatch.candidates.length} candidate
                {effectivePhotoPairBatch.candidates.length === 1 ? "" : "s"}
              </span>
              {photoPairBatchId ? <code>{photoPairBatchId}</code> : null}
              {effectivePhotoPairBatch.candidates.slice(0, 5).map((candidate, index) => {
                const taskId = candidate.created_task_id || candidate.existing_task_id || "";
                return (
                  <button
                    type="button"
                    key={`${candidate.metadata_profile_id}-${candidate.variant_key ?? index}`}
                    onClick={() => taskId && onOpenPhotoPromptPair(taskId)}
                    disabled={!taskId}
                  >
                    <em>{candidate.variant_label || `Candidate ${index + 1}`}</em>
                    <strong>{candidate.prompt}</strong>
                  </button>
                );
              })}
            </div>
          ) : null}
        </div>
      ) : null}
    </section>
  );
}

export default function Home() {
  const [assets, setAssets] = useState<Asset[]>([]);
  const [tasks, setTasks] = useState<Task[]>([]);
  const [memories, setMemories] = useState<Memory[]>([]);
  const [goldExamples, setGoldExamples] = useState<GoldVoiceExample[]>([]);
  const [photoPrioritySummary, setPhotoPrioritySummary] = useState<PhotoReviewPrioritySummary | null>(null);
  const [photoContextProgress, setPhotoContextProgress] = useState<PhotoContextSessionProgress | null>(null);
  const [promptPairAudit, setPromptPairAudit] = useState<PromptPairAudit | null>(null);
  const [promptPairProgress, setPromptPairProgress] = useState<PromptPairReviewProgress | null>(null);
  const [dpoRepairPacket, setDpoRepairPacket] = useState<DpoRejectedReasonRepairPacket | null>(null);
  const [shellWidths, setShellWidths] = useState<Record<ShellColumn, number>>({ sidebar: 212, queue: 326 });
  const [selectedMode, setSelectedMode] = useState<NavMode>("review");
  const [selectedCollection, setSelectedCollection] = useState<CollectionId>("all");
  const [promptPairFilters, setPromptPairFilters] = useState<PromptPairFilters>(defaultPromptPairFilters);
  const [photoTaskFocus, setPhotoTaskFocus] = useState<PhotoTaskFocus>(defaultPhotoTaskFocus);
  const [queueSearch, setQueueSearch] = useState("");
  const [selectedTaskId, setSelectedTaskId] = useState<string | null>(null);
  const [completedThisSession, setCompletedThisSession] = useState(0);
  const [lastSubmitAnnotation, setLastSubmitAnnotation] = useState<Annotation | null>(null);
  const [photoPairStatus, setPhotoPairStatus] = useState<string | null>(null);
  const [photoPairBatch, setPhotoPairBatch] = useState<PhotoPromptPairCandidateResponse | null>(null);
  const [activePhotoPairBatchId, setActivePhotoPairBatchId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [visionBatchBusy, setVisionBatchBusy] = useState(false);
  const workbenchColumnRef = useRef<HTMLElement | null>(null);

  async function load() {
    setLoading(true);
    setError(null);
    try {
      const [
        assetData,
        taskData,
        memoryData,
        goldData,
        photoPriorityData,
        photoContextProgressData,
        promptPairAuditData,
        promptPairProgressData,
        dpoRepairPacketData
      ] = await Promise.all([
        getAssets(),
        getTasks(),
        getMemories(),
        getGoldVoiceExamples(),
        getPhotoReviewPriority("fastest_vector", 50),
        getPhotoContextSessionProgress("family_private", 100),
        getPromptPairAudit(1),
        getPromptPairReviewProgress(),
        getDpoRejectedReasonRepairPacket(25)
      ]);
      setAssets(assetData);
      setTasks(taskData);
      setMemories(memoryData);
      setGoldExamples(goldData);
      setPhotoPrioritySummary(photoPriorityData);
      setPhotoContextProgress(photoContextProgressData);
      setPromptPairAudit(promptPairAuditData);
      setPromptPairProgress(promptPairProgressData);
      setDpoRepairPacket(dpoRepairPacketData);
      const readyTasks = taskData.filter((task) => task.status === "ready");
      if (!selectedTaskId || !readyTasks.some((task) => task.id === selectedTaskId)) {
        setSelectedTaskId(readyTasks[0]?.id ?? null);
      }
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Unable to load CharlesOps data.");
    } finally {
      setLoading(false);
    }
  }

  async function handleArtifactUploaded(upload?: AssetUploadResponse) {
    await load();
    const reviewTaskId = upload?.review_task_ids[0];
    if (!reviewTaskId) {
      return;
    }
    setSelectedTaskId(reviewTaskId);
    setSelectedCollection("all");
    setActivePhotoPairBatchId(null);
    setQueueSearch("");
    setSelectedMode(upload.segment_ids.length > 0 ? "review" : "intake");
  }

  useEffect(() => {
    void load();
  }, []);

  const readyTasks = useMemo(
    () =>
      [...tasks.filter((task) => task.status === "ready")].sort(
        (left, right) =>
          taskSortRank(left) - taskSortRank(right) ||
          right.priority - left.priority ||
          new Date(right.created_at).getTime() - new Date(left.created_at).getTime()
      ),
    [tasks]
  );
  const modeTasks = useMemo(
    () => readyTasks.filter((task) => taskMatchesMode(task, selectedMode)),
    [readyTasks, selectedMode]
  );
  const filteredTasks = useMemo(
    () => {
      const collectionFiltered = modeUsesCollectionFilter(selectedMode)
        ? modeTasks.filter((task) => taskMatchesCollection(task, selectedCollection))
        : modeTasks;
      const promptPairFiltered = selectedMode === "make_gold"
        ? collectionFiltered.filter((task) => taskMatchesPromptPairFilters(task, promptPairFilters))
        : collectionFiltered;
      const photoBatchFiltered =
        selectedMode === "make_gold" && activePhotoPairBatchId
          ? promptPairFiltered.filter((task) => photoPairGenerationBatchId(task) === activePhotoPairBatchId)
          : promptPairFiltered;
      const photoFocused =
        selectedMode === "review" && selectedCollection === "photos" && photoTaskFocus !== "all"
          ? [...photoBatchFiltered.filter((task) => taskMatchesPhotoFocus(task, photoTaskFocus))].sort(
              (left, right) =>
                photoPromotionRank(left) - photoPromotionRank(right) ||
                right.priority - left.priority ||
                new Date(right.created_at).getTime() - new Date(left.created_at).getTime()
            )
          : photoBatchFiltered;
      const searchTerm = queueSearch.trim().toLowerCase();
      if (!searchTerm) {
        return photoFocused;
      }
      return photoFocused.filter((task) => {
        const haystack = [
          task.human_id,
          task.task_type,
          task.queue,
          taskTitle(task),
          taskSubtitle(task),
          promptPairOrdinalLabel(task),
          payloadString(task.input_payload.prompt),
          payloadString(task.input_payload.content),
          payloadString(task.input_payload.chosen),
          payloadString(task.input_payload.rejected),
          payloadString(task.input_payload.source_title),
          payloadString(task.input_payload.source_filename),
          payloadString(task.input_payload.voice_mode),
          payloadString(task.input_payload.photo_pair_generation_batch_id),
          promptPairSourceKind(task)
        ]
          .join(" ")
          .toLowerCase();
        return haystack.includes(searchTerm);
      });
    },
    [activePhotoPairBatchId, modeTasks, photoTaskFocus, promptPairFilters, queueSearch, selectedCollection, selectedMode]
  );
  const nextPhotoPromotionDryRun = useMemo(
    () => {
      if (selectedMode !== "review" || selectedCollection !== "photos" || photoTaskFocus !== "fastest_vector") {
        return null;
      }
      const firstTask = filteredTasks[0];
      const priorityItem = firstTask ? photoPriorityItemForTask(photoPrioritySummary, firstTask) : null;
      return photoPromotionDryRunFromPriorityItem(priorityItem) ?? photoPromotionDryRun(firstTask);
    },
    [filteredTasks, photoPrioritySummary, photoTaskFocus, selectedCollection, selectedMode]
  );
  const topPhotoContextMissingField = useMemo(() => {
    const entries = Object.entries(photoContextProgress?.retrieval_gap_missing_field_counts ?? {});
    return entries.sort((left, right) => Number(right[1]) - Number(left[1]) || left[0].localeCompare(right[0]))[0] ?? null;
  }, [photoContextProgress]);
  const selectedTask = useMemo(() => {
    if (selectedTaskId) {
      const explicit = filteredTasks.find((task) => task.id === selectedTaskId);
      if (explicit) {
        return explicit;
      }
    }
    return filteredTasks[0] ?? null;
  }, [filteredTasks, selectedTaskId]);
  const collectionCounts = useMemo(
    () =>
      Object.fromEntries(
        collectionDefs.map((collection) => [
          collection.id,
          collection.id === "all" ? readyTasks.length : readyTasks.filter((task) => taskMatchesCollection(task, collection.id)).length
        ])
      ) as Record<CollectionId, number>,
    [readyTasks]
  );
  const modeCounts = useMemo(
    () =>
      Object.fromEntries(
        sideNav.map((item) => [item.id, readyTasks.filter((task) => taskMatchesMode(task, item.id)).length])
      ) as Record<NavMode, number>,
    [readyTasks]
  );
  const showCollectionFilters = modeUsesCollectionFilter(selectedMode);
  const promptPairBaseTasks = useMemo(
    () =>
      selectedMode === "make_gold"
        ? modeTasks.filter((task) => taskMatchesCollection(task, selectedCollection))
        : [],
    [modeTasks, selectedCollection, selectedMode]
  );
  const promptPairFilterOptions = useMemo(
    () => ({
      voiceMode: uniqueSorted(promptPairBaseTasks.map((task) => promptPairValue(task, "voice_mode"))),
      artifactMode: uniqueSorted(promptPairBaseTasks.map((task) => promptPairValue(task, "artifact_mode"))),
      qualityStatus: uniqueSorted(promptPairBaseTasks.map(promptPairQualityStatus)),
      syntheticStatus: uniqueSorted(promptPairBaseTasks.map((task) => String(task.input_payload.synthetic === true))),
      sourceKind: uniqueSorted(promptPairBaseTasks.map(promptPairSourceKind))
    }),
    [promptPairBaseTasks]
  );
  const promptPairBatchGroups = useMemo(() => {
    const groups = new Map<string, PhotoPromptPairBatchGroup>();
    for (const task of promptPairBaseTasks) {
      if (!taskMatchesPromptPairFilters(task, promptPairFilters)) {
        continue;
      }
      const batchId = photoPairGenerationBatchId(task);
      if (!batchId) {
        continue;
      }
      const existing = groups.get(batchId);
      const variantLabel = promptPairValue(task, "photo_pair_variant_label");
      if (existing) {
        existing.count += 1;
        existing.updatedAt =
          new Date(task.updated_at).getTime() > new Date(existing.updatedAt).getTime() ? task.updated_at : existing.updatedAt;
        if (variantLabel && !existing.variantLabels.includes(variantLabel)) {
          existing.variantLabels.push(variantLabel);
        }
        continue;
      }
      groups.set(batchId, {
        batchId,
        sourceTitle: photoPairSourceTitle(task),
        sourcePhotoId: promptPairValue(task, "source_photo_id"),
        count: 1,
        firstTaskId: task.id,
        firstPrompt: promptPairValue(task, "prompt"),
        variantLabels: variantLabel ? [variantLabel] : [],
        updatedAt: task.updated_at
      });
    }
    return Array.from(groups.values()).sort((left, right) => new Date(right.updatedAt).getTime() - new Date(left.updatedAt).getTime());
  }, [promptPairBaseTasks, promptPairFilters]);
  const activePromptPairFilterCount =
    Object.values(promptPairFilters).filter((value) => value !== "all").length + (activePhotoPairBatchId ? 1 : 0);
  const promptPairReadinessCounts = promptPairAudit?.preflight_gate_counts ?? {};
  const promptPairHeldAction = promptPairAudit?.next_review_actions?.find(
    (action) => action.action_type === "open_held_prompt_pair_candidate" && typeof action.task_id === "string"
  );
  const promptPairBlockerActions =
    promptPairAudit?.blocker_review_actions?.filter((action) => action.action_type === "open_prompt_pair_blocker" && typeof action.task_id === "string") ?? [];
  const selectedCollectionDef = collectionDefs.find((collection) => collection.id === selectedCollection) ?? collectionDefs[0];
  const queueScopeTitle = showCollectionFilters ? selectedCollectionDef.label : modeLabel(selectedMode);
  const queueScopeSubtitle = selectedMode === "make_gold" && activePhotoPairBatchId
    ? `${filteredTasks.length} items in photo batch ${activePhotoPairBatchId.slice(0, 22)}`
    : queueSearch.trim()
    ? `${filteredTasks.length} of ${modeTasks.length} items match "${queueSearch.trim()}"`
    : selectedMode === "review" && selectedCollection === "photos" && photoTaskFocus === "fastest_vector"
      ? `${filteredTasks.length} fastest vector-memory tasks`
    : `${filteredTasks.length} items`;
  const selectedTaskIndex = selectedTask ? filteredTasks.findIndex((task) => task.id === selectedTask.id) : -1;
  const assetsById = useMemo(() => new Map(assets.map((asset) => [asset.id, asset])), [assets]);
  const photoTaskByAssetId = useMemo(() => {
    const byAsset = new Map<string, Task>();
    for (const task of readyTasks) {
      const assetId = assetIdForTask(task);
      if (!assetId || byAsset.has(assetId)) {
        continue;
      }
      if (taskMatchesCollection(task, "photos")) {
        byAsset.set(assetId, task);
      }
    }
    return byAsset;
  }, [readyTasks]);
  const previewReadyPhotos = useMemo(() => {
    const searchTerm = queueSearch.trim().toLowerCase();
    return assets
      .filter((asset) => asset.asset_type === "photo" && asset.processing_status === "image_preview_ready")
      .filter((asset) => {
        if (!searchTerm) {
          return true;
        }
        return [asset.title, asset.original_filename, asset.human_id].join(" ").toLowerCase().includes(searchTerm);
      })
      .sort((left, right) => {
        const leftHasTask = photoTaskByAssetId.has(left.id) ? 0 : 1;
        const rightHasTask = photoTaskByAssetId.has(right.id) ? 0 : 1;
        return (
          leftHasTask - rightHasTask ||
          (left.title || left.original_filename || left.human_id).localeCompare(
            right.title || right.original_filename || right.human_id
          )
        );
      });
  }, [assets, photoTaskByAssetId, queueSearch]);
  const photoContactGroups = useMemo<PhotoContactSheetGroup[]>(() => {
    const groups = new Map<string, Asset[]>();
    previewReadyPhotos.forEach((asset) => {
      const groupKey = photoContactGroupKey(asset);
      groups.set(groupKey, [...(groups.get(groupKey) ?? []), asset]);
    });
    return Array.from(groups.entries())
      .map(([groupKey, groupAssets]) => {
        const variants = [...groupAssets].sort((left, right) => photoAssetTitle(left).localeCompare(photoAssetTitle(right)));
        const canonical = canonicalPhotoAsset(variants);
        const relatedTask = variants.map((variant) => photoTaskByAssetId.get(variant.id)).find((task): task is Task => Boolean(task));
        return {
          groupKey,
          canonical,
          variants,
          relatedTask,
          title: photoAssetTitle(canonical)
        };
      })
      .sort((left, right) => {
        const leftHasTask = left.relatedTask ? 0 : 1;
        const rightHasTask = right.relatedTask ? 0 : 1;
        return leftHasTask - rightHasTask || left.title.localeCompare(right.title);
      });
  }, [photoTaskByAssetId, previewReadyPhotos]);
  const contactSheetPhotos = photoContactGroups.slice(0, 24);
  const selectedTaskAsset = selectedTask ? assetsById.get(assetIdForTask(selectedTask) ?? "") : undefined;

  function navigateMode(mode: NavMode) {
    setSelectedMode(mode);
    setSelectedCollection(defaultCollectionForMode(mode));
    setPromptPairFilters(defaultPromptPairFilters);
    setPhotoTaskFocus(defaultPhotoTaskFocus);
    setActivePhotoPairBatchId(null);
    setQueueSearch("");
    setSelectedTaskId(null);
  }

  const openTask = useCallback((taskId: string) => {
    setSelectedTaskId(taskId);
    if (typeof window !== "undefined") {
      window.requestAnimationFrame(() => {
        const target = workbenchColumnRef.current ?? document.querySelector<HTMLElement>(".workbench-column");
        target?.scrollIntoView({
          block: "start",
          inline: "start",
          behavior: "smooth"
        });
      });
    }
  }, []);

  const openPromptPairReviewAction = useCallback((taskId?: string | null) => {
    if (!taskId) {
      return;
    }
    setSelectedMode("make_gold");
    setSelectedCollection("all");
    setPromptPairFilters(defaultPromptPairFilters);
    setPhotoTaskFocus(defaultPhotoTaskFocus);
    setActivePhotoPairBatchId(null);
    setQueueSearch("");
    openTask(taskId);
  }, [openTask]);

  const openPhotoReviewTask = useCallback(async (taskId: string) => {
    setSelectedMode("review");
    setSelectedCollection("photos");
    setPromptPairFilters(defaultPromptPairFilters);
    setPhotoTaskFocus(defaultPhotoTaskFocus);
    setActivePhotoPairBatchId(null);
    setQueueSearch("");
    setSelectedTaskId(taskId);
    await load();
    setSelectedMode("review");
    setSelectedCollection("photos");
    openTask(taskId);
  }, [openTask]);

  async function handleSubmit(decisions: Record<string, unknown>, notes?: string) {
    if (!selectedTask) {
      return;
    }
    const annotation = await submitTask(selectedTask.id, decisions, notes);
    setLastSubmitAnnotation(annotation);
    setPhotoPairStatus(null);
    setPhotoPairBatch(null);
    const submittedPhotoPairBatch = annotationPhotoPromptPairBatch(annotation);
    if (submittedPhotoPairBatch) {
      setPhotoPairBatch(submittedPhotoPairBatch);
      setActivePhotoPairBatchId(submittedPhotoPairBatch.generation_batch_id ?? submittedPhotoPairBatch.generation_batch_ids?.[0] ?? null);
      setPhotoPairStatus(
        submittedPhotoPairBatch.created_task_ids.length > 0
          ? `Created ${submittedPhotoPairBatch.created_task_ids.length} Prompt Pair candidates from this photo.`
          : "Opened the existing Prompt Pair candidates for this photo."
      );
    }
    const nextSegmentationTaskId =
      typeof annotation.creates_or_updates.segment_boundary_review_task_id === "string"
        ? annotation.creates_or_updates.segment_boundary_review_task_id
        : null;
    const nextPromptPairTaskId =
      typeof annotation.creates_or_updates.prompt_pair_candidate_task_id === "string"
        ? annotation.creates_or_updates.prompt_pair_candidate_task_id
        : null;
    const makeGoldTaskIds = Array.isArray(annotation.creates_or_updates.make_gold_task_ids)
      ? annotation.creates_or_updates.make_gold_task_ids.filter((id): id is string => typeof id === "string")
      : [];
    const photoPromptPairTaskIds = Array.isArray(annotation.creates_or_updates.photo_prompt_pair_task_ids)
      ? annotation.creates_or_updates.photo_prompt_pair_task_ids.filter((id): id is string => typeof id === "string")
      : [];
    const nextReviewTaskId =
      typeof annotation.creates_or_updates.review_task_id === "string"
        ? annotation.creates_or_updates.review_task_id
        : null;
    const receipt = annotationReceipt(annotation);
    const receiptNextMode = nextModeFromQueue(receiptString(receipt, "next_queue"));
    setCompletedThisSession((count) => count + 1);
    await load();
    if (nextSegmentationTaskId) {
      setSelectedMode("review");
      setSelectedCollection("all");
      setSelectedTaskId(nextSegmentationTaskId);
      return;
    }
    if (makeGoldTaskIds.length > 0) {
      setSelectedMode("make_gold");
      setSelectedCollection("all");
      setActivePhotoPairBatchId(null);
      setQueueSearch("");
      openTask(makeGoldTaskIds[0]);
      return;
    }
    if (photoPromptPairTaskIds.length > 0) {
      setSelectedMode("make_gold");
      setSelectedCollection("all");
      setPromptPairFilters(defaultPromptPairFilters);
      setActivePhotoPairBatchId(submittedPhotoPairBatch?.generation_batch_id ?? submittedPhotoPairBatch?.generation_batch_ids?.[0] ?? null);
      setQueueSearch("");
      openTask(photoPromptPairTaskIds[0]);
      return;
    }
    if (nextPromptPairTaskId) {
      setSelectedMode("make_gold");
      setSelectedCollection("all");
      setActivePhotoPairBatchId(null);
      setQueueSearch("");
      openTask(nextPromptPairTaskId);
      return;
    }
    if (nextReviewTaskId) {
      setSelectedMode(receiptNextMode ?? (selectedTask.task_type === "asset_triage" ? "review" : "make_gold"));
      setSelectedCollection("all");
      setSelectedTaskId(nextReviewTaskId);
      return;
    }
    if (receiptNextMode) {
      setSelectedMode(receiptNextMode);
      setSelectedCollection("all");
    }
  }

  async function handleSkip() {
    if (!selectedTask) {
      return;
    }
    await skipTask(selectedTask.id, "Skipped from workbench");
    await load();
  }

  async function handleFlag() {
    if (!selectedTask) {
      return;
    }
    await flagTask(selectedTask.id, "Flagged sensitive from workbench");
    await load();
  }

  async function handleCreateVisionDraftBatch() {
    setVisionBatchBusy(true);
    setError(null);
    try {
      await createVisionDraftBatch(10);
      navigateMode("review");
      setSelectedTaskId(null);
      await load();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Unable to create vision draft tasks.");
    } finally {
      setVisionBatchBusy(false);
    }
  }

  async function handleCreateSubmittedPhotoPromptPair() {
    const assetId = submittedPhotoAssetId(lastSubmitAnnotation);
    const metadataProfileId = annotationOutputString(lastSubmitAnnotation, "metadata_profile_id");
    if (!assetId && !metadataProfileId) {
      setPhotoPairStatus("No reviewed photo profile is attached to the last submit receipt.");
      return;
    }
    setPhotoPairStatus("Creating 5 photo-grounded prompt-pair candidates...");
    setPhotoPairBatch(null);
    try {
      const response = await createPhotoPromptPairCandidates(5, false, {
        assetId: assetId || undefined,
        metadataProfileId: metadataProfileId || undefined
      });
      setPhotoPairBatch(response);
      setActivePhotoPairBatchId(response.generation_batch_id ?? response.generation_batch_ids?.[0] ?? null);
      const taskId = response.created_task_ids[0] || response.candidates[0]?.existing_task_id || "";
      await load();
      if (taskId) {
        setSelectedMode("make_gold");
        setSelectedCollection("all");
        setPromptPairFilters(defaultPromptPairFilters);
        setActivePhotoPairBatchId(response.generation_batch_id ?? response.generation_batch_ids?.[0] ?? null);
        setQueueSearch("");
        setSelectedTaskId(taskId);
        setPhotoPairStatus(
          response.created_task_ids.length > 0
            ? `Created ${response.created_task_ids.length} Prompt Pairs candidates from this photo.`
            : "Opened the existing Prompt Pairs candidates for this photo."
        );
      } else {
        setPhotoPairStatus("No prompt-pair candidates were created. Check Exports for skipped/held photo-pair candidates.");
      }
    } catch (caught) {
      setPhotoPairStatus(caught instanceof Error ? caught.message : "Unable to create photo prompt-pair candidates.");
    }
  }

  async function handleDeletePromptPairCandidate(reason?: string) {
    if (!selectedTask) {
      return;
    }
    const fallbackTaskId =
      filteredTasks[selectedTaskIndex + 1]?.id ||
      filteredTasks[selectedTaskIndex - 1]?.id ||
      null;
    try {
      const annotation = await deletePromptPairCandidate(
        selectedTask.id,
        reason || "Rejected from Prompt Pairs editor",
        "Removed from active review queue by Adam during prompt-pair triage."
      );
      setLastSubmitAnnotation(annotation);
      await load();
      setSelectedMode("make_gold");
      setSelectedCollection("all");
      setSelectedTaskId(fallbackTaskId);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Unable to delete prompt-pair candidate.");
    }
  }

  const resizeShellColumn = useCallback((column: ShellColumn, nextWidth: number) => {
    const bounds = shellColumnBounds[column];
    setShellWidths((current) => ({ ...current, [column]: clamp(nextWidth, bounds.min, bounds.max) }));
  }, []);

  function startShellResize(column: ShellColumn, event: React.PointerEvent<HTMLDivElement>) {
    event.preventDefault();
    const startX = event.clientX;
    const startWidth = shellWidths[column];
    document.body.classList.add("is-column-resizing");

    function handleMove(moveEvent: PointerEvent) {
      resizeShellColumn(column, startWidth + moveEvent.clientX - startX);
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

  function handleShellResizeKey(column: ShellColumn, event: React.KeyboardEvent<HTMLDivElement>) {
    if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") {
      return;
    }
    event.preventDefault();
    resizeShellColumn(column, shellWidths[column] + (event.key === "ArrowRight" ? RESIZE_STEP : -RESIZE_STEP));
  }

  return (
    <main className="app-shell">
      <header className="global-chrome">
        <div className="brand">
          <button
            className="chrome-back"
            type="button"
            aria-label="Back to CharlesOps workspace"
            {...tooltip("Planned: return to a broader CharlesOps workspace/home view.")}
          >
            CO
          </button>
          <div>
            <strong>Workbench</strong>
            <span>CharlesOps source review and annotation</span>
          </div>
        </div>

        <div className="branch-pill" {...tooltip("Planned: workspace/environment selector. Currently showing the local main workspace.")}>
          <Database size={14} />
          <span>main</span>
          <ChevronDown size={13} />
        </div>
        <div className="sync-pill" {...tooltip("Status: task drafts autosave locally through the API. Future work can add live sync conflict details.")}>
          <CheckCircle2 size={14} />
          <span>Synced</span>
        </div>

        <nav className="top-nav" aria-label="Primary workbench sections">
          {topNav.map((item) => (
            <button
              key={item.id}
              className={selectedMode === item.id ? "active" : ""}
              type="button"
              onClick={() => navigateMode(item.id)}
              {...tooltip(item.tooltip)}
            >
              {item.icon}
              <span>{item.label}</span>
            </button>
          ))}
        </nav>

        <button
          className="avatar-button"
          type="button"
          aria-label="Adam workspace profile"
          {...tooltip("Planned: Adam workspace profile, account, and project menu.")}
        >
          CO
        </button>
      </header>

      <div
        className="workbench-layout"
        style={
          {
            "--sidebar-width": `${shellWidths.sidebar}px`,
            "--queue-width": `${shellWidths.queue}px`
          } as React.CSSProperties
        }
      >
        <aside className="sidebar">
          <nav className="primary-rail" aria-label="Workbench navigation">
            {sideNav.map((item) => {
              return (
                <button
                  key={item.id}
                  className={selectedMode === item.id ? "active" : ""}
                  type="button"
                  onClick={() => navigateMode(item.id)}
                  {...tooltip(item.tooltip)}
                >
                  {item.icon}
                  <span>{item.label}</span>
                  <em>{modeCounts[item.id]}</em>
                </button>
              );
            })}
          </nav>

          {showCollectionFilters ? (
            <div className="collection-block">
              <span className="rail-heading">Source filters</span>
              <nav className="collection-nav" aria-label="Source filters">
                {collectionDefs.map((collection) => (
                  <button
                    key={collection.id}
                    className={selectedCollection === collection.id ? "active" : ""}
                    type="button"
                    onClick={() => {
                      setSelectedCollection(collection.id);
                      setPromptPairFilters(defaultPromptPairFilters);
                      setPhotoTaskFocus(defaultPhotoTaskFocus);
                      setActivePhotoPairBatchId(null);
                      setQueueSearch("");
                      setSelectedTaskId(null);
                    }}
                    {...tooltip(collection.tooltip)}
                  >
                    {collection.icon}
                    <span>{collection.label}</span>
                    <em>{collectionCounts[collection.id]}</em>
                  </button>
                ))}
              </nav>
              {selectedMode === "make_gold" ? (
                <div className="prompt-pair-filter-block" aria-label="Prompt pair filters">
                  <div className="filter-heading-row">
                    <span className="rail-heading">Pair filters</span>
                    {activePromptPairFilterCount > 0 ? (
                      <button
                        type="button"
                        onClick={() => {
                          setPromptPairFilters(defaultPromptPairFilters);
                          setActivePhotoPairBatchId(null);
                          setQueueSearch("");
                          setSelectedTaskId(null);
                        }}
                      >
                        Reset
                      </button>
                    ) : null}
                  </div>
                  {(
                    [
                      ["voiceMode", "Voice mode"],
                      ["artifactMode", "Artifact mode"],
                      ["qualityStatus", "Quality"],
                      ["syntheticStatus", "Synthetic"],
                      ["sourceKind", "Source"]
                    ] as Array<[keyof PromptPairFilters, string]>
                  ).map(([key, label]) => (
                    <label key={key}>
                      <span>{label}</span>
                      <select
                        aria-label={`Prompt pair ${label.toLowerCase()} filter`}
                        value={promptPairFilters[key]}
                        onChange={(event) => {
                          setPromptPairFilters((current) => ({ ...current, [key]: event.target.value }));
                          setActivePhotoPairBatchId(null);
                          setSelectedTaskId(null);
                        }}
                      >
                        <option value="all">All</option>
                        {promptPairFilterOptions[key].map((option) => (
                          <option key={option} value={option}>
                            {filterLabel(option)}
                          </option>
                        ))}
                      </select>
                    </label>
                  ))}
                  <div className="prompt-pair-readiness-summary" aria-label="Prompt pair export readiness counts">
                    <span>
                      <em>Approved-ready</em>
                      <strong>{promptPairReadinessCounts.approved ?? 0}</strong>
                    </span>
                    <span>
                      <em>Needs gold edit</em>
                      <strong>{promptPairReadinessCounts.candidate ?? 0}</strong>
                    </span>
                    <span>
                      <em>Total inspected</em>
                      <strong>{promptPairAudit?.inspectable_pair_count ?? promptPairBaseTasks.length}</strong>
                    </span>
                    {promptPairProgress ? (
                      <div className="prompt-pair-progress-proof" aria-label="Prompt pair review progress proof">
                        <span>Review progress proof</span>
                        <strong>
                          {promptPairProgress.candidate_count} candidate / {promptPairProgress.approved_count} approved
                        </strong>
                        <small>
                          Top blocker: {promptPairProgress.top_blocker ? queueLabel(promptPairProgress.top_blocker) : "None"} (
                          {promptPairProgress.top_blocker_count})
                        </small>
                        <small>{promptPairProgress.completion_signal}</small>
                        <code>{promptPairProgress.content_sha256.slice(0, 16)}</code>
                      </div>
                    ) : null}
                    {dpoRepairPacket?.items.length ? (
                      <div className="prompt-pair-dpo-repair-queue" aria-label="DPO rejected reason repair queue">
                        <span>DPO rejected reason queue</span>
                        <strong>
                          {dpoRepairPacket.reported_candidate_count} shown / {dpoRepairPacket.total_candidate_count} rejected-reason gaps
                        </strong>
                        <small>{dpoRepairPacket.completion_signal}</small>
                        <small>
                          Review-only packet. {dpoRepairPacket.requires_adam_gold_edit ? "Adam gold edit still required." : "Adam review status unknown."}
                        </small>
                        <ol>
                          {dpoRepairPacket.items.slice(0, 3).map((item) => (
                            <li key={item.task_id}>
                              <span>
                                <em>{item.task_human_id}</em>
                                <strong>{item.prompt}</strong>
                                <small>{item.repair_projection.target_blocker_cleared ? "Projected rejected-reason blocker clears" : "Needs rejected-side reason"}</small>
                                {item.suggested_rejected_issue?.note ? (
                                  <p aria-label="Suggested DPO rejected reason">{item.suggested_rejected_issue.note}</p>
                                ) : null}
                                {item.suggested_failure_modes?.length ? (
                                  <ul className="prompt-pair-dpo-failure-modes" aria-label="Suggested DPO failure modes">
                                    {item.suggested_failure_modes.slice(0, 3).map((mode) => (
                                      <li key={mode}>{queueLabel(mode)}</li>
                                    ))}
                                  </ul>
                                ) : null}
                              </span>
                              <button type="button" onClick={() => openPromptPairReviewAction(item.task_id)}>
                                Open DPO reason
                              </button>
                            </li>
                          ))}
                        </ol>
                      </div>
                    ) : null}
                    {promptPairHeldAction?.task_id ? (
                      <button
                        type="button"
                        className="prompt-pair-next-action"
                        aria-label="Open first held prompt pair candidate"
                        onClick={() => openPromptPairReviewAction(promptPairHeldAction.task_id)}
                      >
                        <span>
                          <em>Next review</em>
                          <strong>{promptPairBlockerActionLabel(promptPairHeldAction.blockers?.[0])}</strong>
                        </span>
                        {promptPairHeldAction.blockers?.length ? (
                          <small>{promptPairHeldAction.blockers.slice(0, 2).map(queueLabel).join(", ")}</small>
                        ) : null}
                      </button>
                    ) : null}
                    {promptPairBlockerActions.slice(0, 2).map((action) => (
                      <button
                        key={`${action.blocker ?? "blocker"}-${action.task_id}`}
                        type="button"
                        className="prompt-pair-next-action compact"
                        aria-label={`Open prompt pair blocker ${queueLabel(action.blocker ?? "review blocker")}`}
                        onClick={() => openPromptPairReviewAction(action.task_id)}
                      >
                        <span>
                          <em>{queueLabel(action.blocker ?? "review blocker")}</em>
                          <strong>{action.blocker_count ?? 0}</strong>
                        </span>
                        <small>{promptPairBlockerActionLabel(action.blocker)}</small>
                      </button>
                    ))}
                  </div>
                </div>
              ) : null}
              {selectedMode === "review" && selectedCollection === "photos" ? (
                <div className="prompt-pair-filter-block" aria-label="Photo priority filters">
                  <div className="filter-heading-row">
                    <span className="rail-heading">Photo priority</span>
                    {photoTaskFocus !== "all" ? (
                      <button
                        type="button"
                        onClick={() => {
                          setPhotoTaskFocus(defaultPhotoTaskFocus);
                          setSelectedTaskId(null);
                        }}
                      >
                        Reset
                      </button>
                    ) : null}
                  </div>
                  <label>
                    <span>Review path</span>
                    <select
                      aria-label="Photo priority filter"
                      value={photoTaskFocus}
                      onChange={(event) => {
                        setPhotoTaskFocus(event.target.value as PhotoTaskFocus);
                        setSelectedTaskId(null);
                      }}
                    >
                      <option value="all">All photo tasks</option>
                      <option value="fastest_vector">Fastest vector memory</option>
                    </select>
                  </label>
                  {photoContextProgress ? (
                    <div className="photo-context-progress-proof" aria-label="Photo context review progress proof">
                      <span>Photo context progress proof</span>
                      <strong>
                        {photoContextProgress.submit_ready_count} submit-ready / {photoContextProgress.reported_task_count} tasks
                      </strong>
                      <small>
                        Drafts {photoContextProgress.draft_count} / blocked {photoContextProgress.blocked_count} / retrieval gaps{" "}
                        {photoContextProgress.retrieval_gap_task_count}
                      </small>
                      {topPhotoContextMissingField ? (
                        <small>
                          Top missing field: {queueLabel(topPhotoContextMissingField[0])} ({topPhotoContextMissingField[1]})
                        </small>
                      ) : null}
                      <small>{photoContextProgress.completion_signal}</small>
                      <code>
                        {photoContextProgress.does_not_create_memory_claim ? "no memory claim" : "memory claim risk"} /{" "}
                        {photoContextProgress.does_not_create_embedding_record ? "no embedding" : "embedding risk"} /{" "}
                        {photoContextProgress.content_sha256.slice(0, 16)}
                      </code>
                    </div>
                  ) : null}
                </div>
              ) : null}
            </div>
          ) : (
            <div className="mode-context">
              <span className="rail-heading">Current scope</span>
              <strong>{modeLabel(selectedMode)}</strong>
              <p>Source filters are hidden because this workstream has a dedicated queue.</p>
            </div>
          )}

          <div className="rail-status">
            <span {...tooltip("Status: workbench is idle and ready for the next action.")}>
              <Clock3 size={13} />
              Ready
            </span>
            <span {...tooltip("Status: API calls are succeeding. Future work can replace this with live health polling.")}>
              <CheckCircle2 size={13} />
              API: Healthy
            </span>
          </div>
        </aside>

        <div
          className="column-resizer"
          role="separator"
          aria-label="Resize navigation column"
          aria-orientation="vertical"
          aria-valuemin={shellColumnBounds.sidebar.min}
          aria-valuemax={shellColumnBounds.sidebar.max}
          aria-valuenow={shellWidths.sidebar}
          tabIndex={0}
          onPointerDown={(event) => startShellResize("sidebar", event)}
          onKeyDown={(event) => handleShellResizeKey("sidebar", event)}
          {...tooltip("Built: drag or use arrow keys to resize the navigation column.")}
        />

        <section className="queue-panel" aria-label="Task queue">
          <header className="queue-panel-header">
            <div>
              <h1>{queueScopeTitle}</h1>
              <span>{queueScopeSubtitle}</span>
            </div>
            <div className="queue-tools">
              <button type="button" aria-label="Filter queue" {...tooltip("Planned: advanced queue filters beyond the left source filters.")}>
                <Archive size={15} />
              </button>
              <label className="queue-search" {...tooltip("Built: search task titles, prompts, responses, source filenames, and voice modes in the current queue scope.")}>
                <Search size={15} />
                <input
                  aria-label="Search task queue"
                  type="search"
                  value={queueSearch}
                  onChange={(event) => {
                    setQueueSearch(event.target.value);
                    setSelectedTaskId(null);
                  }}
                  placeholder="Search"
                />
              </label>
              <button type="button" onClick={() => void load()} aria-label="Refresh workbench data" {...tooltip("Built: reload assets, tasks, memories, and gold examples from the API.")}>
                <RefreshCw size={15} />
              </button>
              {selectedMode === "review" ? (
                <button
                  className="wide-tool"
                  type="button"
                  onClick={() => void handleCreateVisionDraftBatch()}
                  aria-label="Create no-call vision draft review tasks from photo assets"
                  disabled={visionBatchBusy}
                  {...tooltip("Built as a safe stub: create no-call vision review tasks. Live vision model calls remain gated.")}
                >
                  <Image size={15} />
                  <span>{visionBatchBusy ? "Creating" : "Create drafts"}</span>
                </button>
              ) : null}
            </div>
          </header>

          <div className="queue-panel-body">
            {selectedMode === "intake" ? (
              <div className="intake-stack">
                <ArtifactUpload onUploaded={handleArtifactUploaded} />
                <GoogleDriveImport onImported={load} />
              </div>
            ) : null}

            {error ? <div className="error-banner">{error}</div> : null}

            {selectedMode === "review" && selectedCollection === "photos" && photoPrioritySummary ? (
              <section className="photo-priority-dry-run" aria-label="Photo context throughput artifact">
                <header>
                  <span>Photo context throughput artifact</span>
                  <strong>
                    {photoPrioritySummary.reported_count} shown / {photoPrioritySummary.total_candidate_count} ranked tasks
                  </strong>
                </header>
                <p>{photoPrioritySummary.throughput_policy.replaceAll("_", " ")}</p>
                <div>
                  <em>Completion signal</em>
                  <span>{photoPrioritySummary.completion_signal.replaceAll("_", " ")}</span>
                </div>
                <div className="photo-priority-submit-preview" aria-label="Throughput ranking proof">
                  <em>Ranking proof</em>
                  <span>{photoPrioritySummary.items[0]?.source_photo_title ?? "No ranked photo task"}</span>
                  <small>
                    Missing Adam fields: {photoPrioritySummary.items[0]?.missing_adam_field_count ?? 0} / payoff{" "}
                    {photoPrioritySummary.items[0]?.downstream_payoff_score ?? 0}
                  </small>
                  <small>
                    {photoPrioritySummary.items[0]?.preview_ready ? "preview ready" : "preview pending"} /{" "}
                    {photoPrioritySummary.items[0]?.path_label ?? "no path"}
                  </small>
                </div>
                <code>{photoPrioritySummary.content_sha256.slice(0, 16)}</code>
              </section>
            ) : null}

            {nextPhotoPromotionDryRun ? (
              <section className="photo-priority-dry-run" aria-label="Next photo promotion dry run">
                <header>
                  <span>{nextPhotoPromotionDryRun.pathLabel}</span>
                  <strong>{nextPhotoPromotionDryRun.taskLabel}</strong>
                </header>
                <p>{nextPhotoPromotionDryRun.whyFirst}</p>
                <div>
                  <em>Projected outcome</em>
                  <span>{nextPhotoPromotionDryRun.projectedOutcome}</span>
                </div>
                <div className="photo-priority-submit-preview" aria-label="Queue submit outcome preview">
                  <em>On Submit</em>
                  <span>{nextPhotoPromotionDryRun.submitOutcomeLabel}</span>
                  <small>{nextPhotoPromotionDryRun.submitOutcomeDetail}</small>
                  <small>{nextPhotoPromotionDryRun.vectorHandoffPreviewStatus.replaceAll("_", " ")}</small>
                </div>
                <div>
                  <em>Still needs</em>
                  <ul>
                    {nextPhotoPromotionDryRun.missingFields.map((field) => (
                      <li key={field}>{field}</li>
                    ))}
                  </ul>
                </div>
                <div>
                  <em>Safeguards</em>
                  <ul>
                    {nextPhotoPromotionDryRun.safeguards.map((item) => (
                      <li key={item}>{item}</li>
                    ))}
                  </ul>
                </div>
              </section>
            ) : null}

            {selectedMode === "review" && selectedCollection === "photos" ? (
              <section className="photo-contact-sheet" aria-label="Photo contact sheet">
                <header>
                  <div>
                    <span>Photo contact sheet</span>
                    <strong>
                      {photoContactGroups.length} photo groups / {previewReadyPhotos.length} preview-ready photos
                    </strong>
                  </div>
                  <em>No memory claim until Adam context</em>
                </header>
                <div className="photo-contact-grid">
                  {contactSheetPhotos.map((group) => {
                    const relatedTask = group.relatedTask;
                    const variantLabel = group.variants.length === 1 ? "1 variant" : `${group.variants.length} variants`;
                    return (
                      <button
                        key={group.groupKey}
                        type="button"
                        className="photo-contact-tile"
                        onClick={() => relatedTask ? openTask(relatedTask.id) : undefined}
                        disabled={!relatedTask}
                        aria-label={`Open photo group ${group.title}`}
                      >
                        <img src={getAssetPreviewUrl(group.canonical.id, "thumbnail")} alt="" loading="lazy" />
                        <span>{group.title}</span>
                        <small>
                          {relatedTask ? taskTypeLabel(relatedTask.task_type) : "No ready task yet"} / {variantLabel}
                        </small>
                      </button>
                    );
                  })}
                </div>
                <p>
                  Visual scan only. Duplicate variants are grouped from imported mirrored copies; downstream memory text still requires Adam-authored review.
                </p>
              </section>
            ) : null}

            {selectedMode === "make_gold" && promptPairBatchGroups.length > 0 ? (
              <section className="photo-pair-batch-shelf" aria-label="Photo prompt-pair batches">
                <header>
                  <div>
                    <span>Photo candidate batches</span>
                    <strong>
                      {promptPairBatchGroups.length} batch{promptPairBatchGroups.length === 1 ? "" : "es"} / candidate-only until gold edit
                    </strong>
                  </div>
                  {activePhotoPairBatchId ? (
                    <button
                      type="button"
                      onClick={() => {
                        setActivePhotoPairBatchId(null);
                        setSelectedTaskId(null);
                      }}
                    >
                      Clear batch
                    </button>
                  ) : null}
                </header>
                <div className="photo-pair-batch-list">
                  {promptPairBatchGroups.slice(0, 6).map((batch) => (
                    <button
                      key={batch.batchId}
                      type="button"
                      className={activePhotoPairBatchId === batch.batchId ? "active" : ""}
                      onClick={() => {
                        setActivePhotoPairBatchId(batch.batchId);
                        setQueueSearch("");
                        setSelectedTaskId(batch.firstTaskId);
                      }}
                    >
                      <span>
                        <strong>{batch.sourceTitle}</strong>
                        <em>
                          {batch.count} candidate{batch.count === 1 ? "" : "s"}
                          {batch.variantLabels.length ? ` / ${batch.variantLabels.slice(0, 2).join(", ")}` : ""}
                        </em>
                      </span>
                      <small>{batch.firstPrompt || batch.sourcePhotoId || "Photo-grounded prompt-pair batch"}</small>
                      <code>{batch.batchId}</code>
                    </button>
                  ))}
                </div>
                <p>
                  These are generated draft tickets from reviewed photo memory records. Keep the strongest versions, edit them in
                  Charles' voice, and delete weak candidates before export review.
                </p>
              </section>
            ) : null}

            {selectedMode === "make_gold" && photoPairBatch && photoPairBatch.candidates.length > 0 ? (
              <section className="photo-pair-batch-shelf latest-photo-pair-handoff" aria-label="Latest generated photo prompt-pair handoff">
                <header>
                  <div>
                    <span>Latest generated photo prompts</span>
                    <strong>
                      {photoPairBatch.candidates.length} candidate{photoPairBatch.candidates.length === 1 ? "" : "s"} from the photo you just submitted
                    </strong>
                  </div>
                  <button
                    type="button"
                    onClick={() => {
                      setActivePhotoPairBatchId(photoPairBatch.generation_batch_id ?? photoPairBatch.generation_batch_ids?.[0] ?? null);
                      setPromptPairFilters(defaultPromptPairFilters);
                      setQueueSearch("");
                      setSelectedTaskId(photoPairBatch.created_task_ids[0] || photoPairBatch.candidates[0]?.existing_task_id || null);
                    }}
                  >
                    Show this batch
                  </button>
                </header>
                <div className="photo-pair-batch-list">
                  {photoPairBatch.candidates.slice(0, 5).map((candidate, index) => {
                    const taskId = candidate.created_task_id || candidate.existing_task_id || "";
                    return (
                      <button
                        key={`${candidate.metadata_profile_id}-${candidate.variant_key ?? index}`}
                        type="button"
                        className={selectedTask?.id === taskId ? "active" : ""}
                        onClick={() => {
                          setActivePhotoPairBatchId(photoPairBatch.generation_batch_id ?? photoPairBatch.generation_batch_ids?.[0] ?? null);
                          setPromptPairFilters(defaultPromptPairFilters);
                          setQueueSearch("");
                          if (taskId) {
                            openTask(taskId);
                          }
                        }}
                        disabled={!taskId}
                      >
                        <span>
                          <strong>{candidate.variant_label || `Candidate ${index + 1}`}</strong>
                          <em>{candidate.asset_title}</em>
                        </span>
                        <small>{candidate.prompt}</small>
                        <code>{taskId ? taskId.slice(0, 8) : "no task"}</code>
                      </button>
                    );
                  })}
                </div>
              </section>
            ) : null}

            <div className="task-list" aria-label="Tasks">
              {loading ? <p className="quiet">Loading workbench data...</p> : null}
              {!loading && filteredTasks.length === 0 ? <p className="quiet">No ready tasks in this collection.</p> : null}
              {filteredTasks.map((task) => {
                const taskAsset = assetsById.get(assetIdForTask(task) ?? "");
                const priorityBadge = selectedMode === "review" && selectedCollection === "photos" ? photoPriorityBadge(task) : null;
                const priorityItem = selectedMode === "review" && selectedCollection === "photos"
                  ? photoPriorityItemForTask(photoPrioritySummary, task)
                  : null;
                const submitOutcomeBadge = photoSubmitOutcomeBadge(priorityItem);
                const photoDelta = selectedMode === "review" && selectedCollection === "photos"
                  ? photoRowReadinessDelta(task, priorityItem)
                  : null;
                const readinessBadges = [
                  ...(priorityBadge ? [priorityBadge] : []),
                  ...(submitOutcomeBadge ? [submitOutcomeBadge] : []),
                  ...readinessBadgesForTask(task, taskAsset)
                ].slice(0, 3);
                const promptPairDelta = promptPairReadinessDelta(task);
                const sourceReviewDelta = sourceReviewGenerationDelta(task);
                const ordinalLabel = promptPairOrdinalLabel(task);
                const showTaskThumbnail =
                  taskAsset?.asset_type === "photo" && taskAsset.processing_status === "image_preview_ready";
                return (
                  <button
                    key={task.id}
                    className={[
                      "task-row",
                      selectedTask?.id === task.id ? "active" : "",
                      showTaskThumbnail ? "has-thumbnail" : ""
                    ].filter(Boolean).join(" ")}
                    type="button"
                    onClick={() => openTask(task.id)}
                    {...tooltip(`Open task: ${taskTitle(task)}. ${taskSubtitle(task)}`)}
                  >
                    {showTaskThumbnail ? (
                      <img
                        className="task-row-thumbnail"
                        src={getAssetPreviewUrl(taskAsset.id, "thumbnail")}
                        alt=""
                        loading="lazy"
                      />
                    ) : null}
                    <span>{taskTypeLabel(task.task_type)}</span>
                    <strong>{taskTitle(task)}</strong>
                    <em>{taskSubtitle(task)}</em>
                    {readinessBadges.length > 0 ? (
                      <div className="queue-readiness-strip" aria-label="Readiness badges">
                        {readinessBadges.map((badge) => (
                          <span key={badge.label} data-tone={badge.tone} title={badge.tooltip}>
                            {badge.label}
                          </span>
                        ))}
                      </div>
                    ) : null}
                    {promptPairDelta ? (
                      <div className="prompt-pair-row-delta" aria-label="Prompt pair readiness delta" data-tone={promptPairDelta.tone}>
                        <span>{promptPairDelta.label}</span>
                        <small>{promptPairDelta.detail}</small>
                      </div>
                    ) : null}
                    {photoDelta ? (
                      <div className="photo-row-delta" aria-label="Photo readiness delta" data-tone={photoDelta.tone}>
                        <span>{photoDelta.label}</span>
                        <small>{photoDelta.detail}</small>
                      </div>
                    ) : null}
                    {sourceReviewDelta ? (
                      <div className="source-review-row-delta" aria-label="Source review generation delta" data-tone={sourceReviewDelta.tone}>
                        <span>{sourceReviewDelta.label}</span>
                        <small>{sourceReviewDelta.detail}</small>
                      </div>
                    ) : null}
                    {ordinalLabel ? <small>{ordinalLabel}</small> : null}
                    <time>{formatRelativeTime(task.updated_at)}</time>
                  </button>
                );
              })}
            </div>
          </div>

          <footer className="queue-pagination">
            <button type="button" aria-label="Previous page" {...tooltip("Planned: paginate longer task lists. Current queue is shown as one scrolling list.")}>
              ‹
            </button>
            <span>1 of {Math.max(1, Math.ceil(filteredTasks.length / 10))}</span>
            <button type="button" aria-label="Next page" {...tooltip("Planned: paginate longer task lists. Current queue is shown as one scrolling list.")}>
              ›
            </button>
          </footer>
        </section>

        <div
          className="column-resizer"
          role="separator"
          aria-label="Resize queue column"
          aria-orientation="vertical"
          aria-valuemin={shellColumnBounds.queue.min}
          aria-valuemax={shellColumnBounds.queue.max}
          aria-valuenow={shellWidths.queue}
          tabIndex={0}
          onPointerDown={(event) => startShellResize("queue", event)}
          onKeyDown={(event) => handleShellResizeKey("queue", event)}
          {...tooltip("Built: drag or use arrow keys to resize the queue column.")}
        />

        <section className="workbench-column" ref={workbenchColumnRef}>
          {selectedMode === "exports" ? (
            <ExportDryRunPanel onOpenReviewTask={openPhotoReviewTask} />
          ) : (
            <div className={selectedMode === "make_gold" ? "workbench-stack has-utility" : "workbench-stack"}>
              <SubmitReceiptBanner annotation={lastSubmitAnnotation} />
              <SubmittedResultPanel
                annotation={lastSubmitAnnotation}
                photoPairStatus={photoPairStatus}
                photoPairBatch={photoPairBatch}
                onViewExports={() => navigateMode("exports")}
                onCreatePhotoPromptPair={handleCreateSubmittedPhotoPromptPair}
                onOpenPhotoPromptPair={(taskId) => {
                  setSelectedMode("make_gold");
                  setSelectedCollection("all");
                  setPromptPairFilters(defaultPromptPairFilters);
                  setActivePhotoPairBatchId(photoPairBatch?.generation_batch_id ?? photoPairBatch?.generation_batch_ids?.[0] ?? null);
                  setSelectedTaskId(taskId);
                }}
              />
              {selectedTask ? (
                <TaskWorkbench
                  key={selectedTask.id}
                  task={selectedTask}
                  queuePosition={selectedTaskIndex + 1}
                  queueTotal={filteredTasks.length}
                  completedThisSession={completedThisSession}
                  memoriesCount={memories.length}
                  goldExamplesCount={goldExamples.length}
                  assetsCount={assets.length}
                  asset={selectedTaskAsset}
                  assets={assets}
                  onSubmit={handleSubmit}
                  onSkip={handleSkip}
                  onFlag={handleFlag}
                  onDeleteCandidate={handleDeletePromptPairCandidate}
                  onPrevious={() => {
                    if (selectedTaskIndex > 0) {
                      openTask(filteredTasks[selectedTaskIndex - 1].id);
                    }
                  }}
                  onNext={() => {
                    if (selectedTaskIndex >= 0 && selectedTaskIndex < filteredTasks.length - 1) {
                      openTask(filteredTasks[selectedTaskIndex + 1].id);
                    }
                  }}
                />
              ) : (
                <div className="empty-state">
                  <Sparkles size={22} />
                  <strong>Queue clear</strong>
                  <span>Seed data may need to be loaded, or every ready task has been handled.</span>
                </div>
              )}
            </div>
          )}
        </section>
      </div>
    </main>
  );
}
