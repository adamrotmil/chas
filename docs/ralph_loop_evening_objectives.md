# CharlesOps Ralph Loop Objectives

Status: draft for collaborative approval
Reference pattern: https://github.com/vercel-labs/ralph-loop-agent
Canonical product spec: `docs/charlesops_v1_master_architecture_and_build_spec.md`

## Purpose

This document defines the objectives, strict acceptance tests, and loop rules for a long-running CharlesOps product-design implementation session.

The loop must not start until Adam explicitly approves this document or an edited version of it.

The goal is not to do a quick polish pass. The goal is to run an iterative agent loop that repeatedly:

1. selects the next unmet objective,
2. writes a small plan,
3. implements the smallest useful increment,
4. runs strict tests,
5. treats failures as signal,
6. revises the plan from the test output,
7. repeats until the phase acceptance tests truly pass or a real blocker is reached.

## Non-Negotiable Loop Rules

- Do not mutate raw source files. Work only with imported/mirrored copies.
- Do not call fine-tuning APIs.
- Do not mark model-generated material as archival source.
- Do not mark generated Charles voice as final/authentic unless it is source-verbatim or Adam-reviewed.
- Do not use "record exists" or HTTP 200 alone as a passing test when the product goal requires specific content.
- Do not accept empty strings, fallback prompts, placeholder drafts, or malformed YAML as passing output.
- Do not hide failing tests by loosening assertions.
- Do not collapse source truth, Adam memory, Adam inference, system inference, model generation, and Adam expert reconstruction.
- Do not export private/sensitive/sealed material unless boundary clearance explicitly allows it.
- Do not stop after a cosmetic UI change when the objective requires durable downstream records.
- Keep all new tests deterministic unless they are explicitly marked as advisory model-eval checks.

## False Positive Prevention

Every objective below uses these pass rules unless stated otherwise:

- Count checks must assert exact expected counts for fixture-driven tests.
- Content checks must assert exact values for system, user/prompt, assistant/chosen/rejected, and line breaks.
- YAML/JSONL checks must parse the exported artifact and compare parsed structure against expected records.
- DB checks must verify the durable downstream rows, not just the API response body.
- Provenance checks must verify source asset id, source segment/span id where available, truth status, synthetic flag, voice mode, boundary snapshot, and export status.
- UI label checks must verify visible text or serialized UI data, not just component existence.
- LLM quality checks cannot be the sole pass condition. They can fail the loop, but they cannot alone prove authenticity.
- Random sampling is allowed only as an additional audit. It cannot replace deterministic fixture tests.

## Required Baseline Tests

Run these before and after each meaningful implementation pass:

```bash
docker compose run --rm --no-deps api pytest -q
npm run typecheck --prefix apps/web
```

When frontend behavior changes, also verify:

```bash
WEB_PORT=3003 docker compose up -d --force-recreate web
curl -I http://localhost:3003/
```

When API behavior changes and Docker image code is baked into the container, rebuild the API image before runtime verification:

```bash
docker compose build api
docker compose up -d --force-recreate api
```

## Phase Sequence

Work in this order:

1. Training spine: source artifact -> generated prompt pairs -> human review -> training-ready export.
2. Photo memory spine: photo import/preview -> contextual annotation -> embedding-ready memory records.
3. Proof milestone: at least 200 inspectable prompt-response pairs that demonstrate the workflow.

Do not jump to the 200-pair milestone until the training spine can produce trustworthy SFT/DPO artifacts from small fixtures.

---

# Phase 1: Training Spine

This phase covers Objectives 1, 2, and 4.

## Objective 1: Generate High-Quality Prompt/Response Suggestions From Source Artifacts

User story:

As a user, I want the system to generate high quality prompt and response suggestions based on source artifacts, including YAML examples, Word docs, emails, and photographs.

Important truth rule:

For imported YAML examples that already contain prompt/response pairs, "high quality" can be tested as lossless extraction. For Word docs, emails, and photographs, "high quality" means the system creates well-structured, source-grounded candidate tickets that remain marked as candidates until Adam reviews them.

### Goal 1.1: Lossless YAML Pair Intake

The system should parse YAML SFT/DPO examples into one prompt-pair ticket per natural pair.

