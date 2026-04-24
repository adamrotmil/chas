# CharlesOps v1.0 Master Architecture and Build Specification

**Version:** v1.0 clean rewrite  
**Date:** 2026-04-24  
**Owner / primary annotator / voice SME:** Adam  
**Working project name:** CharlesOps  
**Canonical status:** This document supersedes earlier planning documents, including the initial Codex build spec and the downstream asset strategy addendum.

---

## 0. Executive thesis

CharlesOps is not primarily a chatbot project.

CharlesOps is a **production memory and voice-asset operating system** for turning a large personal archive into a structured, permissioned, downstream-ready asset library.

The system should let Adam process task after task:

- mirroring assets from Google Drive and other sources,
- labeling and contextualizing photos,
- reviewing emails, journals, memoir passages, and transcripts,
- disambiguating people, places, events, objects, and recurring references,
- creating memory cards and graph links,
- setting boundaries for search, quotation, training, gallery display, and simulation,
- evaluating Charles-style generated responses,
- editing near-miss generated drafts into high-fidelity Adam-approved Charles voice examples,
- exporting retrieval, SFT, DPO, eval, anti-pattern, gallery, and context-pack datasets.

The core idea:

```text
Google Drive and other source systems
  = vaults of originals

CharlesOps production asset library
  = mirrored media + normalized text + metadata + annotations + graph + boundaries

Downstream systems
  = ask-the-archive, Charles voice/chat, photo gallery, memoir builder,
    training datasets, evals, simulation/ritual experiences
```

The build should work backward from the ideal downstream asset state.

Do not merely build a labeling app. Build a system that manufactures the asset classes downstream products will need.

---

## 1. What changed from the earlier plan

The earlier plan correctly identified:

- archive-first, model-second,
- human-in-the-loop annotation,
- voice modes,
- memory graph,
- privacy boundaries,
- SFT/DPO/eval asset creation.

The revised v1.0 architecture adds a sharper downstream asset model:

1. **Google Drive remains a vault, not the operational runtime.**  
   Drive files should be referenced, mirrored, snapshotted, exported, and checksummed. Downstream products should mostly query CharlesOps, not live-query Drive.

2. **CharlesOps should maintain a cloud production asset library.**  
   Text, photos, exported docs, thumbnails, transcripts, audio derivatives, and metadata should be copied into CharlesOps-controlled storage. The relational database stores canonical records, metadata, annotations, boundaries, graph links, task status, and export manifests. Binary files should usually live in object storage or durable file storage, not as ordinary Postgres row blobs.

3. **Photos are first-class downstream assets.**  
   They are not only attachments. They become queryable, permissioned memory anchors usable for archive search, family galleries, memoir illustration, voice context, and future immersive work.

4. **The context pack is the key downstream unit.**  
   Voice/chat/reconstruction systems should not receive a pile of raw files. They should receive a permission-filtered context pack containing the relevant memories, source segments, photos, voice examples, Adam gold edits, style rules, and boundaries.

5. **Adam gold voice edits are crown-jewel training assets.**  
   The system should generate a Charles-style draft, then Adam edits it into a 99.9%-authentic response. That produces SFT examples, DPO pairs, eval cases, anti-patterns, and style rules.

6. **Every task should move an asset toward downstream readiness.**  
   A task is successful only if it improves one or more asset classes: source, segment, memory, voice, training, boundary, gallery, context-pack, or export.

---

## 2. Non-negotiable principles

### 2.1 Preserve originals; operate on mirrors

Raw Drive/local/archive files are source vault items. They should not be mutated by CharlesOps.

CharlesOps creates:

- source references,
- internal asset IDs,
- snapshots/mirrors,
- derivatives,
- annotations,
- task records,
- downstream export datasets.

### 2.2 The archive is not the voice

The archive says what exists.

The voice layer models how Charles moved through language.

The simulation layer creates emotionally plausible reconstructions, but it is not evidence.

The system must preserve the distinction between:

```text
Charles wrote this.
Charles said this.
Adam remembers this.
Adam edited this as an expert reconstruction.
The model generated this.
The system inferred this.
```

### 2.3 Adam is a first-class source and annotator

Adam is not merely a user. Adam is:

- the primary annotator,
- a living memory source,
- a Charles voice SME,
- the final judge of authenticity,
- a boundary setter,
- a producer of gold voice examples.

Adam’s notes and edits should be stored as first-class records with provenance.

### 2.4 Permission and dignity are architectural, not decorative

Every asset, segment, memory, generated output, and export item must carry usage boundaries.

At minimum:

```text
searchable
retrievable_in_chat
quotable
summarizable
usable_for_voice_context
usable_for_sft
usable_for_dpo
usable_for_eval
usable_for_gallery_public
usable_for_gallery_family
usable_for_simulation
contains_living_person_sensitive_material
sealed
```

### 2.5 Fine-tuning is not the memory store

Fine-tuning teaches voice behavior and mode control.

Retrieval/context packs provide facts, memories, photos, source passages, and boundaries.

The downstream Charles system should combine:

```text
base or fine-tuned model
  + context pack
  + retrieval
  + memory graph
  + permission rules
  + mode-specific style guide
  + Adam gold examples
```

It should not rely on a model checkpoint to “remember” the archive.

### 2.6 The UI should optimize for sustained human work

The product should feel like a calm production console:

```text
Open app.
Choose a queue.
Complete 20–50 tasks.
Stop.
Everything is saved, versioned, and useful.
```

Support both quick micro-tasks and emotionally deeper tasks.

---

## 3. North-star downstream systems

CharlesOps exists to supply assets to downstream experiences. The following systems should shape every data model and task design decision.

### 3.1 Ask-the-archive

A conservative, source-grounded archive search and Q&A system.

Example questions:

- “Where does Charles write about Maine?”
- “Find passages about photography.”
- “What sources mention Bernie?”
- “What evidence supports this memory?”
- “What did Charles actually write versus what are we inferring?”

Required asset classes:

- mirrored source assets,
- normalized text,
- source segments,
- citations/provenance,
- entity links,
- theme links,
- boundary flags,
- confidence/uncertainty fields.

This mode should never invent.

### 3.2 Charles voice/chat agent

A constrained generative system that writes in Charles’s voice in a selected mode.

Voice modes:

- casual email,
- father-to-Adam,
- memoir scene,
- argument,
- comic observation,
- grief or memory fragment,
- photography reflection,
- philosophical fragment,
- spoken interview cadence,
- practical/logistical note.

Required asset classes:

- real Charles voice samples labeled by mode,
- Adam gold voice edits,
- SFT examples,
- DPO pairs,
- anti-patterns,
- voice mode cards,
- style rules,
- prompt specs,
- memory cards,
- context packs,
- truth-mode labels.

### 3.3 Gold voice edit training loop

This is the most valuable training-data workflow.

```text
prompt/scenario/context
  -> model draft in selected Charles mode
  -> Adam rates draft
  -> Adam edits draft into authentic Charles-like output
  -> system stores draft, gold edit, ratings, diagnosis, export flags
  -> system emits SFT, DPO, eval, anti-pattern, and style-rule artifacts
```

Adam gold edits are **not** archival Charles writings. They are SME-corrected expert reconstructions of Charles’s voice.

Truth status:

```text
adam_expert_reconstruction
```

### 3.4 Photo memory browser and gallery

Photos should support both private memory work and future public/family gallery experiences.

Example queries:

- “Show photos of Charles and Adam in Maine.”
- “Find photos connected to food as care.”
- “Show family-private photos from the late 1980s.”
- “Create a gallery sequence around fatherhood, Maine, and summer visits.”

Required asset classes:

- mirrored original images,
- thumbnails and display derivatives,
- EXIF and source metadata,
- visual descriptions,
- Adam context notes,
- people/place/date/event labels,
- memory-card links,
- gallery eligibility flags,
- public/family/private access rules.

### 3.5 Memoir builder and reconstruction studio

A long-form drafting and reconstruction system.

Example uses:

- reconstruct memoir scenes,
- assemble thematic chapters,
- build chronological timelines,
- illustrate sections with photos,
- link passages to evidence and memories,
- distinguish source text from generated bridging prose.

Required asset classes:

- memoir/journal/email/audio segments,
- memory cards,
- chronology records,
- contradiction/uncertainty notes,
- photo links,
- voice modes for long-form prose,
- source citations,
- reconstruction boundaries.

### 3.6 Audio and spoken cadence layer

Audio should support:

- transcript search,
- speaker-specific memory extraction,
- spoken cadence notes,
- audio clip references,
- future voice/cadence-aware experiences.

Required asset classes:

