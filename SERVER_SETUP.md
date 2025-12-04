# Руководство по подготовке сервера Timeweb Cloud

## Обзор

Этот документ содержит пошаговые инструкции по подготовке сервера Timeweb Cloud для развертывания Insurance Broker System. Все команды должны выполняться на новом сервере с IP адресом **109.68.215.223**.

## Требования к серверу

- **ОС**: Ubuntu 20.04/22.04 LTS
- **Минимальные ресурсы**: 2 CPU, 4GB RAM, 50GB диск
- **Доступ**: Root или sudo доступ
- **Сеть**: Публичный IP адрес 109.68.215.223

---

## Шаг 1: Установка Docker

### 1.1 Обновление системы

Подключитесь к серверу и обновите пакеты:

```bash
ssh root@109.68.215.223

# Обновление списка пакетов
apt update

# Обновление установленных пакетов
apt upgrade -y
```

### 1.2 Установка зависимостей

```bash
apt install -y \
    apt-transport-https \
    ca-certificates \
    curl \
    gnupg \
    lsb-release
```

### 1.3 Добавление официального GPG ключа Docker

```bash
# Создание директории для ключей
mkdir -p /etc/apt/keyrings

# Загрузка GPG ключа Docker
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
```

### 1.4 Добавление репозитория Docker

```bash
echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu \
  $(lsb_release -cs) stable" | tee /etc/apt/sources.list.d/docker.list > /dev/null
```

### 1.5 Установка Docker Engine

```bash
# Обновление списка пакетов
apt update

# Установка Docker
apt install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
```

### 1.6 Проверка установки Docker

```bash
# Проверка версии
docker --version

# Проверка работы Docker (опционально - может быть ограничение rate limit)
# docker run hello-world

# Включение автозапуска Docker
systemctl enable docker
systemctl start docker

# Проверка статуса Docker
systemctl status docker
```

Ожидаемый вывод: `Docker version 20.10.x` или выше (у вас установлена версия 29.1.2 - это отлично!)

**Примечание о Docker Hub rate limit**:
Если при выполнении `docker run hello-world` вы получаете ошибку "You have reached your unauthenticated pull rate limit", это нормально. Docker Hub ограничивает количество анонимных загрузок образов. Это не влияет на работу проекта, так как образы для Insurance Broker System будут собираться локально из Dockerfile, а не загружаться с Docker Hub.

### 1.7 Аутентификация в Docker Hub (опционально)

Если вы хотите избежать rate limit при загрузке образов с Docker Hub, можете войти в свой аккаунт:

```bash
# Вход в Docker Hub (потребуется username и password/token)
docker login

# Введите ваш Docker Hub username
# Введите ваш Docker Hub password или Personal Access Token
```

**Создание Personal Access Token (рекомендуется вместо пароля):**

1. Зайдите на https://hub.docker.com/
2. Account Settings → Security → New Access Token
3. Создайте токен с именем "timeweb-server"
4. Скопируйте токен и используйте его вместо пароля при `docker login`

После успешного входа:

```bash
# Проверка что вход выполнен
docker info | grep Username

# Теперь можно тестировать без ограничений
docker run hello-world
```

**Примечание**: Учетные данные Docker Hub сохраняются в `~/.docker/config.json`. Для безопасности рекомендуется использовать Personal Access Token вместо пароля.

---

## Шаг 2: Установка Docker Compose v1

**ВАЖНО**: Проект использует синтаксис Docker Compose v1 с дефисом (`docker-compose`), а не v2 (`docker compose`).

### 2.1 Загрузка Docker Compose v1

```bash
# Загрузка последней версии v1 (1.29.2)
curl -L "https://github.com/docker/compose/releases/download/1.29.2/docker-compose-$(uname -s)-$(uname -m)" -o /usr/local/bin/docker-compose
```

### 2.2 Установка прав на выполнение

```bash
chmod +x /usr/local/bin/docker-compose
```

### 2.3 Проверка установки

```bash
docker-compose --version
```

Ожидаемый вывод: `docker-compose version 1.29.2`

---

## Шаг 3: Настройка SSH доступа

### 3.1 Генерация SSH ключей (на локальной машине)

Если у вас еще нет SSH ключей для GitHub Actions:

```bash
# На вашей локальной машине
ssh-keygen -t ed25519 -C "github-actions-deploy" -f ~/.ssh/timeweb_deploy_key

# Это создаст два файла:
# ~/.ssh/timeweb_deploy_key (приватный ключ - для GitHub Secrets)
# ~/.ssh/timeweb_deploy_key.pub (публичный ключ - для сервера)
```

### 3.2 Добавление публичного ключа на сервер

На сервере Timeweb Cloud:

