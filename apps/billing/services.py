from dataclasses import dataclass
from datetime import date, timedelta

from django.db import transaction
from django.db.models import Count, Q
from django.db.models.functions import ExtractMonth, ExtractYear
from django.utils import timezone

from apps.insurers.models import Branch, Insurer
from apps.policies.models import PaymentSchedule

from .models import (
    BillingPeriod,
    BillingTask,
    BillingTaskEvent,
)


@dataclass
class PeriodOption:
    period: BillingPeriod
    total: int
    to_request: int
    requested: int
    sent_to_leasing: int
    selected: bool = False


VISIBLE_PAST_MONTHS = 2
VISIBLE_FUTURE_MONTHS = 6


def add_months(value, months):
    month_index = value.month - 1 + months
    year = value.year + month_index // 12
    month = month_index % 12 + 1
    return date(year, month, 1)


def invoice_deadline_for_due_date(due_date):
    return due_date - timedelta(weeks=2)


def parse_period_code(code):
    if not code:
        return None
    try:
        year_str, month_str = code.split("-", 1)
        year = int(year_str)
        month = int(month_str)
    except (TypeError, ValueError):
        return None
    if month < 1 or month > 12:
        return None
    return year, month


def visible_period_start(today=None):
    today = today or timezone.localdate()
    current_month = date(today.year, today.month, 1)
    return add_months(current_month, -VISIBLE_PAST_MONTHS)


def visible_period_months(today=None):
    today = today or timezone.localdate()
    current_month = date(today.year, today.month, 1)
    return [
        add_months(current_month, offset)
        for offset in range(-VISIBLE_PAST_MONTHS, VISIBLE_FUTURE_MONTHS + 1)
    ]


def preload_periods(today=None):
    """
    Материализует только сами месячные периоды для навигации.
    Задачи создаются отдельно и только для выбранного периода.
    """
    months = visible_period_months(today)
    period_keys = [(month.year, month.month) for month in months]
    years = {year for year, _ in period_keys}

    existing_periods = BillingPeriod.objects.filter(year__in=years)
    existing_keys = {(period.year, period.month) for period in existing_periods}
    missing_periods = [
        BillingPeriod(year=year, month=month)
        for year, month in period_keys
        if (year, month) not in existing_keys
    ]
    if missing_periods:
        BillingPeriod.objects.bulk_create(missing_periods, ignore_conflicts=True)

    period_map = {
        (period.year, period.month): period
        for period in BillingPeriod.objects.filter(year__in=years)
    }
    return [period_map[key] for key in period_keys]


def resolve_selected_period(periods, code=None):
    parsed = parse_period_code(code)
    if parsed:
        year, month = parsed
        for period in periods:
            if period.year == year and period.month == month:
                return period
        period, _ = BillingPeriod.objects.get_or_create(year=year, month=month)
        return period

    today = timezone.localdate()
    current_code = f"{today.year:04d}-{today.month:02d}"
    for period in periods:
        if period.code == current_code:
            return period

    if periods:
        return periods[0]
    period, _ = BillingPeriod.objects.get_or_create(year=today.year, month=today.month)
    return period


@transaction.atomic
def sync_period(year, month):
    period, _ = BillingPeriod.objects.get_or_create(year=year, month=month)

    payments = list(
        PaymentSchedule.objects.filter(
            due_date__gte=period.starts_on,
            due_date__lte=period.ends_on,
            paid_date__isnull=True,
            policy__policy_active=True,
        ).values("id", "due_date")
    )
    if not payments:
        return period

    payment_ids = [payment["id"] for payment in payments]
    existing_tasks = {
        task.payment_schedule_id: task
        for task in BillingTask.objects.filter(
            payment_schedule_id__in=payment_ids
        ).only(
            "id",
            "period_id",
            "payment_schedule_id",
            "invoice_request_deadline",
            "status",
            "updated_at",
        )
    }

    tasks_to_create = []
    created_payment_ids = []
    tasks_to_update = []
    now = timezone.now()

    for payment in payments:
        deadline = invoice_deadline_for_due_date(payment["due_date"])
        task = existing_tasks.get(payment["id"])

        if not task:
            tasks_to_create.append(
                BillingTask(
                    period=period,
                    payment_schedule_id=payment["id"],
                    invoice_request_deadline=deadline,
                )
            )
            created_payment_ids.append(payment["id"])
            continue

        needs_update = False
        if task.period_id != period.id:
            task.period = period
            needs_update = True
        if task.invoice_request_deadline != deadline:
            task.invoice_request_deadline = deadline
            needs_update = True
        if needs_update:
            task.updated_at = now
            tasks_to_update.append(task)

    if tasks_to_create:
        BillingTask.objects.bulk_create(
            tasks_to_create, batch_size=500, ignore_conflicts=True
        )
        created_tasks = list(
            BillingTask.objects.filter(
                payment_schedule_id__in=created_payment_ids
            ).only("id", "status")
        )
        task_ids = [task.id for task in created_tasks]
        existing_event_task_ids = set(
            BillingTaskEvent.objects.filter(
                task_id__in=task_ids,
                event_type=BillingTaskEvent.EVENT_CREATED,
            ).values_list("task_id", flat=True)
        )
        BillingTaskEvent.objects.bulk_create(
            [
                BillingTaskEvent(
                    task=task,
                    event_type=BillingTaskEvent.EVENT_CREATED,
                    new_status=task.status,
                    comment="Задача создана автоматически из графика платежей.",
                )
                for task in created_tasks
                if task.id not in existing_event_task_ids
            ],
            batch_size=500,
        )

    if tasks_to_update:
        BillingTask.objects.bulk_update(
            tasks_to_update,
            ["period", "invoice_request_deadline", "updated_at"],
            batch_size=500,
        )

    return period


