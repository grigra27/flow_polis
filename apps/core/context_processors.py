from datetime import datetime, timedelta, timezone as dt_timezone
from pathlib import Path

from django.conf import settings
from django.core.cache import cache
from django.urls import reverse
from django.utils import timezone


def service_navigation(request):
    return {"requests_home_url": f"{settings.FLOW_ZS_BASE_URL.rstrip('/')}/requests/"}


FOOTER_CACHE_KEY = "footer_status:v1"
FOOTER_CACHE_TTL = 60
# Дайджест ходит в 06:00 ежедневно; 26 часов — суточный цикл плюс запас.
DIGEST_STALE_AFTER = timedelta(hours=26)
BEAT_STALE_AFTER = timedelta(hours=24)


def _build_label():
    # .git не попадает в образ, поэтому время сборки берём из mtime файла,
    # который CI checkout создаёт заново при каждом релизе.
    mtime = Path(settings.BASE_DIR / "config" / "settings.py").stat().st_mtime
    build_dt = datetime.fromtimestamp(mtime, tz=dt_timezone.utc)
    return timezone.localtime(build_dt).strftime("%d.%m %H:%M")


BUILD_LABEL = _build_label()


def _shortMoment(moment, today):
    local = timezone.localtime(moment)
    if local.date() == today:
        return local.strftime("%H:%M")
    return local.strftime("%d.%m %H:%M")


def _collect_status():
    from django.db.models import Max

    from django_celery_beat.models import PeriodicTask

    from apps.communications.models import OutboundEmail
    from apps.core.models import ServiceHeartbeat
    from apps.policies.models import PaymentSchedule

    # Тот же срез, что в PaymentScheduleListView (status=overdue/week),
    # чтобы счётчик в футере совпадал с журналом по ссылке.
    today = timezone.now().date()
    unpaid_active = PaymentSchedule.objects.filter(
        paid_date__isnull=True, policy__policy_active=True
    )
    data = {
        "overdue_count": unpaid_active.filter(due_date__lt=today).count(),
        "week_count": unpaid_active.filter(
            due_date__range=(today, today + timedelta(days=7))
        ).count(),
        "mail_queued": OutboundEmail.objects.filter(
            status=OutboundEmail.STATUS_QUEUED
        ).count(),
        "mail_failed": OutboundEmail.objects.filter(
            status=OutboundEmail.STATUS_FAILED
        ).count(),
        "digest": None,
        "beat_label": None,
        "beat_stale": False,
    }

    now = timezone.now()
    local_today = timezone.localdate()

    digest = ServiceHeartbeat.objects.filter(key="daily_digest").first()
    if digest is None:
        data["digest"] = {"state": "unknown", "label": "нет данных"}
    elif now - digest.last_success_at > DIGEST_STALE_AFTER:
        days = (now - digest.last_success_at).days
        data["digest"] = {"state": "stale", "label": f"{days} дн. назад"}
    else:
        data["digest"] = {
            "state": "ok",
            "label": _shortMoment(digest.last_success_at, local_today),
        }

    beat_last = PeriodicTask.objects.filter(enabled=True).aggregate(
        last=Max("last_run_at")
    )["last"]
    if beat_last is not None:
        data["beat_label"] = _shortMoment(beat_last, local_today)
        data["beat_stale"] = now - beat_last > BEAT_STALE_AFTER

    return data


def footer_status(request):
    """Данные для футера-статус-строки: оперативные счётчики для всех,
    технический уголок (сборка, дайджест, Celery) — только для staff."""
    user = request.user
    if not user.is_authenticated:
        return {}

    data = cache.get(FOOTER_CACHE_KEY)
    if data is None:
        data = _collect_status()
        cache.set(FOOTER_CACHE_KEY, data, FOOTER_CACHE_TTL)

    is_staff = user.is_staff or user.is_superuser
    payments_url = reverse("policies:payments")
    status = {
        "overdue_count": data["overdue_count"],
        "week_count": data["week_count"],
        "overdue_url": f"{payments_url}?status=overdue",
        "week_url": f"{payments_url}?status=week",
        "show_mail": is_staff and user.has_perm("communications.view_outboundemail"),
        "show_tech": is_staff,
        "server_time_iso": timezone.now().isoformat(),
    }

    if status["show_mail"]:
        changelist = reverse("admin:communications_outboundemail_changelist")
        status["mail_queued"] = data["mail_queued"]
        status["mail_failed"] = data["mail_failed"]
        status["mail_queued_url"] = f"{changelist}?status__exact=queued"
        status["mail_failed_url"] = f"{changelist}?status__exact=failed"

    if is_staff:
        status["build_label"] = BUILD_LABEL
        status["env_label"] = "dev" if settings.DEBUG else "prod"
        status["digest"] = data["digest"]
        status["beat_label"] = data["beat_label"]
        status["beat_stale"] = data["beat_stale"]

    return {"footer_status": status}
