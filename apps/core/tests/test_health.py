"""
H-13: живость web (gunicorn/Django) — эндпоинт /health/, probe_web() для
Docker healthcheck и проверка `web` в system_health_check.
H-04: проверка SOCKS5-туннеля до Telegram в system_health_check.
"""
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest
import requests

from apps.core.health import probe_web
from apps.core.management.commands.system_health_check import Command


@pytest.mark.django_db
def test_health_endpoint_is_anonymous_and_does_not_touch_db(
    client, django_assert_num_queries
):
    with django_assert_num_queries(0):
        response = client.get("/health/")

    assert response.status_code == 200
    assert response.content == b"ok"


class _Handler(BaseHTTPRequestHandler):
    status = 200
    body = b"ok"
    seen_headers = {}

    def do_GET(self):
        type(self).seen_headers = dict(self.headers)
        self.send_response(self.status)
        self.end_headers()
        self.wfile.write(self.body)

    def log_message(self, *args):
        pass


@pytest.fixture
def fake_web():
    def start(status=200, body=b"ok"):
        handler = type("Handler", (_Handler,), {"status": status, "body": body})
        server = HTTPServer(("127.0.0.1", 0), handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        servers.append(server)
        return handler, f"http://127.0.0.1:{server.server_port}/health/"

    servers = []
    yield start
    for server in servers:
        server.shutdown()
        server.server_close()


def test_probe_web_ok_sends_host_and_forwarded_proto(fake_web, monkeypatch):
    monkeypatch.setenv("ALLOWED_HOSTS", "polis.insflow.ru,other.example")
    handler, url = fake_web()

    ok, detail = probe_web(url=url)

    assert ok, detail
    assert handler.seen_headers["Host"] == "polis.insflow.ru"
    assert handler.seen_headers["X-Forwarded-Proto"] == "https"


def test_probe_web_server_error_is_not_ok(fake_web):
    _, url = fake_web(status=500, body=b"boom")

    ok, detail = probe_web(url=url)

    assert not ok
    assert "500" in detail


def test_probe_web_unexpected_body_is_not_ok(fake_web):
    _, url = fake_web(body=b"<html>login</html>")

    ok, _ = probe_web(url=url)

    assert not ok


def test_probe_web_nothing_listening_is_not_ok():
    server = HTTPServer(("127.0.0.1", 0), _Handler)
    port = server.server_port
    server.server_close()

    ok, detail = probe_web(url=f"http://127.0.0.1:{port}/health/", timeout=2)

    assert not ok
    assert "нет ответа" in detail


def test_check_web_maps_probe_result(monkeypatch):
    command = Command()

    monkeypatch.setattr(
        "apps.core.health.probe_web", lambda **kw: (True, "HTTP 200 ok")
    )
    assert command._check_web()["status"] == "healthy"

    monkeypatch.setattr("apps.core.health.probe_web", lambda **kw: (False, "timeout"))
    result = command._check_web()
    assert result["status"] == "critical"
    assert result["details"] == "timeout"


def test_check_telegram_proxy_skipped_when_not_configured(monkeypatch):
    monkeypatch.setenv("TELEGRAM_SOCKS5_PROXY", "")

    def fail(*args, **kwargs):
        raise AssertionError("не должно быть сетевого запроса")

    monkeypatch.setattr(requests, "get", fail)

    assert Command()._check_telegram_proxy()["status"] == "healthy"


def test_check_telegram_proxy_down_is_warning(monkeypatch):
    monkeypatch.setenv("TELEGRAM_SOCKS5_PROXY", "172.18.0.1:1080")

    def refused(*args, **kwargs):
        raise requests.exceptions.ConnectionError("connection refused")

    monkeypatch.setattr(requests, "get", refused)

    result = Command()._check_telegram_proxy()
    assert result["status"] == "warning"
    assert "172.18.0.1:1080" in result["details"]


def test_check_telegram_proxy_up_uses_socks5h(monkeypatch):
    monkeypatch.setenv("TELEGRAM_SOCKS5_PROXY", "172.18.0.1:1080")
    calls = []

    class Response:
        status_code = 302

    def fake_get(url, **kwargs):
        calls.append(kwargs["proxies"])
        return Response()

    monkeypatch.setattr(requests, "get", fake_get)

    result = Command()._check_telegram_proxy()
    assert result["status"] == "healthy"
    assert calls == [{"https": "socks5h://172.18.0.1:1080"}]
