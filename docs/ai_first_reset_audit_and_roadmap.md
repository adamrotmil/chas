# AI-First Reset Audit and Roadmap

Date: 2026-05-09

Owner: CharlesOps Workbench

Status: Reset plan for bringing the product back to the intended AI-assisted workflow

## 1. Why This Exists

The project has started to accumulate useful workflow infrastructure: tasks, drafts, receipts, export artifacts, chat sessions, prompt-pair review, photo context review, and a training board.

That infrastructure is not the product goal by itself.

The real product goal is an AI-assisted workbench that helps Adam turn a large, private body of documents, journals, prompt-pair files, and photos into high-quality reviewed training sets for future Charles voice models and agents.

The app should feel like:

- Adam brings photos, documents, journals, and rough prompt pairs.
- The system understands what those objects are.
- The system asks Adam the next best question.
- The system uses Adam's answers to improve source context.
- The system proposes grounded SFT/DPO examples with evidence.
- Adam edits and approves.
- The system exports training datasets with provenance.

The recent concern is valid: parts of the codebase still rely on deterministic scaffolding, hardcoded fallback behavior, and test mocks. Those are useful for safety and repeatable tests, but they should not be confused with the actual product intelligence.

This document is the reset plan.

## 2. Important Clarification About Hardcoded Test Text

The specific screenshot showing:

```py
"assistant_message": "I swapped chosen and rejected."
```

is from a test monkeypatch.

That is not the production model response path. It is a deterministic test fixture that simulates a model plan so the backend can verify:

- patch validation;
- authoritative field movement;
- before/after diffs;
- no direct mutation without backend validation;
- safe behavior without spending model tokens in CI.

Tests should keep using fixed model outputs.

The product problem is different: production behavior still has too many fallback/scaffold paths and too few fully AI-native workflows.

## 3. Current Local AI Configuration

Current local API status, checked via:

```sh
curl http://localhost:8000/api/model-status
```

shows:

```json
{
  "text_generation_model": "gpt-5.5",
  "text_generation_reasoning_effort": "medium",
  "text_generation_live_calls_enabled": true,
  "openai_api_key_configured": true,
  "text_generation_live_ready": true
}
```

So the text-generation/chat path is currently capable of live OpenAI calls in the running API.

The local `.env` path is:

```text
/Users/arotmil/dev/chas/.env
```

Relevant flags:

```env
OPENAI_API_KEY=...
TEXT_GENERATION_MODEL=gpt-5.5
TEXT_GENERATION_REASONING_EFFORT=medium
TEXT_GENERATION_LIVE_CALLS_ENABLED=true
CHAT_REASONING_EFFORT=medium
CHAT_REQUIRE_LIVE_MODEL=true
VISION_MODEL=gpt-4.1-mini
VISION_LIVE_CALLS_ENABLED=false
```

Do not paste the API key into chat. Put it only in `.env` or the process environment.

After changing `.env`, restart the API:

```sh
docker compose up -d api
```

Then confirm:

```sh
curl http://localhost:8000/api/model-status
```

## 4. Current AI / Scaffold Inventory

### 4.1 Chat Workbench

Primary file:

```text
apps/api/app/services/chat_operator.py
```

Current behavior:

- If `live_text_generation_ready()` is true, chat calls the OpenAI Responses API.
- It asks the model to return a JSON plan.
- The backend validates and normalizes the plan.
- If live calls fail or are disabled, the backend falls back to deterministic plans.
- Chat can include image input for a task if `_image_data_url_for_task()` can resolve a local image object.

Current strength:

- Good safety shell.
- Draft-first behavior.
- Explicit confirmation before submit/export.
- Backend owns mutation.
- Recent patch work makes action claims truthful.

Current limitation:

- The model is not yet a first-class tool-using agent.
- The model returns JSON, but it does not use explicit backend tools in a loop.
- Context retrieval is limited to the current task packet.
- Chat cannot yet inspect broader project state deeply enough.
- Chat cannot robustly browse the source corpus, compare many photos, or assemble evidence-backed training candidates.

### 4.2 Operator Assistant

