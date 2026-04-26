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
```

The real local credential values belong in `.env`, which is ignored by git. Docker Compose passes the `NEXT_PUBLIC_GOOGLE_*` values through to `apps/web`.

The current Drive import MVP stores selected Drive file metadata and provenance first. It creates CharlesOps asset, external reference, object file, snapshot, boundary, annotation, and triage task records; binary mirroring/export is intentionally deferred to the next asset pipeline step.

## GitHub Sync

This project is synced to the private GitHub repository `adamrotmil/chas`.

```bash
git remote -v
git push origin main
```
