from django.views.generic import ListView, DetailView
from django.contrib.auth.mixins import LoginRequiredMixin
from .models import Client


class ClientListView(LoginRequiredMixin, ListView):
    model = Client
    template_name = "clients/client_list.html"
    context_object_name = "clients"
    paginate_by = 69

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
        context["policies"] = self.object.policies.select_related(
            "insurer", "branch", "insurance_type", "leasing_manager"
        ).order_by("-start_date")

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
