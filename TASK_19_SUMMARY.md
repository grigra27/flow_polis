# Task 19: Первоначальное развертывание - Резюме

## Статус: Готово к выполнению

Все необходимые инструменты и документация для первоначального развертывания созданы.

## Что было создано

### 1. Автоматизированный скрипт развертывания

**Файл:** `scripts/initial-deploy.sh`

Полностью автоматизированный скрипт, который выполняет все шаги развертывания:

- ✅ Проверка предварительных требований
- ✅ Тестирование SSH подключения к Droplet
- ✅ Проверка установки Docker и Docker Compose
- ✅ Создание директорий приложения
- ✅ Копирование файлов на Droplet (через rsync или scp)
- ✅ Генерация безопасных паролей
- ✅ Создание .env.prod и .env.prod.db
- ✅ Запуск Docker контейнеров
- ✅ Выполнение миграций базы данных
- ✅ Сбор статических файлов
- ✅ Получение SSL сертификата от Let's Encrypt
- ✅ Обновление Nginx конфигурации для HTTPS
- ✅ Проверка работоспособности
- ✅ Создание суперпользователя (опционально)

**Использование:**
```bash
export DROPLET_IP="YOUR_DROPLET_IP"
./scripts/initial-deploy.sh
```

### 2. Руководство по первоначальному развертыванию

**Файл:** `docs/INITIAL_DEPLOYMENT_GUIDE.md`

Подробное пошаговое руководство, включающее:

- Предварительные требования
- Два варианта развертывания (автоматизированный и ручной)
- Детальные инструкции для каждого шага
- Команды для проверки
- Раздел Troubleshooting
- Полезные команды для управления

### 3. Контрольный список развертывания

**Файл:** `DEPLOYMENT_CHECKLIST.md`

Интерактивный чек-лист для отслеживания прогресса:

- Предварительные требования
- Все 7 шагов развертывания
- Проверка работоспособности
- Следующие шаги
- Раздел для заметок

## Как выполнить развертывание

### Вариант 1: Автоматизированный (Рекомендуется)

```bash
# 1. Убедитесь, что Droplet настроен (Tasks 17-18 выполнены)
# 2. Установите переменные окружения
export DROPLET_IP="YOUR_DROPLET_IP"
export DROPLET_USER="root"

# 3. Запустите скрипт
./scripts/initial-deploy.sh

# Скрипт проведет вас через весь процесс
```

### Вариант 2: Ручной

Следуйте инструкциям в `docs/INITIAL_DEPLOYMENT_GUIDE.md`:

1. Копирование файлов на Droplet
2. Создание .env.prod с production переменными
3. Запуск docker-compose
4. Получение SSL сертификата через Let's Encrypt
5. Обновление Nginx конфигурации для HTTPS
6. Проверка доступности сайта

## Предварительные требования

Перед запуском убедитесь, что:

- ✅ **Task 17 выполнен:** Droplet создан и настроен
  - Docker установлен
  - Docker Compose установлен
  - Firewall настроен (порты 22, 80, 443)
  - SSH ключи настроены

- ✅ **Task 18 выполнен:** DNS настроен
  - A запись для onbr.site → Droplet IP
  - A запись для www.onbr.site → Droplet IP
  - DNS распространился (проверено через `dig`)

## Что произойдет во время развертывания

### Шаг 1: Копирование файлов (2-5 минут)
- Создание директорий на Droplet
- Копирование всех файлов приложения
- Установка правильных прав доступа

### Шаг 2: Создание .env.prod (1 минута)
- Генерация SECRET_KEY (50 символов)
- Генерация DB_PASSWORD (32 символа)
- Создание .env.prod с production настройками
- Создание .env.prod.db для PostgreSQL

### Шаг 3: Запуск docker-compose (3-5 минут)
- Загрузка Docker образов
- Запуск всех контейнеров
- Выполнение миграций
- Сбор статических файлов

### Шаг 4: Получение SSL сертификата (2-3 минуты)
- Проверка DNS
- Запуск certbot
- Получение сертификата от Let's Encrypt
- Настройка автоматического обновления

### Шаг 5: Обновление Nginx (1 минута)
- Обновление конфигурации для HTTPS
- Проверка конфигурации
- Перезапуск Nginx

### Шаг 6: Проверка (2 минуты)
- Проверка статуса контейнеров
- Проверка HTTP → HTTPS редиректа
- Проверка доступности сайта
- Проверка SSL сертификата

**Общее время:** ~15-20 минут

## Проверка успешного развертывания

После завершения проверьте:

