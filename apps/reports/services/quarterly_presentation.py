"""Квартальная презентация для лизинговой компании.

Слайд 1 — «Распределение имущества по страховщикам», слайд 2 —
«Распределение имущества по филиалам и страховщикам», слайд 3 —
«Страхование с участием и без участия брокера» по фактическим оплатам,
слайд 4 — «Распределение страхования без участия брокера» по филиалам
и лизингополучателям на тех же парах оплат. Портфель слайдов 1–2
загружается один раз на запрос, пары оплат слайдов 3–4 — тоже,
предпросмотр и PDF используют одни данные. Методика слайдов 1–2 общая
с подробным имущественным отчётом (insured_value + property_report):
полисы в силе на конец квартала с активным на эту дату ДФА, все
филиалы, все сделки, без ОСАГО и без лимитов вида «Ответственность»;
страховая сумма текущего страхового года, неизвестная сумма не
подменяется и не входит в итог.
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

# Фиксированная шкала тепловой карты в рублях: одинаковая сумма получает
# одинаковый уровень в любой строке и любом квартале.
HEAT_THRESHOLDS = (
    Decimal(50_000_000),
    Decimal(100_000_000),
    Decimal(200_000_000),
    Decimal(300_000_000),
)
HEAT_COLORS = ("#F0F5FA", "#DCE8F2", "#C2D6E6", "#A4C1D7", "#82A8C4")
HEAT_LEGEND = (
    {"color": HEAT_COLORS[0], "label": "до 50"},
    {"color": HEAT_COLORS[1], "label": "50–100"},
    {"color": HEAT_COLORS[2], "label": "100–200"},
    {"color": HEAT_COLORS[3], "label": "200–300"},
    {"color": HEAT_COLORS[4], "label": "от 300"},
)


def _heat_level(value: Decimal) -> int:
    """0 — нейтральная ячейка, 1–5 — уровень шкалы по неокруглённой сумме."""
    if value <= 0:
        return 0
    for level, threshold in enumerate(HEAT_THRESHOLDS, 1):
        if value < threshold:
            return level
    return len(HEAT_COLORS)


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


def _billions_display(value: Decimal) -> str:
    """Крупный показатель портфеля: млрд ₽ с двумя знаками, ниже — млн ₽."""
    if value >= Decimal(1_000_000_000):
        scaled = (value / Decimal(1_000_000_000)).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
        return f"{scaled:,.2f}".replace(",", " ").replace(".", ",") + " млрд ₽"
    scaled = (value / Decimal(1_000_000)).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return f"{int(scaled):,}".replace(",", " ") + " млн ₽"


# «Доля пяти крупнейших страховщиков»; при меньшем числе — словом.
TOP_COUNT_WORDS = {1: "одного", 2: "двух", 3: "трёх", 4: "четырёх", 5: "пяти"}


def _top_label(count: int) -> str:
    if count == 1:
        return "Доля крупнейшего страховщика"
    if count == 0:
        return "Доля крупнейших страховщиков"
    return f"Доля {TOP_COUNT_WORDS[count]} крупнейших страховщиков"


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
    # Полосы в таблице: единая шкала по крупнейшей доле отдельно показанных
    # страховщиков; «Иные» и «Итого» остаются без полос.
    real_rows = [row for row in rows if row["key"] is not None]
    max_real_share = max((row["share"] for row in real_rows), default=ZERO)
    for row in rows:
        if row["key"] is None or not max_real_share:
            row["bar"] = ZERO
            row["bar_css"] = ""
        else:
            fraction = row["share"] / max_real_share
            row["bar"] = fraction
            row["bar_css"] = f"{float(fraction) * 100:.1f}"
    top = real_rows[:5]
    top_share = sum((row["share"] for row in top), ZERO)
    notes = []
    if other_count:
        notes.append(f"«Иные» — {other_count} страховщиков с меньшей страховой суммой.")
    notes.append(
        "Страховая сумма текущего страхового года действующих полисов "
        "с активным ДФА; без ОСАГО и лимитов ответственности."
    )
    return {
        "kind": "insurers",
        "title": "Распределение имущества по страховщикам",
        "as_of": as_of,
        "rows": rows,
        "total_sum": total,
        "total_sum_display": _rub(total),
        "total_share_display": "100,00%" if total else "—",
        "portfolio_display": _billions_display(total),
        "top_count": len(top),
        "top_share_display": (
            f"{top_share.quantize(Decimal('0.1'), rounding=ROUND_HALF_UP):.1f}".replace(
                ".", ","
            )
            + "%"
        )
        if total
        else "—",
        "top_label": _top_label(len(top)),
        "record_count": totals["count"],
        "insurer_count": insurer_count,
        "other_count": other_count,
        "unknown_sum_count": sum(not o.insured_sum_known for o in objects),
        "note": " ".join(notes),
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
        # Тепловая карта — только на пересечении отдельных филиалов
        # и отдельно показанных страховщиков; «Иные» остаются нейтральными.
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
                        "heat": (
                            0
                            if row.get("is_other")
                            or (other_insurers and i == column_count - 1)
                            else _heat_level(value)
                        ),
                    }
                    for i, value in enumerate(sums)
                ],
                "is_other": row.get("is_other", False),
            }
        )
    # Цвет ячейки берётся из серверной палитры: один источник для HTML,
    # легенды и PDF — без HEX-дублей в CSS.
    for row in rows:
        for cell in row["cells"]:
            cell["color"] = HEAT_COLORS[cell["heat"] - 1] if cell["heat"] else ""

    # Два крупнейших сочетания «филиал × страховщик» среди видимых ячеек:
    # без «Иных» в обеих осях и без итогов, по неокруглённым суммам.
    combos = []
    for row in rows:
        if row["is_other"]:
            continue
        for i, cell in enumerate(row["cells"]):
            if other_insurers and i == column_count - 1:
                continue
            if cell["sum"] <= 0:
                continue
            combos.append((cell["sum"], row["name"], headers[i]))
    combos.sort(key=lambda item: (-item[0], item[1], item[2]))
    top_combos = [
        {
            "branch": branch,
            "insurer": insurer,
            "display": f"{_million_display(value)} млн ₽",
        }
        for value, branch, insurer in combos[:2]
    ]
    if len(top_combos) >= 2:
        top_combos_label = "Крупнейшие сочетания филиал × страховщик"
    elif top_combos:
        top_combos_label = "Крупнейшее сочетание филиал × страховщик"
    else:
        top_combos_label = ""

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
        "legend": HEAT_LEGEND,
        "top_combos_label": top_combos_label,
        "top_combos": top_combos,
        "total_sum": total,
        "total_sum_display": _cell_display(total),
        "insurer_count": insurer_count,
        "other_insurer_count": other_insurer_count,
        "branch_count": branch_count,
        "other_branch_count": other_branch_count,
        "unknown_sum_count": sum(not o.insured_sum_known for o in objects),
        "note": " ".join(notes),
        "empty": not all_rows,
    }


def build_quarterly_presentation(year: int, quarter: int) -> dict:
    from .quarterly_payments import (
        broker_payment_pairs,
        build_broker_slide,
        build_distribution_slide,
    )

    as_of = quarter_end(year, quarter)
    objects = _portfolio(as_of, None, "all", property_only=True)
    images = ReferenceImages()
    # Пары оплат считаются один раз на запрос и питают слайды 3 и 4.
    pairs = broker_payment_pairs(year, quarter)
    return {
        "year": year,
        "quarter": quarter,
        "quarter_label": f"{QUARTER_NUMERALS[quarter]} квартал {year} года",
        "as_of": as_of,
        "slides": [
            build_insurer_slide(as_of, objects=objects, images=images),
            build_branch_matrix_slide(as_of, objects=objects),
            build_broker_slide(year, quarter, pairs=pairs),
            build_distribution_slide(year, quarter, pairs=pairs),
        ],
    }
