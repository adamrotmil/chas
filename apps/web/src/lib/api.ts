import type {
  Annotation,
  Asset,
  AssetDossier,
  AssetMirrorResponse,
  PhotoReviewInventory,
  PhotoContextReviewPack,
  PhotoContextReviewSession,
  PhotoContextReviewSessionPlan,
  PhotoContextRetrievalGapFieldWorklist,
  PhotoContextRetrievalGapPayoffPreview,
  PhotoContextSessionProgress,
  PhotoContextSubmitProjection,
  PhotoContextTopSlice,
  PhotoReviewPrioritySummary,
  AssetUploadResponse,
  ContextPack,
  ContextPackBuildRequest,
  ContextPackBuildResponse,
  DatasetExport,
  DatasetExportDryRun,
  DemoGenerationBatchResponse,
  DemoGenerationReadiness,
  DemoGenerationRequestPreview,
  DpoRejectedReasonRepairPacket,
  DpoRejectedReasonRepairProjection,
  DownstreamArtifactAudit,
  DownstreamArtifactManifest,
  DownstreamBottleneckQueue,
  DriveFileImport,
  DriveImportRecord,
  DriveImportResponse,
  Entity,
  EntityCreate,
  GoldVoiceExample,
  Memory,
  ModelStatus,
  MorningHandoff,
  PhotoContextTaskCreateResponse,
  PhotoMemoryCorpusResponse,
  PhotoMemoryDraftResponse,
  ReviewedPhotoMemoryDemoReadiness,
  OperatorAssistantSuggestion,
  PhotoMemoryVectorHandoffExport,
  PhotoPromptPairCandidateResponse,
  PromptPairAudit,
  PromptPairAuditPack,
  PromptPairHeldCandidatePack,
  PromptPairPreflightExportGate,
  PromptPairReferencePack,
  PromptPairReviewProgress,
  PromptPairTopBlockerReviewSessionPlan,
  PromptPairTopBlockerSlice,
  PromptPairBatchResponse,
  RetrievalGapReviewSlice,
  RetrievalSearchResponse,
  ReviewedPhotoGalleryResponse,
  Segment,
  SourcePairGenerationPreview,
  Task,
  TaskDraft,
  VoiceMode,
  VisionDraftBatchResponse
} from "./types";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000/api";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers ?? {})
    },
    cache: "no-store"
  });

  if (!response.ok) {
    const body = await response.text();
    throw new Error(body || `Request failed: ${response.status}`);
  }

  return response.json() as Promise<T>;
}

export function getAssets(): Promise<Asset[]> {
  return request<Asset[]>("/assets");
}

export function getPhotoReviewInventory(limit = 100): Promise<PhotoReviewInventory> {
  return request<PhotoReviewInventory>(`/assets/photo-review-inventory?limit=${limit}`);
}

export function getPhotoContextReviewPack(
  scope: "public" | "family_private" | "private" = "family_private",
  limit = 100
): Promise<PhotoContextReviewPack> {
  const params = new URLSearchParams({ scope, limit: String(limit) });
  return request<PhotoContextReviewPack>(`/assets/photo-context-review-pack?${params.toString()}`);
}

export function getPhotoContextTopSlice(
  scope: "public" | "family_private" | "private" = "family_private",
  limit = 5
): Promise<PhotoContextTopSlice> {
  const params = new URLSearchParams({ scope, limit: String(limit) });
  return request<PhotoContextTopSlice>(`/assets/photo-context-review-pack/top-context-slice?${params.toString()}`);
}

export function getPhotoContextReviewSessionPlan(
  scope: "public" | "family_private" | "private" = "family_private",
  limit = 5,
  sourceQuery = "Old Orchard beach"
): Promise<PhotoContextReviewSessionPlan> {
  const params = new URLSearchParams({ scope, limit: String(limit), source_query: sourceQuery });
  return request<PhotoContextReviewSessionPlan>(`/assets/photo-context-review-pack/review-session-plan?${params.toString()}`);
}

export function getPhotoContextReviewSessionPlanYamlUrl(
  scope: "public" | "family_private" | "private" = "family_private",
  limit = 5,
  sourceQuery = "Old Orchard beach"
): string {
  const params = new URLSearchParams({ scope, limit: String(limit), source_query: sourceQuery });
  return `${API_BASE}/assets/photo-context-review-pack/review-session-plan/yaml?${params.toString()}`;
}

