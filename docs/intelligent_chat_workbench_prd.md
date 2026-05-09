# PRD: Intelligent Chat Workbench for CharlesOps

Status: Draft for next implementation phase
Date: 2026-05-08
Repo: `/Users/arotmil/dev/chas`
Primary app: CharlesOps workbench
Primary surface: new Chat tab above Intake
Primary user: Adam
Primary objective: make the workbench feel like a simple, intelligent editorial partner instead of a cluttered data-entry system

## 1. Executive Summary

The current CharlesOps workbench has begun moving toward a better interaction model.

The app now has a Chat tab.

The Chat tab can call a real LLM.

It can inspect the current workbench task.

It can display a richer context panel for photo tasks and SFT/DPO prompt-response tasks.

It has guardrails to avoid asking Adam the same questions that were originally meant to be answered in Charles's voice.

This is a strong foundation, but it should now become a true workbench operator.

The next product goal is not just "chat in the app."

The goal is an intelligent task-completion layer that can:

- choose a useful work item;
- show Adam the relevant source material;
- ask one Adam-facing question at a time;
- understand Adam's freeform answer;
- decide whether to probe, rewrite, or update data;
- preview the changes it wants to make;
- update the database through explicit, validated actions;
- move the workbench ticket forward only when it has enough information;
- preserve provenance so later training data can be trusted.

The product should retain the elegance Adam liked in the original YAML workflow.

The app should not become a large form with a chat box bolted onto it.

The chat should become the primary interface for authoring and refining training data, while the structured workbench remains the source of truth underneath.

The ideal experience is simple:

Adam opens Chat.

The app shows one photo, excerpt, or prompt-response candidate.

The assistant asks one useful question.

Adam answers naturally.

The assistant interprets the answer, asks a follow-up only if needed, then drafts structured updates.

Adam can review the proposed update.

When Adam says ready, the app writes the update through the same task and draft machinery used elsewhere.

The underlying system remains rigorous, auditable, and testable.

## 2. Product Thesis

The current UI feels cluttered because too much of the internal workflow is exposed as direct manipulation.

The real work is editorial and interpretive.

Adam is not trying to operate a database.

Adam is trying to supply memory, taste, judgment, context, and correction.

The workbench should let Adam do that in plain language.

The database should still receive structured outputs.

The best interface is therefore a hybrid:

- Chat is the conversational editorial interface.
- Task drafts are the structured staging area.
- Tickets are the work queue and state machine.
- Assets, excerpts, and annotations are evidence.
- Exports are generated only from reviewed, provenance-rich data.

The chat should make the structured system feel simpler, not less precise.

## 3. Current Implementation Snapshot

This section documents the current state as of this PRD.

The current code already includes the main scaffolding for the next phase.

The frontend includes a new Chat tab in `apps/web/src/app/page.tsx`.

The tab appears above Intake in the left navigation.

The main chat UI is implemented in `apps/web/src/components/ChatWorkbench.tsx`.

The web client calls `sendChatTurn` from `apps/web/src/lib/api.ts`.

The backend exposes `POST /api/chat/turn` through `apps/api/app/routers/chat.py`.

The chat operator logic lives in `apps/api/app/services/chat_operator.py`.

The shared request and response schemas live in `apps/api/app/schemas.py`.

The API includes a `CHAT_REASONING_EFFORT` setting with a default of `medium`.

The backend has deterministic tests in `apps/api/tests/test_chat_operator.py`.

The latest pass improved several important behaviors.

The chat prompt is now Adam-facing.

It is instructed not to ask Adam to answer a source prompt that was originally meant for Charles.

It can detect likely source-prompt reuse and replace it with an Adam-facing review question.

Photo tasks can include a local mirrored image preview as a data URL in the model input.

Prompt-response tasks can be shown as review surfaces instead of raw task text.

The frontend context panel can display photo previews, visible people, visible objects, scene information, and prompt-response candidates.

The deterministic API test suite passed after the latest changes.

The web build passed after the latest changes.

Browser smoke testing confirmed the new context panel renders.

This PRD assumes those changes are the baseline.

## 4. Current Product Gap

The product is still closer to a smart chat prototype than a complete operator.

The most important gap is that the LLM can talk about the task, but the action model is still too shallow.

The chat must become able to perform bounded, validated work.

The next most important gap is persistence.

Chat history, decisions, proposed updates, and action outcomes need to survive refreshes and become audit records.

The third major gap is task intelligence.

The chat should understand the different work surfaces:

- photo context;
- source excerpt review;
- SFT prompt-response drafting;
- DPO pair review;
- voice refinement;
- export readiness;
- metadata enrichment.

The fourth major gap is UI focus.

The Chat tab should make the workbench feel calmer.

It should hide complexity until it is needed.

It should display only the current work item, the immediate question, and the proposed structured update.

The fifth major gap is verification.

The current tests prove the chat does not do the most obvious wrong thing.

The next tests must prove the chat can safely update the data model.

## 5. North Star Experience

Adam opens the app.

Adam clicks Chat.

The chat says something like:

> I am reviewing photo context ticket TASK_PHOTO_CONTEXT_000736. I can see the image and the current draft. I need to confirm who is pictured and why this image matters before I create durable context.

The app shows the photo next to the conversation.

The assistant asks:

> Who is the person in the left side of the photo, and what should Charles remember about this moment?

Adam answers naturally.

The assistant extracts structured fields:

- people;
- place;
- approximate time;
- event;
- emotional salience;
- retrieval cues;
- uncertainty;
- private details;
- whether the photo can be used for training context.

If a required field is missing, the assistant asks one follow-up.

If enough is known, the assistant says:

> I think this is ready. I will add the person, place, event summary, and retrieval cues below. Do you want to submit this ticket?

The app shows a diff preview.

Adam says:

> Ready.

The assistant submits the structured update through the same backend pathway as the manual workbench.

The task advances.

The assistant moves to the next useful ticket.

For DPO or SFT review, the chat should not ask Adam to answer the prompt.

Instead, it should show the prompt and candidate response and ask:

> Does this response sound like Charles? What would you change about the voice, specificity, or memory?

Adam can say:

> The first sentence is too generic. Keep the cooking detail, but make it more reflective and less instructional.

The assistant rewrites the candidate, explains the change, and asks for approval.

The final data is stored as reviewed training material with provenance.

## 6. Goals

Goal 1: Make Chat the simplest path for completing workbench tickets.

Goal 2: Preserve the structured task and draft system as the source of truth.

Goal 3: Let Adam answer naturally instead of filling many fields manually.

Goal 4: Ensure every model action is explicit, typed, validated, and auditable.

Goal 5: Support real multimodal review of photos.

Goal 6: Support high-quality SFT and DPO refinement loops.

Goal 7: Reduce UI clutter by moving most task complexity into progressive disclosure.

Goal 8: Improve trust through previews, diffs, provenance, and reversible actions.

Goal 9: Make testing strong enough that model-driven updates are safe.

Goal 10: Keep the experience aligned with the simple YAML workflow Adam liked.

## 7. Non-Goals

This phase does not need to rebuild the whole workbench UI.

This phase does not need to replace every existing manual workflow.

This phase does not need autonomous bulk submission without Adam review.

