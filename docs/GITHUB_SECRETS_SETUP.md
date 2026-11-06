# Ограниченный SSH-доступ GitHub Actions

B-08 заменяет прежний неограниченный root-ключ отдельным входом для выкладки
готового приложения. Текущий статус перехода — в [BACKLOG.md](BACKLOG.md).

## Подготовка администратором

1. Сохранить независимый административный SSH-сеанс и доступ к консоли Timeweb.
   Создать отдельный Ed25519-ключ CI в закрытом локальном каталоге, mode 0600.
   Приватную часть не отправлять в чат, репозиторий, shell arguments или логи.
2. Проверить публичную host key сервера через существующий доверенный SSH/консоль.
   Сохранить строку known_hosts с именем `onlinepolis-production`: это фиксированный
   `HostKeyAlias` workflow, независимый от адреса в `DROPLET_HOST`. Для ручных
   проверок можно дополнительно сохранить строку фактического адреса сервера.
3. Из проверенного исходного кода передать администраторским каналом файлы
   `scripts/deploy/{install.sh,controller.py,gate.py,security.override.yml}`
   в закрытый каталог сервера. Передать только публичную часть нового ключа.
4. Выполнить installer вручную от root, передав путь к одному публичному ключу:

   ```bash
   bash /root/onlinepolis-deploy-install/install.sh /root/new-deploy-key.pub
   ```

   Installer создаёт UID/GID 20001, root-owned gate/controller/Compose policy,
   отдельный forced-command SSH-вход и единственное разрешение sudo. Проверяет
   `sshd -t` и `visudo`, сохраняет snapshot и откатывает неуспешную установку.
   Существующие root authorized_keys он не меняет.
5. Через новый ключ с `IdentitiesOnly=yes`, `BatchMode=yes`,
   `StrictHostKeyChecking=yes` проверить `status`. Отдельно убедиться, что
   shell-команда, SFTP, PTY и port forwarding отклоняются. Подключиться заново
   через независимый admin-вход.

Не добавлять пользователя в группу docker и не давать ему общий sudo.
Смена имени пользователя при сохранении таких прав не создаёт ограничения.

## GitHub Secrets и включение workflow

Добавить `DEPLOY_SSH_PRIVATE_KEY` и `DEPLOY_SSH_KNOWN_HOSTS` через защищённый
интерфейс либо stdin CLI. Например, имена файлов ниже — локальные защищённые файлы:

```bash
gh secret set DEPLOY_SSH_PRIVATE_KEY --repo grigra27/flow_polis < /private/path/deploy-key
gh secret set DEPLOY_SSH_KNOWN_HOSTS --repo grigra27/flow_polis < /private/path/known_hosts
```

`DROPLET_HOST` сохраняется; `SSH_PORT` нужен только при отличии от 22.
Пользователь в новом workflow зафиксирован как `onlinepolis-deploy`.
Новый workflow не использует старые `SSH_PRIVATE_KEY` и `DROPLET_USER`.
До проверки новой выкладки сохранить старый root deploy key и старые secrets —
это позволяет вернуть прежний workflow при неуспешном переходе.

После разрешённого push проверить полный CI и независимые production-проверки:
ожидаемые image IDs всех трёх приложений, UID/capabilities, все healthcheck,
HTTPS, закрытые анонимные вложения, скачивание после входа и публичные логотипы.
Откат использует сохранённые image IDs и защищённую политику; БД не откатывается.

Только после успеха отозвать конкретный старый root CI key по fingerprint,
сохранив личный admin key и неидентифицированные чужие ключи. Удалить старый
GitHub Secret `SSH_PRIVATE_KEY`, проверить отказ старого deploy-ключа и повторную
работу нового. Не подменять весь root authorized_keys и не очищать чужие записи.
Отпечатки, даты и результат фиксировать без приватного материала.

## Последующие изменения инфраструктуры

Деплой передаёт только образ через `upload`, затем вызывает `activate` и `health`.
У ключа нет произвольного bash/SCP/rsync-доступа. Checkout не копируется на хост.
Compose, nginx, root-скрипты и сам controller обновляет администратор после review.
При изменении защищённых файлов CI остановится на проверке hashes до активации.

Право заменить приложение включает доступ нового кода к его прикладным секретам
и бизнес-данным. Ограничение SSH уменьшает права на хосте; оно не является
изоляцией приложения от собственной БД или проверкой доверенной provenance.
Процедура ротации: [SECRETS_ROTATION.md](SECRETS_ROTATION.md).
