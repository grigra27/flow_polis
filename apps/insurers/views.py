from django.views.generic import ListView, DetailView
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import JsonResponse
from django.views.decorators.http import require_GET
from django.contrib.admin.views.decorators import staff_member_required
from django.db.models import Count, Sum, Q
from decimal import Decimal
from .models import Insurer, CommissionRate


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


class InsurerDetailView(LoginRequiredMixin, DetailView):
    model = Insurer
    template_name = "insurers/insurer_detail.html"
    context_object_name = "insurer"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        # Get policies queryset
        policies_qs = self.object.policies.select_related(
            "client", "branch", "insurance_type"
        )

        # Filter by branch if specified
        branch_id = self.request.GET.get("branch")
        if branch_id:
            policies_qs = policies_qs.filter(branch_id=branch_id)

        context["policies"] = policies_qs.order_by("-start_date")

        # Get branches that have policies for this insurer
        from .models import Branch

        context["branches"] = (
            Branch.objects.filter(policies__insurer=self.object)
            .distinct()
            .order_by("branch_name")
        )

        context["selected_branch"] = branch_id

        context["commission_rates"] = self.object.commission_rates.select_related(
            "insurance_type"
        ).order_by("insurance_type__name")

        # Calculate statistics
        context["statistics"] = self._calculate_statistics()

        return context

    def _calculate_statistics(self):
        """Calculate statistics for the insurer"""
        all_policies = self.object.policies.all()

        # Total counts
        total_policies = all_policies.count()
        active_policies = all_policies.filter(policy_active=True).count()
        inactive_policies = total_policies - active_policies

        # Total premium
        total_premium = all_policies.aggregate(total=Sum("premium_total"))[
            "total"
        ] or Decimal("0")

        # Distribution by branches
        branch_stats = (
            all_policies.filter(branch__isnull=False)
            .values("branch__branch_name")
            .annotate(count=Count("id"), total_premium=Sum("premium_total"))
            .order_by("-count")
        )

        # Calculate percentages for branches
        # Color palette for charts
        colors = [
            "#0d6efd",
            "#6610f2",
            "#6f42c1",
            "#d63384",
            "#dc3545",
            "#fd7e14",
            "#ffc107",
            "#198754",
            "#20c997",
            "#0dcaf0",
        ]

        branch_distribution = []
        for idx, stat in enumerate(branch_stats):
            percentage = (
                (stat["count"] / total_policies * 100) if total_policies > 0 else 0
            )
            branch_distribution.append(
                {
                    "name": stat["branch__branch_name"],
                    "count": stat["count"],
                    "percentage": round(percentage, 1),
                    "total_premium": stat["total_premium"] or Decimal("0"),
                    "color": colors[idx % len(colors)],
                }
            )

        # Distribution by insurance types
        type_stats = (
            all_policies.values("insurance_type__name")
            .annotate(count=Count("id"), total_premium=Sum("premium_total"))
            .order_by("-count")
        )

        # Calculate percentages for insurance types
        type_distribution = []
        for stat in type_stats:
            percentage = (
                (stat["count"] / total_policies * 100) if total_policies > 0 else 0
            )
            type_distribution.append(
                {
                    "name": stat["insurance_type__name"],
                    "count": stat["count"],
                    "percentage": round(percentage, 1),
                    "total_premium": stat["total_premium"] or Decimal("0"),
                }
            )

        # Average premium
        avg_premium = (
            total_premium / total_policies if total_policies > 0 else Decimal("0")
        )

        # Policies with broker participation
        broker_participation = all_policies.filter(broker_participation=True).count()
        broker_percentage = (
            (broker_participation / total_policies * 100) if total_policies > 0 else 0
        )

        return {
            "total_policies": total_policies,
            "active_policies": active_policies,
            "inactive_policies": inactive_policies,
            "total_premium": total_premium,
            "avg_premium": avg_premium,
            "branch_distribution": branch_distribution,
            "type_distribution": type_distribution,
            "broker_participation": broker_participation,
            "broker_percentage": round(broker_percentage, 1),
        }


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
