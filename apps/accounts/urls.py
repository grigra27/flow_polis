"""
URL configuration for accounts app.

Provides routes for:
- Login (accounts:login)
- Logout (accounts:logout)
- Access denied (accounts:access_denied)

Validates: Requirements 1.1, 2.1, 5.2
"""
from django.urls import path
from .views import CustomLoginView, CustomLogoutView, access_denied

app_name = "accounts"

urlpatterns = [
    path("login/", CustomLoginView.as_view(), name="login"),
    path("logout/", CustomLogoutView.as_view(), name="logout"),
    path("access-denied/", access_denied, name="access_denied"),
]
