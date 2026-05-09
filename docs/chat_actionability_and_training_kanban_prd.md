# Chat Actionability and Training Kanban PRD

Date: 2026-05-09

Owner: CharlesOps Workbench

Status: Draft for next implementation pass

## 1. Summary

The current Chat workbench is directionally useful, but two important user-facing problems remain:

1. Chat can say it will perform a concrete edit, such as moving the current Chosen/Preferred text into Rejected, but the underlying task draft may not actually change.
2. After Adam submits a good SFT or DPO pair, the item disappears from the active queue without a visible place where approved pairs accumulate.

These are both workflow clarity problems.

The first problem is an actionability issue. The assistant currently has a narrow control surface: it can write validated `field_updates` to a reversible `TaskDraft`, create submit/export confirmation actions, and confirm those actions. If the live model describes an action in prose but does not emit valid field updates, the backend drops the mutation while the prose still reads like a promise.

The second problem is a state visibility issue. Submit moves the task out of the active review list by setting `tasks.status = submitted`. If export preflight passes, the backend also writes approved rows into `sft_candidates` or `dpo_pairs`. Those approved rows are visible through export dry-runs and JSONL endpoints, but they are not represented as a clear Done column in the main work surface.

This PRD proposes a kanban-style training workbench and a stricter Chat action contract:

- Chat must only say an edit was applied when the backend applied it.
- Chat needs explicit patch operations for set, copy, move, clear, append, and submit preview.
- The UI should show rough pairs, in-progress drafts, approved/submitted pairs, and exported batches as connected workflow columns.
- Approved artifacts should visibly accumulate before batch export.

## 2. Current Findings

### 2.1 Chat Promise Without Mutation

In the screenshot, Adam says:

> Take the text from "Chosen/Preferred" and move it over to "Rejected". I will then give you a new response for chosen.

The assistant replies:

> Got it, Adam - I'll move the current Chosen/Preferred text into Rejected as the weaker voice sample, and leave Chosen ready for your replacement.

But the task does not visibly change.

The likely implementation reason is:

- `build_chat_turn()` accepts the live model plan.
- `_validate_chat_plan()` validates shape and action types.
- `_filter_field_updates()` keeps only allowed field names.
- `_normalize_actions()` drops draft-update action types if `field_updates` is empty.
- `_persist_chat_actions()` only writes a `TaskDraft` result when `field_updates` is non-empty.
- The assistant message is still the model-provided prose unless sanitized.

So the backend can end up with:

- assistant prose claiming a move;
- no valid `field_updates`;
- no draft write;
- no visible action preview;
- no error telling Adam the action was not applied.

This is especially likely for composite operations such as "move chosen to rejected and clear chosen" because the current schema is value-only. It has `field_updates`, but no first-class patch operations.

### 2.2 The Current Schema Cannot Represent Clear/Move Well

The desired operation is not just:

```json
{
  "rejected": "<old chosen text>"
}
```

It is:

```json
[
  { "op": "copy", "from": "chosen", "to": "rejected" },
  { "op": "clear", "field": "chosen" }
]
```

The current `field_updates` shape cannot express `clear`, because empty strings are sanitized away. It also cannot safely express `move` because the backend needs to resolve the source value from the current authoritative task/draft state, not from whatever the model paraphrases.

This makes the assistant less useful for editor-like operations:

- move chosen to rejected;
- swap chosen and rejected;
- clear chosen for replacement;
- append a DPO reason;
- convert SFT candidate into DPO candidate;
- preserve original draft while Adam writes a new accepted answer;
- undo the last draft patch.

### 2.3 Artifact Mode Ambiguity

The task in the screenshot is titled as an SFT review, while the panel displays DPO-like fields:

- Prompt Adam is reviewing
- Chosen / preferred
- Rejected / weaker

The local DB shows at least one nearby task with:

- `artifact_mode = sft`
- `chosen` present
- `rejected` present but empty

That means the object may be structurally between SFT and DPO modes. The UI can look like a DPO candidate while the backend still interprets it as SFT for readiness and normalization.

