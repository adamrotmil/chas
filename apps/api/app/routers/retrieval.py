from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlmodel import Session

from app.config import Settings, get_settings
from app.db.session import get_session
from app.services.embeddings import embed_ready_embedding_records, live_embedding_ready
from app.services.retrieval import (
    photo_memory_embedding_corpus,
    photo_memory_embedding_export,
    ranked_evidence_clusters,
    retrieval_gap_review_slice,
    reviewed_photo_memory_demo_readiness,
    search_embedding_records,
    unified_evidence_corpus,
)

router = APIRouter(prefix="/retrieval", tags=["retrieval"])


@router.get("/embeddings/status")
def embedding_status(app_settings: Settings = Depends(get_settings)) -> Dict[str, Any]:
    return {
        "embedding_model": app_settings.embedding_model,
        "embedding_live_calls_enabled": app_settings.embedding_live_calls_enabled,
        "openai_api_key_configured": bool(app_settings.openai_api_key),
        "embedding_live_ready": live_embedding_ready(app_settings),
        "vector_storage": "local_json_file",
        "vector_values_in_db": False,
        "vector_values_in_exports": False,
    }


@router.post("/embeddings/live-batch")
def create_live_embedding_batch(
    limit: int = Query(default=20, ge=1, le=100),
    session: Session = Depends(get_session),
    app_settings: Settings = Depends(get_settings),
) -> Dict[str, Any]:
    if not live_embedding_ready(app_settings):
        raise HTTPException(
            status_code=400,
            detail="Live embeddings require EMBEDDING_LIVE_CALLS_ENABLED=true and OPENAI_API_KEY.",
        )
    result = embed_ready_embedding_records(session=session, limit=limit, app_settings=app_settings)
    session.commit()
    return result


@router.get("/search")
def search_retrieval(
    q: str = Query(..., min_length=1),
    scope: str = Query(default="family_private", pattern="^(public|family_private|private)$"),
    limit: int = Query(default=10, ge=1, le=50),
    session: Session = Depends(get_session),
    app_settings: Settings = Depends(get_settings),
) -> Dict[str, Any]:
    return search_embedding_records(session=session, query=q, scope=scope, limit=limit, app_settings=app_settings)


@router.get("/evidence-corpus")
def evidence_corpus(
    scope: str = Query(default="family_private", pattern="^(public|family_private|private)$"),
    limit: int = Query(default=100, ge=1, le=1000),
    include_unreviewed: bool = Query(default=False),
    session: Session = Depends(get_session),
) -> Dict[str, Any]:
    return unified_evidence_corpus(
        session=session,
        scope=scope,
        limit=limit,
        include_unreviewed=include_unreviewed,
    )


@router.get("/evidence-clusters")
def evidence_clusters(
    q: str = Query(..., min_length=1),
    scope: str = Query(default="family_private", pattern="^(public|family_private|private)$"),
    limit: int = Query(default=6, ge=1, le=10),
    per_cluster_limit: int = Query(default=3, ge=1, le=5),
    session: Session = Depends(get_session),
    app_settings: Settings = Depends(get_settings),
) -> Dict[str, Any]:
    return ranked_evidence_clusters(
        session=session,
        query=q,
        scope=scope,
        limit=limit,
        per_cluster_limit=per_cluster_limit,
        app_settings=app_settings,
    )


@router.get("/gap-review-slice")
def retrieval_gap_slice(
    q: str = Query(..., min_length=1),
    scope: str = Query(default="family_private", pattern="^(public|family_private|private)$"),
    limit: int = Query(default=5, ge=1, le=10),
    session: Session = Depends(get_session),
) -> Dict[str, Any]:
    return retrieval_gap_review_slice(session=session, query=q, scope=scope, limit=limit)


@router.get("/photo-memory-corpus")
def photo_memory_corpus(
    scope: str = Query(default="family_private", pattern="^(public|family_private|private)$"),
    limit: int = Query(default=100, ge=1, le=1000),
    include_machine_drafts: bool = Query(default=False),
    session: Session = Depends(get_session),
) -> Dict[str, Any]:
    return photo_memory_embedding_corpus(
        session=session,
        scope=scope,
        limit=limit,
        include_machine_drafts=include_machine_drafts,
    )


@router.get("/photo-memory-corpus/export")
def photo_memory_corpus_export(
    scope: str = Query(default="family_private", pattern="^(public|family_private|private)$"),
    limit: int = Query(default=100, ge=1, le=1000),
    include_machine_drafts: bool = Query(default=False),
    session: Session = Depends(get_session),
) -> Dict[str, Any]:
    return photo_memory_embedding_export(
        session=session,
        scope=scope,
        limit=limit,
        include_machine_drafts=include_machine_drafts,
    )


@router.get("/photo-memory-corpus/export.jsonl")
def photo_memory_corpus_export_jsonl(
    scope: str = Query(default="family_private", pattern="^(public|family_private|private)$"),
    limit: int = Query(default=100, ge=1, le=1000),
    include_machine_drafts: bool = Query(default=False),
    session: Session = Depends(get_session),
) -> Response:
    export = photo_memory_embedding_export(
        session=session,
        scope=scope,
        limit=limit,
        include_machine_drafts=include_machine_drafts,
    )
    manifest = export["manifest"]
    filename = f"charlesops_photo_memory_vector_handoff_{scope}_{manifest['record_count']}.jsonl"
    return Response(
        content=export["jsonl"],
        media_type="application/x-ndjson; charset=utf-8",
        headers={"Content-Disposition": f'inline; filename="{filename}"'},
    )


@router.get("/photo-memory-corpus/export.manifest")
def photo_memory_corpus_export_manifest(
    scope: str = Query(default="family_private", pattern="^(public|family_private|private)$"),
    limit: int = Query(default=100, ge=1, le=1000),
    include_machine_drafts: bool = Query(default=False),
    session: Session = Depends(get_session),
) -> Dict[str, Any]:
    return photo_memory_embedding_export(
        session=session,
        scope=scope,
        limit=limit,
        include_machine_drafts=include_machine_drafts,
    )["manifest"]


@router.get("/photo-memory-corpus/reviewed-demo-readiness")
def photo_memory_reviewed_demo_readiness(
    scope: str = Query(default="family_private", pattern="^(public|family_private|private)$"),
    limit: int = Query(default=5, ge=1, le=50),
    session: Session = Depends(get_session),
) -> Dict[str, Any]:
    return reviewed_photo_memory_demo_readiness(session=session, scope=scope, limit=limit)
