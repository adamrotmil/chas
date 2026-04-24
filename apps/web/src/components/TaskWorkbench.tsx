"use client";

import {
  CheckCircle2,
  ClipboardList,
  Flag,
  Gauge,
  Image,
  Mail,
  Save,
  ShieldCheck,
  SkipForward,
  Sparkles,
  TextCursorInput
} from "lucide-react";
import { FormEvent, useEffect, useState } from "react";
import type { Task } from "@/lib/types";

type Decisions = Record<string, unknown>;

interface TaskWorkbenchProps {
  task: Task;
  onSubmit: (decisions: Decisions, notes?: string) => Promise<void>;
  onSkip: () => Promise<void>;
  onFlag: () => Promise<void>;
}

const taskLabels: Record<string, { label: string; icon: React.ReactNode }> = {
  asset_triage: { label: "Asset Triage", icon: <ClipboardList size={18} /> },
  photo_context: { label: "Photo Context", icon: <Image size={18} /> },
  text_segment_review: { label: "Text Segment Review", icon: <TextCursorInput size={18} /> },
  boundary_review: { label: "Boundary Review", icon: <ShieldCheck size={18} /> },
  email_voice_sample: { label: "Email Voice Sample", icon: <Mail size={18} /> },
  gold_voice_edit: { label: "Gold Voice Edit", icon: <Sparkles size={18} /> }
};

function payloadString(value: unknown, fallback = ""): string {
  return typeof value === "string" ? value : fallback;
}

function payloadNumber(value: unknown, fallback = 3): number {
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

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="field">
      <span>{label}</span>
      {children}
    </label>
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
          {option}
        </option>
      ))}
    </select>
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
      <span>{label}</span>
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
      <span>{label}</span>
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

function AssetTriageForm({ task, onChange }: { task: Task; onChange: (value: Decisions) => void }) {
  const payload = task.input_payload;
  const [sourceType, setSourceType] = useState(payloadString(payload.source_type, "unknown"));
  const [importance, setImportance] = useState("medium");
  const [privacy, setPrivacy] = useState("unreviewed");
  const [processNext, setProcessNext] = useState("yes");
  const [triageNotes, setTriageNotes] = useState("");

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

function PhotoContextForm({ task, onChange }: { task: Task; onChange: (value: Decisions) => void }) {
  const payload = task.input_payload;
  const [visiblePeople, setVisiblePeople] = useState(payloadArray(payload.machine_guess_people).join(", "));
  const [absentPeople, setAbsentPeople] = useState("");
  const [place, setPlace] = useState(payloadString(payload.machine_guess_place, "unknown"));
  const [dateRange, setDateRange] = useState("unknown");
  const [dateConfidence, setDateConfidence] = useState("unknown");
  const [event, setEvent] = useState("unknown");
  const [description, setDescription] = useState("");
  const [invisibleContext, setInvisibleContext] = useState("");
  const [tone, setTone] = useState("tender, comic");
  const [themes, setThemes] = useState("fatherhood, memory");
  const [memoryPotential, setMemoryPotential] = useState(4);
  const [privacySensitivity, setPrivacySensitivity] = useState(2);
  const [galleryEligibility, setGalleryEligibility] = useState("family_private");

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
      emotional_tone: parseList(tone),
      themes: parseList(themes),
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
    themes,
    tone,
    visiblePeople
  ]);

  return (
    <div className="form-grid">
      <Field label="Visible people">
        <input value={visiblePeople} onChange={(event) => setVisiblePeople(event.target.value)} />
      </Field>
      <Field label="Absent but relevant">
        <input value={absentPeople} onChange={(event) => setAbsentPeople(event.target.value)} />
      </Field>
      <Field label="Place">
        <input value={place} onChange={(event) => setPlace(event.target.value)} />
      </Field>
      <Field label="Date or range">
        <input value={dateRange} onChange={(event) => setDateRange(event.target.value)} />
      </Field>
      <Field label="Date confidence">
        <Select value={dateConfidence} onChange={setDateConfidence} options={["exact", "year", "decade", "unknown"]} />
      </Field>
      <Field label="Event">
        <input value={event} onChange={(event) => setEvent(event.target.value)} />
      </Field>
      <Field label="Visual correction">
        <TextArea value={description} onChange={setDescription} />
      </Field>
      <Field label="Invisible context">
        <TextArea rows={5} value={invisibleContext} onChange={setInvisibleContext} />
      </Field>
      <Field label="Emotional tone">
        <input value={tone} onChange={(event) => setTone(event.target.value)} />
      </Field>
      <Field label="Themes">
        <input value={themes} onChange={(event) => setThemes(event.target.value)} />
      </Field>
      <Rating label="Memory potential" value={memoryPotential} onChange={setMemoryPotential} />
      <Rating label="Privacy sensitivity" value={privacySensitivity} onChange={setPrivacySensitivity} />
      <Field label="Gallery eligibility">
        <Select value={galleryEligibility} onChange={setGalleryEligibility} options={["none", "family_private", "public_candidate"]} />
      </Field>
    </div>
  );
}

