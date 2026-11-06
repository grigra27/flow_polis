"""Rotation settings and Django's actual signing/session transition behavior."""

import importlib.util
import json
from pathlib import Path
import sys

import pytest
from django.core import signing
from django.test import Client, override_settings
from django.urls import reverse


OLD_KEY = "test-old-rotation-key-not-for-production"
NEW_KEY = "test-new-rotation-key-not-for-production"


def _load_settings_probe(monkeypatch, raw=None):
    monkeypatch.setenv("DEBUG", "True")
    monkeypatch.setenv("SECRET_KEY", NEW_KEY)
    if raw is None:
        monkeypatch.delenv("SECRET_KEY_FALLBACKS_JSON", raising=False)
    else:
        monkeypatch.setenv("SECRET_KEY_FALLBACKS_JSON", raw)
    path = Path(__file__).resolve().parents[1] / "settings.py"
    spec = importlib.util.spec_from_file_location(
        "secret_rotation_settings_probe", path
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_fallback_keys_default_to_empty(monkeypatch):
    assert _load_settings_probe(monkeypatch).SECRET_KEY_FALLBACKS == []


def test_fallback_keys_preserve_order_and_exact_key_text(monkeypatch):
    values = [OLD_KEY, " test-key-with-significant-spaces "]

    module = _load_settings_probe(monkeypatch, json.dumps(values))

    assert module.SECRET_KEY_FALLBACKS == values


@pytest.mark.parametrize(
    "raw",
    [
        "null",
        "{}",
        '"not-an-array"',
        "[123]",
        '[""]',
        '["   "]',
        '["test-old-key", true]',
        '["synthetic-secret-value-must-not-be-disclosed"',
    ],
)
def test_invalid_fallback_configuration_fails_without_echoing_values(monkeypatch, raw):
    with pytest.raises(ValueError) as caught:
        _load_settings_probe(monkeypatch, raw)

    assert str(caught.value) == (
        "SECRET_KEY_FALLBACKS_JSON must be a JSON array of non-empty strings"
    )
    assert raw not in str(caught.value)
    assert "synthetic-secret-value" not in repr(caught.value)


def test_pytest_fallback_configuration_does_not_read_dotenv(monkeypatch):
    import decouple

    original = decouple.config
    calls = []

    def dotenv_config(name, *args, **kwargs):
        calls.append(name)
        if name == "SECRET_KEY_FALLBACKS_JSON":
            return '["dotenv-key-must-be-ignored"]'
        return original(name, *args, **kwargs)

    monkeypatch.setattr(decouple, "config", dotenv_config)

    assert _load_settings_probe(monkeypatch).SECRET_KEY_FALLBACKS == []
    assert "SECRET_KEY_FALLBACKS_JSON" not in calls


def test_invalid_rotation_keys_fail_before_sentry_can_capture_startup_locals(
    monkeypatch,
):
    import sentry_sdk

    initialized = []
    monkeypatch.setattr(sentry_sdk, "init", lambda *a, **kw: initialized.append(True))
    with monkeypatch.context() as runtime:
        # Exercise the production import path, without real telemetry or secrets.
        runtime.delitem(sys.modules, "pytest")
        runtime.setattr(sys, "argv", ["rotation-settings-probe"])
        runtime.setenv("SENTRY_DSN", "https://public@example.invalid/1")
        with pytest.raises(ValueError):
            _load_settings_probe(runtime, '["synthetic-secret-to-hide"')

    assert initialized == []


def test_old_signatures_are_accepted_only_during_configured_grace_period(monkeypatch):
    fallbacks = _load_settings_probe(
        monkeypatch, json.dumps([OLD_KEY])
    ).SECRET_KEY_FALLBACKS
    payload = {"purpose": "rotation-regression"}
    old_signed = signing.dumps(payload, key=OLD_KEY)

    with override_settings(SECRET_KEY=NEW_KEY, SECRET_KEY_FALLBACKS=fallbacks):
        assert signing.loads(old_signed) == payload
        new_signed = signing.dumps(payload)
        with pytest.raises(signing.BadSignature):
            signing.loads(new_signed, key=OLD_KEY, fallback_keys=[])

    with override_settings(SECRET_KEY=NEW_KEY, SECRET_KEY_FALLBACKS=[]):
        with pytest.raises(signing.BadSignature):
            signing.loads(old_signed)


@pytest.mark.django_db
def test_active_session_migrates_but_inactive_old_session_expires_after_key_removal(
    settings, django_user_model
):
    settings.SECRET_KEY = OLD_KEY
    settings.SECRET_KEY_FALLBACKS = []
    user = django_user_model.objects.create_user(username="rotation-test-reader")
    active = Client()
    inactive = Client()
    active.force_login(user)
    inactive.force_login(user)
    old_session_key = active.cookies[settings.SESSION_COOKIE_NAME].value

    settings.SECRET_KEY = NEW_KEY
    settings.SECRET_KEY_FALLBACKS = [OLD_KEY]
    login_url = reverse("accounts:login")

    assert active.get(login_url).status_code == 302
    assert active.cookies[settings.SESSION_COOKIE_NAME].value != old_session_key

    settings.SECRET_KEY_FALLBACKS = []
    assert active.get(login_url).status_code == 302
    assert inactive.get(login_url).status_code == 200
