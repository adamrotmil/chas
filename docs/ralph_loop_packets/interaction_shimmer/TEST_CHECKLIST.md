# Test Checklist: Interaction Shimmer Project

Use this checklist to decide whether the loop should continue.

The loop should continue if any required item below is not testably true.

## Interaction Tests

- [ ] A slider can be dragged or programmatically changed.
- [ ] The slider change updates a visible output.
- [ ] A parameter control can be changed.
- [ ] The parameter change updates a visible output.
- [ ] The UI shows "What changed" after an interaction.
- [ ] The UI shows "Why it changed" after an interaction.
- [ ] Before and after states can be compared.

## Shimmer and State Tests

- [ ] A real pending operation shows shimmer or progress.
- [ ] The pending state disappears on success.
- [ ] A failed operation shows an actionable error.
- [ ] Shimmer is not visible when no work is pending.

## History Tests

- [ ] The app records interaction history.
- [ ] Undo restores the previous state.
- [ ] A history/timeline entry can be selected.
- [ ] Restoring history updates controls, preview, and explanation.

## Remix Tests

- [ ] The user can create Variant A.
- [ ] The user can create Variant B.
- [ ] The user can combine A and B.
- [ ] A Remix variant appears.
- [ ] The Remix identifies which sources it used.
- [ ] Original variants remain intact.

## Chat Operator Tests

- [ ] Chat can inspect current state.
- [ ] Chat can ask the next best missing-information question.
- [ ] Chat can apply a user answer to a real field or parameter.
- [ ] Chat logs what it changed.
- [ ] Chat can suggest readiness to generate, remix, or submit.

## Agent Visibility Tests

- [ ] A single-agent task has visible goal, status, inputs, and output.
- [ ] A sub-agent or parallel task can be represented as a child work item.
- [ ] A loop has visible current objective and latest test result.
- [ ] The user can pause or stop loop work.
- [ ] Agent output leaves an inspectable artifact.

## Ralph Loop Tests

- [ ] Every checkpoint has a plan.
- [ ] Every checkpoint has test commands and results.
- [ ] Failed tests produce the next plan.
- [ ] Passing tests name the exact proven behavior.
- [ ] Working checkpoints are committed.

## No False Pass Rules

Do not mark a checklist item complete if:

- It only works in code but is not visible in the UI.
- It only works visually but has no automated or repeatable test.
- It requires the user to infer what changed.
- It cannot be undone or inspected when the objective requires reversibility.
- It uses fake pending state instead of a real pending operation.
- It uses generic chat text instead of state-aware behavior.
