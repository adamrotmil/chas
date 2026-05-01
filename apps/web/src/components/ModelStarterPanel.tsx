"use client";

import { CheckCircle2, Download, FileJson, Plus, RefreshCw, Save, Trash2 } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import {
  createModelStarterDPOPair,
  createModelStarterSFTExample,
  deleteModelStarterDPOPair,
  deleteModelStarterSFTExample,
  getModelStarterDPOPairs,
  getModelStarterExportZipUrl,
  getModelStarterSFTExamples,
  getModelStarterSummary,
  splitModelStarterSFT,
  updateModelStarterDPOPair,
  updateModelStarterSFTExample,
  validateModelStarter
} from "@/lib/api";
import type {
  ModelStarterDPOPair,
  ModelStarterSFTExample,
  ModelStarterSplit,
  ModelStarterSummary,
  ModelStarterValidation
} from "@/lib/types";

type StarterTab = "sft" | "dpo" | "validate" | "export";

const emptySft: ModelStarterSFTExample = {
  internal_id: "",
  id: "",
  instruction: "",
  response: "",
  voice: "father_to_adam",
  tone: "",
  provenance: "",
  consent_status: "family_private_training_ok",
  pii_tags: [],
  notes: "",
  status: "active",
  created_at: "",
  updated_at: ""
};

const emptyDpo: ModelStarterDPOPair = {
  internal_id: "",
  id: "",
  prompt: "",
  chosen: "",
  rejected: "",
  provenance: "",
  why_chosen: "",
  notes: "",
  status: "active",
  created_at: "",
  updated_at: ""
};

function preview(value: string, limit = 96): string {
  const compact = value.replace(/\s+/g, " ").trim();
  return compact.length > limit ? `${compact.slice(0, limit - 1)}...` : compact || "Empty";
}

function parseTags(value: string): string[] {
  return value
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
}

function tagsText(tags: string[]): string {
  return tags.join(", ");
}

function exportPreview(sft: ModelStarterSFTExample[], dpo: ModelStarterDPOPair[]): string {
  return [
    "charles-model/",
    "  data/",
    `    charles_sft.jsonl (${sft.length} rows)`,
    `    charles_dpo.jsonl (${dpo.length} rows)`,
    "    README.md",
    "  configs/",
    "    train_sft.yaml",
    "  scripts/",
    "    check_jsonl.py",
    "    split_canary_val.py",
    "  .gitignore"
  ].join("\n");
}

function configPreview(): string {
  return [
    'dataset: "./data/charles_sft.jsonl"',
    'template: "instruction-response"',
    'tokenizer: "auto"',
    'model: "your-base-model-name"',
    "epochs: 3",
    "batch_size: 8",
    "learning_rate: 2e-5",
    "max_seq_len: 4096",
    'save_dir: "./checkpoints/sft"',
    'eval_subset: "val"',
    "logging_steps: 25"
  ].join("\n");
}

