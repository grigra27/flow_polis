from datetime import date, timedelta
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.urls import reverse
from django.utils import timezone

from apps.insurers.commissions import rate_history, resolve_commission_rate
from apps.insurers.models import CommissionRate
from apps.policies.models import Policy, PaymentSchedule
from apps.reports.exporters import ThreePercentReportExporter

pytestmark = pytest.mark.django_db
CUT = date(2026, 9, 1)


@pytest.fixture
def terms(insurer_factory, insurance_type_factory, commission_rate_factory):
    insurer = insurer_factory(insurer_name="Версии СК")
    kind = insurance_type_factory(name="Версии КАСКО")
    old = commission_rate_factory(
        insurer=insurer, insurance_type=kind, kv_percent=Decimal("25")
    )
    new = commission_rate_factory(
        insurer=insurer,
        insurance_type=kind,
        effective_from=CUT,
        kv_percent=Decimal("30"),
    )
    return insurer, kind, old, new


@pytest.mark.parametrize(
    "start,expected",
    [(CUT - timedelta(days=1), 25), (CUT, 30), (CUT + timedelta(days=700), 30)],
)
def test_inclusive_selection_and_frozen_policy(
    terms, policy_factory, payment_schedule_factory, start, expected
):
    insurer, kind, old, new = terms
    policy = policy_factory(insurer=insurer, insurance_type=kind, start_date=start)
    assert policy.commission_rate.kv_percent == expected
    payment = payment_schedule_factory(policy=policy, amount=Decimal("100000"))
    assert payment.kv_rub == Decimal(expected) * 1000
    # При сохранении с иной датой закреплённые условия сами не меняются.
    policy.start_date = CUT + timedelta(days=1)
    policy.save()
    policy.refresh_from_db()
    assert policy.commission_rate.kv_percent == expected


def test_backdated_addition_never_changes_existing_contract_or_new_installment(
    terms, policy_factory, payment_schedule_factory
):
    insurer, kind, old, new = terms
    policy = policy_factory(
        insurer=insurer,
        insurance_type=kind,
        start_date=CUT + timedelta(days=30),
        commission_rate=old,
        commission_rate_origin="legacy",
    )
    first = payment_schedule_factory(
        policy=policy, amount=Decimal("100000"), due_date=CUT
    )
    first.kv_rub = Decimal("12345.67")
    first.save()
    CommissionRate.objects.create(
        insurer=insurer,
        insurance_type=kind,
        effective_from=CUT + timedelta(days=1),
        kv_percent=Decimal("35"),
    )
    before = (first.commission_rate_id, first.kv_rub)
    first.payment_info = "Обычная правка"
    first.save()
    first.refresh_from_db()
    assert (first.commission_rate_id, first.kv_rub) == before
    second = payment_schedule_factory(
        policy=policy,
        installment_number=2,
        due_date=CUT + timedelta(days=365),
        amount=Decimal("100000"),
    )
    assert second.commission_rate == old
    assert second.kv_rub == Decimal("25000")
    fresh = policy_factory(
        insurer=insurer, insurance_type=kind, start_date=policy.start_date
    )
    assert fresh.commission_rate.kv_percent == Decimal("35")


def test_missing_rate_stays_missing_when_rate_added_later(
    policy_factory, payment_schedule_factory
):
    policy = policy_factory()
    assert policy.commission_rate is None
    CommissionRate.objects.create(
        insurer=policy.insurer,
        insurance_type=policy.insurance_type,
        kv_percent=20,
        effective_from=policy.start_date,
    )
    policy.save()
    payment = payment_schedule_factory(policy=policy, kv_rub=Decimal("321"))
    assert payment.commission_rate is None
    assert payment.kv_rub == Decimal("321")


def test_rate_protection_and_unique_boundaries(terms, policy_factory):
    insurer, kind, old, new = terms
    policy_factory(insurer=insurer, insurance_type=kind, start_date=CUT)
    new.kv_percent = Decimal("31")
    with pytest.raises(ValidationError, match="новую версию"):
        new.save()
    new.refresh_from_db()
    new.notes = "Уточнение основания"
    new.save()
    with pytest.raises(ValidationError):
        CommissionRate.objects.create(
            insurer=insurer, insurance_type=kind, effective_from=CUT, kv_percent=40
        )
    with pytest.raises(ValidationError):
        CommissionRate.objects.create(
            insurer=insurer, insurance_type=kind, kv_percent=40
        )
    with pytest.raises(IntegrityError), transaction.atomic():
        CommissionRate.objects.bulk_create(
            [
                CommissionRate(
                    insurer=insurer,
                    insurance_type=kind,
                    effective_from=CUT,
                    kv_percent=40,
                )
            ]
        )


