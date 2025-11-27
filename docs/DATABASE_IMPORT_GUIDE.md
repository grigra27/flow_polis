# Руководство по импорту продакшн базы данных

Это руководство описывает процесс импорта базы данных с продакшн сервера в локальное окружение для разработки и тестирования.

## Обзор

Проект поддерживает работу с двумя типами баз данных:
- **SQLite** - легковесная база для быстрой разработки
- **PostgreSQL** - полноценная база, идентичная продакшн окружению

Вы можете легко переключаться между ними, изменяя файл `.env`.

## Автоматический импорт (рекомендуется)

### Запуск скрипта импорта

```bash
./scripts/import_prod_db.sh
```

### Что делает скрипт

1. **Создание бэкапа на проде** - подключается к продакшн серверу и создает дамп базы данных
2. **Скачивание бэкапа** - копирует дамп на локальную машину
3. **Настройка PostgreSQL** - запускает локальный PostgreSQL контейнер (если не запущен)
4. **Импорт данных** - загружает продакшн данные в локальную базу
5. **Очистка** - удаляет временные файлы с продакшн сервера

### Параметры скрипта

Скрипт использует следующие настройки (можно изменить в `scripts/import_prod_db.sh`):

**Продакшн:**
- Сервер: `root@64.227.75.233`
- Контейнер: `insurance_broker_db`
- База данных: `insurance_broker_prod`

**Локально:**
- Контейнер: `local_postgres`
- База данных: `insurance_broker_local`
- Пользователь: `postgres`
- Пароль: `postgres`
- Порт: `5432`

## Переключение между базами данных

### Использовать PostgreSQL с продакшн данными

```bash
cp .env.local.postgres .env
python manage.py runserver
```

### Вернуться на SQLite

```bash
cp .env.local.sqlite .env
python manage.py runserver
```

## Управление локальным PostgreSQL

### Проверить статус контейнера

```bash
docker ps | grep local_postgres
```

### Остановить PostgreSQL

```bash
docker stop local_postgres
```

### Запустить PostgreSQL

```bash
docker start local_postgres
```

### Подключиться к базе данных

```bash
docker exec -it local_postgres psql -U postgres insurance_broker_local
```

### Удалить контейнер полностью

```bash
docker rm -f local_postgres
```

После удаления контейнера все данные будут потеряны. Для повторного импорта запустите скрипт заново.

## Ручной импорт (альтернативный метод)

Если автоматический скрипт не работает, можно выполнить импорт вручную:

### Шаг 1: Создать дамп на проде

```bash
ssh root@64.227.75.233
cd /opt/insurance_broker
docker exec insurance_broker_db pg_dump -U postgres insurance_broker_prod > db_backup.sql
exit
```

### Шаг 2: Скачать дамп

```bash
scp root@64.227.75.233:/opt/insurance_broker/db_backup.sql ./db_backup.sql
```

### Шаг 3: Запустить локальный PostgreSQL

```bash
docker run -d --name local_postgres \
  -e POSTGRES_PASSWORD=postgres \
  -e POSTGRES_DB=insurance_broker_local \
  -p 5432:5432 \
  postgres:15-alpine
```

### Шаг 4: Импортировать дамп

```bash
docker exec -i local_postgres psql -U postgres insurance_broker_local < db_backup.sql
```

### Шаг 5: Очистить временные файлы

```bash
ssh root@64.227.75.233 "rm -f /opt/insurance_broker/db_backup.sql"
rm db_backup.sql
```

## Импорт со сжатием (для больших баз)

Если база данных большая, используйте формат с сжатием:

### На проде

```bash
ssh root@64.227.75.233
cd /opt/insurance_broker
docker exec insurance_broker_db pg_dump -U postgres -Fc insurance_broker_prod > db_backup.dump
exit
```

### Скачать и импортировать

```bash
scp root@64.227.75.233:/opt/insurance_broker/db_backup.dump ./db_backup.dump
docker exec -i local_postgres pg_restore -U postgres -d insurance_broker_local < db_backup.dump
```

## Конфигурация .env файлов

### .env.local.postgres

