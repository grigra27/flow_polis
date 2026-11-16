"""Квартальная презентация для лизинговой компании.

Слайд 1 — «Распределение имущества по страховщикам», слайд 2 —
«Распределение имущества по филиалам и страховщикам». Набор записей
загружается один раз на запрос и используется обоими слайдами,
предпросмотром и PDF. Методика общая с подробным имущественным отчётом
(insured_value + property_report): полисы в силе на конец квартала с
активным на эту дату ДФА, все филиалы, все сделки, без ОСАГО и без
лимитов вида «Ответственность»; страховая сумма текущего страхового
года, неизвестная сумма не подменяется и не входит в итог.
"""

import calendar
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional

from django.utils import timezone

from apps.core.services.reference_images import ReferenceImages

from .insured_value import ZERO
from .property_report import _matrix, _portfolio, _totals, insurer_distribution

MAX_ROWS = 12
TOP_ROWS = MAX_ROWS - 1
MAX_MATRIX_INSURERS = 7
MAX_MATRIX_BRANCHES = 10
TOP_MATRIX_BRANCHES = MAX_MATRIX_BRANCHES - 1
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


def _million_display(value: Decimal) -> str:
    scaled = (value / 1_000_000).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
    return f"{scaled:,.1f}".replace(",", " ").replace(".", ",")


def _cell_display(value: Decimal) -> str:
    """млн ₽ с одним знаком: прочерк без учтённой суммы, «<0,1» вместо 0,0."""
    if not value:
        return "—"
    text = _million_display(value)
    return "<0,1" if text == "0,0" else text


def build_insurer_slide(as_of: date, objects=None, images=None) -> dict:
    images = ReferenceImages() if images is None else images
    if objects is None:
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


def build_branch_matrix_slide(as_of: date, objects=None) -> dict:
    """Слайд 2: филиалы × страховщики на том же наборе записей, что и слайд 1.

    Матрицу считает общий с подробным отчётом _matrix; скрытые страховщики
    и филиалы сворачиваются в «Иные», но все суммы остаются в итогах строк,
    столбцов и общем итоге (включая пересечение обеих групп «Иные»).
    """
    if objects is None:
        objects = _portfolio(as_of, None, "all", property_only=True)
    matrix = _matrix(
        objects,
        lambda o: o.branch_id,
        lambda o: o.branch,
        lambda o: o.insurer_id,
        lambda o: o.insurer,
        columns_limit=MAX_MATRIX_INSURERS,
    )
    all_rows = matrix["rows"]
    headers = matrix["headers"]
    column_count = len(headers)
    other_insurers = column_count > MAX_MATRIX_INSURERS
    insurer_count = len({o.insurer_id for o in objects})
    other_insurer_count = max(0, insurer_count - MAX_MATRIX_INSURERS)

    # Итоги столбцов — по всем филиалам, включая попавшие в «Иные филиалы».
    column_totals = [
        sum((row["cells"][i]["sum"] for row in all_rows), ZERO)
        for i in range(column_count)
    ]
    total = sum((row["total"] for row in all_rows), ZERO)

    branch_count = len(all_rows)
    other_branch_count = 0
    shown = all_rows
    if branch_count > MAX_MATRIX_BRANCHES:
        hidden = all_rows[TOP_MATRIX_BRANCHES:]
        other_branch_count = len(hidden)
        shown = all_rows[:TOP_MATRIX_BRANCHES] + [
            {
                "key": None,
                "name": "Иные филиалы",
                "total": sum((r["total"] for r in hidden), ZERO),
                "cells": [
                    {"sum": sum((r["cells"][i]["sum"] for r in hidden), ZERO)}
                    for i in range(column_count)
                ],
                "is_other": True,
            }
        ]

    rows = []
    for row in shown:
        sums = [cell["sum"] for cell in row["cells"]]
        # Подсветка максимума — только среди отдельно показанных страховщиков
        # и только в строках реальных филиалов; «Иные» не подсвечиваются.
        shown_range = range(column_count - 1 if other_insurers else column_count)
        best = max((sums[i] for i in shown_range), default=ZERO)
        highlight = None
        if best > 0 and not row.get("is_other"):
            highlight = next(i for i in shown_range if sums[i] == best)
        rows.append(
            {
                "key": row["key"],
                "name": row["name"],
                "total": row["total"],
                "total_display": _cell_display(row["total"]),
                "cells": [
                    {
                        "sum": value,
                        "display": _cell_display(value),
                        "highlight": i == highlight,
                    }
                    for i, value in enumerate(sums)
                ],
                "is_other": row.get("is_other", False),
            }
        )

    columns = [
        {
            "name": "Иные страховщики"
            if other_insurers and i == column_count - 1
            else name,
            "total": column_totals[i],
            "total_display": _cell_display(column_totals[i]),
            "is_other": other_insurers and i == column_count - 1,
        }
        for i, name in enumerate(headers)
    ]

    notes = []
    if other_insurers:
        notes.append(
            f"Отдельно показаны {MAX_MATRIX_INSURERS} крупнейших страховщиков; "
            f"«Иные страховщики» — ещё {other_insurer_count}."
        )
    if other_branch_count:
        notes.append(
            f"«Иные филиалы» — {other_branch_count} филиалов с меньшей страховой суммой."
        )
    notes.append(
        "Все суммы — в млн ₽: страховая сумма текущего страхового года "
        "действующих полисов с активным ДФА; без ОСАГО и лимитов ответственности."
    )
    return {
        "kind": "branch_matrix",
        "title": "Распределение имущества по филиалам и страховщикам",
        "as_of": as_of,
        "columns": columns,
        "rows": rows,
        "total_sum": total,
        "total_sum_display": _cell_display(total),
        "insurer_count": insurer_count,
        "other_insurer_count": other_insurer_count,
        "branch_count": branch_count,
        "other_branch_count": other_branch_count,
        "note": " ".join(notes),
        "empty": not all_rows,
    }


def build_quarterly_presentation(year: int, quarter: int) -> dict:
    as_of = quarter_end(year, quarter)
    objects = _portfolio(as_of, None, "all", property_only=True)
    images = ReferenceImages()
    return {
        "year": year,
        "quarter": quarter,
        "quarter_label": f"{QUARTER_NUMERALS[quarter]} квартал {year} года",
        "as_of": as_of,
        "slides": [
            build_insurer_slide(as_of, objects=objects, images=images),
            build_branch_matrix_slide(as_of, objects=objects),
        ],
    }
