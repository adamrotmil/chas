# CharlesOps v1 Codex Kickoff Prompt

Paste this to Codex after placing `charlesops_v1_master_architecture_and_build_spec.md` in the repo under `docs/`.

```text
You are building CharlesOps, a single-user human-in-the-loop production asset library and annotation engine for a large personal archive.

Read docs/charlesops_v1_master_architecture_and_build_spec.md carefully and treat it as the canonical product/engineering spec.

Your first task is Phase 0 + Phase 1 scaffolding only. Do not build a chatbot. Do not call real fine-tuning APIs. Do not implement live model generation yet. Do not mutate raw source files.

Build a monorepo with:
- apps/web: Next.js + React + TypeScript workbench shell
- apps/api: FastAPI + SQLAlchemy/SQLModel + Alembic
- Postgres via docker-compose
- local object storage folders under storage/
- seed demo data for assets, tasks, annotations, boundaries, memories, prompt/generation/gold-edit records

Implement database models and migrations for at least:
assets, external_refs, asset_snapshots, object_files, derivatives, segments, entities, entity_aliases, memories, memory_sources, graph_edges, boundaries, tasks, annotations, prompt_specs, context_packs, context_pack_items, generations, generation_reviews, gold_voice_examples, anti_patterns, style_rules, sft_candidates, dpo_pairs, eval_cases, dataset_exports, dataset_export_items, galleries, gallery_items.

Implement API endpoints for:
- health
- assets list/detail/create/update
- tasks list/next/detail/submit/skip/flag
- annotations create/list
- boundaries create/update/get
- memories create/update/list/detail
- prompt specs/generations/gold voice examples
- dataset export stub

Implement the web shell with:
- dashboard
- task queue selector
- task detail workbench
- generic task submit flow
- task-specific forms for asset_triage, photo_context, text_segment_review, boundary_review, email_voice_sample, and gold_voice_edit

Seed at least:
- 3 assets: photo, text, audio
- 6 tasks, one for each MVP task type
- 2 memories
- 1 context pack
- 1 generation draft
- 1 gold voice edit example

Acceptance:
- docker compose up starts DB/API/Web
- migrations run
- seed data loads
- web can display tasks
- submitting a task creates an annotation and updates task status
- gold voice edit submission creates or updates gold_voice_example, sft_candidate, dpo_pair, eval_case, and anti_pattern records
- basic JSONL export endpoint returns SFT and DPO examples from approved candidates

Keep the code simple, inspectable, typed, and testable. Create README setup instructions and an AGENTS.md with project rules.
```
