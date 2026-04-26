from datetime import datetime, timezone
import re
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import Session, select

from app.db.session import get_session
from app.models import Entity
from app.schemas import EntityCreate, EntityUpdate

router = APIRouter(prefix="/entities", tags=["entities"])


def _entity_or_404(session: Session, entity_id: str) -> Entity:
    entity = session.get(Entity, entity_id)
    if not entity:
        entity = session.exec(select(Entity).where(Entity.human_id == entity_id)).first()
    if not entity:
        raise HTTPException(status_code=404, detail="Entity not found")
    return entity


def _human_id_for_name(name: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9]+", "_", name).strip("_").upper() or "ENTITY"
    return f"CR_ENTITY_{slug[:32]}"


@router.get("", response_model=List[Entity])
def list_entities(
    entity_type: Optional[str] = Query(default=None),
    session: Session = Depends(get_session),
) -> List[Entity]:
    statement = select(Entity)
    if entity_type:
        statement = statement.where(Entity.entity_type == entity_type)
    return session.exec(statement.order_by(Entity.canonical_name)).all()


@router.post("", response_model=Entity)
def create_entity(payload: EntityCreate, session: Session = Depends(get_session)) -> Entity:
    data = payload.model_dump()
    if not data.get("human_id"):
        base_human_id = _human_id_for_name(payload.canonical_name)
        human_id = base_human_id
        suffix = 2
        while session.exec(select(Entity).where(Entity.human_id == human_id)).first():
            human_id = f"{base_human_id}_{suffix}"
            suffix += 1
        data["human_id"] = human_id

    entity = Entity(**data)
    session.add(entity)
    session.commit()
    session.refresh(entity)
    return entity


@router.get("/{entity_id}", response_model=Entity)
def get_entity(entity_id: str, session: Session = Depends(get_session)) -> Entity:
    return _entity_or_404(session, entity_id)


@router.patch("/{entity_id}", response_model=Entity)
def update_entity(
    entity_id: str,
    payload: EntityUpdate,
    session: Session = Depends(get_session),
) -> Entity:
    entity = _entity_or_404(session, entity_id)
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(entity, key, value)
    entity.updated_at = datetime.now(timezone.utc)
    session.add(entity)
    session.commit()
    session.refresh(entity)
    return entity
