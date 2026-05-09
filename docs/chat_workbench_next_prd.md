# CharlesOps Chat Workbench PRD

Date: 2026-05-08

Owner: Adam / CharlesOps

Status: Draft for next implementation phase

Target repo: `adamrotmil/chas`

Primary surfaces:

- `apps/web/src/components/ChatWorkbench.tsx`
- `apps/api/app/services/chat_operator.py`
- `apps/api/app/routers/chat.py`
- `apps/api/app/schemas.py`
- `apps/web/src/app/page.tsx`
- `apps/web/src/components/TaskWorkbench.tsx`
- `apps/api/app/services/operator_assistant.py`
- `apps/api/app/services/photo_context_projection.py`
- `apps/api/app/services/photo_context_progress.py`
- `apps/api/app/services/prompt_pair_audit.py`
- `apps/api/app/services/photo_memory_drafts.py`
- `apps/api/app/services/vision.py`

## 1. Executive Summary

CharlesOps is evolving from a form-heavy review workbench into an intelligent, Adam-facing workbench agent.

The Chat tab should not be a generic chat box bolted onto the existing task system.

The Chat tab should be the most natural way for Adam to move through review work.

It should show Adam the current object of work.

It should understand what kind of work item is active.

It should ask one useful question at a time.

It should ask questions to Adam, not to Charles.

It should never confuse a candidate training prompt with a question Adam should answer.

It should use photos, source documents, prompt-response candidates, DPO pairs, task metadata, drafts, history, and downstream blockers to decide what to ask next.

It should convert Adam's answers into structured draft updates.

It should preview the consequences of those updates.

It should ask for explicit confirmation before submitting or destructive actions.

It should submit through existing backend paths so all receipts, annotations, downstream artifacts, boundaries, memory records, and export gates remain consistent.

The current implementation has made important progress:

- A Chat tab exists above Intake.
- A `POST /api/chat/turn` backend route exists.
- Chat turns use a live model path when configured.
- Chat turns fall back to deterministic behavior when live calls are gated or fail.
- Chat updates `TaskDraft` records.
- Chat can confirm submit through the existing `submit_task` route path.
- The Chat UI now shows photo context and prompt-response context.
- The backend now guards against asking Adam to answer the source prompt.
- The backend can attach local mirrored image previews to live model calls when available.

The next phase should turn this into a deeper, task-aware, testable workbench agent.

This PRD defines the next product requirements, architecture, implementation phases, and verification plan.

## 2. Product Vision

Adam should be able to sit down with CharlesOps and work through a queue conversationally.

The experience should feel like a capable editor, archivist, and production assistant sitting beside Adam.

The assistant should know what is on the screen.

The assistant should know why that item is in the queue.

The assistant should know which field or decision is blocking progress.

The assistant should know which downstream artifacts or model-training paths are affected.

The assistant should know when it is asking about visible photo evidence.

The assistant should know when it is asking about Adam's memory.

The assistant should know when it is asking about privacy and boundaries.

The assistant should know when it is reviewing SFT or DPO examples.

The assistant should know when it is helping rewrite a prompt, a chosen response, a rejected response, or a rubric note.

The assistant should never pretend that generated or inferred content is source truth.

The assistant should never pretend to be Charles.

The assistant should never silently move a ticket forward without Adam's explicit confirmation.

The assistant should reduce UI clutter by letting Adam work in natural language while keeping the existing forms and receipts as inspectable, deterministic structure.

## 3. Problem Statement

The current UI exposes a lot of useful functionality, but it feels sprawling.

The workbench has accumulated panels, queues, previews, drawers, filters, gates, badges, source cards, and forms.

These elements are useful individually.

Together, they make it harder to know what to do next.

Adam's original low-friction process was a simple YAML file edited with LLM assistance.

The elegance of that process came from the fact that Adam could see the whole artifact and edit it directly.

CharlesOps exists because the project needs more than one text file:

- many journals and documents to reference
- photos that carry memory and meaning
- visual understanding and associations
- context layers on documents, excerpts, and photos
- reviewed training data for SFT and DPO
- retrieval-ready memory records
- boundaries and privacy controls
- export gates for high-quality downstream work

The product challenge is to preserve the elegance of the YAML workflow while supporting richer source material and safer downstream automation.

The Chat Workbench is the best candidate for that unifying layer.

## 4. Current State

### 4.1 Implemented Chat Backend

`apps/api/app/routers/chat.py` exposes `POST /api/chat/turn`.

`apps/api/app/services/chat_operator.py` currently:

- selects the active task
- merges existing draft decisions with incoming draft decisions
- builds task-aware prompt context
- calls the OpenAI Responses API when `live_text_generation_ready` is true
- uses `gpt-5.5` by default through `text_generation_model`
- uses `chat_reasoning_effort`, defaulting to `medium`
- validates and filters field updates through `_filter_field_updates`
- saves allowed updates to `TaskDraft`
- computes ready-to-submit state
- prepares a submit payload
- requires explicit confirmation for actual submit
- sanitizes source-prompt leakage for prompt-response tasks
- optionally attaches a local image data URL when a mirrored image preview is available

### 4.2 Implemented Chat Frontend

`apps/web/src/components/ChatWorkbench.tsx` currently:

- renders a Chat workbench under the main shell
- displays the active task title
- displays a model status badge
- displays chat messages
- displays draft updates
- sends turns to `/chat/turn`
- updates local draft state from responses
- calls `onOpenTask` for active task changes
- calls `onSubmitted` and `onRefresh` after confirmed submit
- renders a photo context panel for photo-like tasks
- renders prompt and response cards for SFT and DPO-like tasks
- shows a disabled Confirm submit button until backend reports readiness

### 4.3 Implemented Navigation

`apps/web/src/app/page.tsx` currently:

- defines `chat` as a `NavMode`
- places Chat above Intake
- routes Chat to `ChatWorkbench`
- passes ready tasks, assets, selected task, and preview token to Chat
- hides collection filters for Chat

### 4.4 Relevant Existing Systems

The Chat Workbench must interoperate with:

- `Task`
- `TaskDraft`
- `Annotation`
- `TaskReceipt`
- `Asset`
- `AssetSnapshot`
- `Derivative`
- `ObjectFile`
- `MetadataProfile`
- `Boundary`
- `Memory`
- `EmbeddingRecord`
- `GoldVoiceExample`
- `SFTCandidate`
- `DPOPair`
- `DatasetExport`
- `DatasetExportItem`
- `ContextPack`
- `PromptSpec`
- `Generation`
- `GenerationReview`

### 4.5 Current Test Coverage