Primary file:

```text
apps/api/app/services/operator_assistant.py
```

Current behavior:

- Has a live model path.
- Has deterministic fallback suggestions.
- Parses model field updates into allowed fields.

Current limitation:

- It is still mostly a single-turn assistant for form updates.
- It does not operate as the main intelligence layer for documents/photos/training data.

### 4.3 Text Draft Generation

Primary file:

```text
apps/api/app/services/model_generation.py
```

Current behavior:

- Can call the OpenAI Responses API for text drafts.
- Has a deterministic scaffold fallback:

```py
scaffold_voice_draft(...)
```

Current strength:

- The live path is real.
- The deterministic fallback is clearly named.

Current limitation:

- The fallback can produce plausible-looking text unless the UI makes status obvious.
- Draft generation is not yet deeply tied to retrieval, evidence selection, or iterative Adam feedback.

### 4.4 Source / Prompt Pair Generation

Primary file:

```text
apps/api/app/services/pair_generation.py
```

Current behavior:

- Has `_llm_pair_generation()` using OpenAI when live text is ready.
- Has deterministic span/rule generation paths.
- Falls back to generated/scaffolded pair construction.

Current strength:

- There is a live LLM pair-generation path.
- It asks for JSON prompt/response examples.

Current limitation:

- It is not yet the central workflow.
- It does not yet enforce source citations per generated pair strongly enough.
- It does not yet give Adam a clean "model proposed this from these evidence spans" workflow.
- It does not yet robustly handle large text corpora with retrieval, clustering, and staged review.

### 4.5 Vision / Photo Understanding

Primary file:

```text
apps/api/app/services/vision.py
```

Current behavior:

- Defines a useful structured vision schema.
- Creates vision review tasks.
- Stores no-call system-inference draft scaffolds.
- Explicitly rejects live vision calls:

```py
if not no_live_model_call:
    raise HTTPException(...)
```

Current strength:

- Correct truth boundary: vision output is system inference until Adam reviews it.
- Good review-task skeleton.

Current limitation:

- The app is not yet actually looking at photos in the vision pipeline.
- `VISION_LIVE_CALLS_ENABLED=false` and the service still blocks live calls even if enabled.
- This is one of the largest gaps vs the desired product.

### 4.6 Embeddings / Conceptual Memory

Primary files:

```text
apps/api/app/services/embeddings.py
apps/api/app/services/retrieval.py
apps/api/app/services/context_packs.py
```

Current behavior:

- There are records/plans for embeddings and retrieval.
- The system is structured for retrieval and context packs.

Current limitation:

- It is not yet a full semantic memory layer.
- Vector values/provider integration appear scaffolded or pending.
- Photos, source excerpts, and prompt pairs are not yet unified into a single conceptual retrieval surface.

## 5. Diagnosis

The project has built a lot of useful rails, but the center of gravity is still workflow plumbing.

The app needs a stronger AI spine.

Current state:

```text
UI -> task forms -> deterministic helpers -> occasional live model call -> drafts/exports
```

Target state:

```text
UI -> AI workbench agent -> tools over photos/docs/tasks/schemas/retrieval -> validated draft mutations -> Adam approval -> exports
```

The key difference is that the model should not be decorative. It should be the operator that chooses the next useful action, while the backend remains the validator and source of truth.

## 6. Product Reset Principles

### Principle 1: Live AI Status Must Be Obvious

Every AI-assisted surface should show whether it used:

- live text model;
- live vision model;
- deterministic fallback;
- scaffold/no model call;
- cached model output;
- Adam-authored data.

No generated content should look like model intelligence if it was scaffolded.

### Principle 2: The Model Must Work Through Tools

The model should not directly mutate the database.

It should request backend tools:

- inspect task;
- inspect schema;
- retrieve source context;
- inspect photo;
- propose next question;
- propose SFT candidate;
- propose DPO candidate;
- apply draft patch;
- preview submit;
- preview export.

The backend validates and executes.

### Principle 3: Evidence First

Training data should be generated from evidence packets:

- source document excerpts;
- Adam-reviewed photo context;
- Adam-confirmed memories;
- source spans;
- existing approved examples;
- boundary/permission state.

Every SFT/DPO candidate should carry:

- source refs;
- evidence snippets;
- truth status;
- synthetic status;
- why it was generated;
- why it is safe or not safe to export.

### Principle 4: Adam Edits the Training Data, Not the Plumbing

The forms/board can remain, but the main interaction should be:

```text
Assistant: Here is the photo/document/pair. Here is what I think matters. Is this person Charles? Where was this? Should this be used for voice?
Adam: ...
Assistant: I updated the context and generated two candidate prompt pairs. This one is weak because...
Adam: Use this wording instead.
Assistant: Applied. Ready to submit?
```

### Principle 5: Never Export Scaffolds As Serious Training Data

Approved export rows should never silently include:

- placeholder responses;
- filename-only prompts;
- no-call vision guesses;
- unreviewed model guesses;
- deterministic scaffolds;
- generic generated text without evidence.

If Adam explicitly approves a scaffold-derived row, it must be tagged as such.

## 7. Target Architecture

### 7.1 AI Workbench Agent

Add a new backend orchestration layer:

```text
apps/api/app/services/ai_workbench_agent.py
```

Responsibilities:

- build context packets;
- expose callable tools;
- call the model;
- execute validated tool requests;
- return UI-ready state;
- log provenance.

This should eventually replace the ad hoc split between:

- `chat_operator.py`;
- `operator_assistant.py`;
- prompt-pair helper logic;
- photo context helper logic.

### 7.2 Tool Contract

Initial tools:

```json
[
  {
    "name": "inspect_current_ticket",
    "effect": "read"
  },
  {
    "name": "inspect_schema",
    "effect": "read"
  },
  {
    "name": "retrieve_source_context",
    "effect": "read"
  },
  {
    "name": "analyze_photo",
    "effect": "model_call"
  },
  {
    "name": "propose_next_question",
    "effect": "model_plan"
  },
  {
    "name": "draft_sft_candidate",
    "effect": "model_call"
  },
  {
    "name": "draft_dpo_candidate",
    "effect": "model_call"
  },
  {
    "name": "apply_draft_patch",
    "effect": "draft_mutation"
  },
  {
    "name": "preview_submit",
    "effect": "submit_preview"
  },
  {
    "name": "preview_export",
    "effect": "export_preview"
  }
]
```

The model chooses tools. The backend executes tools.

### 7.3 Agent Response Shape

Every response should include:

```ts
type AgentTurn = {
  assistantMessage: string
  modelStatus: 'live_model_call' | 'fallback' | 'scaffold' | 'cached' | 'error'
  modelName?: string
  modelResponseId?: string
  toolCalls: ToolCallReceipt[]
  appliedMutations: MutationReceipt[]
  evidenceRefs: EvidenceRef[]
  nextQuestion?: string
  activeObject: WorkbenchObject
}
```

### 7.4 Workbench Object Schema Awareness

The agent must be given machine-readable object contracts:

- PhotoReviewTicket
- VisionDraftReviewTicket
- SourceReviewTicket
- PromptPairCandidate
- SFTCandidate
- DPOPair
- TrainingBoardItem
- DatasetExport

The agent should not rely on hardcoded field names in prose. It should inspect the object contract for the current ticket.

## 8. Roadmap

### Phase 0: Stop the Confusion

Goal: Make the current app honest about what is AI and what is scaffold.

Tasks:

1. Add a global AI status panel:
   - text model ready;
   - vision model ready;
   - embeddings ready;
   - current model names;
   - current gates.

2. Add per-output provenance badges:
   - Live model;
   - No-call scaffold;
   - Deterministic fallback;
   - Adam-authored;
   - Adam-reviewed model output.

3. Add export gate:
   - block approved export when row source is scaffold unless Adam explicitly marks it approved.

Verification:

- Model status endpoint reports true local state.
- UI cannot display scaffold content as if it were live model output.
- Existing deterministic tests remain deterministic.

### Phase 1: AI Spine Audit Endpoint

