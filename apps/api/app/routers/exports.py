from typing import List

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlmodel import Session, select

from app.db.session import get_session
from app.exports.jsonl import dpo_export_items, export_dry_run, sft_export_items, to_jsonl
from app.models import DatasetExport, DatasetExportItem
from app.schemas import DatasetBuildRequest

router = APIRouter(prefix="/dataset-exports", tags=["dataset exports"])


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
        manifest={
            "item_count": len(items),
            "format": "jsonl",
            "dry_run": {
                "included_count": dry_run["included_count"],
                "excluded_count": dry_run["excluded_count"],
                "excluded": [
                    {
                        "artifact_type": item["artifact_type"],
                        "artifact_id": item["artifact_id"],
                        "source_gold_voice_example_id": item["source_gold_voice_example_id"],
                        "reasons": item["reasons"],
                    }
                    for item in dry_run["excluded"]
                ],
            },
        },
    )
    session.add(export)
    session.flush()

    for item in items:
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
                boundary_snapshot={"boundary_gate_passed": True},
                quality_snapshot={"status": "approved"},
            )
        )

    session.commit()
    session.refresh(export)
    return export


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