This phase does not need model training itself.

This phase does not need a production-grade agent memory system.

This phase does not need perfect computer vision.

This phase does not need direct editing of raw YAML files.

This phase does not need a new database engine.

This phase does not need to support multiple human reviewers.

This phase does not need to redesign export formats unless the export preview reveals blocking gaps.

## 8. Product Principles

Principle 1: Adam is the addressee.

The chat is talking to Adam.

It is not asking Charles to answer a prompt.

It is not roleplaying as Charles unless explicitly previewing a candidate response.

Principle 2: Show the work item before asking.

For photo tasks, show the image.

For prompt-response tasks, show the prompt and candidate response.

For source text tasks, show the excerpt.

For DPO tasks, show chosen and rejected candidates side by side.

Principle 3: Ask one question at a time.

The assistant can internally track many missing fields.

It should ask only the highest-value next question.

Principle 4: Prefer editorial flow over forms.

The structured fields are important.

Adam should not feel like he is filling a spreadsheet.

Principle 5: Draft first, then submit.

The model can propose updates freely.

Submission or task advancement requires an explicit confirmation path.

Principle 6: No hidden writes.

Every database mutation made by chat should be traceable to a user turn, model proposal, action request, and backend validation.

Principle 7: No fake certainty.

If the model infers something from an image, it should mark it as an inference.

If Adam confirms it, then it can become confirmed context.

Principle 8: Provenance matters.

Training data should know what source material and human decision produced it.

Principle 9: Reversibility matters.

The system should make it easy to undo or supersede a chat-generated update.

Principle 10: The workbench should become calmer as it becomes smarter.

More intelligence should reduce visible clutter.

It should not add another dense control surface.

## 9. Glossary

Adam: the human operator and reviewer using the workbench.

Charles: the intended digital twin or end-state voice being modeled.

Chat: the conversational workbench interface.

Ticket: a unit of work in the database.

Task: same general concept as ticket, usually represented by current backend task objects.

Task draft: structured staged data produced before final submission.

Work surface: the specific content type the chat is helping review.

Photo context: human-reviewed context attached to a photo or image asset.

SFT: supervised fine-tuning example, usually a prompt and ideal response.

DPO: preference pair, usually a prompt plus chosen and rejected responses.

Candidate response: model-generated or draft response that Adam is reviewing.

Source prompt: a prompt intended to elicit a Charles-style answer, not a question Adam should answer directly.

Adam-facing question: a question asking Adam to provide context, critique, validation, or correction.

Action: a typed operation proposed by the model and executed by backend code.

Action preview: a UI diff showing what will change if Adam confirms.

Provenance: metadata that records source material, model suggestions, user decisions, and mutation history.

## 10. Current System Map

The app has a backend API service.

The app has a React frontend.

The app uses a database-backed workbench model.

The workbench exposes tickets or tasks to the user.

Existing task flows include intake, review, and export-oriented operations.

The new chat route provides an LLM-driven turn endpoint.

The current chat route accepts the current task context and message history.

The current chat response can return a reply and structured draft-like data.

The current frontend renders chat messages and a context panel.

The current frontend does not yet persist long-lived chat sessions as first-class records.

The current frontend does not yet show rich action diffs for model-proposed database changes.

The current backend does not yet expose a robust action execution contract for chat.

The current system has enough foundation to build the next phase without starting over.

## 11. Users and Jobs To Be Done

Primary user: Adam.

Adam wants to turn journals, source documents, photos, and memories into high-quality training material.

Adam wants an LLM to help synthesize, draft, and organize that material.

Adam wants to retain final editorial judgment.

Adam wants to avoid sprawling UI complexity.

Adam wants the system to build a durable context layer as a byproduct of review.

Adam wants future agents and models to visually understand and remember photos and their associations.

Adam wants to refine voice examples until they feel right.

Adam wants to preview and trust exports.

Adam wants a workflow that feels closer to editing one good text file than operating an enterprise dashboard.

## 12. Core User Stories

Story 1: As Adam, I want Chat to pick a useful photo ticket and show me the photo so I can answer context questions naturally.

Story 2: As Adam, I want Chat to ask me who is in a photo, where it was taken, and why it matters so that the photo becomes meaningful training context.

Story 3: As Adam, I want Chat to distinguish between what it sees and what I confirm so the database does not store guesses as facts.

Story 4: As Adam, I want Chat to show me a prompt and candidate response so I can refine the voice.

Story 5: As Adam, I want Chat to rewrite a response based on my critique so I can quickly converge on a better SFT example.

Story 6: As Adam, I want Chat to show DPO chosen and rejected responses side by side so I can say which one is better and why.

Story 7: As Adam, I want Chat to create a structured draft from the conversation so I do not have to fill every field manually.

Story 8: As Adam, I want to review a proposed database update before it is submitted.

Story 9: As Adam, I want Chat to move the ticket forward only after I confirm.

Story 10: As Adam, I want Chat history to persist so I can return later without losing context.

Story 11: As Adam, I want the app to remember why a training example was accepted or rejected.

Story 12: As Adam, I want export readiness to be understandable through Chat.

Story 13: As Adam, I want the system to be honest when it does not know something.

Story 14: As Adam, I want the product to feel simpler after adding Chat, not more complex.

## 13. Work Surface Types

The chat should support distinct work surfaces.

Each work surface needs a tailored display and a tailored question strategy.

The model should receive a normalized context packet that identifies the work surface.

The frontend should render a normalized context panel that matches the work surface.

The backend should validate actions according to the work surface.

## 14. Work Surface: Photo Context

Photo context tasks are about making images meaningful.

The photo itself must be visible in the Chat tab.

The model should receive the image when possible.

The model may describe visible features, but must treat them as unconfirmed until Adam confirms.

The assistant should ask about:

- who is pictured;
- where the photo was taken;
- when or roughly when it was taken;
- what event or situation it captures;
- why the photo matters;
- what Charles should remember from it;
- what emotional tone is associated with it;
- what objects or details are important;
- whether any details are private or should be excluded;
- how the image should be retrieved later.

The assistant should avoid asking all of these at once.

The assistant should choose the single most useful missing field.

The frontend should show:

- the image;
- any current draft caption;
- visible people from current metadata;
- visible objects from current metadata;
- scene text or location if known;
- existing notes;
- missing required fields;
- proposed changes after a model turn.

Photo actions should include:

- update photo context draft;
- mark inferred visual observation;
- mark user-confirmed fact;
- add person association;
- add place association;
- add event association;
- add retrieval cues;
- flag privacy concern;
- preview submit;
- submit photo context task.

Acceptance criteria for photo context:

- The Chat tab can show the current photo.
- The LLM can receive the image for live calls when a mirrored image is available.
- The assistant asks Adam about the photo, not as the person in the photo.
- The assistant distinguishes inference from confirmed context.
- A proposed photo draft can be previewed before submission.
- The submitted data can be traced back to the chat turn.

## 15. Work Surface: Prompt-Response Review

Prompt-response review tasks are about voice quality.

The assistant should show the source prompt.

The assistant should show the candidate response.

The assistant should show source context when available.

The assistant should not ask Adam to answer the source prompt.

The assistant should ask Adam to evaluate the candidate response.

Useful questions include:

