"""
«Подробный отчёт по имуществу» для лизинговой компании и общий расчёт
страховой стоимости (сумма текущего страхового года).
"""

from datetime import date
from decimal import Decimal

import pytest
from django.urls import reverse

from apps.clients.models import Client
from apps.insurers.models import Branch, InsuranceType, Insurer, LeasingManager
from apps.policies.models import PaymentSchedule, Policy
from apps.reports.services.insured_value import current_insured_sums, insured_portfolio
from apps.reports.services.property_report import build_property_report
from apps.reports.services.property_snapshot import build_property_snapshot
from apps.reports.services.property_text import (
    CONDITION_NEW,
    CONDITION_UNKNOWN,
    CONDITION_USED,
    NOT_RECOGNIZED,
    detect_brand,
    detect_condition,
)

AS_OF = date(2026, 10, 19)
M = Decimal("1000000")


@pytest.mark.unit
@pytest.mark.parametrize(
    "text, brand, condition",
    [
        ("Chery Tiggo4 PRO (2023г.в., vin 9812)", "Chery", CONDITION_UNKNOWN),
        ("ВИС LADA GRANTA фургон_8899", "LADA", CONDITION_UNKNOWN),
        ("б/у  Погрузчик MERLO ROTO  45.21 (2012 г.в.,б/у)", "Merlo", CONDITION_USED),
        ("экскаватор LIUGONG CLG933E (нов.) vin3238", "LiuGong", CONDITION_NEW),
        ("спец., автомобиль - самосвал КАМАЗ 45143-5H( нов.)", "КАМАЗ", CONDITION_NEW),
        ("Автомобиль EXEED RX, нов, vin9009", "Exeed", CONDITION_NEW),
        ("Новый автомобиль ГАЗель NEXT", "ГАЗ", CONDITION_NEW),
        ("Автомобиль-самосвал МАЗ-6501", "МАЗ", CONDITION_UNKNOWN),
        ("Lada Niva Travel, новая", "LADA", CONDITION_NEW),
        ("Станок токарный", NOT_RECOGNIZED, CONDITION_UNKNOWN),
        (
            "Автомобиль Hyundai Solaris",
            "Hyundai",
            CONDITION_UNKNOWN,
        ),  # первая по тексту
    ],
)
def test_brand_and_condition(text, brand, condition):
    assert detect_brand(text) == brand
    assert detect_condition(text) == condition


@pytest.fixture
def refs(db):
    branch = Branch.objects.create(branch_name="Псков")
    return {
        "client": Client.objects.create(
            client_name="ООО Лизинг", client_inn="7700000301"
        ),
        "client2": Client.objects.create(
            client_name="ООО Второй", client_inn="7700000302"
        ),
        "a": Insurer.objects.create(insurer_name="СК А"),
        "b": Insurer.objects.create(insurer_name="СК Б"),
        "branch": branch,
        "branch2": Branch.objects.create(branch_name="Казань"),
        "kasko": InsuranceType.objects.create(name="КАСКО (и)"),
        "spec": InsuranceType.objects.create(name="Спецтехника (и)"),
        "osago": InsuranceType.objects.create(name="ОСАГО (и)", is_osago=True),
        "manager": LeasingManager.objects.create(name="Бурак", branch=branch),
    }


@pytest.fixture
def make(refs):
    counter = {"n": 0}

    def make_policy(
        sums,
        start=date(2024, 11, 1),
        years=3,
        insurer="a",
        kind="kasko",
        branch="branch",
        client="client",
        description="Автомобиль LADA Vesta (нов.)",
        property_year=2024,
        franchise=0,
        dfa_active=True,
        broker=True,
    ):
        """sums: страховая сумма по годам; премия у каждого взноса 1000."""
        counter["n"] += 1
        policy = Policy.objects.create(
            policy_number=f"IR-{counter['n']}",
            dfa_number=f"D-IR-{counter['n']}",
            client=refs[client],
            insurer=refs[insurer],
            branch=refs[branch],
            insurance_type=refs[kind],
            property_description=description,
            property_year=property_year,
            franchise=Decimal(franchise),
            start_date=start,
            end_date=date(start.year + years, start.month, start.day),
            dfa_active=dfa_active,
            broker_participation=broker,
            leasing_manager=refs["manager"],
        )
        for year, value in enumerate(sums, 1):
            PaymentSchedule.objects.create(
                policy=policy,
                year_number=year,
                installment_number=1,
                due_date=date(start.year + year - 1, start.month, start.day),
                insurance_sum=None if kind == "osago" else value,
                amount=Decimal("1000"),
                kv_rub=Decimal("100"),
            )
        return policy

    return make_policy


@pytest.mark.django_db
def test_current_year_sum_not_max(make):
    p = make([10 * M, 8 * M, 6 * M])  # год 2 начался 01.11.2025
    assert current_insured_sums([p.id], AS_OF) == {p.id: 8 * M}
    assert current_insured_sums([p.id], date(2025, 6, 1)) == {p.id: 10 * M}


