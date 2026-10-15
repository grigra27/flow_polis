"""
Полис ОСАГО из акцепта: тот же файл, что для КАСКО (в нём есть поле «ОСАГО»).

Вид страхования — всегда «ОСАГО», срок — год от даты начала (но не дольше
лизинга), один платёж без страховой суммы. Акцепт, разобранный для одного
раздела, не предзаполняет форму другого.
"""

from datetime import date

import pytest
from django.urls import reverse

from apps.insurers.models import InsuranceType
from apps.policies.models import PaymentSchedule, Policy
from apps.policies.services.accept_parser import parse_accept_file
from apps.policies.services.accept_resolver import (
    ACCEPT_IMPORT_SESSION_KEY,
    resolve_accept_data,
)
from apps.policies.tests.test_accept_import import make_accept_xls
from apps.policies.tests.test_osago_admin import _form_errors, osago_post

pytestmark = pytest.mark.django_db

IMPORT_URL = "admin:policies_osagopolicy_import_accept"


@pytest.fixture
def osago_type(db):
    return InsuranceType.objects.create(name="ОСАГО", is_osago=True)


@pytest.fixture
def refs(client_factory, branch_factory, insurer_factory, osago_type):
    return {
        "client": client_factory(client_name='ООО "АЛТЫН ЯР"', client_inn="1686035567"),
        "branch": branch_factory(branch_name="Казань"),
        "insurer": insurer_factory(),
    }


@pytest.fixture
def admin_client(client, admin_user):
    client.force_login(admin_user)
    return client


def resolve_osago(**overrides):
    parsed = parse_accept_file(make_accept_xls(**overrides), osago=True)
    return resolve_accept_data(parsed.data, parsed.warnings, osago=True)


class TestOsagoResolver:
    def test_prefills_osago_policy(self, refs):
        resolved = resolve_osago()

        initial = resolved.policy_initial
        assert initial["client"] == refs["client"].pk
        assert initial["policyholder"] == refs["client"].pk
        assert initial["branch"] == refs["branch"].pk
        assert initial["dfa_number"] == "20212-ГА-КЗ"
        assert initial["vin_number"] == "XDC732457S9003298"
        # Вид страхования форма ОСАГО подставляет сама.
        assert "insurance_type" not in initial
        assert resolved.resolved["insurance_type"]["label"] == "ОСАГО"

    def test_term_is_one_year_from_start(self, refs):
        resolved = resolve_osago()

        assert resolved.policy_initial["start_date"] == "2025-08-26"
        assert resolved.policy_initial["end_date"] == "2026-08-25"

    def test_term_is_capped_by_lease_end(self, refs):
        resolved = resolve_osago(**{"Дата окончания срока лизинга": "01.03.2026"})

        assert resolved.policy_initial["end_date"] == "2026-03-01"
        assert "до окончания лизинга" in resolved.resolved["term"]["label"]

    def test_leap_day_start(self, refs):
        resolved = resolve_osago(
            **{
                "Дата поставки / дата начала страхования": "29.02.2028",
                "Дата окончания срока лизинга": "01.01.2031",
            }
        )

        assert resolved.policy_initial["end_date"] == "2029-02-28"

    def test_single_payment_without_insurance_sum(self, refs):
        resolved = resolve_osago()

        assert resolved.payment_initial == {"due_date": "2025-08-26"}

    def test_no_kasko_only_warnings(self, refs):
        resolved = resolve_osago(
            **{
                "Необходимый вид страхования": "",
                "Дата окончания срока лизинга": "",
                "стоимость по ДКП, валюта": "",
            }
        )

        assert resolved.warnings == []
        assert resolved.policy_initial["end_date"] == "2026-08-25"

    def test_missing_start_date_warns(self, refs):
        resolved = resolve_osago(**{"Дата поставки / дата начала страхования": ""})

        assert "end_date" not in resolved.policy_initial
        assert "due_date" not in resolved.payment_initial
        assert any("Срок полиса ОСАГО не рассчитан" in w for w in resolved.warnings)

    @pytest.mark.parametrize("value", ["нет", ""])
    def test_osago_flag_not_yes_warns(self, refs, value):
        resolved = resolve_osago(**{"ОСАГО": value})

        assert any("в поле «ОСАГО»" in w for w in resolved.warnings)
        # Только предупреждение: форма всё равно предзаполняется.
        assert resolved.policy_initial["client"] == refs["client"].pk

    def test_existing_osago_for_dfa_warns(self, refs, osago_type):
        Policy.objects.create(
            policy_number="ХХХ 0000000001",
            dfa_number="20212-ГА-КЗ",
            client=refs["client"],
            insurer=refs["insurer"],
            branch=refs["branch"],
            insurance_type=osago_type,
            property_description="Кран",
            start_date=date(2025, 8, 26),
            end_date=date(2026, 8, 25),
        )

        resolved = resolve_osago()

        assert any("ХХХ 0000000001" in w for w in resolved.warnings)

    def test_kasko_mode_unchanged(self, refs, insurance_type_factory):
        kasko = insurance_type_factory(name="КАСКО")
        parsed = parse_accept_file(make_accept_xls())
        resolved = resolve_accept_data(parsed.data, parsed.warnings)

        assert resolved.policy_initial["insurance_type"] == kasko.pk
        assert resolved.policy_initial["end_date"] == "2028-08-20"
        assert resolved.payment_initial["insurance_sum"] == "12750000.00"
        assert resolved.osago is False


