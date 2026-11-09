"""Сопоставление акцепта ЗС и регистрация результата в портфеле."""
from decimal import Decimal, ROUND_HALF_UP
import re

from django.db import transaction
from django.db.models.functions import Trim
from apps.clients.models import Client
from apps.insurers.models import (
    Branch,
    CommissionRate,
    Insurer,
    InsuranceType,
    LeasingManager,
)
from apps.policies.flow_permissions import require_access
from apps.policies.models import FlowPolicyLink, FlowPolicySource, Policy
from .flow_client import FlowError


TYPE_NAMES = {
    "КАСКО": "КАСКО",
    "страхование имущества": "Имущество",
    "страхование спецтехники": "Спецтехника",
}
DASHES = "-‐‑‒–—−"
CENT = Decimal("0.01")


def normalize_dfa(value):
    text = " ".join((value or "").split()).upper()
    if not text or "ПРЕДВАР" in text:
        return ""
    return re.sub(rf"\s*[{re.escape(DASHES)}]\s*", "-", text)


def candidate_policies(dfa_number):
    qs = Policy.objects.select_related(
        "client", "insurer", "branch", "insurance_type"
    ).order_by("-start_date", "-pk")
    normalized = normalize_dfa(dfa_number)
    if not normalized:
        return qs.none()
    # Only presentation characters are interchangeable. Keep suffixes and leading zeroes.
    pattern = "".join(
        rf"\s*[{re.escape(DASHES)}]\s*"
        if char == "-"
        else r"\s+"
        if char == " "
        else re.escape(char)
        for char in normalized
    )
    return qs.filter(dfa_number__iregex=rf"^\s*{pattern}\s*$")


def links_for(summary_id):
    return (
        FlowPolicyLink.objects.filter(source_id=summary_id)
        .select_related("policy", "source")
        .order_by("slot")
    )


def _one(qs):
    items = list(qs[:2])
    return items[0] if len(items) == 1 else None


def _manager(name, branch):
    words = name.split()
    if not words or not branch:
        return None
    managers = LeasingManager.objects.filter(branch=branch)
    key = " ".join(words).casefold()
    exact = [
        m
        for m in managers
        if key in (m.name.casefold(), " ".join(m.full_name.split()).casefold())
    ]
    if exact:
        return exact[0] if len(exact) == 1 else None
    by_surname = [m for m in managers if m.name.casefold() == words[0].casefold()]
    return by_surname[0] if len(by_surname) == 1 else None


def _schedule(offers, rate, separate):
    rows = []
    for offer in sorted(offers, key=lambda row: row["year"]):
        installments = offer["installments"]
        annual = Decimal(offer["premium"])
        cents, remainder = divmod(int(annual * 100), installments)
        for index in range(1, installments + 1):
            row = {"year_number": offer["year"], "installment_number": index}
            if not separate:
                amount = (cents + int(index > installments - remainder)) * CENT
                row["insurance_sum"] = offer["insurance_sum"]
                if amount:
                    row["amount"] = amount
                if rate and amount:
                    row["kv_rub"] = (amount * rate.kv_percent / 100).quantize(
                        CENT, rounding=ROUND_HALF_UP
                    )
            rows.append(row)
    return rows


