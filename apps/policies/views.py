from urllib.parse import urlencode, urlsplit

from django.conf import settings
from django.urls import reverse
from django.utils import timezone
from django.views.generic import ListView, DetailView
from django.contrib.auth.mixins import LoginRequiredMixin
from django_filters.views import FilterView
from django.db.models import Q
from .models import FlowPolicySource, Policy, PaymentSchedule, in_force_q
from .flow_views import source_url
from .filters import PolicyFilter
from .card_edits import can_edit_card_field
from .navigation import JournalPaginator, card_params, journal_label


class PolicyListView(LoginRequiredMixin, FilterView):
    model = Policy
    template_name = "policies/policy_list.html"
    context_object_name = "policies"
    filterset_class = PolicyFilter
    paginate_by = 30
    paginator_class = JournalPaginator

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

        # Universal text search across policy number / DFA number / client / VIN.
        search_query = (self.request.GET.get("search") or "").strip()
        if search_query:
            queryset = queryset.filter(
                Q(policy_number__icontains=search_query)
                | Q(dfa_number__icontains=search_query)
                | Q(client__client_name__icontains=search_query)
                | Q(vin_number__icontains=search_query)
            )

        return queryset

    def _build_active_filters(self):
        from apps.insurers.models import Branch, Insurer, InsuranceType

        active_filters = []
        query_params = self.request.GET

        def add_filter(param, label, value):
            if value not in (None, ""):
                active_filters.append({"param": param, "label": label, "value": value})

        # Универсальный поиск или legacy-текстовые фильтры
        search_query = query_params.get("search")
        if search_query:
            add_filter("search", "Поиск", search_query)
        else:
            add_filter(
                "policy_number", "Номер полиса", query_params.get("policy_number")
            )
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

        osago_labels = {"exclude": "Без ОСАГО", "only": "Только ОСАГО"}
        add_filter("osago", "ОСАГО", osago_labels.get(query_params.get("osago")))

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


class PoliciesBySummaryView(LoginRequiredMixin, DetailView):
    model = FlowPolicySource
    queryset = FlowPolicySource.objects.only("summary_id", "total", "mode")
    pk_url_kwarg = "summary_id"
    context_object_name = "source"
    template_name = "policies/policies_by_summary.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        source = self.object
        only_in_force = self.request.GET.get("in_force") == "1"
        links = list(
            source.links.select_related("policy__client")
            .annotate(in_force=in_force_q(timezone.localdate(), prefix="policy__"))
            .only(
                "slot",
                "source_id",
                "policy__policy_number",
                "policy__dfa_number",
                "policy__property_description",
                "policy__vin_number",
                "policy__client__client_name",
            )
            .order_by("slot", "pk")
        )
        clients = {link.policy.client.client_name for link in links}
        in_force_links = [link for link in links if link.in_force]
        context.update(
            links=in_force_links if only_in_force else links,
            only_in_force=only_in_force,
            total_links=len(links),
            in_force_count=len(in_force_links),
            client_name=next(iter(clients)) if len(clients) == 1 else None,
            source_url=source_url(source.pk),
        )
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
        links = list(
            policy.flow_links.select_related("source").order_by("source_id", "slot")
        )
        context["flow_links"] = links
        context["flow_zs_host"] = urlsplit(settings.FLOW_ZS_BASE_URL).hostname
        navigation = card_params(self.request.GET)
        origin = navigation.get("from_summary")
        for link in links:
            if str(link.source_id) == origin:
                context["group_summary_id"] = link.source_id
                context["group_url"] = reverse(
                    "policies:by-summary",
                    args=[link.source_id],
                    query={"in_force": "1"}
                    if self.request.GET.get("in_force") == "1"
                    else None,
                )
                break
        if origin and "group_url" not in context:
            navigation = {}
        journal = navigation.get("journal", reverse("policies:list"))
        context["back_url"] = context.get("group_url", journal)
        context["back_label"] = (
            f"К полисам по своду № {origin}"
            if "group_url" in context
            else journal_label(journal)
        )
        context["card_query"] = urlencode(navigation)
        context["open_payment"] = self.request.GET.get("payment", "")
        context["can_edit_payment"] = can_edit_card_field(
            self.request.user, PaymentSchedule
        )
        context["card_today"] = timezone.localdate().isoformat()
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
    paginator_class = JournalPaginator

    def get_queryset(self):
        queryset = (
            super()
            .get_queryset()
            .select_related(
                "policy",
                "policy__client",
                "policy__insurer",
                "policy__branch",
                "policy__insurance_type",
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

        # Filter by year/installment pair if specified
        year_number = self.request.GET.get("year_number")
        installment_number = self.request.GET.get("installment_number")
        if year_number:
            try:
                queryset = queryset.filter(year_number=int(year_number))
            except (TypeError, ValueError):
                pass
        if installment_number:
            try:
                queryset = queryset.filter(installment_number=int(installment_number))
            except (TypeError, ValueError):
                pass

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
            # Оплаченные: платежи с указанной датой оплаты
            # но БЕЗ даты согласования СК (иначе они попадают в "Акт согласован СК")
            # Включаем и предоплаты (когда due_date в будущем).
            queryset = queryset.filter(
                paid_date__isnull=False,
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
        context["selected_year_number"] = self.request.GET.get("year_number", "")
        context["selected_installment_number"] = self.request.GET.get(
            "installment_number", ""
        )
        context["year_numbers"] = (
            PaymentSchedule.objects.order_by("year_number")
            .values_list("year_number", flat=True)
            .distinct()
        )
        context["installment_numbers"] = (
            PaymentSchedule.objects.order_by("installment_number")
            .values_list("installment_number", flat=True)
            .distinct()
        )
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
