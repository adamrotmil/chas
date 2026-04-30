"use client";

import { CheckCircle2, ClipboardList, Download, FileJson, Image, RefreshCw, Search, ShieldCheck, Sparkles } from "lucide-react";
import type { FormEvent } from "react";
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  createDemoGenerations,
  createPhotoContextTaskFromInventory,
  createPhotoContextReviewSession,
  createPhotoMemoryDrafts,
  createPhotoPromptPairCandidates,
  getAssetPreviewUrl,
  getAssets,
  getPhotoContextReviewPack,
  getPhotoContextRetrievalGapFieldWorklist,
  getPhotoContextRetrievalGapFieldWorklistYamlUrl,
  getPhotoContextRetrievalGapPayoffPreview,
  getPhotoContextRetrievalGapPayoffPreviewYamlUrl,
  getPhotoContextReviewSessionPlan,
  getPhotoContextReviewSessionPlanYamlUrl,
  getPhotoContextSessionProgress,
  getPhotoContextSessionProgressUrl,
  getPhotoContextTopSlice,
  getPhotoReviewPriorityYamlUrl,
  getDatasetExportDryRun,
  getDemoGenerationReadiness,
  getDemoGenerationRequestPreview,
  getDemoGenerationRequestPreviewYamlUrl,
  getDownstreamArtifactAudit,
  getDownstreamArtifactManifest,
  getDownstreamArtifactManifestUrl,
  getDownstreamBottlenecks,
  getDpoRejectedReasonRepairProjection,
  getDpoRejectedReasonRepairPacket,
  getDpoRejectedReasonRepairPacketYamlUrl,
  getMorningHandoff,
  getMorningHandoffYamlUrl,
  getMemories,
  getModelStatus,
  getPhotoMemoryCorpus,
  getPhotoReviewInventory,
  getPhotoMemoryVectorHandoff,
  getPhotoMemoryVectorHandoffJsonlUrl,
  getPhotoMemoryVectorHandoffManifestUrl,
  getPromptPairAudit,
  getPromptPairAuditPack,
  getPromptPairAuditPackMarkdownUrl,
  getPromptPairHeldCandidates,
  getPromptPairReferencePack,
  getPromptPairReferencePackJsonlUrl,
  getPromptPairReferencePackMarkdownUrl,
  getPromptPairTopBlockerReviewSessionPlan,
  getPromptPairTopBlockerSlice,
  getRetrievalGapReviewSlice,
  getReviewedPhotoMemoryDemoReadiness,
  getReviewedPhotoGallery,
  getTasks,
  searchRetrieval
} from "@/lib/api";
import type {
  Asset,
  DatasetExportDryRun,
  DemoGenerationReadiness,
  DemoGenerationRequestPreview,
  DpoRejectedReasonRepairPacket,
  DpoRejectedReasonRepairProjection,
  DownstreamArtifactAudit,
  DownstreamArtifactManifest,
  DownstreamBottleneckQueue,
  Memory,
  ModelStatus,
  MorningHandoff,
  MorningHandoffChecklistItem,
  PhotoMemoryCorpusResponse,
  PhotoContextReviewPack,
  PhotoContextReviewPackAction,
  PhotoContextReviewPackNoClaimGroup,
  PhotoContextReviewSessionPlan,
  PhotoContextRetrievalGapFieldWorklist,
  PhotoContextRetrievalGapPayoffPreview,
  PhotoContextSessionProgress,
  PhotoContextTopSlice,
  PhotoMemoryDraftResponse,
  PhotoReviewInventory,
  PhotoContextReviewWorklist,
  PhotoMemoryVectorHandoffExport,
  PhotoPromptPairCandidateResponse,
  PromptPairAudit,
  PromptPairAuditPack,
  PromptPairHeldCandidatePack,
  PromptPairHeldCandidateWorklist,
  PromptPairReferencePack,
  PromptPairTopBlockerReviewSessionPlan,
  PromptPairTopBlockerSlice,
  RetrievalGapReviewSlice,
  RetrievalGapReviewSliceItem,
  ReviewedPhotoMemoryDemoReadiness,
  ReviewedPhotoGalleryResponse,
  RetrievalSearchResponse,
  Task
} from "@/lib/types";

const defaultRetrievalGapQuery = "Old Orchard beach";
const baselineRetrievalQueries = ["Japanese flute", "honors ceremony", "Adam flowers", defaultRetrievalGapQuery];
type ExportReadinessTab = "overview" | "prompt_pairs" | "photos" | "model" | "artifacts";
const exportReadinessTabs: { key: ExportReadinessTab; label: string; description: string }[] = [
  { key: "overview", label: "Overview", description: "What needs attention next" },
  { key: "prompt_pairs", label: "Prompt Pairs", description: "SFT/DPO review and voice packs" },
  { key: "photos", label: "Photos & Retrieval", description: "Photo memory, vectors, gallery, and search" },
  { key: "model", label: "Model/Demo", description: "Live model gate and exact requests" },
  { key: "artifacts", label: "Artifacts", description: "Downloadable outputs and hash audit" },
];

interface ReadinessState {
  audit: PromptPairAudit;
  auditPack: PromptPairAuditPack;
  heldPromptPairs: PromptPairHeldCandidatePack;
  topBlockerSlice: PromptPairTopBlockerSlice;
  topBlockerSessionPlan: PromptPairTopBlockerReviewSessionPlan;
  dpoRepairPacket: DpoRejectedReasonRepairPacket;
  dpoRepairProjection: DpoRejectedReasonRepairProjection;
  referencePack: PromptPairReferencePack;
  sft: DatasetExportDryRun;
  dpo: DatasetExportDryRun;
  demoReadiness: DemoGenerationReadiness;
  demoRequestPreview: DemoGenerationRequestPreview;
  modelStatus: ModelStatus;
  assets: Asset[];
  memories: Memory[];
  tasks: Task[];
  corpus: PhotoMemoryCorpusResponse;
  photoInventory: PhotoReviewInventory;
  photoContextPack: PhotoContextReviewPack;
  photoContextTopSlice: PhotoContextTopSlice;
  photoContextSessionPlan: PhotoContextReviewSessionPlan;
  photoContextRetrievalGapFieldWorklist: PhotoContextRetrievalGapFieldWorklist;
  photoContextRetrievalGapPayoffPreview: PhotoContextRetrievalGapPayoffPreview;
  photoContextProgress: PhotoContextSessionProgress;
  vectorHandoff: PhotoMemoryVectorHandoffExport;
  draftVectorPreview: PhotoMemoryVectorHandoffExport;
  reviewedPhotoDemoReadiness: ReviewedPhotoMemoryDemoReadiness;
  gallery: ReviewedPhotoGalleryResponse;
  retrieval: RetrievalSearchResponse[];
  retrievalGapSlice: RetrievalGapReviewSlice;
  photoDrafts: PhotoMemoryDraftResponse;
  photoPairCandidates: PhotoPromptPairCandidateResponse;
  downstreamBottlenecks: DownstreamBottleneckQueue;
  downstreamArtifactManifest: DownstreamArtifactManifest;
  downstreamArtifactAudit: DownstreamArtifactAudit;
  morningHandoff: MorningHandoff;
}

function titleCase(value: string): string {
  return value
    .split("_")
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}

function countPhotoDraftMemories(memories: Memory[]): number {
  return memories.filter(
    (memory) =>
      memory.maturity_level === "L2_machine_draft" &&
      memory.truth_status === "system_inference" &&
      memory.title.toLowerCase().startsWith("photo memory:")
  ).length;
}

function topVoiceModes(audit: PromptPairAudit): Array<[string, number]> {
  return Object.entries(audit.voice_mode_counts)
    .sort((left, right) => right[1] - left[1] || left[0].localeCompare(right[0]))
    .slice(0, 7);
}

function eligibilityLabels(eligibility: { training: boolean; vector: boolean; gallery: boolean; human_review: boolean }): string[] {
  return Object.entries(eligibility)
    .filter(([, enabled]) => enabled)
    .map(([key]) => titleCase(key));
}

function retrievalHasPhotoMemory(search: RetrievalSearchResponse): boolean {
  return search.results.some((result) => Boolean(result.source_photo_id) && result.target_type === "memory");
}

function retrievalResultReviewLabel(result?: RetrievalSearchResponse["results"][number]): string {
  if (!result) {
    return "No reviewed memory result yet";
  }
  const truthStatus = result.review_policy?.truth_status || result.truth_status || "unknown";
  if (result.review_policy?.requires_adam_review) {
    return `Machine-drafted memory / ${titleCase(truthStatus)} / needs Adam review`;
  }
  if (truthStatus === "adam_memory") {
    return "Adam-reviewed memory / boundary-cleared";
  }
  return `${titleCase(truthStatus)} / review status recorded`;
}

type RetrievalGap = NonNullable<RetrievalSearchResponse["retrieval_gap"]>;
type RetrievalGapCandidate = RetrievalGap["sample_context_groups"][number];
type PhotoContextSessionPlanItem = PhotoContextReviewSessionPlan["items"][number];

function retrievalGapEvidenceSummary(gap: RetrievalGap): string {
  const weakCount = Number(gap.weak_evidence_candidate_count ?? 0);
  const backlogCount = Number(
    gap.backlog_only_candidate_count ?? Math.max(0, Number(gap.candidate_photo_group_count ?? 0) - weakCount)
  );
  return `${weakCount} weak matches / ${backlogCount} backlog candidates`;
}

function retrievalGapCandidateLabel(group: RetrievalGapCandidate): string {
  const actionLabel = group.primary_action?.label ?? "Open";
  const terms = (group.matched_query_terms ?? []).join(", ");
  const quality = group.candidate_match_quality === "weak_evidence_match" && terms ? `match: ${terms}` : "backlog only";
  return `${actionLabel}: ${group.display_title} - ${quality}`;
}

function retrievalGapCandidateTitle(group: RetrievalGapCandidate): string {
  const actionLabel = group.primary_action?.label ?? "Open or create review task";
  const evidenceSource = titleCase(String(group.candidate_evidence?.evidence_source ?? "candidate"));
  const mediaKind = titleCase(String(group.candidate_media_kind ?? "image_asset_unknown_kind"));
  const nonMemory = group.candidate_evidence?.not_memory_claim ? "This is not a memory claim." : "Review required.";
  const actionHint = group.primary_action?.task_human_id ? `Task: ${group.primary_action.task_human_id}.` : "Creates or opens a photo context task.";
  return `${actionLabel} for ${group.display_title}. ${evidenceSource}; ${mediaKind}. ${nonMemory} ${actionHint}`;
}

function photoContextActionBody(action: PhotoContextReviewPackAction): Record<string, unknown> {
  const request = action.request;
  const body = request && typeof request === "object" ? request.body : null;
  return body && typeof body === "object" && !Array.isArray(body) ? (body as Record<string, unknown>) : {};
}

function photoContextActionProvenance(item: PhotoContextSessionPlanItem): {
  sourceQuery: string;
  matchQuality: string;
  selectionReason: string;
  queryIsPrioritizationOnly: boolean;
  notMemoryClaim: boolean;
} {
  const actionBody = photoContextActionBody(item.action);
  const provenance = item.action.query_provenance ?? {};
  return {
    sourceQuery: String(actionBody.source_query ?? provenance.source_query ?? item.query_origin.source_query),
    matchQuality: String(actionBody.candidate_match_quality ?? provenance.candidate_match_quality ?? "backlog_only"),
    selectionReason: String(
      actionBody.candidate_selection_reason ?? provenance.candidate_selection_reason ?? "selected_from_photo_context_review_session_plan"
    ),
    queryIsPrioritizationOnly: Boolean(
      actionBody.query_is_context_prioritization_only ?? provenance.query_is_context_prioritization_only ?? item.query_origin.query_is_context_prioritization_only
    ),
    notMemoryClaim: Boolean(actionBody.not_memory_claim ?? provenance.not_memory_claim ?? item.not_memory_claim)
  };
}

interface DownstreamReadinessPanelProps {
  onOpenReviewTask?: (taskId: string) => void | Promise<void>;
}

