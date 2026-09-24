# Production health audit и план улучшений

Дата: 2026-09-24. Сервер: `ssh polis` (Ubuntu 24.04.3, 2 ГБ RAM, 38 ГБ диск), приложение в `/root/insurance_broker`, Docker Compose `docker-compose.prod.yml` (v1, `docker-compose`).

Режим составления: только read-only. На сервере ничего не менялось, в коде ничего не менялось.

Связанный документ: [`prod-backup-improvement-backlog-2026-09-19.md`](./prod-backup-improvement-backlog-2026-09-19.md) — backlog по backup-контуру. Этот документ его не дублирует: пересекающиеся пункты ссылаются на ID оттуда (P0-xx / P1-xx / P2-xx). Новые задачи здесь имеют префикс **H** (health).

Обозначения: риск = Low / Medium / High; «downtime» = нужен ли остановочный перерыв (согласуется отдельно, непосредственно перед задачей).

---

## 0. Итог проверки (что в порядке)

| Проверка | Результат |
|---|---|
| Контейнеры | Все 7 `Up` (web, celery_worker, celery_beat, nginx, db, redis, certbot), `RestartCount=0`, последний деплой 2026-09-24 17:09 MSK |
| Соответствие кода | `rsync -rnc` от `git archive HEAD` (`692d295`) к `/root/insurance_broker`: **все tracked-файлы совпадают байт-в-байт**. Расхождения — только лишние файлы на сервере (см. H-11). Устаревших миграций/`.py`-модулей, которые Django мог бы подхватить, нет |
| Образы | `insurance_broker_web/celery_*:latest` собраны 2026-09-24 17:10, т.е. из текущего кода |
| Django | `check --deploy` — 0 issues; `makemigrations --check` — no changes; непримёненных миграций нет; Django 5.1.11 / Python 3.12.14; PySocks в контейнере есть |
| HTTP | `https://polis.insflow.ru/accounts/login/` → 200 за 0.06 с |
| TLS | Let's Encrypt до 2026-11-30, SAN: `polis.insflow.ru`, `www.polis.insflow.ru`; certbot-контейнер жив, nginx перечитывает сертификаты каждые 6 ч |
| Диск | `/` 19/38 ГБ (51 %), inode 16 % |
| Память | 1.3/1.9 ГБ, available 645 МБ, swap 245 МБ/2 ГБ; OOM-событий в `dmesg` нет. web ~300 МБ, worker ~180 МБ, beat ~100 МБ, db 30 МБ |
| БД | 28 МБ; 1158 полисов, 2412 платежей; 7 соединений |
| Бэкапы | DB — ежедневно 02:00, verified, `result=ok`; media — еженедельно; `system_health_check` видит свежесть обоих (P1-08 работает на проде) |
| Health-check | cron каждые 30 мин, статус `healthy` |
| Telegram | SOCKS5-туннель `tg-relay-tunnel.service` активен (`172.18.0.1:1080`, ufw разрешает только `172.18.0.0/16`); `getMe` через прокси — HTTP 200 / `ok:true` и из контейнера web, и с хоста (curl) |
| Логи | Django `RotatingFileHandler`; cron-логи под logrotate (`/etc/logrotate.d/insurance-broker`, P2-03); json-логи Docker с лимитом `max-size: 10m`, суммарно < 1 МБ |
| Безопасность | ufw активен, fail2ban активен; брутфорс-защита приложения срабатывает (38 CRITICAL «Brute force attack detected» за всю историю — всё сканеры) |

---

## 1. Разбор: вход через `www.polis.insflow.ru` (решено: оставить блокировку)

**Механизм.** `nginx/default.conf` принимает `www` (443-й server-блок отвечает на любой Host, сертификат покрывает www), но проксирует в Django с `proxy_set_header X-Forwarded-Host $server_name` — всегда `polis.insflow.ru`. В Django `USE_X_FORWARDED_HOST = True` (`config/settings.py:507`), `CSRF_TRUSTED_ORIGINS` пуст. Итог: любой POST с `Origin`/`Referer` = `https://www.polis.insflow.ru` получает 403 CSRF. GET при этом обслуживаются (302 на логин).

**Кто это.** Проверка 2026-09-24 по всему `django.log` (с 2025-12-22):

