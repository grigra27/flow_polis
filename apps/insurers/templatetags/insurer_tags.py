from django import template

register = template.Library()


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
