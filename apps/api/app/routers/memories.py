from datetime import datetime, timezone
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from app.db.session import get_session
from app.models import Memory
from app.schemas import MemoryCreate, MemoryUpdate

router = APIRouter(prefix="/memories", tags=["memories"])


def _memory_or_404(session: Session, memory_id: str) -> Memory:
    memory = session.get(Memory, memory_id)
    if not memory:
        memory = session.exec(select(Memory).where(Memory.human_id == memory_id)).first()
    if not memory:
        raise HTTPException(status_code=404, detail="Memory not found")
    return memory


@router.get("", response_model=List[Memory])
def list_memories(session: Session = Depends(get_session)) -> List[Memory]:
    return session.exec(select(Memory).order_by(Memory.created_at.desc())).all()


@router.post("", response_model=Memory)
def create_memory(payload: MemoryCreate, session: Session = Depends(get_session)) -> Memory:
    memory = Memory(**payload.model_dump())
    session.add(memory)
    session.commit()
    session.refresh(memory)
    return memory


@router.get("/{memory_id}", response_model=Memory)
def get_memory(memory_id: str, session: Session = Depends(get_session)) -> Memory:
    return _memory_or_404(session, memory_id)


@router.patch("/{memory_id}", response_model=Memory)
def update_memory(
    memory_id: str,
    payload: MemoryUpdate,
    session: Session = Depends(get_session),
) -> Memory:
    memory = _memory_or_404(session, memory_id)
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(memory, key, value)
    memory.updated_at = datetime.now(timezone.utc)
    session.add(memory)
    session.commit()
    session.refresh(memory)
    return memory