- Does this sound like Charles?
- What feels off?
- What should be more specific?
- What memory or detail is missing?
- Is the tone too generic?
- Is the answer too polished?
- Is the answer too explanatory?
- Should it be shorter or longer?
- Should it include more hesitation, warmth, humor, directness, or reflection?

The assistant should be able to rewrite the response based on Adam's critique.

The assistant should preserve Adam's rationale as review metadata.

The assistant should distinguish between:

- source prompt;
- original candidate response;
- revised candidate response;
- Adam critique;
- final approved response.

Acceptance criteria for prompt-response review:

- The Chat tab shows prompt and candidate response as a review card.
- The assistant asks Adam for critique, not a direct answer.
- Adam can request a rewrite.
- The assistant can produce a revised response.
- The revised response is stored as a draft until approved.
- The final accepted SFT item includes provenance.

## 16. Work Surface: DPO Pair Review

DPO review is about preference and rationale.

The assistant should show:

- the prompt;
- the chosen candidate;
- the rejected candidate;
- any existing label;
- source context;
- model or generation metadata if useful.

The assistant should ask:

- Which response better matches Charles?
- Why is one better?
- What should the rejected response teach the model not to do?
- Is either response unusable?
- Should a better chosen response be rewritten?

The assistant should support:

- flipping chosen and rejected;
- editing chosen;
- editing rejected only as explanatory reference;
- marking both bad;
- creating a new chosen answer;
- saving the preference rationale;
- advancing the DPO task after approval.

Acceptance criteria for DPO review:

- The Chat tab can render chosen and rejected responses side by side.
- Adam can critique the pair in natural language.
- The assistant can infer a proposed preference action.
- The assistant previews the proposed pair update.
- No DPO pair is submitted without explicit confirmation.
- The preference rationale is stored.

## 17. Work Surface: Source Excerpt Review

Source excerpt review is about turning raw documents into usable context.

The assistant should show:

- excerpt text;
- document title or source;
- date if known;
- author if known;
- existing tags;
- linked photos or entities if known;
- candidate memories or prompt seeds if any.

The assistant should ask:

- What is important here?
- Is this a good voice source?
- Is this factual context, tone evidence, or both?
- Should this become a memory, prompt seed, or exclusion?
- Are there names, dates, or places that need normalization?

Actions should include:

- update source metadata;
- create memory note;
- create prompt seed;
- create photo association;
- mark irrelevant;
- mark private or excluded;
- create SFT candidate;
- create DPO candidate.

Acceptance criteria for source excerpt review:

- The Chat tab shows the excerpt and source.
- The assistant asks Adam to classify or interpret the excerpt.
- Structured updates are proposed before saving.
- The saved update records the source excerpt ID.

## 18. Work Surface: Export Readiness

Export readiness is about trust before generating training files.

The assistant should be able to answer:

- how many SFT examples are ready;
- how many DPO pairs are ready;
- how many are blocked;
- what common quality issues remain;
- which examples need Adam review;
- whether photo context coverage is adequate;
- what would be included in the next export.

The assistant should show compact summaries, not giant tables.

The assistant should be able to open a blocker ticket.

The assistant should not silently export.

Acceptance criteria for export readiness:

- Chat can summarize readiness from the database.
- Chat can identify blockers.
- Chat can open or focus a blocker ticket.
- Chat can trigger an export only after explicit confirmation.
- The export includes only approved items.

## 19. Chat Session Requirements

The system should introduce first-class chat sessions.

A chat session should persist across refreshes.

A chat session should be associated with Adam.

A chat session may be associated with an active task.

A chat session may span multiple tasks.

A chat session should store user messages.

A chat session should store assistant messages.

A chat session should store model metadata.

A chat session should store tool or action proposals.

A chat session should store action outcomes.

A chat session should store references to workbench objects discussed.

Recommended table: `chat_sessions`.

Recommended table: `chat_turns`.

Recommended table: `chat_actions`.

Recommended table: `chat_action_results`.

The exact schema can be adjusted to fit existing database patterns.

The product requirement is that chat decisions are durable and inspectable.

## 20. Chat Session Data Model

`chat_sessions` should include:

- `id`;
- `created_at`;
- `updated_at`;
- `status`;
- `active_task_id`;
- `mode`;
- `title`;
- `summary`;
- `last_model`;
- `metadata_json`.

`chat_turns` should include:

- `id`;
- `session_id`;
- `task_id`;
- `role`;
- `content`;
- `created_at`;
- `model`;
- `input_token_count`;
- `output_token_count`;
- `latency_ms`;
- `context_packet_hash`;
- `metadata_json`.

`chat_actions` should include:

- `id`;
- `session_id`;
- `turn_id`;
- `task_id`;
- `action_type`;
- `status`;
- `proposed_payload_json`;
- `validated_payload_json`;
- `requires_confirmation`;
- `confirmed_by_user_at`;
- `executed_at`;
- `error_message`;
- `metadata_json`.

`chat_action_results` should include:

- `id`;
- `action_id`;
- `object_type`;
- `object_id`;
- `before_json`;
- `after_json`;
- `created_at`.

The product should not require this exact naming if an existing migration style suggests different names.

The important requirement is durable session, turn, action, and result records.

## 21. Context Packet Requirements

The backend should build a normalized context packet for every chat turn.

The context packet should be generated server-side.

The frontend should not be responsible for assembling sensitive or authoritative context.

The context packet should include:

- active task ID;
- task kind;
- task status;
- task priority;
- task title;
- task instructions;
- current draft;
- required fields;
- missing fields;
- associated asset IDs;
- associated source excerpt IDs;
- associated prompt-response IDs;
- recent chat summary;
- allowed actions;
- current user intent if detected;
- current work surface;
- source material preview;
- provenance references.

For image tasks, the context packet should include:

- image asset ID;
- image URL or local mirrored path;
- dimensions if known;
- caption if known;
- object detections if known;
- people labels if known;
- scene metadata if known;
- whether the model received actual image pixels.

For prompt-response tasks, the context packet should include:

- prompt text;
- candidate response;
- chosen response if DPO;
- rejected response if DPO;
- source excerpt references;
- current review notes;
- known voice rubric fields.

The context packet should be hashable.

The hash should be stored on the chat turn.

This allows later debugging of why the model proposed a given update.

## 22. Model Behavior Requirements

The model should act as an operator, not just a conversational assistant.

The model should always know the current work surface.

The model should ask Adam one question at a time.

The model should decide whether Adam's latest answer is enough to update a draft.

The model should produce structured proposals in a strict schema.

The model should never mutate the database directly.

The model should never claim an action has happened until the backend confirms it.

The model should never ask Adam to answer a source prompt as Charles.

The model should use image understanding for photo tasks when available.

The model should disclose uncertainty.

The model should prefer a short direct question over a long explanation.

The model should avoid generic onboarding language after the first turn.

The model should not hallucinate database state.

The model should use existing task fields and IDs.

The model should request clarification when Adam's answer is ambiguous.

The model should move forward when enough information is available.

## 23. Structured Response Contract

The chat operator should request structured JSON from the model.

The structured response should include:

- `assistant_message`;
- `work_surface`;
- `active_task_id`;
- `next_question`;
- `needs_user_response`;
- `draft_updates`;
- `proposed_actions`;
- `confidence`;
- `uncertainties`;
- `evidence_refs`;
- `ui_hints`.

`assistant_message` is what appears in chat.

`next_question` should be one question, or null when no question is needed.

`draft_updates` should be field-level proposals.

`proposed_actions` should be typed action requests.

`confidence` should be coarse and useful, not fake precision.

`uncertainties` should list important unknowns.

`evidence_refs` should point to source objects.

`ui_hints` should tell the frontend what preview or diff to show.

The backend should validate the response.

Invalid model responses should fall back to a safe assistant message.

Invalid actions should be rejected and logged.

## 24. Action Model Requirements

Actions are the bridge between chat and the database.

Actions should be explicit.

Actions should be typed.

Actions should be validated server-side.

Actions should be idempotent where possible.

Actions should support dry-run preview.

Actions should support confirmation.

Actions should record before and after state.

Actions should use existing service methods where available.

Actions should not bypass existing task validation.

Initial action types should include:

- `update_task_draft`;
- `preview_task_submission`;
- `submit_task`;
- `focus_task`;
- `skip_task`;
- `flag_task`;
- `create_memory_note`;
- `create_photo_context`;
- `update_photo_context`;
- `create_prompt_response_candidate`;
- `update_prompt_response_candidate`;
- `update_dpo_pair`;
- `mark_candidate_approved`;
- `mark_candidate_rejected`;
- `create_export_preview`;

Some actions should require confirmation.

All submit, approve, reject, export, delete, and destructive actions should require confirmation.

Draft updates may be applied automatically if they are reversible and shown in the UI.

The product should decide whether automatic draft writes are acceptable.

The safe default is preview first.

## 25. Confirmation Requirements

The assistant can say a ticket is ready.

The assistant cannot submit a ticket merely because it thinks it is ready.

Adam must confirm with an explicit intent.

Accepted confirmation phrases can include:

- "ready";
- "submit";
- "yes, submit";
- "approve";
- "looks good";
- "go ahead";
- clicking a Confirm button.

The backend should not rely only on model interpretation of confirmation.

The frontend can send a specific `confirm_action_id`.

The backend should verify the pending action still matches the current database state.

If the underlying task changed, the confirmation should require a refreshed preview.

## 26. UI Requirements: Chat Layout

The Chat tab should remain above Intake.

The Chat tab should become a calmer primary work surface.

The main layout should have:

- a conversation column;
- a current work item panel;
- an action preview area;
- a compact queue or next-up indicator.

On desktop, the work item panel can sit beside the chat.

On mobile, the work item panel should collapse above or behind a tab.

The chat input should stay visible.

The current work item should stay visible enough that Adam knows what he is reviewing.

The UI should avoid making every field visible at once.

The UI should avoid card nesting.

The UI should use progressive disclosure for raw data.

The UI should keep buttons compact and predictable.

## 27. UI Requirements: Current Work Item Panel

The current work item panel should adapt to the work surface.

For photo tasks, it should show:

- image preview;
- asset title or filename;
- visible people;
- visible objects;
- scene hints;
- current draft summary;
- missing fields;
- provenance chips.

For prompt-response tasks, it should show:

- prompt;
- candidate response;
- current review notes;
- source reference;
- voice rubric chips.

For DPO tasks, it should show:

- prompt;
- chosen response;
- rejected response;
- preference rationale;
- edit status.

For source excerpt tasks, it should show:

- source document;
- excerpt;
- known metadata;
- current classification.

The panel should not include long instructions about how to use the app.

The panel should use labels and structure, not tutorial copy.

## 28. UI Requirements: Action Preview

When the assistant proposes an update, the UI should show a preview.

The preview should be field-level.

The preview should distinguish:

- newly added values;
- changed values;
- removed values;
- inferred values;
- user-confirmed values.

The preview should include:

- Confirm;
- Edit;
- Dismiss.

For SFT rewrite, the preview should show:

- original response;
- revised response;
- rationale.

For DPO update, the preview should show:

- chosen response before and after;
- rejected response before and after;
- preference direction;
- rationale.

For photo context, the preview should show:

- caption;
- people;
- place;
- event;
- retrieval cues;
- privacy flags;
- unresolved uncertainties.

## 29. UI Requirements: Conversation

Messages should be concise.

The assistant should not repeat the whole context every turn.

The assistant should use the context panel for display and the message for the next question.

The assistant should ask one question at a time.

The assistant should explain proposed actions briefly.

The assistant should indicate when it has enough information.

The assistant should not use excessive formatting inside messages.

The chat should support multiline Adam responses.

The chat should support paste of longer notes.

The chat should support keyboard submit.

The chat should show loading state.

The chat should show action execution state separately from model thinking state.

## 30. UI Requirements: Queue

The Chat tab should know what it is working on now.

It should also know what it may work on next.

The queue display should be compact.

It should show:

- current task;
- task kind;
- task status;
- maybe one or two next tasks;
- why the current task was selected.

Adam should be able to say:

- "skip this";
- "show me another photo";
- "work on DPO pairs";
- "go back";
- "open this ticket";
- "focus on export blockers".

The assistant should route these intents to task focus actions.

## 31. UI Requirements: Reduced Clutter

The next phase should not add a large new control panel.

The current forms can remain available for power users.

The Chat tab should hide most fields until they matter.

The product should prefer:

- one image;
- one prompt or pair;
- one question;
- one proposed update.

The product should avoid:

- multiple simultaneous tickets;
- dense tables inside Chat;
- long global instructions;
- unstructured JSON blocks as normal UI;
- always-visible raw payloads.

Raw payloads can exist behind developer/debug disclosure.

## 32. Backend Requirements: Chat Operator

The chat operator should be refactored around a clear pipeline.

Step 1: Resolve session.

Step 2: Resolve active task.

Step 3: Build context packet.

Step 4: Build model input.

Step 5: Call model or deterministic fallback.

Step 6: Validate structured response.

Step 7: Create assistant turn.

Step 8: Create proposed actions.

Step 9: Return UI payload.

Step 10: Execute confirmed actions through a separate endpoint or action pathway.

The model call should not mix too many responsibilities in one function.

The code should remain pragmatic and local to existing app patterns.

The first refactor does not need a complex agent framework.

## 33. Backend Requirements: Endpoints

The current `POST /api/chat/turn` can remain the main endpoint.

It should support:

- new message;
- session ID;
- active task ID;
- selected mode;
- pending action confirmation if needed;
- client-known UI state if needed.

Additional endpoints may include:

- `GET /api/chat/sessions`;
- `POST /api/chat/sessions`;
- `GET /api/chat/sessions/{id}`;
- `POST /api/chat/actions/{id}/confirm`;
- `POST /api/chat/actions/{id}/dismiss`;
- `POST /api/chat/actions/{id}/preview`.

The team can choose fewer endpoints if the same behavior is cleanly represented through `POST /api/chat/turn`.

The requirement is not the exact route shape.

The requirement is a clean separation between model suggestion and database mutation.

## 34. Backend Requirements: Image Input

For photo tasks, the backend should attach actual image pixels to the model input when possible.

The current local mirrored image data URL approach is a good start.

