from collections import defaultdict
from datetime import date

from django.views.generic import ListView, DetailView, TemplateView
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import JsonResponse
from django.views.decorators.http import require_GET
from django.contrib.admin.views.decorators import staff_member_required
from django.db.models import Avg, Count, DecimalField, Q, Subquery
from apps.clients.models import Client as LeasingClient
from apps.policies.models import Policy, policy_premium_subquery, in_force_q
from .models import (
    Insurer,
    CommissionRate,
    Branch,
    InsuranceType,
    LeasingManager,
)
from .services import BranchStatisticsService, InsurerStatisticsService


INSURANCE_TYPE_COLORS = {
    "КАСКО": "#3498db",
    "Спецтехника": "#ff8c00",
    "Имущество": "#dc3545",
    "Грузы": "#228b22",
}
DEFAULT_INSURANCE_TYPE_COLOR = "#95a5a6"


class InsurerListView(LoginRequiredMixin, ListView):
    model = Insurer
    template_name = "insurers/insurer_list.html"
    context_object_name = "insurers"
    paginate_by = 50

    def get_queryset(self):
        in_force = in_force_q(date.today(), prefix="policies__")
        queryset = (
            super()
            .get_queryset()
            .prefetch_related("commission_rates__insurance_type")
            .annotate(
                total_policies=Count("policies", distinct=True),
                active_policies=Count(
                    "policies",
                    filter=in_force,
                    distinct=True,
                ),
                broker_participation=Count(
                    "policies",
                    filter=in_force & Q(policies__broker_participation=True),
                    distinct=True,
                ),
            )
        )
        search = self.request.GET.get("search")
        if search:
            queryset = queryset.filter(insurer_name__icontains=search)
        return queryset.order_by("insurer_name")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        insurers = list(context["insurers"])
        insurer_ids = [insurer.id for insurer in insurers]
        type_distribution_map = self._build_type_distribution_map(insurer_ids)

        insurers_with_stats = []
        for insurer in insurers:
            total_policies = int(getattr(insurer, "total_policies", 0) or 0)
            active_policies = int(getattr(insurer, "active_policies", 0) or 0)
            broker_participation = int(getattr(insurer, "broker_participation", 0) or 0)

            raw_type_distribution = type_distribution_map.get(insurer.id, [])
            type_distribution = []
            for type_stat in raw_type_distribution:
                percentage = (
                    (type_stat["count"] / active_policies * 100)
                    if active_policies > 0
                    else 0
                )
                type_distribution.append(
                    {
                        "name": type_stat["name"],
                        "count": type_stat["count"],
                        "percentage": round(percentage, 1),
                        "color": type_stat["color"],
                    }
                )

            broker_percentage = (
                (broker_participation / active_policies * 100)
                if active_policies > 0
                else 0
            )

            insurer.stats = {
                "total_policies": total_policies,
                "active_policies": active_policies,
                "type_distribution": type_distribution,
                "broker_participation": broker_participation,
                "broker_percentage": round(broker_percentage, 1),
            }

            insurers_with_stats.append(insurer)
        context["insurers"] = insurers_with_stats
        return context

    def _build_type_distribution_map(self, insurer_ids):
        if not insurer_ids:
            return {}

        type_stats = (
            Policy.objects.filter(insurer_id__in=insurer_ids)
            .filter(in_force_q(date.today()))
            .values("insurer_id", "insurance_type__name")
            .annotate(count=Count("id"))
            .order_by("insurer_id", "-count", "insurance_type__name")
        )

        distribution_map = defaultdict(list)
        for stat in type_stats:
            insurance_type_name = stat["insurance_type__name"] or "Не указан вид"
            distribution_map[stat["insurer_id"]].append(
                {
                    "name": insurance_type_name,
                    "count": int(stat["count"] or 0),
                    "color": INSURANCE_TYPE_COLORS.get(
                        insurance_type_name, DEFAULT_INSURANCE_TYPE_COLOR
                    ),
                }
            )

        return distribution_map


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
        in_force = in_force_q(date.today())
        overview_data = policies_qs.aggregate(
            total_policies=Count("id"),
            active_policies=Count("id", filter=in_force),
            terminated_policies=Count("id", filter=~in_force),
            avg_premium=Avg(
                Subquery(policy_premium_subquery(), output_field=DecimalField()),
            ),
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


class EcosystemHubView(LoginRequiredMixin, TemplateView):
    template_name = "insurers/ecosystem_hub.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["branch_count"] = Branch.objects.count()
        context["manager_count"] = LeasingManager.objects.count()
        context["client_count"] = LeasingClient.objects.count()
        context["insurer_count"] = Insurer.objects.count()
        return context


class BranchListView(LoginRequiredMixin, ListView):
    model = Branch
    template_name = "insurers/branch_list.html"
    context_object_name = "branches"
    paginate_by = 50

    def get_queryset(self):
        in_force = in_force_q(date.today(), prefix="policies__")
        queryset = (
            super()
            .get_queryset()
            .annotate(
                total_policies=Count("policies", distinct=True),
                active_policies=Count(
                    "policies",
                    filter=in_force,
                    distinct=True,
                ),
                broker_participation=Count(
                    "policies",
                    filter=in_force & Q(policies__broker_participation=True),
                    distinct=True,
                ),
            )
        )
        search = self.request.GET.get("search")
        if search:
            queryset = queryset.filter(branch_name__icontains=search)
        return queryset.order_by("branch_name")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        branches = list(context["branches"])
        branch_ids = [branch.id for branch in branches]
        type_distribution_map = self._build_type_distribution_map(branch_ids)

        branches_with_stats = []
        for branch in branches:
            total_policies = int(getattr(branch, "total_policies", 0) or 0)
            active_policies = int(getattr(branch, "active_policies", 0) or 0)
            broker_participation = int(getattr(branch, "broker_participation", 0) or 0)

            raw_type_distribution = type_distribution_map.get(branch.id, [])
            type_distribution = []
            for type_stat in raw_type_distribution:
                percentage = (
                    (type_stat["count"] / active_policies * 100)
                    if active_policies > 0
                    else 0
                )
                type_distribution.append(
                    {
                        "name": type_stat["name"],
                        "count": type_stat["count"],
                        "percentage": round(percentage, 1),
                        "color": type_stat["color"],
                    }
                )

            broker_percentage = (
                (broker_participation / active_policies * 100)
                if active_policies > 0
                else 0
            )

            branch.stats = {
                "total_policies": total_policies,
                "active_policies": active_policies,
                "type_distribution": type_distribution,
                "broker_participation": broker_participation,
                "broker_percentage": round(broker_percentage, 1),
            }

            branches_with_stats.append(branch)
        context["branches"] = branches_with_stats

        import json
        from django.urls import reverse

        map_markers = []
        for branch in branches_with_stats:
            if branch.latitude and branch.longitude:
                map_markers.append(
                    {
                        "name": branch.branch_name,
                        "lat": float(branch.latitude),
                        "lng": float(branch.longitude),
                        "total": branch.stats["total_policies"],
                        "active": branch.stats["active_policies"],
                        "url": reverse("insurers:branch_detail", args=[branch.pk]),
                    }
                )
        context["map_markers_json"] = json.dumps(map_markers, ensure_ascii=False)
        return context

    def _build_type_distribution_map(self, branch_ids):
        if not branch_ids:
            return {}

        type_stats = (
            Policy.objects.filter(branch_id__in=branch_ids)
            .filter(in_force_q(date.today()))
            .values("branch_id", "insurance_type__name")
            .annotate(count=Count("id"))
            .order_by("branch_id", "-count", "insurance_type__name")
        )

        distribution_map = defaultdict(list)
        for stat in type_stats:
            insurance_type_name = stat["insurance_type__name"] or "Не указан вид"
            distribution_map[stat["branch_id"]].append(
                {
                    "name": insurance_type_name,
                    "count": int(stat["count"] or 0),
                    "color": INSURANCE_TYPE_COLORS.get(
                        insurance_type_name, DEFAULT_INSURANCE_TYPE_COLOR
                    ),
                }
            )

        return distribution_map


class BranchDetailView(LoginRequiredMixin, DetailView):
    model = Branch
    template_name = "insurers/branch_detail.html"
    context_object_name = "branch"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        raw_insurer_id = self.request.GET.get("insurer")
        raw_insurance_type_id = self.request.GET.get("insurance_type")
        stats_filters = BranchStatisticsService.parse_filters(
            selected_insurer_id=raw_insurer_id,
            selected_insurance_type_id=raw_insurance_type_id,
            stats_scope=self.request.GET.get("stats_scope"),
            policy_scope=self.request.GET.get("policy_scope"),
            metric=self.request.GET.get("metric"),
            date_from=self.request.GET.get("date_from"),
            date_to=self.request.GET.get("date_to"),
        )

        policies_qs = self.object.policies.select_related(
            "client", "insurer", "insurance_type", "leasing_manager"
        )
        if stats_filters.selected_insurer_id:
            policies_qs = policies_qs.filter(
                insurer_id=stats_filters.selected_insurer_id
            )
        if stats_filters.selected_insurance_type_id:
            policies_qs = policies_qs.filter(
                insurance_type_id=stats_filters.selected_insurance_type_id
            )

        context["policies"] = policies_qs.order_by("-start_date", "-id")
        context["policies_count"] = policies_qs.count()
        in_force = in_force_q(date.today())
        overview_data = policies_qs.aggregate(
            total_policies=Count("id"),
            active_policies=Count("id", filter=in_force),
            terminated_policies=Count("id", filter=~in_force),
            avg_premium=Avg(
                Subquery(policy_premium_subquery(), output_field=DecimalField()),
            ),
        )
        context["branch_overview"] = {
            "total_policies": overview_data["total_policies"],
            "active_policies": overview_data["active_policies"],
            "terminated_policies": overview_data["terminated_policies"],
            "avg_premium": overview_data["avg_premium"] or 0,
        }

        context["insurers"] = (
            Insurer.objects.filter(policies__branch=self.object)
            .distinct()
            .order_by("insurer_name")
        )
        context["insurance_types"] = (
            InsuranceType.objects.filter(policies__branch=self.object)
            .distinct()
            .order_by("name")
        )
        context["managers"] = (
            LeasingManager.objects.filter(policies__branch=self.object)
            .annotate(
                total_policies=Count(
                    "policies", filter=Q(policies__branch=self.object)
                ),
                active_policies=Count(
                    "policies",
                    filter=Q(policies__branch=self.object)
                    & in_force_q(date.today(), prefix="policies__"),
                ),
            )
            .distinct()
            .order_by("name")
        )

        context["selected_insurer_id"] = stats_filters.selected_insurer_id
        context["selected_insurance_type_id"] = stats_filters.selected_insurance_type_id
        context["stats_scope"] = stats_filters.stats_scope
        context["policy_scope"] = stats_filters.policy_scope
        context["metric"] = stats_filters.metric
        context["date_from"] = stats_filters.date_from
        context["date_to"] = stats_filters.date_to

        context["statistics"] = BranchStatisticsService(self.object).calculate(
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
                    "policies", filter=in_force_q(date.today(), prefix="policies__")
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

        branches = (
            Branch.objects.filter(policies__leasing_manager=self.object)
            .distinct()
            .order_by("branch_name")
        )

        policies_qs = self.object.policies.select_related(
            "client", "insurer", "branch", "insurance_type"
        ).order_by("-start_date", "-id")

        context["policies"] = policies_qs
        context["policies_count"] = policies_qs.count()
        context["branches"] = branches

        in_force = in_force_q(date.today())
        overview_data = policies_qs.aggregate(
            total_policies=Count("id"),
            active_policies=Count("id", filter=in_force),
            terminated_policies=Count("id", filter=~in_force),
        )
        # Ближайшая дата окончания среди действующих полисов (in-force уже
        # гарантирует end_date >= сегодня).
        nearest_end_date = (
            policies_qs.filter(in_force)
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
