from datetime import date

from django.contrib import messages
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.utils import timezone
from django.views import View
from django.views.generic import DetailView, TemplateView

from apps.accounts.mixins import AdminRequiredMixin

from .models import BillingTask
from .services import (
    build_period_options,
    get_filter_options,
    get_tasks_queryset,
    preload_periods,
    resolve_selected_period,
    sync_period,
    update_task,
)


_WEEKDAY_RU = ["пн", "вт", "ср", "чт", "пт", "сб", "вс"]


def _plural_days(n: int) -> str:
    n = abs(n) % 100
    if 11 <= n <= 14:
        return "дней"
    last = n % 10
    if last == 1:
        return "день"
    if 2 <= last <= 4:
        return "дня"
    return "дней"


def _date_hint(target, today: date) -> dict:
    if target is None:
        return {"dow": "", "text": "", "tone": ""}
    delta = (target - today).days
    dow = _WEEKDAY_RU[target.weekday()]
    if delta == 0:
        return {"dow": dow, "text": "сегодня", "tone": "warn"}
    if delta == 1:
        return {"dow": dow, "text": "завтра", "tone": "warn"}
    if delta == -1:
        return {"dow": dow, "text": "вчера", "tone": "danger"}
    abs_d = abs(delta)
    word = _plural_days(abs_d)
    if delta < 0:
        return {"dow": dow, "text": f"просрочен на {abs_d} {word}", "tone": "danger"}
    if delta <= 3:
        return {"dow": dow, "text": f"через {abs_d} {word}", "tone": "warn"}
    return {"dow": dow, "text": f"через {abs_d} {word}", "tone": ""}


def _payment_context(task: BillingTask) -> str:
    payment = task.payment_schedule
    payments_in_year = task.policy.payment_schedule.filter(
        year_number=payment.year_number
    ).count()
    is_yearly = payment.installment_number == 1 and payments_in_year <= 1
    head = (
        "Годовой платёж"
        if is_yearly
        else f"Рассрочка · {payment.installment_number} из {payments_in_year}"
    )
    return f"{head} · {payment.year_number}-й год"


class BillingPeriodListView(AdminRequiredMixin, TemplateView):
    template_name = "billing/period_list.html"
    paginate_by = 50

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        periods = preload_periods()
        selected_period = resolve_selected_period(
            periods, self.request.GET.get("period")
        )
        if all(period.id != selected_period.id for period in periods):
            periods = sorted(
                [*periods, selected_period],
                key=lambda period: (period.year, period.month),
            )
        # Фоновая синхронизация выполняется Celery-задачей sync_billing_periods.
        # Здесь оставлен идемпотентный fallback на случай, если beat не запущен
        # или в выбранный период попал свежесозданный платёж.
        selected_period = sync_period(selected_period.year, selected_period.month)

        tasks_queryset = get_tasks_queryset(selected_period, self.request.GET)
        paginator = Paginator(tasks_queryset, self.paginate_by)
        page_obj = paginator.get_page(self.request.GET.get("page"))

        filter_options = get_filter_options()
        context.update(
            {
                "period_options": build_period_options(periods, selected_period),
                "selected_period": selected_period,
                "tasks": page_obj.object_list,
                "page_obj": page_obj,
                "paginator": paginator,
                "status_choices": BillingTask.STATUS_CHOICES,
                "selected_status": self.request.GET.get("status", "all"),
                "selected_insurer": self.request.GET.get("insurer", ""),
                "selected_branch": self.request.GET.get("branch", ""),
                "search_query": self.request.GET.get("q", ""),
                "insurers": filter_options["insurers"],
                "branches": filter_options["branches"],
                "total_filtered": paginator.count,
            }
        )
        return context


class BillingProlongationPlaceholderView(AdminRequiredMixin, TemplateView):
    template_name = "billing/prolongation_placeholder.html"


class BillingTaskDetailView(AdminRequiredMixin, DetailView):
    model = BillingTask
    template_name = "billing/task_detail.html"
    context_object_name = "task"

    def get_queryset(self):
        return (
            super()
            .get_queryset()
            .select_related(
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
            .prefetch_related("events__user")
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        today = timezone.localdate()
        task = self.object
        context.update(
            {
                "status_choices": BillingTask.STATUS_CHOICES,
                "letter_subject": task.build_letter_subject(),
                "letter_text": task.build_letter_text(),
                "letter_html": task.build_letter_html(),
                "alliance_letter_subject": task.build_alliance_letter_subject(),
                "alliance_letter_text": task.build_alliance_letter_text(),
                "alliance_letter_html": task.build_alliance_letter_html(),
                "return_url": self.request.GET.get(
                    "next",
                    f"{reverse('policies:scheduled_payments')}?period={task.period.code}",
                ),
                "deadline_hint": _date_hint(task.invoice_request_deadline, today),
                "due_hint": _date_hint(task.payment_schedule.due_date, today),
                "payment_context": _payment_context(task),
            }
        )
        return context


class BillingTaskUpdateView(AdminRequiredMixin, View):
    def post(self, request, pk):
        task = get_object_or_404(BillingTask, pk=pk)
        next_url = request.POST.get("next") or task.get_absolute_url()
        action = request.POST.get("action")
        new_status = request.POST.get("status")
        comment = request.POST.get("comment")
        valid_statuses = {status for status, _ in BillingTask.STATUS_CHOICES}

        if action == "comment":
            update_task(task, request.user, comment=comment)
            messages.success(request, "Комментарий сохранен")
            return redirect(next_url)

        if action == "status":
            if new_status not in valid_statuses:
                messages.warning(request, "Выберите корректный статус")
                return redirect(next_url)

            update_task(task, request.user, new_status=new_status)
            messages.success(request, "Статус обновлен")
            return redirect(next_url)

        # Fallback for legacy combined form submissions.
        if new_status not in valid_statuses:
            messages.warning(request, "Выберите корректный статус")
            return redirect(next_url)

        update_task(task, request.user, new_status=new_status, comment=comment)
        messages.success(request, "Задача обновлена")
        return redirect(next_url)


class BillingTaskBulkUpdateView(AdminRequiredMixin, View):
    def post(self, request):
        task_ids = request.POST.getlist("task_ids")
        new_status = request.POST.get("status")
        next_url = request.POST.get("next") or reverse("policies:scheduled_payments")
        valid_statuses = {status for status, _ in BillingTask.STATUS_CHOICES}

        if new_status not in valid_statuses:
            messages.warning(request, "Выберите корректный статус")
            return redirect(next_url)

        if not task_ids:
            messages.warning(request, "Выберите хотя бы одну задачу")
            return redirect(next_url)

        updated_count = 0
        for task in BillingTask.objects.filter(id__in=task_ids):
            previous_updated_at = task.updated_at
            update_task(task, request.user, new_status=new_status)
            if task.updated_at != previous_updated_at:
                updated_count += 1

        messages.success(request, f"Обновлено задач: {updated_count}")
        return redirect(next_url)
