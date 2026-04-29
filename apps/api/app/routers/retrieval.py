from typing import Any, Dict

from fastapi import APIRouter, Depends, Query, Response
from sqlmodel import Session

from app.db.session import get_session
from app.services.retrieval import (
    photo_memory_embedding_corpus,
    photo_memory_embedding_export,
    retrieval_gap_review_slice,
    reviewed_photo_memory_demo_readiness,
    search_embedding_records,
)

router = APIRouter(prefix="/retrieval", tags=["retrieval"])


@router.get("/search")
def search_retrieval(
    q: str = Query(..., min_length=1),
    scope: str = Query(default="family_private", pattern="^(public|family_private|private)$"),
    limit: int = Query(default=10, ge=1, le=50),
    session: Session = Depends(get_session),
) -> Dict[str, Any]:
    return search_embedding_records(session=session, query=q, scope=scope, limit=limit)


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
