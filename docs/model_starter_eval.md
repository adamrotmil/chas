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
- Approved Workbench SFT/DPO rows can be imported idempotently into the model starter tables.
- `/api/model-starter/preview` exposes the exact generated JSONL/config/script text with file-level SHA-256 checksums before download.
- `/api/model-starter/export.zip?include_split=true` can include precomputed `charles_sft.train.jsonl` and `charles_sft.val.jsonl` for a zero-command handoff while the default zip remains the exact required tree.
- The broader downstream artifact manifest lists the model starter package preview as a training-eligible artifact without calling any training API.

## Current Status

The API and Workbench now expose the starter package as a concrete artifact rather than as a concept in the exports page. The seed rows are intentionally small but structurally complete, so the package can validate even before the larger reviewed corpus is promoted into it. Approved Prompt Pair exports can now be pulled into the starter package, and the Export tab shows the exact package files and hashes that the zip will contain.

## Remaining Product Work

- Add model-provider-specific config templates once the training target is chosen.
- Add a visible last-export receipt after download/write-to-storage.
- Add a small provider-readiness note that explains which config values the user must fill in before launching a real training run.
