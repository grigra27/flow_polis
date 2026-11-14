from django.http import HttpResponse
from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from django.utils import timezone
from django.views.decorators.cache import never_cache
from pathlib import Path


@never_cache
@login_required
def dashboard(request):
    """Dashboard 3.0. Все вкладки и расшифровки используют один срез."""
    from django.core.paginator import Paginator
    from django.conf import settings
    from apps.insurers.models import Branch
    from .services.portfolio_scope import PortfolioScope, SCOPE_LABELS
    from .services.dashboard_v3_service import DashboardV3Service, TABS

    scope = PortfolioScope.from_query(request.GET)
    tab = request.GET.get("tab", "overview")
    if tab not in dict(TABS):
        tab = "overview"
    service = DashboardV3Service(scope)
    context = service.context(tab=tab, measure=request.GET.get("measure", "sum"))
    context["preview_label"] = getattr(settings, "DASHBOARD_PREVIEW_LABEL", "")
    context["branches"] = [
        {"id": b.pk, "name": b.branch_name, "selected": b.pk in scope.branch_ids}
        for b in Branch.objects.order_by("branch_name")
    ]
    context["scope_options"] = [
        {"key": key, "label": label, "selected": key == scope.structure_scope}
        for key, label in SCOPE_LABELS.items()
    ]
    context["today_value"] = timezone.localdate().isoformat()
    context["detail"] = service.detail(request.GET)
    if context["detail"]:
        detail = context["detail"]
        detail["total"] = len(detail["rows"])
        detail["page"] = Paginator(detail.pop("rows"), 40).get_page(
            request.GET.get("page")
        )
        params = request.GET.copy()
        for direction, number in (
            ("previous", detail["page"].number - 1),
            ("next", detail["page"].number + 1),
        ):
            params["page"] = number
            detail[direction + "_url"] = "?" + params.urlencode() + "#dashboard-detail"
        detail["close_url"] = service.url(tab, measure=context["measure"])
    return render(request, "core/dashboard.html", context)


@never_cache
@login_required
def serve_media_file(request, path):
    """
    Serve private media to authenticated users without browser/proxy caching.
    """
    from django.http import FileResponse, Http404
    from django.conf import settings

    # Resolve symlinks before checking containment: a string prefix also
    # accepts sibling directories such as media-private next to media.
    try:
        media_root = Path(settings.MEDIA_ROOT).resolve()
        file_path = (media_root / path).resolve(strict=True)
        if not file_path.is_relative_to(media_root) or not file_path.is_file():
            raise Http404("File not found")
        file_handle = file_path.open("rb")
    except (OSError, RuntimeError, ValueError):
        raise Http404("File not found") from None

    response = FileResponse(file_handle, as_attachment=True, filename=file_path.name)
    response["X-Content-Type-Options"] = "nosniff"
    return response


def health(request):
    """
    Живость Django/gunicorn для Docker healthcheck и system_health_check (H-13).
    Без логина и без обращений к БД: проверяет только, что воркер отвечает.
    Снаружи недоступен — nginx отвечает на /health/ сам.
    """
    return HttpResponse("ok", content_type="text/plain")