- 285 отказов с www-Origin/Referer, апрель → сентябрь 2026 (35 / 27 / 38 / 42 / 20 / 123 по месяцам).
- **Все 285 — `POST /`** (корень, а не форма логина). Ни одного отказа с www на `/accounts/login/`. Настоящий сотрудник, логинящийся на www, дал бы именно `Forbidden (...www...): /accounts/login/` — таких записей **0**.
- Запросы идут **пачками ровно по 7, 9 или 10 штук за 2–7 секунд** с интервалом 0.2–0.3 с, круглосуточно (00:43, 04:17, 05:28, 23:19 МСК) — поведение скрипта, не человека.
- Реальные сотрудники входят без проблем: 86 успешных входов за 30 дней (7 учётных записей, последний — 2026-09-24 21:58 МСК).
- Все 119 неуспешных попыток логина за 30 дней — с **пустым username**, 37 разных IP — сканеры.
- Независимо тот же вывод получен в P2-05 backlog'а (2026-09-23) по живым nginx-логам за 2 суток: все 403 — слепые `POST /` с ботовыми User-Agent.

**Решение.** Редирект `www → apex` **не делать** и `CSRF_TRUSTED_ORIGINS` **не заводить**: это ничего не даёт сотрудникам (они ходят без www) и только пропустило бы этот трафик дальше. Текущий 403 — желательное поведение.

**Что можно сделать дальше — H-01** (усилить, а не ослабить): не пускать www и чужие Host'ы в Django вообще, отрезав их на nginx.

---

## 2. Задачи

### H-01 — Отрезать `www` и неизвестные Host'ы на уровне nginx
- **Проблема:** сейчас www и прямые обращения по IP (`109.68.215.223` есть в `ALLOWED_HOSTS`) доходят до Django: тратят воркеры gunicorn, генерируют сотни WARNING'ов («no Referer», «CSRF cookie not set», «Origin checking failed — https://109.68.215.223», «chat.eliteserver.online» и т.п.), которые маскируют настоящие проблемы в логе.
- **Scope:**
  1. В `nginx/default.conf` добавить `default_server` для 80 и 443, отвечающий `return 444;` (закрыть соединение без ответа) — для любых Host, кроме `polis.insflow.ru`. Для 443 `default_server` нужен сертификат: можно использовать текущий (SAN включает www) либо `ssl_reject_handshake on;` (nginx ≥ 1.19.4 — есть 1.31.6).
  2. В основных server-блоках явный `server_name polis.insflow.ru;` уже есть — оставить.
  3. ACME-challenge для www: если www остаётся в сертификате, `location /.well-known/acme-challenge/` должен продолжить работать и для www на 80-м порту — либо **убрать www из сертификата** при следующем выпуске и удалить DNS-запись `www` (решение владельца, Q-1).
  4. Убрать `www.polis.insflow.ru` и `109.68.215.223` из `ALLOWED_HOSTS` в `.env.prod` (после п.1 они всё равно не доходят; оставлять — лишняя поверхность).
