import django_filters
from .models import Policy


class PolicyFilter(django_filters.FilterSet):
    policy_number = django_filters.CharFilter(lookup_expr='icontains', label='Номер полиса')
    dfa_number = django_filters.CharFilter(lookup_expr='icontains', label='Номер ДФА')
    client__client_name = django_filters.CharFilter(lookup_expr='icontains', label='Клиент')
    start_date = django_filters.DateFilter(lookup_expr='gte', label='Дата начала от')
    end_date = django_filters.DateFilter(lookup_expr='lte', label='Дата окончания до')
    
    class Meta:
        model = Policy
        fields = [
            'policy_number', 'dfa_number', 'client__client_name',
            'insurer', 'branch', 'insurance_type',
            'policy_active', 'dfa_active',
            'start_date', 'end_date'
        ]
