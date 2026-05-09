# Interaction Shimmer Ralph Loop Packet

This packet is for a separate project whose north star is not a static dashboard, but an observable interaction system.

The project should make changes feel visible:

- The user drags a slider and sees what changed.
- The user adjusts parameters and sees why the output changed.
- The user can go back, remix, combine ideas, and compare variants.
- Chat is not decorative. It helps ask the next useful question or trigger the next useful action.
- Agents, sub-agents, swarms, and loops are only valuable when their work is visible, interruptible, and auditable.

## Files

- `RALPH_LOOP_OBJECTIVES.md` defines the product objectives and strict tests.
- `AGENT_LOOP_PROMPT.md` is the prompt to hand to an autonomous coding agent.
- `TEST_CHECKLIST.md` is the pass/fail checklist for each loop.

## Intended Use

Copy this folder into the target project and start the loop from `AGENT_LOOP_PROMPT.md`.

The loop should keep making incremental progress until the tests in `TEST_CHECKLIST.md` pass without hand-waving.
