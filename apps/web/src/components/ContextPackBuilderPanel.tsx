"use client";

import { Boxes, CheckCircle2, ShieldAlert, Sparkles } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { buildContextPack, getContextPacks } from "@/lib/api";
import type { ContextPack, ContextPackBuildItem, ContextPackBuildResponse, JsonRecord, Task } from "@/lib/types";

type Props = {
  selectedTask: Task | null;
  tasks: Task[];
};

const defaultUserIntents = [
  "gold_voice_generation",
  "grounded_voice_response",
  "email_reply_candidate",
  "memory_scene_candidate",
  "style_eval_case"
];

const defaultTruthModes = ["adam_expert_reconstruction", "interpretive_synthesis", "archival_source", "system_inference"];

function payloadString(payload: JsonRecord, key: string, fallback = ""): string {
  const value = payload[key];
  return typeof value === "string" && value.trim() ? value : fallback;
}

function payloadStringList(payload: JsonRecord, key: string): string[] {
  const value = payload[key];
  if (!Array.isArray(value)) {
    return [];
  }
  return value.map((item) => String(item)).filter(Boolean);
}

function pushUnique(items: ContextPackBuildItem[], item: ContextPackBuildItem) {
  if (!items.some((existing) => existing.item_type === item.item_type && existing.item_id === item.item_id)) {
    items.push(item);
  }
}

function contextItemsFromTask(task: Task | null): ContextPackBuildItem[] {
  if (!task) {
    return [];
  }
  const payload = task.input_payload;
  const items: ContextPackBuildItem[] = [];
  const chunkIds = [
    ...payloadStringList(payload, "selected_chunk_ids"),
    ...payloadStringList(payload, "source_chunks_to_use"),
    ...payloadStringList(payload, "reviewed_chunk_ids")
  ];
  chunkIds.forEach((id, index) => pushUnique(items, { item_type: "segment", item_id: id, role: "source_chunk", rank: index }));

  for (const key of ["segment_id", "source_segment_id"]) {
    const id = payloadString(payload, key);
    if (id) {
      pushUnique(items, { item_type: "segment", item_id: id, role: "source_segment", rank: items.length });
    }
  }

  if (task.target_type === "segment") {
    pushUnique(items, { item_type: "segment", item_id: task.target_id, role: "task_target", rank: items.length });
  }
  if (task.target_type === "asset") {
    pushUnique(items, { item_type: "asset", item_id: task.target_id, role: "source_asset", rank: items.length });
  }

  for (const key of ["asset_id", "source_asset_id"]) {
    const id = payloadString(payload, key);
    if (id) {
      pushUnique(items, { item_type: "asset", item_id: id, role: "source_asset", rank: items.length });
    }
  }

  return items.map((item, index) => ({ ...item, rank: item.rank ?? index }));
}

function selectedFactoryTask(selectedTask: Task | null, tasks: Task[]): Task | null {
  if (selectedTask) {
    return selectedTask;
  }
  return (
    tasks.find((task) => task.status === "ready" && task.task_type === "grounded_prompt_pair_candidate") ??
    tasks.find((task) => task.status === "ready" && task.input_payload.source_prompt_pair_task_id) ??
    null
  );
}

function previewFactFromTask(task: Task | null): string {
  if (!task) {
    return "";
  }
  const payload = task.input_payload;
  return (
    payloadString(payload, "source_excerpt") ||
    payloadString(payload, "preview_text") ||
    payloadString(payload, "text") ||
    payloadString(payload, "prompt")
  );
}

function boundaryStatus(pack: ContextPack): string {
  const status = pack.boundaries_snapshot.boundary_status;
  return typeof status === "string" ? status : "unknown";
}

function displayDate(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return date.toLocaleString();
}

