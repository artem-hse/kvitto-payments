"""Работа с платежами в БД."""

import hashlib
import json

from fastapi.exceptions import RequestValidationError
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import Payment, Tariff
from app.pricing import TARIFFS_SEED, calc_discount, can_transition, split_schedule
from app.schemas import PaymentCreate


class IdempotencyConflict(Exception):
    """Тот же Idempotency-Key пришёл с другим телом запроса."""


class PaymentNotFound(Exception):
    pass


class InvalidTransition(Exception):
    pass


def seed_tariffs(db: Session) -> None:
    for tariff_id, title, price in TARIFFS_SEED:
        if db.get(Tariff, tariff_id) is None:
            db.add(Tariff(id=tariff_id, title=title, price=price))
    db.commit()


def _request_hash(data: PaymentCreate) -> str:
    payload = data.model_dump(mode="json")
    if payload["promo_code"] is not None:
        payload["promo_code"] = payload["promo_code"].strip().upper()
    raw = json.dumps(payload, sort_keys=True)
    return hashlib.sha256(raw.encode()).hexdigest()


def _find_by_key(db: Session, key: str) -> Payment | None:
    return db.scalar(select(Payment).where(Payment.idempotency_key == key))


def _check_same_request(existing: Payment, request_hash: str) -> Payment:
    if existing.request_hash != request_hash:
        raise IdempotencyConflict
    return existing


def create_payment(
    db: Session, data: PaymentCreate, idempotency_key: str | None
) -> tuple[Payment, bool]:
    """Возвращает (платёж, создан_ли_новый)."""
    req_hash = _request_hash(data)

    if idempotency_key:
        existing = _find_by_key(db, idempotency_key)
        if existing is not None:
            return _check_same_request(existing, req_hash), False

    tariff = db.get(Tariff, data.tariff_id)
    if tariff is None:
        # Тот же формат, что и у стандартной 422 FastAPI
        raise RequestValidationError(
            [{"type": "value_error", "loc": ("body", "tariff_id"),
              "msg": "Unknown tariff", "input": data.tariff_id}]
        )

    discount = calc_discount(tariff.price, data.promo_code)
    amount = tariff.price - discount
    schedule = (
        split_schedule(amount, data.installment_months)
        if data.method == "installment" and data.installment_months
        else None
    )

    payment = Payment(
        tariff_id=tariff.id,
        amount=amount,
        discount=discount,
        method=data.method,
        installment_months=data.installment_months,
        schedule=schedule,
        email=data.email,
        idempotency_key=idempotency_key,
        request_hash=req_hash,
    )
    db.add(payment)
    try:
        db.commit()
    except IntegrityError:
        # Параллельный запрос с тем же ключом успел вставить запись раньше нас
        db.rollback()
        existing = _find_by_key(db, idempotency_key) if idempotency_key else None
        if existing is None:
            raise
        return _check_same_request(existing, req_hash), False

    db.refresh(payment)
    return payment, True


def get_payment(db: Session, payment_id: int) -> Payment:
    payment = db.get(Payment, payment_id)
    if payment is None:
        raise PaymentNotFound
    return payment


def list_payments(db: Session, email: str | None, status: str | None) -> list[Payment]:
    stmt = select(Payment).order_by(Payment.id)
    if email:
        stmt = stmt.where(Payment.email == email)
    if status:
        stmt = stmt.where(Payment.status == status)
    return list(db.scalars(stmt))


def change_status(db: Session, payment_id: int, new_status: str) -> Payment:
    payment = get_payment(db, payment_id)
    if not can_transition(payment.status, new_status):
        raise InvalidTransition

    # Условный UPDATE: статус меняется, только если он всё ещё тот, что мы проверяли.
    # Два одновременных вебхука не смогут оба пройти проверку.
    result = db.execute(
        update(Payment)
        .where(Payment.id == payment_id, Payment.status == payment.status)
        .values(status=new_status)
    )
    if result.rowcount == 0:
        db.rollback()
        raise InvalidTransition
    db.commit()
    db.refresh(payment)
    return payment