Goal: Create a live inventory of what is real AI vs fallback.

Add:

```http
GET /api/ai-spine/audit
```

Response categories:

- `live_text_paths`
- `live_vision_paths`
- `fallback_paths`
- `scaffold_paths`
- `export_risk_paths`
- `missing_model_integrations`

Example:

```json
{
  "text_generation": {
    "configured": true,
    "ready": true,
    "live_paths": ["chat_operator", "pair_generation", "model_generation"]
  },
  "vision": {
    "configured": false,
    "ready": false,
    "blocked_paths": ["vision_draft_batch"]
  },
  "risks": [
    "vision pipeline creates no-call drafts",
    "source pair generation has deterministic fallbacks",
    "embedding provider is not fully active"
  ]
}
```

Verification:

- Endpoint matches env state.
- Endpoint identifies vision as not actually live.
- Endpoint identifies scaffold export risks.

### Phase 2: Real Agent Chat Loop

Goal: Make Chat a tool-using workbench operator.

Replace the current single JSON-plan model call with:

1. Build context packet.
2. Call model with tool contracts.
3. Execute read-only tools.
4. Optionally call model again with tool results.
5. Apply only validated draft mutations.
6. Return receipts.

Initial scope:

- current task only;
- source retrieval limited to linked object;
- photo analysis only if image is available and enabled;
- no submit/export without confirmation.

Verification:

- Chat can answer: "what object am I editing?"
- Chat can inspect schema before changing fields.
- Chat can move chosen/rejected using backend patch tool.
- Chat can ask one useful follow-up question based on object state.
- Chat logs model response ID and tool receipts.

### Phase 3: Live Vision Pipeline

Goal: Let the app truly look at photos.

Current vision code defines the schema but blocks live calls. Implement:

1. `analyze_photo_with_model(asset_id, schema)`.
2. Use Responses API with image input.
3. Store output as `system_inference`.
4. Create `vision_draft_review` task.
5. Chat can use that draft to ask Adam targeted questions.

Important safety rule:

- The model may say "appears to be a man at a beach."
- It may not assert "this is Charles" unless source context says so.
- Adam's confirmation becomes the truth-bearing layer.

Verification:

- Given a photo asset, the API makes a real model call when enabled.
- The task shows model observations and uncertainty.
- UI clearly labels output as unreviewed system inference.
- Submit promotes only Adam-reviewed fields.

### Phase 4: Large Document / Journal Understanding

Goal: Make the system useful for large text inputs.

Implement:

1. Chunk source documents.
2. Extract candidate spans.
3. Embed chunks.
4. Retrieve evidence by theme/question.
5. Ask model to propose prompt pairs from evidence packets.
6. Require citations for each proposed pair.

The user experience should be:

```text
Assistant: I found three passages about cooking, war memory, and Portland. Do you want to make training examples from cooking first?
Adam: yes
Assistant: Here are two candidate prompts and a draft answer. The answer uses source spans A and C. What should be changed?
```

Verification:

- Prompt-pair generation refuses to create examples without evidence refs.
- Each generated pair links to source chunks.
- The UI can open the cited source excerpt.
- Export includes provenance.

### Phase 5: AI-Assisted SFT/DPO Creation

Goal: Make training examples from evidence and Adam feedback, not loose scaffolds.

For SFT:

- generate a prompt;
- generate a draft response;
- show evidence;
- let Adam rewrite;
- store final answer as Adam-approved.

For DPO:

- chosen = Adam-approved or model draft after Adam approval;
- rejected = weaker comparison target;
- reason = explicit failure mode;
- model may propose rejected side, but Adam must approve reason.

Verification:

- DPO export cannot proceed without chosen, rejected, and reason.
- Chosen/rejected are visibly distinct.
- The rejected side is not silently fabricated as final truth.
- Adam can edit via chat or form and the same draft object updates.

### Phase 6: Conceptual Photo Memory Layer

Goal: Make photos useful to future models/agents conceptually.

Build a reviewed photo memory layer:

```text
Photo pixels -> vision inference -> Adam questions -> Adam-reviewed context -> memory/profile -> retrieval embedding -> prompt-pair evidence
```

