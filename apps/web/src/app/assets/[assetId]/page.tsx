"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { ArrowLeft, Boxes, Database, FileText, Image, ShieldCheck, Sparkles } from "lucide-react";
import type { ReactNode } from "react";
import { useEffect, useMemo, useState } from "react";
import { getAssetDossier, getAssetPreviewUrl } from "@/lib/api";
import { maturityLabel } from "@/lib/readiness";
import type { AssetDossier, JsonRecord } from "@/lib/types";

function labelFromKey(value: string): string {
  return value.replaceAll("_", " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function formatDate(value?: string | null): string {
  if (!value) {
    return "Unknown";
  }
  return new Date(value).toLocaleString();
}

function formatBytes(value?: number | null): string {
  if (!value) {
    return "Unknown size";
  }
  if (value < 1024) {
    return `${value} B`;
  }
  if (value < 1024 * 1024) {
    return `${Math.round(value / 1024)} KB`;
  }
  return `${(value / (1024 * 1024)).toFixed(1)} MB`;
}

function valuePreview(value: unknown): string {
  if (value === null || value === undefined || value === "") {
    return "Not set";
  }
  if (Array.isArray(value)) {
    return value.length ? value.join(", ") : "None";
  }
  if (typeof value === "object") {
    return JSON.stringify(value).slice(0, 260);
  }
  return String(value);
}

function CountCard({ label, value }: { label: string; value: unknown }) {
  return (
    <div className="dossier-count-card">
      <span>{label}</span>
      <strong>{String(value ?? 0)}</strong>
    </div>
  );
}

function RecordList({
  title,
  icon,
  records,
  render
}: {
  title: string;
  icon: ReactNode;
  records: unknown[];
  render: (record: unknown, index: number) => React.ReactNode;
}) {
  return (
    <section className="dossier-section">
      <header>
        {icon}
        <strong>{title}</strong>
        <span>{records.length}</span>
      </header>
      <div className="dossier-record-stack">
        {records.length ? records.map(render) : <p className="quiet">No records yet.</p>}
      </div>
    </section>
  );
}

function JsonFacts({ value }: { value: JsonRecord }) {
  const entries = Object.entries(value ?? {}).slice(0, 8);
  if (!entries.length) {
    return <p className="quiet">No structured metadata.</p>;
  }
  return (
    <dl className="dossier-facts">
      {entries.map(([key, item]) => (
        <div key={key}>
          <dt>{labelFromKey(key)}</dt>
          <dd>{valuePreview(item)}</dd>
        </div>
      ))}
    </dl>
  );
}

export default function AssetDossierPage() {
  const params = useParams<{ assetId: string }>();
  const assetId = params.assetId;
  const [dossier, setDossier] = useState<AssetDossier | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
    getAssetDossier(assetId)
      .then((nextDossier) => {
        if (!cancelled) {
          setDossier(nextDossier);
        }
      })
      .catch((caught: unknown) => {
        if (!cancelled) {
          setError(caught instanceof Error ? caught.message : "Unable to load asset dossier.");
        }
      });
    return () => {
      cancelled = true;
    };
  }, [assetId]);

  const previewable = dossier
    ? dossier.asset.asset_type === "photo" || dossier.asset.asset_type === "scan" || (dossier.asset.mime_type ?? "").startsWith("image/")
    : false;
  const latestBoundary = useMemo(() => dossier?.boundaries.at(-1), [dossier]);

  if (error) {
    return (
      <main className="dossier-shell">
        <div className="error-banner">{error}</div>
        <Link href="/" className="dossier-back-link">
          <ArrowLeft size={15} />
          Back to Workbench
        </Link>
      </main>
    );
  }

  if (!dossier) {
    return (
      <main className="dossier-shell">
        <p className="quiet">Loading asset dossier...</p>
      </main>
    );
  }

  return (
    <main className="dossier-shell">
      <header className="dossier-header">
        <Link href="/" className="dossier-back-link">
          <ArrowLeft size={15} />
          Back to Workbench
        </Link>
        <div>
          <span>{labelFromKey(dossier.asset.asset_type)} dossier</span>
          <h1>{dossier.asset.title || dossier.asset.original_filename || dossier.asset.human_id}</h1>
          <p>{dossier.asset.original_filename || dossier.asset.human_id}</p>
        </div>
      </header>

      <section className="dossier-hero">
        <div className="dossier-preview">
          {previewable ? (
            <img src={getAssetPreviewUrl(dossier.asset.id)} alt={dossier.asset.title || "Asset preview"} />
          ) : (
            <div>
              <FileText size={28} />
              <span>{labelFromKey(dossier.asset.asset_type)} source</span>
            </div>
          )}
        </div>
        <div className="dossier-summary-panel">
          <div className="dossier-badge-row">
            <span>{maturityLabel(dossier.asset.maturity_level)}</span>
            <span>{labelFromKey(dossier.asset.import_status)}</span>
            <span>{labelFromKey(dossier.asset.processing_status)}</span>
            {latestBoundary ? <span>{labelFromKey(latestBoundary.privacy_level)}</span> : null}
          </div>
          <dl className="dossier-facts">
            <div>
              <dt>Human ID</dt>
              <dd>{dossier.asset.human_id}</dd>
            </div>
            <div>
              <dt>Source system</dt>
              <dd>{dossier.asset.source_system || "Unknown"}</dd>
            </div>
            <div>
              <dt>MIME type</dt>
              <dd>{dossier.asset.mime_type || "Unknown"}</dd>
            </div>
            <div>
              <dt>Updated</dt>
              <dd>{formatDate(dossier.asset.updated_at)}</dd>
            </div>
          </dl>
        </div>
      </section>

      <section className="dossier-count-grid">
        <CountCard label="Snapshots" value={dossier.counts.snapshots} />
        <CountCard label="Derivatives" value={dossier.counts.derivatives} />
        <CountCard label="Segments" value={dossier.counts.segments} />
        <CountCard label="Boundaries" value={dossier.counts.boundaries} />
        <CountCard label="Tasks" value={dossier.counts.tasks} />
        <CountCard label="Annotations" value={dossier.counts.annotations} />
      </section>

      <div className="dossier-grid">
        <RecordList
          title="Source References"
          icon={<Database size={15} />}
          records={dossier.external_refs}
          render={(record) => {
            const item = record as AssetDossier["external_refs"][number];
            return (
              <article key={item.id} className="dossier-record">
                <strong>{item.source_system}</strong>
                <span>{item.external_id}</span>
                <p>{item.uri || "No source URI recorded."}</p>
                <JsonFacts value={item.metadata_json} />
              </article>
            );
          }}
        />
        <RecordList
          title="Snapshots and Objects"
          icon={<Boxes size={15} />}
          records={[...dossier.snapshots, ...dossier.object_files]}
          render={(record, index) => {
            const item = record as JsonRecord;
            const title = item.snapshot_type ? `${labelFromKey(String(item.snapshot_type))} v${item.version}` : String(item.uri);
            return (
              <article key={String(item.id ?? index)} className="dossier-record">
                <strong>{title}</strong>
                <span>{formatBytes(typeof item.byte_size === "number" ? item.byte_size : null)}</span>
                <p>{String(item.object_key ?? item.checksum_sha256 ?? item.object_file_id ?? "No object detail")}</p>
              </article>
            );
          }}
        />
        <RecordList
          title="Derivatives"
          icon={<Image size={15} />}
          records={dossier.derivatives}
          render={(record) => {
            const item = record as AssetDossier["derivatives"][number];
            return (
              <article key={item.id} className="dossier-record">
                <strong>{labelFromKey(item.derivative_type)}</strong>
                <span>{labelFromKey(item.status)}</span>
                <JsonFacts value={item.metadata_json} />
              </article>
            );
          }}
        />
        <RecordList
          title="Boundaries"
          icon={<ShieldCheck size={15} />}
          records={dossier.boundaries}
          render={(record) => {
            const item = record as AssetDossier["boundaries"][number];
            return (
              <article key={item.id} className="dossier-record">
                <strong>{labelFromKey(item.privacy_level)}</strong>
                <span>{item.reviewed_by ? `Reviewed by ${item.reviewed_by}` : "Unreviewed"}</span>
                <p>{item.notes || "No boundary notes."}</p>
                <div className="dossier-badge-row compact">
                  {item.searchable ? <span>Searchable</span> : null}
                  {item.quotable ? <span>Quotable</span> : null}
                  {item.usable_for_sft ? <span>SFT</span> : null}
                  {item.usable_for_dpo ? <span>DPO</span> : null}
                  {item.redaction_required ? <span>Needs redaction</span> : null}
                </div>
              </article>
            );
          }}
        />
        <RecordList
          title="Tasks and Annotations"
          icon={<Sparkles size={15} />}
          records={[...dossier.tasks, ...dossier.annotations]}
          render={(record, index) => {
            const item = record as JsonRecord;
            return (
              <article key={String(item.id ?? index)} className="dossier-record">
                <strong>{labelFromKey(String(item.task_type ?? item.annotation_type ?? "record"))}</strong>
                <span>{labelFromKey(String(item.status ?? item.created_by ?? "recorded"))}</span>
                <p>{String(item.reason_created ?? item.notes ?? "No notes.")}</p>
              </article>
            );
          }}
        />
        <RecordList
          title="Metadata Profiles"
          icon={<FileText size={15} />}
          records={dossier.metadata_profiles}
          render={(record) => {
            const item = record as AssetDossier["metadata_profiles"][number];
            return (
              <article key={item.id} className="dossier-record">
                <strong>{item.title || labelFromKey(item.profile_type)}</strong>
                <span>{labelFromKey(item.metadata_status)}</span>
                <p>{item.summary || item.adam_context_note || "No summary yet."}</p>
                <JsonFacts value={item.quality_signals} />
              </article>
            );
          }}
        />
      </div>
    </main>
  );
}
