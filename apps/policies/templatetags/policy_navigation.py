from urllib.parse import urlencode

from django import template

register = template.Library()


@register.simple_tag(takes_context=True)
def journal_return_query(context, row_kind, pk):
    path = context["request"].get_full_path()
    return urlencode({"journal": f"{path}#{row_kind}-{pk}"})
