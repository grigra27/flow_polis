from django import template

register = template.Library()


@register.inclusion_tag('insurers/includes/insurer_logo.html')
def insurer_logo(insurer, size='medium'):
    """
    Отображает логотип страховщика с названием
    
    Использование:
    {% load insurer_tags %}
    {% insurer_logo insurer size='small' %}
    
    Размеры: small (24px), medium (32px), large (48px)
    """
    sizes = {
        'small': '24px',
        'medium': '32px',
        'large': '48px',
    }
    
    return {
        'insurer': insurer,
        'size': sizes.get(size, sizes['medium']),
    }