Acceptance tests:

- Fixture: YAML file with 20 SFT examples and 5 DPO examples.
- Generate Pairs creates exactly 25 Prompt Pair tickets.
- Each SFT ticket contains exact `system`, `user`, and `assistant` values from the fixture.
- Each DPO ticket contains exact `system`, `prompt`, `chosen`, and `rejected` values from the fixture.
- The first ticket is `Pair 001`, the second is `Pair 002`, with no duplicate ordinals.
- No generated prompt contains fallback text such as:
  - `Tell me about filename`
  - `Tell me about this`
  - `Write back about this memory`
  unless that exact text is present in the fixture.
- Multiline assistant content preserves exact line breaks and terminal closings such as `dad`.
- Ticket payload includes:
  - source asset id,
  - source segment/chunk id where available,
  - source prompt-pair index,
  - source excerpt,
  - artifact mode,
  - truth status,
  - synthetic flag,
  - voice mode.

Strict failure examples:

- 24 or 26 tickets from the 25-pair fixture is failure.
- A ticket with correct text but missing provenance is failure.
- A fallback prompt is failure even if the response is nonempty.
- Arbitrary line-count chunking is failure for a structured YAML fixture.

### Goal 1.2: Natural Segmentation For Unstructured Text Sources

The system should segment Word docs, plain text, and emails into complete thought units suitable for prompt-pair drafting.

Acceptance tests:

- Fixture: text document with clearly separated email replies, memoir sections, and short note fragments.
- Segmentation creates chunks at natural boundaries, not arbitrary fixed line counts.
- Each chunk contains a complete thought or complete email/note.
- Adjacent chunks do not duplicate more than 10% of their text unless the source itself duplicates it.
- Each chunk stores a locator, character range, and source asset id.
- A chunk that is too large for a single prompt pair is marked `needs_split` rather than silently sent forward.
- A chunk that is too small or contextless is marked `needs_context` rather than exported.

Suggested deterministic test shape:

- Use a fixture with 8 known natural sections.
- Assert exactly 8 primary chunks.
- Assert exact first and last 40 characters for each chunk.
- Assert no chunk crosses a known section delimiter.

### Goal 1.3: LLM-Assisted Pair Generation From Reviewed Text

The system should use reviewed source text, human spans/coding, voice mode, and existing gold examples to draft candidate pairs.

Acceptance tests:

- Given reviewed chunks with Prompt and Response source spans, Generate Pairs creates ticket prompts from Prompt spans and responses from Response spans.
- Given reviewed chunks without explicit spans, Generate Pairs may use LLM generation, but the ticket must be marked `model_generated` or `adam_expert_reconstruction_candidate`, not archival.
- Generation request metadata records:
  - model name,
  - reasoning effort,
  - no-live-call/live-call status,
  - source text used,
  - voice mode,
  - prompt instructions version.
- If live model calls are disabled, output is clearly a scaffold/candidate and cannot be marked approved.
- If live model calls are enabled, model output must still be `needs_adam_review`.

Strict failure examples:

- A model-generated response stored as `archival_source` is failure.
- A generated response without source provenance is failure.
- A generated ticket without model metadata is failure.

### Goal 1.4: Photo-Informed Prompt Suggestions

The system should create prompt-pair candidates from reviewed photo metadata and contextual annotations.

Acceptance tests:

- Fixture: photo asset with reviewed description, people/place/date/theme tags, and Adam context.
- Generate Pairs creates at least one photo-grounded prompt-pair candidate.
- Candidate prompt references the memory question, not just the filename.
- Candidate payload includes photo asset id, photo context profile id, boundary snapshot, and embedding input text.
- Candidate truth status is `adam_memory`, `adam_inference`, `system_inference`, or `adam_expert_reconstruction` as appropriate, never `archival_source` unless the text is truly a source caption/transcription.

Strict failure examples:

- Prompt is `Tell me about IMG_1234.jpg`.
- Photo candidate does not link back to the photo asset.
- Photo candidate ignores boundary fields.

---

## Objective 2: Easily Review And Modify SFT/DPO Prompt Pairs

User story:

As a user, I want to easily review and modify prompt-and-response pairs, in either SFT or DPO format, so that I can train a downstream language model on the results successfully.