export function ContextPackBuilderPanel({ selectedTask, tasks }: Props) {
  const task = useMemo(() => selectedFactoryTask(selectedTask, tasks), [selectedTask, tasks]);
  const items = useMemo(() => contextItemsFromTask(task), [task]);
  const [packs, setPacks] = useState<ContextPack[]>([]);
  const [userIntent, setUserIntent] = useState("gold_voice_generation");
  const [voiceMode, setVoiceMode] = useState("father_to_adam");
  const [truthMode, setTruthMode] = useState("adam_expert_reconstruction");
  const [allowedFact, setAllowedFact] = useState("");
  const [blockedFact, setBlockedFact] = useState("");
  const [result, setResult] = useState<ContextPackBuildResponse | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const payload = task?.input_payload ?? {};
    setUserIntent(payloadString(payload, "prompt_intent", "gold_voice_generation"));
    setVoiceMode(payloadString(payload, "voice_mode", payloadString(payload, "voice_training_role", "father_to_adam")));
    setTruthMode(payloadString(payload, "truth_mode", "adam_expert_reconstruction"));
    setAllowedFact(previewFactFromTask(task).slice(0, 1200));
  }, [task]);

  async function loadPacks() {
    try {
      setPacks(await getContextPacks());
    } catch {
      setPacks([]);
    }
  }

  useEffect(() => {
    void loadPacks();
  }, []);

  async function handleBuild() {
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      const built = await buildContextPack({
        user_intent: userIntent,
        requested_voice_mode: voiceMode,
        truth_mode: truthMode,
        items,
        allowed_facts: allowedFact.trim() ? [allowedFact.trim()] : [],
        blocked_facts: blockedFact.trim() ? [blockedFact.trim()] : [],
        style_guidance: {
          source_task_id: task?.id,
          source_task_type: task?.task_type,
          builder_surface: "workbench_pair_factory"
        }
      });
      setResult(built);
      await loadPacks();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Unable to build context pack.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="utility-panel context-builder-panel" aria-label="Context Pack Builder">
      <header className="utility-panel-header">
        <div>
          <span>
            <Boxes size={14} />
            Context Pack Builder
          </span>
          <strong>{task ? payloadString(task.input_payload, "source_title", payloadString(task.input_payload, "source_filename", task.human_id)) : "No selected source"}</strong>
        </div>
        <button
          type="button"
          onClick={() => void handleBuild()}
          disabled={busy || (items.length === 0 && !allowedFact.trim())}
          title="Built: creates a boundary-checked context pack. It does not call a model."
        >
          <Sparkles size={14} />
          {busy ? "Building" : "Build pack"}
        </button>
      </header>

      <div className="utility-grid context-builder-grid">
        <label>
          <span>User intent</span>
          <select value={userIntent} onChange={(event) => setUserIntent(event.target.value)}>
            {defaultUserIntents.map((option) => (
              <option key={option} value={option}>
                {option}
              </option>
            ))}
          </select>
        </label>
        <label>
          <span>Voice mode</span>
          <input value={voiceMode} onChange={(event) => setVoiceMode(event.target.value)} />
        </label>
        <label>
          <span>Truth mode</span>
          <select value={truthMode} onChange={(event) => setTruthMode(event.target.value)}>
            {defaultTruthModes.map((option) => (
              <option key={option} value={option}>
                {option}
              </option>
            ))}
          </select>
        </label>
        <div className="utility-mini-list">
          <span>Boundary items</span>
          {items.length > 0 ? (
            items.slice(0, 5).map((item) => (
              <em key={`${item.item_type}:${item.item_id}`}>
                {item.item_type}/{item.item_id.slice(0, 8)} · {item.role}
              </em>
            ))
          ) : (
            <em>No source rows found; use the allowed fact field as a temporary manual context fact.</em>
          )}
        </div>
      </div>

      <div className="utility-two-up">
        <label>
          <span>Allowed fact or excerpt</span>
          <textarea value={allowedFact} onChange={(event) => setAllowedFact(event.target.value)} rows={4} />
        </label>
        <label>
          <span>Blocked fact / redaction note</span>
          <textarea value={blockedFact} onChange={(event) => setBlockedFact(event.target.value)} rows={4} />
        </label>
      </div>

      {error ? <div className="utility-alert danger">{error}</div> : null}
      {result ? (
        <div className={result.excluded_count > 0 ? "utility-alert warning" : "utility-alert good"}>
          {result.excluded_count > 0 ? <ShieldAlert size={14} /> : <CheckCircle2 size={14} />}
          <span>
            Built {result.human_id}: {result.included_count} included, {result.excluded_count} excluded
            {result.warnings.length > 0 ? `, ${result.warnings.length} warning(s)` : ""}.
          </span>
        </div>
      ) : null}

      <div className="utility-mini-list recent-pack-list">
        <span>Recent packs</span>
        {packs.slice(0, 4).map((pack) => (
          <em key={pack.id}>
            {pack.human_id} · {pack.user_intent} · {boundaryStatus(pack)} · {displayDate(pack.created_at)}
          </em>
        ))}
        {packs.length === 0 ? <em>No context packs yet.</em> : null}
      </div>
    </section>
  );
}