function TextSegmentReviewForm({ task, onChange }: { task: Task; onChange: (value: Decisions) => void }) {
  const payload = task.input_payload;
  const [boundaryGood, setBoundaryGood] = useState("yes");
  const [title, setTitle] = useState(payloadString(payload.segment_title, ""));
  const [people, setPeople] = useState("Charles, Adam");
  const [places, setPlaces] = useState("");
  const [dateRange, setDateRange] = useState("unknown");
  const [themes, setThemes] = useState("fatherhood, logistics");
  const [tone, setTone] = useState("tender, restrained");
  const [reliability, setReliability] = useState("high");
  const [truthStatus, setTruthStatus] = useState("archival_source");
  const [boundaryNotes, setBoundaryNotes] = useState("");

  useEffect(() => {
    onChange({
      segment_boundary_good: boundaryGood,
      segment_title: title,
      people: parseList(people),
      places: parseList(places),
      date_or_range: dateRange,
      themes: parseList(themes),
      emotional_tone: parseList(tone),
      source_reliability: reliability,
      truth_status: truthStatus,
      boundary_notes: boundaryNotes
    });
  }, [boundaryGood, boundaryNotes, dateRange, onChange, people, places, reliability, themes, title, tone, truthStatus]);

  return (
    <div className="form-grid">
      <Field label="Boundary good">
        <Select value={boundaryGood} onChange={setBoundaryGood} options={["yes", "no"]} />
      </Field>
      <Field label="Segment title">
        <input value={title} onChange={(event) => setTitle(event.target.value)} />
      </Field>
      <Field label="People">
        <input value={people} onChange={(event) => setPeople(event.target.value)} />
      </Field>
      <Field label="Places">
        <input value={places} onChange={(event) => setPlaces(event.target.value)} />
      </Field>
      <Field label="Date or range">
        <input value={dateRange} onChange={(event) => setDateRange(event.target.value)} />
      </Field>
      <Field label="Themes">
        <input value={themes} onChange={(event) => setThemes(event.target.value)} />
      </Field>
      <Field label="Emotional tone">
        <input value={tone} onChange={(event) => setTone(event.target.value)} />
      </Field>
      <Field label="Reliability">
        <Select value={reliability} onChange={setReliability} options={["high", "medium", "low", "unknown"]} />
      </Field>
      <Field label="Truth status">
        <Select
          value={truthStatus}
          onChange={setTruthStatus}
          options={["archival_source", "adam_memory", "adam_inference", "system_inference", "model_generated"]}
        />
      </Field>
      <Field label="Boundary notes">
        <TextArea value={boundaryNotes} onChange={setBoundaryNotes} />
      </Field>
    </div>
  );
}

