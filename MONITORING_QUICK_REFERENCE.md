# Быстрый справочник по мониторингу

Краткая шпаргалка по командам мониторинга и логирования Docker контейнеров.

## 📊 Просмотр логов

```bash
# Удобный скрипт для просмотра логов
./scripts/view-logs.sh                    # Все сервисы
./scripts/view-logs.sh web -f             # Следить за web
./scripts/view-logs.sh celery_worker -n 50  # Последние 50 строк

# Docker Compose команды
docker compose -f docker-compose.prod.yml logs -f web
docker compose -f docker-compose.prod.yml logs --tail=100 all
docker compose -f docker-compose.prod.yml logs -f -t  # С временными метками
```

## 🔍 Статус контейнеров

```bash
# Проверить статус всех сервисов
docker compose -f docker-compose.prod.yml ps

# Список запущенных контейнеров
docker ps

# Все контейнеры (включая остановленные)
docker ps -a
```

## 💚 Health Checks

```bash
# Проверить health status
docker inspect --format='{{.State.Health.Status}}' insurance_broker_web

# Детальная информация
docker inspect insurance_broker_web | jq '.[0].State.Health'
```

## 📈 Использование ресурсов

```bash
# Мониторинг в реальном времени
docker stats

# Один снимок
docker stats --no-stream

# Использование диска
docker system df
docker system df -v  # Детально
```

## 🔧 Управление сервисами

```bash
# Перезапустить сервис
docker compose -f docker-compose.prod.yml restart web

# Перезапустить все
docker compose -f docker-compose.prod.yml restart

# Остановить/запустить
docker compose -f docker-compose.prod.yml stop
docker compose -f docker-compose.prod.yml start
```

## 🐛 Troubleshooting

```bash
# Логи ошибок
docker compose -f docker-compose.prod.yml logs web | grep -i error

# Проверить подключение к БД
docker compose -f docker-compose.prod.yml exec web python manage.py dbshell

# Проверить Redis
docker compose -f docker-compose.prod.yml exec redis redis-cli ping

# Проверить Nginx конфигурацию
docker compose -f docker-compose.prod.yml exec nginx nginx -t

# Войти в контейнер
docker compose -f docker-compose.prod.yml exec web bash
```

## 🧹 Очистка

```bash
# Удалить неиспользуемые ресурсы
docker system prune

# Удалить остановленные контейнеры
docker container prune

# Удалить неиспользуемые volumes
docker volume prune
```

## 📝 Конфигурация логирования

Все сервисы настроены с автоматической ротацией логов:
- **Max size:** 10MB на файл
- **Max files:** 3 файла
- **Total:** ~30MB на контейнер

## 🔗 Полная документация

Смотрите [docs/MONITORING.md](docs/MONITORING.md) для подробной информации.
