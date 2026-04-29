# Ralph Loop Phase Report - 2026-04-29

## Scope

Approved loop objective document:

- `docs/ralph_loop_evening_objectives.md`

Phases attempted:

1. Training spine: source artifact -> prompt pairs -> human review -> training-ready export.
2. Photo memory spine: photo context -> embedding-ready records -> boundary-aware retrieval scaffold.
3. 200-pair proof milestone: inspectable prompt-pair audit.

## Completed Iterations

### Iteration 1: Mixed YAML Intake And Export Parity

Added strict tests for:

- mixed YAML fixture with 20 SFT examples and 5 DPO examples,
- exactly one Prompt Pair ticket per natural pair,
- no filename/fallback prompts,
- exact SFT/DPO content preservation,
- backend YAML preview shape with correct indentation and no trailing blank line,
- submitted SFT/DPO artifacts matching preview after YAML parsing.

Implementation changes:

- backend SFT/DPO YAML generation now uses `|-` chomping and nested block indentation matching the UI preview.
- frontend prompt-pair YAML preview now also uses `|-`.

### Iteration 2: Source Span/Coding Propagation

Added strict test for:

- highlighted Prompt and Response source spans,
- durable `SourceSpanAnnotation` records,
- generated Prompt Pair ticket from the spans,
- speaker/code/notes preserved into pair context.

Implementation change:

- span-derived pairs now aggregate prompt-side and response-side speaker/code/notes into the ticket context.

### Iteration 3: Photo Context Embedding Input Completeness

Added strict test for:

- photo description,
- Adam contextual meaning,
- people/place/date/themes/concrete objects,
- open questions,
- boundary snapshot,
- gallery item,
- metadata-profile embedding input,
- memory embedding input.

Implementation change:

- photo context review now persists `open_questions` onto the durable photo metadata profile and embedding input.

### Iteration 4: Boundary-Aware Photo Retrieval Scaffold

Added strict test for:

- five photo-memory fixtures,
- query `airplane in Maine` retrieving the airplane photo/memory,
- query `food as care` retrieving food/care memory,
- query `Portland harbor` retrieving harbor memory,
- sealed/private material excluded from family retrieval.

Implementation changes:

- added `GET /api/retrieval/search`,
- added deterministic lexical retrieval over embedding-input records,
- retrieval results include source photo id, matched terms, score, boundary snapshot, input preview, and reason.

### Iteration 5: 200-Pair Audit Surface

Added strict test for:

- 200+ inspectable Prompt Pair tickets,
- exact total counts,
- invalid pair count,
- quality counts,
- artifact mode counts,
- voice mode distribution,
- truth status distribution,
- source distribution,
- deterministic representative samples,
- known weak spots.

Implementation changes:

- added `GET /api/prompt-pairs/audit`,
- added prompt-pair audit compilation over Prompt Pair tickets.

## Final Test State

Passing:

```bash
docker compose run --rm --no-deps api pytest -q
# 44 passed

npm run typecheck
# passed

git diff --check
# passed
```

Runtime smoke checks:

- `GET /api/health` returned ok.
- `GET http://localhost:3003/` returned 200.
- `GET /api/prompt-pairs/audit?sample_limit=5` found 403 live Prompt Pair tickets, 403 inspectable, 0 invalid.
- `GET /api/assets/{Rotmil 2021 I}/preview` returned JPEG bytes.
- `GET /api/assets/{Rotmil Honors VIII}/preview` returned JPEG bytes.

## Live Data Observations

- Photo assets total: 273.
- Mirrored photo assets: 82.
- Mirrored examples checked:
  - `Rotmil 2021 I.jpg`: preview returned JPEG, 1356x892.
  - `Rotmil Honors VIII.jpg`: preview returned JPEG, 1196x1600.
- Prompt Pair tickets in live app: 403.
- Prompt Pair audit found:
  - `total_pairs`: 403
  - `inspectable_pair_count`: 403
  - `invalid_pair_count`: 0
  - `artifact_mode_counts`: `{ "sft": 403 }`

## Remaining Gaps

- The live retrieval endpoint returns no results for `airplane in Maine` yet because the newly mirrored photos are preview-ready but have not been Adam-reviewed into photo metadata/memory/embedding records.
- The retrieval scaffold is lexical over embedding-input text; it is a deterministic bridge, not real vector similarity search.
- The 403 Prompt Pair tickets are review candidates. The audit proves structure/inspectability, not final Charles authenticity.
- Frontend UI does not yet expose the new audit/retrieval endpoints directly.

## Recommended Next Loop

Next loop should focus on:

1. Add a compact Prompt Pair audit panel to the frontend.
2. Add a photo review workflow pass for a small set of the newly mirrored photos.
3. Surface photo embedding/retrieval readiness in the UI.
4. Add vector-provider integration behind the existing `EmbeddingRecord` plan, still keeping DB rows as metadata/pointers rather than raw vectors.

## Continuation Update: Product-Facing Readiness And Photo Review Tickets

Additional loop work moved several of the "remaining gaps" above into passing live product checks.

What landed:

- The Exports workspace now includes a `Downstream Readiness` panel.
- The panel shows prompt-pair audit counts, SFT/DPO candidate counts, photo preview readiness, photo-memory review task count, embedding-corpus count, voice-mode coverage, retrieval proof, and photo draft queue items.
- Candidate export preview mode now disables `Build approved export` and shows a warning, so candidate previews cannot be mistaken for boundary-approved export files.
- Machine photo-memory drafts now create ready `vision_draft_review` tickets with image previews and prefilled review fields.
- Five imported photos now have live review tickets:
  - `Romil and Japanese Flute IV.jpg`
  - `Rotmil Honors VIII.jpg`
  - `Rotmil_Scan_15_2-2018 - Adam with flowers.jpg`
  - `Rotmil-Street Walker.jpg`
  - `Rotmil 2021 I.jpg`
- Added `GET /api/retrieval/photo-memory-corpus`, a boundary-filtered corpus endpoint for embedding-ready photo-memory text records.
- Added `GET /api/model-status`, exposing text-generation model configuration without leaking credentials.
- The Ralph gate now requires photo-memory review tasks and photo-memory embedding corpus records.
- The Ralph gate now also requires the visible text-generation model configuration to match `gpt-5.5` with `xhigh` reasoning while fine-tuning remains disabled for MVP.

Current live gate status:

```bash
python3 scripts/ralph_loop_gate.py
# PASS
```

Current baseline:

```bash
docker compose exec api pytest -q
# 49 passed

npm run typecheck --prefix apps/web
# passed

git diff --check
# clean
```

Current live product counts:

- Prompt Pair tickets: 428 total, 428 inspectable, 0 invalid.
- Voice modes represented: 11.
- Candidate export dry-runs:
  - SFT: 403 review candidates.
  - DPO: 25 review candidates.
- Mirrored preview-ready photos: 82.
- Photo-memory draft records: 5 memories / 5 photo profiles.
- Photo-memory review tickets: 5 ready tickets.
- Photo-memory embedding corpus: 10 boundary-filtered records.
- Text-generation model status: `gpt-5.5`, `xhigh`, live calls gated until credentials are supplied.
- Retrieval proof queries passing:
  - `Japanese flute`
  - `honors ceremony`
  - `Adam flowers`

Important caveats:

- The 403 SFT and 25 DPO artifacts are still review candidates, not approved training exports.
- The DPO rejected answers are synthetic review candidates, intentionally marked as model-generated.
- Photo memories remain `system_inference` machine drafts until Adam reviews them in the new photo tickets.
- Retrieval is still lexical over embedding-input text; the corpus endpoint now makes the future vector-provider handoff explicit.

## Continuation Update: Photo Memory To Prompt Pair Bridge

The next loop targeted Objective 1.4: photo-informed prompt suggestions.

What landed:

- Added `POST /api/photo-memory-drafts/prompt-pair-candidates`.
- The endpoint creates `gold_voice_edit` Prompt Pair tickets from photo-memory metadata profiles.
- Each photo-derived ticket includes:
  - source photo id,
  - source metadata profile id,
  - source memory id when available,
  - source embedding record id when available,
  - boundary snapshot,
  - embedding input text,
  - semantic prompt text rather than a filename fallback,
  - `synthetic: true`,
  - non-archival truth status,
  - `candidate_requires_adam_gold_edit: true`.
- The Exports readiness panel now shows a `Photo pairs` metric and a `Photo Prompt Seeds` card.
- The live Ralph gate now requires at least 3 photo-grounded Prompt Pair tickets with provenance and non-archival truth.
- Created 5 live photo-grounded Prompt Pair tickets:
  - `Dad, what does this photograph bring back about student performance?`
  - `Dad, what do you see in this street photograph?`
  - `Dad, what do you remember about Adam holding the flowers?`
  - `Dad, what do you remember about that honors ceremony?`
  - `Dad, what do you remember about the Japanese flute?`

Current live gate status:

```bash
python3 scripts/ralph_loop_gate.py
# PASS
```

Current baseline:

```bash
docker compose exec api pytest -q
# 51 passed

npm run typecheck --prefix apps/web
# passed

## Continuation Update: Browser-Gated Photo Review Surface

The loop added browser-level checks so the product cannot claim readiness from API counts alone.

What landed:

- Added a Playwright smoke suite at `apps/web/tests/readiness-smoke.spec.ts`.
- The Ralph gate now runs that suite as part of `scripts/ralph_loop_gate.py`.
- The smoke suite verifies:
  - Exports shows the demo generation gate.
  - Demo generation is visibly `model_generated / excluded from training`.
  - Retrieval gaps expose actionable photo-context task buttons.
  - A real photo review ticket can be opened from the Review queue.
  - The photo review surface renders the image preview from `/api/assets/{id}/preview`.
  - The photo review form exposes the downstream memory/search-text preview and key annotation fields.
- The photo review form now has a `Downstream memory preview` card that shows the search/vector text being composed from reviewed visual description, people/place/date, tags, Adam context, invisible context, question answers, and open questions.
- The preview is explicitly marked preview-only and keeps truth status separate from the memory text.

Current live gate status:

```bash
python3 scripts/ralph_loop_gate.py --write-checkpoint --json
# PASS, including 2 Playwright browser smokes
```

Latest checkpoint:

- `updates/ralph_loop_gate_checkpoint_20260429T073734_476080Z.json`
- `updates/ralph_loop_gate_checkpoint_20260429T073734_476080Z.md`

## Continuation Update: Photo Queue Has Visual Triage

This loop tightened the photo workflow around the "I need to see the photograph" requirement.

What changed:

- Photo task rows in the Review queue now show thumbnail previews when mirrored image derivatives are ready.
- The thumbnail uses the same controlled preview endpoint as the full review image:
  - `/api/assets/{asset_id}/preview?variant=thumbnail`
- The existing review surface still shows the larger display preview:
  - `/api/assets/{asset_id}/preview?variant=display`
- The browser smoke now asserts both thumbnail and full-preview paths, plus the downstream memory preview card.

Verification:

```bash
npm run typecheck --prefix apps/web
# passed

npx --prefix apps/web playwright test --config apps/web/playwright.config.ts
# 2 passed

python3 scripts/ralph_loop_gate.py --write-checkpoint --json
# PASS
```

Latest checkpoint:

- `updates/ralph_loop_gate_checkpoint_20260429T074137_716997Z.json`
- `updates/ralph_loop_gate_checkpoint_20260429T074137_716997Z.md`

## Continuation Update: Retrieval Gaps Route Into Photo Context Work

This loop made the "no memory claim yet" retrieval path actionable in the browser.

What changed:

- The browser smoke now clicks the retrieval-gap action for `airplane in Maine`.
- The action creates or opens a `photo_context` task instead of making a memory claim.
- The opened task preserves retrieval provenance:
  - original query: `airplane in Maine`,
  - candidate match quality,
  - selection reason,
  - `truth_status: no_claim`,
  - `not_memory_claim: true`.
- A live review task now exists for the first backlog candidate:
  - `TASK_PHOTO_CONTEXT_000735`
  - `Rotmil_10_19 - Cathryn WIlson.jpg`
- Future gate runs now verify that the action remains idempotent: once the task exists, the button becomes `Open context task`.

Verification:

```bash
npx --prefix apps/web playwright test --config apps/web/playwright.config.ts
# 3 passed

python3 scripts/ralph_loop_gate.py --write-checkpoint --json
# PASS, including the retrieval-gap click-through smoke
```

Latest checkpoint:

- `updates/ralph_loop_gate_checkpoint_20260429T074402_575547Z.json`
- `updates/ralph_loop_gate_checkpoint_20260429T074402_575547Z.md`

git diff --check
# clean
```

Browser verification:

- Exports workspace shows the model gate (`gpt-5.5` / `xhigh`).
- Exports workspace shows the new photo-pair metric.
- Exports workspace shows `Photo Prompt Seeds`, including the Japanese flute seed.
- Screenshot saved at `updates/photo_prompt_pair_readiness.png`.
- Prompt Pairs can be filtered to photo-derived tickets.
- The Japanese flute Prompt Pair ticket opens with a source-photo card, live thumbnail, provenance chips, and `SFT held` boundary status.
- Screenshot saved at `updates/photo_prompt_pair_ticket_editor.png`.

Current live product counts:

- Prompt Pair tickets: 433 total, 433 inspectable, 0 invalid.
- SFT candidate dry-run: 408 review candidates.
- DPO candidate dry-run: 25 review candidates.
- Photo-grounded Prompt Pair tickets: 5.

Important caveat:

- These photo-derived prompt-pair tickets are scaffolds for Adam review. They intentionally remain review candidates and should not be treated as approved training data until Adam edits/submits them.

Follow-up UI pass:

- Photo-derived Prompt Pair tickets now use stable `Photo 001`, `Photo 002`, etc. labels.
- Photo-derived Prompt Pair tickets participate in the Photos collection filter.
- Prompt Pair tickets linked to a photo now resolve the source asset for the dossier link and preview/readiness badges.
- The Prompt Pair editor preserves the source truth status for photo-grounded candidates instead of rewriting it to `adam_expert_reconstruction`.
- If the source boundary has `usable_for_sft: false`, the editor holds export flags at false and displays a boundary hold message.

## Continuation Update: Audit Pack, Vector Handoff, And Review Filters

The loop then expanded the live gate and UI beyond "records exist" checks.

What landed:

- Added `GET /api/prompt-pairs/audit-pack`.
- The audit pack returns 20 deterministic representative samples, required voice-mode coverage, known weak spots, source excerpts, context notes, and YAML export previews.
- The Exports readiness panel now exposes:
  - audit-pack sample count,
  - modes represented,
  - weak-spot note,
  - markdown audit character count.
- Added `GET /api/retrieval/photo-memory-corpus/export`.
- The photo-memory vector handoff returns:
  - JSONL records,
  - a manifest,
  - content SHA-256,
  - item ids,
  - boundary policy snapshot,
  - embedding policy snapshot,
  - excluded records and reasons,
  - explicit `live_embedding_call: false`,
  - explicit `vector_values_included: false`.
- The Exports readiness panel now shows `Vector handoff`, record count, content hash prefix, and "No inline vectors / provider handoff."
- Prompt Pair queue now has advanced filters for:
  - voice mode,
  - artifact mode,
  - quality,
  - synthetic/source-derived status,
  - source kind.
- Browser verification confirmed filtering Source=`photo` and Synthetic=`synthetic` narrows the Prompt Pair queue to the 5 photo-grounded tickets.
- Dataset export build manifests now include:
  - export type,
  - version,
  - split,
  - filters,
  - included/excluded counts,
  - source ids,
  - artifact ids,
  - content SHA-256,
  - excluded reasons,
  - boundary policy snapshot,
  - quality policy snapshot.
- Added `GET /api/model-status/demo-readiness`.
- Demo readiness returns:
  - configured model (`gpt-5.5`),
  - reasoning effort (`xhigh`),
  - five held-out prompts,
  - live generation blockers,
  - a safety policy requiring `model_generated` truth status and Adam review.
- The Exports readiness panel now shows `Demo gate`, prompt count, and the honest missing-credentials/live-call blocker.

Screenshots saved:

- `updates/audit_pack_readiness.png`
- `updates/vector_handoff_readiness.png`
- `updates/prompt_pair_filters.png`
- `updates/demo_generation_gate.png`

Current baseline after these changes:

```bash
docker compose exec api pytest -q
# 53 passed

npm run typecheck --prefix apps/web
# passed

python3 scripts/ralph_loop_gate.py --json
# PASS

git diff --check
# clean
```

Current live product counts:

- Prompt Pair tickets: 433 total, 433 inspectable, 0 invalid.
- Audit pack: 20 samples, 8 represented modes, no required mode gaps.
- SFT candidate dry-run: 408 review candidates.
- DPO candidate dry-run: 25 review candidates.
- Photo-grounded Prompt Pair tickets: 5.
- Photo vector handoff: 10 JSONL records, 0 boundary exclusions in the live family-private corpus, content hash `a625745c8ca83e3e3c5b7e23bde1306ffb95c123ac93412a09410c1709190971`.
- Demo generation gate: 5 held-out prompts reserved, blocked by `text_generation_live_calls_disabled` and `openai_api_key_missing`.

Known blocker:

- Goal 5.4 demonstration generation cannot honestly pass yet because live text generation is gated and no OpenAI credentials are configured in this environment. The app records `gpt-5.5` / `xhigh` configuration and can scaffold no-live candidates, but it should not claim a real model demonstration until credentials are supplied and the response is stored as `model_generated`, not training truth.

## Continuation Update: Export Provenance, Rubric Gates, And Boundary-Aware Vector Text

The next loop tightened several false-positive gaps in the downstream handoff:

- Approved SFT/DPO export payloads now carry richer metadata from the originating gold voice example:
  - truth status,
  - voice mode,
  - synthetic flag,
  - artifact mode,
  - freeform context,
  - grounding asset id,
  - source annotation id,
  - exact export preview YAML.
- Dataset export dry-runs now exclude duplicate training rows within the same export type and report `duplicate_export_payload` with `duplicate_of_artifact_id`.
- The live Ralph gate now verifies SFT/DPO dry-runs contain `0` included duplicate rows.
- Chosen/content-side `minor_issues` now keeps the artifact as `candidate` until resolved; rejected-side DPO issues still become DPO reason metadata.
- Candidate SFT/DPO rows now include explicit `review_blockers` such as `needs_adam_gold_edit`, `boundary_holds_sft`, or `truth_status_system_inference_requires_review`.
- The Exports UI now shows candidate `review_blockers` inline on included dry-run rows.
- Photo metadata-profile and memory embedding input text now includes compact boundary summary fields, for example:
  - `boundary_privacy_level: family_private`
  - `boundary_retrievable_in_chat: true`
  - `boundary_usable_for_sft: false`
  - `boundary_usable_for_dpo: false`
- Raw boundary notes are intentionally not copied into the embedding text.
- The live photo-memory draft records were refreshed to backfill the improved embedding input text without mutating raw source files.

The stricter vector handoff gate initially failed against stale live records, then passed after the generated photo-memory records were refreshed. That failure was useful: it proved the loop was checking the live product state, not just unit-test fixtures.

Current baseline after these changes:

```bash
docker compose exec -T api pytest -q
# 57 passed

npm run typecheck --prefix apps/web
# passed

python3 scripts/ralph_loop_gate.py --json
# PASS

git diff --check
# clean
```

Current live gate additions:

- SFT candidate dry-run: 408 included, `0` included duplicates, `0` candidate rows missing review blockers.
- DPO candidate dry-run: 25 included, `0` included duplicates, `0` candidate rows missing review blockers.
- Photo vector handoff: 10 JSONL records, compact boundary summaries present in embedding text, no inline vectors, no live embedding calls.
- Photo vector handoff content hash after backfill: `ae9eb9c7bc969fd11035b031ba817c83d61922651687b6cb57fd88cf186d449a`.

## Continuation Update: Idempotence, Exact Export Retrieval, And Generation Metadata

The next loop cycles focused on making repeated long-run passes safe and making downstream handoffs more exact.

What changed:

- The 200-pair human audit pack is now available as a direct Markdown endpoint:
  - `GET /api/prompt-pairs/audit-pack/markdown?sample_limit=200`
  - The readiness UI links to this exact Markdown artifact.
- Machine photo-memory draft generation is now idempotent:
  - repeated runs reuse existing machine-draft annotations and ready review tasks,
  - repeated runs do not create duplicate photo-memory review tickets,
  - existing Adam-reviewed photo profiles are skipped rather than overwritten by machine templates.
- Boundary snapshots used by embedding records now normalize timestamp strings so JSONL vector handoff hashes stay stable across SQLite/API round trips.
- Built dataset exports now have exact retrievable JSONL by export id:
  - `GET /api/dataset-exports/{export_id}/jsonl`
  - export manifests include `generated_at`, `stable_item_keys`, `content_sha256`, source ids, artifact ids, excluded reasons, and policy snapshots.
  - repeat builds over the same approved inputs preserve item count, stable item keys, item order, and payload hash.
- Source-review fallback prompt-pair generation now avoids filename-only prompts and records generation metadata:
  - `model_name: gpt-5.5`,
  - `reasoning_effort: xhigh`,
  - `no_live_model_call: true`,
  - source text hash/preview/char count,
  - prompt instructions version,
  - strategy such as `deterministic_fallback_source_text`.
- Fallback source-review tickets are explicitly marked as needing Adam gold edit and do not claim `archival_source` when the response is synthetic reconstruction.

Strict tests added to the Ralph gate:

- Dataset export build creates exact retrievable JSONL.
- Source-review fallback pair generation records model/no-live metadata.
- Photo memory draft generation is idempotent and review-safe.

Current baseline after these changes:

```bash
docker compose exec -T api pytest -q
# 59 passed

npm run typecheck --prefix apps/web
# passed

python3 scripts/ralph_loop_gate.py --json
# PASS

git diff --check
# clean
```

Live idempotence evidence:

- Running `POST /api/photo-memory-drafts?limit=5&dry_run=false` twice reused all 5 existing review tasks.
- `created_new_count` stayed `0`.
- The photo vector handoff hash stayed `ae9eb9c7bc969fd11035b031ba817c83d61922651687b6cb57fd88cf186d449a` across both runs.

## Continuation Update: Prompt-Pair Voice Reference Pack

The next loop focused on making the existing prompt-pair corpus compound into future generation work. The source examples Adam imported are now available not only as review tickets and dataset candidates, but also as a structured voice-reference pack for GPT-5.5 drafting.

What changed:

- Added a prompt-pair voice reference pack:
  - `GET /api/prompt-pairs/reference-pack?sample_limit=200`
  - `GET /api/prompt-pairs/reference-pack/jsonl?sample_limit=200`
  - `GET /api/prompt-pairs/reference-pack/markdown?sample_limit=200`
- The pack includes system/user/assistant messages, voice mode, conversation family, truth status, boundary status, source provenance, rubric summaries, export previews, and embedding/reference text.
- The pack explicitly states that it is a drafting reference corpus and does not certify final Charles authenticity or change truth status.
- Duplicate prompt/response message triples are excluded from the reference pack.
- Prompt-pair factory drafting now falls back to the prompt-pair reference corpus when source chunks do not have their own `VoiceReferenceExample` records.
- The Downstream Readiness panel now shows reference-pack readiness, duplicate exclusions, and direct JSONL/Markdown links.

Strict tests added:

- Reference pack returns 200 generation-context JSONL records without authenticity claims.
- Reference pack JSONL line count, content type, stable IDs, role ordering, duplicate exclusion, and Markdown sample sections are verified.
- Prompt-pair factory uses reference-pack examples when source chunks have no local reference examples.
- The Ralph gate now fails if the prompt-pair voice reference pack is missing, non-stable, duplicate-filled, lacks required voice modes, or lacks the no-authenticity-claim safety policy.

Current baseline after these changes:

```bash
docker compose exec -T api pytest -q
# 61 passed

npm run typecheck --prefix apps/web
# passed

python3 scripts/ralph_loop_gate.py --json
# PASS

git diff --check
# clean
```

Live reference-pack evidence:

- Prompt pairs: `433`
- Unique reference examples: `408`
- Selected reference examples: `200`
- Duplicate candidates excluded: `25`
- Content hash: `450ecceb3476d1a57e65750b7b20b8a97638905cefd0dc926448711c17669673`

## Continuation Update: Photo Retrieval Result Diversity

The next loop tightened the photo-memory retrieval contract. The system still preserves both profile and memory embedding records for downstream vector work, but live retrieval now collapses duplicate results that point to the same source photo. This keeps search results from feeling noisy while preserving the underlying multi-record corpus.

What changed:

- `search_embedding_records` now de-duplicates returned results by `source_photo_id`.
- Non-photo records still use their target type/id as the fallback uniqueness key.
- The Ralph gate now fails if any required photo-memory search query returns duplicate source photos in the top results.
- Photo-spine tests now verify unique source photos for direct semantic retrieval and machine-drafted photo-memory retrieval.

Current baseline after these changes:

```bash
docker compose exec -T api pytest -q
# 61 passed

npm run typecheck --prefix apps/web
# passed

python3 scripts/ralph_loop_gate.py --json
# PASS

git diff --check
# clean
```

Live retrieval evidence after de-duplication:

- `Japanese flute`: `1` result, `1` unique source photo.
- `honors ceremony`: `1` result, `1` unique source photo.
- `Adam flowers`: `3` results, `3` unique source photos.

## Continuation Update: Photo Review UI Verification

The next loop checked whether the photo-memory workflow is actually visible in the app, not just present in backend records.

What changed:

- The workbench task-opening handler now tries to scroll the selected editor into view after a task is selected.
- The narrow-layout CSS now bounds the queue panel height and keeps the queue body scrollable, reducing the chance that the selected review surface is buried below a long task list.
- The mobile/small-viewport CSS gives the main workbench column explicit ordering for stacked layouts.

Live browser verification:

- Opened a `Vision Draft Review` task for `Rotmil 2021 I.jpg`.
- Confirmed the selected task exposes:
  - an image preview element backed by `/api/assets/{asset_id}/preview`,
  - preview variant controls for display/thumbnail/original,
  - reviewed visual description,
  - visible people,
  - place/date/event,
  - tags/themes,
  - invisible context,
  - Adam question fields,
  - privacy and downstream-use controls.
- Manual in-browser scrolling shows the real photo preview and the photo-memory annotation form together.

Current UI verification baseline:

```bash
npm run typecheck --prefix apps/web
# passed
```

## Continuation Update: Retrieval Gap Samples Label Semantic Confidence

The next loop tightened the honest no-result path. Retrieval-gap suggestions can be useful, but they must not look like the system found a memory when it only found unreviewed backlog.

What changed:

- `retrieval_gap` now includes `candidate_group_selection_policy: title_overlap_then_backlog_sample`.
- `retrieval_gap` now includes `sample_groups_are_not_memory_claims: true`.
- Each sample context group now includes:
  - `matched_query_terms`,
  - `selection_reason`, either `title_or_filename_overlap` or `backlog_sample_no_semantic_match`.
- The readiness panel now exposes this distinction in the retrieval proof controls, so backlog samples are visibly not semantic memory matches.
- The Ralph gate now fails if no-result retrieval gaps lack the selection policy, the non-claim disclaimer, or per-group selection reasons.

Current baseline after this loop:

```bash
docker compose exec -T api pytest -q
# 66 passed

npm run typecheck --prefix apps/web
# passed

python3 scripts/ralph_loop_gate.py --json
# PASS, 23 live checks

git diff --check
# clean
```

Live evidence:

- `airplane in Maine` still returns `0` memory results.
- The response now says `truth_status: no_claim`.
- The sample groups are explicitly marked as `backlog_sample_no_semantic_match` when there is no title overlap.
- The candidate list is therefore useful for opening photo-context work, but not presented as evidence that the airplane memory exists.

## Continuation Update: SFT Export Guardrails

The next loop tightened the approved-training-data path for SFT. A prompt/response can look structurally valid while still being a placeholder artifact, especially if a failed segmentation step produces a prompt like `Tell me about charles_sft.yaml`.

What changed:

- Added SFT export blockers for:
  - empty system prompt,
  - empty prompt,
  - generic placeholder prompt,
  - filename-derived prompt,
  - empty assistant content,
  - assistant content that is too short to be meaningful,
  - prompt/response identity.
- Approved SFT submissions now stay `candidate` if any of those blockers are present, even when the rubric is otherwise marked clean.
- SFT export payload metadata now carries `quality_gate` and `review_blockers`, so dry-runs explain why a candidate is not approved.
- Prompt-pair review candidates also reuse the SFT blocker helper, while preserving ordinary review candidates that only need Adam gold edit.
- The Ralph gate now runs a regression for the exact filename-placeholder failure mode.

Current baseline after this loop:

```bash
docker compose exec -T api pytest -q
# 67 passed

npm run typecheck --prefix apps/web
# passed

python3 scripts/ralph_loop_gate.py --json
# PASS, 23 live checks

git diff --check
# clean
```

## Continuation Update: Reference Packs Exclude Structural SFT Blockers

The next loop tightened a subtle training-quality leak. Export approval was protected from structural SFT problems, but the voice reference pack could still include the same flawed prompt-pair as model-drafting context.

What changed:

- Prompt-pair audit now uses the same SFT structural blocker helper as export dry-runs.
- Prompt-pair reference packs now exclude structurally blocked SFT rows.
- Added a regression where `Tell me about charles_sft.yaml` is:
  - counted as invalid in audit,
  - excluded from the voice reference JSONL pack,
  - still visible as a task needing edit rather than silently promoted.
- After the live gate caught a valid terse Charles reply (`Tell mom`), the over-broad `sft_assistant_content_too_short` rule was removed. Short can be authentic; empty and placeholder are the real structural problems.

Current baseline after this loop:

```bash
docker compose exec -T api pytest -q
# 68 passed

npm run typecheck --prefix apps/web
# passed

python3 scripts/ralph_loop_gate.py --json
# PASS, 23 live checks

git diff --check
# clean
```

## Continuation Update: Photo Vector Handoff Is Reviewed-Only By Default

The next loop used Locke's sidecar recommendation. Machine photo-memory drafts are useful as review scaffolds and searchable candidates, but they should not seed a downstream vector database as if they were Adam-reviewed memories.

What changed:

- `/api/retrieval/photo-memory-corpus` is now reviewed-only by default.
- `/api/retrieval/photo-memory-corpus/export` is now reviewed-only by default.
- Machine photo-memory drafts remain available only with `include_machine_drafts=true`.
- Default corpus/export responses now preserve excluded machine drafts with `reasons: ["requires_adam_review"]`.
- Vector handoff manifests now declare:
  - `review_policy: reviewed_only_by_default`,
  - `include_machine_drafts: false`.
- The Ralph gate now passes when the handoff has either reviewed records or explicit machine-draft exclusions, and it fails if the default JSONL includes `system_inference`, `model_generated`, or `photo_memory_machine_draft` records.

Current baseline after this loop:

```bash
docker compose exec -T api pytest -q
# 68 passed

npm run typecheck --prefix apps/web
# passed

python3 scripts/ralph_loop_gate.py --json
# PASS, 23 live checks

git diff --check
# clean
```

Live evidence:

- Default photo-memory corpus: `0` records, `5` excluded pending Adam review.
- Default vector handoff JSONL: empty, stable SHA-256 of empty content, `5` excluded pending Adam review.
- Retrieval search still finds machine drafts for review-gated search, with `requires_adam_review: true`; only the vector handoff/export path is stricter.

Honest note:

- These blockers protect export approval, not generation quality by themselves. The next stronger step is to expose the blockers in the Prompt Pairs editing surface so Adam can see and fix them before submission.

## Continuation Update: Prompt Pair Editor Shows SFT Blockers

The next loop moved the SFT guardrail from a backend-only export explanation into the editing surface.

What changed:

- Prompt Pair editing now runs the same local SFT structural checks used by the backend:
  - placeholder prompt,
  - filename-derived prompt,
  - missing/too-short assistant content,
  - prompt/response identity,
  - empty system/user fields.
- The readiness strip now treats those blockers as unresolved structure issues.
- The editor displays each blocker as a visible status chip, so Adam can fix a bad prompt before submit instead of discovering it later in export dry-run metadata.

Current baseline after this loop:

```bash
docker compose exec -T api pytest -q
# 67 passed

npm run typecheck --prefix apps/web
# passed

python3 scripts/ralph_loop_gate.py --json
# PASS, 23 live checks

git diff --check
# clean
```

## Continuation Update: DPO Export Guardrails

The next loop tightened Objective 4.2 around DPO training output. A DPO example should never become an approved training artifact unless the rejected side is real, different, and has explicit issue context.

What changed:

- `gold_voice_edit` DPO submissions now stay `candidate` when:
  - the prompt is empty,
  - chosen is empty,
  - rejected is empty,
  - chosen and rejected are identical,
  - the rejected side has no rubric notes or explicit failure modes.
- DPO blockers are preserved in `DPOPair.reason`, so export dry-runs explain why the row is excluded.
- The Ralph gate now runs a regression where an otherwise "no issues" DPO pair has identical chosen/rejected text; it must be excluded from approved export.

Focused regression:

```bash
docker compose exec -T api pytest -q \
  tests/test_ralph_phase1_training_spine.py::test_submitted_sft_and_dpo_artifacts_match_export_preview_structure \
  tests/test_ralph_phase1_training_spine.py::test_dpo_export_guard_blocks_identical_or_unexplained_rejected_response
# passed
```