### Goal 2.1: One Ticket Per Pair

Prompt Pairs should behave like decomposed tickets, not one giant source document.

Acceptance tests:

- After Generate Pairs on a 25-pair fixture, Prompt Pairs shows 25 tickets.
- Selecting Pair 001 shows only Pair 001 content in the main editor.
- Selecting Pair 002 shows only Pair 002 content.
- Ticket title contains stable ordinal and prompt preview.
- Ticket chips do not duplicate the same status label.

Strict failure examples:

- One ticket contains the whole source document.
- Pair 001 and Pair 002 show the same content.
- UI shows duplicate `Previewable` chips for one ticket.

### Goal 2.2: SFT Plain/YAML Editing

SFT editing should support both low-friction Plain mode and full YAML mode.

Acceptance tests:

- In SFT Plain mode, editing assistant Content updates the Export Artifacts YAML preview.
- In SFT Plain mode, adding `dad` as a final line preserves it exactly in the preview.
- In SFT YAML mode, editing the `system`, `user`, or `assistant` content updates the saved decisions.
- YAML mode preserves indentation on Enter and supports Tab/Shift-Tab behavior.
- Switching Plain -> YAML -> Plain does not lose content.
- Autosaved draft reloads with the same editing mode and content.

Strict failure examples:

- Plain edit updates the textarea but not the export preview.
- YAML edit visually changes content but saved decisions remain stale.
- Switching modes loses line breaks.

### Goal 2.3: DPO Plain/YAML Editing

DPO editing should support side-by-side review and full YAML editing.

Acceptance tests:

- DPO Plain mode shows Chosen and Rejected side by side.
- Editing Chosen updates DPO export preview.
- Editing Rejected updates DPO export preview.
- DPO YAML mode parses `system`, `prompt`, `chosen`, and `rejected`.
- Switching Plain -> YAML -> Plain preserves both Chosen and Rejected exactly.
- Rubric context for Rejected is saved as DPO reason context.

Strict failure examples:

- Chosen and Rejected are swapped.
- Rejected rubric notes are discarded.
- DPO export contains an empty rejected response when the UI showed one.

### Goal 2.4: Rubric And Quality Gate Behavior

Rubrics should document whether a pair is ready, candidate, or blocked.

Acceptance tests:

- `No issues` on required rubric fields permits approved export if boundary fields allow it.
- `Minor issues` preserves the draft but marks export status as candidate or needs review according to product rule.
- `Major issues` on privacy/export safety blocks downstream SFT/DPO export.
- Rubric notes persist and reload.
- Rejected-side DPO rubric notes become reason metadata.

Strict failure examples:

- Major privacy issue still creates approved export item.
- Rubric status is visible in UI but missing from DB.
- DPO reason array is empty when rejected-side issues were marked.

---

## Objective 4: Output Training-Ready Material For Language Model Training

User story:

As a user, I want the system to achieve a final step of outputting material that I can use to train a language model to speak in Charles' authentic voice, based on best practices for language model training.

### Goal 4.1: SFT Export Correctness

Acceptance tests:

- Submitting an approved SFT pair creates:
  - `gold_voice_example`,
  - `sft_candidate`,
  - export-ready quality gate,
  - embedding record or embedding-plan record.
- Stored SFT messages exactly match:
  - role `system`,
  - role `user`,
  - role `assistant`.
- Message contents exactly match Export Artifacts preview after YAML parsing.
- Metadata includes:
  - source gold voice example id,
  - truth status,
  - voice mode,
  - synthetic flag,
  - boundary snapshot,
  - quality snapshot.

Strict failure examples:

- Export preview and stored SFT candidate disagree.
- SFT candidate lacks system prompt.
- Export marks generated material as archival source.

### Goal 4.2: DPO Export Correctness

Acceptance tests:

- Submitting an approved DPO pair creates:
  - `gold_voice_example`,
  - `dpo_pair`,
  - DPO reason metadata,
  - export-ready quality gate.
- Stored prompt, chosen, and rejected exactly match Export Artifacts preview after YAML parsing.
- Chosen and rejected are never identical.
- Rejected is nonempty for export-ready DPO.
- DPO reason includes rejected-side rubric issue notes or explicit failure modes.

