# Мониторинг и логирование Docker окружения

Данный документ описывает команды и инструменты для мониторинга и просмотра логов Docker контейнеров системы управления полисами.

## Содержание

- [Просмотр логов](#просмотр-логов)
- [Мониторинг контейнеров](#мониторинг-контейнеров)
- [Health Checks](#health-checks)
- [Использование ресурсов](#использование-ресурсов)
- [Troubleshooting](#troubleshooting)

## Просмотр логов

### Использование скрипта view-logs.sh

Мы предоставляем удобный скрипт для просмотра логов:

```bash
# Показать последние 100 строк логов всех сервисов
./scripts/view-logs.sh

# Следить за логами конкретного сервиса в реальном времени
./scripts/view-logs.sh web -f

# Показать последние 50 строк с временными метками
./scripts/view-logs.sh celery_worker -n 50 -t

# Следить за всеми логами с временными метками
./scripts/view-logs.sh all -f -t

# Просмотр логов в dev окружении
./scripts/view-logs.sh web --dev
```

### Прямые команды Docker Compose

#### Просмотр логов всех сервисов

```bash
# Production
docker compose -f docker-compose.prod.yml logs

# Development
docker compose -f docker-compose.dev.yml logs
```

#### Просмотр логов конкретного сервиса

```bash
# Django приложение
docker compose -f docker-compose.prod.yml logs web

# PostgreSQL база данных
docker compose -f docker-compose.prod.yml logs db

# Redis
docker compose -f docker-compose.prod.yml logs redis

# Celery Worker
docker compose -f docker-compose.prod.yml logs celery_worker

# Celery Beat
docker compose -f docker-compose.prod.yml logs celery_beat

# Nginx
docker compose -f docker-compose.prod.yml logs nginx

# Certbot
docker compose -f docker-compose.prod.yml logs certbot
```

#### Следить за логами в реальном времени

```bash
# Следить за логами web сервиса
docker compose -f docker-compose.prod.yml logs -f web

# Следить за логами всех сервисов
docker compose -f docker-compose.prod.yml logs -f

# Следить за логами с временными метками
docker compose -f docker-compose.prod.yml logs -f -t
```

#### Ограничение количества строк

```bash
# Показать последние 50 строк
docker compose -f docker-compose.prod.yml logs --tail=50 web

# Показать последние 100 строк всех сервисов
docker compose -f docker-compose.prod.yml logs --tail=100
```

### Прямые команды Docker

```bash
# Просмотр логов по имени контейнера
docker logs insurance_broker_web

# Следить за логами
docker logs -f insurance_broker_web

# Последние 100 строк с временными метками
docker logs --tail=100 -t insurance_broker_web

# Логи за последние 10 минут
docker logs --since=10m insurance_broker_web

# Логи с определенного времени
docker logs --since="2024-01-01T00:00:00" insurance_broker_web
```

## Конфигурация логирования

### Настройки в docker-compose.prod.yml

Все сервисы настроены с следующими параметрами логирования:

```yaml
logging:
  driver: "json-file"
  options:
    max-size: "10m"      # Максимальный размер одного лог-файла
    max-file: "3"        # Количество ротируемых файлов
    tag: "{{.Name}}"     # Тег для идентификации контейнера
```

**Итого:** Каждый контейнер хранит максимум ~30MB логов (3 файла по 10MB).

### Ротация логов

Docker автоматически ротирует логи согласно настройкам:
- Когда лог-файл достигает 10MB, создается новый файл
- Хранятся только последние 3 файла
- Старые файлы автоматически удаляются

## Мониторинг контейнеров

### Статус контейнеров

```bash
# Список всех контейнеров
docker compose -f docker-compose.prod.yml ps

# Детальная информация
docker compose -f docker-compose.prod.yml ps -a

# Только запущенные контейнеры
docker ps

# Все контейнеры (включая остановленные)
docker ps -a
```

### Проверка работоспособности

```bash
# Проверить статус всех сервисов
docker compose -f docker-compose.prod.yml ps

# Вывод должен показывать "healthy" для сервисов с health checks
```

Пример вывода:
```
NAME                              STATUS              PORTS
insurance_broker_web              Up (healthy)        8000/tcp
insurance_broker_db               Up (healthy)        5432/tcp
insurance_broker_redis            Up (healthy)        6379/tcp
insurance_broker_celery_worker    Up (healthy)
insurance_broker_nginx            Up (healthy)        0.0.0.0:80->80/tcp, 0.0.0.0:443->443/tcp
```

## Health Checks

### Настроенные Health Checks

Все основные сервисы имеют health checks:

#### Web (Django)
- **Команда:** `curl -f http://localhost:8000/admin/login/`
- **Интервал:** 30 секунд
- **Таймаут:** 10 секунд
- **Попытки:** 3
- **Период запуска:** 40 секунд

#### Database (PostgreSQL)
- **Команда:** `pg_isready -U postgres`
- **Интервал:** 10 секунд
- **Таймаут:** 5 секунд
- **Попытки:** 5

#### Redis
- **Команда:** `redis-cli ping`
- **Интервал:** 10 секунд
- **Таймаут:** 5 секунд
- **Попытки:** 5

#### Celery Worker
- **Команда:** `celery -A config inspect ping`
- **Интервал:** 30 секунд
- **Таймаут:** 10 секунд
- **Попытки:** 3
- **Период запуска:** 30 секунд

#### Nginx
- **Команда:** `wget --quiet --tries=1 --spider http://localhost/`
- **Интервал:** 30 секунд
- **Таймаут:** 10 секунд
- **Попытки:** 3

### Проверка Health Check вручную

```bash
# Проверить health status конкретного контейнера
docker inspect --format='{{.State.Health.Status}}' insurance_broker_web

# Детальная информация о health check
docker inspect insurance_broker_web | jq '.[0].State.Health'
```

## Использование ресурсов

### Мониторинг в реальном времени

```bash
# Использование CPU, памяти, сети и диска всех контейнеров
docker stats

# Только определенные контейнеры
docker stats insurance_broker_web insurance_broker_db

# Без потоковой передачи (один снимок)
docker stats --no-stream
```

Пример вывода:
```
CONTAINER ID   NAME                       CPU %     MEM USAGE / LIMIT     MEM %     NET I/O           BLOCK I/O
abc123         insurance_broker_web       2.5%      256MiB / 2GiB        12.5%     1.2MB / 850KB     10MB / 5MB
def456         insurance_broker_db        1.2%      128MiB / 2GiB        6.25%     500KB / 300KB     50MB / 20MB
```

### Использование дискового пространства

```bash
# Размер всех контейнеров
docker ps -s

# Использование дискового пространства Docker
docker system df

# Детальная информация
docker system df -v
```

### Информация о volumes

```bash
# Список всех volumes
docker volume ls

# Детальная информация о volume
docker volume inspect onlinepolis_postgres_data

# Размер volumes
docker system df -v | grep -A 10 "Local Volumes"
```

## Troubleshooting

### Контейнер не запускается

```bash
# Проверить логи контейнера
docker compose -f docker-compose.prod.yml logs web

# Проверить последние события
docker events --since 10m

# Инспектировать контейнер
docker inspect insurance_broker_web

# Проверить exit code
docker inspect insurance_broker_web | jq '.[0].State.ExitCode'
```

### Проблемы с подключением к базе данных

```bash
# Проверить, что PostgreSQL запущен и healthy
docker compose -f docker-compose.prod.yml ps db

# Проверить логи PostgreSQL
docker compose -f docker-compose.prod.yml logs db

# Проверить подключение из web контейнера
docker compose -f docker-compose.prod.yml exec web python manage.py dbshell
```

### Проблемы с Celery

```bash
# Проверить статус Celery worker
docker compose -f docker-compose.prod.yml logs celery_worker

# Проверить подключение к Redis
docker compose -f docker-compose.prod.yml exec redis redis-cli ping

# Инспектировать Celery
docker compose -f docker-compose.prod.yml exec celery_worker celery -A config inspect active
```

### Проблемы с Nginx

```bash
# Проверить логи Nginx
docker compose -f docker-compose.prod.yml logs nginx

# Проверить конфигурацию Nginx
docker compose -f docker-compose.prod.yml exec nginx nginx -t

# Перезагрузить Nginx
docker compose -f docker-compose.prod.yml restart nginx
```

### Высокое использование ресурсов

```bash
# Найти контейнер с высоким использованием CPU/памяти
docker stats --no-stream | sort -k 3 -h

# Проверить процессы внутри контейнера
docker compose -f docker-compose.prod.yml top web

# Ограничить ресурсы контейнера (добавить в docker-compose.yml)
# deploy:
#   resources:
#     limits:
#       cpus: '0.5'
#       memory: 512M
```

### Очистка логов

```bash
# Очистить логи конкретного контейнера
truncate -s 0 $(docker inspect --format='{{.LogPath}}' insurance_broker_web)

# Или через Docker
docker compose -f docker-compose.prod.yml down
docker compose -f docker-compose.prod.yml up -d
```

### Полная очистка Docker (ОСТОРОЖНО!)

```bash
# Удалить неиспользуемые контейнеры, сети, образы
docker system prune

# Удалить все (включая volumes)
docker system prune -a --volumes

# Удалить только остановленные контейнеры
docker container prune

# Удалить неиспользуемые volumes
docker volume prune
```

## Мониторинг в production

### Базовый мониторинг

```bash
# Создать скрипт для проверки здоровья системы
cat > /usr/local/bin/check-docker-health.sh << 'EOF'
#!/bin/bash
cd /path/to/project
docker compose -f docker-compose.prod.yml ps | grep -v "Up (healthy)" | grep "Up" && echo "WARNING: Some services are not healthy"
EOF

chmod +x /usr/local/bin/check-docker-health.sh

# Добавить в cron для регулярной проверки
# */5 * * * * /usr/local/bin/check-docker-health.sh
```

### Алерты при падении контейнера

```bash
# Проверить, что все контейнеры запущены
docker compose -f docker-compose.prod.yml ps | grep -v "Up" && echo "ALERT: Some containers are down"
```

### Мониторинг дискового пространства

```bash
# Проверить использование диска
df -h

# Проверить размер логов Docker
du -sh /var/lib/docker/containers/*/*-json.log

# Проверить размер volumes
docker system df -v
```

## Расширенный мониторинг (опционально)

Для production рекомендуется настроить:

1. **Prometheus + Grafana** - для сбора и визуализации метрик
2. **Sentry** - для отслеживания ошибок приложения
3. **ELK Stack** (Elasticsearch, Logstash, Kibana) - для централизованного логирования
4. **Uptime monitoring** - UptimeRobot, Pingdom для проверки доступности

## Полезные команды

```bash
# Перезапустить все сервисы
docker compose -f docker-compose.prod.yml restart

# Перезапустить конкретный сервис
docker compose -f docker-compose.prod.yml restart web

# Остановить все сервисы
docker compose -f docker-compose.prod.yml stop

# Запустить все сервисы
docker compose -f docker-compose.prod.yml start

# Пересобрать и перезапустить
docker compose -f docker-compose.prod.yml up -d --build

# Выполнить команду в контейнере
docker compose -f docker-compose.prod.yml exec web python manage.py shell

# Войти в контейнер
docker compose -f docker-compose.prod.yml exec web bash
```

## Резюме

- Используйте `./scripts/view-logs.sh` для удобного просмотра логов
- Логи автоматически ротируются (max 30MB на контейнер)
- Health checks обеспечивают автоматический мониторинг
- Используйте `docker stats` для мониторинга ресурсов
- Регулярно проверяйте статус контейнеров с помощью `docker compose ps`
- Настройте алерты для production окружения