## Continuation Update: Live Honest Retrieval Gap Gate

The next loop added a live gate for the exact no-result memory case we have been using as a product probe.

What changed:

- The Ralph gate now checks `airplane in Maine`.
- If that query resolves to a memory later, the result must be a canonical memory row with source-photo provenance and review policy.
- If it does not resolve, the response must return:
  - `truth_status: no_claim`,
  - `workflow: photo_context_review`,
  - `next_queue: photo_assets_needing_context`,
  - candidate context groups.

Live evidence:

```bash
python3 scripts/ralph_loop_gate.py --json
# PASS, including Photo retrieval no-claim gaps are honest and actionable
```

## Continuation Update: Duplicate Photo Groups Are De-Noised

The next loop tightened the photo inventory and retrieval-gap handoff so copy/variant files do not keep creating work after the group has already been contextualized.

What changed:

- Photo review inventory now treats a duplicate group as covered when any photo in the group has a `photo_memory` profile.
- Copy variants in a covered group now report `profile_status: covered_by_group_profile` and include `covered_by_group_profile_id`.
- Group/root `needs_context_count` no longer counts copy variants from already-profiled groups.
- Retrieval gap candidates now exclude whole photo groups that already have a profile on any variant, so a no-result query does not suggest reviewing a duplicate copy from an already-covered group.

Focused regression:

```bash
docker compose exec -T api pytest -q \
  tests/test_ralph_phase2_photo_spine.py::test_photo_review_inventory_groups_copy_variants_and_counts_context_gap \
  tests/test_ralph_phase2_photo_spine.py::test_photo_retrieval_gap_is_actionable_without_inventing_memory
# passed

npm run typecheck --prefix apps/web
# passed
```

Honest note:

- The in-app browser screenshot surface is narrow and still emphasizes the queue strongly. The preview exists and is reachable, but this should remain a UX watch item. A future loop should add a more explicit "open selected task" mobile affordance or a split/compact queue toggle if Adam keeps feeling like the editor disappears behind the queue.

## Continuation Update: DPO Issue Context And Photo Intake Inventory

The next loop tightened two places where the app could have passed tests while still being noisy downstream.

What changed:

- DPO candidate synthesis now creates a same-rubric comparison scaffold:
  - `response_a` / rejected side carries issue statuses, issue tags, and explanatory notes.
  - `response_b` / chosen side is marked as the preferred candidate while still requiring Adam review before export.
  - DPO reasons are now explanatory strings such as `voice_authenticity: ...`, not only short machine labels.
- DPO export dry-runs now include:
  - `response_rubric`,
  - `chosen_issue_summary`,
  - `rejected_issue_summary`,
  - `rejected_truth_status`,
  - `candidate_review_policy` with `adam_review_required` and `does_not_certify_final_authenticity`.
- Existing live DPO candidates with older short reason labels are expanded at export time, so the live app gets stricter metadata without a destructive data rewrite.
- The Ralph gate now fails if DPO candidates lack distinct chosen/rejected text, explanatory reasons, rejected-side issue notes, chosen-side issue-free summary, or the Adam-review authenticity disclaimer.
- Photo vector handoff now emits one canonical memory record per source photo rather than duplicate metadata-profile and memory rows for the same image.
- Vector handoff manifests now include `source_photo_count` and a `dedupe_policy_snapshot`.
- Added `GET /api/assets/photo-review-inventory`.
  - It groups copy/variant photo assets by normalized title.
  - It identifies canonical assets.
  - It reports preview-ready photos still needing context.
  - It distinguishes asset-level context gaps from group-level context gaps, so duplicate copies do not masquerade as separate memories.
  - It reports duplicate/copy groups without creating low-quality synthetic memories.
- Added `POST /api/assets/photo-review-inventory/context-task`.
  - It creates an idempotent `photo_context` task for a canonical preview-ready photo group that has no photo-memory profile yet.
  - It refuses to create duplicate context tasks for an asset that already has a ready context task.
  - It refuses group-level task creation when the group already has a photo-memory profile, leaving that group to its existing review task.
- The Downstream Readiness panel now shows photo intake inventory counts and the top context gaps/duplicate groups.
- The Downstream Readiness panel can now create a context task from a real unprofiled photo group.

Current baseline after these changes:

```bash
docker compose exec -T api pytest -q
# 62 passed

npm run typecheck --prefix apps/web
# passed

python3 scripts/ralph_loop_gate.py --json
# PASS, 21 live checks

git diff --check
# clean
```

Live evidence:

- SFT candidate dry-run: `408` included, `0` included duplicates.
- DPO candidate dry-run: `25` included, `0` duplicate rows, `0` rows missing issue context.
- DPO candidates now carry review blockers:
  - `needs_adam_gold_edit`
  - `rejected_truth_status_model_generated_requires_review`
- Photo review inventory:
  - `273` total photo assets.
  - `82` preview-ready photos.
  - `5` photo-memory profiles.
  - `77` preview-ready asset records still lack direct context.
  - `22` canonical photo groups need context after duplicate/copy grouping.
  - `46` duplicate/copy variant groups.
- Photo vector handoff:
  - `5` canonical memory records.
  - `5` unique source photos.
  - `0` boundary-excluded records in the current family-private scope.
  - content hash `1c84cb2e39a6444bb57185f8ff55fafe47826b024d1cd5391b2549c0b7945380`.

Next useful loop target:

- Use the new photo inventory to create a less noisy photo work surface: let Adam choose a duplicate group/canonical image and open a dedicated context task from that group, instead of scanning the whole asset list.

## Continuation Update: Photo Context Questions And OCR Provenance

The next loop made the photo intake task more faithful to the downstream memory goal: Adam's answers to photo-specific questions now become searchable context instead of staying buried in raw annotation JSON.

What changed:

- Inventory-created `photo_context` tasks now include four Adam-facing suggested questions:
  - what is visibly present,
  - what Adam knows that is not visible,
  - what memory/story/relationship/event the photo anchors,
  - what should remain uncertain.
- `question_answers` and `open_questions` are now required decisions on inventory-created photo context tasks.
- Photo-context submit now promotes answered questions into:
  - `MetadataProfile.adam_context_note`,
  - `MetadataProfile.retrieval_notes`,
  - `MetadataProfile.raw_profile.answered_questions`,
  - `MetadataProfile.quality_signals.answered_question_count`,
  - profile embedding input text,
  - memory summary and memory embedding input text.
- Unanswered suggested questions remain explicit `open_questions`, preserving uncertainty rather than converting it into source truth.
- The photo review UI now exposes an `Open questions for later` field in the shared photo-memory review form.
- Reviewed photo OCR/handwriting text now creates a durable `Segment` with:
  - `segment_type="photo_context_ocr_text"`,
  - its own `source_truth_status`,
  - `maturity_level` based on whether OCR is system inference or Adam-reviewed/reconstructed,
  - metadata that marks quote-check requirements.
- Task receipts now label OCR/handwriting segment creation as a downstream outcome.
- The Ralph gate's photo context task contract now covers both idempotent task creation and promotion of Adam question answers/OCR into downstream records.

Current baseline after this loop:

```bash
docker compose exec -T api pytest -q
# 63 passed

npm run typecheck --prefix apps/web
# passed

python3 scripts/ralph_loop_gate.py --json
# PASS, 21 live checks

git diff --check
# clean
```

Strict contract added:

- A photo-context task created from inventory must expose suggested question IDs `visible_facts`, `invisible_context`, `meaning`, and `uncertainty`.
- Submitting that task with Adam answers must make the answer text visible in profile context, memory text, profile embedding input, and memory embedding input.
- Submitting reviewed OCR/handwriting must create a `photo_context_ocr_text` source segment with the selected truth status.

Next useful loop target:

- Make the created `photo_context` task easier to enter from the Downstream Readiness panel and verify the main task queue refresh/open behavior, so the path from inventory gap -> task -> review surface feels direct rather than hidden.

## Continuation Update: Photo Inventory Task Handoff

The next loop connected the photo intake inventory card to the main workbench instead of leaving created tasks hidden in the queue.

What changed:

- `DownstreamReadinessPanel` now accepts an `onOpenPhotoContextTask` callback.
- When the panel creates or finds an existing photo-context task, it reports the task ID upward.
- `ExportDryRunPanel` passes that callback through to the readiness panel.
- The main workbench now handles that callback by:
  - switching to `Review`,
  - switching the collection filter to `Photos`,
  - refreshing live task data,
  - selecting the created/existing `photo_context` task,
  - scrolling the workbench column into view.
- The Ralph gate now includes `npm run typecheck --prefix apps/web`, so future live-gate passes require the frontend to typecheck, not merely return HTTP 200.

Current baseline after this loop:

```bash
npm run typecheck --prefix apps/web
# passed

python3 scripts/ralph_loop_gate.py --json
# PASS, 22 live checks
```

Next useful loop target:

- Add a lightweight API/UI way to inspect the exact newly-created photo-context task payload from the inventory action, so Adam can see why a photo was chosen and what duplicate variants were grouped before he starts annotating.

## Continuation Update: Canonical Photo Retrieval Results

The next loop tightened photo semantic retrieval quality. The product goal is not only to find matching records, but to avoid noisy duplicate evidence when one photo has both a metadata-profile embedding row and a memory embedding row.

What changed:

- Retrieval search now declares a result de-duplication policy:
  - `one_result_per_source_photo: true`,
  - preferred photo target order: `memory`, then `metadata_profile`.
- For photo results with the same `source_photo_id`, retrieval now prefers the canonical `memory` row over metadata-profile rows.
- Existing retrieval tests now require photo queries such as `airplane in Maine`, `food as care`, `Portland harbor`, `Japanese flute`, `honors ceremony`, and `Adam flowers` to return canonical memory rows when memory rows exist.
- The Ralph gate now fails if required live photo retrieval queries return duplicate source photos or a non-memory top result.

Live evidence:

- `Japanese flute` now returns:
  - target type: `memory`,
  - title: `Photo memory: Charles with Japanese flute`,
  - source photo id: `8a4804ea-e2fc-4b8c-9c2d-53e0349de1c1`.
- `airplane in Maine` still returns no live result, which is honest: none of the imported live photos have been Adam-reviewed into that specific memory yet. The test suite covers that behavior with fixture data, and the product now exposes the inventory/context-task path needed to create such a memory from a real photo.

Current baseline after this loop:

```bash
docker compose exec -T api pytest -q
# 63 passed

npm run typecheck --prefix apps/web
# passed

python3 scripts/ralph_loop_gate.py --json
# PASS, 22 live checks

git diff --check
# clean
```

Next useful loop target:

- Add a clear retrieval-gap/readiness signal for queries that return no result, so a future assistant can tell Adam "I don't have that memory yet" and point to the relevant photo-context workflow instead of silently failing.

## Continuation Update: Actionable Retrieval Gaps

The next loop made failed retrieval explicit and useful. A downstream voice/memory system should not silently fail or improvise when the archive has not been reviewed into memory yet.

What changed:

- `GET /api/retrieval/search` now returns `retrieval_gap` whenever no boundary-cleared memory result is found.
- The gap block includes:
  - `status: no_boundary_cleared_memory_result`,
  - `truth_status: no_claim`,
  - a human-readable message,
  - suggested next action,
  - `workflow: photo_context_review`,
  - `next_queue: photo_assets_needing_context`,
  - preview-ready photo counts,
  - photo assets/groups still needing context,
  - sample context groups that Adam can review.
- The readiness panel now includes `airplane in Maine` as an honest retrieval probe. It shows the gap message and context-task workflow rather than pretending a memory exists.
- Web retrieval types now include the result de-dupe policy and optional retrieval-gap payload.

Live evidence:

- `airplane in Maine` returns `0` results and a gap payload:
  - `truth_status: no_claim`,
  - `workflow: photo_context_review`,
  - `next_queue: photo_assets_needing_context`,
  - `82` preview-ready photos,
  - `77` photo assets needing context,
  - `25` photo groups needing context.

Current baseline after this loop:

```bash
docker compose exec -T api pytest -q
# 64 passed

npm run typecheck --prefix apps/web
# passed

python3 scripts/ralph_loop_gate.py --json
# PASS, 22 live checks

git diff --check
# clean
```

Next useful loop target:

- Connect retrieval gaps to photo inventory task creation more directly, so a no-result query can offer candidate context groups and let Adam open a review task from the gap surface.

## Continuation Update: Retrieval Gap To Photo Task Action

The next loop connected the honest no-result state to the annotation workflow.

What changed:

- Retrieval proof now shows candidate context groups when a query has no memory result but the photo archive still has preview-ready groups needing context.
- Each candidate group can now create/open a `photo_context` task directly from the retrieval gap surface.
- The action reuses the same idempotent inventory endpoint and main-workbench callback, so it lands in Review -> Photos with the selected task open.

Current baseline after this loop:

```bash
npm run typecheck --prefix apps/web
# passed

python3 scripts/ralph_loop_gate.py --json
# PASS, 22 live checks
```

Honest note:

- The candidate groups are currently ranked lexically against file/group titles. That is useful for titled assets but not true visual semantic retrieval yet. The next deeper step is to use reviewed photo context, machine draft summaries, and eventually embeddings to rank gap candidates more meaningfully.

## Continuation Update: Retrieval Review Policy

The next loop tightened downstream safety for retrieved photo memories. Some useful photo-memory rows are still machine drafts, and a future voice/context system must not treat them as Adam-certified memory.

What changed:

- Each retrieval result now includes `review_policy`:
  - `requires_adam_review`,
  - `truth_status`,
  - `boundary_reviewed_by`,
  - `does_not_certify_final_memory`.
- The readiness panel now shows `Needs Adam review / system_inference` for retrieved machine-drafted photo memories.
- Retrieval tests now distinguish Adam-reviewed fixture memories from system-inference machine drafts.
- The Ralph gate now fails if a system-inference/model-generated top retrieval result does not explicitly require Adam review or if it certifies final memory truth.

Live evidence:

- `Japanese flute` returns the canonical `memory` row and review policy:
  - `requires_adam_review: true`,
  - `truth_status: system_inference`,
  - `boundary_reviewed_by: system_draft`,
  - `does_not_certify_final_memory: true`.

Current baseline after this loop:

```bash
docker compose exec -T api pytest -q
# 64 passed

npm run typecheck --prefix apps/web
# passed

python3 scripts/ralph_loop_gate.py --json
# PASS, 22 live checks

git diff --check
# clean
```

Next useful loop target:

- Promote reviewed photo-context submissions above machine drafts in retrieval and inventory counts, so Adam-reviewed context visibly replaces machine scaffold material without destructive source mutation.

## Continuation Update: Adam Review Promotes Photo Memory Truth

The next loop targeted a subtle but important promotion gap. Machine photo-memory drafts could be reviewed by Adam and gain better text, but a reviewed vision/photo task could still carry `system_inference` or `L2_machine_draft` residue into downstream surfaces.

What changed:

- Vision/photo draft review now promotes Adam context and answered "why this matters" questions into durable profile context, retrieval notes, and embedding input.
- Reviewed photo memories now update existing machine-draft memory rows to:
  - `truth_status: adam_memory` when Adam supplies memory context,
  - `maturity_level: L3_reviewed`,
  - medium source confidence.
- The workbench now derives photo review truth status from Adam context/question answers instead of hard-coding vision draft reviews to `system_inference`.
- The Ralph gate now includes a regression test that starts from a machine-drafted Japanese flute photo, submits Adam review context, and verifies retrieval, corpus, and photo prompt-pair seeds all use the Adam-reviewed truth.

Focused regression:

```bash
docker compose exec -T api pytest -q tests/test_ralph_phase2_photo_spine.py::test_machine_photo_memory_review_promotes_adam_context_over_system_inference
# passed

npm run typecheck --prefix apps/web
# passed
```

## Continuation Update: Readiness Panel Shows Reviewed-Only Holds

The next loop verified the UI change for the reviewed-only vector handoff state. The system now treats machine photo-memory drafts as useful review material, but not as final embedding-database seed records.

What changed:

- The downstream readiness metrics distinguish ready vector records from records held for Adam review.
- The photo-memory corpus metric now shows held machine drafts rather than implying retrieval failure.
- The vector handoff card now displays:
  - JSONL records ready for embedding,
  - held records awaiting Adam review,
  - reviewed-only policy,
  - no-inline-vector policy.

Current baseline after this loop:

```bash
docker compose exec -T api pytest -q
# 68 passed

npm run typecheck --prefix apps/web
# passed

python3 scripts/ralph_loop_gate.py --json
# PASS, 23 live checks

git diff --check
# clean
```

Next useful loop target:

- Make held vector records inspectable in the readiness panel so Adam can see which photo memories are blocked and why, instead of only seeing the aggregate count.

## Continuation Update: Held Vector Records Are Inspectable

The next loop made reviewed-only vector holds explicit records rather than aggregate counts. This matters because "5 held for Adam review" is safer than accidental export, but it still leaves Adam guessing what needs attention.

What changed:

- Default vector handoff/corpus exclusions now include:
  - source photo ID and source photo title,
  - memory/title label,
  - review status,
  - review queue,
  - truth status and boundary reviewer,
  - exclusion reasons,
  - a suggested next action.
- Boundary exclusions and Adam-review holds are now distinguished:
  - `held_for_adam_review` for machine photo-memory drafts,
  - `excluded_by_boundary` for scope/privacy failures.
- The downstream readiness panel now lists the first held vector records directly in the Vector Handoff card.
- The Ralph gate now fails if held vector records lack a title, source photo identity, reason, review status, or actionable next step.

Current baseline after this loop:

```bash
docker compose exec -T api pytest -q
# 68 passed

npm run typecheck --prefix apps/web
# passed

python3 scripts/ralph_loop_gate.py --json
# PASS, 23 live checks

git diff --check
# clean
```

Live evidence:

- Default vector handoff still exports `0` JSONL records because the current live photo memories are machine drafts.
- It now exposes held samples such as:
  - `Romil and Japanese Flute IV.jpg` / `requires_adam_review`,
  - `Rotmil Honors VIII.jpg` / `requires_adam_review`,
  - `Rotmil_Scan_15_2-2018 - Adam with flowers.jpg` / `requires_adam_review`.

Next useful loop target:

- Add a focused reviewed-photo promotion path in the UI/API so a held photo memory can be promoted into a reviewed vector handoff record after Adam supplies context, then prove the default vector export emits that reviewed record.

## Continuation Update: Held Vector Records Open Exact Review Tasks

The next loop connected the held vector handoff records back to their human review tasks. A held record is now not just inspectable, but actionable from the readiness surface.

What changed:

- Adam-review vector holds now include:
  - `review_task_id`,
  - `review_task_human_id`,
  - `review_queue: vision_drafts_needing_review`.
- The Vector Handoff card now shows an `Open review` button for held records that have a review task.
- The existing workbench callback opens the selected task in Review -> Photos, so held vector rows can take Adam directly to the relevant photo-memory review item.
- The Ralph gate now fails if an Adam-review hold lacks an exact review task reference.

Current baseline after this loop:

```bash
docker compose exec -T api pytest -q
# 68 passed

npm run typecheck --prefix apps/web
# passed

python3 scripts/ralph_loop_gate.py --json
# PASS, 23 live checks

git diff --check
# clean
```

Live evidence:

- Held vector samples now include exact task IDs, for example:
  - `Romil and Japanese Flute IV.jpg` -> `TASK_PHOTO_MEMORY_REVIEW_000725`,
  - `Rotmil Honors VIII.jpg` -> `TASK_PHOTO_MEMORY_REVIEW_000726`,
  - `Rotmil_Scan_15_2-2018 - Adam with flowers.jpg` -> `TASK_PHOTO_MEMORY_REVIEW_000727`.

Next useful loop target:

- Add a small "promotion proof" endpoint or report that simulates the post-review state from an Adam-authored fixture and shows the reviewed record entering the default vector handoff without allowing machine drafts through.

## Continuation Update: Machine Draft Vector Preview Is Explicitly Non-Production

The next loop tightened the distinction between "inspectable draft material" and "downstream vector-store input." Machine photo-memory drafts are valuable for review, but they must not quietly become production embedding records.

What changed:

- `include_machine_drafts=true` corpus and vector handoff responses now mark themselves:
  - `preview_only: true`,
  - `not_for_downstream_vector_store: true`.
- Default reviewed-only corpus and vector handoff responses now explicitly mark:
  - `preview_only: false`,
  - `not_for_downstream_vector_store: false`.
- The Downstream Readiness panel now shows a Draft preview row with the machine-draft preview count and "not for vector DB" policy.
- The Ralph gate now checks both the default export and the machine-draft preview export:
  - default path must be reviewed-only and production-eligible if records exist,
  - draft-preview path must declare itself preview-only and not production vector-store ready.

Current baseline after this loop:

```bash
docker compose exec -T api pytest -q
# 68 passed

npm run typecheck --prefix apps/web
# passed

python3 scripts/ralph_loop_gate.py --json
# PASS, 23 live checks

git diff --check
# clean
```

Live evidence:

- Default vector handoff: `0` records, `5` held, `preview_only: false`.
- Machine-draft preview: `5` records, `preview_only: true`, `not_for_downstream_vector_store: true`.

Next useful loop target:

- Add a visible post-review readiness proof showing the exact fields Adam must supply to promote one held photo memory from draft preview into the reviewed-only default vector handoff.

## Continuation Update: Vector Holds Explain Promotion Requirements

The next loop added the missing "how does this become real?" explanation to held vector records. The UI now does more than say a record is blocked; it tells Adam which review decisions promote it.

What changed:

- Adam-review vector holds now carry `promotion_requirements` with:
  - required review decisions,
  - minimum requirements for reviewed vector handoff,
  - reviewed record requirements,
  - promotion effect.
- The requirements explicitly preserve provenance:
  - metadata source must become `photo_memory_review`,
  - truth status must be one of the reviewed truth statuses,
  - boundary reviewer must be `adam`.
- The Vector Handoff card now summarizes the key promotion fields:
  - Adam context note,
  - question answers,
  - privacy level,
  - downstream readiness.
- The Ralph gate now fails if a held machine draft does not explain those promotion requirements.

Current baseline after this loop:

```bash
docker compose exec -T api pytest -q
# 68 passed

npm run typecheck --prefix apps/web
# passed

python3 scripts/ralph_loop_gate.py --json
# PASS, 23 live checks

git diff --check
# clean
```

Next useful loop target:

- Add a review-submission receipt/check that immediately shows whether the just-reviewed photo memory entered the default vector handoff, stayed held, or was excluded by boundary.

## Continuation Update: Photo Review Receipts Report Vector Handoff Status

The next loop connected photo review submission to downstream vector readiness. After Adam submits a photo-memory review, the receipt can now state whether the reviewed memory became eligible for the default vector handoff.

What changed:

- Photo profile promotion now returns:
  - `vector_handoff_status`,
  - `vector_handoff_reason`,
  - `vector_handoff_record_id`.
- Possible receipt states distinguish:
  - `eligible_reviewed_record`,
  - `excluded_by_boundary`,
  - `held_pending_downstream_clearance`,
  - `held_missing_memory_context`.
- Task receipts now label `memory_embedding_record_id` and `vector_handoff_record_id` as downstream outcomes.
- The task submit API now includes vector handoff status/reason/record ID in the embedded receipt.
- The web submit receipt banner now displays vector handoff status and reason alongside boundary/downstream status.

Current baseline after this loop:

```bash
docker compose exec -T api pytest -q
# 68 passed

npm run typecheck --prefix apps/web
# passed

python3 scripts/ralph_loop_gate.py --json
# PASS, 23 live checks

git diff --check
# clean
```

Focused proof:

- The Adam-reviewed Japanese flute fixture now returns:
  - `vector_handoff_status: eligible_reviewed_record`,
  - `vector_handoff_record_id == memory_embedding_record_id`,
  - a receipt outcome labeled `Vector handoff record`.

Next useful loop target:

- Broaden the receipt proof with a negative boundary case, so a sealed/private-sensitive reviewed photo proves it stays out of vector handoff and reports `excluded_by_boundary`.

## Continuation Update: Sealed Photo Reviews Cannot Over-Promise Vector Eligibility

The next loop added the negative proof and it caught a real edge. A reviewed sealed photo could create a memory embedding row, but it must still report vector handoff exclusion because boundary policy wins over the existence of an embedding row.

What changed:

- Vector handoff receipt status now checks boundary exclusion before declaring a reviewed record eligible.
- `vector_handoff_record_id` is explicit:
  - set to the memory embedding ID only for `eligible_reviewed_record`,
  - set to `null` for boundary-excluded or held states.
- Vision-review artifact creation now preserves explicit vector status/reason/record fields even when the record ID is null.
- Added a sealed-photo regression:
  - Adam reviews the photo,
  - supplies context,
  - marks it `sealed`,
  - receipt reports `excluded_by_boundary`,
  - default vector export emits zero records and one boundary exclusion.

Current baseline after this loop:

```bash
docker compose exec -T api pytest -q
# 69 passed

npm run typecheck --prefix apps/web
# passed

python3 scripts/ralph_loop_gate.py --json
# PASS, 23 live checks

git diff --check
# clean
```

Next useful loop target:

- Add a manifest-level count of reviewed-ready, Adam-review-held, and boundary-excluded photo memory rows, so the vector handoff summary explains the whole population rather than only record/excluded counts.

## Continuation Update: Vector Handoff Manifest Explains The Whole Population

The next loop made vector handoff summaries more legible and testable. The manifest no longer only says `record_count` and `excluded_count`; it now explains why the population is in that state.

What changed:

- Photo-memory corpus and vector handoff export now include:
  - `reviewed_ready_count`,
  - `machine_draft_preview_record_count`,
  - `held_for_adam_review_count`,
  - `boundary_excluded_count`,
  - `review_status_counts`,
  - `exclusion_reason_counts`.
- The default reviewed-only export counts reviewed JSONL rows separately from held/excluded records.
- The machine-draft preview counts draft rows as `machine_draft_preview_record_count`, not reviewed-ready rows.
- The Downstream Readiness Vector Handoff card now shows a population summary:
  - ready,
  - held,
  - boundary excluded.
- The Ralph gate now checks manifest counts against the actual JSONL rows and excluded record list.

Current baseline after this loop:

```bash
docker compose exec -T api pytest -q
# 69 passed

npm run typecheck --prefix apps/web
# passed

python3 scripts/ralph_loop_gate.py --json
# PASS, 23 live checks

git diff --check
# clean
```

Live evidence:

- Default vector handoff:
  - `reviewed_ready_count: 0`,
  - `held_for_adam_review_count: 5`,
  - `boundary_excluded_count: 0`.
- Draft preview:
  - `machine_draft_preview_record_count: 5`,
  - `preview_only: true`.

Next useful loop target:

- Improve retrieval-gap candidate ranking so no-result queries use available draft/review metadata as weak candidate evidence instead of only title overlap/backlog sampling.

## Continuation Update: Retrieval Gaps Now Carry Evidence Without Making Memory Claims

This loop tightened the "no boundary-cleared memory result" path. The product can now surface candidate photo groups for Adam to review without implying that any candidate is already a memory.

What changed:

- Retrieval gaps now consider two reviewable candidate types:
  - preview-ready photo groups with no photo-memory profile,
  - machine-draft photo-memory profiles that still need Adam review.
- Each candidate group now includes:
  - `candidate_status`,
  - `candidate_queue`,
  - `candidate_match_quality`,
  - `selection_reason`,
  - `matched_query_terms`,
  - `candidate_evidence`.
- Candidate evidence explicitly records:
  - `not_memory_claim: true`,
  - source fields used for the suggestion,
  - whether the evidence came from filename/title only or a machine photo-memory draft,
  - machine truth provenance and Adam-review requirements for draft profiles,
  - exact review task IDs when a draft-review task exists.
- Backlog-only candidates are now labeled as `backlog_only` and cannot masquerade as semantic hits.
- Candidate ranking now prioritizes real weak evidence when present, but avoids putting unrelated machine drafts first when there is no query overlap.
- The Ralph gate now fails if no-result photo retrieval gaps omit evidence source, match quality, non-memory disclaimers, or actionable review queues.

Current baseline after this loop:

```bash
docker compose exec -T api pytest -q
# 70 passed

npm run typecheck --prefix apps/web
# passed inside Ralph gate

python3 scripts/ralph_loop_gate.py --json
# PASS, 23 live checks

git diff --check
# clean
```

Live evidence:

- `airplane in Maine` still returns no memory result, which is honest.
- The retrieval gap now reports:
  - `truth_status: no_claim`,
  - `candidate_photo_group_count: 27`,
  - `photo_groups_needing_context_count: 22`,
  - `photo_groups_needing_draft_review_count: 5`,
  - candidate groups with explicit `candidate_match_quality` and `candidate_evidence`.

Next useful loop target:

- Add a user-facing review action from retrieval-gap candidates into the photo context/draft review workflow, so the fallback is not just informative but directly actionable in the workbench.

## Continuation Update: Retrieval Gap Candidates Have Direct Workbench Actions

This loop connected the retrieval-gap backend contract to the workbench UI. A no-result retrieval card can now show candidate review actions without guessing what kind of work the candidate needs.

What changed:

- Retrieval-gap candidate groups now include a `primary_action` object.
- `primary_action` can tell the UI to:
  - create a photo context task for an unprofiled photo group,
  - open an existing photo context task,
  - open an existing machine-draft review task.
- Machine-draft candidates carry exact task IDs in both `candidate_evidence` and `primary_action`.
- The Downstream Readiness "Retrieval Proof" card now renders action buttons from this contract.
- The action button uses `Open draft review` / `Create context task` labels instead of the old title-match language.
- The button title/ARIA text explicitly says the candidate is not a memory claim and names the evidence source.

Current baseline after this loop:

```bash
docker compose exec -T api pytest -q
# 70 passed

npm run typecheck --prefix apps/web
# passed

python3 scripts/ralph_loop_gate.py --json
# PASS, 23 live checks

git diff --check
# clean
```

Browser check:

- Synced updated web files into `chas-web-1` and restarted the web container.
- Opened the in-app browser at `http://localhost:3003/`.
- Verified the Exports view shows:
  - `airplane in Maine`,
  - retrieval-gap action buttons,
  - `Create context task: ... - backlog only` labels.

Next useful loop target:

- Make retrieval-gap fallback samples less noisy by filtering or ranking non-photo-like preview assets, so backlog suggestions do not start with things like Photoshop cover files unless no better photo candidates exist.

## Continuation Update: Retrieval Gap Backlog Is Less Noisy

This loop tightened the no-result photo retrieval path so backlog suggestions prefer photo-like assets over design/document image files.

What changed:

- Retrieval-gap candidate groups now expose `candidate_media_kind`.
- Candidate evidence repeats the same media kind so the UI and export/debug views have a stable audit trail.
- Backlog ranking now prefers `photograph_like` groups before `design_or_document_image` groups when there is no semantic match.
- The live gate fails if the first fallback candidate is a design/document image.
- Browser verification confirmed the `airplane in Maine` fallback actions now start with `.jpg` photo candidates, not the Photoshop cover file.

Current baseline after this loop:

```bash
docker compose exec -T api pytest -q
# 71 passed

npm run typecheck --prefix apps/web
# passed

python3 scripts/ralph_loop_gate.py --json
# PASS, 23 live checks

git diff --check
# clean
```

Browser check:

- Opened the in-app browser at `http://localhost:3003/`.
- Verified the Exports view shows fallback buttons beginning with:
  - `Create context task: Rotmil_10_19 - Cathryn WIlson.jpg - backlog only`
  - `Create context task: Rotmil 2021 II.jpg - backlog only`
  - `Create context task: Rotmil 2021 III.jpg - backlog only`

Next useful loop target:

- Make the no-result retrieval panel say whether candidate actions are weak semantic matches or just backlog triage, so Adam can distinguish "maybe relevant" from "start annotating somewhere."

## Continuation Update: Retrieval Gap Shows Weak-vs-Backlog Counts

This loop added an explicit candidate-quality summary to the no-result retrieval contract and the workbench UI.

What changed:

- Retrieval gaps now include `weak_evidence_candidate_count` and `backlog_only_candidate_count`.
- Tests assert those counts add up to `candidate_photo_group_count` in weak-match, machine-draft, and backlog-only cases.
- The live gate now fails if weak/backlog counts are inconsistent, negative, or if weak evidence exists but is not ranked first.
- The Retrieval Proof card now displays the count summary next to the candidate actions.

Current baseline after this loop:

```bash
docker compose exec -T api pytest -q tests/test_ralph_phase2_photo_spine.py::test_photo_retrieval_gap_is_actionable_without_inventing_memory tests/test_ralph_phase2_photo_spine.py::test_photo_retrieval_gap_surfaces_machine_draft_candidates_as_non_memory_claims tests/test_ralph_phase2_photo_spine.py::test_photo_retrieval_gap_backlog_prefers_photo_like_assets_over_design_files
# 3 passed

npm run typecheck --prefix apps/web
# passed

python3 scripts/ralph_loop_gate.py --json
# PASS, 23 live checks

git diff --check
# clean
```

Browser check:

- Verified the Exports view shows `0 weak matches / 27 backlog candidates` for the `airplane in Maine` no-result gap.
- Verified the fallback action buttons still point to photo-like `.jpg` groups.

Next useful loop target:

- Add the same weak/backlog distinction to the machine-readable report artifacts so downstream reviewers and future loop runs can audit retrieval-gap quality without scraping the UI.

## Continuation Update: Retrieval-Origin Context Survives Task Creation

This loop made retrieval-gap actions preserve why the photo context task was created.

What changed:

- `POST /api/assets/photo-review-inventory/context-task` now accepts optional retrieval-origin fields:
  - `source_query`,
  - `candidate_match_quality`,
  - `candidate_selection_reason`.
- New photo context tasks store a `retrieval_gap_origin` object with:
  - the query that led to the task,
  - weak/backlog match quality,
  - selection reason,
  - `truth_status: no_claim`,
  - `not_memory_claim: true`.
- Retrieval-gap action buttons now pass the active query and candidate quality into task creation.
- The photo task group card displays the retrieval-gap origin when it exists.
- The Ralph live gate now includes a focused contract test proving retrieval-origin context is retained.

Current baseline after this loop:

```bash
docker compose exec -T api pytest -q
# 72 passed

npm run typecheck --prefix apps/web
# passed

python3 scripts/ralph_loop_gate.py --json
# PASS, 23 live checks

git diff --check
# clean
```

Next useful loop target:

- Make task receipts for completed photo context reviews include the retrieval-origin query when present, so downstream memory/vector records remain traceable back to the discovery question.

## Continuation Update: Retrieval-Origin Provenance Reaches Receipts

This loop carried retrieval-gap origin data through the completed task receipt.

What changed:

- Task receipts now include `summary.retrieval_origin` when a photo context task was created from a retrieval gap.
- The submit response exposes the same retrieval origin in `creates_or_updates.receipt.retrieval_origin`.
- The receipt keeps `truth_status: no_claim` and `not_memory_claim: true`, so the original retrieval gap cannot become a memory claim by accident.
- Retrieval-gap `primary_action.request.body` is now self-contained:
  - `source_query`,
  - `candidate_match_quality`,
  - `candidate_selection_reason`.
- The Ralph gate fails if create-photo-context actions omit the query or candidate quality fields.

Current baseline after this loop:

```bash
docker compose exec -T api pytest -q tests/test_ralph_phase2_photo_spine.py::test_photo_retrieval_gap_is_actionable_without_inventing_memory tests/test_ralph_phase2_photo_spine.py::test_photo_context_task_created_from_retrieval_gap_preserves_query_origin
# 2 passed

python3 scripts/ralph_loop_gate.py --json
# PASS, 23 live checks

git diff --check
# clean
```

Next useful loop target:

- Make reviewed photo memory/profile records also retain retrieval-origin provenance when a photo context task had that origin, so vectors and future prompt-pair candidates can trace all the way back to the discovery query.

## Continuation Update: Retrieval-Origin Provenance Reaches Memory and Embedding Records

This loop carried the no-result discovery query into downstream photo-memory artifacts after Adam review.

What changed:

- Reviewed photo metadata profiles now retain `retrieval_gap_origin` in `raw_profile`.
- Profile retrieval notes now include a labeled retrieval-origin block:
  - query,
  - candidate quality,
  - selection reason,
  - `truth_status: no_claim`,
  - explicit non-memory-claim disclaimer.
- Profile embedding records include retrieval-origin metadata and the labeled origin text in the embedding input.
- Memory-source notes include the retrieval-origin block.
- Memory embedding records include the profile retrieval notes and carry retrieval-origin metadata.
- Tests assert that the origin reaches the receipt, metadata profile, profile embedding, and memory embedding.

Current baseline after this loop:

```bash
docker compose exec -T api pytest -q
# 72 passed

npm run typecheck --prefix apps/web
# passed

python3 scripts/ralph_loop_gate.py --json
# PASS, 23 live checks

git diff --check
# clean
```

Next useful loop target:

- Make prompt-pair candidates generated from photo memories carry the same retrieval-origin provenance when available, so voice-training review can see whether the source was discovered from a retrieval gap.

## Continuation Update: Retrieval-Origin Provenance Reaches Photo Prompt-Pair Candidates

This loop carried the same no-claim retrieval provenance into photo-derived Prompt Pair tickets.

What changed:

- Photo prompt-pair candidate responses now include `retrieval_gap_origin` when the underlying reviewed photo profile came from a retrieval gap.
- Generated Prompt Pair tasks now retain that origin in `input_payload`, alongside the source photo id, photo profile id, boundary snapshot, and embedding input text.
- Prompt specs and context packs now carry the origin as workflow provenance.
- The context pack explicitly labels retrieval origin as "workflow provenance only; not a source fact or memory claim."
- The Prompt Pair photo source card now surfaces the original retrieval query and match quality for review context.
- Tests assert the origin survives from a photo context task into the prompt-pair candidate, prompt spec, context pack, and review task.

Current focused baseline after this loop:

```bash
docker compose exec -T api pytest -q tests/test_ralph_phase2_photo_spine.py::test_photo_memory_prompt_pair_candidates_link_photo_profile_boundary_and_embedding_text
# 1 passed

npm run typecheck --prefix apps/web
# passed
```

Next useful loop target:

- Make the photo-memory vector handoff/export include retrieval-origin metadata where available, so downstream semantic search records can be audited back to the discovery query without treating the query as a remembered fact.

## Continuation Update: Retrieval-Origin Provenance Reaches Vector Handoff JSONL

This loop made the downstream vector export carry retrieval-origin provenance in machine-readable form.

What changed:

- Photo-memory handoff summaries now count:
  - `retrieval_origin_record_count`,
  - `retrieval_origin_no_claim_count`.
- Vector JSONL records now include `metadata.retrieval_gap_origin` when the underlying memory embedding has it.
- The export manifest proves that every retrieval-origin record preserved `truth_status: no_claim` and `not_memory_claim: true`.
- The Ralph live gate now checks that JSONL retrieval-origin metadata stays no-claim and that manifest counts match parsed JSONL records.
- Tests prove stable JSONL export, reviewed-only filtering, boundary exclusion, no inline vectors, and retrieval-origin metadata in the exported record.

Current focused baseline after this loop:

```bash
docker compose exec -T api pytest -q tests/test_ralph_phase2_photo_spine.py::test_photo_memory_embedding_export_is_stable_jsonl_with_manifest_and_boundaries
# 1 passed

docker compose exec -T api pytest -q tests/test_ralph_phase2_photo_spine.py::test_photo_memory_prompt_pair_candidates_link_photo_profile_boundary_and_embedding_text
# 1 passed

npm run typecheck --prefix apps/web
# passed
```

Next useful loop target:

- Strengthen the corpus endpoint and retrieval search results so the same retrieval-origin audit data appears consistently in interactive search/corpus previews, not only in export JSONL.

## Continuation Update: Retrieval-Origin Provenance Appears In Corpus And Search Previews

This loop made retrieval-origin provenance visible before export.

What changed:

- Search results now include `retrieval_gap_origin` when the matched embedding record has retrieval-origin metadata.
- Photo-memory corpus records now expose `retrieval_gap_origin` as a top-level preview field, while still keeping the raw metadata copy.
- Corpus summaries now report `retrieval_origin_record_count` and `retrieval_origin_no_claim_count`.
- The Ralph gate now checks corpus/search retrieval origins retain `truth_status: no_claim` and `not_memory_claim: true`.
- Tests now prove the same origin appears in:
  - corpus record previews,
  - export JSONL records,
  - search results.

Current focused baseline after this loop:

```bash
docker compose exec -T api pytest -q tests/test_ralph_phase2_photo_spine.py::test_photo_memory_embedding_export_is_stable_jsonl_with_manifest_and_boundaries
# 1 passed

npm run typecheck --prefix apps/web
# passed
```

Next useful loop target:

- Run the full API, web, and live Ralph gate suites, then use any failures to choose the next increment rather than declaring the loop complete from focused tests alone.

## Continuation Update: Empty Vector Handoff State Has Actionable Review Tasks

This loop strengthened the "no reviewed vector records yet" state.

What changed:

- Photo-memory corpus responses now expose `next_review_actions`.
- Vector handoff exports now expose `next_review_actions` both at the top level and inside the manifest.
- Each held action includes:
  - source photo id/title,
  - review task id/human id when a human review task exists,
  - review queue/status,
  - reasons,
  - suggested next action.
- The Downstream Readiness panel now reads the `next_review_actions` contract directly and shows how many review actions the API exposes.
- The Ralph gate now fails if an empty reviewed corpus or empty vector handoff has exclusions but no actionable next review list.

Current baseline after this loop:

```bash
docker compose exec -T api pytest -q
# 72 passed

npm run typecheck --prefix apps/web
# passed

python3 scripts/ralph_loop_gate.py --json
# PASS, live gate includes next_review_action_count: 5 for corpus/vector handoff

git diff --check
# clean
```

Next useful loop target:

- Improve the photo review task type handling so the same "Open review" action can route cleanly to either photo context tasks or vision draft review tasks without relying on a generic callback name.

## Continuation Update: Review Opening Callback Is Generic

This loop cleaned up a small but important UI contract.

What changed:

- Renamed the readiness callback from `onOpenPhotoContextTask` to `onOpenReviewTask`.
- The Exports panel and Downstream Readiness panel now use the generic review-task callback for both:
  - newly created photo context tasks,
  - existing machine photo-memory draft review tasks.
- The app-level opener was renamed to `openPhotoReviewTask`.
- Typecheck and the live Ralph gate still pass after copying the updated web files into the running container.

Current baseline after this loop:

```bash
npm run typecheck --prefix apps/web
# passed

python3 scripts/ralph_loop_gate.py --json
# PASS

git diff --check
# clean
```

Next useful loop target:

- Add a lightweight API/runtime consistency check to the Ralph gate so future loops catch "source changed but running container has stale baked app code" immediately.

## Continuation Update: Runtime Contract Catches Stale API Containers

This loop made the live gate stricter about the running API matching the checked-out source.

What changed:

- Added `apps/api/app/runtime_contract.py` with a small runtime contract ID and required downstream-readiness fields.
- Added `GET /api/runtime-contract`.
- The endpoint reports:
  - `contract_id`,
  - required response fields for photo-memory corpus and vector handoff,
  - `runtime_contract_source_sha256`,
  - the MVP no-fine-tuning rule.
- The Ralph gate now compares the live endpoint to the checked-out source contract.
- If future code changes update the runtime contract file but the API container is stale, the live gate fails immediately with a contract ID/checksum mismatch.

Current focused baseline after this loop:

```bash
docker compose exec -T api pytest -q tests/test_ralph_phase3_prompt_pair_audit.py::test_runtime_contract_endpoint_matches_source_contract
# 1 passed

python3 scripts/ralph_loop_gate.py --json
# PASS, 24 live checks including API runtime contract match
```

Next useful loop target:

- Add a machine-readable morning report/checkpoint artifact from the live gate output so a long loop can leave behind exact evidence, not only prose.

## Continuation Update: Live Gate Writes Checkpoint Artifacts

This loop made the long-run evidence durable.

What changed:

- `scripts/ralph_loop_gate.py` now supports `--write-checkpoint`.
- A checkpoint run writes:
  - timestamped JSON,
  - timestamped Markdown,
  - `updates/ralph_loop_gate_checkpoint_latest.json`,
  - `updates/ralph_loop_gate_checkpoint_latest.md`.
- The JSON includes every check, every failure detail, and all machine-readable evidence.
- The Markdown gives a morning-readable summary while preserving exact pass/fail details.

Current baseline after this loop:

```bash
python3 -m py_compile scripts/ralph_loop_gate.py
# passed

python3 scripts/ralph_loop_gate.py --write-checkpoint --json
# PASS, wrote checkpoint artifacts under updates/
```

Latest checkpoint artifacts:

- `updates/ralph_loop_gate_checkpoint_latest.json`
- `updates/ralph_loop_gate_checkpoint_latest.md`

Next useful loop target:

- Tighten the demo-generation readiness contract so, once credentials are supplied, generated demo outputs can be stored as `model_generated` proof artifacts without ever becoming training truth.

## Continuation Update: Demo Generations Store Proof Without Training Truth

This loop prepared Objective 5.4 for the moment credentials are supplied, while keeping the current live app honest and blocked.

What changed:

- Added `POST /api/model-status/demo-generations`.
- With missing credentials or live generation disabled, the endpoint returns a blocked status and creates no records.
- When live generation is enabled, the endpoint creates:
  - a `PromptSpec` with `truth_mode: model_generated`,
  - a `ContextPack` marked demo-only and excluded from training export,
  - a `Generation` row with model name, reasoning effort, reference IDs, Adam-review requirement, and `excluded_from_training_export: true`.
- Held-out prompt responses are not sent back into the source text used for demo generation.
- The endpoint creates no `GoldVoiceExample`, `SFTCandidate`, or `DPOPair` records.
- The Ralph gate now runs the demo-generation proof test.

Current focused baseline after this loop:

```bash
docker compose exec -T api pytest -q \
  tests/test_ralph_phase1_training_spine.py::test_demo_generation_readiness_lists_held_out_prompts_and_honest_credential_blocker \
  tests/test_ralph_phase1_training_spine.py::test_demo_generation_endpoint_stores_model_generated_outputs_without_training_truth
# 2 passed

python3 scripts/ralph_loop_gate.py --write-checkpoint --json
# PASS, 25 live checks
```

Honest blocker:

- Live demo generation is still blocked in this environment by `text_generation_live_calls_disabled` and `openai_api_key_missing`.

Next useful loop target:

- Surface the demo-generation endpoint in the readiness UI as a gated action, so Adam can see exactly why it is blocked now and what it will create once credentials are present.

## Continuation Update: Demo Generation Gate Is Visible In The UI

This loop connected the safe demo-generation endpoint to the readiness surface.

What changed:

- The Downstream Readiness panel now shows the demo output policy:
  - `model_generated`,
  - excluded from training.
- The panel now includes a `Generate demo outputs` action.
- While credentials are absent, the action is disabled and shows the live blockers.
- Once live GPT-5.5 credentials and the live-call gate are present, the button will call `POST /api/model-status/demo-generations`.
- The UI action reports whether demo outputs were stored or whether the blocker remains.

Verification:

```bash
npm run typecheck --prefix apps/web
# passed

python3 scripts/ralph_loop_gate.py --write-checkpoint --json
# first run failed Web app is reachable immediately after container restart with ConnectionResetError
# rerun passed after the web server settled
```

Current live checkpoint:

- `updates/ralph_loop_gate_checkpoint_latest.json`
- `updates/ralph_loop_gate_checkpoint_latest.md`

Next useful loop target:

- Add a browser-level smoke check for the readiness UI labels/actions so frontend regressions are caught beyond TypeScript and HTTP 200.

## Continuation Update: Browser-Gated Queue Findability

This loop turned a failed browser assertion into a clearer prompt-pair review contract.

What changed:

- Added a real queue search box in the workbench header.
- Queue search now searches task titles, prompts, responses, sources, voice modes, and ticket metadata inside the current queue scope.
- Prompt-pair ticket titles now include artifact mode, so parallel SFT/DPO tickets are distinguishable:
  - `SFT Pair 001: How's Portland today?`
  - `DPO Pair 001: How's Portland today?`
- Added browser coverage proving:
  - voice-mode filters use the live prompt-pair audit counts,
  - searching `How's Portland today?` reveals the two expected SFT/DPO sibling tickets,
  - applying the SFT artifact filter narrows that search to the exact singleton ticket.

Verification:

```bash
npm run typecheck --prefix apps/web
# passed

npx --prefix apps/web playwright test --config apps/web/playwright.config.ts
# 4 passed

python3 scripts/ralph_loop_gate.py --write-checkpoint --json
# PASS, 26 live checks
```

Current live checkpoint:

- `updates/ralph_loop_gate_checkpoint_20260429T075603_145730Z.json`
- `updates/ralph_loop_gate_checkpoint_latest.json`
- `updates/ralph_loop_gate_checkpoint_latest.md`

Next useful loop target:

- Make the prompt-pair review receipt more explicit after Submit, so the user can immediately see whether the item produced an approved export artifact, a candidate/held artifact, or a boundary/rubric block.

## Continuation Update: Submit Receipts Explain Training Artifact Status

This loop made prompt-pair Submit outcomes less mysterious.

What changed:

- Durable task receipts now include an `export_artifact` summary for gold/prompt-pair submissions.
- The receipt summary records:
  - produced artifact modes,
  - SFT/DPO artifact ids,
  - approved/candidate statuses,
  - structural checks such as SFT `system/user/assistant` and DPO chosen/rejected distinctness,
  - review blockers when an artifact is held.
- The API submit response now returns this same export-artifact summary.
- The workbench submit banner now shows a `Training export receipt` block after Submit, with ready/held status and blockers.
- The Ralph gate now runs focused receipt tests for:
  - approved SFT+DPO output,
  - candidate-held SFT output,
  - DPO-only output.

Verification:

```bash
docker compose exec -T api pytest -q \
  tests/test_task_submit.py::test_gold_voice_submission_creates_annotation_and_training_artifacts \
  tests/test_task_submit.py::test_gold_voice_response_b_minor_issue_stays_candidate_until_resolved \
  tests/test_task_submit.py::test_unified_dpo_gold_submission_creates_dpo_only_artifact
# 3 passed

python3 scripts/ralph_loop_gate.py --write-checkpoint --json
# PASS, 27 live checks
```

Current live checkpoint:

- `updates/ralph_loop_gate_checkpoint_20260429T080035_910494Z.json`
- `updates/ralph_loop_gate_checkpoint_latest.json`
- `updates/ralph_loop_gate_checkpoint_latest.md`

Next useful loop target:

- Add an approved-export end-to-end UI/browser proof, so a submitted prompt pair can be followed all the way to the Exports panel and verified as export-ready without relying only on backend tests.

## Continuation Update: Gallery Preview Is Boundary-Aware

This loop added a first real gallery surface for photo-memory work without pretending machine drafts are finished memories.

What changed:

- Added `GET /api/gallery/reviewed-photos`.
- Gallery results carry:
  - source photo ids,
  - preview/thumbnail URLs,
  - family/public boundary snapshots,
  - reviewed vs. machine-draft status,
  - `requires_adam_review` labels,
  - memory captions and linked memory ids.
- The endpoint defaults to reviewed-only results, while `include_drafts=true` allows review-safe draft previews.
- The downstream readiness panel now shows a `Gallery Preview` section with live thumbnails and review labels.
- The Ralph gate now verifies the gallery endpoint and the browser-visible gallery preview.

Verification:

```bash
docker compose exec -T api pytest -q \
  tests/test_ralph_phase2_photo_spine.py::test_gallery_review_endpoint_defaults_to_reviewed_and_can_preview_drafts
# 1 passed

npm run typecheck --prefix apps/web
# passed

npx --prefix apps/web playwright test --config apps/web/playwright.config.ts
# 4 passed

python3 scripts/ralph_loop_gate.py --write-checkpoint --json
# PASS, 29 live checks
```

Current live checkpoint:

- `updates/ralph_loop_gate_checkpoint_20260429T081004_868085Z.json`
- `updates/ralph_loop_gate_checkpoint_latest.json`
- `updates/ralph_loop_gate_checkpoint_latest.md`

Next useful loop target:

- Add a narrow review-action path from gallery/photo drafts into a durable Adam-review task or promoted reviewed record, then gate that the system can move at least one photo from draft preview to reviewed memory without losing provenance.

## Continuation Update: Gallery Drafts Open Review Tasks

This loop turned the gallery preview into a real work surface instead of a passive thumbnail strip.

What changed:

- Gallery items now include review task fields for draft photo memories:
  - `review_task_id`
  - `review_task_human_id`
  - `review_task_queue`
  - `review_task_status`
- Draft gallery cards now show `Open gallery review`, which opens the corresponding photo memory review task.
- The browser test now proves this flow from Exports -> Gallery Preview -> Vision Draft Review.
- The Ralph gate now fails if draft gallery items lack a review-task link.

Verification:

```bash
docker compose exec -T api pytest -q \
  tests/test_ralph_phase2_photo_spine.py::test_gallery_review_endpoint_defaults_to_reviewed_and_can_preview_drafts
# 1 passed

npm run typecheck --prefix apps/web
# passed

npx --prefix apps/web playwright test --config apps/web/playwright.config.ts
# 5 passed

python3 scripts/ralph_loop_gate.py --write-checkpoint --json
# PASS, 29 live checks
```

Current live checkpoint:

- `updates/ralph_loop_gate_checkpoint_20260429T081540_277572Z.json`
- `updates/ralph_loop_gate_checkpoint_latest.json`
- `updates/ralph_loop_gate_checkpoint_latest.md`

Next useful loop target:

- Add a non-destructive, test-only end-to-end proof that submitting a photo memory review promotes a draft into an Adam-reviewed memory, a reviewed gallery item, and a vector-handoff-eligible embedding record.

## Continuation Update: Photo Promotion Retires Stale Draft Gallery Items

This loop closed a provenance leak in the photo gallery path.

What changed:

- When Adam submits a photo memory review, the system now removes the old `GALLERY_MACHINE_DRAFT_PHOTOS` item for that same photo.
- If Adam approves the photo for family gallery/retrieval, the reviewed gallery item remains as the single gallery representation.
- If Adam seals the photo, the machine-draft gallery card is removed and no reviewed gallery item is created.
- The promotion receipt now exposes `removed_machine_draft_gallery_item_id`.
- Tests now prove:
  - reviewed photo promotion creates one clean reviewed gallery item,
  - vector handoff receives an Adam-reviewed embedding record,
  - sealed photos are excluded from both vector handoff and gallery output.

Verification:

```bash
docker compose exec -T api pytest -q \
  tests/test_ralph_phase2_photo_spine.py::test_machine_photo_memory_review_promotes_adam_context_over_system_inference \
  tests/test_ralph_phase2_photo_spine.py::test_sealed_photo_review_receipt_reports_boundary_exclusion_from_vector_handoff
# 2 passed

docker compose exec -T api pytest -q \
  tests/test_ralph_phase2_photo_spine.py::test_machine_photo_memory_drafts_create_profiles_memories_embeddings_and_retrieval \
  tests/test_ralph_phase2_photo_spine.py::test_machine_photo_memory_review_promotes_adam_context_over_system_inference \
  tests/test_ralph_phase2_photo_spine.py::test_sealed_photo_review_receipt_reports_boundary_exclusion_from_vector_handoff \
  tests/test_ralph_phase2_photo_spine.py::test_machine_photo_memory_drafts_do_not_overwrite_adam_reviewed_photo_profiles \
  tests/test_ralph_phase2_photo_spine.py::test_photo_memory_prompt_pair_candidates_link_photo_profile_boundary_and_embedding_text
# 5 passed

python3 scripts/ralph_loop_gate.py --write-checkpoint --json
# PASS, 29 live checks
```

Current live checkpoint:

- `updates/ralph_loop_gate_checkpoint_20260429T081809_605272Z.json`
- `updates/ralph_loop_gate_checkpoint_latest.json`
- `updates/ralph_loop_gate_checkpoint_latest.md`

Next useful loop target:

- Make the photo review form itself less noisy by pre-filling visible fields from the machine draft and making the downstream consequences clear before Submit.

## Continuation Update: Photo Review Shows Submit Consequences

This loop made the photo review form more legible at the moment of decision.

What changed:

- Added a compact `Submit consequence preview` inside the downstream memory preview.
- The preview now shows:
  - truth label,
  - vector handoff outcome,
  - gallery outcome,
  - explicit training status: `Not SFT/DPO material`.
- Browser coverage now verifies that the photo review surface exposes these consequences before Submit.

Verification:

```bash
npm run typecheck --prefix apps/web
# passed

npx --prefix apps/web playwright test --config apps/web/playwright.config.ts
# 5 passed

python3 scripts/ralph_loop_gate.py --write-checkpoint --json
# PASS, 29 live checks
```

Current live checkpoint:

- `updates/ralph_loop_gate_checkpoint_20260429T082040_273441Z.json`
- `updates/ralph_loop_gate_checkpoint_latest.json`
- `updates/ralph_loop_gate_checkpoint_latest.md`

Next useful loop target:

- Tighten the approved-export path for prompt pairs in the UI, so a user can see exactly when a prompt pair is only a review candidate versus approved training material.

## Continuation Update: Prompt Pair Editor Shows Export Gate

This loop made the approved-vs-candidate distinction visible inside the prompt-pair editor.

What changed:

- Added a `Prompt pair export gate` panel before the YAML preview.
- It shows:
  - Submit outcome,
  - dataset outcome,
  - gate notes/blocker count,
  - blocker chips when present.
- The UI now distinguishes `Approved JSONL after Submit` from `Candidate dry-run only` before the user presses Submit.
- Added browser coverage that opens a singleton prompt-pair ticket and verifies the export gate.

Verification:

```bash
npm run typecheck --prefix apps/web
# passed

npx --prefix apps/web playwright test --config apps/web/playwright.config.ts
# 5 passed

python3 scripts/ralph_loop_gate.py --write-checkpoint --json
# PASS, 29 live checks
```

Current live checkpoint:

- `updates/ralph_loop_gate_checkpoint_20260429T082439_301191Z.json`
- `updates/ralph_loop_gate_checkpoint_latest.json`
- `updates/ralph_loop_gate_checkpoint_latest.md`

Next useful loop target:

- Add a small API/browser audit that catches prompt-pair tickets whose UI gate says approved while the backend would hold them as candidates.

## Continuation Update: Backend Preflight Catches Prompt Pair Gate Drift

This loop made the prompt-pair export gate auditable from the backend, so the UI cannot quietly drift away from the server's export rules without the Ralph gate failing.

What changed:

- Added `/api/prompt-pairs/preflight-export-gate`.
- Centralized SFT/DPO export blockers into the backend preflight path.
- Extended the prompt-pair audit with:
  - `preflight_gate_counts`,
  - `preflight_mismatch_count`,
  - concrete mismatch reasons when a persisted UI preview disagrees with backend rules.
- Tightened `scripts/ralph_loop_gate.py` so the live gate now requires preflight coverage for every prompt pair and zero UI/backend mismatches.

Verification:

```bash
docker compose exec -T api pytest -q tests/test_ralph_phase3_prompt_pair_audit.py
# 9 passed

python3 -m py_compile scripts/ralph_loop_gate.py && git diff --check
# passed

python3 scripts/ralph_loop_gate.py --write-checkpoint --json
# PASS, 29 live checks
```

Current live checkpoint:

- `updates/ralph_loop_gate_checkpoint_20260429T083009_027906Z.json`
- `updates/ralph_loop_gate_checkpoint_latest.json`
- `updates/ralph_loop_gate_checkpoint_latest.md`

Next useful loop target:

- Replace the duplicated frontend prompt-pair gate rules with the backend preflight endpoint, so the visible editor preview is generated by the same rules that submit/export will enforce.

## Continuation Update: Prompt Pair Editor Uses Backend Preflight

This loop removed the browser-side duplicate export-gate logic from the Prompt Pair editor.

What changed:

- Added a web API client for `/api/prompt-pairs/preflight-export-gate`.
- The Prompt Pair editor now calls backend preflight while the user edits.
- The visible gate shows `Backend preflight` once the server has confirmed:
  - submit outcome,
  - dataset outcome,
  - blocker list,
  - normalized YAML preview.
- Drafted `export_gate_preview` is only persisted from the server response, so pending browser state does not masquerade as an approved export gate.
- Browser coverage now counts the preflight API request and fails if the editor does not call it.

Verification:

```bash
npm run typecheck --prefix apps/web
# passed

docker compose exec -T api pytest -q \
  tests/test_ralph_phase3_prompt_pair_audit.py::test_prompt_pair_preflight_export_gate_and_audit_catch_ui_mismatch
# 1 passed

npx --prefix apps/web playwright test --config apps/web/playwright.config.ts
# 5 passed

python3 scripts/ralph_loop_gate.py --write-checkpoint --json
# PASS, 29 live checks
```

Current live checkpoint:

- `updates/ralph_loop_gate_checkpoint_20260429T083728_757403Z.json`
- `updates/ralph_loop_gate_checkpoint_latest.json`
- `updates/ralph_loop_gate_checkpoint_latest.md`

Next useful loop target:

- Make the source-review Generate Pairs path expose an explicit pair-generation run receipt, so Adam can see how many singleton tickets were created, which strategy produced them, and why any source sections were held.

## Continuation Update: Generate Pairs Creates A Run Receipt

This loop made Source Review -> Generate Pairs explain itself.

What changed:

- `create_make_gold_tasks_from_review` now returns a durable `pair_generation_run` object.
- The run receipt records:
  - source task and annotation,
  - source title/text hash/character count,
  - prompt-instructions version,
  - candidate pair count,
  - created pair count,
  - held pair count,
  - held source-section count,
  - strategy counts,
  - live-model-call count,
  - created ticket/task IDs and prompt previews.
- Task receipts now include `pair_generation_run`.
- The submit banner shows a compact Pair generation receipt after Generate Pairs.
- Tests now prove both clean natural-section generation and a held structured source section are reported honestly.

Verification:

```bash
docker compose exec -T api pytest -q \
  tests/test_ralph_phase1_training_spine.py::test_source_review_generate_pairs_from_natural_sections_creates_singleton_prompt_pair_tasks \
  tests/test_task_submit.py::test_source_review_generate_pairs_from_structured_chunks_creates_singleton_prompt_pair_tasks
# 2 passed

python3 -m py_compile apps/api/app/services/pair_generation.py apps/api/app/services/task_receipts.py apps/api/app/routers/tasks.py && git diff --check
# passed

python3 scripts/ralph_loop_gate.py --write-checkpoint --json
# PASS, 29 live checks
```

Current live checkpoint:

- `updates/ralph_loop_gate_checkpoint_20260429T084250_877457Z.json`
- `updates/ralph_loop_gate_checkpoint_latest.json`
- `updates/ralph_loop_gate_checkpoint_latest.md`

Next useful loop target:

- Add pair-generation run details into the 200-pair audit pack, so Adam can audit examples together with their generation strategy, backend preflight status, and source-run provenance.

## Continuation Update: Audit Pack Shows Generation Provenance

This loop made the 200-pair human audit pack more useful for actual review.

What changed:

- Each audit-pack sample now includes backend preflight status:
  - export status,
  - submit outcome,
  - dataset outcome,
  - blocker list.
- Each sample also includes pair-generation provenance:
  - generation strategy,
  - prompt-instructions version when present,
  - live-model-call flag and other generation metadata.
- The markdown audit pack now has explicit `Backend Preflight` and `Pair Generation Provenance` sections for each sample.
- The pack remains honest: it proves structure/provenance/inspectability, not final Charles authenticity.

Verification:

```bash
docker compose exec -T api pytest -q tests/test_ralph_phase3_prompt_pair_audit.py
# 9 passed

python3 -m py_compile apps/api/app/services/prompt_pair_audit.py && git diff --check
# passed

python3 scripts/ralph_loop_gate.py --write-checkpoint --json
# PASS, 29 live checks
```

Current live checkpoint:

- `updates/ralph_loop_gate_checkpoint_20260429T084543_926567Z.json`
- `updates/ralph_loop_gate_checkpoint_latest.json`
- `updates/ralph_loop_gate_checkpoint_latest.md`

Next useful loop target:

- Add an explicit photo-context review pack/export preview, so Adam can inspect which imported photos still need context, which drafts are machine-only, and which records are safe for vector handoff/gallery.

## Continuation Update: Photo Context Review Pack

This loop turned photo intake from several separate panels into one review/export pack.

What changed:

- Added `/api/assets/photo-context-review-pack`.
- The pack now combines:
  - no-claim photo groups that need Adam-authored context,
  - machine-only photo memory drafts held for Adam review,
  - reviewed vector-ready records,
  - gallery preview items,
  - a human-readable YAML export preview,
  - a stable content hash.
- The pack keeps truth boundaries explicit:
  - unreviewed photo groups are `truth_status: no_claim`,
  - machine drafts remain `truth_status: system_inference`,
  - vector-ready records exclude `system_inference` and `model_generated` by default,
  - vector values are still not stored inline in ordinary DB rows.
- The Exports screen now shows a `Photo Context Review Pack` card with thumbnails, review actions, held-draft status, vector policy counts, and the YAML preview.
- The live Ralph gate now includes a dedicated photo-context review-pack check.

Live result:

- 273 photo assets.
- 82 preview-ready/previewable photos.
- 22 no-claim photo groups needing context.
- 5 machine drafts held for Adam review.
- 0 reviewed vector-ready records in live data so far.
- 0 vector policy violations.
- 5 gallery preview items.

Verification:

```bash
docker compose exec -T api pytest -q tests/test_ralph_phase2_photo_spine.py
# 16 passed

npm run typecheck --prefix apps/web
# passed

npx --prefix apps/web playwright test --config apps/web/playwright.config.ts
# 5 passed

python3 scripts/ralph_loop_gate.py --write-checkpoint --json
# PASS, 30 live checks

git diff --check
# clean
```

Current live checkpoint:

- `updates/ralph_loop_gate_checkpoint_20260429T085723_225500Z.json`
- `updates/ralph_loop_gate_checkpoint_latest.json`
- `updates/ralph_loop_gate_checkpoint_latest.md`

Next useful loop target:

- Promote the photo context pack from a passive preview into a review-session workflow: choose a batch of no-claim photo groups, open/save Adam context drafts, and show how many records would become vector/gallery-ready after submission.

## Continuation Update: Photo Context Review Session

