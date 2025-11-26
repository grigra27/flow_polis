# Форматирование процентных значений

## Описание изменений

Все процентные значения в системе (особенно КВ - коэффициент выполнения) теперь отображаются без дробной части, только целые числа.

## Что было изменено

### 1. Создан новый фильтр шаблонов

**Файл:** `apps/policies/templatetags/currency_filters.py`

Добавлен фильтр `percent`, который округляет процентные значения до целых чисел:

```python
@register.filter(name='percent')
def format_percent(value):
    """
    Форматирует процентное значение без дробной части.
    Пример: 12.50 -> "12", 15.00 -> "15"
    """
    try:
        num = float(value)
        return str(int(round(num)))
    except (ValueError, TypeError):
        return value
```

### 2. Обновлены HTML шаблоны

Фильтр применен в следующих шаблонах:

- `templates/insurers/insurer_list.html` - список страховщиков с КВ
- `templates/insurers/insurer_detail.html` - детальная страница страховщика
- `templates/policies/policy_detail.html` - детальная страница полиса

**Использование:**
```django
{% load currency_filters %}
{{ rate.kv_percent|percent }}%
```

### 3. Обновлен экспорт в Excel

**Файл:** `apps/reports/views.py`

В функции `export_payments_excel` значения КВ теперь округляются:

```python
int(round(float(payment.commission_rate.kv_percent))) if payment.commission_rate else 0
```

### 4. Обновлена модель CommissionRate

**Файл:** `apps/insurers/models.py`

Метод `__str__` теперь отображает округленные значения:

```python
def __str__(self):
    return f'{self.insurer} - {self.insurance_type}: {int(round(float(self.kv_percent)))}%'
```

### 5. Обновлена админка

**Файл:** `apps/insurers/admin.py`

Добавлен метод `kv_percent_display` для отображения округленных значений в списке:

```python
def kv_percent_display(self, obj):
    """Отображение КВ без дробной части"""
    return f"{int(round(float(obj.kv_percent)))}%"
```

### 6. Добавлены тесты

**Файл:** `apps/policies/tests/test_currency_filters.py`

Добавлен класс `PercentFiltersTestCase` с тестами для нового фильтра.

## Примеры

### До изменений:
- 12.50% → 12.50%
- 15.00% → 15.00%
- 10.75% → 10.75%

### После изменений:
- 12.50% → 12%
- 15.00% → 15%
- 10.75% → 11%

## Примечание

Округление использует стандартное математическое округление Python (банковское округление):
- 12.5 → 12 (округление к четному)
- 13.5 → 14 (округление к четному)
- 10.4 → 10
- 10.6 → 11

Это не влияет на хранение данных в базе - там по-прежнему хранятся точные значения с двумя знаками после запятой.
