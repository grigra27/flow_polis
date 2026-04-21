from django.views.generic import ListView, DetailView
from django.contrib.auth.mixins import LoginRequiredMixin
from django_filters.views import FilterView
from .models import Policy, PaymentSchedule
from .filters import PolicyFilter


class PolicyListView(LoginRequiredMixin, FilterView):
    model = Policy
    template_name = "policies/policy_list.html"
    context_object_name = "policies"
    filterset_class = PolicyFilter
    paginate_by = 30

    def get_queryset(self):
        queryset = (
            super()
            .get_queryset()
            .select_related("client", "insurer", "branch", "insurance_type")
            .prefetch_related("payment_schedule", "info_tags__tag")
        )

        # Filter by branch if specified
        branch_id = self.request.GET.get("branch")
        if branch_id:
            queryset = queryset.filter(branch_id=branch_id)

        return queryset

    def _build_active_filters(self):
        from apps.insurers.models import Branch, Insurer, InsuranceType, InfoTag

        active_filters = []
        query_params = self.request.GET

        def add_filter(param, label, value):
            if value not in (None, ""):
                active_filters.append({"param": param, "label": label, "value": value})

        # Текстовые фильтры
        add_filter("policy_number", "Номер полиса", query_params.get("policy_number"))
        add_filter("dfa_number", "Номер ДФА", query_params.get("dfa_number"))
        add_filter(
            "client__client_name", "Клиент", query_params.get("client__client_name")
        )

        # Справочники
        insurer_id = query_params.get("insurer")
        if insurer_id:
            insurer_name = (
                Insurer.objects.filter(pk=insurer_id)
                .values_list("insurer_name", flat=True)
                .first()
            )
            add_filter("insurer", "Страховщик", insurer_name or insurer_id)

        branch_id = query_params.get("branch")
        if branch_id:
            branch_name = (
                Branch.objects.filter(pk=branch_id)
                .values_list("branch_name", flat=True)
                .first()
            )
            add_filter("branch", "Филиал", branch_name or branch_id)

        insurance_type_id = query_params.get("insurance_type")
        if insurance_type_id:
            insurance_type_name = (
                InsuranceType.objects.filter(pk=insurance_type_id)
                .values_list("name", flat=True)
                .first()
            )
            add_filter(
                "insurance_type",
                "Вид страхования",
                insurance_type_name or insurance_type_id,
            )

        info1_tag_id = query_params.get("info1_tag")
        if info1_tag_id:
            info1_tag_name = (
                InfoTag.objects.filter(pk=info1_tag_id)
                .values_list("name", flat=True)
                .first()
            )
            add_filter("info1_tag", "Инфо 1", info1_tag_name or info1_tag_id)

        # Булевые фильтры
        bool_mapping = {
            "true": "Да",
            "false": "Нет",
            "1": "Да",
            "0": "Нет",
        }
        bool_filters = [
            ("policy_active", "Полис активен"),
            ("dfa_active", "ДФА активен"),
            ("policy_uploaded", "Полис подгружен"),
            ("broker_participation", "Участие брокера"),
        ]
        for param, label in bool_filters:
            raw_value = query_params.get(param)
            if raw_value is None:
                continue
            bool_value = bool_mapping.get(str(raw_value).lower())
            if bool_value is not None:
                add_filter(param, label, bool_value)

        return active_filters

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        from apps.insurers.models import Branch

        context["branches"] = Branch.objects.all()
        context["selected_branch"] = self.request.GET.get("branch")
        context["active_filters"] = self._build_active_filters()
        context["policies_count"] = self.object_list.count()
        return context


