"""Начальные значения для оформления нового договора из карточки полиса."""


def can_create_from_policy(user):
    return (
        user.is_active
        and user.is_staff
        and user.has_perms(("policies.add_policy", "policies.add_paymentschedule"))
    )


def can_create_osago_from_object(source):
    """Оформление ОСАГО на тот же объект доступно только из полиса КАСКО."""
    return (
        not source.is_osago and source.insurance_type.name.strip().casefold() == "каско"
    )


def object_initial(source):
    return {
        "client": source.client_id,
        "policyholder": source.policyholder_id,
        "branch": source.branch_id,
        "leasing_manager": source.leasing_manager_id,
        "dfa_number": source.dfa_number,
        "property_description": source.property_description,
        "property_year": source.property_year,
        "vin_number": source.vin_number,
    }


def policy_template_initial(source):
    return {
        **object_initial(source),
        "insurer": source.insurer_id,
        "insurance_type": source.insurance_type_id,
        "start_date": source.start_date,
        "end_date": source.end_date,
        "franchise": source.franchise,
        "broker_participation": source.broker_participation,
    }


def other_policies_for_vin(source):
    """Другие договоры по VIN с текущим статусом страхового покрытия."""
    from apps.policies.models import Policy
    from .policy_relations import coverage_status

    vin = (source.vin_number or "").strip()
    if not vin:
        return []
    matches = (
        Policy.objects.filter(vin_number__iexact=vin)
        .exclude(pk=source.pk)
        .select_related("insurance_type", "client")
        .order_by("-start_date", "-pk")
    )
    return [(policy, coverage_status(policy)[1]) for policy in matches]


def osago_for_vin(vin):
    """Действующие, последний завершённый и ближайший будущий договор по VIN."""
    from django.utils import timezone
    from apps.policies.models import Policy, in_force_q

    vin = vin.strip()
    if not vin:
        return []
    today = timezone.localdate()
    matches = Policy.objects.osago().filter(vin_number__iexact=vin)
    fields = ("pk", "policy_number", "start_date", "end_date", "termination_date")
    current = matches.in_force(today).only(*fields).order_by("-start_date", "-pk")
    contracts = [(policy, "Действует") for policy in current]
    if not contracts:
        last = (
            matches.filter(start_date__lte=today)
            .exclude(in_force_q(today))
            .only(*fields)
            .order_by("-start_date", "-pk")
            .first()
        )
        if last:
            contracts.append((last, "Предыдущий"))
    upcoming = (
        matches.filter(
            start_date__gt=today, policy_active=True, termination_date__isnull=True
        )
        .only(*fields)
        .order_by("start_date", "pk")
        .first()
    )
    if upcoming:
        contracts.append((upcoming, "Предстоящий"))
    return contracts
