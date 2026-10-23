"""
Аналитика 2.0, этап 4: «Страховщики», «Каналы», «Клиенты», «Качество
данных», «ОСАГО» (docs/analytics-2.0-plan.md, §4 E–I).
"""

from datetime import date
from decimal import Decimal

import pytest
from django.http import QueryDict
from django.urls import reverse

from apps.analytics import drilldown
from apps.analytics.filters import AnalyticsParams
from apps.analytics.sections import channels, clients, data_quality, insurers, osago
from apps.clients.models import Client
from apps.insurers.models import Branch, InsuranceType, Insurer, LeasingManager
from apps.policies.models import PaymentSchedule, Policy

pytestmark = [pytest.mark.integration, pytest.mark.django_db]

TODAY = date(2026, 10, 16)


def params(query=""):
    return AnalyticsParams.from_query(QueryDict(query), today=TODAY)


@pytest.fixture
def refs(db):
    branch = Branch.objects.create(branch_name="Казань")
    return {
        "c1": Client.objects.create(client_name="ООО Большой", client_inn="7700000101"),
        "c2": Client.objects.create(client_name="ООО Малый", client_inn="7700000102"),
        "a": Insurer.objects.create(insurer_name="СК А"),
        "b": Insurer.objects.create(insurer_name="СК Б"),
        "branch": branch,
        "kasko": InsuranceType.objects.create(name="КАСКО (4)"),
        "osago": InsuranceType.objects.create(name="ОСАГО (4)", is_osago=True),
        "m1": LeasingManager.objects.create(name="Гаврилова", branch=branch),
        "m2": LeasingManager.objects.create(name="Шишкин", branch=branch),
    }


@pytest.fixture
def make(refs):
    counter = {"n": 0}

    def make_policy(
        start,
        payments,
        end=None,
        client="c1",
        insurer="a",
        kind="kasko",
        manager="m1",
        dfa=None,
        dfa_active=True,
        dfa_closed_on=None,
        policy_active=True,
        termination=None,
    ):
        """payments: [(amount, kv, due, paid, act, insurance_sum)]."""
        counter["n"] += 1
        policy = Policy.objects.create(
            policy_number=f"S4-{counter['n']}",
            dfa_number=dfa or f"D4-{counter['n']}",
            client=refs[client],
            insurer=refs[insurer],
            branch=refs["branch"],
            insurance_type=refs[kind],
            property_description="Техника",
            start_date=start,
            end_date=end or date(start.year + 1, start.month, start.day),
            leasing_manager=refs[manager] if manager else None,
            dfa_active=dfa_active,
            dfa_deactivation_date=dfa_closed_on,
            policy_active=policy_active,
            termination_date=termination,
        )
        for index, (amount, kv, due, paid, act, ins_sum) in enumerate(payments, 1):
            PaymentSchedule.objects.create(
                policy=policy,
                year_number=1,
                installment_number=index,
                due_date=due,
                insurance_sum=ins_sum,
                amount=Decimal(amount),
                kv_rub=Decimal(kv),
                paid_date=paid,
                insurer_date=act,
            )
        return policy

    return make_policy


M = Decimal("1000000")


def test_insurers_table(make):
    # СК А: 2 полиса, КВ 25%; акты через 10 и 20 дней; тарифы 2% и 4%.
    make(
        date(2026, 2, 1),
        [(20000, 5000, date(2026, 2, 1), date(2026, 2, 1), date(2026, 2, 11), M)],
    )
    make(
        date(2026, 3, 1),
        [(40000, 10000, date(2026, 3, 1), date(2026, 3, 1), date(2026, 3, 21), M)],
    )
    # СК Б: КВ 10%, ждёт акта 120 дней.
    make(
        date(2026, 6, 1),
        [(30000, 3000, date(2026, 6, 1), date(2026, 6, 18), None, M)],
        insurer="b",
    )
    data = insurers.build(params())
    rows = {r["name"]: r for r in data["rows"]}
    a, b = rows["СК А"], rows["СК Б"]
    assert data["types"] == ["КАСКО (4)"]
    assert a["commission"] == 15000 and a["kv_percent"] == 25
    assert a["share"] == Decimal(15000) / Decimal(18000) * 100
    assert a["act_lag"] == 15
    assert a["tariff_by_type"] == [3]  # медиана 2% и 4%
    assert b["awaiting"] == 3000 and b["awaiting_90"] == 3000
    assert a["nb_share"] == pytest.approx(Decimal(200) / 3)
    assert a["nb_share_change"] is None  # прошлый год — неполная история


