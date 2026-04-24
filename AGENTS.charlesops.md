# AGENTS.md — CharlesOps

## Mission

Build CharlesOps: a human-in-the-loop production asset library and annotation engine for turning a large personal archive into downstream-ready memory, voice, retrieval, training, eval, and gallery assets.

## Canonical spec

Read `docs/charlesops_v1_master_architecture_and_build_spec.md` before making architectural changes.

## Non-negotiables

- Do not build a chatbot first.
- Do not mutate raw source files.
- Do not collapse source truth, Adam memory, model inference, and generated reconstruction.
- Do not use sensitive/private assets in exports without boundary clearance.
- Do not store large media as ordinary DB row blobs by default; use object storage paths.
- Do not call fine-tuning APIs in MVP.
- Keep schemas explicit and migrations versioned.
- Every task completion should create durable annotations and downstream-useful records.

## Build order

1. Core schema.
2. Task engine.
3. Workbench UI.
4. Asset mirror/import.
5. Gold voice edit workflow.
6. Context pack builder.
7. Export compiler.
8. Gallery prototype.

## Truth statuses

Use these labels consistently:

- archival_source
- spoken_source
- adam_memory
- adam_inference
- system_inference
- model_generated
- adam_expert_reconstruction
- interpretive_synthesis

## Boundary rules

All assets/segments/memories/examples require boundary fields before downstream export.

## Tests

Add tests for:

- task lifecycle transitions,
- boundary gate logic,
- gold voice edit export creation,
- dataset export manifests,
- asset mirror records,
- context pack permission filtering.
