"""Назначение окончательного ДФА диапазону объектов одного акцепта."""
from decimal import Decimal
from uuid import uuid4

from django.db import transaction

from apps.policies.models import FlowPolicySource
from .flow_client import FlowError


def group_for(groups, slot):
    return next((g for g in groups if g["first_slot"] <= slot <= g["last_slot"]), None)


def plan_version(groups):
    return ",".join(g["version"] for g in groups)


def unit_template(policy):
    """Только договорные условия одной единицы. Оплаты и реквизиты объекта индивидуальны."""
    common = {
        name: getattr(policy, name + "_id")
        for name in (
            "client",
            "policyholder",
            "insurer",
            "insurance_type",
            "branch",
            "leasing_manager",
        )
    }
    common.update(
        start_date=policy.start_date.isoformat(),
        end_date=policy.end_date.isoformat(),
        franchise=str(policy.franchise),
    )
    rows = []
    for row in policy.payment_schedule.order_by("year_number", "installment_number"):
        rows.append(
            {
                "year_number": row.year_number,
                "installment_number": row.installment_number,
                "due_date": row.due_date.isoformat(),
                "amount": str(row.amount),
                "insurance_sum": str(row.insurance_sum)
                if row.insurance_sum is not None
                else None,
            }
        )
    if not rows or any(
        row["insurance_sum"] is None
        or Decimal(row["insurance_sum"]) <= 0
        or Decimal(row["amount"]) <= 0
        for row in rows
    ):
        raise FlowError("В полисе-образце нужен график со страховой суммой и премией.")
    return {"policy": common, "payments": rows}


def set_template(group, policy, snapshot):
    from .flow_import import prepare_initial

    mapped = prepare_initial(snapshot)["policy"]
    for field, label in (
        ("client", "лизингополучатель"),
        ("insurer", "страховщик"),
        ("insurance_type", "вид страхования"),
        ("branch", "филиал"),
        ("policyholder", "страхователь"),
        ("leasing_manager", "менеджер"),
    ):
        if mapped.get(field) and mapped[field] != getattr(policy, field + "_id"):
            raise FlowError(
                f"Полис-образец отличается от акцепта: {label}. Выберите подходящий полис."
            )
    inn = snapshot["client_inn"].strip()
    if (
        inn.isdigit()
        and len(inn) in (10, 12)
        and inn != (policy.client.client_inn or "").strip()
    ):
        raise FlowError("ИНН лизингополучателя полиса-образца отличается от акцепта.")
    template = unit_template(policy)
    if {p["year_number"] for p in template["payments"]} != {
        o["year"] for o in snapshot["offers"]
    }:
        raise FlowError("Годы графика полиса-образца не совпадают с годами свода.")
    group.update(
        template=template,
        template_policy_number=policy.policy_number,
        template_policy_id=policy.pk,
        version=uuid4().hex,
    )


@transaction.atomic
def edit_plan(snapshot, data, *, remove=False):
    from .flow_import import normalize_dfa

    total = snapshot["source_object_count"]
    if total < 2:
        raise FlowError("Группы ДФА доступны для нескольких объектов.")
    try:
        first, last = int(data["range_start"]), int(data["range_end"])
        if not 1 <= first <= last <= total:
            raise ValueError
    except (KeyError, TypeError, ValueError):
        raise FlowError("Укажите начало и конец диапазона в пределах свода.") from None
    source, _ = FlowPolicySource.objects.select_for_update().get_or_create(
        pk=snapshot["summary_id"], defaults={"total": total, "mode": "separate"}
    )
    if source.total != total and not source.links.exists():
        source.groups, source.total, source.mode = [], total, "separate"
    if source.total != total or source.mode != "separate":
        raise FlowError(
            "Для свода уже выбран другой способ оформления или изменилось число объектов."
        )
    if data.get("plan_version", "") != plan_version(source.groups):
        raise FlowError("Другой менеджер обновил группы ДФА. Проверьте текущий план.")
    group = next(
        (
            g
            for g in source.groups
            if (g["first_slot"], g["last_slot"]) == (first, last)
        ),
        None,
    )
    if remove:
        if not group:
            raise FlowError("Этого диапазона больше нет.")
        source.groups.remove(group)
        if not source.groups and not source.links.exists():
            source.delete()
            return
    else:
        dfa = data.get("group_dfa", "").strip()
        if not normalize_dfa(dfa) or len(dfa) > 100:
            raise FlowError("Введите окончательный номер ДФА длиной до 100 символов.")
        for other in source.groups:
            if (
                other is not group
                and other["first_slot"] <= last
                and first <= other["last_slot"]
            ):
                raise FlowError("Диапазон пересекается с другой группой ДФА.")
        existing = source.links.filter(slot__range=(first, last)).values_list(
            "policy__dfa_number", flat=True
        )
        if any(normalize_dfa(v) != normalize_dfa(dfa) for v in existing):
            raise FlowError(
                "У уже оформленной позиции другой окончательный ДФА. Проверьте диапазон."
            )
        if group is None:
            group = {}
            source.groups.append(group)
        old_template = group.get("template_policy_id")
        keep = (
            old_template
            and normalize_dfa(group["dfa"]) == normalize_dfa(dfa)
            and group["revision"] == snapshot["revision"]
            and not data.get("clear_template")
        )
        if not keep:
            group.clear()
        group.update(
            first_slot=first,
            last_slot=last,
            dfa=dfa,
            revision=snapshot["revision"],
            version=uuid4().hex,
        )
        sample = data.get("template_policy_id")
        if sample:
            if (
                not sample.isascii()
                or not sample.isdigit()
                or len(sample) > 18
                or data.get("confirm_template") != "yes"
            ):
                raise FlowError(
                    "Подтвердите применение условий указанного полиса на одну единицу."
                )
            link = (
                source.links.select_related("policy")
                .filter(policy_id=int(sample), revision=snapshot["revision"])
                .first()
            )
            if not link:
                raise FlowError(
                    "Выберите полис, оформленный по текущей версии акцепта."
                )
            set_template(group, link.policy, snapshot)
        source.groups.sort(key=lambda g: g["first_slot"])
    source.save(update_fields=["groups", "total", "mode"])
