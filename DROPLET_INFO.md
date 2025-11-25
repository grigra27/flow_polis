# 📋 Информация о Droplet

## Основная информация

| Параметр | Значение |
|----------|----------|
| **IP адрес** | `64.227.75.233` |
| **Домен** | `onbr.site` |
| **WWW домен** | `www.onbr.site` |
| **SSH пользователь** | `root` |
| **Директория приложения** | `/opt/insurance_broker` |
| **ОС** | Ubuntu 22.04 LTS |

## Быстрое подключение

### Вариант 1: Используя скрипт
```bash
./connect-droplet.sh
```

### Вариант 2: Напрямую
```bash
ssh root@64.227.75.233
cd /opt/insurance_broker
```

## DNS записи

Убедитесь, что DNS настроен правильно:

```bash
# Проверка основного домена
dig onbr.site +short
# Должен вернуть: 64.227.75.233

# Проверка www поддомена
dig www.onbr.site +short
# Должен вернуть: 64.227.75.233
```

### Настройка DNS

В вашем DNS провайдере добавьте следующие A записи:

| Type | Hostname | Value | TTL |
|------|----------|-------|-----|
| A | @ | 64.227.75.233 | 3600 |
| A | www | 64.227.75.233 | 3600 |

## Открытые порты

| Порт | Сервис | Описание |
|------|--------|----------|
| 22 | SSH | Удаленный доступ |
| 80 | HTTP | Веб-трафик (редирект на HTTPS) |
| 443 | HTTPS | Защищенный веб-трафик |

## Структура приложения на Droplet

```
/opt/insurance_broker/
├── apps/                    # Django приложения
├── config/                  # Конфигурация Django
├── templates/               # HTML шаблоны
├── static/                  # Статические файлы (исходники)
├── nginx/                   # Конфигурация Nginx
│   └── default.conf
├── certbot/                 # SSL сертификаты
│   ├── conf/
│   └── www/
├── scripts/                 # Скрипты управления
├── logs/                    # Логи приложения
├── docker-compose.prod.yml  # Production конфигурация
├── .env.prod               # Production переменные окружения
└── .env.prod.db            # Переменные БД
```

## Docker контейнеры

| Контейнер | Порт | Описание |
|-----------|------|----------|
| nginx | 80, 443 | Веб-сервер и reverse proxy |
| web | 8000 | Django + Gunicorn |
| db | 5432 | PostgreSQL |
| redis | 6379 | Redis (Celery broker) |
| celery_worker | - | Celery worker |
| celery_beat | - | Celery scheduler |
| certbot | - | SSL сертификаты |

## Полезные команды

### Статус сервисов
```bash
ssh root@64.227.75.233 "cd /opt/insurance_broker && docker compose -f docker-compose.prod.yml ps"
```

### Просмотр логов
```bash
ssh root@64.227.75.233 "cd /opt/insurance_broker && docker compose -f docker-compose.prod.yml logs -f web"
```

### Перезапуск приложения
```bash
ssh root@64.227.75.233 "cd /opt/insurance_broker && docker compose -f docker-compose.prod.yml restart web"
```

### Выполнение Django команд
```bash
ssh root@64.227.75.233 "cd /opt/insurance_broker && docker compose -f docker-compose.prod.yml exec web python manage.py [command]"
```

## Мониторинг

### Проверка доступности сайта
```bash
curl -I https://onbr.site
```

### Проверка SSL сертификата
```bash
openssl s_client -connect onbr.site:443 -servername onbr.site < /dev/null | grep "Verify return code"
```

### Проверка использования ресурсов
```bash
ssh root@64.227.75.233 "docker stats --no-stream"
```

## Бэкапы

### Создание бэкапа БД
```bash
ssh root@64.227.75.233 "cd /opt/insurance_broker && docker compose -f docker-compose.prod.yml exec db pg_dump -U postgres insurance_broker_prod > backup_\$(date +%Y%m%d).sql"
```

### Скачивание бэкапа на локальную машину
```bash
scp root@64.227.75.233:/opt/insurance_broker/backup_*.sql ./backups/
```

## Безопасность

### Firewall статус
```bash
ssh root@64.227.75.233 "sudo ufw status verbose"
```

### Обновление системы
```bash
ssh root@64.227.75.233 "sudo apt update && sudo apt upgrade -y"
```

### Проверка fail2ban
```bash
ssh root@64.227.75.233 "sudo fail2ban-client status sshd"
```

## Troubleshooting

### Если сайт не доступен

1. Проверьте статус контейнеров:
```bash
ssh root@64.227.75.233 "cd /opt/insurance_broker && docker compose -f docker-compose.prod.yml ps"
```

2. Проверьте логи:
```bash
ssh root@64.227.75.233 "cd /opt/insurance_broker && docker compose -f docker-compose.prod.yml logs --tail=100"
```

3. Проверьте firewall:
```bash
ssh root@64.227.75.233 "sudo ufw status"
```

### Если SSL не работает

1. Проверьте сертификаты:
```bash
ssh root@64.227.75.233 "cd /opt/insurance_broker && docker compose -f docker-compose.prod.yml run --rm certbot certificates"
```

2. Обновите сертификат:
```bash
ssh root@64.227.75.233 "cd /opt/insurance_broker && docker compose -f docker-compose.prod.yml run --rm certbot renew"
```

## Контакты для поддержки

- **Документация проекта:** [docs/](./docs/)
- **GitHub Issues:** [создать issue](https://github.com/YOUR_REPO/issues)

---

**Дата создания:** 2024-11-25  
**Последнее обновление:** 2024-11-25  
**Статус:** Активен
