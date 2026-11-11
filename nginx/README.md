# Конфигурация Nginx

Сверено 2026-11-11. [default.conf](default.conf) задаёт virtual hosts,
канонический `polis.insflow.ru`, TLS, proxy, static и media.
[nginx.conf](nginx.conf) — глобальные настройки и persistent-логи с маскированием
одноразового кода перехода InsFlow.

**[Общее руководство по DNS, SSL и media](../docs/DNS_SSL_SETUP.md)**
объединяет прежний SSL_SETUP и разбор перезапуска Nginx.

Оба файла защищены на хосте и сравниваются по SHA-256 в workflow.
Обычный релиз приложения их не устанавливает:
[процедура инфраструктурных изменений](../docs/DEPLOYMENT.md).
Общий `/media/` не является публичным file alias: без входа открыты только
логотипы СК, филиалов и иконки видов страхования.
