"""Слайды 3–4 квартальной презентации по фактическим оплатам.

Слайд 3 «Страхование с участием и без участия брокера». Отбор —
фактические оплаты взносов: PaymentSchedule.paid_date внутри выбранного
календарного квартала включительно. due_date, дата начала полиса и дата
согласования акта период не определяют. Все филиалы и оба канала;
участие брокера — Policy.broker_participation. ОСАГО и вид
«Ответственность» исключаются той же классификацией, что на слайдах 1–2.

Платёж определяет попадание в отчёт, но в деньгах учитывается страховая
сумма взноса installment_number=1 того же страхового года: пара
(policy_id, year_number) считается один раз за квартал в месяце первой
подходящей оплаты. В расчётном наборе сохраняются branch_id и client_id
для слайда 4 — «Распределение страхования без участия брокера».
"""

from datetime import date
from decimal import Decimal

from django.db.models import F, Q

from apps.clients.models import Client
from apps.insurers.models import Branch
from apps.policies.models import PaymentSchedule

from .insured_value import ZERO
from .quarterly_presentation import (
    QUARTER_NUMERALS,
    _cell_display,
    _percent,
    quarter_end,
)

MONTH_NAMES = (
    "Январь",
    "Февраль",
    "Март",
    "Апрель",
    "Май",
    "Июнь",
    "Июль",
    "Август",
    "Сентябрь",
    "Октябрь",
    "Ноябрь",
    "Декабрь",
)
CATEGORY_LABELS = {
    "all": "Все договоры",
    "new": "Новые договоры",
    "prolongation": "Пролонгации",
}


def _in_force_at_paid_q():
    """Действие полиса и ДФА на дату фактической оплаты каждой строки.

    Дата расторжения/закрытия приоритетнее флага: в сам день события
    полис или ДФА уже не действует, поэтому оплаты в этот день и позже
    отсекаются, а более ранние оплаты остаются в историческом квартале.
    Снятый флаг без даты консервативно считается закрытым — как в
    in_force_q и dfa_in_force_q. Плановое окно полиса не проверяем:
    отчёт не требует действия полиса на конец квартала.
    """
    return (
        (
            Q(policy__termination_date__isnull=True)
            | Q(policy__termination_date__gt=F("paid_date"))
        )
        & (Q(policy__policy_active=True) | Q(policy__termination_date__isnull=False))
        & (
            Q(policy__dfa_deactivation_date__gt=F("paid_date"))
            | Q(
                policy__dfa_active=True,
                policy__dfa_deactivation_date__isnull=True,
            )
        )
    )


def broker_payment_pairs(year: int, quarter: int) -> list:
    """Пары (полис, страховой год) с фактической оплатой в квартале.

    Два запроса на весь квартал: оплаты и первые взносы годов как источник
    СС. Порядок first-paid стабилен: paid_date, затем PK платежа.
    """
    start = date(year, quarter * 3 - 2, 1)
    end = quarter_end(year, quarter)
    payments = (
        PaymentSchedule.objects.filter(
            paid_date__isnull=False,
            paid_date__gte=start,
            paid_date__lte=end,
        )
        .filter(_in_force_at_paid_q())
        .select_related("policy__insurance_type")
        .order_by("paid_date", "pk")
    )
    pairs = {}
    for pay in payments:
        policy = pay.policy
        insurance_type = policy.insurance_type
        # Та же классификация, что is_liability/without_osago на слайдах 1–2.
        if (
            insurance_type.is_osago
            or insurance_type.name.strip().casefold() == "ответственность"
        ):
            continue
        key = (pay.policy_id, pay.year_number)
        if key in pairs:
            continue
        pairs[key] = {
            "policy_id": pay.policy_id,
            "year_number": pay.year_number,
            "payment_id": pay.pk,
            "month": pay.paid_date.month - start.month + 1,
            "branch_id": policy.branch_id,
            "client_id": policy.client_id,
            "broker": policy.broker_participation,
            "prolongation": pay.year_number > 1 or policy.renewal_to_old_dfa,
        }
    if not pairs:
        return []
    first_sums = {
        (row.policy_id, row.year_number): row.insurance_sum
        for row in PaymentSchedule.objects.filter(
            installment_number=1,
            policy_id__in={key[0] for key in pairs},
        ).only("policy_id", "year_number", "insurance_sum")
    }
    result = []
    for key, pair in pairs.items():
        pair["insured_sum"] = first_sums.get(key)
        result.append(pair)
    return result


