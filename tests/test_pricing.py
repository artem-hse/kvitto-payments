"""Юнит-тесты чистой логики — без HTTP и БД."""

import pytest

from app.pricing import calc_discount, can_transition, split_schedule


@pytest.mark.parametrize("amount", [990_000, 1_990_000, 2_990_000, 891_000, 1_791_000, 1, 7])
@pytest.mark.parametrize("months", [3, 6, 12])
def test_schedule_sum_is_exact(amount, months):
    schedule = split_schedule(amount, months)
    assert len(schedule) == months
    assert sum(schedule) == amount
    # Лишние копейки — в первые платежи: график не возрастает, разброс не больше копейки
    assert schedule == sorted(schedule, reverse=True)
    assert max(schedule) - min(schedule) <= 1
    assert all(isinstance(x, int) for x in schedule)


def test_schedule_example_from_spec():
    assert split_schedule(1_990_000, 3) == [663334, 663333, 663333]


def test_discount_rounds_down_to_whole_kopecks():
    # 10% от 9 999,99 ₽ = 99 999,9 коп. -> 99 999 коп.
    assert calc_discount(999_999, "KVITTO10") == 99_999
    assert calc_discount(1_990_000, None) == 0


@pytest.mark.parametrize(
    ("current", "new", "allowed"),
    [
        ("pending", "succeeded", True),
        ("pending", "failed", True),
        ("succeeded", "refunded", True),
        ("failed", "succeeded", False),
        ("refunded", "succeeded", False),
        ("pending", "refunded", False),
        ("succeeded", "succeeded", False),
        ("failed", "pending", False),
    ],
)
def test_transitions(current, new, allowed):
    assert can_transition(current, new) is allowed
