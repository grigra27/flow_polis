# Инструкция по установке и запуску

## Требования

- Python 3.11 или выше
- PostgreSQL 14+ (для продакшена) или SQLite (для разработки)
- Redis (опционально, для Celery)

## Установка

### 1. Клонирование и создание виртуального окружения

```bash
# Создайте виртуальное окружение
python -m venv venv

# Активируйте его
# macOS/Linux:
source venv/bin/activate
# Windows:
venv\Scripts\activate
```

### 2. Установка зависимостей

```bash
pip install -r requirements.txt
```

### 3. Настройка окружения

```bash
# Скопируйте файл с примером настроек
cp .env.example .env

# Отредактируйте .env файл
# Для разработки можно оставить настройки по умолчанию (будет использоваться SQLite)
```

### 4. Применение миграций

```bash
python manage.py migrate
```

### 5. Создание суперпользователя

```bash
python manage.py createsuperuser
```

Введите username, email и пароль для администратора.

### 6. Загрузка начальных данных (опционально)

```bash
python manage.py loaddata fixtures/initial_data.json
```

Это создаст базовые справочники:
- Виды страхования (КАСКО, Имущество, Спецтехника)
- Филиалы (Москва, Казань, Псков, Архангельск)

### 7. Сбор статических файлов (для продакшена)

```bash
python manage.py collectstatic --noinput
```

## Запуск

### Режим разработки

```bash
python manage.py runserver
```

Откройте браузер: http://127.0.0.1:8000/

### Админ-панель

http://127.0.0.1:8000/admin/

Войдите с учетными данными суперпользователя.

## Настройка PostgreSQL (для продакшена)

### 1. Создайте базу данных

```sql
CREATE DATABASE insurance_broker;
CREATE USER insurance_user WITH PASSWORD 'your_password';
ALTER ROLE insurance_user SET client_encoding TO 'utf8';
ALTER ROLE insurance_user SET default_transaction_isolation TO 'read committed';
ALTER ROLE insurance_user SET timezone TO 'Europe/Moscow';
GRANT ALL PRIVILEGES ON DATABASE insurance_broker TO insurance_user;
```

### 2. Обновите .env файл

```env
DB_NAME=insurance_broker
DB_USER=insurance_user
DB_PASSWORD=your_password
DB_HOST=localhost
DB_PORT=5432
```

### 3. Примените миграции

```bash
python manage.py migrate
```

## Настройка Celery (опционально, для уведомлений)

### 1. Установите и запустите Redis

```bash
# macOS (с Homebrew)
brew install redis
brew services start redis

# Ubuntu/Debian
sudo apt-get install redis-server
sudo systemctl start redis
```

### 2. Запустите Celery worker

```bash
celery -A config worker -l info
```

### 3. Запустите Celery beat (планировщик)

```bash
celery -A config beat -l info
```

### 4. Настройте периодические задачи

Войдите в админ-панель и перейдите в раздел "Periodic tasks" для настройки расписания проверки платежей.

## Тестирование

```bash
# Запуск всех тестов
python manage.py test

# Запуск тестов конкретного приложения
python manage.py test apps.policies
```

## Первые шаги после установки

1. Войдите в админ-панель
2. Добавьте страховые компании (Insurers)
3. Добавьте клиентов (Clients)
4. Настройте ставки комиссий (Commission Rates)
5. Создайте первый полис

## Структура проекта

```
insurance_broker/
├── apps/                   # Django приложения
│   ├── clients/           # Клиенты
│   ├── insurers/          # Справочники
│   ├── policies/          # Полисы (основной модуль)
│   ├── notifications/     # Уведомления
│   ├── reports/           # Отчеты
│   └── core/              # Общие компоненты
├── config/                # Настройки проекта
├── templates/             # HTML шаблоны
├── static/                # Статические файлы
├── fixtures/              # Начальные данные
└── docs/                  # Документация
```

## Решение проблем

### Ошибка при миграциях

```bash
# Удалите базу данных и создайте заново
rm db.sqlite3
python manage.py migrate
```

### Проблемы со статическими файлами

```bash
python manage.py collectstatic --clear --noinput
```

### Celery не запускается

Убедитесь, что Redis запущен:
```bash
redis-cli ping
# Должен вернуть: PONG
```

## Поддержка

Для вопросов и предложений обращайтесь к администратору системы.
