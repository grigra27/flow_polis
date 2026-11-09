import logging

import pytest

from apps.core.logging_filters import SensitiveDataFilter


@pytest.mark.parametrize(
    "endpoint",
    [
        "https://api.telegram.org/bot123456:example_bot_credential/sendMessage",
        "/bot123456:example_bot_credential/sendMessage",
    ],
)
@pytest.mark.parametrize("as_argument", [False, True])
def test_transport_endpoint_credentials_are_removed(endpoint, as_argument):
    record = logging.LogRecord(
        "apps.core.notifications",
        logging.ERROR,
        __file__,
        1,
        "Delivery failed: %s" if as_argument else "Delivery failed: " + endpoint,
        (endpoint,) if as_argument else (),
        None,
    )

    assert SensitiveDataFilter().filter(record)
    rendered = record.getMessage()
    assert "example_bot_credential" not in rendered
    assert "123456:" not in rendered
    assert "/bot***/sendMessage" in rendered


def test_staff_handoff_ticket_is_removed_from_request_line():
    record = logging.makeLogRecord(
        {
            "msg": "%s %s %s",
            "args": ("GET /flow/from-zs/?code=ticket-for-one-use HTTP/1.1", 302, 0),
        }
    )
    assert SensitiveDataFilter().filter(record)
    assert record.getMessage() == "GET /flow/from-zs/?code=*** HTTP/1.1 302 0"
