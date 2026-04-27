# CharlesOps

CharlesOps is a local-first production asset library and annotation engine for turning a personal archive into downstream-ready memory, voice, retrieval, training, eval, and gallery assets.

The canonical product and architecture spec is in [`docs/charlesops_v1_master_architecture_and_build_spec.md`](docs/charlesops_v1_master_architecture_and_build_spec.md).

## Stack

- `apps/web`: Next.js, React, TypeScript
- `apps/api`: FastAPI, SQLModel, Alembic
- `db`: Postgres via Docker Compose
- `storage/`: local object-storage folders for mirrored originals, exports, derivatives, thumbnails, display files, and transcripts

## Quick Start

1. Install Docker Desktop or another Docker Compose-compatible runtime.
2. Copy `.env.example` to `.env` if you want to customize local settings.
3. Start everything:

```bash
docker compose up --build
```

If port `3000` is already in use, run:

```bash
WEB_PORT=3003 docker compose up --build
```

The API container runs migrations and seed data before starting FastAPI.

- Web: http://localhost:3000, or the `WEB_PORT` value you chose
- API health: http://localhost:8000/api/health
- API docs: http://localhost:8000/docs

## Local Development Without Docker

API:

```bash
cd apps/api
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
export DATABASE_URL="sqlite:///./charlesops.local.sqlite"
alembic upgrade head
python -m app.seed
uvicorn app.main:app --reload
```

Web:

```bash
cd apps/web
npm install
NEXT_PUBLIC_API_BASE_URL=http://localhost:8000/api npm run dev
```

## Useful Commands

```bash
# Run backend tests
cd apps/api && pytest

# Run frontend type checks
cd apps/web && npm run typecheck

# Seed demo data again
cd apps/api && python -m app.seed

# Build JSONL export from approved candidates
curl "http://localhost:8000/api/dataset-exports/jsonl?export_type=sft"
curl "http://localhost:8000/api/dataset-exports/jsonl?export_type=dpo"
```

## Vision Draft Pipeline

The vision pipeline is scaffolded but does not call live model APIs by default. It creates review tasks and `system_inference` draft metadata for photos/scans so Adam can validate, correct, and promote useful fields.

```bash
# Create no-call vision review tasks for up to 10 photo/scan assets
curl -X POST http://localhost:8000/api/vision/drafts/batches \
  -H "Content-Type: application/json" \
  -d '{"limit":10,"no_live_model_call":true}'

# Inspect the planned structured output schema
curl http://localhost:8000/api/vision/schema
```

Future live vision calls should stay disabled until explicitly approved:

```bash
VISION_LIVE_CALLS_ENABLED=false
VISION_MODEL=gpt-4.1-mini
OPENAI_API_KEY=...
OPENAI_PROJECT_ID=...
```

See [`docs/vision_pipeline_notes.md`](docs/vision_pipeline_notes.md) for provenance and review rules.

## Google Drive Setup

The local Google Cloud project currently used for development is:

```text
gen-lang-client-0798252524
```

Required APIs:

- Google Drive API
- Google Picker API

Local browser origins for credentials:

- `http://localhost:3000`
- `http://localhost:3003`

Google Picker also needs the numeric Cloud project number:

```text
1030126815863
```

The local env variables are:

```bash
GOOGLE_CLOUD_PROJECT_ID=gen-lang-client-0798252524
NEXT_PUBLIC_GOOGLE_CLOUD_PROJECT_NUMBER=1030126815863
NEXT_PUBLIC_GOOGLE_PICKER_API_KEY=...
NEXT_PUBLIC_GOOGLE_OAUTH_CLIENT_ID=...
OBJECT_STORAGE_PROVIDER=gcs
GCS_BUCKET=charlesops-vault-1030126815863
GCS_PREFIX=charlesops
```

The real local credential values belong in `.env`, which is ignored by git. Docker Compose passes the `NEXT_PUBLIC_GOOGLE_*` values through to `apps/web`.

The Drive import flow stores selected Drive metadata and provenance first. It creates CharlesOps asset, external reference, object file, snapshot, boundary, annotation, and triage task records without mutating Drive originals.

For large vault folders, use **Scan folder** instead of manually selecting files. The scanner walks Drive folders with a configurable file cap, imports metadata in batches of 50, defaults to a 100-file dry run, includes photos/writing/email candidates, leaves audio/video off for now, and skips backup-looking folders unless you turn that off.

After a dry run, inspect the latest metadata records with:

```bash
curl http://localhost:8000/api/imports/drive/recent?limit=100
```

After a metadata import, **Mirror imported** copies the selected Drive bytes into CharlesOps-controlled object storage. Blob files are downloaded with Drive `files.get?alt=media`; native Google Docs/Sheets/Slides are exported to Office/PDF snapshots. The API records a `source_mirror` asset snapshot and points downstream processing at the copy while preserving the Drive external reference for provenance.

Google Cloud Storage is the intended canonical mirror store for this project:

```bash
OBJECT_STORAGE_PROVIDER=gcs
GCS_BUCKET=charlesops-vault-1030126815863
GCS_PREFIX=charlesops
```

The bucket is private, uses Standard storage in the US multi-region, enforces public access prevention, and uses uniform bucket-level access. Local storage remains available as a fallback by setting `OBJECT_STORAGE_PROVIDER=local`.

When GCS mode is enabled, the web app requests a temporary Google Cloud Storage OAuth scope during **Mirror imported** and passes that access token to the local API for the upload only; the token is not stored in the database.

## GitHub Sync

This project is synced to the private GitHub repository `adamrotmil/chas`.

```bash
git remote -v
git push origin main
```
