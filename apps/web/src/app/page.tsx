"use client";

import {
  Archive,
  BarChart3,
  Box,
  Brain,
  CheckCircle2,
  ChevronDown,
  Clock3,
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
import { flagTask, getAssets, getGoldVoiceExamples, getMemories, getTasks, skipTask, submitTask } from "@/lib/api";
import type { Asset, GoldVoiceExample, Memory, Task } from "@/lib/types";
import { GoogleDriveImport } from "@/components/GoogleDriveImport";
import { TaskWorkbench } from "@/components/TaskWorkbench";

type NavMode = "intake" | "queue" | "review" | "gold_edits" | "exports" | "models" | "settings";
type CollectionId = "text_segments" | "voice_samples" | "emails" | "photos" | "videos" | "documents" | "all";
type ShellColumn = "sidebar" | "queue";

const topNav = [
  { id: "queue", label: "Queue", icon: <Inbox size={15} /> },
  { id: "analytics", label: "Analytics", icon: <BarChart3 size={15} /> },
  { id: "sessions", label: "Sessions", icon: <ShieldCheck size={15} /> },
  { id: "exports", label: "Exports", icon: <FileText size={15} /> },
  { id: "settings", label: "Settings", icon: <Settings size={15} /> }
];

const sideNav: { id: NavMode; label: string; icon: React.ReactNode }[] = [
  { id: "intake", label: "Intake", icon: <Inbox size={15} /> },
  { id: "queue", label: "Queue", icon: <Archive size={15} /> },
  { id: "review", label: "Review", icon: <CheckCircle2 size={15} /> },
  { id: "gold_edits", label: "Gold Edits", icon: <Download size={15} /> },
  { id: "exports", label: "Exports", icon: <FolderArchive size={15} /> },
  { id: "models", label: "Models", icon: <Brain size={15} /> },
  { id: "settings", label: "Settings", icon: <Settings size={15} /> }
];

const collectionDefs: { id: CollectionId; label: string; icon: React.ReactNode }[] = [
  { id: "text_segments", label: "Text Segments", icon: <FileText size={15} /> },
  { id: "voice_samples", label: "Voice Samples", icon: <Sparkles size={15} /> },
  { id: "emails", label: "Emails", icon: <Mail size={15} /> },
  { id: "photos", label: "Photos", icon: <Image size={15} /> },
  { id: "videos", label: "Videos", icon: <Video size={15} /> },
  { id: "documents", label: "Documents", icon: <Box size={15} /> },
  { id: "all", label: "All Items", icon: <Database size={15} /> }
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
  return taskType
    .split("_")
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(" ");
}

function taskTitle(task: Task): string {
  const payload = task.input_payload;
  for (const key of ["source_filename", "asset_title", "title", "segment_title", "prompt"]) {
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
  return typeof task.input_payload.source_type === "string" ? task.input_payload.source_type : "";
}

function sourceFilename(task: Task): string {
  return typeof task.input_payload.source_filename === "string" ? task.input_payload.source_filename.toLowerCase() : "";
}

function taskMatchesCollection(task: Task, collection: CollectionId): boolean {
  if (collection === "all") {
    return true;
  }

  const type = sourceType(task);
  const filename = sourceFilename(task);
  switch (collection) {
    case "text_segments":
      return task.task_type === "text_segment_review" || ["document", "text", "journal"].includes(type);
    case "voice_samples":
      return task.task_type === "email_voice_sample" || task.task_type === "gold_voice_edit";
    case "emails":
      return task.task_type === "email_voice_sample" || type === "email" || /\.(eml|msg|mbox)$/i.test(filename);
    case "photos":
      return task.task_type === "photo_context" || type === "photo";
    case "videos":
      return task.task_type.includes("video") || type === "video" || /\.(mov|mp4|m4v)$/i.test(filename);
    case "documents":
      return ["document", "text", "pdf", "scan", "journal"].includes(type) || /\.(doc|docx|txt|rtf|pdf)$/i.test(filename);
    default:
      return true;
  }
}

function taskMatchesMode(task: Task, mode: NavMode): boolean {
  switch (mode) {
    case "gold_edits":
      return task.task_type === "gold_voice_edit";
    case "exports":
      return task.task_type.includes("export") || task.queue.includes("export");
    case "review":
      return task.queue.includes("review") || task.task_type.includes("review");
    case "intake":
      return task.task_type === "asset_triage";
    default:
      return true;
  }
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
  const [selectedCollection, setSelectedCollection] = useState<CollectionId>("text_segments");
  const [selectedTaskId, setSelectedTaskId] = useState<string | null>(null);
  const [completedThisSession, setCompletedThisSession] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

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
    () => modeTasks.filter((task) => taskMatchesCollection(task, selectedCollection)),
    [modeTasks, selectedCollection]
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
  const selectedCollectionDef = collectionDefs.find((collection) => collection.id === selectedCollection) ?? collectionDefs[0];
  const selectedTaskIndex = selectedTask ? filteredTasks.findIndex((task) => task.id === selectedTask.id) : -1;

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
          <button className="chrome-back" type="button" aria-label="Back to CharlesOps workspace">
            CO
          </button>
          <div>
            <strong>Human-in-the-loop Workbench</strong>
            <span>CharlesOps source review and annotation</span>
          </div>
        </div>

        <div className="branch-pill">
          <Database size={14} />
          <span>main</span>
          <ChevronDown size={13} />
        </div>
        <div className="sync-pill">
          <CheckCircle2 size={14} />
          <span>Synced</span>
        </div>

        <nav className="top-nav" aria-label="Primary workbench sections">
          {topNav.map((item) => (
            <button
              key={item.id}
              className={selectedMode === item.id ? "active" : ""}
              type="button"
              onClick={() => {
                if (["queue", "exports", "settings"].includes(item.id)) {
                  setSelectedMode(item.id as NavMode);
                  setSelectedTaskId(null);
                }
              }}
            >
              {item.icon}
              <span>{item.label}</span>
            </button>
          ))}
        </nav>

        <button className="avatar-button" type="button" aria-label="Adam workspace profile">
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
              const count =
                item.id === "queue"
                  ? readyTasks.length
                  : item.id === "gold_edits"
                    ? readyTasks.filter((task) => task.task_type === "gold_voice_edit").length
                    : item.id === "exports"
                      ? readyTasks.filter((task) => task.task_type.includes("export") || task.queue.includes("export")).length
                      : null;
              return (
                <button
                  key={item.id}
                  className={selectedMode === item.id ? "active" : ""}
                  type="button"
                  onClick={() => {
                    setSelectedMode(item.id);
                    setSelectedTaskId(null);
                  }}
                >
                  {item.icon}
                  <span>{item.label}</span>
                  {count !== null ? <em>{count}</em> : null}
                </button>
              );
            })}
          </nav>

          <div className="collection-block">
            <span className="rail-heading">Collections</span>
            <nav className="collection-nav" aria-label="Source collections">
              {collectionDefs.map((collection) => (
                <button
                  key={collection.id}
                  className={selectedCollection === collection.id ? "active" : ""}
                  type="button"
                  onClick={() => {
                    setSelectedCollection(collection.id);
                    setSelectedTaskId(null);
                  }}
                >
                  {collection.icon}
                  <span>{collection.label}</span>
                  <em>{collectionCounts[collection.id]}</em>
                </button>
              ))}
            </nav>
          </div>

          <div className="rail-status">
            <span>
              <Clock3 size={13} />
              Ready
            </span>
            <span>
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
        />

        <section className="queue-panel" aria-label="Task queue">
          <header className="queue-panel-header">
            <div>
              <h1>{selectedCollectionDef.label}</h1>
              <span>{filteredTasks.length} items</span>
            </div>
            <div className="queue-tools">
              <button type="button" aria-label="Filter queue">
                <Archive size={15} />
              </button>
              <button type="button" aria-label="Search queue">
                <Search size={15} />
              </button>
              <button type="button" onClick={() => void load()} aria-label="Refresh workbench data">
                <RefreshCw size={15} />
              </button>
            </div>
          </header>

          {selectedMode === "intake" ? <GoogleDriveImport onImported={load} /> : null}

          {error ? <div className="error-banner">{error}</div> : null}

          <div className="task-list" aria-label="Tasks">
            {loading ? <p className="quiet">Loading workbench data...</p> : null}
            {!loading && filteredTasks.length === 0 ? <p className="quiet">No ready tasks in this collection.</p> : null}
            {filteredTasks.map((task) => (
              <button
                key={task.id}
                className={selectedTask?.id === task.id ? "task-row active" : "task-row"}
                type="button"
                onClick={() => setSelectedTaskId(task.id)}
              >
                <span>{taskTypeLabel(task.task_type)}</span>
                <strong>{taskTitle(task)}</strong>
                <em>{taskSubtitle(task)}</em>
                <small>{queueHealthScore(task)}</small>
                <time>{formatRelativeTime(task.updated_at)}</time>
              </button>
            ))}
          </div>

          <footer className="queue-pagination">
            <button type="button" aria-label="Previous page">
              ‹
            </button>
            <span>1 of {Math.max(1, Math.ceil(filteredTasks.length / 10))}</span>
            <button type="button" aria-label="Next page">
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
        />

        <section className="workbench-column">
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
        </section>
      </div>
    </main>
  );
}
