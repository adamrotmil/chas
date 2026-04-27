"use client";

import {
  Archive,
  Box,
  Brain,
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
  Mail,
  RefreshCw,
  Search,
  Settings,
  ShieldCheck,
  Sparkles,
  Video
} from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  createPromptPairBatch,
  createVisionDraftBatch,
  flagTask,
  getAssets,
  getGoldVoiceExamples,
  getMemories,
  getTasks,
  skipTask,
  submitTask
} from "@/lib/api";
import type { Asset, GoldVoiceExample, Memory, Task } from "@/lib/types";
import { ContextPackBuilderPanel } from "@/components/ContextPackBuilderPanel";
import { ExportDryRunPanel } from "@/components/ExportDryRunPanel";
import { GoogleDriveImport } from "@/components/GoogleDriveImport";
import { TaskWorkbench } from "@/components/TaskWorkbench";
import { assetIdForTask, readinessBadgesForTask } from "@/lib/readiness";

type NavMode =
  | "intake"
  | "queue"
  | "source_review"
  | "segmentation"
  | "prompt_pairs"
  | "vision_drafts"
  | "gold_edits"
  | "privacy"
  | "exports"
  | "models"
  | "settings";
type CollectionId = "all" | "text_segments" | "voice_samples" | "emails" | "photos" | "videos" | "documents";
type ShellColumn = "sidebar" | "queue";

type NavItem = { id: NavMode; label: string; icon: React.ReactNode; tooltip: string };
type CollectionItem = { id: CollectionId; label: string; icon: React.ReactNode; tooltip: string };

const topNav: NavItem[] = [
  { id: "queue", label: "Queue", icon: <Inbox size={15} />, tooltip: "Built: browse and work through ready review tasks." },
  {
    id: "prompt_pairs",
    label: "Pair Factory",
    icon: <ClipboardList size={15} />,
    tooltip: "Built: configure grounded prompt-pair drafts from approved source chunks. No live model call yet."
  },
  {
    id: "gold_edits",
    label: "Gold Edits",
    icon: <Download size={15} />,
    tooltip: "Built: review generated/draft pairs, edit the preferred answer, and set SFT/DPO export readiness."
  },
  {
    id: "exports",
    label: "Exports",
    icon: <FileText size={15} />,
    tooltip: "Partially built: JSONL export exists in the API; richer export review UI is planned."
  },
  {
    id: "settings",
    label: "Settings",
    icon: <Settings size={15} />,
    tooltip: "Planned: project, account, storage, model, and pipeline settings."
  }
];

const sideNav: NavItem[] = [
  { id: "intake", label: "Intake", icon: <Inbox size={15} />, tooltip: "Built: import Drive metadata and start mirror/intake work." },
  { id: "queue", label: "All Queue", icon: <Archive size={15} />, tooltip: "Built: all ready tasks, with source filters below." },
  {
    id: "source_review",
    label: "Source Review",
    icon: <CheckCircle2 size={15} />,
    tooltip: "Built: label raw source material, authorship, truth status, privacy, and processing readiness."
  },
  {
    id: "segmentation",
    label: "Segmentation",
    icon: <FileText size={15} />,
    tooltip: "Built: review extracted chunks, split/merge intent, allowed uses, and privacy clearance."
  },
  {
    id: "prompt_pairs",
    label: "Pair Factory",
    icon: <ClipboardList size={15} />,
    tooltip: "Built: create draft prompt-pair review tasks from approved chunks. Generation is still stubbed."
  },
  {
    id: "vision_drafts",
    label: "Vision Drafts",
    icon: <Image size={15} />,
    tooltip: "Groundwork built: creates no-call vision review tasks. Live vision model calls are gated off."
  },
  {
    id: "gold_edits",
    label: "Gold Edits",
    icon: <Download size={15} />,
    tooltip: "Built: compare draft vs Adam edit and create SFT, DPO, eval, style, and anti-pattern records."
  },
  {
    id: "privacy",
    label: "Privacy",
    icon: <ShieldCheck size={15} />,
    tooltip: "Built in records: boundary/privacy decisions gate downstream use; dedicated UI is still minimal."
  },
  {
    id: "exports",
    label: "Exports",
    icon: <FolderArchive size={15} />,
    tooltip: "Partially built: API export stubs and JSONL output exist; full export dashboard is planned."
  },
  { id: "models", label: "Models", icon: <Brain size={15} />, tooltip: "Planned: model connections, eval runs, and fine-tune readiness controls." },
  { id: "settings", label: "Settings", icon: <Settings size={15} />, tooltip: "Planned: project, account, storage, and pipeline configuration." }
];

