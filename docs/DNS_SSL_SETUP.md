# Руководство по настройке DNS и SSL

## Обзор

Это руководство описывает процесс настройки DNS записей и получения SSL сертификата для домена `polis.insflow.ru` на сервере Timeweb Cloud с IP адресом `109.68.215.223`.

## Предварительные требования

- Доступ к панели управления DNS вашего регистратора доменов
- SSH доступ к серверу Timeweb Cloud (109.68.215.223)
- Docker и Docker Compose установлены на сервере
- Приложение развернуто и работает

## Часть 1: Настройка DNS

### Шаг 1: Создание A записи

1. Войдите в панель управления вашего регистратора доменов (например, Reg.ru, Timeweb, или другой)

2. Найдите раздел управления DNS записями для домена `insflow.ru`

3. Создайте новую A запись со следующими параметрами:

   ```
   Тип записи: A
   Имя (Host): polis
   Значение (Points to): 109.68.215.223
   TTL: 300 (5 минут)
   ```

   **Примечание**: TTL 300 секунд (5 минут) позволяет быстро переключаться между серверами в случае необходимости отката.

4. Сохраните изменения

### Шаг 2: Проверка распространения DNS

DNS изменения могут занять от нескольких минут до 24-48 часов для полного распространения. Используйте следующие команды для проверки:

#### Проверка с помощью nslookup

```bash
nslookup polis.insflow.ru
```

**Ожидаемый результат:**
```
Server:		8.8.8.8
Address:	8.8.8.8#53

Non-authoritative answer:
Name:	polis.insflow.ru
Address: 109.68.215.223
```

#### Проверка с помощью dig

```bash
dig polis.insflow.ru +short
```

**Ожидаемый результат:**
```
109.68.215.223
```

#### Проверка с помощью dig (подробная информация)

```bash
dig polis.insflow.ru
```

Это покажет полную информацию о DNS запросе, включая TTL и серверы имен.

#### Проверка из разных локаций

Используйте онлайн сервисы для проверки распространения DNS из разных точек мира:
- https://www.whatsmydns.net/
- https://dnschecker.org/

Введите `polis.insflow.ru` и тип записи `A`, чтобы увидеть результаты из разных стран.

### Шаг 3: Проверка HTTP доступа

После того как DNS распространился, проверьте HTTP доступ к серверу:

```bash
curl -I http://polis.insflow.ru
```

**Ожидаемый результат (если используется HTTP-only конфигурация):**
```
HTTP/1.1 200 OK
Server: nginx
...
```

**Или (если уже настроен редирект на HTTPS):**
```
HTTP/1.1 301 Moved Permanently
Location: https://polis.insflow.ru/
...
```

## Часть 2: Временная HTTP-only конфигурация

Перед получением SSL сертификата необходимо убедиться, что сервер доступен по HTTP для прохождения ACME challenge от Let's Encrypt.

### Когда использовать HTTP-only конфигурацию

- При первоначальной настройке сервера
- Когда DNS еще не распространился
- Для отладки проблем с доступностью

### Применение HTTP-only конфигурации

1. На сервере перейдите в директорию проекта:

   ```bash
   cd ~/insurance_broker
   ```

2. Создайте резервную копию текущей конфигурации:

   ```bash
   cp nginx/default.conf nginx/default.conf.backup
   ```

3. Скопируйте HTTP-only конфигурацию:

   ```bash
   cp nginx/default.conf.http-only nginx/default.conf
   ```

4. Перезапустите nginx контейнер:

   ```bash
   docker-compose -f docker-compose.prod.yml restart nginx
   ```

5. Проверьте что сервер доступен:

   ```bash
   curl http://polis.insflow.ru
   ```

## Часть 3: Получение SSL сертификата

### Автоматический метод (рекомендуется)

Используйте предоставленный скрипт для автоматического получения SSL сертификата:

1. Убедитесь что DNS настроен и распространился (см. Часть 1, Шаг 2)

2. Убедитесь что используется HTTP-only конфигурация nginx (см. Часть 2)

