"""FastAPI-приложение: эндпоинты тарифов, платежей и вебхука банка."""

import hashlib
import hmac
import os
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, Response, status
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import services
from app.db import SessionLocal, get_db, run_migrations
from app.models import Tariff
from app.pricing import PaymentStatus
from app.schemas import PaymentCreate, PaymentOut, TariffOut, WebhookIn


@asynccontextmanager
async def lifespan(_: FastAPI):
    run_migrations()
    with SessionLocal() as db:
        services.seed_tariffs(db)
    yield


app = FastAPI(title="Kvitto Payments", lifespan=lifespan)

DbSession = Annotated[Session, Depends(get_db)]


@app.exception_handler(services.PaymentNotFound)
async def _not_found(_: Request, __: services.PaymentNotFound) -> JSONResponse:
    return JSONResponse(status_code=404, content={"error": "payment_not_found"})


@app.exception_handler(services.InvalidTransition)
async def _invalid_transition(_: Request, __: services.InvalidTransition) -> JSONResponse:
    return JSONResponse(status_code=409, content={"error": "invalid_transition"})


@app.exception_handler(services.TariffNotFound)
async def _unknown_tariff(request: Request, exc: services.TariffNotFound) -> JSONResponse:
    # Ошибка входных данных — отдаём стандартной 422 FastAPI, тем же форматом
    error = {
        "type": "value_error",
        "loc": ("body", "tariff_id"),
        "msg": "Value error, unknown tariff",
        "input": exc.tariff_id,
    }
    return await request_validation_exception_handler(request, RequestValidationError([error]))


@app.exception_handler(services.IdempotencyConflict)
async def _idem_conflict(_: Request, __: services.IdempotencyConflict) -> JSONResponse:
    return JSONResponse(status_code=409, content={"error": "idempotency_key_reused"})


@app.get("/tariffs", response_model=list[TariffOut])
def list_tariffs(db: DbSession) -> list[Tariff]:
    return list(db.scalars(select(Tariff).order_by(Tariff.id)))


@app.post("/payments", response_model=PaymentOut, status_code=status.HTTP_201_CREATED)
def create_payment(
    data: PaymentCreate,
    response: Response,
    db: DbSession,
    # min_length: пустой ключ иначе записался бы в уникальную колонку и второй запрос дал 500
    idempotency_key: Annotated[
        str | None, Header(alias="Idempotency-Key", min_length=1, max_length=255)
    ] = None,
):
    payment, created = services.create_payment(db, data, idempotency_key)
    if not created:
        response.status_code = status.HTTP_200_OK
    return payment


@app.get("/payments", response_model=list[PaymentOut])
def list_payments(
    db: DbSession,
    email: str | None = None,
    status: PaymentStatus | None = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
):
    return services.list_payments(db, email, status, limit, offset)


@app.get("/payments/{payment_id}", response_model=PaymentOut)
def get_payment(payment_id: int, db: DbSession):
    return services.get_payment(db, payment_id)


async def verify_signature(
    request: Request,
    x_signature: Annotated[str | None, Header(alias="X-Signature")] = None,
) -> None:
    """HMAC-SHA256 от сырого тела. Включается, только если задан WEBHOOK_SECRET."""
    secret = os.getenv("WEBHOOK_SECRET")
    if not secret:
        return
    body = await request.body()
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    # compare_digest — сравнение за постоянное время, без утечки через тайминги
    if x_signature is None or not hmac.compare_digest(expected, x_signature):
        raise HTTPException(status_code=401, detail="invalid_signature")


@app.post("/webhooks/bank", dependencies=[Depends(verify_signature)])
def bank_webhook(data: WebhookIn, db: DbSession) -> dict[str, str]:
    services.change_status(db, data.payment_id, data.status)
    return {"result": "ok"}