- mirrored audio,
- transcript derivatives,
- timestamped segments,
- speaker labels,
- story boundaries,
- nonverbal notes,
- cadence notes,
- memory links,
- boundary flags.

### 3.7 Future immersive / ritual / simulation layer

This is the most interpretive use case.

It should be possible later to build:

- a memory room,
- a walk through Maine/Portland/house/photo spaces,
- a photo-triggered Charles reflection,
- a ritual interface for asking and remembering,
- a VR or spatial gallery.

This layer must only use boundary-cleared assets and must clearly mark reconstructions as reconstructions.

---

## 4. System architecture

### 4.1 Core diagram

```text
                     Source vaults
        ┌──────────────────────────────────┐
        │ Google Drive / local drives       │
        │ email exports / scans / audio     │
        │ journals / memoirs / photos       │
        └─────────────────┬────────────────┘
                          │ import / export / mirror
                          ↓
┌─────────────────────────────────────────────────────────────┐
│              CharlesOps Production Asset Library             │
│                                                             │
│  Object storage / durable file storage                       │
│    raw mirrors, exported docs, photos, audio, thumbnails,    │
│    display images, transcripts, OCR, derived media            │
│                                                             │
│  Postgres                                                    │
│    canonical records, tasks, annotations, entities, memories, │
│    graph edges, boundaries, ratings, generations, exports     │
│                                                             │
│  Search and retrieval indexes                                │
│    full-text search, vector search, image/text embeddings,    │
│    metadata filters, graph traversal                          │
│                                                             │
│  Dataset/export compiler                                     │
│    RAG corpus, context packs, SFT, DPO, evals, anti-patterns, │
│    gallery feeds, memory graph exports                        │
└─────────────────────────┬───────────────────────────────────┘
                          │ context builder / export feeds
                          ↓
        ┌──────────────────────────────────┐
        │ Downstream systems                │
        │ ask-the-archive                   │
        │ Charles voice/chat                │
        │ photo gallery                     │
        │ memoir builder                    │
        │ training/eval pipelines           │
        │ future immersive experiences      │
        └──────────────────────────────────┘
```

### 4.2 Storage separation

Use different storage layers for different responsibilities.

#### Source systems

Examples:

- Google Drive,
- local disk,
- email archives,
- external hard drives,
- future family uploads.

Purpose:

- preserve originals,
- provide source references,
- act as vaults.

CharlesOps should not rely on live Drive queries for every downstream interaction.

#### Object storage / durable file storage

Stores binary files and text derivative files:

```text
raw mirrors
exported Google Docs/Sheets/Slides
photos
audio
video if any
PDFs
scans
thumbnails
web-size display images
OCR outputs
transcript JSON
waveform images
```

MVP can use local file storage. Production should support S3/GCS-compatible object storage.

#### Relational database

Stores:

```text
asset identity
external references
object storage paths
source metadata
annotations
tasks
entities
memory cards
graph edges
boundaries
voice modes
prompt specs
generations
generation reviews
gold voice examples
style rules
anti-patterns
dataset export manifests
gallery curations
context pack records
```

Do not store large binary media as ordinary relational row blobs unless there is a narrow, deliberate reason.

#### Retrieval indexes

Stores/searches:

```text
normalized text
captions
Adam context notes
memory cards
voice samples
gold edits
anti-patterns
transcripts
photo retrieval text
```

Use a hybrid approach:

```text
full-text search
+ vector search
+ metadata filters
+ graph traversal
+ permission filters
```

---

## 5. Ideal downstream asset portfolio

At maturity, CharlesOps should produce and maintain these asset classes.

### 5.1 Source-grade assets

Raw or mirrored source materials with provenance.

Good record:

```yaml
asset_id: CR_ASSET_000421
asset_type: photo
source_system: google_drive
external_refs:
  drive_file_id: "..."
  drive_parent_folder: "Charles / Photos / Maine"
  original_filename: "IMG_0042.jpg"
mime_type: image/jpeg
storage:
  original_object_uri: "object://raw/CR_ASSET_000421/original.jpg"
  display_object_uri: "object://display/CR_ASSET_000421_large.jpg"
  thumbnail_object_uri: "object://thumbs/CR_ASSET_000421_512.jpg"
provenance:
  imported_at: "2026-04-24T00:00:00Z"
  source_created_time: null
  source_modified_time: "2024-10-02T00:00:00Z"
  checksum_sha256: "..."
  mirror_version: 1
boundaries:
  privacy_level: unreviewed
  searchable: false
  usable_for_gallery_public: false
maturity_level: L1_mirrored
```

### 5.2 Segment-grade assets

Meaningful source chunks:

- email body,
- memoir scene,
- journal entry,
- transcript story turn,
- photo record,
- scan/OCR page,
- letter,
- note fragment.

Good record:

```yaml
segment_id: CR_SEG_004812
asset_id: CR_ASSET_000221
segment_type: memoir_scene
source_locator:
  document_title: "Behold III"
  section_hint: "Maine / Adam / food"
text: "..."
people:
  - CR_ENTITY_ADAM
  - CR_ENTITY_CHARLES
places:
  - CR_PLACE_MAINE
themes:
  - fatherhood
  - food_as_care
voice_mode_candidates:
  - memoir_scene
boundaries:
  quotable: true
  usable_for_voice_context: true
  usable_for_sft: false
maturity_level: L3_reviewed
```

### 5.3 Memory-grade assets

Structured memory cards linking evidence, Adam context, uncertainty, emotional texture, and downstream use.

Good record:

```yaml
memory_id: CR_MEMORY_000077
title: "Maine summer visits and food as care"
summary: |
  Charles often expressed tenderness toward Adam through food, logistics,
  weather observations, and practical care rather than direct sentiment.
truth_status: interpretive_synthesis
people:
  - Charles Rotmil
  - Adam Rotmil
places:
  - Maine
date_range:
  start: null
  end: null
source_links:
  - CR_EMAIL_000919
  - CR_SEG_BEHOLD_004812
  - CR_PHOTO_000421
adam_context_notes:
  - ANN_000882
themes:
  - fatherhood
  - food_as_care
  - ordinary_tenderness
emotional_tone:
  - tender
  - comic
  - melancholy
reliability: medium_high
open_questions:
  - "Which exact year was the photo taken?"
boundaries:
  searchable: true
  usable_for_voice_context: true
  usable_for_simulation: true
  quotable: false
maturity_level: L6_downstream_ready
```

### 5.4 Voice-grade assets

Assets that teach or evaluate Charles’s voice.

Types:

- real Charles voice samples,
- Adam gold voice examples,
- voice mode cards,
- style rules,
- anti-patterns,
- prompt scenarios,
- generation reviews.

Good Adam gold record:

```yaml
gold_voice_example_id: CR_GOLD_VOICE_000184
truth_status: adam_expert_reconstruction
voice_mode: father_to_adam
prompt: |
  Write Adam a short note after he leaves Maine.
context_pack_id: CTX_000022
model_draft: |
  Dear Adam, I want you to know how meaningful our time together was...
adam_gold_edit: |
  Adam

  house is too quiet now.
  even the refrigerator sounds dramatic.

  found your coffee cup in the sink.
  good.
  proof you were here.

  call when you get in

  dad
ratings:
  voice_fidelity: 5
  emotional_truth: 5
  concrete_detail: 5
  restraint: 5
  non_parody: 5
failure_modes_in_draft:
  - too_generic
  - too_therapy_like
  - too_emotionally_explicit
downstream_use:
  sft: true
  dpo: true
  eval: true
  style_rule_extraction: true
```

### 5.5 Training-grade assets

Versioned dataset-ready records.

Types:

```text
SFT examples
DPO chosen/rejected pairs
eval prompts
rubric-scored generations
anti-pattern examples
style-rule examples
holdout sets
```

Good SFT candidate:

```yaml
sft_candidate_id: SFT_CAND_000184
source_gold_voice_example_id: CR_GOLD_VOICE_000184
messages:
  - role: system
    content: "You write in Charles's father-to-Adam mode..."
  - role: user
    content: "Write Adam a short note after he leaves Maine."
  - role: assistant
    content: "Adam\n\nhouse is too quiet now..."
quality_gate:
  approved_by: adam
  min_voice_fidelity_met: true
  boundaries_checked: true
  no_archival_misattribution: true
export_status: approved
```

Good DPO candidate:

```yaml
dpo_pair_id: DPO_000184
prompt: "Write Adam a short note after he leaves Maine."
chosen: "Adam\n\nhouse is too quiet now..."
rejected: "Dear Adam, I want you to know how meaningful..."
reason:
  - rejected_too_generic
  - rejected_too_emotionally_explicit
  - chosen_has_object_carried_feeling
```