class PolicyDetailView(LoginRequiredMixin, DetailView):
    model = Policy
    template_name = "policies/policy_detail.html"
    context_object_name = "policy"

    def get_queryset(self):
        return (
            super()
            .get_queryset()
            .select_related(
                "client",
                "policyholder",
                "insurer",
                "branch",
                "insurance_type",
                "leasing_manager",
            )
            .prefetch_related("payment_schedule__commission_rate", "info_tags__tag")
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        policy = self.object
        context["info1_tags"] = policy.info_tags.filter(info_field=1).select_related(
            "tag"
        )
        context["info2_tags"] = policy.info_tags.filter(info_field=2).select_related(
            "tag"
        )

        # Get commission rate for this policy's insurer and insurance type
        from apps.insurers.models import CommissionRate

        try:
            commission_rate = CommissionRate.objects.get(
                insurer=policy.insurer, insurance_type=policy.insurance_type
            )
            context["commission_rate"] = commission_rate
        except CommissionRate.DoesNotExist:
            context["commission_rate"] = None

        # Get rates by insurance year
        context["rates_by_year"] = policy.get_rates_by_year()

        return context


class PaymentScheduleListView(LoginRequiredMixin, ListView):
    model = PaymentSchedule
    template_name = "policies/payment_list.html"
    context_object_name = "payments"
    paginate_by = 30

    def get_queryset(self):
        queryset = (
            super()
            .get_queryset()
            .select_related(
                "policy",
                "policy__client",
                "policy__insurer",
                "policy__branch",
                "commission_rate",
            )
        )

        # Filter by branch if specified
        branch_id = self.request.GET.get("branch")
        if branch_id:
            queryset = queryset.filter(policy__branch_id=branch_id)

        # Filter by insurer if specified
        insurer_id = self.request.GET.get("insurer")
        if insurer_id:
            queryset = queryset.filter(policy__insurer_id=insurer_id)

        # Filter by date range
        date_from = self.request.GET.get("date_from")
        date_to = self.request.GET.get("date_to")

        if date_from:
            queryset = queryset.filter(due_date__gte=date_from)
        if date_to:
            queryset = queryset.filter(due_date__lte=date_to)

        # Filter by status (applies together with branch/insurer/date filters)
        # If date filter is set without explicit status, show all statuses in this date range.
        status = self.request.GET.get("status")
        if not status:
            status = "all" if (date_from or date_to) else "upcoming"
        if status == "all":
            # Все платежи: без фильтрации по статусу
            pass
        elif status == "approved":
            # Согласованные со СК: платежи с указанной датой согласования СК
            queryset = queryset.filter(insurer_date__isnull=False)
        elif status == "paid":
            # Оплаченные: платежи с указанной датой оплаты (дата платежа <= сегодня)
            # но БЕЗ даты согласования СК (иначе они попадают в "Акт согласован СК")
            from django.utils import timezone

            queryset = queryset.filter(
                paid_date__isnull=False,
                due_date__lte=timezone.now().date(),
                insurer_date__isnull=True,
            )
        elif status == "cancelled":
            # Отмененные: неоплаченные платежи по неактивным полисам
            queryset = queryset.filter(
                paid_date__isnull=True,
                policy__policy_active=False,
            )
        elif status == "overdue":
            # Не оплаченные: неоплаченные платежи с датой ранее сегодня (только для активных полисов)
            from django.utils import timezone

            queryset = queryset.filter(
                due_date__lt=timezone.now().date(),
                paid_date__isnull=True,
                policy__policy_active=True,
            )
        elif status == "upcoming":
            # Предстоит в ближайшие 30 дней: неоплаченные платежи от сегодня до +30 дней включительно
            # только для активных полисов
            from django.utils import timezone
            from datetime import timedelta

            today = timezone.now().date()
            next_month = today + timedelta(days=30)
            queryset = queryset.filter(
                due_date__range=[today, next_month],
                paid_date__isnull=True,
                policy__policy_active=True,
            )
        elif status == "future":
            # Будущие: неоплаченные платежи более чем через 30 дней
            # только для активных полисов
            from django.utils import timezone
            from datetime import timedelta

            today = timezone.now().date()
            future_date = today + timedelta(days=31)
            queryset = queryset.filter(
                due_date__gte=future_date,
                paid_date__isnull=True,
                policy__policy_active=True,
            )

        # Сортировка:
        # - для согласованных: по дате согласования (от новых к старым)
        # - для оплаченных: по дате оплаты (от новых к старым)
        # - для не оплаченных: по дате платежа (от старых к новым)
        # - для предстоящих: по дате платежа (от ближайших к дальним)
        # - для остальных: по дате платежа (от ближайших к дальним)
        if status == "approved":
            return queryset.order_by("-insurer_date")
        elif status == "paid":
            return queryset.order_by("-paid_date")
        elif status == "overdue":
            return queryset.order_by("due_date")
        elif status == "upcoming":
            return queryset.order_by("due_date")
        else:
            return queryset.order_by("due_date")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        from apps.insurers.models import Branch, Insurer

        context["branches"] = Branch.objects.all()
        context["insurers"] = Insurer.objects.all()
        context["selected_branch"] = self.request.GET.get("branch")
        context["selected_insurer"] = self.request.GET.get("insurer")
        selected_status = self.request.GET.get("status")
        if not selected_status:
            selected_status = (
                "all"
                if (
                    self.request.GET.get("date_from") or self.request.GET.get("date_to")
                )
                else "upcoming"
            )
        context["selected_status"] = selected_status
        context["can_edit"] = self.request.user.is_staff
        return context