`apps/api/tests/test_chat_operator.py` currently verifies:

- draft-first update behavior
- allowed-field filtering
- source-prompt leakage prevention
- confirmed submit through existing submit path

The broader deterministic API suite currently passes when live model calls are disabled.

The web app typecheck and build pass.

Browser smoke tests have verified:

- Chat renders above Intake
- photo context panel appears
- prompt-response context panel appears
- live photo chat asks Adam image-grounded identity/context questions
- live prompt-response chat asks Adam to review or edit instead of answering the prompt

## 5. Product Principles

### 5.1 Adam Is The Addressee

All chat questions are addressed to Adam.

The assistant asks Adam what he knows, sees, remembers, approves, rejects, edits, or wants to preserve as uncertainty.

The assistant does not ask Adam to roleplay Charles.

The assistant does not ask Adam to answer a source prompt unless the task itself is explicitly asking Adam to author a new prompt-response example.

### 5.2 The Work Item Must Be Visible

Chat is not useful if the object under discussion is hidden.

Every Chat turn should be grounded in a visible work item panel.

For photos, this means the image is visible.

For SFT, this means prompt and draft response are visible.

For DPO, this means prompt, chosen response, rejected response, and rubric/failure context are visible.

For text source review, this means source excerpt, chunk boundaries, and downstream generation controls are visible.

For export or model-starter tasks, this means manifest, blockers, hashes, and next action are visible.

### 5.3 One Question At A Time

The assistant should ask one question at a time.

The assistant can include a short preface when needed.

The assistant should avoid multi-part interrogations that overwhelm the workflow.

If multiple details are needed, it should choose the highest-value next question.

### 5.4 Draft First

All model-interpreted updates go into a draft.

Drafts must be inspectable.

Drafts must be reversible.

Drafts must not mutate source records.

Drafts must not submit tickets unless Adam explicitly confirms.

### 5.5 Existing Data Paths Remain Authoritative

Chat should not invent new submission semantics.

Chat should use existing submit paths.

Chat should use existing projection paths.

Chat should use existing export gates.

Chat should use existing receipt generation.

Chat should use existing downstream artifact creation.

### 5.6 Truth Boundaries Are Sacred

The assistant must keep the following separate:

- visible facts
- machine inference
- Adam memory
- archival source truth
- synthetic reconstruction
- generated model output
- privacy/boundary decisions
- unresolved uncertainty

### 5.7 Smart Does Not Mean Unbounded

The chat model should be smart enough to interpret Adam's answer.

The action system should remain bounded.

The backend should validate all actions.

The backend should filter all fields.

The backend should require confirmation for submit, skip, delete, export, or generation.

### 5.8 Reduce Clutter Without Hiding Auditability

Chat should simplify the main workflow.

The form workbench should remain available as a detailed editor.

The system should show what changed, why it changed, and what will happen if Adam submits.

## 6. Goals

### 6.1 Primary Goals

1. Make Chat the most efficient interface for reviewing photo context tasks.
2. Make Chat the most efficient interface for reviewing SFT and DPO prompt-response candidates.
3. Let Chat use multimodal model input for photos when preview files are available.
4. Let Chat understand task type, queue, blockers, draft state, and downstream consequences.
5. Let Chat update drafts with structured decisions.
6. Let Chat preview submit outcomes before confirmation.
7. Let Chat submit only through existing backend submit paths.
8. Let Chat preserve truth boundaries and uncertainty.
9. Let Chat use existing queues and worklists intelligently.
10. Let Chat become a route into the rest of the workbench rather than a separate toy feature.

### 6.2 Secondary Goals

1. Reduce the need to manually click through complex forms.
2. Make the workbench feel less cluttered without removing functionality.
3. Improve quality of photo memory context.
4. Improve quality of SFT examples.
5. Improve quality of DPO chosen/rejected pairs.
6. Create richer context layers as a byproduct of review.
7. Improve export readiness by resolving blockers conversationally.
8. Improve model-starter package quality through guided review.
9. Make progress measurable.
10. Create a foundation for future autonomous but bounded workbench agents.

## 7. Non-Goals

The next phase should not:

- replace all forms
- remove existing review panels
- bypass task queues
- bypass submit receipts
- bypass export gates
- train or fine tune a model directly
- create new source truth without Adam review
- auto-identify private people as fact without Adam confirmation
- auto-submit tickets after model confidence alone
- make destructive changes without explicit confirmation
- make Chat imitate Charles
- make Chat answer as Charles
- make Chat silently write to final artifacts

## 8. Personas

### 8.1 Adam

Adam is the primary user.

Adam reviews photos, documents, excerpts, SFT examples, DPO examples, boundaries, and downstream training artifacts.

Adam wants a simple, elegant workflow.

Adam wants the system to be smart enough to help.

Adam wants to avoid clutter and rabbit holes.

Adam wants to build a high-quality digital twin with strong memory, voice, and visual context.

Adam must remain the authority for memory, identity, privacy, and final approval.

### 8.2 CharlesOps Assistant

The assistant is a bounded workbench operator.

It asks Adam questions.

It interprets Adam's answers.

It updates drafts.

It previews consequences.

It can propose actions.

It cannot silently mutate source truth.

It cannot silently submit.

It cannot impersonate Charles.

### 8.3 Future Model Or Agents

Future downstream agents will consume:

- SFT examples
- DPO examples
- context packs
- memory records
- photo context
- embeddings
- boundaries
- model-starter package artifacts

The Chat Workbench should improve the quality and structure of these inputs.

## 9. Core User Stories

### 9.1 Photo Review Story

As Adam, I want Chat to show me a photo and ask what it needs to know, so I can identify people, place, memory, event, uncertainty, and boundaries without manually scanning a long form.

Acceptance criteria:

- Chat displays the active photo.
- Chat can ask "Who is the person in the top left?"
- Chat can ask "Where was this taken?"
- Chat can ask "What does this photo bring up for you?"
- Chat can ask "Should this be family private or sealed?"
- Chat records visible facts separately from Adam memory.
- Chat records unresolved uncertainty.
- Chat does not treat the model's visual guesses as Adam truth.
- Chat can mark the photo ready for downstream only after required decisions exist.

### 9.2 Prompt Pair Review Story

As Adam, I want Chat to show me a prompt and response, then ask how the response feels, so we can discuss voice, truth, specificity, and rewrite it until it is right.

Acceptance criteria:

- Chat displays the source prompt.
- Chat displays the draft response.
- Chat asks Adam to evaluate or edit the response.
- Chat never asks Adam to answer the source prompt by default.
- Chat can propose a rewritten response.
- Chat can apply Adam-approved rewrite text to `content` or `chosen`.
- Chat can keep a rejected response distinct from a chosen response.
- Chat can update rubric/failure modes from Adam feedback.
- Chat can preview whether a candidate is export-ready.

