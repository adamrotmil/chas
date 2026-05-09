"use client";

import { useEffect, useMemo, useState } from "react";
import { CheckCircle2, ExternalLink, FileText, GitPullRequestArrow, Loader2, PackageCheck, RefreshCw } from "lucide-react";
import { getTrainingBoard } from "@/lib/api";
import type { TrainingBoardColumn, TrainingBoardItem, TrainingBoardResponse } from "@/lib/types";

interface TrainingBoardProps {
  refreshKey?: string | number | null;
  onOpenTask: (taskId: string) => void;
  onViewExports: () => void;
}

function preview(value: string | undefined | null, limit = 180): string {
  const text = (value ?? "").replace(/\s+/g, " ").trim();
  return text.length > limit ? `${text.slice(0, limit - 3)}...` : text;
}

function compactCount(value: number | undefined): string {
  return `${value ?? 0}`;
}

function columnTone(columnId: string): string {
  if (columnId === "done") {
    return "done";
  }
  if (columnId === "exported") {
    return "exported";
  }
  if (columnId === "needs_fix") {
    return "blocked";
  }
  if (columnId === "doing") {
    return "active";
  }
  return "neutral";
}

function itemPrimaryText(item: TrainingBoardItem): string {
  if (item.artifactMode === "dpo") {
    return item.chosen || item.content || "";
  }
  return item.content || item.chosen || "";
}

function itemSecondaryText(item: TrainingBoardItem): string {
  return item.artifactMode === "dpo" ? item.rejected || "" : item.rejected || "";
}

function artifactIds(item: TrainingBoardItem): string[] {
  return [
    item.taskHumanId ? `Task ${item.taskHumanId}` : "",
    item.goldVoiceExampleId ? `Gold ${item.goldVoiceExampleId.slice(0, 8)}` : "",
    item.sftCandidateId ? `SFT ${item.sftCandidateId.slice(0, 8)}` : "",
    item.dpoPairId ? `DPO ${item.dpoPairId.slice(0, 8)}` : "",
    ...(item.datasetExportIds ?? []).map((id) => `Export ${id.slice(0, 8)}`)
  ].filter(Boolean);
}

function BoardCard({ item, onOpenTask, onViewExports }: { item: TrainingBoardItem; onOpenTask: (taskId: string) => void; onViewExports: () => void }) {
  const primary = itemPrimaryText(item);
  const secondary = itemSecondaryText(item);
  const canOpenTask = Boolean(item.taskId);
  const cardBody = (
    <>
      <div className="training-board-card-head">
        <span>{item.artifactMode.toUpperCase()}</span>
        <em>{item.exportStatus}</em>
      </div>
      <strong>{preview(item.title, 120) || "Untitled training item"}</strong>
      {item.subtitle ? <p>{item.subtitle}</p> : null}
      {item.labels?.length ? (
        <div className="training-board-labels" aria-label="Training item provenance labels">
          {item.labels.slice(0, 5).map((label) => (
            <span key={label}>{label}</span>
          ))}
        </div>
      ) : null}
      {primary ? (
        <div className="training-board-card-text">
          <span>{item.artifactMode === "dpo" ? "Chosen" : "Content"}</span>
          <p>{preview(primary)}</p>
        </div>
      ) : null}
      {secondary ? (
        <div className="training-board-card-text">
          <span>Rejected</span>
          <p>{preview(secondary, 140)}</p>
        </div>
      ) : null}
      {item.blockers.length > 0 ? (
        <div className="training-board-blockers" aria-label="Training item blockers">
          {item.blockers.slice(0, 3).map((blocker) => (
            <span key={blocker}>{blocker.replaceAll("_", " ")}</span>
          ))}
        </div>
      ) : null}
      {artifactIds(item).length > 0 ? (
        <div className="training-board-ids" aria-label="Training artifact identifiers">
          {artifactIds(item).slice(0, 5).map((id) => (
            <span key={id}>{id}</span>
          ))}
        </div>
      ) : null}
    </>
  );

  if (canOpenTask) {
    return (
      <button type="button" className="training-board-card" onClick={() => item.taskId && onOpenTask(item.taskId)}>
        {cardBody}
      </button>
    );
  }
  return (
    <article className="training-board-card" tabIndex={0}>
      {cardBody}
      {item.column === "done" || item.column === "exported" ? (
        <button type="button" className="training-board-inline-action" onClick={onViewExports}>
          <ExternalLink size={13} />
          Exports
        </button>
      ) : null}
    </article>
  );
}

function BoardColumn({ column, onOpenTask, onViewExports }: { column: TrainingBoardColumn; onOpenTask: (taskId: string) => void; onViewExports: () => void }) {
  return (
    <section className="training-board-column" data-tone={columnTone(column.id)} aria-label={`${column.label} training items`}>
      <header>
        <span>{column.label}</span>
        <strong>{column.count}</strong>
      </header>
      <div>
        {column.items.length > 0 ? (
          column.items.map((item) => <BoardCard key={item.id} item={item} onOpenTask={onOpenTask} onViewExports={onViewExports} />)
        ) : (
          <p className="training-board-empty">No items</p>
        )}
      </div>
    </section>
  );
}

export function TrainingBoard({ refreshKey, onOpenTask, onViewExports }: TrainingBoardProps) {
  const [board, setBoard] = useState<TrainingBoardResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  async function loadBoard() {
    setLoading(true);
    setError(null);
    try {
      setBoard(await getTrainingBoard());
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Could not load training board.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void loadBoard();
  }, [refreshKey]);

  const columns = useMemo(() => board?.columns ?? [], [board?.columns]);
  const doneCount = (board?.counts.done ?? 0) + (board?.counts.exported ?? 0);
  const approvedCount = (board?.counts.approved_sft ?? 0) + (board?.counts.approved_dpo ?? 0);

  return (
    <section className="training-board" aria-label="Training kanban board">
      <header className="training-board-header">
        <div>
          <span>
            <GitPullRequestArrow size={15} />
            Training board
          </span>
          <h2>Approved pairs stay visible</h2>
          <p>
            {compactCount(board?.counts.todo)} to do / {compactCount(board?.counts.doing)} doing / {compactCount(doneCount)} done or exported
          </p>
        </div>
        <div className="training-board-actions">
          <span>
            <CheckCircle2 size={14} />
            {approvedCount} approved
          </span>
          <button type="button" onClick={() => void loadBoard()} disabled={loading}>
            {loading ? <Loader2 size={14} className="spin" /> : <RefreshCw size={14} />}
            Refresh
          </button>
          <button type="button" onClick={onViewExports}>
            <PackageCheck size={14} />
            Exports
          </button>
        </div>
      </header>
      {error ? (
        <div className="training-board-error" role="alert">
          <FileText size={14} />
          {error}
        </div>
      ) : null}
      <div className="training-board-columns" aria-busy={loading ? "true" : "false"}>
        {loading && columns.length === 0 ? <p className="training-board-empty">Loading training board...</p> : null}
        {columns.map((column) => (
          <BoardColumn key={column.id} column={column} onOpenTask={onOpenTask} onViewExports={onViewExports} />
        ))}
      </div>
    </section>
  );
}
