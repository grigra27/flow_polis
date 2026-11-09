from django.shortcuts import render
from django.contrib.auth.views import LoginView, LogoutView
from django.urls import Resolver404, resolve, reverse, reverse_lazy
from .forms import CustomAuthenticationForm


class CustomLoginView(LoginView):
    """
    Кастомное представление для входа в систему.

    Перенаправляет аутентифицированных пользователей на дашборд.
    Validates: Requirements 1.1, 1.5, 2.1, 2.2
    """

    template_name = "accounts/login.html"
    form_class = CustomAuthenticationForm
    redirect_authenticated_user = True

    def get_success_url(self):
        """Перенаправление на дашборд после успешного входа"""
        from apps.policies.flow_views import continuation_url, pending_tickets

        target = self.get_redirect_url()
        if target and any(
            target == continuation_url(key) for key in pending_tickets(self.request)
        ):
            return target
        # Ссылка из свода ведёт на обычную карточку портфеля, в том числе у читателя.
        if target.startswith("/") and not target.startswith("//"):
            try:
                matched = resolve(target)
            except Resolver404:
                pass
            else:
                if matched.view_name == "policies:detail":
                    return reverse("policies:detail", kwargs=matched.kwargs)
        return reverse_lazy("core:dashboard")


class CustomLogoutView(LogoutView):
    """
    Кастомное представление для выхода из системы.

    Перенаправляет на страницу входа после выхода.
    Validates: Requirements 5.1, 5.2
    """

    next_page = "accounts:login"


def access_denied(request):
    """
    Представление для отображения страницы отказа в доступе (403).

    Показывается когда обычный пользователь пытается получить доступ
    к ресурсам, доступным только администраторам.
    Validates: Requirements 3.3
    """
    return render(request, "accounts/access_denied.html", status=403)
