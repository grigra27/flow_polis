"""Грузы не продлевают никогда: виды с needs_prolongation=False исключены
из раздела и экспорта «Пролонгация» и из метрик продлений."""

import importlib
import io
from datetime import timedelta

import pytest
from django.apps import apps as django_apps
from django.urls import reverse
from django.utils import timezone
from openpyxl import load_workbook

from apps.analytics import portfolio
from apps.billing import prolongation_services as prol
from apps.clients.models import Client
from apps.core.services.dashboard_v2_service import DashboardV2Service
from apps.insurers.models import Branch, InsuranceType, Insurer
from apps.policies.models import Policy, prolongation_due_q


def _policy(number, insurance_type, end_date, start_date=None):
    return Policy.objects.create(
        policy_number=number,
        dfa_number=f"DFA-{number}",
        client=Client.objects.create(client_name=f"ЛП {number}"),
        insurer=Insurer.objects.get_or_create(insurer_name="СК")[0],
        branch=Branch.objects.get_or_create(branch_name="Филиал")[0],
        insurance_type=insurance_type,
        property_description="Объект",
        start_date=start_date or end_date - timedelta(days=365),
        end_date=end_date,
    )


@pytest.fixture
def end():
    # 15-е число следующего месяца: полисы в силе на начало месяца
    # и попадают в горизонт 90 дней дашборда.
    today = timezone.localdate()
    return (today.replace(day=1) + timedelta(days=32)).replace(day=15)


@pytest.fixture
def pair(db, end):
    kasko = InsuranceType.objects.create(name="КАСКО (тест)")
    cargo = InsuranceType.objects.create(name="Грузы (тест)", needs_prolongation=False)
    return {
        "kasko": _policy("KASKO-PROL", kasko, end),
        "cargo": _policy("CARGO-PROL", cargo, end),
    }


def test_new_insurance_type_needs_prolongation_by_default(db):
    assert InsuranceType.objects.create(name="Новый вид").needs_prolongation


def test_migration_marks_cargo(db):
    cargo = InsuranceType.objects.create(name="Грузы", needs_prolongation=True)
    migration = importlib.import_module(
        "apps.insurers.migrations.0015_insurancetype_needs_prolongation"
    )
    migration.mark_cargo(django_apps, None)
    cargo.refresh_from_db()
    assert not cargo.needs_prolongation


def test_queryset_prolongable(pair):
    assert list(Policy.objects.prolongable()) == [pair["kasko"]]


def test_prolongation_page_and_month_counts(pair, end):
    assert list(prol.get_prolongation_policies(end.year, end.month)) == [pair["kasko"]]

    months = [end.replace(day=1)]
    options = prol.build_prolongation_month_options(months, end.year, end.month)
    assert options[0]["total"] == 1


def test_prolongation_export(client, django_user_model, pair, end):
    user = django_user_model.objects.create_user("staff", password="x", is_staff=True)
    client.force_login(user)
    response = client.get(
        reverse("reports:export_policy_expiration"),
        {
            "date_from": end.replace(day=1).isoformat(),
            "date_to": (end + timedelta(days=1)).isoformat(),
        },
    )
    assert response.status_code == 200
    workbook = load_workbook(io.BytesIO(response.content), read_only=True)
    text = " ".join(
        str(cell)
        for sheet in workbook.worksheets
        for row in sheet.iter_rows(values_only=True)
        for cell in row
    )
    assert "KASKO-PROL" in text
    assert "CARGO-PROL" not in text


def test_analytics_renewal_due(pair, end):
    due = portfolio.renewal_due(Policy.objects.all(), end.replace(day=1), end)
    assert list(due) == [pair["kasko"]]


def test_dashboard_renewal_radar(pair):
    radar = DashboardV2Service()._build_renewal_radar(
        active_policies_qs=Policy.objects.all(), today=timezone.localdate()
    )
    assert radar["active_total"] == 2
    assert radar["horizons"][-1]["count"] == 1


