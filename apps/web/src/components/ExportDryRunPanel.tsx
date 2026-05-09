"use client";

import { CheckCircle2, Download, FileJson, RefreshCw, ShieldAlert } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { buildDatasetExport, getDatasetExportDryRun, getDatasetJsonlUrl, getStoredDatasetJsonlUrl } from "@/lib/api";
import type { DatasetDryRunRow, DatasetExport, DatasetExportDryRun, EvidenceCorpusSnapshot } from "@/lib/types";
import { DownstreamReadinessPanel } from "@/components/DownstreamReadinessPanel";

type ExportType = "sft" | "dpo";

function titleCase(value: string): string {
  return value
    .split("_")
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}

function rowLabel(row: DatasetDryRunRow): string {
  const sourceName = typeof row.source?.gold_human_id === "string" ? row.source.gold_human_id : "";
  return sourceName || `${titleCase(row.artifact_type)} ${row.artifact_id.slice(0, 8)}`;
}

function firstPayloadPreview(row: DatasetDryRunRow): string {
  if (row.artifact_type === "sft_candidate") {
    const messages = row.payload.messages;
    if (Array.isArray(messages)) {
      const assistant = messages.find(
        (message) => typeof message === "object" && message !== null && "role" in message && message.role === "assistant"
      );
      if (assistant && typeof assistant === "object" && "content" in assistant && typeof assistant.content === "string") {
        return assistant.content.slice(0, 180);
      }
    }
  }
  for (const key of ["preferred_output", "non_preferred_output"]) {
    const value = row.payload[key];
    if (typeof value === "string" && value.trim()) {
      return value.slice(0, 180);
    }
  }
  return "No preview text available.";
}

function rowReviewBlockers(row: DatasetDryRunRow): string[] {
  const metadata = row.payload.metadata;
  if (!metadata || typeof metadata !== "object" || !("review_blockers" in metadata)) {
    return [];
  }
  const blockers = metadata.review_blockers;
  return Array.isArray(blockers) ? blockers.map(String).filter(Boolean) : [];
}

function EvidenceCorpusSnapshotPanel({ snapshot }: { snapshot?: EvidenceCorpusSnapshot }) {
  if (!snapshot) {
    return null;
  }
  const familyCounts = Object.entries(snapshot.corpus_family_counts ?? {})
    .sort(([, left], [, right]) => right - left)
    .slice(0, 4);
  const records = Array.isArray(snapshot.records) ? snapshot.records.slice(0, 4) : [];
  return (
    <section className="export-evidence-snapshot" aria-label="Unified evidence corpus snapshot">
      <header>
        <div>
          <span>Evidence corpus</span>
          <strong>{snapshot.scope ?? "family_private"}</strong>
        </div>
        <div>
          <em>{snapshot.record_count ?? 0} reviewed</em>
          <em>{snapshot.excluded_count ?? 0} held</em>
          <em>{snapshot.vector_ready_count ?? 0} vectors</em>
        </div>
      </header>
      {familyCounts.length > 0 ? (
        <div className="export-evidence-families">
          {familyCounts.map(([family, count]) => (
            <span key={family}>
              {titleCase(family)} <strong>{count}</strong>
            </span>
          ))}
        </div>
      ) : null}
      {records.length > 0 ? (
        <div className="export-evidence-records">
          {records.map((record) => (
            <article key={record.embedding_record_id}>
              <em>{titleCase(record.corpus_family)}</em>
              <strong>{record.title || record.target_id}</strong>
              <p>{record.input_preview}</p>
            </article>
          ))}
        </div>
      ) : (
        <p className="quiet">No reviewed evidence records are currently available for this export scope.</p>
      )}
    </section>
  );
}

function DryRunRows({ rows, kind }: { rows: DatasetDryRunRow[]; kind: "included" | "excluded" }) {
  return (
    <div className="dry-run-list">
      {rows.slice(0, 8).map((row) => {
        const blockers = kind === "included" ? rowReviewBlockers(row) : row.reasons ?? [];
        return (
          <article key={`${kind}-${row.artifact_id}`} className="dry-run-row">
            <header>
              <strong>{rowLabel(row)}</strong>
              <span>{row.export_status}</span>
            </header>
            <div className="dry-run-source">
              <span>{titleCase(row.artifact_type)}</span>
              {typeof row.source?.voice_mode === "string" ? <span>{titleCase(row.source.voice_mode)}</span> : null}
              {typeof row.source?.context_boundary_status === "string" ? (
                <span>{titleCase(row.source.context_boundary_status)}</span>
              ) : null}
            </div>
            <p>{firstPayloadPreview(row)}</p>
            {blockers.length ? (
              <div className="reason-strip" aria-label={kind === "included" ? "Review blockers" : "Exclusion reasons"}>
                {blockers.map((reason) => (
                  <em key={reason}>{reason}</em>
                ))}
              </div>
            ) : null}
          </article>
        );
      })}
      {rows.length === 0 ? <p className="quiet">No {kind} rows for this dry-run.</p> : null}
      {rows.length > 8 ? <p className="quiet">{rows.length - 8} more rows hidden in this compact preview.</p> : null}
    </div>
  );
}

