# Исправление ошибки деплоя

## Что произошло

При первом деплое nginx не смог запуститься, потому что в конфигурации указаны SSL сертификаты, которых еще нет.

## Что было сделано

1. **Создан файл `nginx/default.conf.initial`** - конфигурация nginx без SSL для первого запуска

2. **Создан скрипт `scripts/setup-ssl.sh`** - автоматическая настройка SSL:
   - Проверяет DNS
   - Переключает nginx на конфигурацию без SSL
   - Получает SSL сертификат через Let's Encrypt
   - Включает SSL конфигурацию
   - Перезапускает nginx

3. **Обновлен GitHub Actions workflow** - теперь проверяет наличие SSL сертификатов и использует правильную конфигурацию

4. **Создана документация**:
   - `docs/FIRST_DEPLOYMENT.md` - подробное руководство по первому деплою
   - `QUICK_FIX.md` - быстрое решение проблемы

## Что нужно сделать сейчас

### Вариант 1: Автоматический (рекомендуется)

Подключитесь к серверу и запустите скрипт:

```bash
ssh root@109.68.215.223
cd ~/insurance_broker
./scripts/setup-ssl.sh
```

### Вариант 2: Ручной

```bash
ssh root@109.68.215.223
cd ~/insurance_broker

# 1. Переключитесь на конфигурацию без SSL
cp nginx/default.conf nginx/default.conf.ssl
cp nginx/default.conf.initial nginx/default.conf

# 2. Перезапустите nginx
docker-compose -f docker-compose.prod.yml restart nginx

# 3. Получите сертификат
docker-compose -f docker-compose.prod.yml run --rm certbot certonly \
    --webroot \
    --webroot-path=/var/www/certbot \
    --email admin@insflow.ru \
    --agree-tos \
    --no-eff-email \
    -d polis.insflow.ru

# 4. Включите SSL
cp nginx/default.conf.ssl nginx/default.conf
docker-compose -f docker-compose.prod.yml restart nginx
```

## Проверка

После выполнения проверьте:

```bash
# Все контейнеры должны быть запущены
docker-compose -f docker-compose.prod.yml ps

# HTTP должен редиректить на HTTPS
curl -I http://polis.insflow.ru

# HTTPS должен работать
curl -I https://polis.insflow.ru

# Откройте в браузере
# https://polis.insflow.ru
```

## Следующие деплои

После первого успешного деплоя все последующие деплои будут работать автоматически через GitHub Actions, потому что SSL сертификаты уже будут на месте.

## Если что-то пошло не так

1. **Проверьте DNS**:
   ```bash
   nslookup polis.insflow.ru
   # Должен вернуть 109.68.215.223
   ```

2. **Проверьте логи nginx**:
   ```bash
   docker-compose -f docker-compose.prod.yml logs nginx
   ```

3. **Проверьте логи certbot**:
   ```bash
   docker-compose -f docker-compose.prod.yml logs certbot
   ```

4. **Проверьте что порты открыты**:
   ```bash
   sudo ufw status
   # Должны быть открыты 80 и 443
   ```

## Контакты для помощи

Если нужна помощь, предоставьте:
- Вывод команды: `docker-compose -f docker-compose.prod.yml ps`
- Логи nginx: `docker-compose -f docker-compose.prod.yml logs nginx`
- Результат проверки DNS: `nslookup polis.insflow.ru`
