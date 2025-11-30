# Руководство по развертыванию на Digital Ocean

Это руководство описывает полный процесс развертывания Django-приложения "Система управления полисами для страхового брокера" на Digital Ocean Droplet с использованием Docker и автоматизации через GitHub Actions.

## Быстрый старт

Для быстрой настройки Droplet используйте автоматизированный скрипт:

```bash
# SSH в ваш новый Droplet
ssh root@YOUR_DROPLET_IP

# Запустите автоматизированный скрипт установки
curl -fsSL https://raw.githubusercontent.com/YOUR_USERNAME/YOUR_REPO/main/scripts/setup-droplet.sh | bash

# Проверьте установку
curl -fsSL https://raw.githubusercontent.com/YOUR_USERNAME/YOUR_REPO/main/scripts/verify-droplet.sh | bash
```

Для подробных инструкций см. [DROPLET_QUICK_START.md](./DROPLET_QUICK_START.md) или [DROPLET_SETUP.md](./DROPLET_SETUP.md).

## Содержание

1. [Создание Digital Ocean Droplet](#1-создание-digital-ocean-droplet)
2. [Установка Docker и Docker Compose](#2-установка-docker-и-docker-compose)
3. [Настройка Firewall (UFW)](#3-настройка-firewall-ufw)
4. [Настройка SSH ключей](#4-настройка-ssh-ключей)
5. [Настройка DNS для onbr.site](#5-настройка-dns-для-onbrsite)
6. [Настройка автозапуска контейнеров](#6-настройка-автозапуска-контейнеров)
7. [Первоначальное развертывание](#7-первоначальное-развертывание)
8. [Troubleshooting](#8-troubleshooting)

## Дополнительные руководства

- **[DROPLET_QUICK_START.md](./DROPLET_QUICK_START.md)** - Быстрое руководство по настройке Droplet (5 минут)
- **[DROPLET_SETUP.md](./DROPLET_SETUP.md)** - Подробное руководство по настройке Droplet с объяснениями

---

## 1. Создание Digital Ocean Droplet

### 1.1 Требования

- Аккаунт на Digital Ocean
- Минимальные характеристики Droplet:
  - **CPU**: 2 vCPU
  - **RAM**: 2 GB
  - **Storage**: 50 GB SSD
  - **OS**: Ubuntu 22.04 LTS

### 1.2 Создание Droplet через веб-интерфейс

1. Войдите в панель управления Digital Ocean: https://cloud.digitalocean.com/

2. Нажмите **Create** → **Droplets**

3. Выберите параметры:
   - **Image**: Ubuntu 22.04 (LTS) x64
   - **Plan**: Basic
   - **CPU options**: Regular (2 GB RAM / 1 vCPU / 50 GB SSD) или выше
   - **Datacenter region**: Выберите ближайший к вашим пользователям (например, Frankfurt для Европы)
   - **Authentication**: SSH keys (рекомендуется) или Password
   - **Hostname**: `insurance-broker-prod` или другое понятное имя

4. Нажмите **Create Droplet**

5. Дождитесь создания Droplet (обычно 1-2 минуты)

6. Запишите **IP адрес** Droplet - он понадобится для дальнейшей настройки

### 1.3 Создание Droplet через CLI (альтернатива)

Если у вас установлен `doctl` (Digital Ocean CLI):

```bash
# Установка doctl (macOS)
brew install doctl

# Аутентификация
doctl auth init

# Создание Droplet
doctl compute droplet create insurance-broker-prod \
  --image ubuntu-22-04-x64 \
  --size s-2vcpu-2gb \
  --region fra1 \
  --ssh-keys YOUR_SSH_KEY_ID \
  --wait

# Получение IP адреса
doctl compute droplet list
```

---

## 2. Установка Docker и Docker Compose

### 2.1 Подключение к Droplet

```bash
ssh root@YOUR_DROPLET_IP
```

### 2.2 Обновление системы

```bash
# Обновление списка пакетов
apt update

# Обновление установленных пакетов
apt upgrade -y

# Установка необходимых утилит
apt install -y curl git vim ufw
```

### 2.3 Установка Docker

```bash
# Удаление старых версий Docker (если есть)
apt remove -y docker docker-engine docker.io containerd runc

# Установка зависимостей
apt install -y \
    ca-certificates \
    curl \
    gnupg \
    lsb-release

# Добавление официального GPG ключа Docker
mkdir -p /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg

# Добавление репозитория Docker
echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu \
  $(lsb_release -cs) stable" | tee /etc/apt/sources.list.d/docker.list > /dev/null

# Установка Docker Engine
apt update
apt install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

# Проверка установки
docker --version
docker compose version
```

Ожидаемый вывод:
```
Docker version 24.0.x, build xxxxx
Docker Compose version v2.20.x
```

### 2.4 Настройка Docker для работы без sudo (опционально)

```bash
# Создание пользователя для приложения (рекомендуется)
adduser --disabled-password --gecos "" deploy

# Добавление пользователя в группу docker
usermod -aG docker deploy

# Проверка
su - deploy
docker ps
exit
```

### 2.5 Проверка работы Docker

```bash
# Запуск тестового контейнера
docker run hello-world

# Проверка Docker Compose
docker compose version
```

---

## 3. Настройка Firewall (UFW)

### 3.1 Включение UFW

```bash
# Проверка статуса
ufw status

# Настройка правил по умолчанию
ufw default deny incoming
ufw default allow outgoing
```

### 3.2 Разрешение необходимых портов

```bash
# SSH (ВАЖНО: разрешите SSH перед включением firewall!)
ufw allow 22/tcp

# HTTP
ufw allow 80/tcp

# HTTPS
ufw allow 443/tcp

# Проверка правил
ufw show added
```

### 3.3 Включение firewall

```bash
# Включение UFW
ufw enable

# Подтверждение (введите 'y')
# Command may disrupt existing ssh connections. Proceed with operation (y|n)? y

# Проверка статуса
ufw status verbose
```

Ожидаемый вывод:
```
Status: active
Logging: on (low)
Default: deny (incoming), allow (outgoing), disabled (routed)
New profiles: skip

To                         Action      From
--                         ------      ----
22/tcp                     ALLOW IN    Anywhere
80/tcp                     ALLOW IN    Anywhere
443/tcp                    ALLOW IN    Anywhere
22/tcp (v6)                ALLOW IN    Anywhere (v6)
80/tcp (v6)                ALLOW IN    Anywhere (v6)
443/tcp (v6)               ALLOW IN    Anywhere (v6)
```

### 3.4 Дополнительные настройки безопасности (опционально)

```bash
# Ограничение количества SSH подключений (защита от брутфорса)
ufw limit 22/tcp

# Установка fail2ban для дополнительной защиты
apt install -y fail2ban

# Создание конфигурации fail2ban
cat > /etc/fail2ban/jail.local << EOF
[DEFAULT]
bantime = 3600
findtime = 600
maxretry = 5

[sshd]
enabled = true
port = 22
EOF

# Запуск fail2ban
systemctl enable fail2ban
systemctl start fail2ban
systemctl status fail2ban
```

---

## 4. Настройка SSH ключей

### 4.1 Генерация SSH ключа (на локальной машине)

Если у вас еще нет SSH ключа:

```bash
# На вашей локальной машине
ssh-keygen -t ed25519 -C "your_email@example.com"

# Или RSA (если ed25519 не поддерживается)
ssh-keygen -t rsa -b 4096 -C "your_email@example.com"

# Сохраните ключ в ~/.ssh/id_ed25519 (по умолчанию)
# Можете установить passphrase для дополнительной безопасности
```

### 4.2 Копирование публичного ключа на Droplet

```bash
# Метод 1: Использование ssh-copy-id (рекомендуется)
ssh-copy-id root@YOUR_DROPLET_IP

# Метод 2: Ручное копирование
cat ~/.ssh/id_ed25519.pub | ssh root@YOUR_DROPLET_IP "mkdir -p ~/.ssh && cat >> ~/.ssh/authorized_keys"
```

### 4.3 Проверка подключения

```bash
# Подключение без пароля
ssh root@YOUR_DROPLET_IP

# Если подключение успешно, вы вошли на сервер
```

### 4.4 Отключение аутентификации по паролю (рекомендуется)

```bash
# На Droplet
vim /etc/ssh/sshd_config

# Найдите и измените следующие строки:
# PasswordAuthentication no
# PubkeyAuthentication yes
# PermitRootLogin prohibit-password

# Перезапуск SSH сервиса
systemctl restart sshd
```

### 4.5 Настройка SSH ключа для GitHub Actions

Для автоматического деплоя через GitHub Actions нужен отдельный SSH ключ:

```bash
# На локальной машине создайте отдельный ключ для CI/CD
ssh-keygen -t ed25519 -C "github-actions" -f ~/.ssh/github_actions_deploy

# Скопируйте публичный ключ на Droplet
ssh-copy-id -i ~/.ssh/github_actions_deploy.pub root@YOUR_DROPLET_IP

# Скопируйте ПРИВАТНЫЙ ключ для добавления в GitHub Secrets
cat ~/.ssh/github_actions_deploy
# Скопируйте весь вывод (включая BEGIN и END строки)
```

Добавьте приватный ключ в GitHub Secrets:
1. Перейдите в репозиторий на GitHub
2. Settings → Secrets and variables → Actions
3. New repository secret
4. Name: `SSH_PRIVATE_KEY`
5. Value: вставьте содержимое приватного ключа
6. Add secret

---

## 5. Настройка DNS для onbr.site

### 5.1 Получение IP адреса Droplet

```bash
# Если вы на Droplet
curl ifconfig.me

# Или из панели Digital Ocean
# Скопируйте IP адрес из списка Droplets
```

### 5.2 Настройка DNS записей

Перейдите к вашему DNS провайдеру (где зарегистрирован домен onbr.site) и добавьте следующие записи:

#### A записи

| Type | Hostname | Value | TTL |
|------|----------|-------|-----|
| A | @ | YOUR_DROPLET_IP | 3600 |
| A | www | YOUR_DROPLET_IP | 3600 |

Где:
- `@` означает корневой домен (onbr.site)
- `www` означает поддомен (www.onbr.site)
- `YOUR_DROPLET_IP` - IP адрес вашего Droplet
- `TTL` - время жизни записи в секундах (3600 = 1 час)

### 5.3 Настройка через Digital Ocean DNS (если используете)

Если вы используете Digital Ocean для управления DNS:

```bash
# Через веб-интерфейс:
# 1. Networking → Domains → Add Domain
# 2. Введите onbr.site
# 3. Добавьте A записи:
#    - Hostname: @ → Droplet: insurance-broker-prod
#    - Hostname: www → Droplet: insurance-broker-prod

# Через CLI:
doctl compute domain create onbr.site
doctl compute domain records create onbr.site --record-type A --record-name @ --record-data YOUR_DROPLET_IP
doctl compute domain records create onbr.site --record-type A --record-name www --record-data YOUR_DROPLET_IP
```

### 5.4 Проверка распространения DNS

DNS изменения могут занять от нескольких минут до 48 часов для полного распространения.

```bash
# Проверка A записи
dig onbr.site +short
dig www.onbr.site +short

# Или с помощью nslookup
nslookup onbr.site
nslookup www.onbr.site

# Онлайн инструменты для проверки:
# https://dnschecker.org/
# https://www.whatsmydns.net/
```

Ожидаемый результат:
```
YOUR_DROPLET_IP
```

### 5.5 Обновление NS записей (если нужно)

Если домен зарегистрирован не на Digital Ocean, но вы хотите использовать их DNS:

1. Получите nameservers Digital Ocean:
   - ns1.digitalocean.com
   - ns2.digitalocean.com
   - ns3.digitalocean.com

2. Обновите NS записи у вашего регистратора домена

3. Дождитесь распространения (24-48 часов)

---

## 6. Настройка автозапуска контейнеров

### 6.1 Включение автозапуска Docker

```bash
# Включение Docker для автозапуска при загрузке системы
systemctl enable docker

# Проверка статуса
systemctl is-enabled docker
```

Ожидаемый вывод: `enabled`

### 6.2 Настройка restart policy в docker-compose

В файле `docker-compose.prod.yml` должны быть указаны restart policies для всех сервисов:

```yaml
services:
  web:
    restart: unless-stopped
    # или restart: always

  db:
    restart: unless-stopped

  redis:
    restart: unless-stopped

  celery_worker:
    restart: unless-stopped

  celery_beat:
    restart: unless-stopped

  nginx:
    restart: unless-stopped
```

**Разница между политиками:**
- `always` - всегда перезапускать контейнер при остановке
- `unless-stopped` - перезапускать, если контейнер не был остановлен вручную
- `on-failure` - перезапускать только при ошибке

**Рекомендация:** Используйте `unless-stopped` для production

### 6.3 Создание systemd сервиса (альтернативный метод)

Для более тонкого контроля можно создать systemd сервис:

```bash
# Создание сервиса
cat > /etc/systemd/system/insurance-broker.service << EOF
[Unit]
Description=Insurance Broker Docker Compose Application
Requires=docker.service
After=docker.service

[Service]
Type=oneshot
RemainAfterExit=yes
WorkingDirectory=/opt/insurance_broker
ExecStart=/usr/bin/docker compose -f docker-compose.prod.yml up -d
ExecStop=/usr/bin/docker compose -f docker-compose.prod.yml down
TimeoutStartSec=0

[Install]
WantedBy=multi-user.target
EOF

# Перезагрузка systemd
systemctl daemon-reload

# Включение автозапуска
systemctl enable insurance-broker.service

# Запуск сервиса
systemctl start insurance-broker.service

# Проверка статуса
systemctl status insurance-broker.service
```

### 6.4 Проверка автозапуска

```bash
# Перезагрузка сервера
reboot

# После перезагрузки подключитесь снова
ssh root@YOUR_DROPLET_IP

# Проверка запущенных контейнеров
docker ps

# Все контейнеры должны быть в статусе "Up"
```

### 6.5 Мониторинг контейнеров

```bash
# Просмотр статуса всех контейнеров
docker ps -a

# Просмотр логов
docker compose -f docker-compose.prod.yml logs -f

# Просмотр логов конкретного сервиса
docker compose -f docker-compose.prod.yml logs -f web

# Проверка использования ресурсов
docker stats
```

---

## 7. Первоначальное развертывание

### 7.1 Подготовка директории проекта

```bash
# Создание директории для проекта
mkdir -p /opt/insurance_broker
cd /opt/insurance_broker

# Клонирование репозитория (если используете Git)
git clone https://github.com/YOUR_USERNAME/insurance_broker.git .

# Или создание структуры вручную
mkdir -p nginx certbot/conf certbot/www logs
```

### 7.2 Создание файлов переменных окружения

```bash
# Создание .env.prod
cat > .env.prod << EOF
# Django
SECRET_KEY=$(openssl rand -base64 50)
DEBUG=False
ALLOWED_HOSTS=onbr.site,www.onbr.site

# Database
DB_NAME=insurance_broker_prod
DB_USER=postgres
DB_PASSWORD=$(openssl rand -base64 32)
DB_HOST=db
DB_PORT=5432

# Celery
CELERY_BROKER_URL=redis://redis:6379/0
CELERY_RESULT_BACKEND=redis://redis:6379/0

# Email (настройте под ваш SMTP)
EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend
EMAIL_HOST=smtp.gmail.com
EMAIL_PORT=587
EMAIL_USE_TLS=True
EMAIL_HOST_USER=your_email@gmail.com
EMAIL_HOST_PASSWORD=your_app_password
EOF

# Создание .env.prod.db
cat > .env.prod.db << EOF
POSTGRES_DB=insurance_broker_prod
POSTGRES_USER=postgres
POSTGRES_PASSWORD=$(grep DB_PASSWORD .env.prod | cut -d'=' -f2)
EOF

# Установка правильных прав доступа
chmod 600 .env.prod .env.prod.db
```

**ВАЖНО:** Сохраните эти пароли в безопасном месте!

### 7.3 Первоначальный запуск без SSL

Сначала запустим приложение без SSL для получения сертификата:

```bash
# Запуск контейнеров
docker compose -f docker-compose.prod.yml up -d

# Проверка статуса
docker compose -f docker-compose.prod.yml ps

# Просмотр логов
docker compose -f docker-compose.prod.yml logs -f
```

### 7.4 Получение SSL сертификата

```bash
# Запуск скрипта инициализации Let's Encrypt
chmod +x scripts/init-letsencrypt.sh
./scripts/init-letsencrypt.sh

# Или вручную:
docker compose -f docker-compose.prod.yml run --rm certbot certonly \
  --webroot \
  --webroot-path=/var/www/certbot \
  -d onbr.site \
  -d www.onbr.site \
  --email admin@onbr.site \
  --agree-tos \
  --no-eff-email
```

### 7.5 Обновление Nginx конфигурации для HTTPS

После получения сертификата обновите `nginx/default.conf` для использования SSL и перезапустите Nginx:

```bash
# Перезапуск Nginx
docker compose -f docker-compose.prod.yml restart nginx

# Проверка логов Nginx
docker compose -f docker-compose.prod.yml logs nginx
```

### 7.6 Проверка работы приложения

```bash
# Проверка HTTP (должен редиректить на HTTPS)
curl -I http://onbr.site

# Проверка HTTPS
curl -I https://onbr.site

# Проверка SSL сертификата
openssl s_client -connect onbr.site:443 -servername onbr.site < /dev/null
```

### 7.7 Создание суперпользователя Django

```bash
# Создание суперпользователя
docker compose -f docker-compose.prod.yml exec web python manage.py createsuperuser

# Или использование скрипта
docker compose -f docker-compose.prod.yml exec web python create_superuser.py
```

### 7.8 Загрузка начальных данных (если есть)

```bash
# Загрузка fixtures
docker compose -f docker-compose.prod.yml exec web python manage.py loaddata fixtures/initial_data.json
```

---

## 8. Troubleshooting

### 8.1 Контейнер не запускается

```bash
# Проверка логов
docker compose -f docker-compose.prod.yml logs SERVICE_NAME

# Проверка конфигурации
docker compose -f docker-compose.prod.yml config

# Пересборка образа
docker compose -f docker-compose.prod.yml build --no-cache SERVICE_NAME
docker compose -f docker-compose.prod.yml up -d SERVICE_NAME
```

### 8.2 Ошибки подключения к базе данных

```bash
# Проверка, что PostgreSQL запущен
docker compose -f docker-compose.prod.yml ps db

# Проверка логов PostgreSQL
docker compose -f docker-compose.prod.yml logs db

# Проверка подключения из web контейнера
docker compose -f docker-compose.prod.yml exec web python manage.py dbshell

# Проверка переменных окружения
docker compose -f docker-compose.prod.yml exec web env | grep DB_
```

### 8.3 Проблемы с SSL сертификатами

```bash
# Проверка существования сертификатов
ls -la certbot/conf/live/onbr.site/

# Проверка логов certbot
docker compose -f docker-compose.prod.yml logs certbot

# Ручное обновление сертификата
docker compose -f docker-compose.prod.yml run --rm certbot renew

# Проверка конфигурации Nginx
docker compose -f docker-compose.prod.yml exec nginx nginx -t
```

### 8.4 Ошибки миграций

```bash
# Просмотр статуса миграций
docker compose -f docker-compose.prod.yml exec web python manage.py showmigrations

# Применение миграций вручную
docker compose -f docker-compose.prod.yml exec web python manage.py migrate

# Откат миграции
docker compose -f docker-compose.prod.yml exec web python manage.py migrate APP_NAME MIGRATION_NAME
```

### 8.5 Проблемы с Celery

```bash
# Проверка статуса Celery worker
docker compose -f docker-compose.prod.yml logs celery_worker

# Проверка подключения к Redis
docker compose -f docker-compose.prod.yml exec redis redis-cli ping

# Проверка очереди задач
docker compose -f docker-compose.prod.yml exec redis redis-cli
> KEYS *
> LLEN celery

# Перезапуск Celery
docker compose -f docker-compose.prod.yml restart celery_worker celery_beat
```

### 8.6 Статические файлы не отображаются

```bash
# Пересборка статических файлов
docker compose -f docker-compose.prod.yml exec web python manage.py collectstatic --noinput

# Проверка прав доступа
docker compose -f docker-compose.prod.yml exec web ls -la /app/staticfiles/

# Проверка конфигурации Nginx
docker compose -f docker-compose.prod.yml exec nginx cat /etc/nginx/conf.d/default.conf
```

### 8.7 Высокое использование ресурсов

```bash
# Проверка использования ресурсов
docker stats

# Проверка логов на ошибки
docker compose -f docker-compose.prod.yml logs --tail=100

# Перезапуск проблемного контейнера
docker compose -f docker-compose.prod.yml restart SERVICE_NAME

# Очистка неиспользуемых ресурсов
docker system prune -a
```

### 8.8 Проблемы с firewall

```bash
# Проверка статуса UFW
ufw status verbose

# Проверка логов UFW
tail -f /var/log/ufw.log

# Временное отключение для диагностики (НЕ рекомендуется для production)
ufw disable

# Повторное включение
ufw enable
```

### 8.9 Rollback к предыдущей версии

```bash
# Остановка текущих контейнеров
docker compose -f docker-compose.prod.yml down

# Откат к предыдущему коммиту
git log --oneline -10
git checkout PREVIOUS_COMMIT_HASH

# Запуск предыдущей версии
docker compose -f docker-compose.prod.yml up -d --build

# Откат миграций (если нужно)
docker compose -f docker-compose.prod.yml exec web python manage.py migrate APP_NAME PREVIOUS_MIGRATION
```

---

## Полезные команды

### Управление контейнерами

```bash
# Запуск всех сервисов
docker compose -f docker-compose.prod.yml up -d

# Остановка всех сервисов
docker compose -f docker-compose.prod.yml down

# Перезапуск конкретного сервиса
docker compose -f docker-compose.prod.yml restart SERVICE_NAME

# Просмотр логов
docker compose -f docker-compose.prod.yml logs -f SERVICE_NAME

# Выполнение команды в контейнере
docker compose -f docker-compose.prod.yml exec SERVICE_NAME COMMAND
```

### Обслуживание

```bash
# Создание бэкапа базы данных
docker compose -f docker-compose.prod.yml exec db pg_dump -U postgres insurance_broker_prod > backup_$(date +%Y%m%d).sql

# Восстановление из бэкапа
cat backup_20240101.sql | docker compose -f docker-compose.prod.yml exec -T db psql -U postgres insurance_broker_prod

# Очистка старых образов и контейнеров
docker system prune -a

# Просмотр использования диска
df -h
docker system df
```

### Мониторинг

```bash
# Статус всех контейнеров
docker compose -f docker-compose.prod.yml ps

# Использование ресурсов
docker stats

# Проверка здоровья приложения
curl -I https://onbr.site/admin/

# Проверка логов системы
journalctl -u docker -f
```

---

## Контрольный список развертывания

- [ ] Создан Droplet на Digital Ocean
- [ ] Установлены Docker и Docker Compose
- [ ] Настроен firewall (UFW)
- [ ] Настроены SSH ключи
- [ ] Настроены DNS записи для onbr.site
- [ ] Настроен автозапуск Docker
- [ ] Созданы файлы .env.prod и .env.prod.db
- [ ] Запущены Docker контейнеры
- [ ] Получен SSL сертификат от Let's Encrypt
- [ ] Настроен HTTPS редирект
- [ ] Создан суперпользователь Django
- [ ] Загружены начальные данные (если есть)
- [ ] Проверена работа приложения
- [ ] Настроены GitHub Secrets для CI/CD
- [ ] Протестирован автоматический деплой

---

## Дополнительные ресурсы

### Документация проекта

- [Руководство по резервному копированию и восстановлению](BACKUP_RESTORE.md) - Полное руководство по бэкапам базы данных и медиа файлов
- [Структура проекта](PROJECT_STRUCTURE.md) - Описание структуры проекта
- [Переменные окружения](ENVIRONMENT_VARIABLES.md) - Описание всех переменных окружения
- [Руководство пользователя](USER_GUIDE.md) - Руководство по использованию приложения

### Внешняя документация

- [Документация Docker](https://docs.docker.com/)
- [Документация Docker Compose](https://docs.docker.com/compose/)
- [Документация Digital Ocean](https://docs.digitalocean.com/)
- [Документация Let's Encrypt](https://letsencrypt.org/docs/)
- [Документация Django Deployment](https://docs.djangoproject.com/en/4.2/howto/deployment/)
- [UFW Documentation](https://help.ubuntu.com/community/UFW)

---

## Поддержка

Если у вас возникли проблемы:

1. Проверьте раздел [Troubleshooting](#8-troubleshooting)
2. Просмотрите логи контейнеров
3. Проверьте документацию проекта
4. Обратитесь к команде разработки

---

**Последнее обновление:** 2024
**Версия документа:** 1.0