### 9.3 DPO Pair Review Story

As Adam, I want Chat to show me a DPO prompt, chosen response, and rejected response, then ask what makes the rejected side weaker, so the system can produce better preference data.

Acceptance criteria:

- Chat displays prompt, chosen, and rejected.
- Chat asks about the relationship between chosen and rejected.
- Chat can identify missing rejected-side issue notes.
- Chat can turn Adam feedback into `failure_modes`.
- Chat can update `response_rubric`.
- Chat can suggest a better rejected answer when the current rejected answer is too weak, too obvious, or not useful.
- Chat keeps generated rejected drafts marked as review material.
- Chat does not promote DPO pairs until export gates pass.

### 9.4 Source Review Story

As Adam, I want Chat to show me a source excerpt and ask whether it is useful for context, training, prompt pairs, or boundaries, so I can move source material forward without a large form.

Acceptance criteria:

- Chat displays the source excerpt.
- Chat can ask about authorship.
- Chat can ask about voice presence.
- Chat can ask about privacy.
- Chat can ask whether it should generate prompt pairs.
- Chat can keep chunk boundaries and selected spans intact.
- Chat can apply source-review draft decisions.
- Chat can trigger existing generate-pairs flow only after confirmation.

### 9.5 Queue Triage Story

As Adam, I want Chat to decide which ticket is most useful to work on next, so I can focus on high-leverage work.

Acceptance criteria:

- Chat can explain why it picked a ticket.
- Chat can prioritize photo context blockers.
- Chat can prioritize DPO rejected-reason blockers.
- Chat can prioritize source boundary blockers.
- Chat can respect current queue filters.
- Chat can open a selected task.
- Chat can move to the next task after submit.

### 9.6 Database Update Story

As Adam, I want Chat to use what it learns to update the database and move tickets forward, so the conversation has real product consequences.

Acceptance criteria:

- Chat writes drafts to `task_drafts`.
- Chat submit creates `annotations`.
- Chat submit updates task status.
- Chat submit creates or updates downstream records through existing services.
- Chat submit returns receipts.
- Chat exposes what will change before confirmation.

## 10. Functional Requirements

### 10.1 Chat Session Requirements

REQ-001: Chat must maintain a per-task conversation state during a browser session.

REQ-002: Chat must reset conversation state when Adam switches active tasks.

REQ-003: Chat must preserve draft decisions when a new turn is sent.

REQ-004: Chat must include recent chat history in backend model calls.

REQ-005: Chat must cap history sent to the model.

REQ-006: Chat must avoid losing Adam text if an API request fails.

REQ-007: Chat must show request in-progress state.

REQ-008: Chat must show model status: live, gated, fallback, or error.

REQ-009: Chat must show the active task human ID and task type.

REQ-010: Chat must support manually opening the full task form.

### 10.2 Work Item Context Requirements

REQ-011: Chat must render a work item context panel above the conversation.

REQ-012: Photo tasks must render the image preview when available.

REQ-013: Photo tasks must render visible people and objects when available.

REQ-014: Photo tasks must show when visible facts need Adam confirmation.

REQ-015: Prompt-response tasks must render prompt text.

REQ-016: SFT tasks must render draft/content response.

REQ-017: DPO tasks must render chosen and rejected responses.

REQ-018: Prompt-response tasks with source photos must render a source photo thumbnail.

REQ-019: Text source tasks must render source preview or excerpt.

REQ-020: Work item context must be responsive on mobile.

REQ-021: Work item context must not create nested cards inside cards.

REQ-022: Work item text must not overflow buttons or panels.

### 10.3 Adam-Facing Question Requirements

REQ-023: Chat must ask Adam one question at a time.

REQ-024: Chat must ask questions appropriate to the active task type.

REQ-025: Chat must ask photo questions about visible facts, identity, place, time, story, uncertainty, or boundary.

REQ-026: Chat must ask SFT questions about prompt quality, response quality, voice, specificity, truth, and rewrite direction.

REQ-027: Chat must ask DPO questions about chosen/rejected contrast, failure modes, preference signal, and rubric.

REQ-028: Chat must ask source-review questions about authorship, voice, boundary, context, spans, and downstream use.

REQ-029: Chat must not ask Adam to answer the source prompt for prompt-response tasks.

REQ-030: Chat must sanitize model output if it repeats the source prompt as a question to Adam.

REQ-031: Chat must record when sanitization occurred.

REQ-032: Chat must not ask multiple unrelated questions in one turn.

### 10.4 Structured Update Requirements

REQ-033: Chat must return structured `field_updates`.

REQ-034: Backend must filter field updates through task-specific allowed keys.

REQ-035: Backend must ignore unknown field update keys.

REQ-036: Backend must ignore empty field update values.

REQ-037: Backend must store allowed updates in `TaskDraft`.

REQ-038: Backend must merge existing draft decisions with incoming updates.

REQ-039: Chat must show a visible proof of draft updates.

REQ-040: Chat must show changed fields in human-readable labels.

REQ-041: Chat must support text, booleans, arrays, and JSON object updates.

REQ-042: Chat must keep source truth and Adam memory separate.

REQ-043: Chat must keep visible people separate from absent or relevant people.

REQ-044: Chat must keep rejected system inference separate from accepted description.

REQ-045: Chat must keep DPO rejected response separate from chosen response.

### 10.5 Photo Task Requirements

REQ-046: Chat must support `photo_context` tasks.

REQ-047: Chat must support `vision_draft_review` tasks.

REQ-048: Chat must attach local mirrored image previews to live model calls when available.

REQ-049: Chat must not fail if image attachment is unavailable.

REQ-050: Chat must not fetch private media from external origins without existing preview access paths.

REQ-051: Chat must cap image payload size.

REQ-052: Chat must prefer display derivative, then thumbnail derivative, then source mirror.

REQ-053: Chat must not attach non-image object files as image input.

REQ-054: Chat must ask Adam to verify people instead of asserting identity.

REQ-055: Chat must store model visual observations as draft suggestions until Adam confirms.

REQ-056: Chat must store Adam context as Adam-authored memory context.

REQ-057: Chat must support `question_answers` for suggested photo questions.

REQ-058: Chat must support `privacy_level`.

REQ-059: Chat must support `ready_for_downstream`.

REQ-060: Chat must support `gallery_eligibility`.

REQ-061: Chat must support `memory_potential`.

REQ-062: Chat must support `privacy_sensitivity`.

