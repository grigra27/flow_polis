"""Общие фильтры Dashboard и имущественных отчётов."""

from dataclasses import dataclass
from datetime import date
from urllib.parse import urlencode

from django.db.models import Q
from django.utils import timezone
from django.utils.dateparse import parse_date

SCOPE_LABELS = {
    "all": "Все сделки",
    "broker": "С участием брокера",
    "direct": "Без участия брокера",
}


def normalize_scope(value):
    if value in {"broker", "with_broker", "broker_only"}:
        return "broker"
    if value in {"direct", "without_broker"}:
        return "direct"
    return "all"


def dfa_in_force_q(as_of, prefix=""):
    """Восстановить ДФА на дату по известной дате закрытия.

    Снятый флаг без даты не позволяет восстановить прошлое. Дата закрытия
    приоритетнее флага; в сам день закрытия ДФА уже не активен.
    """
    return Q(**{f"{prefix}dfa_deactivation_date__gt": as_of}) | Q(
        **{
            f"{prefix}dfa_active": True,
            f"{prefix}dfa_deactivation_date__isnull": True,
        }
    )


@dataclass(frozen=True)
class PortfolioScope:
    as_of: date
    structure_scope: str = "all"
    branch_ids: tuple = ()

    @classmethod
    def from_query(cls, query):
        try:
            as_of = parse_date(query.get("as_of", ""))
        except (ValueError, TypeError):
            as_of = None
        if as_of is not None and not 2 <= as_of.year <= 9998:
            as_of = None
        branches = tuple(
            sorted(
                {
                    int(value)
                    for value in query.getlist("branch")
                    if len(value) <= 10
                    and value.isascii()
                    and value.isdigit()
                    and 0 < int(value) < 2**31
                }
            )
        )
        return cls(
            as_of or timezone.localdate(),
            normalize_scope(query.get("structure_scope")),
            branches,
        )

    @property
    def label(self):
        return SCOPE_LABELS[self.structure_scope]

    def apply(self, policies):
        if self.structure_scope != "all":
            policies = policies.filter(
                broker_participation=self.structure_scope == "broker"
            )
        if self.branch_ids:
            policies = policies.filter(branch_id__in=self.branch_ids)
        return policies

    def query(self, **extra):
        params = {
            "as_of": self.as_of.isoformat(),
            "structure_scope": self.structure_scope,
            "branch": self.branch_ids,
        }
        params.update(extra)
        return urlencode({k: v for k, v in params.items() if v is not None}, doseq=True)
