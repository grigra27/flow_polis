# Система управления полисами для страхового брокера

Веб-приложение для автоматизации работы страхового брокера - учет полисов, управление графиками платежей и уведомления о предстоящих оплатах.

## Технологии

- Django 4.2
- PostgreSQL / SQLite
- Bootstrap 5
- Celery + Redis
- Python 3.9+

## Быстрый старт

### 1. Установка зависимостей

```bash
python3 -m venv venv
source venv/bin/activate  # для Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Настройка окружения

Файл `.env` уже создан с настройками для разработки (используется SQLite).

### 3. Миграции базы данных

```bash
python3 manage.py migrate
```

### 4. Загрузка начальных данных

```bash
python3 manage.py loaddata fixtures/initial_data.json
```

Это создаст:
- Виды страхования: КАСКО, Имущество, Спецтехника
- Филиалы: Москва, Казань, Псков, Архангельск

### 5. Создание суперпользователя

**Быстрый способ (для разработки):**
```bash
python3 create_superuser.py
```
Будет создан пользователь: `admin` / `admin`

**Или вручную:**
```bash
python3 manage.py createsuperuser
```

### 6. Запуск сервера разработки

```bash
python3 manage.py runserver
```

Откройте http://127.0.0.1:8000/

**Учетные данные:**
- Username: `admin`
- Password: `admin`

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
└── docs/                  # Документация
```

## Основные возможности

- ✅ Учет клиентов и страховых компаний
- ✅ Управление полисами
- ✅ График платежей с автоматическим расчетом комиссий
- ✅ Фильтрация и поиск
- ✅ Экспорт в Excel
- ✅ Уведомления о предстоящих платежах
- ✅ Дашборд с аналитикой

## Разработка

### Запуск тестов

```bash
python manage.py test
```

### Создание миграций

```bash
python manage.py makemigrations
```

### Запуск Celery (для уведомлений)

```bash
celery -A config worker -l info
celery -A config beat -l info
```

## Лицензия

Proprietary
