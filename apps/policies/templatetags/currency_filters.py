from django import template

register = template.Library()


@register.filter(name='rub')
def format_rub(value):
    """
    Форматирует число с разделением тысяч пробелами (без символа рубля).
    Пример: 100000 -> "100 000"
    """
    try:
        # Преобразуем в float и округляем до 2 знаков
        num = float(value)
        # Форматируем с разделением тысяч пробелами
        formatted = "{:,.2f}".format(num).replace(',', ' ')
        # Убираем .00 если число целое
        if formatted.endswith('.00'):
            formatted = formatted[:-3]
        return formatted
    except (ValueError, TypeError):
        return value
