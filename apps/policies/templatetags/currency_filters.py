from django import template

register = template.Library()


@register.filter(name="rub")
def format_rub(value):
    """
    Форматирует число с разделением тысяч пробелами (без символа рубля).
    Показывает копейки только если они не равны нулю.
    Пример: 100000.50 -> "100 000.50", 100000.00 -> "100 000"
    """
    try:
        # Преобразуем в float
        num = float(value)

        # Проверяем, есть ли дробная часть
        if num == int(num):
            # Если дробной части нет, форматируем как целое число
            formatted = "{:,}".format(int(num)).replace(",", " ")
        else:
            # Если есть дробная часть, форматируем с двумя знаками после запятой
            formatted = "{:,.2f}".format(num).replace(",", " ")

        return formatted
    except (ValueError, TypeError):
        return value


@register.filter(name="currency")
def format_currency(value):
    """
    Форматирует число как валюту с символом рубля, округляя до полных рублей.
    Пример: 100000.50 -> "100 001 ₽"
    """
    try:
        # Преобразуем в float и округляем до целого
        num = round(float(value))
        # Форматируем с разделением тысяч пробелами
        formatted = "{:,}".format(num).replace(",", " ")
        return formatted + " ₽"
    except (ValueError, TypeError):
        return value


@register.filter(name="percent")
def format_percent(value):
    """
    Форматирует процентное значение без дробной части.
    Пример: 12.50 -> "12", 15.00 -> "15"
    """
    try:
        # Преобразуем в float и округляем до целого
        num = float(value)
        return str(int(round(num)))
    except (ValueError, TypeError):
        return value


@register.filter(name="get_item")
def get_item(dictionary, key):
    """
    Получает значение из словаря по ключу.
    Используется в шаблонах для доступа к значениям словаря с динамическими ключами.
    Пример: {{ my_dict|get_item:key_variable }}
    """
    if dictionary is None:
        return None
    try:
        return dictionary.get(key)
    except (AttributeError, TypeError):
        return None


@register.filter(name="sub")
def subtract(value, arg):
    """
    Вычитает arg из value.
    Используется в шаблонах для математических операций вычитания.
    Пример: {{ value|sub:other_value }}
    """
    try:
        return float(value) - float(arg)
    except (ValueError, TypeError):
        return 0


@register.filter(name="month_name")
def month_name(month_num):
    """
    Преобразует номер месяца (1-12) в название месяца на русском языке.
    Пример: {{ 1|month_name }} -> "Январь"
    """
    month_names = {
        1: "Январь",
        2: "Февраль",
        3: "Март",
        4: "Апрель",
        5: "Май",
        6: "Июнь",
        7: "Июль",
        8: "Август",
        9: "Сентябрь",
        10: "Октябрь",
        11: "Ноябрь",
        12: "Декабрь",
    }
    try:
        return month_names.get(int(month_num), f"Месяц {month_num}")
    except (ValueError, TypeError):
        return f"Месяц {month_num}"