The next implementation should introduce an explicit normalized training-item state instead of inferring behavior from loose fields.

### 2.4 Where Approved Pairs Go Today

After Submit:

- `submit_task()` creates an `Annotation`.
- For `gold_voice_edit`, it calls `upsert_gold_voice_artifacts()`.
- That creates or updates `GoldVoiceExample`.
- Depending on export flags and preflight, it creates or updates `SFTCandidate` and/or `DPOPair`.
- The task is marked `submitted`.
- The task draft is deleted.

Local DB check at the time of this PRD:

- `gold_voice_edit` tasks:
  - `ready`: 434
  - `submitted`: 5
- approved artifacts:
  - `dpo_pairs.export_status = approved`: 1
  - `sft_candidates.export_status = approved`: 3

The recent submitted DPO example created:

- task: `TASK_MAKE_GOLD_000405`
- approved `dpo_pair_id`: `5f14986f-fba5-4d9c-9893-6324b3c23252`
- `export_ready`: true
- `statuses`: `{ "dpo": "approved" }`

So the approved pair exists. The problem is that the workflow does not show it as a visible Done item.

### 2.5 Existing Export Surface Is Correct But Too Far Away

The Export tab can dry-run approved-only SFT/DPO exports and build a `DatasetExport`. It also exposes JSONL endpoints.

However, from the review workflow, Adam does not see:

- the item moving from To Do to Doing to Done;
- the count of approved pairs accumulating;
- the exact DPO/SFT row created from the submitted ticket;
- which approved items are included in the next batch;
- a quick path from "I approved this" to "show me the done pile."

This makes the system technically correct but emotionally unclear.

## 3. Product Thesis

The workbench should feel like preparing a simple training file with an LLM helper, not like losing records into a database.

The right mental model is a board:

- To Do: rough/generated prompt pairs that need Adam.
- Doing: the current item and draft edits in progress.
- Ready to Submit: validated and waiting for explicit approval.
- Done: submitted/approved training artifacts.
- Exported: approved artifacts included in a built JSONL batch.

Chat should be an intelligent operator on that board, not just a narrator.

## 4. Goals

1. Make Chat action claims truthful.
2. Give Chat reliable control over structured draft edits.
3. Add first-class patch operations for field movement and clearing.
4. Make submitted/approved pairs visible as a Done pile.
5. Let Adam review and export batches from the Done pile.
6. Reduce ambiguity between SFT and DPO states.
7. Preserve all current safety gates: no submit/export without confirmation.
8. Preserve provenance and auditability.

## 5. Non-Goals

This PRD does not require:

- replacing the current TaskWorkbench editor;
- replacing the Export tab;
- building drag-and-drop in the first pass;
- changing the actual JSONL export format;
- weakening privacy or export preflight gates;
- letting the model mutate the DB directly;
- removing existing queue/sidebar navigation.

## 6. User Stories

### 6.1 Chat Applies a Move

As Adam, when I say:

> Move Chosen to Rejected and let me write a new Chosen.

I expect:

- the old chosen response appears in Rejected;
- Chosen becomes empty or marked "awaiting replacement";
- the UI shows the exact before/after patch;
- the assistant asks for the replacement chosen response;
- the backend records the draft patch and provenance.

### 6.2 Chat Does Not Overclaim

As Adam, if Chat cannot apply an edit, I expect it to say:

> I could not apply that because I need a concrete replacement field.

instead of:

> I’ll do it.

### 6.3 Submitted Item Moves to Done

As Adam, after I hit Submit on a good DPO pair, I expect:

- it leaves To Do;
- it appears immediately in Done;
- I can see that it created an approved DPO row;
- I can inspect chosen/rejected/prompt/reason;
- I can undo/reopen only through an explicit audited flow.

### 6.4 Batch Export From Done

As Adam, when I have a bunch of Done pairs, I expect:

- a count of approved SFT and DPO artifacts;
- a preview of which rows will be included;
- a "Build export" action that creates the JSONL batch;
- visibility into which Done items are already in a built export.

