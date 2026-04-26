"use client";

import {
  CheckCircle2,
  ChevronLeft,
  ChevronRight,
  ClipboardList,
  Copy,
  Flag,
  Gauge,
  Image,
  Mail,
  RotateCcw,
  Save,
  ShieldCheck,
  SkipForward,
  Sparkles,
  TextCursorInput
} from "lucide-react";
import { FormEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { createEntity, getAssetTextChunks, getEntities, getTaskDraft, saveTaskDraft } from "@/lib/api";
import type { Entity, Segment, Task } from "@/lib/types";

type Decisions = Record<string, unknown>;
type ChunkSelection = {
  chunk_scope: string;
  selected_chunk_ids: string[];
  active_chunk_id?: string;
  selected_chunk_count: number;
};

function sameChunkSelection(left: ChunkSelection, right: ChunkSelection): boolean {
  return (
    left.chunk_scope === right.chunk_scope &&
    left.active_chunk_id === right.active_chunk_id &&
    left.selected_chunk_count === right.selected_chunk_count &&
    left.selected_chunk_ids.length === right.selected_chunk_ids.length &&
    left.selected_chunk_ids.every((id, index) => id === right.selected_chunk_ids[index])
  );
}

function sameDecisionRecord(left: Decisions, right: Decisions): boolean {
  const leftKeys = Object.keys(left);
  const rightKeys = Object.keys(right);
  return leftKeys.length === rightKeys.length && leftKeys.every((key) => Object.is(left[key], right[key]));
}

interface TaskWorkbenchProps {
  task: Task;
  queuePosition: number;
  queueTotal: number;
  qualityScore: number;
  completedThisSession: number;
  memoriesCount: number;
  goldExamplesCount: number;
  assetsCount: number;
  onSubmit: (decisions: Decisions, notes?: string) => Promise<void>;
  onSkip: () => Promise<void>;
  onFlag: () => Promise<void>;
  onPrevious: () => void;
  onNext: () => void;
}

const taskLabels: Record<string, { label: string; icon: React.ReactNode }> = {
  asset_triage: { label: "Asset Triage", icon: <ClipboardList size={18} /> },
  photo_context: { label: "Photo Context", icon: <Image size={18} /> },
  text_segment_review: { label: "Text Segment Review", icon: <TextCursorInput size={18} /> },
  boundary_review: { label: "Boundary Review", icon: <ShieldCheck size={18} /> },
  email_voice_sample: { label: "Email Voice Sample", icon: <Mail size={18} /> },
  gold_voice_edit: { label: "Gold Voice Edit", icon: <Sparkles size={18} /> }
};

const NEW_PERSON_VALUE = "__new_person__";
const INSPECTOR_RESIZE_STEP = 16;
const inspectorBounds = { min: 320, max: 640 };

const decisionPromptLabels: Record<string, string> = {
  source_genre: "What kind of document it is",
  authorship: "Who made it",
  creator_entity_ids: "Which person record made it",
  authorship_note: "How the creator relates to Charles or this source",
  fictionality_status: "Whether it is factual, fictional, mixed, memory, inference, or generated",
  truth_status: "Where its truth comes from",
  voice_presence: "Whether Charles's voice is present",
  adam_context_note: "Why Adam thinks it matters",
  boundary_rationale: "Why this boundary/use decision is OK",
  usable_for_voice_context: "Whether it can be used for voice context",
  usable_for_grounded_generation: "Whether it can ground generated responses",
  usable_for_sft: "Whether it can be used for SFT",
  usable_for_dpo: "Whether it can be used for DPO",
  charles_voice_presence: "Whether Charles's voice is actually present",
  charles_email_role: "Where Charles appears in the thread",
  other_voice_roles: "Who else is speaking",
  context_use: "How this source should be used",
  authenticity_value: "How authentic the signal is",
  voice_density: "How much Charles voice signal is present",
  adam_gold_edit: "What Adam changed into the preferred version",
  ratings: "Why the preferred version works",
  failure_modes: "What the rejected version gets wrong",
  export_flags: "Which downstream examples to create"
};

function payloadString(value: unknown, fallback = ""): string {
  return typeof value === "string" ? value : fallback;
}

function labelFromKey(value: string): string {
  return value
    .split("_")
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(" ");
}

function promptFromDecisionKey(value: string): string {
  return decisionPromptLabels[value] ?? labelFromKey(value);
}

function taskDisplayTitle(task: Task): string {
  const payload = task.input_payload;
  for (const key of ["source_filename", "asset_title", "title", "segment_title", "prompt"]) {
    const value = payload[key];
    if (typeof value === "string" && value.trim()) {
      return value;
    }
  }
  return task.human_id;
}

function payloadNumber(value: unknown, fallback = 3): number {
  return typeof value === "number" ? value : fallback;
}

function locatorNumber(locator: Record<string, unknown>, key: string, fallback = 0): number {
  const value = locator[key];
  return typeof value === "number" ? value : fallback;
}

function payloadArray(value: unknown): string[] {
  return Array.isArray(value) ? value.map(String) : [];
}

function parseList(value: string): string[] {
  return value
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
}

function decisionString(decisions: Decisions, key: string, fallback = ""): string {
  const value = decisions[key];
  return typeof value === "string" ? value : fallback;
}

function decisionNumber(decisions: Decisions, key: string, fallback: number): number {
  const value = decisions[key];
  return typeof value === "number" ? value : fallback;
}

function decisionListText(decisions: Decisions, key: string, fallback = ""): string {
  const value = decisions[key];
  return Array.isArray(value) ? value.map(String).join(", ") : fallback;
}

function decisionBoolean(decisions: Decisions, key: string, fallback: boolean): boolean {
  const value = decisions[key];
  if (typeof value === "boolean") {
    return value;
  }
  if (typeof value === "string") {
    return value.toLowerCase() === "yes" || value.toLowerCase() === "true";
  }
  return fallback;
}

function clamp(value: number, min: number, max: number): number {
  return Math.min(Math.max(value, min), max);
}

function entityOptionLabel(entity: Entity): string {
  const relationships = [entity.relationship_to_charles, entity.relationship_to_adam].filter(Boolean).join(" / ");
  return relationships ? `${entity.canonical_name} (${relationships})` : entity.canonical_name;
}

function Field({ label, hint, children }: { label: string; hint?: string; children: React.ReactNode }) {
  return (
    <label className="field">
      <span className="field-label">{label}</span>
      {hint ? <small>{hint}</small> : null}
      {children}
    </label>
  );
}

function formatDraftTime(value: string | null): string {
  if (!value) {
    return "";
  }
  return new Intl.DateTimeFormat(undefined, {
    hour: "numeric",
    minute: "2-digit",
    second: "2-digit"
  }).format(new Date(value));
}

function LinePreview({ text }: { text: string }) {
  const lines = text.split(/\r?\n/);
  return (
    <div className="line-preview">
      {lines.map((line, index) => (
        <div className="line-row" key={`${index}-${line.slice(0, 12)}`}>
          <span>{index + 1}</span>
          <code>{line || " "}</code>
        </div>
      ))}
    </div>
  );
}

function FormHint({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="form-hint">
      <strong>{title}</strong>
      <p>{children}</p>
    </div>
  );
}

function TextArea({
  value,
  onChange,
  rows = 4
}: {
  value: string;
  onChange: (value: string) => void;
  rows?: number;
}) {
  return <textarea rows={rows} value={value} onChange={(event) => onChange(event.target.value)} />;
}

function Select({
  value,
  onChange,
  options
}: {
  value: string;
  onChange: (value: string) => void;
  options: string[];
}) {
  return (
    <select value={value} onChange={(event) => onChange(event.target.value)}>
      {options.map((option) => (
        <option key={option} value={option}>
          {labelFromKey(option)}
        </option>
      ))}
    </select>
  );
}

function SourcePreview({ task }: { task: Task }) {
  const previewText = payloadString(task.input_payload.preview_text) || payloadString(task.input_payload.text);
  if (!previewText) {
    return null;
  }
  const emailHeaders =
    task.input_payload.email_headers && typeof task.input_payload.email_headers === "object"
      ? (task.input_payload.email_headers as Record<string, unknown>)
      : null;

  return (
    <section className="source-text">
      <div className="source-text-header">
        <span>Source text</span>
        <strong>{payloadString(task.input_payload.source_filename) || payloadString(task.input_payload.asset_title)}</strong>
      </div>
      {emailHeaders ? (
        <div className="source-text-email">
          {payloadString(emailHeaders.subject) ? <span>Subject: {payloadString(emailHeaders.subject)}</span> : null}
          {payloadString(emailHeaders.from) ? <span>From: {payloadString(emailHeaders.from)}</span> : null}
          {payloadString(emailHeaders.to) ? <span>To: {payloadString(emailHeaders.to)}</span> : null}
          {payloadString(emailHeaders.date) ? <span>Date: {payloadString(emailHeaders.date)}</span> : null}
        </div>
      ) : null}
      <LinePreview text={previewText} />
      {typeof task.input_payload.chunk_count === "number" || typeof task.input_payload.total_chars === "number" ? (
        <div className="source-text-meta">
          {typeof task.input_payload.chunk_count === "number" ? <span>{task.input_payload.chunk_count} chunks</span> : null}
          {typeof task.input_payload.total_chars === "number" ? <span>{task.input_payload.total_chars} chars extracted</span> : null}
          {task.input_payload.truncated ? <span>preview capped</span> : null}
        </div>
      ) : null}
    </section>
  );
}

function EditableExtraction({
  task,
  activeChunk,
  initialCleanedText,
  onChange
}: {
  task: Task;
  activeChunk?: Segment;
  initialCleanedText?: string;
  onChange: (value: Decisions) => void;
}) {
  const previewText = payloadString(task.input_payload.preview_text) || payloadString(task.input_payload.text);
  const activeChunkId = activeChunk?.id ?? "";
  const [cleanedText, setCleanedText] = useState(initialCleanedText || activeChunk?.text_content || previewText);

  useEffect(() => {
    setCleanedText(initialCleanedText || activeChunk?.text_content || previewText);
  }, [activeChunkId, activeChunk?.text_content, initialCleanedText, previewText, task.id]);

  useEffect(() => {
    onChange({
      cleaned_text: cleanedText,
      cleaned_text_scope: activeChunk ? "active_chunk" : "preview",
      cleaned_text_chunk_id: activeChunk?.id ?? null,
      extraction_edit_notes: cleanedText === (activeChunk?.text_content || previewText) ? "unchanged" : "edited"
    });
  }, [activeChunk, cleanedText, onChange, previewText]);

  if (!previewText && !activeChunk) {
    return null;
  }

  return (
    <section className="editable-extraction">
      <div>
        <span>Derived working version</span>
        <strong>{activeChunk ? "Active chunk" : "Preview copy"}</strong>
      </div>
      <TextArea value={cleanedText} onChange={setCleanedText} rows={8} />
      <div className="editor-foot">
        <span>{cleanedText.length} chars</span>
        <span>{cleanedText === (activeChunk?.text_content || previewText) ? "Unchanged" : "Edited"}</span>
      </div>
    </section>
  );
}

function ChunkBrowser({
  task,
  initialSelection,
  onChange
}: {
  task: Task;
  initialSelection: ChunkSelection;
  onChange: (selection: ChunkSelection, activeChunk?: Segment) => void;
}) {
  const assetId = payloadString(task.input_payload.asset_id);
  const [chunks, setChunks] = useState<Segment[]>([]);
  const [activeId, setActiveId] = useState(initialSelection.active_chunk_id ?? "");
  const [selectedIds, setSelectedIds] = useState<string[]>(initialSelection.selected_chunk_ids);
  const [error, setError] = useState("");
  const activeChunk = chunks.find((chunk) => chunk.id === activeId) ?? chunks[0];

  useEffect(() => {
    setChunks([]);
    setActiveId(initialSelection.active_chunk_id ?? "");
    setSelectedIds(initialSelection.selected_chunk_ids);
    setError("");
    if (!assetId) {
      return;
    }

    let cancelled = false;
    getAssetTextChunks(assetId)
      .then((nextChunks) => {
        if (cancelled) {
          return;
        }
        setChunks(nextChunks);
        setActiveId(initialSelection.active_chunk_id ?? nextChunks[0]?.id ?? "");
      })
      .catch((caught: unknown) => {
        if (!cancelled) {
          setError(caught instanceof Error ? caught.message : "Unable to load chunks.");
        }
      });

    return () => {
      cancelled = true;
    };
  }, [assetId, initialSelection.active_chunk_id, initialSelection.selected_chunk_ids, task.id]);

  useEffect(() => {
    onChange({
      chunk_scope: selectedIds.length > 0 ? "selected_chunks" : "preview_only",
      selected_chunk_ids: selectedIds,
      active_chunk_id: activeChunk?.id,
      selected_chunk_count: selectedIds.length
    }, activeChunk);
  }, [activeChunk, onChange, selectedIds]);

  if (!assetId || (chunks.length === 0 && !error)) {
    return null;
  }

  function toggleChunk(chunkId: string) {
    setSelectedIds((current) =>
      current.includes(chunkId) ? current.filter((id) => id !== chunkId) : [...current, chunkId]
    );
  }

  return (
    <section className="chunk-browser">
      <div className="chunk-browser-header">
        <div>
          <span>Extracted chunks</span>
          <strong>{chunks.length} available</strong>
        </div>
        <div className="chunk-actions">
          <button type="button" onClick={() => setSelectedIds(chunks.map((chunk) => chunk.id))} disabled={chunks.length === 0}>
            Select all
          </button>
          <button type="button" onClick={() => setSelectedIds([])} disabled={selectedIds.length === 0}>
            Clear
          </button>
        </div>
      </div>
      {error ? <p className="quiet">{error}</p> : null}
      {chunks.length > 0 ? (
        <>
          <div className="chunk-list" aria-label="Extracted text chunks">
            {chunks.map((chunk, index) => {
              const chunkIndex = locatorNumber(chunk.locator, "chunk_index", index + 1);
              const selected = selectedIds.includes(chunk.id);
              return (
                <div className={chunk.id === activeChunk?.id ? "chunk-row active" : "chunk-row"} key={chunk.id}>
                  <button type="button" onClick={() => setActiveId(chunk.id)}>
                    Chunk {chunkIndex}
                  </button>
                  <input
                    type="checkbox"
                    checked={selected}
                    onChange={() => toggleChunk(chunk.id)}
                    aria-label={`Select chunk ${chunkIndex}`}
                  />
                </div>
              );
            })}
          </div>
          {activeChunk ? (
            <div className="chunk-detail">
              <div className="chunk-detail-meta">
                <span>Chunk {locatorNumber(activeChunk.locator, "chunk_index", 1)}</span>
                <span>
                  chars {locatorNumber(activeChunk.locator, "char_start")}-
                  {locatorNumber(activeChunk.locator, "char_end")}
                </span>
              </div>
              <LinePreview text={activeChunk.text_content ?? ""} />
            </div>
          ) : null}
        </>
      ) : null}
    </section>
  );
}

function Toggle({
  label,
  checked,
  onChange
}: {
  label: string;
  checked: boolean;
  onChange: (checked: boolean) => void;
}) {
  return (
    <label className="toggle">
      <input type="checkbox" checked={checked} onChange={(event) => onChange(event.target.checked)} />
      <span>{labelFromKey(label)}</span>
    </label>
  );
}

function Rating({
  label,
  value,
  onChange
}: {
  label: string;
  value: number;
  onChange: (value: number) => void;
}) {
  return (
    <label className="rating">
      <span>{labelFromKey(label)}</span>
      <input
        type="range"
        min={1}
        max={5}
        value={value}
        onChange={(event) => onChange(Number(event.target.value))}
      />
      <strong>{value}</strong>
    </label>
  );
}

function AssetTriageForm({
  task,
  initialDecisions,
  onChange
}: {
  task: Task;
  initialDecisions: Decisions;
  onChange: (value: Decisions) => void;
}) {
  const payload = task.input_payload;
  const [sourceType, setSourceType] = useState(decisionString(initialDecisions, "source_type", payloadString(payload.source_type, "unknown")));
  const [importance, setImportance] = useState(decisionString(initialDecisions, "importance", "medium"));
  const [privacy, setPrivacy] = useState(decisionString(initialDecisions, "initial_privacy_level", "unreviewed"));
  const [processNext, setProcessNext] = useState(decisionString(initialDecisions, "process_next", "yes"));
  const [triageNotes, setTriageNotes] = useState(decisionString(initialDecisions, "notes"));

  useEffect(() => {
    onChange({
      source_type: sourceType,
      importance,
      initial_privacy_level: privacy,
      process_next: processNext,
      notes: triageNotes
    });
  }, [sourceType, importance, privacy, processNext, triageNotes, onChange]);

  return (
    <div className="form-grid">
      <Field label="Source type">
        <Select
          value={sourceType}
          onChange={setSourceType}
          options={["email", "journal", "memoir", "photo", "audio", "scan", "document", "unknown"]}
        />
      </Field>
      <Field label="Importance">
        <Select value={importance} onChange={setImportance} options={["low", "medium", "high", "sacred"]} />
      </Field>
      <Field label="Initial privacy">
        <Select value={privacy} onChange={setPrivacy} options={["unreviewed", "family_private", "sensitive", "sealed"]} />
      </Field>
      <Field label="Process next">
        <Select value={processNext} onChange={setProcessNext} options={["yes", "no", "later"]} />
      </Field>
      <Field label="Notes">
        <TextArea value={triageNotes} onChange={setTriageNotes} />
      </Field>
    </div>
  );
}

function PhotoContextForm({
  task,
  initialDecisions,
  onChange
}: {
  task: Task;
  initialDecisions: Decisions;
  onChange: (value: Decisions) => void;
}) {
  const payload = task.input_payload;
  const [visiblePeople, setVisiblePeople] = useState(
    decisionListText(initialDecisions, "visible_people", payloadArray(payload.machine_guess_people).join(", "))
  );
  const [absentPeople, setAbsentPeople] = useState(decisionListText(initialDecisions, "absent_but_relevant_people"));
  const [place, setPlace] = useState(decisionString(initialDecisions, "place", payloadString(payload.machine_guess_place, "unknown")));
  const [dateRange, setDateRange] = useState(decisionString(initialDecisions, "date_or_range", "unknown"));
  const [dateConfidence, setDateConfidence] = useState(decisionString(initialDecisions, "date_confidence", "unknown"));
  const [event, setEvent] = useState(decisionString(initialDecisions, "event", "unknown"));
  const [description, setDescription] = useState(decisionString(initialDecisions, "visual_description_correction"));
  const [invisibleContext, setInvisibleContext] = useState(decisionString(initialDecisions, "invisible_context_note"));
  const [memoryPotential, setMemoryPotential] = useState(decisionNumber(initialDecisions, "memory_potential", 4));
  const [privacySensitivity, setPrivacySensitivity] = useState(decisionNumber(initialDecisions, "privacy_sensitivity", 2));
  const [galleryEligibility, setGalleryEligibility] = useState(decisionString(initialDecisions, "gallery_eligibility", "family_private"));

  useEffect(() => {
    onChange({
      visible_people: parseList(visiblePeople),
      absent_but_relevant_people: parseList(absentPeople),
      place,
      date_or_range: dateRange,
      date_confidence: dateConfidence,
      event,
      visual_description_correction: description,
      invisible_context_note: invisibleContext,
      memory_potential: memoryPotential,
      privacy_sensitivity: privacySensitivity,
      gallery_eligibility: galleryEligibility,
      link_to_memory: "existing"
    });
  }, [
    absentPeople,
    dateConfidence,
    dateRange,
    description,
    event,
    galleryEligibility,
    invisibleContext,
    memoryPotential,
    onChange,
    place,
    privacySensitivity,
    visiblePeople
  ]);

  return (
    <div className="form-grid">
      <FormHint title="Photo context">
        Add the who, where, when, and the invisible context that a stranger would miss from the image alone.
      </FormHint>
      <Field label="Who is visible?">
        <input value={visiblePeople} onChange={(event) => setVisiblePeople(event.target.value)} />
      </Field>
      <Field label="Who matters but is not visible?">
        <input value={absentPeople} onChange={(event) => setAbsentPeople(event.target.value)} />
      </Field>
      <Field label="Where is this?">
        <input value={place} onChange={(event) => setPlace(event.target.value)} />
      </Field>
      <Field label="When is it from?">
        <input value={dateRange} onChange={(event) => setDateRange(event.target.value)} />
      </Field>
      <Field label="How sure is the date?">
        <Select value={dateConfidence} onChange={setDateConfidence} options={["exact", "year", "decade", "unknown"]} />
      </Field>
      <Field label="What event or moment is this?">
        <input value={event} onChange={(event) => setEvent(event.target.value)} />
      </Field>
      <Field label="What should the visual description say?">
        <TextArea value={description} onChange={setDescription} />
      </Field>
      <Field label="What context is not visible?">
        <TextArea rows={5} value={invisibleContext} onChange={setInvisibleContext} />
      </Field>
      <Rating label="Memory potential" value={memoryPotential} onChange={setMemoryPotential} />
      <Rating label="Privacy sensitivity" value={privacySensitivity} onChange={setPrivacySensitivity} />
      <Field label="Gallery eligibility">
        <Select value={galleryEligibility} onChange={setGalleryEligibility} options={["none", "family_private", "public_candidate"]} />
      </Field>
    </div>
  );
}

function TextSegmentReviewForm({
  task,
  initialDecisions,
  onChange
}: {
  task: Task;
  initialDecisions: Decisions;
  onChange: (value: Decisions) => void;
}) {
  const payload = task.input_payload;
  const initialCreatorIds = Array.isArray(initialDecisions.creator_entity_ids)
    ? initialDecisions.creator_entity_ids.map(String)
    : [];
  const initialCreatorName = decisionString(initialDecisions, "creator_name");
  const [boundaryGood, setBoundaryGood] = useState(decisionString(initialDecisions, "segment_boundary_good", "yes"));
  const [title, setTitle] = useState(decisionString(initialDecisions, "segment_title", payloadString(payload.segment_title, "")));
  const [sourceGenre, setSourceGenre] = useState(decisionString(initialDecisions, "source_genre", "document"));
  const [authorship, setAuthorship] = useState(decisionString(initialDecisions, "authorship", "unknown"));
  const [entities, setEntities] = useState<Entity[]>([]);
  const [creatorSelection, setCreatorSelection] = useState(initialCreatorIds[0] ?? (initialCreatorName ? NEW_PERSON_VALUE : ""));
  const [newPersonName, setNewPersonName] = useState(initialCreatorName);
  const [newPersonRelationshipToCharles, setNewPersonRelationshipToCharles] = useState(
    decisionString(initialDecisions, "creator_relationship_to_charles")
  );
  const [newPersonRelationshipToAdam, setNewPersonRelationshipToAdam] = useState(
    decisionString(initialDecisions, "creator_relationship_to_adam")
  );
  const [newPersonDescription, setNewPersonDescription] = useState("");
  const [newPersonConfidence, setNewPersonConfidence] = useState(decisionString(initialDecisions, "creator_confidence", "medium"));
  const [entityError, setEntityError] = useState("");
  const [entityBusy, setEntityBusy] = useState(false);
  const [authorshipNote, setAuthorshipNote] = useState(decisionString(initialDecisions, "authorship_note"));
  const [fictionalityStatus, setFictionalityStatus] = useState(decisionString(initialDecisions, "fictionality_status", "unknown"));
  const [truthStatus, setTruthStatus] = useState(decisionString(initialDecisions, "truth_status", "archival_source"));
  const [voicePresence, setVoicePresence] = useState(decisionString(initialDecisions, "voice_presence", "unknown"));
  const [people, setPeople] = useState(decisionListText(initialDecisions, "people"));
  const [places, setPlaces] = useState(decisionListText(initialDecisions, "places"));
  const [dateRange, setDateRange] = useState(decisionString(initialDecisions, "date_or_range", "unknown"));
  const [adamContextNote, setAdamContextNote] = useState(decisionString(initialDecisions, "adam_context_note"));
  const [promptPairPotential, setPromptPairPotential] = useState(decisionString(initialDecisions, "prompt_pair_potential", "medium"));
  const [voiceContext, setVoiceContext] = useState(decisionBoolean(initialDecisions, "usable_for_voice_context", true));
  const [groundedGeneration, setGroundedGeneration] = useState(
    decisionBoolean(initialDecisions, "usable_for_grounded_generation", true)
  );
  const [sft, setSft] = useState(decisionBoolean(initialDecisions, "usable_for_sft", false));
  const [dpo, setDpo] = useState(decisionBoolean(initialDecisions, "usable_for_dpo", false));
  const [boundaryRationale, setBoundaryRationale] = useState(decisionString(initialDecisions, "boundary_rationale"));
  const selectedCreator = entities.find((entity) => entity.id === creatorSelection);
  const creatingPerson = creatorSelection === NEW_PERSON_VALUE;
  const creatorName = selectedCreator?.canonical_name || (creatingPerson ? newPersonName.trim() : "");
  const creatorRelationshipToCharles =
    selectedCreator?.relationship_to_charles || (creatingPerson ? newPersonRelationshipToCharles.trim() : "");
  const creatorRelationshipToAdam =
    selectedCreator?.relationship_to_adam || (creatingPerson ? newPersonRelationshipToAdam.trim() : "");

  useEffect(() => {
    let cancelled = false;
    getEntities("person")
      .then((nextEntities) => {
        if (!cancelled) {
          setEntities(nextEntities);
        }
      })
      .catch((caught: unknown) => {
        if (!cancelled) {
          setEntityError(caught instanceof Error ? caught.message : "Unable to load people.");
        }
      });

    return () => {
      cancelled = true;
    };
  }, [task.id]);

  useEffect(() => {
    onChange({
      segment_boundary_good: boundaryGood,
      segment_title: title,
      source_genre: sourceGenre,
      authorship,
      creator_entity_ids: selectedCreator ? [selectedCreator.id] : [],
      creator_name: creatorName,
      creator_relationship_to_charles: creatorRelationshipToCharles,
      creator_relationship_to_adam: creatorRelationshipToAdam,
      creator_confidence: creatingPerson ? newPersonConfidence : selectedCreator?.confidence,
      authorship_note: authorshipNote,
      fictionality_status: fictionalityStatus,
      people: parseList(people),
      places: parseList(places),
      date_or_range: dateRange,
      truth_status: truthStatus,
      voice_presence: voicePresence,
      adam_context_note: adamContextNote,
      prompt_pair_potential: promptPairPotential,
      usable_for_voice_context: voiceContext ? "yes" : "no",
      usable_for_grounded_generation: groundedGeneration ? "yes" : "no",
      usable_for_sft: sft ? "yes" : "no",
      usable_for_dpo: dpo ? "yes" : "no",
      boundary_rationale: boundaryRationale
    });
  }, [
    adamContextNote,
    authorship,
    authorshipNote,
    boundaryGood,
    boundaryRationale,
    creatorName,
    creatorSelection,
    creatorRelationshipToAdam,
    creatorRelationshipToCharles,
    creatingPerson,
    dateRange,
    dpo,
    fictionalityStatus,
    groundedGeneration,
    onChange,
    people,
    places,
    promptPairPotential,
    selectedCreator?.confidence,
    newPersonConfidence,
    sft,
    sourceGenre,
    title,
    truthStatus,
    voiceContext,
    voicePresence
  ]);

  async function handleCreatePerson() {
    const canonicalName = newPersonName.trim();
    if (!canonicalName) {
      setEntityError("Add a name before creating a person.");
      return;
    }
    setEntityBusy(true);
    setEntityError("");
    try {
      const entity = await createEntity({
        entity_type: "person",
        canonical_name: canonicalName,
        description: newPersonDescription.trim() || null,
        relationship_to_charles: newPersonRelationshipToCharles.trim() || null,
        relationship_to_adam: newPersonRelationshipToAdam.trim() || null,
        confidence: newPersonConfidence
      });
      setEntities((current) => [...current, entity].sort((left, right) => left.canonical_name.localeCompare(right.canonical_name)));
      setCreatorSelection(entity.id);
    } catch (caught) {
      setEntityError(caught instanceof Error ? caught.message : "Unable to create person.");
    } finally {
      setEntityBusy(false);
    }
  }

  return (
    <div className="form-grid">
      <FormHint title="Raw source material">
        Annotate what it is, who made it, what kind of truth it carries, who/where/when it is about, why Adam thinks it matters, and how safely it can be used.
      </FormHint>
      <Field label="Is this segment boundary good?" hint="Use no if this chunk should be split, merged, or excluded before downstream use.">
        <Select value={boundaryGood} onChange={setBoundaryGood} options={["yes", "no"]} />
      </Field>
      <Field label="What should we call this segment?" hint="A short human-readable title for queue cards and retrieval.">
        <input value={title} onChange={(event) => setTitle(event.target.value)} />
      </Field>
      <Field label="What kind of document is it?" hint="The backend stores this as source_genre.">
        <Select
          value={sourceGenre}
          onChange={setSourceGenre}
          options={[
            "document",
            "letter",
            "novel_draft",
            "essay",
            "memoir_fragment",
            "notes",
            "article_clipping",
            "legal_or_financial",
            "unknown"
          ]}
        />
      </Field>
      <Field label="Who made it?" hint="Select a person record, or add one when the creator is not in the list yet.">
        <select value={creatorSelection} onChange={(event) => setCreatorSelection(event.target.value)}>
          <option value="">Unknown or not yet defined</option>
          {entities.map((entity) => (
            <option key={entity.id} value={entity.id}>
              {entityOptionLabel(entity)}
            </option>
          ))}
          <option value={NEW_PERSON_VALUE}>Add a person...</option>
        </select>
      </Field>
      <Field label="How should authorship be categorized?" hint="This coarse value helps filtering; the person record keeps the actual name and relationship.">
        <Select value={authorship} onChange={setAuthorship} options={["charles", "adam", "third_party", "mixed", "unknown"]} />
      </Field>
      {selectedCreator ? (
        <div className="entity-context">
          <strong>{selectedCreator.canonical_name}</strong>
          <span>
            Charles: {selectedCreator.relationship_to_charles || "unknown"} / Adam:{" "}
            {selectedCreator.relationship_to_adam || "unknown"}
          </span>
          {selectedCreator.description ? <p>{selectedCreator.description}</p> : null}
        </div>
      ) : null}
      {creatingPerson ? (
        <div className="person-create-panel">
          <Field label="Person name">
            <input value={newPersonName} onChange={(event) => setNewPersonName(event.target.value)} />
          </Field>
          <Field label="Relationship to Charles">
            <input
              value={newPersonRelationshipToCharles}
              onChange={(event) => setNewPersonRelationshipToCharles(event.target.value)}
            />
          </Field>
          <Field label="Relationship to Adam">
            <input
              value={newPersonRelationshipToAdam}
              onChange={(event) => setNewPersonRelationshipToAdam(event.target.value)}
            />
          </Field>
          <Field label="Confidence">
            <Select value={newPersonConfidence} onChange={setNewPersonConfidence} options={["high", "medium", "low"]} />
          </Field>
          <Field label="Who are they?">
            <TextArea rows={3} value={newPersonDescription} onChange={setNewPersonDescription} />
          </Field>
          <div className="inline-actions">
            <button type="button" onClick={handleCreatePerson} disabled={entityBusy}>
              {entityBusy ? "Adding" : "Add person"}
            </button>
            {entityError ? <span>{entityError}</span> : null}
          </div>
        </div>
      ) : entityError ? (
        <p className="quiet entity-error">{entityError}</p>
      ) : null}
      <Field label="What should we remember about authorship?" hint="For example: Cathryn wrote this poem; Charles read it, saved it, or responded to it.">
        <TextArea rows={3} value={authorshipNote} onChange={setAuthorshipNote} />
      </Field>
      <Field label="Is it factual, fictional, or mixed?" hint="This separates a novel draft from a letter, memory, or factual source.">
        <Select
          value={fictionalityStatus}
          onChange={setFictionalityStatus}
          options={["factual", "fiction", "fictionalized_from_life", "mixed", "unknown"]}
        />
      </Field>
      <Field label="Where does its truth come from?" hint="Archival source, Adam memory, inference, generated text, or reconstruction.">
        <Select
          value={truthStatus}
          onChange={setTruthStatus}
          options={[
            "archival_source",
            "spoken_source",
            "adam_memory",
            "adam_inference",
            "system_inference",
            "model_generated",
            "adam_expert_reconstruction",
            "interpretive_synthesis"
          ]}
        />
      </Field>
      <Field label="Is Charles's voice actually present?" hint="Primary means this is directly useful as Charles voice evidence.">
        <Select
          value={voicePresence}
          onChange={setVoicePresence}
          options={["primary", "partial", "context_only", "absent", "unknown"]}
        />
      </Field>
      <Field label="Who is it about?" hint="Comma-separated people or entities.">
        <input value={people} onChange={(event) => setPeople(event.target.value)} />
      </Field>
      <Field label="Where is it about?" hint="Comma-separated places, if known.">
        <input value={places} onChange={(event) => setPlaces(event.target.value)} />
      </Field>
      <Field label="When is it from or about?" hint="Use a year, date range, or unknown.">
        <input value={dateRange} onChange={(event) => setDateRange(event.target.value)} />
      </Field>
      <Field label="Why does Adam think it matters?" hint="This is retrieval/context metadata, not training target text by itself.">
        <TextArea rows={5} value={adamContextNote} onChange={setAdamContextNote} />
      </Field>
      <Field label="Could this become prompt/response material?" hint="High/medium can spawn a grounded prompt-pair candidate task.">
        <Select value={promptPairPotential} onChange={setPromptPairPotential} options={["high", "medium", "low", "none"]} />
      </Field>
      <FormHint title="Downstream use">
        Decide whether this source can be searched, used as voice context, used to ground generated responses, or exported into training pairs.
      </FormHint>
      <div className="toggle-grid">
        <Toggle label="usable_for_voice_context" checked={voiceContext} onChange={setVoiceContext} />
        <Toggle label="usable_for_grounded_generation" checked={groundedGeneration} onChange={setGroundedGeneration} />
        <Toggle label="usable_for_sft" checked={sft} onChange={setSft} />
        <Toggle label="usable_for_dpo" checked={dpo} onChange={setDpo} />
      </div>
      <Field label="Why is this boundary/use decision OK?" hint="Note privacy, sensitivity, uncertainty, or why this should stay local.">
        <TextArea value={boundaryRationale} onChange={setBoundaryRationale} />
      </Field>
    </div>
  );
}

function BoundaryReviewForm({
  initialDecisions,
  onChange
}: {
  initialDecisions: Decisions;
  onChange: (value: Decisions) => void;
}) {
  const [privacyLevel, setPrivacyLevel] = useState(decisionString(initialDecisions, "privacy_level", "family_private"));
  const [flags, setFlags] = useState({
    searchable: decisionBoolean(initialDecisions, "searchable", true),
    retrievable_in_chat: decisionBoolean(initialDecisions, "retrievable_in_chat", true),
    quotable: decisionBoolean(initialDecisions, "quotable", false),
    summarizable: decisionBoolean(initialDecisions, "summarizable", true),
    usable_for_voice_context: decisionBoolean(initialDecisions, "usable_for_voice_context", true),
    usable_for_sft: decisionBoolean(initialDecisions, "usable_for_sft", false),
    usable_for_dpo: decisionBoolean(initialDecisions, "usable_for_dpo", false),
    usable_for_eval: decisionBoolean(initialDecisions, "usable_for_eval", true),
    usable_for_gallery_public: decisionBoolean(initialDecisions, "usable_for_gallery_public", false),
    usable_for_gallery_family: decisionBoolean(initialDecisions, "usable_for_gallery_family", true),
    usable_for_simulation: decisionBoolean(initialDecisions, "usable_for_simulation", true),
    contains_living_person_sensitive_material: decisionBoolean(
      initialDecisions,
      "contains_living_person_sensitive_material",
      false
    ),
    redaction_required: decisionBoolean(initialDecisions, "redaction_required", false)
  });
  const [notes, setNotes] = useState(decisionString(initialDecisions, "notes"));

  useEffect(() => {
    onChange({ privacy_level: privacyLevel, ...flags, notes });
  }, [flags, notes, onChange, privacyLevel]);

  return (
    <div className="form-grid">
      <FormHint title="Boundary decision">
        Decide whether this item can be searched, quoted, used for voice, used for training, or kept out of downstream flows.
      </FormHint>
      <Field label="How private is this?">
        <Select
          value={privacyLevel}
          onChange={setPrivacyLevel}
          options={["public_safe", "family_private", "sensitive_living_people", "intimate", "sealed"]}
        />
      </Field>
      <div className="toggle-grid">
        {Object.entries(flags).map(([key, checked]) => (
          <Toggle
            key={key}
            label={key}
            checked={checked}
            onChange={(value) => setFlags((current) => ({ ...current, [key]: value }))}
          />
        ))}
      </div>
      <Field label="Why is this boundary decision right?">
        <TextArea value={notes} onChange={setNotes} />
      </Field>
    </div>
  );
}

function EmailVoiceSampleForm({
  task,
  initialDecisions,
  onChange
}: {
  task: Task;
  initialDecisions: Decisions;
  onChange: (value: Decisions) => void;
}) {
  const headers =
    task.input_payload.email_headers && typeof task.input_payload.email_headers === "object"
      ? (task.input_payload.email_headers as Record<string, unknown>)
      : {};
  const [voiceMode, setVoiceMode] = useState(decisionString(initialDecisions, "voice_mode", "father_to_adam"));
  const [charlesVoicePresence, setCharlesVoicePresence] = useState(decisionString(initialDecisions, "charles_voice_presence", "unknown"));
  const [charlesRole, setCharlesRole] = useState(decisionString(initialDecisions, "charles_email_role", "unknown"));
  const [otherVoices, setOtherVoices] = useState(decisionListText(initialDecisions, "other_voice_roles", "Adam, other correspondents"));
  const [contextUse, setContextUse] = useState(decisionString(initialDecisions, "context_use", "conversation_context"));
  const [quotedMaterial, setQuotedMaterial] = useState(decisionBoolean(initialDecisions, "quoted_or_forwarded_material_present", true));
  const [authenticity, setAuthenticity] = useState(decisionNumber(initialDecisions, "authenticity_value", 4));
  const [density, setDensity] = useState(decisionNumber(initialDecisions, "voice_density", 4));
  const [phrases, setPhrases] = useState(decisionListText(initialDecisions, "recurring_phrases", "call when you get in"));
  const [voiceContext, setVoiceContext] = useState(decisionBoolean(initialDecisions, "usable_for_voice_context", true));
  const [sft, setSft] = useState(decisionBoolean(initialDecisions, "usable_for_sft", false));
  const [dpo, setDpo] = useState(decisionBoolean(initialDecisions, "usable_for_dpo", false));
  const [why, setWhy] = useState(decisionString(initialDecisions, "why_it_matters"));
  const [boundaryRationale, setBoundaryRationale] = useState(decisionString(initialDecisions, "boundary_rationale"));

  useEffect(() => {
    onChange({
      voice_mode: voiceMode,
      charles_voice_presence: charlesVoicePresence,
      charles_email_role: charlesRole,
      other_voice_roles: parseList(otherVoices),
      context_use: contextUse,
      quoted_or_forwarded_material_present: quotedMaterial ? "yes" : "no",
      email_subject: payloadString(headers.subject),
      email_from: payloadString(headers.from),
      email_to: payloadString(headers.to),
      email_date: payloadString(headers.date),
      authenticity_value: authenticity,
      voice_density: density,
      recurring_phrases: parseList(phrases),
      usable_for_voice_context: voiceContext ? "yes" : "no",
      usable_for_sft: sft ? "yes" : "no",
      usable_for_dpo: dpo ? "yes" : "no",
      why_it_matters: why,
      boundary_rationale: boundaryRationale
    });
  }, [
    authenticity,
    boundaryRationale,
    charlesRole,
    charlesVoicePresence,
    contextUse,
    density,
    dpo,
    headers.date,
    headers.from,
    headers.subject,
    headers.to,
    onChange,
    otherVoices,
    phrases,
    quotedMaterial,
    sft,
    voiceContext,
    voiceMode,
    why
  ]);

  return (
    <div className="form-grid">
      <FormHint title="Email voice sample">
        Emails can contain multiple voices. Mark whether Charles is actually speaking, who else is present, and whether the thread is voice material, context, or something to exclude.
      </FormHint>
      <Field label="What mode is Charles speaking in?" hint="Use the closest voice/context mode, even if this is only partial evidence.">
        <Select
          value={voiceMode}
          onChange={setVoiceMode}
          options={["casual_email", "father_to_adam", "argument", "comic", "grief", "logistics", "other"]}
        />
      </Field>
      <Field label="Is Charles's voice actually present?" hint="Primary for Charles-authored text; context only if others are speaking about him.">
        <Select
          value={charlesVoicePresence}
          onChange={setCharlesVoicePresence}
          options={["primary", "partial", "context_only", "absent", "unknown"]}
        />
      </Field>
      <Field label="Where does Charles appear in the thread?" hint="Sender, recipient, quoted author, mentioned person, mixed, or unknown.">
        <Select
          value={charlesRole}
          onChange={setCharlesRole}
          options={["sender", "recipient", "quoted_author", "mentioned", "mixed", "unknown"]}
        />
      </Field>
      <Field label="Who else is speaking?" hint="Comma-separated people or roles in the email thread.">
        <input value={otherVoices} onChange={(event) => setOtherVoices(event.target.value)} />
      </Field>
      <Field label="How should this email be used?" hint="Voice sample, conversation context, factual context, prompt/response context, or exclude.">
        <Select
          value={contextUse}
          onChange={setContextUse}
          options={["charles_voice_sample", "conversation_context", "factual_context", "prompt_response_context", "exclude"]}
        />
      </Field>
      <Rating label="Authenticity" value={authenticity} onChange={setAuthenticity} />
      <Rating label="Voice density" value={density} onChange={setDensity} />
      <Field label="Any phrases worth preserving?" hint="Comma-separated turns of phrase, closings, habits, or verbal signatures.">
        <input value={phrases} onChange={(event) => setPhrases(event.target.value)} />
      </Field>
      <FormHint title="Downstream use">
        Decide whether this email can be used as voice context or training material. Quoted/forwarded material marks multi-voice contamination.
      </FormHint>
      <div className="toggle-grid">
        <Toggle label="quoted_or_forwarded_material" checked={quotedMaterial} onChange={setQuotedMaterial} />
        <Toggle label="usable_for_voice_context" checked={voiceContext} onChange={setVoiceContext} />
        <Toggle label="usable_for_sft" checked={sft} onChange={setSft} />
        <Toggle label="usable_for_dpo" checked={dpo} onChange={setDpo} />
      </div>
      <Field label="Why does Adam think it matters?" hint="Context value, voice value, or why the thread should be handled carefully.">
        <TextArea value={why} onChange={setWhy} />
      </Field>
      <Field label="Why is this boundary/use decision OK?">
        <TextArea value={boundaryRationale} onChange={setBoundaryRationale} />
      </Field>
    </div>
  );
}

function GoldVoiceEditForm({
  task,
  initialDecisions,
  onChange
}: {
  task: Task;
  initialDecisions: Decisions;
  onChange: (value: Decisions) => void;
}) {
  const payload = task.input_payload;
  const initialRatings =
    initialDecisions.ratings && typeof initialDecisions.ratings === "object"
      ? (initialDecisions.ratings as Record<string, unknown>)
      : {};
  const defaultRatings = { ...((payload.ratings ?? {}) as Record<string, unknown>), ...initialRatings };
  const [prompt, setPrompt] = useState(decisionString(initialDecisions, "prompt", payloadString(payload.prompt, "")));
  const [voiceMode, setVoiceMode] = useState(decisionString(initialDecisions, "voice_mode", payloadString(payload.voice_mode, "father_to_adam")));
  const [truthMode, setTruthMode] = useState(
    decisionString(initialDecisions, "truth_mode", payloadString(payload.truth_mode, "generative_reconstruction"))
  );
  const [modelDraft, setModelDraft] = useState(decisionString(initialDecisions, "model_draft", payloadString(payload.model_draft, "")));
  const [goldEdit, setGoldEdit] = useState(decisionString(initialDecisions, "adam_gold_edit", payloadString(payload.adam_gold_edit, "")));
  const [authenticityRationale, setAuthenticityRationale] = useState(decisionString(initialDecisions, "authenticity_rationale"));
  const [failureModes, setFailureModes] = useState(
    decisionListText(initialDecisions, "failure_modes", payloadArray(payload.failure_modes).join(", ") || "too_generic, too_therapy_like")
  );
  const [ratings, setRatings] = useState({
    voice_fidelity: payloadNumber(defaultRatings.voice_fidelity, 5),
    mode_match: payloadNumber(defaultRatings.mode_match, 5),
    emotional_truth: payloadNumber(defaultRatings.emotional_truth, 5),
    concrete_detail: payloadNumber(defaultRatings.concrete_detail, 5),
    restraint: payloadNumber(defaultRatings.restraint, 5),
    non_parody: payloadNumber(defaultRatings.non_parody, 5),
    grounding: payloadNumber(defaultRatings.grounding, 5)
  });
  const initialExportFlags =
    initialDecisions.export_flags && typeof initialDecisions.export_flags === "object"
      ? (initialDecisions.export_flags as Record<string, unknown>)
      : {};
  const [exportFlags, setExportFlags] = useState({
    sft: typeof initialExportFlags.sft === "boolean" ? initialExportFlags.sft : true,
    dpo: typeof initialExportFlags.dpo === "boolean" ? initialExportFlags.dpo : true,
    eval: typeof initialExportFlags.eval === "boolean" ? initialExportFlags.eval : true,
    anti_pattern: typeof initialExportFlags.anti_pattern === "boolean" ? initialExportFlags.anti_pattern : true,
    style_rule: typeof initialExportFlags.style_rule === "boolean" ? initialExportFlags.style_rule : true
  });

  useEffect(() => {
    onChange({
      prompt,
      voice_mode: voiceMode,
      truth_mode: truthMode,
      context_pack_id: payloadString(payload.context_pack_id),
      prompt_spec_id: payloadString(payload.prompt_spec_id),
      generation_id: payloadString(payload.generation_id),
      model_draft: modelDraft,
      adam_gold_edit: goldEdit,
      authenticity_rationale: authenticityRationale,
      ratings,
      failure_modes: parseList(failureModes),
      export_flags: exportFlags
    });
  }, [authenticityRationale, exportFlags, failureModes, goldEdit, modelDraft, onChange, payload.context_pack_id, payload.generation_id, payload.prompt_spec_id, prompt, ratings, truthMode, voiceMode]);

  return (
    <div className="gold-grid">
      <FormHint title="Generated/model output">
        Compare the model draft against Adam's preferred version: what the model got wrong, what Adam changed, why the preferred version is more authentic, and which failure mode the rejected version shows.
      </FormHint>
      <Field label="What was the model asked to do?">
        <TextArea value={prompt} onChange={setPrompt} rows={3} />
      </Field>
      <Field label="Which voice mode was requested?">
        <Select
          value={voiceMode}
          onChange={setVoiceMode}
          options={[
            "casual_email",
            "father_to_adam",
            "memoir_scene",
            "argument",
            "comic_observation",
            "grief_memory",
            "photography_reflection",
            "philosophical_fragment",
            "spoken_interview",
            "logistical_note"
          ]}
        />
      </Field>
      <Field label="What kind of reconstruction is this?">
        <Select value={truthMode} onChange={setTruthMode} options={["generative_reconstruction", "simulation", "interpretive"]} />
      </Field>
      <Field label="What did the model write?" hint="This becomes the rejected side if exported as DPO.">
        <TextArea value={modelDraft} onChange={setModelDraft} rows={8} />
      </Field>
      <Field label="What did Adam change it into?" hint="This is the preferred version and the SFT assistant target.">
        <TextArea value={goldEdit} onChange={setGoldEdit} rows={10} />
      </Field>
      <Field label="Why is the preferred version more authentic?" hint="Name the specific voice, restraint, detail, or truth difference.">
        <TextArea value={authenticityRationale} onChange={setAuthenticityRationale} rows={4} />
      </Field>
      <div className="rating-panel">
        {Object.entries(ratings).map(([key, value]) => (
          <Rating
            key={key}
            label={key}
            value={value}
            onChange={(next) => setRatings((current) => ({ ...current, [key]: next }))}
          />
        ))}
      </div>
      <Field label="What failure mode does the rejected version show?" hint="Comma-separated labels such as too generic, too therapy-like, overwritten emotion.">
        <input value={failureModes} onChange={(event) => setFailureModes(event.target.value)} />
      </Field>
      <FormHint title="Export artifacts">
        Choose which downstream records this edit should create: SFT candidate, DPO pair, eval case, anti-pattern, or style rule.
      </FormHint>
      <div className="toggle-grid">
        {Object.entries(exportFlags).map(([key, checked]) => (
          <Toggle
            key={key}
            label={key}
            checked={checked}
            onChange={(value) => setExportFlags((current) => ({ ...current, [key]: value }))}
          />
        ))}
      </div>
    </div>
  );
}

export function TaskWorkbench({
  task,
  queuePosition,
  queueTotal,
  qualityScore,
  completedThisSession,
  memoriesCount,
  goldExamplesCount,
  assetsCount,
  onSubmit,
  onSkip,
  onFlag,
  onPrevious,
  onNext
}: TaskWorkbenchProps) {
  const [draftLoaded, setDraftLoaded] = useState(false);
  const [draftDecisions, setDraftDecisions] = useState<Decisions>({});
  const [inspectorTab, setInspectorTab] = useState<"metadata" | "annotations" | "history">("metadata");
  const [inspectorWidth, setInspectorWidth] = useState(440);
  const [reviewStatus, setReviewStatus] = useState("needs_review");
  const [decisions, setDecisions] = useState<Decisions>({});
  const [chunkSelection, setChunkSelection] = useState<ChunkSelection>({
    chunk_scope: "preview_only",
    selected_chunk_ids: [],
    selected_chunk_count: 0
  });
  const [activeChunk, setActiveChunk] = useState<Segment | undefined>();
  const [textEdits, setTextEdits] = useState<Decisions>({});
  const [notes, setNotes] = useState("");
  const [draftStatus, setDraftStatus] = useState("Loading draft");
  const [draftUpdatedAt, setDraftUpdatedAt] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const lastSavedDraftRef = useRef("");
  const autosaveReadyRef = useRef(false);
  const descriptor = taskLabels[task.task_type] ?? { label: task.task_type, icon: <Gauge size={18} /> };

  useEffect(() => {
    let cancelled = false;
    setDraftLoaded(false);
    setDraftDecisions({});
    setDecisions({});
    setNotes("");
    setChunkSelection({ chunk_scope: "preview_only", selected_chunk_ids: [], selected_chunk_count: 0 });
    setActiveChunk(undefined);
    setTextEdits({});
    setDraftStatus("Loading draft");
    setDraftUpdatedAt(null);
    lastSavedDraftRef.current = "";
    autosaveReadyRef.current = false;

    getTaskDraft(task.id)
      .then((draft) => {
        if (cancelled) {
          return;
        }
        const nextDecisions = draft?.decisions ?? {};
        const selectedChunkIds = Array.isArray(nextDecisions.selected_chunk_ids)
          ? nextDecisions.selected_chunk_ids.map(String)
          : [];
        const nextSelection = {
          chunk_scope: decisionString(nextDecisions, "chunk_scope", selectedChunkIds.length > 0 ? "selected_chunks" : "preview_only"),
          selected_chunk_ids: selectedChunkIds,
          active_chunk_id: decisionString(nextDecisions, "active_chunk_id") || undefined,
          selected_chunk_count: selectedChunkIds.length
        };
        setDraftDecisions(nextDecisions);
        setDecisions(nextDecisions);
        setNotes(draft?.notes ?? "");
        setChunkSelection(nextSelection);
        setDraftUpdatedAt(draft?.updated_at ?? null);
        setDraftStatus(draft ? "Draft restored" : "No draft yet");
        lastSavedDraftRef.current = JSON.stringify({ decisions: { ...nextDecisions, ...nextSelection }, notes: draft?.notes ?? "" });
      })
      .catch((caught: unknown) => {
        if (!cancelled) {
          setDraftStatus(caught instanceof Error ? `Draft load failed: ${caught.message}` : "Draft load failed");
        }
      })
      .finally(() => {
        if (!cancelled) {
          setDraftLoaded(true);
        }
      });

    return () => {
      cancelled = true;
    };
  }, [task.id]);

  const autosaveDecisions = useMemo(
    () => ({ ...decisions, ...chunkSelection, ...textEdits }),
    [chunkSelection, decisions, textEdits]
  );

  useEffect(() => {
    if (!draftLoaded || busy) {
      return;
    }
    const serialized = JSON.stringify({ decisions: autosaveDecisions, notes });
    if (!autosaveReadyRef.current) {
      autosaveReadyRef.current = true;
      lastSavedDraftRef.current = serialized;
      return;
    }
    if (serialized === lastSavedDraftRef.current) {
      return;
    }

    setDraftStatus("Saving draft");
    const timeout = window.setTimeout(() => {
      saveTaskDraft(task.id, autosaveDecisions, notes)
        .then((draft) => {
          lastSavedDraftRef.current = serialized;
          setDraftUpdatedAt(draft.updated_at);
          setDraftStatus("Draft saved");
        })
        .catch((caught: unknown) => {
          setDraftStatus(caught instanceof Error ? `Draft save failed: ${caught.message}` : "Draft save failed");
        });
    }, 1000);

    return () => {
      window.clearTimeout(timeout);
    };
  }, [autosaveDecisions, busy, draftLoaded, notes, task.id]);

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    try {
      await onSubmit(autosaveDecisions, notes);
    } finally {
      setBusy(false);
    }
  }

  const handleChunkChange = useCallback((selection: ChunkSelection, chunk?: Segment) => {
    setChunkSelection((current) => (sameChunkSelection(current, selection) ? current : selection));
    setActiveChunk((current) => (current?.id === chunk?.id ? current : chunk));
  }, []);

  const handleTextEditChange = useCallback((value: Decisions) => {
    setTextEdits((current) => (sameDecisionRecord(current, value) ? current : value));
  }, []);

  const handleDecisionChange = useCallback((value: Decisions) => {
    setDecisions((current) => (sameDecisionRecord(current, value) ? current : value));
  }, []);

  const resizeInspector = useCallback((nextWidth: number) => {
    setInspectorWidth(clamp(nextWidth, inspectorBounds.min, inspectorBounds.max));
  }, []);

  function startInspectorResize(event: React.PointerEvent<HTMLDivElement>) {
    event.preventDefault();
    const startX = event.clientX;
    const startWidth = inspectorWidth;
    document.body.classList.add("is-column-resizing");

    function handleMove(moveEvent: PointerEvent) {
      resizeInspector(startWidth - (moveEvent.clientX - startX));
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

  function handleInspectorResizeKey(event: React.KeyboardEvent<HTMLDivElement>) {
    if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") {
      return;
    }
    event.preventDefault();
    resizeInspector(inspectorWidth + (event.key === "ArrowLeft" ? INSPECTOR_RESIZE_STEP : -INSPECTOR_RESIZE_STEP));
  }

  const initialChunkSelection = useMemo<ChunkSelection>(() => {
    const selectedChunkIds = Array.isArray(draftDecisions.selected_chunk_ids)
      ? draftDecisions.selected_chunk_ids.map(String)
      : [];
    return {
      chunk_scope: decisionString(draftDecisions, "chunk_scope", selectedChunkIds.length > 0 ? "selected_chunks" : "preview_only"),
      selected_chunk_ids: selectedChunkIds,
      active_chunk_id: decisionString(draftDecisions, "active_chunk_id") || undefined,
      selected_chunk_count: selectedChunkIds.length
    };
  }, [draftDecisions]);

  if (!draftLoaded) {
    return (
      <div className="workbench loading-workbench">
        <Gauge size={18} />
        <span>{draftStatus}</span>
      </div>
    );
  }

  const form = (() => {
    switch (task.task_type) {
      case "asset_triage":
        return <AssetTriageForm task={task} initialDecisions={draftDecisions} onChange={handleDecisionChange} />;
      case "photo_context":
        return <PhotoContextForm task={task} initialDecisions={draftDecisions} onChange={handleDecisionChange} />;
      case "text_segment_review":
        return <TextSegmentReviewForm task={task} initialDecisions={draftDecisions} onChange={handleDecisionChange} />;
      case "boundary_review":
        return <BoundaryReviewForm initialDecisions={draftDecisions} onChange={handleDecisionChange} />;
      case "email_voice_sample":
        return <EmailVoiceSampleForm task={task} initialDecisions={draftDecisions} onChange={handleDecisionChange} />;
      case "gold_voice_edit":
        return <GoldVoiceEditForm task={task} initialDecisions={draftDecisions} onChange={handleDecisionChange} />;
      default:
        return (
          <Field label="Decision payload">
            <TextArea
              value={JSON.stringify(decisions, null, 2)}
              onChange={(value) => {
                try {
                  setDecisions(JSON.parse(value) as Decisions);
                } catch {
                  setDecisions({ raw: value });
                }
              }}
              rows={10}
            />
          </Field>
        );
    }
  })();
  const taskSource = payloadString(task.input_payload.source_filename) || payloadString(task.input_payload.asset_title) || task.target_id;

  return (
    <form className="workbench" onSubmit={handleSubmit}>
      <header className="workbench-header">
        <div>
          <div className="task-type">
            {descriptor.icon}
            <span>{descriptor.label}</span>
          </div>
          <h2>{taskDisplayTitle(task)}</h2>
        </div>
        <div className="task-meta">
          <div className="quality-score">
            <strong>{qualityScore}</strong>
            <span>Quality score</span>
          </div>
          <select value={reviewStatus} onChange={(event) => setReviewStatus(event.target.value)} aria-label="Review status">
            <option value="needs_review">Needs Review</option>
            <option value="needs_context">Needs Context</option>
            <option value="draft">Draft</option>
            <option value="approved">Approved</option>
            <option value="blocked">Blocked</option>
          </select>
          <div className="queue-stepper" aria-label="Queue position">
            <button type="button" onClick={onPrevious} disabled={queuePosition <= 1} aria-label="Previous task">
              <ChevronLeft size={16} />
            </button>
            <span>
              {queuePosition} / {queueTotal}
            </span>
            <button type="button" onClick={onNext} disabled={queuePosition >= queueTotal} aria-label="Next task">
              <ChevronRight size={16} />
            </button>
          </div>
        </div>
      </header>

      <div
        className="review-grid"
        style={{ "--inspector-width": `${inspectorWidth}px` } as React.CSSProperties}
      >
        <section className="review-canvas" aria-label="Source and derived review surface">
          <SourcePreview task={task} />
          <ChunkBrowser task={task} initialSelection={initialChunkSelection} onChange={handleChunkChange} />
          <EditableExtraction
            task={task}
            activeChunk={activeChunk}
            initialCleanedText={decisionString(draftDecisions, "cleaned_text")}
            onChange={handleTextEditChange}
          />
        </section>

        <div
          className="column-resizer inspector-column-resizer"
          role="separator"
          aria-label="Resize inspector column"
          aria-orientation="vertical"
          aria-valuemin={inspectorBounds.min}
          aria-valuemax={inspectorBounds.max}
          aria-valuenow={inspectorWidth}
          tabIndex={0}
          onPointerDown={startInspectorResize}
          onKeyDown={handleInspectorResizeKey}
        />

        <aside className="inspector" aria-label="Task inspector">
          <nav className="inspector-tabs" aria-label="Inspector tabs">
            {(["metadata", "annotations", "history"] as const).map((tab) => (
              <button
                key={tab}
                type="button"
                className={inspectorTab === tab ? "active" : ""}
                onClick={() => setInspectorTab(tab)}
              >
                {labelFromKey(tab)}
              </button>
            ))}
          </nav>

          {inspectorTab === "metadata" ? (
            <div className="inspector-panel">
              <section className="metadata-grid">
                <Field label="Collection">
                  <input readOnly value={labelFromKey(task.queue)} />
                </Field>
                <Field label="Source">
                  <input readOnly value={taskSource} />
                </Field>
                <Field label="Type">
                  <input readOnly value={descriptor.label} />
                </Field>
                <Field label="Confidence">
                  <select defaultValue="unreviewed">
                    <option value="high">High</option>
                    <option value="medium">Medium</option>
                    <option value="low">Low</option>
                    <option value="unreviewed">Unreviewed</option>
                  </select>
                </Field>
              </section>
              <section className="preview-band">
                <div>
                  <span>Target</span>
                  <strong>
                    {task.target_type} / {task.target_id.slice(0, 8)}
                  </strong>
                </div>
                <div>
                  <span>Reason</span>
                  <p>{task.reason_created}</p>
                </div>
                <div>
                  <span>Required</span>
                  <p>{task.required_decisions.map(promptFromDecisionKey).join(", ")}</p>
                </div>
              </section>
              <section className="decision-surface">{form}</section>
            </div>
          ) : null}

          {inspectorTab === "annotations" ? (
            <div className="inspector-panel">
              <Field label="Session notes" hint="Working notes for this review session only; these are not exported as training target text.">
                <TextArea value={notes} onChange={setNotes} rows={5} />
              </Field>
              <section className="decision-summary">
                <span>Current draft decisions</span>
                {Object.entries(autosaveDecisions).slice(0, 12).map(([key, value]) => (
                  <div key={key}>
                    <strong>{promptFromDecisionKey(key)}</strong>
                    <p>{Array.isArray(value) ? value.join(", ") : typeof value === "object" ? JSON.stringify(value) : String(value)}</p>
                  </div>
                ))}
              </section>
            </div>
          ) : null}

          {inspectorTab === "history" ? (
            <div className="inspector-panel">
              <section className="history-stack">
                <div>
                  <span>Task status</span>
                  <strong>{labelFromKey(task.status)}</strong>
                </div>
                <div>
                  <span>Draft state</span>
                  <strong>{draftStatus}</strong>
                </div>
                <div>
                  <span>Last autosave</span>
                  <strong>{formatDraftTime(draftUpdatedAt) || "Not saved yet"}</strong>
                </div>
                <div>
                  <span>Session submissions</span>
                  <strong>{completedThisSession}</strong>
                </div>
                <div>
                  <span>Archive graph</span>
                  <strong>
                    {assetsCount} assets / {memoriesCount} memories / {goldExamplesCount} gold edits
                  </strong>
                </div>
              </section>
            </div>
          ) : null}
        </aside>
      </div>

      <footer className="workbench-actions">
        <button type="button" onClick={onSkip}>
          <SkipForward size={18} />
          <span>Skip</span>
        </button>
        <button type="button" onClick={onFlag}>
          <Flag size={18} />
          <span>Flag</span>
        </button>
        <button type="button" disabled>
          <Copy size={18} />
          <span>Duplicate</span>
        </button>
        <button type="button" disabled>
          <RotateCcw size={18} />
          <span>Reset</span>
        </button>
        <button className="primary-action" type="submit" disabled={busy}>
          <Save size={18} />
          <span>{busy ? "Saving" : "Submit"}</span>
        </button>
        <div className="status-chip">
          <CheckCircle2 size={16} />
          <span>{task.status}</span>
        </div>
        <div className="status-chip draft-chip">
          <span>{draftUpdatedAt ? `${draftStatus} ${formatDraftTime(draftUpdatedAt)}` : draftStatus}</span>
        </div>
      </footer>
    </form>
  );
}