def prepare_initial(snapshot, *, slot=0, insurer_id=None, insurance_type_id=None):
    warns = []
    p = {"property_description": snapshot["property_description"]}
    if normalize_dfa(snapshot["dfa_number"]):
        p["dfa_number"] = snapshot["dfa_number"].strip()
    else:
        warns.append("Уточните окончательный номер ДФА.")
    year = snapshot.get("property_year")
    if isinstance(year, int) and 1900 <= year <= 2100:
        p["property_year"] = year
    client = None
    inn = snapshot["client_inn"].strip()
    if re.fullmatch(r"(?:\d{10}|\d{12})", inn):
        client = _one(
            Client.objects.annotate(normal_inn=Trim("client_inn")).filter(
                normal_inn=inn
            )
        )
    if client:
        p["client"] = client.pk
        if snapshot["insured_party"] == "lessee":
            p["policyholder"] = client.pk
    else:
        warns.append("Выберите или добавьте лизингополучателя.")
    if snapshot["insured_party"] != "lessee":
        warns.append("Уточните страхователя по полису.")
    branch = _one(Branch.objects.filter(branch_name__iexact=snapshot["branch"].strip()))
    mgr = _manager(snapshot["manager_name"], branch)
    insurer_name = snapshot["selected_company"].strip()
    insurer = (
        Insurer.objects.filter(pk=insurer_id).first()
        if insurer_id
        else _one(Insurer.objects.filter(insurer_name__iexact=insurer_name))
        if insurer_name.casefold() != "другое"
        else None
    )
    insurance_type = (
        InsuranceType.objects.filter(pk=insurance_type_id, is_osago=False).first()
        if insurance_type_id
        else InsuranceType.objects.filter(
            name=TYPE_NAMES.get(snapshot["insurance_type"]), is_osago=False
        ).first()
    )
    for field, record, name in (
        ("branch", branch, "филиал"),
        ("insurer", insurer, "страховщика"),
        ("insurance_type", insurance_type, "вид страхования"),
        ("leasing_manager", mgr, "менеджера лизинговой компании"),
    ):
        if record:
            p[field] = record.pk
        else:
            warns.append(f"Уточните {name}.")
    rate = (
        CommissionRate.objects.filter(
            insurer=insurer, insurance_type=insurance_type
        ).first()
        if insurer and insurance_type
        else None
    )
    if not rate:
        warns.append(
            "Проверьте комиссию: для выбранного сочетания ставка не определена."
        )
    franchises = {Decimal(row["franchise"]) for row in snapshot["offers"]}
    if len(franchises) == 1:
        p["franchise"] = franchises.pop()
    elif len(franchises) > 1:
        p[
            "franchise"
        ] = None  # Один договор хранит одно значение; выбор остаётся сотруднику.
        warns.append("Франшиза меняется по годам. Уточните значение для полиса.")
    separate = slot > 0 and snapshot["source_object_count"] > 1
    if separate:
        warns.append("Введите страховые суммы и премии этой единицы по документу.")
    return {
        "policy": p,
        "payments": _schedule(snapshot["offers"], rate, separate),
        "warnings": warns,
        "variant": snapshot["variant"],
    }


@transaction.atomic
def save_linked_policy(
    snapshot, slot, user, *, create_policy=None, existing_policy=None, dfa_number=None
):
    """Callback writes the policy AND its schedule inside the same transaction.

    get_or_create handles simultaneous first use of a summary. On PostgreSQL
    the locked source row serializes registration of every one of its units.
    """
    if (create_policy is None) == (existing_policy is None):
        raise ValueError("Укажите одно действие с полисом.")
    require_access(
        user, create=create_policy is not None, link=existing_policy is not None
    )
    total = snapshot["source_object_count"]
    if type(slot) is not int or not 0 <= slot <= total or (total == 1 and slot != 0):
        raise FlowError("Некорректная позиция объекта.")
    mode = "separate" if slot else "common"
    source, _ = FlowPolicySource.objects.select_for_update().get_or_create(
        pk=snapshot["summary_id"], defaults={"total": total, "mode": mode}
    )
    if source.mode != mode or source.total != total:
        raise FlowError(
            "Количество объектов или способ оформления изменились. Откройте свод повторно."
        )
    link = links_for(source.pk).filter(slot=slot).first()
    if link:
        return link.policy, False
    if existing_policy is None:
        if snapshot["variant"] not in (1, 2) or not snapshot["offers"]:
            raise FlowError("Сначала выберите и сохраните вариант предложения в ЗС.")
        policy = create_policy()
    else:
        number = snapshot["dfa_number"] if dfa_number is None else dfa_number
        policy = (
            Policy.objects.select_for_update().filter(pk=existing_policy.pk).first()
        )
        if (
            not policy
            or not normalize_dfa(number)
            or normalize_dfa(number) != normalize_dfa(policy.dfa_number)
        ):
            raise FlowError("ДФА выбранного полиса изменился. Повторите поиск.")
        if source.links.filter(policy=policy).exists():
            raise FlowError("Этот полис уже связан с другой позицией свода.")
    FlowPolicyLink.objects.create(
        source=source,
        slot=slot,
        policy=policy,
        revision=snapshot["revision"],
        created_by=user,
        created_from_summary=existing_policy is None,
    )
    return policy, True
