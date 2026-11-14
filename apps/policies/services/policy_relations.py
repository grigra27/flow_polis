"""Связанные договоры и история страхования объекта без изменения данных."""

from datetime import timedelta

from django.utils import timezone

from .flow_import import candidate_policies


def coverage_status(policy, today=None):
    today = today or timezone.localdate()
    if (policy.termination_date and policy.termination_date <= today) or (
        not policy.policy_active and policy.termination_date is None
    ):
        return "terminated", "Расторгнут"
    if policy.start_date > today:
        return "upcoming", "Предстоящий"
    if policy.end_date < today:
        return "completed", "Завершён"
    return "current", "Действует"


def contract_summary(policy, today=None):
    status, label = coverage_status(policy, today)
    return {"policy": policy, "status": status, "status_label": label}


def other_policies_for_dfa(source):
    """Полный ДФА того же клиента; суффиксы и ведущие нули значимы."""
    today = timezone.localdate()
    return [
        contract_summary(policy, today)
        for policy in candidate_policies(source.dfa_number)
        .filter(client_id=source.client_id)
        .exclude(pk=source.pk)
    ]


def insurance_history(source, related_policies):
    """Хронология по видам, включая открытую карточку и смену клиента."""
    if not related_policies:
        return []
    today = timezone.localdate()
    policies = [source, *(policy for policy, _ in related_policies)]
    policies.sort(key=lambda p: (p.insurance_type.name, p.start_date, p.end_date, p.pk))
    effective_end = source.end_date
    if source.termination_date:
        effective_end = min(effective_end, source.termination_date - timedelta(days=1))
    successors = [
        policy
        for policy in policies
        if policy.pk != source.pk
        and policy.insurance_type_id == source.insurance_type_id
        and policy.start_date > effective_end
    ]
    next_id = successors[0].pk if successors else None
    groups = {}
    for policy in policies:
        group = groups.setdefault(
            policy.insurance_type_id,
            {"insurance_type": policy.insurance_type, "contracts": []},
        )
        group["contracts"].append(
            {
                **contract_summary(policy, today),
                "is_open_card": policy.pk == source.pk,
                "is_next": policy.pk == next_id,
                "different_client": policy.client_id != source.client_id,
            }
        )
    return list(groups.values())