export function createPhotoContextReviewSession(limit = 5, dryRun = true, sourceQuery = "Old Orchard beach"): Promise<PhotoContextReviewSession> {
  const params = new URLSearchParams({
    scope: "family_private",
    limit: String(limit),
    dry_run: String(dryRun),
    source_query: sourceQuery
  });
  return request<PhotoContextReviewSession>(`/assets/photo-context-review-pack/review-session?${params.toString()}`, {
    method: "POST"
  });
}

export function previewPhotoContextSubmitProjection(
  taskId: string,
  decisions: Record<string, unknown>
): Promise<PhotoContextSubmitProjection> {
  return request<PhotoContextSubmitProjection>(`/tasks/${taskId}/photo-context/projection`, {
    method: "POST",
    body: JSON.stringify({ decisions })
  });
}

export function previewSourcePairGeneration(
  taskId: string,
  decisions: Record<string, unknown>
): Promise<SourcePairGenerationPreview> {
  return request<SourcePairGenerationPreview>(`/tasks/${taskId}/pair-generation/preview`, {
    method: "POST",
    body: JSON.stringify({ decisions })
  });
}

export function getPhotoContextSessionProgress(
  scope: "public" | "family_private" | "private" = "family_private",
  limit = 100
): Promise<PhotoContextSessionProgress> {
  const params = new URLSearchParams({ scope, limit: String(limit) });
  return request<PhotoContextSessionProgress>(`/assets/photo-context-review-pack/session-progress?${params.toString()}`);
}

export function getPhotoContextSessionProgressUrl(
  scope: "public" | "family_private" | "private" = "family_private",
  limit = 100
): string {
  const params = new URLSearchParams({ scope, limit: String(limit) });
  return `${API_BASE}/assets/photo-context-review-pack/session-progress/artifact?${params.toString()}`;
}

export function getPhotoContextRetrievalGapFieldWorklist(
  scope: "public" | "family_private" | "private" = "family_private",
  limit = 100
): Promise<PhotoContextRetrievalGapFieldWorklist> {
  const params = new URLSearchParams({ scope, limit: String(limit) });
  return request<PhotoContextRetrievalGapFieldWorklist>(
    `/assets/photo-context-review-pack/retrieval-gap-field-worklist?${params.toString()}`
  );
}

export function getPhotoContextRetrievalGapFieldWorklistYamlUrl(
  scope: "public" | "family_private" | "private" = "family_private",
  limit = 100
): string {
  const params = new URLSearchParams({ scope, limit: String(limit) });
  return `${API_BASE}/assets/photo-context-review-pack/retrieval-gap-field-worklist/yaml?${params.toString()}`;
}

export function getPhotoContextRetrievalGapPayoffPreview(
  scope: "public" | "family_private" | "private" = "family_private",
  limit = 10
): Promise<PhotoContextRetrievalGapPayoffPreview> {
  const params = new URLSearchParams({ scope, limit: String(limit) });
  return request<PhotoContextRetrievalGapPayoffPreview>(
    `/assets/photo-context-review-pack/retrieval-gap-payoff-preview?${params.toString()}`
  );
}

export function getPhotoContextRetrievalGapPayoffPreviewYamlUrl(
  scope: "public" | "family_private" | "private" = "family_private",
  limit = 10
): string {
  const params = new URLSearchParams({ scope, limit: String(limit) });
  return `${API_BASE}/assets/photo-context-review-pack/retrieval-gap-payoff-preview/yaml?${params.toString()}`;
}

export function getPhotoReviewPriority(
  focus: "all" | "fastest_vector" = "fastest_vector",
  limit = 50
): Promise<PhotoReviewPrioritySummary> {
  const params = new URLSearchParams({ focus, limit: String(limit) });
  return request<PhotoReviewPrioritySummary>(`/assets/photo-review-priority?${params.toString()}`);
}

export function getPhotoReviewPriorityYamlUrl(
  focus: "all" | "fastest_vector" = "fastest_vector",
  limit = 50
): string {
  const params = new URLSearchParams({ focus, limit: String(limit) });
  return `${API_BASE}/assets/photo-review-priority/yaml?${params.toString()}`;
}

export function getDownstreamBottlenecks(
  scope: "public" | "family_private" | "private" = "family_private",
  limit = 4
): Promise<DownstreamBottleneckQueue> {
  const params = new URLSearchParams({ scope, limit: String(limit) });
  return request<DownstreamBottleneckQueue>(`/downstream-readiness/bottlenecks?${params.toString()}`);
}