REQ-063: Chat must preview vector handoff consequences.

REQ-064: Chat must preview boundary consequences.

### 10.6 Prompt Pair Requirements

REQ-065: Chat must support `gold_voice_edit` tasks.

REQ-066: Chat must support `grounded_prompt_pair_candidate` tasks.

REQ-067: Chat must detect SFT vs DPO mode.

REQ-068: Chat must never confuse the candidate prompt with Adam's active question.

REQ-069: Chat must support editing `prompt`.

REQ-070: Chat must support editing `content`.

REQ-071: Chat must support editing `chosen`.

REQ-072: Chat must support editing `rejected`.

REQ-073: Chat must support editing `context`.

REQ-074: Chat must support editing `voice_mode`.

REQ-075: Chat must support editing `system_prompt`.

REQ-076: Chat must support updating `failure_modes`.

REQ-077: Chat must support updating `preferred_failure_modes`.

REQ-078: Chat must support updating `response_rubric`.

REQ-079: Chat must support keeping generated or synthetic status explicit.

REQ-080: Chat must support delete-candidate intent as a proposed action, not silent deletion.

REQ-081: Chat must preview export gate status for prompt pairs.

REQ-082: Chat must show when a prompt pair is held for boundary or rejected-reason blockers.

REQ-083: Chat must be able to propose a rewrite without immediately applying it.

REQ-084: Chat must let Adam approve a rewrite before it becomes a draft field update.

### 10.7 Source Review Requirements

REQ-085: Chat must support `text_segment_review`.

REQ-086: Chat must support `text_segment_boundary_review`.

REQ-087: Chat must support `email_voice_sample`.

REQ-088: Chat must render source excerpts.

REQ-089: Chat must understand chunk boundaries.

REQ-090: Chat must understand selected spans when present.

REQ-091: Chat must support source authorship decisions.

REQ-092: Chat must support voice presence decisions.

REQ-093: Chat must support source privacy decisions.

REQ-094: Chat must support prompt-pair generation intent.

REQ-095: Chat must preview generate-pairs results before action.

REQ-096: Chat must not generate prompt pairs without confirmation.

### 10.8 Action Requirements

REQ-097: Chat backend must normalize all proposed actions.

REQ-098: Allowed action types must be explicit and finite.

REQ-099: `update_task_draft` may happen without confirmation when `apply_updates=true`.

REQ-100: `preview_submit` may happen without final submission.

REQ-101: `submit_task` must require confirmation.

REQ-102: `open_task` may navigate but must not mutate data.

REQ-103: `skip_task` must require confirmation.

REQ-104: `flag_task` must require confirmation.

REQ-105: `delete_candidate` must require confirmation.

REQ-106: `generate_pairs` must require confirmation.

REQ-107: `create_photo_context_task` must require confirmation unless it is a dry-run preview.

REQ-108: `export_dataset` must require confirmation and gate checks.

### 10.9 Submit Requirements

REQ-109: Chat must compute readiness based on existing required field logic.

REQ-110: Chat must expose missing required fields.

REQ-111: Chat must expose submit payload preview.

REQ-112: Chat must show a final confirmation button only when ready.

REQ-113: Chat must call existing `submit_task` backend logic.

REQ-114: Chat must create normal annotations.

REQ-115: Chat must update normal task status.

REQ-116: Chat must return normal receipts.

REQ-117: Chat must refresh queue data after submit.

REQ-118: Chat must move to a useful next task after submit.

### 10.10 Queue Intelligence Requirements

REQ-119: Chat must be aware of current selected queue mode.

REQ-120: Chat must be aware of current selected collection when relevant.

REQ-121: Chat must support "what should I work on next?"

REQ-122: Chat must rank work by bottleneck impact.

REQ-123: Chat must rank work by downstream readiness impact.

REQ-124: Chat must rank photo context tasks by retrieval gap impact.

REQ-125: Chat must rank prompt pairs by export blockers.

REQ-126: Chat must explain why it picked a task.

REQ-127: Chat must let Adam override task choice.

REQ-128: Chat must not silently switch tasks during an unfinished draft without warning.

## 11. Architecture Requirements

### 11.1 Backend Service Shape

The current `chat_operator.py` should be evolved into a clearer orchestration module.

Recommended modules:

- `services/chat_operator.py`
- `services/chat_context.py`
- `services/chat_actions.py`
- `services/chat_prompts.py`
- `services/chat_task_profiles.py`
- `services/chat_image_input.py`
- `services/chat_submit_preview.py`

The current single-file implementation is acceptable for the next small phase, but should be decomposed before it becomes too large.

### 11.2 Chat Task Profile

Introduce an internal `ChatTaskProfile` structure.

Suggested shape:

```ts
type ChatTaskProfile = {
  taskKind: 'photo_review' | 'prompt_response_review' | 'source_review' | 'export_review' | 'model_starter_review' | 'general_review'
  taskId: string
  taskHumanId: string
  title: string
  visibleWorkItem: Record<string, unknown>
  allowedFields: string[]
  requiredFields: string[]
  missingFields: string[]
  recommendedNextQuestion: string
  downstreamConsequences: Record<string, unknown>
  truthBoundaryPolicy: Record<string, unknown>
}
```

Backend should generate this profile.

Frontend should be able to render a summarized version of it.

### 11.3 Chat Turn Response Expansion

Current `ChatTurnResponse` should be expanded.

Proposed fields:

```ts
type ChatTurnResponse = {
  assistant_type: 'chat_operator'
  status: string
  assistant_message: string
  next_question?: string | null
  model_name: string
  reasoning_effort: string
  model_ready: boolean
  live_model_call_used: boolean
  active_task: JsonRecord
  task_profile: JsonRecord
  work_item_context: JsonRecord
  actions: ChatAction[]
  field_updates: JsonRecord
  field_update_explanations: ChatFieldUpdateExplanation[]
  draft_decisions: JsonRecord
  draft?: JsonRecord | null
  missing_fields: string[]
  ready_to_submit: boolean
  submit_payload?: JsonRecord | null
  submit_preview?: JsonRecord | null
  submitted_annotation?: Annotation | null
  next_task_recommendation?: JsonRecord | null
  safety_policy: JsonRecord
  error?: string | null
}
```

### 11.4 Action Schema

Move from loose `JsonRecord[]` actions to a typed schema.

Suggested shape:

```ts
type ChatAction = {
  type:
    | 'ask_question'
    | 'update_task_draft'
    | 'preview_submit'
    | 'submit_task'
    | 'open_task'
    | 'skip_task'
    | 'flag_task'
    | 'delete_candidate'
    | 'generate_pairs'
    | 'create_photo_context_task'
    | 'preview_export'
  label: string
  description?: string
  requires_confirmation: boolean
  confirmation_label?: string
  payload?: JsonRecord
  enabled: boolean
  disabled_reason?: string
}
```

### 11.5 Draft Update Explanation

Each field update should include an explanation.

Suggested shape:

```ts
type ChatFieldUpdateExplanation = {
  key: string
  label: string
  previous_value?: unknown
  next_value: unknown
  source: 'adam_reply' | 'model_inference' | 'heuristic' | 'existing_payload'
  confidence: 'low' | 'medium' | 'high'
  requires_adam_review: boolean
  truth_boundary: 'visible_fact' | 'adam_memory' | 'source_truth' | 'machine_inference' | 'synthetic_review'
}
```

### 11.6 Model Prompt Architecture

The live model prompt should be generated from:

1. Developer policy.
2. Task kind policy.
3. Work item context.
4. Current draft decisions.
5. Missing fields.
6. Allowed update schema.
7. Recent chat.
8. Latest Adam message.
9. Available image input.
10. Action constraints.

The prompt should include explicit "do not ask Adam to answer the source prompt" language for prompt-response tasks.

The prompt should include explicit "ask Adam about the image" language for photo tasks.

The prompt should include explicit "do not create memory claims from model inference" language for photo tasks.

### 11.7 Model Output Validation

The backend should validate:

- JSON parses.
- Output is object-shaped.
- `assistant_message` is non-empty.
- `next_question` is Adam-facing.
- `field_updates` are allowed.
- `actions` are allowed.
- confirmation requirements are enforced.
- prompt-response tasks do not reuse source prompt as Adam question.
- photo tasks do not assert private identity as fact without Adam confirmation.
- submit is not ready if required fields are missing.

### 11.8 Multimodal Input

The model should receive image input for photo tasks when possible.

Image input priority:

1. local display derivative
2. local thumbnail derivative
3. local source mirror if image and under size cap
4. no image input, but use metadata and visible UI context

Image input must respect:

- storage root path safety
- content type starts with `image/`
- byte size cap
- preview access token rules for frontend
- no external fetches outside established preview routes

### 11.9 Provider Configuration

Chat should have separate model settings.

Required settings:

- `CHAT_MODEL`, optional, default to `TEXT_GENERATION_MODEL`
- `CHAT_REASONING_EFFORT`, default `medium`
- `CHAT_MAX_OUTPUT_TOKENS`, default `1600`
- `CHAT_IMAGE_INPUT_ENABLED`, default `true`
- `CHAT_LIVE_CALLS_ENABLED`, optional, default to `TEXT_GENERATION_LIVE_CALLS_ENABLED`

Current implementation only adds `CHAT_REASONING_EFFORT`.

Next phase should decide whether Chat needs independent live gating.

## 12. UI Requirements

### 12.1 Layout

The Chat tab should keep the three-column app shell:

- left navigation
- task queue
- workbench

The workbench should contain:

1. header
2. work item context panel
3. chat thread
4. action/proof bar
5. draft update summary
6. composer

### 12.2 Photo Context Panel

Photo panel should show:

- image preview
- title
- task ID
- task reason
- visible people draft
- objects/scene draft
- place/date/event draft
- open questions
- privacy boundary status
- downstream readiness preview

Future enhancement:

- visually highlight regions or objects when segmentation exists
- let Chat ask "who is this person?" by referencing a region
- let Adam click an area and answer about that area

### 12.3 Prompt Pair Context Panel

Prompt pair panel should show:

- artifact mode
- source prompt
- draft response or chosen response
- rejected response when DPO
- context note
- voice mode
- source photo thumbnail if present
- export gate blockers
- DPO rejected reason status

### 12.4 Conversation Thread

The thread should show:

- Adam messages
- assistant messages
- status label for each model turn
- applied field updates
- proposed but not applied updates
- action chips
- errors and fallback notices

### 12.5 Draft Update Proof

Draft proof should show:

- changed field key
- readable label
- new value summary
- previous value summary where useful
- whether it came from Adam reply or model inference
- whether it requires review

### 12.6 Composer

Composer should:

- support multiline input
- support submit with Cmd+Enter
- preserve text on failure
- disable while request is in-flight
- show active question above or near input
- optionally support "apply without sending" for selected model rewrite

### 12.7 Action Buttons

Action area should include:

- Open ticket
- Preview submit
- Confirm submit
- Skip
- Flag
- Delete candidate when applicable
- Generate pairs when applicable
- Next recommended task

Destructive or state-moving actions must require confirmation.

### 12.8 Mobile Behavior

Mobile should:

- stack context panel above chat
- keep image visible
- avoid horizontal overflow
- keep composer accessible
- make action buttons full width
- avoid overlapping text and controls

## 13. Data Requirements

### 13.1 TaskDraft

Chat should continue to use `TaskDraft`.

Potential additions:

- `source`: `form` or `chat`
- `chat_session_id`
- `field_update_log`
- `last_chat_turn_id`

These can be added later if needed.

### 13.2 Chat Turn Persistence

Current chat history is browser-local.

Next phase should decide whether to persist chat turns.

Recommended: persist lightweight chat turns.

Potential table:

```py
class ChatTurn(SQLModel, table=True):
    id: str
    task_id: str
    user_id: str
    role: str
    content: str
    model_name: Optional[str]
    live_model_call_used: bool
    field_updates: Dict[str, Any]
    actions: List[Dict[str, Any]]
    safety_flags: Dict[str, Any]
    created_at: datetime
```

Reasons to persist:

- auditability
- session recovery
- quality review
- debugging model behavior
- future training/eval data for the workbench agent

Reasons not to persist full text:

- privacy
- storage size
- private family context

Recommendation:

- persist summarized operational turns by default
- allow sensitive text redaction
- do not store raw model prompts unless debug flag is enabled

### 13.3 Work Item Context

Backend should return a normalized `work_item_context`.

Frontend should not reconstruct too much from raw payloads.

This makes tests easier and avoids duplicating task-kind logic.

### 13.4 Provenance

Every chat-generated draft update should include provenance.

At minimum:

- source: `chat`
- model status
- model name if live
- field update explanation
- timestamp
- task ID

## 14. Safety Requirements

### 14.1 Source Truth

Chat must not mark machine inference as archival source.

Chat must not mark generated text as archival source.

Chat must not mark Adam memory as source quote.

Chat must not mark OCR as source quote unless OCR review says it is accepted.

### 14.2 Privacy

Chat must ask boundary questions before downstream use.