- **Не входит:** `CSRF_TRUSTED_ORIGINS`, редирект www.
- **Риск:** Medium (ошибка в nginx-конфиге = сайт недоступен; проверять `nginx -t` до reload). **Downtime:** нет (reload).
- **Acceptance:** `curl -H 'Host: www.polis.insflow.ru' https://109.68.215.223/` — соединение закрыто; `https://polis.insflow.ru/` — 200; certbot renew `--dry-run` проходит; через неделю WARNING'ов `Forbidden (...)` в `django.log` на порядок меньше.
- **Rollback:** вернуть `default.conf`, `nginx -s reload`.
- **Статус:** **реализовано, не задеплоено (2026-09-24).** Q-1 решён по умолчанию: www остаётся в DNS и сертификате, отсекается на nginx (удалить DNS-запись можно позже отдельно — конфиг от этого не зависит).
  - `nginx/default.conf`: два `default_server` (`server_name _`). 80 — `return 444`, но с `/.well-known/acme-challenge/` (продление www в SAN) и `location = /health/` (Docker healthcheck ходит с `Host: localhost`). 443 — `ssl_reject_handshake on` + `return 444`. Блоки `polis.insflow.ru` не менялись.
  - Проверено до коммита на временном `nginx:alpine` в сети `insurance_broker_frontend` с боевыми сертификатами, без публикации портов (прод не затронут; контейнер, образ curl и временный каталог удалены): `nginx -t` OK; apex `/accounts/login/` 200, apex `POST /` 403 (как раньше); SNI www и голый IP по https — handshake отклонён (curl exit 35); SNI apex + `Host: www` — 421; http www / IP — соединение закрыто (exit 52); http apex — 301; `/health/` с `Host: localhost` — 200; ACME для www и apex — 404 из webroot (т.е. доходит до certbot-каталога, не 444).
  - Тест `config/tests/test_nginx_host_filtering.py` — 5/5 (на старом конфиге 4 падают).
  - `.env.prod.example`: `ALLOWED_HOSTS=polis.insflow.ru`.
  - **Не сделано (нужно владельцу):** (1) ~~`.env.prod` на сервере~~ — **сделано 2026-09-24**: `ALLOWED_HOSTS=polis.insflow.ru` (было `polis.insflow.ru,www.polis.insflow.ru,109.68.215.223`), бэкап `.env.prod.bak-h01-20260924`; вступит в силу при пересоздании контейнеров деплоем (порядок безопасен: из-за `X-Forwarded-Host $server_name` Django и так всегда видит `polis.insflow.ru`); (2) push → деплой; (3) после деплоя: `docker-compose -f docker-compose.prod.yml run --rm certbot renew --dry-run`, `curl -sI https://polis.insflow.ru/` = 200, `curl -skI --resolve www.polis.insflow.ru:443:109.68.215.223 https://www.polis.insflow.ru/` — ошибка handshake, `docker ps` — nginx `healthy`; через неделю сравнить число `Forbidden (` в `django.log`.

### H-02 — 500 в админке при сохранении графика платежей (ValidationError из `save()`)
- **Проблема:** `PaymentSchedule.save()` (`apps/policies/models.py:479`) вызывает `full_clean()`, а `clean()` проверяет порядок дат относительно **уже сохранённых** платежей. В `PaymentScheduleInline` (`apps/policies/admin.py:68`) нет formset-валидации, поэтому:
  - при создании полиса `policy_id` на этапе проверки формы ещё `None` → `clean()` выходит рано → ошибка всплывает только в `save()` → **HTTP 500**;
  - при правке нескольких платежей сразу они сохраняются по одному, промежуточное состояние в БД нарушает порядок → **HTTP 500**, хотя итоговое состояние может быть корректным.
- **Случаи:** 2026-05-27 (`/admin/policies/policy/add/`), 2026-06-23 (policy 1100), 2026-08-28 (policy 1183), плюс ранние в апреле. Пользователь видит страницу ошибки, данные не сохраняются.
- **Scope:** `BaseInlineFormSet.clean()` для `PaymentScheduleInline`: проверять монотонность `due_date` / `paid_date` / `insurer_date` по **всему набору форм** (с учётом удаляемых строк), отдавать ошибку формы. В `save()` — не падать 500-кой на согласованном наборе (например, проверку порядка в модели выполнять только вне formset-контекста или валидировать итоговое состояние после сохранения всех строк в транзакции).
- **Не входит:** изменение самих правил валидации дат.
- **Риск:** Medium (центральная модель). **Downtime:** нет (обычный деплой).
- **Acceptance:** тесты: (a) новый полис с платежами в неверном порядке → ошибка формы, не 500; (b) перестановка дат двух существующих платежей в корректный итог → сохраняется; (c) некорректный итог → ошибка формы. В `django.log` нет новых `Internal Server Error: /admin/policies/policy/...`.
- **Rollback:** revert коммита.