export function getDownstreamArtifactManifest(
  scope: "public" | "family_private" | "private" = "family_private",
  promptSampleLimit = 200,
  vectorLimit = 20,
  photoSessionQuery = "Old Orchard beach"
): Promise<DownstreamArtifactManifest> {
  const params = new URLSearchParams({
    scope,
    prompt_sample_limit: String(promptSampleLimit),
    vector_limit: String(vectorLimit),
    photo_session_query: photoSessionQuery
  });
  return request<DownstreamArtifactManifest>(`/downstream-readiness/artifact-manifest?${params.toString()}`);
}

export function getDownstreamArtifactManifestUrl(
  scope: "public" | "family_private" | "private" = "family_private",
  promptSampleLimit = 200,
  vectorLimit = 20,
  photoSessionQuery = "Old Orchard beach"
): string {
  const params = new URLSearchParams({
    scope,
    prompt_sample_limit: String(promptSampleLimit),
    vector_limit: String(vectorLimit),
    photo_session_query: photoSessionQuery
  });
  return `${API_BASE}/downstream-readiness/artifact-manifest?${params.toString()}`;
}

export function getDownstreamArtifactAudit(
  scope: "public" | "family_private" | "private" = "family_private",
  promptSampleLimit = 200,
  vectorLimit = 20,
  photoSessionQuery = "Old Orchard beach"
): Promise<DownstreamArtifactAudit> {
  const params = new URLSearchParams({
    scope,
    prompt_sample_limit: String(promptSampleLimit),
    vector_limit: String(vectorLimit),
    photo_session_query: photoSessionQuery
  });
  return request<DownstreamArtifactAudit>(`/downstream-readiness/artifact-audit?${params.toString()}`);
}

export function getMorningHandoff(
  scope: "public" | "family_private" | "private" = "family_private",
  promptSampleLimit = 200,
  vectorLimit = 20,
  bottleneckLimit = 4,
  retrievalGapQuery = "Old Orchard beach"
): Promise<MorningHandoff> {
  const params = new URLSearchParams({
    scope,
    prompt_sample_limit: String(promptSampleLimit),
    vector_limit: String(vectorLimit),
    bottleneck_limit: String(bottleneckLimit),
    retrieval_gap_query: retrievalGapQuery
  });
  return request<MorningHandoff>(`/downstream-readiness/morning-handoff?${params.toString()}`);
}

export function getMorningHandoffYamlUrl(
  scope: "public" | "family_private" | "private" = "family_private",
  promptSampleLimit = 200,
  vectorLimit = 20,
  bottleneckLimit = 4,
  retrievalGapQuery = "Old Orchard beach"
): string {
  const params = new URLSearchParams({
    scope,
    prompt_sample_limit: String(promptSampleLimit),
    vector_limit: String(vectorLimit),
    bottleneck_limit: String(bottleneckLimit),
    retrieval_gap_query: retrievalGapQuery
  });
  return `${API_BASE}/downstream-readiness/morning-handoff.yaml?${params.toString()}`;
}

export function createPhotoContextTaskFromInventory(payload: {
  asset_id?: string;
  group_key?: string;
  use_canonical?: boolean;
  source_query?: string;
  candidate_match_quality?: string;
  candidate_selection_reason?: string;
  session_sequence_number?: number;
  session_selected_count?: number;
  session_plan_content_sha256?: string;
  session_completion_signal?: string;
  session_review_policy?: string;
}): Promise<PhotoContextTaskCreateResponse> {
  return request<PhotoContextTaskCreateResponse>("/assets/photo-review-inventory/context-task", {
    method: "POST",
    body: JSON.stringify(payload)
  });
}

export function getAssetPreviewUrl(assetId: string, variant: "thumbnail" | "display" | "original" = "display"): string {
  return `${API_BASE}/assets/${encodeURIComponent(assetId)}/preview?variant=${encodeURIComponent(variant)}`;
}

export function getAssetDossier(assetId: string): Promise<AssetDossier> {
  return request<AssetDossier>(`/assets/${encodeURIComponent(assetId)}/dossier`);
}

