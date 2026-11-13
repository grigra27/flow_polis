from html.parser import HTMLParser
from urllib.parse import urlencode, urlsplit

import pytest
from django.urls import reverse
from django.forms.models import model_to_dict


class PageLinks(HTMLParser):
    def __init__(self, response):
        super().__init__()
        self.by_class = {}
        self.feed(response.content.decode())

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "a" and "href" in attrs:
            for name in attrs.get("class", "").split():
                self.by_class.setdefault(name, []).append(attrs["href"])


@pytest.mark.django_db
def test_journals_remember_independent_origins(client, admin_user, sample_payment):
    client.force_login(admin_user)
    policy = sample_payment.policy
    policy.policy_number = "ДФА & +/42"
    policy.save()
    policies = reverse(
        "policies:list", query={"search": policy.policy_number, "page": 1}
    )
    payments = reverse("policies:payments", query={"status": "all", "page": 1})
    policy_tab = PageLinks(client.get(policies)).by_class["journal-record"][0]
    payment_tab = PageLinks(client.get(payments)).by_class["journal-record"][0]
    assert (
        client.get(payment_tab).context["back_url"]
        == f"{payments}#payment-{sample_payment.pk}"
    )
    assert (
        client.get(policy_tab).context["back_url"] == f"{policies}#policy-{policy.pk}"
    )
    assert client.get(payment_tab).context["back_label"] == "К журналу платежей"


@pytest.mark.django_db
def test_empty_last_page_after_record_leaves_filter(
    client, admin_user, sample_policy, monkeypatch
):
    from apps.policies.views import PolicyListView

    monkeypatch.setattr(PolicyListView, "paginate_by", 1)
    client.force_login(admin_user)
    sample_policy.pk = None
    sample_policy.save()
    listing = reverse("policies:list", query={"policy_uploaded": "false", "page": 2})
    link = PageLinks(client.get(listing)).by_class["journal-record"][0]
    detail = client.get(link)
    policy = detail.context["policy"]
    policy.policy_uploaded = True
    policy.save()
    back = client.get(detail.context["back_url"].split("#")[0])
    assert back.status_code == 200
    assert back.context["page_obj"].number == 1
    assert policy not in back.context["policies"]


@pytest.mark.django_db
def test_policy_editor_keeps_origin_only_for_return_to_card(
    client, admin_user, sample_policy
):
    from django.contrib import admin
    from django.test import RequestFactory
    from apps.policies.models import Policy

    client.force_login(admin_user)
    origin = reverse("policies:list", query={"branch": sample_policy.branch_id})
    card = reverse("policies:detail", args=[sample_policy.pk])
    response = client.get(card, {"journal": origin})
    edit = PageLinks(response).by_class["btn-warning"][0]
    request = RequestFactory().post(edit, {"_save_and_open_front": "1"})
    request.user = admin_user
    assert admin.site._registry[Policy].response_change(request, sample_policy).url == (
        card + "?" + urlencode({"journal": origin})
    )
    for invalid in ["https://example.org/policies/", "//example.org/", "/admin/"]:
        detail = client.get(card, {"journal": invalid})
        assert detail.context["back_url"] == reverse("policies:list")
        assert not urlsplit(PageLinks(detail).by_class["btn-warning"][0]).query


@pytest.mark.django_db
def test_full_payment_editor_round_trip(client, admin_user, sample_payment):
    client.force_login(admin_user)
    payment = sample_payment
    journal = reverse("policies:payments", query={"status": "all"})
    listing = PageLinks(client.get(journal)).by_class
    direct_edit = listing["btn-tbl-edit"][0]
    origin = f"{journal}#payment-{payment.pk}"
    assert client.get(direct_edit).context["payment_back_url"] == origin
    card = client.get(listing["journal-record"][0])
    edit = next(
        href
        for href in PageLinks(card).by_class["btn-warning"]
        if "/paymentschedule/" in href
    )
    response = client.get(edit)
    back = response.context["payment_back_url"]
    assert back == listing["journal-record"][0]
    assert response.content.decode().count("Вернуться без сохранения") == 2
    payload = {
        key: value
        for key, value in model_to_dict(payment).items()
        if value is not None and value is not False
    }
    payload.update(payment_info="Проверено", _save_and_open_front="1")
    invalid = client.post(edit, {**payload, "amount": ""})
    assert invalid.status_code == 200
    assert invalid.context["payment_back_url"] == back
    result = client.post(edit, payload)
    assert result.status_code == 302
    assert result.url == back
    payment.refresh_from_db()
    assert payment.payment_info == "Проверено"
    opened = client.get(result.url)
    assert opened.context["open_payment"] == str(payment.pk)
    assert opened.context["back_url"] == origin
    assert f'class="collapse show" id="payment-{payment.pk}"' in opened.content.decode()
    del payload["_save_and_open_front"]
    normal = client.post(edit, {**payload, "_save": "1"})
    assert normal.url == reverse("admin:policies_paymentschedule_changelist")


@pytest.mark.django_db
def test_direct_payment_editor_and_popup(client, admin_user, sample_payment):
    client.force_login(admin_user)
    edit = reverse("admin:policies_paymentschedule_change", args=[sample_payment.pk])
    back = client.get(edit).context["payment_back_url"]
    assert back == reverse(
        "policies:detail",
        args=[sample_payment.policy_id],
        query={"payment": sample_payment.pk},
        fragment=f"installment-{sample_payment.pk}",
    )
    popup = client.get(edit, {"_popup": "1"})
    assert "_save_and_open_front" not in popup.content.decode()
    assert "Вернуться без сохранения" not in popup.content.decode()


@pytest.mark.django_db
def test_osago_editor_has_front_save_button(
    client, admin_user, policy_factory, insurance_type_factory
):
    client.force_login(admin_user)
    policy = policy_factory(
        insurance_type=insurance_type_factory(name="ОСАГО", is_osago=True)
    )
    form = client.get(reverse("admin:policies_osagopolicy_change", args=[policy.pk]))
    assert 'name="_save_and_open_front"' in form.content.decode()