3. Запустите скрипт получения SSL:

   ```bash
   cd ~/insurance_broker
   bash scripts/obtain-ssl.sh
   ```

4. Скрипт выполнит следующие действия:
   - Проверит доступность домена
   - Запустит certbot для получения сертификата
   - Проверит успешность получения сертификата
   - Предложит переключиться на HTTPS конфигурацию

5. Следуйте инструкциям скрипта

### Ручной метод

Если автоматический скрипт не работает, выполните следующие шаги вручную:

#### Шаг 1: Убедитесь что контейнеры запущены

```bash
cd ~/insurance_broker
docker-compose -f docker-compose.prod.yml ps
```

Все контейнеры должны быть в состоянии "Up".

#### Шаг 2: Запустите certbot

```bash
docker-compose -f docker-compose.prod.yml run --rm certbot certonly \
  --webroot \
  --webroot-path=/var/www/certbot \
  --email your-email@example.com \
  --agree-tos \
  --no-eff-email \
  -d polis.insflow.ru
```

**Замените** `your-email@example.com` на ваш реальный email адрес.

#### Шаг 3: Проверьте получение сертификата

```bash
docker-compose -f docker-compose.prod.yml exec nginx ls -la /etc/letsencrypt/live/polis.insflow.ru/
```

Вы должны увидеть файлы:
- `cert.pem` - сертификат
- `chain.pem` - цепочка сертификатов
- `fullchain.pem` - полная цепочка
- `privkey.pem` - приватный ключ

## Часть 4: Переключение на HTTPS конфигурацию

После успешного получения SSL сертификата переключитесь на полную HTTPS конфигурацию:

### Шаг 1: Восстановите HTTPS конфигурацию

```bash
cd ~/insurance_broker
cp nginx/default.conf.backup nginx/default.conf
```

Или, если резервная копия не была создана, получите конфигурацию из репозитория:

```bash
git pull origin main
```

### Шаг 2: Перезапустите nginx

```bash
docker-compose -f docker-compose.prod.yml restart nginx
```

### Шаг 3: Проверьте HTTPS доступ

```bash
curl -I https://polis.insflow.ru
```

**Ожидаемый результат:**
```
HTTP/2 200
server: nginx
...
strict-transport-security: max-age=31536000; includeSubDomains; preload
...
```

### Шаг 4: Проверьте редирект с HTTP на HTTPS

```bash
curl -I http://polis.insflow.ru
```

**Ожидаемый результат:**
```
HTTP/1.1 301 Moved Permanently
Location: https://polis.insflow.ru/
...
```

### Шаг 5: Проверьте SSL сертификат в браузере

1. Откройте браузер
2. Перейдите на https://polis.insflow.ru
3. Нажмите на иконку замка в адресной строке
4. Проверьте информацию о сертификате:
   - Издатель: Let's Encrypt
   - Срок действия: ~90 дней с даты выдачи
   - Домен: polis.insflow.ru

## Часть 5: Автоматическое обновление SSL сертификата

Let's Encrypt сертификаты действительны 90 дней. Certbot контейнер настроен на автоматическое обновление.

### Проверка автоматического обновления

Certbot контейнер запускается каждые 12 часов и проверяет необходимость обновления сертификата (обновление происходит за 30 дней до истечения).

### Ручное обновление (если необходимо)

```bash
cd ~/insurance_broker
docker-compose -f docker-compose.prod.yml run --rm certbot renew
docker-compose -f docker-compose.prod.yml restart nginx
```

### Проверка срока действия сертификата

```bash
echo | openssl s_client -servername polis.insflow.ru -connect polis.insflow.ru:443 2>/dev/null | openssl x509 -noout -dates
```

## Устранение неполадок

### Проблема: DNS не распространяется

**Симптомы:**
- `nslookup` или `dig` возвращают старый IP или ошибку
- Прошло более 24 часов с момента изменения DNS

