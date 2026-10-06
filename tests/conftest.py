import os

# БД в памяти для тестов — выставляем до импорта приложения
os.environ["DATABASE_URL"] = "sqlite:///:memory:"
os.environ.pop("WEBHOOK_SECRET", None)

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.db import Base, engine  # noqa: E402
from app.main import app  # noqa: E402


def reset_db() -> None:
    """Пустая база: без таблиц и без отметки о применённых миграциях."""
    Base.metadata.drop_all(engine)
    with engine.begin() as conn:
        conn.exec_driver_sql("DROP TABLE IF EXISTS alembic_version")


@pytest.fixture
def client():
    # Чистая база на каждый тест; lifespan прогонит миграции и создаст тарифы заново
    reset_db()
    with TestClient(app) as c:
        yield c


@pytest.fixture
def make_payment(client):
    def _make(headers: dict | None = None, **overrides):
        body = {"tariff_id": 2, "email": "student@example.com", "method": "card"}
        body.update(overrides)
        return client.post("/payments", json=body, headers=headers or {})

    return _make
