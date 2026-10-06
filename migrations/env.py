"""Окружение Alembic: тот же engine и те же модели, что у приложения."""

from logging.config import fileConfig

from alembic import context

import app.models  # noqa: F401  — регистрирует таблицы в Base.metadata
from app.db import Base, engine

config = context.config

if config.config_file_name is not None and config.attributes.get("configure_logger", True):
    fileConfig(config.config_file_name)


def run_migrations_offline() -> None:
    context.configure(
        url=str(engine.url),
        target_metadata=Base.metadata,
        literal_binds=True,
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    with engine.connect() as connection:
        # render_as_batch — ALTER TABLE в SQLite через пересоздание таблицы
        context.configure(
            connection=connection, target_metadata=Base.metadata, render_as_batch=True
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
