"""
Тесты apps.core.date_utils.

previous_business_day используется в письме в Альянс-лизинг
(apps.billing.models.BillingTask.build_alliance_letter_text) —
сдвигает дату «Оплатить до» на предыдущий рабочий день.
"""
from datetime import date

import pytest

from apps.core.date_utils import is_business_day, previous_business_day


# --- is_business_day ---


@pytest.mark.parametrize("value", [date(2026, 5, 13), date(2024, 2, 29)])
def test_weekday_is_business_day(value):
    assert is_business_day(value) is True


def test_saturday_is_not_business_day():
    # 2026-05-16 — суббота.
    assert is_business_day(date(2026, 5, 16)) is False


def test_sunday_is_not_business_day():
    # 2026-05-17 — воскресенье.
    assert is_business_day(date(2026, 5, 17)) is False


def test_russian_holiday_is_not_business_day():
    # 9 мая 2026 — суббота И День Победы; не рабочий по обоим основаниям.
    assert is_business_day(date(2026, 5, 9)) is False


def test_new_year_holiday_is_not_business_day():
    # 5 января 2026 — понедельник, но новогодние каникулы.
    assert is_business_day(date(2026, 1, 5)) is False


# --- previous_business_day: базовые сдвиги ---


@pytest.mark.parametrize(
    ("deadline", "expected"),
    [
        (date(2026, 5, 13), date(2026, 5, 12)),
        (date(2024, 3, 1), date(2024, 2, 29)),
    ],
)
def test_after_normal_weekday_returns_previous_day(deadline, expected):
    assert previous_business_day(deadline) == expected


def test_monday_returns_previous_friday():
    # Понедельник 2026-05-18 → пятница 2026-05-15 (через выходные).
    assert previous_business_day(date(2026, 5, 18)) == date(2026, 5, 15)


def test_saturday_returns_previous_friday():
    # Суббота 2026-05-16: «день раньше» — пятница 2026-05-15.
    assert previous_business_day(date(2026, 5, 16)) == date(2026, 5, 15)


# --- previous_business_day: праздничные кейсы ---


def test_after_new_year_holidays_jumps_back_to_december():
    # 12 января 2026 (понедельник) — первый рабочий день после каникул.
    # Предыдущий рабочий день — 30 декабря 2025 (вт), потому что
    # 1-8 января — каникулы, 9 января и 31 декабря — перенесённые выходные.
    assert previous_business_day(date(2026, 1, 12)) == date(2025, 12, 30)


def test_after_may_holidays():
    # 12 мая 2026 (вт) идёт сразу после длинных майских.
    # 9 мая — Победа (Сб), 10 мая — Вс, 11 мая — перенесённый выходной.
    assert previous_business_day(date(2026, 5, 12)) == date(2026, 5, 8)


def test_after_defender_of_fatherland():
    # 24 февраля 2026 (вт) — после 23 февраля (Пн, праздник).
    # Предыдущий рабочий день — 20 февраля 2026 (пт).
    assert previous_business_day(date(2026, 2, 24)) == date(2026, 2, 20)


def test_after_womens_day_weekend_block():
    # 9 марта 2026 (Пн) — 8 марта 2026 (Вс, праздник), 7 марта (Сб).
    # Предыдущий рабочий день — 6 марта 2026 (пт).
    assert previous_business_day(date(2026, 3, 9)) == date(2026, 3, 6)


@pytest.mark.parametrize(
    "value",
    [
        date(2024, 4, 27),
        date(2024, 11, 2),
        date(2024, 12, 28),
        date(2025, 11, 1),
        date(2027, 2, 20),
    ],
    ids=lambda value: value.isoformat(),
)
def test_transferred_saturdays_are_business_days(value):
    assert value.weekday() == 5
    assert is_business_day(value) is True


@pytest.mark.parametrize(
    "value",
    [
        date(2026, 1, 9),
        date(2026, 3, 9),
        date(2026, 5, 11),
        date(2026, 12, 31),
        date(2027, 2, 22),
        date(2027, 5, 3),
        date(2027, 5, 10),
        date(2027, 6, 14),
        date(2027, 11, 5),
        date(2027, 12, 31),
    ],
    ids=lambda value: value.isoformat(),
)
def test_transferred_weekdays_are_not_business_days(value):
    assert value.weekday() < 5
    assert is_business_day(value) is False


@pytest.mark.parametrize(
    ("deadline", "expected"),
    [
        (date(2024, 4, 28), date(2024, 4, 27)),
        (date(2024, 5, 2), date(2024, 4, 27)),
        (date(2024, 11, 3), date(2024, 11, 2)),
        (date(2024, 11, 5), date(2024, 11, 2)),
        (date(2024, 12, 29), date(2024, 12, 28)),
        (date(2025, 1, 9), date(2024, 12, 28)),
        (date(2025, 11, 2), date(2025, 11, 1)),
        (date(2025, 11, 5), date(2025, 11, 1)),
        (date(2026, 3, 10), date(2026, 3, 6)),
        (date(2026, 12, 31), date(2026, 12, 30)),
        (date(2027, 1, 11), date(2026, 12, 30)),
        (date(2027, 2, 21), date(2027, 2, 20)),
        (date(2027, 2, 22), date(2027, 2, 20)),
        (date(2027, 2, 23), date(2027, 2, 20)),
        (date(2027, 2, 24), date(2027, 2, 20)),
        (date(2027, 5, 4), date(2027, 4, 30)),
        (date(2027, 5, 11), date(2027, 5, 7)),
        (date(2027, 6, 15), date(2027, 6, 11)),
        (date(2027, 11, 8), date(2027, 11, 3)),
        (date(2028, 1, 1), date(2027, 12, 30)),
    ],
    ids=lambda value: value.isoformat(),
)
def test_previous_business_day_respects_transfers(deadline, expected):
    assert previous_business_day(deadline) == expected
