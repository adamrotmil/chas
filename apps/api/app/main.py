from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.routers import (
    annotations,
    assets,
    boundaries,
    downstream_readiness,
    entities,
    exports,
    gallery,
    imports,
    memories,
    metadata_profiles,
    model_starter,
    model_status,
    prompt_pairs,
    photo_drafts,
    retrieval,
    segments,
    tasks,
    vision,
    voice,
)
from app.runtime_contract import runtime_contract_payload

app = FastAPI(
    title="CharlesOps API",
    version="0.1.0",
    description="Human-in-the-loop production asset library and annotation API.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
@app.get("/api/health")
def health() -> dict:
    return {"ok": True, "service": "charlesops-api"}


@app.get("/api/runtime-contract")
def runtime_contract() -> dict:
    return runtime_contract_payload()


app.include_router(assets.router, prefix="/api")
app.include_router(tasks.router, prefix="/api")
app.include_router(annotations.router, prefix="/api")
app.include_router(boundaries.router, prefix="/api")
app.include_router(downstream_readiness.router, prefix="/api")
app.include_router(entities.router, prefix="/api")
app.include_router(memories.router, prefix="/api")
app.include_router(voice.router, prefix="/api")
app.include_router(exports.router, prefix="/api")
app.include_router(gallery.router, prefix="/api")
app.include_router(imports.router, prefix="/api")
app.include_router(segments.router, prefix="/api")
app.include_router(metadata_profiles.router, prefix="/api")
app.include_router(model_starter.router, prefix="/api")
app.include_router(model_status.router, prefix="/api")
app.include_router(prompt_pairs.router, prefix="/api")
app.include_router(photo_drafts.router, prefix="/api")
app.include_router(retrieval.router, prefix="/api")
app.include_router(vision.router, prefix="/api")
