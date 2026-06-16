from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from django.db.models import Sum, Count, Q
from django.urls import reverse
from django.utils import timezone
from datetime import timedelta
import logging

logger = logging.getLogger(__name__)

STRUCTURE_SCOPE_OPTIONS = (
    {
        "key": "all",
        "label": "Все сделки",
        "hint": "С участием брокера и без",
    },
    {
        "key": "broker",
        "label": "Только с участием брокера",
        "hint": "Только broker_participation = Да",
    },
)


def _normalize_structure_scope(scope):
    normalized = (scope or "").strip().lower()
    if normalized in {"broker", "with_broker", "broker_only"}:
        return "broker"
    return "all"


def _build_structure_scope_context(request, selected_scope):
    normalized_scope = _normalize_structure_scope(selected_scope)
    switch_options = []
    for option in STRUCTURE_SCOPE_OPTIONS:
        params = request.GET.copy()
        params["structure_scope"] = option["key"]
        switch_options.append(
            {
                **option,
                "active": option["key"] == normalized_scope,
                "url": f"{request.path}?{params.urlencode()}#portfolio-structure",
            }
        )

    return {
        "dashboard_v2_structure_scope": normalized_scope,
        "dashboard_v2_structure_scope_options": switch_options,
    }


@login_required
def dashboard(request):
    """
    Dashboard 2.0
    """
    requested_structure_scope = request.GET.get("structure_scope")
    from django.utils.dateparse import parse_date

    requested_as_of = parse_date(request.GET.get("as_of") or "")
    try:
        from apps.core.services.dashboard_v2_service import DashboardV2Service

        context = DashboardV2Service().get_dashboard_context(
            structure_scope=requested_structure_scope or "all",
            as_of=requested_as_of,
        )
    except Exception as exc:
        logger.error("Error building Dashboard 2.0 context: %s", exc, exc_info=True)
        context = {
            "dashboard_v2_meta": {
                "generated_at": timezone.now(),
                "today": timezone.localdate(),
                "period_label": "Ошибка расчета",
            },
            "dashboard_v2_snapshot": {
                "active_policies_count": 0,
                "not_uploaded_policies_count": 0,
                "not_uploaded_policies_share": 0,
                "upcoming_payments_count": 0,
                "upcoming_payments_amount": 0,
                "no_payment_data_count": 0,
                "no_payment_data_amount": 0,
                "health_score": 0,
                "data_quality_score": 0,
                "cards": [],
            },
            "dashboard_v2_health": {
                "score": 0,
                "previous_score": 0,
                "delta": 0,
                "delta_label": "0.0",
                "delta_direction": "flat",
                "components": [],
                "weights": {},
                "interpretation": "Недоступно",
            },
            "dashboard_v2_bridge": {
                "calendar_year": timezone.localdate().year,
                "year_start": timezone.localdate().replace(month=1, day=1),
                "year_end": timezone.localdate().replace(month=12, day=31),
                "actual_period_label": "Прошедших месяцев в этом году еще нет",
                "planned_period_label": "Текущий и будущие месяцы в этом году отсутствуют",
                "actual": {"premium": 0, "insurance_sum": 0},
                "planned": {"premium": 0, "insurance_sum": 0},
                "bridge": {"premium": 0, "insurance_sum": 0},
                "premium_actual_share": 0,
                "premium_plan_share": 0,
            },
            "dashboard_v2_payment_contour": {
                "snapshot": None,
                "window_30": {},
                "statuses": [],
            },
            "dashboard_v2_aging": {"buckets": [], "total_amount": 0, "total_count": 0},
            "dashboard_v2_renewal": {"active_total": 0, "horizons": []},
            "dashboard_v2_data_quality": {"quality_score": 0, "problems": []},
            "dashboard_v2_structure": {
                "policy_count": 0,
                "by_branch": [],
                "by_insurer": [],
                "by_type": [],
                "top_branch": None,
                "top_insurer": None,
                "top_type": None,
                "branch_breakdown": {
                    "top": [],
                    "other_share": 0,
                    "chart": [],
                    "pie_css": "conic-gradient(#e3ecf8 0% 100%)",
                },
                "insurer_breakdown": {
                    "top": [],
                    "other_share": 0,
                    "chart": [],
                    "pie_css": "conic-gradient(#e3ecf8 0% 100%)",
                },
                "type_breakdown": {
                    "top": [],
                    "other_share": 0,
                    "chart": [],
                    "pie_css": "conic-gradient(#e3ecf8 0% 100%)",
                },
            },
            "dashboard_v2_concentration": {
                "insurer": {
                    "hhi": 0,
                    "top1_share": 0,
                    "top3_share": 0,
                    "level": "Низкий",
                },
                "branch": {
                    "hhi": 0,
                    "top1_share": 0,
                    "top3_share": 0,
                    "level": "Низкий",
                },
                "overall_hhi": 0,
                "overall_level": "Низкий",
            },
            "dashboard_v2_dynamics": {
                "window_30": {
                    "days": 30,
                    "created_count": 0,
                    "deactivated_count": 0,
                    "net_growth": 0,
                    "net_growth_label": "+0",
                },
                "window_90": {
                    "days": 90,
                    "created_count": 0,
                    "deactivated_count": 0,
                    "net_growth": 0,
                    "net_growth_label": "+0",
                },
                "overdue_share_current": 0,
                "overdue_share_previous": 0,
                "overdue_share_delta_pp": 0,
                "overdue_share_delta_pp_label": "0.0",
            },
            "dashboard_v2_insights": {"insights": [], "quick_actions": []},
            "dashboard_v2_legacy_relay": {
                "cards": [
                    {
                        "key": "upcoming",
                        "type": "payment",
                        "tone": "warning",
                        "title": "Предстоящие платежи",
                        "count": 0,
                        "rows": [],
                        "link_url": reverse("policies:payments") + "?status=upcoming",
                        "link_label": "Все предстоящие платежи",
                    },
                    {
                        "key": "overdue",
                        "type": "payment",
                        "tone": "danger",
                        "title": "Нет данных об оплате",
                        "count": 0,
                        "rows": [],
                        "link_url": reverse("policies:payments") + "?status=overdue",
                        "link_label": "Все не оплаченные платежи",
                    },
                    {
                        "key": "recent",
                        "type": "policy",
                        "tone": "primary",
                        "title": "Недавно добавленные полисы",
                        "count": 0,
                        "rows": [],
                        "link_url": reverse("policies:list"),
                        "link_label": "Все полисы",
                    },
                    {
                        "key": "not_uploaded",
                        "type": "policy",
                        "tone": "info",
                        "title": "Полисы неподгруженные",
                        "count": 0,
                        "rows": [],
                        "link_url": reverse("policies:list") + "?policy_uploaded=False",
                        "link_label": "Все не подгруженные полисы",
                    },
                ]
            },
            "dashboard_v2_structure_scope": _normalize_structure_scope(
                requested_structure_scope
            ),
        }

    context.update(
        _build_structure_scope_context(
            request,
            selected_scope=context.get(
                "dashboard_v2_structure_scope", requested_structure_scope or "all"
            ),
        )
    )

    return render(request, "core/dashboard.html", context)


