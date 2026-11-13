from html.parser import HTMLParser
from urllib.parse import urlencode, urlsplit

import pytest
from django.urls import reverse


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
