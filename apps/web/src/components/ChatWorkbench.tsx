"use client";

import { FormEvent, KeyboardEvent, useEffect, useMemo, useRef, useState } from "react";
import { CheckCircle2, FileText, History, Image, MessageCircle, Plus, Send, Sparkles, XCircle } from "lucide-react";
import {
  confirmChatAction,
  createChatSession,
  dismissChatAction,
  getAssetPreviewUrl,
  getChatAudit,
  getChatSession,
  getEvidenceClusters,
  getEvidenceCorpus,
  getModelStatus,
  listChatSessions,
  previewChatAction,
  sendChatTurn
} from "@/lib/api";
import type {
  Annotation,
  Asset,
  ChatAuditResponse,
  ChatMessage,
  ChatTurnResponse,
  EvidenceCluster,
  EvidenceClustersResponse,
  EvidenceCorpusResponse,
  JsonRecord,
  ModelStatus,
  Task
} from "@/lib/types";

type LocalChatMessage = ChatMessage & {
  status?: string;
  actions?: JsonRecord[];
  fieldUpdates?: JsonRecord;
  patchResult?: JsonRecord;
};

const CHAT_SESSION_STORAGE_KEY = "chas.chat.session.v1";

interface ChatWorkbenchProps {
  tasks: Task[];
  assets?: Asset[];
  selectedTask: Task | null;
  photoPreviewAccessToken?: string;
  onOpenTask: (taskId: string) => void;
  onSubmitted: (annotation: Annotation) => void;
  onViewTrainingBoard: () => void;
  onRefresh: () => Promise<void>;
}

function payloadString(payload: JsonRecord, key: string, fallback = ""): string {
  const value = payload[key];
  return typeof value === "string" && value.trim() ? value.trim() : fallback;
}

function payloadList(payload: JsonRecord, key: string): string[] {
  const value = payload[key];
  if (Array.isArray(value)) {
    return value.map(String).filter(Boolean);
  }
  if (typeof value === "string" && value.trim()) {
    return value
      .split(",")
      .map((item) => item.trim())
      .filter(Boolean);
  }
  return [];
}

function isPhotoChatTask(task: Task | null): boolean {
  if (!task) {
    return false;
  }
  const payload = task.input_payload ?? {};
  const sourceType = payloadString(payload, "asset_type") || payloadString(payload, "source_type");
  const mimeType = payloadString(payload, "mime_type");
  return (
    task.task_type === "photo_context" ||
    task.task_type === "vision_draft_review" ||
    sourceType === "photo" ||
    mimeType.startsWith("image/")
  );
}

function isPromptPairTask(task: Task | null): boolean {
  return Boolean(task && ["gold_voice_edit", "grounded_prompt_pair_candidate"].includes(task.task_type));
}

function isSourceReviewTask(task: Task | null): boolean {
  return Boolean(task && ["text_segment_review", "text_segment_boundary_review", "email_voice_sample"].includes(task.task_type));
}

function taskAssetId(task: Task | null): string {
  if (!task) {
    return "";
  }
  const payload = task.input_payload ?? {};
  return payloadString(payload, "asset_id") || (task.target_type === "asset" ? task.target_id : "");
}

function sourcePhotoId(task: Task | null): string {
  if (!task) {
    return "";
  }
  return payloadString(task.input_payload ?? {}, "source_photo_id") || taskAssetId(task);
}

function findAsset(assets: Asset[] | undefined, assetId: string): Asset | undefined {
  return assets?.find((asset) => asset.id === assetId || asset.human_id === assetId);
}

function promptPairMode(task: Task | null): string {
  if (!task) {
    return "sft";
  }
  return payloadString(task.input_payload ?? {}, "artifact_mode", "sft");
}

function taskTitle(task: Task | null): string {
  if (!task) {
    return "No active item";
  }
  const payload = task.input_payload ?? {};
  if (isPromptPairTask(task)) {
    const prompt = payloadString(payload, "prompt", task.human_id);
    return `${promptPairMode(task).toUpperCase()} review: ${prompt}`;
  }
  return (
    stringValue(payload.prompt) ||
    stringValue(payload.asset_title) ||
    stringValue(payload.source_title) ||
    stringValue(payload.source_filename) ||
    task.human_id
  );
}

function evidenceClusterQuery(task: Task | null, response: ChatTurnResponse | null): string {
  const payload = task?.input_payload ?? {};
  const values = [
    responseTaskTitle(response),
    taskTitle(task),
    payloadString(payload, "prompt"),
    payloadString(payload, "source_excerpt"),
    payloadString(payload, "asset_title"),
    payloadString(payload, "source_title"),
    payloadString(payload, "source_filename"),
    payloadString(payload, "content"),
    payloadString(payload, "chosen")
  ]
    .map((value) => previewText(value, 140))
    .filter(Boolean);
  const seen = new Set<string>();
  const unique = values.filter((value) => {
    const key = value.toLowerCase();
    if (seen.has(key)) {
      return false;
    }
    seen.add(key);
    return true;
  });
  return previewText(unique.join(" "), 320) || "family memory source review training evidence";
}

function evidenceClusterSourceSegmentId(cluster: EvidenceCluster): string {
  const topRecord = cluster.top_records?.[0];
  if (topRecord?.source_segment_id) {
    return topRecord.source_segment_id;
  }
  if (topRecord && ["segment", "source_span", "source_chunk"].includes(topRecord.target_type)) {
    return topRecord.target_id;
  }
  const targetRef = cluster.target_refs?.find((ref) => ["segment", "source_span", "source_chunk"].includes(String(ref.target_type || "")));
  return typeof targetRef?.target_id === "string" ? targetRef.target_id : "";
}

function evidenceClusterSourceAssetId(cluster: EvidenceCluster): string {
  const topRecord = cluster.top_records?.[0];
  if (cluster.source_asset_id) {
    return cluster.source_asset_id;
  }
  if (topRecord?.source_asset_id) {
    return topRecord.source_asset_id;
  }
  const targetRef = cluster.target_refs?.find((ref) => ref.target_type === "asset");
  return typeof targetRef?.target_id === "string" ? targetRef.target_id : "";
}

function evidenceClusterPhotoId(cluster: EvidenceCluster): string {
  const topRecord = cluster.top_records?.[0];
  if (cluster.source_photo_id) {
    return cluster.source_photo_id;
  }
  if (topRecord?.source_photo_id) {
    return topRecord.source_photo_id;
  }
  const targetRef = cluster.target_refs?.find((ref) => ref.target_type === "asset" || ref.target_type === "photo");
  return typeof targetRef?.target_id === "string" ? targetRef.target_id : "";
}

function evidenceClusterReviewType(cluster: EvidenceCluster): "photo context" | "source" | "" {
  if (cluster.cluster_family === "photo_memory" && evidenceClusterPhotoId(cluster)) {
    return "photo context";
  }
  if (cluster.cluster_family === "source_context" && (evidenceClusterSourceSegmentId(cluster) || evidenceClusterSourceAssetId(cluster))) {
    return "source";
  }
  return "";
}

function evidenceClusterReviewPrompt(cluster: EvidenceCluster): string {
  const topRecord = cluster.top_records?.[0];
  const reviewType = evidenceClusterReviewType(cluster) || "source";
  const sourceAssetId = evidenceClusterSourceAssetId(cluster);
  const sourcePhotoId = evidenceClusterPhotoId(cluster);
  const sourceSegmentId = evidenceClusterSourceSegmentId(cluster);
  return [
    `Please create or open a ${reviewType} review task for this evidence cluster.`,
    `Cluster title: ${cluster.display_title}`,
    `Cluster key: ${cluster.cluster_key}`,
    sourceAssetId ? `Source asset id: ${sourceAssetId}` : "",
    sourcePhotoId ? `Source photo id: ${sourcePhotoId}` : "",
    sourceSegmentId ? `Source segment id: ${sourceSegmentId}` : "",
    topRecord ? `Top record: ${topRecord.title} (${topRecord.target_type}:${topRecord.target_id})` : "",
    "Keep this as a review task request, not a memory claim, and ask for confirmation before any submit/export."
  ]
    .filter(Boolean)
    .join("\n");
}

function stringValue(value: unknown): string {
  return typeof value === "string" && value.trim() ? value.trim() : "";
}

function labelFromKey(value: string): string {
  return value
    .replaceAll("_", " ")
    .split(" ")
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}

function responseTaskId(response: ChatTurnResponse | null): string {
  const value = response?.active_task?.id;
  return typeof value === "string" ? value : "";
}

function responseTaskTitle(response: ChatTurnResponse | null): string {
  const value = response?.active_task?.title;
  return typeof value === "string" ? value : "";
}

function responseDraftNotes(response: ChatTurnResponse | null): string | null {
  const draft = response?.draft;
  if (!draft || typeof draft !== "object") {
    return null;
  }
  const notes = draft.notes;
  return typeof notes === "string" ? notes : null;
}

function responseTaskSelection(response: ChatTurnResponse | null): string {
  const selection = response?.task_selection;
  if (!selection || typeof selection !== "object") {
    return "";
  }
  const reason = typeof selection.selection_reason === "string" ? selection.selection_reason : "";
  const label = typeof selection.requested_route_label === "string" ? selection.requested_route_label : "";
  if (reason === "routed_from_chat_intent" && label) {
    return `Routed to ${label}`;
  }
  if (reason === "no_matching_route_task" && label) {
    return `No ready ${label}`;
  }
  if (reason === "highest_priority_ready_task") {
    return "Highest-priority ready item";
  }
  return "";
}

