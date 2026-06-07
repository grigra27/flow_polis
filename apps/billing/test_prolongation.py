from datetime import date, timedelta

import pytest
from django.contrib.auth.models import User
from django.test import override_settings
from django.urls import reverse

from apps.billing import prolongation_services as prol
from apps.billing.models import ProlongationBatch
from apps.communications.models import OutboundEmail
from apps.communications.validators import validate_outbound_attachment
from apps.clients.models import Client
from apps.insurers.models import Branch, InsuranceType, Insurer
from apps.policies.models import Policy


def _make_policy(
    end_date, *, policy_number, policy_active=True, branch=None, insurer=None
):
    client = Client.objects.create(client_name=f"ЛП {policy_number}")
    insurer = insurer or Insurer.objects.create(insurer_name=f"СК {policy_number}")
    branch = branch or Branch.objects.create(branch_name=f"Филиал {policy_number}")
    insurance_type = InsuranceType.objects.create(name=f"Тип {policy_number}")
    return Policy.objects.create(
        policy_number=policy_number,
        dfa_number=f"DFA-{policy_number}",
        client=client,
        insurer=insurer,
        property_description="Объект",
        start_date=end_date - timedelta(days=365),
        end_date=end_date,
        insurance_type=insurance_type,
        branch=branch,
        policy_active=policy_active,
    )


@pytest.fixture
def month_anchor():
    # 15-е число текущего месяца — всегда внутри месяца, без краевых случаев.
    today = date.today()
    return date(today.year, today.month, 15)


@pytest.mark.django_db
def test_get_prolongation_policies_matches_expiration_filter(month_anchor):
    inside = _make_policy(month_anchor, policy_number="IN")
    _make_policy(month_anchor + timedelta(days=40), policy_number="NEXT")
    _make_policy(month_anchor, policy_number="INACTIVE", policy_active=False)

    result = prol.get_prolongation_policies(month_anchor.year, month_anchor.month)

    assert list(result) == [inside]


@pytest.mark.django_db
def test_month_options_count_policies_per_month(month_anchor):
    _make_policy(month_anchor, policy_number="A")
    _make_policy(month_anchor, policy_number="B")

    months = prol.visible_prolongation_months(today=month_anchor)
    options = prol.build_prolongation_month_options(
        months, month_anchor.year, month_anchor.month
    )

    selected = next(o for o in options if o["selected"])
    assert selected["total"] == 2
    # Горизонт — текущий месяц + 6 вперёд.
    assert len(options) == 7


@pytest.mark.django_db
def test_build_attachment_is_valid_xlsx(month_anchor):
    _make_policy(month_anchor, policy_number="A")
    batch = prol.get_or_create_batch(month_anchor.year, month_anchor.month)
    policies = prol.get_prolongation_policies(month_anchor.year, month_anchor.month)

    attachment = prol.build_prolongation_attachment(batch, policies)

    assert attachment.name.endswith(".xlsx")
    result = validate_outbound_attachment(attachment)
    assert result.size > 0


@pytest.mark.django_db
@override_settings(COMMUNICATIONS_EMAIL_ENABLED=True, COMMUNICATIONS_BCC_EMAILS="")
def test_superuser_can_send_prolongation_email_with_auto_excel(
    client, month_anchor, monkeypatch
):
    monkeypatch.setattr(
        "apps.billing.views.queue_outbound_email",
        lambda outbound_email, user=None: outbound_email,
    )
    _make_policy(month_anchor, policy_number="A")
    admin = User.objects.create_superuser(
        username="prol_sender", email="p@example.com", password="testpass123"
    )
    client.login(username=admin.username, password="testpass123")

    code = f"{month_anchor.year:04d}-{month_anchor.month:02d}"
    response = client.post(
        reverse("policies:prolongation_send_email"),
        {"period": code, "recipient_email": "recipient@example.com"},
    )

    assert response.status_code == 302
    email = OutboundEmail.objects.get()
    assert email.kind == OutboundEmail.KIND_PROLONGATION_FORWARD
    assert email.to_addresses == ["recipient@example.com"]
    assert email.attachments.count() == 1
    assert email.attachments.get().original_filename.endswith(".xlsx")
    # Партия создаётся лениво при отправке и служит content_object письма.
    batch = ProlongationBatch.objects.get(
        year=month_anchor.year, month=month_anchor.month
    )
    assert email.object_id == batch.pk


@pytest.mark.django_db
@override_settings(COMMUNICATIONS_EMAIL_ENABLED=True)
def test_send_without_policies_does_not_create_email(client, month_anchor, monkeypatch):
    monkeypatch.setattr(
        "apps.billing.views.queue_outbound_email",
        lambda outbound_email, user=None: outbound_email,
    )
    admin = User.objects.create_superuser(
        username="empty_sender", email="e@example.com", password="testpass123"
    )
    client.login(username=admin.username, password="testpass123")

    code = f"{month_anchor.year:04d}-{month_anchor.month:02d}"
    response = client.post(
        reverse("policies:prolongation_send_email"),
        {"period": code, "recipient_email": "recipient@example.com"},
    )

    assert response.status_code == 302
    assert not OutboundEmail.objects.exists()


@pytest.mark.django_db
@override_settings(COMMUNICATIONS_RESTRICT_TO_SUPERUSER=True)
def test_regular_user_cannot_send_prolongation(client, month_anchor):
    _make_policy(month_anchor, policy_number="A")
    user = User.objects.create_user(
        username="regular", email="r@example.com", password="testpass123"
    )
    client.login(username=user.username, password="testpass123")

    code = f"{month_anchor.year:04d}-{month_anchor.month:02d}"
    response = client.post(
        reverse("policies:prolongation_send_email"),
        {"period": code, "recipient_email": "recipient@example.com"},
    )

    assert response.status_code == 403
    assert not OutboundEmail.objects.exists()


@pytest.mark.django_db
def test_prolongation_list_view_renders_policies(client, month_anchor):
    _make_policy(month_anchor, policy_number="VISIBLE-POL")
    user = User.objects.create_user(
        username="viewer", email="v@example.com", password="testpass123"
    )
    client.login(username=user.username, password="testpass123")

    code = f"{month_anchor.year:04d}-{month_anchor.month:02d}"
    response = client.get(reverse("policies:prolongation") + f"?period={code}")

    assert response.status_code == 200
    assert "VISIBLE-POL" in response.content.decode()