export async function uploadArtifact(file: File, title?: string): Promise<AssetUploadResponse> {
  const formData = new FormData();
  formData.set("file", file, file.name || "uploaded_artifact");
  formData.set("source_system", "local_upload");
  if (title?.trim()) {
    formData.set("title", title.trim());
  }

  const response = await fetch(`${API_BASE}/assets/upload`, {
    method: "POST",
    body: formData,
    cache: "no-store"
  });

  if (!response.ok) {
    const body = await response.text();
    throw new Error(body || `Request failed: ${response.status}`);
  }

  return response.json() as Promise<AssetUploadResponse>;
}

export function getTasks(): Promise<Task[]> {
  return request<Task[]>("/tasks");
}

export function getAssetTextChunks(assetId: string, textExtractionDerivativeId?: string): Promise<Segment[]> {
  const params = new URLSearchParams({
    asset_id: assetId,
    segment_type: "text_chunk",
    limit: "1000"
  });
  if (textExtractionDerivativeId) {
    params.set("text_extraction_derivative_id", textExtractionDerivativeId);
  }
  return request<Segment[]>(`/segments?${params.toString()}`);
}

export function getMemories(): Promise<Memory[]> {
  return request<Memory[]>("/memories");
}

export function getEntities(entityType = "person"): Promise<Entity[]> {
  return request<Entity[]>(`/entities?entity_type=${encodeURIComponent(entityType)}`);
}

export function createEntity(payload: EntityCreate): Promise<Entity> {
  return request<Entity>("/entities", {
    method: "POST",
    body: JSON.stringify(payload)
  });
}

export function getGoldVoiceExamples(): Promise<GoldVoiceExample[]> {
  return request<GoldVoiceExample[]>("/gold-voice-examples");
}

export function getVoiceModes(): Promise<VoiceMode[]> {
  return request<VoiceMode[]>("/voice-modes");
}

export function createVoiceMode(payload: {
  label: string;
  slug?: string;
  description?: string;
  default_system_prompt?: string;
  family?: string;
}): Promise<VoiceMode> {
  return request<VoiceMode>("/voice-modes", {
    method: "POST",
    body: JSON.stringify(payload)
  });
}

export function getContextPacks(): Promise<ContextPack[]> {
  return request<ContextPack[]>("/context-packs");
}

export function buildContextPack(payload: ContextPackBuildRequest): Promise<ContextPackBuildResponse> {
  return request<ContextPackBuildResponse>("/context-packs/build", {
    method: "POST",
    body: JSON.stringify(payload)
  });
}

export function getDatasetExportDryRun(
  exportType: "sft" | "dpo",
  includeCandidates = false
): Promise<DatasetExportDryRun> {
  return request<DatasetExportDryRun>(
    `/dataset-exports/dry-run?export_type=${encodeURIComponent(exportType)}&include_candidates=${includeCandidates}`
  );
}

export function buildDatasetExport(exportType: "sft" | "dpo", version = "v0", split = "train"): Promise<DatasetExport> {
  return request<DatasetExport>("/dataset-exports/build", {
    method: "POST",
    body: JSON.stringify({ export_type: exportType, version, split })
  });
}

export function getDatasetJsonlUrl(exportType: "sft" | "dpo"): string {
  return `${API_BASE}/dataset-exports/jsonl?export_type=${encodeURIComponent(exportType)}`;
}

export function getModelStatus(): Promise<ModelStatus> {
  return request<ModelStatus>("/model-status");
}

export function getDemoGenerationReadiness(limit = 5): Promise<DemoGenerationReadiness> {
  return request<DemoGenerationReadiness>(`/model-status/demo-readiness?limit=${limit}`);
}

export function getDemoGenerationRequestPreview(limit = 5): Promise<DemoGenerationRequestPreview> {
  return request<DemoGenerationRequestPreview>(`/model-status/demo-generation-request-preview?limit=${limit}`);
}

export function getDemoGenerationRequestPreviewYamlUrl(limit = 5): string {
  return `${API_BASE}/model-status/demo-generation-request-preview/yaml?limit=${limit}`;
}

export function createDemoGenerations(limit = 5): Promise<DemoGenerationBatchResponse> {
  return request<DemoGenerationBatchResponse>("/model-status/demo-generations", {
    method: "POST",
    body: JSON.stringify({ limit })
  });
}

export function getPromptPairAudit(sampleLimit = 20): Promise<PromptPairAudit> {
  return request<PromptPairAudit>(`/prompt-pairs/audit?sample_limit=${sampleLimit}`);
}