def test_history_current_previous_future_are_distinct(terms):
    insurer, kind, old, new = terms
    later = CommissionRate.objects.create(
        insurer=insurer,
        insurance_type=kind,
        effective_from=CUT + timedelta(days=100),
        kv_percent=Decimal("32.50"),
    )
    history = rate_history(
        insurer.commission_rates.select_related("insurance_type"), on_date=CUT
    )
    assert history["current"] == [new]
    assert history["previous"] == [old]
    assert history["scheduled"] == [later]
    assert history["previous"][0].effective_until == CUT - timedelta(days=1)
    assert "32.5%" in str(later)


def test_no_future_fallback(insurer_factory, insurance_type_factory):
    insurer = insurer_factory()
    kind = insurance_type_factory()
    CommissionRate.objects.create(
        insurer=insurer, insurance_type=kind, effective_from=CUT, kv_percent=20
    )
    assert resolve_commission_rate(insurer.pk, kind.pk, CUT - timedelta(days=1)) is None
    assert resolve_commission_rate(insurer.pk, kind.pk, None) is None


@pytest.mark.parametrize(
    "actual,nonstandard",
    [
        ("25000.00", False),
        ("25000.01", False),
        ("24999.99", False),
        ("25000.02", True),
        ("28000.00", True),
        ("22000.00", True),
    ],
)
def test_same_standardness_in_card_and_report(
    terms,
    policy_factory,
    payment_schedule_factory,
    client,
    django_user_model,
    actual,
    nonstandard,
):
    insurer, kind, old, new = terms
    policy = policy_factory(
        insurer=insurer,
        insurance_type=kind,
        start_date=CUT,
        commission_rate=old,
        commission_rate_origin="legacy",
    )
    payment = payment_schedule_factory(policy=policy, amount=Decimal("100000"))
    payment.kv_rub = Decimal(actual)
    payment.save()
    assert payment.is_nonstandard_kv is nonstandard
    assert ThreePercentReportExporter._is_nonstandard_kv(None, payment) is nonstandard
    client.force_login(django_user_model.objects.create_user(username="reader"))
    response = client.get(reverse("policies:detail", args=[policy.pk]))
    assert response.status_code == 200
    assert ('class="rate-difference"' in response.content.decode()) is nonstandard
    assert response.context["commission_rate"] == old


def test_invalid_legacy_reference_is_unknown(
    terms, policy_factory, payment_schedule_factory
):
    insurer, kind, old, new = terms
    policy = policy_factory()
    payment = payment_schedule_factory(policy=policy, commission_rate=old)
    assert payment.base_commission_rate is None
    assert payment.expected_kv_rub is None
    assert not payment.is_nonstandard_kv


def test_api_selects_date_and_preserves_saved_policy(
    terms, policy_factory, admin_client
):
    insurer, kind, old, new = terms
    url = reverse("insurers:api_commission_rate")
    query = {
        "insurer_id": insurer.pk,
        "insurance_type_id": kind.pk,
        "start_date": CUT.isoformat(),
    }
    assert admin_client.get(url, query).json()["commission_rate_id"] == new.pk
    policy = policy_factory(
        insurer=insurer,
        insurance_type=kind,
        start_date=CUT,
        commission_rate=old,
        commission_rate_origin="legacy",
    )
    assert (
        admin_client.get(url, {"policy_id": policy.pk}).json()["commission_rate_id"]
        == old.pk
    )
    query.pop("start_date")
    assert admin_client.get(url, query).status_code == 400
    query["start_date"] = "2026-02-30"
    assert admin_client.get(url, query).status_code == 400


