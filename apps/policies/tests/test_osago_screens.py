"""
ОСАГО на экранах сайта (этап 3).

Журнал полисов — общий, с переключателем «ОСАГО»; карточка полиса ОСАГО —
без франшизы и страховой суммы; список платежей — с ОСАГО; карточки
клиента, СК, филиала, менеджера — ОСАГО в списке полисов, но не в
счётчиках и средней премии (решение владельца).
"""

from datetime import date, timedelta
from decimal import Decimal

import pytest
from django.urls import reverse

from apps.insurers.models import InsuranceType, LeasingManager
from apps.policies.models import PaymentSchedule

pytestmark = [pytest.mark.integration, pytest.mark.django_db]


@pytest.fixture
def user_client(client, django_user_model):
    user = django_user_model.objects.create_user("viewer", password="x")
    client.force_login(user)
    return client


@pytest.fixture
def setup(policy_factory, client_factory, insurer_factory, branch_factory):
    today = date.today()
    osago_type = InsuranceType.objects.create(name="ОСАГО (тест)", is_osago=True)
    kasko_type = InsuranceType.objects.create(name="КАСКО (тест)")
    client = client_factory(client_name="ООО Клиент")
    insurer = insurer_factory(insurer_name="СК Тест")
    branch = branch_factory(branch_name="Филиал Тест")
    manager = LeasingManager.objects.create(name="Иванов", branch=branch)
    common = {
        "client": client,
        "insurer": insurer,
        "branch": branch,
        "leasing_manager": manager,
        "start_date": today - timedelta(days=10),
        "end_date": today + timedelta(days=300),
    }
    kasko = policy_factory(
        policy_number="KASKO-777", insurance_type=kasko_type, **common
    )
    PaymentSchedule.objects.create(
        policy=kasko,
        year_number=1,
        installment_number=1,
        due_date=common["start_date"],
        insurance_sum=Decimal("3000000"),
        amount=Decimal("100000"),
        kv_rub=Decimal("10000"),
    )
    osago = policy_factory(
        policy_number="OSAGO-777",
        insurance_type=osago_type,
        franchise=Decimal("0"),
        **common,
    )
    PaymentSchedule.objects.create(
        policy=osago,
        year_number=1,
        installment_number=1,
        due_date=common["start_date"],
        amount=Decimal("10000"),
        kv_rub=Decimal("1000"),
    )
    return {
        "kasko": kasko,
        "osago": osago,
        "client": client,
        "insurer": insurer,
        "branch": branch,
        "manager": manager,
    }


class TestPolicyJournal:
    def test_default_shows_all_policies(self, user_client, setup):
        html = user_client.get(reverse("policies:list")).content.decode()

        assert "KASKO-777" in html
        assert "OSAGO-777" in html
        assert "osago-badge" in html

    def test_exclude_osago(self, user_client, setup):
        response = user_client.get(reverse("policies:list"), {"osago": "exclude"})
        html = response.content.decode()

        assert "KASKO-777" in html
        assert "OSAGO-777" not in html
        assert {"param": "osago", "label": "ОСАГО", "value": "Без ОСАГО"} in (
            response.context["active_filters"]
        )

    def test_only_osago(self, user_client, setup):
        html = user_client.get(
            reverse("policies:list"), {"osago": "only"}
        ).content.decode()

        assert "OSAGO-777" in html
        assert "KASKO-777" not in html


class TestPolicyDetail:
    def test_osago_detail_has_no_franchise_or_insurance_sum(self, user_client, setup):
        response = user_client.get(reverse("policies:detail", args=[setup["osago"].pk]))
        html = response.content.decode()

        assert response.status_code == 200
        assert "Франшиза" not in html
        assert "None" not in html
        assert response.context["rates_by_year"] == []

    def test_kasko_detail_unchanged(self, user_client, setup):
        html = user_client.get(
            reverse("policies:detail", args=[setup["kasko"].pk])
        ).content.decode()

        assert "Франшиза" in html
        assert "3 000 000" in html


class TestPaymentList:
    def test_osago_payment_is_listed_with_badge(self, user_client, setup):
        html = user_client.get(
            reverse("policies:payments"), {"status": "all"}
        ).content.decode()

        assert "OSAGO-777" in html
        assert "osago-badge" in html


class TestCards:
    def _assert_card(self, response, overview_key):
        html = response.content.decode()
        overview = response.context[overview_key]

        assert response.status_code == 200
        # Список — с ОСАГО.
        assert "KASKO-777" in html
        assert "OSAGO-777" in html
        # Счётчики — без ОСАГО, ОСАГО — отдельно.
        assert overview["total_policies"] == 1
        assert overview["active_policies"] == 1
        assert overview["osago_policies"] == 1
        assert "ещё ОСАГО: 1" in html
        return overview

    def test_client_card(self, user_client, setup):
        response = user_client.get(reverse("clients:detail", args=[setup["client"].pk]))
        self._assert_card(response, "client_overview")

    def test_insurer_card(self, user_client, setup):
        response = user_client.get(
            reverse("insurers:detail", args=[setup["insurer"].pk])
        )
        overview = self._assert_card(response, "insurer_overview")
        assert overview["avg_premium"] == Decimal("100000")
        assert response.context["statistics"]["total_policies"] == 1

    def test_branch_card(self, user_client, setup):
        response = user_client.get(
            reverse("insurers:branch_detail", args=[setup["branch"].pk])
        )
        overview = self._assert_card(response, "branch_overview")
        assert overview["avg_premium"] == Decimal("100000")
        assert response.context["statistics"]["total_policies"] == 1

    def test_manager_card(self, user_client, setup):
        response = user_client.get(
            reverse("insurers:manager_detail", args=[setup["manager"].pk])
        )
        self._assert_card(response, "manager_overview")

    def test_no_osago_line_without_osago(self, user_client, setup):
        setup["osago"].payment_schedule.all().delete()
        setup["osago"].delete()

        html = user_client.get(
            reverse("clients:detail", args=[setup["client"].pk])
        ).content.decode()

        assert "ещё ОСАГО" not in html