function storedTurnMessage(turn: JsonRecord): LocalChatMessage | null {
  const role = turn.role === "assistant" ? "assistant" : turn.role === "user" ? "user" : null;
  const content = typeof turn.content === "string" ? turn.content : "";
  if (!role || !content.trim()) {
    return null;
  }
  const metadata = turn.metadata_json && typeof turn.metadata_json === "object" ? (turn.metadata_json as JsonRecord) : {};
  return {
    role,
    content,
    status: typeof metadata.status === "string" ? metadata.status : undefined
  };
}

function storedSessionId(): string | null {
  if (typeof window === "undefined") {
    return null;
  }
  return window.localStorage.getItem(CHAT_SESSION_STORAGE_KEY);
}

function persistSessionId(sessionId: string | null) {
  if (typeof window === "undefined") {
    return;
  }
  if (sessionId) {
    window.localStorage.setItem(CHAT_SESSION_STORAGE_KEY, sessionId);
  } else {
    window.localStorage.removeItem(CHAT_SESSION_STORAGE_KEY);
  }
}

function sessionOptionLabel(session: JsonRecord): string {
  return (
    recordString(session, "title") ||
    recordString(session, "active_task_id") ||
    recordString(session, "id", "Untitled chat")
  );
}

function compactJsonValue(value: unknown): string {
  if (typeof value === "string") {
    return value.length > 72 ? `${value.slice(0, 69)}...` : value;
  }
  if (typeof value === "boolean") {
    return value ? "yes" : "no";
  }
  if (Array.isArray(value)) {
    return `${value.length} item${value.length === 1 ? "" : "s"}`;
  }
  if (value && typeof value === "object") {
    return "updated";
  }
  return String(value ?? "");
}

function previewJsonValue(value: unknown): string {
  if (typeof value === "string") {
    return value.length > 520 ? `${value.slice(0, 517)}...` : value;
  }
  if (Array.isArray(value)) {
    return value.map(String).join(", ");
  }
  if (value && typeof value === "object") {
    return JSON.stringify(value);
  }
  if (typeof value === "boolean") {
    return value ? "yes" : "no";
  }
  return String(value ?? "");
}

function previewText(value: unknown, limit = 180): string {
  const text = String(value ?? "").replace(/\s+/g, " ").trim();
  return text.length > limit ? `${text.slice(0, Math.max(0, limit - 3))}...` : text;
}

function actionString(action: JsonRecord | undefined, key: string, fallback = ""): string {
  const value = action?.[key];
  return typeof value === "string" && value.trim() ? value.trim() : fallback;
}

function asJsonRecord(value: unknown): JsonRecord | null {
  return value && typeof value === "object" && !Array.isArray(value) ? (value as JsonRecord) : null;
}

function asJsonRecords(value: unknown): JsonRecord[] {
  return Array.isArray(value) ? value.map(asJsonRecord).filter((item): item is JsonRecord => Boolean(item)) : [];
}

function patchDiffRows(message: LocalChatMessage): JsonRecord[] {
  const patchResult = asJsonRecord(message.patchResult);
  return asJsonRecords(patchResult?.field_diffs).slice(0, 6);
}

function patchBlockedReason(message: LocalChatMessage): string {
  const patchResult = asJsonRecord(message.patchResult);
  return recordString(patchResult, "blocked_reason");
}

function recordString(record: JsonRecord | null | undefined, key: string, fallback = ""): string {
  const value = record?.[key];
  return typeof value === "string" && value.trim() ? value.trim() : fallback;
}

function shortId(value: string, length = 10): string {
  return value.length > length ? value.slice(0, length) : value;
}

function promptPairArtifactMode(task: Task | null, workSurface?: JsonRecord): string {
  return recordString(workSurface, "artifact_mode") || promptPairMode(task);
}

function promptPairFieldContract(workSurface?: JsonRecord): JsonRecord {
  return asJsonRecord(workSurface?.field_contract) ?? {};
}

function promptPairFieldLabel(key: string, task: Task | null, workSurface?: JsonRecord): string {
  if (isPhotoChatTask(task)) {
    if (key === "visual_description_correction") {
      return "Reviewed visual description";
    }
    if (key === "adam_context_note") {
      return "Memory context";
    }
    if (key === "open_questions") {
      return "Open questions";
    }
    if (key === "retrieval_cues") {
      return "Retrieval cues";
    }
    return labelFromKey(key);
  }
  if (!isPromptPairTask(task)) {
    return labelFromKey(key);
  }
  const artifactMode = promptPairArtifactMode(task, workSurface);
  if (artifactMode === "dpo") {
    if (key === "chosen" || key === "content") {
      return "Chosen / preferred";
    }
    if (key === "rejected") {
      return "Rejected / weaker";
    }
    if (key === "context") {
      return "Preference rationale";
    }
  } else {
    if (key === "content") {
      return "Accepted SFT response";
    }
    if (key === "rejected") {
      return "Rejected original response";
    }
    if (key === "chosen") {
      return "Derived export response";
    }
    if (key === "context") {
      return "Review notes";
    }
  }
  if (key === "failure_modes") {
    return "Failure modes";
  }
  if (key === "export_flags") {
    return "Export flags";
  }
  return labelFromKey(key);
}

function decisionHasValue(decisions: JsonRecord, key: string): boolean {
  const value = decisions[key];
  if (Array.isArray(value)) {
    return value.some((item) => String(item).trim());
  }
  if (value && typeof value === "object") {
    return Object.keys(value).length > 0;
  }
  if (typeof value === "boolean") {
    return true;
  }
  return typeof value === "number" || (typeof value === "string" && value.trim().length > 0);
}

function missingRequiredFields(task: Task, decisions: JsonRecord): string[] {
  return (task.required_decisions ?? []).filter((field) => !decisionHasValue(decisions, field));
}

function fieldSourceLabel(task: Task, field: string): string {
  if (isPhotoChatTask(task)) {
    if (["adam_context_note", "retrieval_cues", "event_summary", "memory_caption", "emotional_salience"].includes(field)) {
      return "Adam memory";
    }
    if (["open_questions", "uncertainties", "uncertainty_notes"].includes(field)) {
      return "Uncertainty";
    }
    if (["machine_guess_people", "machine_guess_objects", "machine_tags", "visual_summary"].includes(field)) {
      return "Model inference";
    }
    if (["asset_id", "source_photo_id", "source_photo_title", "asset_title"].includes(field)) {
      return "Database link";
    }
    return "Adam fact";
  }
  if (isPromptPairTask(task)) {
    if (field === "prompt") {
      return "Source prompt";
    }
    if (["context", "failure_modes", "operator_candidate_triage_intent"].includes(field)) {
      return "Adam critique";
    }
    if (["content", "chosen", "rejected"].includes(field)) {
      return "Edited response";
    }
    if (field === "export_flags") {
      return "Export policy";
    }
    return "Review details";
  }
  if (isSourceReviewTask(task)) {
    return "Source review";
  }
  return "Adam review";
}

function uniqueLabels(values: string[]): string[] {
  return Array.from(new Set(values.filter(Boolean)));
}

function ChatContextStatus({ task, decisions, draftDecisions }: { task: Task; decisions: JsonRecord; draftDecisions?: JsonRecord }) {
  const missing = missingRequiredFields(task, decisions).slice(0, 5);
  const draftKeys = Object.keys(draftDecisions ?? {}).filter((key) => key !== "chat_provenance");
  const provenanceLabels = uniqueLabels(draftKeys.map((key) => fieldSourceLabel(task, key))).slice(0, 4);
  if (missing.length === 0 && draftKeys.length === 0 && provenanceLabels.length === 0) {
    return null;
  }
  return (
    <div className="chat-context-status" aria-label="Chat work item readiness">
      <article>
        <em>Missing fields</em>
        <p>{missing.length > 0 ? missing.map(labelFromKey).join(", ") : "None"}</p>
      </article>
      <article>
        <em>Draft</em>
        <p>{draftKeys.length > 0 ? `${draftKeys.length} captured` : "No draft yet"}</p>
      </article>
      <article>
        <em>Provenance</em>
        <div>
          {provenanceLabels.length > 0 ? provenanceLabels.map((label) => <span key={label}>{label}</span>) : <span>Pending</span>}
        </div>
      </article>
    </div>
  );
}

function previewFieldOrder(task: Task | null, workSurface?: JsonRecord): string[] {
  if (isPhotoChatTask(task)) {
    return [
      "memory_caption",
      "visual_description_correction",
      "visible_people",
      "people",
      "place",
      "places",
      "event",
      "date_or_range",
      "retrieval_cues",
      "privacy_level",
      "open_questions"
    ];
  }
  if (isPromptPairTask(task)) {
    return promptPairArtifactMode(task, workSurface) === "dpo"
      ? ["prompt", "chosen", "rejected", "context", "failure_modes", "operator_candidate_triage_intent"]
      : ["prompt", "content", "rejected", "context", "failure_modes", "export_flags"];
  }
  if (isSourceReviewTask(task)) {
    return ["source_genre", "authorship", "truth_status", "voice_presence", "privacy_level", "summary", "why_it_matters"];
  }
  return [];
}

