# Ralph Loop Morning Status

Generated: 2026-04-29T20:01:16.771857+00:00
Live handoff content SHA-256: `6a0f9cbf03cfe3ea6971b31db5735daa27179241bdaf93c0f29b52f022c03ffe`

## Latest Gate

- Checkpoint: `updates/ralph_loop_gate_checkpoint_latest.json`
- Checkpoint Markdown: `updates/ralph_loop_gate_checkpoint_latest.md`
- Checkpoint generated: `2026-04-29T20:01:10.593145Z`
- Checks passed: 48 / 48
- Phase report: `updates/ralph_loop_2026-04-29_phase_report.md`
- Visual checkpoint: `updates/exports_readiness_operator_handoff_2026-04-29.png`

## Bottleneck Order

1. Prompt Pairs: 30 item(s), action `open_held_prompt_pair_candidate`
2. Photo Context: 22 item(s), action `open_existing_photo_context_task`
3. Vector Handoff: 5 item(s), action `open_photo_vector_review`
4. Demo Generation: 2 item(s), action `configure_text_generation_credentials`

## Live Product Handoff

# Morning Handoff

Prompt Pairs is the top bottleneck; artifacts are hash-audited.

## Readiness
- Prompt pairs: 403 approved / 30 candidates (needs_gold_review).
- Photo context: 22 groups need context / 5 held drafts (needs_adam_context).
- Vector handoff: 0 ready / 5 held (review_holds_remaining).
- Demo generation: text_generation_live_calls_disabled, openai_api_key_missing (credential_gated).
- Downstream artifacts: 18 artifacts / 0 hash mismatches (hash_audited).

## Next Actions
- Prompt Pairs: Backend preflight keeps this prompt pair in candidate dry-run until blockers are resolved.
- Photo Context: Create or open context tasks so photos can become reviewed memory records.
- Vector Handoff: Open the photo memory review task and promote Adam-authored context before vector export.
- Demo Generation: Add credentials and enable live text generation when ready; no fine-tuning API call is part of MVP.

## Retrieval Gap Work
- Query: airplane in Maine
- Status: no_boundary_cleared_memory_result / no_claim
- Candidates: 27 total, 5 previewed.
- Completion: retrieval_query_returns_boundary_cleared_memory_or_context_task_submit_ready

## Safety
- No fine-tuning API calls in MVP.
- No live model calls for this handoff.
- Demo outputs, when enabled, remain model_generated until Adam review.
- Photo backlog remains no_claim until Adam-authored context is submitted.


## Prompt Pairs

- Approved-ready: 403
- Candidate/held: 30
- Inspectable pairs: 433
- DPO rejected reason gaps: 25
- Source-boundary training blocks: 5

## Photo Context

- Total photos: 273
- Preview-ready photos: 82
- Photo groups needing context: 22
- Photo assets needing context: 71
- Photo groups needing draft review: 5
- Reviewed vector-ready photos: 0

## Retrieval Gap

- Query: airplane in Maine
- Status: no_boundary_cleared_memory_result / no_claim
- Candidate count: 27
- Slice hash: `858f02e157cc8d6bfde49342724a232d7191aabfe218bf7f1d6db4d6be89d528`

## Downstream Artifacts

- Artifact count: 18
- Hash mismatches: 0
- Manifest hash: `e57d7da70bafee0506518dd996a53b77c9ec2e64c10c115efc3d768d42a6e4a7`
- Audit hash: `3e0e72cefdf2a6c62fb4b64348a438db940db7aac558b7317d49ce0a61a8e083`

## Model Generation Gate

- Model: `gpt-5.5`
- Reasoning effort: `xhigh`
- Can generate now: `False`
- Blockers: text_generation_live_calls_disabled, openai_api_key_missing
- Output truth status: `model_generated`
- Fine-tuning API calls allowed: `False`

## Verification Commands

```bash
docker compose exec -T api pytest -q
npm run typecheck --prefix apps/web
npx --prefix apps/web playwright test --config apps/web/playwright.config.ts
python3 scripts/ralph_loop_gate.py --write-checkpoint --json
git diff --check
```

## Safety Notes

- No fine-tuning APIs were called.
- Raw source files were not mutated.
- Photo retrieval gaps remain no-claim until Adam-authored context is submitted.
- Candidate prompt pairs remain out of approved training export until blockers are resolved.