```bash
# Создание директории .ssh если её нет
mkdir -p ~/.ssh

# Установка правильных прав доступа
chmod 700 ~/.ssh

# Создание или редактирование authorized_keys
nano ~/.ssh/authorized_keys
```

Вставьте содержимое файла `~/.ssh/timeweb_deploy_key.pub` (с вашей локальной машины) в файл `authorized_keys`.

```bash
# Установка правильных прав доступа
chmod 600 ~/.ssh/authorized_keys
```

### 3.3 Проверка SSH подключения

С вашей локальной машины:

```bash
# Тест подключения с использованием ключа
ssh -i ~/.ssh/timeweb_deploy_key root@109.68.215.223 "echo 'SSH connection successful'"
```

Если видите сообщение "SSH connection successful", настройка выполнена правильно.

### 3.4 Добавление приватного ключа в GitHub Secrets

1. Скопируйте содержимое приватного ключа:
   ```bash
   cat ~/.ssh/timeweb_deploy_key
   ```

2. Перейдите в настройки репозитория GitHub:
   - Settings → Secrets and variables → Actions
   - Нажмите "New repository secret"
   - Name: `SSH_PRIVATE_KEY`
   - Value: вставьте полное содержимое приватного ключа

---

## Шаг 4: Создание структуры директорий

### 4.1 Создание основной директории проекта

```bash
# Создание директории проекта
mkdir -p ~/insurance_broker

# Переход в директорию
cd ~/insurance_broker
```

### 4.2 Создание поддиректорий

```bash
# Создание директорий для данных
mkdir -p certbot/conf
mkdir -p certbot/www
mkdir -p logs
mkdir -p media
mkdir -p staticfiles

# Установка прав доступа
chmod -R 755 ~/insurance_broker
```

### 4.3 Проверка структуры

```bash
tree -L 2 ~/insurance_broker
```

Ожидаемая структура:
```
/root/insurance_broker/
├── certbot/
│   ├── conf/
│   └── www/
├── logs/
├── media/
└── staticfiles/
```

---

## Шаг 5: Создание файлов окружения

### 5.1 Создание .env.prod

```bash
cd ~/insurance_broker
nano .env.prod
```

Вставьте следующий шаблон и замените значения в `<угловых скобках>`:

```bash
# Django Settings
SECRET_KEY=<сгенерируйте уникальный ключ - используйте команду ниже>
DEBUG=False
ALLOWED_HOSTS=polis.insflow.ru,www.polis.insflow.ru,109.68.215.223

# Database Settings
DB_NAME=insurance_broker_prod
DB_USER=postgres
DB_PASSWORD=<сгенерируйте сильный пароль>
DB_HOST=db
DB_PORT=5432

# Celery Settings
CELERY_BROKER_URL=redis://redis:6379/0
CELERY_RESULT_BACKEND=redis://redis:6379/0

# Email Settings (опционально)
EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend
EMAIL_HOST=smtp.gmail.com
EMAIL_PORT=587
EMAIL_USE_TLS=True
EMAIL_HOST_USER=<ваш email>
EMAIL_HOST_PASSWORD=<app password для Gmail>
DEFAULT_FROM_EMAIL=noreply@insflow.ru

# Security Settings
SECURE_SSL_REDIRECT=True
SECURE_HSTS_SECONDS=31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS=True
SECURE_HSTS_PRELOAD=True
SESSION_COOKIE_SECURE=True
CSRF_COOKIE_SECURE=True
SECURE_CONTENT_TYPE_NOSNIFF=True
SECURE_BROWSER_XSS_FILTER=True
X_FRAME_OPTIONS=DENY

# Static and Media Files
STATIC_ROOT=/app/staticfiles
MEDIA_ROOT=/app/media
STATIC_URL=/static/
MEDIA_URL=/media/

# Logging
LOG_LEVEL=INFO
```

### 5.2 Генерация SECRET_KEY

Для генерации безопасного SECRET_KEY используйте:

```bash
python3 -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"
```

Если Python/Django не установлен на сервере, используйте:

```bash
openssl rand -base64 50
```

### 5.3 Генерация пароля базы данных

```bash
openssl rand -base64 32
```

Скопируйте сгенерированный пароль - он понадобится для обоих файлов.

### 5.4 Создание .env.prod.db

```bash
nano .env.prod.db
```

Вставьте следующий шаблон (используйте **тот же пароль** что и в .env.prod):

```bash
POSTGRES_DB=insurance_broker_prod
POSTGRES_USER=postgres
POSTGRES_PASSWORD=<тот же пароль что и DB_PASSWORD в .env.prod>
```

### 5.5 Установка прав доступа на файлы окружения

```bash
# Ограничение доступа только для владельца
chmod 600 .env.prod
chmod 600 .env.prod.db

# Проверка прав
ls -la .env.prod*
```