export function getPromptPairReviewProgress(): Promise<PromptPairReviewProgress> {
  return request<PromptPairReviewProgress>("/prompt-pairs/review-progress");
}

export function getPromptPairAuditPack(sampleLimit = 20): Promise<PromptPairAuditPack> {
  return request<PromptPairAuditPack>(`/prompt-pairs/audit-pack?sample_limit=${sampleLimit}`);
}

export function getPromptPairHeldCandidates(limit = 30): Promise<PromptPairHeldCandidatePack> {
  return request<PromptPairHeldCandidatePack>(`/prompt-pairs/held-candidates?limit=${limit}`);
}

export function getPromptPairTopBlockerSlice(limit = 5, blocker?: string): Promise<PromptPairTopBlockerSlice> {
  const params = new URLSearchParams({ limit: String(limit) });
  if (blocker) {
    params.set("blocker", blocker);
  }
  return request<PromptPairTopBlockerSlice>(`/prompt-pairs/top-blocker-slice?${params.toString()}`);
}

export function getPromptPairTopBlockerReviewSessionPlan(limit = 5, blocker?: string): Promise<PromptPairTopBlockerReviewSessionPlan> {
  const params = new URLSearchParams({ limit: String(limit) });
  if (blocker) {
    params.set("blocker", blocker);
  }
  return request<PromptPairTopBlockerReviewSessionPlan>(`/prompt-pairs/top-blocker-review-session-plan?${params.toString()}`);
}

export function getDpoRejectedReasonRepairPacket(limit = 25): Promise<DpoRejectedReasonRepairPacket> {
  return request<DpoRejectedReasonRepairPacket>(`/prompt-pairs/dpo-rejected-reason-repair-pack?limit=${limit}`);
}

export function getDpoRejectedReasonRepairPacketYamlUrl(limit = 25): string {
  return `${API_BASE}/prompt-pairs/dpo-rejected-reason-repair-pack/yaml?limit=${encodeURIComponent(String(limit))}`;
}

export function getDpoRejectedReasonRepairProjection(taskId?: string): Promise<DpoRejectedReasonRepairProjection> {
  const params = new URLSearchParams();
  if (taskId) {
    params.set("task_id", taskId);
  }
  const suffix = params.toString() ? `?${params.toString()}` : "";
  return request<DpoRejectedReasonRepairProjection>(`/prompt-pairs/dpo-rejected-reason-repair-projection${suffix}`);
}

export function getPromptPairAuditPackMarkdownUrl(sampleLimit = 200): string {
  return `${API_BASE}/prompt-pairs/audit-pack/markdown?sample_limit=${encodeURIComponent(String(sampleLimit))}`;
}

export function preflightPromptPairExportGate(payload: Record<string, unknown>): Promise<PromptPairPreflightExportGate> {
  return request<PromptPairPreflightExportGate>("/prompt-pairs/preflight-export-gate", {
    method: "POST",
    body: JSON.stringify(payload)
  });
}

export function getPromptPairReferencePack(sampleLimit = 200): Promise<PromptPairReferencePack> {
  return request<PromptPairReferencePack>(`/prompt-pairs/reference-pack?sample_limit=${sampleLimit}`);
}

export function getPromptPairReferencePackJsonlUrl(sampleLimit = 200): string {
  return `${API_BASE}/prompt-pairs/reference-pack/jsonl?sample_limit=${encodeURIComponent(String(sampleLimit))}`;
}

export function getPromptPairReferencePackMarkdownUrl(sampleLimit = 200): string {
  return `${API_BASE}/prompt-pairs/reference-pack/markdown?sample_limit=${encodeURIComponent(String(sampleLimit))}`;
}

export function searchRetrieval(
  query: string,
  scope: "public" | "family_private" | "private" = "family_private",
  limit = 3
): Promise<RetrievalSearchResponse> {
  const params = new URLSearchParams({ q: query, scope, limit: String(limit) });
  return request<RetrievalSearchResponse>(`/retrieval/search?${params.toString()}`);
}

export function getRetrievalGapReviewSlice(
  query: string,
  scope: "public" | "family_private" | "private" = "family_private",
  limit = 5
): Promise<RetrievalGapReviewSlice> {
  const params = new URLSearchParams({ q: query, scope, limit: String(limit) });
  return request<RetrievalGapReviewSlice>(`/retrieval/gap-review-slice?${params.toString()}`);
}

