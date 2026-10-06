"""Краевые случаи, найденные при ревью: до исправления часть из них давала 500."""

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.db import SessionLocal
from app.models import Payment


def count_payments() -> int:
    with SessionLocal() as db:
        return db.scalar(select(func.count()).select_from(Payment))


# --- Огромные и «нечестные» id ---


@pytest.mark.parametrize("tariff_id", [2**31, 2**63, 2**70, 0, -1])
def test_out_of_range_tariff_id_is_422(make_payment, tariff_id):
    assert make_payment(tariff_id=tariff_id).status_code == 422
    assert count_payments() == 0


@pytest.mark.parametrize("tariff_id", [True, 2.0, "2"])
def test_tariff_id_must_be_real_int(make_payment, tariff_id):
    # В lax-режиме Pydantic превратил бы true в 1 и создал платёж за basic
    assert make_payment(tariff_id=tariff_id).status_code == 422
    assert count_payments() == 0


def test_unknown_tariff_is_standard_422(make_payment):
    resp = make_payment(tariff_id=999)
    assert resp.status_code == 422
    [error] = resp.json()["detail"]
    assert error["loc"] == ["body", "tariff_id"]
    assert error["input"] == 999


@pytest.mark.parametrize("payment_id", [2**31, 2**63, 2**70, 0])
def test_out_of_range_payment_id_is_404(client, payment_id):
    assert client.get(f"/payments/{payment_id}").status_code == 404
    webhook = client.post("/webhooks/bank", json={"payment_id": payment_id, "status": "failed"})
    assert webhook.status_code == 404


def test_webhook_payment_id_must_be_real_int(client, make_payment):
    pid = make_payment().json()["id"]
    resp = client.post("/webhooks/bank", json={"payment_id": str(pid), "status": "succeeded"})
    assert resp.status_code == 422
    assert client.get(f"/payments/{pid}").json()["status"] == "pending"


# --- Тело запроса ---


def test_client_cannot_set_amount(make_payment):
    # Лишние поля запрещены: молча проигнорированный "amount" ввёл бы клиента в заблуждение
    resp = make_payment(amount=1, discount=1_990_000)
    assert resp.status_code == 422
    assert count_payments() == 0


def test_email_is_case_insensitive(client, make_payment):
    created = make_payment(email="Student@Example.COM").json()
    assert created["email"] == "student@example.com"
    found = client.get("/payments", params={"email": "STUDENT@example.com"}).json()
    assert [p["id"] for p in found] == [created["id"]]


# --- Idempotency-Key ---


@pytest.mark.parametrize("key", ["", "x" * 256])
def test_invalid_idempotency_key_is_422(make_payment, key):
    # Пустой ключ раньше записывался в уникальную колонку, и повтор падал с 500
    for _ in range(2):
        assert make_payment(headers={"Idempotency-Key": key}).status_code == 422
    assert count_payments() == 0


def test_idempotent_replay_returns_current_status(client, make_payment):
    headers = {"Idempotency-Key": "order-7"}
    pid = make_payment(headers=headers).json()["id"]
    client.post("/webhooks/bank", json={"payment_id": pid, "status": "succeeded"})

    replay = make_payment(headers=headers)

    assert replay.status_code == 200
    assert replay.json()["id"] == pid
    assert replay.json()["status"] == "succeeded"
    assert count_payments() == 1


def test_promo_case_does_not_break_idempotency(make_payment):
    # KVITTO10 и kvitto10 — один и тот же запрос, а не конфликт ключа
    headers = {"Idempotency-Key": "promo"}
    first = make_payment(headers=headers, promo_code="KVITTO10")
    second = make_payment(headers=headers, promo_code="kvitto10")
    assert second.status_code == 200
    assert second.json() == first.json()
    assert count_payments() == 1


# --- Список платежей ---


def test_list_pagination(client, make_payment):
    ids = [make_payment().json()["id"] for _ in range(5)]
    page = client.get("/payments", params={"limit": 2, "offset": 2}).json()
    assert [p["id"] for p in page] == ids[2:4]
    assert client.get("/payments", params={"limit": 0}).status_code == 422
    assert client.get("/payments", params={"limit": 501}).status_code == 422


# --- Ограничения БД как последний рубеж ---


@pytest.mark.parametrize(
    "overrides", [{"amount": -1}, {"discount": -1}, {"status": "paid"}, {"method": "cash"}]
)
def test_db_rejects_invalid_rows(client, overrides):
    row = {
        "tariff_id": 1,
        "amount": 990_000,
        "discount": 0,
        "method": "card",
        "email": "a@example.com",
        **overrides,
    }
    with SessionLocal() as db:
        db.add(Payment(**row))
        with pytest.raises(IntegrityError):
            db.commit()