**Решение:**
1. Проверьте правильность настройки A записи в панели управления DNS
2. Убедитесь что изменения сохранены
3. Попробуйте очистить локальный DNS кеш:
   ```bash
   # macOS
   sudo dscacheutil -flushcache; sudo killall -HUP mDNSResponder

   # Linux
   sudo systemd-resolve --flush-caches

   # Windows
   ipconfig /flushdns
   ```
4. Используйте публичные DNS серверы для проверки (8.8.8.8, 1.1.1.1)

### Проблема: Certbot не может получить сертификат

**Симптомы:**
- Ошибка "Failed authorization procedure"
- Ошибка "Connection refused"

**Решение:**
1. Убедитесь что DNS настроен и распространился
2. Проверьте что nginx контейнер запущен:
   ```bash
   docker-compose -f docker-compose.prod.yml ps nginx
   ```
3. Проверьте что порт 80 открыт:
   ```bash
   sudo ufw status
   curl http://polis.insflow.ru/.well-known/acme-challenge/test
   ```
4. Проверьте логи nginx:
   ```bash
   docker-compose -f docker-compose.prod.yml logs nginx
   ```
5. Убедитесь что используется HTTP-only конфигурация

### Проблема: HTTPS не работает после получения сертификата

**Симптомы:**
- Браузер показывает ошибку "Connection refused" или "SSL error"
- `curl https://polis.insflow.ru` возвращает ошибку

**Решение:**
1. Проверьте что порт 443 открыт:
   ```bash
   sudo ufw status
   ```
2. Проверьте что nginx использует правильную конфигурацию:
   ```bash
   docker-compose -f docker-compose.prod.yml exec nginx nginx -t
   ```
3. Проверьте логи nginx:
   ```bash
   docker-compose -f docker-compose.prod.yml logs nginx
   ```
4. Убедитесь что файлы сертификата существуют:
   ```bash
   docker-compose -f docker-compose.prod.yml exec nginx ls -la /etc/letsencrypt/live/polis.insflow.ru/
   ```
5. Перезапустите nginx:
   ```bash
   docker-compose -f docker-compose.prod.yml restart nginx
   ```

### Проблема: Смешанный контент (Mixed Content)

**Симптомы:**
- Браузер показывает предупреждения о небезопасном контенте
- Некоторые ресурсы не загружаются

**Решение:**
1. Убедитесь что все ссылки в приложении используют относительные пути или HTTPS
2. Проверьте настройки Django:
   ```python
   SECURE_SSL_REDIRECT = True
   SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
   ```
3. Проверьте заголовки в nginx конфигурации

## Проверочный чеклист

После завершения настройки DNS и SSL, убедитесь что:

- [ ] DNS запись создана и распространилась
- [ ] `nslookup polis.insflow.ru` возвращает 109.68.215.223
- [ ] `dig polis.insflow.ru +short` возвращает 109.68.215.223
- [ ] HTTP доступ работает: `curl http://polis.insflow.ru`
- [ ] SSL сертификат получен успешно
- [ ] Файлы сертификата существуют в `/etc/letsencrypt/live/polis.insflow.ru/`
- [ ] HTTPS доступ работает: `curl https://polis.insflow.ru`
- [ ] HTTP редиректит на HTTPS
- [ ] Браузер показывает зеленый замок для https://polis.insflow.ru
- [ ] Сертификат выдан Let's Encrypt
- [ ] Срок действия сертификата ~90 дней
- [ ] HSTS заголовок присутствует
- [ ] Автоматическое обновление certbot настроено

## Дополнительные ресурсы

- [Let's Encrypt документация](https://letsencrypt.org/docs/)
- [Certbot документация](https://certbot.eff.org/docs/)
- [Nginx SSL конфигурация](https://nginx.org/en/docs/http/configuring_https_servers.html)
- [SSL Labs тест](https://www.ssllabs.com/ssltest/) - проверка качества SSL конфигурации

## Следующие шаги

После успешной настройки DNS и SSL:

1. Проведите полное функциональное тестирование приложения
2. Настройте мониторинг доступности и срока действия сертификата
3. Обновите документацию с новым доменом
4. Уведомите пользователей о новом адресе (если применимо)
5. Настройте редирект со старого домена (если применимо)