### 5.6 Boundary-grade assets

Use policies attached to assets, segments, memories, examples, and exports.

Good boundary record:

```yaml
boundary_id: BND_000921
target_type: segment
target_id: CR_SEG_004812
privacy_level: family_private
searchable: true
retrievable_in_chat: true
quotable: false
summarizable: true
usable_for_voice_context: true
usable_for_sft: false
usable_for_dpo: false
usable_for_eval: true
usable_for_gallery_public: false
usable_for_gallery_family: true
usable_for_simulation: true
contains_living_person_sensitive_material: false
notes: "Useful as context, but do not quote directly in public outputs."
reviewed_by: adam
reviewed_at: "2026-04-24T00:00:00Z"
```

### 5.7 Gallery-grade assets

Photo/audio/text assets cleared for display.

Good gallery record:

```yaml
gallery_item_id: GAL_ITEM_000144
asset_id: CR_ASSET_000421
gallery_scope: family_private
title: "Maine, late 1980s"
display_caption: |
  Charles and Adam during a summer visit in Maine.
memory_caption: |
  Adam remembers this period as connected to food, practical care,
  and Charles's indirect tenderness.
image_uri: "object://display/CR_ASSET_000421_large.jpg"
thumbnail_uri: "object://thumbs/CR_ASSET_000421_512.jpg"
linked_memories:
  - CR_MEMORY_000077
boundary_snapshot:
  public_safe: false
  family_private: true
```

### 5.8 Context-pack assets

The context pack is the main downstream runtime object.

Good context pack:

```yaml
context_pack_id: CTX_000913
user_intent: photo_reflection
requested_voice_mode: father_to_adam
truth_mode: generative_reconstruction
retrieved_assets:
  photos:
    - CR_PHOTO_1988_MAINE_003
  source_segments:
    - CR_EMAIL_2009_0812_001
    - CR_SEG_BEHOLD_004812
  memory_cards:
    - CR_MEMORY_MAINE_VISITS_001
    - CR_MEMORY_FOOD_AS_CARE_002
  voice_examples:
    - CR_GOLD_VOICE_FATHER_TO_ADAM_000017
    - CR_REAL_EMAIL_SAMPLE_000044
allowed_facts:
  - "The photo is believed to be from Maine."
  - "Adam remembers this as connected to summer visits."
  - "Charles often expressed care through food and logistics."
boundaries:
  quote_source_text: false
  disclose_generated: true
  do_not_mention:
    - sensitive_living_person_note
style_guidance:
  mode: father_to_adam
  avoid:
    - generic sentimentality
    - therapy language
    - overdone ellipses
```

---

## 6. Asset maturity levels

Every asset should have a maturity level. The Ops process should move assets upward.

```text
L0 — Source seen
  The system knows the asset exists in Drive or another source.

L1 — Mirrored
  The asset has been copied/exported into CharlesOps storage with source reference and checksum.

L2 — Extracted
  The asset has thumbnails, OCR, transcript, EXIF, visual description, normalized text, or other derivatives.

L3 — Reviewed
  Adam or trusted reviewer has checked basic identity, context, type, or transcription.

L4 — Linked
  The asset connects to people, places, dates, themes, memories, related sources, or graph edges.

L5 — Boundary-cleared
  Permissions are set for search, quotation, training, gallery, simulation, and privacy.

L6 — Downstream-ready
  The asset can be used by RAG, context packs, gallery, memoir builder, or voice system.

L7 — Published/exported/trained
  The asset has been included in a specific dataset export, gallery release, eval suite, or model training run.
```

Dashboard example:

```text
Photos:
  12,400 total
  8,000 mirrored
  4,500 extracted
  1,200 reviewed
  300 linked to memories
  180 gallery-ready
  75 usable in voice context
```

---

## 7. Task engine design

### 7.1 The task is the atomic unit of work

The UI should not feel like a database. It should feel like:

```text
Show me the next most useful thing I can do.
Let me make a judgment.
Save that judgment forever.
Use that judgment to generate the next better task.
```

Task record:

```yaml
task_id: TASK_001002
task_type: photo_context
target_type: asset
target_id: CR_ASSET_000421
status: ready
priority: 73
assigned_to: adam
reason_created: "Photo is mirrored but lacks people/place/date/context."
input_summary:
  asset_preview: thumbnail
  machine_guess_people: ["Charles?", "Adam?"]
  machine_guess_place: "Maine?"
required_decisions:
  - confirm_people
  - estimate_date
  - add_invisible_context
  - set_boundary
  - link_or_create_memory
produces:
  - photo_record_update
  - annotations
  - possible_memory_card
  - boundary_update
  - graph_edges
```

### 7.2 Task lifecycle

```text
generated
  -> ready
  -> in_progress
  -> submitted
  -> accepted
  -> compiled
```

Special states:

```text
skipped
blocked_needs_context
blocked_needs_family_review
sensitive_hold
archive_only
do_not_process
duplicate
low_value
error
```

### 7.3 Queue types

The app should expose queues, not folders.

```text
Highest-value next tasks
Photos needing context
Photos needing boundary review
Emails needing voice review
Generated responses needing Adam gold edits
Memoir scenes needing segmentation
Audio clips needing transcript/speaker review
Entities needing disambiguation
Memory cards needing source links
Assets needing gallery eligibility
Dataset candidates needing export approval
Sensitive items needing boundary decisions
Micro-tasks only
Deep tasks only
```

### 7.4 Micro vs deep tasks

Micro-tasks:

```text
confirm person
confirm place
rate voice 1–5
mark sensitive
accept/reject label
link duplicate
approve transcript segment
```

Deep tasks:

```text
write invisible context note
create memory card
repair generated response
resolve contradictory memories
define boundary for sensitive passage
write why this sounds like Charles
```

### 7.5 Next-best-task priority

Priority should consider:

```text
source importance
uncertainty
emotional value
training value
memory graph value
gallery value
sensitivity risk
age in queue
blocking status
Adam preference / energy mode
```

Example formula:

```text
priority =
  source_importance
  + uncertainty
  + memory_graph_value
  + training_value
  + gallery_value
  + age_bonus
  - sensitivity_risk_if_unreviewed
```

Human override flags:

```text
sacred
do soon
later
low value
archive only
sealed
```

---

## 8. MVP task types

### 8.1 Asset triage

Purpose: identify what an asset is and whether it should be processed.

Fields:

```yaml
source_type: email | journal | memoir | autobiography | photo | audio | scan | document | unknown
importance: low | medium | high | sacred
initial_privacy_level: unreviewed | family_private | sensitive | sealed
process_next: yes | no | later
notes: string
```

Produces:

- asset metadata update,
- preliminary boundary,
- follow-up extraction/mirroring task.

### 8.2 Source mirror review

Purpose: confirm that a Drive/local asset has been mirrored/exported correctly.

Fields:

```yaml
mirror_ok: yes | no
checksum_verified: yes | no | not_applicable
export_format_ok: yes | no | not_applicable
source_reference_ok: yes | no
needs_reimport: yes | no
```

Produces:

- asset snapshot status,
- object file status,
- extraction task if ready.

### 8.3 Photo context

Purpose: turn photos into memory anchors.

Fields:

```yaml
visible_people: list
absent_but_relevant_people: list
place: string | unknown
date_or_range: string | unknown
date_confidence: exact | year | decade | unknown
event: string | unknown
visual_description_correction: string
invisible_context_note: string
emotional_tone: list
themes: list
memory_potential: 1-5
privacy_sensitivity: 1-5
gallery_eligibility: none | family_private | public_candidate
link_to_memory: existing | create_new | skip
```

The key field:

```text
What would a stranger miss from looking at this?
```

### 8.4 Text segment review

Purpose: review normalized emails, memoir scenes, journal entries, letters, scans, and notes.

Fields:

```yaml
segment_boundary_good: yes | no
segment_title: string
people: list
places: list
date_or_range: string | unknown
themes: list
emotional_tone: list
source_reliability: high | medium | low | unknown
truth_status: archival_source | adam_memory | inference | generated
boundary_notes: string
```

### 8.5 Email voice sample review

Purpose: identify high-value real Charles voice samples.

Fields:

```yaml
voice_mode: casual_email | father_to_adam | argument | comic | grief | logistics | other
authenticity_value: 1-5
voice_density: 1-5
emotional_tone: list
recurring_phrases: list
usable_for_voice_context: yes | no
usable_for_sft: yes | no | only_with_redaction
usable_for_dpo: yes | no
why_it_matters: string
```

### 8.6 Memoir segment review

Purpose: turn long memoir/autobiography text into scene-grade assets.

Fields:

```yaml
scene_title: string
scene_boundary_good: yes | no
people: list
places: list
time_period: string | unknown
themes: list
voice_mode: memoir_scene | comic_observation | argument | grief_memory | philosophical_fragment
scene_integrity: 1-5
thematic_density: 1-5
voice_importance: 1-5
factual_clarity: 1-5
generative_safety: 1-5
```

### 8.7 Audio transcript review

Purpose: clean audio transcripts and capture spoken cadence.

Fields:

```yaml
speaker_label: Charles | Eva | Adam | other | unknown
transcription_corrections: string
story_boundary: start | middle | end | standalone
emotional_shift: string
nonverbal_notes:
  - laugh
  - pause
  - interruption
  - self_correction
  - silence
cadence_notes: string
possible_memory_card: yes | no
```

### 8.8 Entity disambiguation

Purpose: resolve people, places, objects, institutions, recurring references.

Fields:

```yaml
entity_type: person | place | object | event | institution | concept | phrase
canonical_name: string
aliases: list
relationship_to_charles: string
relationship_to_adam: string
confidence: high | medium | low
merge_with_existing: entity_id | none
notes: string
```

### 8.9 Memory card creation/review

Purpose: create or improve memory-grade assets.

Fields:

```yaml
title: string
summary: markdown
truth_status: archival | adam_memory | interpretive_synthesis | generated_reconstruction
people: list
places: list
date_range: string | unknown
source_links: list
emotional_tone: list
themes: list
reliability: high | medium | low | contested
open_questions: list
usable_for_voice_context: yes | no
usable_for_simulation: yes | no
```

### 8.10 Boundary review

Purpose: decide allowed downstream uses.

Fields:

```yaml
privacy_level: public_safe | family_private | sensitive_living_people | intimate | sealed
searchable: boolean
retrievable_in_chat: boolean
quotable: boolean
summarizable: boolean
usable_for_voice_context: boolean
usable_for_sft: boolean
usable_for_dpo: boolean
usable_for_eval: boolean
usable_for_gallery_public: boolean
usable_for_gallery_family: boolean
usable_for_simulation: boolean
contains_living_person_sensitive_material: boolean
redaction_required: boolean
notes: string
```

### 8.11 Gold voice edit

Purpose: turn a model draft into an Adam-approved Charles voice example.

Fields:

```yaml
prompt: string
voice_mode: string
truth_mode: generative_reconstruction | simulation | interpretive
context_pack_id: string | null
model_draft: markdown
adam_gold_edit: markdown
ratings:
  voice_fidelity: 1-5
  mode_match: 1-5
  emotional_truth: 1-5
  concrete_detail: 1-5
  restraint: 1-5
  non_parody: 1-5
  grounding: 1-5
failure_modes:
  - too_generic
  - too_therapy_like
  - too_sentimental
  - too_polished
  - too_mannered
  - overdone_ellipses
  - forced_gravity
  - no_physical_carrier_of_feeling
export_flags:
  sft: boolean
  dpo: boolean
  eval: boolean
  anti_pattern: boolean
  style_rule: boolean
```

Produces:

- gold voice example,
- SFT candidate,
- DPO pair,
- eval case,
- anti-pattern entry,
- style-rule candidate.

### 8.12 Gallery curation

Purpose: prepare photo/audio/text assets for downstream gallery views.

Fields:

```yaml
gallery_scope: none | family_private | public_candidate | public_approved
display_title: string
display_caption: string
memory_caption: string
sequence_tags: list
related_memory_cards: list
requires_redaction: boolean
notes: string
```

### 8.13 Context pack review

Purpose: review generated context packs before they become templates or eval cases.

Fields:

```yaml
intent_correct: yes | no
retrieved_assets_relevant: 1-5
boundaries_correct: yes | no
allowed_facts_correct: yes | no
style_guidance_correct: yes | no
missing_context: string
remove_items: list
approve_for_generation: yes | no
```

### 8.14 Dataset export approval

Purpose: approve items before they enter an export dataset.

Fields:

```yaml
export_type: rag_corpus | sft | dpo | eval | anti_pattern | gallery | memory_graph
quality_gate_passed: yes | no
boundary_gate_passed: yes | no
holdout_set: train | validation | test | exclude
notes: string
```

---

## 9. Multi-axis rating rubrics

Do not rate every asset on every axis. Each task type gets the minimum rubric it needs.

### 9.1 Voice evaluation rubric

```yaml
voice_fidelity:
  scale: 1-5
  question: "Does this sound like Charles rather than generic literary AI?"
mode_match:
  scale: 1-5
  question: "Is this the correct Charles mode?"
emotional_truth:
  scale: 1-5
  question: "Does feeling arrive indirectly and believably?"
concrete_detail:
  scale: 1-5
  question: "Are there objects, food, weather, rooms, light, roads, bodies?"
restraint:
  scale: 1-5
  question: "Does it avoid over-explaining or over-sentimentalizing?"
non_parody:
  scale: 1-5
  question: "Does it avoid cheap tics and costume punctuation?"
grounding:
  scale: 1-5
  question: "If it implies facts, are those facts supported or allowed by context?"
```

Suggested gate:

```text
SFT candidate requires:
  voice_fidelity >= 4
  emotional_truth >= 4
  non_parody >= 4
  restraint >= 4
  boundary_gate_passed = true
  no archival misattribution
```

### 9.2 Photo context rubric

```yaml
identity_confidence: exact | likely | unsure | unknown
date_confidence: exact | year | decade | unknown
emotional_importance: 1-5
memory_potential: 1-5
privacy_sensitivity: 1-5
gallery_potential: 1-5
```

### 9.3 Memoir segment rubric

```yaml
scene_integrity: 1-5
thematic_density: 1-5
voice_importance: 1-5
factual_clarity: 1-5
generative_safety: 1-5
```

### 9.4 Memory card rubric

```yaml
source_support: 1-5
emotional_texture: 1-5
relationship_importance: 1-5
retrieval_value: 1-5
simulation_safety: 1-5
uncertainty_clarity: 1-5
```

---

## 10. The gold voice edit workflow in detail

### 10.1 Why this is central

Adam knows Charles deeply enough to transform a near-miss model draft into a high-fidelity Charles voice output. That creates uniquely valuable training data.

The system should make this easy and repeatable.

### 10.2 Screen layout

```text
┌───────────────────────────────────────────────────────────┐
│ GOLD VOICE EDIT                                           │
│ Mode: father_to_adam | Truth: generative reconstruction   │
├───────────────────────┬───────────────────────────────────┤
│ Prompt / scenario      │ Retrieved context                 │
│                       │ - memory cards                    │
│                       │ - source facts                    │
│                       │ - photo records                   │
│                       │ - style rules                     │
├───────────────────────┴───────────────────────────────────┤
│ Model draft                                                │
│ [editable or locked comparison pane]                       │
├────────────────────────────────────────────────────────────┤
│ Adam gold edit                                             │
│ [large text editor]                                        │
├────────────────────────────────────────────────────────────┤
│ Ratings: fidelity / mode / emotional truth / detail / ...  │
│ Failure tags: too generic, therapy-like, no object, etc.   │
│ Export: SFT [x] DPO [x] Eval [x] Anti-pattern [x]          │
│ [Submit] [Save draft] [Skip] [Flag sensitive]              │
└────────────────────────────────────────────────────────────┘
```

### 10.3 What gets created

From one completed gold voice edit:

```text
generation_review
  stores ratings and failure-mode diagnosis

gold_voice_example
  stores Adam's corrected response

sft_candidate
  prompt -> Adam gold response

dpo_pair
  chosen = Adam gold response
  rejected = original model draft

eval_case
  prompt + target qualities + failure modes

anti_pattern
  captures what the draft did wrong

style_rule_candidate
  captures what Adam changed and why
```

### 10.4 Example transformation

Bad/weak model draft:

```text
Dear Adam,

I want you to know how meaningful our visit was. I feel very grateful for the time we shared...
```

Adam gold edit:

```text
Adam

house is too quiet now.
even the refrigerator sounds dramatic.

found your coffee cup in the sink.
good.
proof you were here.

call when you get in

dad
```

Diagnosis:

```yaml
failure_modes:
  - too_generic
  - too_therapy_like
  - too_emotionally_explicit
  - no_physical_carrier_of_feeling
positive_features:
  - ordinary object carries emotion
  - tenderness remains indirect
  - humor interrupts sadness
  - brief practical ending
```

---

## 11. Context builder and downstream RAG

### 11.1 Do not RAG directly over Drive at runtime

The downstream system should not usually query Drive live for every response. It should query CharlesOps’s operational asset library and retrieval indexes.

