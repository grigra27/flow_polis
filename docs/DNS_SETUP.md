# Руководство по настройке DNS для onbr.site

Это руководство описывает процесс настройки DNS записей для домена onbr.site, чтобы он указывал на ваш Digital Ocean Droplet.

## Содержание

1. [Предварительные требования](#предварительные-требования)
2. [Получение IP адреса Droplet](#получение-ip-адреса-droplet)
3. [Настройка DNS записей](#настройка-dns-записей)
4. [Проверка распространения DNS](#проверка-распространения-dns)
5. [Troubleshooting](#troubleshooting)

---

## Предварительные требования

- Зарегистрированный домен onbr.site
- Доступ к панели управления DNS вашего регистратора домена
- Запущенный Digital Ocean Droplet с известным IP адресом

---

## Получение IP адреса Droplet

### Метод 1: Через веб-интерфейс Digital Ocean

1. Войдите в панель управления Digital Ocean: https://cloud.digitalocean.com/
2. Перейдите в раздел **Droplets**
3. Найдите ваш Droplet (например, `insurance-broker-prod`)
4. Скопируйте **IPv4 адрес** (например, `123.45.67.89`)

### Метод 2: Через SSH на Droplet

```bash
# Подключитесь к Droplet
ssh root@YOUR_DROPLET_IP

# Получите публичный IP адрес
curl ifconfig.me
# или
curl icanhazip.com
# или
hostname -I | awk '{print $1}'
```

### Метод 3: Через Digital Ocean CLI

```bash
# Установите doctl (если еще не установлен)
# macOS:
brew install doctl

# Аутентификация
doctl auth init

# Получите список Droplets с IP адресами
doctl compute droplet list --format Name,PublicIPv4
```

**Запишите IP адрес** - он понадобится для следующих шагов.

---

## Настройка DNS записей

### Вариант A: Использование Digital Ocean DNS (рекомендуется)

Digital Ocean предоставляет бесплатный DNS хостинг для ваших доменов.

#### Через веб-интерфейс

1. Войдите в панель управления Digital Ocean
2. Перейдите в **Networking** → **Domains**
3. Нажмите **Add Domain**
4. Введите `onbr.site` и нажмите **Add Domain**
5. Добавьте A записи:

**Первая A запись (корневой домен):**
- **Type**: A
- **Hostname**: `@`
- **Will Direct To**: Выберите ваш Droplet из списка
- **TTL**: 3600 (или оставьте по умолчанию)
- Нажмите **Create Record**

**Вторая A запись (www поддомен):**
- **Type**: A
- **Hostname**: `www`
- **Will Direct To**: Выберите ваш Droplet из списка
- **TTL**: 3600 (или оставьте по умолчанию)
- Нажмите **Create Record**

#### Через CLI

```bash
# Создайте домен
doctl compute domain create onbr.site

# Добавьте A запись для корневого домена
doctl compute domain records create onbr.site \
  --record-type A \
  --record-name @ \
  --record-data YOUR_DROPLET_IP \
  --record-ttl 3600

# Добавьте A запись для www поддомена
doctl compute domain records create onbr.site \
  --record-type A \
  --record-name www \
  --record-data YOUR_DROPLET_IP \
  --record-ttl 3600

# Проверьте созданные записи
doctl compute domain records list onbr.site
```

#### Обновление NS записей у регистратора

После создания домена в Digital Ocean, вам нужно обновить NS (nameserver) записи у вашего регистратора домена:

1. Войдите в панель управления вашего регистратора домена (где вы купили onbr.site)
2. Найдите раздел управления DNS/Nameservers
3. Замените существующие nameservers на nameservers Digital Ocean:
   ```
   ns1.digitalocean.com
   ns2.digitalocean.com
   ns3.digitalocean.com
   ```
4. Сохраните изменения

**Важно:** Распространение NS записей может занять 24-48 часов.

---

### Вариант B: Использование DNS вашего регистратора

Если вы предпочитаете использовать DNS сервисы вашего регистратора домена:

#### Общие инструкции

1. Войдите в панель управления вашего регистратора домена
2. Найдите раздел управления DNS (может называться: DNS Management, DNS Settings, Zone Editor, и т.д.)
3. Добавьте следующие A записи:

| Type | Name/Host | Value/Points To | TTL |
|------|-----------|-----------------|-----|
| A | @ | YOUR_DROPLET_IP | 3600 |
| A | www | YOUR_DROPLET_IP | 3600 |

Где:
- `@` - означает корневой домен (onbr.site)
- `www` - поддомен (www.onbr.site)
- `YOUR_DROPLET_IP` - IP адрес вашего Droplet (например, 123.45.67.89)
- `TTL` - время жизни записи в секундах (3600 = 1 час)

#### Примеры для популярных регистраторов

**GoDaddy:**
1. My Products → DNS → Manage Zones
2. Выберите onbr.site
3. Add → A Record
4. Name: `@`, Value: `YOUR_DROPLET_IP`, TTL: 1 Hour
5. Add → A Record
6. Name: `www`, Value: `YOUR_DROPLET_IP`, TTL: 1 Hour

**Namecheap:**
1. Domain List → Manage → Advanced DNS
2. Add New Record → A Record
3. Host: `@`, Value: `YOUR_DROPLET_IP`, TTL: Automatic
4. Add New Record → A Record
5. Host: `www`, Value: `YOUR_DROPLET_IP`, TTL: Automatic

**Cloudflare:**
1. Select your site → DNS → Records
2. Add record → Type: A, Name: `@`, IPv4 address: `YOUR_DROPLET_IP`, Proxy status: DNS only
3. Add record → Type: A, Name: `www`, IPv4 address: `YOUR_DROPLET_IP`, Proxy status: DNS only

**Google Domains:**
1. My domains → Manage → DNS
2. Custom records → Manage custom records
3. Create new record → Type: A, Host name: `@`, Data: `YOUR_DROPLET_IP`, TTL: 1h
4. Create new record → Type: A, Host name: `www`, Data: `YOUR_DROPLET_IP`, TTL: 1h

---

## Проверка распространения DNS

DNS изменения не происходят мгновенно. Распространение может занять:
- **Минимум**: 5-15 минут
- **Обычно**: 1-4 часа
- **Максимум**: 24-48 часов (для NS записей)

### Локальная проверка

#### Использование dig (рекомендуется)

```bash
# Проверка корневого домена
dig onbr.site +short

# Проверка www поддомена
dig www.onbr.site +short

# Детальная информация
dig onbr.site

# Проверка с конкретным DNS сервером
dig @8.8.8.8 onbr.site +short
dig @1.1.1.1 onbr.site +short
```

**Ожидаемый результат:**
```
YOUR_DROPLET_IP
```

#### Использование nslookup

```bash
# Проверка корневого домена
nslookup onbr.site

# Проверка www поддомена
nslookup www.onbr.site

# Проверка с конкретным DNS сервером
nslookup onbr.site 8.8.8.8
```

**Ожидаемый результат:**
```
Server:		8.8.8.8
Address:	8.8.8.8#53

Non-authoritative answer:
Name:	onbr.site
Address: YOUR_DROPLET_IP
```

#### Использование host

```bash
# Проверка корневого домена
host onbr.site

# Проверка www поддомена
host www.onbr.site
```

#### Использование curl

```bash
# Проверка HTTP доступности
curl -I http://onbr.site

# Проверка HTTPS доступности (после настройки SSL)
curl -I https://onbr.site
```

### Онлайн инструменты для проверки

Эти инструменты проверяют DNS записи с разных точек мира:

1. **DNS Checker** - https://dnschecker.org/
   - Введите `onbr.site`
   - Выберите тип записи: A
   - Проверьте распространение по всему миру

2. **What's My DNS** - https://www.whatsmydns.net/
   - Введите `onbr.site`
   - Выберите тип: A
   - Посмотрите результаты с разных DNS серверов

3. **DNS Propagation Checker** - https://www.whatsmydns.net/dns-propagation-checker
   - Комплексная проверка распространения

4. **Google DNS** - https://dns.google/
   - Введите `onbr.site`
   - Проверьте A записи

### Автоматизированная проверка

Используйте предоставленный скрипт для автоматической проверки:

```bash
# Сделайте скрипт исполняемым
chmod +x scripts/check-dns.sh

# Запустите проверку
./scripts/check-dns.sh onbr.site YOUR_DROPLET_IP
```

Скрипт будет:
- Проверять DNS записи каждые 30 секунд
- Показывать прогресс распространения
- Уведомлять, когда DNS полностью распространился

---

## Дополнительные DNS записи (опционально)

### CNAME запись для дополнительных поддоменов

Если вам нужны дополнительные поддомены (например, `api.onbr.site`, `admin.onbr.site`):

```bash
# Через Digital Ocean CLI
doctl compute domain records create onbr.site \
  --record-type CNAME \
  --record-name api \
  --record-data onbr.site. \
  --record-ttl 3600

# Или добавьте A запись напрямую
doctl compute domain records create onbr.site \
  --record-type A \
  --record-name api \
  --record-data YOUR_DROPLET_IP \
  --record-ttl 3600
```

### MX записи для email (если нужно)

Если вы хотите получать email на домене onbr.site:

```bash
# Пример для Google Workspace
doctl compute domain records create onbr.site \
  --record-type MX \
  --record-name @ \
  --record-data "1 aspmx.l.google.com." \
  --record-priority 1 \
  --record-ttl 3600
```

### TXT записи для верификации

Для верификации домена (Google, SPF, DKIM):

```bash
# Пример SPF записи
doctl compute domain records create onbr.site \
  --record-type TXT \
  --record-name @ \
  --record-data "v=spf1 include:_spf.google.com ~all" \
  --record-ttl 3600
```

---

## Troubleshooting

### Проблема: DNS не распространяется

**Решение:**

1. Проверьте правильность IP адреса:
```bash
# На Droplet
curl ifconfig.me
```

2. Проверьте, что записи созданы правильно:
```bash
# Через Digital Ocean CLI
doctl compute domain records list onbr.site

# Или через веб-интерфейс
# Networking → Domains → onbr.site
```

3. Очистите локальный DNS кэш:
```bash
# macOS
sudo dscacheutil -flushcache
sudo killall -HUP mDNSResponder

# Linux
sudo systemd-resolve --flush-caches

# Windows
ipconfig /flushdns
```

4. Подождите дольше - DNS распространение может занять до 48 часов

### Проблема: dig показывает старый IP адрес

**Решение:**

1. Проверьте TTL записи - возможно, кэш еще не истек
2. Проверьте с другим DNS сервером:
```bash
dig @8.8.8.8 onbr.site +short  # Google DNS
dig @1.1.1.1 onbr.site +short  # Cloudflare DNS
dig @208.67.222.222 onbr.site +short  # OpenDNS
```

3. Если разные DNS серверы показывают разные результаты - DNS еще распространяется

### Проблема: NXDOMAIN (домен не найден)

**Решение:**

1. Проверьте, что домен добавлен в DNS:
```bash
doctl compute domain list
```

2. Проверьте NS записи:
```bash
dig NS onbr.site
```

3. Убедитесь, что NS записи у регистратора указывают на правильные nameservers

### Проблема: Сайт не открывается, хотя DNS работает

**Решение:**

1. Проверьте, что Droplet запущен:
```bash
doctl compute droplet list
```

2. Проверьте, что firewall разрешает порты 80 и 443:
```bash
ssh root@YOUR_DROPLET_IP
ufw status
```

3. Проверьте, что Nginx запущен:
```bash
docker compose -f docker-compose.prod.yml ps nginx
```

4. Проверьте логи Nginx:
```bash
docker compose -f docker-compose.prod.yml logs nginx
```

### Проблема: www.onbr.site не работает

**Решение:**

1. Проверьте, что A запись для www создана:
```bash
dig www.onbr.site +short
```

2. Проверьте, что Nginx настроен для обоих доменов:
```bash
docker compose -f docker-compose.prod.yml exec nginx cat /etc/nginx/conf.d/default.conf | grep server_name
```

Должно быть:
```
server_name onbr.site www.onbr.site;
```

---

## Проверочный список

После настройки DNS убедитесь, что:

- [ ] IP адрес Droplet получен и записан
- [ ] A запись для `@` (onbr.site) создана
- [ ] A запись для `www` (www.onbr.site) создана
- [ ] `dig onbr.site +short` возвращает правильный IP
- [ ] `dig www.onbr.site +short` возвращает правильный IP
- [ ] DNS распространился (проверено через dnschecker.org)
- [ ] `curl -I http://onbr.site` возвращает ответ
- [ ] Firewall на Droplet разрешает порты 80 и 443
- [ ] Nginx запущен и настроен для обоих доменов

---

## Следующие шаги

После успешной настройки DNS:

1. **Получите SSL сертификат** - см. `scripts/init-letsencrypt.sh`
2. **Настройте HTTPS** - обновите Nginx конфигурацию
3. **Протестируйте приложение** - откройте https://onbr.site в браузере
4. **Настройте мониторинг** - используйте uptime monitoring сервисы

---

## Полезные ссылки

- [Digital Ocean DNS Documentation](https://docs.digitalocean.com/products/networking/dns/)
- [DNS Propagation Explained](https://www.cloudflare.com/learning/dns/dns-propagation/)
- [Understanding DNS Records](https://www.cloudflare.com/learning/dns/dns-records/)
- [TTL Explained](https://www.cloudflare.com/learning/cdn/glossary/time-to-live-ttl/)

---

**Последнее обновление:** 2024
**Версия документа:** 1.0
