"""Интеграционные тесты через HTTP. Проверяем данные в ответе и в базе, а не только код."""

import hashlib
import hmac
import json

import pytest


def test_tariffs(client):
    resp = client.get("/tariffs")
    assert resp.status_code == 200
    assert resp.json() == [
        {"id": 1, "title": "basic", "price": 990_000},
        {"id": 2, "title": "standard", "price": 1_990_000},
        {"id": 3, "title": "premium", "price": 2_990_000},
    ]


# --- Деньги и промокод ---


def test_payment_without_promo(make_payment):
    resp = make_payment()
    assert resp.status_code == 201
    body = resp.json()
    assert body["amount"] == 1_990_000
    assert body["discount"] == 0
    assert body["status"] == "pending"
    assert body["schedule"] is None
    assert body["installment_months"] is None
    assert body["created_at"].endswith("Z") or body["created_at"].endswith("+00:00")


@pytest.mark.parametrize("code", ["KVITTO10", "kvitto10", "KvItTo10", " kvitto10 "])
def test_payment_with_promo_any_case(make_payment, code):
    resp = make_payment(promo_code=code)
    assert resp.status_code == 201
    body = resp.json()
    assert body["discount"] == 199_000
    assert body["amount"] == 1_791_000
    assert body["amount"] + body["discount"] == 1_990_000


def test_unknown_promo_returns_422(make_payment):
    resp = make_payment(promo_code="FREE100")
    assert resp.status_code == 422


# --- Рассрочка ---


@pytest.mark.parametrize("months", [3, 6, 12])
@pytest.mark.parametrize("promo", [None, "kvitto10"])
@pytest.mark.parametrize("tariff_id", [1, 2, 3])
def test_installment_schedule_sums_to_amount(make_payment, months, promo, tariff_id):
    resp = make_payment(
        tariff_id=tariff_id, method="installment", installment_months=months, promo_code=promo
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["installment_months"] == months
    assert len(body["schedule"]) == months
    assert sum(body["schedule"]) == body["amount"]


def test_installment_example_from_spec(make_payment):
    resp = make_payment(method="installment", installment_months=3)
    assert resp.json()["schedule"] == [663334, 663333, 663333]


@pytest.mark.parametrize(
    "overrides",
    [
        {"method": "installment"},  # нет срока
        {"method": "installment", "installment_months": 4},  # недопустимый срок
        {"method": "card", "installment_months": 3},  # срок без рассрочки
        {"method": "cash"},
        {"email": "not-an-email"},
        {"tariff_id": 999},
    ],
)
def test_validation_errors(make_payment, overrides):
    assert make_payment(**overrides).status_code == 422


# --- Идемпотентность ---


def test_same_idempotency_key_returns_same_payment(client, make_payment):
    headers = {"Idempotency-Key": "order-42"}
    first = make_payment(headers=headers)
    second = make_payment(headers=headers)

    assert first.status_code == 201
    assert second.status_code == 200
    assert second.json() == first.json()
    # Второй платёж в базе не появился
    assert len(client.get("/payments").json()) == 1


def test_different_keys_create_different_payments(make_payment):
    a = make_payment(headers={"Idempotency-Key": "a"})
    b = make_payment(headers={"Idempotency-Key": "b"})
    assert a.json()["id"] != b.json()["id"]


def test_same_key_different_body_is_conflict(client, make_payment):
    make_payment(headers={"Idempotency-Key": "k"}, tariff_id=1)
    resp = make_payment(headers={"Idempotency-Key": "k"}, tariff_id=3)
    assert resp.status_code == 409
    assert len(client.get("/payments").json()) == 1


# --- Получение платежа ---


def test_get_payment(client, make_payment):
    created = make_payment().json()
    resp = client.get(f"/payments/{created['id']}")
    assert resp.status_code == 200
    assert resp.json() == created


def test_get_missing_payment_returns_404(client):
    assert client.get("/payments/9999").status_code == 404


# --- Вебхук и статусы ---


def _webhook(client, payment_id, status, **kwargs):
    body = {"payment_id": payment_id, "status": status}
    return client.post("/webhooks/bank", json=body, **kwargs)


def test_webhook_valid_transitions(client, make_payment):
    pid = make_payment().json()["id"]

    resp = _webhook(client, pid, "succeeded")
    assert resp.status_code == 200
    assert resp.json() == {"result": "ok"}
    assert client.get(f"/payments/{pid}").json()["status"] == "succeeded"

    assert _webhook(client, pid, "refunded").status_code == 200
    assert client.get(f"/payments/{pid}").json()["status"] == "refunded"


@pytest.mark.parametrize(
    ("path", "forbidden"),
    [
        ([], "refunded"),  # pending -> refunded
        (["failed"], "succeeded"),  # failed -> succeeded
        (["succeeded"], "failed"),  # succeeded -> failed
        (["succeeded", "refunded"], "succeeded"),
        (["succeeded"], "succeeded"),  # повтор того же статуса тоже запрещён
    ],
)
def test_forbidden_transition_returns_409_and_keeps_status(client, make_payment, path, forbidden):
    pid = make_payment().json()["id"]
    for s in path:
        assert _webhook(client, pid, s).status_code == 200
    status_before = client.get(f"/payments/{pid}").json()["status"]

    resp = _webhook(client, pid, forbidden)

    assert resp.status_code == 409
    assert resp.json() == {"error": "invalid_transition"}
    assert client.get(f"/payments/{pid}").json()["status"] == status_before


def test_webhook_missing_payment_returns_404(client):
    assert _webhook(client, 9999, "succeeded").status_code == 404


def test_webhook_unknown_status_returns_422(client, make_payment):
    pid = make_payment().json()["id"]
    assert _webhook(client, pid, "paid").status_code == 422


# --- Бонусы: фильтры и подпись ---


def test_list_filters(client, make_payment):
    a = make_payment(email="a@example.com").json()
    make_payment(email="b@example.com")
    _webhook(client, a["id"], "succeeded")

    by_email = client.get("/payments", params={"email": "a@example.com"}).json()
    assert [p["id"] for p in by_email] == [a["id"]]

    by_status = client.get("/payments", params={"status": "pending"}).json()
    assert [p["email"] for p in by_status] == ["b@example.com"]


def test_webhook_signature(client, make_payment, monkeypatch):
    monkeypatch.setenv("WEBHOOK_SECRET", "s3cret")
    pid = make_payment().json()["id"]
    raw = json.dumps({"payment_id": pid, "status": "succeeded"}).encode()
    good = hmac.new(b"s3cret", raw, hashlib.sha256).hexdigest()
    ct = {"Content-Type": "application/json"}

    no_sig = client.post("/webhooks/bank", content=raw, headers=ct)
    bad_sig = client.post("/webhooks/bank", content=raw, headers={**ct, "X-Signature": "0" * 64})
    assert no_sig.status_code == 401
    assert bad_sig.status_code == 401
    assert client.get(f"/payments/{pid}").json()["status"] == "pending"

    ok = client.post("/webhooks/bank", content=raw, headers={**ct, "X-Signature": good})
    assert ok.status_code == 200
    assert client.get(f"/payments/{pid}").json()["status"] == "succeeded"
