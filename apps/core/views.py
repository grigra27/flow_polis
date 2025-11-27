from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from django.db.models import Sum, Count, Q
from django.utils import timezone
from datetime import timedelta


@login_required
def dashboard(request):
    """
    Main dashboard view
    """
    from apps.policies.models import Policy, PaymentSchedule
    
    today = timezone.now().date()
    next_month = today + timedelta(days=30)
    
    # Statistics
    total_policies = Policy.objects.filter(policy_active=True).count()
    
    upcoming_payments = PaymentSchedule.objects.filter(
        due_date__range=[today, next_month],
        paid_date__isnull=True
    ).select_related('policy', 'policy__client')
    
    overdue_payments = PaymentSchedule.objects.filter(
        due_date__lt=today,
        paid_date__isnull=True
    ).select_related('policy', 'policy__client')
    
    # Policies not uploaded
    not_uploaded_policies = Policy.objects.filter(
        policy_uploaded=False
    ).select_related('client', 'insurer', 'branch')
    
    # Recent policies
    recent_policies = Policy.objects.select_related(
        'client', 'insurer', 'branch'
    ).order_by('-created_at')[:10]
    
    context = {
        'total_policies': total_policies,
        'upcoming_payments_count': upcoming_payments.count(),
        'overdue_payments_count': overdue_payments.count(),
        'upcoming_payments': upcoming_payments[:10],
        'overdue_payments': overdue_payments[:10],
        'not_uploaded_policies_count': not_uploaded_policies.count(),
        'not_uploaded_policies': not_uploaded_policies[:10],
        'recent_policies': recent_policies,
    }
    
    return render(request, 'core/dashboard.html', context)