This loop made the photo context pack actionable without making hidden truth claims.

What changed:

- Added `POST /api/assets/photo-context-review-pack/review-session`.
- The endpoint supports:
  - `dry_run=true`, which selects review-session items but creates no tasks,
  - `dry_run=false`, which creates or reuses `photo_context` tasks for the selected no-claim groups.
- Each session item preserves:
  - `truth_status: no_claim`,
  - `not_memory_claim: true`,
  - the target queue,
  - the created or existing task IDs.
- The Exports screen now has `Create top context tasks`, which creates the first batch and opens the first review task.
- The live gate now checks the dry-run path so the review-session contract cannot silently mutate state.

Verification:

```bash
docker compose exec -T api pytest -q \
  tests/test_ralph_phase2_photo_spine.py::test_photo_context_review_session_dry_runs_then_creates_no_claim_context_tasks \
  tests/test_ralph_phase2_photo_spine.py::test_photo_context_review_pack_combines_no_claim_gaps_held_drafts_and_vector_ready_records
# 2 passed

docker compose exec -T api pytest -q tests/test_ralph_phase2_photo_spine.py
# 17 passed

npm run typecheck --prefix apps/web
# passed

npx --prefix apps/web playwright test --config apps/web/playwright.config.ts
# 5 passed

python3 scripts/ralph_loop_gate.py --write-checkpoint --json
# PASS, 30 live checks
```

Current live checkpoint:

- `updates/ralph_loop_gate_checkpoint_20260429T090158_000894Z.json`
- `updates/ralph_loop_gate_checkpoint_latest.json`
- `updates/ralph_loop_gate_checkpoint_latest.md`

Next useful loop target:

- Add an after-submit projection for photo context tasks: before Adam submits, the UI should show exactly which memory/profile/embedding/gallery/vector artifacts would be created or held, using the current draft values.

## Continuation Update: Photo Context Submit Projection

This loop made the photo-context editor more honest before submission.

What changed:

- Added `POST /api/tasks/{task_id}/photo-context/projection`.
- The projection reads Adam's current draft decisions and returns the exact downstream consequences without creating annotations, profiles, memories, embeddings, OCR segments, or gallery rows.
- The projection reports:
  - metadata profile create/update status,
  - boundary snapshot after submit,
  - profile embedding readiness,
  - memory and memory-embedding/vector handoff status,
  - gallery eligibility,
  - OCR/handwriting segment status,
  - held/blocked reasons.
- The projection explicitly preserves the photo policy:
  - `does_not_mutate_state: true`,
  - `no_live_embedding_call: true`,
  - `ordinary_db_vector_storage: false`,
  - photo context is not SFT/DPO training material.
- The photo-context UI now replaces the local-only downstream preview with the backend submit projection when the selected task is a `photo_context` task.
- The Ralph gate now includes a dedicated non-mutating projection check.

Verification:

```bash
docker compose exec -T api pytest -q \
  tests/test_ralph_phase2_photo_spine.py::test_photo_context_submit_projection_is_non_mutating_and_matches_downstream_readiness \
  tests/test_ralph_phase2_photo_spine.py::test_photo_context_submit_projection_reports_boundary_and_context_holds_without_mutation
# 2 passed

docker compose exec -T api pytest -q tests/test_ralph_phase2_photo_spine.py
# 19 passed

docker compose exec -T api pytest -q
# 80 passed

npm run typecheck --prefix apps/web
# passed

npx --prefix apps/web playwright test --config apps/web/playwright.config.ts
# 5 passed

python3 scripts/ralph_loop_gate.py --write-checkpoint --json
# PASS, 31 live checks

git diff --check
# clean
```

Current live checkpoint:

- `updates/ralph_loop_gate_checkpoint_20260429T091413_218930Z.json`
- `updates/ralph_loop_gate_checkpoint_latest.json`
- `updates/ralph_loop_gate_checkpoint_latest.md`

Next useful loop target:

- Give Adam a compact "review session progress" panel for photo-context work: how many context tasks were created from the pack, how many have drafts, how many are submit-ready according to the projection, and which blocked reasons are most common.

## Continuation Update: Photo Context Session Progress

This loop added a progress layer over photo-context review work.

What changed:

- Added `GET /api/assets/photo-context-review-pack/session-progress`.
- The progress endpoint summarizes `photo_context` tasks and saved Adam drafts without creating any downstream records.
- For each task with a draft, it runs the same non-mutating submit projection and reports:
  - progress status,
  - vector handoff status,
  - gallery scope after submit,
  - blocked reasons,
  - the next action.
- The Exports `Photo Context Review Pack` card now shows:
  - submit-ready / drafted / total context task counts,
  - common projection blockers,
  - the first progress tasks with thumbnails and direct open actions.
- The live Ralph gate now checks the progress endpoint and a focused test that proves drafts are summarized without mutating profile/memory/gallery/embedding tables.

Live result:

- 1 live `photo_context` task is currently visible in progress.
- 0 saved drafts yet.
- 1 task still needs a draft.
- 0 submit-ready photo-context drafts.

Verification:

```bash
docker compose exec -T api pytest -q \
  tests/test_ralph_phase2_photo_spine.py::test_photo_context_session_progress_summarizes_drafts_and_projection_blockers_without_mutation
# 1 passed

docker compose exec -T api pytest -q tests/test_ralph_phase2_photo_spine.py
# 20 passed

docker compose exec -T api pytest -q
# 81 passed

npm run typecheck --prefix apps/web
# passed

npx --prefix apps/web playwright test --config apps/web/playwright.config.ts
# 5 passed

python3 scripts/ralph_loop_gate.py --write-checkpoint --json
# PASS, 32 live checks

git diff --check
# clean
```

Current live checkpoint:

- `updates/ralph_loop_gate_checkpoint_20260429T092032_940623Z.json`
- `updates/ralph_loop_gate_checkpoint_latest.json`
- `updates/ralph_loop_gate_checkpoint_latest.md`

Next useful loop target:

- Improve the photo-context editor itself: add a compact "required fields / submit readiness" rail inside the task so Adam can see why a single draft is not submit-ready without leaving the review flow.

## Continuation Update: Photo Context Required-Field Checklist

This loop moved single-task readiness guidance into the photo-context review flow.

What changed:

- Extended `POST /api/tasks/{task_id}/photo-context/projection` with:
  - `field_requirements`,
  - `submit_readiness`,
  - `missing_required_fields`.
- The checklist distinguishes:
  - required submit fields such as reviewed visual description, privacy level, downstream choice, and OCR status,
  - optional-but-important Adam context that upgrades the truth label to `adam_memory`.
- The photo-context editor now shows a `Required field checklist` under the backend submit projection.
- Browser smoke now verifies that opening a no-claim photo context task exposes the checklist in the review flow.

Verification:

```bash
docker compose exec -T api pytest -q \
  tests/test_ralph_phase2_photo_spine.py::test_photo_context_submit_projection_is_non_mutating_and_matches_downstream_readiness \
  tests/test_ralph_phase2_photo_spine.py::test_photo_context_submit_projection_reports_boundary_and_context_holds_without_mutation
# 2 passed

docker compose exec -T api pytest -q tests/test_ralph_phase2_photo_spine.py
# 20 passed

docker compose exec -T api pytest -q
# 81 passed

npm run typecheck --prefix apps/web
# passed

npx --prefix apps/web playwright test --config apps/web/playwright.config.ts
# 5 passed

python3 scripts/ralph_loop_gate.py --write-checkpoint --json
# PASS, 32 live checks

git diff --check
# clean
```

Current live checkpoint:

- `updates/ralph_loop_gate_checkpoint_20260429T092458_559072Z.json`
- `updates/ralph_loop_gate_checkpoint_latest.json`
- `updates/ralph_loop_gate_checkpoint_latest.md`

Next useful loop target:

- Add a durable photo-context export preview for submit-ready drafts, so Adam can inspect the exact memory/profile/boundary/embedding/gallery payload that will be written before clicking Submit.

## Continuation Update: Photo Context Submit Payload Preview

This loop made the photo-context submit projection inspectable as an export-like artifact.

What changed:

- Extended the photo-context projection with:
  - `export_preview_yaml`,
  - `content_sha256`.
- The YAML preview includes:
  - task and source photo IDs,
  - metadata profile action and truth status,
  - boundary flags,
  - downstream memory/vector/gallery/OCR consequences,
  - safety flags showing no mutation, no live embedding call, and no ordinary DB vector storage.
- The photo-context editor now shows a collapsible `Submit payload preview` beneath the backend projection.
- API tests verify the preview contains the expected YAML sections and stable hash.
- Browser smoke verifies the preview is visible inside a real no-claim photo-context task.

Verification:

```bash
docker compose exec -T api pytest -q \
  tests/test_ralph_phase2_photo_spine.py::test_photo_context_submit_projection_is_non_mutating_and_matches_downstream_readiness \
  tests/test_ralph_phase2_photo_spine.py::test_photo_context_submit_projection_reports_boundary_and_context_holds_without_mutation
# 2 passed

docker compose exec -T api pytest -q tests/test_ralph_phase2_photo_spine.py
# 20 passed

docker compose exec -T api pytest -q
# 81 passed

npm run typecheck --prefix apps/web
# passed

npx --prefix apps/web playwright test --config apps/web/playwright.config.ts
# 5 passed

python3 scripts/ralph_loop_gate.py --write-checkpoint --json
# PASS, 32 live checks

git diff --check
# clean
```

Current live checkpoint:

- `updates/ralph_loop_gate_checkpoint_20260429T092859_447379Z.json`
- `updates/ralph_loop_gate_checkpoint_latest.json`
- `updates/ralph_loop_gate_checkpoint_latest.md`

Next useful loop target:

- Add source-review style receipts for photo-context submissions, so after Adam submits a photo context task the UI can show the exact created profile/memory/boundary/embedding/gallery records plus the same YAML payload hash for audit continuity.

## Continuation Update: Photo Context Receipt Audit Continuity

This loop tied the pre-submit photo-context projection to the durable submit receipt.

What changed:

- `POST /api/tasks/{task_id}/submit` now computes the non-mutating photo-context projection immediately before writing photo-context artifacts.
- Photo-context submit outputs now include:
  - `submit_projection`,
  - `submit_projection_content_sha256`,
  - the exact `export_preview_yaml` shown before submit,
  - submit readiness, blocker reasons, boundary privacy, gallery scope, and vector handoff status.
- `TaskReceipt.summary` persists the same `submit_projection` object for later audit.
- The workbench receipt banner now exposes a collapsible `Photo context submit projection` section with the payload hash and YAML preview.
- The Ralph gate now includes a focused contract check that proves projection hash/YAML continuity from preview to submit receipt.

Verification:

```bash
docker compose exec -T api pytest -q \
  tests/test_ralph_phase2_photo_spine.py::test_photo_context_submit_projection_is_non_mutating_and_matches_downstream_readiness \
  tests/test_ralph_phase2_photo_spine.py::test_photo_context_submit_receipt_carries_projection_hash_and_payload_preview \
  tests/test_ralph_phase2_photo_spine.py::test_photo_context_submit_projection_reports_boundary_and_context_holds_without_mutation
# 3 passed

docker compose exec -T api pytest -q tests/test_ralph_phase2_photo_spine.py
# 21 passed

docker compose exec -T api pytest -q
# 82 passed

npm run typecheck --prefix apps/web
# passed

npx --prefix apps/web playwright test --config apps/web/playwright.config.ts
# 5 passed

python3 scripts/ralph_loop_gate.py --write-checkpoint --json
# PASS, 32 live checks

git diff --check
# clean
```

Current live checkpoint:

- `updates/ralph_loop_gate_checkpoint_20260429T093555_555095Z.json`
- `updates/ralph_loop_gate_checkpoint_latest.json`
- `updates/ralph_loop_gate_checkpoint_latest.md`

Next useful loop target:

- Add a photo-context receipt/history surface on the asset detail/review pack side, so completed photo context submissions can be inspected later without relying only on the transient "last submit" banner.

## Continuation Update: Asset Dossier Receipt History

This loop made photo-context submit receipts visible after the submit moment has passed.

What changed:

- The asset dossier page now shows a `Task Receipts` section.
- Receipt cards expose:
  - receipt human ID,
  - task type and downstream status,
  - boundary status,
  - photo-context submit readiness,
  - the submit projection hash,
  - a collapsible exact submit payload YAML preview.
- The photo-context receipt continuity test now also calls `GET /api/assets/{asset_id}/dossier` and proves the same projection hash/YAML are retrievable through the asset history.

Verification:

```bash
docker compose exec -T api pytest -q \
  tests/test_ralph_phase2_photo_spine.py::test_photo_context_submit_receipt_carries_projection_hash_and_payload_preview
# 1 passed

docker compose exec -T api pytest -q tests/test_ralph_phase2_photo_spine.py
# 21 passed

docker compose exec -T api pytest -q
# 82 passed

npm run typecheck --prefix apps/web
# passed

npx --prefix apps/web playwright test --config apps/web/playwright.config.ts
# 5 passed

python3 scripts/ralph_loop_gate.py --write-checkpoint --json
# PASS, 32 live checks

git diff --check
# clean
```

Current live checkpoint:

- `updates/ralph_loop_gate_checkpoint_20260429T094020_499782Z.json`
- `updates/ralph_loop_gate_checkpoint_latest.json`
- `updates/ralph_loop_gate_checkpoint_latest.md`

Next useful loop target:

- Add a dedicated, export-like photo memory corpus preview for reviewed photo-context records, so the system can show exactly what text would be handed to a vector database and why each record is included or excluded.

## Continuation Update: Vector Handoff Inclusion Trace

This loop made vector handoff rows explain why they are included, not just what text they contain.

What changed:

- Photo memory corpus rows now include:
  - `review_status`,
  - `inclusion_reason`,
  - `inclusion_trace`.
- JSONL vector handoff rows mirror the inclusion reason at the top level and inside metadata.
- Inclusion traces record metadata source, truth status, boundary reviewer, scope, dedupe policy, and selected target type.
- The Downstream Readiness vector panel now shows sample handoff text and exclusion records, so the reviewed/held split is inspectable directly in the UI.
- Browser smoke now asserts that at least one vector preview/exclusion record is visible in the export readiness panel.
- The Ralph gate now verifies corpus records and JSONL records include inclusion reasons/traces and dedupe rationale.

Verification:

```bash
docker compose exec -T api pytest -q \
  tests/test_ralph_phase2_photo_spine.py::test_photo_memory_embedding_export_is_stable_jsonl_with_manifest_and_boundaries
# 1 passed

docker compose exec -T api pytest -q tests/test_ralph_phase2_photo_spine.py
# 21 passed

docker compose exec -T api pytest -q
# 82 passed

npm run typecheck --prefix apps/web
# passed

npx --prefix apps/web playwright test --config apps/web/playwright.config.ts
# 5 passed

python3 scripts/ralph_loop_gate.py --write-checkpoint --json
# PASS, 32 live checks

git diff --check
# clean
```

Current live checkpoint:

- `updates/ralph_loop_gate_checkpoint_20260429T094529_082617Z.json`
- `updates/ralph_loop_gate_checkpoint_latest.json`
- `updates/ralph_loop_gate_checkpoint_latest.md`

Next useful loop target:

- Seed a small reviewed-photo-context demo set from safe local test fixtures or user-reviewed samples, so the live app can show at least one reviewed vector-ready photo memory instead of only machine drafts and no-claim gaps.

## Continuation Update: Reviewed Photo Demo Readiness

This loop avoided fabricating a reviewed demo and made the absence of reviewed photo-memory records explicit and actionable.

What changed:

- Added `GET /api/retrieval/photo-memory-corpus/reviewed-demo-readiness`.
- The endpoint is read-only and reports whether a reviewed, vector-ready photo memory can be shown.
- When no reviewed records exist, it returns `status: needs_adam_review`, a `no_reviewed_vector_ready_photo_memory` blocker, and exact candidate review actions.
- Candidate actions point either to photo-context tasks, photo-memory review tasks, or boundary-clearance work.
- The Downstream Readiness panel now includes a Reviewed Photo Demo Readiness card with safety policy, blockers, reviewed samples, and open-review buttons.
- The Ralph gate now verifies the endpoint does not fabricate Adam memory, does not mutate state, does not call embeddings/fine-tuning APIs, and only shows reviewed samples when reviewed records exist.

Verification:

```bash
docker compose exec -T api pytest -q \
  tests/test_ralph_phase2_photo_spine.py::test_reviewed_photo_memory_demo_readiness_is_truthful_before_and_after_adam_review
# 1 passed

docker compose exec -T api pytest -q tests/test_ralph_phase2_photo_spine.py
# 22 passed

docker compose exec -T api pytest -q
# 83 passed

npm run typecheck --prefix apps/web
# passed

npx --prefix apps/web playwright test --config apps/web/playwright.config.ts
# 5 passed

python3 scripts/ralph_loop_gate.py --write-checkpoint --json
# PASS, 33 live checks

git diff --check
# clean
```

Current live checkpoint:

- `updates/ralph_loop_gate_checkpoint_20260429T095645_942419Z.json`
- `updates/ralph_loop_gate_checkpoint_latest.json`
- `updates/ralph_loop_gate_checkpoint_latest.md`

Live state after this loop:

- 0 reviewed vector-ready photo memories.
- 5 exact photo-memory review actions exposed for demo unlock.
- 1 photo-context task ready for Adam-authored context.
- No fabricated reviewed memory created.

Next useful loop target:

- Make the photo review task itself more efficient: add a compact “promotion checklist” in the task workbench for photo-memory review/context tasks, so Adam can see exactly which fields must be resolved to turn a held photo into a reviewed vector-ready memory.

## Continuation Update: Photo Promotion Checklist

This loop made the human review task clearer at the moment of work.

What changed:

- The photo-memory review surface now always shows a `Promotion checklist`.
- For `photo_context` tasks, the checklist is driven by the backend submit projection.
- For `vision_draft_review` tasks, the checklist is derived locally from the same promotion rules before a submit projection exists.
- The checklist names the fields that decide downstream status:
  - reviewed visual description,
  - Adam context or answers,
  - privacy level,
  - downstream choice,
  - OCR/handwriting status,
  - vector handoff status.
- Browser smoke tests now verify the checklist appears when opening both a gallery machine-draft review task and a retrieval-created photo-context task.

Verification:

```bash
npm run typecheck --prefix apps/web
# passed

npx --prefix apps/web playwright test --config apps/web/playwright.config.ts
# 5 passed

python3 scripts/ralph_loop_gate.py --write-checkpoint --json
# PASS, 33 live checks

git diff --check
# clean
```

Current live checkpoint:

- `updates/ralph_loop_gate_checkpoint_20260429T100105_634307Z.json`
- `updates/ralph_loop_gate_checkpoint_latest.json`
- `updates/ralph_loop_gate_checkpoint_latest.md`

Next useful loop target:

- Add a focused photo-review queue filter/action for “can become reviewed vector memory fastest,” using the same checklist/projection signals to prioritize tasks with the shortest path to an eligible reviewed record.

## Continuation Update: Photo Priority Filter

This loop made the photo review queue better at answering: “which task should Adam open first if the goal is a reviewed, vector-ready photo memory?”

What changed:

- Review > Photos now includes a `Photo priority` filter.
- `Fastest vector memory` prioritizes:
  - machine-drafted photo memory review tasks,
  - retrieval-created photo-context tasks,
  - ordinary photo-context tasks.
- Queue rows now show priority badges such as `Fastest vector path`, `Retrieval context path`, and `Context path`.
- The queue subtitle changes when the priority filter is active, so the user sees that the current list is scoped to the fastest vector-memory path rather than the whole photo backlog.
- Browser smoke tests verify the filter, scoped queue header, and first visible priority badge.

Verification:

```bash
npm run typecheck --prefix apps/web
# passed

npx --prefix apps/web playwright test --config apps/web/playwright.config.ts
# 5 passed

python3 scripts/ralph_loop_gate.py --write-checkpoint --json
# PASS, 33 live checks

git diff --check
# clean
```

Current live checkpoint:

- `updates/ralph_loop_gate_checkpoint_20260429T100647_960541Z.json`
- `updates/ralph_loop_gate_checkpoint_latest.json`
- `updates/ralph_loop_gate_checkpoint_latest.md`

Next useful loop target:

- Add a compact reviewed-photo promotion dry-run for the first prioritized task, so the queue can show why it is fastest and which exact fields are still missing before the user opens it.

## Continuation Update: Photo Promotion Dry Run

This loop added a queue-level preview that explains why the highest-priority photo task is first in line.

What changed:

- When Review > Photos is filtered to `Fastest vector memory`, the queue now shows a `Next photo promotion dry run`.
- The dry run names the first task, the review path, and why that task is the fastest path.
- It lists the exact fields still needed before promotion, including:
  - Adam context or answers,
  - downstream choice set to retrieval-ready,
  - boundary review for family/public use,
  - reviewed visual description where the task has no machine draft.
- It also shows safeguards:
  - no memory claim yet,
  - no vector write before submit,
  - not SFT/DPO training material.
- Browser smoke tests now verify the dry-run panel, projected outcome, missing-field list, and no-claim safeguard.

Verification:

```bash
npm run typecheck --prefix apps/web
# passed

npx --prefix apps/web playwright test --config apps/web/playwright.config.ts
# 5 passed

python3 scripts/ralph_loop_gate.py --write-checkpoint --json
# PASS, 33 live checks

git diff --check
# clean
```

Current live checkpoint:

- `updates/ralph_loop_gate_checkpoint_20260429T101237_468237Z.json`
- `updates/ralph_loop_gate_checkpoint_latest.json`
- `updates/ralph_loop_gate_checkpoint_latest.md`

Next useful loop target:

- Make the photo priority/dry-run logic testable outside the browser by moving the ranking and missing-field explanation into a shared helper or API summary, then assert it with deterministic unit/API tests.

## Continuation Update: API-Backed Photo Priority Summary

This loop moved the photo priority explanation out of UI-only logic and into a deterministic API contract.

What changed:

- Added `GET /api/assets/photo-review-priority`.
- The endpoint returns a non-mutating priority summary with:
  - ranked photo review tasks,
  - path labels,
  - source photo ids and titles,
  - retrieval-gap query provenance,
  - missing fields,
  - projected outcome,
  - no-claim safeguards,
  - truth status before review.
- The frontend now fetches this summary and uses it for the `Next photo promotion dry run`, with local derivation only as fallback.
- Added a deterministic API test proving:
  - machine-drafted photo memory review tasks outrank retrieval-created context tasks even when their ordinary priority is lower,
  - retrieval-created context tasks preserve the source query,
  - ordinary context tasks remain after retrieval tasks,
  - unscaffolded photo reviews are excluded from `fastest_vector` but present in `all`,
  - the endpoint does not mutate task rows.

Verification:

```bash
docker compose exec -T api pytest -q tests/test_ralph_phase2_photo_spine.py::test_photo_review_priority_summary_orders_fastest_paths_and_preserves_no_claim_policy
# 1 passed

docker compose exec -T api pytest -q
# 84 passed

npm run typecheck --prefix apps/web
# passed

npx --prefix apps/web playwright test --config apps/web/playwright.config.ts
# 5 passed

python3 scripts/ralph_loop_gate.py --write-checkpoint --json
# PASS, 33 live checks

git diff --check
# clean
```

Current live checkpoint:

- `updates/ralph_loop_gate_checkpoint_20260429T101912_915841Z.json`
- `updates/ralph_loop_gate_checkpoint_latest.json`
- `updates/ralph_loop_gate_checkpoint_latest.md`

Next useful loop target:

- Add this photo priority contract to the Ralph gate so future loops cannot accidentally break the queue-level promotion explanation while still passing broader UI smoke tests.

## Continuation Update: Photo Priority Gate Contract

This loop made the photo-priority behavior part of the live Ralph gate.

What changed:

- The gate now calls `GET /api/assets/photo-review-priority?focus=fastest_vector`.
- The live check requires:
  - summary type `photo_review_priority`,
  - no-claim prioritization policy,
  - non-mutating behavior,
  - no live model call,
  - ranked items,
  - fastest-vector path presence,
  - source photo identity,
  - missing-field explanations,
  - no-memory-claim safeguards.
- The gate also runs the deterministic fixture test for ordering and no-claim policy.
- Gate size increased from 33 to 35 live checks.

Verification:

```bash
python3 scripts/ralph_loop_gate.py --write-checkpoint --json
# PASS, 35 live checks

git diff --check
# clean
```

Current live checkpoint:

- `updates/ralph_loop_gate_checkpoint_20260429T102051_090556Z.json`
- `updates/ralph_loop_gate_checkpoint_latest.json`
- `updates/ralph_loop_gate_checkpoint_latest.md`

Next useful loop target:

- Make reviewed-photo promotion easier to complete by adding a “fill from machine draft” affordance or a compact default decision set that marks what is machine-derived vs. what still needs Adam context, without submitting anything automatically.

## Continuation Update: Machine Draft Visible Defaults

This loop made machine-drafted photo review safer and faster inside the task form.

What changed:

- Photo memory review tasks now show a `Machine draft defaults` panel when machine-derived visible-field scaffolding exists.
- The panel labels these values as machine-derived, visible-field defaults only.
- It explicitly says they are not Adam memory until corrected, contextualized, and submitted.
- Added `Restore visible defaults`, which restores:
  - reviewed visual description,
  - visible people,
  - place,
  - date range,
  - tags/themes,
  - visible objects,
  - OCR/handwriting text.
- The restore action does not fill Adam context, invisible context, downstream clearance, or boundary review.
- Browser smoke now edits the reviewed visual description, clicks restore, and verifies the machine default comes back.

Verification:

```bash
npm run typecheck --prefix apps/web
# passed

npx --prefix apps/web playwright test --config apps/web/playwright.config.ts
# 5 passed

python3 scripts/ralph_loop_gate.py --write-checkpoint --json
# PASS, 35 live checks

git diff --check
# clean
```

Current live checkpoint:

- `updates/ralph_loop_gate_checkpoint_20260429T102418_686747Z.json`
- `updates/ralph_loop_gate_checkpoint_latest.json`
- `updates/ralph_loop_gate_checkpoint_latest.md`

Next useful loop target:

- Add an explicit “reviewed memory readiness” control group in the photo task form so Adam can move from machine scaffold to reviewed vector-ready state with fewer scattered choices while still preserving boundary/truth separation.

## Continuation Update: Reviewed Memory Readiness Controls

This loop added a compact shortcut group for the boundary/downstream decisions that previously required hunting through scattered fields.

What changed:

- Photo memory review now includes `Reviewed memory readiness controls`.
- Added three safe shortcuts:
  - `Set retrieval-ready defaults`,
  - `Hold for later`,
  - `Keep sealed`.
- The panel explicitly says these shortcuts only adjust boundary, gallery, and downstream decisions.
- It also says Adam context or answers are still required before the photo becomes reviewed memory truth.
- The retrieval-ready shortcut sets:
  - privacy level: `family_private`,
  - ready downstream: `yes`,
  - gallery eligibility: `family_private`,
  - OCR status: `not_present` only when there is no OCR text.
- Browser smoke now clicks the shortcut and verifies the underlying dropdown values, not just visible text.

Verification:

```bash
npm run typecheck --prefix apps/web
# passed

npx --prefix apps/web playwright test --config apps/web/playwright.config.ts
# 5 passed

python3 scripts/ralph_loop_gate.py --write-checkpoint --json
# PASS, 35 live checks

git diff --check
# clean
```

Current live checkpoint:

- `updates/ralph_loop_gate_checkpoint_20260429T102651_444591Z.json`
- `updates/ralph_loop_gate_checkpoint_latest.json`
- `updates/ralph_loop_gate_checkpoint_latest.md`

Next useful loop target:

- Add a compact review-progress indicator to the photo task form that counts which promotion checklist items are complete vs. held, so Adam can see progress change immediately as fields are edited.

## Continuation Update: Photo Promotion Progress

This loop made the photo review checklist visibly reactive instead of only descriptive.

What changed:

- Photo memory review now shows a `Promotion progress` readout inside the downstream memory preview.
- The readout counts checklist items as `complete` vs. `held`.
- The count is computed from the same promotion checklist that drives the visible status cards.
- Browser smoke now verifies the readout is visible, then fills Adam context and clicks `Set retrieval-ready defaults`.
- The test requires the readout to reach `6 complete` and `0 held`, which catches regressions where UI text exists but the actual review state does not move.

Verification:

```bash
npm run typecheck --prefix apps/web
# passed

docker compose exec -T api pytest -q
# 84 passed

npx --prefix apps/web playwright test --config apps/web/playwright.config.ts
# 5 passed

python3 scripts/ralph_loop_gate.py --write-checkpoint --json
# PASS, 35 live checks

git diff --check
# clean
```

Current live checkpoint:

- `updates/ralph_loop_gate_checkpoint_20260429T103113_120111Z.json`
- `updates/ralph_loop_gate_checkpoint_latest.json`
- `updates/ralph_loop_gate_checkpoint_latest.md`

Next useful loop target:

- Add a durable review receipt / vector handoff preview after photo context submit so completing a photo task produces a clear downstream artifact trail, not just changed form state.

## Continuation Update: Photo Submit Receipt Handoff

This loop made the post-submit artifact trail more explicit for photo review.

What changed:

- The existing submit receipt banner now has a first-class `Vector handoff` row for photo memory submissions.
- The row exposes:
  - vector handoff status,
  - vector record id when present,
  - whether the submit used no live embedding call,
  - whether ordinary DB vector storage was avoided,
  - the backend handoff reason.
- The existing photo context submit projection details still show the exact YAML payload preview and content hash.
- Browser smoke now mocks only the submit response, then proves the receipt UI appears without mutating imported archive records.

Verification:

```bash
npm run typecheck --prefix apps/web
# passed

docker compose exec -T api pytest -q
# 84 passed

npx --prefix apps/web playwright test --config apps/web/playwright.config.ts
# 6 passed

python3 scripts/ralph_loop_gate.py --write-checkpoint --json
# PASS, 35 live checks

git diff --check
# clean
```

Current live checkpoint:

- `updates/ralph_loop_gate_checkpoint_20260429T103634_152038Z.json`
- `updates/ralph_loop_gate_checkpoint_latest.json`
- `updates/ralph_loop_gate_checkpoint_latest.md`

Next useful loop target:

- Add a reviewed-photo dossier shortcut from the receipt or task surface so Adam can inspect the durable asset record immediately after a submit.

## Continuation Update: Receipt To Asset Dossier

This loop closed the loop from photo submit back to durable asset inspection.

What changed:

- The submit receipt banner now uses the returned annotation target to link photo submissions to their asset dossier.
- `Annotation` typing now includes optional `target_type` and `target_id`, matching the backend response.
- The vector handoff receipt row shows `Open asset dossier` when the submitted target is an asset.
- Browser smoke verifies the link target from a mocked photo submit receipt.

Verification:

```bash
npm run typecheck --prefix apps/web
# passed

docker compose exec -T api pytest -q
# 84 passed

npx --prefix apps/web playwright test --config apps/web/playwright.config.ts
# 6 passed

python3 scripts/ralph_loop_gate.py --write-checkpoint --json
# PASS, 35 live checks

git diff --check
# clean
```

Current live checkpoint:

- `updates/ralph_loop_gate_checkpoint_20260429T103937_007979Z.json`
- `updates/ralph_loop_gate_checkpoint_latest.json`
- `updates/ralph_loop_gate_checkpoint_latest.md`

Next useful loop target:

- Make the asset dossier receipt section show vector handoff status/reason directly, so the inspection target has the same downstream clarity as the submit receipt.

## Continuation Update: Dossier Vector Receipt Clarity

This loop made the durable asset dossier carry the same downstream handoff signal as the immediate submit receipt.

What changed:

- Asset dossier `Task Receipts` now show:
  - vector handoff status,
  - vector record id,
  - vector handoff reason,
  - existing submit payload YAML and hash.
- The dossier reads the status from `created_or_updated.vector_handoff_status`, falling back to the submit projection when needed.
- Browser smoke now mocks a full asset dossier response and verifies the vector handoff badges, reason, and YAML preview render correctly.

Verification:

```bash
npm run typecheck --prefix apps/web
# passed

docker compose exec -T api pytest -q
# 84 passed

npx --prefix apps/web playwright test --config apps/web/playwright.config.ts
# 7 passed

python3 scripts/ralph_loop_gate.py --write-checkpoint --json
# PASS, 35 live checks

git diff --check
# clean
```

Current live checkpoint:

- `updates/ralph_loop_gate_checkpoint_20260429T104312_246086Z.json`
- `updates/ralph_loop_gate_checkpoint_latest.json`
- `updates/ralph_loop_gate_checkpoint_latest.md`

Next useful loop target:

- Add a compact “what is export-ready now?” summary to the exports page so the training/photo handoff state is legible without opening multiple panels.

## Continuation Update: Export Readiness Summary

This loop made the exports page answer “what is ready right now?” without forcing Adam through several panels.

What changed:

- Added `Export readiness summary` to the top of the downstream readiness area.
- It summarizes:
  - SFT and DPO reviewable training rows,
  - photo vector handoff ready vs. held,
  - photo review queue submit-ready vs. blocked,
  - demo generation gate status.
- The language avoids false readiness claims: training rows are called reviewable, and approved export still requires gold clearance.
- Browser smoke verifies the summary and each major readiness category appears on the Exports page.