### H-03 — Email-напоминания об оплатах не запускаются на проде
- **Проблема:** `apps/notifications/tasks.py` — `check_upcoming_payments` (7/3/1 день до даты) и `check_overdue_payments`. В `django_celery_beat.PeriodicTask` на проде только `celery.backend_cleanup`; в root crontab этих задач тоже нет; `CELERY_BEAT_SCHEDULE` в коде нет. Функция, описанная в CLAUDE.md, фактически не работает. SMTP при этом настроен (`EmailBackend=smtp`, `EMAIL_HOST` задан).
- **Scope:** решение владельца (Q-2): включить или признать неиспользуемой. Если включать — сначала проверить адресатов и содержание писем (`send_payment_reminder` / `send_overdue_notification`), объём просрочек (первый запуск `check_overdue_payments` отправит **все** исторические просрочки), затем создать `PeriodicTask` (миграцией данных или через admin) и описать в `docs/NOTIFICATIONS_PIPELINE.md`. Если не включать — удалить задачи или пометить как неиспользуемые и поправить CLAUDE.md.
- **Риск:** Medium (письма внешним получателям). **Downtime:** нет.
- **Acceptance:** есть письменное решение; при включении — первое письмо проверено вручную на тестовом адресе.

### H-04 — Подтвердить доставку в Telegram после включения SOCKS5-прокси и актуализировать документацию
- **Проблема:** с 2026-04-25 по 2026-09-24 06:00 Telegram был недоступен (`Network is unreachable` / curl timeout) — ежедневный дайджест, бэкапы и алерты уходили только в VK. Прокси задеплоен 2026-09-24 (`0f951e5`, `692d295`); связность проверена `getMe`, но реальная отправка сообщений cron'ом ещё не наблюдалась.
- **Scope:**
  1. 2026-09-25: проверить `logs/backup-db.log` (02:00) и `logs/daily-digest.log` (06:00) — нет `curl (28)` / `Network is unreachable`, есть успешная отправка в TG.
  2. Мониторинг туннеля: `tg-relay-tunnel.service` уже с `Restart=always` (5 с), но этого мало — добавить в `system_health_check` проверку доступности SOCKS-порта (иначе при падении туннеля TG снова молча отвалится).
  3. Обновить P1-06 / P1-10 backlog'а и `docs/NOTIFICATIONS_PIPELINE.md`: там зафиксировано «Telegram мёртв, VK — единственный канал» — теперь это не так.
- **Риск:** Low. **Downtime:** нет.

### H-05 — Media-бэкап превышает лимит Telegram (50 МБ > 45 МБ)
- **Проблема:** `backup-media.log` 2026-09-24: `File too large for Telegram (50 MB > 45 MB)` → архив уходит только в VK. После H-04 это станет единственным препятствием к доставке media в оба канала. Статус `offsite=-` — осознанно принятый владельцем риск (backlog, рев. 4), здесь не пересматривается.
- **Scope:** разбить архив на части (`split -b 45M`) с отправкой нескольких документов и инструкцией сборки, либо осознанно оставить media только в VK и понизить сообщение с ERROR до INFO.
- **Риск:** Low. **Downtime:** нет.
- **Acceptance:** в следующем еженедельном прогоне нет `ERROR File is already compressed and too large`.

### H-06 — Обновления ОС и отложенная перезагрузка
- **Проблема:** uptime 276 дней; `/var/run/reboot-required` существует; работает ядро `6.8.0-90`, установлены до `6.8.0-107`; `libc6` ждёт перезагрузки; `apt list --upgradable` — 76 пакетов, из них 7 security.
- **Scope:** окно обслуживания: свежий DB+media бэкап → `apt upgrade` → reboot → проверить автоподъём Docker-стека (`restart: unless-stopped`/`always` в compose), `tg-relay-tunnel.service`, cron, сайт, health-check. Затем удалить старые ядра (`apt autoremove`).
- **Риск:** Medium. **Downtime:** да, ~2–5 мин — согласовать.
- **Acceptance:** `uname -r` = последнее ядро; `reboot-required` отсутствует; все контейнеры `Up`; health-check `healthy`.

### H-07 — SSH: вход под root по паролю
- **Проблема:** `sshd -T`: `permitrootlogin yes`, `passwordauthentication yes`. fail2ban спасает от перебора, но не от утёкшего пароля. Порт 22 открыт для всех.
- **Scope:** убедиться, что вход по ключу работает для всех нужных ключей (включая `deploy_key` из GitHub Actions), затем `PasswordAuthentication no`, `PermitRootLogin prohibit-password`. Сохранить открытую сессию до проверки нового входа.
- **Риск:** Medium (можно потерять доступ — держать консоль Timeweb под рукой). **Downtime:** нет.
- **Acceptance:** `ssh -o PreferredAuthentications=password polis` отклоняется; деплой из CI проходит.