Drive remains the vault/source. CharlesOps is the production library.

### 11.2 Layered retrieval

Use multiple retrieval layers:

```text
Text RAG
  emails, journals, memoir passages, transcript segments, OCR, normalized docs

Memory RAG
  memory cards, timeline events, relationship patterns, theme summaries

Photo RAG
  photo records via captions, tags, people, places, Adam context notes,
  visual descriptions, image embeddings if implemented

Voice RAG
  mode-specific real voice samples, Adam gold edits, style rules, anti-patterns

Boundary RAG
  permissions and constraints retrieved/applied before generation or display
```

### 11.3 Context pack assembly pipeline

```text
user request or downstream job
  -> classify intent
  -> select truth mode
  -> select voice mode if needed
  -> apply boundary pre-filter
  -> retrieve candidate assets
  -> rerank by relevance, maturity, reliability, and permission
  -> assemble allowed facts
  -> include style guidance and anti-patterns
  -> attach media references if allowed
  -> create context_pack record
  -> pass to generator or gallery/memoir/search view
```

### 11.4 Truth modes

```yaml
archival:
  rule: "Only state what is supported by source material. Cite sources. Do not invent."
interpretive:
  rule: "Synthesize patterns, but mark uncertainty."
generative:
  rule: "Create new text in a voice mode using allowed memories/style/context. Disclose generation status where appropriate."
simulation:
  rule: "Emotionally plausible reconstruction. Must never pretend to be a quote or fact. Requires boundary clearance."
```

### 11.5 Example: photo reflection request

Request:

```text
What would Charles say about this photo?
```

System:

```text
classifies intent = photo_reflection
truth mode = generative_reconstruction
voice mode = father_to_adam or photo_memory_fragment
retrieves photo record
retrieves Adam invisible context note
retrieves linked Maine/fatherhood/food memory cards
retrieves relevant real emails and gold voice examples
retrieves anti-patterns
applies boundaries
builds context pack
generates response
labels as generated reconstruction, not quote
```

---

## 12. Database/domain model

The MVP should implement this model with enough structure to support downstream expansion. Use UUIDs internally or stable human-readable IDs; if both, store both.

### 12.1 Core tables

```text
assets
external_refs
asset_snapshots
object_files
derivatives
segments
entities
entity_aliases
memories
memory_sources
graph_edges
boundaries
tasks
annotations
annotation_versions
voice_modes
voice_samples
prompt_specs
context_packs
context_pack_items
generations
generation_reviews
gold_voice_examples
style_rules
anti_patterns
sft_candidates
dpo_pairs
eval_cases
dataset_exports
dataset_export_items
galleries
gallery_items
jobs
users
```

### 12.2 Assets

```sql
assets (
  id uuid primary key,
  human_id text unique,
  asset_type text not null,
  title text,
  original_filename text,
  mime_type text,
  source_system text,
  source_created_time timestamptz,
  source_modified_time timestamptz,
  import_status text,
  processing_status text,
  maturity_level text,
  created_at timestamptz,
  updated_at timestamptz
)
```

### 12.3 External references

```sql
external_refs (
  id uuid primary key,
  asset_id uuid references assets(id),
  source_system text not null,
  external_id text not null,
  uri text,
  parent_ref text,
  metadata jsonb,
  created_at timestamptz,
  unique(source_system, external_id)
)
```

### 12.4 Asset snapshots and object files

```sql
asset_snapshots (
  id uuid primary key,
  asset_id uuid references assets(id),
  snapshot_type text, -- original_copy | google_doc_export | revision_copy
  version integer,
  checksum_sha256 text,
  source_modified_time timestamptz,
  captured_at timestamptz,
  object_file_id uuid
)

object_files (
  id uuid primary key,
  storage_provider text, -- local | s3 | gcs | minio
  bucket text,
  object_key text,
  uri text,
  content_type text,
  byte_size bigint,
  checksum_sha256 text,
  metadata jsonb,
  created_at timestamptz
)
```

### 12.5 Derivatives

```sql
derivatives (
  id uuid primary key,
  asset_id uuid references assets(id),
  source_snapshot_id uuid references asset_snapshots(id),
  derivative_type text, -- thumbnail | display_image | ocr_text | transcript | waveform | markdown_export
  version integer,
  object_file_id uuid references object_files(id),
  status text,
  metadata jsonb,
  created_at timestamptz
)
```

### 12.6 Segments

```sql
segments (
  id uuid primary key,
  human_id text unique,
  asset_id uuid references assets(id),
  segment_type text,
  title text,
  text_content text,
  locator jsonb,
  start_time_ms integer,
  end_time_ms integer,
  source_truth_status text,
  maturity_level text,
  metadata jsonb,
  created_at timestamptz,
  updated_at timestamptz
)
```

### 12.7 Entities and graph edges

```sql
entities (
  id uuid primary key,
  human_id text unique,
  entity_type text,
  canonical_name text,
  description text,
  relationship_to_charles text,
  relationship_to_adam text,
  confidence text,
  created_at timestamptz,
  updated_at timestamptz
)

entity_aliases (
  id uuid primary key,
  entity_id uuid references entities(id),
  alias text,
  source text,
  confidence text
)

graph_edges (
  id uuid primary key,
  from_type text,
  from_id uuid,
  relation text,
  to_type text,
  to_id uuid,
  confidence text,
  evidence jsonb,
  created_by uuid,
  created_at timestamptz
)
```

### 12.8 Memories

```sql
memories (
  id uuid primary key,
  human_id text unique,
  title text,
  summary text,
  truth_status text,
  reliability text,
  date_start date,
  date_end date,
  emotional_tone text[],
  themes text[],
  open_questions jsonb,
  maturity_level text,
  created_at timestamptz,
  updated_at timestamptz
)

memory_sources (
  id uuid primary key,
  memory_id uuid references memories(id),
  source_type text, -- asset | segment | annotation | gold_voice_example
  source_id uuid,
  role text, -- supports | contradicts | illustrates | context
  confidence text,
  notes text
)
```

### 12.9 Boundaries

```sql
boundaries (
  id uuid primary key,
  target_type text,
  target_id uuid,
  privacy_level text,
  searchable boolean,
  retrievable_in_chat boolean,
  quotable boolean,
  summarizable boolean,
  usable_for_voice_context boolean,
  usable_for_sft boolean,
  usable_for_dpo boolean,
  usable_for_eval boolean,
  usable_for_gallery_public boolean,
  usable_for_gallery_family boolean,
  usable_for_simulation boolean,
  contains_living_person_sensitive_material boolean,
  redaction_required boolean,
  notes text,
  reviewed_by uuid,
  reviewed_at timestamptz,
  created_at timestamptz
)
```

### 12.10 Tasks and annotations

```sql
tasks (
  id uuid primary key,
  human_id text unique,
  task_type text,
  target_type text,
  target_id uuid,
  status text,
  priority integer,
  queue text,
  assigned_to uuid,
  reason_created text,
  input_payload jsonb,
  required_decisions jsonb,
  created_by text,
  created_at timestamptz,
  updated_at timestamptz,
  completed_at timestamptz
)

annotations (
  id uuid primary key,
  task_id uuid references tasks(id),
  annotator_id uuid,
  annotation_type text,
  decisions jsonb,
  notes text,
  creates_or_updates jsonb,
  created_at timestamptz
)
```

### 12.11 Prompt/generation/gold edit tables

```sql
prompt_specs (
  id uuid primary key,
  human_id text unique,
  prompt_type text,
  voice_mode text,
  truth_mode text,
  prompt_text text,
  success_criteria jsonb,
  metadata jsonb,
  created_at timestamptz
)

context_packs (
  id uuid primary key,
  human_id text unique,
  user_intent text,
  requested_voice_mode text,
  truth_mode text,
  allowed_facts jsonb,
  boundaries_snapshot jsonb,
  style_guidance jsonb,
  created_at timestamptz
)

context_pack_items (
  id uuid primary key,
  context_pack_id uuid references context_packs(id),
  item_type text,
  item_id uuid,
  role text,
  rank integer,
  included boolean,
  exclusion_reason text
)

generations (
  id uuid primary key,
  prompt_spec_id uuid references prompt_specs(id),
  context_pack_id uuid references context_packs(id),
  model_name text,
  model_parameters jsonb,
  output_text text,
  created_at timestamptz
)

generation_reviews (
  id uuid primary key,
  generation_id uuid references generations(id),
  reviewer_id uuid,
  ratings jsonb,
  failure_modes text[],
  notes text,
  created_at timestamptz
)

gold_voice_examples (
  id uuid primary key,
  human_id text unique,
  generation_id uuid references generations(id),
  prompt_spec_id uuid references prompt_specs(id),
  context_pack_id uuid references context_packs(id),
  voice_mode text,
  truth_status text,
  adam_gold_edit text,
  ratings jsonb,
  failure_modes text[],
  downstream_use jsonb,
  approved_by uuid,
  approved_at timestamptz,
  created_at timestamptz
)
```

