"""Миграции Alembic: схема после upgrade совпадает с моделями, downgrade откатывает всё."""

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import inspect

from app.db import ALEMBIC_INI, Base, engine
from tests.conftest import reset_db


def _config() -> Config:
    cfg = Config(str(ALEMBIC_INI))
    cfg.attributes["configure_logger"] = False
    return cfg


def test_migrations_match_models():
    reset_db()
    command.upgrade(_config(), "head")
    with engine.connect() as conn:
        diff = compare_metadata(MigrationContext.configure(conn), Base.metadata)
    # Пустой diff: модели изменили — а миграцию написать забыли, тест упадёт
    assert diff == []


def test_downgrade_to_base():
    reset_db()
    cfg = _config()
    command.upgrade(cfg, "head")
    command.downgrade(cfg, "base")
    assert set(inspect(engine).get_table_names()) == {"alembic_version"}
