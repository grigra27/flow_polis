from django.views.generic import ListView, DetailView
from django.contrib.auth.mixins import LoginRequiredMixin
from .models import Insurer


class InsurerListView(LoginRequiredMixin, ListView):
    model = Insurer
    template_name = 'insurers/insurer_list.html'
    context_object_name = 'insurers'
    paginate_by = 50

    def get_queryset(self):
        queryset = super().get_queryset()
        search = self.request.GET.get('search')
        if search:
            queryset = queryset.filter(insurer_name__icontains=search)
        return queryset


class InsurerDetailView(LoginRequiredMixin, DetailView):
    model = Insurer
    template_name = 'insurers/insurer_detail.html'
    context_object_name = 'insurer'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['policies'] = self.object.policies.select_related(
            'client', 'branch', 'insurance_type'
        ).order_by('-start_date')
        context['commission_rates'] = self.object.commission_rates.select_related(
            'insurance_type'
        ).order_by('insurance_type__name')
        return context
