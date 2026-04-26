# Пользователи и права доступа

## Типы пользователей

Система поддерживает три типа пользователей:

### 1. Обычный пользователь

```python
is_staff = False
is_superuser = False
```

**Может:**
- Просматривать всех клиентов, страховщиков, полисы, платежи
- Экспортировать данные в Excel
- Работать с дашбордом

**Не может:**
- Создавать, редактировать или удалять записи
- Заходить в admin-панель Django

Кнопки «Добавить», «Редактировать», «Удалить» в интерфейсе скрыты.

### 2. Администратор с ограниченными правами

```python
is_staff = True
is_superuser = False
# + конкретные права в разделе "Права пользователя"
```

**Может:**
- Всё что обычный пользователь
- Заходить в admin-панель Django
- Только те действия, на которые явно выданы права

**Как настроить:** создать пользователя → `is_staff = True`, `is_superuser = False` → выбрать нужные права в разделе «Права пользователя».

### 3. Суперпользователь

```python
is_staff = True
is_superuser = True
```

Полный доступ ко всему. Обходит все проверки прав. Может управлять другими пользователями.

---

## Доступные права по моделям

| Модель | Право | Код |
|--------|-------|-----|
| Полис | Создание | `policies.add_policy` |
| Полис | Редактирование | `policies.change_policy` |
| Полис | Удаление | `policies.delete_policy` |
| Полис | Просмотр | `policies.view_policy` |
| График платежей | Создание | `policies.add_paymentschedule` |
| График платежей | Редактирование | `policies.change_paymentschedule` |
| График платежей | Удаление | `policies.delete_paymentschedule` |
| График платежей | Просмотр | `policies.view_paymentschedule` |
| Клиент | Создание | `clients.add_client` |
| Клиент | Редактирование | `clients.change_client` |
| Клиент | Удаление | `clients.delete_client` |
| Клиент | Просмотр | `clients.view_client` |
| Страховщик | Создание | `insurers.add_insurer` |
| Страховщик | Редактирование | `insurers.change_insurer` |
| Страховщик | Удаление | `insurers.delete_insurer` |
| Страховщик | Просмотр | `insurers.view_insurer` |

---

## Примеры конфигураций

**Менеджер по полисам** — создаёт и редактирует полисы, но не удаляет:
- `is_staff = True`, `is_superuser = False`
- Права: `add_policy`, `change_policy`, `view_policy`, `add_paymentschedule`, `change_paymentschedule`, `view_paymentschedule`

**Оператор ввода данных** — только добавляет новые полисы:
- `is_staff = True`, `is_superuser = False`
- Права: `add_policy`, `view_policy`, `add_paymentschedule`, `view_paymentschedule`, `add_client`, `view_client`

**Аудитор** — только просмотр:
- `is_staff = False` (обычный пользователь) — достаточно для просмотра без admin

---

## Создание пользователей

### Через admin-панель (рекомендуется)

1. Перейти на `/admin/` → Authentication and Authorization → Users → Add user
2. Заполнить username и password → Save and continue editing
3. Выставить флаги `is_staff` / `is_superuser` и при необходимости выбрать права
4. Save

### Через командную строку

```bash
# Суперпользователь
docker-compose -f docker-compose.prod.yml exec web python manage.py createsuperuser
```

### Через Django shell

```python
from django.contrib.auth.models import User

# Обычный пользователь
user = User.objects.create_user(username='ivanov', password='SecurePass123!')

# Суперпользователь
admin = User.objects.create_superuser(username='petrov', password='AdminPass456!')
```

---

## Использование прав в коде

### Views

```python
from apps.accounts.decorators import admin_required
from apps.accounts.mixins import AdminRequiredMixin

@admin_required(permission='policies.add_policy')
def create_policy(request): ...

class PolicyCreateView(AdminRequiredMixin, CreateView):
    permission_required = 'policies.add_policy'
```

### Шаблоны

```django
{% load permission_tags %}

{% can_edit request.user as user_can_edit %}
{% if user_can_edit %}
    <a href="{% url 'policies:create' %}">Добавить полис</a>
{% endif %}

{% if perms.policies.change_policy %}
    <a href="{% url 'policies:edit' policy.id %}">Редактировать</a>
{% endif %}
```

---

## FAQ

**Пользователь с `is_staff=True` не видит данные в админке?**
Нужно выдать права на просмотр (`view_*`) для соответствующих моделей.

**Как дать доступ только к просмотру полисов?**
`is_staff=True`, `is_superuser=False`, права: `policies.view_policy`, `policies.view_paymentschedule`.

**Можно создать группу с одинаковыми правами?**
Да — в admin-панели есть раздел «Группы». Создать группу, назначить права, добавить пользователей в группу.

**Row-level permissions (доступ только к своим полисам)?**
Текущая система не поддерживает — потребуется доработка.