function BoundaryReviewForm({ onChange }: { onChange: (value: Decisions) => void }) {
  const [privacyLevel, setPrivacyLevel] = useState("family_private");
  const [flags, setFlags] = useState({
    searchable: true,
    retrievable_in_chat: true,
    quotable: false,
    summarizable: true,
    usable_for_voice_context: true,
    usable_for_sft: false,
    usable_for_dpo: false,
    usable_for_eval: true,
    usable_for_gallery_public: false,
    usable_for_gallery_family: true,
    usable_for_simulation: true,
    contains_living_person_sensitive_material: false,
    redaction_required: false
  });
  const [notes, setNotes] = useState("");

  useEffect(() => {
    onChange({ privacy_level: privacyLevel, ...flags, notes });
  }, [flags, notes, onChange, privacyLevel]);

  return (
    <div className="form-grid">
      <Field label="Privacy level">
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
      <Field label="Notes">
        <TextArea value={notes} onChange={setNotes} />
      </Field>
    </div>
  );
}

function EmailVoiceSampleForm({ onChange }: { onChange: (value: Decisions) => void }) {
  const [voiceMode, setVoiceMode] = useState("father_to_adam");
  const [authenticity, setAuthenticity] = useState(4);
  const [density, setDensity] = useState(4);
  const [tone, setTone] = useState("tender, dry");
  const [phrases, setPhrases] = useState("call when you get in");
  const [voiceContext, setVoiceContext] = useState(true);
  const [sft, setSft] = useState(false);
  const [dpo, setDpo] = useState(false);
  const [why, setWhy] = useState("");

  useEffect(() => {
    onChange({
      voice_mode: voiceMode,
      authenticity_value: authenticity,
      voice_density: density,
      emotional_tone: parseList(tone),
      recurring_phrases: parseList(phrases),
      usable_for_voice_context: voiceContext ? "yes" : "no",
      usable_for_sft: sft ? "yes" : "no",
      usable_for_dpo: dpo ? "yes" : "no",
      why_it_matters: why
    });
  }, [authenticity, density, dpo, onChange, phrases, sft, tone, voiceContext, voiceMode, why]);

  return (
    <div className="form-grid">
      <Field label="Voice mode">
        <Select
          value={voiceMode}
          onChange={setVoiceMode}
          options={["casual_email", "father_to_adam", "argument", "comic", "grief", "logistics", "other"]}
        />
      </Field>
      <Rating label="Authenticity" value={authenticity} onChange={setAuthenticity} />
      <Rating label="Voice density" value={density} onChange={setDensity} />
      <Field label="Emotional tone">
        <input value={tone} onChange={(event) => setTone(event.target.value)} />
      </Field>
      <Field label="Recurring phrases">
        <input value={phrases} onChange={(event) => setPhrases(event.target.value)} />
      </Field>
      <div className="toggle-grid">
        <Toggle label="usable_for_voice_context" checked={voiceContext} onChange={setVoiceContext} />
        <Toggle label="usable_for_sft" checked={sft} onChange={setSft} />
        <Toggle label="usable_for_dpo" checked={dpo} onChange={setDpo} />
      </div>
      <Field label="Why it matters">
        <TextArea value={why} onChange={setWhy} />
      </Field>
    </div>
  );
}