@pytest.fixture
def rule_a_cases(db, end):
    """Правило пролонгации «вариант А» (2026-10-23): полис доживает до своей
    даты окончания — активен и не расторгнут досрочно; ДФА открыт."""
    kasko = InsuranceType.objects.create(name="КАСКО (правило А)")

    def make(number, **fields):
        policy = _policy(number, kasko, end, start_date=fields.pop("start_date", None))
        Policy.objects.filter(pk=policy.pk).update(**fields)
        return number

    return {
        "in": {
            make("A-PLAIN"),
            # Расторжение не раньше окончания — не досрочное.
            make("A-TERM-AT-END", termination_date=end),
            # Начался в том же месяце — всё равно подлежит пролонгации.
            make("A-SHORT", start_date=end - timedelta(days=5)),
            make("A-NO-BROKER", broker_participation=False),
        },
        "out": {
            # Как №205: расторгнут за неделю до окончания, флаг снят.
            make(
                "A-TERM-EARLY",
                termination_date=end - timedelta(days=7),
                policy_active=False,
            ),
            # Как №891: дата расторжения есть, а флаг забыли снять.
            make("A-TERM-FLAG-LEFT", termination_date=end - timedelta(days=7)),
            make("A-INACTIVE", policy_active=False),
            # Закрытый ДФА исключается независимо от даты закрытия и брокера.
            make("A-DFA-CLOSED-NO-DATE", dfa_active=False),
            make(
                "A-DFA-CLOSED-PAST",
                dfa_active=False,
                dfa_deactivation_date=end - timedelta(days=10),
            ),
            make(
                "A-DFA-CLOSED-FUTURE",
                dfa_active=False,
                dfa_deactivation_date=end + timedelta(days=10),
            ),
            make(
                "A-DFA-CLOSED-NO-BROKER", dfa_active=False, broker_participation=False
            ),
        },
    }


def test_prolongation_due_q(rule_a_cases):
    numbers = set(
        Policy.objects.filter(prolongation_due_q()).values_list(
            "policy_number", flat=True
        )
    )
    assert numbers == rule_a_cases["in"]


def test_page_and_export_use_the_same_rule(
    client, django_user_model, rule_a_cases, end
):
    page = set(
        prol.get_prolongation_policies(end.year, end.month).values_list(
            "policy_number", flat=True
        )
    )
    assert page == rule_a_cases["in"]

    user = django_user_model.objects.create_user("staff", password="x", is_staff=True)
    client.force_login(user)
    page_response = client.get(
        reverse("policies:prolongation"), {"period": end.strftime("%Y-%m")}
    )
    assert page_response.status_code == 200
    context = page_response.context
    assert {policy.policy_number for policy in context["policies"]} == rule_a_cases[
        "in"
    ]
    assert context["total_filtered"] == len(rule_a_cases["in"])
    assert context["full_month_count"] == len(rule_a_cases["in"])
    selected = next(option for option in context["month_options"] if option["selected"])
    assert selected["total"] == len(rule_a_cases["in"])

    start, finish = prol.month_bounds(end.year, end.month)
    response = client.get(
        reverse("reports:export_policy_expiration"),
        {"date_from": start.isoformat(), "date_to": finish.isoformat()},
    )
    assert response.status_code == 200
    all_numbers = rule_a_cases["in"] | rule_a_cases["out"]
    rows = {row[0]: row for row in _cells(response.content) if row[0] in all_numbers}
    assert set(rows) == rule_a_cases["in"]
    assert rows["A-NO-BROKER"][-1] == "без брокера"


def _cells(content):
    workbook = load_workbook(io.BytesIO(content), read_only=True)
    rows = [
        list(row)
        for sheet in workbook.worksheets
        for row in sheet.iter_rows(values_only=True)
    ]
    workbook.close()
    return rows