### 6.5 Kanban Board Workflow

As Adam, I want to work in a simple board:

- To Do: rough generated pairs;
- Doing: selected/current;
- Needs Fix: items with blockers;
- Done: approved artifacts;
- Exported: built into a dataset file.

I should not have to understand raw task statuses or export table names to trust the workflow.

## 7. Proposed UX

### 7.1 Training Board Tab

Rename or extend the current Training tab into a board view.

Initial columns:

1. To Do
   - ready `gold_voice_edit` tasks.
   - candidate prompt pairs needing Adam review.

2. Doing
   - selected task.
   - tasks with active `TaskDraft`.
   - current Chat session task.

3. Needs Fix
   - candidates with backend preflight blockers.
   - DPO rows missing rejected reason.
   - privacy/boundary/rubric blockers.

4. Done
   - submitted tasks whose receipt created approved SFT/DPO artifacts.
   - approved `sft_candidates`.
   - approved `dpo_pairs`.

5. Exported
   - approved artifacts included in a built `DatasetExport`.

The first version can use columns without drag-and-drop. Click-to-move is enough:

- "Start" moves or pins item into Doing.
- "Submit" moves it into Done if approved.
- "Reopen" creates audited follow-up task.
- "Build batch" creates export from Done.

### 7.2 Board Card Contents

Each card should show:

- pair number or task human ID;
- artifact mode: SFT or DPO;
- prompt preview;
- status: Ready, Drafting, Blocked, Approved, Exported;
- export gate: approved/candidate/blocked;
- source file or photo reference;
- last touched time;
- badges for missing required fields or blockers.

For DPO Done cards, show compact:

- prompt;
- chosen preview;
- rejected preview;
- reason count;
- export status.

For SFT Done cards, show compact:

- prompt;
- assistant response preview;
- export status.

### 7.3 Done Detail Panel

Clicking a Done card should open a read-only detail view:

- generated `GoldVoiceExample`;
- generated `SFTCandidate` or `DPOPair`;
- source `Annotation`;
- receipt;
- export eligibility;
- whether it has been included in a `DatasetExport`;
- JSONL row preview.

Actions:

- Copy JSONL row;
- Open source task/annotation;
- Reopen as follow-up edit;
- Exclude from next export;
- Include in next export if currently approved.

### 7.4 Chat and Board Integration

The Chat panel should show:

- current board column for the active item;
- pending patch preview;
- whether the patch was actually applied;
- a "View in board" action after submit;
- Done count after submit.

After a successful submit:

> Submitted. This created 1 approved DPO row and moved Pair 403 to Done. Done now has 1 DPO pair ready for export.

If submit creates candidate material, not approved:

> Submitted as review-candidate material. It moved to Needs Fix because the backend gate found 2 blockers.

## 8. Data Model Requirements

### 8.1 Training Item Projection

Add a read model endpoint that projects tasks and approved artifacts into board columns.

Possible endpoint:

```http
GET /api/training-board
```

Response:

```json
{
  "columns": [
    {
      "id": "todo",
      "label": "To Do",
      "count": 434,
      "items": []
    },
    {
      "id": "doing",
      "label": "Doing",
      "count": 1,
      "items": []
    },
    {
      "id": "needs_fix",
      "label": "Needs Fix",
      "count": 0,
      "items": []
    },
    {
      "id": "done",
      "label": "Done",
      "count": 4,
      "items": []
    },
    {
      "id": "exported",
      "label": "Exported",
      "count": 0,
      "items": []
    }
  ],
  "counts": {
    "ready_tasks": 434,
    "submitted_tasks": 5,
    "approved_sft": 3,
    "approved_dpo": 1
  }
}
```

### 8.2 Training Board Item Shape