def build_period_options(periods, selected_period):
    period_keys = {(period.year, period.month) for period in periods}
    counts = (
        BillingTask.objects.filter(period__in=periods)
        .values("period_id", "status")
        .annotate(total=Count("id"))
    )
    count_map = {}
    for item in counts:
        count_map.setdefault(item["period_id"], {})[item["status"]] = item["total"]

    if periods:
        min_start = min(period.starts_on for period in periods)
        max_end = max(period.ends_on for period in periods)
        unsynced_counts = (
            PaymentSchedule.objects.filter(
                due_date__gte=min_start,
                due_date__lte=max_end,
                paid_date__isnull=True,
                policy__policy_active=True,
                billing_task__isnull=True,
            )
            .annotate(
                period_year=ExtractYear("due_date"),
                period_month=ExtractMonth("due_date"),
            )
            .values("period_year", "period_month")
            .annotate(total=Count("id"))
        )
        unsynced_count_map = {
            (item["period_year"], item["period_month"]): item["total"]
            for item in unsynced_counts
            if (item["period_year"], item["period_month"]) in period_keys
        }
    else:
        unsynced_count_map = {}

    options = []
    for period in periods:
        period_counts = count_map.get(period.id, {})
        unsynced_count = unsynced_count_map.get((period.year, period.month), 0)
        to_request = (
            period_counts.get(BillingTask.STATUS_TO_REQUEST, 0) + unsynced_count
        )
        requested = period_counts.get(BillingTask.STATUS_REQUESTED, 0)
        sent_to_leasing = period_counts.get(BillingTask.STATUS_SENT_TO_LEASING, 0)
        options.append(
            PeriodOption(
                period=period,
                total=to_request + requested + sent_to_leasing,
                to_request=to_request,
                requested=requested,
                sent_to_leasing=sent_to_leasing,
                selected=period.id == selected_period.id,
            )
        )
    return options


def get_tasks_queryset(period, request_get):
    tasks = BillingTask.objects.filter(period=period).select_related(
        "period",
        "responsible",
        "payment_schedule",
        "payment_schedule__policy",
        "payment_schedule__policy__client",
        "payment_schedule__policy__policyholder",
        "payment_schedule__policy__insurer",
        "payment_schedule__policy__branch",
        "payment_schedule__policy__leasing_manager",
    )

    selected_status = request_get.get("status")
    if selected_status and selected_status != "all":
        tasks = tasks.filter(status=selected_status)

    insurer_id = request_get.get("insurer")
    if insurer_id:
        tasks = tasks.filter(payment_schedule__policy__insurer_id=insurer_id)

    branch_id = request_get.get("branch")
    if branch_id:
        tasks = tasks.filter(payment_schedule__policy__branch_id=branch_id)

    search = request_get.get("q", "").strip()
    if search:
        tasks = tasks.filter(
            Q(payment_schedule__policy__policy_number__icontains=search)
            | Q(payment_schedule__policy__dfa_number__icontains=search)
            | Q(payment_schedule__policy__client__client_name__icontains=search)
            | Q(payment_schedule__policy__policyholder__client_name__icontains=search)
            | Q(payment_schedule__policy__property_description__icontains=search)
            | Q(payment_schedule__policy__insurer__insurer_name__icontains=search)
        )

    return tasks.order_by(
        "invoice_request_deadline",
        "payment_schedule__due_date",
        "payment_schedule__policy__insurer__insurer_name",
        "payment_schedule__policy__policy_number",
    )


def update_task(task, user, new_status=None, comment=None):
    valid_statuses = {status for status, _ in BillingTask.STATUS_CHOICES}
    old_status = task.status
    changed_fields = []
    events = []

    if new_status and new_status in valid_statuses and new_status != task.status:
        task.status = new_status
        changed_fields.append("status")

        if not task.responsible_id:
            task.responsible = user
            changed_fields.append("responsible")

        now = timezone.now()
        if new_status == BillingTask.STATUS_REQUESTED and not task.requested_at:
            task.requested_at = now
            changed_fields.append("requested_at")
        elif (
            new_status == BillingTask.STATUS_SENT_TO_LEASING
            and not task.sent_to_leasing_at
        ):
            if not task.requested_at:
                task.requested_at = now
                changed_fields.append("requested_at")
            task.sent_to_leasing_at = now
            changed_fields.append("sent_to_leasing_at")

        events.append(
            BillingTaskEvent(
                task=task,
                user=user,
                event_type=BillingTaskEvent.EVENT_STATUS_CHANGED,
                old_status=old_status,
                new_status=new_status,
            )
        )

    if comment is not None and comment != task.comment:
        task.comment = comment
        changed_fields.append("comment")

    if changed_fields:
        task.save(update_fields=[*set(changed_fields), "updated_at"])
        if events:
            BillingTaskEvent.objects.bulk_create(events)

    return task


def get_filter_options():
    return {
        "branches": Branch.objects.order_by("branch_name"),
        "insurers": Insurer.objects.order_by("insurer_name"),
    }
