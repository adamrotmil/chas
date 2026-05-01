# Agent Loop Instructions: Charles Model Starter Workbench

## Goal

Create a minimal, working “Charles model starter” capability while working inside the existing workbench.

The loop may choose either path:

1. **Integrate into the existing workbench**
   - Add screens, routes, API endpoints, and export utilities that let the user create, inspect, validate, and export SFT/DPO starter datasets.
2. **Create a skinny version alongside the workbench**
   - A focused mini-app or module that does only this job well:
     - manage SFT examples
     - manage DPO preference pairs
     - validate JSONL
     - split train/validation
     - export a trainer-ready starter package

The outcome should be a practical starter system, not a speculative architecture.

---

## Product Definition

The user wants a small end-to-end workflow for persona reconstruction training data.

The core concept:

- **SFT** teaches: “what would Charles say?”
- **DPO** teaches: “this feels more like Charles than that”
- The workbench should help produce clean, versionable data artifacts:
  - `charles_sft.jsonl`
  - `charles_dpo.jsonl`
  - `train_sft.yaml`
  - validation/split scripts
  - a zip export

---

## Required User Stories

### 1. Create SFT examples

As a user, I can create/edit/delete SFT examples with:

- `id`
- `instruction`
- `response`
- `voice`
- `tone`
- `provenance`
- `consent_status`
- `pii_tags`
- optional notes

Minimum required fields:

- `id`
- `instruction`
- `response`

The UI should make it easy to add examples quickly.

---

### 2. Create DPO preference pairs

As a user, I can create/edit/delete preference pairs with:

- `id`
- `prompt`
- `chosen`
- `rejected`
- `provenance`
- optional `why_chosen`

Minimum required fields:

- `id`
- `prompt`
- `chosen`
- `rejected`

The UI should make the contrast obvious.

Preferred layout:

- prompt at top
- chosen response left
- rejected response right
- notes/provenance below

---

### 3. Validate JSONL readiness

As a user, I can run validation and see:

- missing required fields
- invalid JSONL
- duplicate IDs
- empty strings
- unusually short responses
- DPO examples where chosen equals rejected
- basic PII tag presence warning when names/emails appear but `pii_tags` is empty

Validation should be available from the UI and from a script/API endpoint.

---

### 4. Export starter package

As a user, I can export a zip package containing:

```text
charles-model/
├─ data/
│  ├─ charles_sft.jsonl
│  ├─ charles_dpo.jsonl
│  └─ README.md
├─ configs/
│  └─ train_sft.yaml
├─ scripts/
│  ├─ check_jsonl.py
│  └─ split_canary_val.py
└─ .gitignore
```

The exported JSONL must be newline-delimited UTF-8.

---

### 5. Split train/validation

As a user, I can produce:

```text
data/charles_sft.train.jsonl
data/charles_sft.val.jsonl
```

Default validation ratio: `0.05`.

The split should be deterministic when a seed is provided.

---

## Recommended Architecture

Prefer the smallest viable change.

### Option A: Add to existing workbench

Add a section such as:

```text
/model-starter
/model-starter/sft
/model-starter/dpo
/model-starter/export
```

Potential backend endpoints:

```text
GET    /api/model-starter/sft
POST   /api/model-starter/sft
PUT    /api/model-starter/sft/{id}
DELETE /api/model-starter/sft/{id}

GET    /api/model-starter/dpo
POST   /api/model-starter/dpo
PUT    /api/model-starter/dpo/{id}
DELETE /api/model-starter/dpo/{id}

POST   /api/model-starter/validate
POST   /api/model-starter/export
POST   /api/model-starter/split
```

Use whatever existing persistence pattern the workbench already uses.

---

### Option B: Skinny version

If the workbench is currently too broad or fragile, create:

```text
apps/model-starter/
```

or

```text
apps/skinny-model-starter/
```

It should still share utility code where sensible.

The skinny version should include:

- simple list/detail UI
- local JSON storage or existing DB adapter
- export zip endpoint
- scripts and tests

---

## Data Schemas

### SFT JSONL row

```json
{
  "id": "001",
  "provenance": "memoir_notes_2024_10.md#L120",
  "voice": "telegraphic",
  "tone": "intimate",
  "consent_status": "author",
  "pii_tags": ["name:Charles"],
  "instruction": "Write a short note to Julia about the Zeiss lens habit—keep it in your voice.",
  "response": "Julia—\nlight first. glass second. the frame… comes last.\n…you carry less. see more.\n—dad"
}
```

Required:

```text
id, instruction, response
```

Recommended:

```text
provenance, voice, tone, consent_status, pii_tags
```

---

### DPO JSONL row

```json
{
  "id": "p001",
  "provenance": "sft_001_variants",
  "prompt": "Write a short note to Julia about the Zeiss lens habit—keep it in your voice.",
  "chosen": "Julia—\nlight first. glass second. the frame… comes last.\n…you carry less. see more.\n—dad",
  "rejected": "Hi Julia! When selecting optics, prioritize image quality and portability. Love, Dad",
  "why_chosen": "Chosen preserves compression, intimacy, sensory order, and non-generic cadence."
}
```

Required:

```text
id, prompt, chosen, rejected
```

Recommended:

```text
provenance, why_chosen
```

---

## Seed Examples

Include at least these starter examples unless the existing workbench already has better examples.

### SFT

