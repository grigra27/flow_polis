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
- ✅ Система аутентификации и авторизации с разделением прав доступа

## Система аутентификации

Приложение использует встроенную систему аутентификации Django с разделением прав доступа на два уровня: обычные пользователи и администраторы.

### Типы пользователей

#### Обычный пользователь (Regular User)
**Права доступа:**
- ✅ Просмотр всех данных (клиенты, страховщики, полисы, платежи)
- ✅ Экспорт отчетов в Excel
- ✅ Доступ к дашборду с аналитикой
- ❌ Создание, редактирование и удаление записей
- ❌ Доступ к административной панели Django

**Технические характеристики:**
- `is_staff = False`
- `is_superuser = False`

#### Администратор (Administrator)
**Права доступа:**
- ✅ Все права обычного пользователя
- ✅ Создание, редактирование и удаление всех записей
- ✅ Полный доступ к административной панели Django
- ✅ Управление пользователями системы

**Технические характеристики:**
- `is_staff = True`
- `is_superuser = True`

### Вход в систему

#### Через веб-интерфейс

1. Откройте приложение в браузере: http://127.0.0.1:8000/ (или ваш домен)
2. Вы будете автоматически перенаправлены на страницу входа
3. Введите имя пользователя и пароль
4. Нажмите кнопку "Войти"
5. После успешной аутентификации вы будете перенаправлены на дашборд

**Учетные данные по умолчанию (для разработки):**
- Имя пользователя: `admin`
- Пароль: `admin`

⚠️ **Важно:** Измените пароль администратора по умолчанию перед развертыванием в production!

#### Выход из системы

- Нажмите кнопку "Выход" в навигационном меню
- Ваша сессия будет завершена, и вы будете перенаправлены на страницу входа

### Управление пользователями

#### Создание пользователей через административную панель

**Для администраторов:**

1. Войдите в систему как администратор
2. Перейдите в административную панель: http://127.0.0.1:8000/admin/
3. Выберите раздел "Пользователи" (Users)
4. Нажмите "Добавить пользователя" (Add user)
5. Заполните обязательные поля:
   - **Имя пользователя** (Username) - уникальное имя для входа
   - **Пароль** (Password) - надежный пароль
   - **Подтверждение пароля** (Password confirmation)
6. Нажмите "Сохранить и продолжить редактирование"
7. Установите тип пользователя:
   - Для **обычного пользователя**: оставьте все галочки снятыми
   - Для **администратора**: установите галочки:
     - ✅ Статус персонала (Staff status)
     - ✅ Статус суперпользователя (Superuser status)
8. Нажмите "Сохранить"

#### Создание пользователей через командную строку

**Создание суперпользователя (администратора):**

```bash
# Интерактивный режим
python manage.py createsuperuser

# Или быстрый способ для разработки
python create_superuser.py
```

**Создание обычного пользователя через Django shell:**

```bash
python manage.py shell
```

```python
from django.contrib.auth.models import User

# Создание обычного пользователя
user = User.objects.create_user(
    username='ivanov',
    password='secure_password_123',
    first_name='Иван',
    last_name='Иванов',
    email='ivanov@example.com'
)
# is_staff и is_superuser автоматически установлены в False

# Создание администратора
admin = User.objects.create_superuser(
    username='petrov',
    password='admin_password_456',
    first_name='Петр',
    last_name='Петров',
    email='petrov@example.com'
)
# is_staff и is_superuser автоматически установлены в True
```

#### Создание пользователей в Docker окружении

**Development:**
```bash
docker compose -f docker-compose.dev.yml exec web python manage.py createsuperuser
```

**Production:**
```bash
docker compose -f docker-compose.prod.yml exec web python manage.py createsuperuser
```

### Изменение типа пользователя

Чтобы изменить обычного пользователя на администратора (или наоборот):

**Через административную панель:**
1. Войдите как администратор
2. Перейдите в админ-панель → Пользователи
3. Выберите нужного пользователя
4. Измените галочки "Статус персонала" и "Статус суперпользователя"
5. Сохраните изменения

**Через Django shell:**
```python
from django.contrib.auth.models import User

# Сделать пользователя администратором
user = User.objects.get(username='ivanov')
user.is_staff = True
user.is_superuser = True
user.save()

# Сделать администратора обычным пользователем
admin = User.objects.get(username='petrov')
admin.is_staff = False
admin.is_superuser = False
admin.save()
```

### Безопасность

#### Требования к паролям

Django автоматически применяет следующие требования к паролям:
- Минимум 8 символов
- Не может быть слишком похож на имя пользователя
- Не может быть полностью числовым
- Не может быть слишком распространенным паролем

#### Хеширование паролей

Все пароли автоматически хешируются с использованием алгоритма PBKDF2 с SHA256. Пароли никогда не хранятся в открытом виде.

#### Управление сессиями

- Сессии автоматически истекают после периода неактивности
- При выходе из системы все данные сессии полностью очищаются
- В production используются secure cookies через HTTPS

