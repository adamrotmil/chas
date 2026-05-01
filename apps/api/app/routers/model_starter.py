from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlmodel import Session, select

from app.db.session import get_session
from app.models import ModelStarterDPOPair, ModelStarterSFTExample
from app.schemas import (
    ModelStarterDPOPairCreate,
    ModelStarterDPOPairRead,
    ModelStarterDPOPairUpdate,
    ModelStarterImportApprovedResponse,
    ModelStarterSFTExampleCreate,
    ModelStarterSFTExampleRead,
    ModelStarterSFTExampleUpdate,
    ModelStarterSplitRequest,
    ModelStarterSplitResponse,
    ModelStarterSummary,
    ModelStarterValidationResponse,
)
from app.services.model_starter import (
    PACKAGE_TREE,
    dpo_row,
    ensure_seed_data,
    import_approved_workbench_exports,
    package_bytes,
    sft_row,
    split_sft_ids,
    touch_updated,
    validate_model_starter,
)

router = APIRouter(prefix="/model-starter", tags=["model starter"])


def _sft_read(example: ModelStarterSFTExample) -> ModelStarterSFTExampleRead:
    return ModelStarterSFTExampleRead(
        internal_id=example.id,
        id=example.example_id,
        instruction=example.instruction,
        response=example.response,
        voice=example.voice,
        tone=example.tone,
        provenance=example.provenance,
        consent_status=example.consent_status,
        pii_tags=example.pii_tags,
        notes=example.notes,
        status=example.status,
        created_at=example.created_at,
        updated_at=example.updated_at,
    )


def _dpo_read(pair: ModelStarterDPOPair) -> ModelStarterDPOPairRead:
    return ModelStarterDPOPairRead(
        internal_id=pair.id,
        id=pair.example_id,
        prompt=pair.prompt,
        chosen=pair.chosen,
        rejected=pair.rejected,
        provenance=pair.provenance,
        why_chosen=pair.why_chosen,
        notes=pair.notes,
        status=pair.status,
        created_at=pair.created_at,
        updated_at=pair.updated_at,
    )


def _active_sft(session: Session) -> list[ModelStarterSFTExample]:
    return session.exec(
        select(ModelStarterSFTExample)
        .where(ModelStarterSFTExample.status != "deleted")
        .order_by(ModelStarterSFTExample.example_id.asc())
    ).all()


def _active_dpo(session: Session) -> list[ModelStarterDPOPair]:
    return session.exec(
        select(ModelStarterDPOPair)
        .where(ModelStarterDPOPair.status != "deleted")
        .order_by(ModelStarterDPOPair.example_id.asc())
    ).all()


def _get_sft_by_example_id(session: Session, example_id: str) -> ModelStarterSFTExample:
    example = session.exec(
        select(ModelStarterSFTExample)
        .where(ModelStarterSFTExample.example_id == example_id)
        .where(ModelStarterSFTExample.status != "deleted")
    ).first()
    if not example:
        raise HTTPException(status_code=404, detail="SFT example not found")
    return example


def _get_dpo_by_example_id(session: Session, example_id: str) -> ModelStarterDPOPair:
    pair = session.exec(
        select(ModelStarterDPOPair)
        .where(ModelStarterDPOPair.example_id == example_id)
        .where(ModelStarterDPOPair.status != "deleted")
    ).first()
    if not pair:
        raise HTTPException(status_code=404, detail="DPO pair not found")
    return pair


@router.get("/summary", response_model=ModelStarterSummary)
def model_starter_summary(session: Session = Depends(get_session)) -> ModelStarterSummary:
    ensure_seed_data(session)
    sft_examples = _active_sft(session)
    dpo_pairs = _active_dpo(session)
    return ModelStarterSummary(
        sft_count=len(sft_examples),
        dpo_count=len(dpo_pairs),
        validation=ModelStarterValidationResponse(**validate_model_starter(sft_examples, dpo_pairs)),
        package_tree=PACKAGE_TREE,
    )


@router.get("/sft", response_model=list[ModelStarterSFTExampleRead])
def list_sft_examples(session: Session = Depends(get_session)) -> list[ModelStarterSFTExampleRead]:
    ensure_seed_data(session)
    return [_sft_read(example) for example in _active_sft(session)]


@router.post("/sft", response_model=ModelStarterSFTExampleRead)
def create_sft_example(
    payload: ModelStarterSFTExampleCreate,
    session: Session = Depends(get_session),
) -> ModelStarterSFTExampleRead:
    ensure_seed_data(session)
    existing = session.exec(select(ModelStarterSFTExample).where(ModelStarterSFTExample.example_id == payload.id)).first()
    if existing and existing.status != "deleted":
        raise HTTPException(status_code=409, detail="SFT example id already exists")
    example = existing or ModelStarterSFTExample(example_id=payload.id, instruction="", response="")
    example.example_id = payload.id
    example.instruction = payload.instruction
    example.response = payload.response
    example.voice = payload.voice
    example.tone = payload.tone
    example.provenance = payload.provenance
    example.consent_status = payload.consent_status
    example.pii_tags = payload.pii_tags
    example.notes = payload.notes
    example.status = "active"
    touch_updated(example)
    session.add(example)
    session.commit()
    session.refresh(example)
    return _sft_read(example)