def test_channels_change_drop_and_renewal(make):
    q = "from=2026-07-01&to=2026-09-30"
    # Гаврилова: 4 полиса год назад, 1 сейчас — падение.
    for day in (1, 5, 10, 15):
        make(date(2025, 7, day), [(4000, 1000, date(2025, 7, day), None, None, M)])
    make(date(2026, 8, 1), [(4000, 1000, date(2026, 8, 1), None, None, M)])
    # Шишкин: 0 → 2.
    for day in (3, 4):
        make(
            date(2026, 9, day),
            [(4000, 1000, date(2026, 9, day), None, None, M)],
            manager="m2",
        )
    data = channels.build(params(q), QueryDict("by=manager"))
    rows = {r["name"]: r for r in data["rows"]}
    g, s = rows["Гаврилова"], rows["Шишкин"]
    assert data["history_ok"]
    assert (g["nb_count"], g["prev_count"], g["change"]) == (1, 4, -75)
    assert g["dropped"]
    assert (s["nb_count"], s["prev_count"], s["change"], s["dropped"]) == (
        2,
        0,
        None,
        False,
    )
    # Полисы Гавриловой 2025 года закончились в июле 2026 без продления.
    assert (g["renewal_due"], g["renewal_rate"]) == (4, 0)


def test_clients_concentration(make):
    make(date(2026, 2, 1), [(40000, 9000, date(2026, 2, 1), None, None, M)])
    make(
        date(2026, 3, 1),
        [(4000, 1000, date(2026, 3, 1), None, None, M)],
        client="c2",
    )
    make(date(2025, 1, 1), [(4000, 1, date(2025, 1, 1), None, None, M)], client="c2")
    data = clients.build(params())
    assert data["clients_total"] == 2
    assert data["top10_share"] == 100
    rows = {r["name"]: r for r in data["rows"]}
    assert rows["ООО Большой"]["share"] == 90
    assert rows["ООО Большой"]["is_new"]
    assert not rows["ООО Малый"]["is_new"]
    assert data["pareto"]["values"] == [90.0, 100.0]
    client_id = rows["ООО Малый"]["id"]
    assert (
        drilldown.resolve("client_policies", params(), {"client": client_id}).count()
        == 2
    )


def test_data_quality_checks(make, refs):
    make(date(2026, 1, 10), [(4000, 0, date(2026, 1, 10), None, None, M)])  # КВ 0
    make(  # ДФА закрыт без даты
        date(2026, 1, 11),
        [(4000, 1000, date(2026, 1, 11), None, None, M)],
        dfa_active=False,
    )
    make(  # неактивен без даты расторжения
        date(2026, 1, 12),
        [(4000, 1000, date(2026, 1, 12), None, None, M)],
        policy_active=False,
    )
    no_sum = make(  # нет страховой суммы, оплачен на 200 дней раньше, без менеджера
        date(2026, 1, 13),
        [(4000, 1000, date(2026, 8, 1), date(2026, 1, 13), None, M)],
        manager=None,
    )
    # Модель требует сумму при сохранении — ошибку данных создаём в обход.
    PaymentSchedule.objects.filter(policy=no_sum).update(insurance_sum=None)
    make(  # закончился 3 месяца назад, ДФА открыт, нового полиса нет
        date(2025, 7, 15),
        [(4000, 1000, date(2025, 7, 15), date(2025, 7, 15), date(2025, 8, 1), M)],
        end=date(2026, 7, 14),
    )
    broken = make(date(2026, 1, 14), [(4000, 1000, date(2026, 1, 14), None, None, M)])
    PaymentSchedule.objects.filter(policy=broken).update(installment_number=2)

    data = data_quality.build(params())
    counts = {r["key"]: r["count"] for r in data["rows"]}
    assert counts == {
        "dq_stale_open_dfa": 1,
        "dq_kv_zero": 1,
        "dq_dfa_closed_without_date": 1,
        "dq_inactive_without_termination": 1,
        "dq_missing_first_installment": 1,
        "dq_no_insurance_sum": 1,
        "dq_paid_far_early": 1,
        "dq_no_manager": 1,
    }
    assert data_quality.money_problem_count(params()) == 4
    for key in counts:
        assert drilldown.resolve(key, params()).count() == 1, key


def test_osago_tab_ignores_toggle(make):
    make(
        date(2026, 4, 1),
        [(10000, 1000, date(2026, 4, 1), date(2026, 4, 1), None, None)],
        kind="osago",
    )
    make(date(2026, 4, 2), [(40000, 10000, date(2026, 4, 2), None, None, M)])
    for query in ("", "osago=1"):
        totals = osago.build(params(query))["totals"]
        assert (totals["policies"], totals["kv"], totals["paid"]) == (1, 1000, 1)
        assert totals["kv_percent"] == 10


@pytest.mark.parametrize(
    "key",
    [
        "dq_stale_open_dfa",
        "dq_kv_zero",
        "osago_policies",
        "osago_payments",
        "client_policies",
    ],
)
def test_stage4_lists_render(client, django_user_model, make, key):
    make(date(2026, 4, 2), [(40000, 0, date(2026, 4, 2), None, None, M)])
    client.force_login(django_user_model.objects.create_superuser("r", "r@r.ru", "x"))
    url = reverse("analytics:list", args=[key])
    assert client.get(url + "?client=1").status_code == 200
    assert client.get(url + "?format=xlsx").status_code == 200
