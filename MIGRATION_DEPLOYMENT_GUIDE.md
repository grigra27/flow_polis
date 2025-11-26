# Руководство по деплою миграции insurance_sum

## Проблема

Деплой упал с ошибкой 137 (out of memory) при выполнении миграций базы данных. Это произошло при попытке применить миграцию 0004, которая переносит данные из `policy.property_value` в `payment.insurance_sum`.

## Решение

Миграция была оптимизирована для работы с большими объемами данных:
- Добавлена обработка батчами (по 500 записей)
- Улучшена совместимость с PostgreSQL
- Добавлена обработка ошибок

## Шаги для безопасного деплоя

### 1. Проверка состояния на продакшене

Подключитесь к серверу и проверьте текущее состояние:

```bash
ssh -i ~/.ssh/deploy_key user@your-server

# Перейдите в директорию проекта
cd /path/to/project

# Активируйте виртуальное окружение
source venv/bin/activate

# Проверьте текущие миграции
python manage.py showmigrations policies
```

### 2. Создайте резервную копию базы данных

**ОБЯЗАТЕЛЬНО!** Перед любыми изменениями:

```bash
# Создайте резервную копию
./scripts/backup-db.sh

# Или вручную для PostgreSQL:
pg_dump -U postgres -d your_database > backup_before_migration_$(date +%Y%m%d_%H%M%S).sql
```

### 3. Проверьте доступную память

```bash
# Проверьте свободную память
free -h

# Проверьте размер базы данных
python manage.py shell << 'PYTHON'
from apps.policies.models import Policy, PaymentSchedule
print(f"Policies: {Policy.objects.count()}")
print(f"Payments: {PaymentSchedule.objects.count()}")
PYTHON
```

### 4. Откатите неудачную миграцию (если нужно)

Если миграция 0003 или 0004 уже частично применена:

```bash
# Откатите к миграции 0002
python manage.py migrate policies 0002

# Проверьте состояние
python manage.py showmigrations policies
```

### 5. Примените миграции с использованием безопасного скрипта

```bash
# Скопируйте обновленный код на сервер
git pull origin main

# Запустите безопасный скрипт миграции
./scripts/safe-migrate.sh
```

Скрипт автоматически:
- Проверит текущее состояние
- Оценит необходимую память
- Применит миграции с таймаутом 5 минут
- Откатит изменения при ошибке
- Проверит результат

### 6. Альтернативный метод (ручной)

Если скрипт не работает, выполните миграцию вручную:

```bash
# Установите таймаут для команды
timeout 300 python manage.py migrate policies

# Если упало - откатите
python manage.py migrate policies 0002
```

### 7. Проверка после миграции

```bash
# Проверьте, что миграции применены
python manage.py showmigrations policies

# Проверьте данные
python manage.py shell << 'PYTHON'
from apps.policies.models import PaymentSchedule

# Проверьте, что все платежи имеют insurance_sum
null_count = PaymentSchedule.objects.filter(insurance_sum__isnull=True).count()
total = PaymentSchedule.objects.count()
print(f"Payments with insurance_sum: {total - null_count}/{total}")

if null_count > 0:
    print(f"WARNING: {null_count} payments have NULL insurance_sum!")
else:
    print("✅ All payments have insurance_sum")
PYTHON
```

### 8. Перезапустите приложение

```bash
# Для Docker
docker-compose restart web

# Или для systemd
sudo systemctl restart your-app
```

## Если миграция все еще падает

### Проблема: Недостаточно памяти

**Решение 1: Увеличьте память сервера**
- Временно увеличьте размер дроплета в DigitalOcean
- После миграции можно вернуть обратно

**Решение 2: Выполните миграцию в несколько этапов**

Создайте временный скрипт для ручного переноса данных:

```python
# manual_migration.py
from apps.policies.models import Policy, PaymentSchedule
from decimal import Decimal

batch_size = 100
policies = Policy.objects.all()
total = policies.count()

for i in range(0, total, batch_size):
    batch = policies[i:i + batch_size]
    print(f"Processing batch {i//batch_size + 1}/{(total//batch_size) + 1}")
    
    for policy in batch:
        if hasattr(policy, 'property_value'):
            PaymentSchedule.objects.filter(
                policy=policy,
                insurance_sum__isnull=True
            ).update(insurance_sum=policy.property_value)
    
    print(f"Completed {min(i + batch_size, total)}/{total} policies")

print("✅ Manual migration complete!")
```

Запустите:
```bash
python manage.py shell < manual_migration.py
```

### Проблема: Таймаут PostgreSQL

Увеличьте таймауты в PostgreSQL:

```sql
-- Подключитесь к PostgreSQL
psql -U postgres -d your_database

-- Увеличьте таймауты
SET statement_timeout = '10min';
SET lock_timeout = '5min';
```

## Откат изменений

Если что-то пошло не так и нужно полностью откатить:

```bash
# 1. Откатите миграции
python manage.py migrate policies 0002

# 2. Восстановите из резервной копии (если нужно)
psql -U postgres -d your_database < backup_before_migration_YYYYMMDD_HHMMSS.sql

# 3. Откатите код
git checkout <previous-commit>

# 4. Перезапустите приложение
docker-compose restart web
```

## Проверка успешности деплоя

После успешного деплоя проверьте:

1. ✅ Миграции применены: `python manage.py showmigrations policies`
2. ✅ Все платежи имеют insurance_sum
3. ✅ Админка работает корректно
4. ✅ Можно создавать новые платежи
5. ✅ Можно копировать платежи
6. ✅ Фильтрация по insurance_sum работает

## Контакты для помощи

Если возникли проблемы:
1. Проверьте логи: `docker-compose logs web`
2. Проверьте логи PostgreSQL: `docker-compose logs db`
3. Создайте issue в репозитории с описанием ошибки
