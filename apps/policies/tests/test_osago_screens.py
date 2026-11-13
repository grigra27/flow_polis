"""
ОСАГО на экранах сайта (этап 3).

Журнал полисов — общий, с переключателем «ОСАГО»; карточка полиса ОСАГО —
без франшизы и страховой суммы; список платежей — с ОСАГО; карточки
клиента, СК, филиала, менеджера — ОСАГО в списке полисов, но не в
счётчиках и средней премии (решение владельца).
"""

from datetime import date, timedelta
from decimal import Decimal
from html.parser import HTMLParser
from urllib.parse import parse_qs, urlsplit

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.insurers.models import InsuranceType, LeasingManager
from apps.policies.models import PaymentSchedule

pytestmark = [pytest.mark.integration, pytest.mark.django_db]


class PaymentPage(HTMLParser):
    """Ссылки и варианты ОСАГО на отрисованной странице графика."""

    def __init__(self, response):
        super().__init__()
        self.links = {}
        self.options = []
        self.in_osago = False
        self.option = None
        self.feed(response.content.decode())

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "a" and "href" in attrs:
            for name in attrs.get("class", "").split():
                self.links.setdefault(name, []).append(attrs["href"])
        elif tag == "select" and attrs.get("name") == "osago":
            self.in_osago = True
        elif tag == "option" and self.in_osago:
            self.option = {
                "value": attrs.get("value", ""),
                "selected": "selected" in attrs,
                "label": "",
            }

    def handle_data(self, data):
        if self.option is not None:
            self.option["label"] += data

    def handle_endtag(self, tag):
        if tag == "option" and self.option is not None:
            self.option["label"] = self.option["label"].strip()
            self.options.append(self.option)
            self.option = None
        elif tag == "select" and self.in_osago:
            self.in_osago = False


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

    @pytest.mark.parametrize(
        ("mode", "expected", "selected"),
        [
            (None, {"kasko", "osago"}, ""),
            ("", {"kasko", "osago"}, ""),
            ("exclude", {"kasko"}, "exclude"),
            ("only", {"osago"}, "only"),
            ("invalid", {"kasko", "osago"}, ""),
        ],
    )
    def test_filter_modes(self, user_client, setup, mode, expected, selected):
        params = {"status": "all"}
        if mode is not None:
            params["osago"] = mode
        response = user_client.get(reverse("policies:payments"), params)

        assert response.status_code == 200
        assert {payment.policy_id for payment in response.context["payments"]} == {
            setup[key].pk for key in expected
        }
        assert response.context["page_obj"].paginator.count == len(expected)

        options = PaymentPage(response).options
        assert [(option["value"], option["label"]) for option in options] == [
            ("", "Все полисы"),
            ("exclude", "Без ОСАГО"),
            ("only", "Только ОСАГО"),
        ]
        selected_option = next(
            (option for option in options if option["selected"]), options[0]
        )
        assert selected_option["value"] == selected

    def test_osago_combines_with_existing_payment_filters(
        self, user_client, setup, policy_factory, insurer_factory, branch_factory
    ):
        today = timezone.now().date()
        due = today + timedelta(days=5)
        PaymentSchedule.objects.filter(
            policy__in=[setup["osago"], setup["kasko"]]
        ).update(due_date=due)
        other_insurer = insurer_factory(insurer_name="Другая СК")
        other_branch = branch_factory(branch_name="Другой филиал")
        for suffix, insurer, branch in [
            ("insurer", other_insurer, setup["branch"]),
            ("branch", setup["insurer"], other_branch),
        ]:
            policy = policy_factory(
                policy_number=f"OSAGO-{suffix}",
                insurance_type=setup["osago"].insurance_type,
                insurer=insurer,
                branch=branch,
                franchise=Decimal("0"),
            )
            PaymentSchedule.objects.create(
                policy=policy,
                year_number=1,
                installment_number=1,
                due_date=due,
                amount=Decimal("10000"),
            )

        params = {
            "osago": "only",
            "status": "upcoming",
            "branch": setup["branch"].pk,
            "insurer": setup["insurer"].pk,
            "date_from": today.isoformat(),
            "date_to": (today + timedelta(days=10)).isoformat(),
            "year_number": 1,
            "installment_number": 1,
        }
        response = user_client.get(reverse("policies:payments"), params)
        assert [payment.policy_id for payment in response.context["payments"]] == [
            setup["osago"].pk
        ]

        response = user_client.get(
            reverse("policies:payments"), {**params, "osago": "exclude"}
        )
        assert [payment.policy_id for payment in response.context["payments"]] == [
            setup["kasko"].pk
        ]
        response = user_client.get(
            reverse("policies:payments"), {**params, "year_number": 2}
        )
        assert list(response.context["payments"]) == []

    def test_osago_keeps_default_upcoming_status(
        self, user_client, setup, policy_factory
    ):
        PaymentSchedule.objects.filter(policy=setup["osago"]).update(
            due_date=timezone.now().date() + timedelta(days=5)
        )
        past_policy = policy_factory(
            policy_number="OSAGO-PAST",
            insurance_type=setup["osago"].insurance_type,
            franchise=Decimal("0"),
        )
        PaymentSchedule.objects.create(
            policy=past_policy,
            year_number=1,
            installment_number=1,
            due_date=timezone.now().date() - timedelta(days=5),
            amount=Decimal("10000"),
        )
        upcoming = user_client.get(reverse("policies:payments"), {"osago": "only"})
        assert upcoming.context["selected_status"] == "upcoming"
        assert {payment.policy_id for payment in upcoming.context["payments"]} == {
            setup["osago"].pk
        }
        all_statuses = user_client.get(
            reverse("policies:payments"), {"status": "all", "osago": "only"}
        )
        assert {payment.policy_id for payment in all_statuses.context["payments"]} == {
            setup["osago"].pk,
            past_policy.pk,
        }

    def test_filter_survives_navigation_and_reset(
        self, user_client, setup, policy_factory, monkeypatch
    ):
        from apps.policies.views import PaymentScheduleListView

        monkeypatch.setattr(PaymentScheduleListView, "paginate_by", 1)
        other = policy_factory(
            policy_number="OSAGO-778",
            client=setup["client"],
            insurer=setup["insurer"],
            branch=setup["branch"],
            insurance_type=setup["osago"].insurance_type,
            franchise=Decimal("0"),
        )
        PaymentSchedule.objects.create(
            policy=other,
            year_number=1,
            installment_number=1,
            due_date=timezone.now().date() - timedelta(days=5),
            amount=Decimal("10000"),
        )
        today = timezone.now().date()
        params = {
            "status": "all",
            "osago": "only",
            "branch": str(setup["branch"].pk),
            "insurer": str(setup["insurer"].pk),
            "date_from": (today - timedelta(days=30)).isoformat(),
            "date_to": today.isoformat(),
            "year_number": "1",
            "installment_number": "1",
            "page": "2",
        }
        response = user_client.get(reverse("policies:payments"), params)
        assert response.status_code == 200
        assert response.context["page_obj"].number == 2
        page = PaymentPage(response)

        for status in ("approved", "paid", "overdue", "upcoming", "future", "all"):
            link = page.links[f"pl-status-btn--{status}"][0]
            query = parse_qs(urlsplit(link).query)
            assert query == {
                key: [status if key == "status" else value]
                for key, value in params.items()
                if key != "page"
            }
        for link in page.links["pl-branch-tab"]:
            query = parse_qs(urlsplit(link).query)
            assert query["osago"] == ["only"]
            assert "page" not in query
        assert any(
            parse_qs(urlsplit(link).query).get("osago") == ["only"]
            and parse_qs(urlsplit(link).query).get("page") == ["1"]
            for link in page.links["pl-page-btn"]
        )

        payment = response.context["payments"][0]
        card = user_client.get(page.links["journal-record"][0])
        assert card.context["back_url"] == (
            response.wsgi_request.get_full_path() + f"#payment-{payment.pk}"
        )
        reset = parse_qs(urlsplit(page.links["btn-pl-reset"][0]).query)
        assert reset == {"status": ["all"], "branch": [str(setup["branch"].pk)]}


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
