"""Exercise the configured callback and real SDK delivery without network I/O."""

import importlib.util
from pathlib import Path
import socket
import sys

import decouple
from django.core.exceptions import DisallowedHost, PermissionDenied, SuspiciousOperation
import pytest
import sentry_sdk
from sentry_sdk.transport import Transport
from sentry_sdk.utils import event_from_exception


@pytest.fixture
def configured_before_send(monkeypatch):
    options = {}

    def fake_config(name, default=None, cast=None):
        values = {
            "DEBUG": True,
            "SECRET_KEY": "test-sentry-settings-not-for-production",  # pragma: allowlist secret
            "SENTRY_DSN": "https://public@example.invalid/1",
        }
        value = values.get(name, default)
        return cast(value) if cast else value

    def deny_network(*args, **kwargs):
        raise AssertionError("Sentry filter tests must not access the network")

    monkeypatch.setattr(socket.socket, "connect", deny_network)
    monkeypatch.setattr(socket, "create_connection", deny_network)
    with monkeypatch.context() as runtime:
        # Enter the real SDK initialization branch using synthetic configuration.
        runtime.delitem(sys.modules, "pytest")
        runtime.setattr(sys, "argv", ["sentry-filter-settings-probe"])
        runtime.setattr(decouple, "config", fake_config)
        runtime.setattr(sentry_sdk, "init", lambda **kwargs: options.update(kwargs))
        path = Path(__file__).resolve().parents[1] / "settings.py"
        spec = importlib.util.spec_from_file_location(
            "sentry_filter_settings_probe", path
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

    assert options["dsn"] == "https://public@example.invalid/1"
    return options["before_send"]


@pytest.mark.parametrize(
    "error",
    [
        ValueError("Cannot process policy data"),
        RuntimeError("Worker failed"),
        ConnectionRefusedError("Connection refused"),
    ],
    ids=["application-error", "worker-error", "real-network-failure"],
)
def test_configured_callback_preserves_real_errors(configured_before_send, error):
    event = {"message": "failure", "tags": {"source": "regression"}}

    assert (
        configured_before_send(event, {"exc_info": (type(error), error, None)}) is event
    )


@pytest.mark.parametrize(
    "error",
    [
        DisallowedHost("Unexpected host"),
        SuspiciousOperation("Rejected input"),
        PermissionDenied("No access"),
        BrokenPipeError("Broken pipe"),
        ConnectionResetError("CONNECTION RESET BY PEER"),
        RuntimeError("Request failed: client disconnected while reading"),
    ],
    ids=["host", "suspicious", "permission", "broken-pipe", "reset", "disconnect"],
)
def test_configured_callback_drops_known_noise(configured_before_send, error):
    event = {"message": "expected noise"}

    assert (
        configured_before_send(event, {"exc_info": (type(error), error, None)}) is None
    )


@pytest.mark.parametrize(
    "hint",
    [None, {}, {"exc_info": None}, {"exc_info": (None, None, None)}],
    ids=["no-hint", "empty-hint", "null-exception", "empty-exception-tuple"],
)
def test_configured_callback_preserves_events_without_exception(
    configured_before_send, hint
):
    event = {"message": "Worker reported an error", "level": "error"}

    assert configured_before_send(event, hint) is event


class MemoryTransport(Transport):
    def __init__(self):
        super().__init__()
        self.events = []

    def capture_envelope(self, envelope):
        self.events.append(envelope.get_event())


@pytest.mark.parametrize(
    "error, delivered",
    [
        (ValueError("Cannot process policy data"), True),
        (PermissionDenied("No access"), False),
        (BrokenPipeError("Broken pipe"), False),
        (None, True),
    ],
    ids=["real-error", "permission-noise", "connection-noise", "message-only"],
)
def test_registered_callback_controls_sdk_delivery(
    configured_before_send, error, delivered
):
    transport = MemoryTransport()
    client = sentry_sdk.Client(
        dsn="https://public@example.invalid/1",
        before_send=configured_before_send,
        transport=transport,
        default_integrations=False,
        auto_enabling_integrations=False,
        send_client_reports=False,
    )
    if error is None:
        event, hint = {"message": "Worker reported an error", "level": "error"}, {}
    else:
        event, hint = event_from_exception(error, client_options=client.options)
    event["tags"] = {"source": "sdk-regression"}

    try:
        event_id = client.capture_event(event, hint=hint)
    finally:
        client.close()

    assert bool(event_id) is delivered
    assert len(transport.events) == int(delivered)
    if delivered:
        captured = transport.events[0]
        assert captured["tags"]["source"] == "sdk-regression"
        if error is None:
            assert captured["message"] == "Worker reported an error"
        else:
            assert captured["exception"]["values"][0]["type"] == type(error).__name__
