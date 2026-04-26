"use client";

import { Activity, Archive, Database, RefreshCw, Sparkles } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { flagTask, getAssets, getGoldVoiceExamples, getMemories, getTasks, skipTask, submitTask } from "@/lib/api";
import type { Asset, GoldVoiceExample, Memory, Task } from "@/lib/types";
import { GoogleDriveImport } from "@/components/GoogleDriveImport";
import { TaskWorkbench } from "@/components/TaskWorkbench";

function queueLabel(queue: string): string {
  return queue
    .split("_")
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(" ");
}

function metric(label: string, value: number, detail: string, icon: React.ReactNode) {
  return (
    <div className="metric">
      <div className="metric-icon">{icon}</div>
      <span>{label}</span>
      <strong>{value}</strong>
      <small>{detail}</small>
    </div>
  );
}

export default function Home() {
  const [assets, setAssets] = useState<Asset[]>([]);
  const [tasks, setTasks] = useState<Task[]>([]);
  const [memories, setMemories] = useState<Memory[]>([]);
  const [goldExamples, setGoldExamples] = useState<GoldVoiceExample[]>([]);
  const [selectedQueue, setSelectedQueue] = useState<string>("all");
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

  const readyTasks = useMemo(() => tasks.filter((task) => task.status === "ready"), [tasks]);
  const filteredTasks = useMemo(
    () => readyTasks.filter((task) => selectedQueue === "all" || task.queue === selectedQueue),
    [readyTasks, selectedQueue]
  );
  const queues = useMemo(() => Array.from(new Set(readyTasks.map((task) => task.queue))).sort(), [readyTasks]);
  const selectedTask = useMemo(() => {
    if (selectedTaskId) {
      const explicit = filteredTasks.find((task) => task.id === selectedTaskId);
      if (explicit) {
        return explicit;
      }
    }
    return filteredTasks[0] ?? null;
  }, [filteredTasks, selectedTaskId]);

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

  return (
    <main className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <div className="brand-mark">CO</div>
          <div>
            <strong>CharlesOps</strong>
            <span>Production archive console</span>
          </div>
        </div>

        <nav className="queue-nav" aria-label="Task queues">
          <button
            className={selectedQueue === "all" ? "active" : ""}
            onClick={() => {
              setSelectedQueue("all");
              setSelectedTaskId(null);
            }}
          >
            All Ready
            <span>{readyTasks.length}</span>
          </button>
          {queues.map((queue) => (
            <button
              key={queue}
              className={selectedQueue === queue ? "active" : ""}
              onClick={() => {
                setSelectedQueue(queue);
                setSelectedTaskId(null);
              }}
            >
              {queueLabel(queue)}
              <span>{readyTasks.filter((task) => task.queue === queue).length}</span>
            </button>
          ))}
        </nav>
      </aside>

      <section className="main-column">
        <header className="topbar">
          <div>
            <span className="eyebrow">Phase 0 + Phase 1 MVP</span>
            <h1>Human-in-the-loop workbench</h1>
          </div>
          <button className="icon-button" onClick={() => void load()} aria-label="Refresh workbench data">
            <RefreshCw size={18} />
          </button>
        </header>

        <section className="dashboard" aria-label="Dashboard">
          {metric("Assets", assets.length, "seeded source records", <Archive size={18} />)}
          {metric("Ready tasks", readyTasks.length, "waiting for review", <Activity size={18} />)}
          {metric("Memories", memories.length, "cards in graph", <Database size={18} />)}
          {metric("Gold edits", goldExamples.length, "voice examples", <Sparkles size={18} />)}
          {metric("Session", completedThisSession, "submitted now", <Activity size={18} />)}
        </section>

        <GoogleDriveImport onImported={load} />

        {error ? <div className="error-banner">{error}</div> : null}

        <section className="workspace-grid">
          <div className="task-list" aria-label="Tasks">
            <div className="section-heading">
              <span>Queue</span>
              <strong>{queueLabel(selectedQueue)}</strong>
            </div>
            {loading ? <p className="quiet">Loading workbench data...</p> : null}
            {!loading && filteredTasks.length === 0 ? <p className="quiet">No ready tasks in this queue.</p> : null}
            {filteredTasks.map((task) => (
              <button
                key={task.id}
                className={selectedTask?.id === task.id ? "task-row active" : "task-row"}
                onClick={() => setSelectedTaskId(task.id)}
              >
                <span>{task.task_type}</span>
                <strong>{task.human_id}</strong>
                <small>{task.priority}</small>
              </button>
            ))}
          </div>

          <div className="workbench-column">
            {selectedTask ? (
              <TaskWorkbench
                key={selectedTask.id}
                task={selectedTask}
                onSubmit={handleSubmit}
                onSkip={handleSkip}
                onFlag={handleFlag}
              />
            ) : (
              <div className="empty-state">
                <Sparkles size={22} />
                <strong>Queue clear</strong>
                <span>Seed data may need to be loaded, or every ready task has been handled.</span>
              </div>
            )}
          </div>
        </section>
      </section>
    </main>
  );
}