def test_email_attachment_equals_export_for_the_month(
    client, django_user_model, rule_a_cases, end
):
    """Excel к письму со вкладки и экспорт за тот же месяц — одна таблица."""
    batch = prol.get_or_create_batch(end.year, end.month)
    attachment = prol.build_prolongation_attachment(
        batch, prol.get_prolongation_policies(end.year, end.month)
    )

    user = django_user_model.objects.create_user("staff", password="x", is_staff=True)
    client.force_login(user)
    response = client.get(
        reverse("reports:export_policy_expiration"),
        {
            "date_from": batch.starts_on.isoformat(),
            "date_to": batch.ends_on.isoformat(),
        },
    )

    assert _cells(attachment.read()) == _cells(response.content)


def test_page_filters_only_narrow_view_and_export_supports_branch(
    client, django_user_model, rule_a_cases, end
):
    branch = Branch.objects.create(branch_name="Отдельный филиал")
    Policy.objects.filter(policy_number="A-PLAIN").update(branch=branch)
    user = django_user_model.objects.create_user("staff", password="x", is_staff=True)
    client.force_login(user)

    response = client.get(
        reverse("policies:prolongation"),
        {"period": end.strftime("%Y-%m"), "branch": branch.pk, "q": "A-PLAIN"},
    )
    assert response.status_code == 200
    assert [policy.policy_number for policy in response.context["policies"]] == [
        "A-PLAIN"
    ]
    assert response.context["total_filtered"] == 1
    assert response.context["full_month_count"] == len(rule_a_cases["in"])

    start, finish = prol.month_bounds(end.year, end.month)
    download_url = (
        f'{reverse("reports:export_policy_expiration")}'
        f"?date_from={start.isoformat()}&date_to={finish.isoformat()}"
    )
    assert f'href="{download_url}"' in response.content.decode()
    full_export = client.get(download_url)
    assert full_export.status_code == 200
    all_numbers = rule_a_cases["in"] | rule_a_cases["out"]
    assert {
        row[0] for row in _cells(full_export.content) if row[0] in all_numbers
    } == rule_a_cases["in"]

    branch_export = client.get(
        reverse("reports:export_policy_expiration"),
        {
            "date_from": start.isoformat(),
            "date_to": finish.isoformat(),
            "branch": branch.pk,
        },
    )
    assert branch_export.status_code == 200
    assert {
        row[0] for row in _cells(branch_export.content) if row[0] in all_numbers
    } == {"A-PLAIN"}


def test_faq_modals_on_both_pages(client, django_user_model, db):
    user = django_user_model.objects.create_user("staff", password="x", is_staff=True)
    client.force_login(user)
    rule = "Дата расторжения» пуста или не раньше даты окончания"

    page = client.get(reverse("policies:prolongation")).content.decode()
    assert 'id="prolongationFaqModal"' in page
    assert rule in page
    assert "отмечен «ДФА активен»" in page
    assert "закрыт ДФА — снят «ДФА активен»" in page

    reports = client.get(reverse("reports:index")).content.decode()
    assert 'id="policyExpirationFaqModal"' in reports
    assert rule in reports
    assert "отмечен «ДФА активен»" in reports
    assert "закрыт ДФА — снят «ДФА активен»" in reports


def test_only_closed_dfa_produces_empty_page_and_no_export(
    client, django_user_model, db, end
):
    insurance_type = InsuranceType.objects.create(name="КАСКО (закрытый ДФА)")
    policy = _policy("ONLY-CLOSED-DFA", insurance_type, end)
    Policy.objects.filter(pk=policy.pk).update(dfa_active=False)
    user = django_user_model.objects.create_user("staff", password="x", is_staff=True)
    client.force_login(user)

    response = client.get(
        reverse("policies:prolongation"), {"period": end.strftime("%Y-%m")}
    )
    assert response.status_code == 200
    assert not response.context["policies"]
    assert response.context["total_filtered"] == 0
    assert response.context["full_month_count"] == 0
    selected = next(
        option for option in response.context["month_options"] if option["selected"]
    )
    assert selected["total"] == 0

    start, finish = prol.month_bounds(end.year, end.month)
    response = client.get(
        reverse("reports:export_policy_expiration"),
        {"date_from": start.isoformat(), "date_to": finish.isoformat()},
    )
    assert response.status_code == 302
    assert response.url == reverse("reports:index")
