# GitHub Actions: сборка и ограниченный деплой

`.github/workflows/deploy.yml` запускается push в `main` или вручную.
Статус B-08 и остальных задач ведётся в `docs/BACKLOG.md`.

1. Проверка Compose и полный pytest выполняются до production-операций.
2. Buildx один раз собирает `linux/amd64` с revision исходного commit SHA.
3. Python/Redis smoke проверяет именно готовый образ. Docker archive связывается
   SHA-256/canonical config digest с проверенными слоями и runtime configuration.
4. Архив сохраняется immutable workflow artifact на два дня. Deploy скачивает
   точный artifact ID с `digest-mismatch: error`; повтор failed deploy использует
   исходный image ref из build output, даже если attempt изменился.
5. CI подключается отдельным ограниченным ключом к `onlinepolis-deploy`, используя
   заранее проверенный known_hosts и `StrictHostKeyChecking=yes`.
6. `status` проверяет protocol и hashes защищённой серверной конфигурации.
   `upload` принимает только ограниченный gzip image stream и проверенные metadata.
   Controller проверяет и перепаковывает только Config/Layers/единственный app tag.
   Исходный OCI index или посторонние tags не передаются Docker loader.
7. `activate` использует root-owned Compose+security policy. Миграции/static
   выполняются один раз; переключаются только web/worker/beat и nginx. На сервере
   нет build, rsync checkout, SCP или произвольного remote bash.
8. `health` сверяет фактические native image IDs, все семь сервисов и HTTPS login.
   При сбое выполняется ограниченный `rollback`; schema/media/static назад
   автоматически не возвращаются. Снимки прежних образов сохраняются сервером.

## Доступ и секреты

Нужны `DEPLOY_SSH_PRIVATE_KEY`, `DEPLOY_SSH_KNOWN_HOSTS`, `DROPLET_HOST` и при
нестандартном порте `SSH_PORT`. Имя `onlinepolis-deploy` зафиксировано в workflow.
Прикладные секреты находятся только в root-owned `.env.prod` и передаются
контейнерам серверной политикой. Пользователь CI не входит в docker/admin и имеет
sudo только на проверяющий фиксированный controller.

Изменение кода приложения остаётся полномочием CI: приложение видит свои секреты,
БД и media. Hash из CI обеспечивает целостность передачи, а не независимую
авторизацию автора образа. Host-политика и административные ключи этому ключу
не доступны для замены.

## Защищённая конфигурация

CI сравнивает четыре source hashes: `docker-compose.prod.yml`,
`scripts/deploy/security.override.yml`, `nginx/nginx.conf`, `nginx/default.conf`.
При расхождении администратор сначала проверяет и устанавливает host-изменения;
CI сам их не устанавливает. root scripts/cron также больше не обновляются rsync.
Установка и переход: `docs/GITHUB_SECRETS_SETUP.md`.
Ротация ключей/паролей: `docs/SECRETS_ROTATION.md`.

Контейнеры приложения запускаются с UID/GID 10001, без setuid entrypoint,
с `cap_drop: ALL` и `no-new-privileges`. Названия контейнеров, project
`insurance_broker`, сети и существующие data volumes сохраняются.

## Проверки и восстановление

Перед выкладкой: целевые controller/gate/rotation tests, full pytest, pre-commit,
Compose merge и actionlint. На сервере отдельно проверяются allow/deny SSH-команды,
root/admin доступ, импорт нормализованного архива, runtime user/caps, health и media.
Одного зелёного CI недостаточно для подтверждения фактически работающего образа.

При неуспехе `activate` controller пытается восстановить сохранённые образы.
Отдельный GitHub recovery job вызывает `rollback RUNID` в том числе после
обрыва SSH. Общий server lock исключает одновременную активацию и восстановление.
Если миграция несовместима со старым кодом, требуется ручное восстановление;
автоматического понижения схемы нет.

Артефакт после двух дней истекает: для новой доставки перезапустить полный
workflow, а не только failed deploy job. Старые rollback-образы сохраняются
независимо от срока GitHub artifact.
