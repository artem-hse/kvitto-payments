"""Подключение к БД, сессии SQLAlchemy и запуск миграций."""

import os
from collections.abc import Iterator
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.pool import StaticPool

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./kvitto.db")
ALEMBIC_INI = Path(__file__).resolve().parent.parent / "alembic.ini"


def _make_engine(url: str):
    if url.startswith("sqlite"):
        kwargs: dict = {"connect_args": {"check_same_thread": False}}
        # in-memory SQLite живёт внутри одного соединения — держим его общим
        if ":memory:" in url:
            kwargs["poolclass"] = StaticPool
        return create_engine(url, **kwargs)
    return create_engine(url, pool_pre_ping=True)


engine = _make_engine(DATABASE_URL)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def run_migrations() -> None:
    """`alembic upgrade head` из кода — схема при старте всегда актуальна."""
    cfg = Config(str(ALEMBIC_INI))
    # Не перенастраивать логирование uvicorn конфигом из alembic.ini
    cfg.attributes["configure_logger"] = False
    command.upgrade(cfg, "head")


def get_db() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
