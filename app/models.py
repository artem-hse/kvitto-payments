"""ORM-модели. Все денежные поля — целые копейки (BigInteger), никаких float."""

from datetime import UTC, datetime

from sqlalchemy import JSON, BigInteger, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


def utcnow() -> datetime:
    return datetime.now(UTC)


class Tariff(Base):
    __tablename__ = "tariffs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(50), unique=True)
    price: Mapped[int] = mapped_column(BigInteger)  # копейки


class Payment(Base):
    __tablename__ = "payments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    tariff_id: Mapped[int] = mapped_column(ForeignKey("tariffs.id"))
    amount: Mapped[int] = mapped_column(BigInteger)  # к оплате, копейки
    discount: Mapped[int] = mapped_column(BigInteger, default=0)  # копейки
    method: Mapped[str] = mapped_column(String(20))
    installment_months: Mapped[int | None] = mapped_column(Integer, nullable=True)
    schedule: Mapped[list[int] | None] = mapped_column(JSON, nullable=True)
    email: Mapped[str] = mapped_column(String(320), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    # Уникальность ключа гарантирует БД — это защищает от гонки двух одновременных запросов.
    idempotency_key: Mapped[str | None] = mapped_column(String(255), unique=True, nullable=True)
    # Отпечаток тела запроса: тот же ключ с другим телом — ошибка, а не тихий возврат.
    request_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