export function getPhotoMemoryCorpus(
  scope: "public" | "family_private" | "private" = "family_private",
  limit = 100,
  includeMachineDrafts = false
): Promise<PhotoMemoryCorpusResponse> {
  const params = new URLSearchParams({ scope, limit: String(limit), include_machine_drafts: String(includeMachineDrafts) });
  return request<PhotoMemoryCorpusResponse>(`/retrieval/photo-memory-corpus?${params.toString()}`);
}

export function getPhotoMemoryVectorHandoff(
  scope: "public" | "family_private" | "private" = "family_private",
  limit = 100,
  includeMachineDrafts = false
): Promise<PhotoMemoryVectorHandoffExport> {
  const params = new URLSearchParams({ scope, limit: String(limit), include_machine_drafts: String(includeMachineDrafts) });
  return request<PhotoMemoryVectorHandoffExport>(`/retrieval/photo-memory-corpus/export?${params.toString()}`);
}

export function getPhotoMemoryVectorHandoffJsonlUrl(
  scope: "public" | "family_private" | "private" = "family_private",
  limit = 100,
  includeMachineDrafts = false
): string {
  const params = new URLSearchParams({ scope, limit: String(limit), include_machine_drafts: String(includeMachineDrafts) });
  return `${API_BASE}/retrieval/photo-memory-corpus/export.jsonl?${params.toString()}`;
}

export function getPhotoMemoryVectorHandoffManifestUrl(
  scope: "public" | "family_private" | "private" = "family_private",
  limit = 100,
  includeMachineDrafts = false
): string {
  const params = new URLSearchParams({ scope, limit: String(limit), include_machine_drafts: String(includeMachineDrafts) });
  return `${API_BASE}/retrieval/photo-memory-corpus/export.manifest?${params.toString()}`;
}

export function getReviewedPhotoMemoryDemoReadiness(
  scope: "public" | "family_private" | "private" = "family_private",
  limit = 5
): Promise<ReviewedPhotoMemoryDemoReadiness> {
  const params = new URLSearchParams({ scope, limit: String(limit) });
  return request<ReviewedPhotoMemoryDemoReadiness>(
    `/retrieval/photo-memory-corpus/reviewed-demo-readiness?${params.toString()}`
  );
}

export function getReviewedPhotoGallery(
  scope: "public" | "family_private" = "family_private",
  limit = 24,
  includeDrafts = false
): Promise<ReviewedPhotoGalleryResponse> {
  const params = new URLSearchParams({ scope, limit: String(limit), include_drafts: String(includeDrafts) });
  return request<ReviewedPhotoGalleryResponse>(`/gallery/reviewed-photos?${params.toString()}`);
}

export function createPhotoMemoryDrafts(limit = 5, dryRun = true): Promise<PhotoMemoryDraftResponse> {
  return request<PhotoMemoryDraftResponse>(
    `/photo-memory-drafts?limit=${limit}&dry_run=${dryRun}`,
    { method: "POST" }
  );
}

export function createPhotoPromptPairCandidates(
  limit = 5,
  dryRun = true,
  options: { assetId?: string; metadataProfileId?: string } = {}
): Promise<PhotoPromptPairCandidateResponse> {
  const params = new URLSearchParams({
    limit: String(limit),
    dry_run: String(dryRun)
  });
  if (options.assetId) {
    params.set("asset_id", options.assetId);
  }
  if (options.metadataProfileId) {
    params.set("metadata_profile_id", options.metadataProfileId);
  }
  return request<PhotoPromptPairCandidateResponse>(
    `/photo-memory-drafts/prompt-pair-candidates?${params.toString()}`,
    { method: "POST" }
  );
}

export interface PromptPairBatchOptions {
  limit?: number;
  queue?: string;
  prompt_intent?: string;
  voice_mode?: string;
  truth_mode?: string;
  target_response_shape?: string;
  boundary_clearance_needed?: string;
  conversation_family?: string;
  system_prompt?: string;
  no_live_model_call?: boolean;
}

export function createPromptPairBatch(options: PromptPairBatchOptions | number = 10): Promise<PromptPairBatchResponse> {
  const payload = typeof options === "number" ? { limit: options } : options;
  return request<PromptPairBatchResponse>("/prompt-pairs/batches", {
    method: "POST",
    body: JSON.stringify(payload)
  });
}

