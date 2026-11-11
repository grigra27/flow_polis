# GitHub Actions

Источник — [deploy.yml](deploy.yml), сверено 2026-11-11.
`Deploy to Production` запускается при push в `main` и вручную.
Последовательность: `validate → test → build → deploy`; `notify` пишет итог
в Actions, при ошибке deploy выполняется `rollback`.

- [Деплой, Compose, подготовка сервера и recovery](../../docs/DEPLOYMENT.md).
- [Установка SSH-доступа и подключение GitHub Actions](../../docs/SECURITY.md).
- [Параметры CI и окружения](../../docs/ENVIRONMENT_VARIABLES.md#параметры-compose-bash-и-ci).
- [Проверка работающего образа и сервисов](../../docs/MONITORING.md).
- [Ротация ключей и паролей](../../docs/SECRETS_ROTATION.md).
