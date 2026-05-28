from __future__ import annotations

from pathlib import Path

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.models import Base
from app.settings import AppSettings


def _ensure_sqlite_parent_exists(database_url: str) -> None:
    if not database_url.startswith("sqlite:///"):
        return

    sqlite_path = database_url.removeprefix("sqlite:///")
    if sqlite_path == ":memory:":
        return

    Path(sqlite_path).parent.mkdir(parents=True, exist_ok=True)


def create_engine_from_settings(settings: AppSettings) -> Engine:
    _ensure_sqlite_parent_exists(settings.database_url)
    return create_engine(settings.database_url, future=True)


def create_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def init_database(engine: Engine) -> None:
    Base.metadata.create_all(engine)