Strict failure examples:

- Empty rejected response passes.
- Chosen and rejected are swapped or identical.
- DPO reason is empty despite marked rejected-side issues.

### Goal 4.3: Dataset Export Manifest

Acceptance tests:

- Export compiler creates a dataset export record and dataset export items.
- Manifest includes:
  - export type,
  - version,
  - generated timestamp,
  - item count,
  - filters used,
  - excluded count and reasons,
  - source ids,
  - boundary policy snapshot,
  - quality policy snapshot.
- Export item payloads parse as valid JSONL/YAML according to export type.
- Boundary-blocked items are excluded and listed with reason.
- Re-running the same export inputs produces stable item count and stable item ids/order.

Strict failure examples:

- Export file exists but manifest is missing.
- Blocked item appears in export payload.
- Export count differs across identical runs.

### Goal 4.4: Training Best-Practice Guardrails

Acceptance tests:

- SFT dataset includes system/user/assistant structure only.
- DPO dataset includes prompt/input, preferred/chosen, non-preferred/rejected.
- Metadata is present but not injected into assistant text.
- Holdout/eval split exists or is explicitly marked as not yet configured.
- Duplicate examples are detected and excluded or flagged.
- No example has empty prompt, empty response, placeholder draft, or filename-only prompt.

Strict failure examples:

- Assistant response contains provenance metadata intended only for training metadata.
- Duplicate prompt/response rows pass silently.
- Placeholder scaffold is exported as approved training data.

---

# Phase 2: Photo Memory And Embedding Spine

This phase covers Objectives 3 and 6.

## Objective 3: Annotate And Add Contextual Metadata To Photographs

User story:

As a user, I want to annotate and add contextual metadata to photographs. I want to see a visual preview of the photographs so that I can provide meaningful context such as a verbal description of the meaning of the photograph.

### Goal 3.1: Reliable Photo Preview

Acceptance tests:

- Local imported image asset creates an image preview derivative.
- `GET /api/assets/{asset_id}/preview` returns HTTP 200 with image media type for local mirrored photo.
- UI photo task renders an `<img>` preview for previewable local photo assets.
- Missing preview shows a specific unavailable state, not a broken image.
- Preview payload distinguishes local preview, Drive thumbnail fallback, and unavailable GCS preview.

Strict failure examples:

- UI has an `<img>` tag whose URL returns 404.
- Preview status says available but image bytes are missing.
- API returns 200 with non-image content.

### Goal 3.2: Photo Context Annotation

Acceptance tests:

- Photo review form supports:
  - visible description,
  - Adam meaning/context,
  - people,
  - place,
  - approximate date/date uncertainty,
  - event/memory tags,
  - themes,
  - open questions,
  - boundary fields.
- Submission creates or updates durable metadata profile.
- Visual description is stored separately from Adam memory/inference.
- Truth status fields distinguish visual fact, Adam memory, and system inference.

Strict failure examples:

- Description and interpretation are collapsed into one undifferentiated field.
- Adam uncertainty is discarded.
- Boundary fields are absent.

### Goal 3.3: Photo Downstream Records

Acceptance tests:

- Photo context submission creates:
  - metadata profile,
  - memory record or memory-source link,
  - gallery candidate if boundary allows,
  - embedding input record or embedding-plan record.
- Created records link back to the source photo asset.
- Created records include boundary snapshot.
- Created records include maturity/readiness state.

Strict failure examples:

- Photo annotation only creates a task annotation and no downstream-useful record.
- Gallery candidate is created for sealed/private photo.
- Memory record has no link back to photo.

---

## Objective 6: Inform A Vector Embeddings Database For Photo Semantic Search

User story:

As a user, I want the system to be able to inform a vector embeddings database that will support semantic similarity search among many photographs.

Example:

If a user asks, "Do you remember that time we flew an airplane in Maine?", the system should be able to respond meaningfully from memory given a photograph of the event with contextual text associated as part of the embeddings.

### Goal 6.1: Embedding Input Text For Photos

Acceptance tests:

- Reviewed photo produces embedding input text.
- Embedding input text includes:
  - visual description,
  - Adam contextual meaning,
  - people,
  - place,
  - event,
  - approximate date,
  - themes,
  - uncertainty/open questions,
  - boundary summary.