export function ModelStarterPanel() {
  const [tab, setTab] = useState<StarterTab>("sft");
  const [summary, setSummary] = useState<ModelStarterSummary | null>(null);
  const [sftRows, setSftRows] = useState<ModelStarterSFTExample[]>([]);
  const [dpoRows, setDpoRows] = useState<ModelStarterDPOPair[]>([]);
  const [selectedSftId, setSelectedSftId] = useState<string | null>(null);
  const [selectedDpoId, setSelectedDpoId] = useState<string | null>(null);
  const [sftDraft, setSftDraft] = useState<ModelStarterSFTExample>(emptySft);
  const [dpoDraft, setDpoDraft] = useState<ModelStarterDPOPair>(emptyDpo);
  const [validation, setValidation] = useState<ModelStarterValidation | null>(null);
  const [split, setSplit] = useState<ModelStarterSplit | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  async function load() {
    setLoading(true);
    setError(null);
    try {
      const [summaryData, sftData, dpoData] = await Promise.all([
        getModelStarterSummary(),
        getModelStarterSFTExamples(),
        getModelStarterDPOPairs()
      ]);
      setSummary(summaryData);
      setValidation(summaryData.validation);
      setSftRows(sftData);
      setDpoRows(dpoData);
      const nextSft = selectedSftId ? sftData.find((row) => row.id === selectedSftId) : sftData[0];
      const nextDpo = selectedDpoId ? dpoData.find((row) => row.id === selectedDpoId) : dpoData[0];
      setSelectedSftId(nextSft?.id ?? null);
      setSelectedDpoId(nextDpo?.id ?? null);
      setSftDraft(nextSft ?? emptySft);
      setDpoDraft(nextDpo ?? emptyDpo);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Unable to load model starter records.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void load();
  }, []);

  const activeSft = useMemo(() => sftRows.find((row) => row.id === selectedSftId) ?? null, [selectedSftId, sftRows]);
  const activeDpo = useMemo(() => dpoRows.find((row) => row.id === selectedDpoId) ?? null, [selectedDpoId, dpoRows]);
  const canExport = (validation ?? summary?.validation)?.ready ?? false;

  function selectSft(row: ModelStarterSFTExample) {
    setSelectedSftId(row.id);
    setSftDraft(row);
    setNotice(null);
  }

  function selectDpo(row: ModelStarterDPOPair) {
    setSelectedDpoId(row.id);
    setDpoDraft(row);
    setNotice(null);
  }

  async function saveSft() {
    setSaving(true);
    setError(null);
    try {
      if (activeSft) {
        const saved = await updateModelStarterSFTExample(activeSft.id, sftDraft);
        setSelectedSftId(saved.id);
        setNotice(`Saved SFT ${saved.id}.`);
      } else {
        const saved = await createModelStarterSFTExample(sftDraft);
        setSelectedSftId(saved.id);
        setNotice(`Created SFT ${saved.id}.`);
      }
      await load();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Unable to save SFT example.");
    } finally {
      setSaving(false);
    }
  }

  async function saveDpo() {
    setSaving(true);
    setError(null);
    try {
      if (activeDpo) {
        const saved = await updateModelStarterDPOPair(activeDpo.id, dpoDraft);
        setSelectedDpoId(saved.id);
        setNotice(`Saved DPO ${saved.id}.`);
      } else {
        const saved = await createModelStarterDPOPair(dpoDraft);
        setSelectedDpoId(saved.id);
        setNotice(`Created DPO ${saved.id}.`);
      }
      await load();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Unable to save DPO pair.");
    } finally {
      setSaving(false);
    }
  }

  async function deleteSft() {
    if (!activeSft) {
      return;
    }
    setSaving(true);
    setError(null);
    try {
      await deleteModelStarterSFTExample(activeSft.id);
      setSelectedSftId(null);
      setSftDraft(emptySft);
      setNotice(`Deleted SFT ${activeSft.id}.`);
      await load();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Unable to delete SFT example.");
    } finally {
      setSaving(false);
    }
  }

  async function deleteDpo() {
    if (!activeDpo) {
      return;
    }
    setSaving(true);
    setError(null);
    try {
      await deleteModelStarterDPOPair(activeDpo.id);
      setSelectedDpoId(null);
      setDpoDraft(emptyDpo);
      setNotice(`Deleted DPO ${activeDpo.id}.`);
      await load();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Unable to delete DPO pair.");
    } finally {
      setSaving(false);
    }
  }

  async function runValidation() {
    setLoading(true);
    setError(null);
    try {
      const result = await validateModelStarter();
      setValidation(result);
      setNotice(result.ready ? "Validation passed. Package is trainer-ready." : "Validation found blockers.");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Unable to validate model starter package.");
    } finally {
      setLoading(false);
    }
  }

  async function runSplit() {
    setLoading(true);
    setError(null);
    try {
      const result = await splitModelStarterSFT(0.05, 42);
      setSplit(result);
      setNotice(`Split preview: ${result.train_count} train / ${result.val_count} val.`);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Unable to preview SFT split.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <section className="model-starter-workbench" aria-label="Model starter package">
      <header className="model-starter-hero">
        <div>
          <span>
            <FileJson size={15} />
            Model starter
          </span>
          <h2>Trainer-ready Charles model package</h2>
          <p>
            Edit the exact SFT and DPO rows, validate them, and export a zip with data, config, scripts, and split-ready files.
          </p>
        </div>
        <div className="model-starter-actions">
          <button type="button" onClick={() => void load()} disabled={loading}>
            <RefreshCw size={14} />
            Refresh
          </button>
          <a href={getModelStarterExportZipUrl()} aria-disabled={!canExport}>
            <Download size={14} />
            Export zip
          </a>
        </div>
      </header>

      <div className="model-starter-metrics">
        <article>
          <span>SFT rows</span>
          <strong>{summary?.sft_count ?? sftRows.length}</strong>
        </article>
        <article>
          <span>DPO rows</span>
          <strong>{summary?.dpo_count ?? dpoRows.length}</strong>
        </article>
        <article data-ready={canExport ? "true" : "false"}>
          <span>Validation</span>
          <strong>{canExport ? "Ready" : "Blocked"}</strong>
        </article>
        <article>
          <span>Issues</span>
          <strong>
            {(validation ?? summary?.validation)?.error_count ?? 0} errors / {(validation ?? summary?.validation)?.warning_count ?? 0} warnings
          </strong>
        </article>
      </div>

      {error ? <div className="utility-alert danger">{error}</div> : null}
      {notice ? <div className="utility-alert good">{notice}</div> : null}

      <nav className="model-starter-tabs" aria-label="Model starter sections">
        {([
          ["sft", "SFT"],
          ["dpo", "DPO"],
          ["validate", "Validate"],
          ["export", "Export"]
        ] as Array<[StarterTab, string]>).map(([id, label]) => (
          <button key={id} type="button" className={tab === id ? "active" : ""} onClick={() => setTab(id)}>
            {label}
          </button>
        ))}
      </nav>

      {tab === "sft" ? (
        <div className="starter-editor-grid">
          <div className="starter-table-card">
            <header>
              <strong>SFT examples</strong>
              <button type="button" onClick={() => { setSelectedSftId(null); setSftDraft({ ...emptySft, id: `sft-${String(sftRows.length + 1).padStart(3, "0")}` }); }}>
                <Plus size={13} />
                New
              </button>
            </header>
            <div className="starter-row-list">
              {sftRows.map((row) => (
                <button key={row.id} type="button" className={selectedSftId === row.id ? "active" : ""} onClick={() => selectSft(row)}>
                  <span>{row.id}</span>
                  <strong>{preview(row.instruction, 72)}</strong>
                  <em>{row.voice || "No voice"} / {row.tone || "No tone"}</em>
                </button>
              ))}
            </div>
          </div>
          <form className="starter-editor-card" onSubmit={(event) => { event.preventDefault(); void saveSft(); }}>
            <header>
              <strong>{activeSft ? `Editing ${activeSft.id}` : "New SFT example"}</strong>
              <div>
                <button type="button" onClick={() => void deleteSft()} disabled={!activeSft || saving} className="danger-button">
                  <Trash2 size={13} />
                  Delete
                </button>
                <button type="submit" disabled={saving}>
                  <Save size={13} />
                  Save
                </button>
              </div>
            </header>
            <div className="starter-field-row">
              <label>
                <span>ID</span>
                <input value={sftDraft.id} onChange={(event) => setSftDraft((current) => ({ ...current, id: event.target.value }))} />
              </label>
              <label>
                <span>Voice</span>
                <input value={sftDraft.voice ?? ""} onChange={(event) => setSftDraft((current) => ({ ...current, voice: event.target.value }))} />
              </label>
              <label>
                <span>Tone</span>
                <input value={sftDraft.tone ?? ""} onChange={(event) => setSftDraft((current) => ({ ...current, tone: event.target.value }))} />
              </label>
            </div>
            <label>
              <span>Instruction</span>
              <textarea value={sftDraft.instruction} onChange={(event) => setSftDraft((current) => ({ ...current, instruction: event.target.value }))} />
            </label>
            <label>
              <span>Response</span>
              <textarea className="tall" value={sftDraft.response} onChange={(event) => setSftDraft((current) => ({ ...current, response: event.target.value }))} />
            </label>
            <div className="starter-field-row">
              <label>
                <span>Consent</span>
                <input value={sftDraft.consent_status ?? ""} onChange={(event) => setSftDraft((current) => ({ ...current, consent_status: event.target.value }))} />
              </label>
              <label>
                <span>PII tags</span>
                <input value={tagsText(sftDraft.pii_tags)} onChange={(event) => setSftDraft((current) => ({ ...current, pii_tags: parseTags(event.target.value) }))} />
              </label>
            </div>
            <label>
              <span>Provenance</span>
              <textarea value={sftDraft.provenance ?? ""} onChange={(event) => setSftDraft((current) => ({ ...current, provenance: event.target.value }))} />
            </label>
            <label>
              <span>Notes</span>
              <textarea value={sftDraft.notes ?? ""} onChange={(event) => setSftDraft((current) => ({ ...current, notes: event.target.value }))} />
            </label>
          </form>
        </div>
      ) : null}

      {tab === "dpo" ? (
        <div className="starter-editor-grid">
          <div className="starter-table-card">
            <header>
              <strong>DPO pairs</strong>
              <button type="button" onClick={() => { setSelectedDpoId(null); setDpoDraft({ ...emptyDpo, id: `dpo-${String(dpoRows.length + 1).padStart(3, "0")}` }); }}>
                <Plus size={13} />
                New
              </button>
            </header>
            <div className="starter-row-list">
              {dpoRows.map((row) => (
                <button key={row.id} type="button" className={selectedDpoId === row.id ? "active" : ""} onClick={() => selectDpo(row)}>
                  <span>{row.id}</span>
                  <strong>{preview(row.prompt, 72)}</strong>
                  <em>{preview(row.why_chosen ?? "", 84)}</em>
                </button>
              ))}
            </div>
          </div>
          <form className="starter-editor-card" onSubmit={(event) => { event.preventDefault(); void saveDpo(); }}>
            <header>
              <strong>{activeDpo ? `Editing ${activeDpo.id}` : "New DPO pair"}</strong>
              <div>
                <button type="button" onClick={() => void deleteDpo()} disabled={!activeDpo || saving} className="danger-button">
                  <Trash2 size={13} />
                  Delete
                </button>
                <button type="submit" disabled={saving}>
                  <Save size={13} />
                  Save
                </button>
              </div>
            </header>
            <label>
              <span>ID</span>
              <input value={dpoDraft.id} onChange={(event) => setDpoDraft((current) => ({ ...current, id: event.target.value }))} />
            </label>
            <label>
              <span>Prompt</span>
              <textarea value={dpoDraft.prompt} onChange={(event) => setDpoDraft((current) => ({ ...current, prompt: event.target.value }))} />
            </label>
            <div className="starter-dpo-responses">
              <label>
                <span>Chosen</span>
                <textarea className="tall" value={dpoDraft.chosen} onChange={(event) => setDpoDraft((current) => ({ ...current, chosen: event.target.value }))} />
              </label>
              <label>
                <span>Rejected</span>
                <textarea className="tall" value={dpoDraft.rejected} onChange={(event) => setDpoDraft((current) => ({ ...current, rejected: event.target.value }))} />
              </label>
            </div>
            <label>
              <span>Why chosen</span>
              <textarea value={dpoDraft.why_chosen ?? ""} onChange={(event) => setDpoDraft((current) => ({ ...current, why_chosen: event.target.value }))} />
            </label>
            <label>
              <span>Provenance</span>
              <textarea value={dpoDraft.provenance ?? ""} onChange={(event) => setDpoDraft((current) => ({ ...current, provenance: event.target.value }))} />
            </label>
          </form>
        </div>
      ) : null}

      {tab === "validate" ? (
        <section className="starter-validation-card">
          <header>
            <div>
              <span>Strict readiness</span>
              <strong>{(validation ?? summary?.validation)?.ready ? "Ready for trainer handoff" : "Blocked until errors are fixed"}</strong>
            </div>
            <button type="button" onClick={() => void runValidation()} disabled={loading}>
              <CheckCircle2 size={14} />
              Validate
            </button>
          </header>
          <div className="starter-validation-list">
            {(validation ?? summary?.validation)?.issues.length ? (
              (validation ?? summary?.validation)?.issues.map((issue) => (
                <article key={`${issue.artifact_type}-${issue.example_id}-${issue.field}-${issue.code}`} data-severity={issue.severity}>
                  <span>{issue.severity}</span>
                  <strong>{issue.example_id || "missing id"} / {issue.field}</strong>
                  <p>{issue.message}</p>
                  <code>{issue.code}</code>
                </article>
              ))
            ) : (
              <p className="quiet">No validation issues. This does not train anything; it means the starter package structure is ready.</p>
            )}
          </div>
        </section>
      ) : null}

      {tab === "export" ? (
        <section className="starter-export-card">
          <header>
            <div>
              <span>Exact package preview</span>
              <strong>What the Export zip button generates</strong>
            </div>
            <div>
              <button type="button" onClick={() => void runSplit()} disabled={loading}>
                Preview split
              </button>
              <a href={getModelStarterExportZipUrl()}>
                <Download size={14} />
                Download zip
              </a>
            </div>
          </header>
          <div className="starter-export-grid">
            <pre>{exportPreview(sftRows, dpoRows)}</pre>
            <pre>{configPreview()}</pre>
          </div>
          {split ? (
            <div className="starter-split-proof">
              <span>Deterministic split</span>
              <strong>{split.train_count} train / {split.val_count} val from {split.source_count} SFT rows</strong>
              <p>
                Seed {split.deterministic_seed}; val ratio {split.val_ratio}. Validation IDs: {split.val_ids.join(", ") || "none"}.
                The zip includes the split script; run it after extract to create the train/val files.
              </p>
            </div>
          ) : null}
        </section>
      ) : null}
    </section>
  );
}
