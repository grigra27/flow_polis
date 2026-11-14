from html.parser import HTMLParser
from urllib.parse import parse_qs, urlsplit

import pytest
from django.urls import reverse

from apps.insurers.models import InfoTag
from apps.policies.filters import PolicyFilter
from apps.policies.models import Policy, PolicyInfo


pytestmark = pytest.mark.django_db


class Links(HTMLParser):
    def __init__(self, response):
        super().__init__()
        self.by_class = {}
        self.feed(response.content.decode())

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "a" and "href" in attrs:
            for css_class in attrs.get("class", "").split():
                self.by_class.setdefault(css_class, []).append(attrs["href"])


@pytest.mark.parametrize("field", [1, 2])
def test_tag_filter_matches_tag_and_field_on_the_same_record(
    policy_factory, insurance_type_factory, field
):
    kind = insurance_type_factory()
    selected = InfoTag.objects.create(name="Перенайм")
    different = InfoTag.objects.create(name="Аренда")
    matching = policy_factory(insurance_type=kind)
    wrong_slot = policy_factory(insurance_type=kind)
    for policy, tag, slot in [
        (matching, selected, field),
        (matching, different, 3 - field),
        (wrong_slot, selected, 3 - field),
        (wrong_slot, different, field),
    ]:
        PolicyInfo.objects.create(policy=policy, tag=tag, info_field=slot)

    filtered = PolicyFilter(
        {f"info{field}_tag": selected.pk}, queryset=Policy.objects.all()
    )
    assert list(filtered.qs) == [matching]


def test_two_tag_filters_require_both_fields_without_duplicate_policies(
    policy_factory, insurance_type_factory
):
    kind = insurance_type_factory()
    first = InfoTag.objects.create(name="Перенайм")
    second = InfoTag.objects.create(name="Изъятое")
    both = policy_factory(insurance_type=kind)
    only_first = policy_factory(insurance_type=kind)
    reversed_fields = policy_factory(insurance_type=kind)
    for policy, tag, field in [
        (both, first, 1),
        (both, second, 2),
        (both, second, 1),
        (only_first, first, 1),
        (reversed_fields, first, 2),
        (reversed_fields, second, 1),
    ]:
        PolicyInfo.objects.create(policy=policy, tag=tag, info_field=field)

    filtered = PolicyFilter(
        {"info1_tag": first.pk, "info2_tag": second.pk},
        queryset=Policy.objects.all(),
    )
    assert list(filtered.qs) == [both]


def test_tag_selection_is_visible_removable_and_survives_card_round_trip(
    client, django_user_model, sample_policy, policy_factory, monkeypatch
):
    from apps.policies.views import PolicyListView

    monkeypatch.setattr(PolicyListView, "paginate_by", 1)
    client.force_login(django_user_model.objects.create_user(username="reader"))
    tag = InfoTag.objects.create(name="Перенайм")
    second_policy = policy_factory(insurance_type=sample_policy.insurance_type)
    for policy in (sample_policy, second_policy):
        for field in (1, 2):
            PolicyInfo.objects.create(policy=policy, tag=tag, info_field=field)
    listing_url = reverse(
        "policies:list", query={"info1_tag": tag.pk, "info2_tag": tag.pk, "page": 2}
    )
    response = client.get(listing_url)
    assert response.status_code == 200
    for field in (1, 2):
        name = f"info{field}_tag"
        assert {
            "param": name,
            "label": f"Инфо {field}",
            "value": tag.name,
        } in response.context["active_filters"]
        assert str(response.context["filter"].form[name].value()) == str(tag.pk)
        assert f'name="{name}"' in response.content.decode()

    links = Links(response).by_class
    remaining_filters = [
        parse_qs(urlsplit(url).query) for url in links["pl-filter-chip-remove"]
    ]
    assert {"info1_tag": [str(tag.pk)]} in remaining_filters
    assert {"info2_tag": [str(tag.pk)]} in remaining_filters
    assert links["btn-pl-reset"] == [reverse("policies:list")]
    assert links["pl-clear-all"] == [reverse("policies:list")]

    page_one = next(
        url
        for url in links["pl-page-btn"]
        if parse_qs(urlsplit(url).query).get("page") == ["1"]
    )
    assert parse_qs(urlsplit(page_one).query) == {
        "info1_tag": [str(tag.pk)],
        "info2_tag": [str(tag.pk)],
        "page": ["1"],
    }
    card = client.get(links["journal-record"][0])
    assert card.context["back_url"] == (
        f"{listing_url}#policy-{card.context['policy'].pk}"
    )


@pytest.mark.parametrize("value", ["not-a-tag", "999999"])
def test_invalid_tag_does_not_crash_the_journal(client, django_user_model, value):
    client.force_login(django_user_model.objects.create_user(username="reader"))
    response = client.get(reverse("policies:list"), {"info2_tag": value})
    assert response.status_code == 200
    assert not list(response.context["policies"])
    assert response.context["filter"].form.errors["info2_tag"]