- Embedding input text excludes raw private notes if boundary forbids retrieval.
- Embedding input record links to photo asset, metadata profile, memory record, and boundary snapshot.

Strict failure examples:

- Embedding text is only the filename.
- Embedding text omits Adam context.
- Embedding text includes sealed notes.

### Goal 6.2: Semantic Retrieval Fixture

Acceptance tests:

- Fixture contains at least 5 photo memories:
  - airplane in Maine,
  - beach/Old Orchard,
  - food/cooking,
  - chess,
  - Portland harbor.
- Query `airplane in Maine` retrieves the airplane photo/memory in top 1 or top 2.
- Query `food as care` retrieves cooking/food photo memory in top 1 or top 2.
- Query `Portland harbor` retrieves harbor photo memory in top 1 or top 2.
- Retrieval result includes source photo id, memory summary, boundary decision, and why it matched.

Strict failure examples:

- Retrieval returns only assets with matching filenames.
- Retrieval ignores boundary filters.
- Retrieval result lacks source id or explanation.

### Goal 6.3: Boundary-Aware Retrieval

Acceptance tests:

- Sealed/private photo memory is excluded from public retrieval.
- Family-private photo memory is included only for family-private retrieval context.
- Searchable false means the record is not returned.
- Boundary snapshot is included in retrieval output.

Strict failure examples:

- Public query returns sealed photo context.
- Retrieval endpoint cannot explain why an item was excluded.

---

# Phase 3: 200-Pair Proof Milestone

This phase covers Objective 5.

## Objective 5: Inspect A Successful 200-Pair Charles Voice Example Set

User story:

As a user, I want to see a successful example of a model speaking in Charles' authentic voice, by looking at and understanding at least 200 prompt-response pairs that were output by the system.

Important authenticity rule:

The phrase "successful example" cannot mean that the system has automatically proven Charles authenticity. It means the system can produce and expose a reviewable, training-ready candidate set, with enough evidence, rubric context, and source provenance for Adam to understand and approve the examples.

### Goal 5.1: 200 Inspectable Pair Tickets

Acceptance tests:

- System contains at least 200 Prompt Pair tickets generated from imported source artifacts.
- Every ticket has:
  - stable ordinal,
  - prompt,
  - response/chosen,
  - source link,
  - voice mode,
  - synthetic flag,
  - truth status,
  - quality status,
  - boundary status.
- No ticket has empty prompt or empty response.
- No ticket has fallback filename prompt unless present in source.
- Tickets are filterable by voice mode, artifact mode, quality status, synthetic status, and source.

Strict failure examples:

- Count includes duplicate tickets from the same source/pair index.
- Count includes placeholder scaffolds.
- Tickets exist but cannot be inspected individually.

### Goal 5.2: 200 Exportable Or Reviewable Training Artifacts

Acceptance tests:

- At least 200 examples are either:
  - approved/exportable, or
  - explicitly marked candidate with issues needing Adam review.
- Exportable subset passes all SFT/DPO structural tests.
- Candidate subset includes clear reason it is not exportable.
- Dataset audit report lists:
  - total pairs,
  - exportable count,
  - candidate count,
  - blocked count,
  - top voice modes,
  - source distribution,
  - issue distribution.

Strict failure examples:

- "200" count includes blocked items without reporting them as blocked.
- Exportable count includes malformed artifacts.
- Candidate items have no reason/status.

### Goal 5.3: Human Audit Pack

Acceptance tests:

- Audit page or generated markdown report shows at least 20 representative pairs sampled deterministically from the 200.
- Each sample shows:
  - prompt,
  - response,
  - voice mode,
  - source excerpt,
  - context note,
  - rubric status,
  - export preview.
- Sample set includes at least:
  - short note/logistical mode,
  - father-to-Adam tenderness,
  - memoir scene,
  - comic observation,
  - photography reflection,
  - philosophical fragment.
- Audit pack includes "known weak spots" section, not only successes.

Strict failure examples:

- Audit pack is only counts.
- Audit pack hides source/provenance.
- Audit pack contains only one voice mode.

### Goal 5.4: Demonstration Generation