### 12.12 Dataset exports

```sql
dataset_exports (
  id uuid primary key,
  human_id text unique,
  export_type text, -- rag | sft | dpo | eval | anti_pattern | gallery | memory_graph
  version text,
  status text,
  manifest jsonb,
  object_file_id uuid references object_files(id),
  created_at timestamptz
)

dataset_export_items (
  id uuid primary key,
  dataset_export_id uuid references dataset_exports(id),
  source_type text,
  source_id uuid,
  split text, -- train | validation | test | none
  payload jsonb,
  boundary_snapshot jsonb,
  quality_snapshot jsonb
)
```

---

## 13. Export formats

### 13.1 RAG corpus export

JSONL item:

```json
{
  "id": "CR_SEG_004812",
  "type": "memoir_scene",
  "text": "...",
  "source": {
    "asset_id": "CR_ASSET_000221",
    "title": "Behold III",
    "locator": {"section": "Maine / Adam / food"}
  },
  "metadata": {
    "people": ["Charles", "Adam"],
    "places": ["Maine"],
    "themes": ["fatherhood", "food_as_care"],
    "voice_mode": ["memoir_scene"]
  },
  "boundaries": {
    "quotable": true,
    "usable_for_voice_context": true,
    "usable_for_simulation": false
  }
}
```

### 13.2 SFT export

JSONL chat-style item:

```json
{
  "messages": [
    {
      "role": "system",
      "content": "Write in Charles's father-to-Adam mode. Use indirect tenderness, concrete objects, restraint, and practical endings. Do not claim generated text is archival."
    },
    {
      "role": "user",
      "content": "Write Adam a short note after he leaves Maine."
    },
    {
      "role": "assistant",
      "content": "Adam\n\nhouse is too quiet now..."
    }
  ],
  "metadata": {
    "source_gold_voice_example_id": "CR_GOLD_VOICE_000184",
    "truth_status": "adam_expert_reconstruction",
    "voice_mode": "father_to_adam"
  }
}
```

### 13.3 DPO export

```json
{
  "input": {
    "messages": [
      {"role": "system", "content": "Write in Charles's father-to-Adam mode..."},
      {"role": "user", "content": "Write Adam a short note after he leaves Maine."}
    ]
  },
  "preferred_output": "Adam\n\nhouse is too quiet now...",
  "non_preferred_output": "Dear Adam, I want you to know how meaningful...",
  "metadata": {
    "reason": ["too_generic", "too_therapy_like", "chosen_has_object_carried_feeling"]
  }
}
```

### 13.4 Eval export

```json
{
  "eval_id": "EVAL_000184",
  "prompt": "Write Adam a short note after he leaves Maine.",
  "voice_mode": "father_to_adam",
  "truth_mode": "generative_reconstruction",
  "success_criteria": {
    "voice_fidelity_min": 4,
    "emotional_truth_min": 4,
    "non_parody_min": 4,
    "must_include": ["concrete object carrying emotion"],
    "must_avoid": ["therapy language", "over-explanation", "fake profundity"]
  },
  "gold_reference_id": "CR_GOLD_VOICE_000184"
}
```

### 13.5 Gallery feed export

```json
{
  "gallery_item_id": "GAL_ITEM_000144",
  "scope": "family_private",
  "title": "Maine, late 1980s",
  "image_url": "signed-or-public-url",
  "thumbnail_url": "signed-or-public-url",
  "display_caption": "Charles and Adam during a summer visit in Maine.",
  "memory_caption": "Adam remembers this period as connected to food and practical care.",
  "linked_memories": ["CR_MEMORY_000077"],
  "boundaries": {
    "public_safe": false,
    "family_private": true
  }
}
```

---

## 14. UI product specification

### 14.1 Core screens

#### Workbench

Primary daily task UI.

Features:

- queue selector,
- current task card,
- asset/source preview,
- decision fields,
- rating widgets,
- notes/context field,
- boundary controls,
- submit/skip/flag/create-follow-up,
- keyboard shortcuts,
- session progress.

#### Asset browser

Search and inspect asset records.

Features:

- filters by type, maturity, boundary, source, person, place, theme,
- preview photos/docs/audio,
- see provenance, object files, derivatives,
- see linked tasks, annotations, memories, gallery items.

#### Memory graph browser

Inspect memory cards and links.

Features:

- memory card list/detail,
- linked sources,
- linked photos,
- related people/places/themes,
- reliability and open questions,
- boundary status.

#### Gold voice edit studio

Dedicated prompt/draft/edit/rate/export screen.

Features:

- prompt/scenario pane,
- voice mode selector,
- truth mode selector,
- context pack pane,
- model draft pane,
- Adam gold editor,
- rating rubric,
- failure tags,
- export flags,
- anti-pattern/style-rule extraction.

#### Dataset export console

Build and inspect exports.

Features:

- export type selector,
- candidate list,
- quality/boundary gate status,
- train/validation/test assignment,
- manifest preview,
- JSONL/YAML download.

#### Gallery curation console

Prepare photo/audio/text items for display.

Features:

- image grid,
- public/family/private filters,
- caption editor,
- sequence builder,
- memory links,
- signed/public URL status.

### 14.2 Workbench task layout

```text
┌────────────────────────────────────────────────────────────┐
│ Queue: Photos needing context       Session: 17 completed  │
├────────────────────────────────────┬───────────────────────┤
│ Asset preview                       │ Machine/source hints  │
│ photo / text / audio transcript     │ metadata / guesses    │
├────────────────────────────────────┴───────────────────────┤
│ Required decisions                                          │
│ task-specific fields                                        │
├────────────────────────────────────────────────────────────┤
│ What would a stranger miss? / notes / context               │
├────────────────────────────────────────────────────────────┤
│ Boundaries and downstream eligibility                       │
├────────────────────────────────────────────────────────────┤
│ Submit | Save draft | Skip | Flag sensitive | Follow-up     │
└────────────────────────────────────────────────────────────┘
```

### 14.3 Dashboard metrics

Archive health:

```text
assets imported
assets mirrored
assets extracted
assets reviewed
assets boundary-cleared
assets downstream-ready
```

Voice health:

```text
real voice samples by mode
Adam gold edits by mode
SFT candidates approved
DPO pairs approved
eval cases created
anti-patterns identified
common failure modes
average voice fidelity score
```

Gallery health:

```text
photos mirrored
photos reviewed
family-private gallery candidates
public candidates
captioned items
curated sequences
```

Task health:

```text
ready tasks
blocked tasks
sensitive holds
oldest ready tasks
highest-value queues
session throughput
```

---

## 15. API specification

### 15.1 Assets

```text
GET    /api/assets
POST   /api/assets
GET    /api/assets/{id}
PATCH  /api/assets/{id}
GET    /api/assets/{id}/preview
GET    /api/assets/{id}/annotations
GET    /api/assets/{id}/tasks
GET    /api/assets/{id}/memories
POST   /api/assets/{id}/mirror
POST   /api/assets/{id}/extract
```

### 15.2 Object files and derivatives

```text
GET    /api/object-files/{id}/signed-url
GET    /api/assets/{id}/derivatives
POST   /api/assets/{id}/derivatives
```

### 15.3 Tasks

```text
GET    /api/tasks
GET    /api/tasks/next?queue=photo_context
GET    /api/tasks/{id}
PATCH  /api/tasks/{id}
POST   /api/tasks/{id}/submit
POST   /api/tasks/{id}/skip
POST   /api/tasks/{id}/flag
POST   /api/tasks/{id}/follow-up
```

### 15.4 Annotations

```text
GET    /api/annotations/{id}
POST   /api/annotations
GET    /api/targets/{target_type}/{target_id}/annotations
```

### 15.5 Entities and memories

```text
GET    /api/entities
POST   /api/entities
PATCH  /api/entities/{id}
POST   /api/entities/merge

GET    /api/memories
POST   /api/memories
GET    /api/memories/{id}
PATCH  /api/memories/{id}
POST   /api/memories/{id}/sources
POST   /api/graph-edges
```

### 15.6 Boundaries

```text
GET    /api/boundaries/{target_type}/{target_id}
POST   /api/boundaries
PATCH  /api/boundaries/{id}
```

### 15.7 Prompt/generation/gold edit

