# Ralph Loop Continuity Fix - 2026-04-29

## What Went Wrong

The previous loop stopped after focused regression tests passed. Those tests were useful, but they only proved that several local behaviors were protected. They did not prove that the larger CharlesOps product milestone was met.

The loop therefore treated "green unit tests" as the stop condition, instead of treating them as permission to re-run a stricter live product gate.

## Fix

Added `scripts/ralph_loop_gate.py`.

This script checks the running app against the next user-facing milestone. It intentionally fails while meaningful product gaps remain. Future Ralph-loop runs should start by running:

```bash
python3 scripts/ralph_loop_gate.py
```

Then the agent should pick the first failing check, write a micro-plan, implement a small increment, run focused tests, run baseline tests, and re-run the gate.

The loop should not stop while this gate is red unless there is a real blocker requiring Adam input.

## Current Gate Result

Current status: FAIL.

Passing checks:

- API is reachable.
- Web app is reachable.
- 82 mirrored photos are preview-ready.
- `Rotmil 2021 I.jpg` and `Rotmil Honors VIII.jpg` return real JPEG preview bytes.

Failing checks:

- Prompt pairs only have 1 voice mode represented; gate requires at least 4.
- Dataset export dry-runs expose 0 SFT artifacts and 0 DPO artifacts.
- Reviewed photo profiles are 0; gate requires at least 5.
- Photo-linked memories are 0; gate requires at least 5.
- Photo retrieval returns no memory results for:
  - `airplane in Maine`,
  - `food as care`,
  - `Portland harbor`.

## New Stop Rule

Focused tests passing is not a stopping condition.

The loop may stop only when:

- `python3 scripts/ralph_loop_gate.py` passes for the selected milestone,
- baseline tests pass,
- or a real blocker is recorded.
