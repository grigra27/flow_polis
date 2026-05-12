from datetime import date

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.utils import timezone
from django.views import View
from django.views.generic import DetailView, TemplateView

from apps.communications.models import OutboundEmail
from apps.communications.services import (
    CommunicationsError,
    CommunicationsConfigurationError,
    create_outbound_email,
    queue_outbound_email,
)

from .forms import AllianceEmailForm, ManualRecipientEmailForm
from .mail_builders import (
    build_alliance_forward_email_payload,
    build_insurer_request_email_payload,
)
from .models import BillingTask
from .services import (
    BRANCH_GROUP_1,
    BRANCH_GROUP_2,
    BRANCH_GROUP_CHOICES,
    build_period_options,
    get_filter_options,
    get_branch_ids_for_group,
    get_tasks_queryset,
    parse_int_list_query_param,
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


class BillingPeriodListView(LoginRequiredMixin, TemplateView):
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

        filter_options = get_filter_options()
        branches = list(filter_options["branches"])
        group1_branch_ids = get_branch_ids_for_group(branches, BRANCH_GROUP_1)
        group2_branch_ids = get_branch_ids_for_group(branches, BRANCH_GROUP_2)
        branch_name_map = {branch.id: branch.branch_name for branch in branches}
        group1_branch_names = [
            branch_name_map[branch_id]
            for branch_id in group1_branch_ids
            if branch_id in branch_name_map
        ]
        group2_branch_names = [
            branch_name_map[branch_id]
            for branch_id in group2_branch_ids
            if branch_id in branch_name_map
        ]
        requested_branch_ids = parse_int_list_query_param(self.request.GET, "branch")
        requested_branch_group = self.request.GET.get("branch_group", "")
        branch_group_ids = []
        if requested_branch_group == BRANCH_GROUP_1:
            branch_group_ids = group1_branch_ids
        elif requested_branch_group == BRANCH_GROUP_2:
            branch_group_ids = group2_branch_ids

        if requested_branch_ids:
            selected_branch_ids = requested_branch_ids
            active_branch_group = ""
            branch_ids_filter = selected_branch_ids
        elif requested_branch_group in BRANCH_GROUP_CHOICES:
            selected_branch_ids = branch_group_ids
            active_branch_group = requested_branch_group
            branch_ids_filter = selected_branch_ids
        else:
            selected_branch_ids = []
            active_branch_group = ""
            branch_ids_filter = None

        tasks_queryset = get_tasks_queryset(
            selected_period,
            self.request.GET,
            branch_ids_filter=branch_ids_filter,
        )
        paginator = Paginator(tasks_queryset, self.paginate_by)
        page_obj = paginator.get_page(self.request.GET.get("page"))

        selected_branches = [str(branch_id) for branch_id in selected_branch_ids]

        period_params = self.request.GET.copy()
        period_params.pop("period", None)
        period_params.pop("page", None)
        period_query = period_params.urlencode()
        period_query_suffix = f"&{period_query}" if period_query else ""

        def _group_filter_url(group_code):
            params = self.request.GET.copy()
            params.pop("page", None)
            params.pop("branch", None)
            params.pop("branch_group", None)
            params["period"] = selected_period.code
            params["branch_group"] = group_code
            return f"{reverse('policies:scheduled_payments')}?{params.urlencode()}"

        group1_url = _group_filter_url(BRANCH_GROUP_1)
        group2_url = _group_filter_url(BRANCH_GROUP_2)
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
                "selected_branches": selected_branches,
                "active_branch_group": active_branch_group,
                "branch_group_1": BRANCH_GROUP_1,
                "branch_group_2": BRANCH_GROUP_2,
                "group1_url": group1_url,
                "group2_url": group2_url,
                "group1_branch_names": group1_branch_names,
                "group2_branch_names": group2_branch_names,
                "period_query_suffix": period_query_suffix,
                "search_query": self.request.GET.get("q", ""),
                "insurers": filter_options["insurers"],
                "branches": branches,
                "total_filtered": paginator.count,
            }
        )
        return context


class BillingProlongationPlaceholderView(LoginRequiredMixin, TemplateView):
    template_name = "billing/prolongation_placeholder.html"