function orderedPreviewRows(task: Task | null, payload: JsonRecord | null | undefined, workSurface?: JsonRecord): [string, unknown][] {
  if (!payload) {
    return [];
  }
  const entries = Object.entries(payload);
  const used = new Set<string>();
  const ordered: [string, unknown][] = [];
  for (const key of previewFieldOrder(task, workSurface)) {
    if (key in payload && decisionHasValue(payload, key)) {
      ordered.push([key, payload[key]]);
      used.add(key);
    }
  }
  for (const [key, value] of entries) {
    if (!used.has(key) && decisionHasValue(payload, key)) {
      ordered.push([key, value]);
    }
  }
  return ordered;
}

function summaryString(summary: JsonRecord | null, key: string, fallback = ""): string {
  const value = summary?.[key];
  return typeof value === "string" && value.trim() ? value.trim() : fallback;
}

function summaryNumber(summary: JsonRecord | null, key: string): number {
  const value = summary?.[key];
  return typeof value === "number" && Number.isFinite(value) ? value : 0;
}

function summaryList(value: unknown): string[] {
  return Array.isArray(value)
    ? value
        .map((item) => previewJsonValue(item))
        .map((item) => item.trim())
        .filter(Boolean)
    : [];
}

function toolReceiptDetail(receipt: JsonRecord): string {
  const result = asJsonRecord(receipt.result);
  if (!result) {
    return recordString(receipt, "status", "unknown");
  }
  if (recordString(result, "corpus_type")) {
    const recordCount = typeof result.record_count === "number" ? result.record_count : 0;
    const excludedCount = typeof result.excluded_count === "number" ? result.excluded_count : 0;
    return `${recordCount} reviewed / ${excludedCount} held`;
  }
  if (recordString(result, "preview_type") === "source_review_generate_pairs_preview") {
    const createdCount = typeof result.projected_created_pair_count === "number" ? result.projected_created_pair_count : 0;
    const heldCount = typeof result.projected_held_pair_count === "number" ? result.projected_held_pair_count : 0;
    return `${createdCount} candidate${createdCount === 1 ? "" : "s"} / ${heldCount} held`;
  }
  if (Array.isArray(result.results)) {
    return `${result.results.length} match${result.results.length === 1 ? "" : "es"}`;
  }
  const retrievalGap = asJsonRecord(result.retrieval_gap);
  if (recordString(retrievalGap, "status")) {
    return labelFromKey(recordString(retrievalGap, "status"));
  }
  if (Array.isArray(result.missing_fields)) {
    return `${result.missing_fields.length} missing`;
  }
  return recordString(receipt, "status", "completed");
}

function submittedArtifactRows(annotation: Annotation | null | undefined): { label: string; value: string }[] {
  const records = asJsonRecord(annotation?.creates_or_updates) ?? {};
  const sourcePairTaskIds = Array.isArray(records.make_gold_task_ids) ? records.make_gold_task_ids.filter((value): value is string => typeof value === "string" && Boolean(value)) : [];
  const photoPairTaskIds = Array.isArray(records.photo_prompt_pair_task_ids) ? records.photo_prompt_pair_task_ids.filter((value): value is string => typeof value === "string" && Boolean(value)) : [];
  const generatedPairTaskCount = new Set([...sourcePairTaskIds, ...photoPairTaskIds]).size;
  const pairGenerationRun = asJsonRecord(records.pair_generation_run);
  return [
    ["Review record", annotation?.id ?? ""],
    ["Gold", stringValue(records.gold_voice_example_id)],
    ["SFT", stringValue(records.sft_candidate_id)],
    ["DPO", stringValue(records.dpo_pair_id)],
    ["Pair tasks", generatedPairTaskCount ? String(generatedPairTaskCount) : ""],
    ["Pair run", stringValue(pairGenerationRun?.run_type)],
    ["Receipt", stringValue(records.task_receipt_id)]
  ]
    .filter(([, value]) => value)
    .map(([label, value]) => ({ label, value }));
}

function ShortText({ value, fallback = "Not supplied yet." }: { value: string; fallback?: string }) {
  return <p>{value.trim() || fallback}</p>;
}

function ChatWorkSummaryPanel({ summary, onOpenTask }: { summary?: JsonRecord; onOpenTask: (taskId: string) => void }) {
  const safeSummary = asJsonRecord(summary);
  const summaryType = summaryString(safeSummary, "summary_type");
  if (summaryType === "model_plan_contract") {
    const uncertainties = summaryList(safeSummary?.uncertainties);
    const evidenceRefs = summaryList(safeSummary?.evidence_refs);
    const uiHints = asJsonRecord(safeSummary?.ui_hints);
    const toolReceipts = asJsonRecords(safeSummary?.tool_receipts);
    const rejectedActions = Array.isArray(safeSummary?.rejected_actions)
      ? safeSummary.rejected_actions.map(asJsonRecord).filter((item): item is JsonRecord => Boolean(item))
      : [];
    return (
      <details className="chat-work-summary chat-model-receipt" data-kind="model-plan" aria-label="Chat model plan summary">
        <summary>
          <span>
            <Sparkles size={14} />
            Live model used tools
          </span>
          <em>{toolReceipts.length} tool{toolReceipts.length === 1 ? "" : "s"}</em>
        </summary>
        <div>
          <article>
            <em>Confidence</em>
            <strong>{labelFromKey(summaryString(safeSummary, "confidence", "unknown"))}</strong>
          </article>
          <article>
            <em>Awaiting Adam</em>
            <strong>{safeSummary?.needs_user_response === false ? "No" : "Yes"}</strong>
          </article>
          <article>
            <em>Evidence refs</em>
            <strong>{evidenceRefs.length}</strong>
          </article>
          <article>
            <em>Tool calls</em>
            <strong>{toolReceipts.length}</strong>
          </article>
        </div>
        {uncertainties.length > 0 ? <p>Uncertainty: {uncertainties.slice(0, 2).join(" / ")}</p> : null}
        {toolReceipts.length > 0 ? (
          <div className="chat-tool-receipts" aria-label="Chat read tool receipts">
            {toolReceipts.slice(0, 4).map((receipt, index) => (
              <span key={`${summaryString(receipt, "tool_name", "tool")}-${index}`}>
                {labelFromKey(summaryString(receipt, "tool_name", "tool"))}: {toolReceiptDetail(receipt)}
              </span>
            ))}
          </div>
        ) : null}
        {Object.keys(uiHints ?? {}).length > 0 ? <p>UI hints: {Object.entries(uiHints ?? {}).map(([key, value]) => `${labelFromKey(key)} ${compactJsonValue(value)}`).join(" / ")}</p> : null}
        {rejectedActions.length > 0 ? (
          <p>Rejected action: {rejectedActions.map((action) => labelFromKey(summaryString(action, "type", "unsupported action"))).join(", ")}</p>
        ) : null}
      </details>
    );
  }
  if (["export_preview", "export_build_confirmation", "export_build_confirmed"].includes(summaryType)) {
    const previews = Array.isArray(safeSummary?.previews)
      ? safeSummary.previews.map(asJsonRecord).filter((item): item is JsonRecord => Boolean(item))
      : [];
    const primaryPreview = previews[0] ?? null;
    const previewRows = Array.isArray(primaryPreview?.preview_rows)
      ? primaryPreview.preview_rows.map(asJsonRecord).filter((item): item is JsonRecord => Boolean(item)).slice(0, 3)
      : [];
    const exportLabel =
      summaryString(safeSummary, "export_type", "export").toUpperCase() === "BOTH"
        ? "SFT + DPO"
        : summaryString(safeSummary, "export_type", "export").toUpperCase();
    return (
      <section className="chat-work-summary" aria-label="Chat work summary">
        <span>
          <FileText size={14} />
          {summaryType === "export_preview" ? "Export preview" : "Export build"}
        </span>
        <div>
          <article>
            <em>Format</em>
            <strong>{exportLabel || "JSONL"}</strong>
          </article>
          <article>
            <em>Included</em>
            <strong>{summaryNumber(safeSummary, "included_count")}</strong>
          </article>
          <article>
            <em>Excluded</em>
            <strong>{summaryNumber(safeSummary, "excluded_count")}</strong>
          </article>
        </div>
        <p>
          {summaryString(primaryPreview, "top_exclusion_reason")
            ? `Top exclusion: ${labelFromKey(summaryString(primaryPreview, "top_exclusion_reason"))}. ${summaryType === "export_build_confirmed" ? "Export build confirmed." : "No export was built yet."}`
            : summaryType === "export_build_confirmed"
              ? "Approved-only export build confirmed."
              : "Approved-only dry run. No export was built yet."}
        </p>
        {previewRows.length > 0 ? (
          <div className="chat-export-preview-rows">
            {previewRows.map((row, index) => (
              <article key={`${summaryString(row, "artifact_id", String(index))}-${index}`}>
                <em>{summaryString(row, "source_label", `Row ${index + 1}`)}</em>
                <strong>{labelFromKey(summaryString(row, "artifact_type", "training row"))}</strong>
              </article>
            ))}
          </div>
        ) : null}
      </section>
    );
  }
  if (summaryType === "action_dismissed") {
    return (
      <section className="chat-work-summary" aria-label="Chat work summary">
        <span>
          <XCircle size={14} />
          Action dismissed
        </span>
        <div>
          <article>
            <em>Action</em>
            <strong>{summaryString(safeSummary, "action_label", labelFromKey(summaryString(safeSummary, "action_type", "chat action")))}</strong>
          </article>
          <article>
            <em>State</em>
            <strong>Dismissed</strong>
          </article>
          <article>
            <em>Mutation</em>
            <strong>{safeSummary?.does_not_mutate_state === true ? "None" : "Unknown"}</strong>
          </article>
        </div>
        <p>No database write was applied for that pending action.</p>
      </section>
    );
  }
  if (summaryType !== "export_readiness") {
    return null;
  }
  const topItem = asJsonRecord(safeSummary?.top_item);
  const topAction = asJsonRecord(topItem?.action);
  const topTaskId = summaryString(topAction, "task_id");
  const orderedAreaKeys = Array.isArray(safeSummary?.ordered_area_keys) ? safeSummary.ordered_area_keys.map(String) : [];
  const itemCount = typeof safeSummary?.item_count === "number" ? safeSummary.item_count : orderedAreaKeys.length;
  return (
    <section className="chat-work-summary" aria-label="Chat work summary">
      <span>
        <FileText size={14} />
        Export readiness
      </span>
      <div>
        <article>
          <em>Open areas</em>
          <strong>{itemCount}</strong>
        </article>
        <article>
          <em>Top blocker</em>
          <strong>{summaryString(topItem, "area_label", "None")}</strong>
        </article>
        <article>
          <em>Area</em>
          <strong>{orderedAreaKeys.slice(0, 3).map(labelFromKey).join(", ") || "Clear"}</strong>
        </article>
      </div>
      <p>{summaryString(topItem, "summary", "No active bottleneck is reported by the current worklist.")}</p>
      {topTaskId ? (
        <button type="button" className="chat-work-summary-action" onClick={() => onOpenTask(topTaskId)}>
          Open top blocker
        </button>
      ) : null}
    </section>
  );
}

