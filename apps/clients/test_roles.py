from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.clients.models import Client
from apps.insurers.models import Branch, InsuranceType, Insurer
from apps.policies.models import Policy


pytestmark = pytest.mark.django_db


@pytest.fixture
def role_portfolio(client, django_user_model):
    client.force_login(django_user_model.objects.create_user("role_reader"))
    company = Client.objects.create(client_name="Компания в двух ролях")
    other = Client.objects.create(client_name="Другой лизингополучатель")
    kind = InsuranceType.objects.create(name="КАСКО")
    osago = InsuranceType.objects.create(name="ОСАГО", is_osago=True)
    insurer = Insurer.objects.create(insurer_name="Страховщик")
    branch = Branch.objects.create(branch_name="Филиал")
    today = timezone.localdate()

    def contract(number, lessee, holder, insurance_type=kind):
        return Policy.objects.create(
            policy_number=number,
            client=lessee,
            policyholder=holder,
            insurer=insurer,
            insurance_type=insurance_type,
            branch=branch,
            property_description="Тестовый объект",
            start_date=today - timedelta(days=30),
            end_date=today + timedelta(days=60),
        )

    return {
        "company": company,
        "other": other,
        "lessee": contract("LESSEE-ONLY", company, other),
        "holder": contract("HOLDER-ONLY", other, company),
        "both": contract("BOTH-ROLES", company, company),
        "osago": contract("HOLDER-OSAGO", other, company, osago),
        "unrelated": contract("UNRELATED", other, other),
    }


@pytest.mark.parametrize("query", ["", "?role=lessee", "?role=unknown"])
def test_company_defaults_to_lessee_role(client, role_portfolio, query):
    data = role_portfolio
    response = client.get(reverse("clients:detail", args=[data["company"].pk]) + query)
    assert response.status_code == 200
    assert response.context["client_role"] == "lessee"
    assert {p.pk for p in response.context["policies"]} == {
        data["lessee"].pk,
        data["both"].pk,
    }
    assert response.context["client_role_counts"] == {
        "lessee": 2,
        "policyholder": 3,
    }
    assert response.context["client_role_policy_count"] == 2
    assert response.context["client_overview"]["total_policies"] == 2
    assert response.context["client_overview"]["osago_policies"] == 0
    assert 'href="?role=lessee" aria-current="page"' in response.content.decode()


def test_policyholder_tab_shows_its_contracts_and_preserves_osago_counts(
    client, role_portfolio
):
    data = role_portfolio
    response = client.get(
        reverse("clients:detail", args=[data["company"].pk]) + "?role=policyholder"
    )
    assert response.status_code == 200
    policies = list(response.context["policies"])
    assert len(policies) == 3
    assert {p.pk for p in policies} == {
        data["holder"].pk,
        data["both"].pk,
        data["osago"].pk,
    }
    assert response.context["client_role_policy_count"] == 3
    assert response.context["client_role_label"] == "Страхователь"
    overview = response.context["client_overview"]
    assert overview["total_policies"] == 2
    assert overview["active_policies"] == 2
    assert overview["osago_policies"] == 1
    html = response.content.decode()
    assert 'href="?role=policyholder" aria-current="page"' in html
    assert "ещё ОСАГО: 1" in html
    assert data["other"].client_name in html
    assert (reverse("clients:detail", args=[data["other"].pk]) + "?role=lessee") in html
    assert html.count('class="record-number"') == 3
    assert "LESSEE-ONLY" not in html
    assert "UNRELATED" not in html


@pytest.mark.parametrize(
    "role,label", [("lessee", "лизингополучателя"), ("policyholder", "страхователя")]
)
def test_empty_company_roles_have_correct_labels(client, role_portfolio, role, label):
    company = Client.objects.create(client_name="Компания без полисов")
    response = client.get(
        reverse("clients:detail", args=[company.pk]) + f"?role={role}"
    )
    assert response.status_code == 200
    assert response.context["client_role_counts"] == {
        "lessee": 0,
        "policyholder": 0,
    }
    assert f"У компании пока нет полисов в роли {label}" in response.content.decode()


def test_policyholder_only_company_can_open_its_contracts(client, role_portfolio):
    data = role_portfolio
    company = Client.objects.create(client_name="Только страхователь")
    Policy.objects.filter(pk=data["holder"].pk).update(policyholder=company)
    url = reverse("clients:detail", args=[company.pk])
    default = client.get(url)
    assert list(default.context["policies"]) == []
    response = client.get(url + "?role=policyholder")
    assert [p.pk for p in response.context["policies"]] == [data["holder"].pk]
    assert response.context["client_role_counts"] == {
        "lessee": 0,
        "policyholder": 1,
    }