Chat must not make sealed/private-sensitive material retrievable without explicit field decisions.

Chat must surface privacy blockers.

Chat must preserve redaction requirements.

### 14.3 Identity

For photos, Chat can say "this appears to show..."

For private people, Chat should ask Adam to identify.

Chat should not assert identity from model vision alone.

### 14.4 Voice

Chat must not imitate Charles in assistant messages.

Chat can help edit Charles-style training examples.

Chat must label synthetic reconstruction as synthetic or Adam expert reconstruction.

Chat must preserve the boundary between editing a training example and pretending to be Charles.

### 14.5 Action Safety

Submit requires confirmation.

Delete requires confirmation.

Skip requires confirmation.

Flag requires confirmation.

Generate pairs requires confirmation.

Export requires confirmation and gates.

## 15. Implementation Phases

### 15.1 Phase 1: Harden Current Chat Foundation

Objective:

Make the current Chat tab reliable and task-aware enough to use daily.

Scope:

- typed action schema
- backend `task_profile`
- backend `work_item_context`
- missing field list in response
- submit preview in response
- field update explanations
- regression tests for Adam-facing questions
- browser tests for photo and prompt pair panels

Implementation tasks:

1. Add typed `ChatAction` schema.
2. Add typed `ChatFieldUpdateExplanation` schema.
3. Add `task_profile` to `ChatTurnResponse`.
4. Add `work_item_context` to `ChatTurnResponse`.
5. Move frontend context-panel rendering to backend normalized data.
6. Add missing field display in Chat UI.
7. Add submit preview area in Chat UI.
8. Add source-prompt leakage tests for SFT and DPO.
9. Add photo identity question tests.
10. Add browser test for photo context.
11. Add browser test for SFT context.
12. Add browser test for DPO context.

Exit criteria:

- Chat can be used for photo tasks without opening the full form.
- Chat can be used for SFT review without asking Adam to answer the prompt.
- Chat can be used for DPO review without losing chosen/rejected separation.
- Tests pass.

### 15.2 Phase 2: Conversational Photo Context Completion

Objective:

Make Chat a first-class photo review workflow.

Scope:

- image-grounded questions
- visible facts
- people/place/date/event
- memory association
- open questions
- privacy
- downstream readiness
- submit preview

Implementation tasks:

1. Build `photo_chat_task_profile`.
2. Include suggested questions from `vision_draft` and photo context plan.
3. Include retrieval-gap origin when present.
4. Include existing metadata profile when present.
5. Include draft progress and missing fields.
6. Add model prompt policy for photo review.
7. Add parser rules for people/place/date/event.
8. Add parser rules for privacy and downstream readiness.
9. Add UI proof rows for photo fields.
10. Add submit projection preview to Chat.
11. Add "ready to submit" state only when projection is acceptable.
12. Add "show full form" escape hatch.

Exit criteria:

- Adam can complete a typical photo context task through Chat.
- Submit creates the same downstream records as form submit.
- Projection matches form path.
- No model-only identity is promoted as fact.

### 15.3 Phase 3: Conversational SFT/DPO Editing

Objective:

Make Chat a high-quality training-data editor.

Scope:

- SFT response rewrite
- DPO chosen/rejected contrast
- rubric editing
- failure modes
- export gate blockers
- source photo boundary blockers

Implementation tasks:

1. Build `prompt_pair_chat_task_profile`.
2. Include export preflight blockers.
3. Include DPO repair projection.
4. Include prompt pair audit context.
5. Add model prompt policy for SFT review.
6. Add model prompt policy for DPO review.
7. Add proposed rewrite flow.
8. Add "apply rewrite" action.
9. Add "keep current response" action.
10. Add "mark rejected reason" action.
11. Add field update explanations for rubric changes.
12. Add UI diff between old and proposed response.
13. Add test for SFT rewrite proposal not auto-applied.
14. Add test for DPO failure mode update.
15. Add test for source boundary blocker display.

Exit criteria:

- Adam can refine a prompt-response candidate through discussion.
- Chat can apply approved rewrite to draft.
- DPO pairs get meaningful rejected-side reasons.
- Export gate status is visible.

### 15.4 Phase 4: Queue-Level Operator

Objective:

Let Chat intelligently decide what to work on next.

Scope:

- next task recommendation
- bottleneck ranking
- worklist awareness
- queue progress
- session planning

Implementation tasks:

1. Build `/api/chat/next-task` or add next-task intent to `/chat/turn`.
2. Use photo context progress.
3. Use prompt pair audit.
4. Use downstream readiness.
5. Use current filters.
6. Rank by impact.
7. Explain recommendation.
8. Add "open recommended task" action.
9. Add "skip recommendation" action.
10. Add post-submit next-task recommendation.

Exit criteria:

- Chat can answer "what should I work on next?"
- Recommendation is grounded in existing readiness/bottleneck data.
- Adam can override easily.

### 15.5 Phase 5: Persisted Chat Sessions And Audit

Objective:

Make Chat durable and auditable.

Scope:

- chat sessions
- chat turns
- field update logs
- prompt/model observability
- redaction policy

Implementation tasks:

1. Add chat session model.
2. Add chat turn model.
3. Persist assistant/user turns.
4. Persist field update explanations.
5. Persist safety flags.
6. Do not persist raw image data.
7. Add debug-only prompt logging.
8. Add UI session history.
9. Add task-level chat transcript drawer.

Exit criteria:

- Browser refresh does not erase important chat context.
- Audit trail shows how draft fields were produced.
- Sensitive raw model prompts are not stored by default.

## 16. Detailed Testing Plan

### 16.1 Backend Unit Tests

Add tests for:

- task kind detection
- photo work surface creation
- prompt pair work surface creation
- source review work surface creation
- allowed field filtering
- unknown field rejection
- empty value rejection
- source-prompt reuse detection
- source-prompt action-label sanitization
- photo fallback question selection
- SFT fallback question selection
- DPO fallback question selection
- image data URL creation from display derivative
- image data URL creation from thumbnail derivative
- image data URL creation from source mirror
- no image data URL for non-image content type
- no image data URL for unsafe path
- no image data URL for oversize file
- deterministic fallback after live model failure
- no second live call during fallback
- submit readiness with missing fields
- submit readiness with completed fields
- confirmed submit path

### 16.2 Backend Integration Tests

Add tests for:

