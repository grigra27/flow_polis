"""Квартальная презентация для лизинговой компании.

Слайд 1 — «Распределение имущества по страховщикам». Данные считаются один
раз и используются и предпросмотром, и PDF. Методика общая с подробным
имущественным отчётом (insured_value + property_report): полисы в силе на
конец квартала с активным на эту дату ДФА, все филиалы, все сделки, без
ОСАГО и без лимитов вида «Ответственность»; страховая сумма текущего
страхового года, неизвестная сумма не подменяется и не входит в итог.
"""

import calendar
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional

from django.utils import timezone

from apps.core.services.reference_images import ReferenceImages

from .insured_value import ZERO
from .property_report import _portfolio, _totals, insurer_distribution

MAX_ROWS = 12
TOP_ROWS = MAX_ROWS - 1
QUARTER_NUMERALS = {1: "I", 2: "II", 3: "III", 4: "IV"}


def quarter_end(year: int, quarter: int) -> date:
    """Последний календарный день квартала."""
    month = quarter * 3
    return date(year, month, calendar.monthrange(year, month)[1])


def last_completed_quarter(today: Optional[date] = None):
    """(год, квартал) последнего завершённого календарного квартала."""
    today = today or timezone.localdate()
    quarter = (today.month - 1) // 3 + 1
    if quarter == 1:
        return today.year - 1, 4
    return today.year, quarter - 1


def _rub(value: Decimal) -> str:
    whole = value.quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return f"{int(whole):,}".replace(",", " ")


def _percent(value: Decimal) -> str:
    return f"{value.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP):.2f}".replace(
        ".", ","
    )


def build_insurer_slide(as_of: date) -> dict:
    images = ReferenceImages()
    objects = _portfolio(as_of, None, "all", property_only=True)
    rows = insurer_distribution(objects, images)
    totals = _totals(objects)
    total = totals["sum"]
    insurer_count = len(rows)
    other_count = 0
    if len(rows) > MAX_ROWS:
        hidden = rows[TOP_ROWS:]
        other_count = len(hidden)
        other_sum = sum((r["sum"] for r in hidden), ZERO)
        rows = rows[:TOP_ROWS] + [
            {
                "key": None,
                "name": "Иные",
                "sum": other_sum,
                "count": sum(r["count"] for r in hidden),
                "share": other_sum / total * 100 if total else ZERO,
                "image_url": "",
            }
        ]
    for row in rows:
        row["sum_display"] = _rub(row["sum"])
        row["share_display"] = _percent(row["share"]) + "%"
    return {
        "kind": "insurers",
        "title": "Распределение имущества по страховщикам",
        "as_of": as_of,
        "rows": rows,
        "total_sum": total,
        "total_sum_display": _rub(total),
        "total_share_display": "100,00%" if total else "—",
        "record_count": totals["count"],
        "insurer_count": insurer_count,
        "other_count": other_count,
        "empty": not rows,
    }


def build_quarterly_presentation(year: int, quarter: int) -> dict:
    as_of = quarter_end(year, quarter)
    return {
        "year": year,
        "quarter": quarter,
        "quarter_label": f"{QUARTER_NUMERALS[quarter]} квартал {year} года",
        "as_of": as_of,
        "slides": [build_insurer_slide(as_of)],
    }