@pytest.mark.django_db
def test_falls_back_to_max_without_current_installment(make):
    p = make([10 * M, 8 * M])
    PaymentSchedule.objects.filter(policy=p).update(installment_number=2)
    assert current_insured_sums([p.id], AS_OF) == {p.id: 10 * M}


@pytest.mark.django_db
def test_portfolio_scope(make):
    make([5 * M])  # в силе
    make([5 * M], broker=False)  # без участия брокера — входит
    make([5 * M], dfa_active=False)  # ДФА закрыт — не входит
    make([5 * M], start=date(2022, 1, 1), years=1)  # закончился — не входит
    make(
        [Decimal("0")], kind="osago", years=1, start=date(2026, 3, 1)
    )  # ОСАГО — не входит
    assert len(insured_portfolio(AS_OF)) == 2


@pytest.mark.django_db
def test_snapshot_uses_current_year_sum(make):
    make([10 * M, 8 * M, 6 * M])
    snapshot = build_property_snapshot(as_of=AS_OF)
    assert snapshot["total_insurance_sum"] == 8 * M


@pytest.fixture
def portfolio(make):
    make(
        [10 * M, 9 * M, 8 * M],
        description="тягач седельный SANY S525 (нов.)",
        kind="spec",
        property_year=2025,
    )
    make(
        [4 * M, 3 * M, 2 * M],
        insurer="b",
        description="б/у Автомобиль AUDI Q7",
        property_year=2014,
        franchise=50000,
    )
    make(
        [2 * M, 2 * M, 2 * M],
        branch="branch2",
        client="client2",
        description="Станок токарный",
        property_year=None,
    )
    make(
        [60 * M],
        start=date(2026, 1, 15),
        years=1,
        description="экскаватор LIUGONG (нов.)",
        kind="spec",
    )


@pytest.mark.django_db
def test_report_numbers(portfolio):
    r = build_property_report(as_of=AS_OF)
    # 9 + 3 + 2 + 60 = 74 млн (текущий год, а не максимум 76)
    assert r["totals"]["sum"] == 74 * M
    assert r["totals"]["count"] == 4
    assert r["totals"]["lessees"] == 2

    insurers = {row["name"]: row for row in r["insurers"]}
    assert insurers["СК А"]["sum"] == 71 * M
    assert sum(row["share"] for row in r["insurers"]) == pytest.approx(100)
    # Полис на 60 млн заканчивается 15.01.2027 — в пределах 90 дней.
    assert insurers["СК А"]["ending_soon"] == 60 * M
    assert r["concentration"]["insurers"] == 2

    sizes = {row["name"]: row["count"] for row in r["by_size"]}
    assert sizes == {"1–3 млн": 1, "3–5 млн": 1, "5–10 млн": 1, "50 млн и больше": 1}
    ages = {row["name"]: row["count"] for row in r["by_age"]}
    assert ages["до 1 года"] == 1 and ages["старше 10 лет"] == 1
    assert ages["год выпуска не указан"] == 1
    conditions = {row["name"]: row["count"] for row in r["by_condition"]}
    assert conditions == {CONDITION_NEW: 2, CONDITION_USED: 1, CONDITION_UNKNOWN: 1}
    brands = [row["name"] for row in r["by_brand"]]
    assert brands[-1] == NOT_RECOGNIZED
    assert set(brands[:-1]) == {"LiuGong", "SANY", "Audi"}
    franchise = {row["name"]: row["count"] for row in r["by_franchise"]}
    assert franchise == {"без франшизы": 3, "30–100 тыс.": 1}

    matrix = {row["name"]: row for row in r["branch_by_insurer"]["rows"]}
    assert matrix["Псков"]["total"] == 72 * M
    assert r["top_objects"][0]["sum"] == 60 * M
    # Кварталы до июля 2025 не сравниваются — на 19.10.2026 их нет.
    assert r["insurer_dynamics"]["dates"][-1] == AS_OF


@pytest.mark.django_db
def test_branch_filter(portfolio, refs):
    r = build_property_report(as_of=AS_OF, branch_ids=[refs["branch2"].id])
    assert r["totals"]["sum"] == 2 * M


@pytest.mark.integration
@pytest.mark.django_db
def test_report_page_has_no_commission_or_premium(client, django_user_model, portfolio):
    client.force_login(django_user_model.objects.create_user("u", "u@u.ru", "x"))
    url = reverse("reports:property_report")
    response = client.get(url + "?as_of=2026-10-19")
    assert response.status_code == 200
    html = response.content.decode()
    for word in ("КВ", "комисси", "преми", "тариф"):
        assert word not in html.split('<div class="pr">', 1)[1], word

    export = client.get(url + "?as_of=2026-10-19&format=xlsx")
    assert export.status_code == 200
    assert export["Content-Type"].startswith("application/vnd.openxmlformats")


@pytest.mark.integration
@pytest.mark.django_db
def test_exports_page_links_both_reports(client, django_user_model):
    client.force_login(django_user_model.objects.create_user("u", "u@u.ru", "x"))
    html = client.get(reverse("reports:index")).content.decode()
    assert reverse("reports:property_snapshot_report") in html
    assert reverse("reports:property_report") in html