```ts
type TrainingBoardItem = {
  id: string
  kind: 'task' | 'sft_candidate' | 'dpo_pair' | 'dataset_export_item'
  column: 'todo' | 'doing' | 'needs_fix' | 'done' | 'exported'
  taskId?: string
  taskHumanId?: string
  annotationId?: string
  goldVoiceExampleId?: string
  sftCandidateId?: string
  dpoPairId?: string
  datasetExportIds?: string[]
  artifactMode: 'sft' | 'dpo' | 'gold_voice'
  prompt: string
  chosen?: string
  rejected?: string
  content?: string
  reason?: string[]
  sourceLabel?: string
  exportStatus: 'candidate' | 'approved' | 'exported' | 'blocked'
  gateStatus: 'ready' | 'blocked' | 'unknown'
  blockers: string[]
  updatedAt: string
  completedAt?: string
}
```

### 8.3 Column Assignment Rules

To Do:

- `tasks.task_type = gold_voice_edit`
- `tasks.status = ready`
- no active draft
- no blocking-only state selected.

Doing:

- current selected task;
- active Chat session task;
- task has `TaskDraft`;
- task manually pinned by Adam.

Needs Fix:

- submitted candidate material where export status is `candidate`;
- ready task with preflight blockers;
- DPO missing rejected reason;
- source boundary or privacy block.

Done:

- submitted task with receipt `export_artifact.export_ready = true`;
- `sft_candidates.export_status = approved`;
- `dpo_pairs.export_status = approved`;
- not yet in a built export batch.

Exported:

- approved artifact included in one or more `dataset_export_items`.

### 8.4 Do Not Move Raw Source Records

The board should be a projection. It should not mutate raw source assets, source documents, or imported prompt-pair payloads just by displaying them in columns.

## 9. Chat Patch Contract

### 9.1 Replace Value-Only Updates With Patch Operations

Keep `field_updates` for simple cases, but introduce `draft_patch`.

```ts
type DraftPatchOperation =
  | { op: 'set'; field: string; value: unknown }
  | { op: 'clear'; field: string }
  | { op: 'copy'; from: string; to: string }
  | { op: 'move'; from: string; to: string }
  | { op: 'swap'; left: string; right: string }
  | { op: 'append'; field: string; value: unknown }
```

Example:

```json
{
  "assistant_message": "I can move the current preferred text to rejected and wait for your new chosen response.",
  "draft_patch": [
    { "op": "copy", "from": "chosen", "to": "rejected" },
    { "op": "clear", "field": "chosen" },
    { "op": "set", "field": "artifact_mode", "value": "dpo" }
  ],
  "proposed_actions": [
    {
      "action_type": "update_task_draft",
      "label": "Move preferred response to rejected",
      "requires_confirmation": false
    }
  ],
  "next_question": "What should the new chosen response say?"
}
```

### 9.2 Backend Resolves Patch Operations

The backend must resolve patch operations against authoritative current state:

1. Start with task input payload.
2. Overlay existing `TaskDraft`.
3. Resolve copy/move/swap from that merged object.
4. Validate all target fields against allowed schema.
5. Apply patch to a new draft object.
6. Produce field diffs.
7. Persist `TaskDraft`.
8. Record `ChatActionResult`.

The model should not be trusted to copy long text exactly when the backend can copy it from state.

### 9.3 Patch Validation Rules

The backend should reject or convert to clarification if:

- operation references unknown fields;
- operation would clear a required field and submit in the same turn;
- operation would make chosen and rejected identical;
- operation changes artifact mode without required companion fields;
- operation tries to mutate source-only fields;
- operation tries to submit/export without confirmation;
- operation result has no diff.

### 9.4 Assistant Message Must Be Reconciled With Actual Action Result

After validation, the backend should generate or rewrite status text based on executed actions.

If a patch executed:

> Applied: moved Chosen to Rejected. Chosen is now empty and ready for your replacement.

If no patch executed:

> I understood the edit, but I did not change the draft because I need a valid target field. Which response should become Rejected?

The model should not be allowed to claim "I moved" unless:

- a corresponding patch action exists;
- the backend applied it;
- a non-empty diff was recorded.

### 9.5 Action Preview

Every patch should produce a preview:

```json
{
  "field_diffs": [
    {
      "field": "rejected",
      "change_type": "copied",
      "before": "",
      "after": "<old chosen text>",
      "source_field": "chosen"
    },
    {
      "field": "chosen",
      "change_type": "cleared",
      "before": "<old chosen text>",
      "after": ""
    }
  ]
}
```

For auto-applied reversible draft edits, the preview can appear as "Applied draft update" with undo.

For risky edits, require confirmation.

## 10. DPO/SFT State Requirements

### 10.1 Normalize Ambiguous Prompt Pair State

Create a canonical helper:

```ts
type PromptPairMode = 'sft' | 'dpo'

type NormalizedPromptPairState = {
  mode: PromptPairMode
  prompt: string
  content?: string
  chosen?: string
  rejected?: string
  canConvertToDpo: boolean
  requiredMissing: string[]
  sourceOfTruth: 'task_payload' | 'task_draft' | 'submitted_artifact'
}
```

This should be shared by:

- Chat context packet;
- Chat patch validator;
- TaskWorkbench editor;
- Training board card projection;
- export preflight.

### 10.2 Convert SFT-Like Item to DPO

If an SFT task has chosen-like content and Adam says to create a DPO pair:

1. Set `artifact_mode = dpo`.
2. Copy current accepted response into `rejected`.
3. Clear `chosen`.
4. Ask Adam for new chosen.
5. Mark readiness missing `chosen`.

Do not submit until chosen, rejected, prompt, voice mode, and reason are present.

### 10.3 Preserve SFT Rewrite Behavior

The previous fix remains required:

- for SFT, Adam's accepted rewrite goes to `content`;
- the original draft can be preserved in `rejected`;
- `chosen` should not be stored as an SFT draft field except as derived export compatibility.

## 11. API Requirements

### 11.1 Training Board Endpoints

Add:

```http
GET /api/training-board
GET /api/training-board/items/{id}
```

Optional later:

```http
POST /api/training-board/items/{id}/start
POST /api/training-board/items/{id}/reopen
POST /api/training-board/exports/build
```

### 11.2 Chat Patch Endpoint Behavior

`POST /api/chat/turn` can remain the main endpoint, but response should include:

```ts
type ChatTurnResponse = {
  ...
  draft_patch?: DraftPatchOperation[]
  patch_result?: {
    applied: boolean
    field_diffs: FieldDiff[]
    blocked_reason?: string
  }
}
```

### 11.3 Export Batch Visibility

Add to board projection:

- latest dry-run included counts;
- approved-but-not-exported count;
- built export IDs per artifact;
- row inclusion/exclusion reasons.

## 12. Frontend Requirements

### 12.1 Board UI

Add a board view inside Training or as a new top-level "Board" view.

Minimum viable board:

- horizontal columns on desktop;
- stacked columns on mobile;
- cards are keyboard focusable;
- selecting a card opens existing TaskWorkbench or Done detail;
- counts appear in column headers;
- no drag-and-drop required in v1.

### 12.2 Chat UI Changes

When Chat applies a patch:

- show a compact "Applied draft patch" strip;
- list changed fields;
- show before/after for copy/move/clear;
- include Undo for the last reversible draft patch.

When Chat cannot apply:

- show a clear blocked action message;
- do not show "applied" language;
- ask one specific follow-up.

When Chat submits:

- show "Moved to Done" or "Moved to Needs Fix";
- show approved artifact IDs;
- show "View Done pile" button;
- show "Build export" only when approved rows exist.

### 12.3 TaskWorkbench Changes

After Submit:

- do not simply advance/disappear without confirmation context;
- show a receipt drawer or toast:
  - submitted task ID;
  - created artifact type;
  - approved vs candidate;
  - destination column;
  - link to Done item;
  - link to Export dry-run.

### 12.4 Export Tab Changes

The Export tab can remain the detailed batch builder.

Add stronger bridge text and actions:

- "Included from Done";
- "Approved but not yet built";
- "Open Done board";
- "Last built export";
- "Download latest built JSONL";
- "Download live approved JSONL".

## 13. Observability and Audit

Every Chat patch should record:

