from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from hashlib import md5
from typing import Any, Dict, List, Optional

from django.core.cache import cache
from django.db.models import Count, DecimalField, Max, QuerySet, Subquery, Sum
from django.db.models.functions import Coalesce
from django.utils.dateparse import parse_date

from apps.policies.models import policy_premium_subquery, in_force_q


BRANCH_COLORS = [
    "#0d6efd",
    "#6610f2",
    "#6f42c1",
    "#d63384",
    "#dc3545",
    "#fd7e14",
    "#ffc107",
    "#198754",
    "#20c997",
    "#0dcaf0",
]

INSURANCE_TYPE_COLORS = {
    "каско": "#2b8aeb",
    "спецтехника": "#fd7e14",
    "имущество": "#dc3545",
    "грузы": "#2f9e44",
    "осаго": "#6f42c1",
}


@dataclass(frozen=True)
class StatisticsFilters:
    selected_branch_id: Optional[int]
    selected_insurance_type_id: Optional[int]
    stats_scope: str
    policy_scope: str
    metric: str
    date_from: Optional[date]
    date_to: Optional[date]


class InsurerStatisticsService:
    CACHE_TTL_SECONDS = 15 * 60
    VALID_STATS_SCOPE = {"all", "current"}
    VALID_POLICY_SCOPE = {"all", "active"}
    VALID_METRIC = {"count", "premium"}

    def __init__(self, insurer):
        self.insurer = insurer

    @classmethod
    def parse_filters(
        cls,
        *,
        selected_branch_id: Optional[str],
        selected_insurance_type_id: Optional[str],
        stats_scope: Optional[str],
        policy_scope: Optional[str],
        metric: Optional[str],
        date_from: Optional[str],
        date_to: Optional[str],
    ) -> StatisticsFilters:
        branch_id = cls._safe_int(selected_branch_id)
        insurance_type_id = cls._safe_int(selected_insurance_type_id)

        parsed_scope = stats_scope if stats_scope in cls.VALID_STATS_SCOPE else "all"
        parsed_policy_scope = (
            policy_scope if policy_scope in cls.VALID_POLICY_SCOPE else "active"
        )
        parsed_metric = metric if metric in cls.VALID_METRIC else "premium"
        if parsed_scope == "current" and branch_id is None:
            parsed_scope = "all"

        parsed_date_from = parse_date(date_from) if date_from else None
        parsed_date_to = parse_date(date_to) if date_to else None
        if parsed_date_from and parsed_date_to and parsed_date_from > parsed_date_to:
            parsed_date_from, parsed_date_to = parsed_date_to, parsed_date_from

        return StatisticsFilters(
            selected_branch_id=branch_id,
            selected_insurance_type_id=insurance_type_id,
            stats_scope=parsed_scope,
            policy_scope=parsed_policy_scope,
            metric=parsed_metric,
            date_from=parsed_date_from,
            date_to=parsed_date_to,
        )

    def calculate(self, filters: StatisticsFilters) -> Dict[str, Any]:
        cache_key = self._build_cache_key(filters)
        cached_stats = cache.get(cache_key)
        if cached_stats is not None:
            return cached_stats

        base_queryset = self._build_base_queryset(filters)
        scoped_queryset = self._build_policy_scope_queryset(base_queryset, filters)

        total_policies = base_queryset.count()
        active_policies = base_queryset.filter(in_force_q(date.today())).count()
        inactive_policies = max(total_policies - active_policies, 0)

        scoped_policies = scoped_queryset.count()
        total_premium = scoped_queryset.aggregate(
            total=Coalesce(
                Sum(Subquery(policy_premium_subquery(), output_field=DecimalField())),
                Decimal("0"),
            )
        )["total"] or Decimal("0")
        avg_premium = (
            total_premium / scoped_policies if scoped_policies > 0 else Decimal("0")
        )

        broker_participation = scoped_queryset.filter(broker_participation=True).count()
        broker_percentage = (
            (broker_participation / scoped_policies * 100) if scoped_policies > 0 else 0
        )

        branch_distribution = self._build_branch_distribution(scoped_queryset, filters)
        type_distribution = self._build_type_distribution(scoped_queryset, filters)

        branch_chart_data = {
            "labels": [item["name"] for item in branch_distribution],
            "values": [item["metric_value_float"] for item in branch_distribution],
            "colors": [item["color"] for item in branch_distribution],
            "counts": [item["count"] for item in branch_distribution],
            "premiums": [item["total_premium_float"] for item in branch_distribution],
            "metric": filters.metric,
        }

        statistics = {
            "total_policies": total_policies,
            "active_policies": active_policies,
            "inactive_policies": inactive_policies,
            "scoped_policies": scoped_policies,
            "total_premium": total_premium,
            "avg_premium": avg_premium,
            "branch_distribution": branch_distribution,
            "type_distribution": type_distribution,
            "broker_participation": broker_participation,
            "broker_percentage": round(broker_percentage, 1),
            "stats_scope": filters.stats_scope,
            "policy_scope": filters.policy_scope,
            "metric": filters.metric,
            "date_from": filters.date_from,
            "date_to": filters.date_to,
            "branch_chart_data": branch_chart_data,
        }

        cache.set(cache_key, statistics, self.CACHE_TTL_SECONDS)
        return statistics

    def _build_base_queryset(self, filters: StatisticsFilters) -> QuerySet:
        queryset = self.insurer.policies.all()
        if filters.date_from:
            queryset = queryset.filter(start_date__gte=filters.date_from)
        if filters.date_to:
            queryset = queryset.filter(start_date__lte=filters.date_to)

        if filters.stats_scope == "current" and filters.selected_branch_id:
            queryset = queryset.filter(branch_id=filters.selected_branch_id)

        if filters.selected_insurance_type_id:
            queryset = queryset.filter(
                insurance_type_id=filters.selected_insurance_type_id
            )

        return queryset

    def _build_policy_scope_queryset(
        self, base_queryset: QuerySet, filters: StatisticsFilters
    ) -> QuerySet:
        if filters.policy_scope == "active":
            return base_queryset.filter(in_force_q(date.today()))
        return base_queryset

    def _build_branch_distribution(
        self, scoped_queryset: QuerySet, filters: StatisticsFilters
    ) -> List[Dict[str, Any]]:
        branch_stats = scoped_queryset.values(
            "branch_id", "branch__branch_name"
        ).annotate(
            count=Count("id"),
            total_premium=Coalesce(
                Sum(Subquery(policy_premium_subquery(), output_field=DecimalField())),
                Decimal("0"),
            ),
        )
        if filters.metric == "premium":
            branch_stats = branch_stats.order_by("-total_premium", "-count")
        else:
            branch_stats = branch_stats.order_by("-count", "branch__branch_name")

        rows = list(branch_stats)
        total_metric_value = self._sum_metric(rows, filters.metric)

        distribution: List[Dict[str, Any]] = []
        for idx, row in enumerate(rows):
            branch_id = row["branch_id"]
            branch_name = row["branch__branch_name"] or "Не указан филиал"
            count = int(row["count"] or 0)
            premium = row["total_premium"] or Decimal("0")
            metric_value = premium if filters.metric == "premium" else Decimal(count)
            percentage = (
                float(metric_value / total_metric_value * 100)
                if total_metric_value > 0
                else 0
            )

            distribution.append(
                {
                    "id": branch_id,
                    "name": branch_name,
                    "count": count,
                    "total_premium": premium,
                    "total_premium_float": float(premium),
                    "metric_value": metric_value,
                    "metric_value_float": float(metric_value),
                    "percentage": round(percentage, 1),
                    "color": self._color_for_branch(branch_id, idx),
                }
            )

        return distribution

    def _build_type_distribution(
        self, scoped_queryset: QuerySet, filters: StatisticsFilters
    ) -> List[Dict[str, Any]]:
        type_stats = scoped_queryset.values(
            "insurance_type_id", "insurance_type__name"
        ).annotate(
            count=Count("id"),
            total_premium=Coalesce(
                Sum(Subquery(policy_premium_subquery(), output_field=DecimalField())),
                Decimal("0"),
            ),
        )
        if filters.metric == "premium":
            type_stats = type_stats.order_by("-total_premium", "-count")
        else:
            type_stats = type_stats.order_by("-count", "insurance_type__name")

        rows = list(type_stats)
        total_metric_value = self._sum_metric(rows, filters.metric)

        distribution: List[Dict[str, Any]] = []
        for idx, row in enumerate(rows):
            insurance_type_id = row["insurance_type_id"]
            type_name = row["insurance_type__name"] or "Не указан вид"
            count = int(row["count"] or 0)
            premium = row["total_premium"] or Decimal("0")
            metric_value = premium if filters.metric == "premium" else Decimal(count)
            percentage = (
                float(metric_value / total_metric_value * 100)
                if total_metric_value > 0
                else 0
            )

            distribution.append(
                {
                    "id": insurance_type_id,
                    "name": type_name,
                    "count": count,
                    "total_premium": premium,
                    "total_premium_float": float(premium),
                    "metric_value": metric_value,
                    "metric_value_float": float(metric_value),
                    "percentage": round(percentage, 1),
                    "color": self._color_for_type(type_name, insurance_type_id, idx),
                }
            )

        return distribution

    def _build_cache_key(self, filters: StatisticsFilters) -> str:
        latest_update = self.insurer.policies.aggregate(max_updated=Max("updated_at"))[
            "max_updated"
        ]
        latest_update_iso = latest_update.isoformat() if latest_update else "none"
        raw_key = (
            f"insurer:{self.insurer.pk}:stats:v2:"
            f"branch={filters.selected_branch_id}:type={filters.selected_insurance_type_id}:"
            f"stats_scope={filters.stats_scope}:policy_scope={filters.policy_scope}:"
            f"metric={filters.metric}:date_from={filters.date_from}:date_to={filters.date_to}:"
            f"latest={latest_update_iso}"
        )
        return f"insurer_stats:{md5(raw_key.encode('utf-8')).hexdigest()}"

    @staticmethod
    def _safe_int(value: Optional[str]) -> Optional[int]:
        if value in (None, ""):
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _sum_metric(rows: List[Dict[str, Any]], metric: str) -> Decimal:
        if metric == "premium":
            return sum((row.get("total_premium") or Decimal("0")) for row in rows)
        return Decimal(sum(int(row.get("count") or 0) for row in rows))

    @staticmethod
    def _color_for_branch(branch_id: Optional[int], idx: int) -> str:
        if branch_id is None:
            return "#6c757d"
        return BRANCH_COLORS[(branch_id + idx) % len(BRANCH_COLORS)]

    @staticmethod
    def _color_for_type(type_name: str, type_id: Optional[int], idx: int) -> str:
        normalized_name = (type_name or "").strip().lower()
        if normalized_name in INSURANCE_TYPE_COLORS:
            return INSURANCE_TYPE_COLORS[normalized_name]
        if type_id is None:
            return "#95a5a6"
        return BRANCH_COLORS[(type_id + idx) % len(BRANCH_COLORS)]