@login_required
def serve_media_file(request, path):
    """
    Serves media files with Content-Disposition header for security.
    Validates: Requirement 8.5

    This prevents inline execution of uploaded files by forcing download.
    """
    from django.http import FileResponse, Http404
    from django.conf import settings
    import os
    import mimetypes

    # Construct full file path
    file_path = os.path.join(settings.MEDIA_ROOT, path)

    # Check if file exists
    if not os.path.exists(file_path):
        raise Http404("File not found")

    # Check if path is within MEDIA_ROOT (prevent directory traversal)
    real_path = os.path.realpath(file_path)
    real_media_root = os.path.realpath(settings.MEDIA_ROOT)

    if not real_path.startswith(real_media_root):
        raise Http404("Invalid file path")

    # Get MIME type
    content_type, _ = mimetypes.guess_type(file_path)
    if content_type is None:
        content_type = "application/octet-stream"

    # Open file
    try:
        file_handle = open(file_path, "rb")
    except IOError:
        raise Http404("Cannot open file")

    # Create response with Content-Disposition header
    response = FileResponse(file_handle, content_type=content_type)

    # Set Content-Disposition to attachment to prevent inline execution
    filename = os.path.basename(file_path)
    response["Content-Disposition"] = f'attachment; filename="{filename}"'

    # Additional security headers
    response["X-Content-Type-Options"] = "nosniff"

    return response