#### Защита от несанкционированного доступа

- Все страницы требуют аутентификации (кроме страницы входа)
- Middleware автоматически проверяет права доступа к URL создания/редактирования/удаления
- Попытки несанкционированного доступа логируются
- Обычные пользователи получают ошибку 403 при попытке доступа к защищенным ресурсам

#### Рекомендации для production

1. **Измените пароль администратора по умолчанию:**
   ```bash
   python manage.py changepassword admin
   ```

2. **Используйте сильные пароли:**
   - Минимум 12 символов
   - Комбинация букв, цифр и специальных символов
   - Уникальные для каждого пользователя

3. **Включите HTTPS:**
   - В production HTTPS включен автоматически через Nginx и Let's Encrypt
   - Все cookies передаются только через защищенное соединение

4. **Регулярно проверяйте логи:**
   ```bash
   # Проверка попыток несанкционированного доступа
   docker compose -f docker-compose.prod.yml logs web | grep -i "unauthorized"
   ```

5. **Ограничьте количество администраторов:**
   - Создавайте администраторов только при необходимости
   - Большинству пользователей достаточно прав обычного пользователя

### Условное отображение элементов интерфейса

Интерфейс автоматически адаптируется в зависимости от типа пользователя:

**Для обычных пользователей:**
- Скрыты кнопки "Добавить", "Редактировать", "Удалить"
- Скрыта ссылка на административную панель в навигации
- Доступны кнопки "Экспорт в Excel"

**Для администраторов:**
- Отображаются все элементы управления
- Доступна ссылка "Админка" в навигации
- Доступны все функции создания, редактирования и удаления

### Troubleshooting

#### Забыли пароль администратора

```bash
# Локально
python manage.py changepassword admin

# В Docker
docker compose -f docker-compose.prod.yml exec web python manage.py changepassword admin
```

#### Пользователь не может войти

1. Проверьте, что учетная запись активна:
   ```python
   from django.contrib.auth.models import User
   user = User.objects.get(username='username')
   print(user.is_active)  # Должно быть True
   ```

2. Если учетная запись неактивна, активируйте её:
   ```python
   user.is_active = True
   user.save()
   ```

#### Обычный пользователь видит кнопки редактирования

Это может произойти из-за кеширования браузера:
1. Очистите кеш браузера (Ctrl+Shift+Delete)
2. Выйдите из системы и войдите снова
3. Проверьте права пользователя в админ-панели

#### Ошибка 403 для администратора

Проверьте флаги пользователя:
```python
from django.contrib.auth.models import User
admin = User.objects.get(username='admin')
print(f"is_staff: {admin.is_staff}")  # Должно быть True
print(f"is_superuser: {admin.is_superuser}")  # Должно быть True
```

Если флаги неверные, исправьте:
```python
admin.is_staff = True
admin.is_superuser = True
admin.save()
```

## Разработка

### Локальная разработка (без Docker)

#### Запуск тестов

```bash
python manage.py test
```

#### Создание миграций

```bash
python manage.py makemigrations
```

#### Запуск Celery (для уведомлений)

```bash
celery -A config worker -l info
celery -A config beat -l info
```

### Локальная разработка (с Docker)

Для разработки с использованием Docker используйте `docker-compose.dev.yml`:

#### Первоначальная настройка

1. Скопируйте пример файла окружения:
```bash
cp .env.dev.example .env
```

2. Отредактируйте `.env` при необходимости (по умолчанию настроен для разработки)

#### Запуск development окружения

```bash
# Сборка и запуск всех сервисов
docker compose -f docker-compose.dev.yml up --build

# Или в фоновом режиме
docker compose -f docker-compose.dev.yml up -d --build
```

#### Особенности development окружения

- **Hot Reload**: Исходный код монтируется как volume, изменения применяются автоматически
- **Django Development Server**: Используется `runserver` вместо Gunicorn
- **Debug Toolbar**: Включен django-debug-toolbar для отладки
- **SQLite**: По умолчанию используется SQLite (можно настроить PostgreSQL)
- **Прямой доступ к сервисам**: Все порты доступны на localhost
  - Django: http://localhost:8000
  - Redis: localhost:6379
- **Console Email Backend**: Email выводятся в консоль

#### Управление development окружением

```bash
# Просмотр логов
docker compose -f docker-compose.dev.yml logs -f

# Выполнение команд Django
docker compose -f docker-compose.dev.yml exec web python manage.py migrate
docker compose -f docker-compose.dev.yml exec web python manage.py createsuperuser
docker compose -f docker-compose.dev.yml exec web python manage.py shell

# Остановка сервисов
docker compose -f docker-compose.dev.yml down

# Пересборка после изменения requirements.txt
docker compose -f docker-compose.dev.yml up --build
```

#### Отладка в контейнере

Для использования `pdb` или других отладчиков:

```bash
# Запустите web сервис в интерактивном режиме
docker compose -f docker-compose.dev.yml run --rm --service-ports web
```

## Production Deployment

### Docker Compose для Production

Проект включает полную конфигурацию Docker для production развертывания.

**Сервисы:**
- `web` - Django приложение с Gunicorn
- `db` - PostgreSQL 15
- `redis` - Redis для Celery
- `celery_worker` - Celery worker для фоновых задач
- `celery_beat` - Celery beat для периодических задач
- `nginx` - Nginx reverse proxy и SSL терминация

**Volumes для персистентности данных:**
- `postgres_data` - данные PostgreSQL
- `redis_data` - данные Redis
- `static_volume` - статические файлы Django
- `media_volume` - загруженные медиа файлы

**Networks для изоляции:**
- `backend` - внутренняя сеть для БД и Redis
- `frontend` - сеть для Nginx и web приложения

### Настройка окружения

1. Скопируйте примеры файлов окружения:
```bash
cp .env.prod.example .env.prod
cp .env.prod.db.example .env.prod.db
```

2. Отредактируйте `.env.prod` и `.env.prod.db` с вашими production значениями:
   - Сгенерируйте новый `SECRET_KEY`
   - Установите `DEBUG=False`
   - Настройте `ALLOWED_HOSTS` с вашим доменом
   - Установите безопасные пароли для БД
   - Настройте email параметры

### Локальное тестирование перед деплоем

**ВАЖНО:** Перед развертыванием в production, протестируйте Docker setup локально!

#### Автоматическая проверка

Запустите скрипт автоматической проверки:

```bash
./scripts/checkpoint-local-testing.sh
```

Или используйте Python скрипт:

```bash
python scripts/verify_docker_setup.py
```

Эти скрипты проверят:
- ✓ Установку и запуск Docker
- ✓ Синтаксис docker-compose.prod.yml
- ✓ Запуск всех сервисов
- ✓ Подключение к базе данных
- ✓ Миграции
- ✓ Сбор статических файлов
- ✓ Работу Celery
- ✓ Доступность через Nginx
- ✓ Интеграционные тесты

#### Ручная проверка

Подробное руководство по тестированию: **[CHECKPOINT_16_GUIDE.md](CHECKPOINT_16_GUIDE.md)**

### Запуск в Production

```bash
# Сборка и запуск всех сервисов
docker compose -f docker-compose.prod.yml up -d --build

# Проверка статуса сервисов
docker compose -f docker-compose.prod.yml ps

# Просмотр логов
docker compose -f docker-compose.prod.yml logs -f

# Остановка сервисов
docker compose -f docker-compose.prod.yml down
```

### Управление

```bash
# Выполнение миграций
docker compose -f docker-compose.prod.yml exec web python manage.py migrate

# Создание суперпользователя
docker compose -f docker-compose.prod.yml exec web python manage.py createsuperuser

# Сбор статических файлов
docker compose -f docker-compose.prod.yml exec web python manage.py collectstatic --noinput

# Просмотр логов конкретного сервиса
docker compose -f docker-compose.prod.yml logs -f web
docker compose -f docker-compose.prod.yml logs -f celery_worker
```

### SSL Certificate Setup

Для настройки HTTPS с Let's Encrypt используйте автоматический скрипт:

```bash
# Убедитесь, что DNS указывает на ваш сервер
# и файлы .env.prod настроены

# Запуск инициализации SSL
./scripts/init-letsencrypt.sh

# Для тестирования (staging сервер Let's Encrypt)
STAGING=1 ./scripts/init-letsencrypt.sh
```

Скрипт автоматически:
- Настроит nginx конфигурацию
- Получит SSL сертификат от Let's Encrypt
- Настроит автоматическое обновление сертификатов
- Включит HTTPS и редирект с HTTP

Подробная документация: [nginx/SSL_SETUP.md](nginx/SSL_SETUP.md)

### Restart Policies

Все сервисы настроены с `restart: unless-stopped`, что означает:
- Автоматический перезапуск при падении контейнера
- Автоматический запуск при перезагрузке сервера
- Остановка только при явной команде `docker compose down`

### Health Checks

Все критические сервисы имеют health checks:
- `db` - проверка готовности PostgreSQL
- `redis` - проверка доступности Redis
- `web` - проверка доступности Django приложения
- `celery_worker` - проверка работы Celery worker
- `nginx` - проверка работы Nginx

### Testing

#### Integration Tests

Проект включает полный набор интеграционных тестов для Docker окружения:

```bash
# Запуск всех интеграционных тестов
./tests/run_integration_tests.sh

# Или напрямую через Python
python tests/test_docker_integration.py

# Валидация структуры тестов (без Docker)
python tests/validate_tests.py
```

**Что тестируется:**
- ✅ Запуск всех контейнеров
- ✅ Подключение к PostgreSQL и Redis
- ✅ Работа Nginx reverse proxy
- ✅ Сбор и отдача статических файлов
- ✅ **Property 1**: Персистентность данных при перезапуске
- ✅ **Property 4**: Автоматический перезапуск упавших контейнеров

