"""Утилиты для работы с датами с учётом производственного календаря РФ."""

from datetime import date, timedelta

import holidays


_RU_HOLIDAYS = holidays.country_holidays("RU")


def is_business_day(value: date) -> bool:
    """Является ли дата рабочим днём в России.

    Учитывает субботу/воскресенье и государственные праздники РФ
    (через библиотеку `holidays`, включая часть перенесённых выходных,
    которые библиотека успела закодировать).

    Ограничение: переносы рабочих суббот, объявляемые отдельными
    постановлениями Правительства, библиотека может не знать.
    План перехода на полный календарь — `docs/FUTURE_IMPROVEMENTS.md`.
    """
    if value.weekday() >= 5:
        return False
    return value not in _RU_HOLIDAYS


def previous_business_day(value: date) -> date:
    """Предыдущий рабочий день относительно `value`.

    Шагает назад от `value - 1 день`, пропуская выходные и праздники.
    Используется при формировании письма в Альянс-лизинг: лизингу
    указывается срок оплаты на один рабочий день раньше дедлайна СК,
    чтобы они успели провести платёж в банковский день.
    """
    candidate = value - timedelta(days=1)
    while not is_business_day(candidate):
        candidate -= timedelta(days=1)
    return candidate