const collectionDefs: CollectionItem[] = [
  { id: "all", label: "All Sources", icon: <Database size={15} />, tooltip: "Built: show all ready source tasks in this workstream." },
  { id: "text_segments", label: "Text Segments", icon: <FileText size={15} />, tooltip: "Built: text/document review and segmentation tasks." },
  { id: "voice_samples", label: "Voice Samples", icon: <Sparkles size={15} />, tooltip: "Built: direct or contextual Charles voice review tasks." },
  { id: "emails", label: "Emails", icon: <Mail size={15} />, tooltip: "Built: email voice/context review tasks." },
  { id: "photos", label: "Photos", icon: <Image size={15} />, tooltip: "Partially built: photo intake/vision review; local/GCS preview support is still being expanded." },
  { id: "videos", label: "Videos", icon: <Video size={15} />, tooltip: "Planned: video-specific preview, transcript, and scene annotation workflows." },
  { id: "documents", label: "Documents", icon: <Box size={15} />, tooltip: "Built: document/text extraction and review tasks where mirrored text is available." }
];

const RESIZE_STEP = 16;
const shellColumnBounds: Record<ShellColumn, { min: number; max: number }> = {
  sidebar: { min: 172, max: 340 },
  queue: { min: 260, max: 520 }
};

function clamp(value: number, min: number, max: number): number {
  return Math.min(Math.max(value, min), max);
}

function queueLabel(queue: string): string {
  return queue
    .split("_")
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(" ");
}

