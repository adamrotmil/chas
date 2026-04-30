# Ralph Loop Phase Report - 2026-04-30 Photo Prompt Pair Batch UX

## Loop Goal

Make the reviewed-photo to prompt-pair workflow easier to understand after submit:

- photo reviews should generate or reopen review-gated prompt-pair candidates,
- existing candidates should be discoverable rather than disappearing into the queue,
- Prompt Pairs should expose photo-generated candidates as explicit batches,
- model-generation credentials should remain visibly gated and `.env`-safe.

## Product Changes

1. Prompt Pairs now has a **Photo candidate batches** shelf.
   - Groups ready prompt-pair tickets by `photo_pair_generation_batch_id`.
   - Shows source title, candidate count, variant labels, first prompt, and batch ID.
   - Clicking a batch filters the queue to only that photo-derived candidate set.
   - `Clear batch` returns to the ordinary Prompt Pairs queue.

2. Photo submit handoff now keeps batch context.
   - When a photo submit creates or reopens candidates, the UI activates the corresponding batch instead of doing a loose text search.
   - Submitted photo receipts still show the five candidate buttons.

3. Existing photo prompt-pair candidates now reopen correctly.
   - `photo_prompt_pair_task_ids` now includes both newly created task IDs and existing candidate task IDs.
   - This fixes the receipt/handoff path when the batch already exists.

4. Model credential safety is now explicit.
   - Credential requirements state that `.env` and `.env.*` stay ignored.
   - `.env.example` remains the tracked template.
   - The UI shows this under the Demo Generation Gate.

## Verification

Latest strict gate:

- `python3 scripts/ralph_loop_gate.py --write-checkpoint --json`
- Passed: 54/54
- Latest checkpoint:
  - `updates/ralph_loop_gate_checkpoint_latest.md`
  - `updates/ralph_loop_gate_checkpoint_latest.json`

Focused checks run during the loop:

- `npm run typecheck --prefix apps/web`
- `npx --prefix apps/web playwright test --config apps/web/playwright.config.ts -g "prompt pairs can be filtered and searched as singleton tickets"`
- `docker compose exec -T api pytest -q tests/test_ralph_phase2_photo_spine.py::test_machine_photo_memory_review_promotes_adam_context_over_system_inference`
- `docker compose exec -T api pytest -q tests/test_ralph_phase1_training_spine.py::test_model_status_exposes_gpt_55_xhigh_without_enabling_live_calls_or_fine_tuning`
- `npx --prefix apps/web playwright test --config apps/web/playwright.config.ts -g "exports readiness exposes demo gate"`

## Current Bottleneck

The top downstream bottleneck remains Prompt Pairs review:

- 403 approved-ready
- 31 candidate/held
- top blockers include DPO rejected-reason gaps and source-boundary blocks

Next useful loop:

- make the Prompt Pairs workdown more guided by blocker type,
- add a stronger "keep/edit/delete" triage surface for photo candidate batches,
- or begin live model-call configuration once local credentials are present.
