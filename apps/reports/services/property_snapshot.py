"""
Снимок распределения портфеля действующих полисов по страховой сумме.

Считает то же, что блок Portfolio Structure в Dashboard V2, но возвращает
полный список без отсечения «топ-5 + Прочие». Используется для отчёта-
презентации руководству лизинговой компании.

Логика «страховой суммы полиса» воспроизводит dashboard V2:
для каждого полиса берётся MAX(insurance_sum) из его графика платежей,
эти значения суммируются по группам (филиал / страховщик / вид страхования).
"""
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple

from django.db.models import Max
from django.db.models.functions import Coalesce
from django.utils import timezone

from apps.policies.models import PaymentSchedule, Policy


DECIMAL_ZERO = Decimal("0")

# Палитра для секторов пирога. Подобрана так, чтобы соседние сегменты
# не сливались; повторяется по кругу, если групп больше длины палитры.
PIE_PALETTE: List[str] = [
    "#2563eb",
    "#16a34a",
    "#f59e0b",
    "#dc2626",
    "#7c3aed",
    "#0891b2",
    "#db2777",
    "#65a30d",
    "#ea580c",
    "#0f766e",
    "#9333ea",
    "#475569",
    "#b45309",
    "#1d4ed8",
    "#15803d",
    "#be123c",
    "#0369a1",
    "#a16207",
    "#581c87",
    "#334155",
]


def _aggregate_dimension(
    label_field: str,
    id_field: Optional[str] = None,
) -> Tuple[List[Dict[str, Any]], Decimal]:
    """
    Сгруппировать активные полисы по `label_field` и сложить MAX(insurance_sum)
    по каждому полису внутри группы.
    """
    payments_qs = PaymentSchedule.objects.filter(policy__policy_active=True)

    value_fields = [label_field, "policy_id"]
    if id_field:
        value_fields.append(id_field)

    policy_rows = (
        payments_qs.values(*value_fields)
        .annotate(policy_max=Coalesce(Max("insurance_sum"), DECIMAL_ZERO))
        .order_by()
    )

    grouped: Dict[str, Dict[str, Any]] = {}
    for row in policy_rows:
        label = row.get(label_field) or "Не указано"
        entity_id = row.get(id_field) if id_field else None
        key = f"{entity_id}:{label}" if entity_id is not None else label

        grouped.setdefault(
            key,
            {
                "id": entity_id,
                "name": label,
                "insurance_sum": DECIMAL_ZERO,
                "policy_count": 0,
            },
        )
        grouped[key]["insurance_sum"] += row["policy_max"] or DECIMAL_ZERO
        grouped[key]["policy_count"] += 1

    items = sorted(
        grouped.values(),
        key=lambda x: x["insurance_sum"],
        reverse=True,
    )

    total = sum((item["insurance_sum"] for item in items), DECIMAL_ZERO)

    for index, item in enumerate(items):
        if total > DECIMAL_ZERO:
            item["share"] = (item["insurance_sum"] / total * Decimal("100")).quantize(
                Decimal("0.1")
            )
        else:
            item["share"] = DECIMAL_ZERO
        # Округляем до целых рублей: отчёт для руководства, копейки лишние.
        item["insurance_sum"] = item["insurance_sum"].quantize(Decimal("1"))
        item["color"] = PIE_PALETTE[index % len(PIE_PALETTE)]

    return items, total.quantize(Decimal("1"))


def _build_pie_gradient(items: List[Dict[str, Any]]) -> str:
    """Собрать CSS conic-gradient из долей секторов."""
    if not items:
        return "conic-gradient(#e5e7eb 0% 100%)"

    segments: List[str] = []
    cursor = Decimal("0")
    for item in items:
        end = cursor + item["share"]
        segments.append(f"{item['color']} {cursor}% {end}%")
        cursor = end

    # Если из-за округления не добрали до 100%, добиваем последним цветом.
    if cursor < Decimal("100"):
        segments.append(f"{items[-1]['color']} {cursor}% 100%")

    return "conic-gradient(" + ", ".join(segments) + ")"


def build_property_snapshot() -> Dict[str, Any]:
    """Сформировать данные для отчёта-снимка распределения портфеля."""
    by_branch, total = _aggregate_dimension(
        label_field="policy__branch__branch_name",
        id_field="policy__branch_id",
    )
    by_insurer, _ = _aggregate_dimension(
        label_field="policy__insurer__insurer_name",
        id_field="policy__insurer_id",
    )
    by_type, _ = _aggregate_dimension(
        label_field="policy__insurance_type__name",
        id_field="policy__insurance_type_id",
    )

    active_policies_count = Policy.objects.filter(policy_active=True).count()

    return {
        "as_of": timezone.localdate(),
        "total_insurance_sum": total,
        "active_policies_count": active_policies_count,
        "sections": [
            {
                "title": "По филиалам",
                "subtitle": "Распределение страховой суммы по филиалам",
                "items": by_branch,
                "pie_css": _build_pie_gradient(by_branch),
            },
            {
                "title": "По страховщикам",
                "subtitle": "Распределение страховой суммы по страховым компаниям",
                "items": by_insurer,
                "pie_css": _build_pie_gradient(by_insurer),
            },
            {
                "title": "По видам страхования",
                "subtitle": "Распределение страховой суммы по видам страхования",
                "items": by_type,
                "pie_css": _build_pie_gradient(by_type),
            },
        ],
    }
