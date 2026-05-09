# Chat Workbench Operator Contract

Status: implemented contract reference
Date: 2026-05-08

This document captures the implemented Chat Workbench contract for the intelligent chat operator described in `docs/intelligent_chat_workbench_prd.md`.

## Purpose

The Chat tab is a draft-first operator surface.

The model may propose work, but database mutations go through typed backend actions, previews, confirmation checks, and durable audit records.

## Endpoints

- `POST /api/chat/turn`
  - Creates or reuses a chat session.
  - Records user and assistant turns.
  - Builds the server-side context packet.
  - Calls the live model when enabled, otherwise uses deterministic fallback.
  - Applies reversible draft updates when allowed.
  - Creates pending confirmation actions for submit/export operations.

- `GET /api/chat/sessions`
  - Lists recent chat sessions for a user.

- `POST /api/chat/sessions`
  - Creates a new chat session.

- `GET /api/chat/sessions/{session_id}`
  - Restores a persisted session, turns, actions, and the latest response payload.

- `POST /api/chat/actions/{action_id}/preview`
  - Returns the authoritative backend preview payload for a pending action.
  - Reports stale status and whether the action can still be confirmed.

- `POST /api/chat/actions/{action_id}/confirm`
  - Confirms supported pending actions after stale checks.
  - Currently executes task submission and dataset export build actions.

- `POST /api/chat/actions/{action_id}/dismiss`
  - Dismisses a pending confirmation action without mutating the target task/export.

- `GET /api/chat/audit`
  - Returns a read-only audit summary for a task, session, or recent chat activity.
  - Includes sessions, turns, actions, results, provenance links, status counts, context hashes, and quality gaps.

## Action Types

The backend exposes these model-visible action contracts:

- `ask_question`
- `update_task_draft`
- `preview_submit`
- `preview_task_submission`
- `submit_task`
- `open_task`
- `focus_task`
- `skip_task`
- `flag_task`
- `create_memory_note`
- `create_photo_context`
- `update_photo_context`
- `create_prompt_response_candidate`
- `update_prompt_response_candidate`
- `update_dpo_pair`
- `mark_candidate_approved`
- `mark_candidate_rejected`
- `create_export_preview`
- `build_dataset_export`

Unsupported action types are rejected, logged, and surfaced in response metadata.

`focus_task` normalizes to `open_task`.

`preview_task_submission` normalizes to `preview_submit`.

`mark_candidate_approved` normalizes to `submit_task` only when the task is ready.

`mark_candidate_rejected` normalizes to a reversible draft update when there is a valid draft change to preserve.

## Confirmation Rules

These actions require explicit confirmation:

- `submit_task`
- `mark_candidate_approved`
- `mark_candidate_rejected`
- `build_dataset_export`

Confirmation can be sent through the action confirmation endpoint or through `POST /api/chat/turn` with the matching confirmation fields.

The backend rejects confirmation when:

- the action is missing;
- the action is not pending confirmation;
- the action belongs to another session;
- the task draft changed after preview;
- the export dry-run hash changed after preview;
- the action type cannot be confirmed directly.

Dismissal is allowed for pending confirmation actions and records a `chat_action_results` row with no target mutation.

## Context Packet Shape

Every normal chat turn builds a server-side context packet. The frontend does not assemble authoritative context.

For existing sessions, the backend hydrates recent prior user and assistant turns from `chat_turns` before building the context packet or calling the live model. Client-provided `history` can add unsaved context, but persisted server history is the baseline so a refreshed or API-driven session does not lose conversational memory.

The packet includes:

- `active_task`
- `task_kind`
- `work_surface`
- `object_contracts`
- `source_refs`
- `associated_object_ids`
- `source_material_preview`
- `recent_chat`
- `current_draft`
- `provenance_refs`
- `required_decisions`
- `missing_fields`
- `allowed_field_updates`
- `allowed_actions`
- `action_contracts`
- `image_context`
- `current_user_intent`

`associated_object_ids` normalizes links into:

- `asset_ids`
- `source_excerpt_ids`
- `prompt_response_ids`
- `context_pack_ids`

`image_context` includes:

- image asset ID;
- preview URL;
- local pixel availability;
- whether pixels are included in the live model request;
- content type;
- object file ID;
- byte size;
- width and height when known;
- reason when pixels are unavailable.

Prompt-response work surfaces include a `field_contract`.

The context packet also includes `object_contracts`. These are the canonical schemas the chat operator and live model must use when interpreting a ticket. For prompt-response work, the contract names the artifact mode, canonical fields, aliases such as `accepted_response` and `rejected_response`, submit mappings, and rules that prevent brittle UI-based inference.

For SFT:

- accepted response field: `content`;
- rejected/original evidence field: `rejected`;
- derived export compatibility field: `chosen`.
- submit mapping: SFT assistant message uses `content`; if a preference pair is produced, DPO `chosen` uses `content` and DPO `rejected` uses `rejected`.
- stale drafts that put Adam's accepted SFT rewrite into `chosen` are normalized back to `content`, with the original draft preserved in `rejected`.

For DPO:

- accepted/preferred field: `chosen`;
- weaker/non-preferred field: `rejected`.
- `content` is not canonical for DPO. If a model proposes `content`, the backend maps it to `chosen`.

## Provenance

Chat-generated submissions attach `chat_provenance` to submitted decisions and receipts.

The provenance includes:

- chat session ID;
- preview turn ID;
- confirmation turn ID;
- chat action ID;
- task ID;
- context packet hash;
- source references;
- field-level provenance;
- decision diffs.

Photo context provenance distinguishes:

- Adam-confirmed facts;
- Adam-provided memory;
- Adam-confirmed uncertainty;
- model visual inference;
- database-derived association.

SFT and DPO provenance distinguishes:

- source prompt;
- Adam critique;
- edited response;
- backend export policy;
- final approval.

## Audit Surface

`GET /api/chat/audit` supports three useful modes:

- task audit: `?task_id=...`
- session audit: `?session_id=...`
- combined task/session audit: `?task_id=...&session_id=...`

The response includes:

- session, turn, action, and result counts;
- action status counts;
- latest context packet hash;
- quality gaps;
- quality signals;
- recent turns;
- recent actions;
- recent action results;
- provenance links.

The Chat UI renders a compact audit panel rather than raw JSON.

It shows:

- turn count;
- action count;
- result count;
- latest context hash prefix;
- linked source target when available;
- quality gap chips.

## Local Verification

Backend:

```bash
docker compose build api
docker compose run --rm -e TEXT_GENERATION_LIVE_CALLS_ENABLED=false -e OPENAI_API_KEY= api pytest -q
```

Opt-in live model smoke checks:

```bash
python3 scripts/chat_live_smoke.py --api-base http://localhost:8000/api --require-ready
```

The smoke runner calls `/api/model-status` first and skips unless live calls and credentials are configured. It posts chat turns with `apply_updates=false`, so it can inspect live model behavior without submitting tasks or building exports.

Frontend:

```bash
npm --prefix apps/web run typecheck
npm --prefix apps/web run build
WEB_BASE_URL=http://localhost:3002 npx --prefix apps/web playwright test --config apps/web/playwright.config.ts
```
