# CharlesOps Training Pair Quality Contract

This contract defines the shape CharlesOps should produce for SFT, DPO, eval, and draft-generation review work.

The training text should feel like a human exchange with Charles, not like an annotation task.

## Exported Conversation Shape

SFT rows should use a minimal conversation envelope:

```yaml
messages:
  - role: system
    content: You are Charles Rotmil.
  - role: user
    content: <natural user message, email, memory prompt, or thread turn>
  - role: assistant
    content: <Adam-approved Charles voice response>
```

The system prompt may be:

- `You are Charles Rotmil.`
- `You are Charles Rotmil. Write naturally in his voice.`

Avoid exporting instruction-heavy system prompts unless Adam deliberately approves one for a specific experiment.

## Keep Provenance Backstage

The exported user and assistant text must not include factory language such as:

- "Using reviewed source material..."
- "Grounding source..."
- "Draft a Charles-style response..."
- "Do not claim this is archival..."
- "[stub draft - no live model call]"

Those constraints belong in hidden metadata, context packs, task payloads, and quality gates.

Each record should still preserve backstage provenance:

- source asset ids
- source segment/chunk ids
- source title and excerpt
- truth status
- conversation family
- voice mode
- privacy and boundary clearance
- generation method
- model name and reasoning effort, if any
- Adam gold edit annotation id

## Conversation Families

Use explicit families to keep generation and review targeted:

- `verbatim_email_reply`
- `adam_prompted_memory`
- `source_based_story_recall`
- `mundane_text_message`
- `ps_digression`
- `nb_digression`
- `long_literary_source_excerpt`
- `multi_turn_thread`

Families are labels for routing, sampling, review, and eval. They should not leak into the user-facing prompt text.

## Role of Adam's Existing Prompt-Pair Corpus

Adam's curated examples are a source-grade voice artifact. They should be imported and processed like other archive material:

1. Mirror the corpus as a preserved source asset.
2. Segment it into individual prompt pairs or multi-turn threads.
3. Label each segment with conversation family, medium, voice mode, truth status, and boundaries.
4. Sample a small number of relevant exemplars into draft-generation context packs.
5. Keep exemplars out of exported rows unless that specific row is itself being exported as a training example.

The corpus is especially valuable for synthetic draft generation because it shows the shape of the whole exchange: the sparse user prompt, the implied relationship, and the way the assistant response carries voice without explaining itself.

## Draft Generation Rules

Model drafts are allowed only when explicitly enabled by environment and task decision gates. A model draft is never a gold example.

Recommended text-generation defaults:

- API: OpenAI Responses API
- model: `gpt-5.5`
- reasoning effort: `xhigh`
- output: plain text only
- generation truth status: `model_generated`

The draft should use source material and selected exemplars as grounding, but it must not quote private source text unless the relevant boundary allows quotation.

## Gold Edit Rule

The Adam gold edit is the training target.

Truth status:

```text
adam_expert_reconstruction
```

The rejected DPO side should be either:

- a real model draft generated in the same natural conversation shape, or
- a clearly marked backstage scaffold that is held out of serious DPO export unless Adam explicitly approves it.

## Quality Gate

An exportable row should pass these checks:

- The exported system/user/assistant messages contain no factory labels.
- The assistant response sounds like one of the curated examples, not a style guide.
- Boundaries permit the requested downstream use.
- The gold edit is Adam-approved.
- Source truth, Adam memory, model inference, and expert reconstruction remain distinguishable in metadata.
