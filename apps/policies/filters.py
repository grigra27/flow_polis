import django_filters
from django import forms
from .models import Policy


class PolicyFilter(django_filters.FilterSet):
    policy_number = django_filters.CharFilter(lookup_expr='icontains', label='Номер полиса')
    dfa_number = django_filters.CharFilter(lookup_expr='icontains', label='Номер ДФА')
    client__client_name = django_filters.CharFilter(lookup_expr='icontains', label='Клиент')
    start_date_from = django_filters.DateFilter(
        field_name='start_date',
        lookup_expr='gte',
        label='Дата начала от',
        widget=forms.DateInput(attrs={'type': 'date', 'class': 'form-control'})
    )
    start_date_to = django_filters.DateFilter(
        field_name='start_date',
        lookup_expr='lte',
        label='Дата начала до',
        widget=forms.DateInput(attrs={'type': 'date', 'class': 'form-control'})
    )
    policy_uploaded = django_filters.BooleanFilter(label='Статус подгрузки')
    
    class Meta:
        model = Policy
        fields = [
            'policy_number', 'dfa_number', 'client__client_name',
            'insurer', 'branch', 'insurance_type',
            'policy_active', 'dfa_active', 'policy_uploaded', 'broker_participation',
            'start_date_from', 'start_date_to'
        ]