```text
GET    /api/prompt-specs
POST   /api/prompt-specs
POST   /api/context-packs/build
GET    /api/context-packs/{id}
POST   /api/generations
GET    /api/generations/{id}
POST   /api/generations/{id}/review
POST   /api/gold-voice-examples
GET    /api/gold-voice-examples
```

### 15.8 Exports

```text
GET    /api/dataset-exports
POST   /api/dataset-exports/build
GET    /api/dataset-exports/{id}
GET    /api/dataset-exports/{id}/download
```

### 15.9 Gallery

```text
GET    /api/galleries
POST   /api/galleries
GET    /api/galleries/{id}/items
POST   /api/galleries/{id}/items
PATCH  /api/gallery-items/{id}
```

---

## 16. Google Drive and source intake

### 16.1 Drive’s role

Google Drive is a source vault and intake source. CharlesOps should:

- connect to Drive,
- let Adam select files/folders,
- store Drive file IDs and metadata,
- copy blob files into CharlesOps storage,
- export Google Workspace documents into useful derivative formats,
- checksum mirrored/exported files,
- create asset records and tasks.

### 16.2 MVP intake

MVP should support mock/local import first:

```text
/import_samples/photos
/import_samples/text
/import_samples/audio
```

Then add real Drive connector behind an interface.

### 16.3 Drive connector responsibilities

```text
list/select files
retrieve file metadata
store external_refs
mirror blob files
export Google Docs/Sheets/Slides
create asset_snapshots
create object_files
create derivatives if needed
create tasks
```

### 16.4 Drive source metadata to preserve

```yaml
source_system: google_drive
drive_file_id: string
drive_name: string
drive_mime_type: string
drive_created_time: string
drive_modified_time: string
drive_parents: list
drive_web_view_link: string
drive_md5_checksum: string | null
drive_size: integer | null
```

### 16.5 Official implementation notes

- Use Drive file IDs as external references.
- Blob files can be downloaded via Drive API `files.get` with `alt=media`.
- Google Workspace files should be exported via `files.export` into formats such as Markdown, plain text, PDF, or DOCX as appropriate.
- Google Picker can be used in the web app to let Adam select Drive files/folders with OAuth-based permission.

References:

- Google Drive API: Download and export files — https://developers.google.com/workspace/drive/api/guides/manage-downloads
- Google Drive API: Files resource — https://developers.google.com/workspace/drive/api/reference/rest/v3/files
- Google Picker overview — https://developers.google.com/workspace/drive/picker/guides/overview

---

## 17. Object storage strategy

### 17.1 MVP

Use local storage:

```text
storage/
  raw/
  exports/
  derivatives/
  thumbs/
  display/
  transcripts/
```

Store object paths in `object_files`.

### 17.2 Production

Use S3-compatible storage, Google Cloud Storage, or equivalent.

Object examples:

```text
raw/CR_ASSET_000421/original.jpg
exports/CR_ASSET_000221/google_doc_export.md
derivatives/CR_ASSET_000421/thumb_512.jpg
derivatives/CR_ASSET_000421/display_2048.jpg
derivatives/CR_ASSET_000778/transcript_v1.json
```

### 17.3 Metadata

Each object file should store:

```yaml
content_type: image/jpeg
byte_size: 8429123
checksum_sha256: "..."
source_asset_id: CR_ASSET_000421
derivative_type: original | thumbnail | display | transcript | ocr | export
created_at: timestamp
```

### 17.4 Why not store large binaries in Postgres rows by default

Postgres can store binary data, but a photo-rich, audio-rich archive will be cleaner if binary media live in object storage and Postgres stores metadata/pointers.

This supports:

- image resizing,
- signed URLs,
- CDN/gallery delivery,
- easier backups,
- storage lifecycle rules,
- large audio/photo handling,
- clearer separation of media and metadata.

---

## 18. Voice modes and style system

### 18.1 Global Charles voice card

```yaml
essence: |
  Charles's voice carries tenderness indirectly through objects, food,
  weather, errands, irritation, jokes, and sudden remembered pain.

core_moves:
  - Notices physical detail before naming emotion.
  - Lets humor interrupt grief.
  - Distrusts polished abstraction.
  - Moves associatively through memory.
  - Can be abrupt, but not empty.
  - Shows love through practical concern.

recurring_material:
  - food
  - roads
  - Maine
  - photography
  - Jewish / European memory
  - money anxiety
  - mothers and fathers
  - weather
  - domestic rooms
  - aging bodies
  - absurd public spaces

avoid:
  - generic therapy language
  - overly smooth inspirational prose
  - constant ellipses
  - forced Holocaust gravity
  - mystical overstatement
  - explaining the emotion too directly
  - parody punctuation
```

### 18.2 Voice mode cards

Each mode should have:

```yaml
mode: father_to_adam
description: "Tenderness through practical concern, jokes, food, money, weather, small observations."
use_when:
  - writing to Adam
  - brief note
  - post-visit reflection
  - indirect tenderness
features:
  - short paragraphs
  - direct address
  - ordinary object carries emotion
  - humor undercuts sadness
  - practical ending
avoid:
  - generic sentimentality
  - therapy language
  - polished essay form
  - too much explanation
```

Required mode cards:

```text
casual_email
father_to_adam
memoir_scene
argument
comic_observation
grief_memory
photography_reflection
philosophical_fragment
spoken_interview
logistical_note
```

---

## 19. Anti-pattern library

Bad outputs are valuable if classified.

Examples:

```yaml
generic_therapy_language:
  examples:
    - "I want you to know how deeply meaningful our connection is."
    - "This was a healing moment for us both."
  why_wrong: "Too modern therapeutic, too smooth, too emotionally explicit."

fake_old_man_poetry:
  examples:
    - "The rain remembers what the heart forgets."
  why_wrong: "Poetic but decorative; not grounded in Charles's physical observational logic."

overdid_ellipses:
  examples:
    - "Adam... I was thinking... maybe..."
  why_wrong: "Turns punctuation into costume."

forced_historical_gravity:
  examples:
    - "As my people suffered..."
  why_wrong: "Introduces grave historical material without prompt/source need."

dadbot_sentimentality:
  examples:
    - "I love you more than words can say."
  why_wrong: "May be emotionally true, but not his likely expressive mechanism in this mode."
```

---

## 20. Recommended technical stack

### 20.1 MVP stack

```text
Frontend:
  Next.js + React + TypeScript
  Tailwind or CSS modules

Backend:
  FastAPI + Python
  SQLAlchemy or SQLModel
  Pydantic schemas

Database:
  Postgres
  pgvector optional behind feature flag

Migrations:
  Alembic

Jobs:
  simple jobs table + worker process for MVP
  later Celery/RQ/Dramatiq/Temporal

Storage:
  local filesystem object store for MVP
  S3/GCS/MinIO adapter interface

Auth:
  single-user local auth first
  later OAuth/family roles

Exports:
  JSONL, YAML, Markdown manifests

Testing:
  pytest backend
  Playwright frontend smoke tests
```

### 20.2 Suggested monorepo

```text
charlesops/
  README.md
  AGENTS.md
  docker-compose.yml
  .env.example

  apps/
    web/
      package.json
      src/
        app/
        components/
        lib/
        styles/
    api/
      pyproject.toml
      app/
        main.py
        db/
        models/
        schemas/
        routers/
        services/
        workers/
        exports/
        fixtures/
        tests/

  docs/
    charlesops_v1_master_architecture_and_build_spec.md
    schemas/
    task_types/
    voice_modes/
    exports/

  storage/
    raw/
    exports/
    derivatives/
    thumbs/
    display/
    transcripts/

  scripts/
    seed_demo_data.py
    validate_exports.py
    build_sample_exports.py
```

---

## 21. Implementation phases

### Phase 0 — Repo scaffold

Deliver:

- monorepo structure,
- Docker Compose with Postgres,
- FastAPI health route,
- Next.js shell,
- seed demo data,
- README and AGENTS.md.

Acceptance:

```text
docker compose up works
web loads
api health check works
database migrations run
seed data loads
```

### Phase 1 — Core domain model

Deliver:

- database tables for assets, object files, snapshots, derivatives, boundaries, tasks, annotations, entities, memories, graph edges,
- Pydantic schemas,
- API CRUD endpoints,
- seed examples for photo/text/gold voice draft.

Acceptance:

```text
assets can be created and viewed
tasks can be created and completed
annotations persist
boundaries persist
memory cards can link to assets/segments
```

### Phase 2 — Workbench MVP

Deliver:

- queue selector,
- task detail view,
- task submit flow,
- support task types:
  - asset_triage,
  - photo_context,
  - text_segment_review,
  - boundary_review,
  - email_voice_sample,
  - gold_voice_edit.

