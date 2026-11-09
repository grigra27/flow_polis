import secrets
from urllib.parse import parse_qs, urlsplit
from unittest.mock import patch

import pytest
from django.test import Client
from django.urls import reverse


@pytest.mark.django_db
def test_two_login_tabs_keep_their_own_summary_and_ignore_foreign_continuations(
    client, admin_user, settings
):
    settings.FLOW_HANDOFF_ENABLED = True
    landing = reverse("flow_policy_landing")
    codes = ["first-opaque-code", "second-opaque-code"]
    continuations = [client.get(landing, {"code": code}).url for code in codes]
    assert continuations[0] != continuations[1]
    logins = [client.get(url).url for url in continuations]
    for login, continuation in zip(logins, continuations):
        assert parse_qs(urlsplit(login).query)["next"] == [continuation]
        assert not any(code in login or code in continuation for code in codes)

    foreign = Client()
    foreign.force_login(admin_user)
    assert foreign.get(continuations[1]).status_code == 409

    login_password = secrets.token_urlsafe(24)
    admin_user.set_password(login_password)
    admin_user.save()
    result = client.post(
        reverse("accounts:login"),
        {
            "username": admin_user.username,
            "password": login_password,
            "next": continuations[1],
        },
    )
    assert result.url == continuations[1]
    # The already open login in the first tab also returns to its own handoff.
    assert client.get(logins[0]).url == continuations[0]
    snapshots = {
        code: {
            "summary_id": i,
            "source_object_count": 1,
            "dfa_number": "",
            "offers": [],
            "variant": None,
        }
        for i, code in enumerate(codes, start=1)
    }
    with patch(
        "apps.policies.flow_views.flow_client.exchange_ticket",
        side_effect=snapshots.__getitem__,
    ) as exchange:
        for i in [1, 0]:
            response = client.get(continuations[i])
            draft_key = response.url.rstrip("/").rsplit("/", 1)[-1]
            assert (
                client.session["flow_policy_drafts"][draft_key]["snapshot"][
                    "summary_id"
                ]
                == i + 1
            )
        assert [call.args[0] for call in exchange.call_args_list] == list(
            reversed(codes)
        )
        assert client.get(continuations[1]).status_code == 409


@pytest.mark.django_db
def test_pending_handoffs_are_bounded(client, settings):
    settings.FLOW_HANDOFF_ENABLED = True
    landing = reverse("flow_policy_landing")
    for i in range(11):
        response = client.get(landing, {"code": f"test-{i}"})
        if i == 0:
            oldest = response.url
    assert client.get(oldest).status_code == 409
    assert client.get(response.url).url.startswith(reverse("accounts:login"))
