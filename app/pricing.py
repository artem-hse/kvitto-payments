"""Чистая бизнес-логика без БД и HTTP: цены, промокоды, график рассрочки, статусы.

Вынесена отдельно, чтобы её можно было тестировать напрямую.
"""

from typing import Literal

PaymentStatus = Literal["pending", "succeeded", "failed", "refunded"]

# Промокод -> скидка в процентах. Ключи в верхнем регистре, сравнение без учёта регистра.
PROMO_CODES: dict[str, int] = {"KVITTO10": 10}

ALLOWED_TRANSITIONS: set[tuple[str, str]] = {
    ("pending", "succeeded"),
    ("pending", "failed"),
    ("succeeded", "refunded"),
}

TARIFFS_SEED: list[tuple[int, str, int]] = [
    (1, "basic", 990_000),  # 9 900 ₽
    (2, "standard", 1_990_000),  # 19 900 ₽
    (3, "premium", 2_990_000),  # 29 900 ₽
]


def normalize_promo(code: str) -> str:
    return code.strip().upper()


def is_known_promo(code: str) -> bool:
    return normalize_promo(code) in PROMO_CODES


def calc_discount(price: int, promo_code: str | None) -> int:
    """Скидка в копейках. Целочисленное деление округляет скидку вниз,
    поэтому и скидка, и сумма к оплате всегда целые копейки."""
    if promo_code is None:
        return 0
    percent = PROMO_CODES[normalize_promo(promo_code)]
    return price * percent // 100


def split_schedule(amount: int, months: int) -> list[int]:
    """Делит сумму на `months` платежей в копейках.

    Сумма графика ровно равна amount; лишние копейки уходят в первые платежи:
    1990000 / 3 -> [663334, 663333, 663333].
    """
    if months <= 0:
        raise ValueError("months must be positive")
    base, remainder = divmod(amount, months)
    return [base + 1] * remainder + [base] * (months - remainder)


def can_transition(current: str, new: str) -> bool:
    return (current, new) in ALLOWED_TRANSITIONS
