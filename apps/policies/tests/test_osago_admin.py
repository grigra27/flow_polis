"""
Раздел «Полисы ОСАГО» в админке (этап 2).

ОСАГО заводится в отдельном разделе (прокси OsagoPolicy над той же
таблицей): вид страхования подставляется сам, один платёж без страховой
суммы, без франшизы. В разделе «Полисы» ОСАГО не видно и выбрать нельзя.
Ошибки правил показываются в форме, а не HTTP 500.
"""

from datetime import date
from decimal import Decimal

import pytest
from django.contrib.auth.models import Permission, User
from django.urls import reverse

from apps.insurers.models import CommissionRate, InsuranceType
from apps.policies.models import PaymentSchedule, Policy

pytestmark = [pytest.mark.admin, pytest.mark.django_db]

OSAGO_ADD_URL = "admin:policies_osagopolicy_add"
POLICY_ADD_URL = "admin:policies_policy_add"


@pytest.fixture
def osago_type(db):
    return InsuranceType.objects.create(name="ОСАГО (тест)", is_osago=True)


@pytest.fixture
def kasko_type(db):
    return InsuranceType.objects.create(name="КАСКО (тест)")


@pytest.fixture
def refs(client_factory, insurer_factory, branch_factory):
    return {
        "client": client_factory(),
        "insurer": insurer_factory(),
        "branch": branch_factory(),
    }


@pytest.fixture
def admin_client(client, admin_user):
    client.force_login(admin_user)
    return client


def _management(prefix, total, initial=0):
    return {
        f"{prefix}-TOTAL_FORMS": str(total),
        f"{prefix}-INITIAL_FORMS": str(initial),
        f"{prefix}-MIN_NUM_FORMS": "0",
        f"{prefix}-MAX_NUM_FORMS": "1000",
    }


def _policy_fields(refs, insurance_type, **overrides):
    data = {
        "policy_number": "XXX-0001",
        "dfa_number": "ДФА-1",
        "client": refs["client"].pk,
        "insurer": refs["insurer"].pk,
        "branch": refs["branch"].pk,
        "insurance_type": insurance_type.pk,
        "property_description": "Тягач",
        "start_date": "2026-01-15",
        "end_date": "2027-01-14",
        "policy_active": "on",
        "dfa_active": "on",
        "broker_participation": "on",
        "info3": "",
        "info4": "",
        **_management("info_tags", 0),
    }
    data.update(overrides)
    return data


def osago_post(refs, insurance_type, payment=None, **overrides):
    row = {
        "due_date": "2026-01-15",
        "amount": "12000.00",
        "kv_rub": "1200.00",
        "paid_date": "",
        "insurer_date": "",
        "payment_info": "",
    }
    row.update(payment or {})
    data = _policy_fields(refs, insurance_type, **overrides)
    data.update(_management("payment_schedule", 1))
    data.update({f"payment_schedule-0-{k}": v for k, v in row.items()})
    return data


def kasko_post(refs, insurance_type, payment=None, **overrides):
    row = {
        "year_number": "1",
        "installment_number": "1",
        "due_date": "2026-01-15",
        "insurance_sum": "3000000.00",
        "amount": "60000.00",
        "kv_rub": "6000.00",
        "paid_date": "",
        "insurer_date": "",
        "payment_info": "",
    }
    row.update(payment or {})
    data = _policy_fields(
        refs, insurance_type, franchise="0", end_date="2029-01-14", **overrides
    )
    data.update(_management("payment_schedule", 1))
    data.update({f"payment_schedule-0-{k}": v for k, v in row.items()})
    return data


def _form_errors(response):
    """Ошибки формы и inline'ов из контекста ответа админки (для сообщений)."""
    errors = []
    if response.context:
        if response.context.get("adminform"):
            errors.append(response.context["adminform"].form.errors)
        for formset in response.context.get("inline_admin_formsets", []):
            errors.append(formset.formset.errors)
            errors.append(formset.formset.non_form_errors())
    return errors


