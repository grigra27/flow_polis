from django import template

register = template.Library()


@register.filter
def ru_pluralize(value, forms):
    """
    Склонение существительных в русском языке

    Использование:
    {{ count }} {{ count|ru_pluralize:"полис,полиса,полисов" }}

    forms: строка с тремя формами через запятую (1, 2-4, 5+)
    """
    try:
        value = int(value)
        forms_list = forms.split(",")

        if len(forms_list) != 3:
            return forms_list[0] if forms_list else ""

        # Определяем форму по правилам русского языка
        if value % 10 == 1 and value % 100 != 11:
            return forms_list[0]
        elif value % 10 in [2, 3, 4] and value % 100 not in [12, 13, 14]:
            return forms_list[1]
        else:
            return forms_list[2]
    except (ValueError, TypeError):
        return forms_list[0] if "forms_list" in locals() else ""


@register.inclusion_tag("insurers/includes/insurer_logo.html")
def insurer_logo(insurer, size="medium"):
    """
    Отображает логотип страховщика с названием

    Использование:
    {% load insurer_tags %}
    {% insurer_logo insurer size='small' %}

    Размеры: small (24px), medium (32px), large (48px)
    """
    sizes = {
        "small": "24px",
        "medium": "32px",
        "large": "48px",
    }

    return {
        "insurer": insurer,
        "size": sizes.get(size, sizes["medium"]),
    }


@register.inclusion_tag("insurers/includes/branch_logo.html")
def branch_logo(branch, size="medium"):
    """
    Отображает логотип филиала с названием

    Использование:
    {% load insurer_tags %}
    {% branch_logo branch size='small' %}

    Размеры: small (24px), medium (32px), large (48px)
    """
    sizes = {
        "small": "24px",
        "medium": "32px",
        "large": "48px",
    }

    return {
        "branch": branch,
        "size": sizes.get(size, sizes["medium"]),
    }


@register.inclusion_tag("insurers/includes/insurance_type_icon.html")
def insurance_type_icon(insurance_type, size="medium"):
    """
    Отображает иконку вида страхования с названием

    Использование:
    {% load insurer_tags %}
    {% insurance_type_icon insurance_type size='small' %}

    Размеры: small (24px), medium (32px), large (48px)
    """
    sizes = {
        "small": "24px",
        "medium": "32px",
        "large": "48px",
    }

    return {
        "insurance_type": insurance_type,
        "size": sizes.get(size, sizes["medium"]),
    }
