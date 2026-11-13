"""Создание по образцу через настоящие карточку, admin action и форму с инлайнами."""

from datetime import timedelta
from decimal import Decimal

import pytest
from django.contrib.auth.models import Permission
from django.urls import reverse
from django.utils import timezone

from apps.insurers.models import InsuranceType
from apps.policies.models import PaymentSchedule, Policy

pytestmark = [pytest.mark.admin, pytest.mark.django_db]


def form_payload(response):
    """Значения редактируемых полей и management form, как при отправке браузером."""
    main = response.context["adminform"].form
    data = {}

    def add_fields(form):
        for field in form:
            if field.field.disabled or field.name == "DELETE":
                continue
            value = field.value()
            if getattr(field.field.widget, "input_type", None) == "checkbox":
                if value:
                    data[field.html_name] = "on"
            elif value not in (None, ""):
                data[field.html_name] = str(value)

    add_fields(main)
    for inline in response.context["inline_admin_formsets"]:
        fs = inline.formset
        add_fields(fs.management_form)
        for row in fs.forms:
            add_fields(row)
    return data


@pytest.mark.parametrize("osago", [False, True])
def test_template_preview_retry_and_save(
    admin_client, policy_factory, payment_schedule_factory, client_factory, osago
):
    today = timezone.localdate()
    kind = InsuranceType.objects.create(name="Образец", is_osago=osago)
    src = policy_factory(
        insurance_type=kind,
        policyholder=client_factory(),
        start_date=today - timedelta(days=30),
        end_date=today + timedelta(days=100),
        vin_number="TEST123",
        property_year=2020,
        franchise=0,
        policy_uploaded=True,
        policy_active=False,
        termination_date=today,
        dfa_active=False,
        dfa_deactivation_date=today,
        renewal_to_old_dfa=True,
    )
    dates = [today] if osago else [today, today + timedelta(days=90)]
    for index, due in enumerate(dates, start=1):
        payment_schedule_factory(
            policy=src,
            installment_number=index,
            due_date=due,
            paid_date=due,
            insurer_date=due,
            alliance_paid=True,
            payment_info="Оплата образца",
            insurance_sum=None if osago else Decimal("100000"),
            amount=Decimal("10000"),
            kv_rub=Decimal("345.67"),
        )
    section = "osagopolicy" if osago else "policy"
    url = reverse(f"admin:policies_{section}_add", query={"from_policy": src.pk})
    card_url = reverse("policies:detail", args=[src.pk])
    assert url in admin_client.get(card_url).content.decode()
    action = admin_client.post(
        reverse(f"admin:policies_{section}_changelist"),
        {
            "action": "copy_policy",
            "_selected_action": src.pk,
        },
    )
    assert action.status_code == 302 and action.url == url

    response = admin_client.get(url)
    assert response.status_code == 200 and card_url in response.content.decode()
    data = form_payload(response)
    assert "policy_number" not in data
    assert data["dfa_number"] == src.dfa_number and data["vin_number"] == src.vin_number
    assert data["policyholder"] == str(src.policyholder_id) and data["client"] == str(
        src.client_id
    )
    assert data["insurer"] == str(src.insurer_id)
    assert "policy_uploaded" not in data and "termination_date" not in data
    assert "info3" not in data and "info4" not in data
    assert data["policy_active"] == data["dfa_active"] == "on"
    assert int(data["payment_schedule-TOTAL_FORMS"]) == len(dates)
    assert Policy.objects.count() == 1 and PaymentSchedule.objects.count() == len(dates)

    invalid = admin_client.post(url, data)
    assert (
        invalid.status_code == 200
        and "policy_number" in invalid.context["adminform"].form.errors
    )
    assert Policy.objects.count() == 1
    data["policy_number"] = "НОВЫЙ-01"
    data["payment_schedule-0-kv_rub"] = "200.11"
    data["_save_and_open_front"] = "1"
    saved = admin_client.post(url, data)
    assert saved.status_code == 302
    new = Policy.objects.get(policy_number=data["policy_number"])
    assert new.is_osago == osago and saved.url == reverse(
        "policies:detail", args=[new.pk]
    )
    assert new.policy_active and new.dfa_active and not new.renewal_to_old_dfa
    assert not new.policy_uploaded and not new.info3 and not new.info4
    assert not new.termination_date and not new.dfa_deactivation_date
    payments = list(new.payment_schedule.order_by("installment_number"))
    assert [p.due_date for p in payments] == dates
    assert all(p.amount == Decimal("10000") for p in payments)
    assert all(
        not p.paid_date
        and not p.insurer_date
        and not p.alliance_paid
        and not p.payment_info
        for p in payments
    )
    assert payments[0].kv_rub == Decimal("200.11")
    assert payments[0].insurance_sum == (None if osago else Decimal("100000"))
    src.refresh_from_db()
    assert src.policy_uploaded and src.payment_schedule.filter(
        paid_date__isnull=False
    ).count() == len(dates)


def test_template_requires_add_rights_for_policy_and_installments(
    client, django_user_model, sample_policy
):
    user = django_user_model.objects.create_user("operator", is_staff=True)
    add_policy = Permission.objects.get(
        content_type__app_label="policies", codename="add_policy"
    )
    user.user_permissions.add(add_policy)
    client.force_login(user)
    url = reverse("admin:policies_policy_add", query={"from_policy": sample_policy.pk})
    card_url = reverse("policies:detail", args=[sample_policy.pk])
    assert url not in client.get(card_url).content.decode()
    assert client.get(url).status_code == client.post(url, {}).status_code == 403
    user.user_permissions.add(
        Permission.objects.get(
            content_type__app_label="policies", codename="add_paymentschedule"
        )
    )
    assert url in client.get(card_url).content.decode()
    assert client.get(url).status_code == 200


def test_one_source_and_its_own_section(admin_client, sample_policy, policy_factory):
    second = policy_factory(insurance_type=sample_policy.insurance_type)
    url = reverse("admin:policies_policy_changelist")
    response = admin_client.post(
        url,
        {"action": "copy_policy", "_selected_action": [sample_policy.pk, second.pk]},
        follow=True,
    )
    assert "Выберите один полис-образец" in response.content.decode()
    assert Policy.objects.count() == 2
    wrong_section = reverse(
        "admin:policies_osagopolicy_add", query={"from_policy": sample_policy.pk}
    )
    assert admin_client.get(wrong_section).status_code == 404
    assert (
        admin_client.get(
            reverse("admin:policies_policy_add"), {"from_policy": "bad"}
        ).status_code
        == 404
    )