export function createVisionDraftBatch(limit = 10): Promise<VisionDraftBatchResponse> {
  return request<VisionDraftBatchResponse>("/vision/drafts/batches", {
    method: "POST",
    body: JSON.stringify({ limit, no_live_model_call: true })
  });
}

export function submitTask(
  taskId: string,
  decisions: Record<string, unknown>,
  notes?: string
): Promise<Annotation> {
  return request<Annotation>(`/tasks/${taskId}/submit`, {
    method: "POST",
    body: JSON.stringify({ decisions, notes })
  });
}

export function getOperatorAssistantSuggestion(
  taskId: string,
  decisions: Record<string, unknown>,
  operatorAnswer?: string,
  notes?: string
): Promise<OperatorAssistantSuggestion> {
  return request<OperatorAssistantSuggestion>(`/tasks/${taskId}/operator-assistant`, {
    method: "POST",
    body: JSON.stringify({ decisions, notes, operator_answer: operatorAnswer })
  });
}

export function getTaskDraft(taskId: string): Promise<TaskDraft | null> {
  return request<TaskDraft | null>(`/tasks/${taskId}/draft`);
}

export function saveTaskDraft(taskId: string, decisions: Record<string, unknown>, notes?: string): Promise<TaskDraft> {
  return request<TaskDraft>(`/tasks/${taskId}/draft`, {
    method: "PUT",
    body: JSON.stringify({ decisions, notes, user_id: "adam" })
  });
}

export async function deleteTaskDraft(taskId: string): Promise<void> {
  await request<{ deleted: boolean }>(`/tasks/${taskId}/draft`, {
    method: "DELETE"
  });
}

export function skipTask(taskId: string, reason?: string): Promise<Task> {
  return request<Task>(`/tasks/${taskId}/skip`, {
    method: "POST",
    body: JSON.stringify({ reason })
  });
}

export function flagTask(taskId: string, reason?: string): Promise<Task> {
  return request<Task>(`/tasks/${taskId}/flag`, {
    method: "POST",
    body: JSON.stringify({ reason })
  });
}

export function deletePromptPairCandidate(taskId: string, reason?: string, notes?: string): Promise<Annotation> {
  return request<Annotation>(`/tasks/${taskId}/delete-candidate`, {
    method: "POST",
    body: JSON.stringify({ reason, notes })
  });
}

export function importDriveFiles(files: DriveFileImport[]): Promise<DriveImportResponse> {
  return request<DriveImportResponse>("/imports/drive", {
    method: "POST",
    body: JSON.stringify({ files, imported_by: "adam", create_triage_tasks: true })
  });
}

export function getRecentDriveImports(limit = 100): Promise<DriveImportRecord[]> {
  return request<DriveImportRecord[]>(`/imports/drive/recent?limit=${limit}`);
}

export interface UploadAssetMirrorMetadata {
  source_system?: string;
  source_uri?: string | null;
  drive_file_id?: string | null;
  drive_mime_type?: string | null;
  export_mime_type?: string | null;
  source_modified_time?: string | null;
  storage_access_token?: string | null;
  filename?: string;
}

export async function uploadAssetMirror(
  assetId: string,
  blob: Blob,
  metadata: UploadAssetMirrorMetadata
): Promise<AssetMirrorResponse> {
  const formData = new FormData();
  formData.set("file", blob, metadata.filename ?? "source_file");
  formData.set("source_system", metadata.source_system ?? "google_drive");
  if (metadata.source_uri) {
    formData.set("source_uri", metadata.source_uri);
  }
  if (metadata.drive_file_id) {
    formData.set("drive_file_id", metadata.drive_file_id);
  }
  if (metadata.drive_mime_type) {
    formData.set("drive_mime_type", metadata.drive_mime_type);
  }
  if (metadata.export_mime_type) {
    formData.set("export_mime_type", metadata.export_mime_type);
  }
  if (metadata.source_modified_time) {
    formData.set("source_modified_time", metadata.source_modified_time);
  }
  if (metadata.storage_access_token) {
    formData.set("storage_access_token", metadata.storage_access_token);
  }

  const response = await fetch(`${API_BASE}/assets/${assetId}/mirror/upload`, {
    method: "POST",
    body: formData,
    cache: "no-store"
  });

  if (!response.ok) {
    const body = await response.text();
    throw new Error(body || `Request failed: ${response.status}`);
  }

  return response.json() as Promise<AssetMirrorResponse>;
}
