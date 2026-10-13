"""
Проверка живости gunicorn/Django изнутри web-контейнера (H-13).

Модуль намеренно не импортирует Django: он запускается Docker healthcheck'ом
как `python -m apps.core.health` каждые 30 секунд, и поднимать ради этого
settings/ORM незачем. Тот же `probe_web()` использует `system_health_check`,
чтобы зависание gunicorn доходило уведомлением в VK/Telegram, а не только
меняло статус контейнера в `docker ps`.

Запрос идёт на 127.0.0.1:8000 в обход nginx (nginx отвечает на /health/ сам
и Django не проверяет), поэтому вручную выставляем:
  • Host — первый из ALLOWED_HOSTS, иначе Django вернёт 400 DisallowedHost;
  • X-Forwarded-Proto: https — иначе SECURE_SSL_REDIRECT ответит 301.
"""
import os
import sys
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

WEB_HEALTH_URL = "http://127.0.0.1:8000/health/"


def _default_host():
    hosts = [h.strip() for h in os.environ.get("ALLOWED_HOSTS", "").split(",")]
    hosts = [h for h in hosts if h and h != "*"]
    return hosts[0].lstrip(".") if hosts else "localhost"


def probe_web(url=WEB_HEALTH_URL, host=None, timeout=5):
    """Возвращает (ok, описание). Исключений наружу не бросает."""
    request = Request(
        url,
        headers={"Host": host or _default_host(), "X-Forwarded-Proto": "https"},
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            body = response.read(64).decode("utf-8", "replace").strip()
            if response.status == 200 and body == "ok":
                return True, "HTTP 200 ok"
            return False, f"HTTP {response.status}: {body!r}"
    except HTTPError as e:
        return False, f"HTTP {e.code}"
    except (URLError, OSError) as e:
        return False, f"нет ответа: {getattr(e, 'reason', e)}"


if __name__ == "__main__":
    ok, detail = probe_web()
    print(detail)
    sys.exit(0 if ok else 1)