```bash
# 1. Статус контейнеров
ssh root@YOUR_DROPLET_IP
cd /opt/insurance_broker
docker compose -f docker-compose.prod.yml ps

# Все должны быть "Up"

# 2. Доступность сайта
curl -I https://onbr.site
# Должен вернуть 200 OK

# 3. HTTP редирект
curl -I http://onbr.site
# Должен вернуть 301/302 на HTTPS

# 4. SSL сертификат
openssl s_client -connect onbr.site:443 -servername onbr.site < /dev/null | grep "Verify return code"
# Должен вернуть: Verify return code: 0 (ok)
```

## Что делать после развертывания

1. **Сохраните пароли**
   - SECRET_KEY
   - DB_PASSWORD
   - Сохраните в безопасном месте (password manager)

2. **Создайте суперпользователя**
   ```bash
   docker compose -f docker-compose.prod.yml exec web python manage.py createsuperuser
   ```

3. **Проверьте админ панель**
   - Откройте https://onbr.site/admin/
   - Войдите под суперпользователем

4. **Загрузите начальные данные** (если есть)
   ```bash
   docker compose -f docker-compose.prod.yml exec web python manage.py loaddata fixtures/initial_data.json
   ```

5. **Переходите к Task 20**
   - Настройка GitHub Secrets для CI/CD

## Troubleshooting

### Проблема: SSH подключение не работает

```bash
# Проверьте SSH ключи
ssh -v root@YOUR_DROPLET_IP

# Проверьте firewall
ssh root@YOUR_DROPLET_IP "sudo ufw status"
```

### Проблема: Docker не установлен

```bash
# Запустите скрипт настройки Droplet
./scripts/setup-droplet.sh
```

### Проблема: DNS не распространился

```bash
# Проверьте DNS
dig onbr.site +short

# Подождите и попробуйте снова (может занять до 48 часов)
```

### Проблема: SSL сертификат не получается

```bash
# Попробуйте с staging сервером
ssh root@YOUR_DROPLET_IP
cd /opt/insurance_broker
STAGING=1 ./scripts/init-letsencrypt.sh

# Проверьте логи
docker compose -f docker-compose.prod.yml logs certbot
```

### Проблема: Контейнеры не запускаются

```bash
# Проверьте логи
docker compose -f docker-compose.prod.yml logs

# Проверьте .env файлы
cat .env.prod
cat .env.prod.db

# Пересоберите образы
docker compose -f docker-compose.prod.yml build --no-cache
docker compose -f docker-compose.prod.yml up -d
```

## Откат изменений

Если что-то пошло не так:

```bash
# Остановите контейнеры
docker compose -f docker-compose.prod.yml down

# Удалите volumes (ВНИМАНИЕ: удалит данные!)
docker compose -f docker-compose.prod.yml down -v

# Начните заново
./scripts/initial-deploy.sh
```

## Файлы и скрипты

### Созданные файлы

1. **scripts/initial-deploy.sh** - Автоматизированный скрипт развертывания
2. **docs/INITIAL_DEPLOYMENT_GUIDE.md** - Подробное руководство
3. **DEPLOYMENT_CHECKLIST.md** - Контрольный список

### Существующие файлы (используются)

1. **scripts/deploy.sh** - Скрипт для последующих деплоев
2. **scripts/init-letsencrypt.sh** - Скрипт получения SSL
3. **docker-compose.prod.yml** - Production конфигурация
4. **.env.prod.example** - Пример переменных окружения
5. **nginx/default.conf** - Nginx конфигурация

## Следующие задачи

После успешного выполнения Task 19:

- **Task 20:** Настроить GitHub Secrets
  - SSH_PRIVATE_KEY
  - DROPLET_HOST
  - DROPLET_USER

- **Task 21:** Протестировать автоматический деплой
  - Сделать тестовый коммит
  - Проверить GitHub Actions

- **Task 22:** Финальная проверка
  - Проверить все функции
  - Проверить HTTPS
  - Проверить Celery
  - Проверить логирование

## Требования (Requirements)

Этот task выполняет требования:

- **4.1:** Получение SSL сертификата от Let's Encrypt
- **4.2:** Автоматическое использование SSL сертификата Nginx

## Заметки

- Скрипт `initial-deploy.sh` идемпотентен - можно запускать несколько раз
- Все пароли генерируются автоматически и безопасно
- SSL сертификат настроен на автоматическое обновление
- Все контейнеры настроены на автоматический перезапуск

## Полезные ссылки

- [Полное руководство по развертыванию](docs/DEPLOYMENT.md)
- [Настройка Droplet](docs/DROPLET_SETUP.md)
- [Настройка DNS](docs/DNS_SETUP.md)
- [Руководство по первоначальному развертыванию](docs/INITIAL_DEPLOYMENT_GUIDE.md)

---

**Статус:** ✅ Готово к выполнению  
**Время выполнения:** ~15-20 минут  
**Сложность:** Средняя (автоматизирована)  
**Требует:** Tasks 17, 18 должны быть выполнены  

**Дата создания:** 2024-11-25