### H-08 — Порт 10050 (Zabbix agent) открыт для всего интернета
- **Проблема:** `ufw`: `10050/tcp ALLOW Anywhere`, слушает `zabbix_agentd` на `0.0.0.0`. Вероятно, мониторинг хостера Timeweb.
- **Scope:** выяснить, чей это агент (Q-3). Если хостера — ограничить ufw их адресами; если не используется — остановить и закрыть порт.
- **Риск:** Low. **Downtime:** нет.

### H-09 — Мусор Docker: ~19 ГБ reclaimable
- **Проблема:** `docker system df`: build cache 9.87 ГБ (8.95 reclaimable, 988 записей), images 10.23 ГБ (9.77 reclaimable), включая старый `insurance_broker-web:latest` (март 2026, имя от compose v2) и `hello-world`; 237 томов, из них **232 dangling** (анонимные тома, копящиеся при каждом деплое); остановленный контейнер `affectionate_matsumoto` (hello-world, 9 мес.). Это половина занятого диска.
- **Scope:** разово: `docker builder prune -af`, `docker image prune -af`, `docker volume prune -f` (перед этим убедиться, что именованные тома `insurance_broker_*` — `postgres_data`, `media_volume`, `static_volume`, redis — используются и не попадут под prune), `docker rm affectionate_matsumoto`. Постоянно: шаг очистки в `deploy.yml` после успешного деплоя (`docker image prune -f && docker builder prune -f --filter until=168h`) и выяснить, какой сервис порождает анонимные тома (вероятно `VOLUME` в образе без явного монтирования).
- **Риск:** Medium (`volume prune` — только после сверки списка томов). **Downtime:** нет.
- **Acceptance:** `docker system df` reclaimable < 2 ГБ; после следующего деплоя число dangling-томов не растёт.

### H-10 — systemd journal 3 ГБ
- **Проблема:** `journalctl --disk-usage` = 3.0 ГБ.
- **Scope:** `journalctl --vacuum-size=500M`; в `/etc/systemd/journald.conf` — `SystemMaxUse=500M`, `systemctl restart systemd-journald`.
- **Риск:** Low. **Downtime:** нет.

### H-11 — Деплой не удаляет файлы, исчезнувшие из репозитория
- **Проблема:** `deploy.yml` делает `rsync -avz` **без `--delete`**, поэтому на сервере копятся файлы, удалённые из git (включая удалённые в рамках P2-06):
  - корень: 22 `*.md` (`DEPLOYMENT_*`, `DOCKER_*`, `TELEGRAM_*`, `MIGRATION_GUIDE.md`, `POST_MIGRATION_CHECKLIST.md`, `SERVER_SETUP.md` и др.), `check_prod_readiness.py`, `create_superuser.py`, `fix_all_missing_commission_rates.py`, `fix_migration_conflict.sh`, `connect-droplet.sh`, `.env.dev.example`, `.env.local.postgres`, `.env.local.sqlite`, `.env.prod.db.example`;
  - `.claude/worktrees/lucid-cohen/` (копия рабочего дерева);
  - `apps/core/test_*.py` (5 старых тестов), `apps/analytics/templates/analytics/insurance_type_analytics.html`, `apps/billing/templates/billing/prolongation_placeholder.html`;
  - `templates/core/dashboard_v2.html`, `templates/includes/page_breadcrumb.html`, `templates/reports/*_help.html` (3 шт.);
  - `docs/`: 12 старых документов (`DEPLOYMENT.md`, `AUTHENTICATION.md`, `DROPLET_*`, `DNS_*`, `TELEGRAM_*` и др.);
  - `nginx/default.conf.ssl`, `scripts/` — 8 старых скриптов (`setup-ssl.sh`, `init-letsencrypt.sh`, `migrate-database.sh`, `verify-production.sh` и др.);
  - `.hypothesis/examples/` — ~290 файлов.
  Сейчас они не влияют на работу (миграций и импортируемых модулей среди них нет), но старый шаблон или скрипт может быть случайно использован, а удалённая из репо миграция **осталась бы на сервере и применилась**.