Подробная документация: [DOCKER_TESTING.md](DOCKER_TESTING.md)

### Мониторинг и логирование

#### Просмотр логов

Используйте удобный скрипт для просмотра логов:

```bash
# Просмотр логов всех сервисов
./scripts/view-logs.sh

# Следить за логами конкретного сервиса
./scripts/view-logs.sh web -f

# Последние 50 строк с временными метками
./scripts/view-logs.sh celery_worker -n 50 -t
```

#### Проверка здоровья системы

```bash
# Проверить статус всех контейнеров
./scripts/monitor-health.sh

# С отправкой алертов на email
./scripts/monitor-health.sh --alert-email admin@example.com
```

#### Конфигурация логирования

Все сервисы настроены с автоматической ротацией логов:
- **Max size:** 10MB на файл
- **Max files:** 3 файла
- **Total:** ~30MB на контейнер

Логи автоматически ротируются Docker, предотвращая переполнение диска.

#### Быстрый справочник

```bash
# Статус контейнеров
docker compose -f docker-compose.prod.yml ps

# Использование ресурсов
docker stats

# Логи конкретного сервиса
docker compose -f docker-compose.prod.yml logs -f web

# Health check статус
docker inspect --format='{{.State.Health.Status}}' insurance_broker_web
```

Подробная документация: [docs/MONITORING.md](docs/MONITORING.md)  
Быстрый справочник: [MONITORING_QUICK_REFERENCE.md](MONITORING_QUICK_REFERENCE.md)

### Переменные окружения

#### Обязательные переменные для Production

**Django Core:**
- `SECRET_KEY` - Криптографический ключ (генерируйте случайно, 50+ символов)
- `DEBUG` - Должен быть `False` в production
- `ALLOWED_HOSTS` - Список доменов через запятую (например: `onbr.site,www.onbr.site`)

**База данных:**
- `DB_NAME` - Имя базы данных (например: `insurance_broker_prod`)
- `DB_USER` - Пользователь PostgreSQL (например: `postgres`)
- `DB_PASSWORD` - Пароль БД (используйте сильный случайный пароль)
- `DB_HOST` - Хост БД (в Docker: `db`)
- `DB_PORT` - Порт БД (обычно: `5432`)

**Celery:**
- `CELERY_BROKER_URL` - URL Redis (в Docker: `redis://redis:6379/0`)
- `CELERY_RESULT_BACKEND` - URL Redis для результатов

**Email:**
- `EMAIL_BACKEND` - Backend для отправки email
- `EMAIL_HOST` - SMTP сервер (например: `smtp.gmail.com`)
- `EMAIL_PORT` - SMTP порт (обычно: `587`)
- `EMAIL_USE_TLS` - Использовать TLS (`True`)
- `EMAIL_HOST_USER` - Email для отправки
- `EMAIL_HOST_PASSWORD` - Пароль или App Password

**Генерация секретов:**
```bash
# Генерация SECRET_KEY
python -c 'from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())'

# Генерация DB_PASSWORD
python -c 'import secrets; print(secrets.token_urlsafe(32))'
```

Полная документация: [docs/ENVIRONMENT_VARIABLES.md](docs/ENVIRONMENT_VARIABLES.md)

### Troubleshooting

#### Контейнер не запускается

**Симптомы:** Контейнер постоянно перезапускается или имеет статус "Exited"

**Диагностика:**
```bash
# Проверка статуса
docker compose -f docker-compose.prod.yml ps

# Просмотр логов
docker compose -f docker-compose.prod.yml logs SERVICE_NAME

# Проверка конфигурации
docker compose -f docker-compose.prod.yml config
```

**Решения:**
1. Проверьте логи на наличие ошибок
2. Убедитесь, что все переменные окружения установлены
3. Проверьте, что зависимые сервисы (db, redis) запущены
4. Пересоберите образ: `docker compose -f docker-compose.prod.yml build --no-cache SERVICE_NAME`

#### Ошибки подключения к базе данных

**Симптомы:** "could not connect to server", "connection refused"

**Диагностика:**
```bash
# Проверка статуса PostgreSQL
docker compose -f docker-compose.prod.yml ps db

# Проверка логов БД
docker compose -f docker-compose.prod.yml logs db

# Проверка переменных окружения
docker compose -f docker-compose.prod.yml exec web env | grep DB_

# Тест подключения
docker compose -f docker-compose.prod.yml exec web python manage.py dbshell
```

**Решения:**
1. Убедитесь, что `DB_PASSWORD` в `.env.prod` совпадает с `POSTGRES_PASSWORD` в `.env.prod.db`
2. Проверьте, что `DB_HOST=db` (имя сервиса в docker-compose)
3. Дождитесь полного запуска PostgreSQL (может занять 10-15 секунд)
4. Проверьте health check: `docker inspect --format='{{.State.Health.Status}}' insurance_broker_db`

