# SSH SOCKS5-туннель Москва → Амстердам для Telegram

2026-09-24: `polis` (продакшен, РФ) не может достучаться до
`api.telegram.org` напрямую — блокировка на уровне DPI/SNI, `curl` уходит
в таймаут. VK не подвержен блокировке и остаётся 100%-резервным каналом
(см. `docs/NOTIFICATIONS_PIPELINE.md`), но было решено дополнительно
провести Telegram-трафик через сервер в Амстердаме (`ams`), где связь
чистая, через SSH SOCKS5-туннель.

Код (`scripts/telegram-notify.sh`, `apps/core/notifications.py`) уже умеет
работать через прокси, если она поднята — это чисто конфигурация
(`TELEGRAM_SOCKS5_PROXY=host:port`), поведение без неё не меняется.
Ручной части — двух шагов ниже — оказалось не хватить сделать автоматически:
попытка создать SSH-пользователя и ключи на удалённых серверах была
заблокирована защитным классификатором Claude Code как «unauthorized
persistence» (создание новых SSH-ключей/доступов — типичный признак
бэкдора, поэтому агенту это делать не дают, даже когда это легитимно).
Поэтому — выполнить вручную, команды ниже.

Приватный ключ уже сгенерирован на `polis`:
`/root/.ssh/tg_relay_key` (публичный ключ — `tg_relay_key.pub`).

## Шаг 1 — на ams: ограниченный пользователь только для форвардинга

Подключиться: `ssh ams`, дальше от root:

```bash
useradd -m -s /usr/sbin/nologin \
    -c 'restricted account: SSH SOCKS5 relay for polis -> Telegram, nothing else' \
    tgrelay

mkdir -p /home/tgrelay/.ssh
chmod 700 /home/tgrelay/.ssh

# PUBKEY — вывод "cat /root/.ssh/tg_relay_key.pub" на polis, см. ниже.
cat > /home/tgrelay/.ssh/authorized_keys << 'EOF'
command="/bin/true",no-agent-forwarding,no-X11-forwarding,no-pty,no-user-rc,permitopen="api.telegram.org:443" ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIAuxHDobhYH64d2owLy/toaJZkO2ic3LXgYLXcsfcNJp polis-tg-relay-tunnel
EOF
chmod 600 /home/tgrelay/.ssh/authorized_keys
chown -R tgrelay:tgrelay /home/tgrelay/.ssh
```

Что дают опции в `authorized_keys` (важно не терять при копипасте):
- `command="/bin/true"` — если кто-то попробует использовать этот ключ для
  обычного шелла/команды, вместо неё выполнится безобидная заглушка.
  Туннель (`ssh -N`) команду вообще не запрашивает, так что в норме это
  никогда не сработает — это защита на случай подмены клиента.
- `no-pty,no-agent-forwarding,no-X11-forwarding,no-user-rc` — никакого
  интерактивного шелла и сопутствующих возможностей.
- `permitopen="api.telegram.org:443"` — ключевое ограничение: через этот
  туннель можно открыть соединение ТОЛЬКО до `api.telegram.org:443`,
  никуда больше в сети ams (ни к другим ботам на этой машине, ни в
  интернет вообще). Даже если приватный ключ утечёт с polis, максимум,
  что с ним можно сделать — постучаться в Bot API.

Порт 22 у ams уже открыт в `ufw`, ничего в файрволе менять не нужно.
Новых пакетов ставить не нужно — используется уже работающий `sshd`.

## Шаг 2 — на polis: постоянный туннель через systemd

```bash
# Разово — прописать ключ ams в отдельный known_hosts (не в общий,
# чтобы не путать с обычными административными SSH-сессиями):
ssh-keyscan -t ed25519 72.56.67.83 > /root/.ssh/tg_relay_known_hosts

cat > /etc/systemd/system/tg-relay-tunnel.service << 'EOF'
[Unit]
Description=SSH SOCKS5 tunnel to Amsterdam for Telegram Bot API access
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=root
ExecStart=/usr/bin/ssh -N -D 127.0.0.1:1080 \
    -o ExitOnForwardFailure=yes \
    -o ServerAliveInterval=30 \
    -o ServerAliveCountMax=3 \
    -o StrictHostKeyChecking=yes \
    -o UserKnownHostsFile=/root/.ssh/tg_relay_known_hosts \
    -i /root/.ssh/tg_relay_key \
    tgrelay@72.56.67.83
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable --now tg-relay-tunnel.service
systemctl status tg-relay-tunnel.service --no-pager
```

Проверка, что туннель реально работает:

```bash
curl --socks5-hostname 127.0.0.1:1080 -sS -o /dev/null -w 'HTTP %{http_code}\n' https://api.telegram.org
# ожидается: HTTP 302 (или похожий быстрый ответ), а не таймаут
```

Проверка, что ограничение `permitopen` реально работает (туннель не
превратился в общий прокси на всю сеть ams):

```bash
curl --socks5-hostname 127.0.0.1:1080 -sS --connect-timeout 5 -o /dev/null -w 'HTTP %{http_code}\n' https://vk.com
# ожидается: ошибка/отказ (channel open failed), НЕ HTTP 200 —
# permitopen разрешает только api.telegram.org:443
```

## Шаг 3 — включить в .env.prod

В `/root/insurance_broker/.env.prod` добавить:

```
TELEGRAM_SOCKS5_PROXY=127.0.0.1:1080
```

Это подхватят и bash-скрипты бэкапов (`telegram-config.sh` читает
`.env.prod`), и Django-контейнер (`docker-compose.prod.yml` наверняка
пробрасывает `.env.prod` в `web`-сервис — проверить перед первым
включением, что `TELEGRAM_SOCKS5_PROXY` реально долетает до контейнера,
как долетают остальные `TELEGRAM_*`).

Важный нюанс: `127.0.0.1:1080` — это порт на **хосте** (где крутится
туннель), а Django/Celery работают **внутри Docker-контейнера**, у
которого свой `127.0.0.1`. Если контейнер использует `network_mode: host`
или туннель поднят так, что доступен из контейнера иначе (например,
через `host.docker.internal` или IP docker-моста) — адрес в
`TELEGRAM_SOCKS5_PROXY` для Python-пути (`apps.core.notifications`) нужно
указать соответствующий, а не `127.0.0.1`. Для bash-скриптов бэкапов
(`backup-db-telegram.sh` и т.д.) это не проблема — они выполняются прямо
на хосте через cron, не в контейнере.

## Откат

Полностью и без следов на обоих серверах:

```bash
# на polis:
systemctl disable --now tg-relay-tunnel.service
rm -f /etc/systemd/system/tg-relay-tunnel.service
rm -f /root/.ssh/tg_relay_key /root/.ssh/tg_relay_key.pub /root/.ssh/tg_relay_known_hosts
# убрать TELEGRAM_SOCKS5_PROXY из .env.prod

# на ams:
userdel -r tgrelay
```

После отката код продолжит работать как раньше (пустой
`TELEGRAM_SOCKS5_PROXY` = прямое соединение, как до этой задачи) —
ничего в коде откатывать не нужно.