- **Scope:** разово удалить перечисленное (список сверить `rsync -rnc --delete` заново перед удалением); в `deploy.yml` добавить `--delete` с явными `--exclude` для всего, что живёт только на сервере: `.env.prod`, `.env.prod.db`, `certbot/`, `logs/`, `staticfiles/`, `media/`.
- **Риск:** High для `--delete` (ошибка в exclude = удаление `.env.prod`/сертификатов/логов) — сначала `--dry-run` в CI и ручная проверка вывода. **Downtime:** нет.
- **Acceptance:** повторный `rsync -rnc --delete` показывает 0 расхождений.

### H-12 — Мусор в git
- **Проблема:** в репозитории отслеживаются `.coverage` (110 КБ), `.hypothesis/` и пустой файл `Ожидается` в корне; всё это уезжает на прод.
- **Scope:** `git rm --cached .coverage .hypothesis Ожидается` (последний — просто удалить, если не нужен владельцу), добавить `.coverage` и `.hypothesis/` в `.gitignore`; дополнить `.dockerignore`.
- **Риск:** Low. **Downtime:** нет.

### H-13 — Нет реального healthcheck у web (Django)
- **Проблема:** в `docker-compose.prod.yml:84-85` написано «web monitored via nginx healthcheck instead», но healthcheck nginx (`wget http://localhost/health/`) попадает в `location /health/ { return 200 "healthy\n"; }` 80-го server-блока — **nginx отвечает сам, Django не проверяется**. Если gunicorn зависнет, Docker этого не увидит (частично покрывает cron `system_health_check`).
- **Scope:** healthcheck для web на Python без curl: `python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health/', timeout=5)"` (нужен лёгкий Django-endpoint `/health/`, не требующий логина и не ходящий в тяжёлые запросы), либо nginx `/health/` проксировать в Django.
- **Риск:** Low. **Downtime:** нет (рестарт web при деплое).
- **Acceptance:** `docker inspect insurance_broker_web` показывает `Health.Status=healthy`; при `docker pause` gunicorn → `unhealthy`.

### H-14 — nginx: предупреждение `ssl_stapling ignored`
- **Проблема:** `nginx: [warn] "ssl_stapling" ignored, no OCSP responder URL in the certificate` — Let's Encrypt прекратил OCSP в 2025, директивы бесполезны.
- **Scope:** удалить `ssl_stapling on; ssl_stapling_verify on;` (`nginx/default.conf:52-53`).
- **Риск:** Low. **Downtime:** нет (reload).

### H-15 — nginx: access-логи эфемерны и без Host; `nginx/nginx.conf` из репо не используется
- **Проблема:** `access.log` → `/dev/stdout` контейнера, при каждом деплое контейнер пересоздаётся — история теряется (на момент аудита — 3 часа). Это же ограничило разбор P2-05 и раздела 1. `nginx/nginx.conf` в репозитории **не монтируется** (compose монтирует только `default.conf`), работает дефолтный `nginx.conf` образа; в формате лога нет `$host`, поэтому www/IP-трафик в access-логе не отличить.
- **Scope:** смонтировать `nginx/nginx.conf` (или удалить его из репо, если он не нужен); добавить `$host` в `log_format`; писать access-лог в том `./logs/nginx/` с logrotate (дополнить `/etc/logrotate.d/insurance-broker`) либо поднять json-file `max-size`/`max-file` и не пересоздавать nginx без изменений.
- **Риск:** Low. **Downtime:** нет.

### H-16 — Redis: `vm.overcommit_memory = 0`
- **Проблема:** redis при старте: `WARNING Memory overcommit must be enabled!` — фоновое сохранение может падать при нехватке памяти (на хосте 2 ГБ RAM).
- **Scope:** `/etc/sysctl.d/99-redis.conf`: `vm.overcommit_memory = 1`, `sysctl --system`. Удобно совместить с H-06.
- **Риск:** Low. **Downtime:** нет.

### H-17 — Celery: `CPendingDeprecationWarning` про `broker_connection_retry`
- **Проблема:** worker при старте предупреждает, что в Celery 6 `broker_connection_retry` перестанет управлять повторами при старте.
- **Scope:** явно задать `CELERY_BROKER_CONNECTION_RETRY_ON_STARTUP = True` в `config/settings.py`.
- **Риск:** Low. **Downtime:** нет.

