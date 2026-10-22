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
from apps.policies.models import Policy


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