class TestOsagoAdd:
    def test_creates_osago_policy_with_single_payment(
        self, admin_client, refs, osago_type
    ):
        response = admin_client.post(
            reverse(OSAGO_ADD_URL), osago_post(refs, osago_type)
        )

        assert response.status_code == 302, _form_errors(response)
        policy = Policy.objects.get(policy_number="XXX-0001")
        assert policy.insurance_type == osago_type
        assert policy.franchise == Decimal("0")
        payment = policy.payment_schedule.get()
        assert (payment.year_number, payment.installment_number) == (1, 1)
        assert payment.insurance_sum is None
        assert payment.amount == Decimal("12000.00")

    def test_insurance_type_is_forced_to_osago(
        self, admin_client, refs, osago_type, kasko_type
    ):
        """В скрытое поле подсунули КАСКО — полис всё равно ОСАГО."""
        response = admin_client.post(
            reverse(OSAGO_ADD_URL), osago_post(refs, kasko_type)
        )

        assert response.status_code == 302, _form_errors(response)
        assert Policy.objects.get(policy_number="XXX-0001").insurance_type == (
            osago_type
        )

    def test_kv_above_cap_is_form_error_not_500(self, admin_client, refs, osago_type):
        response = admin_client.post(
            reverse(OSAGO_ADD_URL),
            osago_post(refs, osago_type, payment={"kv_rub": "1500.00"}),
        )

        assert response.status_code == 200
        assert not Policy.objects.filter(policy_number="XXX-0001").exists()
        assert "kv_rub" in str(_form_errors(response))

    def test_term_above_one_year_is_form_error(self, admin_client, refs, osago_type):
        response = admin_client.post(
            reverse(OSAGO_ADD_URL),
            osago_post(refs, osago_type, end_date="2027-02-01"),
        )

        assert response.status_code == 200
        assert not Policy.objects.exists()
        assert "end_date" in str(_form_errors(response))

    def test_payment_is_required(self, admin_client, refs, osago_type):
        data = osago_post(refs, osago_type, payment={"due_date": "", "amount": ""})

        response = admin_client.post(reverse(OSAGO_ADD_URL), data)

        assert response.status_code == 200
        assert not Policy.objects.exists()

    def test_add_page_renders_hidden_insurance_type(self, admin_client, osago_type):
        response = admin_client.get(reverse(OSAGO_ADD_URL))

        assert response.status_code == 200
        html = response.content.decode()
        assert 'type="hidden" name="insurance_type"' in html
        assert f'value="{osago_type.pk}"' in html
        assert 'name="franchise"' not in html
        assert "payment_schedule-0-insurance_sum" not in html

    def test_changing_existing_osago_payment(
        self, admin_client, refs, osago_type, policy_factory
    ):
        policy = policy_factory(
            insurance_type=osago_type,
            start_date=date(2026, 1, 15),
            end_date=date(2027, 1, 14),
            franchise=Decimal("0"),
            **refs,
        )
        payment = PaymentSchedule.objects.create(
            policy=policy,
            year_number=1,
            installment_number=1,
            due_date=date(2026, 1, 15),
            amount=Decimal("12000"),
            kv_rub=Decimal("1200"),
        )
        data = osago_post(
            refs,
            osago_type,
            payment={"paid_date": "2026-01-20"},
            policy_number=policy.policy_number,
        )
        data.update(_management("payment_schedule", 1, initial=1))
        data["payment_schedule-0-id"] = payment.pk
        data["payment_schedule-0-policy"] = policy.pk

        response = admin_client.post(
            reverse("admin:policies_osagopolicy_change", args=[policy.pk]), data
        )

        assert response.status_code == 302, _form_errors(response)
        payment.refresh_from_db()
        assert payment.paid_date == date(2026, 1, 20)


class TestKvAutoCalculation:
    def test_rate_is_linked_on_save(self, admin_client, refs, osago_type):
        CommissionRate.objects.create(
            insurer=refs["insurer"], insurance_type=osago_type, kv_percent=Decimal("8")
        )

        response = admin_client.post(
            reverse(OSAGO_ADD_URL),
            osago_post(refs, osago_type, payment={"kv_rub": "960.00"}),
        )

        assert response.status_code == 302, _form_errors(response)
        payment = PaymentSchedule.objects.get()
        assert payment.commission_rate.kv_percent == Decimal("8")
        assert payment.kv_rub == Decimal("960.00")


