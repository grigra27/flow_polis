import django_filters
from django import forms
from .models import Policy
from apps.insurers.models import InfoTag


class PolicyFilter(django_filters.FilterSet):
    policy_number = django_filters.CharFilter(
        lookup_expr="icontains", label="Номер полиса"
    )
    dfa_number = django_filters.CharFilter(lookup_expr="icontains", label="Номер ДФА")
    client__client_name = django_filters.CharFilter(
        lookup_expr="icontains", label="Клиент"
    )
    start_date_from = django_filters.DateFilter(
        field_name="start_date",
        lookup_expr="gte",
        label="Дата начала от",
        widget=forms.DateInput(attrs={"type": "date", "class": "form-control"}),
    )
    start_date_to = django_filters.DateFilter(
        field_name="start_date",
        lookup_expr="lte",
        label="Дата начала до",
        widget=forms.DateInput(attrs={"type": "date", "class": "form-control"}),
    )
    end_date_from = django_filters.DateFilter(
        field_name="end_date",
        lookup_expr="gte",
        label="Дата окончания от",
        widget=forms.DateInput(attrs={"type": "date", "class": "form-control"}),
    )
    end_date_to = django_filters.DateFilter(
        field_name="end_date",
        lookup_expr="lte",
        label="Дата окончания до",
        widget=forms.DateInput(attrs={"type": "date", "class": "form-control"}),
    )

    # Булевые поля со стандартным виджетом
    policy_active = django_filters.BooleanFilter(label="Полис активен")
    dfa_active = django_filters.BooleanFilter(label="ДФА активен")
    policy_uploaded = django_filters.BooleanFilter(label="Полис подгружен")
    broker_participation = django_filters.BooleanFilter(label="Участие брокера")

    # Журнал полисов — общий список; ОСАГО можно скрыть или показать отдельно.
    osago = django_filters.ChoiceFilter(
        label="ОСАГО",
        choices=(("exclude", "Без ОСАГО"), ("only", "Только ОСАГО")),
        empty_label="Все полисы",
        method="filter_osago",
    )

    def filter_osago(self, queryset, name, value):
        if value == "exclude":
            return queryset.without_osago()
        if value == "only":
            return queryset.osago()
        return queryset

    # Фильтр по инфо1 тегам
    info1_tag = django_filters.ModelChoiceFilter(
        queryset=InfoTag.objects.all(),
        field_name="info_tags__tag",
        method="filter_info1_tag",
        label="Инфо 1",
        empty_label="Все теги",
    )

    def filter_info1_tag(self, queryset, name, value):
        """Фильтрация по тегам инфо1"""
        if value:
            return queryset.filter(
                info_tags__tag=value, info_tags__info_field=1
            ).distinct()
        return queryset

    class Meta:
        model = Policy
        fields = [
            "policy_number",
            "dfa_number",
            "client__client_name",
            "insurer",
            "branch",
            "insurance_type",
            "start_date_from",
            "start_date_to",
            "end_date_from",
            "end_date_to",
            "policy_active",
            "dfa_active",
            "policy_uploaded",
            "broker_participation",
            "osago",
            "info1_tag",
        ]
