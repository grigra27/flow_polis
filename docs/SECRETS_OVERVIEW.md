# Управление секретами: обзор архитектуры

Этот документ описывает **как устроена** работа с секретами в проекте — где что лежит, как одно с другим связано, какие есть слабые места. Это обзорный документ.

Связанные документы:
- `docs/ENVIRONMENT_VARIABLES.md` — справочник значений каждой переменной (что значит `SECRET_KEY`, какие у неё дефолты и т.д.).
- `docs/GITHUB_SECRETS_SETUP.md` — пошаговый how-to по настройке SSH-ключей в GitHub.
- `.env.example`, `.env.prod.example`, `.env.prod.db.example` — рабочие шаблоны.

---

## TL;DR

```
GitHub Secrets (4 ключа)         →  только SSH-доступ к серверу
                                    Никаких прикладных секретов

Сервер ~/insurance_broker/       →  .env.prod        — Django + всё
                                    .env.prod.db     — credentials Postgres
                                    certbot/conf/    — SSL-сертификаты (приватный ключ Let's Encrypt)

Локально (рядом с manage.py)     →  .env             — dev-значения разработчика
```

Все три слоя **независимы** — никто никуда автоматически ничего не копирует. Связи между ними нет.

Прикладные креды (DB_PASSWORD, SECRET_KEY, токены SMTP/Telegram/Sentry) **не проходят через GitHub** ни в каком виде. Они кладутся на сервер один раз руками и потом не трогаются — даже при деплое.

---

## Слой 1: GitHub Secrets — только инфра

Хранятся в `Settings → Secrets and variables → Actions` репозитория. Используются исключительно в `.github/workflows/deploy.yml` для SSH-входа на сервер.

| Secret | Зачем |
|--------|-------|
| `SSH_PRIVATE_KEY` | приватный ключ для входа на сервер от имени `DROPLET_USER` |
| `SSH_PORT` | порт SSH (если не 22) |
| `DROPLET_HOST` | IP или доменное имя сервера |
| `DROPLET_USER` | юзер на сервере (root или deploy) |

**Что НЕ хранится в GitHub Secrets**: `SECRET_KEY`, `DB_PASSWORD`, `EMAIL_HOST_PASSWORD`, `TELEGRAM_BOT_TOKEN`, `SENTRY_DSN`, `VK_COMMUNITY_TOKEN` — ничего из прикладного.

Это разумная схема: если кто-то получит доступ к репо или к workflow-логам — он не получит креды от прода. Минус — при добавлении нового сервера или ротации `SECRET_KEY` приходится лезть руками по SSH.

Настройка с нуля описана в `docs/GITHUB_SECRETS_SETUP.md`.

---

## Слой 2: На сервере — два `.env` файла + SSL

Лежит в `~/insurance_broker/` от имени `DROPLET_USER`.

### `.env.prod` — для Django (web, celery_worker, celery_beat)

Подключается через `env_file: .env.prod` в `docker-compose.prod.yml` для всех Django-контейнеров. Django читает эти переменные через `decouple.config(...)`.

**Обязательные** (без них Django не стартует — проверка в `config/settings.py:104-134`):
- `SECRET_KEY` (если равен дефолту `django-insecure-change-this-key` — fail на старте)
- `DEBUG=False`
- `ALLOWED_HOSTS=polis.insflow.ru,...`
- `DB_NAME`, `DB_USER`, `DB_PASSWORD` (host=`db`, port=5432 — внутри docker network)

