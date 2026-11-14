from datetime import date

from django.db.models import Count
from django.views.generic import ListView, DetailView
from django.contrib.auth.mixins import LoginRequiredMixin
from .models import Client
from apps.policies.models import in_force_q


class ClientListView(LoginRequiredMixin, ListView):
    model = Client
    template_name = "clients/client_list.html"
    context_object_name = "clients"
    paginate_by = 39

    def get_queryset(self):
        queryset = super().get_queryset()
        search = self.request.GET.get("search")
        if search:
            queryset = (
                queryset.filter(client_name__icontains=search)
                | queryset.filter(client_inn__icontains=search)
                | queryset.filter(alternative_name__icontains=search)
            )
        return queryset


class ClientDetailView(LoginRequiredMixin, DetailView):
    model = Client
    template_name = "clients/client_detail.html"
    context_object_name = "client"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        role = self.request.GET.get("role", "lessee")
        if role not in {"lessee", "policyholder"}:
            role = "lessee"
        role_counts = {
            "lessee": self.object.policies.count(),
            "policyholder": self.object.policyholder_policies.count(),
        }
        related_policies = (
            self.object.policyholder_policies
            if role == "policyholder"
            else self.object.policies
        )
        policies_qs = related_policies.select_related(
            "client", "insurer", "branch", "insurance_type", "leasing_manager"
        )
        context.update(
            client_role=role,
            client_role_label="Страхователь"
            if role == "policyholder"
            else "Лизингополучатель",
            client_role_counts=role_counts,
            client_role_policy_count=role_counts[role],
        )
        context["policies"] = policies_qs.order_by("-start_date")

        in_force = in_force_q(date.today())
        # Счётчики и средняя премия — по портфелю без ОСАГО (решение владельца:
        # ОСАГО в списке карточки, но не в счётчиках и средних), ОСАГО — отдельно.
        overview_data = policies_qs.without_osago().aggregate(
            total_policies=Count("id"),
            active_policies=Count("id", filter=in_force),
            terminated_policies=Count("id", filter=~in_force),
        )
        # Ближайшая дата окончания среди действующих полисов (in-force уже
        # гарантирует end_date >= сегодня, поэтому первый по возрастанию — ближайший).
        nearest_end_date = (
            policies_qs.filter(in_force)
            .order_by("end_date")
            .values_list("end_date", flat=True)
            .first()
        )

        context["client_overview"] = {
            "total_policies": overview_data["total_policies"],
            "osago_policies": policies_qs.osago().count(),
            "active_policies": overview_data["active_policies"],
            "terminated_policies": overview_data["terminated_policies"],
            "nearest_end_date": nearest_end_date,
        }

        # Получаем уникальных менеджеров и филиалы, работающие с этим клиентом
        managers_data = {}
        for policy in context["policies"]:
            if policy.leasing_manager:
                manager = policy.leasing_manager
                if manager.id not in managers_data:
                    managers_data[manager.id] = {
                        "manager": manager,
                        "branches": set(),
                        "policies_count": 0,
                    }
                managers_data[manager.id]["branches"].add(policy.branch.branch_name)
                managers_data[manager.id]["policies_count"] += 1

        context["managers_info"] = list(managers_data.values())

        return context