### H-18 — Разовая ошибка Postgres `database "insurance_broker" does not exist`
- **Проблема:** в логе db-контейнера одно `FATAL: database "insurance_broker" does not exist` после рестарта 2026-09-24 14:10 UTC. Боевая БД называется иначе; кто-то подключился с именем по умолчанию.
- **Scope:** найти источник: healthcheck db (`pg_isready -U postgres` — не создаёт FATAL), скрипты в `scripts/` (grep `insurance_broker` как имя БД), ручные команды. Если это скрипт — поправить имя БД.
- **Риск:** Low. **Downtime:** нет.

### H-19 — Память: 2 ГБ впритык
- **Проблема:** used 1.3/1.9 ГБ, в swap 245 МБ. Нет проблем сейчас, но экспорт больших Excel-отчётов или сборка образа во время деплоя на этом же хосте могут вызвать OOM.
- **Scope:** наблюдение: добавить в `system_health_check` порог по swap (если его нет); при росте — ограничить `--concurrency` celery worker и число gunicorn-воркеров либо расширить тариф.
- **Риск:** Low. **Downtime:** нет.

### H-20 — Актуализировать документацию
- **Проблема:**
  - `CLAUDE.md`: указаны Django 4.2 / Python 3.9 — фактически Django 5.1.11 / Python 3.12; ссылки на `docs/DEPLOYMENT.md` и `docs/AUTHENTICATION.md` ведут на удалённые файлы; описание `apps.notifications` не упоминает, что задачи не запланированы (H-03).
  - `docs/NOTIFICATIONS_PIPELINE.md`: «`daily_digest` … не нашёл записи … либо через системный cron, либо вручную» — фактически root crontab, 06:00 ежедневно; также правка по Telegram (H-04).
  - `docs/prod-backup-improvement-backlog-2026-09-19.md`, реестр: P1-05 и P1-08 значатся «реализовано, не задеплоено», но на проде уже работают — `backup-retention.sh` подключён обоими backup-скриптами, `system_health_check` выводит `Backup Media: fresh, result=ok`. Первый боевой прогон retention — понедельник 2026-09-28 04:00: проверить `logs/backup-cleanup.log` и закрыть задачи.
  - `docker-compose.prod.yml:84-85`: комментарий про «monitored via nginx» вводит в заблуждение (H-13).
- **Риск:** Low. **Downtime:** нет.

### H-21 — Наблюдение: исторические ошибки, которые должны больше не повторяться
Ошибки в `django.log`, последние вхождения которых старые; код, судя по всему, исправлен. Задача — раз в месяц убеждаться, что они не вернулись (например, отдельным пунктом в `daily_digest` или grep в health-check):

| Ошибка | Кол-во | Последний раз |
|---|---|---|
| `Error exporting insurer analytics: 'Insurer' object has no attribute 'get'` | 377 | 2025-12-29 |
| `Error generating dashboard charts: 'Insurer' object is not subscriptable` | 6 | 2025-12-30 |
| `daily_digest`: `'Insurer' object has no attribute 'name'` | 1 | 2025-12-23 |
| `daily_digest`: Telegram `HTTP 400 Bad Request` / `401 Unauthorized` | 5 | 2025-12-29 / 2026-01-30 |
| `Internal Server Error: /accounts/login/` (`MultiValueDictKeyError: 'next'` и др.) | 44 | 2026-04-19 |
| `Internal Server Error: /policies/payments/` (`Field 'id' expected a number but got '5?status=paid'`) | 1 | 2026-04-16 |
| `PaymentSchedule.clean()`: `Cannot use None as a query value` | 4 | 2026-09-14 — **исправлено** `d48f1a8` (P2-01) |