function ChatAuditPanel({ audit, loading, error }: { audit: ChatAuditResponse | null; loading: boolean; error: string | null }) {
  if (!audit && !loading && !error) {
    return null;
  }
  const gaps = audit?.quality_gaps ?? [];
  const provenance = asJsonRecord(audit?.provenance_links?.[0]);
  const sourceRefs = asJsonRecord(provenance?.source_refs);
  const sourceLabel = recordString(sourceRefs, "target_id") || recordString(provenance, "target_id");
  const latestAction = asJsonRecord(audit?.recent_actions?.[0]);
  const latestHash = audit?.latest_context_packet_hash ? shortId(audit.latest_context_packet_hash, 12) : "None yet";
  return (
    <section className="chat-audit-panel" aria-label="Chat audit trail">
      <span>
        <History size={14} />
        Audit trail
      </span>
      <div>
        <article>
          <em>Turns</em>
          <strong>{loading && !audit ? "Loading" : audit?.turn_count ?? 0}</strong>
        </article>
        <article>
          <em>Actions</em>
          <strong>{audit?.action_count ?? 0}</strong>
        </article>
        <article>
          <em>Results</em>
          <strong>{audit?.result_count ?? 0}</strong>
        </article>
        <article>
          <em>Hash</em>
          <strong>{latestHash}</strong>
        </article>
      </div>
      <p>
        {error
          ? error
          : sourceLabel
            ? `Linked source: ${sourceLabel}.`
            : latestAction
              ? `Latest action: ${labelFromKey(recordString(latestAction, "action_type", "chat action"))}.`
              : "No persisted action has been linked to this work item yet."}
      </p>
      <div className="chat-audit-gaps" aria-label="Chat audit quality gaps">
        {gaps.length > 0 ? gaps.slice(0, 4).map((gap) => <span key={gap}>{labelFromKey(gap)}</span>) : <span>No open gaps</span>}
      </div>
    </section>
  );
}

function ChatEvidenceShelf({
  corpus,
  loading,
  error
}: {
  corpus: EvidenceCorpusResponse | null;
  loading: boolean;
  error: string | null;
}) {
  if (!corpus && !loading && !error) {
    return null;
  }
  const familyCounts = Object.entries(corpus?.corpus_family_counts ?? {})
    .sort(([, left], [, right]) => right - left)
    .slice(0, 4);
  const records = corpus?.records ?? [];
  return (
    <section className="chat-evidence-shelf" aria-label="Reviewed evidence corpus">
      <span>
        <FileText size={14} />
        Evidence corpus
      </span>
      <div>
        <article>
          <em>Reviewed</em>
          <strong>{loading && !corpus ? "Loading" : corpus?.record_count ?? 0}</strong>
        </article>
        <article>
          <em>Held</em>
          <strong>{corpus?.excluded_count ?? 0}</strong>
        </article>
        <article>
          <em>Vectors</em>
          <strong>{corpus?.vector_ready_count ?? 0}</strong>
        </article>
      </div>
      {error ? <p>{error}</p> : null}
      {familyCounts.length > 0 ? (
        <div className="chat-evidence-families" aria-label="Evidence families">
          {familyCounts.map(([family, count]) => (
            <span key={family}>
              {labelFromKey(family)} <strong>{count}</strong>
            </span>
          ))}
        </div>
      ) : null}
      {records.length > 0 ? (
        <div className="chat-evidence-records" aria-label="Reviewed evidence records">
          {records.slice(0, 3).map((record) => (
            <article key={record.embedding_record_id}>
              <em>{labelFromKey(record.corpus_family)}</em>
              <strong>{previewText(record.title, 82) || shortId(record.target_id, 8)}</strong>
              <p>{previewText(record.input_preview, 120)}</p>
            </article>
          ))}
        </div>
      ) : null}
    </section>
  );
}

function ChatEvidenceClusterPanel({
  clusters,
  loading,
  error,
  busy,
  onReviewCluster,
  compact = false
}: {
  clusters: EvidenceClustersResponse | null;
  loading: boolean;
  error: string | null;
  busy: boolean;
  onReviewCluster: (cluster: EvidenceCluster) => void;
  compact?: boolean;
}) {
  if (!clusters && !loading && !error) {
    return null;
  }
  const items = clusters?.clusters ?? [];
  const visibleItems = compact ? items.slice(0, 1) : items.slice(0, 3);
  const hiddenItems = compact ? items.slice(1, 4) : [];
  const renderCluster = (cluster: EvidenceCluster) => {
    const topRecords = cluster.top_records ?? [];
    const matchedTerms = (cluster.matched_terms ?? []).map(String).filter(Boolean);
    const reviewType = evidenceClusterReviewType(cluster);
    return (
      <article key={cluster.cluster_id || cluster.cluster_key}>
        <div>
          <em>{labelFromKey(cluster.cluster_family)}</em>
          <strong>{compact ? "Best source match" : `${cluster.record_count} records`}</strong>
        </div>
        <h3>{previewText(cluster.display_title, 88) || shortId(cluster.cluster_key, 14)}</h3>
        {reviewType ? (
          <button
            type="button"
            aria-label={`Review evidence cluster ${cluster.display_title}`}
            onClick={() => onReviewCluster(cluster)}
            disabled={busy}
          >
            Review
          </button>
        ) : (
          <span className="chat-evidence-cluster-reference">Reference evidence</span>
        )}
        <p>{previewText(cluster.planning_hint, compact ? 100 : 150)}</p>
        {!compact && matchedTerms.length > 0 ? (
          <div className="chat-evidence-cluster-terms" aria-label="Cluster matched terms">
            {matchedTerms.slice(0, 4).map((term) => (
              <span key={term}>{term}</span>
            ))}
          </div>
        ) : null}
        {topRecords.length > 0 ? (
          <ul aria-label="Top cluster records">
            {topRecords.slice(0, compact ? 1 : 2).map((record) => (
              <li key={record.embedding_record_id}>
                <strong>{previewText(record.title, 76) || shortId(record.target_id, 8)}</strong>
                <span>{previewText(record.input_preview, compact ? 86 : 110)}</span>
              </li>
            ))}
          </ul>
        ) : null}
      </article>
    );
  };
  return (
    <section className="chat-evidence-cluster-panel" data-compact={compact ? "true" : "false"} aria-label="Ranked evidence clusters">
      <header>
        <span>
          <Sparkles size={14} />
          Evidence
        </span>
        <em>{loading && !clusters ? "Loading" : compact ? "best match" : `${clusters?.cluster_count ?? 0} clusters`}</em>
      </header>
      <p>
        {error
          ? error
          : clusters
            ? compact
              ? "Most relevant reviewed source for this item."
              : `Query: ${previewText(clusters.query, 150)}`
            : "Loading reviewed document, photo, and voice clusters for this item."}
      </p>
      {items.length > 0 ? (
        <>
          <div className="chat-evidence-cluster-grid">{visibleItems.map(renderCluster)}</div>
          {hiddenItems.length > 0 ? (
            <details className="chat-more-evidence">
              <summary>More evidence</summary>
              <div className="chat-evidence-cluster-grid">{hiddenItems.map(renderCluster)}</div>
            </details>
          ) : null}
        </>
      ) : !loading && !error ? (
        <p>No reviewed evidence cluster matched this item yet.</p>
      ) : null}
    </section>
  );
}