The backend should record whether image pixels were included.

The assistant should not imply it saw the image if no image was attached.

If image pixels are unavailable, the assistant can use metadata and ask Adam to open or describe the image.

The image input should be size-limited.

The image input should fail gracefully.

The image input should not block all chat behavior if unavailable.

## 35. Backend Requirements: Prompt Safety

The source prompt problem is central.

The assistant must never confuse:

- a prompt to be answered by Charles;
- a review question to be answered by Adam.

The backend should keep the current sanitizer and expand tests around it.

The structured context packet should label source prompts explicitly.

The model instructions should say:

- do not answer source prompts as if you are Charles;
- do not ask Adam to answer source prompts directly;
- ask Adam to critique, approve, reject, or edit the candidate response.

If the model violates this, the backend should replace the question with a safe fallback.

This fallback should be specific to the task kind.

## 36. Backend Requirements: Deterministic Fallback

The app should work in local development without a live LLM call.

The deterministic fallback should produce useful Adam-facing questions.

The deterministic fallback should know the work surface.

The deterministic fallback should avoid source prompt reuse.

The deterministic fallback should return predictable structured data for tests.

The fallback should not pretend to have seen image pixels.

The fallback should be clearly marked in metadata.

## 37. Backend Requirements: Validation

All model outputs should be validated.

The backend should reject unknown action types.

The backend should reject updates to unknown fields.

The backend should reject updates to tasks outside the session scope.

The backend should reject submit actions without confirmation.

The backend should reject destructive actions without confirmation.

The backend should reject stale confirmations.

The backend should reject actions whose preconditions no longer match.

The backend should sanitize long text fields.

The backend should enforce basic limits on array lengths.

The backend should record validation failures for observability.

## 38. Backend Requirements: Provenance

Every chat-generated data update should preserve provenance.

At minimum, provenance should include:

- chat session ID;
- chat turn ID;
- action ID;
- task ID;
- source object IDs;
- model name;
- model response ID if available;
- context packet hash;
- user confirmation timestamp;
- prior value;
- new value.

For photo context, provenance should distinguish:

- model visual inference;
- existing metadata;
- Adam-confirmed fact;
- Adam-provided memory;
- database-derived association.

For SFT and DPO, provenance should distinguish:

- source prompt;
- generated candidate;
- Adam critique;
- assistant rewrite;
- final approval.

## 39. Backend Requirements: Observability

The chat operator should log key events.

Events should include:

- session created;
- turn received;
- context packet built;
- model call started;
- model call completed;
- model call failed;
- structured response validated;
- action proposed;
- action confirmed;
- action executed;
- action failed.

Logs should include IDs, not giant payloads.

Debug mode can expose raw payloads.

Production-like mode should avoid logging sensitive content unnecessarily.

The UI should surface user-readable failures.

The backend should preserve developer-readable failures.

## 40. Data Quality Requirements

The chat should improve data quality, not just speed.

Required quality dimensions:

- specificity;
- voice fidelity;
- factual grounding;
- source traceability;
- photo context usefulness;
- privacy awareness;
- edit rationale;
- export readiness.

Each accepted training example should be traceable to:

- the source material;
- the reason it was accepted;
- the human review moment;
- any model rewrite.

Each rejected candidate should preserve why it was rejected when useful for DPO.

Photo context should support future retrieval and visual memory.

## 41. Voice Quality Requirements

The chat should help refine Charles's voice.

It should not merely produce generic polished prose.

It should encourage Adam to identify:

- too generic;
- too modern;
- too sentimental;
- too formal;
- too explanatory;
- too terse;
- missing personal detail;
- wrong emotional register;
- wrong level of certainty;
- invented detail.

The assistant should convert this feedback into:

- revised response text;
- voice notes;
- DPO rationale;
- future generation hints;
- possible rubric updates.

The product should gradually accumulate useful voice guidance.

That guidance should not override specific source evidence.

## 42. Photo Memory Requirements

The photo layer is not just captioning.

The photo layer should help future models understand visual memories.

A photo context record should support:

- people;
- relationships;
- place;
- event;
- date or era;
- visible objects;
- emotional salience;
- associated stories;
- source reliability;
- privacy constraints;
- retrieval cues;
- training usage suitability.

The model can propose visible observations.

Adam should confirm personal meaning.

The database should distinguish visible facts from remembered associations.

The export layer should be able to include photo-derived context where appropriate.

## 43. Memory and Context Layer Requirements

The workbench should produce more than SFT and DPO rows.

It should produce a context layer.

The context layer should include durable facts, memories, associations, and source links.

The chat should create and refine this layer as a byproduct of work.

The context layer should later help:

- prompt generation;
- response evaluation;
- retrieval;
- agent memory;
- photo understanding;
- quality audits.

The context layer should be reviewed, not entirely inferred.

The context layer should be exportable or queryable.

## 44. Task Selection Requirements

The assistant should be able to choose a next useful task.

Initial task selection can be simple.

Priority should consider:

- task status;
- task type requested by Adam;
- missing required fields;
- export blockers;
- recency;
- whether an asset preview exists;
- whether a task has a draft in progress;
- whether a previous chat turn is awaiting confirmation.

The assistant should tell Adam why it selected a task when useful.

Adam should be able to override selection in plain language.

## 45. Task Progression Requirements

The assistant should know task readiness.

Readiness should be based on deterministic validation, not only model confidence.

For photo context, readiness might require:

- image asset ID;
- at least one confirmed context statement;
- privacy status;
- retrieval cues or summary;
- no unresolved blocking uncertainty.

For SFT, readiness might require:

- prompt;
- approved response;
- source reference;
- voice review status;
- no unresolved factual issue.

For DPO, readiness might require:

- prompt;
- chosen response;
- rejected response;
- preference rationale;
- approval status.

When ready, the assistant should offer submission.

When not ready, it should ask the next best question.

## 46. Error Handling Requirements

If the model call fails, the UI should show a concise error and allow retry.

If image loading fails, the UI should show metadata and still allow text review.

If action validation fails, the UI should explain what changed.

If confirmation is stale, the UI should request a refreshed preview.

If the backend rejects an update, the assistant should not claim success.

If deterministic fallback is active, the UI can continue working with limited intelligence.

If the database is unavailable, chat should not accept actions that imply persistence.

## 47. Security and Privacy Requirements

The workbench likely contains personal material.

The product should treat all source documents, photos, and chat messages as sensitive.

The system should avoid sending unnecessary context to the model.

The system should avoid logging full personal content in server logs.

The system should include privacy flags on photo context.

The system should allow Adam to mark content as excluded from training.

The system should never export excluded content.

The system should record when a model saw an image or source excerpt.

The system should support local deterministic testing without external model calls.

## 48. Accessibility Requirements

The Chat tab should be keyboard usable.

The input should have a clear focus state.

Buttons should have accessible labels.

Image previews should have alt text based on available context.

Diffs should not rely only on color.

The layout should remain usable on narrow screens.

Long text should wrap cleanly.

The current work item should be reachable by keyboard.

Loading and error states should be announced appropriately where feasible.

## 49. Performance Requirements

The Chat tab should render quickly.

Initial session load should not require fetching all tasks.

Context packet building should load only relevant objects.

