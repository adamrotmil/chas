# Codex Start Prompt

You are working in the Charles workbench repo.

Your goal is to add a minimal “Charles model starter” workflow that can produce SFT and DPO starter data and export a trainer-ready zip package.

Read `AGENT_LOOP_INSTRUCTIONS.md` completely, then run an autonomous implementation loop.

Prefer the smallest practical implementation. If the existing workbench architecture supports it cleanly, integrate it. If that would cause too much complexity, create a skinny app/module alongside it.

You must:

1. Inspect the repo structure.
2. Decide integrated vs skinny.
3. Write `docs/model_starter_decision.md`.
4. Implement schemas, validation, export, split, UI, and scripts.
5. Add seed examples.
6. Add tests.
7. Write `docs/model_starter_eval.md`.
8. Commit meaningful increments.

Run tests and fix failures.

Keep going until the acceptance criteria are met or until you hit a real blocker. If blocked, document the blocker, partial progress, and the next exact command or file to modify.