- `/api/chat/turn` with photo task and empty message returns photo question
- `/api/chat/turn` with photo task and Adam identity answer updates people fields
- `/api/chat/turn` with photo task and memory answer updates Adam context
- `/api/chat/turn` with photo task and privacy answer updates privacy
- `/api/chat/turn` with SFT task returns review question
- `/api/chat/turn` with DPO task returns contrast question
- `/api/chat/turn` with DPO feedback updates failure modes
- `/api/chat/turn` with ready but missing fields refuses submit
- `/api/chat/turn` with ready and complete fields prepares submit payload
- `/api/chat/turn` with confirm submit creates annotation
- `/api/chat/turn` does not mutate source objects
- `/api/chat/turn` preserves task status before confirmation

### 16.3 Frontend Unit Or Component Tests

Add tests for:

- Chat renders no-task empty state.
- Chat renders photo context panel.
- Chat renders SFT context panel.
- Chat renders DPO context panel.
- Chat renders source review context panel.
- Chat renders draft update proof.
- Chat disables confirm submit when not ready.
- Chat enables confirm submit when ready.
- Chat preserves input after failed request.
- Chat resets messages on task switch.
- Chat does not lose task selection after refresh.

### 16.4 Browser Tests

Add Playwright tests for:

- Chat nav is first item above Intake.
- Photo task opens with image preview.
- Photo initial assistant question is Adam-facing.
- Photo chat turn can update draft fields.
- Prompt pair opens with prompt and response cards.
- SFT initial assistant question asks for review/edit, not source prompt answer.
- DPO initial assistant question asks about chosen/rejected contrast.
- Source prompt leakage regression using "How did you learn to cook?"
- Confirm submit remains disabled until backend readiness.
- Confirm submit calls `/api/chat/turn` with `confirm_submit=true`.
- Submitted annotation banner appears after confirmed submit.

### 16.5 Manual Acceptance Tests

Manual photo test:

1. Open Chat.
2. Select a photo context task.
3. Verify image is visible.
4. Verify Chat asks who/what/where/context question.
5. Answer: "That is Cathryn in the kitchen in Maine."
6. Verify draft fields update people/place/context appropriately.
7. Answer privacy boundary.
8. Preview submit.
9. Confirm submit.
10. Verify annotation, boundary, metadata profile, and memory/vector consequences.

Manual SFT test:

1. Open Chat.
2. Select SFT prompt pair.
3. Verify prompt and draft response are visible.
4. Verify Chat asks how the response should change.
5. Say response feels generic and needs a concrete image.
6. Verify Chat proposes rewrite or updates context without auto-submitting.
7. Approve rewrite.
8. Verify draft `content` changes.
9. Verify export gate preview.
10. Confirm submit when ready.

Manual DPO test:

1. Open Chat.
2. Select DPO pair.
3. Verify prompt, chosen, rejected are visible.
4. Verify Chat asks about contrast.
5. Say rejected is too generic and misses Charles' cadence.
6. Verify `failure_modes` or `response_rubric` update.
7. Verify rejected response remains separate.
8. Verify DPO rejected reason blocker clears.
9. Confirm submit when ready.

Manual source review test:

1. Open Chat.
2. Select text source review.
3. Verify source excerpt is visible.
4. Ask Chat what it needs.
5. Answer authorship/privacy/generate-pairs intent.
6. Verify draft fields update.
7. Preview generated pairs.
8. Confirm generate pairs only when ready.

## 17. Observability

Chat should expose enough detail to debug behavior.

Required observability fields:

- model name
- reasoning effort
- live model call used
- model ready
- fallback status
- sanitization flags
- image input attached yes/no
- image input source type
- field update keys
- rejected field update keys
- action types
- ready-to-submit state
- missing fields
- submit preview hash when applicable

Backend logs should not expose secrets.

Frontend should show user-friendly status only.

Debug panels can show raw payloads behind a disclosure.

## 18. Metrics

Suggested product metrics:

- chat turns per submitted task
- average time to submit photo context task
- average time to submit prompt pair
- percentage of chat turns that update drafts
- percentage of chat turns that require fallback
- percentage of model outputs sanitized
- number of photo tasks completed via Chat
- number of SFT/DPO tasks completed via Chat
- number of export blockers cleared via Chat
- number of manual form opens from Chat
- number of abandoned chat sessions

Suggested quality metrics:

- DPO pairs with non-empty rejected reason
- SFT examples passing export gate
- photo context tasks with people/place/date/context/boundary
- reviewed memory records created from photo context
- vector handoff eligible records
- source boundary blockers resolved

## 19. Open Product Questions

1. Should Chat have independent live call gating from text generation?
2. Should Chat sessions persist by default?
3. Should raw chat transcripts be stored, summarized, or not stored?
4. Should photo image input use full display derivative or thumbnail by default?
5. Should Chat support selecting regions of an image?
6. Should Chat propose edits as patches before applying?
7. Should Chat become the default first screen?
8. Should Chat hide the queue for a more focused mode?
9. Should Chat support voice input from Adam?
10. Should Chat support "show me why" explanations for every field update?
11. Should Chat support batch review?
12. Should Chat auto-advance after submit?
13. Should Chat produce a YAML view of the current draft?
14. Should Chat support comparing current draft to export JSONL?
15. Should Chat be able to create new tasks from conversation?

## 20. Risks

### 20.1 Model Misinterpretation

Risk:

The model may misclassify Adam's answer or update the wrong field.

Mitigation:

- field filtering
- field update explanations
- draft proof
- explicit apply/confirm for larger rewrites
- tests with representative examples

### 20.2 Source Prompt Leakage

Risk:

The model may ask Adam the training prompt.

Mitigation:

- prompt policy
- backend sanitizer
- regression tests
- UI labels that show prompt as review material

### 20.3 False Photo Identity

Risk:

The model may identify a person incorrectly.

Mitigation:

- ask Adam for identity
- label model observations as inference
- do not promote identity without Adam answer

### 20.4 Silent Data Mutation

Risk:

Chat could mutate the database in surprising ways.

Mitigation:

- draft-first
- explicit confirmation
- action schemas
- reuse existing submit paths
- tests for status not changing before confirm

### 20.5 UI Complexity Returning

Risk:

Chat could become another cluttered panel.

Mitigation:

- one visible work item
- one question
- compact proof
- advanced details behind disclosures
- keep form as secondary path

## 21. Definition Of Done For Next Major Phase

The next major phase is done when:

- Adam can complete at least one photo context task entirely through Chat.
- Adam can complete at least one SFT review task entirely through Chat.
- Adam can complete at least one DPO review task entirely through Chat.
- Chat never asks Adam to answer a source prompt in prompt-response review.
- Chat uses image input for local mirrored photo previews when available.
- Chat previews submit consequences.
- Chat requires confirmation before submit.
- Chat submit creates the same backend records as form submit.
- The deterministic API suite passes.
- Web typecheck passes.
- Web production build passes.
- Browser tests cover photo, SFT, DPO, and source-prompt leakage.
- Manual acceptance tests have been run against real local data.