function taskTypeLabel(taskType: string): string {
  const labels: Record<string, string> = {
    text_segment_review: "Source Review",
    text_segment_boundary_review: "Segment Boundary Review",
    boundary_review: "Privacy Review",
    grounded_prompt_pair_candidate: "Prompt Pair Factory",
    gold_voice_edit: "Gold Voice Edit",
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

function taskTitle(task: Task): string {
  const payload = task.input_payload;
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
  const parts = [
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
  switch (collection) {
    case "text_segments":
      return (
        !isPromptPairTask(task) &&
        (["text_segment_review", "text_segment_boundary_review"].includes(task.task_type) ||
          ["document", "text", "journal"].includes(type))
      );
    case "voice_samples":
      return task.task_type === "email_voice_sample" || (task.task_type === "gold_voice_edit" && !isPromptPairTask(task));
    case "emails":
      return task.task_type === "email_voice_sample" || type === "email" || /\.(eml|msg|mbox)$/i.test(filename);
    case "photos":
      return task.task_type === "photo_context" || type === "photo";
    case "videos":
      return task.task_type.includes("video") || type === "video" || /\.(mov|mp4|m4v)$/i.test(filename);
    case "documents":
      return !isPromptPairTask(task) && (["document", "text", "pdf", "scan", "journal"].includes(type) || /\.(doc|docx|txt|rtf|pdf)$/i.test(filename));
    default:
      return true;
  }
}

function taskMatchesMode(task: Task, mode: NavMode): boolean {
  switch (mode) {
    case "source_review":
      return ["text_segment_review", "email_voice_sample", "photo_context"].includes(task.task_type);
    case "vision_drafts":
      return task.task_type === "vision_draft_review";
    case "segmentation":
      return task.task_type === "text_segment_boundary_review";
    case "gold_edits":
      return task.task_type === "gold_voice_edit";
    case "prompt_pairs":
      return task.task_type === "grounded_prompt_pair_candidate";
    case "privacy":
      return task.task_type === "boundary_review" || task.queue.includes("boundary") || task.queue.includes("privacy");
    case "exports":
      return task.task_type.includes("export") || task.queue.includes("export");
    case "intake":
      return task.task_type === "asset_triage";
    default:
      return true;
  }
}

function modeUsesCollectionFilter(mode: NavMode): boolean {
  return mode === "queue" || mode === "source_review";
}

function defaultCollectionForMode(mode: NavMode): CollectionId {
  if (mode === "queue" || mode === "source_review") {
    return "all";
  }
  return "all";
}

function tooltip(text: string): { title: string } {
  return { title: text };
}

function queueHealthScore(task: Task): number {
  const payload = task.input_payload;
  const hasPreview = typeof payload.preview_text === "string" && payload.preview_text.trim().length > 0;
  const hasSource = typeof payload.source_filename === "string" || typeof payload.asset_title === "string";
  const imported = task.created_by !== "seed";
  const chunkBonus = typeof payload.chunk_count === "number" && payload.chunk_count > 0 ? 6 : 0;
  return Math.min(98, 70 + task.priority * 3 + (hasPreview ? 8 : 0) + (hasSource ? 5 : 0) + (imported ? 5 : 0) + chunkBonus);
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

export default function Home() {
  const [assets, setAssets] = useState<Asset[]>([]);
  const [tasks, setTasks] = useState<Task[]>([]);
  const [memories, setMemories] = useState<Memory[]>([]);
  const [goldExamples, setGoldExamples] = useState<GoldVoiceExample[]>([]);
  const [shellWidths, setShellWidths] = useState<Record<ShellColumn, number>>({ sidebar: 212, queue: 326 });
  const [selectedMode, setSelectedMode] = useState<NavMode>("queue");
  const [selectedCollection, setSelectedCollection] = useState<CollectionId>("all");
  const [selectedTaskId, setSelectedTaskId] = useState<string | null>(null);
  const [completedThisSession, setCompletedThisSession] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [batchBusy, setBatchBusy] = useState(false);
  const [visionBatchBusy, setVisionBatchBusy] = useState(false);

  async function load() {
    setLoading(true);
    setError(null);
    try {
      const [assetData, taskData, memoryData, goldData] = await Promise.all([
        getAssets(),
        getTasks(),
        getMemories(),
        getGoldVoiceExamples()
      ]);
      setAssets(assetData);
      setTasks(taskData);
      setMemories(memoryData);
      setGoldExamples(goldData);
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

  useEffect(() => {
    void load();
  }, []);

  const readyTasks = useMemo(
    () =>
      [...tasks.filter((task) => task.status === "ready")].sort(
        (left, right) => taskSortRank(left) - taskSortRank(right) || right.priority - left.priority
      ),
    [tasks]
  );
  const modeTasks = useMemo(
    () => readyTasks.filter((task) => taskMatchesMode(task, selectedMode)),
    [readyTasks, selectedMode]
  );
  const filteredTasks = useMemo(
    () =>
      modeUsesCollectionFilter(selectedMode)
        ? modeTasks.filter((task) => taskMatchesCollection(task, selectedCollection))
        : modeTasks,
    [modeTasks, selectedCollection, selectedMode]
  );
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
  const selectedCollectionDef = collectionDefs.find((collection) => collection.id === selectedCollection) ?? collectionDefs[0];
  const queueScopeTitle = showCollectionFilters ? selectedCollectionDef.label : modeLabel(selectedMode);
  const selectedTaskIndex = selectedTask ? filteredTasks.findIndex((task) => task.id === selectedTask.id) : -1;
  const assetsById = useMemo(() => new Map(assets.map((asset) => [asset.id, asset])), [assets]);
  const selectedTaskAsset = selectedTask ? assetsById.get(assetIdForTask(selectedTask) ?? "") : undefined;

  function navigateMode(mode: NavMode) {
    setSelectedMode(mode);
    setSelectedCollection(defaultCollectionForMode(mode));
    setSelectedTaskId(null);
  }

  async function handleSubmit(decisions: Record<string, unknown>, notes?: string) {
    if (!selectedTask) {
      return;
    }
    await submitTask(selectedTask.id, decisions, notes);
    setCompletedThisSession((count) => count + 1);
    await load();
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

  async function handleCreatePromptPairBatch() {
    setBatchBusy(true);
    setError(null);
    try {
      await createPromptPairBatch(10);
      navigateMode("gold_edits");
      setSelectedTaskId(null);
      await load();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Unable to create prompt pair drafts.");
    } finally {
      setBatchBusy(false);
    }
  }

  async function handleCreateVisionDraftBatch() {
    setVisionBatchBusy(true);
    setError(null);
    try {
      await createVisionDraftBatch(10);
      navigateMode("vision_drafts");
      setSelectedTaskId(null);
      await load();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Unable to create vision draft tasks.");
    } finally {
      setVisionBatchBusy(false);
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
              const showCount = !["models", "settings"].includes(item.id);
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
                  {showCount ? <em>{modeCounts[item.id]}</em> : null}
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
              <span>{filteredTasks.length} items</span>
            </div>
            <div className="queue-tools">
              <button type="button" aria-label="Filter queue" {...tooltip("Planned: advanced queue filters beyond the left source filters.")}>
                <Archive size={15} />
              </button>
              <button type="button" aria-label="Search queue" {...tooltip("Planned: search task titles, source filenames, and metadata.")}>
                <Search size={15} />
              </button>
              <button type="button" onClick={() => void load()} aria-label="Refresh workbench data" {...tooltip("Built: reload assets, tasks, memories, and gold examples from the API.")}>
                <RefreshCw size={15} />
              </button>
              {selectedMode === "prompt_pairs" ? (
                <button
                  className="wide-tool"
                  type="button"
                  onClick={() => void handleCreatePromptPairBatch()}
                  aria-label="Create stub prompt pair drafts from ready candidates"
                  disabled={batchBusy}
                  {...tooltip("Built: create up to 10 no-live-model prompt-pair draft review tasks from ready candidates.")}
                >
                  <Sparkles size={15} />
                  <span>{batchBusy ? "Creating" : "Create reviews"}</span>
                </button>
              ) : null}
              {selectedMode === "vision_drafts" ? (
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

          {selectedMode === "intake" ? <GoogleDriveImport onImported={load} /> : null}

          {error ? <div className="error-banner">{error}</div> : null}

          <div className="task-list" aria-label="Tasks">
            {loading ? <p className="quiet">Loading workbench data...</p> : null}
            {!loading && filteredTasks.length === 0 ? <p className="quiet">No ready tasks in this collection.</p> : null}
            {filteredTasks.map((task) => {
              const taskAsset = assetsById.get(assetIdForTask(task) ?? "");
              const readinessBadges = readinessBadgesForTask(task, taskAsset).slice(0, 3);
              return (
                <button
                  key={task.id}
                  className={selectedTask?.id === task.id ? "task-row active" : "task-row"}
                  type="button"
                  onClick={() => setSelectedTaskId(task.id)}
                  {...tooltip(`Open task: ${taskTitle(task)}. ${taskSubtitle(task)}`)}
                >
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
                  <small>{queueHealthScore(task)}</small>
                  <time>{formatRelativeTime(task.updated_at)}</time>
                </button>
              );
            })}
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

        <section className="workbench-column">
          {selectedMode === "exports" ? (
            <ExportDryRunPanel />
          ) : (
            <div className={selectedMode === "prompt_pairs" ? "workbench-stack has-utility" : "workbench-stack"}>
              {selectedMode === "prompt_pairs" ? <ContextPackBuilderPanel selectedTask={selectedTask} tasks={tasks} /> : null}
              {selectedTask ? (
                <TaskWorkbench
                  key={selectedTask.id}
                  task={selectedTask}
                  queuePosition={selectedTaskIndex + 1}
                  queueTotal={filteredTasks.length}
                  qualityScore={queueHealthScore(selectedTask)}
                  completedThisSession={completedThisSession}
                  memoriesCount={memories.length}
                  goldExamplesCount={goldExamples.length}
                  assetsCount={assets.length}
                  asset={selectedTaskAsset}
                  onSubmit={handleSubmit}
                  onSkip={handleSkip}
                  onFlag={handleFlag}
                  onPrevious={() => {
                    if (selectedTaskIndex > 0) {
                      setSelectedTaskId(filteredTasks[selectedTaskIndex - 1].id);
                    }
                  }}
                  onNext={() => {
                    if (selectedTaskIndex >= 0 && selectedTaskIndex < filteredTasks.length - 1) {
                      setSelectedTaskId(filteredTasks[selectedTaskIndex + 1].id);
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