Verification:

```bash
npm run typecheck --prefix apps/web
# passed

docker compose exec -T api pytest -q
# 84 passed

npx --prefix apps/web playwright test --config apps/web/playwright.config.ts
# 7 passed

python3 scripts/ralph_loop_gate.py --write-checkpoint --json
# PASS, 35 live checks

git diff --check
# clean
```

Current live checkpoint:

- `updates/ralph_loop_gate_checkpoint_20260429T104623_742699Z.json`
- `updates/ralph_loop_gate_checkpoint_latest.json`
- `updates/ralph_loop_gate_checkpoint_latest.md`

Next useful loop target:

- Make the Prompt Pairs queue expose export-readiness counts beside filters, so Adam can see candidates vs approved without opening a ticket.

## Continuation Update: Prompt Pair Readiness Counts

This loop made the Prompt Pairs queue disclose export readiness before Adam opens a ticket.

What changed:

- The workbench now loads the backend prompt-pair audit alongside task data.
- Prompt Pair filters include `Prompt pair export readiness counts`.
- The summary shows:
  - approved-ready count,
  - needs-gold-edit candidate count,
  - total inspected pairs.
- Browser smoke compares those displayed counts against the live `/api/prompt-pairs/audit` response.

Verification:

```bash
npm run typecheck --prefix apps/web
# passed

docker compose exec -T api pytest -q
# 84 passed

npx --prefix apps/web playwright test --config apps/web/playwright.config.ts
# 7 passed

python3 scripts/ralph_loop_gate.py --write-checkpoint --json
# PASS, 35 live checks

git diff --check
# clean
```

Current live checkpoint:

- `updates/ralph_loop_gate_checkpoint_20260429T105057_705340Z.json`
- `updates/ralph_loop_gate_checkpoint_latest.json`
- `updates/ralph_loop_gate_checkpoint_latest.md`

Next useful loop target:

- Add a short “why held?” explanation to Prompt Pair tickets when backend preflight keeps an item in candidate status.

## Continuation Update: Prompt Pair Held Explanation

This loop made candidate Prompt Pair tickets explain why they are not export-ready yet.

What changed:

- Candidate prompt-pair tickets now show a `Why held?` explanation below backend preflight blockers.
- The explanation is generated from backend blocker keys, so it follows the selected ticket instead of being hard-coded.
- The copy makes the export status explicit: the item remains a candidate dry-run until those blockers are resolved.
- Browser smoke mocks a backend candidate preflight and verifies the displayed blockers and explanation.

Verification:

```bash
npm run typecheck --prefix apps/web
# passed

docker compose exec -T api pytest -q
# 84 passed

npx --prefix apps/web playwright test --config apps/web/playwright.config.ts
# 8 passed

python3 scripts/ralph_loop_gate.py --write-checkpoint --json
# PASS, 35 live checks

git diff --check
# clean
```

Current live checkpoint:

- `updates/ralph_loop_gate_checkpoint_20260429T105518_600820Z.json`
- `updates/ralph_loop_gate_checkpoint_latest.json`
- `updates/ralph_loop_gate_checkpoint_latest.md`

Next useful loop target:

- Add a direct “open held candidate” action near Prompt Pair readiness counts so Adam can jump from the queue summary into the next item that needs review.

## Continuation Update: Prompt Pair Next Review Action

This loop turned the Prompt Pair readiness summary into an actionable queue jump.

What changed:

- `/api/prompt-pairs/audit` now returns `next_review_actions` from backend preflight, including the first held candidate task.
- The Prompt Pairs sidebar shows an `Open held candidate` action when backend audit finds a candidate.
- Clicking the action clears local prompt-pair filters and opens the exact singleton ticket returned by the audit.
- Browser smoke verifies the action is visible, opens the expected active ticket, and lands on a candidate export gate.

Verification:

```bash
npm run typecheck --prefix apps/web
# passed

docker compose exec -T api pytest -q
# 84 passed

npx --prefix apps/web playwright test --config apps/web/playwright.config.ts
# 8 passed

python3 scripts/ralph_loop_gate.py --write-checkpoint --json
# PASS, 35 live checks

git diff --check
# clean
```

Current live checkpoint:

- `updates/ralph_loop_gate_checkpoint_20260429T110241_393968Z.json`
- `updates/ralph_loop_gate_checkpoint_latest.json`
- `updates/ralph_loop_gate_checkpoint_latest.md`

Next useful loop target:

- Add the same kind of direct review action to the photo vector readiness summary, so Adam can jump from “held photo vectors” to the fastest review task.

## Continuation Update: Photo Vector Summary Action

This loop made the top export readiness snapshot actionable for held photo vectors.

What changed:

- The `Photo vector handoff` card in `Export-ready now` now shows `Open fastest review` when the vector handoff API exposes a held review task.
- The action is sourced from `vectorHandoff.next_review_actions` or the manifest mirror, so it follows backend vector policy.
- Clicking it opens the actual photo memory review task in the Review workflow.
- Browser smoke now verifies the summary action opens a Vision Draft Review task with photo preview, promotion checklist, and downstream memory preview.

Verification:

```bash
npm run typecheck --prefix apps/web
# passed

docker compose exec -T api pytest -q
# 84 passed

npx --prefix apps/web playwright test --config apps/web/playwright.config.ts
# 9 passed

python3 scripts/ralph_loop_gate.py --write-checkpoint --json
# PASS, 35 live checks

git diff --check
# clean
```

Current live checkpoint:

- `updates/ralph_loop_gate_checkpoint_20260429T110652_273611Z.json`
- `updates/ralph_loop_gate_checkpoint_latest.json`
- `updates/ralph_loop_gate_checkpoint_latest.md`

Next useful loop target:

- Expose issue-specific prompt-pair filters from backend preflight blockers, so Adam can jump to DPO items missing rejected-side rationale separately from general gold edits.

## Continuation Update: Prompt Pair Blocker Actions

This loop made prompt-pair candidates explain their backlog by backend blocker type.

What changed:

- `/api/prompt-pairs/audit` now returns `preflight_blocker_counts`.
- The same audit also returns `blocker_review_actions`, one jump action for the first task behind each backend blocker.
- The Prompt Pairs readiness summary renders compact blocker-specific actions, including the blocker label and count.
- Browser smoke verifies the blocker count matches the API, opens the blocker example, and still opens the general held-candidate task.

Verification:

```bash
npm run typecheck --prefix apps/web
# passed

docker compose exec -T api pytest -q
# 84 passed

npx --prefix apps/web playwright test --config apps/web/playwright.config.ts
# 9 passed

python3 scripts/ralph_loop_gate.py --write-checkpoint --json
# PASS, 35 live checks

git diff --check
# clean
```

Current live checkpoint:

- `updates/ralph_loop_gate_checkpoint_20260429T111036_557887Z.json`
- `updates/ralph_loop_gate_checkpoint_latest.json`
- `updates/ralph_loop_gate_checkpoint_latest.md`

Next useful loop target:

- Add a small export-preview integrity check for Prompt Pair tickets so the UI clearly shows when editable YAML/plain text and backend preview are synchronized.

## Continuation Update: Prompt Pair Export Preview Integrity

This loop added a backend synchronization check to the Prompt Pair export preview.

What changed:

- Prompt Pair tickets now show an `Export preview integrity` badge beside the YAML preview.
- The badge distinguishes backend pending, backend unavailable, backend synchronized, and backend preview differs.
- Browser smoke verifies a live synchronized pair and a mocked backend mismatch.
- The first test run found a real formatter drift: frontend YAML quoted apostrophes more aggressively than backend preflight. The frontend scalar rule now matches the backend rule, so `How's Portland today?` previews synchronize.

Verification:

```bash
npm run typecheck --prefix apps/web
# passed

docker compose exec -T api pytest -q
# 84 passed

npx --prefix apps/web playwright test --config apps/web/playwright.config.ts
# 9 passed

python3 scripts/ralph_loop_gate.py --write-checkpoint --json
# PASS, 35 live checks

git diff --check
# clean
```

Current live checkpoint:

- `updates/ralph_loop_gate_checkpoint_20260429T111539_575632Z.json`
- `updates/ralph_loop_gate_checkpoint_latest.json`
- `updates/ralph_loop_gate_checkpoint_latest.md`

Next useful loop target:

- Add an API-level contract test that frontend/export YAML samples stay aligned with backend pair-export formatting for apostrophes, quoted scalars, and multiline content.

## Continuation Update: Pair YAML Scalar Contract

This loop locked in the YAML scalar behavior that the preview-integrity test exposed.

What changed:

- Added an API contract test for pair-export YAML scalar edge cases.
- The test verifies:
  - apostrophes like `How's Portland today?` remain plain scalars,
  - quoted scalar fields escape quotes,
  - multiline SFT/DPO responses stay block scalars.
- Full API coverage increased to 85 passing tests.

Verification:

```bash
docker compose exec -T api pytest -q
# 85 passed

npm run typecheck --prefix apps/web
# passed

npx --prefix apps/web playwright test --config apps/web/playwright.config.ts
# 9 passed

python3 scripts/ralph_loop_gate.py --write-checkpoint --json
# PASS, 35 live checks

git diff --check
# clean
```

Current live checkpoint:

- `updates/ralph_loop_gate_checkpoint_20260429T111909_113810Z.json`
- `updates/ralph_loop_gate_checkpoint_latest.json`
- `updates/ralph_loop_gate_checkpoint_latest.md`

Next useful loop target:

- Add a compact “what changes on submit” receipt preview to Prompt Pair tickets, showing approved-vs-candidate artifact type before Adam presses Submit.

## Continuation Update: Prompt Pair Submit Receipt Preview

This loop made the Prompt Pair submit outcome explicit before Adam presses Submit.

What changed:

- Prompt Pair tickets now show an `On Submit` receipt preview in the export gate.
- Approved items say they create an approved `SFT` or `DPO` artifact.
- Held items say they create an `SFT` or `DPO` review candidate and remain outside approved training export.
- Browser smoke verifies both a live approved SFT item and a mocked held candidate.

Verification:

```bash
npm run typecheck --prefix apps/web
# passed

docker compose exec -T api pytest -q
# 85 passed

npx --prefix apps/web playwright test --config apps/web/playwright.config.ts
# 9 passed

python3 scripts/ralph_loop_gate.py --write-checkpoint --json
# PASS, 35 live checks

git diff --check
# clean
```

Current live checkpoint:

- `updates/ralph_loop_gate_checkpoint_20260429T112210_652748Z.json`
- `updates/ralph_loop_gate_checkpoint_latest.json`
- `updates/ralph_loop_gate_checkpoint_latest.md`

Next useful loop target:

- Add the same “what changes on submit” clarity to photo-context tasks, so Adam can see whether a photo answer will create a vector-safe memory record, remain held for context, or stay blocked by boundary review.

## Continuation Update: Photo Context Submit Outcome Preview

This loop brought the photo-memory workflow closer to the same review clarity as Prompt Pairs.

What changed:

- Photo review tasks now show an `On Submit` outcome preview inside the downstream memory panel.
- The preview distinguishes:
  - vector-safe reviewed memory record,
  - held photo context,
  - missing-context hold,
  - boundary-excluded vector handoff,
  - local vision-draft annotation.
- The preview explicitly says that eligible vector handoff is reviewed-only, makes no live embedding call, and does not store ordinary DB vector blobs.
- Browser smoke now proves that adding Adam context to a photo-context task flips the projection to `Creates vector-safe memory record` before Submit.

Verification:

```bash
npm run typecheck --prefix apps/web
# passed

docker compose exec -T api pytest -q tests/test_ralph_phase2_photo_spine.py
# 23 passed

npx --prefix apps/web playwright test --config apps/web/playwright.config.ts --grep "photo review exposes|retrieval no-claim"
# 2 passed

docker compose exec -T api pytest -q
# 85 passed

npx --prefix apps/web playwright test --config apps/web/playwright.config.ts
# 9 passed

python3 scripts/ralph_loop_gate.py --write-checkpoint --json
# PASS, 35 live checks

git diff --check
# clean
```

Current live checkpoint:

- `updates/ralph_loop_gate_checkpoint_20260429T112707_824539Z.json`
- `updates/ralph_loop_gate_checkpoint_latest.json`
- `updates/ralph_loop_gate_checkpoint_latest.md`

Next useful loop target:

- Make the photo context work queue expose the same submit-outcome language before a task is opened, so Adam can choose fastest vector-memory work from the queue without hunting through each ticket.

## Continuation Update: Photo Queue Submit Outcome Preview

This loop moved photo outcome clarity from the opened ticket up into the queue.

What changed:

- The photo review priority API now returns structured submit-outcome fields:
  - `submit_outcome_badge`
  - `submit_outcome_label`
  - `submit_outcome_detail`
  - `vector_handoff_preview_status`
- The photo queue dry-run card now shows an `On Submit` section before the task is opened.
- Photo task rows now include an `On submit: ...` badge when the API can predict the path.
- Browser smoke verifies that the fastest vector queue exposes the submit outcome, vector/memory detail, and row badge before Adam opens a ticket.
- A failing first browser run caught that the API container had not reloaded the new service code; after restarting the API, the strict queue test passed.

Verification:

```bash
npm run typecheck --prefix apps/web
# passed

docker compose exec -T api pytest -q tests/test_ralph_phase2_photo_spine.py::test_photo_review_priority_summary_orders_fastest_paths_and_preserves_no_claim_policy
# 1 passed

npx --prefix apps/web playwright test --config apps/web/playwright.config.ts --grep "photo review exposes"
# 1 passed

docker compose exec -T api pytest -q
# 85 passed

npx --prefix apps/web playwright test --config apps/web/playwright.config.ts
# 9 passed

python3 scripts/ralph_loop_gate.py --write-checkpoint --json
# PASS, 35 live checks

git diff --check
# clean
```

Current live checkpoint:

- `updates/ralph_loop_gate_checkpoint_20260429T113306_070411Z.json`
- `updates/ralph_loop_gate_checkpoint_latest.json`
- `updates/ralph_loop_gate_checkpoint_latest.md`

Next useful loop target:

- Add durable export/download affordances for the prompt-pair audit/reference packs and photo-memory vector handoff manifests, with visible hashes so Adam can trust what will leave the system.

## Continuation Update: Downstream Artifact Downloads And Hashes

This loop made downstream artifacts more inspectable and portable from the Exports surface.

What changed:

- Prompt-pair audit packs now include a `content_sha256` hash of the exact Markdown payload.
- Photo vector handoff now has direct endpoints for:
  - `/api/retrieval/photo-memory-corpus/export.jsonl`
  - `/api/retrieval/photo-memory-corpus/export.manifest`
- The Exports readiness panel now includes a dedicated `Downstream artifact downloads` strip with:
  - Prompt pair audit Markdown link and exact hash,
  - Voice reference JSONL/Markdown links and exact hash,
  - Photo vector JSONL/manifest links and exact hash.
- Browser smoke verifies the links point to the API artifact endpoints and that a visible 64-character hash is present.

Verification:

```bash
npm run typecheck --prefix apps/web
# passed

docker compose exec -T api pytest -q tests/test_ralph_phase3_prompt_pair_audit.py::test_prompt_pair_audit_pack_returns_markdown_with_required_voice_modes_and_export_previews
# 1 passed

docker compose exec -T api pytest -q tests/test_ralph_phase2_photo_spine.py::test_machine_photo_memory_drafts_create_profiles_memories_embeddings_and_retrieval
# 1 passed

npx --prefix apps/web playwright test --config apps/web/playwright.config.ts --grep "exports readiness"
# 1 passed

docker compose exec -T api pytest -q
# 85 passed

npx --prefix apps/web playwright test --config apps/web/playwright.config.ts
# 9 passed

python3 scripts/ralph_loop_gate.py --write-checkpoint --json
# PASS, 35 live checks

git diff --check
# clean
```

Current live checkpoint:

- `updates/ralph_loop_gate_checkpoint_20260429T114022_233484Z.json`
- `updates/ralph_loop_gate_checkpoint_latest.json`
- `updates/ralph_loop_gate_checkpoint_latest.md`

Next useful loop target:

- Strengthen the model-generation readiness path by showing exactly which held-out prompts and reference-pack hashes would be sent to GPT-5.5 when credentials/live calls are enabled.

## Continuation Update: GPT-5.5 Demo Input Plan

This loop made the model-generation gate more transparent without enabling live model calls.

What changed:

- `/api/model-status/demo-readiness` now returns a `generation_input_plan`.
- The plan includes:
  - Responses API target,
  - model name `gpt-5.5`,
  - reasoning effort `xhigh`,
  - `store=false`,
  - live-call blockers,
  - reference-pack content hash,
  - held-out prompt-set hash,
  - held-out prompts with per-prompt hashes.
- The Exports Demo Generation Gate now shows the input plan, reference hash, prompt-set hash, and the first held-out prompts before live generation is possible.
- Browser smoke verifies the exact model/reasoning display, `store=false / blocked`, visible 64-character hashes, and the held-out `How's Portland today?` prompt.

Verification:

```bash
npm run typecheck --prefix apps/web
# passed

docker compose exec -T api pytest -q tests/test_ralph_phase1_training_spine.py::test_demo_generation_readiness_lists_held_out_prompts_and_honest_credential_blocker
# 1 passed

npx --prefix apps/web playwright test --config apps/web/playwright.config.ts --grep "exports readiness"
# 1 passed

docker compose exec -T api pytest -q
# 85 passed

npx --prefix apps/web playwright test --config apps/web/playwright.config.ts
# 9 passed

python3 scripts/ralph_loop_gate.py --write-checkpoint --json
# PASS, 35 live checks

git diff --check
# clean
```

Current live checkpoint:

- `updates/ralph_loop_gate_checkpoint_20260429T114455_316975Z.json`
- `updates/ralph_loop_gate_checkpoint_latest.json`
- `updates/ralph_loop_gate_checkpoint_latest.md`

Next useful loop target:

- Add an operator-facing “next bottleneck” summary that ranks Prompt Pair, photo context, vector handoff, and demo generation blockers into one ordered work queue.

## Continuation Update: Ranked Bottleneck Work Queue

This loop turned the Exports panel into a clearer operator console for the next unit of human work.

What changed:

- The downstream readiness surface now shows a `Next bottlenecks` queue.
- The queue ranks work across:
  - Prompt Pairs still held as candidates,
  - Photo Context groups needing Adam-authored context,
  - Vector Handoff exclusions,
  - Demo Generation live-call blockers.
- Each row explains the blocker, gives the next concrete action, and exposes the relevant button when the app can open or create the task directly.
- The browser test intentionally verifies duplicate button labels by scoping them to the right region, so the UI can reuse action language without making tests or operators ambiguous.

Verification:

```bash
npm run typecheck --prefix apps/web
# passed

npx --prefix apps/web playwright test --config apps/web/playwright.config.ts --grep "exports readiness"
# 1 passed

docker compose exec -T api pytest -q
# 85 passed

npx --prefix apps/web playwright test --config apps/web/playwright.config.ts
# 9 passed

python3 scripts/ralph_loop_gate.py --write-checkpoint --json
# PASS, 35 live checks

git diff --check
# clean
```

Current live checkpoint:

- `updates/ralph_loop_gate_checkpoint_20260429T115109_731578Z.json`
- `updates/ralph_loop_gate_checkpoint_latest.json`
- `updates/ralph_loop_gate_checkpoint_latest.md`

Next useful loop target:

- Make the ranked bottleneck queue machine-verifiable from the API as well as the UI, so overnight progress can be measured without depending only on browser text assertions.

## Continuation Update: API-Verifiable Bottleneck Queue

This loop promoted the UI-only bottleneck queue into a backend contract.

What changed:

- Added `/api/downstream-readiness/bottlenecks`.
- The endpoint ranks Prompt Pairs, Photo Context, Vector Handoff, and Demo Generation with:
  - ordered area keys,
  - counts and summaries,
  - concrete action metadata,
  - truth/boundary/training safety policy,
  - a stable `queue_sha256` for machine verification.
- The Exports panel now renders the API-provided queue rather than re-deriving the ordering in React.
- The runtime contract now requires the bottleneck response fields.
- The Ralph gate now includes `Downstream bottleneck queue is API-verifiable`.

Verification:

```bash
docker compose exec -T api pytest -q tests/test_ralph_phase3_prompt_pair_audit.py::test_downstream_bottleneck_queue_is_api_ranked_and_machine_verifiable
# 1 passed

npm run typecheck --prefix apps/web
# passed

npx --prefix apps/web playwright test --config apps/web/playwright.config.ts --grep "exports readiness"
# 1 passed

docker compose exec -T api pytest -q
# 86 passed

npx --prefix apps/web playwright test --config apps/web/playwright.config.ts
# 9 passed

python3 scripts/ralph_loop_gate.py --write-checkpoint --json
# PASS, 36 live checks

git diff --check
# clean
```

Current live checkpoint:

- `updates/ralph_loop_gate_checkpoint_20260429T120053_824655Z.json`
- `updates/ralph_loop_gate_checkpoint_latest.json`
- `updates/ralph_loop_gate_checkpoint_latest.md`

Next useful loop target:

- Reduce the Prompt Pair bottleneck itself by adding a review-batch surface for the 30 held candidates, so Adam can resolve several candidate blockers without hunting one ticket at a time.

## Continuation Update: Held Prompt Pair Review Pack

This loop turned the Prompt Pair bottleneck into an actionable held-candidate pack instead of a vague count.

What changed:

- Added `/api/prompt-pairs/held-candidates`.
- The endpoint returns a candidate-only review pack with:
  - total held candidate count,
  - reported candidate count,
  - blocker counts,
  - voice mode counts,
  - artifact mode counts,
  - candidate prompts and response previews,
  - per-ticket actions,
  - a stable `content_sha256`.
- The pack explicitly marks itself as not training-export eligible:
  - `review_policy: candidate_review_only_no_training_export`
  - `does_not_promote_to_training_export: true`
  - `requires_adam_gold_edit: true`
- The Exports panel now shows the held pack, top blockers, pack hash, and first review actions.
- The Ralph gate now includes `Held prompt-pair review pack is actionable`.

Verification:

```bash
docker compose exec -T api pytest -q tests/test_ralph_phase3_prompt_pair_audit.py::test_prompt_pair_audit_reports_200_plus_inspectable_pairs_with_samples_and_weak_spots
# 1 passed

npm run typecheck --prefix apps/web
# passed

npx --prefix apps/web playwright test --config apps/web/playwright.config.ts --grep "exports readiness"
# 1 passed

docker compose exec -T api pytest -q
# 86 passed

npx --prefix apps/web playwright test --config apps/web/playwright.config.ts
# 9 passed

python3 scripts/ralph_loop_gate.py --write-checkpoint --json
# PASS, 37 live checks

git diff --check
# clean
```

Current live checkpoint:

- `updates/ralph_loop_gate_checkpoint_20260429T120609_696040Z.json`
- `updates/ralph_loop_gate_checkpoint_latest.json`
- `updates/ralph_loop_gate_checkpoint_latest.md`

Next useful loop target:

- Make the held Prompt Pair pack easier to work through in batches by grouping candidates into blocker worklists with stable review sequence keys.

## Continuation Update: Prompt Pair Blocker Worklists

This loop made the held Prompt Pair pack batch-oriented instead of only ticket-oriented.

What changed:

- The `/api/prompt-pairs/held-candidates` response now includes `worklists`.
- Worklists group held candidates by backend blocker, currently:
  - `dpo_rejected_reason_empty`
  - `source_boundary_blocks_training`
- Each worklist has:
  - a stable `worklist_key`,
  - candidate counts,
  - sequence start/end,
  - candidate previews,
  - a stable `review_sequence_key`,
  - a recommended action to open the first candidate in that blocker batch.
- The runtime contract now requires the held-candidates worklist fields.
- The Exports panel now shows "Prompt pair blocker worklists" with sequence/hash proof and a "Work this blocker" action.
- The Ralph gate now verifies that held candidates expose actionable worklists, not just a flat candidate list.

Verification:

```bash
docker compose exec -T api pytest -q tests/test_ralph_phase3_prompt_pair_audit.py::test_prompt_pair_audit_reports_200_plus_inspectable_pairs_with_samples_and_weak_spots
# 1 passed

npm run typecheck --prefix apps/web
# passed

npx --prefix apps/web playwright test --config apps/web/playwright.config.ts --grep "exports readiness"
# 1 passed

docker compose exec -T api pytest -q
# 86 passed

npx --prefix apps/web playwright test --config apps/web/playwright.config.ts
# 9 passed

python3 scripts/ralph_loop_gate.py --write-checkpoint --json
# PASS, 37 live checks

git diff --check
# clean
```

Current live checkpoint:

- `updates/ralph_loop_gate_checkpoint_20260429T121249_636551Z.json`
- `updates/ralph_loop_gate_checkpoint_latest.json`
- `updates/ralph_loop_gate_checkpoint_latest.md`

Next useful loop target:

- Convert the same "batchable bottleneck" idea into a photo-context review progress surface, so Adam can see which photo groups are still no-claim, which already have review tasks, and which are closest to vector-ready memory records.

## Continuation Update: Photo Context Review Worklists

This loop added batchable photo-context worklists to the existing photo review pack.

What changed:

- `/api/assets/photo-context-review-pack` now includes `review_worklists`.
- The runtime contract now requires the photo context pack worklist fields.
- The live pack currently exposes three worklists:
  - `photo_context:no_claim_needs_context`
  - `photo_context:machine_draft_needs_adam_review`
  - `photo_context:gallery_draft_needs_review`
- Each worklist includes:
  - a stable namespaced key,
  - a stable `review_sequence_key`,
  - candidate counts,
  - candidate previews with photo thumbnails,
  - a recommended first action,
  - explicit `not_memory_claim` policy.
- The Exports panel now shows a "Photo context worklists" section with counts, hashes, and open actions.
- The YAML/Markdown pack previews now include the review-worklist summary.

Verification:

```bash
docker compose exec -T api pytest -q tests/test_ralph_phase2_photo_spine.py::test_photo_context_review_pack_combines_no_claim_gaps_held_drafts_and_vector_ready_records
# 1 passed

npm run typecheck --prefix apps/web
# passed

npx --prefix apps/web playwright test --config apps/web/playwright.config.ts --grep "exports readiness"
# 1 passed

docker compose exec -T api pytest -q
# 86 passed

npx --prefix apps/web playwright test --config apps/web/playwright.config.ts
# 9 passed

python3 scripts/ralph_loop_gate.py --write-checkpoint --json
# PASS, 37 live checks

git diff --check
# clean
```

Current live checkpoint:

- `updates/ralph_loop_gate_checkpoint_20260429T122048_580115Z.json`
- `updates/ralph_loop_gate_checkpoint_latest.json`
- `updates/ralph_loop_gate_checkpoint_latest.md`

Next useful loop target:

- Make the artifact outputs more inspectable by adding a compact artifact manifest endpoint that lists every current downstream file-like output, its format, hash, source endpoint, and training/vector/gallery eligibility.

## Continuation Update: Downstream Artifact Manifest

This loop added a single machine-readable inventory of downstream outputs.

What changed:

- Added `/api/downstream-readiness/artifact-manifest`.
- The manifest lists 10 current outputs across:
  - prompt-pair audit,
  - prompt-pair voice references,
  - approved SFT/DPO JSONL,
  - candidate SFT/DPO dry-runs,
  - photo-context review YAML preview,
  - photo vector handoff JSONL and manifest.
- Each artifact includes:
  - `artifact_key`,
  - format,
  - source endpoint,
  - optional download endpoint,
  - content hash,
  - record count,
  - preview size,
  - training/vector/gallery/human-review eligibility,
  - policy snapshot.
- The runtime contract now requires the artifact manifest fields.
- The Exports panel now shows the artifact manifest hash and a `Manifest JSON` link.
- The Ralph gate now verifies hashes, formats, endpoints, eligibility flags, and candidate-vs-approved policy.

Verification:

```bash
docker compose exec -T api pytest -q tests/test_ralph_phase3_prompt_pair_audit.py::test_downstream_artifact_manifest_lists_hashable_outputs_without_side_effects
# 1 passed

npm run typecheck --prefix apps/web
# passed

npx --prefix apps/web playwright test --config apps/web/playwright.config.ts --grep "exports readiness"
# 1 passed

docker compose exec -T api pytest -q
# 87 passed

npx --prefix apps/web playwright test --config apps/web/playwright.config.ts
# 9 passed

python3 scripts/ralph_loop_gate.py --write-checkpoint --json
# PASS, 38 live checks

git diff --check
# clean
```

Current live checkpoint:

- `updates/ralph_loop_gate_checkpoint_20260429T123155_682099Z.json`
- `updates/ralph_loop_gate_checkpoint_latest.json`
- `updates/ralph_loop_gate_checkpoint_latest.md`

Next useful loop target:

- Add a small export-audit endpoint that validates the manifest's download/source endpoints against their declared hashes for a bounded subset, catching stale or mismatched artifact links before a human trusts them.

## Continuation Update: Downstream Artifact Hash Audit

This loop added a verification layer for the artifact manifest.

What changed:

- Added `/api/downstream-readiness/artifact-audit`.
- The audit recomputes the artifact bodies behind the manifest entries and compares:
  - declared hash,
  - recomputed hash,
  - source endpoint,
  - download endpoint,
  - output format,
  - policy snapshot.
- The Exports panel now shows `Hash audit: all hashes match` beside the artifact manifest.
- The runtime contract now requires the artifact-audit fields.
- The Ralph gate now verifies that all 10 manifest artifacts pass hash recomputation.

Verification:

```bash
docker compose exec -T api pytest -q tests/test_ralph_phase3_prompt_pair_audit.py::test_downstream_artifact_audit_recomputes_manifest_hashes
# 1 passed

npm run typecheck --prefix apps/web
# passed

npx --prefix apps/web playwright test --config apps/web/playwright.config.ts --grep "exports readiness"
# 1 passed

docker compose exec -T api pytest -q
# 88 passed

npx --prefix apps/web playwright test --config apps/web/playwright.config.ts
# 9 passed

python3 scripts/ralph_loop_gate.py --write-checkpoint --json
# PASS, 39 live checks

git diff --check
# clean
```

Current live checkpoint:

- `updates/ralph_loop_gate_checkpoint_20260429T123727_667952Z.json`
- `updates/ralph_loop_gate_checkpoint_latest.json`
- `updates/ralph_loop_gate_checkpoint_latest.md`

Next useful loop target:

- Make manifest/audit results more actionable by showing a compact per-artifact table in the UI with eligibility badges and hash status, so the user can see what is training-ready, vector-ready, or review-only without opening JSON.

## Continuation Update: Artifact Manifest Table

This loop made the export surface more legible instead of requiring the user to open raw JSON to understand what would be produced.

What changed:

- The Exports readiness panel now includes a compact `Artifact Manifest` table.
- The table shows the first six downstream outputs with:
  - artifact label,
  - output format,
  - artifact family,
  - training/vector/gallery/human-review eligibility labels,
  - per-artifact hash audit status.
- The existing manifest download still points to the exact JSON manifest.
- The UI smoke test now verifies visible artifact labels, eligibility labels, and `hash ok` status, not just that the card exists.

Verification:

```bash
npm run typecheck --prefix apps/web
# passed

npx --prefix apps/web playwright test --config apps/web/playwright.config.ts --grep "exports readiness"
# 1 passed

docker compose exec -T api pytest -q
# 88 passed

npx --prefix apps/web playwright test --config apps/web/playwright.config.ts
# 9 passed

python3 scripts/ralph_loop_gate.py --write-checkpoint --json
# PASS, 39 live checks

git diff --check
# clean
```

Current live checkpoint:

- `updates/ralph_loop_gate_checkpoint_20260429T124337_892645Z.json`
- `updates/ralph_loop_gate_checkpoint_latest.json`
- `updates/ralph_loop_gate_checkpoint_latest.md`

Next useful loop target:

- Add a small morning handoff endpoint/report that summarizes the current gate checkpoint, top unresolved bottlenecks, and next operator actions, so the long-running loop has a durable status surface when Adam returns.

## Continuation Update: Morning Handoff Surface

This loop added a durable morning status surface for the long run.

What changed:

- Added `/api/downstream-readiness/morning-handoff`.
- The handoff reports:
  - top bottleneck area,
  - prompt-pair/photo/vector/demo/artifact readiness,
  - top operator actions,
  - artifact manifest and hash-audit status,
  - live model gating status,
  - safety reminders that no fine-tuning APIs are called and demo outputs stay `model_generated`.
- The runtime contract now requires the handoff endpoint fields.
- The Exports panel now shows a `Morning Handoff` card with the top bottleneck, readiness strip, hash audit status, and report hash.
- The Ralph gate now verifies that the handoff names real bottlenecks, preserves `no_claim` photo truth, preserves `model_generated` demo truth, and includes the no-fine-tuning policy.

Verification:

```bash
docker compose exec -T api pytest -q tests/test_ralph_phase3_prompt_pair_audit.py::test_downstream_morning_handoff_summarizes_live_bottlenecks_and_artifacts
# 1 passed

npm run typecheck --prefix apps/web
# passed

npx --prefix apps/web playwright test --config apps/web/playwright.config.ts --grep "exports readiness"
# 1 passed after tightening ambiguous text assertions

docker compose exec -T api pytest -q
# 89 passed

npx --prefix apps/web playwright test --config apps/web/playwright.config.ts
# 9 passed

python3 scripts/ralph_loop_gate.py --write-checkpoint --json
# PASS, 40 live checks

git diff --check
# clean
```