**Опциональные** (есть defaults):
- Email: `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`, `EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_USE_TLS`
- Sentry: `SENTRY_DSN`, `SENTRY_RELEASE`
- Celery: `CELERY_BROKER_URL`, `CELERY_RESULT_BACKEND` (по умолчанию `redis://redis:6379/0`)
- Telegram: `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `TELEGRAM_ENABLED`, `TELEGRAM_ERROR_RATE_LIMIT`, `TELEGRAM_*_LIMIT`
- VK: `VK_COMMUNITY_TOKEN`, `VK_USER_ID`, `VK_ENABLED`
- Backups: `BACKUP_BASE_DIR`, `BACKUP_DB_DIR`, `BACKUP_MEDIA_DIR`
- HTTPS: `SECURE_SSL_REDIRECT`, `SECURE_HSTS_SECONDS`

Полный референс — `docs/ENVIRONMENT_VARIABLES.md`.

### `.env.prod.db` — только для контейнера Postgres

3 ключа, читаются образом `postgres:15-alpine` напрямую при инициализации БД:
- `POSTGRES_DB` — имя БД
- `POSTGRES_USER` — суперюзер БД
- `POSTGRES_PASSWORD` — пароль

**Критично**: эти три значения **должны совпадать** с `DB_NAME` / `DB_USER` / `DB_PASSWORD` в `.env.prod` — иначе Django не подключится. Никакой синхронизации нет, это руками.

### `certbot/conf/live/<домен>/` — SSL-материал

- `privkey.pem` — приватный ключ TLS-сертификата Let's Encrypt. **Это полноценный секрет**: утечка = MITM на твоём домене.
- `fullchain.pem`, `cert.pem`, `chain.pem` — публичные сертификаты, не секрет.

Создаётся при первой инициализации через `./scripts/init-letsencrypt.sh` или certbot руками. Автоматически обновляется certbot'ом.

### Как они туда попадают и что их защищает

В `.github/workflows/deploy.yml` rsync явно исключает три пути:
```bash
--exclude='.env.prod'
--exclude='.env.prod.db'
--exclude='certbot/'
```

То есть:
- Деплой **никогда не перезаписывает** эти файлы.
- Следующий шаг workflow **проверяет** наличие `.env.prod` и `.env.prod.db` и фейлит сборку, если их нет.
- Первичная установка — руками: `ssh user@server`, создать оба файла на основе `.env.prod*.example`, выставить `chmod 600`.
- Ротация любого секрета — тоже руками: `ssh`, отредактировать, `docker compose restart`.

### Что ещё на сервере по сути является секретом

Не файл-конфиг, но всё равно влияет:
- **Docker volume `postgres_data`** — физические данные БД (включая хеши паролей пользователей Django).
- **`~/.ssh/authorized_keys`** на сервере — контролирует, кто вообще может зайти и прочитать всё перечисленное выше.
- **Бэкапы в `/root/insurance_broker_backups/`** (смонтированы в контейнер web как `/app/server_backups:ro`) — содержат снэпшоты БД.

---

## Слой 3: Локально, у разработчика

`.env` рядом с `manage.py`. Создаётся руками на основе `.env.example`. Используется и при `python manage.py runserver`, и при `docker compose up` (через `env_file: .env` в `docker-compose.yml`).

Минимум для запуска:
- `SECRET_KEY` — можно дефолт `django-insecure-...`, потому что при `DEBUG=True` проверка не срабатывает
- `DEBUG=True`
- `ALLOWED_HOSTS=localhost,127.0.0.1`
- `DB_NAME=` (пустой → автоматически SQLite через `db.sqlite3`) ИЛИ полный набор `DB_*` (если разработчик импортировал прод-БД через `scripts/import_prod_db.sh`)

Опциональные блоки (Telegram, VK, SMTP) обычно отключены или ведут на песочничные боты.

---

## Карта код ↔ ENV

Все секреты читаются через `decouple.config("KEY", default=...)`:

| Где читается | Какие ключи |
|------|-------|
| `config/settings.py` | `SECRET_KEY`, `DEBUG`, `ALLOWED_HOSTS`, `DB_*`, `EMAIL_*`, `CELERY_*`, `SENTRY_*`, `SECURE_SSL_REDIRECT`, `SECURE_HSTS_SECONDS`, `BACKUP_*` |
| `apps/core/telegram_handler.py` | `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `TELEGRAM_ENABLED`, `TELEGRAM_ERROR_RATE_LIMIT`, `TELEGRAM_*_LIMIT` |
| `apps/core/vk_handler.py` | `VK_COMMUNITY_TOKEN`, `VK_USER_ID`, `VK_ENABLED` |

