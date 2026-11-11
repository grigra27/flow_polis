# Секреты и доступ к инфраструктуре

Сверено с [workflow](../.github/workflows/deploy.yml),
[gate/controller и установщиком](../scripts/deploy/),
[settings.py](../config/settings.py) 2026-11-11.
Здесь объединены управление секретами и установка ограниченного SSH-доступа.
Эффективные серверные значения и состояние доступа проверяются отдельно;
история B-08 — в [BACKLOG.md](BACKLOG.md).

## Граница доступа CI

GitHub использует отдельный ключ и пользователя `onlinepolis-deploy`,
UID/GID 20001. У него нет Docker socket, групп docker/admin и общего sudo.
Forced-command gate допускает только `status`, `upload`, `activate`, `health`,
`rollback` с проверенными аргументами и вызывает root-owned controller.
Shell, SFTP/SCP, rsync, PTY и forwarding через этот вход запрещены.

Контроллер проверяет и перепаковывает образ, применяет защищённую host-политику.
Приложения работают как `10001:10001`, без setuid entrypoint, с `cap_drop: ALL`
и `no-new-privileges`. CI не задаёт mounts, user/caps, команды контейнеров,
Nginx или исполняемые root-скрипты. [Процесс релиза](DEPLOYMENT.md).

Право заменить приложение включает доступ его кода к прикладным credentials,
БД и media. Ограниченный SSH уменьшает полномочия на хосте, но не скрывает
секреты от нового приложения. Переданный SHA и checksum обеспечивают целостность,
а не независимое одобрение автора или provenance образа.

## Защищённые файлы

| Путь | Владелец и назначение |
|---|---|
| `/root/insurance_broker/.env.prod` | root:root, 0600; единое окружение приложения и PostgreSQL |
| `/etc/onlinepolis-deploy/compose.yml` | root; базовая Compose-конфигурация |
| `/etc/onlinepolis-deploy/security.override.yml` | root; обязательная runtime-политика |
| `/usr/local/sbin/onlinepolis-deploy-controller` | root; фиксированные операции деплоя |
| `/usr/local/libexec/onlinepolis-deploy-gate` | root; проверка SSH-команды перед sudo |
| `/etc/ssh/authorized_keys/onlinepolis-deploy` | root; ограниченные публичные deploy-ключи |
| `/root/insurance_broker/nginx/` | root; Nginx-конфигурация |
| `/root/insurance_broker/certbot/` | root; сертификаты и приватные TLS-ключи |

Прикладные секреты не проходят через Git или artifact сборки. Их перечень,
источники и defaults — в [ENVIRONMENT_VARIABLES.md](ENVIRONMENT_VARIABLES.md).
Изменения Compose/Nginx, controller, host-скриптов и cron устанавливаются
администратором отдельно. Четыре protected hashes проверяются до upload;
[состав и порядок](DEPLOYMENT.md#что-обновляет-релиз).

## Установка ограниченного доступа

Предварительно нужен [подготовленный стек](DEPLOYMENT.md#первоначальное-развёртывание).
Установку администратор выполняет отдельно от обычного релиза.

1. Сохранить независимый административный SSH-сеанс и доступ к консоли Timeweb.
   Создать отдельный Ed25519-ключ CI в закрытом каталоге, mode 0600. Приватную
   часть не передавать в чат, Git, shell arguments или логи.
2. Проверить публичную host key через доверенный SSH/консоль. Сохранить
   known_hosts со строкой для `onlinepolis-production`: это фиксированный
   `HostKeyAlias` workflow, независимый от адреса сервера. Для ручной проверки
   можно добавить строку фактического адреса. `ssh-keyscan` сам по себе
   подлинность ключа не удостоверяет.
3. Передать административным каналом проверенные
   `scripts/deploy/{install.sh,controller.py,gate.py,security.override.yml}`
   в закрытый каталог сервера и только публичную часть deploy-ключа.
4. Выполнить от root:

   ```bash
   bash /root/onlinepolis-deploy-install/install.sh /root/new-deploy-key.pub
   ```

   Installer создаёт аккаунт, gate/controller/Compose policy, forced-command
   SSH-вход и единственное разрешение sudo. Он проверяет `sshd -t` и `visudo`,
   сохраняет snapshot и откатывает неуспешную установку. Существующие root
   authorized_keys не меняются.
5. Новым ключом с `IdentitiesOnly=yes`, `BatchMode=yes`,
   `StrictHostKeyChecking=yes` проверить `status`, отказ shell/SFTP/PTY/forwarding.
   Заново проверить независимый admin-вход. Не выдавать deploy-пользователю
   docker-group или общий sudo.

## Подключение GitHub Actions

Workflow читает `DEPLOY_SSH_PRIVATE_KEY`, `DEPLOY_SSH_KNOWN_HOSTS`,
`DROPLET_HOST` и опциональный `SSH_PORT`; [единый справочник](ENVIRONMENT_VARIABLES.md#параметры-compose-bash-и-ci).
Имя `onlinepolis-deploy` зафиксировано в workflow. Прикладные пароли
и `SECRET_KEY` в GitHub не добавляются.

Значения ключей передаются защищённым интерфейсом либо stdin CLI:

```bash
gh secret set DEPLOY_SSH_PRIVATE_KEY --repo grigra27/flow_polis < /private/path/deploy-key
gh secret set DEPLOY_SSH_KNOWN_HOSTS --repo grigra27/flow_polis < /private/path/known_hosts
```

При первом переходе с root CI сохранить старый deploy-ключ и старые Secrets
до успешной проверки нового workflow. После согласованного push проверить
image IDs всех приложений, UID/caps, health, HTTPS, приватные вложения
с авторизацией и публичные изображения. Автоматический rollback БД не откатывает.

Только после успеха отозвать конкретный старый root CI key по fingerprint,
сохранив личный admin key и неидентифицированные чужие ключи. Удалить прежний
`SSH_PRIVATE_KEY`, проверить отказ старого и работу нового ключа.
`DROPLET_USER` и прежний `SSH_PRIVATE_KEY` текущим workflow не используются.
Не заменять целиком root authorized_keys. Фиксировать дату и результат без
приватного материала. Состояние уже выполненного перехода — в бэклоге.

## PostgreSQL, ротация и локальная работа

Compose отображает `POSTGRES_*` из `.env.prod` в `DB_*` приложений. Legacy
`DB_*` при наличии должны совпадать либо быть удалены. Изменение env-пароля
не меняет пароль существующей роли PostgreSQL. Старый `.env.prod.db` текущим
Compose не используется; перед удалением проверить старые host-скрипты.

Смена Django/DB/provider/SSH-секретов, fallback keys, перечитывание env через
recreate и восстановление согласованной пары значений описаны в отдельной
[SECRETS_ROTATION.md](SECRETS_ROTATION.md). При компрометации старый Django-ключ
не сохраняют в fallback. Поддержка fallback сама по себе ключи не меняет.

Локальный `.env` содержит только dev credentials. Production env, приватные
ключи, дампы и сертификаты не попадают в Git или диагностический вывод.
Проверки показывают наличие/совпадение и результат соединения без значений;
локальные тесты выполняются без production env/данных и внешней отправки.