class BillingTaskDetailView(LoginRequiredMixin, DetailView):
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
            .filter(payment_schedule__policy__broker_participation=True)
            .prefetch_related("events__user")
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        today = timezone.localdate()
        task = self.object
        outbound_emails = (
            OutboundEmail.objects.for_object(task)
            .select_related("created_by", "sent_by")
            .prefetch_related("recipients", "attachments", "delivery_attempts")
        )
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
                "outbound_emails": outbound_emails,
                "manual_recipient_form": ManualRecipientEmailForm(),
                "alliance_email_form": AllianceEmailForm(),
            }
        )
        return context


class BillingTaskUpdateView(LoginRequiredMixin, View):
    def post(self, request, pk):
        task = get_object_or_404(
            BillingTask,
            pk=pk,
            payment_schedule__policy__broker_participation=True,
        )
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


class BillingTaskBulkUpdateView(LoginRequiredMixin, View):
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
        for task in BillingTask.objects.filter(
            id__in=task_ids,
            payment_schedule__policy__broker_participation=True,
        ):
            previous_updated_at = task.updated_at
            update_task(task, request.user, new_status=new_status)
            if task.updated_at != previous_updated_at:
                updated_count += 1

        messages.success(request, f"Обновлено задач: {updated_count}")
        return redirect(next_url)


class SuperuserEmailSendMixin:
    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_superuser:
            raise PermissionDenied
        return super().dispatch(request, *args, **kwargs)

    def get_task(self, pk):
        return get_object_or_404(
            BillingTask.objects.select_related(
                "period",
                "responsible",
                "payment_schedule",
                "payment_schedule__policy",
                "payment_schedule__policy__client",
                "payment_schedule__policy__policyholder",
                "payment_schedule__policy__insurer",
                "payment_schedule__policy__branch",
                "payment_schedule__policy__leasing_manager",
            ),
            pk=pk,
            payment_schedule__policy__broker_participation=True,
        )

    def get_next_url(self, request, task):
        return request.POST.get("next") or task.get_absolute_url()

    def create_and_queue_email(self, request, payload, attachments=None):
        if not settings.COMMUNICATIONS_EMAIL_ENABLED:
            raise CommunicationsConfigurationError("Отправка писем временно отключена")
        outbound_email = create_outbound_email(
            **payload,
            created_by=request.user,
            attachments=attachments,
        )
        return queue_outbound_email(outbound_email, user=request.user)


class BillingTaskSendInsurerEmailView(
    LoginRequiredMixin, SuperuserEmailSendMixin, View
):
    def post(self, request, pk):
        task = self.get_task(pk)
        next_url = self.get_next_url(request, task)
        form = ManualRecipientEmailForm(request.POST)
        if not form.is_valid():
            messages.warning(request, "Укажите корректный email получателя")
            return redirect(next_url)

        try:
            payload = build_insurer_request_email_payload(
                task, form.cleaned_data["recipient_email"]
            )
            self.create_and_queue_email(request, payload)
        except (CommunicationsError, ValidationError) as exc:
            messages.error(request, str(exc))
            return redirect(next_url)

        messages.success(request, "Письмо в СК поставлено в очередь отправки")
        return redirect(next_url)


class BillingTaskSendAllianceEmailView(
    LoginRequiredMixin, SuperuserEmailSendMixin, View
):
    def post(self, request, pk):
        task = self.get_task(pk)
        next_url = self.get_next_url(request, task)
        form = AllianceEmailForm(request.POST, request.FILES)
        if not form.is_valid():
            error_text = "Проверьте email получателя и файл счета"
            if form.errors:
                first_errors = next(iter(form.errors.values()))
                if first_errors:
                    error_text = first_errors[0]
            messages.warning(request, error_text)
            return redirect(next_url)

        try:
            payload = build_alliance_forward_email_payload(
                task, form.cleaned_data["recipient_email"]
            )
            self.create_and_queue_email(
                request,
                payload,
                attachments=[form.cleaned_data["invoice_file"]],
            )
        except (CommunicationsError, ValidationError) as exc:
            messages.error(request, str(exc))
            return redirect(next_url)

        messages.success(request, "Письмо в Альянс поставлено в очередь отправки")
        return redirect(next_url)
