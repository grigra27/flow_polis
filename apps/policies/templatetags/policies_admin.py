from django import template
from django.contrib.admin.templatetags.admin_modify import submit_row
from django.contrib.admin.templatetags.base import InclusionAdminNode

register = template.Library()


@register.simple_tag
def payment_fields(inline_form):
    """Index the admin's editable or read-only fields for the payment row."""
    return {
        field.field["name"] if field.is_readonly else field.field.name: field
        for fieldset in inline_form
        for line in fieldset
        for field in line
    }


def policy_submit_row(context):
    ctx = submit_row(context)
    ctx.update(
        {
            # Show the custom button only in regular add/change forms
            # where a normal save action is available.
            "show_save_and_open_front": ctx.get("show_save", False)
            and not context.get("is_popup", False),
            "save_and_open_front_button_name": context.get(
                "save_and_open_front_button_name",
                "_save_and_open_front",
            ),
        }
    )
    return ctx


@register.tag(name="policy_submit_row")
def policy_submit_row_tag(parser, token):
    return InclusionAdminNode(
        parser,
        token,
        func=policy_submit_row,
        template_name="submit_line.html",
    )
