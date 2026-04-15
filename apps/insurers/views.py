from datetime import date

from django.views.generic import ListView, DetailView
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import JsonResponse
from django.views.decorators.http import require_GET
from django.contrib.admin.views.decorators import staff_member_required
from django.db.models import Avg, Count, Q
from .models import (
    Insurer,
    CommissionRate,
    Branch,
    InsuranceType,
    LeasingManager,
)
from .services import InsurerStatisticsService


class InsurerListView(LoginRequiredMixin, ListView):
    model = Insurer
    template_name = "insurers/insurer_list.html"
    context_object_name = "insurers"
    paginate_by = 50

    def get_queryset(self):
        queryset = (
            super().get_queryset().prefetch_related("commission_rates__insurance_type")
        )
        search = self.request.GET.get("search")
        if search:
            queryset = queryset.filter(insurer_name__icontains=search)
        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        # Add statistics for each insurer
        insurers_with_stats = []
        for insurer in context["insurers"]:
            insurer.stats = self._calculate_insurer_statistics(insurer)
            insurers_with_stats.append(insurer)

        context["insurers"] = insurers_with_stats
        return context

    def _calculate_insurer_statistics(self, insurer):
        """Calculate statistics for a single insurer"""
        all_policies = insurer.policies.all()
        active_policies = all_policies.filter(policy_active=True)

        # Total counts
        total_policies = all_policies.count()
        active_count = active_policies.count()

        # Distribution by insurance types (only active policies)
        type_stats = (
            active_policies.values("insurance_type__name")
            .annotate(count=Count("id"))
            .order_by("-count")
        )

        # Calculate percentages for insurance types
        type_distribution = []

        # Фиксированные цвета для видов страхования
        insurance_type_colors = {
            "КАСКО": "#3498db",  # синий (оставляем как есть)
            "Спецтехника": "#ff8c00",  # оранжевый
            "Имущество": "#dc3545",  # красный
            "Грузы": "#228b22",  # темно-зеленый
        }
        default_color = "#95a5a6"  # серый цвет для неизвестных видов

        for stat in type_stats:
            percentage = (stat["count"] / active_count * 100) if active_count > 0 else 0
            insurance_type_name = stat["insurance_type__name"]
            color = insurance_type_colors.get(insurance_type_name, default_color)

            type_distribution.append(
                {
                    "name": insurance_type_name,
                    "count": stat["count"],
                    "percentage": round(percentage, 1),
                    "color": color,
                }
            )

        # Broker participation (only active policies)
        broker_participation = active_policies.filter(broker_participation=True).count()
        broker_percentage = (
            (broker_participation / active_count * 100) if active_count > 0 else 0
        )

        return {
            "total_policies": total_policies,
            "active_policies": active_count,
            "type_distribution": type_distribution,
            "broker_participation": broker_participation,
            "broker_percentage": round(broker_percentage, 1),
        }


class InsurerDetailView(LoginRequiredMixin, DetailView):
    model = Insurer
    template_name = "insurers/insurer_detail.html"
    context_object_name = "insurer"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        raw_branch_id = self.request.GET.get("branch")
        raw_insurance_type_id = self.request.GET.get("insurance_type")
        stats_filters = InsurerStatisticsService.parse_filters(
            selected_branch_id=raw_branch_id,
            selected_insurance_type_id=raw_insurance_type_id,
            stats_scope=self.request.GET.get("stats_scope"),
            policy_scope=self.request.GET.get("policy_scope"),
            metric=self.request.GET.get("metric"),
            date_from=self.request.GET.get("date_from"),
            date_to=self.request.GET.get("date_to"),
        )

        policies_qs = self.object.policies.select_related(
            "client", "branch", "insurance_type"
        )
        if stats_filters.selected_branch_id:
            policies_qs = policies_qs.filter(branch_id=stats_filters.selected_branch_id)
        if stats_filters.selected_insurance_type_id:
            policies_qs = policies_qs.filter(
                insurance_type_id=stats_filters.selected_insurance_type_id
            )

        context["policies"] = policies_qs.order_by("-start_date", "-id")
        context["policies_count"] = policies_qs.count()
        overview_data = policies_qs.aggregate(
            total_policies=Count("id"),
            active_policies=Count("id", filter=Q(policy_active=True)),
            terminated_policies=Count("id", filter=Q(policy_active=False)),
            avg_premium=Avg("premium_total"),
        )
        context["insurer_overview"] = {
            "total_policies": overview_data["total_policies"],
            "active_policies": overview_data["active_policies"],
            "terminated_policies": overview_data["terminated_policies"],
            "avg_premium": overview_data["avg_premium"] or 0,
        }

        context["branches"] = (
            Branch.objects.filter(policies__insurer=self.object)
            .distinct()
            .order_by("branch_name")
        )
        context["insurance_types"] = (
            InsuranceType.objects.filter(policies__insurer=self.object)
            .distinct()
            .order_by("name")
        )

        context["selected_branch_id"] = stats_filters.selected_branch_id
        context["selected_insurance_type_id"] = stats_filters.selected_insurance_type_id
        context["stats_scope"] = stats_filters.stats_scope
        context["policy_scope"] = stats_filters.policy_scope
        context["metric"] = stats_filters.metric
        context["date_from"] = stats_filters.date_from
        context["date_to"] = stats_filters.date_to

        context["commission_rates"] = self.object.commission_rates.select_related(
            "insurance_type"
        ).order_by("insurance_type__name")

        context["statistics"] = InsurerStatisticsService(self.object).calculate(
            stats_filters
        )

        return context