Current live checkpoint:

- `updates/ralph_loop_gate_checkpoint_20260429T125306_436155Z.json`
- `updates/ralph_loop_gate_checkpoint_latest.json`
- `updates/ralph_loop_gate_checkpoint_latest.md`

Next useful loop target:

- Turn the handoff's top bottlenecks into a concrete, inspectable operator checklist so the next work is not just visible but sequenced into small, verifiable actions.

## Continuation Update: Operator Checklist

This loop turned the morning handoff from a status readout into a sequenced work surface.

What changed:

- `/api/downstream-readiness/morning-handoff` now includes `operator_checklist`.
- Each checklist item includes:
  - stable checklist id,
  - area key and priority,
  - action type and task target when available,
  - actionable vs blocked status,
  - completion signal,
  - acceptance test,
  - safety boundary.
- Prompt-pair checklist items require Adam gold review before authenticity/training promotion.
- Photo-context checklist items explicitly preserve `no_claim` until Adam-authored context exists.
- Demo-generation checklist items remain blocked until credentials/live-call settings are ready and preserve the no-fine-tuning MVP rule.
- The Exports panel renders the checklist inside `Morning Handoff`.
- Browser tests now assert the concrete completion signals are visible.

Verification:

```bash
docker compose exec -T api pytest -q tests/test_ralph_phase3_prompt_pair_audit.py::test_downstream_morning_handoff_summarizes_live_bottlenecks_and_artifacts
# 1 passed

npm run typecheck --prefix apps/web
# passed

npx --prefix apps/web playwright test --config apps/web/playwright.config.ts --grep "exports readiness"
# 1 passed

docker compose exec -T api pytest -q
# 89 passed

npx --prefix apps/web playwright test --config apps/web/playwright.config.ts
# 9 passed

python3 scripts/ralph_loop_gate.py --write-checkpoint --json
# PASS, 40 live checks

git diff --check
# clean
```

Current live checkpoint:

- `updates/ralph_loop_gate_checkpoint_20260429T125809_723227Z.json`
- `updates/ralph_loop_gate_checkpoint_latest.json`
- `updates/ralph_loop_gate_checkpoint_latest.md`

Next useful loop target:

- Add a narrow, non-mutating “review queue slice” for the top prompt-pair blocker so Adam can open the first few candidate tickets with blocker reasons, YAML previews, and completion criteria from one place.

## Continuation Update: Prompt-Pair Top Blocker Slice

This loop made the highest prompt-pair bottleneck directly inspectable.

What changed:

- Added `/api/prompt-pairs/top-blocker-slice`.
- The slice is read-only and candidate-only; it does not promote any row to training export.
- It selects the top backend blocker worklist and returns:
  - blocker name,
  - candidate count,
  - review sequence hash,
  - completion signal,
  - safety boundaries,
  - first five candidate tasks,
  - prompt and response previews,
  - source/context previews,
  - exact export YAML preview,
  - backend preflight status and blockers,
  - open-task action.
- The runtime contract now requires this endpoint.
- The Exports panel shows the top blocker slice inside `Held Prompt Pair Review Pack`.
- Browser tests now assert the blocker slice, completion signal, YAML preview marker, and hash.
- Live state currently reports top blocker `dpo_rejected_reason_empty` with 25 held candidates and 5 previewed tasks.

Verification:

```bash
docker compose exec -T api pytest -q tests/test_ralph_phase3_prompt_pair_audit.py::test_prompt_pair_top_blocker_slice_exposes_reviewable_yaml_previews
# 1 passed

npm run typecheck --prefix apps/web
# passed

npx --prefix apps/web playwright test --config apps/web/playwright.config.ts --grep "exports readiness"
# 1 passed

docker compose exec -T api pytest -q
# 90 passed

npx --prefix apps/web playwright test --config apps/web/playwright.config.ts
# 9 passed

python3 scripts/ralph_loop_gate.py --write-checkpoint --json
# PASS, 41 live checks

git diff --check
# clean
```

Current live checkpoint:

- `updates/ralph_loop_gate_checkpoint_20260429T130501_776691Z.json`
- `updates/ralph_loop_gate_checkpoint_latest.json`
- `updates/ralph_loop_gate_checkpoint_latest.md`

Next useful loop target:

- Add the analogous non-mutating review slice for photo context: top no-claim photo groups with preview URLs, suggested context fields, task/create action, and completion criteria.

## Continuation Update: Photo Context Top Slice

This loop made the highest photo-context bottleneck directly inspectable.

What changed:

- Added `/api/assets/photo-context-review-pack/top-context-slice`.
- The slice is read-only and no-claim by design; it does not turn filename/title evidence into memory.
- It exposes the top photo-context worklist as `photo_context:no_claim_needs_context`.
- Each item includes:
  - preview and thumbnail URLs,
  - source photo IDs and titles,
  - suggested context fields for Adam (`visible_facts`, `invisible_context`, `meaning`, `uncertainty`),
  - open/create task action,
  - no-claim safety boundary,
  - completion criteria,
  - candidate evidence and review policy.
- The runtime contract now requires this endpoint.
- The Exports panel shows the top photo context slice inside `Photo Context Review Pack`.
- Browser tests now assert the slice summary, image preview, no-claim policy, suggested fields, and completion signal.
- Live state currently reports 22 photo-context candidate groups and previews the first five: `Rotmil 2021 II.jpg`, `Rotmil 2021 III.jpg`, `Rotmil 2021 IV.jpg`, `Rotmil 2021 V.jpg`, and `Rotmil 2021 VI.jpg`.
- Playwright caught one real UI ambiguity during this loop: the top-slice summary and list had similar accessible labels. I tightened the selector and kept the product assertion strict.

Verification:

```bash
docker compose exec -T api pytest -q tests/test_ralph_phase2_photo_spine.py::test_photo_context_review_pack_combines_no_claim_gaps_held_drafts_and_vector_ready_records
# 1 passed

npm run typecheck --prefix apps/web
# passed

npx --prefix apps/web playwright test --config apps/web/playwright.config.ts --grep "exports readiness"
# 1 passed

docker compose exec -T api pytest -q
# 90 passed

npx --prefix apps/web playwright test --config apps/web/playwright.config.ts
# 9 passed

python3 scripts/ralph_loop_gate.py --write-checkpoint --json
# PASS, 42 live checks

git diff --check
# clean
```

Current live checkpoint:

- `updates/ralph_loop_gate_checkpoint_20260429T131444_286249Z.json`
- `updates/ralph_loop_gate_checkpoint_latest.json`
- `updates/ralph_loop_gate_checkpoint_latest.md`

Next useful loop target:

- Connect retrieval gaps such as `airplane in Maine` to a first-class review slice, so no-result memory queries can drive photo-context tickets with explicit query provenance and no-claim boundaries.

## Continuation Update: Retrieval Gap Review Slice

This loop turned an honest no-result retrieval response into a first-class review slice.

What changed:

- Added `/api/retrieval/gap-review-slice`.
- The slice wraps a query such as `airplane in Maine` and returns reviewable photo candidates when no boundary-cleared memory exists.
- It preserves:
  - source query,
  - no-claim retrieval provenance,
  - candidate match quality,
  - selection reason,
  - source-photo preview and thumbnail URLs,
  - create/open task action,
  - Adam-authored completion criteria.
- The slice explicitly does not create memory claims, mutate source files, create training examples, or promote anything to vector handoff.
- The runtime contract now requires this endpoint.
- The Exports panel now shows a retrieval-gap slice summary and previewable candidate cards under Retrieval Proof.
- Browser testing caught a stale-container false positive first, then an accessibility/test ambiguity caused by intentionally showing the same query twice. I restarted the live containers and tightened the selector while keeping the product assertion strict.
- Live state for `airplane in Maine` currently reports 27 no-claim candidate groups, 5 previewed, 0 weak evidence matches, and 27 backlog-only candidates.

Verification:

```bash
docker compose exec -T api pytest -q tests/test_ralph_phase2_photo_spine.py::test_photo_retrieval_gap_is_actionable_without_inventing_memory tests/test_ralph_phase2_photo_spine.py::test_photo_retrieval_gap_surfaces_machine_draft_candidates_as_non_memory_claims
# 2 passed

npm run typecheck --prefix apps/web
# passed

npx --prefix apps/web playwright test --config apps/web/playwright.config.ts --grep "exports readiness"
# 1 passed

docker compose exec -T api pytest -q
# 90 passed

npx --prefix apps/web playwright test --config apps/web/playwright.config.ts
# 9 passed

python3 scripts/ralph_loop_gate.py --write-checkpoint --json
# PASS, 43 live checks

git diff --check
# clean
```

Current live checkpoint:

- `updates/ralph_loop_gate_checkpoint_20260429T132528_043408Z.json`
- `updates/ralph_loop_gate_checkpoint_latest.json`
- `updates/ralph_loop_gate_checkpoint_latest.md`

Next useful loop target:

- Make the morning handoff consume the new retrieval-gap slice, so the next operator checklist can point directly from an unanswered memory query to the exact no-claim photo candidates that would close it.

## Continuation Update: Morning Handoff Retrieval Gap Work

This loop connected the morning handoff to the retrieval-gap review slice.

What changed:

- `GET /api/downstream-readiness/morning-handoff` now accepts `retrieval_gap_query`.
- The handoff includes `retrieval_gap_work`, using the same `/api/retrieval/gap-review-slice` semantics.
- The photo-context operator checklist mirrors the retrieval-gap query, candidate count, slice hash, and preview titles.
- The handoff Markdown now includes a `Retrieval Gap Work` section.
- The runtime contract now requires `retrieval_gap_work` on morning handoff responses.
- The Exports panel now shows the handoff’s unanswered memory query, no-claim candidate count, slice hash, first candidate, and review policy.
- Live handoff state for `airplane in Maine` reports 27 no-claim candidates and the same slice hash as the standalone retrieval-gap endpoint: `98505505cc99c0f27222fa5d445ae0560339ef1a12d247dd3dcb7112a5004bc5`.

Verification:

```bash
docker compose exec -T api pytest -q tests/test_ralph_phase3_prompt_pair_audit.py::test_downstream_morning_handoff_summarizes_live_bottlenecks_and_artifacts
# 1 passed

npm run typecheck --prefix apps/web
# passed

npx --prefix apps/web playwright test --config apps/web/playwright.config.ts --grep "exports readiness"
# 1 passed

docker compose exec -T api pytest -q
# 90 passed

npx --prefix apps/web playwright test --config apps/web/playwright.config.ts
# 9 passed

python3 scripts/ralph_loop_gate.py --write-checkpoint --json
# PASS, 43 live checks

git diff --check
# clean
```

Current live checkpoint:

- `updates/ralph_loop_gate_checkpoint_20260429T133314_175106Z.json`
- `updates/ralph_loop_gate_checkpoint_latest.json`
- `updates/ralph_loop_gate_checkpoint_latest.md`

Next useful loop target:

- Add an exportable, hash-audited YAML artifact for the morning handoff itself, so the overnight session leaves a durable operator packet alongside the machine-readable endpoints.

## Continuation Update: Morning Handoff YAML Artifact

This loop made the morning handoff itself a downstream artifact instead of only an API view.

What changed:

- Added `morning_handoff_yaml` to the downstream artifact manifest as an `operator_handoff` artifact.
- Added `GET /api/downstream-readiness/morning-handoff.yaml` returning human-readable YAML.
- Added the handoff YAML to the downstream artifact hash audit.
- Avoided recursive artifact summaries by compiling the handoff's internal artifact summary without the handoff artifact itself.
- Added a Handoff YAML download card to the Exports panel.
- Made the YAML artifact stable by omitting volatile generation timestamps; the live browser had caught a hash mismatch when the running API still emitted `generated_at`.

Verification:

```bash
docker compose exec -T api pytest -q tests/test_ralph_phase3_prompt_pair_audit.py::test_downstream_artifact_manifest_lists_hashable_outputs_without_side_effects tests/test_ralph_phase3_prompt_pair_audit.py::test_downstream_artifact_audit_recomputes_manifest_hashes
# 2 passed

npm run typecheck --prefix apps/web
# passed

npx --prefix apps/web playwright test --config apps/web/playwright.config.ts --grep "exports readiness"
# 1 passed

curl /api/downstream-readiness/artifact-audit
# checked_count: 11, mismatch_count: 0, morning_handoff_yaml hash_matches: true

docker compose exec -T api pytest -q
# 90 passed

npx --prefix apps/web playwright test --config apps/web/playwright.config.ts
# 9 passed

python3 scripts/ralph_loop_gate.py --write-checkpoint --json
# PASS, 43 live checks

git diff --check
# clean
```

Current live checkpoint:

- `updates/ralph_loop_gate_checkpoint_20260429T134507_798328Z.json`
- `updates/ralph_loop_gate_checkpoint_latest.json`
- `updates/ralph_loop_gate_checkpoint_latest.md`

Next useful loop target:

- Add an artifact-audit detail surface for mismatches, so future failures show the exact artifact key, declared hash, recomputed hash, and likely stability cause directly in the UI.

## Continuation Update: Artifact Hash Audit Detail Surface

This loop made export hash failures visible in the operator UI instead of only in the gate output.

What changed:

- Added an `Artifact Hash Audit` card to the Exports readiness panel.
- The card lists every audited artifact, its format, hash status, label, declared hash prefix, and recomputed hash prefix.
- The browser smoke test now asserts that the card is present, that all 11 artifacts are checked with 0 mismatches, and that the `Morning handoff YAML` artifact appears in the detailed audit list.
- This keeps the artifact manifest and artifact audit connected in the place Adam is already reviewing downstream outputs.

Verification:

```bash
docker compose exec -T api pytest -q tests/test_ralph_phase3_prompt_pair_audit.py::test_downstream_artifact_audit_recomputes_manifest_hashes
# 1 passed

npm run typecheck --prefix apps/web
# passed

npx --prefix apps/web playwright test --config apps/web/playwright.config.ts --grep "exports readiness"
# 1 passed

docker compose exec -T api pytest -q
# 90 passed

npx --prefix apps/web playwright test --config apps/web/playwright.config.ts
# 9 passed

python3 scripts/ralph_loop_gate.py --write-checkpoint --json
# PASS, 43 live checks

git diff --check
# clean
```

Current live checkpoint:

- `updates/ralph_loop_gate_checkpoint_20260429T134954_061885Z.json`
- `updates/ralph_loop_gate_checkpoint_latest.json`
- `updates/ralph_loop_gate_checkpoint_latest.md`

Next useful loop target:

- Improve the top prompt-pair blocker path by adding an exportable repair packet for the 25 DPO candidates whose rejected response rationale is missing.

## Continuation Update: DPO Rejected-Reason Repair Packet

This loop turned the largest prompt-pair blocker into a concrete repair packet.

What changed:

- Added `GET /api/prompt-pairs/dpo-rejected-reason-repair-pack`.
- Added `GET /api/prompt-pairs/dpo-rejected-reason-repair-pack/yaml`.
- The packet exposes the 25 DPO candidates blocked by `dpo_rejected_reason_empty`, including task IDs, prompts, chosen/rejected previews, backend blockers, repair fields, completion criteria, and open-ticket actions.
- Added `dpo_rejected_reason_repair_yaml` to the downstream artifact manifest and artifact hash audit.
- The Exports panel now shows a DPO repair packet download, the rejected-reason gap count, and a repair worklist with direct “Open DPO repair” actions.
- The runtime contract now includes the repair packet endpoint.

Verification:

```bash
curl /api/prompt-pairs/dpo-rejected-reason-repair-pack?limit=3
# total_candidate_count: 25, reported_candidate_count: 3, blocker: dpo_rejected_reason_empty

curl /api/downstream-readiness/artifact-audit
# checked_count: 12, mismatch_count: 0, dpo_rejected_reason_repair_yaml hash_matches: true

docker compose exec -T api pytest -q tests/test_ralph_phase3_prompt_pair_audit.py::test_prompt_pair_top_blocker_slice_exposes_reviewable_yaml_previews tests/test_ralph_phase3_prompt_pair_audit.py::test_downstream_artifact_manifest_lists_hashable_outputs_without_side_effects tests/test_ralph_phase3_prompt_pair_audit.py::test_downstream_artifact_audit_recomputes_manifest_hashes
# 3 passed

npm run typecheck --prefix apps/web
# passed

npx --prefix apps/web playwright test --config apps/web/playwright.config.ts --grep "exports readiness"
# 1 passed

docker compose exec -T api pytest -q
# 90 passed

npx --prefix apps/web playwright test --config apps/web/playwright.config.ts
# 9 passed

python3 scripts/ralph_loop_gate.py --write-checkpoint --json
# PASS, 44 live checks

git diff --check
# clean
```

Current live checkpoint:

- `updates/ralph_loop_gate_checkpoint_20260429T140050_058417Z.json`
- `updates/ralph_loop_gate_checkpoint_latest.json`
- `updates/ralph_loop_gate_checkpoint_latest.md`

Next useful loop target:

- Add an Adam-facing “review one repair candidate” projection that shows what will change if a DPO rejected-side reason is added, without mutating the task.

## Continuation Update: Non-Mutating DPO Repair Projection

This loop made the DPO repair packet explanatory enough to review safely.

What changed:

- Each DPO repair item now includes a `repair_projection`.
- The projection applies a hypothetical `failure_modes` patch in memory only.
- It records before/after backend blockers, cleared blockers, whether the target blocker clears, the after-repair export status, and the fact that Adam gold review is still required.
- The repair packet YAML includes projected target-blocker status and projected after-export status.
- The Exports UI now shows a `Non-mutating projection` row in the DPO repair packet worklist.

Verification:

```bash
docker compose exec -T api pytest -q tests/test_ralph_phase3_prompt_pair_audit.py::test_prompt_pair_top_blocker_slice_exposes_reviewable_yaml_previews
# 1 passed

npm run typecheck --prefix apps/web
# passed

npx --prefix apps/web playwright test --config apps/web/playwright.config.ts --grep "exports readiness"
# 1 passed

docker compose exec -T api pytest -q
# 90 passed

npx --prefix apps/web playwright test --config apps/web/playwright.config.ts
# 9 passed

python3 scripts/ralph_loop_gate.py --write-checkpoint --json
# PASS, 44 live checks

git diff --check
# clean
```

Current live checkpoint:

- `updates/ralph_loop_gate_checkpoint_20260429T140556_157128Z.json`
- `updates/ralph_loop_gate_checkpoint_latest.json`
- `updates/ralph_loop_gate_checkpoint_latest.md`

Next useful loop target:

- Make the photo-context bottleneck equally decomposable by producing a query-aware “review session plan” for the top no-claim photo groups.

## Continuation Update: Query-Aware Photo Context Review Session Plan

This loop turned the broad photo-context bottleneck into a first-class review-session plan.

What changed:

- Added `/api/assets/photo-context-review-pack/review-session-plan`.
- The plan selects the top no-claim photo groups, preserves the retrieval query as prioritization context only, and never treats the query as evidence about the photo.
- Each planned item carries preview URLs, no-claim truth boundaries, a create/open context-task action, Adam-authored completion criteria, and a shared field plan: visible facts, invisible context, meaning, uncertainty.
- The Downstream Readiness UI now shows the review-session plan directly under the photo top slice, including the query context and field plan.
- The runtime contract and Ralph gate now fail if this session plan stops being non-mutating, no-claim, query-aware, or actionable.

Verification:

```bash
docker compose exec -T api pytest -q tests/test_ralph_phase2_photo_spine.py::test_photo_context_review_pack_combines_no_claim_gaps_held_drafts_and_vector_ready_records
# 1 passed

npm run typecheck --prefix apps/web
# passed

npx --prefix apps/web playwright test --config apps/web/playwright.config.ts --grep "exports readiness exposes demo gate and retrieval actions"
# 1 passed

docker compose exec -T api pytest -q
# 90 passed

npx --prefix apps/web playwright test --config apps/web/playwright.config.ts
# 9 passed

python3 scripts/ralph_loop_gate.py --write-checkpoint --json
# PASS, 45 live checks

git diff --check
# clean
```

Current live checkpoint:

- `updates/ralph_loop_gate_checkpoint_20260429T141654_783308Z.json`
- `updates/ralph_loop_gate_checkpoint_latest.json`
- `updates/ralph_loop_gate_checkpoint_latest.md`

Next useful loop target:

- Make the photo review-session plan downloadable and hash-audited alongside the other downstream artifacts, so the morning handoff and export surface share the same exact no-claim photo work packet.

## Continuation Update: Photo Review Session Plan As Hash-Audited Artifact

This loop made the query-aware photo review-session plan a real downstream artifact instead of only a live JSON panel.

What changed:

- The review-session plan now includes an exact YAML export preview and an export SHA-256.
- Added `/api/assets/photo-context-review-pack/review-session-plan/yaml`.
- Added `photo_context_review_session_plan_yaml` to the downstream artifact manifest.
- The artifact hash audit recomputes the YAML body and verifies it against the declared manifest hash.
- The Downstream Readiness UI now shows a `Photo session plan` artifact card with the YAML link and the audited hash.
- The YAML carries top-level safety language even when a fixture has zero selected items, including `query_is_context_prioritization_only: true`.

Verification:

```bash
docker compose exec -T api pytest -q tests/test_ralph_phase2_photo_spine.py::test_photo_context_review_pack_combines_no_claim_gaps_held_drafts_and_vector_ready_records tests/test_ralph_phase3_prompt_pair_audit.py::test_downstream_artifact_manifest_lists_hashable_outputs_without_side_effects tests/test_ralph_phase3_prompt_pair_audit.py::test_downstream_artifact_audit_recomputes_manifest_hashes
# 3 passed

npm run typecheck --prefix apps/web
# passed

npx --prefix apps/web playwright test --config apps/web/playwright.config.ts --grep "exports readiness exposes demo gate and retrieval actions"
# 1 passed

docker compose exec -T api pytest -q
# 90 passed

npx --prefix apps/web playwright test --config apps/web/playwright.config.ts
# 9 passed

python3 scripts/ralph_loop_gate.py --write-checkpoint --json
# PASS, 45 live checks; artifact_count: 13; checked_count: 13; mismatch_count: 0

git diff --check
# clean
```

Current live checkpoint:

- `updates/ralph_loop_gate_checkpoint_20260429T142742_154570Z.json`
- `updates/ralph_loop_gate_checkpoint_latest.json`
- `updates/ralph_loop_gate_checkpoint_latest.md`

Next useful loop target:

- Make the photo context task creation path consume the review-session plan’s selected items exactly, with a dry-run receipt that records plan hash, selected item keys, and the projected task deltas before any mutation.

## Continuation Update: Plan-Exact Photo Context Session Receipts

This loop closed the gap between the photo review-session plan and the endpoint that creates review tasks.

What changed:

- `POST /api/assets/photo-context-review-pack/review-session` now builds from the same review-session plan used by the UI and artifact export.
- Dry-run receipts include `plan_content_sha256`, `plan_export_preview_sha256`, `selected_item_keys`, and `projected_task_delta`.
- Each returned item includes `plan_item_key` and query provenance, preserving `query_is_context_prioritization_only`.
- Non-dry-run task creation still creates/open tasks, but the response records the plan selection that drove the mutation.
- The runtime contract now requires the review-session receipt fields.
- The Ralph gate now fails if the dry-run receipt is not plan-backed, not no-claim, or does not prove zero mutation.
- One gate bug was also caught and fixed: the checker was treating a valid zero mutation count as missing because of `0 or 99`.

Verification:

```bash
docker compose exec -T api pytest -q tests/test_ralph_phase2_photo_spine.py::test_photo_context_review_session_dry_runs_then_creates_no_claim_context_tasks
# 1 passed

npm run typecheck --prefix apps/web
# passed

docker compose exec -T api pytest -q
# 90 passed

npx --prefix apps/web playwright test --config apps/web/playwright.config.ts
# 9 passed

python3 scripts/ralph_loop_gate.py --write-checkpoint --json
# PASS, 45 live checks

git diff --check
# clean
```

Current live checkpoint:

- `updates/ralph_loop_gate_checkpoint_20260429T143651_349613Z.json`
- `updates/ralph_loop_gate_checkpoint_latest.json`
- `updates/ralph_loop_gate_checkpoint_latest.md`

Next useful loop target:

- Make the Prompt Pairs side equally receipt-driven by exposing a non-mutating “resolve DPO rejected reason” projection for one repair candidate, including before/after blockers, export status, and exact YAML diff preview.

## Continuation Update: Single-Candidate DPO Repair Projection Receipt

This loop made the DPO rejected-reason repair path inspectable at the single-ticket level before any human edit is saved.

What changed:

- Added `/api/prompt-pairs/dpo-rejected-reason-repair-projection`.
- The endpoint returns a non-mutating receipt for one DPO candidate, including the proposed rejected-side failure mode patch.
- The receipt compares before/after preflight blockers and proves that `dpo_rejected_reason_empty` would be cleared without promoting the item to approved export.
- The projection keeps the stricter safety state: the item still requires Adam gold edit and does not become training-ready.
- The response includes an exact YAML diff preview, plus before/after YAML snapshots and a stable content hash.
- The runtime contract and Ralph gate now require this projection surface.

Verification:

```bash
docker compose exec -T api pytest -q tests/test_ralph_phase3_prompt_pair_audit.py::test_prompt_pair_top_blocker_slice_exposes_reviewable_yaml_previews
# 1 passed

npm run typecheck --prefix apps/web
# passed

docker compose exec -T api pytest -q
# 90 passed

npx --prefix apps/web playwright test --config apps/web/playwright.config.ts
# 9 passed

python3 scripts/ralph_loop_gate.py --write-checkpoint --json
# PASS, 45 live checks

git diff --check
# clean
```

Current live checkpoint:

- `updates/ralph_loop_gate_checkpoint_20260429T144820_673476Z.json`
- `updates/ralph_loop_gate_checkpoint_latest.json`
- `updates/ralph_loop_gate_checkpoint_latest.md`

Next useful loop target:

- Bring the single-candidate DPO projection into the Downstream Readiness UI so Adam can see the exact rejected-reason diff before opening the repair ticket.

## Continuation Update: DPO Repair Projection In The Readiness UI

This loop moved the DPO repair projection from an API-only receipt into the operator-facing readiness surface.

What changed:

- The Downstream Readiness panel now fetches `/api/prompt-pairs/dpo-rejected-reason-repair-projection`.
- The DPO repair packet section renders a single-ticket repair receipt with:
  - the task human ID and prompt,
  - before blockers,
  - projected after blockers,
  - the rejected-side failure mode patch,
  - a short receipt hash,
  - the exact YAML diff preview.
- The UI copy keeps the safety boundary visible: this is non-mutating and Adam gold edit is still required.
- Browser coverage now asserts that the receipt, blocker transition, failure mode, hash, and YAML diff affordance are visible.

Verification:

```bash
npm run typecheck --prefix apps/web
# passed

docker compose exec -T api pytest -q tests/test_ralph_phase3_prompt_pair_audit.py::test_prompt_pair_top_blocker_slice_exposes_reviewable_yaml_previews
# 1 passed

npx --prefix apps/web playwright test --config apps/web/playwright.config.ts --grep "exports readiness exposes demo gate and retrieval actions"
# 1 passed

docker compose exec -T api pytest -q
# 90 passed

npx --prefix apps/web playwright test --config apps/web/playwright.config.ts
# 9 passed

python3 scripts/ralph_loop_gate.py --write-checkpoint --json
# PASS, 45 live checks

git diff --check
# clean
```

Current live checkpoint:

- `updates/ralph_loop_gate_checkpoint_20260429T145446_832387Z.json`
- `updates/ralph_loop_gate_checkpoint_latest.json`
- `updates/ralph_loop_gate_checkpoint_latest.md`

Next useful loop target:

- Improve the photo-memory review path for retrieval gaps by making the review task prefill and receipt explicitly capture the retrieval query, “not a memory claim” status, and the exact fields Adam needs to answer for semantic retrieval.

## Continuation Update: Retrieval-Gap Photo Tasks Carry Query-Specific Review Plans

This loop made the photo-memory path more explicit for semantic retrieval gaps such as `airplane in Maine`.

What changed:

- Photo context tasks created from retrieval gaps now include:
  - a `retrieval_gap_review` plan,
  - `not_memory_claim: true`,
  - a completion signal,
  - exact required review fields for semantic retrieval.
- The task’s suggested questions now include a query-specific prompt: what, if anything, connects the photo to the retrieval query.
- Existing older photo context tasks are backfilled when opened through the retrieval-gap action, so the operator does not get a stale task without the field plan.
- The photo context projection now tracks `retrieval_query_relevance` as a checklist field, marking it missing or complete based on Adam’s answer.
- The UI action for existing retrieval-gap tasks now calls the create/open endpoint first, backfills the operational task record, then opens the task.
- The task UI shows a `Retrieval gap task plan` card with the no-claim policy and required answer fields.

Verification:

```bash
docker compose exec -T api pytest -q tests/test_ralph_phase2_photo_spine.py::test_photo_context_task_created_from_retrieval_gap_preserves_query_origin tests/test_ralph_phase2_photo_spine.py::test_existing_photo_context_task_opened_from_retrieval_gap_backfills_review_plan
# 2 passed

npm run typecheck --prefix apps/web
# passed

npx --prefix apps/web playwright test --config apps/web/playwright.config.ts --grep "retrieval no-claim action opens a photo context task"
# 1 passed

docker compose exec -T api pytest -q
# 91 passed

npx --prefix apps/web playwright test --config apps/web/playwright.config.ts
# 9 passed

python3 scripts/ralph_loop_gate.py --write-checkpoint --json
# PASS, 45 live checks

git diff --check
# clean
```

Current live checkpoint:

- `updates/ralph_loop_gate_checkpoint_20260429T150750_263207Z.json`
- `updates/ralph_loop_gate_checkpoint_latest.json`
- `updates/ralph_loop_gate_checkpoint_latest.md`

Next useful loop target:

- Add a retrieval-gap completion receipt or worklist summary that proves which semantic questions remain unanswered across open photo-context tasks, so the operator can work the queue by missing retrieval fields rather than by filenames alone.

## Continuation Update: Retrieval-Gap Missing Field Summary

This loop made the photo-context progress queue report what retrieval-gap work is missing at the field level.

What changed:

- `photo_context_session_progress` now reports:
  - `retrieval_gap_task_count`,
  - `retrieval_gap_missing_field_counts`,
  - per-task `retrieval_gap_origin`,
  - per-task review policy and completion signal,
  - per-task missing retrieval fields.
- Saved drafts are projected through the backend before counting missing fields.
- Tasks with no draft use their `retrieval_gap_review.required_fields` plan, so they still show what Adam needs to answer.
- The Downstream Readiness panel now shows `Retrieval gap fields` with missing-field counts and retrieval-gap task count.
- Progress cards show missing retrieval fields before generic vector status, making the work queue more semantic than filename-based.

Verification:

```bash
docker compose exec -T api pytest -q tests/test_ralph_phase2_photo_spine.py::test_photo_context_session_progress_summarizes_retrieval_gap_missing_fields
# 1 passed

npm run typecheck --prefix apps/web
# passed

npx --prefix apps/web playwright test --config apps/web/playwright.config.ts --grep "exports readiness exposes demo gate and retrieval actions"
# 1 passed

docker compose exec -T api pytest -q
# 92 passed

npx --prefix apps/web playwright test --config apps/web/playwright.config.ts
# 9 passed

python3 scripts/ralph_loop_gate.py --write-checkpoint --json
# PASS, 45 live checks

git diff --check
# clean
```

Current live checkpoint:

- `updates/ralph_loop_gate_checkpoint_20260429T151346_047523Z.json`
- `updates/ralph_loop_gate_checkpoint_latest.json`
- `updates/ralph_loop_gate_checkpoint_latest.md`

Next useful loop target:

- Add a compact exportable photo-context worklist artifact for these missing retrieval fields, so the morning handoff and artifact audit can preserve the exact queue state rather than only showing it live in the UI.

## Continuation Update: Retrieval-Gap Field Worklist Artifact

This loop turned the live retrieval-gap missing-field summary into a durable, hash-audited export artifact.

What changed:

- Added `GET /api/assets/photo-context-review-pack/retrieval-gap-field-worklist`.
- Added `GET /api/assets/photo-context-review-pack/retrieval-gap-field-worklist/yaml`.
- The worklist is explicitly non-mutating, does not create memory claims, and requires Adam context before any downstream memory/vector promotion.
- Each item records the task id, photo title, retrieval query provenance, missing fields, completion signal, progress status, and no-claim truth boundary.
- The downstream artifact manifest now includes `photo_context_retrieval_gap_field_worklist_yaml`.
- The artifact hash audit now recomputes 14 outputs and verifies the new YAML worklist.
- The Downstream Readiness panel now shows a `Retrieval fields worklist` download and an in-panel summary of the missing semantic fields.
- The live loop gate now checks that the field worklist agrees with session progress and that listed items remain `no_claim`.

Verification:

```bash
docker compose exec -T api pytest -q tests/test_ralph_phase2_photo_spine.py::test_photo_context_session_progress_summarizes_retrieval_gap_missing_fields tests/test_ralph_phase3_prompt_pair_audit.py::test_downstream_artifact_manifest_lists_hashable_outputs_without_side_effects tests/test_ralph_phase3_prompt_pair_audit.py::test_downstream_artifact_audit_recomputes_manifest_hashes
# 3 passed

npm run typecheck --prefix apps/web
# passed

docker compose exec -T api pytest -q
# 92 passed

npx --prefix apps/web playwright test --config apps/web/playwright.config.ts
# 9 passed

python3 scripts/ralph_loop_gate.py --write-checkpoint --json
# PASS, 45 live checks

git diff --check
# clean
```

Current live checkpoint:

- `updates/ralph_loop_gate_checkpoint_20260429T152735_564662Z.json`
- `updates/ralph_loop_gate_checkpoint_latest.json`
- `updates/ralph_loop_gate_checkpoint_latest.md`

Next useful loop target:

- Add a read-only preview of the exact photo-memory/vector records that would become available if the top retrieval-gap worklist items were completed, so Adam can see which unanswered fields have the highest downstream retrieval payoff before opening tasks.

## Continuation Update: Retrieval-Gap Payoff Preview

This loop added a non-mutating payoff preview for retrieval-gap photo work. It answers: "If Adam completes these missing fields, what downstream memory/vector surfaces would that unlock?"

What changed:

- Added `GET /api/assets/photo-context-review-pack/retrieval-gap-payoff-preview`.
- Added `GET /api/assets/photo-context-review-pack/retrieval-gap-payoff-preview/yaml`.
- Added the YAML payoff preview to the downstream artifact manifest and hash audit.
- Artifact manifest now reports 15 inspectable outputs.
- Artifact audit now recomputes 15 outputs with zero mismatches.
- Payoff items are still `no_claim` before completion.
- Missing Adam context is shown as explicit `[requires Adam: ...]` placeholders rather than generated memory text.
- Each payoff item names the records that completion would unlock:
  - `photo_memory_metadata_profile`
  - `photo_memory_text_record`
  - `reviewed_only_vector_handoff_record`
  - `retrieval_search_candidate_for_query`
- The Downstream Readiness UI now shows `Retrieval payoff preview`, with vector unlock counts and a payoff template preview.
- The live loop gate now checks that payoff previews point back to the field-worklist hash, preserve placeholder policy, and do not create memory claims.

Verification:

```bash
docker compose exec -T api pytest -q tests/test_ralph_phase2_photo_spine.py::test_photo_context_session_progress_summarizes_retrieval_gap_missing_fields tests/test_ralph_phase3_prompt_pair_audit.py::test_downstream_artifact_manifest_lists_hashable_outputs_without_side_effects tests/test_ralph_phase3_prompt_pair_audit.py::test_downstream_artifact_audit_recomputes_manifest_hashes
# 3 passed

npm run typecheck --prefix apps/web
# passed

docker compose exec -T api pytest -q
# 92 passed

npx --prefix apps/web playwright test --config apps/web/playwright.config.ts
# 9 passed

python3 scripts/ralph_loop_gate.py --write-checkpoint --json
# PASS, 45 live checks

git diff --check
# clean
```

Current live checkpoint:

- `updates/ralph_loop_gate_checkpoint_20260429T153824_741023Z.json`
- `updates/ralph_loop_gate_checkpoint_latest.json`
- `updates/ralph_loop_gate_checkpoint_latest.md`

Next useful loop target:

- Make the photo-context task itself show the same retrieval payoff preview beside the editable review form, so Adam sees why each missing field matters at the moment he is filling it in.

## Continuation Update: Task-Level Retrieval Payoff Preview

This loop moved the retrieval-gap payoff from a readiness/report artifact into the actual photo-context review task, so the reviewer sees the downstream consequence at the moment of editing.

What changed:

- Added a `Task retrieval payoff preview` section inside the editable photo-context task.
- The preview is shown only when the task has retrieval-gap provenance, such as `airplane in Maine`.
- The panel preserves the no-claim policy:
  - it says `No generated memory claim`;
  - it shows the `retrieval_gap_no_claim_until_adam_context` policy;
  - it uses `[requires Adam: ...]` placeholders for missing context.
- The task-level panel shows the same downstream unlock target as the readiness artifact:
  - `reviewed_only_vector_handoff_record`
  - query provenance
  - still-needed fields
- As Adam edits the reviewed visual description, the payoff template updates in place.
- Browser coverage now verifies that opening the retrieval no-claim action lands in a photo-context task with the payoff preview visible and live-updating.

Verification:

```bash
npm run typecheck --prefix apps/web
# passed

npx --prefix apps/web playwright test --config apps/web/playwright.config.ts --grep "retrieval no-claim action opens a photo context task with query provenance"
# 1 passed

docker compose exec -T api pytest -q
# 92 passed

npm run typecheck --prefix apps/web
# passed

npx --prefix apps/web playwright test --config apps/web/playwright.config.ts
# 9 passed

python3 scripts/ralph_loop_gate.py --write-checkpoint --json
# PASS, 45 live checks

git diff --check
# clean
```

Current live checkpoint:

- `updates/ralph_loop_gate_checkpoint_20260429T154549_916534Z.json`
- `updates/ralph_loop_gate_checkpoint_latest.json`
- `updates/ralph_loop_gate_checkpoint_latest.md`

Next useful loop target:

- Turn the top photo-context bottleneck into a concrete, ordered review session in the workbench, so the reviewer can clear the highest-payoff retrieval gaps from one visible queue rather than opening single tasks one at a time.

## Continuation Update: Ordered Photo Context Review Session Queue

This loop turned the read-only photo context session plan into a visible ordered queue inside the workbench.

What changed:

- Added an `Ordered photo context review session` surface to the Downstream Readiness panel.
- The queue lists the selected no-claim photo groups in explicit sequence order.
- Each queue item shows:
  - thumbnail preview;
  - sequence number;
  - source query provenance, currently `airplane in Maine`;
  - `No Claim` truth status;
  - completion criteria;
  - the first field prompts Adam needs to answer.
- Added a `Create/open session queue` action that uses the existing no-claim session endpoint.
- Added per-item `Create context task` / `Open context task` actions.
- The UI keeps the existing policy intact: creating/opening a task does not create a memory claim, and the query is only prioritization context until Adam submits reviewed context.

Verification:

```bash
npm run typecheck --prefix apps/web
# passed

npx --prefix apps/web playwright test --config apps/web/playwright.config.ts --grep "exports readiness exposes demo gate and retrieval actions"
# 1 passed

docker compose exec -T api pytest -q
# 92 passed

npm run typecheck --prefix apps/web
# passed

npx --prefix apps/web playwright test --config apps/web/playwright.config.ts
# 9 passed

python3 scripts/ralph_loop_gate.py --write-checkpoint --json
# PASS, 45 live checks

git diff --check
# clean
```

Current live checkpoint:

- `updates/ralph_loop_gate_checkpoint_20260429T155215_534500Z.json`
- `updates/ralph_loop_gate_checkpoint_latest.json`
- `updates/ralph_loop_gate_checkpoint_latest.md`

Next useful loop target:

- Add a task-side "review session position" strip for photo-context tasks opened from the session queue, so the reviewer knows which queue item they are editing, what comes next, and what completion signal they are trying to change.

## Continuation Update: Task-Side Review Session Position

This loop made the ordered photo-context review session durable at the task level.

What changed:

- Extended photo-context task creation with optional review-session provenance:
  - sequence number;
  - selected item count;
  - session plan hash;
  - completion signal;
  - review policy;
  - no-claim marker.
- The review-session endpoint now includes `review_session_origin` in dry-run and created/opened session items.
- Tasks created or opened from a session queue now store `review_session_origin` in `task.input_payload`.
- Existing photo-context tasks are updated with session/query provenance when reopened from the session queue.
- Added a `Review session position` strip inside photo-context tasks.
- The strip shows:
  - `1 / 5` style queue position;
  - retrieval query context;
  - session completion signal;
  - plan hash;
  - query-aware no-claim policy.
- Browser coverage now opens a task through the ordered session queue and verifies the task-side session position strip.

Verification:

```bash
docker compose exec -T api pytest -q tests/test_ralph_phase2_photo_spine.py::test_photo_context_review_session_dry_runs_then_creates_no_claim_context_tasks
# 1 passed

npm run typecheck --prefix apps/web
# passed

npx --prefix apps/web playwright test --config apps/web/playwright.config.ts --grep "retrieval no-claim action opens a photo context task with query provenance"
# 1 passed

docker compose exec -T api pytest -q
# 92 passed

npm run typecheck --prefix apps/web
# passed

npx --prefix apps/web playwright test --config apps/web/playwright.config.ts
# 9 passed

python3 scripts/ralph_loop_gate.py --write-checkpoint --json
# PASS, 45 live checks

git diff --check
# clean
```

Current live checkpoint:

- `updates/ralph_loop_gate_checkpoint_20260429T160409_703520Z.json`
- `updates/ralph_loop_gate_checkpoint_latest.json`
- `updates/ralph_loop_gate_checkpoint_latest.md`

Next useful loop target:

- Add a session-progress mini dashboard to the opened photo-context task, showing which review-session fields are now complete, which blockers remain, and whether submitting this task would move the session completion metric.

## Continuation Update: Task-Side Session Progress Impact

This loop added a live session-impact panel inside opened photo-context tasks.

What changed:

- Added a `Session progress impact` panel to photo-context tasks that came from a review session.
- The panel reads the live backend submit projection when available.
- It shows:
  - field completion count;
  - remaining projected blockers;
  - whether submit would move the session completion metric;
  - no-claim wording before submit.
- The panel falls back to retrieval review requirements while the backend projection is loading.
- Browser coverage now verifies that a task opened from the ordered session queue shows:
  - review session position;
  - session progress impact;
  - fields complete;
  - remaining blockers;
  - session completion metric.

Verification:

```bash
npm run typecheck --prefix apps/web
# passed

npx --prefix apps/web playwright test --config apps/web/playwright.config.ts --grep "retrieval no-claim action opens a photo context task with query provenance"
# 1 passed

docker compose exec -T api pytest -q
# 92 passed

npm run typecheck --prefix apps/web
# passed

npx --prefix apps/web playwright test --config apps/web/playwright.config.ts
# 9 passed

python3 scripts/ralph_loop_gate.py --write-checkpoint --json
# PASS, 45 live checks

git diff --check
# clean
```

Current live checkpoint:

- `updates/ralph_loop_gate_checkpoint_20260429T160918_483163Z.json`
- `updates/ralph_loop_gate_checkpoint_latest.json`
- `updates/ralph_loop_gate_checkpoint_latest.md`

Next useful loop target:

- Add a non-mutating "complete this session item" autofill assist for photo-context tasks, using only safe defaults for boundary/downstream controls while leaving Adam-authored meaning fields empty.

## Continuation Update: Session-Safe Defaults Assist

This loop added a conservative session assist for photo-context review tasks.

What changed:

- Added `Apply session-safe defaults` inside the task-side `Session progress impact` panel.
- The assist sets only operational review controls:
  - `privacy_level = family_private`;
  - `ready_for_downstream = yes`;
  - `gallery_eligibility = family_private`;
  - OCR status to `not_present` only if no OCR text exists.
- The assist explicitly does not fill or alter Adam-authored memory text:
  - reviewed visual description;
  - why it matters;
  - retrieval-query answers.
- Browser coverage now captures text-field values before using the assist, clicks it, confirms safe dropdowns changed, and confirms the Adam-authored fields are unchanged.

Verification:

```bash
npm run typecheck --prefix apps/web
# passed

npx --prefix apps/web playwright test --config apps/web/playwright.config.ts --grep "retrieval no-claim action opens a photo context task with query provenance"
# 1 passed

docker compose exec -T api pytest -q
# 92 passed

npm run typecheck --prefix apps/web
# passed

npx --prefix apps/web playwright test --config apps/web/playwright.config.ts
# 9 passed

python3 scripts/ralph_loop_gate.py --write-checkpoint --json
# PASS, 45 live checks

git diff --check
# clean
```

Current live checkpoint:

- `updates/ralph_loop_gate_checkpoint_20260429T161531_068789Z.json`
- `updates/ralph_loop_gate_checkpoint_latest.json`
- `updates/ralph_loop_gate_checkpoint_latest.md`

Next useful loop target:

- Add a photo-context "required Adam fields" focus drawer that groups the missing human-authored fields together, so session work feels like answering the few necessary questions rather than hunting through the full form.

## Continuation Update: Required Adam Fields Focus Drawer

This loop reduced task noise by grouping the human-authored fields in one visible checklist.

What changed:

- Added `Required Adam fields` drawer to photo-context review tasks.
- The drawer summarizes:
  - reviewed visual description;
  - connection to retrieval query;
  - why it matters;
  - invisible context;
  - open questions.
- Each item shows whether it is complete or still needs Adam.
- The drawer explicitly says `No generated memory text here`.
- It does not replace the editable fields; it gives the reviewer a compact map before they continue through the full form.
- Browser coverage now verifies the drawer and all grouped Adam-field labels inside the retrieval/session task flow.

Verification:

```bash
npm run typecheck --prefix apps/web
# passed

npx --prefix apps/web playwright test --config apps/web/playwright.config.ts --grep "retrieval no-claim action opens a photo context task with query provenance"
# 1 passed

docker compose exec -T api pytest -q
# 92 passed

npm run typecheck --prefix apps/web
# passed

npx --prefix apps/web playwright test --config apps/web/playwright.config.ts
# 9 passed

python3 scripts/ralph_loop_gate.py --write-checkpoint --json
# PASS, 45 live checks

git diff --check
# clean
```

Current live checkpoint:

- `updates/ralph_loop_gate_checkpoint_20260429T162115_538618Z.json`
- `updates/ralph_loop_gate_checkpoint_latest.json`
- `updates/ralph_loop_gate_checkpoint_latest.md`

Next useful loop target:

- Add a "copy review prompt" affordance for required Adam fields, producing a concise human-readable prompt Adam can answer outside the UI and paste back without including generated memory claims.

## Continuation Update: Copy Review Prompt Affordance

This loop made the required Adam-field drawer portable without converting it into generated memory content.

What changed:

- Added a `Copy review prompt` affordance inside the photo-context required Adam-fields drawer.
- The prompt preview includes the photo title, retrieval query when present, and the five required Adam-authored fields.
- The prompt explicitly instructs Adam to answer only from memory or direct observation.
- The prompt explicitly says it is not generated memory text.
- Browser coverage now verifies the prompt preview and no-invention language in the retrieval/session task flow.

Verification:

```bash
npm run typecheck --prefix apps/web
# passed

npx --prefix apps/web playwright test --config apps/web/playwright.config.ts --grep "retrieval no-claim action opens a photo context task with query provenance"
# 1 passed

docker compose exec -T api pytest -q
# 92 passed

npm run typecheck --prefix apps/web
# passed

npx --prefix apps/web playwright test --config apps/web/playwright.config.ts
# 9 passed

python3 scripts/ralph_loop_gate.py --write-checkpoint --json
# PASS, 45 live checks

git diff --check
# clean
```

Current live checkpoint:

- `updates/ralph_loop_gate_checkpoint_20260429T162803_421292Z.json`
- `updates/ralph_loop_gate_checkpoint_latest.json`
- `updates/ralph_loop_gate_checkpoint_latest.md`

Next useful loop target:

- Add a paste-back answer scratchpad/parser for the copied review prompt so Adam can bring answers back into the task without manually hunting for each field.

## Continuation Update: Paste-Back Adam Answer Parser

This loop closed the round trip between the copied Adam prompt and the photo-context review fields.

What changed:

- Added an `Adam answer paste parser` inside the required Adam-fields drawer.
- Added a canonical `Connection to retrieval query` field to the photo-context form when a retrieval query is present.
- The parser maps numbered Adam answers back into:
  - reviewed visual description;
  - connection to retrieval query;
  - why it matters;
  - invisible context;
  - open questions.
- The parser also fills any on-screen retrieval/query question ids, while preserving the canonical `retrieval_query_relevance` key.
- The submit preview now visibly advances to `Creates vector-safe memory record` once the required Adam fields and boundary defaults are present.
- Browser coverage verifies pasted answers populate the actual form fields and change the downstream payoff preview.

Verification:

```bash
npm run typecheck --prefix apps/web
# passed

npx --prefix apps/web playwright test --config apps/web/playwright.config.ts --grep "retrieval no-claim action opens a photo context task with query provenance"
# 1 passed

docker compose exec -T api pytest -q
# 92 passed

npm run typecheck --prefix apps/web
# passed

npx --prefix apps/web playwright test --config apps/web/playwright.config.ts
# 9 passed

python3 scripts/ralph_loop_gate.py --write-checkpoint --json
# PASS, 45 live checks

git diff --check
# clean
```

Current live checkpoint:

- `updates/ralph_loop_gate_checkpoint_20260429T164127_274865Z.json`
- `updates/ralph_loop_gate_checkpoint_latest.json`
- `updates/ralph_loop_gate_checkpoint_latest.md`

Next useful loop target:

- Add a session-level completed-item receipt after photo-context submit so Adam can see which review-session queue item just moved from no-claim gap toward vector-safe memory readiness.

## Continuation Update: Review Session Submit Receipt

This loop made photo-context submit receipts session-aware.

What changed:

- API task receipts now preserve `review_session_origin` from photo-context tasks.
- The task submit response exposes that session origin in `creates_or_updates.receipt`.
- The persisted `TaskReceipt.summary` keeps the same session-origin payload for later audit/dossier surfaces.
- The web submit receipt now shows a `Review session item` panel with:
  - session item position;
  - selected session count;
  - retrieval query;
  - plan hash preview;
  - a clear statement that the no-claim gap moved toward vector-safe memory readiness.
- Tests verify both backend receipt persistence and frontend receipt visibility.

Verification:

```bash
docker compose exec -T api pytest -q tests/test_ralph_phase2_photo_spine.py::test_photo_context_submit_receipt_carries_projection_hash_and_payload_preview
# 1 passed

npx --prefix apps/web playwright test --config apps/web/playwright.config.ts --grep "photo submit receipt exposes vector handoff without mutating the archive"
# 1 passed

docker compose exec -T api pytest -q
# 92 passed

npm run typecheck --prefix apps/web
# passed

npx --prefix apps/web playwright test --config apps/web/playwright.config.ts
# 9 passed

python3 scripts/ralph_loop_gate.py --write-checkpoint --json
# PASS, 45 live checks

git diff --check
# clean
```

Current live checkpoint:

- `updates/ralph_loop_gate_checkpoint_20260429T164918_682656Z.json`
- `updates/ralph_loop_gate_checkpoint_latest.json`
- `updates/ralph_loop_gate_checkpoint_latest.md`

Next useful loop target:

- Move to the current top bottleneck, prompt-pair candidates, and add a DPO rejected-reason focus aid so held DPO tickets explain exactly what Adam needs to write before they can move from candidate toward export readiness.

## Continuation Update: DPO Rejected-Reason Focus Aid

This loop added a focused aid for the current top prompt-pair blocker.

What changed:

- Added a `DPO rejected reason` focus panel when a DPO ticket has no rejected-side reason.
- The panel explains that Adam needs to add a Minor/Major issue note under the Rejected rubric.
- The panel explicitly says the note is comparison metadata, not a new memory claim.
- Added an `Apply review-note scaffold` action that creates a provisional rejected-side rubric note under Voice authenticity.
- The scaffold does not certify the item as authentic or export-ready; backend preflight can still hold the candidate for Adam gold edit and generated rejected-side review.
- Browser coverage verifies the empty-reason blocker disappears from mocked backend preflight after the scaffold creates a DPO reason.

Verification:

```bash
npm run typecheck --prefix apps/web
# passed

npx --prefix apps/web playwright test --config apps/web/playwright.config.ts --grep "DPO rejected reason focus aid applies a provisional rejected-side note"
# 1 passed

docker compose exec -T api pytest -q
# 92 passed

npm run typecheck --prefix apps/web
# passed

npx --prefix apps/web playwright test --config apps/web/playwright.config.ts
# 10 passed

python3 scripts/ralph_loop_gate.py --write-checkpoint --json
# PASS, 45 live checks

git diff --check
# clean
```

Current live checkpoint:

- `updates/ralph_loop_gate_checkpoint_20260429T165520_921146Z.json`
- `updates/ralph_loop_gate_checkpoint_latest.json`
- `updates/ralph_loop_gate_checkpoint_latest.md`

Next useful loop target:

- Make the DPO repair workflow more inspectable from the Prompt Pairs list by surfacing blocker-specific counts and an action label that distinguishes `dpo_rejected_reason_empty` from other held candidates.

## Continuation Update: Prompt-Pair Blocker Action Labels

This loop made the Prompt Pairs queue read more like actionable work and less like internal preflight state.

What changed:

- Added blocker-specific action labels in the Prompt Pairs readiness rail.
- `dpo_rejected_reason_empty` now surfaces as `Write rejected reason`.
- `source_boundary_blocks_training` now surfaces as `Review source boundary`.
- The first held-candidate action also uses the blocker-specific verb instead of a generic `Open held candidate` label.
- Browser coverage verifies the blocker count and the human-readable action label before opening the corresponding ticket.

Verification:

```bash
npm run typecheck --prefix apps/web
# passed

npx --prefix apps/web playwright test --config apps/web/playwright.config.ts --grep "prompt pairs can be filtered and searched as singleton tickets"
# 1 passed

docker compose exec -T api pytest -q
# 92 passed

npm run typecheck --prefix apps/web
# passed

npx --prefix apps/web playwright test --config apps/web/playwright.config.ts
# 10 passed

python3 scripts/ralph_loop_gate.py --write-checkpoint --json
# PASS, 45 live checks

git diff --check
# clean
```

Current live checkpoint:

- `updates/ralph_loop_gate_checkpoint_20260429T170102_091883Z.json`
- `updates/ralph_loop_gate_checkpoint_latest.json`
- `updates/ralph_loop_gate_checkpoint_latest.md`

Next useful loop target:

- Add a compact morning-status artifact for this long loop that summarizes the current bottleneck counts, latest checkpoint, and exact commands run, so the overnight work has a durable handoff beyond the raw phase report.

## Continuation Update: Morning Status Artifact

This loop created the compact handoff artifact for Adam's morning review:

- `updates/ralph_loop_2026-04-29_morning_status.md`

What it captures:

- Latest Ralph gate checkpoint and markdown paths.
- Current bottleneck order and action types.
- The live API morning-handoff markdown and content hash.
- Prompt-pair counts: `403` approved-ready, `30` candidate/held, `25` DPO rejected-reason gaps, `5` source-boundary blocks.
- Photo-context counts: `273` total photos, `82` preview-ready photos, `22` photo groups needing context, `71` photo assets needing context, `5` held draft groups.
- Retrieval gap status for `airplane in Maine`, including no-claim status and slice hash.
- Downstream artifact hash status.
- GPT-5.5 / xhigh text-generation gate status without making live model or fine-tuning calls.
- Safety notes confirming no raw source mutation and no fine-tuning API calls.

Verification:

```bash
python3 -m py_compile scripts/write_ralph_morning_status.py
# passed

python3 scripts/write_ralph_morning_status.py --output updates/ralph_loop_2026-04-29_morning_status.md
# wrote the handoff artifact

rg -n "open_held_prompt_pair_candidate|Preview-ready photos: 82|Photo groups needing context: 22|Live handoff content SHA-256|No fine-tuning APIs were called|Raw source files were not mutated" updates/ralph_loop_2026-04-29_morning_status.md
# all expected lines present

docker compose exec -T api pytest -q
# 92 passed

npm run typecheck --prefix apps/web
# passed

npx --prefix apps/web playwright test --config apps/web/playwright.config.ts
# 10 passed

python3 scripts/ralph_loop_gate.py --write-checkpoint --json
# PASS, 45 live checks

git diff --check
# clean
```

Current live checkpoint:

- `updates/ralph_loop_gate_checkpoint_20260429T170823_590536Z.json`
- `updates/ralph_loop_gate_checkpoint_latest.json`
- `updates/ralph_loop_gate_checkpoint_latest.md`

Next useful loop target:

- Make the generated morning handoff directly actionable in the web UI by exposing the `/api/downstream-readiness/morning-handoff` checklist in a compact operator panel, so Adam can open the next bottleneck from the same surface instead of reading only the markdown artifact.

## Continuation Update: Actionable Morning Handoff Panel

This loop made the morning handoff actionable in the web workbench, not just downloadable as YAML or readable as markdown.

What changed:

- The `Morning Handoff` panel now renders each operator checklist item as an action row.
- Prompt-pair, photo-context, and vector-handoff rows expose their own buttons.
- The demo-generation row remains visibly disabled as `Gated` while live GPT-5.5 credentials/live mode are unavailable.
- Each row keeps the completion signal and safety boundary visible beside the action.
- The handler opens an existing review task when the checklist has a task id, and can create/open a photo context review session for photo-context checklist work.

Verification:

```bash
npm run typecheck --prefix apps/web
# passed

npx --prefix apps/web playwright test --config apps/web/playwright.config.ts --grep "exports readiness exposes demo gate and retrieval actions"
# 1 passed

docker compose exec -T api pytest -q
# 92 passed

npm run typecheck --prefix apps/web
# passed

npx --prefix apps/web playwright test --config apps/web/playwright.config.ts
# 10 passed

python3 scripts/ralph_loop_gate.py --write-checkpoint --json
# PASS, 45 live checks

git diff --check
# clean
```

Current live checkpoint:

- `updates/ralph_loop_gate_checkpoint_20260429T171356_676449Z.json`
- `updates/ralph_loop_gate_checkpoint_latest.json`
- `updates/ralph_loop_gate_checkpoint_latest.md`

Next useful loop target:

- Tighten the generated morning-status file after each Ralph checkpoint so it references the newest checkpoint automatically, then continue with a small prompt-pair repair affordance that lets Adam act on the DPO rejected-reason queue from the top blocker slice without hunting through the task list.

## Continuation Update: Top Blocker Repair Affordance

This loop tightened the prompt-pair blocker repair path.

What changed:

- The top prompt-pair blocker slice now has an `Open top blocker` action.
- Each listed top-blocker candidate now has an `Open blocker repair` action.
- The browser test now verifies those controls from the top-blocker slice directly, not only from the separate DPO repair packet.
- The generated morning-status markdown was refreshed after the new checkpoint so it points at the latest gate.

Useful failure caught:

- The first focused Playwright pass failed on a broad text selector after the new `Open top blocker` button made "Top blocker" appear twice. I tightened those assertions to exact text matches, then reran the focused and full suites.

Verification:

```bash
npm run typecheck --prefix apps/web
# passed

npx --prefix apps/web playwright test --config apps/web/playwright.config.ts --grep "exports readiness exposes demo gate and retrieval actions"
# failed once on selector ambiguity, then passed after exact-match assertions

docker compose exec -T api pytest -q
# 92 passed

npm run typecheck --prefix apps/web
# passed

npx --prefix apps/web playwright test --config apps/web/playwright.config.ts
# 10 passed

python3 scripts/ralph_loop_gate.py --write-checkpoint --json
# PASS, 45 live checks

python3 scripts/write_ralph_morning_status.py --output updates/ralph_loop_2026-04-29_morning_status.md
# refreshed latest checkpoint reference

git diff --check
# clean
```

Current live checkpoint:

- `updates/ralph_loop_gate_checkpoint_20260429T171943_552162Z.json`
- `updates/ralph_loop_gate_checkpoint_latest.json`
- `updates/ralph_loop_gate_checkpoint_latest.md`

Next useful loop target:

- Add a small visual checkpoint for the operator surfaces by taking a browser screenshot of the Exports readiness view and storing it with the loop updates, then continue improving the photo-context review path where the largest live bottleneck after prompt pairs remains.

## Continuation Update: Visual Operator Checkpoint

This loop added a visual checkpoint for the Exports readiness operator surface.

Artifact:

- `updates/exports_readiness_operator_handoff_2026-04-29.png`

What it shows:

- The `Morning Handoff` operator checklist.
- Prompt-pair, photo-context, and vector-handoff rows with actionable buttons.
- Demo-generation row visibly blocked as `Gated`.
- The top-bottleneck action at the bottom of the handoff panel.

Notes:

- The first screenshot captured the top of the page rather than the handoff panel, so I scrolled to the operator checklist and recaptured it.
- The browser visible-screenshot API initially wrote JPEG bytes; I replaced it with a Playwright viewport screenshot so the `.png` extension matches the actual file content.
- `scripts/write_ralph_morning_status.py` now includes the visual checkpoint path when the screenshot exists.

Verification:

```bash
file updates/exports_readiness_operator_handoff_2026-04-29.png
# PNG image data, 550 x 473

python3 scripts/write_ralph_morning_status.py --output updates/ralph_loop_2026-04-29_morning_status.md
# refreshed visual checkpoint path

python3 -m py_compile scripts/write_ralph_morning_status.py
# passed

python3 - <<'PY'
from PIL import Image
img = Image.open('updates/exports_readiness_operator_handoff_2026-04-29.png')
assert img.format == 'PNG'
assert img.size == (550, 473)
print(f'{img.format} {img.size[0]}x{img.size[1]}')
PY
# PNG 550x473

git diff --check
# clean
```

Current live checkpoint remains:

- `updates/ralph_loop_gate_checkpoint_20260429T171943_552162Z.json`
- `updates/ralph_loop_gate_checkpoint_latest.json`
- `updates/ralph_loop_gate_checkpoint_latest.md`

Next useful loop target:

- Improve the photo-context review path by adding a more explicit "what changes if I complete this?" preview near the top of photo context tasks, because `22` groups / `71` photo assets still need Adam-authored context before they can become vector-safe memories.

## Continuation Update: Photo Context Completion Payoff

This loop made photo-context tasks explain their downstream payoff before the long annotation form.

What changed:

- Added a top-of-task `Photo context completion payoff` panel for photo-context review.
- The panel shows the current submit outcome, backend projection status, vector-handoff status, Adam-required field completion, retrieval query provenance, review-session position, and the remaining context fields.
- The panel repeats the important boundary rule in plain language: no memory claim is made until Adam submits context.
- The focused retrieval-gap browser test now requires this panel to prove the `airplane in Maine` query provenance, vector-handoff gate, Adam field count, and no-claim language.

Verification:

```bash
npm run typecheck --prefix apps/web
# passed

npx --prefix apps/web playwright test --config apps/web/playwright.config.ts -g "retrieval no-claim action opens a photo context task with query provenance"
# 1 passed

docker compose exec -T api pytest -q
# 92 passed

npx --prefix apps/web playwright test --config apps/web/playwright.config.ts
# 10 passed

python3 scripts/ralph_loop_gate.py --write-checkpoint --json
# PASS, 45 live checks

python3 scripts/write_ralph_morning_status.py --output updates/ralph_loop_2026-04-29_morning_status.md
# refreshed latest checkpoint reference

git diff --check
# clean
```

Current live checkpoint:

- `updates/ralph_loop_gate_checkpoint_20260429T173042_819510Z.json`
- `updates/ralph_loop_gate_checkpoint_latest.json`
- `updates/ralph_loop_gate_checkpoint_latest.md`

Next useful loop target:

- Reduce the remaining photo-context bottleneck by turning the top payoff preview into an even faster fill path: expose the missing Adam fields as a compact checklist with jump/focus actions and a visible "will this move the session metric?" state as fields are completed.

## Continuation Update: Photo Context Jump Checklist

This loop made the photo-context payoff preview actionable.

What changed:

- Added a compact jump checklist for Adam-required photo-context fields.
- Each checklist item focuses the corresponding review field without generating or filling memory content.
- Added an explicit session-metric status to the top payoff preview so the operator can see whether completing the item would move the review-session metric.
- Added field-focus hooks for reviewed visual description, retrieval-query relevance, why-it-matters, invisible context, and open questions.
- Strengthened the retrieval-gap browser test so it clicks the jump checklist, proves focus lands on the right fields, and waits for the top payoff panel to show `Would move session completion metric` once the required Adam fields and downstream boundary controls are complete.

Verification:

```bash
npm run typecheck --prefix apps/web
# passed

npx --prefix apps/web playwright test --config apps/web/playwright.config.ts -g "retrieval no-claim action opens a photo context task with query provenance"
# 1 passed

docker compose exec -T api pytest -q
# 92 passed

npx --prefix apps/web playwright test --config apps/web/playwright.config.ts
# 10 passed

python3 scripts/ralph_loop_gate.py --write-checkpoint --json
# PASS, 45 live checks

python3 scripts/write_ralph_morning_status.py --output updates/ralph_loop_2026-04-29_morning_status.md
# refreshed latest checkpoint reference

git diff --check
# clean
```

Current live checkpoint:

- `updates/ralph_loop_gate_checkpoint_20260429T173723_026464Z.json`
- `updates/ralph_loop_gate_checkpoint_latest.json`
- `updates/ralph_loop_gate_checkpoint_latest.md`

Next useful loop target:

- Improve prompt-pair repair throughput by making the DPO rejected-reason blocker worklist as direct as the photo-context jump checklist: show the top rejected-side issue gap, one-click scaffold, and exact YAML delta preview before submit.

## Continuation Update: Inline DPO Repair Projection

This loop brought the DPO rejected-reason repair packet into the Prompt Pair editor itself.

What changed:

- The DPO rejected-reason focus aid now loads the backend non-mutating repair projection for the current ticket.
- It shows the top rejected-side gap, before/after blocker state, whether `dpo_rejected_reason_empty` clears, and a content hash.
- It exposes the YAML diff preview inline before Submit.
- The scaffold button now applies the projected reason language, still as comparison metadata only.
- The browser test mocks and verifies the repair projection, expands the YAML delta, applies the scaffold, and proves the rejected-reason blocker disappears while `needs_adam_gold_edit` remains.

Verification:

```bash
npm run typecheck --prefix apps/web
# passed

npx --prefix apps/web playwright test --config apps/web/playwright.config.ts -g "DPO rejected reason focus aid applies a provisional rejected-side note"
# 1 passed

docker compose exec -T api pytest -q
# 92 passed

npx --prefix apps/web playwright test --config apps/web/playwright.config.ts
# 10 passed

python3 scripts/ralph_loop_gate.py --write-checkpoint --json
# PASS, 45 live checks

python3 scripts/write_ralph_morning_status.py --output updates/ralph_loop_2026-04-29_morning_status.md
# refreshed latest checkpoint reference

git diff --check
# clean
```

Current live checkpoint:

- `updates/ralph_loop_gate_checkpoint_20260429T174459_918443Z.json`
- `updates/ralph_loop_gate_checkpoint_latest.json`
- `updates/ralph_loop_gate_checkpoint_latest.md`

Next useful loop target:

- Add a lightweight export-readiness delta line to Prompt Pair tickets so the queue itself shows whether opening a ticket will likely clear `dpo_rejected_reason_empty`, `source_boundary_blocks_training`, or only leave `needs_adam_gold_edit`.

## Continuation Update: Prompt Pair Queue Delta

This loop added blocker-specific readiness hints directly on Prompt Pair queue rows.

What changed:

- Prompt Pair rows now show a compact `Prompt pair readiness delta` line.
- DPO rows missing rejected-side reasons say they will likely clear `Dpo Rejected Reason Empty` while leaving Adam gold review.
- Photo-grounded/source-boundary blocked rows say the source boundary blocks training export.
- Candidate rows that only need Adam confirmation say they remain candidate-only until Adam confirms gold.
- Approved-looking rows show a conservative local approved-ready signal while still deferring final authority to backend preflight inside the editor.

Verification:

```bash
npm run typecheck --prefix apps/web
# passed

npx --prefix apps/web playwright test --config apps/web/playwright.config.ts -g "prompt pairs can be filtered and searched as singleton tickets"
# 1 passed

docker compose exec -T api pytest -q
# 92 passed

npx --prefix apps/web playwright test --config apps/web/playwright.config.ts
# 10 passed

python3 scripts/ralph_loop_gate.py --write-checkpoint --json
# PASS, 45 live checks

python3 scripts/write_ralph_morning_status.py --output updates/ralph_loop_2026-04-29_morning_status.md
# refreshed latest checkpoint reference

git diff --check
# clean
```

Current live checkpoint:

- `updates/ralph_loop_gate_checkpoint_20260429T175114_360286Z.json`
- `updates/ralph_loop_gate_checkpoint_latest.json`
- `updates/ralph_loop_gate_checkpoint_latest.md`

Next useful loop target:

- Make photo-context queue rows equally explicit by showing whether a photo task is a retrieval-gap item, fastest vector candidate, or context-only backlog item, plus the exact field that must be supplied next.

## Continuation Update: Photo Queue Delta

This loop made the Photo Review queue explain the practical next step before the operator opens a photo task.

What changed:

- Photo queue rows now show a compact `Photo readiness delta` line.
- Retrieval-gap rows identify themselves as a no-claim query path and show the next Adam-authored context field needed.
- Fast vector candidates identify themselves as the quickest path toward a vector-safe memory record.
- Context-only backlog rows explain that submitting reviewed context can create a vector-safe memory while preserving archive/source boundaries.
- The row copy stays conservative: it describes projected review payoff, not a certified memory claim.

Verification:

```bash
npm run typecheck --prefix apps/web
# passed

npx --prefix apps/web playwright test --config apps/web/playwright.config.ts -g "photo review exposes image preview and downstream memory text preview"
# 1 passed

docker compose exec -T api pytest -q
# 92 passed

npx --prefix apps/web playwright test --config apps/web/playwright.config.ts
# 10 passed

python3 scripts/ralph_loop_gate.py --write-checkpoint --json
# PASS, 45 live checks

python3 scripts/write_ralph_morning_status.py --output updates/ralph_loop_2026-04-29_morning_status.md
# refreshed latest checkpoint reference

git diff --check
# clean
```

Current live checkpoint:

- `updates/ralph_loop_gate_checkpoint_20260429T175859_616753Z.json`
- `updates/ralph_loop_gate_checkpoint_latest.json`
- `updates/ralph_loop_gate_checkpoint_latest.md`

Next useful loop target:

- Add the same kind of pre-submit delta to Source Review so `Generate Pairs` previews how many singleton prompt-pair tickets will be created, whether annotated spans will be used, and what will block generation before the operator clicks.

## Continuation Update: Source Review Generate Pairs Preview

This loop made `Generate Pairs` predictable before the operator clicks.

What changed:

- Added a non-mutating backend dry-run endpoint at `/api/tasks/{task_id}/pair-generation/preview`.
- The dry run uses the same deterministic pair-generation rules as submit for structured YAML, structured chunks, highlighted Prompt/Response spans, natural sections, and fallback source text.
- Source Review rows now show a `Source review generation delta` hint before the task is opened.
- The Source Review workbench now shows a `Generate Pairs preview` panel with projected ticket count, held count, source sections, span count, strategy, next queue, first-ticket preview, and safety boundaries.
- The preview explicitly says it creates no prompt specs, generations, context packs, annotations, or tasks; submit still creates candidate Prompt Pair tickets requiring Adam gold review.

Verification:

```bash
docker compose exec -T api pytest -q tests/test_ralph_phase1_training_spine.py::test_source_review_pair_generation_preview_is_non_mutating_and_matches_natural_sections
# 1 passed

npm run typecheck --prefix apps/web
# passed

npx --prefix apps/web playwright test --config apps/web/playwright.config.ts -g "source review previews Generate Pairs ticket creation before submit"
# 1 passed

docker compose exec -T api pytest -q
# 93 passed

npx --prefix apps/web playwright test --config apps/web/playwright.config.ts
# 11 passed

python3 scripts/ralph_loop_gate.py --write-checkpoint --json
# PASS, 45 live checks

python3 scripts/write_ralph_morning_status.py --output updates/ralph_loop_2026-04-29_morning_status.md
# refreshed latest checkpoint reference

git diff --check
# clean
```

Current live checkpoint:

- `updates/ralph_loop_gate_checkpoint_20260429T181006_371235Z.json`
- `updates/ralph_loop_gate_checkpoint_latest.json`
- `updates/ralph_loop_gate_checkpoint_latest.md`

Next useful loop target:

- Add Source Review preview artifacts to the downstream manifest/runtime contract so the preview is not only visible in the workbench but also auditable as a durable API artifact with required fields and hashable output.

## Continuation Update: Source Review Preview Contract

This loop promoted the Source Review `Generate Pairs` dry-run from a UI convenience into a machine-verifiable contract artifact.

What changed:

- Added `/api/tasks/{task_id}/pair-generation/preview` to the runtime contract with required non-mutating, no-live-model, count, strategy, safety, and hash fields.
- Added a Ralph gate check that opens a live source-review task, posts the dry-run payload, verifies the required contract fields, and confirms the task set did not change.
- Added `source_review_pair_generation_preview_json` to the downstream artifact manifest and hash audit.
- The artifact manifest now reports 16 inspectable artifacts when the operator handoff itself is included.
- The live morning handoff reports 15 artifacts because it excludes the handoff artifact from its nested artifact summary.

Verification:

```bash
docker compose exec -T api pytest -q tests/test_ralph_phase1_training_spine.py::test_source_review_pair_generation_preview_is_non_mutating_and_matches_natural_sections tests/test_ralph_phase3_prompt_pair_audit.py::test_runtime_contract_includes_source_review_pair_generation_preview_fields tests/test_ralph_phase3_prompt_pair_audit.py::test_downstream_artifact_manifest_lists_hashable_outputs_without_side_effects tests/test_ralph_phase3_prompt_pair_audit.py::test_downstream_artifact_audit_recomputes_manifest_hashes
# 4 passed

npm run typecheck --prefix apps/web
# passed

npx --prefix apps/web playwright test --config apps/web/playwright.config.ts -g "exports readiness exposes demo gate and retrieval actions"
# 1 passed

docker compose exec -T api pytest -q
# 94 passed

npx --prefix apps/web playwright test --config apps/web/playwright.config.ts
# 11 passed

python3 scripts/ralph_loop_gate.py --write-checkpoint --json
# PASS, 46 live checks

python3 scripts/write_ralph_morning_status.py --output updates/ralph_loop_2026-04-29_morning_status.md
# refreshed latest checkpoint reference

git diff --check
# clean
```

Current live checkpoint:

- `updates/ralph_loop_gate_checkpoint_20260429T181832_625012Z.json`
- `updates/ralph_loop_gate_checkpoint_latest.json`
- `updates/ralph_loop_gate_checkpoint_latest.md`

Next useful loop target:

- Improve the photo context workflow by adding a searchable/photo-grid review queue inside the workbench, so Adam can scan the 82 preview-ready photos visually and choose which photo memory to annotate next instead of relying only on task rows.

## Continuation Update: Photo Contact Sheet

This loop added a visual scan layer to the photo review queue without changing the archive or pretending a thumbnail is a memory.

What changed:

- Added a `Photo contact sheet` region to Review > Photos, showing preview-ready mirrored photo thumbnails above the task list.
- Kept the copy explicit: visual scan only, imported mirrored copies, and no memory claim until Adam-authored review.
- Connected tiles with ready photo tasks to the existing review task opener while leaving tiles without tasks disabled.
- Added browser assertions for the contact sheet copy, thumbnail rendering, and thumbnail preview endpoint contract.
- Tightened the tile accessibility labels so the contact sheet region remains uniquely addressable.

Verification:

```bash
npm run typecheck --prefix apps/web
# passed

npx --prefix apps/web playwright test --config apps/web/playwright.config.ts -g "photo review exposes image preview and downstream memory text preview"
# 1 passed

docker compose exec -T api pytest -q
# 94 passed

npx --prefix apps/web playwright test --config apps/web/playwright.config.ts
# 11 passed

python3 scripts/ralph_loop_gate.py --write-checkpoint --json
# PASS, 46 live checks

python3 scripts/write_ralph_morning_status.py --output updates/ralph_loop_2026-04-29_morning_status.md
# refreshed latest checkpoint reference

git diff --check
# clean
```

Current live checkpoint:

- `updates/ralph_loop_gate_checkpoint_20260429T182704_278194Z.json`
- `updates/ralph_loop_gate_checkpoint_latest.json`
- `updates/ralph_loop_gate_checkpoint_latest.md`

Next useful loop target:

- Use the contact sheet as a springboard for a stricter photo review objective: selecting a photo should expose the exact context fields, completion blockers, and downstream vector/search consequence in one compact operator surface.

## Continuation Update: Grouped Photo Contact Sheet

This loop reduced noise in the photo review queue by grouping duplicate/copy variants into canonical contact-sheet tiles.

What changed:

- Ported the backend photo grouping heuristics into the workbench contact sheet: copy suffixes, numbered variants, and duplicate filenames collapse into a shared group key.
- The contact sheet now reports photo groups and preview-ready photo totals separately.
- Each group uses a canonical thumbnail while preserving variant counts.
- Tiles still open existing review tasks when available and stay disabled when no ready task exists.
- The UI copy now explicitly says duplicate variants are grouped and that all displayed media are imported mirrored copies.

Verification:

```bash
npm run typecheck --prefix apps/web
# passed

npx --prefix apps/web playwright test --config apps/web/playwright.config.ts -g "photo review exposes image preview and downstream memory text preview"
# 1 passed

docker compose exec -T api pytest -q
# 94 passed

npx --prefix apps/web playwright test --config apps/web/playwright.config.ts
# 11 passed

python3 scripts/ralph_loop_gate.py --write-checkpoint --json
# PASS, 46 live checks

python3 scripts/write_ralph_morning_status.py --output updates/ralph_loop_2026-04-29_morning_status.md
# refreshed latest checkpoint reference

git diff --check
# clean
```

Current live checkpoint:

- `updates/ralph_loop_gate_checkpoint_20260429T183239_377851Z.json`
- `updates/ralph_loop_gate_checkpoint_latest.json`
- `updates/ralph_loop_gate_checkpoint_latest.md`

Next useful loop target:

- Shift back to the top downstream bottleneck: prompt-pair candidates. The app should make the held DPO/source-boundary blockers easier to work down one ticket at a time without confusing candidate material with approved training rows.

## Continuation Update: Prompt-Pair Candidate Workdown

This loop made held prompt-pair tickets more actionable without promoting candidate material into approved training export.

What changed:

- Added a `Prompt pair candidate workdown` panel to held prompt-pair tickets.
- The panel converts backend preflight blockers into concrete next actions, including DPO rejected-reason notes, Adam gold confirmation, source boundary review, and privacy/boundary clearance.
- The panel repeats the safety contract: Submit saves candidate review progress and does not create an approved SFT/DPO row until backend blockers clear.
- The DPO repair browser test now verifies the blocker count drops from two blockers to one blocker after applying the projected rejected-side scaffold.
- Stabilized prompt-pair tests so they select the intended DPO ticket directly instead of depending on queue order.

Verification:

```bash
npm run typecheck --prefix apps/web
# passed

npx --prefix apps/web playwright test --config apps/web/playwright.config.ts -g "prompt pair ticket explains|DPO rejected reason"
# 2 passed

docker compose exec -T api pytest -q
# 94 passed

npx --prefix apps/web playwright test --config apps/web/playwright.config.ts
# 11 passed

python3 scripts/ralph_loop_gate.py --write-checkpoint --json
# PASS, 46 live checks

python3 scripts/write_ralph_morning_status.py --output updates/ralph_loop_2026-04-29_morning_status.md
# refreshed latest checkpoint reference

git diff --check
# clean
```

Current live checkpoint:

- `updates/ralph_loop_gate_checkpoint_20260429T184006_724568Z.json`
- `updates/ralph_loop_gate_checkpoint_latest.json`
- `updates/ralph_loop_gate_checkpoint_latest.md`

Next useful loop target:

- Add a machine-checkable way to prove prompt-pair candidates are getting closer to approval across a review session, not just easier to inspect one by one.

## Continuation Update: Prompt-Pair Review Progress Proof

This loop added a hashable, non-mutating progress endpoint for prompt-pair review so the operator can prove review movement at the session level.

What changed:

- Added `/api/prompt-pairs/review-progress`.
- Added the endpoint to the runtime contract.
- The response reports approved count, candidate count, blocker counts, top blocker, next action, completion signal, and a content hash.
- The Prompt Pairs sidebar now shows a `Review progress proof` card with candidate/approved counts, top blocker, completion signal, and a short hash.
- Browser coverage verifies the progress proof matches `/api/prompt-pairs/audit` counts and exposes the hash in the UI.
- API coverage verifies the endpoint is read-only, does not promote candidates to training export, and reports the actual top blocker from backend preflight.

Verification:

```bash
docker compose exec -T api pytest -q tests/test_ralph_phase3_prompt_pair_audit.py::test_prompt_pair_top_blocker_slice_exposes_reviewable_yaml_previews
# 1 passed

npm run typecheck --prefix apps/web
# passed

npx --prefix apps/web playwright test --config apps/web/playwright.config.ts -g "prompt pairs can be filtered"
# 1 passed

docker compose exec -T api pytest -q
# 94 passed

npx --prefix apps/web playwright test --config apps/web/playwright.config.ts
# 11 passed

python3 scripts/ralph_loop_gate.py --write-checkpoint --json
# PASS, 46 live checks

python3 scripts/write_ralph_morning_status.py --output updates/ralph_loop_2026-04-29_morning_status.md
# refreshed latest checkpoint reference

git diff --check
# clean
```

Current live checkpoint:

- `updates/ralph_loop_gate_checkpoint_20260429T184737_960280Z.json`
- `updates/ralph_loop_gate_checkpoint_latest.json`
- `updates/ralph_loop_gate_checkpoint_latest.md`

Next useful loop target:

- Extend the live Ralph gate to check `/api/prompt-pairs/review-progress` directly, so the endpoint is not only unit/browser-tested but also part of the overnight contract gate.

## Continuation Update: Ralph Gate Prompt-Pair Progress Check

This loop moved the prompt-pair review progress proof into the live Ralph gate itself.

What changed:

- Added a gate check named `Prompt-pair review progress is machine-checkable`.
- The gate now verifies `/api/prompt-pairs/review-progress` against `/api/prompt-pairs/audit`.
- It confirms candidate counts, approved counts, blocker counts, top blocker, completion signal, and the 64-character content hash.
- It also checks the endpoint is explicitly non-mutating, does not promote candidates into training export, and requires Adam gold edit review.
- The check compares task ids before and after the request so a passing gate proves the endpoint is a read-only progress projection.

Verification:

```bash
python3 -m py_compile scripts/ralph_loop_gate.py
# passed

python3 scripts/ralph_loop_gate.py --write-checkpoint --json
# PASS, 47 live checks

python3 scripts/write_ralph_morning_status.py --output updates/ralph_loop_2026-04-29_morning_status.md
# refreshed latest checkpoint reference

git diff --check
# clean
```

Current live checkpoint:

- `updates/ralph_loop_gate_checkpoint_20260429T185254_477884Z.json`
- `updates/ralph_loop_gate_checkpoint_latest.json`
- `updates/ralph_loop_gate_checkpoint_latest.md`

Next useful loop target:

- Add prompt-pair review progress to the downstream artifact manifest and hash audit so it becomes one of the named export/readiness artifacts, not only an API/UI/gate proof.

## Continuation Update: Prompt-Pair Progress Artifact

This loop promoted prompt-pair review progress into the downstream artifact manifest and hash audit.

What changed:

- Added `prompt_pair_review_progress_json` to `/api/downstream-readiness/artifact-manifest`.
- The artifact is review-only, not training-eligible, and points to `/api/prompt-pairs/review-progress`.
- Its policy snapshot preserves the read-only progress projection, candidate-only status, Adam gold edit requirement, top blocker, completion signal, and domain progress hash.
- `/api/downstream-readiness/artifact-audit` now recomputes the progress JSON body hash alongside the other manifest artifacts.
- The browser readiness test now derives the audit count from the API instead of hard-coding the previous count.
- The live gate now requires the progress artifact and its hash-audit check.

Verification:

```bash
docker compose exec -T api pytest -q tests/test_ralph_phase3_prompt_pair_audit.py::test_downstream_artifact_manifest_lists_hashable_outputs_without_side_effects tests/test_ralph_phase3_prompt_pair_audit.py::test_downstream_artifact_audit_recomputes_manifest_hashes
# 2 passed

npx --prefix apps/web playwright test --config apps/web/playwright.config.ts -g "exports readiness exposes demo gate"
# 1 passed

docker compose exec -T api pytest -q
# 94 passed

npm run typecheck --prefix apps/web
# passed

npx --prefix apps/web playwright test --config apps/web/playwright.config.ts
# 11 passed

python3 scripts/ralph_loop_gate.py --write-checkpoint --json
# PASS, 47 live checks

python3 scripts/write_ralph_morning_status.py --output updates/ralph_loop_2026-04-29_morning_status.md
# refreshed latest checkpoint reference

git diff --check
# clean
```

Current live checkpoint:

- `updates/ralph_loop_gate_checkpoint_20260429T190117_489760Z.json`
- `updates/ralph_loop_gate_checkpoint_latest.json`
- `updates/ralph_loop_gate_checkpoint_latest.md`

Next useful loop target:

- Create a review-session style workflow for the top prompt-pair blocker, similar to the photo context session plan, so repeated DPO rejected-reason issues can be batched into concrete ticket work without promoting anything to approved export.

## Continuation Update: Prompt-Pair Top-Blocker Session Plan

This loop added a non-mutating batch session plan for the top prompt-pair blocker.

What changed:

- Added `/api/prompt-pairs/top-blocker-review-session-plan`.
- Added `/api/prompt-pairs/top-blocker-review-session-plan/yaml`.
- Added the endpoint to the runtime contract.
- The plan selects the top blocker batch, exposes field prompts, selected ticket ids, completion criteria, projected task delta, content hash, and YAML export preview hash.
- The projected task delta explicitly proves the plan opens existing prompt-pair tickets only: no raw source mutation, no task creation, no approved export creation.
- The Exports UI now shows a `Prompt Pair Blocker Session` panel with selected count, completion signal, field prompts, selected items, and open-ticket actions.
- The live Ralph gate now checks the endpoint contract, non-mutation, no export promotion, field prompts, selected items, YAML hash, and task-set stability.

Verification:

```bash
docker compose exec -T api pytest -q tests/test_ralph_phase3_prompt_pair_audit.py::test_prompt_pair_top_blocker_slice_exposes_reviewable_yaml_previews
# 1 passed

npm run typecheck --prefix apps/web
# passed

npx --prefix apps/web playwright test --config apps/web/playwright.config.ts -g "exports readiness exposes demo gate"
# 1 passed

docker compose exec -T api pytest -q
# 94 passed

npx --prefix apps/web playwright test --config apps/web/playwright.config.ts
# 11 passed

python3 scripts/ralph_loop_gate.py --write-checkpoint --json
# PASS, 48 live checks

python3 scripts/write_ralph_morning_status.py --output updates/ralph_loop_2026-04-29_morning_status.md
# refreshed latest checkpoint reference

git diff --check
# clean
```

Current live checkpoint:

- `updates/ralph_loop_gate_checkpoint_20260429T191223_105731Z.json`
- `updates/ralph_loop_gate_checkpoint_latest.json`
- `updates/ralph_loop_gate_checkpoint_latest.md`

Next useful loop target:

- Promote the prompt-pair blocker session plan into the downstream artifact manifest and hash audit, so batch review plans become named export/readiness artifacts just like the photo context session plans.

## Continuation Update: Prompt-Pair Session Plan Artifact

This loop promoted the prompt-pair top-blocker session plan into the downstream artifact manifest and hash audit.

What changed:

- Added `prompt_pair_top_blocker_session_plan_yaml` to `/api/downstream-readiness/artifact-manifest`.
- The artifact downloads from `/api/prompt-pairs/top-blocker-review-session-plan/yaml?limit=5`.
- Its manifest policy records no state mutation, no training export promotion, Adam gold edit requirement, blocker, selected count, candidate count, domain plan hash, completion signal, and projected task delta.
- `/api/downstream-readiness/artifact-audit` now recomputes the YAML body hash for the session plan.
- The Exports UI artifact table and hash audit details now show the prompt-pair top-blocker session plan artifact.
- The live gate now requires the artifact and validates its policy/hash through the existing manifest/audit checks.

Verification:

```bash
docker compose exec -T api pytest -q tests/test_ralph_phase3_prompt_pair_audit.py::test_downstream_artifact_manifest_lists_hashable_outputs_without_side_effects tests/test_ralph_phase3_prompt_pair_audit.py::test_downstream_artifact_audit_recomputes_manifest_hashes
# 2 passed

npx --prefix apps/web playwright test --config apps/web/playwright.config.ts -g "exports readiness exposes demo gate"
# 1 passed

docker compose exec -T api pytest -q
# 94 passed

npm run typecheck --prefix apps/web
# passed

npx --prefix apps/web playwright test --config apps/web/playwright.config.ts
# 11 passed

python3 scripts/ralph_loop_gate.py --write-checkpoint --json
# PASS, 48 live checks

python3 scripts/write_ralph_morning_status.py --output updates/ralph_loop_2026-04-29_morning_status.md
# refreshed latest checkpoint reference

git diff --check
# clean
```

Current live checkpoint:

- `updates/ralph_loop_gate_checkpoint_20260429T191809_331829Z.json`
- `updates/ralph_loop_gate_checkpoint_latest.json`
- `updates/ralph_loop_gate_checkpoint_latest.md`

Next useful loop target:

- Add an analogous review-progress/session proof for photo context work, so the overnight handoff can show whether photo memory/vector readiness is moving or merely being inspected.

## Continuation Update: Photo Context Progress Proof

This loop made photo-context review progress machine-checkable in the same spirit as prompt-pair progress.

What changed:

- Added `/api/assets/photo-context-review-pack/session-progress` to the runtime contract.
- Strengthened the photo progress payload with explicit proof fields: no state mutation, no memory claim creation, no embedding record creation, Adam-context requirement, completion signal, safety boundaries, and a stable content hash.
- The Exports UI now shows a `Progress proof` row in the Photo Context Review Pack card with the completion signal and hash.
- The live Ralph gate now requires the proof flags, completion signal, safety boundaries, content hash, and runtime-contract fields.
- The browser smoke now asserts that the proof is visible to the operator.

Verification:

```bash
docker compose exec -T api pytest -q tests/test_ralph_phase2_photo_spine.py
# 25 passed

npm run typecheck --prefix apps/web
# passed

npx --prefix apps/web playwright test --config apps/web/playwright.config.ts apps/web/tests/readiness-smoke.spec.ts
# 11 passed

docker compose exec -T api pytest -q
# 94 passed

python3 scripts/ralph_loop_gate.py --write-checkpoint --json
# PASS, 48 live checks

python3 scripts/write_ralph_morning_status.py --output updates/ralph_loop_2026-04-29_morning_status.md
# refreshed latest checkpoint reference

git diff --check
# clean
```

Current live checkpoint:

- `updates/ralph_loop_gate_checkpoint_20260429T192957_608395Z.json`
- `updates/ralph_loop_gate_checkpoint_latest.json`
- `updates/ralph_loop_gate_checkpoint_latest.md`

Next useful loop target:

- Promote photo context session progress into the downstream artifact manifest and hash audit, so photo review progress has a named, downloadable proof artifact just like prompt-pair review progress.

## Continuation Update: Photo Progress Artifact

This loop promoted photo-context session progress into a first-class downstream artifact.

What changed:

- Added a stable `/api/assets/photo-context-review-pack/session-progress/artifact` endpoint.
- The artifact omits volatile projection internals while preserving task status, blockers, retrieval-gap fields, proof flags, safety boundaries, and the source progress hash.
- Added `photo_context_session_progress_json` to `/api/downstream-readiness/artifact-manifest`.
- `/api/downstream-readiness/artifact-audit` now recomputes the photo progress artifact hash and includes it in the checked artifact list.
- The Exports UI now shows a `Photo progress proof` download tile with a `Progress JSON` link.
- The browser smoke asserts the tile, link, and artifact hash audit row.
- The live gate requires the photo progress artifact family, JSON format, no-mutation/no-memory/no-embedding policy, Adam-context requirement, completion signal, domain progress hash, and audit hash match.

Verification:

```bash
docker compose exec -T api pytest -q tests/test_ralph_phase3_prompt_pair_audit.py::test_downstream_artifact_manifest_lists_hashable_outputs_without_side_effects tests/test_ralph_phase3_prompt_pair_audit.py::test_downstream_artifact_audit_recomputes_manifest_hashes
# 2 passed

npm run typecheck --prefix apps/web
# passed

npx --prefix apps/web playwright test --config apps/web/playwright.config.ts -g "exports readiness exposes demo gate"
# 1 passed

docker compose exec -T api pytest -q
# 94 passed

npx --prefix apps/web playwright test --config apps/web/playwright.config.ts
# 11 passed

python3 scripts/ralph_loop_gate.py --write-checkpoint --json
# PASS, 48 live checks

python3 scripts/write_ralph_morning_status.py --output updates/ralph_loop_2026-04-29_morning_status.md
# refreshed latest checkpoint reference

git diff --check
# clean
```

Current live checkpoint:

- `updates/ralph_loop_gate_checkpoint_20260429T194156_947542Z.json`
- `updates/ralph_loop_gate_checkpoint_latest.json`
- `updates/ralph_loop_gate_checkpoint_latest.md`

Next useful loop target:

- Add a compact “operator acceptance tests” section to the Exports UI that reads directly from the latest gate/checkpoint concepts, so the app itself explains which strict checks define done for prompt pairs, photo context, vectors, artifacts, and demo generation.

## Continuation Update: Operator Acceptance Tests UI

This loop made the strict acceptance criteria visible inside the Exports surface instead of leaving them only in external test output.

What changed:

- Added an `Operator Acceptance Tests` card below Morning Handoff.
- The card surfaces the existing operator checklist completion signals for prompt pairs, photo context, vector handoff, and demo generation.
- Added explicit acceptance rows for artifact hash audit and photo progress proof.
- The photo progress proof row repeats the no-memory-claim/no-embedding boundary alongside its completion signal.
- Browser smoke now asserts the card, prompt-pair completion signal, photo-context completion signal, artifact hash status, and photo progress proof boundary.

Verification:

```bash
npm run typecheck --prefix apps/web
# passed

npx --prefix apps/web playwright test --config apps/web/playwright.config.ts -g "exports readiness exposes demo gate"
# 1 passed

npx --prefix apps/web playwright test --config apps/web/playwright.config.ts
# 11 passed

python3 scripts/ralph_loop_gate.py --write-checkpoint --json
# PASS, 48 live checks

python3 scripts/write_ralph_morning_status.py --output updates/ralph_loop_2026-04-29_morning_status.md
# refreshed latest checkpoint reference

docker compose exec -T api pytest -q
# 94 passed

git diff --check
# clean
```

Current live checkpoint:

- `updates/ralph_loop_gate_checkpoint_20260429T194639_776567Z.json`
- `updates/ralph_loop_gate_checkpoint_latest.json`
- `updates/ralph_loop_gate_checkpoint_latest.md`

Next useful loop target:

- Add a compact review-session progress summary to the Prompt Pairs screen itself, so the operator can see top blocker, candidate count, and acceptance signal while working tickets rather than only in Exports.

## Continuation Update: Photo Progress Proof In Review Queue

The Prompt Pairs review-session proof was already present and tested in the workbench, so this loop moved the same acceptance idea into the Review > Photos path where Adam is actually annotating photo context.

What changed:

- Review > Photos now loads `/api/assets/photo-context-review-pack/session-progress`.
- The Photo priority panel shows a `Photo context progress proof` card with submit-ready count, draft count, blocked count, retrieval-gap count, top missing retrieval field, completion signal, safety boundary flags, and content hash.
- The smoke test now compares the UI card against the live API payload, including the no-memory-claim/no-embedding guarantees and hash prefix.

Verification:

```bash
npm run typecheck --prefix apps/web
# passed

npx --prefix apps/web playwright test --config apps/web/playwright.config.ts -g "photo review exposes image preview"
# 1 passed

npx --prefix apps/web playwright test --config apps/web/playwright.config.ts
# 11 passed

docker compose exec -T api pytest -q
# 94 passed

python3 scripts/ralph_loop_gate.py --write-checkpoint --json
# PASS, live checkpoint written

python3 scripts/write_ralph_morning_status.py --output updates/ralph_loop_2026-04-29_morning_status.md
# refreshed latest checkpoint reference

git diff --check
# clean
```

Current live checkpoint:

- `updates/ralph_loop_gate_checkpoint_20260429T195534_426776Z.json`
- `updates/ralph_loop_gate_checkpoint_latest.json`
- `updates/ralph_loop_gate_checkpoint_latest.md`

Next useful loop target:

- Make reviewed photo memories first-class context-pack inputs. The current context-pack asset fact path can degrade a reviewed photo to title/filename-only context; this weakens Objective 6 because retrieval/memory context should carry Adam-reviewed photo description and meaning when boundary-cleared.

## Continuation Update: Reviewed Photo Context Packs

This loop strengthened the downstream context-pack path for photos. A boundary-cleared reviewed photo asset no longer degrades to a filename-only context fact when included in a context pack.

What changed:

- `context_packs._item_fact()` now recognizes photo assets.
- Reviewed photo context facts include reviewed visual description, Adam context, truth status, reviewer, date, people, places, themes, concrete objects, open questions, and linked reviewed memories.
- System-inference and model-generated photo drafts are excluded from this reviewed-photo context fact path.
- Existing asset boundary checks still run first, so sealed or redaction-required photo assets do not contribute facts.
- Added a strict test proving:
  - reviewed photo profile text is included;
  - linked reviewed memory text is included;
  - truth/provenance labels are included;
  - machine-draft/system-inference text is excluded;
  - sealed photo context is excluded.

Verification:

```bash
docker compose exec -T api pytest -q tests/test_context_packs.py
# 2 passed

docker compose exec -T api pytest -q
# 95 passed

npm run typecheck --prefix apps/web
# passed

python3 scripts/ralph_loop_gate.py --write-checkpoint --json
# PASS, live checkpoint written

python3 scripts/write_ralph_morning_status.py --output updates/ralph_loop_2026-04-29_morning_status.md
# refreshed latest checkpoint reference

git diff --check
# clean
```

Current live checkpoint:

- `updates/ralph_loop_gate_checkpoint_20260429T200110_593145Z.json`
- `updates/ralph_loop_gate_checkpoint_latest.json`
- `updates/ralph_loop_gate_checkpoint_latest.md`

Next useful loop target:

- Make the reviewed-photo context-pack behavior visible as an artifact or audit check, so the Ralph gate can prove photo-memory context packs are downstream-ready rather than relying only on the unit test.