## 22. Recommended Next Engineering Tickets

### Ticket 1: Typed Chat Response Schema

Add typed actions, task profile, work item context, missing fields, submit preview, and field update explanations.

### Ticket 2: Backend Task Profile Builder

Move task-kind logic into a dedicated task profile builder.

### Ticket 3: Chat Context Panel From Backend Data

Refactor frontend context panel to render normalized backend work item context.

### Ticket 4: Photo Chat Completion Flow

Implement robust photo field extraction and submit projection preview.

### Ticket 5: Prompt Pair Chat Rewrite Flow

Implement proposed rewrite, diff, apply, and rubric updates.

### Ticket 6: DPO Rejected Reason Flow

Implement DPO-specific feedback capture and blocker-clearing behavior.

### Ticket 7: Chat Browser Test Suite

Add Playwright coverage for Chat flows.

### Ticket 8: Persisted Chat Session Prototype

Add optional chat session persistence with privacy-conscious defaults.

### Ticket 9: Queue Recommendation

Let Chat recommend the next highest-leverage task using existing readiness services.

### Ticket 10: Observability And Debug Payloads

Add safe debug disclosure for task profile, model status, actions, and submit preview.

## 23. Appendix: Current Files To Watch

Backend:

- `apps/api/app/services/chat_operator.py`
- `apps/api/app/routers/chat.py`
- `apps/api/app/schemas.py`
- `apps/api/app/services/operator_assistant.py`
- `apps/api/app/services/photo_context_projection.py`
- `apps/api/app/services/photo_context_progress.py`
- `apps/api/app/services/photo_context_review_pack.py`
- `apps/api/app/services/photo_memory.py`
- `apps/api/app/services/photo_memory_drafts.py`
- `apps/api/app/services/prompt_pair_audit.py`
- `apps/api/app/services/prompt_pair_dpo.py`
- `apps/api/app/services/pair_export.py`
- `apps/api/app/services/gold_voice.py`
- `apps/api/app/services/source_review.py`
- `apps/api/app/services/pair_generation.py`
- `apps/api/app/services/vision.py`

Frontend:

- `apps/web/src/components/ChatWorkbench.tsx`
- `apps/web/src/app/page.tsx`
- `apps/web/src/app/globals.css`
- `apps/web/src/lib/api.ts`
- `apps/web/src/lib/types.ts`
- `apps/web/src/components/TaskWorkbench.tsx`
- `apps/web/src/components/DownstreamReadinessPanel.tsx`
- `apps/web/src/components/ExportDryRunPanel.tsx`
- `apps/web/src/components/ModelStarterPanel.tsx`

Tests:

- `apps/api/tests/test_chat_operator.py`
- `apps/api/tests/test_ralph_phase2_photo_spine.py`
- `apps/api/tests/test_ralph_phase3_prompt_pair_audit.py`
- `apps/api/tests/test_dataset_exports.py`
- `apps/api/tests/test_task_submit.py`
- `apps/web/tests/readiness-smoke.spec.ts`

## 24. Appendix: Verification Commands

Backend focused:

```bash
docker exec chas-api-1 sh -lc 'OPENAI_API_KEY= TEXT_GENERATION_LIVE_CALLS_ENABLED=false python -m pytest tests/test_chat_operator.py'
```

Backend full deterministic:

```bash
docker exec chas-api-1 sh -lc 'OPENAI_API_KEY= TEXT_GENERATION_LIVE_CALLS_ENABLED=false python -m pytest'
```

Frontend typecheck:

```bash
npm --prefix apps/web run typecheck
```

Frontend build:

```bash
npm --prefix apps/web run build
```

Browser smoke:

```bash
WEB_BASE_URL=http://localhost:3002 npx --prefix apps/web playwright test
```

Manual local app:

```bash
npm --prefix apps/web run dev -- --port 3002
```

## 25. Appendix: Prompt Policy Snippets

Prompt-response task policy:

```text
Adam is reviewing this prompt-response candidate.
The candidate prompt is source material displayed for review.
Never ask Adam to answer the candidate prompt.
Ask Adam to judge, edit, keep, reject, or explain the candidate prompt and response.
```

Photo task policy:

```text
Adam is reviewing a photo.
Ask about visible facts, identity, place, time, memory, uncertainty, and boundary.
Do not turn model visual guesses into Adam memory.
Do not assert private identities without Adam confirmation.
```

DPO task policy:

```text
Adam is reviewing a preference pair.
Ask about the contrast between chosen and rejected.
Capture why rejected is weaker.
Keep chosen and rejected separate.
Update rubric and failure modes only from Adam-approved feedback.
```

Source task policy:

```text
Adam is reviewing source material.
Ask about authorship, boundary, voice presence, context, spans, and downstream usefulness.
Do not generate pairs or promote source material without explicit confirmation.
```

## 26. Appendix: Acceptance Test Matrix

| Area | Scenario | Expected Result |
| --- | --- | --- |
| Photo | Empty turn | Adam-facing photo question |
| Photo | Identity answer | People draft update |
| Photo | Place answer | Place draft update |
| Photo | Memory answer | Adam context update |
| Photo | Privacy answer | Privacy boundary draft update |
| Photo | Submit before complete | Missing fields shown |
| Photo | Submit after complete | Existing submit path |
| SFT | Empty turn | Review/edit question |
| SFT | Source prompt leak | Sanitized question |
| SFT | Rewrite feedback | Proposed rewrite |
| SFT | Approve rewrite | Content draft update |
| DPO | Empty turn | Chosen/rejected contrast question |
| DPO | Generic rejected feedback | Failure mode update |
| DPO | Missing rejected reason | Blocker shown |
| DPO | Ready submit | Existing submit path |
| Source | Empty turn | Source boundary/context question |
| Source | Generate pair intent | Preview first |
| Queue | What next | Recommendation with reason |
| Safety | Unknown field | Dropped |
| Safety | Delete intent | Confirmation required |
| Safety | Model failure | Deterministic fallback |

## 27. Closing Product Direction

The next version of Chat should feel less like a generic LLM endpoint and more like the central operating layer of CharlesOps.

It should hold the elegance of Adam editing a single YAML file, while handling the complexity of photos, documents, memories, prompt pairs, DPO data, privacy, retrieval, and exports.

The design target is not "chatbot in the app."

The design target is "smart workbench operator that knows the object, asks the next right question, updates the right draft fields, and moves the system forward only when Adam confirms."