function ChatContextPanel({
  task,
  asset,
  sourceAsset,
  draftDecisions,
  workSurface,
  photoPreviewAccessToken
}: {
  task: Task | null;
  asset?: Asset;
  sourceAsset?: Asset;
  draftDecisions?: JsonRecord;
  workSurface?: JsonRecord;
  photoPreviewAccessToken?: string;
}) {
  if (!task) {
    return (
      <section className="chat-context-panel" aria-label="Chat work item context">
        <div className="chat-context-empty">
          <MessageCircle size={18} />
          <span>Select an item from the worklist to start a focused conversation.</span>
        </div>
      </section>
    );
  }

  const payload = task.input_payload ?? {};
  const decisions = { ...payload, ...(draftDecisions ?? {}) };
  const activePhotoId = sourcePhotoId(task);
  const title =
    payloadString(decisions, "asset_title") ||
    payloadString(decisions, "source_photo_title") ||
    payloadString(decisions, "source_title") ||
    payloadString(decisions, "source_filename") ||
    asset?.title ||
    asset?.original_filename ||
    sourceAsset?.title ||
    sourceAsset?.original_filename ||
    task.human_id;

  if (isPhotoChatTask(task)) {
    const visiblePeople = [
      ...payloadList(payload, "visible_people"),
      ...payloadList(payload, "machine_guess_people"),
      ...payloadList(payload, "people")
    ];
    const objects = [
      ...payloadList(payload, "concrete_objects"),
      ...payloadList(payload, "machine_guess_objects"),
      ...payloadList(payload, "objects")
    ];
    return (
      <section className="chat-context-panel has-photo" aria-label="Chat work item context">
        <div className="chat-photo-preview">
          {activePhotoId ? (
            <img src={getAssetPreviewUrl(activePhotoId, "display", photoPreviewAccessToken)} alt={title} />
          ) : (
            <div>
              <Image size={24} />
              <span>No preview image is attached to this item.</span>
            </div>
          )}
        </div>
        <div className="chat-context-details">
          <span>
            <Image size={14} />
            Photo item
          </span>
          <strong>{title}</strong>
          <div className="chat-context-facts">
            <article>
              <em>Visible people</em>
              <p>{visiblePeople.slice(0, 6).join(", ") || "Needs Adam confirmation"}</p>
            </article>
            <article>
              <em>Objects / scene</em>
              <p>{objects.slice(0, 8).join(", ") || "Needs Adam confirmation"}</p>
            </article>
          </div>
          <ShortText value={payloadString(payload, "visual_summary") || payloadString(payload, "description")} fallback="Use the image and Adam's answers to separate visible facts from memory." />
          <ChatContextStatus task={task} decisions={decisions} draftDecisions={draftDecisions} />
        </div>
      </section>
    );
  }

  if (isPromptPairTask(task)) {
    const artifactMode = promptPairArtifactMode(task, workSurface);
    const fieldContract = promptPairFieldContract(workSurface);
    const acceptedField = recordString(fieldContract, "accepted_response_field", artifactMode === "dpo" ? "chosen" : "content");
    const rejectedField = recordString(fieldContract, "rejected_response_field", "rejected");
    const prompt = payloadString(decisions, "prompt");
    const content = payloadString(decisions, "content") || payloadString(decisions, "adam_gold_edit");
    const chosen = payloadString(decisions, "chosen") || content;
    const rejected = payloadString(decisions, "rejected") || payloadString(decisions, "model_draft");
    const acceptedResponse = acceptedField === "chosen" ? chosen : content || chosen;
    const gridMode = artifactMode === "dpo" ? "dpo" : rejected ? "sft_with_rejected" : "sft";
    return (
      <section className="chat-context-panel prompt-review" aria-label="Chat work item context">
        {payloadString(payload, "source_photo_id") ? (
          <div className="chat-source-thumb">
            <img src={getAssetPreviewUrl(payloadString(payload, "source_photo_id"), "thumbnail", photoPreviewAccessToken)} alt={title} />
          </div>
        ) : null}
        <div className="chat-context-details">
          <span>
            <FileText size={14} />
            {artifactMode.toUpperCase()} candidate
          </span>
          <strong>{title}</strong>
          <div className="chat-pair-grid" data-mode={gridMode}>
            <article>
              <em>Prompt Adam is reviewing</em>
              <ShortText value={prompt} />
            </article>
            {artifactMode === "dpo" ? (
              <>
                <article>
                  <em>Chosen / preferred</em>
                  <ShortText value={chosen} />
                </article>
                <article>
                  <em>Rejected / weaker</em>
                  <ShortText value={rejected} />
                </article>
              </>
            ) : (
              <>
                <article>
                  <em>{promptPairFieldLabel(acceptedField, task, workSurface)}</em>
                  <ShortText value={acceptedResponse} />
                </article>
                {rejected ? (
                  <article>
                    <em>{promptPairFieldLabel(rejectedField, task, workSurface)}</em>
                    <ShortText value={rejected} />
                  </article>
                ) : null}
              </>
            )}
          </div>
          <ChatContextStatus task={task} decisions={decisions} draftDecisions={draftDecisions} />
        </div>
      </section>
    );
  }

  if (isSourceReviewTask(task)) {
    const excerpt =
      payloadString(decisions, "preview_text") ||
      payloadString(decisions, "source_excerpt") ||
      payloadString(decisions, "content") ||
      payloadString(decisions, "text");
    const sourceGenre = payloadString(decisions, "source_genre");
    const authorship = payloadString(decisions, "authorship");
    const truthStatus = payloadString(decisions, "truth_status");
    const privacyLevel = payloadString(decisions, "privacy_level");
    const voicePresence = payloadString(decisions, "voice_presence") || payloadString(decisions, "charles_voice_presence");
    const downstreamUse = [
      payloadString(decisions, "usable_for_voice_context") ? `Voice ${payloadString(decisions, "usable_for_voice_context")}` : "",
      payloadString(decisions, "usable_for_grounded_generation") ? `Grounded ${payloadString(decisions, "usable_for_grounded_generation")}` : "",
      payloadString(decisions, "generate_pairs_on_submit") ? `Pairs ${payloadString(decisions, "generate_pairs_on_submit")}` : ""
    ].filter(Boolean);
    return (
      <section className="chat-context-panel source-review" aria-label="Chat work item context">
        <div className="chat-context-details">
          <span>
            <FileText size={14} />
            Source excerpt
          </span>
          <strong>{title}</strong>
          <div className="chat-pair-grid">
            <article>
              <em>Source document</em>
              <ShortText value={payloadString(decisions, "source_title") || payloadString(decisions, "source_filename") || task.human_id} />
            </article>
            <article>
              <em>Excerpt Adam is reviewing</em>
              <ShortText value={excerpt} />
            </article>
          </div>
          <div className="chat-context-facts">
            <article>
              <em>Known details</em>
              <p>
                {[sourceGenre, authorship, truthStatus]
                  .filter(Boolean)
                  .map(labelFromKey)
                  .join(" / ") || "Needs classification"}
              </p>
            </article>
            <article>
              <em>Current classification</em>
              <p>
                {[voicePresence && labelFromKey(voicePresence), privacyLevel && labelFromKey(privacyLevel), downstreamUse.join(", ")]
                  .filter(Boolean)
                  .join(" / ") || "No downstream decision yet"}
              </p>
            </article>
          </div>
          <ChatContextStatus task={task} decisions={decisions} draftDecisions={draftDecisions} />
        </div>
      </section>
    );
  }

  return (
    <section className="chat-context-panel" aria-label="Chat work item context">
      <div className="chat-context-details">
        <span>
          <FileText size={14} />
          Review item
        </span>
        <strong>{title}</strong>
        <ShortText
          value={
            payloadString(payload, "preview_text") ||
            payloadString(payload, "source_excerpt") ||
            payloadString(payload, "content") ||
            payloadString(payload, "context")
          }
          fallback="Use the conversation to capture the next review decision."
        />
        <ChatContextStatus task={task} decisions={decisions} draftDecisions={draftDecisions} />
      </div>
    </section>
  );
}

function ChatContextStrip({
  task,
  asset,
  sourceAsset,
  draftDecisions,
  workSurface,
  photoPreviewAccessToken,
  workSummary,
  evidenceClusters,
  evidenceClustersLoading,
  evidenceClustersError,
  evidenceBusy,
  onReviewCluster,
  evidenceCorpus,
  evidenceLoading,
  evidenceError,
  audit,
  auditLoading,
  auditError,
  onOpenTask
}: {
  task: Task | null;
  asset?: Asset;
  sourceAsset?: Asset;
  draftDecisions?: JsonRecord;
  workSurface?: JsonRecord;
  photoPreviewAccessToken?: string;
  workSummary?: JsonRecord;
  evidenceClusters: EvidenceClustersResponse | null;
  evidenceClustersLoading: boolean;
  evidenceClustersError: string | null;
  evidenceBusy: boolean;
  onReviewCluster: (cluster: EvidenceCluster) => void;
  evidenceCorpus: EvidenceCorpusResponse | null;
  evidenceLoading: boolean;
  evidenceError: string | null;
  audit: ChatAuditResponse | null;
  auditLoading: boolean;
  auditError: string | null;
  onOpenTask: (taskId: string) => void;
}) {
  return (
    <details className="chat-context-strip" open>
      <summary>
        <span>Context</span>
        <strong>{task ? taskTitle(task) : "Choose an item"}</strong>
      </summary>
      <div className="chat-context-strip-body">
        <ChatContextPanel
          task={task}
          asset={asset}
          sourceAsset={sourceAsset}
          draftDecisions={draftDecisions}
          workSurface={workSurface}
          photoPreviewAccessToken={photoPreviewAccessToken}
        />
        <ChatEvidenceClusterPanel
          clusters={evidenceClusters}
          loading={evidenceClustersLoading}
          error={evidenceClustersError}
          busy={evidenceBusy}
          onReviewCluster={onReviewCluster}
          compact
        />
        <details className="chat-provenance-drawer">
          <summary>Provenance</summary>
          <ChatWorkSummaryPanel summary={workSummary} onOpenTask={onOpenTask} />
          <ChatEvidenceShelf corpus={evidenceCorpus} loading={evidenceLoading} error={evidenceError} />
          <ChatAuditPanel audit={audit} loading={auditLoading} error={auditError} />
        </details>
      </div>
    </details>
  );
}