@router.put("/sft/{example_id}", response_model=ModelStarterSFTExampleRead)
def update_sft_example(
    example_id: str,
    payload: ModelStarterSFTExampleUpdate,
    session: Session = Depends(get_session),
) -> ModelStarterSFTExampleRead:
    ensure_seed_data(session)
    example = _get_sft_by_example_id(session, example_id)
    next_example_id = payload.id if payload.id is not None else example.example_id
    if next_example_id != example.example_id:
        duplicate = session.exec(select(ModelStarterSFTExample).where(ModelStarterSFTExample.example_id == next_example_id)).first()
        if duplicate and duplicate.id != example.id and duplicate.status != "deleted":
            raise HTTPException(status_code=409, detail="SFT example id already exists")
        example.example_id = next_example_id
    for field in ["instruction", "response", "voice", "tone", "provenance", "consent_status", "notes", "status"]:
        value = getattr(payload, field)
        if value is not None:
            setattr(example, field, value)
    if payload.pii_tags is not None:
        example.pii_tags = payload.pii_tags
    touch_updated(example)
    session.add(example)
    session.commit()
    session.refresh(example)
    return _sft_read(example)


@router.delete("/sft/{example_id}")
def delete_sft_example(example_id: str, session: Session = Depends(get_session)) -> dict:
    ensure_seed_data(session)
    example = _get_sft_by_example_id(session, example_id)
    example.status = "deleted"
    touch_updated(example)
    session.add(example)
    session.commit()
    return {"deleted": True, "id": example_id}


@router.get("/dpo", response_model=list[ModelStarterDPOPairRead])
def list_dpo_pairs(session: Session = Depends(get_session)) -> list[ModelStarterDPOPairRead]:
    ensure_seed_data(session)
    return [_dpo_read(pair) for pair in _active_dpo(session)]


@router.post("/dpo", response_model=ModelStarterDPOPairRead)
def create_dpo_pair(
    payload: ModelStarterDPOPairCreate,
    session: Session = Depends(get_session),
) -> ModelStarterDPOPairRead:
    ensure_seed_data(session)
    existing = session.exec(select(ModelStarterDPOPair).where(ModelStarterDPOPair.example_id == payload.id)).first()
    if existing and existing.status != "deleted":
        raise HTTPException(status_code=409, detail="DPO pair id already exists")
    pair = existing or ModelStarterDPOPair(example_id=payload.id, prompt="", chosen="", rejected="")
    pair.example_id = payload.id
    pair.prompt = payload.prompt
    pair.chosen = payload.chosen
    pair.rejected = payload.rejected
    pair.provenance = payload.provenance
    pair.why_chosen = payload.why_chosen
    pair.notes = payload.notes
    pair.status = "active"
    touch_updated(pair)
    session.add(pair)
    session.commit()
    session.refresh(pair)
    return _dpo_read(pair)


@router.put("/dpo/{example_id}", response_model=ModelStarterDPOPairRead)
def update_dpo_pair(
    example_id: str,
    payload: ModelStarterDPOPairUpdate,
    session: Session = Depends(get_session),
) -> ModelStarterDPOPairRead:
    ensure_seed_data(session)
    pair = _get_dpo_by_example_id(session, example_id)
    next_example_id = payload.id if payload.id is not None else pair.example_id
    if next_example_id != pair.example_id:
        duplicate = session.exec(select(ModelStarterDPOPair).where(ModelStarterDPOPair.example_id == next_example_id)).first()
        if duplicate and duplicate.id != pair.id and duplicate.status != "deleted":
            raise HTTPException(status_code=409, detail="DPO pair id already exists")
        pair.example_id = next_example_id
    for field in ["prompt", "chosen", "rejected", "provenance", "why_chosen", "notes", "status"]:
        value = getattr(payload, field)
        if value is not None:
            setattr(pair, field, value)
    touch_updated(pair)
    session.add(pair)
    session.commit()
    session.refresh(pair)
    return _dpo_read(pair)


@router.delete("/dpo/{example_id}")
def delete_dpo_pair(example_id: str, session: Session = Depends(get_session)) -> dict:
    ensure_seed_data(session)
    pair = _get_dpo_by_example_id(session, example_id)
    pair.status = "deleted"
    touch_updated(pair)
    session.add(pair)
    session.commit()
    return {"deleted": True, "id": example_id}


@router.post("/validate", response_model=ModelStarterValidationResponse)
def validate_starter(session: Session = Depends(get_session)) -> ModelStarterValidationResponse:
    ensure_seed_data(session)
    return ModelStarterValidationResponse(**validate_model_starter(_active_sft(session), _active_dpo(session)))


@router.post("/split", response_model=ModelStarterSplitResponse)
def split_starter_sft(
    payload: ModelStarterSplitRequest,
    session: Session = Depends(get_session),
) -> ModelStarterSplitResponse:
    ensure_seed_data(session)
    rows = [sft_row(example) for example in _active_sft(session)]
    split = split_sft_ids(rows, val_ratio=payload.val_ratio, seed=payload.seed)
    return ModelStarterSplitResponse(
        source_count=split["source_count"],
        train_count=split["train_count"],
        val_count=split["val_count"],
        train_ids=split["train_ids"],
        val_ids=split["val_ids"],
        deterministic_seed=split["deterministic_seed"],
        val_ratio=split["val_ratio"],
    )


@router.post("/import-approved", response_model=ModelStarterImportApprovedResponse)
def import_approved_workbench_rows(session: Session = Depends(get_session)) -> ModelStarterImportApprovedResponse:
    return ModelStarterImportApprovedResponse(**import_approved_workbench_exports(session))


@router.post("/export")
@router.get("/export.zip")
def export_starter_package(session: Session = Depends(get_session)) -> Response:
    content = package_bytes(session)
    return Response(
        content=content,
        media_type="application/zip",
        headers={"Content-Disposition": 'attachment; filename="charles-model.zip"'},
    )