### H-22 — Справка: закрытые/проверенные пункты (без действий)
- **Ставка КВ Югория × КАСКО:** предупреждения `Commission rate not found … insurer=17, insurance_type=1` (последнее 2026-09-17) — **уже закрыто** в P2-02 (ставка 30 % добавлена 2026-09-23, проверено на проде: у insurer 17 есть ставки для типов 1–4). Новых предупреждений быть не должно — сверить в рамках H-21.
- **Брутфорс и сканеры:** `security.log` — 38 CRITICAL, 324 WARNING, все с пустым username/ботовыми UA; в nginx-логе — эксплойт-пробы (`/webadmin/tools/unixlogin.php`, `/backupmgt/...`) — получают 301/403. Действий не требуется; H-01 уменьшит шум.
- **CSRF-шум** («no Referer», «CSRF cookie not set», «Referer is insecure», чужие origins) — классифицирован в P2-05 как сканеры; подтверждено в разделе 1.

---

## 3. Вопросы владельцу

- **Q-1 (H-01):** оставить `www` в DNS и сертификате (с отсечением на nginx) или убрать запись `www` совсем?
- **Q-2 (H-03):** email-напоминания об оплатах нужны? Если да — кому они должны уходить?
- **Q-3 (H-08):** Zabbix-агент на 10050 — мониторинг Timeweb, который вы используете, или можно отключить?

## 4. Рекомендуемый порядок

1. **Сразу, без окна:** H-04 п.1 (проверка 25.09 утром), H-02 (реальные 500 у пользователей), H-12, H-14, H-17, H-20.
2. **После ответов владельца:** H-03, H-08. (H-01 — реализовано 2026-09-24.)
3. **Окно обслуживания (одно):** свежий бэкап → H-10 → H-09 → H-16 → H-06 (reboot) → H-07 → проверка всего стека.
4. **Инфраструктура деплоя:** H-11 (`--delete` с dry-run), H-13, H-15, H-05, H-04 п.2–3.
5. **Фоном:** H-18, H-19, H-21; 2026-09-28 — закрыть P1-05/P1-08 backlog'а (H-20).

## 5. Реестр

| ID | Тема | Приоритет | Риск | Downtime | Статус |
|---|---|---|---|---|---|
| H-01 | Отсечь www/IP на nginx | P2 | Medium | нет | реализовано, `.env.prod` обновлён, ждёт push/деплоя |
| H-02 | 500 в админке при сохранении графика платежей | **P1** | Medium | нет | открыто |
| H-03 | Email-напоминания не запланированы | P1 | Medium | нет | ждёт Q-2 |
| H-04 | Подтвердить Telegram через прокси + мониторинг туннеля + доки | P1 | Low | нет | открыто (проверка 2026-09-25) |
| H-05 | Media-бэкап > лимита Telegram | P3 | Low | нет | открыто |
| H-06 | Обновления ОС, reboot | P1 | Medium | **да** | открыто |
| H-07 | SSH root+пароль | P1 | Medium | нет | открыто |
| H-08 | Zabbix 10050 открыт всем | P2 | Low | нет | ждёт Q-3 |
| H-09 | Мусор Docker ~19 ГБ, 232 dangling-тома | P2 | Medium | нет | открыто |
| H-10 | journald 3 ГБ | P3 | Low | нет | открыто |
| H-11 | rsync без `--delete`, лишние файлы на сервере | P2 | High | нет | открыто |
| H-12 | `.coverage`/`.hypothesis`/`Ожидается` в git | P3 | Low | нет | открыто |
| H-13 | Нет реального healthcheck web | P2 | Low | нет | открыто |
| H-14 | `ssl_stapling` warning | P3 | Low | нет | открыто |
| H-15 | nginx-логи эфемерны, без `$host`; `nginx.conf` не смонтирован | P2 | Low | нет | открыто |
| H-16 | Redis overcommit | P3 | Low | нет | открыто |
| H-17 | Celery deprecation warning | P3 | Low | нет | открыто |
| H-18 | FATAL `database "insurance_broker" does not exist` | P3 | Low | нет | открыто |
| H-19 | Память 2 ГБ впритык | P3 | Low | нет | наблюдение |
| H-20 | Документация (CLAUDE.md, NOTIFICATIONS_PIPELINE, backlog, compose) | P2 | Low | нет | открыто |
| H-21 | Контроль невозврата исторических ошибок | P3 | Low | нет | наблюдение |
| H-22 | Справка: КВ Югория, брутфорс, CSRF-шум | — | — | — | закрыто |