Acceptance tests:

- Pick 5 held-out prompts not used in the training/export set.
- Generate responses using the configured text model and the current context/gold examples.
- Store model name, prompt, context pack id, retrieval sources, and response.
- Responses are marked as model-generated demonstration outputs, not training truth.
- Automated checks verify no empty responses and no policy/provenance violation.
- Optional LLM judge or rubric scorer may flag quality issues, but Adam review is required before calling them authentic.

Strict failure examples:

- Demo response is stored as gold training data.
- Demo response has no model metadata.
- Demo response claims unsupported facts from archive.

---

# Loop Execution Protocol

## Start Condition

The loop may start only after Adam explicitly says to start the loop.

Before starting, the agent should restate:

- selected phase,
- selected objectives,
- exact tests to be introduced or run first,
- expected stopping condition.

## Iteration Template

Each loop iteration must produce a short iteration note, either in chat or in `updates/`, containing:

```markdown
## Iteration N

Objective:
Goal:
Current failing test or unmet acceptance criterion:
Plan:
Files likely to change:
Commands to run:
Expected pass condition:
```

Then execute the plan.

## Test-Driven Behavior

When a goal does not already have a test:

1. Add or identify a strict test first.
2. Run it and confirm whether it fails for the expected reason.
3. Implement the smallest fix.
4. Re-run the focused test.
5. Re-run the baseline tests.

If the test unexpectedly passes before implementation, inspect whether it is a weak/false-positive test. Strengthen it before moving on.

## Live Acceptance Gate

The ordinary unit test suite is necessary, but it is not sufficient for an overnight Ralph loop.

Unit tests answer:

- did a specific behavior regress?
- does a fixture-driven service behave correctly?
- does the frontend still typecheck?

The live acceptance gate answers:

- is the product now meaningfully closer to Adam's actual objective?
- can the imported live material move through the workflow?
- do prompt pairs, photo context, exports, and retrieval work together in the running app?

Before a long loop starts, run:

```bash
python3 scripts/ralph_loop_gate.py
```

This command is expected to fail until the approved milestone is actually true. Treat each failing check as the next work queue. A focused unit test passing is only permission to re-run the gate; it is not permission to stop.

Default live gate requirements include:

- at least 200 inspectable prompt-pair tickets,
- no structurally invalid prompt pairs,
- at least 4 voice modes represented in the prompt-pair audit,
- SFT/DPO export dry-runs exposing reviewable artifacts,
- at least 80 mirrored preview-ready photos,
- live image previews for `Rotmil 2021 I.jpg` and `Rotmil Honors VIII.jpg`,
- at least 5 reviewed photo profiles,
- at least 5 photo-linked memories,
- photo retrieval either returns reviewed/boundary-allowed memory results or an honest no-claim gap with photo-context actions,
- live retrieval proof queries for reviewed photo memories,
- a no-claim/actionable review path for `airplane in Maine` until Adam-authored airplane context exists.

If the live gate is red and no blocker has been recorded, continue looping.

## Failure Handling

When tests fail:

- Do not abandon the goal.
- Read the failure carefully.
- Write a revised micro-plan.
- Fix the smallest likely cause.
- Re-run focused tests first, then baseline.

When a blocker appears:

- Record the blocker.
- Classify it as:
  - missing credentials,
  - missing fixture/source data,
  - architectural conflict,
  - product ambiguity,
  - external service unavailable,
  - unsafe/privacy concern.
- Continue to the next independent goal only if doing so does not hide the blocker.

## Stop Conditions

Stop the loop only when one of these is true:

- The live acceptance gate passes for the selected milestone and the baseline tests pass.
- A blocker requires Adam input.
- A change would require destructive data migration or raw source mutation.
- The app cannot be built or tested because of external infrastructure failure.

Do not stop merely because a focused regression test passes, a small phase report can be written, or one useful endpoint exists. If the gate is still red, write the next micro-plan and keep going.

## Final Morning Report

At the end of the loop, produce:

- objectives attempted,
- tests added,
- tests passing,
- tests failing,
- product changes completed,
- exact remaining blockers,
- links to changed files,
- recommended next loop.

The report must not claim "done" unless the strict tests passed.
