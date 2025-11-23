# Структура проекта

## Обзор

Проект построен на Django 4.2 с модульной архитектурой. Каждое приложение отвечает за свою область функциональности.

## Структура директорий

```
insurance_broker/
├── .kiro/                          # Спецификации Kiro
│   └── specs/
│       └── insurance-broker-system.md
│
├── apps/                           # Django приложения
│   ├── clients/                    # Модуль клиентов
│   │   ├── models.py              # Client
│   │   ├── admin.py               # Админка клиентов
│   │   ├── views.py               # Список и детали клиентов
│   │   └── urls.py
│   │
│   ├── insurers/                   # Справочники
│   │   ├── models.py              # Insurer, Branch, InsuranceType, InfoTag, CommissionRate
│   │   ├── admin.py               # Админка справочников
│   │   └── apps.py
│   │
│   ├── policies/                   # Основной модуль - Полисы
│   │   ├── models.py              # Policy, PaymentSchedule, PolicyInfo
│   │   ├── admin.py               # Админка с inline для платежей
│   │   ├── views.py               # Список, детали, фильтрация
│   │   ├── filters.py             # Django-filters для поиска
│   │   ├── signals.py             # Автоматические расчеты
│   │   └── urls.py
│   │
│   ├── notifications/              # Уведомления
│   │   ├── tasks.py               # Celery задачи
│   │   └── apps.py
│   │
│   ├── reports/                    # Отчеты и экспорт
│   │   ├── views.py               # Экспорт в Excel
│   │   └── urls.py
│   │
│   └── core/                       # Общие компоненты
│       ├── models.py              # TimeStampedModel (базовая модель)
│       ├── views.py               # Дашборд
│       └── urls.py
│
├── config/                         # Настройки Django
│   ├── settings.py                # Основные настройки
│   ├── urls.py                    # Главный URL конфиг
│   ├── wsgi.py                    # WSGI для продакшена
│   ├── asgi.py                    # ASGI (для будущего)
│   └── celery.py                  # Настройки Celery
│
├── templates/                      # HTML шаблоны
│   ├── base.html                  # Базовый шаблон с Bootstrap 5
│   ├── core/
│   │   └── dashboard.html         # Главная страница
│   ├── policies/
│   │   ├── policy_list.html       # Журнал полисов
│   │   ├── policy_detail.html     # Карточка полиса
│   │   └── payment_list.html      # График платежей
│   ├── clients/
│   │   ├── client_list.html       # Список клиентов
│   │   └── client_detail.html     # Карточка клиента
│   └── reports/
│       └── index.html             # Страница отчетов
│
├── static/                         # Статические файлы
│   ├── css/
│   │   └── custom.css
│   └── js/
│       └── custom.js
│
├── fixtures/                       # Начальные данные
│   └── initial_data.json          # Виды страхования, филиалы
│
├── docs/                           # Документация
│   └── USER_GUIDE.md              # Руководство пользователя
│
├── manage.py                       # Django management
├── requirements.txt                # Python зависимости
├── .env                           # Переменные окружения
├── .env.example                   # Пример настроек
├── .gitignore                     # Git ignore
├── README.md                      # Основная документация
├── INSTALL.md                     # Инструкция по установке
├── QUICKSTART.md                  # Быстрый старт
├── PROJECT_STRUCTURE.md           # Этот файл
└── create_superuser.py            # Скрипт создания админа
```

## Модели данных

### apps/clients/models.py
- **Client** - Клиенты (лизингополучатели, страхователи)

### apps/insurers/models.py
- **Insurer** - Страховые компании
- **Branch** - Филиалы лизинговой компании
- **InsuranceType** - Виды страхования
- **InfoTag** - Метки для классификации
- **CommissionRate** - Ставки комиссий

### apps/policies/models.py
- **Policy** - Страховые полисы (основная модель)
- **PaymentSchedule** - График платежей
- **PolicyInfo** - Связь полисов с метками

### apps/core/models.py
- **TimeStampedModel** - Абстрактная модель с created_at/updated_at

## Ключевые файлы

