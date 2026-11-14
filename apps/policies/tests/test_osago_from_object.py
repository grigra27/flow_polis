from datetime import timedelta
from decimal import Decimal

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.insurers.models import InsuranceType
from apps.policies.models import Policy
from apps.policies.tests.test_copy_policy import form_payload

pytestmark = [pytest.mark.admin, pytest.mark.django_db]


@pytest.fixture
def kasko_policy(sample_policy):
    sample_policy.insurance_type = InsuranceType.objects.create(name="КАСКО")
    sample_policy.save(update_fields=["insurance_type"])
    return sample_policy


def test_issue_osago_from_policy_card(
    admin_client, policy_factory, sample_payment, insurer_factory, kasko_policy
):
    obj = kasko_policy
    obj.vin_number = "VINTEST123"
    obj.property_year = 2022
    obj.save()
    kind = InsuranceType.objects.create(name="ОСАГО", is_osago=True)
    today = timezone.localdate()
    earlier = policy_factory(
        insurance_type=kind,
        vin_number=obj.vin_number,
        policy_number="ОСАГО-ПРОШЛЫЙ",
        start_date=today - timedelta(days=200),
        end_date=today - timedelta(days=30),
    )
    url = reverse("admin:policies_osagopolicy_add", query={"from_object": obj.pk})
    card = reverse("policies:detail", args=[obj.pk])
    assert url in admin_client.get(card).content.decode()
    response = admin_client.get(url)
    assert response.status_code == 200
    assert response.context["osago_matches"] == [(earlier, "Предыдущий")]
    data = form_payload(response)
    assert data["vin_number"] == obj.vin_number and data["dfa_number"] == obj.dfa_number
    assert data["property_year"] == str(obj.property_year) and data["client"] == str(
        obj.client_id
    )
    assert data["payment_schedule-TOTAL_FORMS"] == "1"
    assert (
        not {
            "start_date",
            "end_date",
            "policy_number",
            "insurer",
            "payment_schedule-0-due_date",
            "payment_schedule-0-amount",
        }
        & data.keys()
    )
    assert Policy.objects.count() == 2
    insurer = insurer_factory(insurer_name="Другая СК")
    data.update(
        policy_number="ОСАГО-НОВЫЙ",
        insurer=insurer.pk,
        start_date=today.isoformat(),
        end_date=(today + timedelta(days=300)).isoformat(),
        _save_and_open_front="1",
    )
    data.update(
        {
            "payment_schedule-0-due_date": today.isoformat(),
            "payment_schedule-0-amount": "10000",
            "payment_schedule-0-kv_rub": "800",
        }
    )
    saved = admin_client.post(url, data)
    assert saved.status_code == 302
    new = Policy.objects.get(policy_number="ОСАГО-НОВЫЙ")
    assert saved.url == reverse("policies:detail", args=[new.pk])
    assert new.is_osago and new.insurer == insurer and new.vin_number == obj.vin_number
    assert new.franchise == 0 and not new.policy_uploaded
    payment = new.payment_schedule.get()
    assert (
        payment.year_number,
        payment.installment_number,
        payment.insurance_sum,
        payment.amount,
    ) == (1, 1, None, Decimal("10000"))
    assert payment.paid_date is None and payment.insurer_date is None
    assert admin_client.get(card).context["osago_matches"] == [(new, "Действует")]
    assert (
        "Оформить ОСАГО на этот объект"
        not in admin_client.get(saved.url).content.decode()
    )
    assert (
        admin_client.get(
            reverse("admin:policies_policy_add"), {"from_object": obj.pk}
        ).status_code
        == 404
    )


def test_osago_matches_require_vin_and_an_authorized_operator(
    admin_client, client, django_user_model, kasko_policy, policy_factory
):
    kind = InsuranceType.objects.create(name="ОСАГО", is_osago=True)
    policy_factory(
        insurance_type=kind, vin_number="", dfa_number=kasko_policy.dfa_number
    )
    card = reverse("policies:detail", args=[kasko_policy.pk])
    url = reverse(
        "admin:policies_osagopolicy_add", query={"from_object": kasko_policy.pk}
    )
    assert admin_client.get(url).context["osago_matches"] == []
    viewer = django_user_model.objects.create_user("reader", is_staff=True)
    client.force_login(viewer)
    assert url not in client.get(card).content.decode()
    assert client.get(url).status_code == client.post(url, {}).status_code == 403


@pytest.mark.parametrize(
    "type_name",
    [
        "Ответственность",
        "Грузы",
        "Имущество",
        "Спецтехника",
        "КАСКО спецтехники",
        "ОСАГО",
    ],
)
def test_osago_from_other_insurance_types_is_unavailable(
    admin_client, sample_policy, type_name
):
    sample_policy.insurance_type = InsuranceType.objects.create(
        name=type_name, is_osago=type_name == "ОСАГО"
    )
    sample_policy.vin_number = "VINTEST123"
    sample_policy.save(update_fields=["insurance_type", "vin_number"])
    card = admin_client.get(reverse("policies:detail", args=[sample_policy.pk]))
    assert card.status_code == 200
    assert "Оформить ОСАГО на этот объект" not in card.content.decode()
    assert "Создать по образцу" in card.content.decode()

    url = reverse(
        "admin:policies_osagopolicy_add", query={"from_object": sample_policy.pk}
    )
    before = Policy.objects.count()
    assert admin_client.get(url).status_code == 404
    assert admin_client.post(url, {}).status_code == 404
    assert Policy.objects.count() == before