function GoldVoiceEditForm({ task, onChange }: { task: Task; onChange: (value: Decisions) => void }) {
  const payload = task.input_payload;
  const defaultRatings = (payload.ratings ?? {}) as Record<string, unknown>;
  const [prompt, setPrompt] = useState(payloadString(payload.prompt, ""));
  const [voiceMode, setVoiceMode] = useState(payloadString(payload.voice_mode, "father_to_adam"));
  const [truthMode, setTruthMode] = useState(payloadString(payload.truth_mode, "generative_reconstruction"));
  const [modelDraft, setModelDraft] = useState(payloadString(payload.model_draft, ""));
  const [goldEdit, setGoldEdit] = useState(payloadString(payload.adam_gold_edit, ""));
  const [failureModes, setFailureModes] = useState(payloadArray(payload.failure_modes).join(", ") || "too_generic, too_therapy_like");
  const [ratings, setRatings] = useState({
    voice_fidelity: payloadNumber(defaultRatings.voice_fidelity, 5),
    mode_match: payloadNumber(defaultRatings.mode_match, 5),
    emotional_truth: payloadNumber(defaultRatings.emotional_truth, 5),
    concrete_detail: payloadNumber(defaultRatings.concrete_detail, 5),
    restraint: payloadNumber(defaultRatings.restraint, 5),
    non_parody: payloadNumber(defaultRatings.non_parody, 5),
    grounding: payloadNumber(defaultRatings.grounding, 5)
  });
  const [exportFlags, setExportFlags] = useState({
    sft: true,
    dpo: true,
    eval: true,
    anti_pattern: true,
    style_rule: true
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
      ratings,
      failure_modes: parseList(failureModes),
      export_flags: exportFlags
    });
  }, [exportFlags, failureModes, goldEdit, modelDraft, onChange, payload.context_pack_id, payload.generation_id, payload.prompt_spec_id, prompt, ratings, truthMode, voiceMode]);

  return (
    <div className="gold-grid">
      <Field label="Prompt">
        <TextArea value={prompt} onChange={setPrompt} rows={3} />
      </Field>
      <Field label="Voice mode">
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
      <Field label="Truth mode">
        <Select value={truthMode} onChange={setTruthMode} options={["generative_reconstruction", "simulation", "interpretive"]} />
      </Field>
      <Field label="Model draft">
        <TextArea value={modelDraft} onChange={setModelDraft} rows={8} />
      </Field>
      <Field label="Adam gold edit">
        <TextArea value={goldEdit} onChange={setGoldEdit} rows={10} />
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
      <Field label="Failure modes">
        <input value={failureModes} onChange={(event) => setFailureModes(event.target.value)} />
      </Field>
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

export function TaskWorkbench({ task, onSubmit, onSkip, onFlag }: TaskWorkbenchProps) {
  const [decisions, setDecisions] = useState<Decisions>({});
  const [notes, setNotes] = useState("");
  const [busy, setBusy] = useState(false);
  const descriptor = taskLabels[task.task_type] ?? { label: task.task_type, icon: <Gauge size={18} /> };

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    try {
      await onSubmit(decisions, notes);
    } finally {
      setBusy(false);
    }
  }

  const form = (() => {
    switch (task.task_type) {
      case "asset_triage":
        return <AssetTriageForm task={task} onChange={setDecisions} />;
      case "photo_context":
        return <PhotoContextForm task={task} onChange={setDecisions} />;
      case "text_segment_review":
        return <TextSegmentReviewForm task={task} onChange={setDecisions} />;
      case "boundary_review":
        return <BoundaryReviewForm onChange={setDecisions} />;
      case "email_voice_sample":
        return <EmailVoiceSampleForm onChange={setDecisions} />;
      case "gold_voice_edit":
        return <GoldVoiceEditForm task={task} onChange={setDecisions} />;
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

  return (
    <form className="workbench" onSubmit={handleSubmit}>
      <header className="workbench-header">
        <div>
          <div className="task-type">
            {descriptor.icon}
            <span>{descriptor.label}</span>
          </div>
          <h2>{payloadString(task.input_payload.title) || payloadString(task.input_payload.segment_title) || task.human_id}</h2>
        </div>
        <div className="task-meta">
          <span>{task.queue}</span>
          <strong>{task.priority}</strong>
        </div>
      </header>

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
          <p>{task.required_decisions.join(", ")}</p>
        </div>
      </section>

      {payloadString(task.input_payload.text) ? (
        <section className="source-text">
          <span>Source text</span>
          <p>{payloadString(task.input_payload.text)}</p>
        </section>
      ) : null}

      <section className="decision-surface">{form}</section>

      <Field label="Session notes">
        <TextArea value={notes} onChange={setNotes} rows={3} />
      </Field>

      <footer className="workbench-actions">
        <button className="primary-action" type="submit" disabled={busy}>
          <Save size={18} />
          <span>{busy ? "Saving" : "Submit"}</span>
        </button>
        <button type="button" onClick={onSkip}>
          <SkipForward size={18} />
          <span>Skip</span>
        </button>
        <button type="button" onClick={onFlag}>
          <Flag size={18} />
          <span>Flag</span>
        </button>
        <div className="status-chip">
          <CheckCircle2 size={16} />
          <span>{task.status}</span>
        </div>
      </footer>
    </form>
  );
}