#### Проблемы с SSL сертификатами

**Симптомы:** "certificate not found", "SSL handshake failed"

**Диагностика:**
```bash
# Проверка существования сертификатов
ls -la certbot/conf/live/onbr.site/

# Проверка логов certbot
docker compose -f docker-compose.prod.yml logs certbot

# Проверка конфигурации Nginx
docker compose -f docker-compose.prod.yml exec nginx nginx -t

# Тест SSL
openssl s_client -connect onbr.site:443 -servername onbr.site < /dev/null
```

**Решения:**
1. Убедитесь, что DNS указывает на ваш сервер: `dig onbr.site`
2. Проверьте, что порт 80 открыт для ACME challenge
3. Запустите скрипт инициализации: `./scripts/init-letsencrypt.sh`
4. Для тестирования используйте staging: `STAGING=1 ./scripts/init-letsencrypt.sh`
5. Проверьте лимиты Let's Encrypt (5 сертификатов/неделю на домен)

#### Ошибки миграций

**Симптомы:** "Migration failed", "relation does not exist"

**Диагностика:**
```bash
# Просмотр статуса миграций
docker compose -f docker-compose.prod.yml exec web python manage.py showmigrations

# Просмотр логов миграций
docker compose -f docker-compose.prod.yml logs web | grep migrate
```

**Решения:**
1. Применить миграции вручную:
   ```bash
   docker compose -f docker-compose.prod.yml exec web python manage.py migrate
   ```

2. Откатить проблемную миграцию:
   ```bash
   docker compose -f docker-compose.prod.yml exec web python manage.py migrate APP_NAME MIGRATION_NAME
   ```

3. Создать фейковую миграцию (если таблицы уже существуют):
   ```bash
   docker compose -f docker-compose.prod.yml exec web python manage.py migrate --fake APP_NAME
   ```

4. Проверить целостность БД:
   ```bash
   docker compose -f docker-compose.prod.yml exec db psql -U postgres insurance_broker_prod -c "\dt"
   ```

#### Проблемы с Celery

**Симптомы:** Задачи не выполняются, "Connection refused to Redis"

**Диагностика:**
```bash
# Проверка статуса Celery worker
docker compose -f docker-compose.prod.yml logs celery_worker

# Проверка подключения к Redis
docker compose -f docker-compose.prod.yml exec redis redis-cli ping
# Должен вернуть: PONG

# Проверка очереди задач
docker compose -f docker-compose.prod.yml exec redis redis-cli
> KEYS celery*
> LLEN celery

# Проверка активных workers
docker compose -f docker-compose.prod.yml exec web celery -A config inspect active
```

**Решения:**
1. Перезапустить Celery сервисы:
   ```bash
   docker compose -f docker-compose.prod.yml restart celery_worker celery_beat
   ```

2. Проверить переменные окружения:
   ```bash
   docker compose -f docker-compose.prod.yml exec celery_worker env | grep CELERY
   ```

3. Очистить очередь задач (если застряли):
   ```bash
   docker compose -f docker-compose.prod.yml exec redis redis-cli FLUSHDB
   ```

4. Проверить логи на ошибки импорта:
   ```bash
   docker compose -f docker-compose.prod.yml logs celery_worker | grep -i error
   ```

#### Статические файлы не отображаются

**Симптомы:** CSS/JS не загружаются, 404 ошибки на /static/

**Диагностика:**
```bash
# Проверка наличия статических файлов
docker compose -f docker-compose.prod.yml exec web ls -la /app/staticfiles/

# Проверка конфигурации Nginx
docker compose -f docker-compose.prod.yml exec nginx cat /etc/nginx/conf.d/default.conf | grep static

# Проверка volume
docker volume inspect insurance_broker_static_volume

# Тест доступа
curl -I https://onbr.site/static/css/custom.css
```

**Решения:**
1. Пересобрать статические файлы:
   ```bash
   docker compose -f docker-compose.prod.yml exec web python manage.py collectstatic --noinput --clear
   ```

2. Проверить права доступа:
   ```bash
   docker compose -f docker-compose.prod.yml exec web ls -la /app/staticfiles/
   docker compose -f docker-compose.prod.yml exec nginx ls -la /app/staticfiles/
   ```

3. Перезапустить Nginx:
   ```bash
   docker compose -f docker-compose.prod.yml restart nginx
   ```

4. Проверить настройки Django:
   ```bash
   docker compose -f docker-compose.prod.yml exec web python manage.py shell
   >>> from django.conf import settings
   >>> print(settings.STATIC_ROOT)
   >>> print(settings.STATIC_URL)
   ```

#### Высокое использование ресурсов

**Симптомы:** Медленная работа, высокая загрузка CPU/RAM

