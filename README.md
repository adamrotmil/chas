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

The API container runs migrations and seed data before starting FastAPI.

- Web: http://localhost:3000
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

## GitHub Sync

This folder is intentionally ready to become a Git repository. A good project repo name would be `adamrotmil/charlesops` or `adamrotmil/chas`. The special `adamrotmil.github.io` repo is usually reserved for GitHub Pages, so use it only if you specifically want this project to become that Pages site.

```bash
git init
git add .
git commit -m "Scaffold CharlesOps phase 0 and 1"
gh repo create adamrotmil/charlesops --private --source=. --remote=origin --push
```
