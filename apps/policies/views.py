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
        return super().get_queryset().select_related(
            'client', 'insurer', 'branch', 'insurance_type'
        ).prefetch_related('payment_schedule')


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


class PaymentScheduleListView(LoginRequiredMixin, ListView):
    model = PaymentSchedule
    template_name = 'policies/payment_list.html'
    context_object_name = 'payments'
    paginate_by = 100

    def get_queryset(self):
        queryset = super().get_queryset().select_related(
            'policy', 'policy__client', 'policy__insurer', 'commission_rate'
        )
        
        # Filter by status
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