def _sums(pairs):
    known = [p for p in pairs if p["insured_sum"] is not None]
    total = sum((p["insured_sum"] for p in known), ZERO)
    without = sum((p["insured_sum"] for p in known if not p["broker"]), ZERO)
    return total, without


def _share_display(total: Decimal, without: Decimal) -> str:
    if not total:
        return "—"
    return _percent(without / total * 100) + "%"


def _block(pairs) -> list:
    rows = []
    for category, label in CATEGORY_LABELS.items():
        if category == "all":
            selected = pairs
        else:
            wanted = category == "prolongation"
            selected = [p for p in pairs if p["prolongation"] == wanted]
        total, without = _sums(selected)
        rows.append(
            {
                "label": label,
                "total": total,
                "without": without,
                "total_display": _cell_display(total),
                "without_display": _cell_display(without),
                "share_display": _share_display(total, without),
            }
        )
    return rows


def build_broker_slide(year: int, quarter: int, pairs=None) -> dict:
    if pairs is None:
        pairs = broker_payment_pairs(year, quarter)
    known = [p for p in pairs if p["insured_sum"] is not None]
    unknown = [p for p in pairs if p["insured_sum"] is None]
    start_month = quarter * 3 - 2
    months = [
        {
            "name": MONTH_NAMES[start_month - 1 + i],
            "rows": _block([p for p in known if p["month"] == i + 1]),
        }
        for i in range(3)
    ]
    total, without = _sums(known)
    quarter_rows = _block(known)
    # Итоги >= 100 млрд ₽ не влезают в колонку обычным кеглем — HTML уменьшит шрифт.
    numeric = [
        row[key]
        for block in [quarter_rows] + [m["rows"] for m in months]
        for row in block
        for key in ("total_display", "without_display")
    ]
    compact = any(len(text) >= 9 for text in numeric)
    note = (
        "Страховая сумма учитывается один раз на полис и страховой год за квартал; "
        "пролонгации — оплаты за второй и последующие страховые годы и перезаключения "
        "к старому ДФА; без ОСАГО и лимитов ответственности."
    )
    if unknown:
        note += (
            f" Пар полис–год с неопределённой СС: {len(unknown)} "
            f"(без брокера — {sum(not p['broker'] for p in unknown)}); "
            "в денежные итоги они не включены."
        )
    return {
        "kind": "broker",
        "title": "Страхование с участием и без участия брокера",
        "as_of": quarter_end(year, quarter),
        "quarter_label": f"{QUARTER_NUMERALS[quarter]} квартал {year} года",
        "subtitle": "По фактической дате оплаты взносов",
        "months": months,
        "quarter_block": {"name": "Итого за квартал", "rows": quarter_rows},
        "table_rows": [
            {
                "label": quarter_rows[i]["label"],
                "cells": [month["rows"][i] for month in months] + [quarter_rows[i]],
            }
            for i in range(3)
        ],
        "share_display": _share_display(total, without),
        "without_display": _cell_display(without),
        "total_display": _cell_display(total),
        "unknown_count": len(unknown),
        "unknown_without_count": sum(not p["broker"] for p in unknown),
        "note": note,
        "empty": not pairs,
        "compact": compact,
    }


# Слайд 4: максимум строк в каждой таблице без учёта шапки и «Итого».
# При большем числе групп остаются 7 крупнейших и строка «Иные».
DIST_MAX_ROWS = 8
DIST_TOP_ROWS = DIST_MAX_ROWS - 1


def _distribution_names(model, field: str, ids) -> dict:
    """Названия справочника одним запросом на разрез, не на строку."""
    return dict(model.objects.filter(pk__in=ids).values_list("pk", field))