Image data URLs should be resized or constrained.

Model calls can be slower, but the UI should show progress.

The assistant should stream in a future phase if helpful.

Action previews should return quickly.

The UI should not freeze when displaying long prompt-response examples.

## 50. Feature Flags and Configuration

The live LLM path should remain configurable.

Important settings include:

- API key;
- model name;
- reasoning effort;
- live call enabled flag;
- maximum image size;
- maximum context packet size;
- deterministic fallback mode;
- debug payload visibility.

The default reasoning effort should stay practical.

The current default of `medium` is appropriate unless a specific task requires more.

Local tests should not require live model calls.

## 51. Proposed Implementation Phases

The work should proceed in phases.

Each phase should leave the app usable.

Each phase should include tests.

Each phase should avoid broad rewrites.

## 52. Phase 1: Persist Chat Sessions

Objective: make chat durable and inspectable.

Tasks:

- add database models or migrations for chat sessions;
- add database models or migrations for chat turns;
- add database models or migrations for chat actions if needed;
- update `POST /api/chat/turn` to create or reuse a session;
- store user turns;
- store assistant turns;
- store active task ID;
- store model metadata;
- return session ID to frontend;
- load prior turns when reopening Chat;
- add deterministic tests for persistence.

Acceptance criteria:

- refreshing the page does not lose the current chat session;
- a chat turn is visible in the database;
- assistant responses are linked to task IDs;
- tests pass without live LLM calls.

## 53. Phase 2: Build Normalized Context Packets

Objective: centralize task context for the model and UI.

Tasks:

- create a server-side context packet builder;
- support photo tasks;
- support prompt-response tasks;
- support DPO tasks;
- support source excerpt tasks;
- include required and missing fields;
- include allowed actions;
- include provenance refs;
- include whether image pixels are available;
- hash context packets;
- store the hash on chat turns.

Acceptance criteria:

- each supported task kind produces a valid packet;
- tests assert key packet fields;
- image tasks include image availability metadata;
- prompt-response tasks label source prompts clearly;
- UI can render from packet data.

## 54. Phase 3: Structured Model Output

Objective: replace loose conversational parsing with a strict response contract.

Tasks:

- define Pydantic schema for model output;
- request structured JSON from the model;
- validate model output;
- normalize fallback output;
- reject invalid action proposals;
- generate safe fallback messages;
- add tests for invalid model JSON;
- add tests for source-prompt violation repair.

Acceptance criteria:

- chat responses always conform to the API schema;
- bad model output does not crash the endpoint;
- source prompt reuse is caught;
- action proposals are machine-readable.

## 55. Phase 4: Action Preview and Confirmation

Objective: let chat propose real work without hidden writes.

Tasks:

- implement action records;
- implement `update_task_draft` preview;
- implement submit preview;
- implement confirmation endpoint or turn payload;
- add action cards to frontend;
- show field-level diffs;
- support dismiss;
- support stale preview detection;
- record before and after values.

Acceptance criteria:

- model can propose a draft update;
- UI shows the proposed update;
- no submit happens before confirmation;
- confirmed action writes through backend validation;
- stale confirmations are rejected.

## 56. Phase 5: Photo Context Completion Loop

Objective: make the photo workflow genuinely useful.

Tasks:

- show image prominently in Chat;
- send image to model when available;
- ask Adam about visible and contextual details;
- create structured photo context draft;
- distinguish inferred vs confirmed facts;
- preview photo context update;
- submit photo context through task flow;
- add manual QA with a real photo task.

Acceptance criteria:

- assistant asks about the photo content;
- assistant can create a useful draft from Adam's answer;
- confirmed facts are marked differently from visual inferences;
- submitted photo context appears in the database;
- failed image input degrades gracefully.

## 57. Phase 6: SFT Rewrite Loop

Objective: support voice refinement from prompt-response candidates.

Tasks:

- show prompt and candidate response;
- ask Adam for critique;
- rewrite response from critique;
- show original vs revised response;
- store critique and revised response as draft;
- approve response after confirmation;
- attach source refs and voice notes.

Acceptance criteria:

- assistant never asks Adam to answer the source prompt;
- assistant can rewrite a candidate based on critique;
- UI shows an understandable diff;
- approved response is stored as training-ready SFT;
- critique is preserved as provenance.

## 58. Phase 7: DPO Pair Review Loop

Objective: make preference review fast and reliable.

Tasks:

- show chosen and rejected candidates side by side;
- ask Adam to compare voice quality;
- infer preference action from Adam response;
- support flipping candidates;
- support marking both bad;
- support rewriting chosen;
- store preference rationale;
- submit approved DPO pair.

Acceptance criteria:

- DPO cards render in Chat;
- Adam can approve or revise pair in natural language;
- proposed preference update is previewed;
- approved pair includes rationale;
- pair is not submitted without confirmation.

## 59. Phase 8: Smart Queue and Mode Control

Objective: let Adam direct the kind of work Chat should do.

Tasks:

- add lightweight mode selector or natural language mode detection;
- support "work on photos";
- support "work on DPO pairs";
- support "show export blockers";
- support "skip";
- support "go back";
- rank next tasks;
- explain current task selection briefly.

Acceptance criteria:

- Adam can change work type from chat;
- task focus changes without leaving the tab;
- current task reason is visible;
- skipped tasks are not immediately repeated.

## 60. Phase 9: Export Readiness Assistant

Objective: make exports understandable and trustworthy.

Tasks:

- build export readiness summary;
- count approved SFT examples;
- count approved DPO pairs;
- identify blockers;
- show representative quality issues;
- let Adam open blocker tasks;
- generate export preview on confirmation.

Acceptance criteria:

- Chat can answer what is ready to export;
- Chat can explain what is blocked;
- export preview does not include unapproved items;
- export generation requires confirmation.

## 61. Phase 10: Quality Analytics and Audit

Objective: create confidence in the dataset.

Tasks:

- add dataset quality summary;
- track review coverage;
- track source coverage;
- track photo context coverage;
- track voice critique categories;
- track rejected candidate reasons;
- expose audit history per training item;
- add admin/debug view if needed.

Acceptance criteria:

- Adam can inspect why an item exists;
- quality gaps are visible;
- audit trail links item to chat session and source;
- exported items include provenance metadata where appropriate.

## 62. Testing Strategy Overview

Testing must cover deterministic behavior and model-assisted behavior.

Unit tests should cover backend logic.

Integration tests should cover database mutations.

Frontend tests should cover rendering and user flows.

Manual QA should cover live model behavior.

Visual smoke tests should cover the new work surfaces.

The default automated test suite should not require live LLM calls.

Live model tests should be opt-in.

## 63. Backend Unit Tests

Add tests for context packet building.

Test photo context packet includes asset references.

Test photo context packet marks image availability.

Test prompt-response packet includes prompt and candidate response.

Test DPO packet includes chosen and rejected responses.

Test source excerpt packet includes source metadata.

Test source prompt is labeled as source prompt.

Test fallback next question is Adam-facing.

Test source prompt reuse is detected.

Test model response validation accepts valid structured output.

Test model response validation rejects missing required fields.

Test unknown action type is rejected.

Test unknown draft field is rejected.

Test action requiring confirmation is not executed immediately.

