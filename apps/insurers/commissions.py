"""Подбор версий ставок и история для справочников."""
from collections import defaultdict
from datetime import date, timedelta

from django.utils import timezone

from .models import CommissionRate


def resolve_commission_rate(insurer_id, insurance_type_id, start_date):
    return CommissionRate.objects.for_policy(
        insurer_id, insurance_type_id, start_date
    ).first()


def rate_history(rates, *, on_date=None):
    """Один текущий процент на вид; предыдущие и будущие условия отдельно."""
    on_date = on_date or timezone.localdate()
    groups = defaultdict(list)
    for rate in rates:
        groups[rate.insurance_type_id].append(rate)
    result = {"current": [], "previous": [], "scheduled": [], "on_date": on_date}
    for versions in groups.values():
        versions.sort(key=lambda rate: (rate.effective_from or date.min, rate.pk))
        applicable = [
            rate
            for rate in versions
            if not rate.effective_from or rate.effective_from <= on_date
        ]
        current = applicable[-1] if applicable else None
        for index, rate in enumerate(versions):
            next_date = (
                versions[index + 1].effective_from
                if index + 1 < len(versions)
                else None
            )
            rate.effective_until = next_date - timedelta(days=1) if next_date else None
            rate.selection_status = (
                "current"
                if rate is current
                else "scheduled"
                if rate.effective_from and rate.effective_from > on_date
                else "previous"
            )
            result[rate.selection_status].append(rate)
    for key in ("current", "previous", "scheduled"):
        result[key].sort(
            key=lambda rate: (rate.insurance_type.name, rate.effective_from or date.min)
        )
    return result
