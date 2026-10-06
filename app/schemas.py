"""Pydantic-схемы запросов и ответов."""

from datetime import UTC, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator

from app.models import MAX_DB_ID
from app.pricing import PaymentStatus, is_known_promo

PaymentMethod = Literal["card", "sbp", "installment"]

# strict: `true` и `2.0` не превращаются молча в 1 и 2.
# le: число больше колонки Integer дало бы 500 от драйвера БД, а не 422.
DbId = Annotated[int, Field(strict=True, ge=1, le=MAX_DB_ID)]


class TariffOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    price: int


class PaymentCreate(BaseModel):
    # Лишнее поле (например, "amount") — 422: сумму считает сервер, клиент её не задаёт.
    model_config = ConfigDict(extra="forbid")

    tariff_id: DbId
    email: EmailStr
    method: PaymentMethod
    installment_months: Literal[3, 6, 12] | None = None
    promo_code: str | None = None

    @field_validator("email")
    @classmethod
    def normalize_email(cls, v: str) -> str:
        # Один ящик — одна запись: иначе фильтр по email не найдёт Student@... по student@...
        return v.lower()

    @field_validator("promo_code")
    @classmethod
    def check_promo(cls, v: str | None) -> str | None:
        # Неизвестный промокод -> стандартная 422 от FastAPI
        if v is not None and not is_known_promo(v):
            raise ValueError("unknown promo code")
        return v

    @model_validator(mode="after")
    def check_installment(self) -> "PaymentCreate":
        if self.method == "installment" and self.installment_months is None:
            raise ValueError("installment_months is required for installment")
        if self.method != "installment" and self.installment_months is not None:
            raise ValueError("installment_months is allowed only for installment")
        return self


class PaymentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    status: PaymentStatus
    tariff_id: int
    amount: int
    discount: int
    method: PaymentMethod
    installment_months: int | None
    schedule: list[int] | None
    email: str
    created_at: datetime

    @field_validator("created_at")
    @classmethod
    def ensure_utc(cls, v: datetime) -> datetime:
        # SQLite теряет таймзону при хранении; мы всегда пишем UTC — возвращаем её явно
        return v if v.tzinfo else v.replace(tzinfo=UTC)


class WebhookIn(BaseModel):
    # Без ge/le: несуществующий платёж — это 404 по заданию, а не 422
    payment_id: Annotated[int, Field(strict=True)]
    status: PaymentStatus
