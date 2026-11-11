# Ротация секретов Onlinepolis

Сверено с [settings.py](../config/settings.py), [production policy](../scripts/deploy/security.override.yml) 2026-11-11.
Эффективные серверные значения и состояние доступа проверяются отдельно.

Процедура для администратора production. Подготовлена 2026-11-06,
актуализирована 2026-11-07 для кода на Django 5.2 LTS, PostgreSQL 15,
Compose plugin, проект `insurance_broker`.
Добавление этой инструкции и поддержки fallback-ключей **не меняет действующие
секреты**. Каждый тип секрета меняется отдельной операцией.

Плановая ротация запускается по решению владельца. Эта процедура не вводит
обязательную периодичность, автоматическое расписание или срок действия ключей.
При утечке или подозрении на компрометацию секрет отзывают и заменяют отдельно
от планового графика. Начатую плановую замену завершают отключением старого значения.

## Подготовка и применение конфигурации

Сначала завершить текущий деплой и согласовать короткое окно обслуживания.
Сохранить работающий административный SSH-сеанс и доступ через консоль Timeweb.
Секреты вводить через защищённый редактор/менеджер паролей: не через аргументы
shell, чат, Git или CI-логи. При смене PostgreSQL-пароля иметь свежий проверенный
бэкап БД.

В административной Bash-shell сервера:

```bash
set +x
set -euo pipefail
umask 077
cd /root/insurance_broker
rotation_dir="/root/.local/state/onlinepolis-secrets/$(date +%Y%m%dT%H%M%S)"
install -d -m 700 "$rotation_dir"
exec 9> /root/.local/state/onlinepolis-deploy.lock
flock -w 3600 9
cp .env.prod "$rotation_dir/env.before"
chmod 600 "$rotation_dir/env.before"
test ! -e .env.prod.next
cp .env.prod .env.prod.next
chmod 600 .env.prod.next
```

Отредактировать `.env.prod.next` приватно. Это staging-файл, ещё не используемый
приложением. После подготовки конкретного секрета опубликовать его в том же
каталоге и заново загрузить переменные в текущую shell:

```bash
mv .env.prod.next .env.prod
set -a
source .env.prod
set +a
rotation_compose=(docker compose --compatibility -p insurance_broker --project-directory /root/insurance_broker --env-file /root/insurance_broker/.env.prod -f /etc/onlinepolis-deploy/compose.yml -f /etc/onlinepolis-deploy/security.override.yml)
"${rotation_compose[@]}" config --quiet
"${rotation_compose[@]}" up -d --no-deps --no-build --pull never --force-recreate --wait --wait-timeout 180 web celery_worker celery_beat < /dev/null
"${rotation_compose[@]}" up -d --no-deps --no-build --pull never --force-recreate --wait --wait-timeout 90 nginx < /dev/null
"${rotation_compose[@]}" exec -T --interactive=false nginx nginx -t < /dev/null
```