### Настройки
- `config/settings.py` - Основные настройки Django
- `.env` - Переменные окружения (не в git)
- `.env.example` - Пример настроек

### Админка
- `apps/*/admin.py` - Настройки Django Admin для каждого модуля
- `apps/policies/admin.py` - Inline для графика платежей

### Views
- `apps/core/views.py` - Дашборд с статистикой
- `apps/policies/views.py` - Список и детали полисов
- `apps/reports/views.py` - Экспорт в Excel

### Бизнес-логика
- `apps/policies/signals.py` - Автоматические расчеты:
  - Расчет комиссии в рублях
  - Обновление общей премии полиса
- `apps/notifications/tasks.py` - Celery задачи для уведомлений

### Шаблоны
- `templates/base.html` - Базовый шаблон с Bootstrap 5
- `templates/*/` - Шаблоны для каждого модуля

## Технологический стек

### Backend
- **Django 4.2** - Web framework
- **Python 3.9+** - Язык программирования
- **SQLite** - База данных (разработка)
- **PostgreSQL** - База данных (продакшен)

### Frontend
- **Bootstrap 5** - CSS framework
- **Bootstrap Icons** - Иконки
- **Vanilla JavaScript** - Минимальный JS

### Дополнительно
- **Celery** - Фоновые задачи (опционально)
- **Redis** - Брокер для Celery (опционально)
- **django-filter** - Фильтрация данных
- **django-import-export** - Экспорт в Excel
- **django-auditlog** - История изменений
- **openpyxl** - Работа с Excel

## Основные возможности

### 1. Управление полисами
- CRUD операции через админку
- Просмотр списка с фильтрами
- Детальная карточка полиса
- История изменений

### 2. График платежей
- Inline редактирование в админке
- Автоматический расчет комиссий
- Отслеживание статусов оплаты
- Фильтрация по статусам

### 3. Справочники
- Клиенты
- Страховые компании
- Филиалы
- Виды страхования
- Ставки комиссий
- Инфо-метки

### 4. Отчеты
- Экспорт полисов в Excel
- Экспорт графика платежей в Excel
- Фильтрация перед экспортом

### 5. Дашборд
- Статистика по полисам
- Предстоящие платежи
- Просроченные платежи
- Недавние полисы

### 6. Уведомления (опционально)
- Проверка предстоящих платежей
- Email-уведомления
- Celery задачи

## Автоматизация

### Signals (apps/policies/signals.py)

1. **pre_save на PaymentSchedule**
   - Автоматический расчет `kv_rub` из `amount` и `commission_rate`

2. **post_save/post_delete на PaymentSchedule**
   - Обновление `premium_total` в Policy при изменении графика

### Properties в моделях

1. **PaymentSchedule.is_paid**
   - Проверка наличия `paid_date`

2. **PaymentSchedule.is_overdue**
   - Сравнение `due_date` с текущей датой

3. **Policy.calculate_premium_total()**
   - Суммирование всех платежей

## Безопасность

- CSRF защита (Django)
- SQL injection защита (Django ORM)
- XSS защита (Django templates)
- Аутентификация пользователей
- Разграничение прав (Django permissions)
- Audit log (django-auditlog)

## Производительность

- Индексы на часто используемые поля
- select_related/prefetch_related в views
- Пагинация списков (50 элементов)
- Кэширование статики (WhiteNoise)

## Расширяемость

Проект легко расширяется:
- Добавление новых приложений в `apps/`
- Расширение моделей через наследование
- Добавление новых views и templates
- Интеграция с внешними API
- Добавление REST API (DRF уже установлен)

## Следующие шаги

1. Добавить REST API для мобильного приложения
2. Интеграция с email для автоматических уведомлений
3. Добавить графики и аналитику (Chart.js)
4. Экспорт в PDF
5. Интеграция с 1С
6. Telegram бот для уведомлений
7. Двухфакторная аутентификация
8. Права доступа на уровне объектов

## Поддержка

Для вопросов по структуре проекта обращайтесь к документации:
- `README.md` - Общая информация
- `INSTALL.md` - Установка
- `QUICKSTART.md` - Быстрый старт
- `docs/USER_GUIDE.md` - Руководство пользователя
