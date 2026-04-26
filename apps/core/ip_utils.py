"""
Безопасное извлечение IP клиента из request'а.

PLAN 9 (b): раньше middleware читал HTTP_X_FORWARDED_FOR без проверки
кто именно его прислал. Атакующий мог подделать заголовок и заставить
систему записывать неудачные попытки логина на чужой IP — это и DoS-
вектор (можно забанить любой IP), и обход brute-force защиты (можно
бесконечно перебирать пароли, меняя поддельный X-Forwarded-For).

Теперь: X-Forwarded-For доверяется ТОЛЬКО когда непосредственный
peer (REMOTE_ADDR) — наш Nginx (внутренний docker-IP из приватных
RFC 1918 диапазонов или loopback). Иначе игнорируем заголовок и
используем REMOTE_ADDR как есть.
"""
import ipaddress
import logging

logger = logging.getLogger(__name__)

# Явный список trusted-сетей. НЕ полагаемся на ipaddress.is_private —
# Python 3.12 включает туда все RFC 5737 TEST-NET сети (203.0.113.0/24,
# 198.51.100.0/24 и т.п.), которые на практике могут быть публичными
# адресами клиентов. Здесь только то, через что реально приходит наш
# собственный трафик: RFC 1918 приватные + loopback + IPv6 ULA.
TRUSTED_PROXY_NETWORKS = [
    ipaddress.ip_network("10.0.0.0/8"),  # RFC 1918
    ipaddress.ip_network(
        "172.16.0.0/12"
    ),  # RFC 1918 (включая docker default 172.17/16)
    ipaddress.ip_network("192.168.0.0/16"),  # RFC 1918
    ipaddress.ip_network("127.0.0.0/8"),  # IPv4 loopback
    ipaddress.ip_network("::1/128"),  # IPv6 loopback
    ipaddress.ip_network("fc00::/7"),  # IPv6 unique-local (RFC 4193)
]


def _is_trusted_proxy(ip_str: str) -> bool:
    """
    True если ip_str принадлежит к доверенным сетям, через которые
    к нам приходит трафик: docker network (172.16/12), наш VPC (10/8,
    192.168/16), loopback.

    В нашей архитектуре Django сидит за Nginx в одной docker network,
    поэтому Nginx виден Django как 172.x.x.x. Любой публичный IP в
    REMOTE_ADDR значит что запрос пришёл напрямую к Django (минуя
    Nginx) — что нештатно и заголовку X-Forwarded-For нельзя верить.
    """
    try:
        ip = ipaddress.ip_address(ip_str)
    except (ValueError, TypeError):
        return False
    return any(ip in net for net in TRUSTED_PROXY_NETWORKS)


def get_client_ip(request) -> str:
    """
    Безопасно извлекает IP клиента из request'а.

    Returns:
        str — IP клиента, либо REMOTE_ADDR если X-Forwarded-For
        не заслуживает доверия. Никогда не возвращает None: при любых
        проблемах вернётся "0.0.0.0" (валидный IP, не вызовет crash в
        логировании или БД GenericIPAddressField).
    """
    remote_addr = request.META.get("REMOTE_ADDR") or "0.0.0.0"

    # Если непосредственный peer — не наш доверенный proxy, никаких
    # X-Forwarded-For не читаем (его мог поставить сам атакующий).
    if not _is_trusted_proxy(remote_addr):
        return remote_addr

    xff = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if not xff:
        return remote_addr

    # X-Forwarded-For = "client, proxy1, proxy2"
    # Берём правый-most IP, который НЕ trusted (тот что добавил последний наш
    # proxy перед нами). Если все trusted — фолбэк на REMOTE_ADDR.
    parts = [p.strip() for p in xff.split(",") if p.strip()]
    for candidate in reversed(parts):
        try:
            ipaddress.ip_address(candidate)  # валидация что это вообще IP
        except (ValueError, TypeError):
            continue
        if not _is_trusted_proxy(candidate):
            return candidate

    return remote_addr