export function DownstreamReadinessPanel({ onOpenReviewTask }: DownstreamReadinessPanelProps) {
  const [state, setState] = useState<ReadinessState | null>(null);
  const [loading, setLoading] = useState(false);
  const [retrievalGapQuery, setRetrievalGapQuery] = useState(defaultRetrievalGapQuery);
  const [retrievalGapQueryDraft, setRetrievalGapQueryDraft] = useState(defaultRetrievalGapQuery);
  const [photoActionKey, setPhotoActionKey] = useState<string | null>(null);
  const [photoSessionStatus, setPhotoSessionStatus] = useState<string | null>(null);
  const [promptPairActionKey, setPromptPairActionKey] = useState<string | null>(null);
  const [promptPairFocusStatus, setPromptPairFocusStatus] = useState<string | null>(null);
  const [demoActionStatus, setDemoActionStatus] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<ExportReadinessTab>("overview");
  const [error, setError] = useState<string | null>(null);

  const activeRetrievalQueries = useMemo(() => {
    const selectedQuery = retrievalGapQuery.trim() || defaultRetrievalGapQuery;
    return baselineRetrievalQueries.includes(selectedQuery)
      ? baselineRetrievalQueries
      : [...baselineRetrievalQueries.filter((query) => query !== defaultRetrievalGapQuery), selectedQuery];
  }, [retrievalGapQuery]);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [audit, auditPack, heldPromptPairs, topBlockerSlice, topBlockerSessionPlan, dpoRepairPacket, dpoRepairProjection, referencePack, sft, dpo, demoReadiness, demoRequestPreview, modelStatus, assets, memories, tasks, corpus, photoInventory, photoContextPack, photoContextTopSlice, photoContextSessionPlan, photoContextRetrievalGapFieldWorklist, photoContextRetrievalGapPayoffPreview, photoContextProgress, vectorHandoff, draftVectorPreview, reviewedPhotoDemoReadiness, gallery, retrievalGapSlice, photoDrafts, photoPairCandidates, downstreamBottlenecks, downstreamArtifactManifest, downstreamArtifactAudit, morningHandoff, ...retrieval] = await Promise.all([
        getPromptPairAudit(12),
        getPromptPairAuditPack(200),
        getPromptPairHeldCandidates(30),
        getPromptPairTopBlockerSlice(5),
        getPromptPairTopBlockerReviewSessionPlan(5),
        getDpoRejectedReasonRepairPacket(25),
        getDpoRejectedReasonRepairProjection(),
        getPromptPairReferencePack(200),
        getDatasetExportDryRun("sft", true),
        getDatasetExportDryRun("dpo", true),
        getDemoGenerationReadiness(5),
        getDemoGenerationRequestPreview(5),
        getModelStatus(),
        getAssets(),
        getMemories(),
        getTasks(),
        getPhotoMemoryCorpus("family_private", 20),
        getPhotoReviewInventory(100),
        getPhotoContextReviewPack("family_private", 100),
        getPhotoContextTopSlice("family_private", 5),
        getPhotoContextReviewSessionPlan("family_private", 5, retrievalGapQuery),
        getPhotoContextRetrievalGapFieldWorklist("family_private", 100),
        getPhotoContextRetrievalGapPayoffPreview("family_private", 10),
        getPhotoContextSessionProgress("family_private", 100),
        getPhotoMemoryVectorHandoff("family_private", 20),
        getPhotoMemoryVectorHandoff("family_private", 20, true),
        getReviewedPhotoMemoryDemoReadiness("family_private", 5),
        getReviewedPhotoGallery("family_private", 6, true),
        getRetrievalGapReviewSlice(retrievalGapQuery, "family_private", 5),
        createPhotoMemoryDrafts(5, true),
        createPhotoPromptPairCandidates(5, true),
        getDownstreamBottlenecks("family_private", 4),
        getDownstreamArtifactManifest("family_private", 200, 20, retrievalGapQuery),
        getDownstreamArtifactAudit("family_private", 200, 20, retrievalGapQuery),
        getMorningHandoff("family_private", 200, 20, 4, retrievalGapQuery),
        ...activeRetrievalQueries.map((query) => searchRetrieval(query, "family_private", 3))
      ]);
      setState({ audit, auditPack, heldPromptPairs, topBlockerSlice, topBlockerSessionPlan, dpoRepairPacket, dpoRepairProjection, referencePack, sft, dpo, demoReadiness, demoRequestPreview, modelStatus, assets, memories, tasks, corpus, photoInventory, photoContextPack, photoContextTopSlice, photoContextSessionPlan, photoContextRetrievalGapFieldWorklist, photoContextRetrievalGapPayoffPreview, photoContextProgress, vectorHandoff, draftVectorPreview, reviewedPhotoDemoReadiness, gallery, retrievalGapSlice, photoDrafts, photoPairCandidates, downstreamBottlenecks, downstreamArtifactManifest, downstreamArtifactAudit, morningHandoff, retrieval });
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Unable to load downstream readiness.");
    } finally {
      setLoading(false);
    }
  }, [activeRetrievalQueries, retrievalGapQuery]);

  useEffect(() => {
    void load();
  }, [load]);

  const handleCreatePhotoContextTask = useCallback(
    async (groupKey: string) => {
      setPhotoActionKey(groupKey);
      setError(null);
      try {
        const created = await createPhotoContextTaskFromInventory({ group_key: groupKey, use_canonical: true });
        await load();
        await onOpenReviewTask?.(created.task_id);
      } catch (caught) {
        setError(caught instanceof Error ? caught.message : "Unable to create photo context task.");
      } finally {
        setPhotoActionKey(null);
      }
    },
    [load, onOpenReviewTask]
  );

  const handleOpenRetrievalGapCandidate = useCallback(
    async (group: RetrievalGapCandidate, sourceQuery: string) => {
      setPhotoActionKey(group.group_key);
      setError(null);
      try {
        const taskId = group.primary_action?.task_id ?? group.candidate_evidence?.review_task_id;
        if (typeof taskId === "string" && taskId) {
          const opened = await createPhotoContextTaskFromInventory({
            group_key: group.group_key,
            asset_id: group.canonical_asset_id,
            use_canonical: true,
            source_query: sourceQuery,
            candidate_match_quality: group.candidate_match_quality,
            candidate_selection_reason: group.selection_reason
          });
          await load();
          await onOpenReviewTask?.(opened.task_id || taskId);
          return;
        }
        const created = await createPhotoContextTaskFromInventory({
          group_key: group.group_key,
          asset_id: group.canonical_asset_id,
          use_canonical: true,
          source_query: sourceQuery,
          candidate_match_quality: group.candidate_match_quality,
          candidate_selection_reason: group.selection_reason
        });
        await load();
        await onOpenReviewTask?.(created.task_id);
      } catch (caught) {
        setError(caught instanceof Error ? caught.message : "Unable to open retrieval candidate.");
      } finally {
        setPhotoActionKey(null);
      }
    },
    [load, onOpenReviewTask]
  );

  const handleOpenRetrievalGapSliceItem = useCallback(
    async (item: RetrievalGapReviewSliceItem) => {
      setPhotoActionKey(item.item_key);
      setError(null);
      try {
        const taskId = item.action?.task_id;
        if (typeof taskId === "string" && taskId) {
          const opened = await createPhotoContextTaskFromInventory({
            group_key: item.group_key,
            asset_id: item.source_photo_id,
            use_canonical: true,
            source_query: item.query,
            candidate_match_quality: item.candidate_match_quality,
            candidate_selection_reason: item.selection_reason
          });
          await load();
          await onOpenReviewTask?.(opened.task_id || taskId);
          return;
        }
        const created = await createPhotoContextTaskFromInventory({
          group_key: item.group_key,
          asset_id: item.source_photo_id,
          use_canonical: true,
          source_query: item.query,
          candidate_match_quality: item.candidate_match_quality,
          candidate_selection_reason: item.selection_reason
        });
        await load();
        await onOpenReviewTask?.(created.task_id);
      } catch (caught) {
        setError(caught instanceof Error ? caught.message : "Unable to open retrieval gap slice item.");
      } finally {
        setPhotoActionKey(null);
      }
    },
    [load, onOpenReviewTask]
  );

  const handleOpenPhotoContextPackGroup = useCallback(
    async (group: PhotoContextReviewPackNoClaimGroup) => {
      setPhotoActionKey(group.group_key);
      setError(null);
      try {
        const taskId = group.primary_action.task_id;
        if (typeof taskId === "string" && taskId) {
          await onOpenReviewTask?.(taskId);
          return;
        }
        const created = await createPhotoContextTaskFromInventory({
          group_key: group.group_key,
          asset_id: group.canonical_asset_id,
          use_canonical: true
        });
        await load();
        await onOpenReviewTask?.(created.task_id);
      } catch (caught) {
        setError(caught instanceof Error ? caught.message : "Unable to open photo context review pack item.");
      } finally {
        setPhotoActionKey(null);
      }
    },
    [load, onOpenReviewTask]
  );

  const handleOpenPhotoContextWorklist = useCallback(
    async (worklist: PhotoContextReviewWorklist) => {
      setPhotoActionKey(worklist.worklist_key);
      setError(null);
      try {
        const taskId = worklist.recommended_action.task_id;
        if (typeof taskId === "string" && taskId) {
          await onOpenReviewTask?.(taskId);
          return;
        }
        const first = worklist.candidate_previews[0];
        const firstTaskId = first?.action.task_id;
        if (typeof firstTaskId === "string" && firstTaskId) {
          await onOpenReviewTask?.(firstTaskId);
          return;
        }
        if (first?.source_photo_id && first.item_key) {
          const created = await createPhotoContextTaskFromInventory({
            group_key: first.item_key,
            asset_id: first.source_photo_id,
            use_canonical: true
          });
          await load();
          await onOpenReviewTask?.(created.task_id);
          return;
        }
        setError("This photo context worklist does not have an openable first item yet.");
      } catch (caught) {
        setError(caught instanceof Error ? caught.message : "Unable to open photo context worklist.");
      } finally {
        setPhotoActionKey(null);
      }
    },
    [load, onOpenReviewTask]
  );

  const handleFocusPromptPairWorklist = useCallback(async (worklist: PromptPairHeldCandidateWorklist) => {
    setPromptPairActionKey(worklist.worklist_key);
    setPromptPairFocusStatus(null);
    setError(null);
    try {
      const [topBlockerSlice, topBlockerSessionPlan] = await Promise.all([
        getPromptPairTopBlockerSlice(5, worklist.blocker),
        getPromptPairTopBlockerReviewSessionPlan(5, worklist.blocker)
      ]);
      setState((current) => (current ? { ...current, topBlockerSlice, topBlockerSessionPlan } : current));
      setPromptPairFocusStatus(`${titleCase(worklist.blocker)} focused for batch review.`);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Unable to focus prompt pair blocker worklist.");
    } finally {
      setPromptPairActionKey(null);
    }
  }, []);

  const handleOpenPhotoContextSliceItem = useCallback(
    async (item: PhotoContextTopSlice["items"][number]) => {
      setPhotoActionKey(item.item_key);
      setError(null);
      try {
        const taskId = item.action.task_id;
        if (typeof taskId === "string" && taskId) {
          await onOpenReviewTask?.(taskId);
          return;
        }
        const created = await createPhotoContextTaskFromInventory({
          group_key: item.item_key,
          asset_id: item.source_photo_id,
          use_canonical: true
        });
        await load();
        await onOpenReviewTask?.(created.task_id);
      } catch (caught) {
        setError(caught instanceof Error ? caught.message : "Unable to open top photo context item.");
      } finally {
        setPhotoActionKey(null);
      }
    },
    [load, onOpenReviewTask]
  );

  const handleCreateDemoGenerations = useCallback(async () => {
    setDemoActionStatus("Running demo gate...");
    setError(null);
    try {
      const result = await createDemoGenerations(5);
      setDemoActionStatus(
        result.created_count > 0
          ? `${result.created_count} model_generated demo outputs stored`
          : `${titleCase(result.status)}: ${result.blockers.join(", ") || "no blockers"}`
      );
      await load();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Unable to create demo generations.");
    }
  }, [load]);

  const handleCreatePhotoContextReviewSession = useCallback(async () => {
    setPhotoActionKey("photo-context-review-session");
    setPhotoSessionStatus("Creating review tasks...");
    setError(null);
    try {
      const result = await createPhotoContextReviewSession(5, false, retrievalGapQuery);
      setPhotoSessionStatus(
        `${result.created_count} created / ${result.existing_count} already ready / ${result.selected_count} selected`
      );
      await load();
      const firstTaskId = result.review_task_ids[0];
      if (firstTaskId) {
        await onOpenReviewTask?.(firstTaskId);
      }
    } catch (caught) {
      setPhotoSessionStatus(null);
      setError(caught instanceof Error ? caught.message : "Unable to create photo context review session.");
    } finally {
      setPhotoActionKey(null);
    }
  }, [load, onOpenReviewTask, retrievalGapQuery]);

  const handleOpenMorningChecklistItem = useCallback(
    async (item: MorningHandoffChecklistItem) => {
      setError(null);
      if (item.task_id) {
        await onOpenReviewTask?.(item.task_id);
        return;
      }
      if (item.area_key === "photo_context" && item.action_type !== "configure_text_generation_credentials") {
        await handleCreatePhotoContextReviewSession();
        return;
      }
      setError(`${item.label} is blocked: ${item.safety_boundary}`);
    },
    [handleCreatePhotoContextReviewSession, onOpenReviewTask]
  );

  const handleOpenPhotoContextSessionItem = useCallback(
    async (item: PhotoContextSessionPlanItem) => {
      const actionKey = `session-${item.group_key}`;
      const actionProvenance = photoContextActionProvenance(item);
      setPhotoActionKey(actionKey);
      setError(null);
      try {
        const created = await createPhotoContextTaskFromInventory({
          group_key: item.group_key,
          asset_id: item.canonical_asset_id,
          use_canonical: true,
          source_query: actionProvenance.sourceQuery || item.query_origin?.source_query || retrievalGapQuery,
          candidate_match_quality: actionProvenance.matchQuality,
          candidate_selection_reason: actionProvenance.selectionReason,
          session_sequence_number: item.sequence_number,
          session_selected_count: state?.photoContextSessionPlan.selected_count,
          session_plan_content_sha256: state?.photoContextSessionPlan.content_sha256,
          session_completion_signal: state?.photoContextSessionPlan.completion_signal,
          session_review_policy: state?.photoContextSessionPlan.review_policy
        });
        await load();
        await onOpenReviewTask?.(created.task_id);
      } catch (caught) {
        setError(caught instanceof Error ? caught.message : "Unable to open review session item.");
      } finally {
        setPhotoActionKey(null);
      }
    },
    [load, onOpenReviewTask, retrievalGapQuery, state?.photoContextSessionPlan]
  );

  const handleApplyRetrievalGapQuery = useCallback(
    (event: FormEvent<HTMLFormElement>) => {
      event.preventDefault();
      const nextQuery = retrievalGapQueryDraft.trim();
      if (!nextQuery) {
        setRetrievalGapQueryDraft(retrievalGapQuery);
        return;
      }
      if (nextQuery === retrievalGapQuery) {
        void load();
        return;
      }
      setRetrievalGapQuery(nextQuery);
    },
    [load, retrievalGapQuery, retrievalGapQueryDraft]
  );

  const metrics = useMemo(() => {
    if (!state) {
      return null;
    }
    const photoAssets = state.assets.filter((asset) => asset.asset_type === "photo");
    const previewReady = photoAssets.filter((asset) => asset.processing_status === "image_preview_ready");
    const retrievalPasses = state.retrieval.filter(retrievalHasPhotoMemory).length;
    return {
      voiceModeCount: Object.keys(state.audit.voice_mode_counts).length,
      sftCount: state.sft.included_count,
      dpoCount: state.dpo.included_count,
      demoPromptCount: state.demoReadiness.held_out_prompt_count,
      previewReadyCount: previewReady.length,
      photoAssetCount: photoAssets.length,
      photoDraftMemoryCount: countPhotoDraftMemories(state.memories),
      photoReviewTaskCount: state.tasks.filter(
        (task) =>
          task.status === "ready" &&
          task.task_type === "vision_draft_review" &&
          task.input_payload.source_photo_memory_draft === true
      ).length,
      photoPairTaskCount: state.tasks.filter(
        (task) =>
          task.status === "ready" &&
          task.task_type === "gold_voice_edit" &&
          typeof task.input_payload.source_photo_profile_id === "string"
      ).length,
      photoPairCandidateCount: state.photoPairCandidates.candidates.length,
      auditPackSampleCount: state.auditPack.sample_count,
      auditPackModeCount: state.auditPack.represented_modes.length,
      referencePackSampleCount: state.referencePack.sample_count,
      referencePackModeCount: state.referencePack.represented_modes.length,
      corpusRecordCount: state.corpus.record_count,
      corpusExcludedCount: Number(state.corpus.excluded_count ?? 0),
      vectorHandoffRecordCount: Number(state.vectorHandoff.manifest.record_count ?? 0),
      vectorHandoffExcludedCount: Number(state.vectorHandoff.manifest.excluded_count ?? 0),
      reviewedPhotoDemoReadyCount: Number(state.reviewedPhotoDemoReadiness.reviewed_vector_ready_count ?? 0),
      reviewedPhotoDemoActionCount: state.reviewedPhotoDemoReadiness.candidate_actions.length,
      draftVectorPreviewCount: Number(state.draftVectorPreview.manifest.record_count ?? 0),
      galleryItemCount: state.gallery.item_count,
      galleryDraftCount: state.gallery.draft_item_count,
      galleryReviewedCount: state.gallery.reviewed_item_count,
      galleryHiddenDraftCount: state.gallery.hidden_draft_count,
      photoNeedsContextCount: state.photoInventory.needs_context_count,
      photoNeedsContextGroupCount: state.photoInventory.needs_context_group_count,
      packNeedsContextGroupCount: state.photoContextPack.manifest.needs_context_group_count,
      packHeldDraftCount: state.photoContextPack.manifest.held_for_adam_review_count,
      packReviewedVectorReadyCount: state.photoContextPack.manifest.reviewed_vector_ready_count,
      packPhotoWorklistCount: state.photoContextPack.manifest.photo_context_worklist_count,
      packYamlPreviewChars: state.photoContextPack.export_preview_yaml.length,
      contextTaskProgressCount: state.photoContextProgress.reported_task_count,
      contextTaskDraftCount: state.photoContextProgress.draft_count,
      contextTaskSubmitReadyCount: state.photoContextProgress.submit_ready_count,
      contextTaskBlockedCount: state.photoContextProgress.blocked_count,
      photoDuplicateGroupCount: state.photoInventory.duplicate_group_count,
      retrievalPasses
    };
  }, [state]);

  const artifactAuditByKey = useMemo(() => {
    if (!state) {
      return new Map<string, boolean>();
    }
    return new Map(state.downstreamArtifactAudit.checks.map((check) => [check.artifact_key, check.hash_matches]));
  }, [state]);

  const artifactManifestByKey = useMemo(() => {
    if (!state) {
      return new Map();
    }
    return new Map(state.downstreamArtifactManifest.items.map((artifact) => [artifact.artifact_key, artifact]));
  }, [state]);

  const healthTone =
    state && metrics && state.audit.invalid_pair_count === 0 && metrics.sftCount >= 200 && metrics.dpoCount > 0 && metrics.retrievalPasses === activeRetrievalQueries.length
      ? "good"
      : "warning";
  const vectorSummaryAction =
    state?.vectorHandoff.next_review_actions?.find((action) => Boolean(action.review_task_id)) ??
    state?.vectorHandoff.manifest.next_review_actions?.find((action) => Boolean(action.review_task_id));
  const nextBottlenecks = state?.downstreamBottlenecks.items ?? [];
  const topPromptPairBlockerItem = state?.topBlockerSlice.items[0];
  const credentialRequirements = state?.demoReadiness.credential_requirements ?? state?.modelStatus.credential_requirements;

  return (
    <section className="downstream-readiness" aria-label="Downstream readiness" data-active-tab={activeTab}>
      <header className="readiness-header">
        <div>
          <span>
            <Sparkles size={15} />
            Downstream Readiness
          </span>
          <h3>Live gate snapshot</h3>
          <p>Review candidates, photo memory drafts, and retrieval checks stay visibly marked until Adam review promotes them.</p>
        </div>
        <button type="button" onClick={() => void load()} disabled={loading} title="Refresh prompt-pair, export, photo, and retrieval readiness checks.">
          <RefreshCw size={14} />
          {loading ? "Checking" : "Refresh"}
        </button>
      </header>

      <nav className="export-tab-bar" aria-label="Export readiness sections">
        {exportReadinessTabs.map((tab) => (
          <button
            key={tab.key}
            type="button"
            className={activeTab === tab.key ? "active" : ""}
            aria-pressed={activeTab === tab.key}
            onClick={() => setActiveTab(tab.key)}
          >
            <span>{tab.label}</span>
            <em>{tab.description}</em>
          </button>
        ))}
      </nav>

      <form className="memory-query-control" aria-label="Memory retrieval query control" onSubmit={handleApplyRetrievalGapQuery}>
        <label htmlFor="memory-retrieval-query">
          <span>Example retrieval probe</span>
          <input
            id="memory-retrieval-query"
            value={retrievalGapQueryDraft}
            onChange={(event) => setRetrievalGapQueryDraft(event.target.value)}
            aria-label="Memory query"
            placeholder="Describe a memory search to test retrieval readiness"
          />
        </label>
        <button type="submit" disabled={loading || !retrievalGapQueryDraft.trim()}>
          Apply query
        </button>
        <small>
          Active probe: <strong>{retrievalGapQuery}</strong>. This is an example search for retrieval readiness; it can prioritize photo context, but it is not a memory claim or a required answer for every photo.
        </small>
      </form>

      {error ? <div className="utility-alert danger">{error}</div> : null}

      <section className="readiness-card" aria-label="Morning handoff" data-export-tab="overview">
        <h4>Morning Handoff</h4>
        <p>{state?.morningHandoff.headline ?? "Building handoff..."}</p>
        <div className="photo-draft-list">
          {state?.morningHandoff.readiness_summary.slice(0, 5).map((item) => (
            <span key={item.area_key}>
              <em>{item.status}</em>
              <strong>{item.label}</strong>
              <small>{item.metric}</small>
            </span>
          ))}
        </div>
        <div className="handoff-strip">
          <span>
            Top bottleneck: <strong>{titleCase(state?.morningHandoff.primary_bottleneck_area_key ?? "pending")}</strong>
          </span>
          <span>
            Hash audit: <strong>{state?.morningHandoff.artifact_summary.all_hashes_match ? "all hashes match" : "needs attention"}</strong>
          </span>
          <span>
            Report hash: <code>{state?.morningHandoff.content_sha256 ?? "pending"}</code>
          </span>
        </div>
        <div className="photo-draft-list" aria-label="Morning retrieval gap work">
          <span>
            <em>Example probe gap</em>
            <strong>{state?.morningHandoff.retrieval_gap_work.query ?? "No query selected"}</strong>
            <small>{state?.morningHandoff.retrieval_gap_work.completion_signal ?? "completion signal pending"}</small>
          </span>
          <span>
            <em>No-claim candidates</em>
            <strong>{state?.morningHandoff.retrieval_gap_work.candidate_count ?? 0} candidates</strong>
            <small>{String(state?.morningHandoff.retrieval_gap_work.content_sha256 ?? "hash pending").slice(0, 16)}</small>
          </span>
          <span>
            <em>First candidate</em>
            <strong>{state?.morningHandoff.retrieval_gap_work.items[0]?.display_title ?? "No candidate yet"}</strong>
            <small>{state?.morningHandoff.retrieval_gap_work.review_policy ?? "no-claim policy pending"}</small>
          </span>
        </div>
        <div className="operator-checklist" aria-label="Operator checklist">
          {state?.morningHandoff.operator_checklist.slice(0, 4).map((item) => (
            <article key={item.checklist_id} data-status={item.status}>
              <div>
                <em>{String(item.priority_rank).padStart(2, "0")} / {item.status}</em>
                <strong>{item.label}</strong>
                <small>{item.completion_signal}</small>
                <small>{item.safety_boundary}</small>
              </div>
              <button
                type="button"
                disabled={item.status === "blocked" || (!item.task_id && item.area_key !== "photo_context")}
                onClick={() => void handleOpenMorningChecklistItem(item)}
                title={item.acceptance_test}
              >
                {item.action_label ?? "Open"}
              </button>
            </article>
          ))}
        </div>
        {state?.morningHandoff.top_bottlenecks[0]?.action.task_id ? (
          <button
            type="button"
            onClick={() => void onOpenReviewTask?.(state.morningHandoff.top_bottlenecks[0].action.task_id as string)}
          >
            Open top bottleneck
          </button>
        ) : null}
      </section>

      <section className="readiness-card" aria-label="Operator acceptance tests" data-export-tab="overview">
        <h4>Operator Acceptance Tests</h4>
        <div className="photo-draft-list">
          {state?.morningHandoff.operator_checklist.slice(0, 4).map((item) => (
            <span key={`acceptance-${item.checklist_id}`}>
              <em>{item.status}</em>
              <strong>{item.label}</strong>
              <small>{item.completion_signal}</small>
            </span>
          ))}
          <span>
            <em>{state?.downstreamArtifactAudit.all_hashes_match ? "passed" : "needs attention"}</em>
            <strong>Artifact hash audit</strong>
            <small>{state?.downstreamArtifactAudit.all_hashes_match ? "all hashes match" : `${state?.downstreamArtifactAudit.mismatch_count ?? 0} mismatches`}</small>
          </span>
          <span>
            <em>{state?.photoContextProgress.does_not_create_memory_claim ? "passed" : "needs attention"}</em>
            <strong>Photo progress proof</strong>
            <small>
              {state?.photoContextProgress.completion_signal ?? "completion signal pending"} / no memory claim / no embedding
            </small>
          </span>
        </div>
      </section>

      <section className="export-readiness-summary" aria-label="Export readiness summary" data-export-tab="overview">
        <header>
          <span>Export-ready now</span>
          <strong>Training, photo vectors, and demo gate</strong>
        </header>
        <div>
          <article data-tone={metrics && metrics.sftCount >= 200 && metrics.dpoCount > 0 ? "good" : "warning"}>
            <span>Training rows</span>
            <strong>
              {metrics?.sftCount ?? 0} SFT / {metrics?.dpoCount ?? 0} DPO
            </strong>
            <em>Reviewable rows; approved export still requires gold clearance.</em>
          </article>
          <article data-tone={metrics && metrics.vectorHandoffRecordCount > 0 ? "good" : "warning"}>
            <span>Photo vector handoff</span>
            <strong>
              {metrics?.vectorHandoffRecordCount ?? 0} ready / {metrics?.vectorHandoffExcludedCount ?? 0} held
            </strong>
            <em>{metrics?.photoNeedsContextGroupCount ?? 0} photo groups still need Adam context.</em>
            {vectorSummaryAction?.review_task_id ? (
              <button
                type="button"
                aria-label="Open fastest photo vector review"
                onClick={() => void onOpenReviewTask?.(vectorSummaryAction.review_task_id as string)}
                title={`Open ${vectorSummaryAction.review_task_human_id ?? "photo vector review task"}`}
              >
                Open fastest review
              </button>
            ) : null}
          </article>
          <article data-tone={metrics && metrics.contextTaskSubmitReadyCount > 0 ? "good" : "warning"}>
            <span>Photo review queue</span>
            <strong>
              {metrics?.contextTaskSubmitReadyCount ?? 0} submit-ready / {metrics?.contextTaskBlockedCount ?? 0} blocked
            </strong>
            <em>{metrics?.contextTaskDraftCount ?? 0} active draft task(s) in the session.</em>
          </article>
          <article data-tone={state?.demoReadiness.can_generate ? "good" : "warning"}>
            <span>Demo generation</span>
            <strong>{state?.demoReadiness.can_generate ? "Ready" : "Gated"}</strong>
            <em>{state?.demoReadiness.blockers.join(", ") || "No blockers"}</em>
          </article>
        </div>
      </section>

      <section className="bottleneck-queue" aria-label="Next bottleneck work queue" data-export-tab="overview">
        <header>
          <span>Next bottlenecks</span>
          <strong>Highest-leverage work across pairs, photos, vectors, and demo gate</strong>
        </header>
        <div>
          {nextBottlenecks.map((item, index) => (
            <article key={item.area_key}>
              <span>{String(index + 1).padStart(2, "0")}</span>
              <div>
                <strong>{item.area_label}</strong>
                <p>{item.summary}</p>
                <em>{item.next_action}</em>
              </div>
              {item.action.task_id ? (
                <button type="button" onClick={() => void onOpenReviewTask?.(item.action.task_id as string)}>
                  {item.action.label ?? "Open"}
                </button>
              ) : item.area_key === "photo_context" && item.action.enabled ? (
                <button
                  type="button"
                  onClick={() => void handleCreatePhotoContextReviewSession()}
                  disabled={photoActionKey === "photo-context-review-session"}
                >
                  {photoActionKey === "photo-context-review-session" ? "Creating" : item.action.label ?? "Create tasks"}
                </button>
              ) : (
                <button type="button" disabled>
                  {item.action.label ?? "Gated"}
                </button>
              )}
            </article>
          ))}
        </div>
      </section>

      <section className="artifact-download-grid" aria-label="Downstream artifact downloads" data-export-tab="artifacts">
        <article>
          <header>
            <Download size={14} />
            <span>Prompt pair audit pack</span>
          </header>
          <strong>Markdown for human review</strong>
          <code>{state?.auditPack.content_sha256 ?? "hash pending"}</code>
          <a href={getPromptPairAuditPackMarkdownUrl(200)} target="_blank" rel="noreferrer">
            Audit Markdown
          </a>
        </article>
        <article>
          <header>
            <Download size={14} />
            <span>Voice reference pack</span>
          </header>
          <strong>JSONL plus audit view</strong>
          <code>{state?.referencePack.content_sha256 ?? "hash pending"}</code>
          <div>
            <a href={getPromptPairReferencePackJsonlUrl(200)} target="_blank" rel="noreferrer">
              Reference JSONL
            </a>
            <a href={getPromptPairReferencePackMarkdownUrl(200)} target="_blank" rel="noreferrer">
              Reference Markdown
            </a>
          </div>
        </article>
        <article>
          <header>
            <Download size={14} />
            <span>Photo vector handoff</span>
          </header>
          <strong>Embedding input JSONL and manifest</strong>
          <code>{state?.vectorHandoff.manifest.content_sha256 ?? "hash pending"}</code>
          <div>
            <a href={getPhotoMemoryVectorHandoffJsonlUrl("family_private", 20)} target="_blank" rel="noreferrer">
              Vector JSONL
            </a>
            <a href={getPhotoMemoryVectorHandoffManifestUrl("family_private", 20)} target="_blank" rel="noreferrer">
              Vector manifest
            </a>
          </div>
        </article>
        <article>
          <header>
            <Download size={14} />
            <span>Photo session plan</span>
          </header>
          <strong>{state?.photoContextSessionPlan.selected_count ?? 0} no-claim photo groups</strong>
          <code>{artifactManifestByKey.get("photo_context_review_session_plan_yaml")?.content_sha256 ?? state?.photoContextSessionPlan.export_preview_sha256 ?? "hash pending"}</code>
          <small>{state?.photoContextSessionPlan.source_query ?? retrievalGapQuery} / query is prioritization only</small>
          <a href={getPhotoContextReviewSessionPlanYamlUrl("family_private", 5, retrievalGapQuery)} target="_blank" rel="noreferrer">
            Session YAML
          </a>
        </article>
        <article>
          <header>
            <FileJson size={14} />
            <span>Photo progress proof</span>
          </header>
          <strong>
            {state?.photoContextProgress.submit_ready_count ?? 0} submit-ready / {state?.photoContextProgress.reported_task_count ?? 0} tasks
          </strong>
          <code>{artifactManifestByKey.get("photo_context_session_progress_json")?.content_sha256 ?? state?.photoContextProgress.content_sha256 ?? "hash pending"}</code>
          <small>{state?.photoContextProgress.completion_signal ?? "completion signal pending"}</small>
          <a href={getPhotoContextSessionProgressUrl("family_private", 100)} target="_blank" rel="noreferrer">
            Progress JSON
          </a>
        </article>
        <article>
          <header>
            <Download size={14} />
            <span>Retrieval fields worklist</span>
          </header>
          <strong>
            {state?.photoContextRetrievalGapFieldWorklist.reported_item_count ?? 0} tasks /{" "}
            {state?.photoContextRetrievalGapFieldWorklist.missing_field_total ?? 0} missing fields
          </strong>
          <code>
            {artifactManifestByKey.get("photo_context_retrieval_gap_field_worklist_yaml")?.content_sha256 ??
              state?.photoContextRetrievalGapFieldWorklist.export_preview_sha256 ??
              "hash pending"}
          </code>
          <small>{state?.photoContextRetrievalGapFieldWorklist.completion_signal ?? "completion signal pending"}</small>
          <a href={getPhotoContextRetrievalGapFieldWorklistYamlUrl("family_private", 100)} target="_blank" rel="noreferrer">
            Field YAML
          </a>
        </article>
        <article>
          <header>
            <Download size={14} />
            <span>Retrieval payoff preview</span>
          </header>
          <strong>
            {state?.photoContextRetrievalGapPayoffPreview.reported_item_count ?? 0} previews /{" "}
            {state?.photoContextRetrievalGapPayoffPreview.unlockable_vector_record_count ?? 0} vector unlocks
          </strong>
          <code>
            {artifactManifestByKey.get("photo_context_retrieval_gap_payoff_preview_yaml")?.content_sha256 ??
              state?.photoContextRetrievalGapPayoffPreview.export_preview_sha256 ??
              "hash pending"}
          </code>
          <small>{state?.photoContextRetrievalGapPayoffPreview.review_policy ?? "payoff preview pending"}</small>
          <a href={getPhotoContextRetrievalGapPayoffPreviewYamlUrl("family_private", 10)} target="_blank" rel="noreferrer">
            Payoff YAML
          </a>
        </article>
        <article>
          <header>
            <Download size={14} />
            <span>Photo throughput priority</span>
          </header>
          <strong>
            {artifactManifestByKey.get("photo_review_priority_yaml")?.record_count ?? 0} ranked review tasks
          </strong>
          <code>{artifactManifestByKey.get("photo_review_priority_yaml")?.content_sha256 ?? "hash pending"}</code>
          <small>
            {String(
              artifactManifestByKey.get("photo_review_priority_yaml")?.policy?.completion_signal ??
                "completion signal pending"
            )}
          </small>
          <a href={getPhotoReviewPriorityYamlUrl("fastest_vector", 10)} target="_blank" rel="noreferrer">
            Priority YAML
          </a>
        </article>
        <article>
          <header>
            <Download size={14} />
            <span>DPO repair packet</span>
          </header>
          <strong>{state?.dpoRepairPacket.total_candidate_count ?? 0} rejected-reason gaps</strong>
          <code>{artifactManifestByKey.get("dpo_rejected_reason_repair_yaml")?.content_sha256 ?? state?.dpoRepairPacket.export_preview_sha256 ?? "hash pending"}</code>
          <small>{state?.dpoRepairPacket.completion_signal ?? "completion signal pending"}</small>
          <a href={getDpoRejectedReasonRepairPacketYamlUrl(25)} target="_blank" rel="noreferrer">
            Repair YAML
          </a>
        </article>
        <article>
          <header>
            <Sparkles size={14} />
            <span>Demo request preview</span>
          </header>
          <strong>{state?.demoRequestPreview.request_count ?? 0} exact request bodies</strong>
          <code>
            {artifactManifestByKey.get("demo_generation_request_preview_yaml")?.content_sha256 ??
              state?.demoRequestPreview.export_preview_sha256 ??
              "hash pending"}
          </code>
          <small>
            {artifactAuditByKey.get("demo_generation_request_preview_yaml") ? "hash ok" : "hash pending"} / no live model call
          </small>
          <a href={getDemoGenerationRequestPreviewYamlUrl(5)} target="_blank" rel="noreferrer">
            Request YAML
          </a>
        </article>
        <article>
          <header>
            <FileJson size={14} />
            <span>Artifact manifest</span>
          </header>
          <strong>{state?.downstreamArtifactManifest.artifact_count ?? 0} outputs / {state?.downstreamArtifactManifest.formats.join(", ") ?? "formats pending"}</strong>
          <code>{state?.downstreamArtifactManifest.content_sha256 ?? "hash pending"}</code>
          <small>
            Hash audit: {state?.downstreamArtifactAudit.all_hashes_match ? "all hashes match" : `${state?.downstreamArtifactAudit.mismatch_count ?? 0} mismatches`}
          </small>
          <a href={getDownstreamArtifactManifestUrl("family_private", 200, 20, retrievalGapQuery)} target="_blank" rel="noreferrer">
            Manifest JSON
          </a>
        </article>
        <article>
          <header>
            <Download size={14} />
            <span>Morning handoff</span>
          </header>
          <strong>Operator packet YAML</strong>
          <code>{artifactManifestByKey.get("morning_handoff_yaml")?.content_sha256 ?? "hash pending"}</code>
          <small>
            Hash audit: {artifactAuditByKey.get("morning_handoff_yaml") ? "hash ok" : "hash pending"}
          </small>
          <a href={getMorningHandoffYamlUrl("family_private", 200, 20, 4, retrievalGapQuery)} target="_blank" rel="noreferrer">
            Handoff YAML
          </a>
        </article>
      </section>

      <section className="readiness-card" aria-label="Artifact manifest table" data-export-tab="artifacts">
        <h4>Artifact Manifest</h4>
        <div className="photo-draft-list">
          {state?.downstreamArtifactManifest.items.map((artifact) => {
            const labels = eligibilityLabels(artifact.eligibility).join(", ") || "Review only";
            const hashMatches = artifactAuditByKey.get(artifact.artifact_key);
            return (
              <span key={artifact.artifact_key}>
                <em>
                  {artifact.format.toUpperCase()} / {titleCase(artifact.artifact_family)}
                </em>
                <strong>{artifact.label}</strong>
                <small>
                  {labels} / {hashMatches ? "hash ok" : "hash pending"}
                </small>
              </span>
            );
          })}
        </div>
      </section>

      <section className="readiness-card" aria-label="Artifact hash audit details" data-export-tab="artifacts">
        <h4>Artifact Hash Audit</h4>
        <p>
          {state?.downstreamArtifactAudit.checked_count ?? 0} checked / {state?.downstreamArtifactAudit.mismatch_count ?? 0} mismatches
        </p>
        <div className="photo-draft-list">
          {state?.downstreamArtifactAudit.checks.map((check) => {
            const artifact = artifactManifestByKey.get(check.artifact_key);
            return (
              <span key={check.artifact_key} data-status={check.hash_matches ? "ok" : "mismatch"}>
                <em>
                  {check.format?.toUpperCase() ?? "ARTIFACT"} / {check.hash_matches ? "hash ok" : "hash mismatch"}
                </em>
                <strong>{artifact?.label ?? titleCase(check.artifact_key)}</strong>
                <small>
                  declared {check.declared_sha256.slice(0, 12)} / recomputed {check.recomputed_sha256.slice(0, 12)}
                </small>
              </span>
            );
          })}
        </div>
      </section>

      <div className="readiness-metrics" data-export-tab="overview">
        <article data-tone={healthTone}>
          <ShieldCheck size={15} />
          <span>Audit</span>
          <strong>{state?.audit.inspectable_pair_count ?? 0}</strong>
          <em>{state?.audit.invalid_pair_count ?? 0} invalid</em>
        </article>
        <article>
          <FileJson size={15} />
          <span>SFT</span>
          <strong>{metrics?.sftCount ?? 0}</strong>
          <em>{state?.sft.mode ?? "candidate dry-run"}</em>
        </article>
        <article>
          <FileJson size={15} />
          <span>DPO</span>
          <strong>{metrics?.dpoCount ?? 0}</strong>
          <em>{state?.dpo.mode ?? "candidate dry-run"}</em>
        </article>
        <article data-tone={state?.auditPack.representative_requirements_met ? "good" : "warning"}>
          <ClipboardList size={15} />
          <span>200-pack</span>
          <strong>{metrics?.auditPackSampleCount ?? 0}</strong>
          <em>{metrics?.auditPackModeCount ?? 0} modes represented</em>
        </article>
        <article data-tone={state?.referencePack.ready_for_generation_context ? "good" : "warning"}>
          <ClipboardList size={15} />
          <span>References</span>
          <strong>{metrics?.referencePackSampleCount ?? 0}</strong>
          <em>{metrics?.referencePackModeCount ?? 0} modes / {state?.referencePack.duplicate_excluded_count ?? 0} dupes excluded</em>
        </article>
        <article>
          <Sparkles size={15} />
          <span>Text model</span>
          <strong>{state?.modelStatus.text_generation_model ?? "gpt-5.5"}</strong>
          <em>{state?.modelStatus.text_generation_reasoning_effort ?? "xhigh"} / {state?.modelStatus.text_generation_live_ready ? "live ready" : "gated"}</em>
        </article>
        <article data-tone={state?.demoReadiness.can_generate ? "good" : "warning"}>
          <Sparkles size={15} />
          <span>Demo gate</span>
          <strong>{metrics?.demoPromptCount ?? 0}</strong>
          <em>{state?.demoReadiness.can_generate ? "ready for live generation" : "blocked honestly"}</em>
        </article>
        <article>
          <Image size={15} />
          <span>Photos</span>
          <strong>{metrics ? `${metrics.previewReadyCount}/${metrics.photoAssetCount}` : "0/0"}</strong>
          <em>{metrics?.photoNeedsContextGroupCount ?? 0} groups need context / {metrics?.photoDuplicateGroupCount ?? 0} duplicate groups</em>
        </article>
        <article>
          <FileJson size={15} />
          <span>Photo pairs</span>
          <strong>{metrics?.photoPairTaskCount ?? 0}</strong>
          <em>{metrics?.photoPairCandidateCount ?? 0} grounded candidates</em>
        </article>
        <article>
          <Search size={15} />
          <span>Corpus</span>
          <strong>{metrics?.corpusRecordCount ?? 0}</strong>
          <em>
            {metrics?.corpusExcludedCount
              ? `${metrics.corpusExcludedCount} held for Adam review`
              : metrics
                ? `${metrics.retrievalPasses}/${activeRetrievalQueries.length} retrieval checks`
                : `0/${activeRetrievalQueries.length} retrieval checks`}
          </em>
        </article>
        <article data-tone={metrics && metrics.vectorHandoffRecordCount > 0 ? "good" : "warning"}>
          <FileJson size={15} />
          <span>Vector handoff</span>
          <strong>{metrics?.vectorHandoffRecordCount ?? 0}</strong>
          <em>{metrics?.vectorHandoffExcludedCount ?? 0} held for Adam review</em>
        </article>
        <article data-tone={state?.reviewedPhotoDemoReadiness.can_show_reviewed_vector_memory ? "good" : "warning"}>
          <Image size={15} />
          <span>Photo demo</span>
          <strong>{metrics?.reviewedPhotoDemoReadyCount ?? 0}</strong>
          <em>
            {state?.reviewedPhotoDemoReadiness.can_show_reviewed_vector_memory
              ? "reviewed memory ready"
              : `${metrics?.reviewedPhotoDemoActionCount ?? 0} review actions`}
          </em>
        </article>
        <article data-tone={metrics && metrics.galleryItemCount > 0 ? "warning" : "neutral"}>
          <Image size={15} />
          <span>Gallery</span>
          <strong>{metrics?.galleryItemCount ?? 0}</strong>
          <em>{metrics?.galleryReviewedCount ?? 0} reviewed / {metrics?.galleryDraftCount ?? 0} draft</em>
        </article>
      </div>

      <div className="readiness-columns">
        <section className="readiness-card" data-export-tab="prompt_pairs">
          <h4>Voice Mode Coverage</h4>
          <div className="voice-mode-list">
            {state
              ? topVoiceModes(state.audit).map(([mode, count]) => (
                  <span key={mode}>
                    <em>{titleCase(mode)}</em>
                    <strong>{count}</strong>
                  </span>
                ))
              : null}
          </div>
        </section>

        <section className="readiness-card" data-export-tab="prompt_pairs">
          <h4>200-Pair Human Audit Pack</h4>
          <div className="photo-draft-list">
            <span>
              <em>Samples</em>
              <strong>{state?.auditPack.sample_count ?? 0} examples ready for human audit</strong>
            </span>
            <span>
              <em>Weak spots</em>
              <strong>{state?.auditPack.known_weak_spots[0] ?? "None recorded"}</strong>
            </span>
            <span>
              <em>Markdown audit</em>
              <strong>
                <a href={getPromptPairAuditPackMarkdownUrl(200)} target="_blank" rel="noreferrer">
                  {state?.auditPack.markdown.length ?? 0} chars ready
                </a>
              </strong>
            </span>
          </div>
        </section>

        <section className="readiness-card" aria-label="Held prompt pair review pack" data-export-tab="prompt_pairs">
          <h4>Held Prompt Pair Review Pack</h4>
          <div className="photo-draft-list">
            <span>
              <em>Candidates</em>
              <strong>
                {state?.heldPromptPairs.reported_candidate_count ?? 0} shown / {state?.heldPromptPairs.total_candidate_count ?? 0} held
              </strong>
            </span>
            <span>
              <em>Top blockers</em>
              <strong>
                {state
                  ? Object.entries(state.heldPromptPairs.blocker_counts)
                      .slice(0, 3)
                      .map(([blocker, count]) => `${titleCase(blocker)} ${count}`)
                      .join(" / ") || "None"
                  : "Checking"}
              </strong>
            </span>
            <span>
              <em>Review policy</em>
              <strong>{state?.heldPromptPairs.does_not_promote_to_training_export ? "Candidate review only, no export promotion" : "Needs policy check"}</strong>
            </span>
            <span>
              <em>Pack hash</em>
              <strong>{String(state?.heldPromptPairs.content_sha256 ?? "hash pending").slice(0, 16)}</strong>
            </span>
          </div>
          <div className="photo-draft-list" aria-label="Top prompt pair blocker slice">
            <span>
              <em>Top blocker</em>
              <strong>{state?.topBlockerSlice.blocker ? titleCase(state.topBlockerSlice.blocker) : "No blocker"}</strong>
              <small>
                {state?.topBlockerSlice.selection_policy ? titleCase(state.topBlockerSlice.selection_policy) : "Selection pending"} /{" "}
                {state?.topBlockerSlice.completion_signal ?? "completion signal pending"}
              </small>
              {topPromptPairBlockerItem?.task_id ? (
                <button type="button" onClick={() => void onOpenReviewTask?.(topPromptPairBlockerItem.task_id)}>
                  Open top blocker
                </button>
              ) : null}
            </span>
            <span>
              <em>Slice hash</em>
              <strong>{String(state?.topBlockerSlice.content_sha256 ?? "hash pending").slice(0, 16)}</strong>
              <small>{state?.topBlockerSlice.review_policy ?? "read-only review slice"}</small>
            </span>
            {state?.topBlockerSlice.items.slice(0, 3).map((item) => (
              <span key={item.task_id}>
                <em>
                  {item.task_human_id} / {titleCase(item.artifact_mode)}
                </em>
                <strong>{item.prompt}</strong>
                <small>
                  YAML preview / {item.backend_preflight.blockers.map(titleCase).join(", ")}
                </small>
                {item.source_boundary_summary ? (
                  <small>
                    Source boundary: {titleCase(item.source_boundary_summary.status)} / blocks{" "}
                    {item.source_boundary_summary.blocked_training_uses.map(titleCase).join(", ") || "nothing"}
                  </small>
                ) : null}
                <button type="button" onClick={() => void onOpenReviewTask?.(item.task_id)}>
                  Open blocker repair
                </button>
              </span>
            ))}
          </div>
          {promptPairFocusStatus ? <div className="utility-alert">{promptPairFocusStatus}</div> : null}
          <section className="photo-context-session-queue prompt-pair-session-plan" aria-label="Prompt pair blocker session plan">
            <header>
              <div>
                <span>Prompt Pair Blocker Session</span>
                <strong>
                  {state?.topBlockerSessionPlan.selected_count ?? 0} selected /{" "}
                  {state?.topBlockerSessionPlan.candidate_count ?? 0} candidates
                </strong>
                <em>
                  {state?.topBlockerSessionPlan.selection_policy ? titleCase(state.topBlockerSessionPlan.selection_policy) : "Selection pending"} /{" "}
                  {state?.topBlockerSessionPlan.completion_signal ?? "session plan pending"}
                </em>
              </div>
              <code>{String(state?.topBlockerSessionPlan.export_preview_sha256 ?? "hash pending").slice(0, 16)}</code>
            </header>
            <div className="session-field-prompts" aria-label="Prompt pair session fields">
              {state?.topBlockerSessionPlan.field_plan.map((field) => (
                <span key={field.field}>
                  <em>{titleCase(field.field)}</em>
                  <strong>{field.prompt}</strong>
                  <small>{titleCase(field.truth_status_after_submit)}</small>
                </span>
              ))}
            </div>
            <ol>
              {state?.topBlockerSessionPlan.items.slice(0, 5).map((item) => (
                <li key={item.task_id}>
                  <div>
                    <span>{String(item.sequence_number).padStart(2, "0")}</span>
                    <strong>{item.prompt}</strong>
                    <em>
                      {item.task_human_id} / {titleCase(item.artifact_mode)} / {item.current_blockers.map(titleCase).join(", ")}
                    </em>
                    {item.source_boundary_summary ? (
                      <small>
                        Source boundary blocks {item.source_boundary_summary.blocked_training_uses.map(titleCase).join(", ")};{" "}
                        {item.source_boundary_summary.remediation_options[0]}
                      </small>
                    ) : null}
                    <small>{item.completion_criteria.slice(0, 2).join("; ")}</small>
                  </div>
                  <button type="button" onClick={() => void onOpenReviewTask?.(item.task_id)}>
                    Open session item
                  </button>
                </li>
              ))}
            </ol>
          </section>
          <div className="photo-draft-list" aria-label="DPO rejected reason repair packet">
            <span>
              <em>DPO repair packet</em>
              <strong>
                {state?.dpoRepairPacket.reported_candidate_count ?? 0} shown / {state?.dpoRepairPacket.total_candidate_count ?? 0} rejected-reason gaps
              </strong>
              <small>{state?.dpoRepairPacket.review_policy ?? "repair packet pending"}</small>
            </span>
            <span>
              <em>Repair fields</em>
              <strong>{state?.dpoRepairPacket.repair_fields.map(titleCase).join(", ") ?? "failure modes"}</strong>
              <small>{state?.dpoRepairPacket.export_preview_sha256.slice(0, 16) ?? "hash pending"}</small>
            </span>
            {state?.dpoRepairPacket.items[0]?.repair_projection ? (
              <span>
                <em>Non-mutating projection</em>
                <strong>
                  {state.dpoRepairPacket.items[0].repair_projection.target_blocker_cleared
                    ? "Target blocker clears"
                    : "Target blocker remains"}
                </strong>
                <small>
                  {state.dpoRepairPacket.items[0].repair_projection.before_blockers.length} before /{" "}
                  {state.dpoRepairPacket.items[0].repair_projection.after_blockers.length} after / Adam review still required
                </small>
              </span>
            ) : null}
            {state?.dpoRepairProjection.found ? (
              <div className="repair-projection-receipt" aria-label="DPO repair projection receipt">
                <span>
                  <em>Single-ticket repair receipt</em>
                  <strong>{state.dpoRepairProjection.task_human_id ?? "DPO repair candidate"}</strong>
                  <small>{state.dpoRepairProjection.prompt}</small>
                </span>
                <span>
                  <em>Before blockers</em>
                  <strong>{state.dpoRepairProjection.before.blockers.map(titleCase).join(", ") || "None"}</strong>
                  <small>{state.dpoRepairProjection.before.dataset_outcome}</small>
                </span>
                <span>
                  <em>Projected after blockers</em>
                  <strong>{state.dpoRepairProjection.after.blockers.map(titleCase).join(", ") || "None"}</strong>
                  <small>
                    {state.dpoRepairProjection.target_blocker_cleared ? "Rejected reason blocker clears" : "Rejected reason blocker remains"}
                    {" / "}
                    {state.dpoRepairProjection.still_requires_adam_gold_edit ? "Adam gold edit still required" : "Needs review"}
                  </small>
                </span>
                <span>
                  <em>Failure mode patch</em>
                  <strong>{state.dpoRepairProjection.after.failure_modes.map(titleCase).join(", ") || "None"}</strong>
                  <small>
                    non-mutating / hash <code>{state.dpoRepairProjection.content_sha256.slice(0, 16)}</code>
                  </small>
                </span>
                {state.dpoRepairProjection.suggested_rejected_issue?.note ? (
                  <span>
                    <em>Suggested rejected note</em>
                    <strong>{titleCase(state.dpoRepairProjection.suggested_rejected_issue.issue_tag)}</strong>
                    <small>{state.dpoRepairProjection.suggested_rejected_issue.note}</small>
                  </span>
                ) : null}
                <details>
                  <summary>YAML diff preview</summary>
                  <pre>{state.dpoRepairProjection.yaml_diff_preview}</pre>
                </details>
              </div>
            ) : null}
            {state?.dpoRepairPacket.items.slice(0, 3).map((item) => (
              <span key={item.task_id}>
                <em>
                  {item.task_human_id} / {titleCase(item.voice_mode)}
                </em>
                <strong>{item.prompt}</strong>
                <small>{item.backend_preflight.blockers.map(titleCase).join(", ")}</small>
                <button type="button" onClick={() => void onOpenReviewTask?.(item.task_id)}>
                  Open DPO repair
                </button>
              </span>
            ))}
          </div>
          <div className="photo-draft-list">
            {state?.heldPromptPairs.candidates.slice(0, 5).map((candidate) => (
              <span key={candidate.task_id}>
                <em>
                  {candidate.task_human_id} / {titleCase(candidate.voice_mode)}
                </em>
                <strong>{candidate.prompt}</strong>
                <small>{candidate.blockers.map(titleCase).join(", ") || candidate.dataset_outcome}</small>
                {candidate.source_boundary_summary ? (
                  <small>
                    Source boundary: {candidate.source_boundary_summary.blocked_training_uses.map(titleCase).join(", ")} blocked
                  </small>
                ) : null}
                <button type="button" onClick={() => void onOpenReviewTask?.(candidate.task_id)}>
                  Open held pair
                </button>
              </span>
            ))}
          </div>
          <div className="photo-draft-list" aria-label="Prompt pair blocker worklists">
            {state?.heldPromptPairs.worklists.slice(0, 4).map((worklist) => (
              <span key={worklist.worklist_key}>
                <em>
                  {titleCase(worklist.blocker)} / {worklist.candidate_count} held
                </em>
                <strong>{worklist.title}</strong>
                <small>
                  Sequence {worklist.sequence_start ?? "?"}-{worklist.sequence_end ?? "?"} / {worklist.review_sequence_key.slice(0, 12)}
                </small>
                {worklist.candidate_previews[0]?.source_boundary_summary ? (
                  <small>
                    Boundary decision: {worklist.candidate_previews[0].source_boundary_summary.blocked_training_uses.map(titleCase).join(", ")} blocked
                  </small>
                ) : null}
                <button
                  type="button"
                  onClick={() => void handleFocusPromptPairWorklist(worklist)}
                  disabled={loading || promptPairActionKey === worklist.worklist_key}
                >
                  {loading ? "Checking" : promptPairActionKey === worklist.worklist_key ? "Focusing" : "Focus blocker"}
                </button>
              </span>
            ))}
          </div>
        </section>

        <section className="readiness-card" data-export-tab="model">
          <h4>Demo Generation Gate</h4>
          <div className="photo-draft-list">
            <span>
              <em>Status</em>
              <strong>{state?.demoReadiness.status ? titleCase(state.demoReadiness.status) : "Checking"}</strong>
            </span>
            <span>
              <em>Held-out prompts</em>
              <strong>{state?.demoReadiness.held_out_prompt_count ?? 0} prompts reserved</strong>
            </span>
            <span>
              <em>Blockers</em>
              <strong>{state?.demoReadiness.blockers.join(", ") || "None"}</strong>
            </span>
            <span>
              <em>Output policy</em>
              <strong>
                {state?.demoReadiness.safety_policy.outputs_truth_status === "model_generated"
                  ? "model_generated / excluded from training"
                  : "needs policy check"}
              </strong>
            </span>
            <span>
              <em>Credential setup</em>
              <strong>
                {(credentialRequirements?.required_env ?? [])
                  .map((item) => `${item.name}${item.configured ? " ok" : item.required_value ? `=${item.required_value}` : " needed"}`)
                  .join(" / ") || "No live credential requirements"}
              </strong>
              <small>{credentialRequirements?.safety_policy.fine_tuning_api_calls_allowed === false ? "No fine-tuning calls in MVP" : "policy pending"}</small>
              {credentialRequirements?.env_file_policy ? (
                <small>
                  Secrets stay local: {credentialRequirements.env_file_policy.ignored_patterns.join(", ")} ignored /{" "}
                  {credentialRequirements.env_file_policy.tracked_template} tracked
                </small>
              ) : null}
            </span>
          </div>
          <section className="demo-input-plan" aria-label="Demo generation input plan">
            <div>
              <em>Model request</em>
              <strong>
                {state?.demoReadiness.generation_input_plan
                  ? `${state.demoReadiness.generation_input_plan.model_name} / ${state.demoReadiness.generation_input_plan.reasoning_effort}`
                  : "gpt-5.5 / xhigh"}
              </strong>
            </div>
            <div>
              <em>Reference pack hash</em>
              <code>{state?.demoReadiness.generation_input_plan?.reference_pack_content_sha256 ?? state?.referencePack.content_sha256 ?? "hash pending"}</code>
            </div>
            <div>
              <em>Held-out prompt set hash</em>
              <code>{state?.demoReadiness.generation_input_plan?.held_out_prompt_set_sha256 ?? "hash pending"}</code>
            </div>
            <div>
              <em>Live call policy</em>
              <strong>
                {state?.demoReadiness.generation_input_plan?.store === false ? "store=false" : "store policy pending"} /{" "}
                {state?.demoReadiness.generation_input_plan?.live_generation_ready ? "live ready" : "blocked"}
              </strong>
            </div>
            <ul>
              {(state?.demoReadiness.generation_input_plan?.held_out_prompts ?? state?.demoReadiness.held_out_prompts ?? [])
                .slice(0, 3)
                .map((prompt) => (
                  <li key={prompt.task_id}>
                    <span>{prompt.voice_mode ? titleCase(String(prompt.voice_mode)) : "Held-out prompt"}</span>
                    <strong>{prompt.prompt}</strong>
                    {prompt.prompt_sha256 ? <code>{prompt.prompt_sha256}</code> : null}
                  </li>
              ))}
            </ul>
          </section>
          <section className="demo-input-plan demo-request-preview" aria-label="Demo generation exact request preview">
            <div>
              <em>Exact request preview</em>
              <strong>
                {state?.demoRequestPreview.request_count ?? 0} Responses API request bodies /{" "}
                {state?.demoRequestPreview.no_live_model_call ? "no live model call" : "policy pending"}
              </strong>
            </div>
            <div>
              <em>Preview hash</em>
              <code>{state?.demoRequestPreview.export_preview_sha256 ?? "hash pending"}</code>
            </div>
            <div>
              <em>Generation policy</em>
              <strong>
                {state?.demoRequestPreview.no_generation_created ? "No generation created" : "Needs review"} /{" "}
                {state?.demoRequestPreview.does_not_promote_to_training_export ? "no training export promotion" : "promotion policy pending"}
              </strong>
            </div>
            {state?.demoRequestPreview.requests.slice(0, 2).map((request) => (
              <div key={request.task_id} className="demo-request-preview-item">
                <em>
                  {request.task_human_id} / {titleCase(request.voice_mode ?? "unknown")}
                </em>
                <strong>{request.prompt}</strong>
                <small>
                  Request {request.request_body_sha256.slice(0, 16)} / {request.user_message_char_count} chars /{" "}
                  {request.reference_example_count} references
                </small>
                <small>
                  {request.safety_checks.held_out_answer_excluded_from_request ? "Held-out answer excluded" : "held-out answer needs audit"}
                  {" / "}
                  {request.safety_checks.rejected_response_excluded_from_request ? "Rejected response excluded" : "rejected response needs audit"}
                </small>
                <details>
                  <summary>Request body JSON</summary>
                  <pre>{request.request_body_json}</pre>
                </details>
              </div>
            ))}
          </section>
          <div className="readiness-actions">
            <button
              type="button"
              onClick={() => void handleCreateDemoGenerations()}
              disabled={!state?.demoReadiness.can_generate}
              title={
                state?.demoReadiness.can_generate
                  ? "Create model_generated demo outputs"
                  : `Blocked: ${state?.demoReadiness.blockers.join(", ") || "demo gate"}`
              }
            >
              <Sparkles size={14} />
              Generate demo outputs
            </button>
            <span>{demoActionStatus || "Requires live GPT-5.5 credentials"}</span>
          </div>
        </section>

        <section className="readiness-card" data-export-tab="model prompt_pairs">
          <h4>Voice Reference Pack</h4>
          <div className="photo-draft-list">
            <span>
              <em>Generation context</em>
              <strong>{state?.referencePack.sample_count ?? 0} prompt pairs selected</strong>
            </span>
            <span>
              <em>Safety policy</em>
              <strong>{state?.referencePack.safety_policy.does_not_certify_final_authenticity ? "Reference only, not final truth" : "Needs review"}</strong>
            </span>
            <span>
              <em>JSONL / Markdown</em>
              <strong>
                <a href={getPromptPairReferencePackJsonlUrl(200)} target="_blank" rel="noreferrer">
                  {String(state?.referencePack.content_sha256 ?? "").slice(0, 12) || "JSONL"}
                </a>
                {" / "}
                <a href={getPromptPairReferencePackMarkdownUrl(200)} target="_blank" rel="noreferrer">
                  audit view
                </a>
              </strong>
            </span>
          </div>
        </section>

        <section className="readiness-card" data-export-tab="photos">
          <h4>Retrieval Proof</h4>
          <div className="retrieval-proof-list">
            {state?.retrieval.map((search) => {
              const top = search.results[0];
              const passed = retrievalHasPhotoMemory(search);
              return (
                <article key={search.query} data-tone={passed ? "good" : "warning"}>
                  <CheckCircle2 size={13} />
                  <div>
                    <strong>{search.query}</strong>
                    <span>{top ? top.title : search.retrieval_gap?.message ?? "No memory result yet"}</span>
                    {top?.matched_terms.length ? <em>{top.matched_terms.join(", ")}</em> : null}
                    <em>{retrievalResultReviewLabel(top)}</em>
                    {!top && search.retrieval_gap ? (
                      <em>
                        {search.retrieval_gap.photo_groups_needing_context_count} need context / {search.retrieval_gap.photo_groups_needing_draft_review_count ?? 0} drafts need review
                      </em>
                    ) : null}
                    {!top && search.retrieval_gap ? <em>{retrievalGapEvidenceSummary(search.retrieval_gap)}</em> : null}
                    {!top && search.retrieval_gap?.sample_context_groups.length ? (
                      <div className="retrieval-gap-actions" aria-label={`Candidate photo groups for ${search.query}`}>
                        {search.retrieval_gap.sample_context_groups.slice(0, 3).map((group) => (
                          <button
                            key={`${search.query}-${group.group_key}`}
                            type="button"
                            disabled={photoActionKey === group.group_key}
                            onClick={() => void handleOpenRetrievalGapCandidate(group, search.query)}
                            aria-label={retrievalGapCandidateTitle(group)}
                            title={retrievalGapCandidateTitle(group)}
                          >
                            {photoActionKey === group.group_key ? "Opening" : retrievalGapCandidateLabel(group)}
                          </button>
                        ))}
                      </div>
                    ) : null}
                  </div>
                </article>
              );
            })}
          </div>
          <div className="photo-draft-list" aria-label="Retrieval gap review slice summary">
            <span>
              <em>Gap slice</em>
              <strong>{state?.retrievalGapSlice.query ?? "No query selected"}</strong>
              <small>{state?.retrievalGapSlice.completion_signal ?? "completion signal pending"}</small>
            </span>
            <span>
              <em>No-claim candidates</em>
              <strong>
                {state?.retrievalGapSlice.weak_evidence_candidate_count ?? 0} weak / {state?.retrievalGapSlice.backlog_only_candidate_count ?? 0} backlog
              </strong>
              <small>{state?.retrievalGapSlice.review_policy ?? "retrieval gap policy pending"}</small>
            </span>
            <span>
              <em>Slice hash</em>
              <strong>{String(state?.retrievalGapSlice.content_sha256 ?? "hash pending").slice(0, 16)}</strong>
              <small>{state?.retrievalGapSlice.gap_open ? "No memory result yet" : "Resolved"}</small>
            </span>
          </div>
          <div className="photo-review-pack-list" aria-label="Retrieval gap review slice">
            {state?.retrievalGapSlice.items.slice(0, 3).map((item) => (
              <article key={item.item_key} data-tone="warning">
                <img src={getAssetPreviewUrl(item.source_photo_id, "thumbnail")} alt="" loading="lazy" />
                <div>
                  <strong>{item.display_title}</strong>
                  <span>{titleCase(item.candidate_match_quality ?? "backlog_only")} / {titleCase(item.retrieval_gap_truth_status)}</span>
                  <em>
                    {item.matched_query_terms.length
                      ? `Query match: ${item.matched_query_terms.join(", ")}`
                      : "No direct filename match; backlog review candidate"}
                  </em>
                  <small>{item.completion_criteria[2] ?? "Adam-authored context required before memory."}</small>
                  <button
                    type="button"
                    onClick={() => void handleOpenRetrievalGapSliceItem(item)}
                    disabled={photoActionKey === item.item_key}
                    title={`${item.action.label ?? "Open review task"} for ${item.display_title}`}
                  >
                    {photoActionKey === item.item_key ? "Opening" : item.action.label ?? "Open review task"}
                  </button>
                </div>
              </article>
            ))}
          </div>
        </section>

        <section className="readiness-card" data-export-tab="photos">
          <h4>Photo Intake Inventory</h4>
          <div className="photo-draft-list">
            <span>
              <em>Needs context</em>
              <strong>{state?.photoInventory.needs_context_group_count ?? 0} photo groups / {state?.photoInventory.needs_context_count ?? 0} assets</strong>
            </span>
            <span>
              <em>Duplicate groups</em>
              <strong>{state?.photoInventory.duplicate_group_count ?? 0} copy/variant clusters</strong>
            </span>
            {state?.photoInventory.groups.filter((group) => group.needs_context).slice(0, 3).map((group) => (
              <span key={group.group_key}>
                <em>{group.display_title}</em>
                <strong>{group.asset_count} asset{group.asset_count === 1 ? "" : "s"} / {group.needs_context_count} need context</strong>
                <button type="button" onClick={() => void handleCreatePhotoContextTask(group.group_key)} disabled={photoActionKey === group.group_key}>
                  {photoActionKey === group.group_key ? "Creating" : "Create task"}
                </button>
              </span>
            ))}
          </div>
        </section>

        <section className="readiness-card" aria-label="Photo context review pack" data-export-tab="photos">
          <h4>Photo Context Review Pack</h4>
          <div className="photo-draft-list">
            <span>
              <em>No-claim photo groups</em>
              <strong>{metrics?.packNeedsContextGroupCount ?? 0} groups need Adam context</strong>
            </span>
            <span>
              <em>Machine drafts held</em>
              <strong>{metrics?.packHeldDraftCount ?? 0} not for vector DB yet</strong>
            </span>
            <span>
              <em>Reviewed vector-ready</em>
              <strong>{metrics?.packReviewedVectorReadyCount ?? 0} records / {state?.photoContextPack.manifest.vector_policy_violation_count ?? 0} policy violations</strong>
            </span>
            <span>
              <em>Review worklists</em>
              <strong>{metrics?.packPhotoWorklistCount ?? 0} batch queues</strong>
            </span>
            <span>
              <em>Review task progress</em>
              <strong>
                {metrics?.contextTaskSubmitReadyCount ?? 0} submit-ready / {metrics?.contextTaskDraftCount ?? 0} drafted / {metrics?.contextTaskProgressCount ?? 0} tasks
              </strong>
            </span>
            <span>
              <em>Progress proof</em>
              <strong>{state?.photoContextProgress.completion_signal ?? "progress proof pending"}</strong>
              <small>
                {state?.photoContextProgress.does_not_create_memory_claim && state.photoContextProgress.does_not_create_embedding_record
                  ? `no memory claim / no embedding / ${state.photoContextProgress.content_sha256.slice(0, 16)}`
                  : "boundary proof pending"}
              </small>
            </span>
            <span>
              <em>Projection blockers</em>
              <strong>
                {state && Object.keys(state.photoContextProgress.blocked_reason_counts).length > 0
                  ? Object.entries(state.photoContextProgress.blocked_reason_counts)
                      .slice(0, 3)
                      .map(([reason, count]) => `${titleCase(reason)} (${count})`)
                      .join(", ")
                  : "None in saved drafts"}
              </strong>
            </span>
            <span>
              <em>Retrieval gap fields</em>
              <strong>
                {state && Object.keys(state.photoContextProgress.retrieval_gap_missing_field_counts).length > 0
                  ? Object.entries(state.photoContextProgress.retrieval_gap_missing_field_counts)
                      .slice(0, 3)
                      .map(([field, count]) => `${titleCase(field)} (${count})`)
                      .join(", ")
                  : "No missing retrieval fields"}
              </strong>
              <small>{state?.photoContextProgress.retrieval_gap_task_count ?? 0} retrieval-gap task(s)</small>
            </span>
            <span>
              <em>Field worklist artifact</em>
              <strong>
                {state?.photoContextRetrievalGapFieldWorklist.reported_item_count ?? 0} tasks /{" "}
                {state?.photoContextRetrievalGapFieldWorklist.missing_field_total ?? 0} missing fields
              </strong>
              <small>
                {artifactAuditByKey.get("photo_context_retrieval_gap_field_worklist_yaml") ? "hash ok" : "hash pending"} /{" "}
                {String(state?.photoContextRetrievalGapFieldWorklist.export_preview_sha256 ?? "hash pending").slice(0, 16)}
              </small>
            </span>
          </div>
          <div className="repair-projection-receipt" aria-label="Retrieval gap field worklist">
            <span>
              <em>Review policy</em>
              <strong>{state?.photoContextRetrievalGapFieldWorklist.review_policy ?? "retrieval gap policy pending"}</strong>
              <small>{state?.photoContextRetrievalGapFieldWorklist.completion_signal ?? "completion signal pending"}</small>
            </span>
            <span>
              <em>Missing fields</em>
              <strong>
                {state?.photoContextRetrievalGapFieldWorklist.missing_field_counts
                  .slice(0, 4)
                  .map((field) => `${titleCase(field.field_key)} (${field.count})`)
                  .join(", ") || "No missing retrieval fields"}
              </strong>
              <small>{state?.photoContextRetrievalGapFieldWorklist.query_counts[0]?.query ?? "No retrieval query yet"}</small>
            </span>
            <span>
              <em>Field guidance</em>
              <strong>
                {state?.photoContextRetrievalGapFieldWorklist.field_guidance
                  .map((field) => field.label)
                  .join(", ") || "Guidance pending"}
              </strong>
              <small>
                {state?.photoContextRetrievalGapFieldWorklist.field_guidance
                  .map((field) => [field.why_required, field.adam_prompt].filter(Boolean).join(" "))
                  .filter(Boolean)
                  .join(" ")
                  || "Adam-authored context unlocks retrieval without creating a memory claim."}
              </small>
            </span>
            {state?.photoContextRetrievalGapFieldWorklist.items.slice(0, 3).map((item) => (
              <span key={item.task_id}>
                <em>
                  {item.task_human_id} / {titleCase(item.progress_status)}
                </em>
                <strong>{item.source_photo_title}</strong>
                <small>Missing {item.missing_fields.map(titleCase).join(", ")}</small>
              </span>
            ))}
          </div>
          <div className="repair-projection-receipt" aria-label="Retrieval gap payoff preview">
            <span>
              <em>Payoff preview</em>
              <strong>{state?.photoContextRetrievalGapPayoffPreview.review_policy ?? "payoff preview pending"}</strong>
              <small>
                {state?.photoContextRetrievalGapPayoffPreview.uses_placeholders_for_missing_adam_context
                  ? "uses Adam placeholders, not generated memory"
                  : "needs placeholder policy"}
              </small>
            </span>
            <span>
              <em>Vector unlocks</em>
              <strong>
                {state?.photoContextRetrievalGapPayoffPreview.unlockable_vector_record_count ?? 0} unlockable /{" "}
                {state?.photoContextRetrievalGapPayoffPreview.reported_item_count ?? 0} previewed
              </strong>
              <small>{String(state?.photoContextRetrievalGapPayoffPreview.content_sha256 ?? "hash pending").slice(0, 16)}</small>
            </span>
            {state?.photoContextRetrievalGapPayoffPreview.items.slice(0, 2).map((item) => (
              <span key={item.task_id}>
                <em>
                  {item.task_human_id} / score {item.payoff_score}
                </em>
                <strong>{item.source_photo_title}</strong>
                <small>
                  {item.after_completion_vector_status} / {item.unlocked_records.slice(0, 2).map(titleCase).join(", ")}
                </small>
              </span>
            ))}
            <details>
              <summary>Payoff template preview</summary>
              <pre>{state?.photoContextRetrievalGapPayoffPreview.items[0]?.vector_text_template ?? ""}</pre>
            </details>
          </div>
          <div className="photo-draft-list" aria-label="Top photo context slice summary">
            <span>
              <em>Top context slice</em>
              <strong>{state?.photoContextTopSlice.title ?? "No active slice"}</strong>
              <small>{state?.photoContextTopSlice.completion_signal ?? "completion signal pending"}</small>
            </span>
            <span>
              <em>Slice hash</em>
              <strong>{String(state?.photoContextTopSlice.content_sha256 ?? "hash pending").slice(0, 16)}</strong>
              <small>{state?.photoContextTopSlice.review_policy ?? "read-only photo context slice"}</small>
            </span>
          </div>
          <div className="photo-review-pack-list" aria-label="Top photo context slice">
            {state?.photoContextTopSlice.items.slice(0, 3).map((item) => (
              <article key={item.item_key} data-tone="warning">
                <img src={getAssetPreviewUrl(item.source_photo_id, "thumbnail")} alt="" loading="lazy" />
                <div>
                  <strong>{item.display_title}</strong>
                  <span>No-claim photo group / {item.asset_count ?? 1} variants</span>
                  <em>{item.suggested_context_fields.slice(0, 4).map(titleCase).join(", ")}</em>
                  <button
                    type="button"
                    onClick={() => void handleOpenPhotoContextSliceItem(item)}
                    disabled={photoActionKey === item.item_key}
                    title={`${item.action.label ?? "Open context task"} for ${item.display_title}`}
                  >
                    {photoActionKey === item.item_key ? "Opening" : item.action.label ?? "Open context task"}
                  </button>
                </div>
              </article>
            ))}
          </div>
          <div className="photo-draft-list" aria-label="Photo context review session plan">
            <span>
              <em>Review session plan</em>
              <strong>
                {state?.photoContextSessionPlan.selected_count ?? 0} selected / {state?.photoContextSessionPlan.candidate_count ?? 0} no-claim groups
              </strong>
              <small>{state?.photoContextSessionPlan.review_policy ?? "read-only session plan"}</small>
            </span>
            <span>
              <em>Query context</em>
              <strong>{state?.photoContextSessionPlan.source_query ?? retrievalGapQuery}</strong>
              <small>{state?.photoContextSessionPlan.does_not_create_memory_claim ? "prioritization only, not a memory claim" : "needs policy check"}</small>
            </span>
            <span>
              <em>Field plan</em>
              <strong>{state?.photoContextSessionPlan.field_plan.map((field) => titleCase(field.field)).join(", ") ?? "visible facts"}</strong>
              <small>{String(state?.photoContextSessionPlan.content_sha256 ?? "hash pending").slice(0, 16)}</small>
            </span>
            {state?.photoContextSessionPlan.items.slice(0, 2).map((item) => (
              <span key={item.group_key}>
                <em>
                  {item.display_title} / {titleCase(item.truth_status)}
                </em>
                <strong>{item.field_plan[1]?.prompt ?? "Add Adam-authored context"}</strong>
                <small>{item.query_origin.query_is_context_prioritization_only ? "query is prioritization only" : "needs provenance review"}</small>
              </span>
            ))}
          </div>
          <section className="photo-context-session-queue" aria-label="Ordered photo context review session">
            <header>
              <div>
                <span>Ordered session queue</span>
                <strong>
                  {state?.photoContextSessionPlan.selected_count ?? 0} highest-payoff no-claim photo group(s)
                </strong>
              </div>
              <button
                type="button"
                onClick={() => void handleCreatePhotoContextReviewSession()}
                disabled={!state?.photoContextSessionPlan.items.length || photoActionKey === "photo-context-review-session"}
              >
                {photoActionKey === "photo-context-review-session" ? "Creating" : "Create/open session queue"}
              </button>
            </header>
            <ol>
              {state?.photoContextSessionPlan.items.map((item) => {
                const actionKey = `session-${item.group_key}`;
                const actionProvenance = photoContextActionProvenance(item);
                return (
                  <li key={item.group_key}>
                    <img src={getAssetPreviewUrl(item.canonical_asset_id, "thumbnail")} alt="" loading="lazy" />
                    <div>
                      <span>{String(item.sequence_number).padStart(2, "0")}</span>
                      <strong>{item.display_title}</strong>
                      <em>
                        {titleCase(item.truth_status)} / {item.query_origin.source_query} / not memory until Adam context
                      </em>
                      <small>{item.completion_criteria.slice(0, 2).join("; ")}</small>
                    </div>
                    <div className="session-action-provenance" aria-label={`Session action provenance for ${item.display_title}`}>
                      <span>Action provenance</span>
                      <strong>
                        {titleCase(actionProvenance.matchQuality)} / {titleCase(actionProvenance.selectionReason)}
                      </strong>
                      <em>Request carries query: {actionProvenance.sourceQuery}</em>
                      <small>
                        {actionProvenance.queryIsPrioritizationOnly && actionProvenance.notMemoryClaim
                          ? "prioritization only, not a memory claim"
                          : "needs provenance review before task creation"}
                      </small>
                    </div>
                    <div className="session-field-prompts" aria-label={`Session fields for ${item.display_title}`}>
                      {item.field_plan.slice(0, 3).map((field) => (
                        <span key={`${item.group_key}-${field.field}`}>
                          <em>{titleCase(field.field)}</em>
                          <strong>{field.prompt}</strong>
                        </span>
                      ))}
                    </div>
                    <button
                      type="button"
                      onClick={() => void handleOpenPhotoContextSessionItem(item)}
                      disabled={photoActionKey === actionKey}
                    >
                      {photoActionKey === actionKey ? "Opening" : item.action.label ?? "Open session item"}
                    </button>
                  </li>
                );
              })}
            </ol>
          </section>
          <div className="photo-draft-list" aria-label="Photo context worklists">
            {state?.photoContextPack.review_worklists.slice(0, 4).map((worklist) => (
              <span key={worklist.worklist_key}>
                <em>
                  {worklist.priority_rank}. {titleCase(worklist.item_kind)} / {worklist.candidate_count} held
                </em>
                <strong>{worklist.title}</strong>
                <small>
                  {titleCase(worklist.truth_status)} / {worklist.review_sequence_key.slice(0, 12)}
                </small>
                <button
                  type="button"
                  onClick={() => void handleOpenPhotoContextWorklist(worklist)}
                  disabled={photoActionKey === worklist.worklist_key}
                >
                  {photoActionKey === worklist.worklist_key ? "Opening" : "Open worklist"}
                </button>
              </span>
            ))}
          </div>
          <div className="photo-review-pack-list">
            {state?.photoContextProgress.items.slice(0, 2).map((item) => (
              <article key={item.task_id} data-tone={item.progress_status === "submit_ready" ? "good" : "warning"}>
                <img src={getAssetPreviewUrl(item.source_photo_id, "thumbnail")} alt="" loading="lazy" />
                <div>
                  <strong>{item.source_photo_title}</strong>
                  <span>{titleCase(item.progress_status)} / {item.has_draft ? "draft saved" : "no draft yet"}</span>
                  <em>
                    {item.retrieval_gap_missing_fields?.length
                      ? `Missing retrieval: ${item.retrieval_gap_missing_fields.slice(0, 2).map(titleCase).join(", ")}`
                      : item.vector_handoff_status
                        ? titleCase(item.vector_handoff_status)
                        : "Projection waits for draft"}
                  </em>
                  <button
                    type="button"
                    onClick={() => void onOpenReviewTask?.(item.task_id)}
                    title={`Open ${item.task_human_id}`}
                  >
                    Open progress task
                  </button>
                </div>
              </article>
            ))}
            {state?.photoContextPack.needs_context_groups.slice(0, 2).map((group) => (
              <article key={group.group_key} data-tone="warning">
                <img src={getAssetPreviewUrl(group.canonical_asset_id, "thumbnail")} alt="" loading="lazy" />
                <div>
                  <strong>{group.display_title}</strong>
                  <span>No-claim photo group / {group.asset_count} variants</span>
                  <em>{group.truth_status} / title and filename only</em>
                  <button
                    type="button"
                    disabled={photoActionKey === group.group_key}
                    onClick={() => void handleOpenPhotoContextPackGroup(group)}
                    title={`${group.primary_action.label ?? "Create context task"} for ${group.display_title}`}
                  >
                    {photoActionKey === group.group_key ? "Opening" : group.primary_action.label ?? "Create context task"}
                  </button>
                </div>
              </article>
            ))}
            {state?.photoContextPack.machine_drafts_held.slice(0, 2).map((draft) => (
              <article key={draft.metadata_profile_id} data-tone="warning">
                <img src={getAssetPreviewUrl(draft.source_photo_id, "thumbnail")} alt="" loading="lazy" />
                <div>
                  <strong>{draft.source_photo_title}</strong>
                  <span>Needs Adam review / {titleCase(draft.truth_status)}</span>
                  <em>{draft.summary_preview || "Machine draft held for context review"}</em>
                  {draft.task_id ? (
                    <button
                      type="button"
                      onClick={() => void onOpenReviewTask?.(draft.task_id as string)}
                      title={`Open ${draft.task_human_id ?? "photo draft review task"}`}
                    >
                      Open draft review
                    </button>
                  ) : null}
                </div>
              </article>
            ))}
          </div>
          <details className="photo-review-yaml">
            <summary>YAML preview</summary>
            <pre>{state?.photoContextPack.export_preview_yaml ?? ""}</pre>
          </details>
          <div className="readiness-actions">
            <button
              type="button"
              onClick={() => void handleCreatePhotoContextReviewSession()}
              disabled={!state?.photoContextPack.needs_context_groups.length || photoActionKey === "photo-context-review-session"}
              title="Create review tasks for the first five no-claim photo groups and open the first one."
            >
              <ClipboardList size={14} />
              Create top context tasks
            </button>
            <span>{photoSessionStatus || "No-claim until Adam submits context"}</span>
          </div>
          <small>{metrics?.packYamlPreviewChars ?? 0} chars / {String(state?.photoContextPack.content_sha256 ?? "").slice(0, 12)}</small>
        </section>

        <section className="readiness-card" data-export-tab="photos model">
          <h4>Reviewed Photo Demo Readiness</h4>
          <div className="photo-draft-list">
            <span>
              <em>Status</em>
              <strong>{state?.reviewedPhotoDemoReadiness.status ? titleCase(state.reviewedPhotoDemoReadiness.status) : "Checking"}</strong>
            </span>
            <span>
              <em>Reviewed records</em>
              <strong>{state?.reviewedPhotoDemoReadiness.reviewed_vector_ready_count ?? 0} vector-ready photo memories</strong>
            </span>
            <span>
              <em>Safety policy</em>
              <strong>
                {state?.reviewedPhotoDemoReadiness.safety_policy.does_not_fabricate_adam_memory
                  ? "No fabricated Adam memory"
                  : "Needs safety review"}
              </strong>
            </span>
            <span>
              <em>Blockers</em>
              <strong>{state?.reviewedPhotoDemoReadiness.blockers.join(", ") || "None"}</strong>
            </span>
            {state?.reviewedPhotoDemoReadiness.sample_reviewed_records.slice(0, 2).map((record) => (
              <span key={record.id ?? record.source_photo_id ?? record.title ?? "reviewed-demo"} className="vector-preview-record">
                <em>{record.title ?? record.id ?? "Reviewed photo memory"}</em>
                <strong>{record.inclusion_reason ? titleCase(record.inclusion_reason) : "Reviewed By Adam"}</strong>
                <small>{record.text_preview}</small>
              </span>
            ))}
            {!state?.reviewedPhotoDemoReadiness.can_show_reviewed_vector_memory
              ? state?.reviewedPhotoDemoReadiness.candidate_actions.slice(0, 3).map((action, index) => {
                  const taskId = action.task_id ?? action.review_task_id;
                  return (
                    <span key={`${action.action_type}-${action.source_photo_id ?? index}`}>
                      <em>{action.source_photo_title ?? titleCase(action.action_type)}</em>
                      <strong>{action.reason ? titleCase(action.reason) : action.reasons?.join(", ") || "Review needed"}</strong>
                      {taskId ? (
                        <button
                          type="button"
                          onClick={() => void onOpenReviewTask?.(taskId)}
                          title={`Open ${action.task_human_id ?? action.review_task_human_id ?? "photo review task"}`}
                        >
                          Open review
                        </button>
                      ) : null}
                      <small>{action.suggested_next_action}</small>
                    </span>
                  );
                })
              : null}
          </div>
        </section>

        <section className="readiness-card" data-export-tab="photos">
          <h4>Vector Handoff</h4>
          <div className="photo-draft-list">
            <span>
              <em>JSONL records</em>
              <strong>{Number(state?.vectorHandoff.manifest.record_count ?? 0)} embedding inputs ready</strong>
            </span>
            <span>
              <em>Held records</em>
              <strong>{Number(state?.vectorHandoff.manifest.excluded_count ?? 0)} awaiting Adam review</strong>
            </span>
            <span>
              <em>Population</em>
              <strong>
                {Number(state?.vectorHandoff.manifest.reviewed_ready_count ?? 0)} ready /{" "}
                {Number(state?.vectorHandoff.manifest.held_for_adam_review_count ?? 0)} held /{" "}
                {Number(state?.vectorHandoff.manifest.boundary_excluded_count ?? 0)} boundary
              </strong>
            </span>
            <span>
              <em>Next actions</em>
              <strong>{Number(state?.vectorHandoff.manifest.next_review_actions?.length ?? 0)} review actions exposed by API</strong>
            </span>
            <span>
              <em>Draft preview</em>
              <strong>
                {Number(state?.draftVectorPreview.manifest.record_count ?? 0)} preview-only /{" "}
                {state?.draftVectorPreview.manifest.not_for_downstream_vector_store ? "not for vector DB" : "needs policy check"}
              </strong>
            </span>
            <span>
              <em>Content hash</em>
              <strong>{String(state?.vectorHandoff.manifest.content_sha256 ?? "").slice(0, 16) || "Not ready"}</strong>
            </span>
            <span>
              <em>Vector policy</em>
              <strong>
                {state?.vectorHandoff.manifest.review_policy === "reviewed_only_by_default"
                  ? "Reviewed-only / no inline vectors"
                  : state?.vectorHandoff.manifest.vector_values_included === false
                    ? "No inline vectors / provider handoff"
                    : "Needs review"}
              </strong>
            </span>
            {state?.vectorHandoff.records.slice(0, 3).map((record) => (
              <span key={record.id} className="vector-preview-record">
                <em>{String(record.metadata.title ?? record.id)}</em>
                <strong>{record.inclusion_reason ? titleCase(record.inclusion_reason) : titleCase(String(record.review_status ?? "included"))}</strong>
                <small>{record.text}</small>
              </span>
            ))}
            {state?.vectorHandoff.excluded.slice(0, 3).map((held) => (
              <span key={`excluded-${held.source_photo_id}-${held.embedding_record_id}`} className="vector-preview-record">
                <em>{held.source_photo_title ?? held.title}</em>
                <strong>{held.reasons.join(", ")} / {held.review_status.replaceAll("_", " ")}</strong>
                <small>{held.suggested_next_action}</small>
              </span>
            ))}
            {state?.vectorHandoff.next_review_actions?.slice(0, 4).map((action, index) => (
              <span key={`${action.source_photo_id ?? "action"}-${index}`}>
                <em>{action.source_photo_title ?? "Photo memory review"}</em>
                <strong>
                  {action.reasons.join(", ") || "review_needed"} / {action.review_status.replaceAll("_", " ")}
                </strong>
                {action.review_task_id ? (
                  <button
                    type="button"
                    onClick={() => void onOpenReviewTask?.(action.review_task_id as string)}
                    title={`Open ${action.review_task_human_id ?? "photo memory review task"}`}
                  >
                    Open review
                  </button>
                ) : null}
                <small>{action.suggested_next_action}</small>
              </span>
            ))}
            {!state?.vectorHandoff.next_review_actions?.length ? state?.vectorHandoff.excluded.slice(0, 4).map((held) => {
              const requiredDecisions = Array.isArray(held.promotion_requirements?.required_decisions)
                ? (held.promotion_requirements.required_decisions as string[])
                : [];
              const requiredPreview = requiredDecisions
                .filter((item) => ["adam_context_note", "question_answers", "privacy_level", "ready_for_downstream"].includes(item))
                .map(titleCase)
                .join(", ");
              return (
                <span key={`${held.source_photo_id}-${held.embedding_record_id}`}>
                  <em>{held.source_photo_title ?? held.title}</em>
                  <strong>
                    {held.reasons.join(", ")} / {held.review_status.replaceAll("_", " ")}
                  </strong>
                  {held.review_task_id ? (
                    <button
                      type="button"
                      onClick={() => void onOpenReviewTask?.(held.review_task_id as string)}
                      title={`Open ${held.review_task_human_id ?? "photo memory review task"}`}
                    >
                      Open review
                    </button>
                  ) : null}
                  <small>{requiredPreview ? `Promote with: ${requiredPreview}. ` : ""}{held.suggested_next_action}</small>
                </span>
              );
            }) : null}
          </div>
        </section>

        <section className="readiness-card" data-export-tab="photos">
          <h4>Photo Draft Queue {metrics ? `(${metrics.photoReviewTaskCount} ready)` : ""}</h4>
          <div className="photo-draft-list">
            {state?.photoDrafts.candidates.slice(0, 5).map((candidate) => (
              <span key={candidate.asset_id}>
                <em>{candidate.template_title.replace("Photo memory: ", "")}</em>
                <strong>{candidate.asset_title}</strong>
              </span>
            ))}
          </div>
        </section>

        <section className="readiness-card" data-export-tab="prompt_pairs photos">
          <h4>Photo Prompt Seeds {metrics ? `(${metrics.photoPairTaskCount} tickets)` : ""}</h4>
          <div className="photo-draft-list">
            {state?.photoPairCandidates.candidates.slice(0, 5).map((candidate) => (
              <span key={candidate.metadata_profile_id}>
                <em>{candidate.prompt}</em>
                <strong>{titleCase(candidate.truth_status)}</strong>
              </span>
            ))}
          </div>
        </section>

        <section className="readiness-card" data-export-tab="photos">
          <h4>Gallery Preview</h4>
          <div className="gallery-preview-list" aria-label="Gallery preview">
            {state?.gallery.items.slice(0, 4).map((item) => (
              <article key={item.gallery_item_id} data-tone={item.requires_adam_review ? "warning" : "good"}>
                <img src={getAssetPreviewUrl(item.source_photo_id, "thumbnail")} alt="" loading="lazy" />
                <div>
                  <strong>{item.title}</strong>
                  <span>{item.display_caption || "No caption yet"}</span>
                  <em>
                    {item.requires_adam_review ? "Needs Adam review" : "Reviewed"} / {titleCase(item.gallery_scope)}
                  </em>
                  {item.review_task_id ? (
                    <button
                      type="button"
                      onClick={() => void onOpenReviewTask?.(item.review_task_id as string)}
                      aria-label={`Open gallery review task for ${item.title}`}
                      title={`Open ${item.review_task_human_id ?? "photo memory review task"}`}
                    >
                      Open gallery review
                    </button>
                  ) : null}
                </div>
              </article>
            ))}
            {!state?.gallery.items.length ? (
              <span>
                <em>Reviewed-only gallery</em>
                <strong>{state?.gallery.hidden_draft_count ?? 0} draft item(s) hidden until Adam review</strong>
              </span>
            ) : null}
          </div>
        </section>
      </div>
    </section>
  );
}
