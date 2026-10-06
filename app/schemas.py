"""Pydantic-схемы запросов и ответов."""

from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, field_validator, model_validator

from app.pricing import PaymentStatus, is_known_promo

PaymentMethod = Literal["card", "sbp", "installment"]


class TariffOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    price: int


class PaymentCreate(BaseModel):
    tariff_id: int
    email: EmailStr
    method: PaymentMethod
    installment_months: Literal[3, 6, 12] | None = None
    promo_code: str | None = None

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
    payment_id: int
    status: PaymentStatus
