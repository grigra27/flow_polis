import django_filters
from apps.policies.models import Policy, PaymentSchedule


class PolicyExportFilter(django_filters.FilterSet):
    """Фильтр для экспорта полисов"""

    policy_number = django_filters.CharFilter(
        field_name="policy_number", lookup_expr="icontains", label="Номер полиса"
    )
    dfa_number = django_filters.CharFilter(
        field_name="dfa_number", lookup_expr="icontains", label="Номер ДФА"
    )
    client__client_name = django_filters.CharFilter(
        field_name="client__client_name", lookup_expr="icontains", label="Клиент"
    )
    start_date_from = django_filters.DateFilter(
        field_name="start_date", lookup_expr="gte", label="Дата начала от"
    )
    start_date_to = django_filters.DateFilter(
        field_name="start_date", lookup_expr="lte", label="Дата начала до"
    )
    end_date_from = django_filters.DateFilter(
        field_name="end_date", lookup_expr="gte", label="Дата окончания от"
    )
    end_date_to = django_filters.DateFilter(
        field_name="end_date", lookup_expr="lte", label="Дата окончания до"
    )

    class Meta:
        model = Policy
        fields = [
            "insurer",
            "branch",
            "insurance_type",
            "policy_active",
            "dfa_active",
            "broker_participation",
        ]


class PaymentExportFilter(django_filters.FilterSet):
    """Фильтр для экспорта платежей"""

    policy__policy_number = django_filters.CharFilter(
        field_name="policy__policy_number",
        lookup_expr="icontains",
        label="Номер полиса",
    )
    policy__client__client_name = django_filters.CharFilter(
        field_name="policy__client__client_name",
        lookup_expr="icontains",
        label="Клиент",
    )
    due_date_from = django_filters.DateFilter(
        field_name="due_date", lookup_expr="gte", label="Дата платежа от"
    )
    due_date_to = django_filters.DateFilter(
        field_name="due_date", lookup_expr="lte", label="Дата платежа до"
    )
    is_paid = django_filters.BooleanFilter(
        field_name="paid_date", lookup_expr="isnull", exclude=True, label="Оплачен"
    )

    class Meta:
        model = PaymentSchedule
        fields = [
            "policy__insurer",
            "policy__branch",
            "year_number",
            "installment_number",
        ]