Each photo should accumulate:

- visible description;
- people;
- place/date;
- Adam's memory/context;
- privacy boundary;
- retrieval cues;
- associations to documents or other photos;
- downstream permissions.

Verification:

- Chat can show a photo and ask image-specific questions.
- Chat can remember Adam's answer as photo context.
- Photo context becomes retrievable.
- Prompt-pair generation can cite reviewed photo context.

### Phase 7: Training Dataset Assembly

Goal: Make exports feel like building a high-quality training file.

The board is useful here, but it should be secondary to quality.

Done pile should show:

- approved SFT examples;
- approved DPO pairs;
- source evidence;
- model/scaffold provenance;
- boundary status;
- export eligibility;
- batch inclusion.

Export should:

- include only approved rows;
- preserve source refs;
- preserve truth/synthetic status;
- preserve evidence refs;
- provide review manifests;
- provide JSONL.

Verification:

- Done count matches approved artifact count.
- Export preview matches Done eligible rows.
- Exported rows show dataset export IDs.
- No blocked/candidate rows appear in final JSONL.

## 9. Concrete Next Implementation Pass

The next pass should be small and decisive:

### Build `ai_spine_audit`

Files:

```text
apps/api/app/routers/ai_spine.py
apps/api/app/services/ai_spine_audit.py
apps/web/src/components/AISpinePanel.tsx
```

Capabilities:

- Show which paths are live.
- Show which paths are scaffold.
- Show current env gates.
- Show risks.
- Link to affected workbench areas.

### Add Live/Scaffold Badges Everywhere

Affected UI:

- Chat header;
- photo/vision task panels;
- prompt-pair generation panels;
- training board cards;
- export previews.

### Add One Real Live Smoke Test Script

Not CI by default.

```text
scripts/live_ai_smoke.py
```

Checks:

- model status ready;
- one text chat turn uses live model;
- model response ID is recorded;
- no submit/export happens;
- output is marked model-generated.

### Then Implement Live Vision

Only after the audit makes scaffold/liveness visible.

## 10. Testing Strategy

Keep deterministic tests.

Hardcoded model responses in tests are not the problem. They are necessary.

Add model-eval smoke checks separately:

- not run in CI unless explicitly requested;
- require `OPENAI_API_KEY`;
- require `TEXT_GENERATION_LIVE_CALLS_ENABLED=true`;
- require explicit `RUN_LIVE_AI_SMOKE=true`.

Test classes:

1. Deterministic safety tests:
   - patch validation;
   - no unconfirmed submit;
   - no scaffold export;
   - no source prompt reuse;
   - no mutation without backend validation.

2. Live AI smoke tests:
   - live chat turn records model ID;
   - live pair generation returns cited candidates;
   - live vision draft returns schema-valid system inference.

3. Product workflow tests:
   - photo -> vision -> Adam answer -> reviewed memory;
   - source -> retrieval -> SFT candidate -> Adam edit -> approved export;
   - SFT candidate -> DPO pair -> done board -> JSONL export.

## 11. Acceptance Criteria For Reset

The project is back on track when:

1. Adam can open Chat and know whether it is using a live model.
2. Chat can inspect the active object and schema.
3. Chat can ask image-specific questions after a real vision call.
4. Chat can retrieve source excerpts from large documents.
5. Chat can propose SFT/DPO candidates from cited evidence.
6. Adam can edit those candidates naturally.
7. The system stores Adam-reviewed context separately from model inference.
8. Final exports exclude unreviewed scaffolds.
9. Approved examples visibly accumulate.
10. Every training row has provenance.

## 12. Immediate Recommendation

Do not build more UI until the AI spine is visible.

The next merge should be:

```text
AI spine audit + honest liveness/scaffold badges + live smoke script
```

Then:

```text
Live vision pipeline
```

Then:

```text
Evidence-backed source-to-SFT/DPO generation
```

That sequence will move the project away from "workflow UI with occasional AI" and toward the intended product: an intelligent training-data workbench for building a high-quality Charles model/agent.
