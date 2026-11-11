# Пользователи и права доступа

Сверено с [middleware](../apps/accounts/middleware.py),
[mixins](../apps/accounts/mixins.py), [billing](../apps/billing/views.py),
[аналитикой](../apps/analytics/views.py) и
[правами InsFlow](../apps/policies/flow_permissions.py) 2026-11-11.

## Роли

| Учётная запись | Основные возможности |
|---|---|
| Обычная: `is_staff=False`, `is_superuser=False` | Общие журналы и карточки, главная, отчёты; без Django admin |
| Ограниченный администратор: `is_staff=True`, `is_superuser=False` | Admin и действия по выданным model permissions |
| Суперпользователь | Полный административный доступ, отдельный раздел аналитики |

Флаг staff не заменяет права на модели в Django admin. Обычный пользователь
не является строго read-only для всего продукта: комментарии очередных взносов
доступны вошедшим пользователям, а отправка писем зависит от отдельного флага.
Главная со сводкой и `/analytics/` — разные разделы.

## Отдельные проверки

- `/analytics/` и её детализации/экспорт используют `SuperuserRequiredMixin`.
- Middleware ограничивает административные и create/edit/update/delete URL;
  обновление комментария задачи очередного взноса имеет явное исключение.
- Отправка писем: `COMMUNICATIONS_RESTRICT_TO_SUPERUSER=True` по умолчанию
  допускает только суперпользователя. При `False` допускается любой
  авторизованный пользователь раздела. Permission
  `communications.send_outbound_email` существует, но этот UI-гейт его
  **не проверяет**. Саму отправку дополнительно включает
  `COMMUNICATIONS_EMAIL_ENABLED`.
- Создание полиса из InsFlow требует активного staff-пользователя с
  `policies.add_policy` **и** `policies.add_paymentschedule`.
- Связывание существующего полиса с InsFlow требует активного staff-пользователя
  с `policies.link_flow_policy` либо права создания плюс
  `policies.change_policy`.
- Загрузка приватных media требует входа. В коде нет универсального
  разграничения доступа к каждому документу по владельцу полиса.

## Типовые model permissions

| Модель | Коды |
|---|---|
| Полис | `policies.view_policy`, `add_policy`, `change_policy`, `delete_policy` |
| Платёж | `policies.view_paymentschedule`, `add_paymentschedule`, `change_paymentschedule`, `delete_paymentschedule` |
| Клиент | `clients.view_client`, `add_client`, `change_client`, `delete_client` |
| Страховщик | `insurers.view_insurer`, `add_insurer`, `change_insurer`, `delete_insurer` |
| Связь InsFlow | `policies.link_flow_policy` |

В строке таблицы префикс приложения относится ко всем перечисленным кодам.
Для массового назначения используйте группы Django. Прав на уровне «видеть
только свои полисы» общая ролевая модель не предоставляет.

## Настройка сотрудника

1. В Django admin создайте пользователя и личный пароль.
2. Для просмотра общих журналов оставьте staff/superuser выключенными.
3. Для работы в admin включите staff и выдайте минимальный необходимый набор
   view/add/change/delete прав или группу.
4. Для перехода из InsFlow отдельно проверьте права создания/связывания.
5. Проверьте доступ под учётной записью сотрудника, включая прямые URL.

Для локального создания суперпользователя:

```bash
python manage.py createsuperuser
```

На сервере команду запускает администратор в работающем web-контейнере:
`docker exec -it insurance_broker_web python manage.py createsuperuser`.
Это операция изменения данных; ограниченный deploy-ключ не даёт такого shell.
Пароль не задавайте аргументом команды и не сохраняйте в документации.