@dataclass(frozen=True)
class BranchStatisticsFilters:
    selected_insurer_id: Optional[int]
    selected_insurance_type_id: Optional[int]
    stats_scope: str
    policy_scope: str
    metric: str
    date_from: Optional[date]
    date_to: Optional[date]


class BranchStatisticsService:
    CACHE_TTL_SECONDS = 15 * 60
    VALID_STATS_SCOPE = {"all", "current"}
    VALID_POLICY_SCOPE = {"all", "active"}
    VALID_METRIC = {"count", "premium"}

    def __init__(self, branch):
        self.branch = branch

    @classmethod
    def parse_filters(
        cls,
        *,
        selected_insurer_id: Optional[str],
        selected_insurance_type_id: Optional[str],
        stats_scope: Optional[str],
        policy_scope: Optional[str],
        metric: Optional[str],
        date_from: Optional[str],
        date_to: Optional[str],
    ) -> BranchStatisticsFilters:
        insurer_id = cls._safe_int(selected_insurer_id)
        insurance_type_id = cls._safe_int(selected_insurance_type_id)

        parsed_scope = stats_scope if stats_scope in cls.VALID_STATS_SCOPE else "all"
        parsed_policy_scope = (
            policy_scope if policy_scope in cls.VALID_POLICY_SCOPE else "active"
        )
        parsed_metric = metric if metric in cls.VALID_METRIC else "premium"
        if parsed_scope == "current" and insurer_id is None:
            parsed_scope = "all"

        parsed_date_from = parse_date(date_from) if date_from else None
        parsed_date_to = parse_date(date_to) if date_to else None
        if parsed_date_from and parsed_date_to and parsed_date_from > parsed_date_to:
            parsed_date_from, parsed_date_to = parsed_date_to, parsed_date_from

        return BranchStatisticsFilters(
            selected_insurer_id=insurer_id,
            selected_insurance_type_id=insurance_type_id,
            stats_scope=parsed_scope,
            policy_scope=parsed_policy_scope,
            metric=parsed_metric,
            date_from=parsed_date_from,
            date_to=parsed_date_to,
        )

    def calculate(self, filters: BranchStatisticsFilters) -> Dict[str, Any]:
        cache_key = self._build_cache_key(filters)
        cached_stats = cache.get(cache_key)
        if cached_stats is not None:
            return cached_stats

        base_queryset = self._build_base_queryset(filters)
        scoped_queryset = self._build_policy_scope_queryset(base_queryset, filters)

        total_policies = base_queryset.count()
        active_policies = base_queryset.filter(in_force_q(date.today())).count()
        inactive_policies = max(total_policies - active_policies, 0)

        scoped_policies = scoped_queryset.count()
        total_premium = scoped_queryset.aggregate(
            total=Coalesce(
                Sum(Subquery(policy_premium_subquery(), output_field=DecimalField())),
                Decimal("0"),
            )
        )["total"] or Decimal("0")
        avg_premium = (
            total_premium / scoped_policies if scoped_policies > 0 else Decimal("0")
        )

        broker_participation = scoped_queryset.filter(broker_participation=True).count()
        broker_percentage = (
            (broker_participation / scoped_policies * 100) if scoped_policies > 0 else 0
        )

        insurer_distribution = self._build_insurer_distribution(
            scoped_queryset, filters
        )
        type_distribution = self._build_type_distribution(scoped_queryset, filters)

        insurer_chart_data = {
            "labels": [item["name"] for item in insurer_distribution],
            "values": [item["metric_value_float"] for item in insurer_distribution],
            "colors": [item["color"] for item in insurer_distribution],
            "counts": [item["count"] for item in insurer_distribution],
            "premiums": [item["total_premium_float"] for item in insurer_distribution],
            "metric": filters.metric,
        }

        statistics = {
            "total_policies": total_policies,
            "active_policies": active_policies,
            "inactive_policies": inactive_policies,
            "scoped_policies": scoped_policies,
            "total_premium": total_premium,
            "avg_premium": avg_premium,
            "insurer_distribution": insurer_distribution,
            "type_distribution": type_distribution,
            "broker_participation": broker_participation,
            "broker_percentage": round(broker_percentage, 1),
            "stats_scope": filters.stats_scope,
            "policy_scope": filters.policy_scope,
            "metric": filters.metric,
            "date_from": filters.date_from,
            "date_to": filters.date_to,
            "insurer_chart_data": insurer_chart_data,
        }

        cache.set(cache_key, statistics, self.CACHE_TTL_SECONDS)
        return statistics

    def _build_base_queryset(self, filters: BranchStatisticsFilters) -> QuerySet:
        queryset = self.branch.policies.all()
        if filters.date_from:
            queryset = queryset.filter(start_date__gte=filters.date_from)
        if filters.date_to:
            queryset = queryset.filter(start_date__lte=filters.date_to)

        if filters.stats_scope == "current" and filters.selected_insurer_id:
            queryset = queryset.filter(insurer_id=filters.selected_insurer_id)

        if filters.selected_insurance_type_id:
            queryset = queryset.filter(
                insurance_type_id=filters.selected_insurance_type_id
            )

        return queryset

    def _build_policy_scope_queryset(
        self, base_queryset: QuerySet, filters: BranchStatisticsFilters
    ) -> QuerySet:
        if filters.policy_scope == "active":
            return base_queryset.filter(in_force_q(date.today()))
        return base_queryset

    def _build_insurer_distribution(
        self, scoped_queryset: QuerySet, filters: BranchStatisticsFilters
    ) -> List[Dict[str, Any]]:
        insurer_stats = scoped_queryset.values(
            "insurer_id", "insurer__insurer_name"
        ).annotate(
            count=Count("id"),
            total_premium=Coalesce(
                Sum(Subquery(policy_premium_subquery(), output_field=DecimalField())),
                Decimal("0"),
            ),
        )
        if filters.metric == "premium":
            insurer_stats = insurer_stats.order_by("-total_premium", "-count")
        else:
            insurer_stats = insurer_stats.order_by("-count", "insurer__insurer_name")

        rows = list(insurer_stats)
        total_metric_value = self._sum_metric(rows, filters.metric)

        distribution: List[Dict[str, Any]] = []
        for idx, row in enumerate(rows):
            insurer_id = row["insurer_id"]
            insurer_name = row["insurer__insurer_name"] or "Не указан страховщик"
            count = int(row["count"] or 0)
            premium = row["total_premium"] or Decimal("0")
            metric_value = premium if filters.metric == "premium" else Decimal(count)
            percentage = (
                float(metric_value / total_metric_value * 100)
                if total_metric_value > 0
                else 0
            )

            distribution.append(
                {
                    "id": insurer_id,
                    "name": insurer_name,
                    "count": count,
                    "total_premium": premium,
                    "total_premium_float": float(premium),
                    "metric_value": metric_value,
                    "metric_value_float": float(metric_value),
                    "percentage": round(percentage, 1),
                    "color": self._color_for_insurer(insurer_id, idx),
                }
            )

        return distribution

    def _build_type_distribution(
        self, scoped_queryset: QuerySet, filters: BranchStatisticsFilters
    ) -> List[Dict[str, Any]]:
        type_stats = scoped_queryset.values(
            "insurance_type_id", "insurance_type__name"
        ).annotate(
            count=Count("id"),
            total_premium=Coalesce(
                Sum(Subquery(policy_premium_subquery(), output_field=DecimalField())),
                Decimal("0"),
            ),
        )
        if filters.metric == "premium":
            type_stats = type_stats.order_by("-total_premium", "-count")
        else:
            type_stats = type_stats.order_by("-count", "insurance_type__name")

        rows = list(type_stats)
        total_metric_value = self._sum_metric(rows, filters.metric)

        distribution: List[Dict[str, Any]] = []
        for idx, row in enumerate(rows):
            insurance_type_id = row["insurance_type_id"]
            type_name = row["insurance_type__name"] or "Не указан вид"
            count = int(row["count"] or 0)
            premium = row["total_premium"] or Decimal("0")
            metric_value = premium if filters.metric == "premium" else Decimal(count)
            percentage = (
                float(metric_value / total_metric_value * 100)
                if total_metric_value > 0
                else 0
            )

            distribution.append(
                {
                    "id": insurance_type_id,
                    "name": type_name,
                    "count": count,
                    "total_premium": premium,
                    "total_premium_float": float(premium),
                    "metric_value": metric_value,
                    "metric_value_float": float(metric_value),
                    "percentage": round(percentage, 1),
                    "color": self._color_for_type(type_name, insurance_type_id, idx),
                }
            )

        return distribution

    def _build_cache_key(self, filters: BranchStatisticsFilters) -> str:
        latest_update = self.branch.policies.aggregate(max_updated=Max("updated_at"))[
            "max_updated"
        ]
        latest_update_iso = latest_update.isoformat() if latest_update else "none"
        raw_key = (
            f"branch:{self.branch.pk}:stats:v1:"
            f"insurer={filters.selected_insurer_id}:type={filters.selected_insurance_type_id}:"
            f"stats_scope={filters.stats_scope}:policy_scope={filters.policy_scope}:"
            f"metric={filters.metric}:date_from={filters.date_from}:date_to={filters.date_to}:"
            f"latest={latest_update_iso}"
        )
        return f"branch_stats:{md5(raw_key.encode('utf-8')).hexdigest()}"

    @staticmethod
    def _safe_int(value: Optional[str]) -> Optional[int]:
        if value in (None, ""):
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _sum_metric(rows: List[Dict[str, Any]], metric: str) -> Decimal:
        if metric == "premium":
            return sum((row.get("total_premium") or Decimal("0")) for row in rows)
        return Decimal(sum(int(row.get("count") or 0) for row in rows))

    @staticmethod
    def _color_for_insurer(insurer_id: Optional[int], idx: int) -> str:
        if insurer_id is None:
            return "#6c757d"
        return BRANCH_COLORS[(insurer_id + idx) % len(BRANCH_COLORS)]

    @staticmethod
    def _color_for_type(type_name: str, type_id: Optional[int], idx: int) -> str:
        normalized_name = (type_name or "").strip().lower()
        if normalized_name in INSURANCE_TYPE_COLORS:
            return INSURANCE_TYPE_COLORS[normalized_name]
        if type_id is None:
            return "#95a5a6"
        return BRANCH_COLORS[(type_id + idx) % len(BRANCH_COLORS)]
