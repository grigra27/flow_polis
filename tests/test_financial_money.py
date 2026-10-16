"""
Деньги в финансовой аналитике (apps.analytics.money).

Решение владельца 2026-10-16: «заработано» — по дате акта с СК, как в
ежемесячном отчёте по КВ. Расторгнутые полисы и взносы после закрытия ДФА не
ожидаются; просрочка показывается отдельно и в итог года не входит.
"""

from datetime import date, timedelta
from decimal import Decimal

import pytest
from django.urls import reverse

from apps.analytics import money
from apps.clients.models import Client
from apps.insurers.models import Branch, InsuranceType, Insurer
from apps.policies.models import PaymentSchedule, Policy

pytestmark = [pytest.mark.integration, pytest.mark.django_db]

TODAY = date(2026, 10, 16)


@pytest.fixture
def make_payment(db):
    refs = {
        "client": Client.objects.create(
            client_name="ООО Деньги", client_inn="7700000055"
        ),
        "insurer": Insurer.objects.create(insurer_name="СК Деньги"),
        "branch": Branch.objects.create(branch_name="Филиал Деньги"),
        "type": InsuranceType.objects.create(name="КАСКО (деньги)"),
    }
    counter = {"n": 0}

    def make(
        kv,
        due,
        paid=None,
        act=None,
        policy_active=True,
        dfa_closed_on=None,
    ):
        counter["n"] += 1
        policy = Policy.objects.create(
            policy_number=f"M-{counter['n']}",
            dfa_number=f"ДФА-M-{counter['n']}",
            client=refs["client"],
            insurer=refs["insurer"],
            branch=refs["branch"],
            insurance_type=refs["type"],
            property_description="Имущество",
            start_date=date(2025, 1, 1),
            end_date=date(2028, 12, 31),
            policy_active=policy_active,
            dfa_active=dfa_closed_on is None,
            dfa_deactivation_date=dfa_closed_on,
        )
        return PaymentSchedule.objects.create(
            policy=policy,
            year_number=1,
            installment_number=1,
            due_date=due,
            insurance_sum=Decimal("1000000"),
            amount=Decimal(kv) * 10,
            kv_rub=Decimal(kv),
            paid_date=paid,
            insurer_date=act,
        )

    return make


def outlook():
    return money.build_current_year_outlook(PaymentSchedule.objects.all(), TODAY)


def test_earned_is_by_act_date_not_due_date(make_payment):
    # Срок в 2025-м, акт в марте 2026 → заработано в марте 2026.
    make_payment(
        100, due=date(2025, 12, 10), paid=date(2026, 2, 1), act=date(2026, 3, 5)
    )
    # Срок в феврале 2026, оплачен, акта нет → не заработано, а «ждёт акта».
    make_payment(40, due=date(2026, 2, 10), paid=date(2026, 2, 12))
    # Акт в прошлом году — не в этом году.
    make_payment(7, due=date(2025, 6, 1), paid=date(2025, 6, 2), act=date(2025, 7, 1))

    result = outlook()

    assert result["earned_commission"] == Decimal("100")
    assert result["monthly_breakdown"][2]["earned_commission"] == Decimal("100")
    assert result["awaiting_act_commission"] == Decimal("40")
    assert result["awaiting_act_count"] == 1


def test_scheduled_skips_cancelled_payments(make_payment):
    make_payment(10, due=date(2026, 11, 5))
    make_payment(20, due=date(2026, 12, 5))
    make_payment(500, due=date(2026, 11, 5), policy_active=False)  # расторгнут
    make_payment(
        300, due=date(2026, 11, 5), dfa_closed_on=date(2026, 9, 1)
    )  # после ДФА
    make_payment(4, due=date(2027, 1, 5))  # следующий год

    result = outlook()

    assert result["scheduled_commission"] == Decimal("30")
    assert result["scheduled_count"] == 2
    assert result["monthly_breakdown"][10]["scheduled_commission"] == Decimal("10")


def test_payment_due_before_dfa_closure_is_still_expected(make_payment):
    make_payment(15, due=date(2026, 11, 1), dfa_closed_on=date(2026, 12, 1))

    assert outlook()["scheduled_commission"] == Decimal("15")


def test_overdue_is_separate_and_not_in_total(make_payment):
    make_payment(
        100, due=date(2026, 1, 10), paid=date(2026, 1, 11), act=date(2026, 2, 1)
    )
    make_payment(60, due=date(2026, 8, 1))  # просрочен
    make_payment(
        900, due=date(2026, 8, 1), policy_active=False
    )  # отменён, не просрочка
    make_payment(25, due=date(2026, 11, 1))

    result = outlook()

    assert result["overdue_commission"] == Decimal("60")
    assert result["overdue_count"] == 1
    assert result["projected_full_year_commission"] == Decimal("125")