function initialAssistantMessage(task: Task | null): string {
  if (!task) {
    return "Which item should we work through first?";
  }
  if (isPhotoChatTask(task)) {
    return "I’m showing you this photo. What can you tell me about who or what is visible, starting only with what you know for sure?";
  }
  if (isPromptPairTask(task)) {
    return promptPairMode(task) === "dpo"
      ? "I’m showing you the prompt plus chosen and rejected responses. What feels stronger, weaker, generic, wrong, or missing?"
      : "I’m showing you the prompt and draft response. How does the response sound, and what should we rewrite before it becomes gold?";
  }
  return "What should we decide for this item?";
}

export function ChatWorkbench({
  tasks,
  assets,
  selectedTask,
  photoPreviewAccessToken,
  onOpenTask,
  onSubmitted,
  onViewTrainingBoard,
  onRefresh
}: ChatWorkbenchProps) {
  const [activeTaskId, setActiveTaskId] = useState<string | null>(selectedTask?.id ?? null);
  const [sessionId, setSessionId] = useState<string | null>(() => storedSessionId());
  const [hydratedSessionId, setHydratedSessionId] = useState<string | null>(null);
  const [recentSessions, setRecentSessions] = useState<JsonRecord[]>([]);
  const [messages, setMessages] = useState<LocalChatMessage[]>([
    {
      role: "assistant",
      content: initialAssistantMessage(selectedTask)
    }
  ]);
  const [draftDecisions, setDraftDecisions] = useState<JsonRecord>({});
  const [notes, setNotes] = useState<string | null>(null);
  const [input, setInput] = useState("");
  const [lastResponse, setLastResponse] = useState<ChatTurnResponse | null>(null);
  const [audit, setAudit] = useState<ChatAuditResponse | null>(null);
  const [auditLoading, setAuditLoading] = useState(false);
  const [auditError, setAuditError] = useState<string | null>(null);
  const [evidenceCorpus, setEvidenceCorpus] = useState<EvidenceCorpusResponse | null>(null);
  const [evidenceLoading, setEvidenceLoading] = useState(false);
  const [evidenceError, setEvidenceError] = useState<string | null>(null);
  const [evidenceClusters, setEvidenceClusters] = useState<EvidenceClustersResponse | null>(null);
  const [evidenceClustersLoading, setEvidenceClustersLoading] = useState(false);
  const [evidenceClustersError, setEvidenceClustersError] = useState<string | null>(null);
  const [modelStatus, setModelStatus] = useState<ModelStatus | null>(null);
  const [actionPreviewState, setActionPreviewState] = useState<{
    actionId: string;
    staleReason: string | null;
    canConfirm: boolean;
    loading: boolean;
    previewPayload: JsonRecord | null;
  } | null>(null);
  const [busy, setBusy] = useState(false);
  const [busyMessage, setBusyMessage] = useState("Thinking through the current item.");
  const [error, setError] = useState<string | null>(null);
  const scrollRef = useRef<HTMLDivElement | null>(null);
  const selectedTaskIdRef = useRef<string | null>(selectedTask?.id ?? null);

  const activeTask = useMemo(
    () => tasks.find((task) => task.id === activeTaskId) ?? selectedTask,
    [activeTaskId, selectedTask, tasks]
  );
  const activeAsset = useMemo(() => findAsset(assets, taskAssetId(activeTask)), [activeTask, assets]);
  const activeSourceAsset = useMemo(() => findAsset(assets, sourcePhotoId(activeTask)), [activeTask, assets]);
  const activeEvidenceClusterQuery = useMemo(
    () => evidenceClusterQuery(activeTask, lastResponse),
    [activeTask, lastResponse?.active_task?.id, lastResponse?.active_task?.title, lastResponse?.turn_id]
  );

  useEffect(() => {
    let cancelled = false;
    listChatSessions("adam", 8)
      .then((payload) => {
        if (!cancelled) {
          setRecentSessions(payload.sessions ?? []);
        }
      })
      .catch(() => {
        if (!cancelled) {
          setRecentSessions([]);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [sessionId, lastResponse?.turn_id]);

  useEffect(() => {
    const nextTaskId = selectedTask?.id ?? null;
    if (selectedTaskIdRef.current === nextTaskId) {
      return;
    }
    selectedTaskIdRef.current = nextTaskId;
    setActiveTaskId(nextTaskId);
    setSessionId(null);
    setHydratedSessionId(null);
    persistSessionId(null);
    setDraftDecisions({});
    setNotes(null);
    setLastResponse(null);
    setAudit(null);
    setAuditError(null);
    setError(null);
    setMessages([
      {
        role: "assistant",
        content: initialAssistantMessage(selectedTask)
      }
    ]);
  }, [selectedTask]);

  useEffect(() => {
    if (!sessionId || hydratedSessionId === sessionId) {
      return;
    }
    let cancelled = false;
    getChatSession(sessionId)
      .then((payload) => {
        if (cancelled) {
          return;
        }
        const storedMessages = payload.turns.map(storedTurnMessage).filter((message): message is LocalChatMessage => Boolean(message));
        if (storedMessages.length > 0) {
          setMessages(storedMessages);
        }
        if (payload.latest_response) {
          setLastResponse(payload.latest_response);
          setDraftDecisions(payload.latest_response.draft_decisions ?? {});
          setNotes(responseDraftNotes(payload.latest_response));
        }
        const restoredTaskId = payload.session.active_task_id;
        if (typeof restoredTaskId === "string" && restoredTaskId) {
          setActiveTaskId(restoredTaskId);
          selectedTaskIdRef.current = restoredTaskId;
          onOpenTask(restoredTaskId);
        }
        setHydratedSessionId(sessionId);
      })
      .catch(() => {
        if (cancelled) {
          return;
        }
        persistSessionId(null);
        setSessionId(null);
        setHydratedSessionId(null);
      });
    return () => {
      cancelled = true;
    };
  }, [hydratedSessionId, onOpenTask, sessionId]);

  useEffect(() => {
    const taskId = activeTask?.id ?? responseTaskId(lastResponse) ?? null;
    if (!taskId && !sessionId) {
      setAudit(null);
      setAuditError(null);
      setAuditLoading(false);
      return;
    }
    let cancelled = false;
    setAuditLoading(true);
    setAuditError(null);
    getChatAudit({ taskId, sessionId, limit: 8 })
      .then((payload) => {
        if (cancelled) {
          return;
        }
        setAudit(payload);
      })
      .catch((caught) => {
        if (cancelled) {
          return;
        }
        setAuditError(caught instanceof Error ? caught.message : "Could not load chat audit trail.");
      })
      .finally(() => {
        if (!cancelled) {
          setAuditLoading(false);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [activeTask?.id, lastResponse?.context_packet_hash, lastResponse?.turn_id, sessionId]);

  useEffect(() => {
    scrollRef.current?.scrollIntoView({ block: "end" });
  }, [messages, busy]);

  useEffect(() => {
    let cancelled = false;
    setEvidenceLoading(true);
    setEvidenceError(null);
    getEvidenceCorpus("family_private", 8)
      .then((payload) => {
        if (!cancelled) {
          setEvidenceCorpus(payload);
        }
      })
      .catch((caught) => {
        if (!cancelled) {
          setEvidenceError(caught instanceof Error ? caught.message : "Could not load reviewed evidence corpus.");
        }
      })
      .finally(() => {
        if (!cancelled) {
          setEvidenceLoading(false);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [lastResponse?.turn_id]);

  useEffect(() => {
    if (!activeEvidenceClusterQuery.trim()) {
      setEvidenceClusters(null);
      setEvidenceClustersError(null);
      setEvidenceClustersLoading(false);
      return;
    }
    let cancelled = false;
    setEvidenceClustersLoading(true);
    setEvidenceClustersError(null);
    getEvidenceClusters({ query: activeEvidenceClusterQuery, scope: "family_private", limit: 4, perClusterLimit: 3 })
      .then((payload) => {
        if (!cancelled) {
          setEvidenceClusters(payload);
        }
      })
      .catch((caught) => {
        if (!cancelled) {
          setEvidenceClustersError(caught instanceof Error ? caught.message : "Could not load evidence clusters.");
          setEvidenceClusters(null);
        }
      })
      .finally(() => {
        if (!cancelled) {
          setEvidenceClustersLoading(false);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [activeEvidenceClusterQuery]);

  useEffect(() => {
    let cancelled = false;
    getModelStatus()
      .then((status) => {
        if (!cancelled) {
          setModelStatus(status);
        }
      })
      .catch(() => {
        if (!cancelled) {
          setModelStatus(null);
        }
      });
    return () => {
      cancelled = true;
    };
  }, []);

  async function runTurn(message: string, options?: { confirmSubmit?: boolean; confirmAction?: JsonRecord; dismissAction?: JsonRecord }) {
    const trimmed = message.trim();
    if (!trimmed && !options?.confirmSubmit && !options?.confirmAction && !options?.dismissAction) {
      return;
    }
    const history = messages.map(({ role, content }) => ({ role, content }));
    const isActionResolution = Boolean(options?.confirmSubmit || options?.confirmAction || options?.dismissAction);
    const userMessage: LocalChatMessage | null = isActionResolution ? null : { role: "user", content: trimmed };
    if (userMessage) {
      setMessages((current) => [...current, userMessage]);
    }
    setBusyMessage(
      options?.dismissAction
        ? "Dismissing pending action."
        : options?.confirmSubmit || options?.confirmAction
          ? "Applying confirmed action."
          : "Thinking through the current item."
    );
    setBusy(true);
    setError(null);
    try {
      const pendingSubmitAction = lastResponse?.actions.find(
        (action) => actionString(action, "type") === "submit_task" && actionString(action, "status") === "pending_confirmation" && actionString(action, "id")
      );
      const confirmAction = options?.confirmAction;
      const dismissAction = options?.dismissAction;
      const confirmActionType = actionString(confirmAction, "type");
      const dismissActionId = actionString(dismissAction, "id");
      const confirmActionId =
        actionString(confirmAction, "id") || dismissActionId || (options?.confirmSubmit && pendingSubmitAction ? actionString(pendingSubmitAction, "id") : null);
      const commandPayload = { message: trimmed, session_id: sessionId, mode: "chat", user_id: "adam" };
      const response = dismissActionId
        ? await dismissChatAction(dismissActionId, { ...commandPayload, message: trimmed || "dismiss" })
        : confirmActionId && (options?.confirmSubmit || confirmAction)
          ? await confirmChatAction(confirmActionId, { ...commandPayload, message: trimmed || "confirm" })
          : await sendChatTurn({
              message: trimmed || "ready",
              session_id: sessionId,
              task_id: activeTask?.id ?? activeTaskId,
              mode: "chat",
              history,
              draft_decisions: draftDecisions,
              notes,
              apply_updates: true,
              confirm_action: Boolean(confirmAction && confirmActionType !== "submit_task"),
              confirm_submit: Boolean(options?.confirmSubmit || confirmActionType === "submit_task"),
              dismiss_action: Boolean(dismissAction),
              confirm_action_id: confirmActionId,
              user_id: "adam"
            });
      setLastResponse(response);
      if (response.session_id) {
        setSessionId(response.session_id);
        setHydratedSessionId(response.session_id);
        persistSessionId(response.session_id);
      }
      setDraftDecisions(response.draft_decisions ?? {});
      setNotes(responseDraftNotes(response));
      const nextTaskId = responseTaskId(response);
      if (nextTaskId) {
        setActiveTaskId(nextTaskId);
        onOpenTask(nextTaskId);
      }
      if (response.submitted_annotation) {
        onSubmitted(response.submitted_annotation);
        await onRefresh();
      }
      if (response.built_export) {
        await onRefresh();
      }
      setMessages((current) => [
        ...current,
        {
          role: "assistant",
          content: response.assistant_message,
          status: response.status,
          actions: response.actions,
          fieldUpdates: response.field_updates,
          patchResult: response.patch_result
        }
      ]);
      setInput("");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Chat turn failed.");
    } finally {
      setBusy(false);
      setBusyMessage("Thinking through the current item.");
    }
  }

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    await runTurn(input);
  }

  function handleEvidenceClusterReview(cluster: EvidenceCluster) {
    if (busy) {
      return;
    }
    void runTurn(evidenceClusterReviewPrompt(cluster));
  }

  function handleComposerKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key !== "Enter" || event.shiftKey || event.metaKey || event.ctrlKey || event.altKey) {
      return;
    }
    event.preventDefault();
    if (!busy && input.trim()) {
      void runTurn(input);
    }
  }

  async function handleNewChat() {
    setBusy(true);
    setError(null);
    try {
      const payload = await createChatSession({
        user_id: "adam",
        mode: "chat",
        active_task_id: activeTask?.id ?? null,
        title: activeTask ? `Chat: ${activeTask.human_id}` : "Chat"
      });
      const newSessionId = typeof payload.session.id === "string" ? payload.session.id : null;
      setSessionId(newSessionId);
      setHydratedSessionId(newSessionId);
      persistSessionId(newSessionId);
      setActiveTaskId(activeTask?.id ?? null);
      setMessages([{ role: "assistant", content: initialAssistantMessage(activeTask) }]);
      setDraftDecisions({});
      setNotes(null);
      setInput("");
      setLastResponse(payload.latest_response ?? null);
      setAudit(null);
      setAuditError(null);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Could not create a new chat session.");
    } finally {
      setBusy(false);
    }
  }

  function handleRecentSessionChange(value: string) {
    if (!value || value === sessionId) {
      return;
    }
    setSessionId(value);
    setHydratedSessionId(null);
    persistSessionId(value);
    setError(null);
  }

  const updateRows = Object.entries(lastResponse?.field_updates ?? {});
  const readyToSubmit = lastResponse?.ready_to_submit === true && Boolean(lastResponse?.submit_payload);
  const pendingActions = (lastResponse?.actions ?? []).filter((action) => actionString(action, "status") === "pending_confirmation");
  const primaryPendingAction = pendingActions[0];
  const primaryPendingActionId = actionString(primaryPendingAction, "id");
  const submitPayload = asJsonRecord(lastResponse?.submit_payload);
  const exportBuildPayload = asJsonRecord(lastResponse?.export_build_payload);
  const pendingActionPreviewApplies = actionPreviewState?.actionId === primaryPendingActionId ? actionPreviewState : null;
  const authoritativePreviewPayload = asJsonRecord(pendingActionPreviewApplies?.previewPayload);
  const authoritativeSubmitPayload = asJsonRecord(authoritativePreviewPayload?.submit_payload);
  const authoritativeExportBuildPayload = asJsonRecord(authoritativePreviewPayload?.export_build_payload);
  const submitDecisions = asJsonRecord(authoritativeSubmitPayload?.decisions) ?? asJsonRecord(submitPayload?.decisions);
  const pendingPreviewPayload =
    actionString(primaryPendingAction, "type") === "build_dataset_export"
      ? (authoritativeExportBuildPayload ?? exportBuildPayload)
      : submitDecisions;
  const authoritativeFieldDiffRows = asJsonRecords(authoritativePreviewPayload?.field_diffs);
  const fieldDiffRows = (authoritativeFieldDiffRows.length > 0 ? authoritativeFieldDiffRows : asJsonRecords(lastResponse?.field_diffs)).slice(0, 8);
  const pendingActionStaleReason = pendingActionPreviewApplies?.staleReason ?? null;
  const readyToConfirmPendingAction = Boolean(primaryPendingActionId) && !pendingActionPreviewApplies?.loading && pendingActionPreviewApplies?.canConfirm !== false;
  const readyToDismissPendingAction = Boolean(primaryPendingActionId);
  const pendingActionStatusText = pendingActionPreviewApplies?.loading
    ? "Checking action freshness."
    : pendingActionStaleReason
      ? pendingActionStaleReason
      : pendingActions.length === 1
        ? "Ready for Adam confirmation."
        : `${pendingActions.length} pending confirmations.`;
  const taskSelectionLabel = responseTaskSelection(lastResponse);
  const liveRequiredBlocked = lastResponse?.status === "live_model_required_not_ready" || lastResponse?.status === "live_error_blocked";
  const submittedRows = submittedArtifactRows(lastResponse?.submitted_annotation);
  const batchContinuation = asJsonRecord(lastResponse?.batch_continuation);
  const continuedTaskHumanId = stringValue(batchContinuation?.next_task_human_id);
  const liveReady = modelStatus?.text_generation_live_ready === true;
  const modelBadge = lastResponse?.live_model_call_used
    ? "Live LLM"
    : liveRequiredBlocked
      ? "Live required"
    : liveReady
      ? "Live ready"
    : lastResponse?.model_ready
      ? "LLM fallback"
      : "LLM gated";
  const modelName = lastResponse?.model_name || modelStatus?.text_generation_model || "";
  const responseWorkSurface = asJsonRecord(lastResponse?.work_surface) ?? undefined;
  const pendingPreviewRows = orderedPreviewRows(activeTask, pendingPreviewPayload, responseWorkSurface).slice(0, 8);

  useEffect(() => {
    if (!primaryPendingActionId) {
      setActionPreviewState(null);
      return;
    }
    let cancelled = false;
    setActionPreviewState({
      actionId: primaryPendingActionId,
      staleReason: null,
      canConfirm: false,
      loading: true,
      previewPayload: null
    });
    previewChatAction(primaryPendingActionId, { session_id: sessionId, user_id: "adam" })
      .then((payload) => {
        if (cancelled) {
          return;
        }
        setActionPreviewState({
          actionId: primaryPendingActionId,
          staleReason: typeof payload.stale_reason === "string" ? payload.stale_reason : null,
          canConfirm: payload.can_confirm === true,
          loading: false,
          previewPayload: asJsonRecord(payload.preview_payload)
        });
      })
      .catch((caught) => {
        if (cancelled) {
          return;
        }
        setActionPreviewState({
          actionId: primaryPendingActionId,
          staleReason: caught instanceof Error ? caught.message : "Could not refresh this action preview.",
          canConfirm: false,
          loading: false,
          previewPayload: null
        });
      });
    return () => {
      cancelled = true;
    };
  }, [primaryPendingActionId, sessionId]);

  return (
    <section className="chat-workbench" aria-label="Chat operator">
      <header className="chat-workbench-header">
        <div>
          <span>
            <MessageCircle size={15} />
            Chat
          </span>
          <h2>{taskTitle(activeTask)}</h2>
          <p>
            {activeTask ? `${labelFromKey(activeTask.task_type)}` : "Pick a ready item from the worklist."}
            {taskSelectionLabel ? ` / ${taskSelectionLabel}` : ""}
          </p>
        </div>
        <div className="chat-status-stack">
          <button type="button" onClick={() => void handleNewChat()} disabled={busy}>
            <Plus size={14} />
            New chat
          </button>
          {recentSessions.length > 0 ? (
            <select
              aria-label="Recent chat sessions"
              value={sessionId ?? ""}
              onChange={(event) => handleRecentSessionChange(event.target.value)}
              disabled={busy}
            >
              <option value="">Recent chats</option>
              {recentSessions.map((session) => {
                const id = recordString(session, "id");
                return id ? (
                  <option key={id} value={id}>
                    {sessionOptionLabel(session)}
                  </option>
                ) : null;
              })}
            </select>
          ) : null}
          <span data-live={lastResponse?.live_model_call_used || liveReady ? "true" : "false"}>{modelBadge}</span>
          {modelName ? <em>{modelName}</em> : null}
        </div>
      </header>

      <ChatContextStrip
        task={activeTask}
        asset={activeAsset}
        sourceAsset={activeSourceAsset}
        draftDecisions={draftDecisions}
        workSurface={responseWorkSurface}
        photoPreviewAccessToken={photoPreviewAccessToken}
        workSummary={lastResponse?.work_summary}
        evidenceClusters={evidenceClusters}
        evidenceClustersLoading={evidenceClustersLoading}
        evidenceClustersError={evidenceClustersError}
        evidenceBusy={busy}
        onReviewCluster={handleEvidenceClusterReview}
        evidenceCorpus={evidenceCorpus}
        evidenceLoading={evidenceLoading}
        evidenceError={evidenceError}
        audit={audit}
        auditLoading={auditLoading}
        auditError={auditError}
        onOpenTask={onOpenTask}
      />

      <div className="chat-body" role="log" aria-label="Chat messages" aria-live="polite" aria-relevant="additions text">
        {messages.map((message, index) => (
          <article key={`${message.role}-${index}`} className="chat-message" data-role={message.role}>
            <div>
              <span>{message.role === "user" ? "Adam" : "Chat"}</span>
              {message.status ? <em>{labelFromKey(message.status)}</em> : null}
            </div>
            <p>{message.content}</p>
            {message.fieldUpdates && Object.keys(message.fieldUpdates).length > 0 ? (
              <div className="chat-update-strip" aria-label="Draft updates">
                {Object.entries(message.fieldUpdates).map(([key, value]) => (
                  <span key={key}>
                    <strong>{promptPairFieldLabel(key, activeTask, responseWorkSurface)}</strong>
                    <em>{compactJsonValue(value)}</em>
                  </span>
                ))}
              </div>
            ) : null}
            {patchDiffRows(message).length > 0 ? (
              <div className="chat-patch-strip" aria-label="Applied draft patch">
                {patchDiffRows(message).map((diff, diffIndex) => {
                  const field = recordString(diff, "field") || `field_${diffIndex}`;
                  return (
                    <span key={`${field}-${diffIndex}`}>
                      <strong>{promptPairFieldLabel(field, activeTask, responseWorkSurface)}</strong>
                      <em>{labelFromKey(recordString(diff, "change_type", "changed"))}</em>
                    </span>
                  );
                })}
              </div>
            ) : patchBlockedReason(message) ? (
              <div className="chat-patch-strip" data-state="blocked" aria-label="Blocked draft patch">
                <span>
                  <strong>Patch blocked</strong>
                  <em>{patchBlockedReason(message)}</em>
                </span>
              </div>
            ) : null}
          </article>
        ))}
        {busy ? (
          <article className="chat-message" data-role="assistant" role="status" aria-live="polite" aria-atomic="true">
            <div>
              <span>Chat</span>
              <em>Working</em>
            </div>
            <p>{busyMessage}</p>
          </article>
        ) : null}
        <div ref={scrollRef} />
      </div>

      {error ? (
        <div className="chat-error" role="alert">
          {error}
        </div>
      ) : null}

      {pendingActions.length > 0 ? (
        <section className="chat-action-preview" aria-label="Pending chat action preview" aria-live="polite">
          <span>
            <CheckCircle2 size={14} />
            Pending action
          </span>
          <div className="chat-action-preview-main">
            <div>
              <strong>{actionString(pendingActions[0], "label", labelFromKey(actionString(pendingActions[0], "type", "pending_action")))}</strong>
              <p>{pendingActionStatusText}</p>
            </div>
            <div className="chat-action-preview-buttons">
              {activeTask && actionString(primaryPendingAction, "type") !== "build_dataset_export" ? (
                <button type="button" data-variant="secondary" onClick={() => onOpenTask(activeTask.id)} disabled={busy}>
                  <FileText size={14} />
                  Edit
                </button>
              ) : null}
              <button
                type="button"
                data-variant="secondary"
                onClick={() => void runTurn("dismiss", { dismissAction: primaryPendingAction })}
                disabled={!readyToDismissPendingAction || busy}
              >
                <XCircle size={14} />
                Dismiss
              </button>
              <button type="button" onClick={() => void runTurn("ready", { confirmAction: primaryPendingAction })} disabled={!readyToConfirmPendingAction || busy}>
                <CheckCircle2 size={14} />
                Confirm
              </button>
            </div>
          </div>
          {fieldDiffRows.length > 0 ? (
            <div className="chat-action-preview-diffs" aria-label="Pending action field changes">
              {fieldDiffRows.map((diff, index) => {
                const field = stringValue(diff.field) || `field_${index}`;
                return (
                  <article key={`${field}-${index}`}>
                    <div>
                      <em>{promptPairFieldLabel(field, activeTask, responseWorkSurface)}</em>
                      <span>{labelFromKey(stringValue(diff.change_type) || "changed")}</span>
                      {stringValue(diff.value_source) ? <span data-source>{labelFromKey(stringValue(diff.value_source))}</span> : null}
                    </div>
                    <p>
                      <strong>Before</strong>
                      {previewJsonValue(diff.before)}
                    </p>
                    <p>
                      <strong>After</strong>
                      {previewJsonValue(diff.after)}
                    </p>
                  </article>
                );
              })}
            </div>
          ) : pendingPreviewRows.length > 0 ? (
            <div className="chat-action-preview-fields">
              {pendingPreviewRows.map(([key, value]) => (
                <article key={key}>
                  <em>{promptPairFieldLabel(key, activeTask, responseWorkSurface)}</em>
                  <p>{compactJsonValue(value)}</p>
                </article>
              ))}
            </div>
          ) : null}
        </section>
      ) : null}

      <aside className="chat-action-bar" aria-label="Chat actions">
        <div>
          <span>Active item</span>
          <strong>{responseTaskTitle(lastResponse) || taskTitle(activeTask)}</strong>
        </div>
        <button type="button" onClick={() => activeTask?.id && onOpenTask(activeTask.id)} disabled={!activeTask}>
          Open item
        </button>
        <button type="button" onClick={() => void runTurn("ready", { confirmSubmit: true })} disabled={!readyToSubmit || busy}>
          <CheckCircle2 size={14} />
          Confirm submit
        </button>
      </aside>

      {lastResponse?.submitted_annotation ? (
        <section className="chat-submitted-destination" aria-label="Submitted training destination">
          <div>
            <span>Submitted</span>
            <strong>{continuedTaskHumanId ? `Opened ${continuedTaskHumanId}` : "Moved to the Training Set"}</strong>
            <p>
              {continuedTaskHumanId
                ? "This item left the ready worklist. The next item in this batch is now active."
                : "This item left the ready worklist. Approved SFT/DPO rows now accumulate for export."}
            </p>
          </div>
          {submittedRows.length > 0 ? (
            <div className="chat-submitted-records" aria-label="Submitted artifact records">
              {submittedRows.slice(0, 5).map((row) => (
                <span key={`${row.label}-${row.value}`}>
                  <em>{row.label}</em>
                  <strong>{row.value.slice(0, 12)}</strong>
                </span>
              ))}
            </div>
          ) : null}
          <button type="button" onClick={onViewTrainingBoard}>
            <FileText size={14} />
            Training Set
          </button>
        </section>
      ) : null}

      {updateRows.length > 0 ? (
        <section className="chat-draft-proof" aria-label="Latest draft changes">
          <span>
            <Sparkles size={14} />
            Draft updates
          </span>
          <div>
            {updateRows.map(([key, value]) => (
              <article key={key}>
                <strong>{promptPairFieldLabel(key, activeTask, responseWorkSurface)}</strong>
                <p>{previewJsonValue(value)}</p>
              </article>
            ))}
          </div>
        </section>
      ) : null}

      <form className="chat-composer" onSubmit={handleSubmit}>
        <textarea
          value={input}
          onChange={(event) => setInput(event.target.value)}
          onKeyDown={handleComposerKeyDown}
          aria-label="Answer the current chat question"
          placeholder={activeTask ? "Answer the current question..." : "Ask to work on photos, DPO pairs, SFT examples, sources, or exports..."}
          rows={3}
          disabled={busy}
        />
        <button type="submit" disabled={busy || !input.trim()}>
          <Send size={15} />
          Send
        </button>
      </form>
    </section>
  );
}