class LeasingManagerListView(LoginRequiredMixin, ListView):
    model = LeasingManager
    template_name = "insurers/manager_list.html"
    context_object_name = "managers"
    paginate_by = 50

    def get_queryset(self):
        queryset = (
            super()
            .get_queryset()
            .annotate(
                total_policies=Count("policies"),
                active_policies=Count(
                    "policies", filter=Q(policies__policy_active=True)
                ),
            )
        )

        search = self.request.GET.get("search")
        if search:
            queryset = queryset.filter(
                Q(name__icontains=search)
                | Q(full_name__icontains=search)
                | Q(phone__icontains=search)
                | Q(email__icontains=search)
            )

        return queryset.order_by("name")


class LeasingManagerDetailView(LoginRequiredMixin, DetailView):
    model = LeasingManager
    template_name = "insurers/manager_detail.html"
    context_object_name = "manager"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        policies_qs = self.object.policies.select_related(
            "client", "insurer", "branch", "insurance_type"
        ).order_by("-start_date", "-id")
        context["policies"] = policies_qs
        context["policies_count"] = policies_qs.count()

        overview_data = policies_qs.aggregate(
            total_policies=Count("id"),
            active_policies=Count("id", filter=Q(policy_active=True)),
            terminated_policies=Count("id", filter=Q(policy_active=False)),
        )
        nearest_end_date = (
            policies_qs.filter(policy_active=True, end_date__gte=date.today())
            .order_by("end_date")
            .values_list("end_date", flat=True)
            .first()
        )
        if nearest_end_date is None:
            nearest_end_date = (
                policies_qs.filter(policy_active=True)
                .order_by("end_date")
                .values_list("end_date", flat=True)
                .first()
            )

        context["manager_overview"] = {
            "total_policies": overview_data["total_policies"],
            "active_policies": overview_data["active_policies"],
            "terminated_policies": overview_data["terminated_policies"],
            "nearest_end_date": nearest_end_date,
        }

        return context


@staff_member_required
@require_GET
def get_commission_rate(request):
    """
    API endpoint to get commission rate for a given insurer and insurance type.

    Query parameters:
    - insurer_id: ID of the insurer
    - insurance_type_id: ID of the insurance type

    Returns:
    - JSON with commission_rate_id and kv_percent if found
    - JSON with error message if not found
    """
    insurer_id = request.GET.get("insurer_id")
    insurance_type_id = request.GET.get("insurance_type_id")

    if not insurer_id or not insurance_type_id:
        return JsonResponse(
            {
                "success": False,
                "error": "Необходимо указать insurer_id и insurance_type_id",
            },
            status=400,
        )

    try:
        commission_rate = CommissionRate.objects.get(
            insurer_id=insurer_id, insurance_type_id=insurance_type_id
        )

        return JsonResponse(
            {
                "success": True,
                "commission_rate_id": commission_rate.id,
                "kv_percent": str(commission_rate.kv_percent),
                "display_name": str(commission_rate),
            }
        )

    except CommissionRate.DoesNotExist:
        return JsonResponse(
            {
                "success": False,
                "error": "Ставка комиссии не найдена для данной комбинации страховщика и вида страхования",
            }
        )

    except Exception as e:
        return JsonResponse(
            {"success": False, "error": f"Ошибка: {str(e)}"}, status=500
        )