def _distribution_block(pairs, key_field: str, names: dict, other_label: str) -> dict:
    """Разрез: строки групп, «Иные» и «Итого» в страховой сумме без брокера.

    Сортировка — по убыванию неокруглённой СС, при равенстве по ID группы.
    Доля каждой строки считается от итога «Без брокера» за квартал, как на
    слайде 3; итог строки «Итого» до округления равен этому итогу.
    """
    groups = {}
    for pair in pairs:
        groups.setdefault(pair[key_field], []).append(pair["insured_sum"])
    total = sum((p["insured_sum"] for p in pairs), ZERO)
    rows = [
        {"id": group_id, "name": names[group_id], "sum": sum(sums, ZERO)}
        for group_id, sums in groups.items()
    ]
    rows.sort(key=lambda row: (-row["sum"], row["id"]))
    other_count = 0
    if len(rows) > DIST_MAX_ROWS:
        hidden = rows[DIST_TOP_ROWS:]
        other_count = len(hidden)
        rows = rows[:DIST_TOP_ROWS] + [
            {
                "id": None,
                "name": other_label,
                "sum": sum((row["sum"] for row in hidden), ZERO),
                "is_other": True,
            }
        ]
    for row in rows:
        row["sum_display"] = _cell_display(row["sum"])
        row["share_display"] = _share_display(total, row["sum"])
    return {
        "rows": rows,
        "total": {
            "name": "Итого",
            "sum": total,
            "sum_display": _cell_display(total),
            "share_display": _share_display(total, total),
        },
        "other_count": other_count,
    }


def build_distribution_slide(year: int, quarter: int, pairs=None) -> dict:
    """Слайд 4: раскладка «Без брокера» по филиалам и лизингополучателям.

    Тот же набор пар, что у слайда 3 (broker_payment_pairs передаётся
    наружу один раз на сборку): берём только broker=False и известную
    страховую сумму. Пустой срез без брокера и срез, в котором ни у
    одной пары не определена СС, — разные состояния без таблиц и долей.
    """
    if pairs is None:
        pairs = broker_payment_pairs(year, quarter)
    without = [p for p in pairs if not p["broker"]]
    known = [p for p in without if p["insured_sum"] is not None]
    unknown = [p for p in without if p["insured_sum"] is None]
    slide = {
        "kind": "broker_distribution",
        "title": "Распределение страхования без участия брокера",
        "as_of": quarter_end(year, quarter),
        "quarter_label": f"{QUARTER_NUMERALS[quarter]} квартал {year} года",
        "subtitle": "По фактической дате оплаты взносов",
        "sum_label": "Страховая сумма без брокера за квартал",
        "unknown_count": len(unknown),
        "empty": not without,
        "no_sums": bool(without) and not known,
    }
    base_note = (
        "Разрезы — обслуживающий филиал и лизингополучатель; "
        "отбор по фактическим оплатам и страховые суммы — как на слайде 3."
    )
    if not known:
        slide["sum_display"] = "—"
        slide["tables"] = []
        slide["note"] = base_note
        return slide
    branch_names = _distribution_names(
        Branch, "branch_name", {p["branch_id"] for p in known}
    )
    client_names = _distribution_names(
        Client, "client_name", {p["client_id"] for p in known}
    )
    branches = _distribution_block(known, "branch_id", branch_names, "Иные филиалы")
    clients = _distribution_block(
        known, "client_id", client_names, "Иные лизингополучатели"
    )
    slide["sum_display"] = _cell_display(branches["total"]["sum"])
    # Итоги >= 100 млрд ₽ не влезают в колонку обычным кеглем — HTML уменьшит шрифт.
    displays = [
        row[key]
        for block in (branches, clients)
        for row in block["rows"] + [block["total"]]
        for key in ("sum_display", "share_display")
    ]
    slide["compact"] = any(len(text) >= 9 for text in displays)
    slide["tables"] = [
        {"name": "По филиалам", "css": "qp-dist--narrow", **branches},
        {"name": "По лизингополучателям", "css": "qp-dist--wide", **clients},
    ]
    notes = [base_note]
    if branches["other_count"]:
        notes.append(
            f"«Иные филиалы» — ещё {branches['other_count']} "
            "филиалов с меньшей страховой суммой."
        )
    if clients["other_count"]:
        notes.append(
            f"«Иные лизингополучатели» — ещё {clients['other_count']} "
            "лизингополучателей с меньшей страховой суммой."
        )
    if unknown:
        notes.append(
            f"Пар полис–год с неопределённой СС: {len(unknown)}; "
            "в денежные итоги и доли они не включены."
        )
    slide["note"] = " ".join(notes)
    return slide