Test confirmed action executes only when valid.

Test stale action confirmation is rejected.

Test action records before and after state.

Test deterministic fallback does not claim to see image pixels.

Test image input failure does not fail entire chat turn.

## 64. Backend Integration Tests

Add an integration test for photo context update.

Flow:

- create photo task;
- create chat session;
- send Adam answer;
- model fallback proposes draft update;
- preview action is returned;
- confirm action;
- assert task draft changed;
- assert provenance references chat turn.

Add an integration test for photo context submission.

Flow:

- create ready photo draft;
- request submit;
- receive preview;
- confirm;
- assert task status advances;
- assert submitted context exists.

Add an integration test for SFT rewrite.

Flow:

- create prompt-response task;
- send critique;
- assistant proposes revised response;
- confirm update;
- assert revised response stored;
- assert original candidate preserved.

Add an integration test for DPO preference update.

Flow:

- create DPO task;
- send preference critique;
- assistant proposes chosen/rejected update;
- confirm;
- assert pair updated;
- assert rationale stored.

Add an integration test for source excerpt classification.

Flow:

- create source excerpt task;
- send Adam classification;
- assistant proposes metadata update;
- confirm;
- assert source context updated.

## 65. Frontend Component Tests

Test Chat tab appears above Intake.

Test empty chat session renders starter state.

Test photo work item panel renders image.

Test photo work item panel renders visible people.

Test photo work item panel renders visible objects.

Test prompt-response panel renders prompt.

Test prompt-response panel renders candidate response.

Test DPO panel renders chosen and rejected.

Test source excerpt panel renders excerpt.

Test action preview renders field changes.

Test Confirm button appears for confirmation-required actions.

Test Dismiss button removes preview.

Test loading state appears during send.

Test error state appears on API failure.

Test long text wraps without layout overflow.

Test mobile layout keeps chat input usable.

## 66. End-to-End Tests

Use Playwright or the project's existing browser test approach.

E2E 1: photo context happy path.

Steps:

- open app;
- click Chat;
- focus a photo task;
- verify image is visible;
- send answer about person/place;
- verify draft preview appears;
- confirm;
- verify task draft update appears.

E2E 2: SFT critique happy path.

Steps:

- open Chat;
- focus SFT review task;
- verify prompt and response visible;
- send critique;
- verify revised response preview appears;
- confirm;
- verify approved draft state.

E2E 3: DPO review happy path.

Steps:

- open Chat;
- focus DPO task;
- verify chosen and rejected visible;
- send preference feedback;
- verify pair update preview;
- confirm;
- verify rationale saved.

E2E 4: source prompt guardrail.

Steps:

- focus task whose source prompt asks "How did you learn to cook?";
- verify assistant asks Adam to review the response;
- assert assistant does not ask "How did you learn to cook?" as the next Adam question.

E2E 5: stale confirmation.

Steps:

- create preview;
- mutate task through another path;
- confirm old preview;
- assert confirmation is rejected;
- assert refreshed preview is requested.

## 67. Visual Verification

Capture desktop screenshot for Chat photo task.

Capture desktop screenshot for Chat SFT task.

Capture desktop screenshot for Chat DPO task.

Capture mobile screenshot for Chat photo task.

Capture mobile screenshot for action preview.

Check that no text overlaps.

Check that images are not cropped in a misleading way.

Check that prompt and response blocks are readable.

Check that buttons fit labels.

Check that long responses wrap.

Check that the current work item is obvious.

Check that raw debug payloads are not visible by default.

## 68. Manual QA Script: Photo Task

Start local API.

Start local web app.

Open Chat.

Ask Chat to work on photos.

Verify it selects a photo task.

Verify the image appears.

Verify the assistant asks an Adam-facing question.

Answer with person, place, event, and memory.

Verify the assistant extracts structured fields.

Verify it asks a follow-up only if needed.

Verify it offers a ready-to-submit preview.

Confirm submission.

Verify database state.

Verify task advanced.

Verify provenance records chat session and turn.

## 69. Manual QA Script: SFT Review

Open Chat.

Ask Chat to work on voice examples.

Verify it selects an SFT or prompt-response task.

Verify prompt and candidate response are visible.

Verify assistant asks for critique.

Say the response is too generic and needs a specific memory.

Verify assistant rewrites the response.

Verify original and revised responses are visible.

Ask for another edit.

Verify assistant updates the revision.

Approve the response.

Verify approved response is stored.

Verify source prompt is preserved.

Verify critique is preserved.

## 70. Manual QA Script: DPO Review

Open Chat.

Ask Chat to show DPO pairs.

Verify chosen and rejected candidates are visible.

Say which one is better and why.

Verify assistant proposes correct preference action.

Ask it to rewrite the chosen response.

Verify revised chosen response appears.

Approve the pair.

Verify DPO pair status advances.

Verify rationale is stored.

## 71. Manual QA Script: Export Readiness

Open Chat.

Ask what is ready to export.

Verify assistant reports counts.

Ask what is blocked.

Verify assistant lists blocker categories.

Open one blocker from chat.

Complete it.

Ask for readiness again.

Verify counts update.

Ask for export preview.

Verify confirmation is required.

Confirm only if expected.

Verify export contains approved items only.

## 72. Database Verification Queries

After a chat turn, verify a chat session exists.

After a chat turn, verify user and assistant turns exist.

After an action preview, verify action status is pending.

After confirmation, verify action status is executed.

After confirmation, verify before and after state is recorded.

After photo context update, verify context fields changed.

After SFT rewrite, verify original response is preserved.

After DPO update, verify rationale is stored.

After submission, verify task status changed.

After export preview, verify unapproved items are excluded.

The exact SQL depends on the final schema.

The PRD requirement is that every manual QA flow has a database-level verification.

## 73. Live Model Verification

Live model tests should be opt-in.

They should run only when API credentials are configured.

They should avoid writing final database changes unless explicitly set.

Recommended live smoke 1: photo question quality.

Expected result:

- assistant references visible image features;
- assistant asks Adam a context question;
- assistant does not invent personal facts as confirmed.

Recommended live smoke 2: SFT prompt guardrail.

Expected result:

- assistant shows prompt and candidate response;
- assistant asks for critique;
- assistant does not ask Adam to answer as Charles.

Recommended live smoke 3: DPO interpretation.

Expected result:

- assistant correctly interprets preference feedback;
- assistant proposes a structured DPO action;
- assistant waits for confirmation.

Recommended live smoke 4: ambiguous answer.

Expected result:

- assistant asks a useful follow-up;
- assistant does not submit incomplete data.

## 74. Automated Command Checklist

For backend deterministic tests:

```bash
OPENAI_API_KEY= TEXT_GENERATION_LIVE_CALLS_ENABLED=false python -m pytest
```

For targeted chat tests:

```bash
OPENAI_API_KEY= TEXT_GENERATION_LIVE_CALLS_ENABLED=false python -m pytest apps/api/tests/test_chat_operator.py
```

For web build:

```bash
npm run build
```

Use the actual package manager commands from the repo if they differ.

The implementation phase should document exact commands after confirming the repo scripts.

## 75. Acceptance Criteria Summary

AC-001: Chat sessions persist across refresh.

AC-002: Chat turns are stored with task references.

