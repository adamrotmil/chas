"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { ArrowLeft, Boxes, ClipboardList, Database, FileText, Image, ShieldCheck, Sparkles } from "lucide-react";
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
        <CountCard label="Receipts" value={dossier.counts.task_receipts} />
        <CountCard label="Context Packs" value={dossier.counts.context_packs} />
        <CountCard label="Gold Examples" value={dossier.counts.gold_voice_examples} />
        <CountCard label="SFT" value={dossier.counts.sft_candidates} />
        <CountCard label="DPO" value={dossier.counts.dpo_pairs} />
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
          title="Task Receipts"
          icon={<ClipboardList size={15} />}
          records={dossier.task_receipts ?? []}
          render={(record) => {
            const item = record as NonNullable<AssetDossier["task_receipts"]>[number];
            const projectionValue = item.summary.submit_projection;
            const projection =
              projectionValue && typeof projectionValue === "object" && !Array.isArray(projectionValue)
                ? (projectionValue as JsonRecord)
                : null;
            const contentHash = typeof projection?.content_sha256 === "string" ? projection.content_sha256 : "";
            const readiness = typeof projection?.submit_readiness === "string" ? projection.submit_readiness : "";
            const previewYaml = typeof projection?.export_preview_yaml === "string" ? projection.export_preview_yaml : "";
            const vectorStatus =
              typeof item.created_or_updated.vector_handoff_status === "string"
                ? item.created_or_updated.vector_handoff_status
                : typeof projection?.vector_handoff_status === "string"
                ? projection.vector_handoff_status
                : "";
            const vectorReason =
              typeof item.created_or_updated.vector_handoff_reason === "string" ? item.created_or_updated.vector_handoff_reason : "";
            const vectorRecordId =
              typeof item.created_or_updated.vector_handoff_record_id === "string" ? item.created_or_updated.vector_handoff_record_id : "";
            return (
              <article key={item.id} className="dossier-record">
                <strong>{item.human_id}</strong>
                <span>
                  {labelFromKey(item.task_type)} · {labelFromKey(item.downstream_status)}
                </span>
                <p>{item.next_action_label || "Durable annotation receipt recorded."}</p>
                <div className="dossier-badge-row compact">
                  <span>Boundary {labelFromKey(item.boundary_status)}</span>
                  {readiness ? <span>{labelFromKey(readiness)}</span> : null}
                  {vectorStatus ? <span>Vector {labelFromKey(vectorStatus)}</span> : null}
                  {vectorRecordId ? <span>Vector record {vectorRecordId.slice(0, 8)}</span> : null}
                  {contentHash ? <span>Hash {contentHash.slice(0, 12)}</span> : null}
                </div>
                {vectorReason ? <p className="dossier-receipt-vector-reason">{vectorReason}</p> : null}
                {previewYaml ? (
                  <details className="dossier-receipt-preview">
                    <summary>Submit payload YAML</summary>
                    <pre>{previewYaml}</pre>
                  </details>
                ) : null}
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
        <RecordList
          title="Context Packs"
          icon={<Boxes size={15} />}
          records={dossier.context_packs}
          render={(record) => {
            const item = record as AssetDossier["context_packs"][number];
            const packItems = dossier.context_pack_items.filter((packItem) => packItem.context_pack_id === item.id);
            return (
              <article key={item.id} className="dossier-record">
                <strong>{item.human_id}</strong>
                <span>{labelFromKey(item.user_intent)}</span>
                <p>
                  {packItems.length} linked item{packItems.length === 1 ? "" : "s"} · {item.allowed_facts.length} allowed fact
                  {item.allowed_facts.length === 1 ? "" : "s"}
                </p>
                <JsonFacts value={item.boundaries_snapshot} />
              </article>
            );
          }}
        />
        <RecordList
          title="Gold Voice Examples"
          icon={<Sparkles size={15} />}
          records={dossier.gold_voice_examples}
          render={(record) => {
            const item = record as AssetDossier["gold_voice_examples"][number];
            return (
              <article key={item.id} className="dossier-record">
                <strong>{item.human_id}</strong>
                <span>{labelFromKey(item.voice_mode)}</span>
                <p>{item.adam_gold_edit.slice(0, 220) || "No gold edit text."}</p>
                <div className="dossier-badge-row compact">
                  {item.downstream_use?.sft ? <span>SFT requested</span> : null}
                  {item.downstream_use?.dpo ? <span>DPO requested</span> : null}
                  {item.approved_by ? <span>Approved</span> : null}
                </div>
              </article>
            );
          }}
        />
        <RecordList
          title="Export Artifacts"
          icon={<Database size={15} />}
          records={[
            ...dossier.sft_candidates.map((item) => ({ ...item, artifact_kind: "sft_candidate" })),
            ...dossier.dpo_pairs.map((item) => ({ ...item, artifact_kind: "dpo_pair" })),
            ...dossier.eval_cases.map((item) => ({ ...item, artifact_kind: "eval_case" })),
            ...dossier.anti_patterns.map((item) => ({ ...item, artifact_kind: "anti_pattern" })),
            ...dossier.style_rules.map((item) => ({ ...item, artifact_kind: "style_rule" }))
          ]}
          render={(record, index) => {
            const item = record as JsonRecord;
            const title = String(item.human_id ?? item.artifact_kind ?? item.id ?? `artifact_${index}`);
            const status = String(item.export_status ?? item.status ?? "recorded");
            const body = String(item.prompt ?? item.rule ?? item.name ?? item.why_wrong ?? item.id ?? "No artifact preview.");
            return (
              <article key={String(item.id ?? index)} className="dossier-record">
                <strong>{labelFromKey(title)}</strong>
                <span>{labelFromKey(status)}</span>
                <p>{body.slice(0, 220)}</p>
              </article>
            );
          }}
        />
      </div>
    </main>
  );
}