Acceptance:

```text
Adam can complete a queue of seeded tasks
submissions create annotations
asset/memory/boundary records update
completed tasks leave queue
```

### Phase 3 — Asset mirroring and derivatives

Deliver:

- local import/mirror pipeline,
- object file records,
- thumbnail generation for images,
- text import and segmentation,
- mock Drive connector interface,
- real Drive connector scaffold if credentials available.

Acceptance:

```text
sample files import into storage/raw
object_files records created
photo thumbnails created
text segments created
follow-up tasks generated
```

### Phase 4 — Gold voice edit and training asset compiler

Deliver:

- prompt specs,
- generations,
- generation reviews,
- gold voice examples,
- anti-patterns,
- style rules,
- SFT/DPO/eval candidate generation.

Acceptance:

```text
one model draft + Adam edit creates:
  gold_voice_example
  sft_candidate
  dpo_pair
  eval_case
  anti_pattern candidate
```

MVP can use manually entered model drafts; live model generation can be added later.

### Phase 5 — Context pack builder

Deliver:

- manual/contextual context-pack builder,
- simple retrieval over segments/memories/voice examples,
- boundary filtering,
- context pack review task.

Acceptance:

```text
context pack can be built for a prompt
only allowed assets are included
context pack can feed gold voice edit workflow
```

### Phase 6 — Export console

Deliver:

- export manifest builder,
- JSONL/YAML export download,
- export approval task,
- train/validation/test split tagging.

Acceptance:

```text
RAG, SFT, DPO, eval, anti-pattern, memory graph exports can be generated from approved items
boundary snapshots included
```

### Phase 7 — Gallery prototype

Deliver:

- gallery item records,
- image grid,
- family/private/public candidate filters,
- display captions,
- gallery feed export.

Acceptance:

```text
reviewed photos can become gallery items
family-private gallery feed can be exported
public items require explicit public approval
```

---

## 22. MVP acceptance criteria

The first real MVP is successful when Adam can:

1. Import or seed assets.
2. Mirror assets into local object storage.
3. See task queues.
4. Complete photo context, text segment, boundary, email voice, and gold voice tasks.
5. Store annotations and boundaries.
6. Create or update memory cards.
7. Produce at least:
   - 20 reviewed asset records,
   - 10 photo records with invisible context,
   - 10 reviewed text segments,
   - 5 memory cards,
   - 10 gold voice examples,
   - 10 DPO pairs,
   - 10 SFT candidates,
   - 10 eval cases,
   - 10 anti-pattern entries.
8. Export datasets as JSONL/YAML.
9. Preserve truth status and boundaries in every export.

---

## 23. Security, privacy, and dignity

### 23.1 Local-first default

Start local-first. Real cloud deployment should come after schemas and workflows are stable.

### 23.2 Sensitive material

Any asset can be marked:

```text
family_private
sensitive_living_people
intimate
sealed
```

Sealed assets should not be used for retrieval, training, gallery, or simulation.

### 23.3 Export gates

Before export, every item must pass:

```text
quality gate
boundary gate
truth-status gate
redaction gate if needed
```

### 23.4 Auditability

For every downstream output, the system should be able to answer:

```text
Which assets influenced this?
Which annotations permitted it?
Which boundary snapshot applied?
Was this source text, Adam memory, model inference, or generated reconstruction?
```

---

## 24. Official reference notes

These implementation notes are based on current public documentation and should be verified during implementation.

### Google Drive

- Drive file metadata includes fields such as `id`, `name`, `createdTime`, and `modifiedTime`.
- Blob file content can be downloaded using `files.get` with `alt=media`.
- Google Workspace documents can be exported using `files.export`.
- Google Picker can let users select/upload Drive files in a web app with OAuth-based access.

References:

- https://developers.google.com/workspace/drive/api/reference/rest/v3/files
- https://developers.google.com/workspace/drive/api/guides/manage-downloads
- https://developers.google.com/workspace/drive/picker/guides/overview

### Object storage

- Object storage is appropriate for file data plus metadata such as content type, checksums, custom metadata, and generation/version identifiers.

Reference:

- https://cloud.google.com/storage/docs/metadata

### OpenAI retrieval and optimization

- Retrieval/vector stores support semantic search and file search over indexed files.
- File search combines semantic and keyword search over uploaded/vector-store-backed files.
- Supervised fine-tuning should start from representative examples of “good” outputs.
- Evals should be set up before serious fine-tuning investment.
- DPO uses preferred/non-preferred response pairs.

References:

- https://platform.openai.com/docs/guides/retrieval
- https://platform.openai.com/docs/guides/tools-file-search
- https://platform.openai.com/docs/guides/supervised-fine-tuning
- https://platform.openai.com/docs/guides/fine-tuning

---

## 25. First Codex prompt

Paste this to Codex after adding this document to the repo.

```text
You are building CharlesOps, a single-user human-in-the-loop production asset library and annotation engine for a large personal archive.

Read docs/charlesops_v1_master_architecture_and_build_spec.md carefully and treat it as the canonical product/engineering spec.

Your first task is Phase 0 + Phase 1 scaffolding only. Do not build a chatbot. Do not call real fine-tuning APIs. Do not implement live model generation yet. Do not mutate raw source files.

Build a monorepo with:
- apps/web: Next.js + React + TypeScript workbench shell
- apps/api: FastAPI + SQLAlchemy/SQLModel + Alembic
- Postgres via docker-compose
- local object storage folders under storage/
- seed demo data for assets, tasks, annotations, boundaries, memories, prompt/generation/gold-edit records

Implement database models and migrations for at least:
assets, external_refs, asset_snapshots, object_files, derivatives, segments, entities, entity_aliases, memories, memory_sources, graph_edges, boundaries, tasks, annotations, prompt_specs, context_packs, context_pack_items, generations, generation_reviews, gold_voice_examples, anti_patterns, style_rules, sft_candidates, dpo_pairs, eval_cases, dataset_exports, dataset_export_items, galleries, gallery_items.

Implement API endpoints for:
- health
- assets list/detail/create/update
- tasks list/next/detail/submit/skip/flag
- annotations create/list
- boundaries create/update/get
- memories create/update/list/detail
- prompt specs/generations/gold voice examples
- dataset export stub

Implement the web shell with:
- dashboard
- task queue selector
- task detail workbench
- generic task submit flow
- task-specific forms for asset_triage, photo_context, text_segment_review, boundary_review, email_voice_sample, and gold_voice_edit

Seed at least:
- 3 assets: photo, text, audio
- 6 tasks, one for each MVP task type
- 2 memories
- 1 context pack
- 1 generation draft
- 1 gold voice edit example

Acceptance:
- docker compose up starts DB/API/Web
- migrations run
- seed data loads
- web can display tasks
- submitting a task creates an annotation and updates task status
- gold voice edit submission creates or updates gold_voice_example, sft_candidate, dpo_pair, eval_case, and anti_pattern records
- basic JSONL export endpoint returns SFT and DPO examples from approved candidates

Keep the code simple, inspectable, typed, and testable. Create README setup instructions and an AGENTS.md with project rules.
```

---

## 26. AGENTS.md template

```markdown
# AGENTS.md — CharlesOps

## Mission

Build CharlesOps: a human-in-the-loop production asset library and annotation engine for turning a large personal archive into downstream-ready memory, voice, retrieval, training, eval, and gallery assets.

## Canonical spec

Read `docs/charlesops_v1_master_architecture_and_build_spec.md` before making architectural changes.

## Non-negotiables

- Do not build a chatbot first.
- Do not mutate raw source files.
- Do not collapse source truth, Adam memory, model inference, and generated reconstruction.
- Do not use sensitive/private assets in exports without boundary clearance.
- Do not store large media as ordinary DB row blobs by default; use object storage paths.
- Do not call fine-tuning APIs in MVP.
- Keep schemas explicit and migrations versioned.
- Every task completion should create durable annotations and downstream-useful records.

## Build order

1. Core schema.
2. Task engine.
3. Workbench UI.
4. Asset mirror/import.
5. Gold voice edit workflow.
6. Context pack builder.
7. Export compiler.
8. Gallery prototype.

## Truth statuses

Use these labels consistently:

- archival_source
- spoken_source
- adam_memory
- adam_inference
- system_inference
- model_generated
- adam_expert_reconstruction
- interpretive_synthesis

## Boundary rules

All assets/segments/memories/examples require boundary fields before downstream export.

## Tests

Add tests for:

- task lifecycle transitions,
- boundary gate logic,
- gold voice edit export creation,
- dataset export manifests,
- asset mirror records,
- context pack permission filtering.
```