```jsonl
{"id":"001","provenance":"starter_seed","voice":"telegraphic","tone":"intimate","consent_status":"author","pii_tags":["name:Charles","name:Julia"],"instruction":"Write a short note to Julia about the Zeiss lens habit—keep it in your voice.","response":"Julia—\nlight first. glass second. the frame… comes last.\n…you carry less. see more.\n—dad"}
{"id":"002","provenance":"starter_seed","voice":"public_intellectual","tone":"reflective","consent_status":"author","pii_tags":[],"instruction":"Explain your credo on small details in street photography.","response":"Details are the hinge. Not decoration. A door swings on them; the city opens or stays shut. I wait for the stray sleeve, the ash, the hand about to knock."}
```

### DPO

```jsonl
{"id":"p001","provenance":"starter_seed","prompt":"Write a short note to Julia about the Zeiss lens habit—keep it in your voice.","chosen":"Julia—\nlight first. glass second. the frame… comes last.\n…you carry less. see more.\n—dad","rejected":"Hi Julia! When selecting optics, prioritize image quality and portability. Love, Dad","why_chosen":"Chosen preserves elliptical cadence, intimacy, and object-specific memory."}
{"id":"p002","provenance":"starter_seed","prompt":"Explain your credo on small details in street photography.","chosen":"Details are the hinge. Not decoration. A door swings on them; the city opens or stays shut. I wait for the stray sleeve, the ash, the hand about to knock.","rejected":"In photography, details are important because they contribute to overall composition.","why_chosen":"Chosen feels specific, aphoristic, visual, and less generic."}
```

---

## Training Config Template

Create this in the export package:

```yaml
dataset: "./data/charles_sft.jsonl"
template: "instruction-response"
tokenizer: "auto"
model: "your-base-model-name"
epochs: 3
batch_size: 8
learning_rate: 2e-5
max_seq_len: 4096
save_dir: "./checkpoints/sft"
eval_subset: "val"
logging_steps: 25
```

---

## Required Scripts

### `scripts/check_jsonl.py`

Must validate both SFT and DPO shapes.

Expected behavior:

```bash
python scripts/check_jsonl.py data/charles_sft.jsonl --type sft
python scripts/check_jsonl.py data/charles_dpo.jsonl --type dpo
```

Output should include:

- checked count
- warnings count
- errors count
- line-level issues

Exit non-zero on errors.

---

### `scripts/split_canary_val.py`

Expected behavior:

```bash
python scripts/split_canary_val.py data/charles_sft.jsonl --val-ratio 0.05 --seed 42
```

Output:

```text
data/charles_sft.train.jsonl
data/charles_sft.val.jsonl
```

Requirements:

- deterministic with seed
- preserve UTF-8
- do not mutate source file

---

## UI Requirements

Keep this simple.

### Main page

Show:

- count of SFT examples
- count of DPO pairs
- validation status
- export button
- quick actions:
  - New SFT example
  - New DPO pair
  - Run validation
  - Export zip

### SFT table

Columns:

- ID
- voice
- tone
- instruction preview
- response preview
- provenance
- validation status

### DPO table

Columns:

- ID
- prompt preview
- chosen preview
- rejected preview
- provenance
- validation status

### Editor

Use large text areas. This is a writing workflow, not a tiny form workflow.

---

## Agent Loop Procedure

Run the loop autonomously.

### Phase 1: Inspect

- Identify current app structure.
- Find existing export/data/model-status/gallery/prompt-pair patterns.
- Reuse existing conventions where practical.
- Decide Option A or Option B.
- Document the decision in `docs/model_starter_decision.md`.

### Phase 2: Implement backend/data layer

- Add schemas/types.
- Add validation utilities.
- Add persistence.
- Add export package builder.
- Add split function.

### Phase 3: Implement UI

- Add model starter landing page.
- Add SFT list/editor.
- Add DPO list/editor.
- Add validation/export controls.

### Phase 4: Add scripts

- Add CLI validation script.
- Add CLI split script.
- Ensure they can run independently.

### Phase 5: Tests

Add tests for:

- valid SFT row
- invalid SFT missing response
- valid DPO row
- invalid DPO chosen equals rejected
- duplicate IDs
- export zip contains expected files
- split output is deterministic

### Phase 6: Self-evaluate

Create `docs/model_starter_eval.md` with:

- what was implemented
- what was intentionally deferred
- how to run it
- screenshots or route names if screenshots are not practical
- known risks
- next recommended loop

### Phase 7: Commit

Commit meaningful increments.

Suggested commit sequence:

```text
feat(model-starter): add schemas and validation utilities
feat(model-starter): add export package builder
feat(model-starter): add starter UI
test(model-starter): cover validation export and split flows
docs(model-starter): add decision and eval notes
```

Do not leave the repo in a broken state between commits.

---

## Acceptance Criteria

The loop is successful when all of these are true:

- User can create SFT examples.
- User can create DPO preference pairs.
- User can validate data.
- User can export a zip with the exact starter package structure.
- Exported JSONL is valid UTF-8 newline-delimited JSON.
- Scripts run from the exported package.
- Tests pass.
- Documentation explains how to run and what was changed.
- The implementation is small enough to understand and extend.

---

## Non-Goals

Do not implement actual model training.

Do not add a heavyweight ML pipeline.

Do not require external services.

Do not overbuild annotation taxonomies.

Do not create a generic dataset platform. This is for a specific Charles persona-reconstruction workflow.

---

## Design Principle

The workbench should feel like an archive-to-training-data instrument.

Not a dashboard.

Not an ML platform.

A careful table.

A small editor.

A clean export.

A repeatable loop.
