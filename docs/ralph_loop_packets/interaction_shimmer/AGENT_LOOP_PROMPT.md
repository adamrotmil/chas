# Agent Loop Prompt: Interaction Shimmer Project

You are working autonomously on an interaction-heavy product prototype.

Your job is to make the system visibly interactive, inspectable, reversible, and remixable.

Do not optimize for static screens. Optimize for observable cause and effect.

## Vision Notes

- Show the interactions.
- Show the shimmer.
- Let the user drag sliders.
- Let the user adjust parameters.
- Show what changes.
- Explain why it changed.
- Make changes observable.
- Let the user go back.
- Let the user combine ideas.
- Show the remix.
- Decide where chat belongs and make it useful.
- Make agents, sub-agents, swarms, and loops visible as work, not magic.

## Operating Rules

1. Start by reading `RALPH_LOOP_OBJECTIVES.md` and `TEST_CHECKLIST.md`.
2. Inspect the target codebase.
3. Identify the smallest objective that can be made testably better.
4. Write a short plan.
5. Implement the change.
6. Run tests that prove the behavior.
7. If tests fail, write a new plan and continue.
8. If tests pass, commit the checkpoint and move to the next objective.
9. Keep looping until the strict tests pass or a genuine blocker is documented.

## Product Bias

Prefer:

- Direct manipulation over hidden configuration.
- Real-time preview over delayed submit.
- Comparison over replacement.
- Reversible exploration over destructive editing.
- Plain explanations over mysterious model behavior.
- Inspectable artifacts over hidden agent output.

Avoid:

- Decorative shimmer with no pending state.
- Chat that gives generic advice.
- Agents that work invisibly.
- Controls whose effects cannot be observed.
- "Done" claims without tests.

## Minimum First Milestone

The first useful milestone should prove this loop can produce an interaction workbench:

- One visible preview.
- One slider.
- One parameter control.
- One "What changed" explanation.
- One undo/history mechanism.
- One automated test that changes a control and verifies the output changed.

After that, expand toward remix, chat, and agent-loop visibility.

## Reporting Format

At the end of each checkpoint, write:

```text
Checkpoint:
- Goal attempted:
- What changed:
- Files changed:
- Tests run:
- Tests passed:
- Tests failed:
- Remaining gaps:
- Next loop plan:
```

Do not stop after a cosmetic change if the interaction remains untestable.
