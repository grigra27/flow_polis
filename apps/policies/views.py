from django.views.generic import ListView, DetailView
from django.contrib.auth.mixins import LoginRequiredMixin
from django_filters.views import FilterView
from .models import Policy, PaymentSchedule
from .filters import PolicyFilter


class PolicyListView(LoginRequiredMixin, FilterView):
    model = Policy
    template_name = 'policies/policy_list.html'
    context_object_name = 'policies'
    filterset_class = PolicyFilter
    paginate_by = 50

    def get_queryset(self):
        queryset = super().get_queryset().select_related(
            'client', 'insurer', 'branch', 'insurance_type'
        ).prefetch_related('payment_schedule', 'info_tags__tag')
        
        # Filter by branch if specified
        branch_id = self.request.GET.get('branch')
        if branch_id:
            queryset = queryset.filter(branch_id=branch_id)
        
        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        from apps.insurers.models import Branch
        context['branches'] = Branch.objects.all()
        context['selected_branch'] = self.request.GET.get('branch')
        return context


class PolicyDetailView(LoginRequiredMixin, DetailView):
    model = Policy
    template_name = 'policies/policy_detail.html'
    context_object_name = 'policy'

    def get_queryset(self):
        return super().get_queryset().select_related(
            'client', 'policyholder', 'insurer', 'branch', 'insurance_type'
        ).prefetch_related(
            'payment_schedule__commission_rate',
            'info_tags__tag'
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        policy = self.object
        context['info1_tags'] = policy.info_tags.filter(info_field=1).select_related('tag')
        context['info2_tags'] = policy.info_tags.filter(info_field=2).select_related('tag')
        
        # Get commission rate for this policy's insurer and insurance type
        from apps.insurers.models import CommissionRate
        try:
            commission_rate = CommissionRate.objects.get(
                insurer=policy.insurer,
                insurance_type=policy.insurance_type
            )
            context['commission_rate'] = commission_rate
        except CommissionRate.DoesNotExist:
            context['commission_rate'] = None
        
        return context


class PaymentScheduleListView(LoginRequiredMixin, ListView):
    model = PaymentSchedule
    template_name = 'policies/payment_list.html'
    context_object_name = 'payments'
    paginate_by = 100

    def get_queryset(self):
        queryset = super().get_queryset().select_related(
            'policy', 'policy__client', 'policy__insurer', 'policy__branch', 'commission_rate'
        )
        
        # Filter by branch if specified
        branch_id = self.request.GET.get('branch')
        if branch_id:
            queryset = queryset.filter(policy__branch_id=branch_id)
        
        # Filter by date range
        date_from = self.request.GET.get('date_from')
        date_to = self.request.GET.get('date_to')
        
        if date_from:
            queryset = queryset.filter(due_date__gte=date_from)
        if date_to:
            queryset = queryset.filter(due_date__lte=date_to)
        
        # Filter by status (only if no date range specified)
        if not date_from and not date_to:
            status = self.request.GET.get('status')
            if status == 'upcoming':
                from django.utils import timezone
                from datetime import timedelta
                today = timezone.now().date()
                next_month = today + timedelta(days=30)
                queryset = queryset.filter(
                    due_date__range=[today, next_month],
                    paid_date__isnull=True
                )
            elif status == 'overdue':
                from django.utils import timezone
                queryset = queryset.filter(
                    due_date__lt=timezone.now().date(),
                    paid_date__isnull=True
                )
            elif status == 'paid':
                queryset = queryset.filter(paid_date__isnull=False)
        
        return queryset.order_by('due_date')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        from apps.insurers.models import Branch
        context['branches'] = Branch.objects.all()
        context['selected_branch'] = self.request.GET.get('branch')
        return context
