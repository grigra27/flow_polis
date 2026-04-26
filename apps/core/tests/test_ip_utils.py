"""
Тесты apps.core.ip_utils.get_client_ip.

PLAN 9 (b): X-Forwarded-For должен учитываться ТОЛЬКО когда непосредственный
peer (REMOTE_ADDR) — наш доверенный proxy (Nginx из приватной сети).
Иначе атакующий мог бы подменить заголовок и отравить наши логи /
заблокировать чужой IP через brute-force защиту.
"""
from types import SimpleNamespace

from apps.core.ip_utils import get_client_ip


def _request(remote_addr: str, xff: str = None):
    """Mini-request с нужным META."""
    meta = {"REMOTE_ADDR": remote_addr}
    if xff is not None:
        meta["HTTP_X_FORWARDED_FOR"] = xff
    return SimpleNamespace(META=meta)


def test_trusts_xff_when_peer_is_internal_docker_ip():
    """Запрос пришёл от Nginx (172.x в docker network) — XFF доверяем."""
    req = _request(remote_addr="172.18.0.5", xff="203.0.113.42")
    assert get_client_ip(req) == "203.0.113.42"


def test_trusts_xff_when_peer_is_loopback():
    """Локальная разработка (REMOTE_ADDR=127.0.0.1) — XFF доверяем."""
    req = _request(remote_addr="127.0.0.1", xff="203.0.113.99")
    assert get_client_ip(req) == "203.0.113.99"


def test_ignores_xff_when_peer_is_public_ip():
    """
    Если запрос пришёл напрямую к Django от публичного IP (минуя Nginx) —
    XFF мог быть подделан атакующим. Игнорируем.
    """
    req = _request(remote_addr="203.0.113.42", xff="1.2.3.4")
    assert get_client_ip(req) == "203.0.113.42"


def test_returns_remote_addr_when_no_xff():
    """Нет XFF — возвращаем REMOTE_ADDR как есть."""
    req = _request(remote_addr="172.18.0.5")
    assert get_client_ip(req) == "172.18.0.5"


def test_picks_rightmost_untrusted_in_xff_chain():
    """
    XFF: 'real_client, proxy1, proxy2'. Берём правый-most не-trusted IP —
    это тот, который добавил наш собственный proxy перед Django.
    """
    # 10.0.0.5 и 172.18.0.6 — trusted (внутренние). 203.0.113.42 — клиент.
    req = _request(remote_addr="172.18.0.5", xff="203.0.113.42, 10.0.0.5, 172.18.0.6")
    assert get_client_ip(req) == "203.0.113.42"


def test_handles_invalid_xff_gracefully():
    """XFF с мусором — не падаем, возвращаем REMOTE_ADDR."""
    req = _request(remote_addr="172.18.0.5", xff="not-an-ip, also garbage")
    assert get_client_ip(req) == "172.18.0.5"


def test_ipv6_xff_through_trusted_proxy():
    """IPv6 в XFF тоже работает."""
    req = _request(remote_addr="172.18.0.5", xff="2001:db8::1")
    assert get_client_ip(req) == "2001:db8::1"


def test_empty_remote_addr_falls_back():
    """REMOTE_ADDR пустой (странно, но возможно) — возвращаем 0.0.0.0."""
    req = _request(remote_addr="")
    assert get_client_ip(req) == "0.0.0.0"


def test_attacker_cannot_spoof_xff_to_become_other_user():
    """
    Главный security-сценарий: атакующий с публичным IP бьёт Django напрямую
    и шлёт X-Forwarded-For с IP жертвы. Раньше система записывала IP жертвы
    в LoginAttempt, и после 5 попыток жертва оказывалась заблокирована —
    DoS. Теперь записываем реальный IP атакующего.
    """
    # Атакующий, REMOTE_ADDR публичный
    req = _request(remote_addr="198.51.100.7", xff="8.8.8.8")  # 8.8.8.8 — "жертва"
    assert get_client_ip(req) == "198.51.100.7"
