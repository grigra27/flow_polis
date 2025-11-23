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
        
        # Get policies queryset
        policies_qs = self.object.policies.select_related(
            'client', 'branch', 'insurance_type'
        )
        
        # Filter by branch if specified
        branch_id = self.request.GET.get('branch')
        if branch_id:
            policies_qs = policies_qs.filter(branch_id=branch_id)
        
        context['policies'] = policies_qs.order_by('-start_date')
        
        # Get branches that have policies for this insurer
        from .models import Branch
        context['branches'] = Branch.objects.filter(
            policies__insurer=self.object
        ).distinct().order_by('branch_name')
        
        context['selected_branch'] = branch_id
        
        context['commission_rates'] = self.object.commission_rates.select_related(
            'insurance_type'
        ).order_by('insurance_type__name')
        return context