Ожидаемый вывод: `-rw------- 1 root root`

### 5.6 Проверка файлов окружения

```bash
# Проверка что файлы существуют и не пусты
test -f .env.prod && test -s .env.prod && echo ".env.prod OK" || echo ".env.prod MISSING or EMPTY"
test -f .env.prod.db && test -s .env.prod.db && echo ".env.prod.db OK" || echo ".env.prod.db MISSING or EMPTY"

# Проверка что пароли совпадают
DB_PASS=$(grep "^DB_PASSWORD=" .env.prod | cut -d'=' -f2)
PG_PASS=$(grep "^POSTGRES_PASSWORD=" .env.prod.db | cut -d'=' -f2)
if [ "$DB_PASS" = "$PG_PASS" ]; then
    echo "✓ Пароли совпадают"
else
    echo "✗ ОШИБКА: Пароли не совпадают!"
fi
```

---

## Шаг 6: Настройка Firewall (UFW)

### 6.1 Установка UFW (если не установлен)

```bash
apt install -y ufw
```

### 6.2 Настройка правил firewall

```bash
# Разрешить SSH (ВАЖНО: сделайте это первым!)
ufw allow 22/tcp

# Разрешить HTTP
ufw allow 80/tcp

# Разрешить HTTPS
ufw allow 443/tcp

# Проверка правил перед включением
ufw show added
```

### 6.3 Включение UFW

```bash
# Включение firewall
ufw --force enable

# Проверка статуса
ufw status verbose
```

Ожидаемый вывод:
```
Status: active

To                         Action      From
--                         ------      ----
22/tcp                     ALLOW       Anywhere
80/tcp                     ALLOW       Anywhere
443/tcp                    ALLOW       Anywhere
22/tcp (v6)                ALLOW       Anywhere (v6)
80/tcp (v6)                ALLOW       Anywhere (v6)
443/tcp (v6)               ALLOW       Anywhere (v6)
```

### 6.4 Дополнительные настройки безопасности (опционально)

```bash
# Ограничение количества SSH подключений (защита от brute-force)
ufw limit 22/tcp

# Запрет ping (опционально)
# echo "net.ipv4.icmp_echo_ignore_all = 1" >> /etc/sysctl.conf
# sysctl -p
```

---

## Шаг 7: Финальная проверка готовности сервера

### 7.1 Чеклист проверки

Выполните следующие команды для проверки:

```bash
# 1. Проверка Docker
docker --version && echo "✓ Docker установлен" || echo "✗ Docker НЕ установлен"

# 2. Проверка Docker Compose v1
docker-compose --version | grep "1.29" && echo "✓ Docker Compose v1 установлен" || echo "✗ Docker Compose v1 НЕ установлен"

# 3. Проверка директории проекта
test -d ~/insurance_broker && echo "✓ Директория проекта существует" || echo "✗ Директория проекта НЕ существует"

# 4. Проверка файлов окружения
test -f ~/insurance_broker/.env.prod && echo "✓ .env.prod существует" || echo "✗ .env.prod НЕ существует"
test -f ~/insurance_broker/.env.prod.db && echo "✓ .env.prod.db существует" || echo "✗ .env.prod.db НЕ существует"

# 5. Проверка SSH ключей
test -f ~/.ssh/authorized_keys && echo "✓ SSH ключи настроены" || echo "✗ SSH ключи НЕ настроены"

# 6. Проверка firewall
ufw status | grep "Status: active" && echo "✓ Firewall активен" || echo "✗ Firewall НЕ активен"

# 7. Проверка открытых портов
ufw status | grep -E "80/tcp|443/tcp|22/tcp" && echo "✓ Порты открыты" || echo "✗ Порты НЕ открыты"
```

### 7.2 Автоматический скрипт проверки

Создайте скрипт для быстрой проверки:

```bash
cat > ~/check_server_ready.sh << 'EOF'
#!/bin/bash

echo "=== Проверка готовности сервера Timeweb Cloud ==="
echo ""

ERRORS=0

# Docker
if docker --version > /dev/null 2>&1; then
    echo "✓ Docker установлен: $(docker --version)"
else
    echo "✗ Docker НЕ установлен"
    ERRORS=$((ERRORS + 1))
fi

# Docker Compose v1
if docker-compose --version 2>&1 | grep -q "1.29"; then
    echo "✓ Docker Compose v1 установлен: $(docker-compose --version)"
else
    echo "✗ Docker Compose v1 НЕ установлен или неверная версия"
    ERRORS=$((ERRORS + 1))
fi

# Директория проекта
if [ -d ~/insurance_broker ]; then
    echo "✓ Директория проекта существует"
else
    echo "✗ Директория проекта НЕ существует"
    ERRORS=$((ERRORS + 1))
fi

# Файлы окружения
if [ -f ~/insurance_broker/.env.prod ] && [ -s ~/insurance_broker/.env.prod ]; then
    echo "✓ .env.prod существует и не пуст"
else
    echo "✗ .env.prod НЕ существует или пуст"
    ERRORS=$((ERRORS + 1))
fi

if [ -f ~/insurance_broker/.env.prod.db ] && [ -s ~/insurance_broker/.env.prod.db ]; then
    echo "✓ .env.prod.db существует и не пуст"
else
    echo "✗ .env.prod.db НЕ существует или пуст"
    ERRORS=$((ERRORS + 1))
fi

# SSH ключи
if [ -f ~/.ssh/authorized_keys ]; then
    echo "✓ SSH ключи настроены"
else
    echo "✗ SSH ключи НЕ настроены"
    ERRORS=$((ERRORS + 1))
fi

# Firewall
if ufw status | grep -q "Status: active"; then
    echo "✓ Firewall активен"
else
    echo "✗ Firewall НЕ активен"
    ERRORS=$((ERRORS + 1))
fi

# Порты
if ufw status | grep -qE "80/tcp.*ALLOW" && ufw status | grep -qE "443/tcp.*ALLOW" && ufw status | grep -qE "22/tcp.*ALLOW"; then
    echo "✓ Необходимые порты открыты (22, 80, 443)"
else
    echo "✗ Не все необходимые порты открыты"
    ERRORS=$((ERRORS + 1))
fi

echo ""
if [ $ERRORS -eq 0 ]; then
    echo "=== ✓ Сервер готов к развертыванию! ==="
    exit 0
else
    echo "=== ✗ Обнаружено ошибок: $ERRORS ==="
    echo "Пожалуйста, исправьте ошибки перед продолжением"
    exit 1
fi
EOF

chmod +x ~/check_server_ready.sh
```

Запустите скрипт:

```bash
~/check_server_ready.sh
```

---

## Шаг 8: Обновление GitHub Secrets

После завершения настройки сервера, обновите следующие секреты в GitHub:

1. **DROPLET_HOST**: `109.68.215.223`
2. **DROPLET_USER**: `root` (или другой пользователь, если используете не root)
3. **SSH_PRIVATE_KEY**: содержимое файла `~/.ssh/timeweb_deploy_key` (с вашей локальной машины)

### Инструкции по обновлению GitHub Secrets:

1. Перейдите в репозиторий на GitHub
2. Settings → Secrets and variables → Actions
3. Для каждого секрета:
   - Нажмите на имя секрета
   - Нажмите "Update secret"
   - Вставьте новое значение
   - Нажмите "Update secret"

---

## Следующие шаги

После завершения настройки сервера:

1. ✓ Сервер Timeweb Cloud готов
2. → Настройте DNS (см. DNS_SSL_SETUP.md)
3. → Выполните миграцию базы данных (см. скрипты в scripts/)
4. → Запустите первое развертывание через GitHub Actions

---

## Устранение неполадок

### Проблема: Docker Compose v2 установлен вместо v1

```bash
# Удаление v2
apt remove docker-compose-plugin

# Установка v1 (см. Шаг 2)
```

### Проблема: SSH подключение не работает

```bash
# Проверка SSH сервиса
systemctl status ssh

# Проверка прав на .ssh директорию
ls -la ~/.ssh/

# Проверка логов SSH
tail -f /var/log/auth.log
```

### Проблема: UFW блокирует SSH после включения

Если вы потеряли SSH доступ:
1. Используйте консоль Timeweb Cloud (веб-интерфейс)
2. Отключите UFW: `ufw disable`
3. Добавьте правило для SSH: `ufw allow 22/tcp`
4. Включите UFW снова: `ufw enable`

### Проблема: Docker Hub rate limit при тестировании

Если вы видите ошибку "You have reached your unauthenticated pull rate limit":
- Это не критично для проекта
- Образы проекта собираются локально из Dockerfile
- Для тестирования Docker можно использовать:
  ```bash
  # Проверка что Docker daemon работает
  systemctl status docker

  # Проверка что Docker может создавать контейнеры
  docker info
  ```

### Проблема: Недостаточно места на диске

```bash
# Проверка использования диска
df -h

# Очистка Docker
docker system prune -a --volumes
```

---

## Контакты и поддержка

Если возникли проблемы при настройке сервера:
- Проверьте документацию Timeweb Cloud
- Обратитесь в поддержку Timeweb Cloud
- Проверьте логи: `journalctl -xe`

---

**Дата создания**: 2024-12-04
**Версия**: 1.0
**Статус**: Готов к использованию
