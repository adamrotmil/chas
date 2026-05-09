import hashlib
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlmodel import Session, select

from app.db.session import get_session
from app.exports.jsonl import dpo_export_items, export_dry_run, sft_export_items, to_jsonl
from app.models import DatasetExport, DatasetExportItem, utcnow
from app.schemas import DatasetBuildRequest

router = APIRouter(prefix="/dataset-exports", tags=["dataset exports"])


def _manifest_excluded(dry_run: Dict[str, Any]) -> List[Dict[str, Any]]:
    return [
        {
            "artifact_type": item["artifact_type"],
            "artifact_id": item["artifact_id"],
            "source_gold_voice_example_id": item["source_gold_voice_example_id"],
            "reasons": item["reasons"],
        }
        for item in dry_run["excluded"]
    ]


def _export_manifest(payload: DatasetBuildRequest, dry_run: Dict[str, Any], items: List[Dict[str, Any]]) -> Dict[str, Any]:
    excluded = _manifest_excluded(dry_run)
    excluded_reasons = sorted({reason for item in excluded for reason in item["reasons"]})
    source_ids = [
        str(row["source_gold_voice_example_id"])
        for row in dry_run["included"]
        if row.get("source_gold_voice_example_id")
    ]
    artifact_ids = [str(row["artifact_id"]) for row in dry_run["included"]]
    stable_item_keys = [f"{row['artifact_type']}:{row['artifact_id']}" for row in dry_run["included"]]
    jsonl = to_jsonl(items)
    return {
        "export_type": payload.export_type,
        "version": payload.version,
        "split": payload.split,
        "format": "jsonl",
        "generated_at": utcnow().isoformat().replace("+00:00", "Z"),
        "item_count": len(items),
        "included_count": dry_run["included_count"],
        "excluded_count": dry_run["excluded_count"],
        "source_ids": source_ids,
        "artifact_ids": artifact_ids,
        "stable_item_keys": stable_item_keys,
        "content_sha256": hashlib.sha256(jsonl.encode("utf-8")).hexdigest(),
        "filters": {
            "export_type": payload.export_type,
            "include_candidates": False,
            "status": "approved_only",
            "split": payload.split,
        },
        "split_policy_snapshot": {
            "requested_split": payload.split,
            "holdout_eval_split_configured": False,
            "explicit_holdout_status": "not_configured",
            "notes": (
                "MVP dataset builds only the requested approved split. "
                "Held-out demo prompts are tracked separately by /api/model-status/demo-readiness."
            ),
        },
        "excluded_reasons": excluded_reasons,
        "boundary_policy_snapshot": {
            "blocked_context_boundaries_excluded": True,
            "export_requires_boundary_gate": True,
            "private_or_sensitive_items_require_explicit_clearance": True,
        },
        "quality_policy_snapshot": {
            "candidate_items_excluded_from_build": True,
            "requires_approved_artifact_status": True,
            "response_b_major_privacy_issue_blocks_export": True,
        },
        "evidence_corpus_snapshot": dry_run.get("evidence_corpus_snapshot", {}),
        "dry_run": {
            "included_count": dry_run["included_count"],
            "excluded_count": dry_run["excluded_count"],
            "excluded": excluded,
        },
    }


@router.get("", response_model=List[DatasetExport])
def list_dataset_exports(session: Session = Depends(get_session)) -> List[DatasetExport]:
    return session.exec(select(DatasetExport).order_by(DatasetExport.created_at.desc())).all()


@router.post("/build", response_model=DatasetExport)
def build_dataset_export(
    payload: DatasetBuildRequest,
    session: Session = Depends(get_session),
) -> DatasetExport:
    try:
        dry_run = export_dry_run(session, payload.export_type)
    except ValueError:
        dry_run = {"included": [], "excluded": [], "included_count": 0, "excluded_count": 0}
    items = [item["payload"] for item in dry_run["included"]]

    export = DatasetExport(
        human_id=f"EXPORT_{payload.export_type.upper()}_{len(items):04d}",
        export_type=payload.export_type,
        version=payload.version,
        status="built",
        manifest=_export_manifest(payload, dry_run, items),
    )
    session.add(export)
    session.flush()

    for row in dry_run["included"]:
        item = row["payload"]
        source = row.get("source") or {}
        source_id = (
            item.get("metadata", {}).get("source_gold_voice_example_id")
            or item.get("metadata", {}).get("source_id")
            or "unknown"
        )
        session.add(
            DatasetExportItem(
                dataset_export_id=export.id,
                source_type=payload.export_type,
                source_id=source_id,
                split=payload.split,
                payload=item,
                boundary_snapshot={
                    "boundary_gate_passed": True,
                    "context_boundary_status": source.get("context_boundary_status"),
                    "task_receipt_boundary_status": source.get("receipt_boundary_status"),
                },
                quality_snapshot={
                    "status": row.get("export_status"),
                    "artifact_type": row.get("artifact_type"),
                    "quality_gate_passed": row.get("export_status") == "approved",
                },
            )
        )

    session.commit()
    session.refresh(export)
    return export


@router.get("/{export_id}/jsonl")
def stored_export_jsonl(
    export_id: str,
    session: Session = Depends(get_session),
) -> Response:
    export = session.get(DatasetExport, export_id)
    if export is None:
        raise HTTPException(status_code=404, detail="Dataset export not found")
    items = session.exec(
        select(DatasetExportItem).where(DatasetExportItem.dataset_export_id == export_id)
    ).all()
    source_ids = export.manifest.get("source_ids") if isinstance(export.manifest, dict) else []
    source_order = {str(source_id): index for index, source_id in enumerate(source_ids) if source_id}
    items = sorted(
        items,
        key=lambda item: (
            source_order.get(str(item.source_id), len(source_order)),
            item.source_type,
            item.source_id,
            item.id,
        ),
    )
    return Response(content=to_jsonl([item.payload for item in items]), media_type="application/x-ndjson")


@router.get("/jsonl")
def export_jsonl(
    export_type: str,
    session: Session = Depends(get_session),
) -> Response:
    if export_type == "sft":
        body = to_jsonl(sft_export_items(session))
    elif export_type == "dpo":
        body = to_jsonl(dpo_export_items(session))
    else:
        raise HTTPException(status_code=400, detail="export_type must be sft or dpo")
    return Response(content=body, media_type="application/x-ndjson")


@router.get("/dry-run")
def dry_run_dataset_export(
    export_type: str,
    include_candidates: bool = False,
    session: Session = Depends(get_session),
) -> dict:
    try:
        return export_dry_run(session, export_type, include_candidates=include_candidates)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
