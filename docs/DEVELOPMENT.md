# Локальная разработка

Сверено с кодом 2026-11-11. Источники: [settings.py](../config/settings.py),
[Dockerfile.dev](../Dockerfile.dev), [docker-compose.yml](../docker-compose.yml),
[pytest.ini](../pytest.ini), [requirements.txt](../requirements.txt).
Карта приложений находится в [архитектуре](architecture.md).

## Python и окружение

Нужны Python 3.12 и зависимости из `requirements.txt`.

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Создайте `.env` из `.env.example`, только если локального файла ещё нет.
При `DEBUG=True` и пустом `DB_NAME` используется SQLite `db.sqlite3`.
При непустом `DB_NAME` Django выбирает PostgreSQL даже в режиме разработки.
Не используйте production-секреты для обычного локального запуска.

```bash
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

Начальные справочники `fixtures/initial_data.json` загружаются только в новую
пустую базу после миграций. Они не создают пользователей и полисы.
Импорт рабочей копии БД: [DATABASE_GUIDE.md](DATABASE_GUIDE.md).

## Docker для разработки

В `docker-compose.yml` четыре сервиса: `web`, `redis`, `celery_worker`,
`celery_beat`. **Сервиса `db` здесь нет.** Исходники смонтированы в `/app`,
работает Django runserver, `DEBUG=True` задан в Compose.

Перед запуском для фоновых задач внутри Docker задайте в локальном `.env`:

```dotenv
CELERY_BROKER_URL=redis://redis:6379/0
CELERY_RESULT_BACKEND=redis://redis:6379/0
```

Затем запустите стек:

```bash
docker compose up -d --build
docker compose exec web python manage.py migrate
docker compose exec web python manage.py createsuperuser
docker compose logs --tail=100 web celery_worker
```

Web доступен на `localhost:8000`, Redis — на `localhost:6379`.
При запуске Python на хосте используется `redis://localhost:6379/0`.
Имена `localhost` внутри web-контейнера и на хосте означают разные машины.
Для PostgreSQL в Docker подготовьте отдельный контейнер и доступный из web
адрес; импортный скрипт с именем `local_postgres` не добавляет его в сеть Compose.

```bash
docker compose down
```

## Celery без Docker

Сначала запустите Redis и задайте доступный broker URL. В отдельных терминалах
с активированным venv:

```bash
celery -A config worker -l info
celery -A config beat -l info --scheduler django_celery_beat.schedulers:DatabaseScheduler
```

Периодические задания хранятся в `django-celery-beat`; наличие beat-процесса
само по себе не доказывает, что нужная запись расписания включена.
Отправка деловых писем по умолчанию отключена. Для локальных проверок
используйте перехват SMTP/подмену провайдера; console backend Django не
перехватывает собственный SMTP-провайдер `apps.communications`.

## Проверки

```bash
pytest
pre-commit run --all-files
```

Правила фикстур, тесты миграций и shell-скриптов — в
[tests/README.md](../tests/README.md). Pre-commit использует detect-secrets,
black и стандартные проверки файлов. Миграции исключены из форматирования black.

## Отличия production

Production использует другой Dockerfile, готовый образ из CI, PostgreSQL,
Gunicorn, Nginx и обязательную security override. Локальный Compose не
предназначен для запуска на сервере. Процесс релиза описан отдельно:
[DEPLOYMENT.md](DEPLOYMENT.md).