interface ExportDryRunPanelProps {
  onOpenReviewTask?: (taskId: string) => void | Promise<void>;
}

export function ExportDryRunPanel({ onOpenReviewTask }: ExportDryRunPanelProps) {
  const [exportType, setExportType] = useState<ExportType>("sft");
  const [includeCandidates, setIncludeCandidates] = useState(false);
  const [dryRun, setDryRun] = useState<DatasetExportDryRun | null>(null);
  const [builtExport, setBuiltExport] = useState<DatasetExport | null>(null);
  const [loading, setLoading] = useState(false);
  const [building, setBuilding] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function loadDryRun(nextExportType = exportType, nextIncludeCandidates = includeCandidates) {
    setLoading(true);
    setError(null);
    try {
      const nextDryRun = await getDatasetExportDryRun(nextExportType, nextIncludeCandidates);
      setDryRun(nextDryRun);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Unable to load export dry-run.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void loadDryRun(exportType, includeCandidates);
  }, [exportType, includeCandidates]);

  async function handleBuildExport() {
    setBuilding(true);
    setError(null);
    try {
      const built = await buildDatasetExport(exportType);
      setBuiltExport(built);
      await loadDryRun(exportType, includeCandidates);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Unable to build dataset export.");
    } finally {
      setBuilding(false);
    }
  }

  const total = useMemo(() => (dryRun ? dryRun.included_count + dryRun.excluded_count : 0), [dryRun]);

  return (
    <section className="utility-workbench export-dry-run-workbench" aria-label="Dataset Export Dry Run">
      <header className="utility-workbench-header">
        <div>
          <span>
            <FileJson size={15} />
            Export Review
          </span>
          <h2>Boundary-aware JSONL dry-run</h2>
          <p>Preview what SFT or DPO artifacts would export before building files. Boundary, privacy, status, and rubric blocks are visible here.</p>
        </div>
        <div className="utility-actions">
          <button type="button" onClick={() => void loadDryRun()} disabled={loading} title="Built: refresh dry-run counts from the API.">
            <RefreshCw size={14} />
            {loading ? "Refreshing" : "Refresh"}
          </button>
          <a href={getDatasetJsonlUrl(exportType)} target="_blank" rel="noreferrer" title="Built: open the current approved-only JSONL endpoint.">
            <Download size={14} />
            JSONL
          </a>
          <button
            type="button"
            onClick={() => void handleBuildExport()}
            disabled={building || includeCandidates}
            title={
              includeCandidates
                ? "Candidate rows are preview-only. Turn off candidate preview before building an approved export."
                : "Built: create a DatasetExport record from currently included approved rows."
            }
          >
            <CheckCircle2 size={14} />
            {building ? "Building" : "Build approved export"}
          </button>
        </div>
      </header>

      <div className="utility-controls">
        <label>
          <span>Export type</span>
          <select value={exportType} onChange={(event) => setExportType(event.target.value as ExportType)}>
            <option value="sft">SFT</option>
            <option value="dpo">DPO</option>
          </select>
        </label>
        <label className="check-control">
          <input
            type="checkbox"
            checked={includeCandidates}
            onChange={(event) => setIncludeCandidates(event.target.checked)}
          />
          <span>Include candidate-status artifacts in dry-run</span>
        </label>
      </div>

      {error ? <div className="utility-alert danger">{error}</div> : null}
      {includeCandidates ? (
        <div className="utility-alert warning">
          <ShieldAlert size={14} />
          <span>Candidate rows are review previews only. Approved-only mode is required before building an export file.</span>
        </div>
      ) : null}
      {builtExport ? (
        <div className="utility-alert good">
          <CheckCircle2 size={14} />
          <span>
            Built {builtExport.human_id} with {String(builtExport.manifest.item_count ?? 0)} item(s).{" "}
            <a href={getStoredDatasetJsonlUrl(builtExport.id)} target="_blank" rel="noreferrer">
              Open stored JSONL
            </a>
          </span>
        </div>
      ) : null}

      <DownstreamReadinessPanel onOpenReviewTask={onOpenReviewTask} />

      <div className="dry-run-metrics">
        <article>
          <span>Total artifacts</span>
          <strong>{total}</strong>
        </article>
        <article>
          <span>Included</span>
          <strong>{dryRun?.included_count ?? 0}</strong>
        </article>
        <article>
          <span>Blocked / held</span>
          <strong>{dryRun?.excluded_count ?? 0}</strong>
        </article>
        <article>
          <span>Mode</span>
          <strong>{dryRun?.mode ?? "approved_only"}</strong>
        </article>
      </div>

      <EvidenceCorpusSnapshotPanel snapshot={dryRun?.evidence_corpus_snapshot} />

      <div className="dry-run-columns">
        <section>
          <h3>
            <CheckCircle2 size={14} />
            Included
          </h3>
          <DryRunRows rows={dryRun?.included ?? []} kind="included" />
        </section>
        <section>
          <h3>
            <ShieldAlert size={14} />
            Blocked or held
          </h3>
          <DryRunRows rows={dryRun?.excluded ?? []} kind="excluded" />
        </section>
      </div>
    </section>
  );
}