AC-003: Context packets are built server-side.

AC-004: Context packet hashes are stored.

AC-005: Photo tasks can show an image in Chat.

AC-006: Photo tasks can send image input to the model when available.

AC-007: The assistant asks Adam about photo context.

AC-008: Visual inferences are not stored as confirmed facts without Adam.

AC-009: Prompt-response tasks show prompt and candidate response.

AC-010: The assistant never asks Adam to answer the source prompt as Charles.

AC-011: SFT critiques can produce revised responses.

AC-012: SFT revisions are previewed before approval.

AC-013: DPO tasks show chosen and rejected responses.

AC-014: DPO preference updates are previewed before approval.

AC-015: Source excerpt tasks show source text and metadata.

AC-016: Draft updates are typed and validated.

AC-017: Submit actions require confirmation.

AC-018: Destructive actions require confirmation.

AC-019: Stale confirmations are rejected.

AC-020: Action before and after state is recorded.

AC-021: Chat-generated updates include provenance.

AC-022: The UI shows action previews clearly.

AC-023: The UI supports desktop and mobile layouts.

AC-024: The deterministic fallback remains useful.

AC-025: Automated tests pass without live LLM calls.

AC-026: Live model smoke tests can be run manually.

AC-027: Export readiness can be summarized in Chat.

AC-028: Exports include only approved data.

AC-029: Privacy and exclusion flags are respected.

AC-030: The Chat tab reduces perceived workflow clutter.

## 76. Edge Cases

Adam gives a long answer containing multiple updates.

The assistant should extract what it can and ask only for the most important missing piece.

Adam corrects a previous answer.

The assistant should update the draft and preserve superseded provenance.

Adam says "skip."

The assistant should skip the current task and choose another.

Adam says "ready" without a pending preview.

The assistant should explain what still needs confirmation or generate a preview.

Adam asks a general question about the dataset.

The assistant should answer from available database summaries or state that it needs a specific query.

The image is missing.

The assistant should use metadata and ask Adam for context.

The image is too large.

The backend should downsize or omit image input and record that.

The model proposes an unsupported action.

The backend should reject it and produce a safe message.

The task changes while a preview is pending.

The confirmation should be rejected as stale.

The model hallucinates a person in a photo.

The assistant should label it as a visual guess until Adam confirms.

Adam asks to exclude a photo.

The assistant should propose a privacy or exclusion update.

Adam gives voice critique but no replacement text.

The assistant should propose a rewrite and ask for approval.

Both DPO responses are bad.

The assistant should support marking both bad and creating a new candidate.

## 77. Risks

Risk: The chat becomes another cluttered surface.

Mitigation: Keep the UI focused on one work item, one question, and one preview.

Risk: The model writes bad data.

Mitigation: Use typed actions, validation, previews, and confirmations.

Risk: The model asks the wrong question.

Mitigation: Work-surface-specific fallback questions and prompt-reuse sanitization.

Risk: The model invents photo context.

Mitigation: Separate visual inference from Adam-confirmed memory.

Risk: Chat history becomes noisy.

Mitigation: Persist turns but summarize sessions for prompt context.

Risk: Context packets become too large.

Mitigation: Include only task-relevant context and use source refs for the rest.

Risk: The frontend duplicates backend logic.

Mitigation: Build authoritative context packets server-side.

Risk: Export quality is hard to judge.

Mitigation: Add readiness summaries and provenance.

Risk: Tests become flaky with live LLM calls.

Mitigation: Keep live calls opt-in and deterministic tests primary.

## 78. Open Questions

Should draft updates be written automatically after each turn, or only after Adam confirms a preview?

Should chat sessions be task-scoped by default or project-scoped by default?

Should the assistant always pick the next task, or should Adam choose a mode first?

What are the minimum required fields for each task kind?

Which current database tables should hold durable photo context?

How should visual inferences be represented in exports?

Should voice critique accumulate into a reusable voice rubric?

How much raw chat should be exported or retained as provenance?

Should exclusion and privacy be global source flags or per-export flags?

How should the product handle multiple candidate rewrites for one prompt?

Should there be an explicit "review queue" table or derive queue from task status?

Should action previews use JSON Patch, field diffs, or current draft schemas?

## 79. Recommended Next Implementation Order

First, persist chat sessions and turns.

Second, introduce normalized context packets.

Third, introduce structured model output.

Fourth, introduce action previews.

Fifth, implement one complete vertical slice for photo context.

Sixth, implement one complete vertical slice for SFT rewrite.

Seventh, implement DPO pair review.

Eighth, add smart queue controls.

Ninth, add export readiness.

This order keeps the platform safe before giving the model more power.

It also creates visible product value early.

## 80. Minimal Vertical Slice Definition

The smallest next slice that proves the product direction is:

- persisted chat session;
- photo context packet;
- photo visible in Chat;
- Adam-facing photo question;
- structured draft update proposal;
- field-level preview;
- confirmation;
- database update;
- provenance record;
- automated tests.

This slice proves:

- the chat can understand a real work item;
- the model can produce structured work;
- Adam can review before write;
- the database remains authoritative;
- the UI is calmer than the full form.

## 81. Implementation Notes

Prefer existing project patterns over new frameworks.

Keep migrations small.

Keep the chat operator testable without network calls.

Keep the frontend state model simple.

Do not let the frontend invent authoritative task context.

Do not expose debug JSON by default.

Keep model prompts short but precise.

Use schemas to force shape.

Use backend validation to enforce safety.

Preserve the current manual workbench paths.

Make the Chat path additive and progressively more capable.

## 82. Documentation Requirements

Update developer documentation after implementation.

Document environment variables.

Document live model test requirements.

Document how to run deterministic tests.

Document action types.

Document context packet shape.

Document database provenance fields.

Document manual QA scripts.

Document known limitations.

## 83. Release Criteria

The next release should not be considered ready until:

- deterministic backend tests pass;
- frontend build passes;
- Chat photo vertical slice works locally;
- Chat SFT review works locally;
- source prompt guardrail is covered by tests;
- action confirmation is covered by tests;
- manual QA screenshots are captured;
- no unreviewed model action can submit or export data;
- the UI is checked on desktop and mobile widths.

## 84. Success Metrics

Qualitative success:

- Adam feels the workflow is simpler.
- Adam can complete a ticket mostly through conversation.
- Adam trusts the preview before submission.
- Adam sees fewer raw fields during normal work.
- Adam can refine voice examples faster.
- Adam can add photo meaning without manual database thinking.

Quantitative success:

- time to complete one photo context ticket decreases;
- time to approve one SFT example decreases;
- percentage of examples with provenance increases;
- percentage of photo assets with context increases;
- number of unreviewed export blockers decreases;
- number of source prompt guardrail failures is zero in tests;
- no confirmed action is executed without audit record.

## 85. Final Product Direction

The workbench should feel like a thoughtful editorial assistant with a structured memory underneath.

Adam should be able to work conversationally.

The system should translate that conversation into rigorous data.

The model should help ask, draft, compare, and revise.

The backend should validate, record, and protect.

The frontend should show just enough context to make each decision clear.

The end state is a high-quality digital twin preparation system.

The next phase should prove that this can happen ticket by ticket.
