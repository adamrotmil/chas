from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from app.db.session import get_session
from app.models import (
    ContextPack,
    ContextPackItem,
    Generation,
    GenerationReview,
    GoldVoiceExample,
    PromptSpec,
    utcnow,
)
from app.schemas import (
    GenerationCreate,
    GenerationReviewCreate,
    GoldVoiceExampleCreate,
    ContextPackBuildRequest,
    ContextPackBuildResponse,
    PromptSpecCreate,
)
from app.services.context_packs import build_context_pack

router = APIRouter(tags=["voice"])


@router.get("/prompt-specs", response_model=List[PromptSpec])
def list_prompt_specs(session: Session = Depends(get_session)) -> List[PromptSpec]:
    return session.exec(select(PromptSpec).order_by(PromptSpec.created_at.desc())).all()


@router.post("/prompt-specs", response_model=PromptSpec)
def create_prompt_spec(
    payload: PromptSpecCreate,
    session: Session = Depends(get_session),
) -> PromptSpec:
    prompt = PromptSpec(**payload.model_dump())
    session.add(prompt)
    session.commit()
    session.refresh(prompt)
    return prompt


@router.get("/context-packs", response_model=List[ContextPack])
def list_context_packs(session: Session = Depends(get_session)) -> List[ContextPack]:
    return session.exec(select(ContextPack).order_by(ContextPack.created_at.desc())).all()


@router.get("/context-packs/{context_pack_id}/items", response_model=List[ContextPackItem])
def list_context_pack_items(
    context_pack_id: str,
    session: Session = Depends(get_session),
) -> List[ContextPackItem]:
    context_pack = session.get(ContextPack, context_pack_id) or session.exec(
        select(ContextPack).where(ContextPack.human_id == context_pack_id)
    ).first()
    if not context_pack:
        raise HTTPException(status_code=404, detail="Context pack not found")
    return session.exec(
        select(ContextPackItem).where(ContextPackItem.context_pack_id == context_pack.id).order_by(ContextPackItem.rank.asc())
    ).all()


@router.post("/context-packs/build", response_model=ContextPackBuildResponse)
def build_context_pack_endpoint(
    payload: ContextPackBuildRequest,
    session: Session = Depends(get_session),
) -> ContextPackBuildResponse:
    result = build_context_pack(session, payload)
    session.commit()
    context_pack = result["context_pack"]
    return ContextPackBuildResponse(
        context_pack_id=context_pack.id,
        human_id=context_pack.human_id,
        included_count=result["included_count"],
        excluded_count=result["excluded_count"],
        warnings=result["warnings"],
    )


@router.get("/context-packs/{context_pack_id}", response_model=ContextPack)
def get_context_pack(
    context_pack_id: str,
    session: Session = Depends(get_session),
) -> ContextPack:
    context_pack = session.get(ContextPack, context_pack_id)
    if not context_pack:
        context_pack = session.exec(
            select(ContextPack).where(ContextPack.human_id == context_pack_id)
        ).first()
    if not context_pack:
        raise HTTPException(status_code=404, detail="Context pack not found")
    return context_pack


@router.get("/generations/{generation_id}", response_model=Generation)
def get_generation(
    generation_id: str,
    session: Session = Depends(get_session),
) -> Generation:
    generation = session.get(Generation, generation_id)
    if not generation:
        raise HTTPException(status_code=404, detail="Generation not found")
    return generation


@router.post("/generations", response_model=Generation)
def create_generation(
    payload: GenerationCreate,
    session: Session = Depends(get_session),
) -> Generation:
    generation = Generation(**payload.model_dump())
    session.add(generation)
    session.commit()
    session.refresh(generation)
    return generation


@router.post("/generations/{generation_id}/review", response_model=GenerationReview)
def review_generation(
    generation_id: str,
    payload: GenerationReviewCreate,
    session: Session = Depends(get_session),
) -> GenerationReview:
    if not session.get(Generation, generation_id):
        raise HTTPException(status_code=404, detail="Generation not found")
    review = GenerationReview(generation_id=generation_id, **payload.model_dump())
    session.add(review)
    session.commit()
    session.refresh(review)
    return review


@router.get("/gold-voice-examples", response_model=List[GoldVoiceExample])
def list_gold_voice_examples(session: Session = Depends(get_session)) -> List[GoldVoiceExample]:
    return session.exec(select(GoldVoiceExample).order_by(GoldVoiceExample.created_at.desc())).all()


@router.post("/gold-voice-examples", response_model=GoldVoiceExample)
def create_gold_voice_example(
    payload: GoldVoiceExampleCreate,
    session: Session = Depends(get_session),
) -> GoldVoiceExample:
    gold = GoldVoiceExample(**payload.model_dump())
    gold.truth_status = "adam_expert_reconstruction"
    gold.approved_at = utcnow() if gold.approved_by else None
    session.add(gold)
    session.commit()
    session.refresh(gold)
    return gold
