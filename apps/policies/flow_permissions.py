"""Права локальной учётной записи «Полисов» при оформлении из ЗС."""
from functools import wraps

from django.core.exceptions import PermissionDenied
from django.shortcuts import render
from django.utils.cache import add_never_cache_headers


CREATE_DENIED = "У вашей учётной записи в «Полисах» нет права создавать полисы."


class FlowAccessDenied(PermissionDenied):
    pass


def can_create(user):
    return (
        user.is_active
        and user.is_staff
        and user.has_perms(("policies.add_policy", "policies.add_paymentschedule"))
    )


def can_link(user):
    return (
        user.is_active
        and user.is_staff
        and (
            user.has_perm("policies.link_flow_policy")
            or (can_create(user) and user.has_perm("policies.change_policy"))
        )
    )


def require_access(user, *, create=False, link=False):
    if link and not can_link(user):
        raise FlowAccessDenied(
            "У вашей учётной записи в «Полисах» нет права связывать существующие полисы со сводом."
        )
    if (create and not can_create(user)) or (
        not create and not link and not (can_create(user) or can_link(user))
    ):
        raise FlowAccessDenied(CREATE_DENIED)


def forbidden(request, reason=CREATE_DENIED):
    response = render(
        request, "policies/flow_error.html", {"error": str(reason)}, status=403
    )
    response["Referrer-Policy"] = "no-referrer"
    add_never_cache_headers(response)
    return response


def explain_denial(view):
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        try:
            return view(request, *args, **kwargs)
        except FlowAccessDenied as error:
            return forbidden(request, error)

    return wrapped
