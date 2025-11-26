# Руководство по системе аутентификации

## Обзор

Система страхового брокера использует встроенную систему аутентификации Django с двухуровневой моделью прав доступа. Это руководство содержит подробную информацию о работе с системой аутентификации, управлении пользователями и настройке безопасности.

## Архитектура системы

### Компоненты

1. **Модуль аутентификации** (`apps.accounts`)
   - Обработка входа и выхода пользователей
   - Кастомные формы с русской локализацией
   - Красивый интерфейс страницы входа

2. **Модуль авторизации**
   - Декораторы для function-based views
   - Миксины для class-based views
   - Middleware для автоматической проверки прав

3. **Система прав доступа**
   - Использование флага `is_staff` для разделения типов пользователей
   - Context processors для передачи информации о правах в шаблоны
   - Template tags для условного отображения элементов

### Модель пользователя

Используется встроенная модель `django.contrib.auth.models.User` без модификаций.

**Ключевые поля:**
- `username` - уникальное имя пользователя для входа
- `password` - хешированный пароль (PBKDF2 + SHA256)
- `is_staff` - флаг администратора
- `is_superuser` - флаг суперпользователя
- `is_active` - флаг активности учетной записи
- `first_name`, `last_name` - имя и фамилия
- `email` - адрес электронной почты
- `last_login` - дата последнего входа
- `date_joined` - дата создания учетной записи

## Типы пользователей

### Обычный пользователь (Regular User)

**Характеристики:**
```python
is_staff = False
is_superuser = False
is_active = True
```

**Права доступа:**
- ✅ Просмотр всех данных
  - Клиенты
  - Страховые компании
  - Полисы
  - Платежи
  - Отчеты
- ✅ Экспорт данных в Excel
- ✅ Доступ к дашборду с аналитикой
- ❌ Создание новых записей
- ❌ Редактирование существующих записей
- ❌ Удаление записей
- ❌ Доступ к административной панели Django

**Интерфейс:**
- Скрыты кнопки "Добавить", "Редактировать", "Удалить"
- Скрыта ссылка на админ-панель в навигации
- Отображается индикатор "Обычный пользователь" в интерфейсе

### Администратор (Administrator)

**Характеристики:**
```python
is_staff = True
is_superuser = True
is_active = True
```


**Права доступа:**
- ✅ Все права обычного пользователя
- ✅ Создание новых записей (клиенты, страховщики, полисы)
- ✅ Редактирование всех существующих записей
- ✅ Удаление записей
- ✅ Полный доступ к административной панели Django
- ✅ Управление пользователями системы
- ✅ Настройка системы через админ-панель

**Интерфейс:**
- Отображаются все элементы управления
- Доступна ссылка "Админка" в навигации
- Отображается индикатор "Администратор" в интерфейсе

## Создание пользователей

### Метод 1: Через административную панель (рекомендуется)

**Шаг 1: Вход в админ-панель**
1. Войдите в систему как администратор
2. Перейдите по адресу: `http://your-domain.com/admin/`
3. Или нажмите на ссылку "Админка" в навигации

**Шаг 2: Создание пользователя**
1. В разделе "Authentication and Authorization" выберите "Users"
2. Нажмите кнопку "Add user" (Добавить пользователя)
3. Заполните обязательные поля:
   - **Username** - уникальное имя пользователя (латиница, цифры, @/./+/-/_)
   - **Password** - надежный пароль (минимум 8 символов)
   - **Password confirmation** - повторите пароль
4. Нажмите "Save and continue editing"

**Шаг 3: Настройка прав и дополнительной информации**
1. Заполните личную информацию (опционально):
   - **First name** - Имя
   - **Last name** - Фамилия
   - **Email address** - Email

2. Установите права доступа:
   
   **Для обычного пользователя:**
   - ☐ Active (должна быть установлена)
   - ☐ Staff status (НЕ устанавливать)
   - ☐ Superuser status (НЕ устанавливать)
   
   **Для администратора:**
   - ☑ Active
   - ☑ Staff status
   - ☑ Superuser status

3. Нажмите "Save"

### Метод 2: Через командную строку

**Создание суперпользователя (администратора):**

```bash
# Локальная разработка
python manage.py createsuperuser

# Docker development
docker compose -f docker-compose.dev.yml exec web python manage.py createsuperuser

# Docker production
docker compose -f docker-compose.prod.yml exec web python manage.py createsuperuser
```

Интерактивный процесс запросит:
- Username (имя пользователя)
- Email address (опционально, можно пропустить)
- Password (пароль, не отображается при вводе)
- Password (again) (подтверждение пароля)

**Быстрое создание для разработки:**

```bash
# Создает пользователя admin/admin
python create_superuser.py
```

⚠️ **Внимание:** Используйте только для локальной разработки!

### Метод 3: Через Django shell

**Создание обычного пользователя:**

```bash
python manage.py shell
```

```python
from django.contrib.auth.models import User

# Создание обычного пользователя
user = User.objects.create_user(
    username='ivanov',
    password='SecurePassword123!',
    first_name='Иван',
    last_name='Иванов',
    email='ivanov@company.com'
)

print(f"Создан пользователь: {user.username}")
print(f"is_staff: {user.is_staff}")  # False
print(f"is_superuser: {user.is_superuser}")  # False
```

**Создание администратора:**

```python
from django.contrib.auth.models import User

# Создание администратора
admin = User.objects.create_superuser(
    username='petrov',
    password='AdminPassword456!',
    first_name='Петр',
    last_name='Петров',
    email='petrov@company.com'
)

print(f"Создан администратор: {admin.username}")
print(f"is_staff: {admin.is_staff}")  # True
print(f"is_superuser: {admin.is_superuser}")  # True
```

**Массовое создание пользователей:**

```python
from django.contrib.auth.models import User

users_data = [
    {'username': 'sidorov', 'first_name': 'Сидор', 'last_name': 'Сидоров', 'password': 'Pass123!'},
    {'username': 'kozlov', 'first_name': 'Козлов', 'last_name': 'Иван', 'password': 'Pass456!'},
    {'username': 'novikov', 'first_name': 'Новиков', 'last_name': 'Петр', 'password': 'Pass789!'},
]

for data in users_data:
    user = User.objects.create_user(**data)
    print(f"Создан: {user.username}")
```

