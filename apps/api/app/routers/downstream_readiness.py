from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, Depends, Query, Response
from sqlmodel import Session

from app.config import Settings, get_settings
from app.db.session import get_session
from app.services.downstream_readiness import (
    compile_downstream_artifact_audit,
    compile_downstream_artifact_manifest,
    compile_downstream_bottleneck_queue,
    compile_morning_handoff,
    compile_morning_handoff_yaml,
)

router = APIRouter(prefix="/downstream-readiness", tags=["downstream readiness"])


@router.get("/bottlenecks")
def downstream_bottlenecks(
    scope: str = Query(default="family_private", pattern="^(public|family_private|private)$"),
    limit: int = Query(default=4, ge=1, le=10),
    app_settings: Settings = Depends(get_settings),
    session: Session = Depends(get_session),
) -> Dict[str, Any]:
    return compile_downstream_bottleneck_queue(
        session=session,
        app_settings=app_settings,
        scope=scope,
        limit=limit,
    )


@router.get("/artifact-manifest")
def downstream_artifact_manifest(
    scope: str = Query(default="family_private", pattern="^(public|family_private|private)$"),
    prompt_sample_limit: int = Query(default=200, ge=1, le=500),
    vector_limit: int = Query(default=20, ge=1, le=1000),
    photo_session_query: str = Query(default="Old Orchard beach", min_length=1, max_length=200),
    app_settings: Settings = Depends(get_settings),
    session: Session = Depends(get_session),
) -> Dict[str, Any]:
    return compile_downstream_artifact_manifest(
        session=session,
        scope=scope,
        prompt_sample_limit=prompt_sample_limit,
        vector_limit=vector_limit,
        app_settings=app_settings,
        photo_session_query=photo_session_query,
    )


@router.get("/artifact-audit")
def downstream_artifact_audit(
    scope: str = Query(default="family_private", pattern="^(public|family_private|private)$"),
    prompt_sample_limit: int = Query(default=200, ge=1, le=500),
    vector_limit: int = Query(default=20, ge=1, le=1000),
    photo_session_query: str = Query(default="Old Orchard beach", min_length=1, max_length=200),
    app_settings: Settings = Depends(get_settings),
    session: Session = Depends(get_session),
) -> Dict[str, Any]:
    return compile_downstream_artifact_audit(
        session=session,
        scope=scope,
        prompt_sample_limit=prompt_sample_limit,
        vector_limit=vector_limit,
        app_settings=app_settings,
        photo_session_query=photo_session_query,
    )


@router.get("/morning-handoff")
def downstream_morning_handoff(
    scope: str = Query(default="family_private", pattern="^(public|family_private|private)$"),
    prompt_sample_limit: int = Query(default=200, ge=1, le=500),
    vector_limit: int = Query(default=20, ge=1, le=1000),
    bottleneck_limit: int = Query(default=4, ge=1, le=10),
    retrieval_gap_query: str = Query(default="Old Orchard beach", min_length=1, max_length=200),
    app_settings: Settings = Depends(get_settings),
    session: Session = Depends(get_session),
) -> Dict[str, Any]:
    return compile_morning_handoff(
        session=session,
        app_settings=app_settings,
        scope=scope,
        prompt_sample_limit=prompt_sample_limit,
        vector_limit=vector_limit,
        bottleneck_limit=bottleneck_limit,
        retrieval_gap_query=retrieval_gap_query,
    )


@router.get("/morning-handoff.yaml")
def downstream_morning_handoff_yaml(
    scope: str = Query(default="family_private", pattern="^(public|family_private|private)$"),
    prompt_sample_limit: int = Query(default=200, ge=1, le=500),
    vector_limit: int = Query(default=20, ge=1, le=1000),
    bottleneck_limit: int = Query(default=4, ge=1, le=10),
    retrieval_gap_query: str = Query(default="Old Orchard beach", min_length=1, max_length=200),
    app_settings: Settings = Depends(get_settings),
    session: Session = Depends(get_session),
) -> Response:
    yaml_body = compile_morning_handoff_yaml(
        session=session,
        app_settings=app_settings,
        scope=scope,
        prompt_sample_limit=prompt_sample_limit,
        vector_limit=vector_limit,
        bottleneck_limit=bottleneck_limit,
        retrieval_gap_query=retrieval_gap_query,
    )
    filename = f"charlesops_morning_handoff_{scope}.yaml"
    return Response(
        content=yaml_body,
        media_type="text/yaml; charset=utf-8",
        headers={"Content-Disposition": f'inline; filename="{filename}"'},
    )