class TestRegularPolicySection:
    def test_empty_insurance_sum_is_form_error_not_500(
        self, admin_client, refs, kasko_type
    ):
        """Регрессия этапа 1: insurance_sum стал blank=True на уровне поля."""
        response = admin_client.post(
            reverse(POLICY_ADD_URL),
            kasko_post(refs, kasko_type, payment={"insurance_sum": ""}),
        )

        assert response.status_code == 200
        assert not Policy.objects.exists()
        assert "insurance_sum" in str(_form_errors(response))

    def test_regular_policy_still_saves(self, admin_client, refs, kasko_type):
        response = admin_client.post(
            reverse(POLICY_ADD_URL), kasko_post(refs, kasko_type)
        )

        assert response.status_code == 302, _form_errors(response)
        assert Policy.objects.get().payment_schedule.get().insurance_sum == (
            Decimal("3000000.00")
        )

    def test_osago_type_cannot_be_chosen(self, admin_client, refs, osago_type):
        response = admin_client.post(
            reverse(POLICY_ADD_URL),
            kasko_post(refs, osago_type, payment={"insurance_sum": ""}),
        )

        assert response.status_code == 200
        assert not Policy.objects.exists()
        assert "insurance_type" in str(_form_errors(response))

    def test_autocomplete_hides_osago(self, admin_client, osago_type, kasko_type):
        response = admin_client.get(
            reverse("admin:autocomplete"),
            {
                "app_label": "policies",
                "model_name": "policy",
                "field_name": "insurance_type",
                "term": "",
            },
        )

        names = [item["text"] for item in response.json()["results"]]
        assert kasko_type.name in names
        assert osago_type.name not in names


class TestSectionsSplit:
    @pytest.fixture
    def two_policies(self, policy_factory, refs, osago_type, kasko_type):
        osago = policy_factory(
            policy_number="OSAGO-1",
            insurance_type=osago_type,
            franchise=Decimal("0"),
            **refs,
        )
        kasko = policy_factory(policy_number="KASKO-1", insurance_type=kasko_type)
        return osago, kasko

    def test_changelists_are_split(self, admin_client, two_policies):
        regular = admin_client.get(reverse("admin:policies_policy_changelist"))
        osago = admin_client.get(reverse("admin:policies_osagopolicy_changelist"))

        assert "KASKO-1" in regular.content.decode()
        assert "OSAGO-1" not in regular.content.decode()
        assert "OSAGO-1" in osago.content.decode()
        assert "KASKO-1" not in osago.content.decode()

    def test_change_view_redirects_to_own_section(self, admin_client, two_policies):
        osago, kasko = two_policies

        to_osago = admin_client.get(
            reverse("admin:policies_policy_change", args=[osago.pk])
        )
        to_regular = admin_client.get(
            reverse("admin:policies_osagopolicy_change", args=[kasko.pk])
        )

        assert to_osago.status_code == 302
        assert to_osago.url == reverse(
            "admin:policies_osagopolicy_change", args=[osago.pk]
        )
        assert to_regular.url == reverse(
            "admin:policies_policy_change", args=[kasko.pk]
        )

    def test_regular_changelist_keeps_accept_import_button(self, admin_client):
        regular = admin_client.get(reverse("admin:policies_policy_changelist"))
        osago = admin_client.get(reverse("admin:policies_osagopolicy_changelist"))

        import_url = reverse("admin:policies_policy_import_accept")
        assert import_url in regular.content.decode()
        assert import_url not in osago.content.decode()


class TestPermissions:
    def _staff(self, *codenames):
        user = User.objects.create_user("limited", password="x", is_staff=True)
        user.user_permissions.set(
            Permission.objects.filter(
                content_type__app_label="policies", codename__in=codenames
            )
        )
        return user

    def test_policy_permissions_open_osago_section(self, client, osago_type):
        client.force_login(
            self._staff(
                "add_policy",
                "change_policy",
                "view_policy",
                "add_paymentschedule",
                "change_paymentschedule",
                "view_paymentschedule",
            )
        )

        assert client.get(reverse(OSAGO_ADD_URL)).status_code == 200
        assert (
            client.get(reverse("admin:policies_osagopolicy_changelist")).status_code
            == 200
        )

    def test_without_policy_permissions_osago_is_closed(self, client, osago_type):
        client.force_login(self._staff("view_paymentschedule"))

        assert client.get(reverse(OSAGO_ADD_URL)).status_code == 403
