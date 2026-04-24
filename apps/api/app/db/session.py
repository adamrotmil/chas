from typing import Generator

from sqlalchemy.engine import Engine
from sqlmodel import Session, create_engine

from app.config import settings


def _connect_args() -> dict:
    if settings.database_url.startswith("sqlite"):
        return {"check_same_thread": False}
    return {}


engine: Engine = create_engine(settings.database_url, connect_args=_connect_args(), echo=False)


def get_session() -> Generator[Session, None, None]:
    with Session(engine) as session:
        yield session