class TestOsagoAcceptAdminFlow:
    def _upload(self, admin_client, url_name=IMPORT_URL, **overrides):
        response = admin_client.post(
            reverse(url_name), {"accept_file": make_accept_xls(**overrides)}
        )
        assert response.status_code == 200
        token = list(admin_client.session[ACCEPT_IMPORT_SESSION_KEY])[-1]
        return response, token

    def test_preview_then_prefilled_osago_form(self, admin_client, refs):
        response, token = self._upload(admin_client)

        content = response.content.decode()
        assert Policy.objects.count() == 0
        assert "Проверка акцепта (ОСАГО)" in content
        assert "26.08.2025 – 25.08.2026" in content
        add_url = f"{reverse('admin:policies_osagopolicy_add')}?accept_token={token}"
        assert add_url.replace("&", "&amp;") in content or add_url in content

        form = admin_client.get(add_url)
        assert form.status_code == 200
        html = form.content.decode()
        assert 'value="20212-ГА-КЗ"' in html
        assert 'value="2026-08-25"' in html or "25.08.2026" in html
        assert "Данные из акцепта" in html
        assert "12750000" not in html  # стоимость ДКП не нужна ОСАГО

    def test_saving_prefilled_form_creates_osago(self, admin_client, refs, osago_type):
        _, token = self._upload(admin_client)
        data = osago_post(
            refs,
            osago_type,
            payment={"due_date": "2025-08-26"},
            dfa_number="20212-ГА-КЗ",
            start_date="2025-08-26",
            end_date="2026-08-25",
        )

        response = admin_client.post(
            f"{reverse('admin:policies_osagopolicy_add')}?accept_token={token}", data
        )

        assert response.status_code == 302, _form_errors(response)
        policy = Policy.objects.get()
        assert policy.is_osago
        assert PaymentSchedule.objects.get().insurance_sum is None

    def test_payload_of_other_section_is_ignored(self, admin_client, refs):
        _, osago_token = self._upload(admin_client)
        _, kasko_token = self._upload(
            admin_client, url_name="admin:policies_policy_import_accept"
        )

        kasko_form = admin_client.get(
            f"{reverse('admin:policies_policy_add')}?accept_token={osago_token}"
        )
        osago_form = admin_client.get(
            f"{reverse('admin:policies_osagopolicy_add')}?accept_token={kasko_token}"
        )

        for response in (kasko_form, osago_form):
            assert response.status_code == 200
            assert "Данные из акцепта" not in response.content.decode()

    def test_buttons(self, admin_client, refs):
        changelist = admin_client.get(
            reverse("admin:policies_osagopolicy_changelist")
        ).content.decode()
        assert reverse(IMPORT_URL) in changelist
        assert "Добавить из акцепта (ОСАГО)" in changelist

        journal = admin_client.get(reverse("policies:list")).content.decode()
        assert reverse(IMPORT_URL) in journal
        assert reverse("admin:policies_policy_import_accept") in journal

    def test_requires_add_permission(self, client, django_user_model, refs):
        client.force_login(
            django_user_model.objects.create_user("staff", password="x", is_staff=True)
        )

        assert client.get(reverse(IMPORT_URL)).status_code == 403
