# CharlesOps Vision Pipeline Notes

## Purpose

The vision pipeline drafts metadata for photos, scans, and handwritten material. It is an accelerator for Adam review, not a truth source.

## Provenance Rule

Vision model output is always `system_inference` until Adam reviews it. Adam-reviewed answers are stored separately from the raw model draft so CharlesOps does not collapse:

- what the image actually is,
- what a model inferred,
- what Adam knows or remembers,
- what Adam corrected or approved.

## Current Scaffold

The current implementation does not call a live model. It creates:

- a `MetadataProfile` for the asset with `metadata_status=machine_draft`,
- a `vision_draft_review` task,
- a request plan describing the future Responses API call,
- scaffolded follow-up questions for Adam.

Submitting the review task promotes the profile to `adam_reviewed` and can create a `vision_ocr_text` segment when Adam supplies or corrects OCR/handwriting text.

## Future Live Model Call

The live call should use a vision-capable Responses model with Structured Outputs. The expected output shape is versioned as `charlesops_vision_draft_v1` in `apps/api/app/services/vision.py`.

The model should draft:

- visual summary,
- visible people or uncertainty,
- place/time guesses,
- concrete objects,
- themes/tags,
- OCR and handwriting text,
- uncertainties,
- privacy flags,
- suggested questions for Adam.

## Dynamic Questions

Dynamic questions should be treated as review prompts, not schema changes. Store them as:

- `raw_profile.system_inference_draft.suggested_questions`,
- review-task `input_payload.suggested_questions`,
- Adam responses in `question_answers`.

Adam's responses can then feed:

- reviewed metadata fields,
- retrieval and embedding hints,
- memory/context notes,
- privacy decisions,
- future segmentation or prompt-pair tasks.

## Safety Gate

Because photos and journals may be private, `VISION_LIVE_CALLS_ENABLED` should remain false until Adam explicitly approves a live run and an API key/project are configured.
