from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

import pytest
from django.contrib.auth.models import AnonymousUser, Permission, User
from django.core.cache import cache
from django.core.management import call_command
from django.test import RequestFactory
from django.urls import reverse
from django.utils import timezone

from apps.clients.models import Client
from apps.communications.models import MailAccount, OutboundEmail
from apps.core.context_processors import FOOTER_CACHE_KEY, footer_status
from apps.core.models import ServiceHeartbeat
from apps.insurers.models import Branch, CommissionRate, InsuranceType, Insurer
from apps.policies.models import PaymentSchedule, Policy


@pytest.fixture(autouse=True)
def _clear_footer_cache():
    cache.delete(FOOTER_CACHE_KEY)
    yield
    cache.delete(FOOTER_CACHE_KEY)


@pytest.fixture
def portfolio(db):
    today = timezone.localdate()
    client = Client.objects.create(
        client_name="ООО Футер Тест", client_inn="1234567890"
    )
    insurer = Insurer.objects.create(insurer_name="СК Футер")
    branch = Branch.objects.create(branch_name="Москва")
    insurance_type = InsuranceType.objects.create(name="КАСКО")
    rate = CommissionRate.objects.create(
        insurer=insurer,
        insurance_type=insurance_type,
        kv_percent=Decimal("10.00"),
    )

    def make_policy(number, active=True):
        return Policy.objects.create(
            policy_number=number,
            dfa_number=f"DFA-{number}",
            client=client,
            insurer=insurer,
            branch=branch,
            insurance_type=insurance_type,
            property_description="Автомобиль",
            start_date=today - timedelta(days=120),
            end_date=today + timedelta(days=200),
            franchise=Decimal("0"),
            policy_active=active,
            policy_uploaded=True,
            broker_participation=True,
        )

    def make_payment(policy, due_offset, paid=False, installment=1):
        return PaymentSchedule.objects.create(
            policy=policy,
            year_number=1,
            installment_number=installment,
            due_date=today + timedelta(days=due_offset),
            amount=Decimal("1000.00"),
            insurance_sum=Decimal("10000.00"),
            commission_rate=rate,
            kv_rub=Decimal("100.00"),
            paid_date=today if paid else None,
        )

    active = make_policy("F-001")
    inactive = make_policy("F-002", active=False)

    # Номера взносов уникальны в рамках года, даты строго возрастают.
    make_payment(active, -10, installment=1)  # просрочен
    make_payment(active, -5, paid=True, installment=2)  # оплачен, не считается
    make_payment(active, 0, installment=3)  # сегодня → неделя
    make_payment(active, 7, installment=4)  # граница недели
    make_payment(active, 8, installment=5)  # уже за неделей
    make_payment(active, 20, installment=6)  # будущее
    make_payment(inactive, -3)  # неактивный полис, не считается

    return {"active": active, "inactive": inactive}


def _request(user):
    request = RequestFactory().get("/")
    request.user = user
    return request


@pytest.mark.django_db
def test_anonymous_gets_no_footer_status():
    assert footer_status(_request(AnonymousUser())) == {}


@pytest.mark.django_db
def test_regular_user_sees_payments_only(portfolio):
    user = User.objects.create_user("reader", password="x")
    status = footer_status(_request(user))["footer_status"]

    assert status["overdue_count"] == 1
    assert status["week_count"] == 2
    assert status["overdue_url"] == reverse("policies:payments") + "?status=overdue"
    assert status["week_url"] == reverse("policies:payments") + "?status=week"
    assert status["show_mail"] is False
    assert status["show_tech"] is False
    assert "mail_queued" not in status
    assert "build_label" not in status


@pytest.mark.django_db
def test_superuser_sees_mail_and_tech(portfolio):
    user = User.objects.create_superuser("boss", password="x")
    status = footer_status(_request(user))["footer_status"]

    assert status["show_mail"] is True
    assert status["show_tech"] is True
    assert status["mail_queued"] == 0
    assert status["mail_failed"] == 0
    assert status["build_label"]
    assert status["env_label"] in {"dev", "prod"}
    assert status["digest"] == {"state": "unknown", "label": "нет данных"}
    assert status["beat_label"] is None
    assert status["server_time_iso"]


@pytest.mark.django_db
def test_staff_without_mail_permission_does_not_see_mail(portfolio):
    user = User.objects.create_user("limited", password="x", is_staff=True)
    status = footer_status(_request(user))["footer_status"]

    assert status["show_mail"] is False
    assert status["show_tech"] is True


