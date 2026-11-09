"""Утилиты для работы с датами с учётом производственного календаря РФ."""

from calendar import isleap
from datetime import date, timedelta
from functools import lru_cache

import holidays


# Подтверждённые переносы для пятидневной рабочей недели. Базовые праздники
# остаются в holidays; закреплённая версия 0.96 ещё не содержит эти переносы.
# 2026: постановление Правительства РФ от 24.09.2025 № 1466 и ст. 112 ТК РФ.
# http://publication.pravo.gov.ru/Document/View/0001202509240023
# 2027: постановление Правительства РФ от 17.09.2026 № 1187 и ст. 112 ТК РФ.
# http://publication.pravo.gov.ru/Document/View/0001202609180037
# Разъяснение ст. 112: https://mintrud.gov.ru/labour/relationship/351
# Сводный перечень: https://www.cbr.ru/other/holidays/
_EXTRA_NON_WORKING_DAYS = {
    2026: frozenset(
        {date(2026, 1, 9), date(2026, 3, 9), date(2026, 5, 11), date(2026, 12, 31)}
    ),
    2027: frozenset(
        {
            date(2027, 2, 22),
            date(2027, 5, 3),
            date(2027, 5, 10),
            date(2027, 6, 14),
            date(2027, 11, 5),
            date(2027, 12, 31),
        }
    ),
}
_WORKING_WEEKENDS = {2027: frozenset({date(2027, 2, 20)})}


@lru_cache(maxsize=32)
def _working_days_for_year(year: int) -> frozenset[date]:
    """Собрать неизменяемый календарь, не разделяя lazy-состояние holidays."""
    calendar = holidays.country_holidays("RU", years=[year], expand=False)
    non_working = _EXTRA_NON_WORKING_DAYS.get(year, frozenset())
    working_weekends = _WORKING_WEEKENDS.get(year, frozenset())
    first_day = date(year, 1, 1)
    days = (first_day + timedelta(days=offset) for offset in range(365 + isleap(year)))
    return frozenset(
        day
        for day in days
        if day in working_weekends
        or (day not in non_working and calendar.is_working_day(day))
    )


def is_business_day(value: date) -> bool:
    """Является ли дата рабочим днём в России.

    Пятидневная неделя с учётом государственных праздников и рабочих
    суббот. Переносы на 2026–2027 годы сверены с официальными источниками;
    для остальных лет используются данные закреплённой версии holidays.
    После публикации календаря на следующий год набор переносов нужно сверить.
    """
    day = date(value.year, value.month, value.day)
    return day in _working_days_for_year(day.year)


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