### Особенность: тестовая обёртка `get_runtime_config`

В `config/settings.py` есть функция `get_runtime_config(name, default)`. Для DB-настроек она используется вместо прямого `decouple.config`.

Поведение:
- В тестах (`RUNNING_TESTS = True`) читает напрямую из `os.environ`, **минуя `.env`**. Это нужно, чтобы локальный `.env` разработчика не влиял на pytest.
- В обычном режиме — через `decouple.config`, который читает `.env` или env vars процесса.

`RUNNING_TESTS = "test" in sys.argv or "pytest" in sys.modules` — срабатывает и для `manage.py test`, и для pytest.

---

## Слабые места схемы

1. **Дублирование `DB_PASSWORD` ↔ `POSTGRES_PASSWORD`** между двумя файлами на сервере. Никакой проверки, что они совпадают — рассинхрон даст `password authentication failed` с диагностикой только в логах контейнера.
2. **Первичная установка только руками по SSH.** Нет чек-листа в репо, приходится копировать `.env.prod.example` и заполнять. Велик риск забыть один ключ.
3. **Нет ротации.** Если `SECRET_KEY` утечёт — это `ssh`, `vim`, `docker compose restart`. Никакого audit log, никакой проверки «давно ли менял».
4. **Шаблоны `.env.prod.example` содержат placeholder-значения** (типа `your-secret-key-here-change-this-...`). Pre-commit hook `detect-secrets` исключает их через regex (`.pre-commit-config.yaml:11-13`), а сами `.env.prod*` лежат в `.gitignore` — но человеческий фактор остаётся.
5. **GitHub Secrets защищены минимально.** `SSH_PRIVATE_KEY` даёт root-доступ к серверу, где лежат **все** прикладные секреты в открытом виде. Утечка одного ключа = утечка всего.
6. **`SENTRY_DSN` — формально не секрет, но содержит project ID.** В трейсах Sentry видна привязка к проекту.
7. **Если `.env` лежит в синхронизируемой папке** (Yandex.Disk, iCloud, Dropbox) — он размножается на все устройства разработчика и в облако. Допустимо только если там dev-only креды и `DEBUG=True` SECRET_KEY.

---

## Что меняется в CI после ввода тестов (PLAN.md, пункт 1)

Новый job `test` в workflow получает **фейковые** значения через `env:` блок прямо в YAML:
```yaml
SECRET_KEY: ci-test-secret-key-not-for-production  # pragma: allowlist secret
DEBUG: "True"
ALLOWED_HOSTS: localhost,127.0.0.1
```

Это нужно только чтобы импорт `config.settings` не упал на проверке prod-варианта. Сами тесты используют `config.test_settings` с SQLite, поэтому DB_*/SMTP/Telegram креды им не нужны.

---

## Кратко: «что вносится руками»

| Слой | Что вносится | Когда | Кем |
|------|--------------|-------|-----|
| GitHub Secrets | 4 SSH-ключа | один раз при настройке репо | владелец репо |
| Сервер `.env.prod` | ~25 переменных приложения | один раз при первой установке + при ротации | админ через SSH |
| Сервер `.env.prod.db` | 3 переменные Postgres | один раз; должны совпадать с DB_* в `.env.prod` | админ через SSH |
| Сервер `certbot/conf/` | SSL приватный ключ | автоматически certbot'ом, обновляется тоже автоматически | certbot |
| Локально `.env` | те же ~25 переменных, но dev-значения | каждый разработчик у себя | сам разработчик |

В CI/CD pipeline ничего из прикладных секретов не задействовано.
