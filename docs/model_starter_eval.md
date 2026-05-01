# Model Starter Evaluation

## Goal

CharlesOps must produce a package a user can take away and use as the starting point for training a Charles voice model.

## Acceptance Checks

- SFT examples can be created, edited, deleted, and listed.
- DPO pairs can be created, edited, deleted, and listed.
- Validation catches:
  - missing required SFT fields
  - missing required DPO fields
  - duplicate IDs
  - unusually short responses
  - chosen/rejected equality
  - likely PII with empty `pii_tags`
- Export zip includes the exact trainer package tree under `charles-model/`.
- Exported JSONL is newline-delimited UTF-8.
- Exported `check_jsonl.py` exits nonzero on errors and zero on valid package rows.
- Exported `split_canary_val.py` creates deterministic train/validation files without mutating the source JSONL.

## Current Status

The API and Workbench now expose the starter package as a concrete artifact rather than as a concept in the exports page. The seed rows are intentionally small but structurally complete, so the package can validate even before the larger reviewed corpus is promoted into it.

## Remaining Product Work

- Add a promotion action from approved Prompt Pairs into the model starter tables.
- Add model-provider-specific config templates once the training target is chosen.
- Add package manifest checksums and a visible last-export receipt.
- Add a richer preview of the first 20 JSONL rows in the UI.
