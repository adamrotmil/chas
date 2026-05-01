# Model Starter Decision

## Decision

Integrate the model starter into the existing CharlesOps Workbench as a first-class export target.

## Why

The Workbench already owns the review concepts that matter for trainer-ready output: source review, prompt pairs, gold edits, boundary gates, dataset exports, and downstream artifacts. A separate skinny app would prove the package shape, but it would not compound with the real review pipeline.

## Implementation Shape

- Add durable `model_starter_sft_examples` and `model_starter_dpo_pairs` tables.
- Add `/api/model-starter/*` endpoints for create, edit, delete, validate, split, and zip export.
- Add a `Model Starter` Workbench tab for direct editing and export preview.
- Keep the starter package human-readable and portable:
  - `data/charles_sft.jsonl`
  - `data/charles_dpo.jsonl`
  - `configs/train_sft.yaml`
  - `scripts/check_jsonl.py`
  - `scripts/split_canary_val.py`
  - `data/README.md`
  - `.gitignore`

## Non-Goals In This Pass

- No fine-tuning API calls.
- No automatic upload to a training provider.
- No claim that raw reviewed photos or prompt candidates are training truth until Adam approves them.

## Validation Standard

The feature is valid only if the exported zip can be extracted and its scripts can validate/split the JSONL files from inside the package.
