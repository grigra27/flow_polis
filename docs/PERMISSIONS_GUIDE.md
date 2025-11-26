# Руководство по управлению правами пользователей

## Обзор

Система поддерживает три типа пользователей:

1. **Обычный пользователь** - только просмотр и экспорт данных
2. **Администратор с ограниченными правами** - доступ к админ-панели + конкретные права
3. **Суперпользователь** - полный доступ ко всему

## Типы пользователей

### 1. Обычный пользователь (Просмотр + Экспорт)

**Настройки:**
- `is_staff` = False
- `is_superuser` = False

**Возможности:**
- Просмотр всех данных (клиенты, полисы, страховщики)
- Экспорт отчетов в Excel
- Просмотр дашборда

**Ограничения:**
- Нет доступа к админ-панели
- Не может создавать, редактировать или удалять данные
- Не видит кнопки редактирования в интерфейсе

### 2. Администратор с ограниченными правами

**Настройки:**
- `is_staff` = True
- `is_superuser` = False
- Выбрать конкретные права в разделе "Права пользователя"

**Возможности:**
- Доступ к админ-панели Django
- Только те действия, на которые выданы права
- Например: может добавлять полисы, но не может их удалять

**Как настроить:**

1. Создайте пользователя в админ-панели
2. Установите `is_staff` = True
3. Оставьте `is_superuser` = False
4. В разделе "Права пользователя" выберите нужные права:
   - `policies | полис | Can add полис` - может создавать полисы
   - `policies | полис | Can change полис` - может редактировать полисы
   - `policies | полис | Can delete полис` - может удалять полисы
   - `policies | полис | Can view полис` - может просматривать полисы
   - И так далее для других моделей

### 3. Суперпользователь (Полный доступ)

**Настройки:**
- `is_staff` = True
- `is_superuser` = True

**Возможности:**
- Полный доступ ко всем функциям системы
- Может управлять пользователями
- Может выдавать права другим пользователям
- Обходит все проверки прав

## Доступные права по моделям

### Полисы (Policies)

- `policies.add_policy` - Создание полисов
- `policies.change_policy` - Редактирование полисов
- `policies.delete_policy` - Удаление полисов
- `policies.view_policy` - Просмотр полисов

### График платежей (Payment Schedule)

- `policies.add_paymentschedule` - Создание платежей
- `policies.change_paymentschedule` - Редактирование платежей
- `policies.delete_paymentschedule` - Удаление платежей
- `policies.view_paymentschedule` - Просмотр платежей

### Клиенты (Clients)

- `clients.add_client` - Создание клиентов
- `clients.change_client` - Редактирование клиентов
- `clients.delete_client` - Удаление клиентов
- `clients.view_client` - Просмотр клиентов

### Страховщики (Insurers)

- `insurers.add_insurer` - Создание страховщиков
- `insurers.change_insurer` - Редактирование страховщиков
- `insurers.delete_insurer` - Удаление страховщиков
- `insurers.view_insurer` - Просмотр страховщиков

## Примеры использования

### Пример 1: Менеджер по полисам

Пользователь должен иметь возможность создавать и редактировать полисы, но не удалять их.

**Настройки:**
- `is_staff` = True
- `is_superuser` = False
- Права:
  - ✅ `policies.add_policy`
  - ✅ `policies.change_policy`
  - ✅ `policies.view_policy`
  - ✅ `policies.add_paymentschedule`
  - ✅ `policies.change_paymentschedule`
  - ✅ `policies.view_paymentschedule`

### Пример 2: Оператор ввода данных

Пользователь должен только вводить новые полисы, но не редактировать существующие.

**Настройки:**
- `is_staff` = True
- `is_superuser` = False
- Права:
  - ✅ `policies.add_policy`
  - ✅ `policies.view_policy`
  - ✅ `policies.add_paymentschedule`
  - ✅ `policies.view_paymentschedule`
  - ✅ `clients.add_client`
  - ✅ `clients.view_client`

### Пример 3: Аудитор

Пользователь должен видеть все данные, но не может ничего изменять.

**Настройки:**
- `is_staff` = False (обычный пользователь)
- `is_superuser` = False

Или альтернативно:
- `is_staff` = True
- `is_superuser` = False
- Права:
  - ✅ `policies.view_policy`
  - ✅ `policies.view_paymentschedule`
  - ✅ `clients.view_client`
  - ✅ `insurers.view_insurer`

## Проверка прав в коде

### В представлениях (views)

```python
from apps.accounts.decorators import admin_required
from apps.accounts.mixins import AdminRequiredMixin

# Function-based view с проверкой конкретного права
@admin_required(permission='policies.add_policy')
def create_policy(request):
    # Только пользователи с правом add_policy могут создавать полисы
    ...

# Class-based view с проверкой права
class PolicyCreateView(AdminRequiredMixin, CreateView):
    permission_required = 'policies.add_policy'
    ...
```

### В шаблонах

```django
{% load permission_tags %}

{# Проверка общего права на редактирование #}
{% can_edit request.user as user_can_edit %}
{% if user_can_edit %}
    <a href="{% url 'policies:create' %}">Добавить полис</a>
{% endif %}

{# Проверка конкретного права #}
{% can_edit request.user 'policies.add_policy' as can_add_policy %}
{% if can_add_policy %}
    <a href="{% url 'policies:create' %}">Добавить полис</a>
{% endif %}

{# Альтернативный способ #}
{% has_perm request.user 'policies.change_policy' as can_change %}
{% if can_change %}
    <a href="{% url 'policies:edit' policy.id %}">Редактировать</a>
{% endif %}

{# Проверка встроенным способом Django #}
{% if perms.policies.add_policy %}
    <a href="{% url 'policies:create' %}">Добавить полис</a>
{% endif %}
```

## Миграция существующих пользователей

Если у вас уже есть пользователи с `is_staff=True`, они продолжат работать как раньше. Однако теперь вы можете:

1. Оставить их как суперпользователей (`is_superuser=True`) для полного доступа
2. Или снять `is_superuser` и выдать конкретные права для ограниченного доступа

## Рекомендации по безопасности

1. **Принцип минимальных привилегий**: Выдавайте только те права, которые действительно нужны пользователю
2. **Регулярный аудит**: Периодически проверяйте, какие права у каких пользователей
3. **Суперпользователи**: Создавайте минимальное количество суперпользователей
4. **Документирование**: Записывайте, почему конкретному пользователю выданы определенные права

## Часто задаваемые вопросы

**Q: Пользователь с `is_staff=True` не видит данные в админке. Почему?**

A: Нужно выдать права на просмотр (`view_*`) для соответствующих моделей.

**Q: Как дать пользователю доступ ко всем полисам, но только к просмотру?**

A: Установите `is_staff=True`, `is_superuser=False` и выдайте только права `policies.view_policy` и `policies.view_paymentschedule`.

**Q: Можно ли создать группы пользователей с одинаковыми правами?**

A: Да! В админ-панели есть раздел "Группы". Создайте группу, выдайте ей права, затем добавьте пользователей в эту группу.

**Q: Что делать, если пользователь должен иметь доступ только к определенным полисам?**

A: Текущая система не поддерживает row-level permissions. Для этого потребуется дополнительная разработка.

## Поддержка

При возникновении вопросов или проблем с правами пользователей обращайтесь к системному администратору.
