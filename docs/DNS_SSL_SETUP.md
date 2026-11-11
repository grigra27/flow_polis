# DNS, SSL и Nginx

Сверено с [default.conf](../nginx/default.conf),
[nginx.conf](../nginx/nginx.conf), [Compose](../docker-compose.prod.yml) и
[media view](../apps/core/views.py) 2026-11-11. Объединены прежние руководства
по DNS/SSL, отдельный nginx/SSL_SETUP и разбор перезапуска Nginx.
Фактические DNS-записи и срок сертификата требуют проверки сервера.

## Домен и маршрутизация

Канонический адрес — `https://polis.insflow.ru/`. A/AAAA должны соответствовать
реальному адресу сервера; не добавляйте AAAA без работающего IPv6.
HTTP-запросы к каноническому домену перенаправляются на HTTPS, кроме ACME
и `/health/`. Webroot ACME — `/var/www/certbot` в контейнерах,
на хосте — `/root/insurance_broker/certbot/www`.

Для чужого Host Nginx закрывает HTTP соединение с кодом 444. Для неизвестного
SNI, включая `www.polis.insflow.ru`, TLS handshake отклоняется. Это намеренное
поведение, а не ошибка редиректа. Catch-all HTTP сохраняет ACME challenge:
старый сертификат/renewal может содержать www, хотя сайт по нему не открывается.
Решение по www зафиксировано в [бэклоге](BACKLOG.md); менять его для устранения
«ошибки сайта» не требуется.

## Сертификаты и продление

Nginx читает:

- `/etc/letsencrypt/live/polis.insflow.ru/fullchain.pem`;
- `/etc/letsencrypt/live/polis.insflow.ru/privkey.pem`.

Они берутся из host-каталога `certbot/conf`, смонтированного read-only в Nginx
и с записью в certbot. ACME webroot также общий. Certbot каждые 12 часов
выполняет `renew --webroot -w /var/www/certbot --quiet`; Nginx каждые 6 часов
перезагружает конфигурацию. Наличие loop не доказывает успешное продление.

Администратор может проверить состояние без вывода приватного ключа:

```bash
docker exec insurance_broker_certbot certbot certificates
docker exec insurance_broker_nginx nginx -t
docker logs --tail=100 insurance_broker_certbot
```

Проверка renewal с тестовым ACME:

```bash
docker exec insurance_broker_certbot certbot renew   --webroot -w /var/www/certbot --dry-run
```

Успех зависит от DNS, доступности порта 80, webroot и всех имён существующей
renewal-конфигурации. После изменения сертификата:
`docker exec insurance_broker_nginx nginx -s reload`.

На пустом сервере HTTPS-конфигурация не стартует без сертификата. Для первичной
выдачи администратор отдельно подготавливает временный HTTP/webroot или другой
согласованный ACME challenge, получает сертификат, затем возвращает проверенную
HTTPS-конфигурацию. Универсального скрипта `init-letsencrypt.sh` в репозитории
сейчас нет. [Подготовка сервера](DEPLOYMENT.md#первоначальное-развёртывание).

## Static и media

`/static/` обслуживается из общего `static_volume`, кеш — 30 дней.
Публичны только три каталога media:
`insurer_logos`, `branch_logos`, `insurance_type_icons`; кеш — 7 дней.

Остальные `/media/` проксируются в Django с проверкой входа и запретом кеширования
приватного ответа. Возвращать общий `alias /app/media/` для удобства нельзя:
это откроет документы без авторизации. Приватные файлы отдаёт Django после
проверки входа.

## Проверки при сбое

| Симптом | Проверка |
|---|---|
| Nginx перезапускается | `docker logs`, `nginx -t`, наличие и читаемость сертификатов, upstream web |
| 502 | Работает ли web и прямой Django health, сети и DNS сервиса `web` |
| Сертификат не продлевается | DNS всех SAN, порт 80, challenge webroot, лог certbot |
| www/IP не открывается | Сверить канонический домен; блокировка задана явно |
| Static отсутствует | Результат collectstatic и общий том web/Nginx |
| Документ требует входа | Ожидаемое поведение приватных media; проверять авторизованный запрос |

`/health/` Nginx отвечает сам. Проверка приложения —
`docker exec insurance_broker_web python -m apps.core.health`.
[Мониторинг](MONITORING.md) описывает остальные проверки.

## Применение конфигурации

Nginx-файлы защищены и сверяются по хешам в CI. Изменение в Git само по себе
не устанавливает их на хост; это отдельная административная операция.
После неё нужны `nginx -t`, reload и проверка HTTPS/входа/media.
[Деплой и protected hashes](DEPLOYMENT.md).
