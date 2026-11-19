"""Права на action повторной отправки failed-писем.

Просмотр журнала доступен staff с view-правом, но повторная отправка —
мутирующее действие, поэтому оно должно требовать change-право.
"""
import pytest
from django.contrib.admin.sites import AdminSite
from django.contrib.auth.models import Permission, User
from django.test import RequestFactory

from apps.communications.admin import OutboundEmailAdmin
from apps.communications.models import OutboundEmail


def _request(user):
    request = RequestFactory().get("/admin/communications/outboundemail/")
    request.user = user
    return request


def _staff(username, *codenames):
    user = User.objects.create_user(username, password="x", is_staff=True)
    for codename in codenames:
        user.user_permissions.add(Permission.objects.get(codename=codename))
    return User.objects.get(pk=user.pk)


@pytest.mark.django_db
class TestRetryActionPermissions:
    def _admin(self):
        return OutboundEmailAdmin(OutboundEmail, AdminSite())

    def test_view_only_staff_can_view_but_not_retry(self):
        user = _staff("viewer", "view_outboundemail")
        admin = self._admin()
        request = _request(user)

        assert admin.has_view_permission(request) is True
        assert admin.has_change_permission(request) is False
        assert "retry_failed_emails" not in admin.get_actions(request)

    def test_change_staff_gets_retry_action(self):
        user = _staff("editor", "view_outboundemail", "change_outboundemail")
        admin = self._admin()

        assert "retry_failed_emails" in admin.get_actions(_request(user))

    def test_superuser_gets_retry_action(self):
        user = User.objects.create_superuser("boss", "boss@example.com", "x")
        admin = self._admin()

        assert "retry_failed_emails" in admin.get_actions(_request(user))