**Диагностика:**
```bash
# Проверка использования ресурсов
docker stats

# Проверка процессов в контейнере
docker compose -f docker-compose.prod.yml exec web top

# Проверка использования диска
df -h
docker system df

# Проверка логов на ошибки
docker compose -f docker-compose.prod.yml logs --tail=100 | grep -i error
```

**Решения:**
1. Увеличить ресурсы Droplet (вертикальное масштабирование)

2. Оптимизировать количество Gunicorn workers:
   ```yaml
   # В docker-compose.prod.yml
   command: gunicorn config.wsgi:application --bind 0.0.0.0:8000 --workers 3
   # Формула: (2 x CPU cores) + 1
   ```

3. Очистить неиспользуемые ресурсы Docker:
   ```bash
   docker system prune -a
   docker volume prune
   ```

4. Настроить лимиты ресурсов в docker-compose:
   ```yaml
   services:
     web:
       deploy:
         resources:
           limits:
             cpus: '1.0'
             memory: 512M
   ```

5. Включить кэширование Redis для Django:
   ```python
   # В settings.py
   CACHES = {
       'default': {
           'BACKEND': 'django.core.cache.backends.redis.RedisCache',
           'LOCATION': 'redis://redis:6379/1',
       }
   }
   ```

#### Проблемы с firewall

**Симптомы:** Сайт недоступен извне, timeout при подключении

**Диагностика:**
```bash
# Проверка статуса UFW
sudo ufw status verbose

# Проверка открытых портов
sudo netstat -tulpn | grep LISTEN

# Проверка логов UFW
sudo tail -f /var/log/ufw.log

# Тест подключения снаружи
curl -I http://YOUR_SERVER_IP
```

**Решения:**
1. Открыть необходимые порты:
   ```bash
   sudo ufw allow 80/tcp
   sudo ufw allow 443/tcp
   sudo ufw allow 22/tcp
   sudo ufw enable
   ```

2. Проверить правила:
   ```bash
   sudo ufw status numbered
   ```

3. Удалить дублирующие правила:
   ```bash
   sudo ufw delete [номер правила]
   ```

4. Перезапустить UFW:
   ```bash
   sudo ufw disable
   sudo ufw enable
   ```

### Rollback (откат к предыдущей версии)

#### Быстрый откат через Git

Если деплой прошел неудачно, можно быстро откатиться к предыдущей версии:

```bash
# 1. Остановить текущие контейнеры
docker compose -f docker-compose.prod.yml down

# 2. Посмотреть историю коммитов
git log --oneline -10

# 3. Откатиться к предыдущему коммиту
git checkout PREVIOUS_COMMIT_HASH
# Или откатиться на один коммит назад
git checkout HEAD~1

# 4. Пересобрать и запустить
docker compose -f docker-compose.prod.yml up -d --build

# 5. Проверить статус
docker compose -f docker-compose.prod.yml ps
```

#### Откат миграций базы данных

Если проблема в миграциях:

```bash
# 1. Посмотреть список миграций
docker compose -f docker-compose.prod.yml exec web python manage.py showmigrations

# 2. Откатить к конкретной миграции
docker compose -f docker-compose.prod.yml exec web python manage.py migrate APP_NAME MIGRATION_NAME

# Пример: откат к миграции 0001
docker compose -f docker-compose.prod.yml exec web python manage.py migrate policies 0001

# 3. Перезапустить приложение
docker compose -f docker-compose.prod.yml restart web
```

#### Восстановление из бэкапа

Если нужно полностью восстановить базу данных:

```bash
# 1. Остановить приложение (но оставить БД)
docker compose -f docker-compose.prod.yml stop web celery_worker celery_beat

# 2. Восстановить из бэкапа
./scripts/restore-db.sh --interactive
# Или из конкретного файла
./scripts/restore-db.sh --file ~/insurance_broker_backups/database/db_backup_20240115.sql.gz

# 3. Запустить приложение
docker compose -f docker-compose.prod.yml start web celery_worker celery_beat
```

#### Откат Docker образов

Если проблема в новом образе:

```bash
# 1. Посмотреть историю образов
docker images insurance_broker_web --format "table {{.ID}}\t{{.CreatedAt}}\t{{.Size}}"

# 2. Остановить контейнеры
docker compose -f docker-compose.prod.yml down

# 3. Пометить старый образ как latest
docker tag OLD_IMAGE_ID insurance_broker_web:latest

# 4. Запустить с старым образом
docker compose -f docker-compose.prod.yml up -d

# 5. Проверить
docker compose -f docker-compose.prod.yml ps
```

#### Автоматический откат через deploy.sh

Скрипт `deploy.sh` автоматически откатывается при ошибках:

```bash
# Скрипт автоматически:
# 1. Создает бэкап текущего состояния
# 2. Пытается развернуть новую версию
# 3. Проверяет health checks
# 4. При ошибке откатывается к бэкапу

./scripts/deploy.sh
```

#### Полный откат системы

В крайнем случае, полный откат к рабочему состоянию:

```bash
# 1. Остановить все
docker compose -f docker-compose.prod.yml down

# 2. Откатить код
git reset --hard WORKING_COMMIT_HASH

# 3. Восстановить БД из бэкапа
./scripts/restore-db.sh --latest

# 4. Очистить Docker кэш
docker system prune -a -f

# 5. Пересобрать все с нуля
docker compose -f docker-compose.prod.yml build --no-cache

# 6. Запустить
docker compose -f docker-compose.prod.yml up -d

# 7. Проверить
docker compose -f docker-compose.prod.yml ps
./scripts/monitor-health.sh
```

### Просмотр логов

#### Базовые команды

```bash
# Логи всех сервисов
docker compose -f docker-compose.prod.yml logs

# Логи конкретного сервиса
docker compose -f docker-compose.prod.yml logs web

# Следить за логами в реальном времени
docker compose -f docker-compose.prod.yml logs -f

# Последние 100 строк
docker compose -f docker-compose.prod.yml logs --tail=100

# Логи с временными метками
docker compose -f docker-compose.prod.yml logs -t

# Комбинация опций
docker compose -f docker-compose.prod.yml logs -f --tail=50 -t web
```

#### Использование скрипта view-logs.sh

Удобный скрипт для просмотра логов:

```bash
# Логи всех сервисов
./scripts/view-logs.sh

# Следить за логами web сервиса
./scripts/view-logs.sh web -f

# Последние 50 строк с временными метками
./scripts/view-logs.sh celery_worker -n 50 -t

# Следить за всеми логами с метками времени
./scripts/view-logs.sh all -f -t

# Логи Nginx
./scripts/view-logs.sh nginx -f
```

#### Логи по сервисам

**Web (Django приложение):**
```bash
# Все логи приложения
docker compose -f docker-compose.prod.yml logs -f web

# Только ошибки
docker compose -f docker-compose.prod.yml logs web | grep -i error

# HTTP запросы
docker compose -f docker-compose.prod.yml logs web | grep "GET\|POST\|PUT\|DELETE"
```

**База данных (PostgreSQL):**
```bash
# Логи PostgreSQL
docker compose -f docker-compose.prod.yml logs -f db

# Ошибки подключения
docker compose -f docker-compose.prod.yml logs db | grep -i "connection\|error"

# Медленные запросы
docker compose -f docker-compose.prod.yml logs db | grep "duration"
```

**Celery Worker:**
```bash
# Логи worker
docker compose -f docker-compose.prod.yml logs -f celery_worker

# Выполненные задачи
docker compose -f docker-compose.prod.yml logs celery_worker | grep "Task.*succeeded"

# Ошибки задач
docker compose -f docker-compose.prod.yml logs celery_worker | grep -i "error\|failed"
```

**Celery Beat (планировщик):**
```bash
# Логи beat
docker compose -f docker-compose.prod.yml logs -f celery_beat

# Запланированные задачи
docker compose -f docker-compose.prod.yml logs celery_beat | grep "Scheduler"
```

**Nginx:**
```bash
# Логи Nginx
docker compose -f docker-compose.prod.yml logs -f nginx

# Access log (HTTP запросы)
docker compose -f docker-compose.prod.yml logs nginx | grep "GET\|POST"

# Error log
docker compose -f docker-compose.prod.yml logs nginx | grep "error"

# SSL ошибки
docker compose -f docker-compose.prod.yml logs nginx | grep -i "ssl"
```

**Redis:**
```bash
# Логи Redis
docker compose -f docker-compose.prod.yml logs -f redis

# Подключения
docker compose -f docker-compose.prod.yml logs redis | grep "Accepted"
```

#### Фильтрация и поиск в логах

```bash
# Поиск по ключевому слову
docker compose -f docker-compose.prod.yml logs | grep "keyword"

# Поиск без учета регистра
docker compose -f docker-compose.prod.yml logs | grep -i "error"

# Поиск нескольких слов
docker compose -f docker-compose.prod.yml logs | grep -E "error|warning|critical"

# Исключить строки
docker compose -f docker-compose.prod.yml logs | grep -v "healthcheck"

# Подсчет вхождений
docker compose -f docker-compose.prod.yml logs | grep -c "error"

# Контекст (показать 3 строки до и после)
docker compose -f docker-compose.prod.yml logs | grep -C 3 "error"
```

#### Экспорт логов

```bash
# Сохранить логи в файл
docker compose -f docker-compose.prod.yml logs > logs_$(date +%Y%m%d_%H%M%S).txt

# Сохранить логи конкретного сервиса
docker compose -f docker-compose.prod.yml logs web > web_logs.txt

# Сохранить только ошибки
docker compose -f docker-compose.prod.yml logs | grep -i error > errors.txt

# Архивировать логи
docker compose -f docker-compose.prod.yml logs | gzip > logs_$(date +%Y%m%d).txt.gz
```

#### Логи системы (хост)