Нужен **recreate**, потому что `restart` не перечитывает изменённые переменные
окружения. Nginx пересоздаётся для разрешения нового адреса web; БД, Redis и certbot
этими командами не пересоздаются. Используется защищённая Compose-база вместе с
security overlay: команда с одним repo-файлом могла бы снять ограничения UID/caps.
Используются уже проверенные загруженные образы,
сборки на сервере нет. [Docker Compose: restart](https://docs.docker.com/reference/cli/docker/compose/restart/).

После проверок освободить общий lock: `flock -u 9; exec 9>&-`. Не оставлять shell
с lock открытой до следующего рабочего дня. Пока lock удерживается, не вызывать
controller `activate`/`health`/`rollback`: они используют тот же lock. Прямые
Compose-проверки выше выполняются в уже удерживаемом окне. Зафиксировать дату, тип секрета,
оператора, результат и срок удаления старого значения; сами значения не записывать.

## SECRET_KEY: плановая смена и компрометация

Сначала развернуть версию приложения с `SECRET_KEY_FALLBACKS_JSON`. Это JSON-массив
непустых строк, по умолчанию `[]`; ошибочная форма останавливает запуск без вывода
значений. Переменная хранит **старые настоящие ключи** в том же защищённом
`.env.prod`, что и текущий `SECRET_KEY`. Deploy-процесс с административным доступом
может прочитать этот файл; fallback не скрывает ключ от такого доступа. Код
выкладываемого приложения получает текущий и старые ключи из окружения: право
публиковать произвольный app-образ не изолирует эти секреты от его кода.

Для плановой смены:

1. Создать новый случайный ключ в менеджере паролей или в закрытом файле. Например,
   следующий код пишет 256 бит случайности без вывода ключа в терминал:

   ```bash
   python3 - "$rotation_dir/secret-key.next" <<'PY'
   import os, secrets, sys
   fd = os.open(sys.argv[1], os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
   with os.fdopen(fd, "w") as stream:
       stream.write(secrets.token_hex(32) + "\n")
   print("new_key_saved=True")
   PY
   ```

2. В staging-конфигурации установить новый `SECRET_KEY`, а прежнее значение
   поместить первым элементом `SECRET_KEY_FALLBACKS_JSON`. Формат — shell-safe
   JSON в одинарных кавычках; сохранить все символы старого ключа без изменений.
   Если старый ключ содержит апостроф, записать этот символ внутри JSON как
   `\u0027`: JSON-декодирование восстановит апостроф, а shell-кавычки останутся целыми.
   Не переносить реальные значения в примеры или историю команд.
3. Применить конфигурацию общей последовательностью выше. Новые подписи создаются
   новым ключом; fallback позволяет временно проверять старые. Проверить вход и
   ранее открытую сессию. Активная Django-сессия при проверке старого auth hash
   переводится на новый ключ. [Django: сессии](https://docs.djangoproject.com/en/5.2/topics/auth/default/#session-invalidation-on-password-change).
4. Назначить конечный срок grace-периода по максимальному реально используемому
   TTL сессий/подписанных данных. В текущем production `SESSION_COOKIE_AGE=86400`
   секунд; если используются password-reset токены или собственные подписи,
   отдельно учесть их сроки. После окна установить `SECRET_KEY_FALLBACKS_JSON='[]'`
   и снова пересоздать приложения/nginx. Старые немигрировавшие сессии и подписи
   перестанут приниматься. Пользовательские пароли от смены `SECRET_KEY` не меняются.
   [Django: SECRET_KEY_FALLBACKS](https://docs.djangoproject.com/en/5.2/ref/settings/#secret-key-fallbacks).

При **компрометации** старого ключа не оставлять его в fallback: сразу новый ключ
и `[]`, с ожидаемым завершением старых сессий/подписей. Не возвращать утёкший ключ
ради сохранения входа. Защищённые временные копии удалить после закрытия окна
восстановления; резервные копии тоже могут содержать старые секреты.

## PostgreSQL: пароль роли и конфигурация приложения

`POSTGRES_PASSWORD` — источник значения для новых контейнеров Django через
`DB_PASSWORD`. Изменение файла само по себе **не меняет пароль существующей роли**
в инициализированном volume PostgreSQL. [Официальный образ PostgreSQL](https://hub.docker.com/_/postgres).

1. Подготовить staging-файл с новым `POSTGRES_PASSWORD`, сохранив прежнее значение
   в защищённой копии для восстановления. Если в файле остались legacy `DB_*`,
   удалить их либо синхронизировать с `POSTGRES_*`; controller проверяет совпадение
   legacy-значений и фактического DB-окружения приложений с источником PostgreSQL.
2. До смены пароля открыть интерактивную административную сессию БД:

   ```bash
   set -a
   source .env.prod
   set +a
   docker exec -it insurance_broker_db psql -X -U "$POSTGRES_USER" -d "$POSTGRES_DB"
   ```

   В psql выполнить `\password` для текущей роли и дважды ввести новый пароль.
   Команда выполняет `ALTER ROLE`, не помещая открытый пароль в SQL/history/logs.
   Затем `\q` возвращает в административную shell.
   Не использовать `psql -c "ALTER ROLE ... PASSWORD '...'"`.
   [PostgreSQL 15: \password](https://www.postgresql.org/docs/15/app-psql.html#APP-PSQL-META-COMMAND-PASSWORD).
3. Сразу опубликовать staging-файл и пересоздать приложения/nginx общей
   последовательностью. Между сменой пароля роли и пересозданием приложения
   возможны ошибки новых соединений; это окно обслуживания, а не безостановочная
   dual-password схема. Не удалять volume и не запускать повторный `initdb`.
4. Проверить **новое TCP-соединение** из web с новой конфигурацией; один статус
   `pg_isready` не доказывает правильность пароля.
   [PostgreSQL: pg_isready](https://www.postgresql.org/docs/15/app-pg-isready.html).
   Пример выдаёт только результат:

   ```bash
   "${rotation_compose[@]}" exec -T --interactive=false -e SENTRY_DSN= -e TELEGRAM_ENABLED=false -e VK_ENABLED=false web python -c '
   import logging, sys
   logging.disable(logging.CRITICAL)
   try:
       from django.conf import settings
       settings.LOGGING_CONFIG = None
       import django
       django.setup()
       from django.db import connection
       connection.ensure_connection()
       with connection.cursor() as cursor:
           cursor.execute("SELECT 1")
           ok = cursor.fetchone() == (1,)
       print("fresh_database_connection_ok=" + str(ok))
       sys.exit(0 if ok else 1)
   except Exception:
       print("fresh_database_connection_ok=False")
       sys.exit(1)
   ' < /dev/null
   ```

   Дополнительно проверить обычный вход, чтение данных и Celery healthcheck.
   При сбое восстановить согласованную пару **пароль роли + env**, затем снова
   пересоздать приложения; возврат только файла оставляет рассинхрон. Для
   компрометации выпустить ещё один новый пароль вместо возврата старого.

## SMTP, Telegram, VK

Владелец почты/бота/сообщества выпускает новый секрет штатным способом провайдера.
Если разрешены параллельные креды: выпуск → staging/env → recreate → контрольная
проверка → отзыв старого. Если выпуск сразу отзывает старый, согласовать короткое
окно и выполнить замену без задержки.

| Контур | Что меняется в `.env.prod` | Проверка |
|---|---|---|
| Письма billing | `COMMUNICATIONS_SMTP_PASSWORD` и при необходимости аккаунт/host | Сначала доступность SMTP по B-01, затем согласованное тестовое письмо |
| Общая Django-почта | `EMAIL_HOST_PASSWORD`, если это отдельные credentials | Отдельная проверка этого backend |
| Telegram | `TELEGRAM_BOT_TOKEN`; `TELEGRAM_CHAT_ID` только при смене назначения | Контрольная доставка в согласованный чат |
| VK | `VK_COMMUNITY_TOKEN`; `VK_USER_ID` только при смене получателя | Контрольная доставка согласованному получателю |

Python-процессы получают новые значения после recreate. Bash-скрипты бэкапов читают
`.env.prod` при следующем запуске; не запускать полный бэкап только ради теста
токена. Не переотправлять все старые `failed` письма автоматически. После проверки
отозвать старый секрет у провайдера; при неуспехе вернуть ещё действующий старый
или выпустить новый, если отзыв уже произошёл.

## SSH-ключ CI и цепочка доверия

Это отдельная операция от переноса deploy-пользователя. Новый workflow использует
пользователя `onlinepolis-deploy` и Secrets `DEPLOY_SSH_PRIVATE_KEY` /
`DEPLOY_SSH_KNOWN_HOSTS`; старые `SSH_PRIVATE_KEY` и `DROPLET_USER` сохраняются до
успешного первого CI-перехода. Сохранить независимый административный доступ через
SSH/консоль. Перед проверками через controller освободить общий rotation-lock. Отпечаток host key проверить по доверенной
консоли и уже доверенному `known_hosts`: один `ssh-keyscan` не удостоверяет сервер.
Проверка нового доступа использует `StrictHostKeyChecking=yes`.
[OpenSSH: ssh-keyscan](https://man.openbsd.org/ssh-keyscan.1).

1. На доверенной машине создать отдельный Ed25519-ключ. Текущий CI требует
   неинтерактивного ключа без passphrase; административный ключ хранится отдельно:

   ```bash
   ssh-keygen -t ed25519 -N '' -f ~/.ssh/onlinepolis_deploy_next -C onlinepolis-deploy-next
   ```

2. Через действующий административный сеанс добавить **публичную** часть новому
   ключу в `authorized_keys` того же deploy-пользователя с теми же forced-command/
   `restrict`/прочими ограничениями. Не заменять весь файл и не снимать ограничения
   для проверки. Старую строку пока сохранить.
   [OpenSSH: authorized_keys](https://man.openbsd.org/sshd.8#AUTHORIZED_KEYS_FILE_FORMAT).
3. Проверить новый ключ отдельным соединением с `IdentitiesOnly=yes`,
   `BatchMode=yes`, `StrictHostKeyChecking=yes`; выполнить только разрешённую
   диагностическую команду deploy-wrapper. Использовать verb `status` нового controller, без произвольной shell-команды.
   В GitHub заменить приватный ключ через
   защищённый интерфейс или stdin, не выводя его:

   ```bash
   gh secret set DEPLOY_SSH_PRIVATE_KEY --repo grigra27/flow_polis < ~/.ssh/onlinepolis_deploy_next
   ```

   При первоначальной настройке или подтверждённой смене host key обновить
   `DEPLOY_SSH_KNOWN_HOSTS` из заранее проверенного файла через stdin. При обычной
   смене клиентского ключа доверенный host key менять не нужно.

4. Проверить штатный CI-деплой и восстановление доступа через независимый admin
   канал. Только после успеха удалить старую **конкретную** строку deploy-ключа
   из `authorized_keys` и закрытые копии старого приватного ключа. Проверить, что
   старый ключ больше не проходит аутентификацию, а новый по-прежнему работает.
   При проблеме до отзыва вернуть прежний GitHub Secret; при компрометации старый
   ключ не возвращать — использовать административный канал для выпуска нового.

При первом переходе legacy-ключ может оставаться в `authorized_keys` прежнего
`DROPLET_USER` (включая root). Его отзыв — отдельный завершающий шаг после успешной
проверки нового CI. Удаление старого ключа из нового deploy-аккаунта не отзывает
доступ через прежний аккаунт. Не удалять общий административный ключ, пока не
проверен независимый admin-доступ.
