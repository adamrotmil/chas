# Ralph Loop Objectives: Interaction Shimmer Project

## North Star

Build a product experience where the user can see, manipulate, compare, rewind, and remix system behavior.

The product should answer these questions through the UI itself:

- What interaction is happening?
- What changed when I moved this control?
- Why did it change?
- How can I observe the effect?
- How do I go back?
- How do I combine two ideas?
- What is the remix?
- Where does chat help?
- What do agents actually do?
- What happens when sub-agents or loops are running?

This should feel like an interaction workbench, not a static settings page.

## Objective 1: Observable Interactions

As a user, I want every meaningful control to produce an observable change, so that I understand cause and effect.

Required behaviors:

- At least one slider changes a visible output in real time.
- At least one parameter control changes a visible output in real time.
- The UI labels what changed after each interaction.
- The UI explains why the output changed in plain language.
- The UI preserves the before and after state for comparison.

Strict tests:

- A test can move the slider and verify that a named output value changes.
- A test can change a parameter and verify that the visual preview changes.
- A test can read a visible "What changed" field after the interaction.
- A test can read a visible "Why it changed" field after the interaction.
- A test fails if the output changes silently with no explanation.

## Objective 2: Shimmer and Feedback

As a user, I want the interface to show that the system is thinking or transforming, so that state changes feel alive and legible.

Required behaviors:

- Loading, generation, preview recompute, and agent work use visible shimmer or progress states.
- Shimmer is tied to a real pending state, not decoration.
- Completed work replaces shimmer with concrete output.
- Failed work replaces shimmer with an actionable error.

Strict tests:

- A test can trigger a recompute and observe a pending visual state.
- A test can wait for completion and verify the pending state disappears.
- A test can force or simulate failure and verify an error is visible.
- A test fails if shimmer appears permanently or without a real pending operation.

## Objective 3: Backtracking and Timeline

As a user, I want to go back to earlier states, so that exploration feels safe.

Required behaviors:

- The app records interaction history.
- The user can undo at least one change.
- The user can restore a previous state from a visible timeline or history list.
- Restored state updates the output preview and explanation.

Strict tests:

- A test can make two changes, undo once, and verify the previous output returns.
- A test can select a timeline entry and verify controls and output match that entry.
- A test fails if history only logs text but cannot restore state.

## Objective 4: Combine and Remix

As a user, I want to combine two ideas or variants and create a remix, so that the product supports exploration rather than only linear editing.

Required behaviors:

- The user can create at least two variants.
- The user can select two variants and combine them.
- The remix output must explain which parts came from each source.
- The original variants remain available after remix.

Strict tests:

- A test can create Variant A and Variant B.
- A test can combine A and B.
- A test can verify a new Remix variant appears.
- A test can verify the Remix cites both source variants.
- A test fails if combine overwrites either source variant.

## Objective 5: Chat as Operator, Not Decoration

As a user, I want chat to help operate the workbench, ask useful questions, and apply my answers, so that I can move faster without hunting through fields.

Required behaviors:

- Chat can inspect current state.
- Chat can ask the next best question when required information is missing.
- Chat can apply an answer to the correct field or parameter.
- Chat can suggest when enough information exists to generate or submit.
- Chat actions are previewed or logged before/after they happen.

Strict tests:

- A test can ask chat "what should I do next?" and receive a state-aware answer.
- A test can answer a chat question and verify a field changed.
- A test can verify the chat log records what was applied.
- A test fails if chat only gives generic advice unrelated to current UI state.

## Objective 6: Agents, Sub-Agents, Swarms, and Loops

As a user, I want to understand what agents are doing, so that autonomous work feels observable and controllable.

Required behaviors:

- The app distinguishes single-agent, sub-agent, swarm, and loop work.
- Each agent task has a visible goal, status, inputs, outputs, and next step.
- The user can inspect agent work products.
- The user can stop or pause a loop.
- The loop has explicit pass/fail tests.

Strict tests:

- A test can start a loop and see an active status.
- A test can inspect at least one agent work item.
- A test can pause or stop the loop.
- A test can read the latest test result for the loop.
- A test fails if an agent completes work without leaving an inspectable artifact.

## Objective 7: Ralph Loop Discipline

As a user, I want the autonomous loop to keep moving until strict tests pass, so that "done" means verified rather than merely attempted.

Required loop behavior:

- Write a short plan before each implementation cycle.
- Implement the smallest useful improvement.
- Run the relevant tests.
- If tests fail, write the next incremental plan and continue.
- Commit only working checkpoints.
- Never mark a goal complete without a test that proves it.

Strict tests:

- Each loop report includes plan, change summary, test commands, test results, and remaining gaps.
- A failed test creates a follow-up plan.
- A passing test names the exact behavior it proves.
- A test fails if the report says "done" without command output or observable proof.