def test_projected_year_is_earned_plus_awaiting_plus_scheduled(make_payment):
    make_payment(100, due=date(2026, 3, 1), paid=date(2026, 3, 2), act=date(2026, 4, 1))
    make_payment(30, due=date(2026, 9, 1), paid=date(2026, 9, 2))
    make_payment(20, due=date(2026, 12, 1))

    result = outlook()

    assert result["projected_full_year_commission"] == Decimal("150")
    assert result["projected_full_year_premium"] == Decimal("1500")


def test_monthly_forecast_skips_cancelled_and_keeps_paid(make_payment):
    make_payment(10, due=date(2026, 10, 1), paid=date(2026, 10, 2))
    make_payment(20, due=date(2026, 10, 20))
    make_payment(700, due=date(2026, 10, 20), policy_active=False)
    make_payment(5, due=date(2028, 3, 1))

    forecast = money.build_monthly_forecast(PaymentSchedule.objects.all(), TODAY)

    assert forecast[0]["month"] == date(2026, 10, 1)
    assert forecast[0]["forecasted_commission"] == Decimal("30")
    assert forecast[-1]["month"] == date(2028, 3, 1)
    assert sum(m["forecasted_commission"] for m in forecast) == Decimal("35")


def test_payment_status_overdue_skips_cancelled(make_payment):
    make_payment(10, due=date(2026, 8, 1))
    make_payment(10, due=date(2026, 8, 1), policy_active=False)
    make_payment(10, due=date(2026, 11, 1))

    status = money.build_payment_status(PaymentSchedule.objects.all(), TODAY)

    assert status["overdue_payments"] == 1
    assert status["pending_payments"] == 1
    assert status["total_payments"] == 3


def test_year_to_date_totals_same_period(make_payment):
    make_payment(
        10, due=date(2025, 3, 1), paid=date(2025, 3, 1), act=date(2025, 10, 16)
    )
    make_payment(
        99, due=date(2025, 3, 1), paid=date(2025, 3, 1), act=date(2025, 10, 17)
    )

    assert money.year_to_date_totals(PaymentSchedule.objects.all(), TODAY, year=2025)[
        "commission"
    ] == Decimal("10")


def test_financial_page_renders_bridge(client, django_user_model, make_payment):
    make_payment(100, due=date.today(), paid=date.today(), act=date.today())
    client.force_login(django_user_model.objects.create_superuser("r", "r@r.ru", "x"))

    response = client.get(reverse("analytics:financial_analytics"))

    assert response.status_code == 200
    html = response.content.decode()
    assert "Заработано с начала года" in html
    assert "Ждёт акта" in html
    assert "Просрочено, под риском" in html


def test_financial_export_works(client, django_user_model, make_payment):
    make_payment(100, due=date.today(), paid=date.today(), act=date.today())
    client.force_login(django_user_model.objects.create_superuser("r", "r@r.ru", "x"))

    response = client.get(reverse("analytics:financial_analytics"), {"export": "excel"})

    assert response.status_code == 200
    assert "spreadsheet" in response["Content-Type"]


def test_time_series_shared_axis_fact_by_act_and_plan(make_payment):
    from apps.analytics.services import AnalyticsService
    from django.core.cache import cache

    today = date.today()
    month_start = today.replace(day=1)
    prev_month = (month_start - timedelta(days=1)).replace(day=1)
    # Акт в текущем месяце по взносу со сроком в прошлом месяце.
    make_payment(100, due=prev_month, paid=prev_month, act=today)
    make_payment(40, due=prev_month)  # план прошлого месяца, не оплачен
    make_payment(999, due=prev_month, policy_active=False)  # отменён — не в плане

    cache.clear()
    data = AnalyticsService().get_time_series_analytics()

    labels = [p["label"] for p in data["commission_revenue_dynamics"]]
    assert labels == [p["label"] for p in data["policy_count_dynamics"]]
    assert labels == [p["label"] for p in data["commission_plan_dynamics"]]
    fact = {p["label"]: p["value"] for p in data["commission_revenue_dynamics"]}
    plan = {p["label"]: p["value"] for p in data["commission_plan_dynamics"]}
    assert fact[today.strftime("%Y-%m")] == Decimal("100")
    assert fact[prev_month.strftime("%Y-%m")] == Decimal("0")
    assert plan[prev_month.strftime("%Y-%m")] == Decimal("140")


def test_time_series_page_renders_russian_months(
    client, django_user_model, make_payment
):
    make_payment(100, due=date.today(), paid=date.today(), act=date.today())
    client.force_login(django_user_model.objects.create_superuser("r", "r@r.ru", "x"))

    response = client.get(reverse("analytics:time_series_analytics"))

    assert response.status_code == 200
    html = response.content.decode()
    assert "January" not in html
    assert "КВ по графику" in html