- session ID;
- turn ID;
- action ID;
- task ID;
- patch operations;
- resolved before/after values;
- whether applied;
- blocked reason if not applied;
- model response ID if live;
- context packet hash.

Every board transition should be explainable:

- why item is in To Do;
- why item is in Doing;
- why item is in Needs Fix;
- why item is in Done;
- why item is in Exported.

For submitted artifacts, the Done card should link:

- source task;
- annotation;
- task receipt;
- gold voice example;
- SFT candidate or DPO pair;
- dataset exports containing the artifact.

## 14. Safety Requirements

Do not allow Chat to:

- submit without explicit confirmation;
- build export without explicit confirmation;
- delete without explicit confirmation;
- claim an operation happened if backend rejected it;
- clear required fields and submit in same action;
- turn unconfirmed machine inference into Adam fact;
- bypass export preflight.

Done does not mean exported. Done means approved and eligible for export.

Exported means included in a built dataset export.

## 15. Implementation Plan

### Phase 1: Fix Chat Action Truthfulness

1. Add `draft_patch` model schema.
2. Add patch resolver and validator.
3. Support `copy`, `move`, `clear`, `swap`, `set`, `append`.
4. Reconcile assistant message with actual patch result.
5. Add tests for "move chosen to rejected and clear chosen."
6. Add tests for no overclaim when patch has no diff.

### Phase 2: Normalize Prompt Pair State

1. Add shared backend normalized prompt pair projection.
2. Use it in Chat context packet.
3. Use it in export preflight.
4. Use it in board projection.
5. Resolve SFT-with-chosen ambiguity.

### Phase 3: Add Training Board Read Model

1. Add `/api/training-board`.
2. Project To Do, Doing, Needs Fix, Done, Exported.
3. Add counts and card previews.
4. Add tests against seeded DB states.

### Phase 4: Add Board UI

1. Add board view in Training.
2. Render columns and cards.
3. Clicking To Do/Doing opens TaskWorkbench.
4. Clicking Done opens Done detail panel.
5. Add responsive and keyboard coverage.

### Phase 5: Bridge Submit to Done

1. After submit, show receipt and destination.
2. Add "View in Done" action.
3. Add "Build DPO/SFT export" action when appropriate.
4. Keep current queue navigation but stop making submission feel like disappearance.

### Phase 6: Batch Export From Done

1. Show approved-but-not-exported count.
2. Build export from approved-only dry-run.
3. Mark exported artifacts in board projection.
4. Add stored export detail and download links.

## 16. Acceptance Criteria

AC-001: If Chat says it moved text, a patch result with field diffs exists.

AC-002: If the backend cannot apply a patch, Chat says it did not apply it.

AC-003: "Move Chosen to Rejected" copies the exact current chosen text into rejected.

AC-004: The same operation clears chosen or marks it awaiting replacement.

AC-005: Clearing required chosen field prevents submit until Adam supplies a new chosen.

AC-006: Swapping chosen/rejected works from authoritative backend state.

AC-007: Patch operations reject unknown fields.

AC-008: Patch operations reject no-op changes.

AC-009: Patch operations record before/after values in `ChatActionResult`.

AC-010: Assistant prose is generated or corrected from applied action results.

AC-011: Ambiguous SFT/DPO tasks are normalized consistently across Chat and editor.

AC-012: Submitted approved DPO pairs appear in Done immediately.

AC-013: Submitted approved SFT examples appear in Done immediately.

AC-014: Submitted candidate material appears in Needs Fix with blockers.

AC-015: Done cards show created artifact IDs and export status.

AC-016: Done cards link to source task, annotation, receipt, and export artifact.

AC-017: Exported cards show which `DatasetExport` included them.

AC-018: Board counts match DB counts for ready/submitted/approved/exported states.

AC-019: Export dry-run included rows match the Done approved rows.

AC-020: Batch export does not include candidate or blocked artifacts.

AC-021: Submit still requires explicit confirmation.

AC-022: Export build still requires explicit confirmation.

AC-023: Board works on desktop.

AC-024: Board remains usable on mobile.