```bash
# Логи Docker daemon
sudo journalctl -u docker -f

# Логи системы
sudo journalctl -f

# Логи за последний час
sudo journalctl --since "1 hour ago"

# Логи конкретного контейнера через journalctl
sudo journalctl CONTAINER_NAME=insurance_broker_web -f
```

#### Мониторинг в реальном времени

```bash
# Следить за логами всех сервисов с цветным выводом
docker compose -f docker-compose.prod.yml logs -f --tail=20

# Использовать tmux для мониторинга нескольких сервисов
tmux new-session -d -s logs
tmux split-window -h
tmux select-pane -t 0
tmux send-keys "docker compose -f docker-compose.prod.yml logs -f web" C-m
tmux select-pane -t 1
tmux send-keys "docker compose -f docker-compose.prod.yml logs -f celery_worker" C-m
tmux attach-session -t logs
```

#### Анализ логов

```bash
# Топ ошибок
docker compose -f docker-compose.prod.yml logs | grep -i error | sort | uniq -c | sort -rn | head -10

# Статистика HTTP кодов
docker compose -f docker-compose.prod.yml logs nginx | grep -oP 'HTTP/\d\.\d" \K\d+' | sort | uniq -c

# Самые частые URL
docker compose -f docker-compose.prod.yml logs nginx | grep -oP 'GET \K[^ ]+' | sort | uniq -c | sort -rn | head -10

# Медленные запросы Django
docker compose -f docker-compose.prod.yml logs web | grep "Slow query" | wc -l
```

### CI/CD и автоматический деплой

#### Настройка GitHub Actions

Проект включает полную настройку CI/CD через GitHub Actions для автоматического развертывания при push в main ветку.

**Что происходит автоматически:**
1. ✅ Валидация конфигурации Docker
2. ✅ Сборка Docker образов
3. ✅ Деплой на Digital Ocean Droplet
4. ✅ Выполнение миграций
5. ✅ Health checks
6. ✅ Автоматический rollback при ошибках

#### Настройка GitHub Secrets

Для работы автоматического деплоя необходимо настроить GitHub Secrets:

**Быстрая настройка (5 минут):**

```bash
# Автоматическая настройка SSH ключа и получение значений для GitHub
./scripts/setup-github-secrets.sh

# Проверка настройки
./scripts/verify-github-secrets.sh
```

**Необходимые секреты:**
- `SSH_PRIVATE_KEY` - Приватный SSH ключ для подключения к Droplet
- `DROPLET_HOST` - IP адрес Droplet (64.227.75.233)
- `DROPLET_USER` - SSH пользователь (root)

**Добавление секретов в GitHub:**
1. Перейдите: **Settings** → **Secrets and variables** → **Actions**
2. Нажмите **New repository secret**
3. Добавьте каждый из трех секретов

**Проверка работы:**
```bash
# Тестовый деплой
git commit --allow-empty -m "test: verify GitHub Actions"
git push origin main

# Проверьте статус: GitHub → Actions → Deploy to Production
```

**Документация:**
- [GitHub Secrets Setup Guide](docs/GITHUB_SECRETS_SETUP.md) - Полное руководство по настройке
- [GitHub Secrets Quick Reference](GITHUB_SECRETS_QUICK_REFERENCE.md) - Быстрая справка

#### Workflow файл

Workflow настроен в `.github/workflows/deploy.yml` и включает:
- Валидацию конфигурации
- Сборку Docker образов
- Деплой через SSH
- Выполнение миграций
- Health checks
- Автоматический rollback при ошибках

### Документация

- [Deployment Guide](docs/DEPLOYMENT.md) - Полное руководство по развертыванию на Digital Ocean
- [GitHub Secrets Setup](docs/GITHUB_SECRETS_SETUP.md) - Настройка секретов для CI/CD
- [GitHub Secrets Quick Reference](GITHUB_SECRETS_QUICK_REFERENCE.md) - Быстрая справка по секретам
- [DNS Setup Guide](docs/DNS_SETUP.md) - Полное руководство по настройке DNS
- [DNS Quick Reference](docs/DNS_QUICK_REFERENCE.md) - Быстрый справочник по DNS
- [Monitoring Guide](docs/MONITORING.md) - Полное руководство по мониторингу и логированию
- [Monitoring Quick Reference](MONITORING_QUICK_REFERENCE.md) - Быстрый справочник команд
- [Backup & Restore Guide](docs/BACKUP_RESTORE.md) - Руководство по резервному копированию
- [Docker Testing Guide](DOCKER_TESTING.md) - Руководство по интеграционным тестам
- [SSL Setup Guide](nginx/SSL_SETUP.md) - Настройка SSL сертификатов
- [Scripts Documentation](scripts/README.md) - Документация по скриптам
- [Docker Compose Reference](DOCKER_COMPOSE_REFERENCE.md) - Справка по Docker Compose
- [Environment Variables](docs/ENVIRONMENT_VARIABLES.md) - Переменные окружения

## Лицензия

Proprietary