def test_admin_add_and_protect_rate(terms, policy_factory, admin_client):
    insurer, kind, old, new = terms
    data = {
        "insurer": insurer.pk,
        "insurance_type": kind.pk,
        "kv_percent": "31.25",
        "effective_from": "2027-01-01",
        "notes": "Допсоглашение",
    }
    response = admin_client.post(reverse("admin:insurers_commissionrate_add"), data)
    assert response.status_code == 302
    added = CommissionRate.objects.get(effective_from=date(2027, 1, 1), insurer=insurer)
    assert added.kv_percent == Decimal("31.25")
    policy_factory(insurer=insurer, insurance_type=kind, start_date=date(2027, 1, 1))
    response = admin_client.get(
        reverse("admin:insurers_commissionrate_change", args=[added.pk])
    )
    assert 'name="kv_percent"' not in response.content.decode()
    data["kv_percent"] = "99"
    assert (
        admin_client.post(
            reverse("admin:insurers_commissionrate_change", args=[added.pk]), data
        ).status_code
        == 302
    )
    added.refresh_from_db()
    assert added.kv_percent == Decimal("31.25")


def test_insurer_pages_show_one_current_rate_and_history(terms, admin_client):
    insurer, kind, old, new = terms
    future = timezone.localdate() + timedelta(days=3650)
    CommissionRate.objects.create(
        insurer=insurer,
        insurance_type=kind,
        effective_from=future,
        kv_percent=Decimal("33.25"),
    )
    response = admin_client.get(reverse("insurers:list"))
    listed = next(row for row in response.context["insurers"] if row.pk == insurer.pk)
    assert len(listed.rate_history["current"]) == 1
    response = admin_client.get(reverse("insurers:detail", args=[insurer.pk]))
    html = response.content.decode()
    assert "Предыдущие ставки" in html
    assert "Запланированные изменения" in html
    assert "33,25%" in html
    assert "Добавить ставку" in html


def test_inline_new_rows_calculate_but_saved_and_manual_zero_stay(
    terms, admin_user, policy_factory, payment_schedule_factory
):
    from .test_payment_inline_date_sequence import _build_formset, _payment_row

    insurer, kind, old, new = terms
    policy = policy_factory(
        insurer=insurer, insurance_type=kind, start_date=CUT, commission_rate=old
    )
    saved = payment_schedule_factory(policy=policy, due_date=CUT)
    saved.kv_rub = Decimal("123.45")
    saved.save()
    formset = _build_formset(
        admin_user,
        policy,
        [
            _payment_row(1, 1, CUT, kv_rub="123.45"),
            _payment_row(1, 2, CUT + timedelta(days=30), kv_rub=""),
            _payment_row(1, 3, CUT + timedelta(days=60), kv_rub="0"),
        ],
        existing=[saved],
    )
    assert formset.empty_form["kv_rub"].value() is None
    assert formset.is_valid(), formset.errors
    formset.save()
    assert list(
        policy.payment_schedule.order_by("installment_number").values_list(
            "kv_rub", flat=True
        )
    ) == [Decimal("123.45"), Decimal("2500"), Decimal("0")]
    assert set(
        policy.payment_schedule.values_list("commission_rate_id", flat=True)
    ) == {old.pk}


def test_clearing_saved_commission_gives_field_error(
    terms, admin_user, policy_factory, payment_schedule_factory
):
    from .test_payment_inline_date_sequence import _build_formset, _payment_row

    insurer, kind, old, new = terms
    policy = policy_factory(insurer=insurer, insurance_type=kind, start_date=CUT)
    saved = payment_schedule_factory(policy=policy, due_date=CUT)
    formset = _build_formset(
        admin_user, policy, [_payment_row(1, 1, CUT, kv_rub="")], existing=[saved]
    )
    assert not formset.is_valid()
    assert "kv_rub" in formset.forms[0].errors


@pytest.mark.parametrize("value,valid", [("", False), ("0", True), ("123.45", True)])
def test_missing_base_requires_explicit_commission(
    admin_user, policy_factory, value, valid
):
    from .test_payment_inline_date_sequence import _build_formset, _payment_row

    policy = policy_factory()
    formset = _build_formset(
        admin_user, policy, [_payment_row(1, 1, CUT, kv_rub=value)]
    )
    assert formset.is_valid() is valid
    if valid:
        formset.save()
        payment = policy.payment_schedule.get()
        assert payment.commission_rate is None
        assert payment.kv_rub == Decimal(value)
    else:
        assert "kv_rub" in formset.forms[0].errors
