# Быстрое исправление проблемы с деплоем

## Проблема
Деплой упал с ошибкой 137 (out of memory) при выполнении миграций.

## Быстрое решение

### На сервере выполните:

```bash
# 1. Подключитесь к серверу
ssh -i ~/.ssh/deploy_key user@your-droplet

# 2. Перейдите в директорию проекта
cd /path/to/onlinepolis

# 3. ОБЯЗАТЕЛЬНО создайте резервную копию!
./scripts/backup-db.sh

# 4. Откатите неудачную миграцию
docker-compose exec web python manage.py migrate policies 0002

# 5. Обновите код (миграция теперь оптимизирована)
git pull origin main

# 6. Пересоберите контейнер
docker-compose build web

# 7. Запустите безопасную миграцию
docker-compose exec web ./scripts/safe-migrate.sh

# 8. Если все ОК - перезапустите
docker-compose restart web
```

## Что было исправлено

1. **Оптимизирована миграция 0004**:
   - Добавлена обработка данных батчами (по 500 записей)
   - Улучшена совместимость с PostgreSQL
   - Добавлена обработка ошибок

2. **Создан безопасный скрипт миграции**:
   - Автоматический откат при ошибке
   - Проверка состояния до и после
   - Таймаут 5 минут

## Проверка после деплоя

```bash
# Проверьте, что миграции применены
docker-compose exec web python manage.py showmigrations policies

# Должно быть:
# [X] 0001_initial
# [X] 0002_editable_commission
# [X] 0003_paymentschedule_insurance_sum
# [X] 0004_transfer_property_value

# Проверьте данные
docker-compose exec web python manage.py shell << 'PYTHON'
from apps.policies.models import PaymentSchedule
null_count = PaymentSchedule.objects.filter(insurance_sum__isnull=True).count()
total = PaymentSchedule.objects.count()
print(f"✅ Payments with insurance_sum: {total - null_count}/{total}")
PYTHON
```

## Если все еще не работает

1. **Увеличьте память дроплета** (временно):
   - В DigitalOcean увеличьте размер до 2GB RAM
   - Выполните миграцию
   - Верните обратно

2. **Выполните миграцию вручную**:
   ```bash
   docker-compose exec web python manage.py shell
   ```
   
   Затем в shell:
   ```python
   from apps.policies.models import Policy, PaymentSchedule
   
   for policy in Policy.objects.all():
       if hasattr(policy, 'property_value'):
           PaymentSchedule.objects.filter(
               policy=policy
           ).update(insurance_sum=policy.property_value)
   ```

## Откат (если нужно)

```bash
# Откатите миграции
docker-compose exec web python manage.py migrate policies 0002

# Откатите код
git checkout <previous-commit>

# Пересоберите
docker-compose build web
docker-compose restart web
```

## Контакты
Если проблема не решается - создайте issue с логами:
```bash
docker-compose logs web > deployment_error.log
```
