# DNS Quick Reference для onbr.site

Краткая справка по настройке и проверке DNS для домена onbr.site.

## Быстрая настройка

### 1. Получите IP адрес Droplet

```bash
# На Droplet
curl ifconfig.me

# Или через Digital Ocean CLI
doctl compute droplet list --format Name,PublicIPv4
```

### 2. Добавьте DNS записи

#### Через Digital Ocean (рекомендуется)

```bash
# Создайте домен
doctl compute domain create onbr.site

# Добавьте A записи
doctl compute domain records create onbr.site \
  --record-type A --record-name @ --record-data YOUR_DROPLET_IP

doctl compute domain records create onbr.site \
  --record-type A --record-name www --record-data YOUR_DROPLET_IP

# Проверьте записи
doctl compute domain records list onbr.site
```

#### Через веб-интерфейс

1. Digital Ocean → Networking → Domains → Add Domain
2. Введите `onbr.site`
3. Добавьте A записи:
   - Hostname: `@` → Droplet: ваш Droplet
   - Hostname: `www` → Droplet: ваш Droplet

### 3. Обновите NS записи у регистратора

Измените nameservers на:
```
ns1.digitalocean.com
ns2.digitalocean.com
ns3.digitalocean.com
```

### 4. Проверьте распространение

```bash
# Используйте наш скрипт
./scripts/check-dns.sh onbr.site YOUR_DROPLET_IP

# Или вручную
dig onbr.site +short
dig www.onbr.site +short
```

---

## Необходимые DNS записи

| Type | Name | Value | TTL | Описание |
|------|------|-------|-----|----------|
| A | @ | YOUR_DROPLET_IP | 3600 | Корневой домен (onbr.site) |
| A | www | YOUR_DROPLET_IP | 3600 | WWW поддомен (www.onbr.site) |

---

## Команды для проверки

### Базовая проверка

```bash
# Проверка корневого домена
dig onbr.site +short

# Проверка www поддомена
dig www.onbr.site +short

# Детальная информация
dig onbr.site

# Проверка NS записей
dig NS onbr.site +short
```

### Проверка с разными DNS серверами

```bash
# Google DNS
dig @8.8.8.8 onbr.site +short

# Cloudflare DNS
dig @1.1.1.1 onbr.site +short

# OpenDNS
dig @208.67.222.222 onbr.site +short
```

### Проверка HTTP/HTTPS

```bash
# HTTP
curl -I http://onbr.site

# HTTPS (после настройки SSL)
curl -I https://onbr.site
```

### Автоматизированная проверка

```bash
# Запустите скрипт проверки
./scripts/check-dns.sh onbr.site YOUR_DROPLET_IP

# Непрерывная проверка (каждые 30 секунд)
watch -n 30 "dig onbr.site +short"
```

---

## Онлайн инструменты

- **DNS Checker**: https://dnschecker.org/#A/onbr.site
- **What's My DNS**: https://www.whatsmydns.net/#A/onbr.site
- **Google DNS**: https://dns.google/query?name=onbr.site&type=A
- **DNS Propagation**: https://www.whatsmydns.net/dns-propagation-checker

---

## Время распространения

| Тип изменения | Обычное время | Максимум |
|---------------|---------------|----------|
| A записи | 15-60 минут | 4 часа |
| NS записи | 4-24 часа | 48 часов |
| TTL изменения | Зависит от старого TTL | - |

---

## Troubleshooting

### DNS не распространяется

```bash
# 1. Проверьте правильность записей
doctl compute domain records list onbr.site

# 2. Очистите локальный DNS кэш
# macOS:
sudo dscacheutil -flushcache && sudo killall -HUP mDNSResponder

# Linux:
sudo systemd-resolve --flush-caches

# 3. Проверьте с другим DNS сервером
dig @8.8.8.8 onbr.site +short
```

### Показывает старый IP

```bash
# Проверьте TTL - возможно кэш еще не истек
dig onbr.site | grep "^onbr.site"

# Подождите время, равное TTL
```

### NXDOMAIN (домен не найден)

```bash
# Проверьте NS записи
dig NS onbr.site

# Убедитесь, что домен добавлен
doctl compute domain list
```

---

## Проверочный список

- [ ] IP адрес Droplet получен
- [ ] A запись для @ создана
- [ ] A запись для www создана
- [ ] NS записи обновлены у регистратора (если используется DO DNS)
- [ ] `dig onbr.site +short` возвращает правильный IP
- [ ] `dig www.onbr.site +short` возвращает правильный IP
- [ ] DNS проверен через онлайн инструменты
- [ ] HTTP доступен (curl -I http://onbr.site)

---

## Следующие шаги

После успешной настройки DNS:

1. **Получите SSL сертификат**
   ```bash
   ./scripts/init-letsencrypt.sh
   ```

2. **Проверьте HTTPS**
   ```bash
   curl -I https://onbr.site
   ```

3. **Настройте автоматическое обновление SSL**
   ```bash
   # Добавьте в crontab
   0 0 * * * docker compose -f /opt/insurance_broker/docker-compose.prod.yml run --rm certbot renew
   ```

---

## Полезные ссылки

- [Полное руководство по DNS](DNS_SETUP.md)
- [Руководство по развертыванию](DEPLOYMENT.md)
- [Digital Ocean DNS Docs](https://docs.digitalocean.com/products/networking/dns/)

---

**Последнее обновление:** 2024