@pytest.mark.django_db
def test_staff_with_mail_permission_see_mail(portfolio):
    user = User.objects.create_user("mailer", password="x", is_staff=True)
    perm = Permission.objects.get(codename="view_outboundemail")
    user.user_permissions.add(perm)
    user = User.objects.get(pk=user.pk)

    account = MailAccount.objects.create(
        code="test", name="Тест", email="test@example.com"
    )
    common = {
        "account": account,
        "kind": OutboundEmail.KIND_BILLING_INSURER_REQUEST,
        "from_email": "test@example.com",
        "subject": "Счет",
        "body_text": "Текст",
        "content_object": portfolio["active"],
    }
    OutboundEmail.objects.create(status=OutboundEmail.STATUS_QUEUED, **common)
    OutboundEmail.objects.create(status=OutboundEmail.STATUS_SENDING, **common)
    OutboundEmail.objects.create(status=OutboundEmail.STATUS_FAILED, **common)
    OutboundEmail.objects.create(status=OutboundEmail.STATUS_SENT, **common)

    status = footer_status(_request(user))["footer_status"]
    assert status["show_mail"] is True
    assert status["mail_queued"] == 1
    assert status["mail_failed"] == 1
    assert status["mail_queued_url"].endswith("?status__exact=queued")
    assert status["mail_failed_url"].endswith("?status__exact=failed")


@pytest.mark.django_db
def test_counters_are_cached(portfolio):
    user = User.objects.create_user("reader2", password="x")
    first = footer_status(_request(user))["footer_status"]
    assert first["overdue_count"] == 1

    extra_policy = Policy.objects.create(
        policy_number="F-EXTRA",
        dfa_number="DFA-F-EXTRA",
        client=portfolio["active"].client,
        insurer=portfolio["active"].insurer,
        branch=portfolio["active"].branch,
        insurance_type=portfolio["active"].insurance_type,
        property_description="Автомобиль",
        start_date=timezone.localdate() - timedelta(days=120),
        end_date=timezone.localdate() + timedelta(days=200),
        franchise=Decimal("0"),
        policy_active=True,
        policy_uploaded=True,
        broker_participation=True,
    )
    PaymentSchedule.objects.create(
        policy=extra_policy,
        year_number=1,
        installment_number=1,
        due_date=timezone.localdate() - timedelta(days=1),
        amount=Decimal("500.00"),
        insurance_sum=Decimal("5000.00"),
    )
    cached = footer_status(_request(user))["footer_status"]
    assert cached["overdue_count"] == 1

    cache.delete(FOOTER_CACHE_KEY)
    fresh = footer_status(_request(user))["footer_status"]
    assert fresh["overdue_count"] == 2


@pytest.mark.django_db
def test_digest_fresh_and_stale():
    user = User.objects.create_superuser("boss2", password="x")
    now = timezone.now()

    ServiceHeartbeat.objects.create(key="daily_digest", last_success_at=now)
    status = footer_status(_request(user))["footer_status"]
    assert status["digest"]["state"] == "ok"
    assert status["digest"]["label"] == timezone.localtime(now).strftime("%H:%M")

    cache.delete(FOOTER_CACHE_KEY)
    ServiceHeartbeat.objects.filter(key="daily_digest").update(
        last_success_at=now - timedelta(days=2)
    )
    status = footer_status(_request(user))["footer_status"]
    assert status["digest"] == {"state": "stale", "label": "2 дн. назад"}


@pytest.mark.django_db
def test_daily_digest_records_heartbeat_on_delivery():
    with patch("apps.core.notifications.send_telegram", return_value=True):
        call_command("daily_digest", "--test", "--no-vk")

    beat = ServiceHeartbeat.objects.get(key="daily_digest")
    assert beat.detail == "Telegram: да, VK: нет"
    assert timezone.now() - beat.last_success_at < timedelta(minutes=1)


@pytest.mark.django_db
def test_daily_digest_skips_heartbeat_when_nothing_delivered():
    with patch("apps.core.notifications.send_telegram", return_value=False):
        call_command("daily_digest", "--test", "--no-vk")

    assert not ServiceHeartbeat.objects.filter(key="daily_digest").exists()


@pytest.mark.django_db
def test_footer_renders_on_dashboard(client):
    User.objects.create_superuser("boss3", password="x")
    client.force_login(User.objects.get(username="boss3"))
    response = client.get(reverse("core:dashboard"))

    assert response.status_code == 200
    content = response.content.decode()
    assert "app-footer" in content
    assert "Просрочено" in content
    assert "af-tech" in content
    assert "дайджест" in content
    assert "af-clock" in content