AC-025: Keyboard users can open cards and actions.

AC-026: Chat patch previews are readable and do not rely only on color.

AC-027: Tests cover live-model prose without valid patch payload.

AC-028: Tests cover "promise sanitized because no mutation happened."

AC-029: Tests cover Done accumulation after submit.

AC-030: Tests cover approved DPO batch export from Done.

## 17. Test Plan

### Backend Unit Tests

Add tests for patch resolver:

- set field;
- clear field;
- copy chosen to rejected;
- move chosen to rejected;
- swap chosen and rejected;
- append failure mode;
- reject unknown field;
- reject no-op patch;
- reject submit with missing chosen after clear.

Add tests for prompt-pair normalization:

- SFT with `content`;
- SFT with accidental `chosen`;
- DPO with chosen/rejected;
- DPO with missing rejected;
- SFT-to-DPO conversion.

Add tests for board projection:

- ready task -> To Do;
- task with draft -> Doing;
- submitted approved DPO -> Done;
- submitted approved SFT -> Done;
- submitted candidate with blocker -> Needs Fix;
- artifact included in dataset export -> Exported.

### Backend Integration Tests

Add Chat integration test:

1. Seed DPO-like task with chosen and empty rejected.
2. POST chat turn: "Move chosen to rejected and I'll give a new chosen."
3. Assert response patch applied.
4. Assert `TaskDraft.decisions.rejected` equals previous chosen.
5. Assert `TaskDraft.decisions.chosen` is absent or empty.
6. Assert response asks for new chosen.

Add no-overclaim test:

1. Mock live model returning assistant message "I moved it" with no patch or field updates.
2. Assert backend response does not claim the move happened.
3. Assert no `TaskDraft` is created.
4. Assert action result says blocked/no-op.

### Frontend Tests

Add Playwright tests:

- board columns render counts;
- submit moves item into Done;
- Done card shows DPO chosen/rejected;
- Chat move action shows applied patch diff;
- Chat failed patch shows blocked message;
- mobile board remains usable.

### Manual QA

Manual flow 1:

1. Open Chat on Pair 402.
2. Say "Move chosen to rejected. I'll give a new chosen."
3. Verify rejected field updates immediately.
4. Verify chosen field is empty/awaiting replacement.
5. Provide new chosen.
6. Submit.
7. Verify item appears in Done.

Manual flow 2:

1. Open Training board.
2. Approve three DPO pairs.
3. Verify Done count increases each time.
4. Build DPO export.
5. Verify those cards move or badge as Exported.
6. Download JSONL and inspect rows.

## 18. Open Questions

1. Should Doing be a real persisted status or a projection from selection/draft/session?
2. Should drag-and-drop be allowed in v1, or should buttons come first?
3. Should Done include all submitted tasks or only export-approved artifacts?
4. Should candidate submitted material live in Needs Fix or Done with a blocker badge?
5. Should clearing a required field store `null`, empty string, or a special `field_state.awaiting_input` marker?
6. Should Chat auto-apply reversible patches, or preview every patch for confirmation?

## 19. Recommended Decisions

1. Make board columns a projection first.
2. Do not implement drag-and-drop in v1.
3. Use explicit buttons: Start, Submit, Reopen, Build Export.
4. Store patch operation results in chat action metadata.
5. Represent cleared required fields with a structured marker, not an empty string that sanitizers drop.
6. Generate assistant action-result copy from backend truth, not directly from model prose.
7. Keep Done limited to approved artifacts and put candidate submissions in Needs Fix.

## 20. Why This Direction Is Right

The kanban model matches Adam's mental model:

- rough work comes in;
- one item is being edited;
- approved items accumulate;
- a batch export is created from approved items.

It also aligns with the actual backend:

- `tasks` are the work queue;
- `TaskDraft` is Doing;
- `Annotation` and receipts are submission history;
- `SFTCandidate` and `DPOPair` are approved/candidate training artifacts;
- `DatasetExport` is the batch file.

The missing product layer is not more raw form fields. It is a visible state model that explains where each artifact is and what can happen next.
