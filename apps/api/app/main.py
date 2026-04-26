from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.routers import annotations, assets, boundaries, exports, imports, memories, segments, tasks, voice

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


app.include_router(assets.router, prefix="/api")
app.include_router(tasks.router, prefix="/api")
app.include_router(annotations.router, prefix="/api")
app.include_router(boundaries.router, prefix="/api")
app.include_router(memories.router, prefix="/api")
app.include_router(voice.router, prefix="/api")
app.include_router(exports.router, prefix="/api")
app.include_router(imports.router, prefix="/api")
app.include_router(segments.router, prefix="/api")