```bash
SECRET_KEY=django-insecure-dev-key-change-in-production
DEBUG=True
ALLOWED_HOSTS=localhost,127.0.0.1

DB_NAME=insurance_broker_local
DB_USER=postgres
DB_PASSWORD=postgres
DB_HOST=localhost
DB_PORT=5432

EMAIL_BACKEND=django.core.mail.backends.console.EmailBackend
CELERY_BROKER_URL=redis://localhost:6379/0
CELERY_RESULT_BACKEND=redis://localhost:6379/0
```

### .env.local.sqlite

```bash
SECRET_KEY=django-insecure-dev-key-change-in-production
DEBUG=True
ALLOWED_HOSTS=localhost,127.0.0.1

DB_NAME=
DB_USER=
DB_PASSWORD=
DB_HOST=
DB_PORT=

EMAIL_BACKEND=django.core.mail.backends.console.EmailBackend
CELERY_BROKER_URL=redis://localhost:6379/0
CELERY_RESULT_BACKEND=redis://localhost:6379/0
```

## Как работает переключение баз данных

Django автоматически определяет тип базы данных на основе переменной `DB_NAME` в `config/settings.py`:

```python
db_name = config('DB_NAME', default='')
if db_name:
    # PostgreSQL
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.postgresql',
            'NAME': db_name,
            'USER': config('DB_USER', default='postgres'),
            'PASSWORD': config('DB_PASSWORD', default=''),
            'HOST': config('DB_HOST', default='localhost'),
            'PORT': config('DB_PORT', default='5432'),
        }
    }
else:
    # SQLite (default for development)
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': BASE_DIR / 'db.sqlite3',
        }
    }
```

Если `DB_NAME` пустая - используется SQLite, если заполнена - PostgreSQL.

## Устранение проблем

### Ошибка: "Container already exists"

```bash
docker rm -f local_postgres
./scripts/import_prod_db.sh
```

### Ошибка: "Port 5432 already in use"

Остановите другой PostgreSQL или измените порт в скрипте:

```bash
# Найти процесс на порту 5432
lsof -i :5432

# Остановить локальный PostgreSQL (если установлен через Homebrew)
brew services stop postgresql
```

### Ошибка подключения к проду

Проверьте SSH доступ:

```bash
ssh root@64.227.75.233
```

### База данных пустая после импорта

Проверьте логи импорта на наличие ошибок. Возможно, нужно пересоздать базу:

```bash
docker exec local_postgres psql -U postgres -c "DROP DATABASE insurance_broker_local;"
docker exec local_postgres psql -U postgres -c "CREATE DATABASE insurance_broker_local;"
docker exec -i local_postgres psql -U postgres insurance_broker_local < db_backup.sql
```

## Безопасность

⚠️ **Важно:**
- Продакшн данные могут содержать чувствительную информацию
- Не коммитьте файлы дампов в Git
- Используйте локальную базу только для разработки и тестирования
- Не отправляйте тестовые email с продакшн данными (используется console backend)

## Рекомендации

1. **Регулярно обновляйте локальную базу** - запускайте импорт раз в неделю или перед началом работы над новой функцией
2. **Используйте PostgreSQL для тестирования** - это гарантирует совместимость с продакшн окружением
3. **Используйте SQLite для быстрой разработки** - когда не нужны продакшн данные
4. **Делайте бэкапы локальной базы** - если внесли важные тестовые данные

## Дополнительные команды

### Создать бэкап локальной базы

```bash
docker exec local_postgres pg_dump -U postgres insurance_broker_local > local_backup.sql
```

### Восстановить из локального бэкапа

```bash
docker exec -i local_postgres psql -U postgres insurance_broker_local < local_backup.sql
```

### Посмотреть размер базы данных

```bash
docker exec local_postgres psql -U postgres -c "SELECT pg_size_pretty(pg_database_size('insurance_broker_local'));"
```

### Список всех таблиц

```bash
docker exec local_postgres psql -U postgres insurance_broker_local -c "\dt"
```

### Количество записей в таблице

```bash
docker exec local_postgres psql -U postgres insurance_broker_local -c "SELECT COUNT(*) FROM your_table_name;"
```
