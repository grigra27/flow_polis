from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Dict, List, Any

from django.conf import settings
from django.db.models import Q, Sum
from django.db.models.functions import Coalesce
from django.urls import reverse
from django.utils import timezone


DECIMAL_ZERO = Decimal("0")
DECIMAL_HUNDRED = Decimal("100")


def _to_decimal(value: Any) -> Decimal:
    if isinstance(value, Decimal):
        return value
    if value is None:
        return DECIMAL_ZERO
    return Decimal(str(value))


def _safe_percent(part: Decimal, whole: Decimal) -> Decimal:
    if whole <= 0:
        return DECIMAL_ZERO
    return (part / whole) * DECIMAL_HUNDRED


def _sum_amount(qs, field: str) -> Decimal:
    total = qs.aggregate(total=Coalesce(Sum(field), DECIMAL_ZERO)).get("total")
    return _to_decimal(total)


def _signed(value: Decimal) -> str:
    if value > 0:
        return f"+{value:.1f}"
    return f"{value:.1f}"


def _media_url(path: Any) -> str | None:
    if not path:
        return None

    media_url = settings.MEDIA_URL or "/media/"
    if not media_url.endswith("/"):
        media_url = f"{media_url}/"
    return f"{media_url}{str(path).lstrip('/')}"


@dataclass(frozen=True)
class _SnapshotStatus:
    paid_count: int
    pending_count: int
    overdue_count: int
    total_count: int
    paid_amount: Decimal
    pending_amount: Decimal
    overdue_amount: Decimal
    paid_share: Decimal
    pending_share: Decimal
    overdue_share: Decimal


class DashboardV2Service:
    """
    Aggregates metrics for Dashboard 2.0.

    The service intentionally returns only portfolio-level aggregates and segment
    level totals (no policy numbers or client-level sensitive data).
    """

    def get_dashboard_context(self) -> Dict[str, Any]:
        from apps.policies.models import Policy, PaymentSchedule

        today = timezone.localdate()
        prev_date = today - timedelta(days=30)
        current_month_start = today.replace(day=1)

        policies_qs = Policy.objects.all()
        active_policies_qs = policies_qs.filter(policy_active=True)
        active_payments_qs = PaymentSchedule.objects.filter(policy__policy_active=True)

        health = self._build_health_index(
            policies_qs=policies_qs,
            active_payments_qs=active_payments_qs,
            today=today,
            prev_date=prev_date,
        )

        bridge = self._build_bridge_metrics(
            active_payments_qs=active_payments_qs,
            current_month_start=current_month_start,
            today=today,
        )

        payment_contour = self._build_payment_contour(
            active_payments_qs=active_payments_qs,
            today=today,
        )

        aging = self._build_overdue_aging(
            active_payments_qs=active_payments_qs,
            today=today,
        )

        renewal = self._build_renewal_radar(
            active_policies_qs=active_policies_qs,
            today=today,
        )

        data_quality = self._build_data_quality(
            policies_qs=policies_qs,
            active_policies_qs=active_policies_qs,
            active_payments_qs=active_payments_qs,
        )

        snapshot = self._build_system_snapshot(
            active_policies_qs=active_policies_qs,
            active_payments_qs=active_payments_qs,
            health=health,
            data_quality=data_quality,
            today=today,
        )

        structure = self._build_portfolio_structure(
            active_payments_qs=active_payments_qs,
            current_month_start=current_month_start,
        )

        concentration = self._build_concentration_risk(structure=structure)

        dynamics = self._build_dynamics(
            policies_qs=policies_qs,
            active_payments_qs=active_payments_qs,
            today=today,
        )

        insights = self._build_insights(
            health=health,
            payment_contour=payment_contour,
            renewal=renewal,
            data_quality=data_quality,
            concentration=concentration,
            dynamics=dynamics,
        )
        legacy_relay = self._build_legacy_relay(
            policies_qs=policies_qs,
            active_payments_qs=active_payments_qs,
            today=today,
        )

        return {
            "dashboard_v2_meta": {
                "generated_at": timezone.now(),
                "today": today,
                "period_label": f"{today.strftime('%d.%m.%Y')} (срез)",
            },
            "dashboard_v2_snapshot": snapshot,
            "dashboard_v2_health": health,
            "dashboard_v2_bridge": bridge,
            "dashboard_v2_payment_contour": payment_contour,
            "dashboard_v2_aging": aging,
            "dashboard_v2_renewal": renewal,
            "dashboard_v2_data_quality": data_quality,
            "dashboard_v2_structure": structure,
            "dashboard_v2_concentration": concentration,
            "dashboard_v2_dynamics": dynamics,
            "dashboard_v2_insights": insights,
            "dashboard_v2_legacy_relay": legacy_relay,
        }

    def _build_health_index(
        self,
        *,
        policies_qs,
        active_payments_qs,
        today: date,
        prev_date: date,
    ) -> Dict[str, Any]:
        current = self._health_snapshot(
            policies_qs=policies_qs, active_payments_qs=active_payments_qs, as_of=today
        )
        previous = self._health_snapshot(
            policies_qs=policies_qs,
            active_payments_qs=active_payments_qs,
            as_of=prev_date,
        )

        delta = current["score"] - previous["score"]

        return {
            "score": current["score"],
            "previous_score": previous["score"],
            "delta": delta,
            "delta_label": _signed(delta),
            "delta_direction": "up" if delta > 0 else ("down" if delta < 0 else "flat"),
            "components": current["components"],
            "weights": {
                "payment_discipline": 40,
                "uploaded_ratio": 20,
                "active_ratio": 20,
                "broker_ratio": 20,
            },
            "interpretation": self._health_interpretation(current["score"]),
        }

    def _health_snapshot(
        self, *, policies_qs, active_payments_qs, as_of: date
    ) -> Dict[str, Any]:
        scoped_policies = policies_qs.filter(created_at__date__lte=as_of)
        scoped_active_policies = scoped_policies.filter(policy_active=True)
        scoped_active_payments = active_payments_qs.filter(
            policy__created_at__date__lte=as_of
        )

        total_policies = scoped_policies.count()
        active_policies = scoped_active_policies.count()

        uploaded_policies = scoped_active_policies.filter(policy_uploaded=True).count()
        broker_policies = scoped_active_policies.filter(
            broker_participation=True
        ).count()

        uploaded_ratio = _safe_percent(
            _to_decimal(uploaded_policies), _to_decimal(active_policies)
        )
        active_ratio = _safe_percent(
            _to_decimal(active_policies), _to_decimal(total_policies)
        )
        broker_ratio = _safe_percent(
            _to_decimal(broker_policies), _to_decimal(active_policies)
        )
        payment_discipline = self._payment_discipline_as_of(
            scoped_active_payments, as_of
        )

        score = (
            payment_discipline * Decimal("0.40")
            + uploaded_ratio * Decimal("0.20")
            + active_ratio * Decimal("0.20")
            + broker_ratio * Decimal("0.20")
        )

        score = max(DECIMAL_ZERO, min(DECIMAL_HUNDRED, score))

        return {
            "score": score.quantize(Decimal("0.1")),
            "components": [
                {
                    "key": "payment_discipline",
                    "label": "Платежная дисциплина",
                    "value": payment_discipline.quantize(Decimal("0.1")),
                    "weight": 40,
                },
                {
                    "key": "uploaded_ratio",
                    "label": "Подгруженные полисы",
                    "value": uploaded_ratio.quantize(Decimal("0.1")),
                    "weight": 20,
                },
                {
                    "key": "active_ratio",
                    "label": "Активные полисы",
                    "value": active_ratio.quantize(Decimal("0.1")),
                    "weight": 20,
                },
                {
                    "key": "broker_ratio",
                    "label": "Участие брокера",
                    "value": broker_ratio.quantize(Decimal("0.1")),
                    "weight": 20,
                },
            ],
        }

    def _payment_discipline_as_of(self, active_payments_qs, as_of: date) -> Decimal:
        due_qs = active_payments_qs.filter(due_date__lte=as_of)
        total_due = due_qs.count()
        if total_due == 0:
            return DECIMAL_HUNDRED

        paid_due = due_qs.filter(paid_date__isnull=False, paid_date__lte=as_of).count()
        return _safe_percent(_to_decimal(paid_due), _to_decimal(total_due))

    def _health_interpretation(self, score: Decimal) -> str:
        if score >= Decimal("85"):
            return "Стабильный"
        if score >= Decimal("70"):
            return "Контролируемый"
        return "Требует внимания"

    def _build_bridge_metrics(
        self,
        *,
        active_payments_qs,
        current_month_start: date,
        today: date,
    ) -> Dict[str, Any]:
        year_start = date(today.year, 1, 1)
        year_end = date(today.year, 12, 31)

        actual_qs = active_payments_qs.filter(
            due_date__gte=year_start,
            due_date__lt=current_month_start,
            paid_date__isnull=False,
        )
        planned_qs = active_payments_qs.filter(
            due_date__gte=current_month_start,
            due_date__lte=year_end,
        )

        actual = {
            "premium": _sum_amount(actual_qs, "amount"),
            "insurance_sum": _sum_amount(actual_qs, "insurance_sum"),
        }
        planned = {
            "premium": _sum_amount(planned_qs, "amount"),
            "insurance_sum": _sum_amount(planned_qs, "insurance_sum"),
        }

        bridge = {
            "premium": actual["premium"] + planned["premium"],
            "insurance_sum": actual["insurance_sum"] + planned["insurance_sum"],
        }

        premium_actual_share = _safe_percent(actual["premium"], bridge["premium"])
        premium_plan_share = _safe_percent(planned["premium"], bridge["premium"])

        if current_month_start > year_start:
            actual_period_label = (
                f"{year_start.strftime('%d.%m.%Y')}–"
                f"{(current_month_start - timedelta(days=1)).strftime('%d.%m.%Y')}"
            )
        else:
            actual_period_label = "Прошедших месяцев в этом году еще нет"

        if current_month_start <= year_end:
            planned_period_label = (
                f"{current_month_start.strftime('%d.%m.%Y')}–"
                f"{year_end.strftime('%d.%m.%Y')}"
            )
        else:
            planned_period_label = "Текущий и будущие месяцы в этом году отсутствуют"

        return {
            "calendar_year": today.year,
            "year_start": year_start,
            "year_end": year_end,
            "actual_period_label": actual_period_label,
            "planned_period_label": planned_period_label,
            "actual": actual,
            "planned": planned,
            "bridge": bridge,
            "premium_actual_share": premium_actual_share.quantize(Decimal("0.1")),
            "premium_plan_share": premium_plan_share.quantize(Decimal("0.1")),
        }

    def _build_payment_contour(
        self, *, active_payments_qs, today: date
    ) -> Dict[str, Any]:
        current = self._status_snapshot(active_payments_qs, as_of=today)

        current_window_start = today - timedelta(days=29)
        prev_window_start = today - timedelta(days=59)
        prev_window_end = today - timedelta(days=30)

        current_window_qs = active_payments_qs.filter(
            due_date__gte=current_window_start, due_date__lte=today
        )
        prev_window_qs = active_payments_qs.filter(
            due_date__gte=prev_window_start, due_date__lte=prev_window_end
        )

        current_window = self._status_snapshot(current_window_qs, as_of=today)
        previous_window = self._status_snapshot(prev_window_qs, as_of=prev_window_end)

        return {
            "snapshot": current,
            "window_30": {
                "current": current_window,
                "previous": previous_window,
                "delta_paid_count": current_window.paid_count
                - previous_window.paid_count,
                "delta_pending_count": current_window.pending_count
                - previous_window.pending_count,
                "delta_overdue_count": current_window.overdue_count
                - previous_window.overdue_count,
            },
            "statuses": [
                {
                    "key": "paid",
                    "label": "Оплачено",
                    "count": current.paid_count,
                    "amount": current.paid_amount,
                    "share": current.paid_share,
                    "badge_class": "bg-success",
                },
                {
                    "key": "pending",
                    "label": "Ожидает оплаты",
                    "count": current.pending_count,
                    "amount": current.pending_amount,
                    "share": current.pending_share,
                    "badge_class": "bg-warning text-dark",
                },
                {
                    "key": "overdue",
                    "label": "Просрочено",
                    "count": current.overdue_count,
                    "amount": current.overdue_amount,
                    "share": current.overdue_share,
                    "badge_class": "bg-danger",
                },
            ],
        }

    def _status_snapshot(self, qs, *, as_of: date) -> _SnapshotStatus:
        paid_qs = qs.filter(paid_date__isnull=False, paid_date__lte=as_of)
        unpaid_qs = qs.filter(Q(paid_date__isnull=True) | Q(paid_date__gt=as_of))
        overdue_qs = unpaid_qs.filter(due_date__lt=as_of)
        pending_qs = unpaid_qs.filter(due_date__gte=as_of)

        paid_count = paid_qs.count()
        pending_count = pending_qs.count()
        overdue_count = overdue_qs.count()
        total_count = paid_count + pending_count + overdue_count

        paid_amount = _sum_amount(paid_qs, "amount")
        pending_amount = _sum_amount(pending_qs, "amount")
        overdue_amount = _sum_amount(overdue_qs, "amount")
        total_amount = paid_amount + pending_amount + overdue_amount

        return _SnapshotStatus(
            paid_count=paid_count,
            pending_count=pending_count,
            overdue_count=overdue_count,
            total_count=total_count,
            paid_amount=paid_amount,
            pending_amount=pending_amount,
            overdue_amount=overdue_amount,
            paid_share=_safe_percent(
                _to_decimal(paid_count), _to_decimal(total_count)
            ).quantize(Decimal("0.1")),
            pending_share=_safe_percent(
                _to_decimal(pending_count), _to_decimal(total_count)
            ).quantize(Decimal("0.1")),
            overdue_share=_safe_percent(
                _to_decimal(overdue_count), _to_decimal(total_count)
            ).quantize(Decimal("0.1")),
        )

    def _build_overdue_aging(
        self, *, active_payments_qs, today: date
    ) -> Dict[str, Any]:
        overdue_qs = active_payments_qs.filter(
            paid_date__isnull=True, due_date__lt=today
        )

        ranges = [
            ("1-30", today - timedelta(days=30), today - timedelta(days=1)),
            ("31-60", today - timedelta(days=60), today - timedelta(days=31)),
            ("61-90", today - timedelta(days=90), today - timedelta(days=61)),
        ]

        buckets: List[Dict[str, Any]] = []
        for label, start_date, end_date in ranges:
            bucket_qs = overdue_qs.filter(
                due_date__gte=start_date, due_date__lte=end_date
            )
            buckets.append(
                {
                    "label": label,
                    "count": bucket_qs.count(),
                    "amount": _sum_amount(bucket_qs, "amount"),
                }
            )

        plus_90_qs = overdue_qs.filter(due_date__lt=today - timedelta(days=90))
        buckets.append(
            {
                "label": "90+",
                "count": plus_90_qs.count(),
                "amount": _sum_amount(plus_90_qs, "amount"),
            }
        )

        total_amount = sum((bucket["amount"] for bucket in buckets), DECIMAL_ZERO)
        total_count = sum((bucket["count"] for bucket in buckets))

        for bucket in buckets:
            bucket["share"] = _safe_percent(bucket["amount"], total_amount).quantize(
                Decimal("0.1")
            )

        critical_bucket = (
            max(buckets, key=lambda item: item["amount"]) if buckets else None
        )

        return {
            "buckets": buckets,
            "total_amount": total_amount,
            "total_count": total_count,
            "critical_bucket": critical_bucket,
        }

    def _build_renewal_radar(
        self, *, active_policies_qs, today: date
    ) -> Dict[str, Any]:
        active_total = active_policies_qs.count()
        prev_ref = today - timedelta(days=30)

        horizons = []
        for days in (30, 60, 90):
            current_count = active_policies_qs.filter(
                end_date__gte=today, end_date__lte=today + timedelta(days=days)
            ).count()
            previous_count = active_policies_qs.filter(
                end_date__gte=prev_ref, end_date__lte=prev_ref + timedelta(days=days)
            ).count()
            delta = current_count - previous_count

            horizons.append(
                {
                    "days": days,
                    "count": current_count,
                    "previous_count": previous_count,
                    "delta": delta,
                    "delta_label": f"{delta:+d}",
                    "share": _safe_percent(
                        _to_decimal(current_count), _to_decimal(active_total)
                    ).quantize(Decimal("0.1")),
                }
            )

        return {
            "active_total": active_total,
            "horizons": horizons,
        }

    def _build_data_quality(
        self,
        *,
        policies_qs,
        active_policies_qs,
        active_payments_qs,
    ) -> Dict[str, Any]:
        total_policies = policies_qs.count()
        active_policies_count = active_policies_qs.count()
        active_payments_count = active_payments_qs.count()

        not_uploaded_count = active_policies_qs.filter(policy_uploaded=False).count()
        missing_commission_count = active_payments_qs.filter(
            commission_rate__isnull=True
        ).count()
        inactive_without_termination_count = policies_qs.filter(
            policy_active=False, termination_date__isnull=True
        ).count()
        active_with_termination_count = policies_qs.filter(
            policy_active=True, termination_date__isnull=False
        ).count()
        status_conflict_count = (
            inactive_without_termination_count + active_with_termination_count
        )

        not_uploaded_ratio = _safe_percent(
            _to_decimal(not_uploaded_count), _to_decimal(active_policies_count)
        )
        missing_commission_ratio = _safe_percent(
            _to_decimal(missing_commission_count), _to_decimal(active_payments_count)
        )
        status_conflict_ratio = _safe_percent(
            _to_decimal(status_conflict_count), _to_decimal(total_policies)
        )

        quality_score = DECIMAL_HUNDRED - (
            not_uploaded_ratio * Decimal("0.40")
            + missing_commission_ratio * Decimal("0.40")
            + status_conflict_ratio * Decimal("0.20")
        )
        quality_score = max(DECIMAL_ZERO, min(DECIMAL_HUNDRED, quality_score))

        problems = [
            {
                "label": "Активные полисы без подгруженного файла",
                "count": not_uploaded_count,
                "ratio": not_uploaded_ratio.quantize(Decimal("0.1")),
            },
            {
                "label": "Платежи без ставки комиссии",
                "count": missing_commission_count,
                "ratio": missing_commission_ratio.quantize(Decimal("0.1")),
            },
            {
                "label": "Конфликты статусов полиса",
                "count": status_conflict_count,
                "ratio": status_conflict_ratio.quantize(Decimal("0.1")),
            },
        ]

        return {
            "quality_score": quality_score.quantize(Decimal("0.1")),
            "problems": problems,
            "inactive_without_termination_count": inactive_without_termination_count,
            "active_with_termination_count": active_with_termination_count,
        }

    def _build_system_snapshot(
        self,
        *,
        active_policies_qs,
        active_payments_qs,
        health: Dict[str, Any],
        data_quality: Dict[str, Any],
        today: date,
    ) -> Dict[str, Any]:
        upcoming_qs = active_payments_qs.filter(
            due_date__gte=today,
            due_date__lte=today + timedelta(days=30),
            paid_date__isnull=True,
        )
        overdue_qs = active_payments_qs.filter(
            due_date__lt=today, paid_date__isnull=True
        )

        active_policies_count = active_policies_qs.count()
        not_uploaded_count = active_policies_qs.filter(policy_uploaded=False).count()

        upcoming_count = upcoming_qs.count()
        overdue_count = overdue_qs.count()

        upcoming_amount = _sum_amount(upcoming_qs, "amount")
        overdue_amount = _sum_amount(overdue_qs, "amount")

        not_uploaded_share = _safe_percent(
            _to_decimal(not_uploaded_count), _to_decimal(active_policies_count)
        ).quantize(Decimal("0.1"))

        return {
            "active_policies_count": active_policies_count,
            "not_uploaded_policies_count": not_uploaded_count,
            "not_uploaded_policies_share": not_uploaded_share,
            "upcoming_payments_count": upcoming_count,
            "upcoming_payments_amount": upcoming_amount,
            "no_payment_data_count": overdue_count,
            "no_payment_data_amount": overdue_amount,
            "health_score": health["score"],
            "data_quality_score": data_quality["quality_score"],
            "cards": [
                {
                    "key": "active_policies",
                    "label": "Активные полисы",
                    "count": active_policies_count,
                    "hint": "текущий активный портфель",
                    "amount": None,
                    "tone": "primary",
                },
                {
                    "key": "not_uploaded",
                    "label": "Не подгружен полис",
                    "count": not_uploaded_count,
                    "hint": f"{not_uploaded_share:.1f}% от активных",
                    "amount": None,
                    "tone": "info",
                },
                {
                    "key": "upcoming_30",
                    "label": "Предстоящие платежи (30д)",
                    "count": upcoming_count,
                    "hint": "без факта оплаты",
                    "amount": upcoming_amount,
                    "tone": "warning",
                },
                {
                    "key": "no_payment_data",
                    "label": "Нет данных об оплате",
                    "count": overdue_count,
                    "hint": "просроченные платежи",
                    "amount": overdue_amount,
                    "tone": "danger",
                },
            ],
        }

    def _build_portfolio_structure(
        self,
        *,
        active_payments_qs,
        current_month_start: date,
    ) -> Dict[str, Any]:
        actual_qs = active_payments_qs.filter(
            due_date__lt=current_month_start, paid_date__isnull=False
        )
        planned_qs = active_payments_qs.filter(due_date__gte=current_month_start)

        by_branch = self._build_bridge_distribution(
            actual_qs=actual_qs,
            planned_qs=planned_qs,
            label_field="policy__branch__branch_name",
            id_field="policy__branch_id",
            logo_field="policy__branch__logo",
        )
        by_insurer = self._build_bridge_distribution(
            actual_qs=actual_qs,
            planned_qs=planned_qs,
            label_field="policy__insurer__insurer_name",
            id_field="policy__insurer_id",
            logo_field="policy__insurer__logo",
        )
        by_type = self._build_bridge_distribution(
            actual_qs=actual_qs,
            planned_qs=planned_qs,
            label_field="policy__insurance_type__name",
            id_field="policy__insurance_type_id",
            logo_field="policy__insurance_type__icon",
        )

        return {
            "by_branch": by_branch,
            "by_insurer": by_insurer,
            "by_type": by_type,
            "top_branch": by_branch[0] if by_branch else None,
            "top_insurer": by_insurer[0] if by_insurer else None,
            "top_type": by_type[0] if by_type else None,
            "branch_breakdown": self._build_segment_breakdown(by_branch),
            "insurer_breakdown": self._build_segment_breakdown(by_insurer),
            "type_breakdown": self._build_segment_breakdown(by_type),
        }

    def _build_bridge_distribution(
        self,
        *,
        actual_qs,
        planned_qs,
        label_field: str,
        id_field: str | None = None,
        logo_field: str | None = None,
    ) -> List[Dict[str, Any]]:
        value_fields = [label_field]
        if id_field:
            value_fields.append(id_field)
        if logo_field:
            value_fields.append(logo_field)

        actual_rows = (
            actual_qs.values(*value_fields)
            .annotate(total=Coalesce(Sum("amount"), DECIMAL_ZERO))
            .order_by()
        )
        planned_rows = (
            planned_qs.values(*value_fields)
            .annotate(total=Coalesce(Sum("amount"), DECIMAL_ZERO))
            .order_by()
        )

        aggregate_map: Dict[str, Dict[str, Any]] = {}

        for row in actual_rows:
            label = row.get(label_field) or "Не указано"
            entity_id = row.get(id_field) if id_field else None
            logo_url = _media_url(row.get(logo_field)) if logo_field else None
            key = f"{entity_id}:{label}" if entity_id is not None else label

            aggregate_map.setdefault(
                key,
                {
                    "id": entity_id,
                    "name": label,
                    "logo_url": logo_url,
                    "fact": DECIMAL_ZERO,
                    "plan": DECIMAL_ZERO,
                },
            )
            if logo_url and not aggregate_map[key]["logo_url"]:
                aggregate_map[key]["logo_url"] = logo_url
            aggregate_map[key]["fact"] = _to_decimal(row.get("total"))

        for row in planned_rows:
            label = row.get(label_field) or "Не указано"
            entity_id = row.get(id_field) if id_field else None
            logo_url = _media_url(row.get(logo_field)) if logo_field else None
            key = f"{entity_id}:{label}" if entity_id is not None else label

            aggregate_map.setdefault(
                key,
                {
                    "id": entity_id,
                    "name": label,
                    "logo_url": logo_url,
                    "fact": DECIMAL_ZERO,
                    "plan": DECIMAL_ZERO,
                },
            )
            if logo_url and not aggregate_map[key]["logo_url"]:
                aggregate_map[key]["logo_url"] = logo_url
            aggregate_map[key]["plan"] = _to_decimal(row.get("total"))

        rows = []
        total_bridge = DECIMAL_ZERO
        for totals in aggregate_map.values():
            bridge = totals["fact"] + totals["plan"]
            total_bridge += bridge
            rows.append(
                {
                    "id": totals["id"],
                    "name": totals["name"],
                    "logo_url": totals["logo_url"],
                    "fact_premium": totals["fact"],
                    "plan_premium": totals["plan"],
                    "bridge_premium": bridge,
                }
            )

        rows.sort(key=lambda item: item["bridge_premium"], reverse=True)

        for row in rows:
            row["share"] = _safe_percent(row["bridge_premium"], total_bridge).quantize(
                Decimal("0.1")
            )

        return rows

    def _build_segment_breakdown(self, rows: List[Dict[str, Any]]) -> Dict[str, Any]:
        top_rows = rows[:5]
        top_share = sum((row["share"] for row in top_rows), DECIMAL_ZERO)
        other_share = max(DECIMAL_ZERO, DECIMAL_HUNDRED - top_share).quantize(
            Decimal("0.1")
        )

        chart_rows = [
            {
                "name": row["name"],
                "share": row["share"],
                "logo_url": row.get("logo_url"),
                "is_other": False,
            }
            for row in top_rows
        ]

        if other_share > 0:
            chart_rows.append(
                {
                    "name": "Прочие",
                    "share": other_share,
                    "logo_url": None,
                    "is_other": True,
                }
            )

        return {
            "top": top_rows,
            "other_share": other_share,
            "chart": chart_rows,
        }

    def _build_concentration_risk(self, *, structure: Dict[str, Any]) -> Dict[str, Any]:
        insurer = self._concentration_stats(structure.get("by_insurer", []))
        branch = self._concentration_stats(structure.get("by_branch", []))

        overall_hhi = max(insurer["hhi"], branch["hhi"])
        overall_level = self._hhi_level(overall_hhi)

        return {
            "insurer": insurer,
            "branch": branch,
            "overall_hhi": overall_hhi.quantize(Decimal("0.1")),
            "overall_level": overall_level,
        }

    def _concentration_stats(self, rows: List[Dict[str, Any]]) -> Dict[str, Any]:
        if not rows:
            return {
                "hhi": DECIMAL_ZERO,
                "top1_share": DECIMAL_ZERO,
                "top3_share": DECIMAL_ZERO,
                "level": "Низкий",
            }

        hhi = sum((row["share"] ** 2 for row in rows), DECIMAL_ZERO)
        top1_share = rows[0]["share"]
        top3_share = sum((row["share"] for row in rows[:3]), DECIMAL_ZERO)

        return {
            "hhi": hhi.quantize(Decimal("0.1")),
            "top1_share": top1_share.quantize(Decimal("0.1")),
            "top3_share": top3_share.quantize(Decimal("0.1")),
            "level": self._hhi_level(hhi),
        }

    def _hhi_level(self, hhi_value: Decimal) -> str:
        if hhi_value < Decimal("1500"):
            return "Низкий"
        if hhi_value < Decimal("2500"):
            return "Средний"
        return "Высокий"

    def _build_dynamics(
        self, *, policies_qs, active_payments_qs, today: date
    ) -> Dict[str, Any]:
        stats_30 = self._policy_flow_stats(
            policies_qs=policies_qs, days=30, today=today
        )
        stats_90 = self._policy_flow_stats(
            policies_qs=policies_qs, days=90, today=today
        )

        current_window_start = today - timedelta(days=29)
        prev_window_start = today - timedelta(days=59)
        prev_window_end = today - timedelta(days=30)

        current_due_qs = active_payments_qs.filter(
            due_date__gte=current_window_start, due_date__lte=today
        )
        prev_due_qs = active_payments_qs.filter(
            due_date__gte=prev_window_start, due_date__lte=prev_window_end
        )

        current_snapshot = self._status_snapshot(current_due_qs, as_of=today)
        prev_snapshot = self._status_snapshot(prev_due_qs, as_of=prev_window_end)

        overdue_share_delta_pp = (
            current_snapshot.overdue_share - prev_snapshot.overdue_share
        )

        return {
            "window_30": stats_30,
            "window_90": stats_90,
            "overdue_share_current": current_snapshot.overdue_share,
            "overdue_share_previous": prev_snapshot.overdue_share,
            "overdue_share_delta_pp": overdue_share_delta_pp.quantize(Decimal("0.1")),
            "overdue_share_delta_pp_label": _signed(overdue_share_delta_pp),
        }

    def _policy_flow_stats(
        self, *, policies_qs, days: int, today: date
    ) -> Dict[str, Any]:
        start = today - timedelta(days=days - 1)

        created_count = policies_qs.filter(
            created_at__date__gte=start, created_at__date__lte=today
        ).count()
        deactivated_count = policies_qs.filter(
            termination_date__gte=start, termination_date__lte=today
        ).count()
        net_growth = created_count - deactivated_count

        return {
            "days": days,
            "created_count": created_count,
            "deactivated_count": deactivated_count,
            "net_growth": net_growth,
            "net_growth_label": f"{net_growth:+d}",
        }

    def _build_insights(
        self,
        *,
        health,
        payment_contour,
        renewal,
        data_quality,
        concentration,
        dynamics,
    ) -> Dict[str, Any]:
        insights: List[Dict[str, Any]] = []

        if health["score"] < Decimal("75"):
            insights.append(
                {
                    "level": "danger",
                    "title": "Индекс здоровья ниже целевого уровня",
                    "message": (
                        f"Текущий индекс {health['score']:.1f}. "
                        "Рекомендуется проверить просрочку и качество данных."
                    ),
                    "action_label": "Проверить просрочку",
                    "action_url": reverse("policies:payments") + "?status=overdue",
                }
            )

        snapshot = payment_contour["snapshot"]
        if snapshot.overdue_count > 0:
            insights.append(
                {
                    "level": "warning",
                    "title": "Есть просроченные платежи",
                    "message": (
                        f"{snapshot.overdue_count} платежей на сумму "
                        f"{snapshot.overdue_amount:,.0f} ₽ остаются просроченными."
                    ),
                    "action_label": "Открыть просрочку",
                    "action_url": reverse("policies:payments") + "?status=overdue",
                }
            )

        horizon_30 = renewal["horizons"][0] if renewal["horizons"] else None
        if horizon_30 and horizon_30["share"] >= Decimal("10"):
            insights.append(
                {
                    "level": "info",
                    "title": "Высокая нагрузка по продлениям в 30 дней",
                    "message": (
                        f"В ближайшие 30 дней истекает {horizon_30['count']} полисов "
                        f"({horizon_30['share']:.1f}% активного портфеля)."
                    ),
                    "action_label": "Открыть раздел экспорта",
                    "action_url": reverse("reports:index"),
                }
            )

        if data_quality["quality_score"] < Decimal("85"):
            insights.append(
                {
                    "level": "warning",
                    "title": "Качество данных требует внимания",
                    "message": (
                        f"Индекс качества данных: {data_quality['quality_score']:.1f}. "
                        "Есть заметная доля технических пропусков."
                    ),
                    "action_label": "Проверить неподгруженные полисы",
                    "action_url": reverse("policies:list") + "?policy_uploaded=False",
                }
            )

        if concentration["overall_level"] == "Высокий":
            insights.append(
                {
                    "level": "warning",
                    "title": "Высокая концентрация портфеля",
                    "message": (
                        f"HHI {concentration['overall_hhi']:.1f}. "
                        "Портфель зависит от ограниченного числа сегментов."
                    ),
                    "action_label": "Посмотреть структуру",
                    "action_url": reverse("core:dashboard_v2") + "#portfolio-structure",
                }
            )

        if dynamics["window_30"]["net_growth"] < 0:
            insights.append(
                {
                    "level": "info",
                    "title": "Отрицательный чистый прирост за 30 дней",
                    "message": (
                        f"Чистый прирост: {dynamics['window_30']['net_growth_label']} "
                        "полисов. Нужен контроль входящего потока."
                    ),
                    "action_label": "Открыть журнал полисов",
                    "action_url": reverse("policies:list"),
                }
            )

        if not insights:
            insights.append(
                {
                    "level": "success",
                    "title": "Портфель стабилен",
                    "message": "Критичных отклонений по ключевым индикаторам не найдено.",
                    "action_label": "Открыть платежи",
                    "action_url": reverse("policies:payments") + "?status=upcoming",
                }
            )

        quick_actions = [
            {
                "label": "Просроченные платежи",
                "url": reverse("policies:payments") + "?status=overdue",
            },
            {
                "label": "Предстоящие платежи (30 дней)",
                "url": reverse("policies:payments") + "?status=upcoming",
            },
            {
                "label": "Неподгруженные полисы",
                "url": reverse("policies:list") + "?policy_uploaded=False",
            },
            {
                "label": "Экспорты",
                "url": reverse("reports:index"),
            },
        ]

        return {
            "insights": insights[:5],
            "quick_actions": quick_actions,
        }

    def _build_legacy_relay(
        self,
        *,
        policies_qs,
        active_payments_qs,
        today: date,
    ) -> Dict[str, Any]:
        preview_limit = 5
        upcoming_horizon = today + timedelta(days=30)

        upcoming_qs = (
            active_payments_qs.filter(
                due_date__range=[today, upcoming_horizon],
                paid_date__isnull=True,
            )
            .select_related("policy", "policy__client")
            .order_by("due_date", "policy__policy_number")
        )
        overdue_qs = (
            active_payments_qs.filter(
                due_date__lt=today,
                paid_date__isnull=True,
            )
            .select_related("policy", "policy__client")
            .order_by("due_date", "policy__policy_number")
        )
        recent_policies_qs = policies_qs.select_related(
            "client", "insurer", "branch"
        ).order_by("-created_at")
        not_uploaded_qs = (
            policies_qs.filter(policy_uploaded=False)
            .select_related("client", "insurer", "branch")
            .order_by("-created_at")
        )

        upcoming_rows = [
            self._serialize_payment_relay_row(
                payment=payment, today=today, overdue=False
            )
            for payment in upcoming_qs[:preview_limit]
        ]
        overdue_rows = [
            self._serialize_payment_relay_row(
                payment=payment, today=today, overdue=True
            )
            for payment in overdue_qs[:preview_limit]
        ]
        recent_rows = [
            self._serialize_policy_relay_row(policy)
            for policy in recent_policies_qs[:preview_limit]
        ]
        not_uploaded_rows = [
            self._serialize_policy_relay_row(policy)
            for policy in not_uploaded_qs[:preview_limit]
        ]

        return {
            "cards": [
                {
                    "key": "upcoming",
                    "type": "payment",
                    "tone": "warning",
                    "title": "Предстоящие платежи",
                    "count": upcoming_qs.count(),
                    "rows": upcoming_rows,
                    "link_url": reverse("policies:payments") + "?status=upcoming",
                    "link_label": "Все предстоящие платежи",
                },
                {
                    "key": "overdue",
                    "type": "payment",
                    "tone": "danger",
                    "title": "Нет данных об оплате",
                    "count": overdue_qs.count(),
                    "rows": overdue_rows,
                    "link_url": reverse("policies:payments") + "?status=overdue",
                    "link_label": "Все не оплаченные платежи",
                },
                {
                    "key": "recent",
                    "type": "policy",
                    "tone": "primary",
                    "title": "Недавно добавленные полисы",
                    "count": recent_policies_qs.count(),
                    "rows": recent_rows,
                    "link_url": reverse("policies:list"),
                    "link_label": "Все полисы",
                },
                {
                    "key": "not_uploaded",
                    "type": "policy",
                    "tone": "info",
                    "title": "Полисы неподгруженные",
                    "count": not_uploaded_qs.count(),
                    "rows": not_uploaded_rows,
                    "link_url": reverse("policies:list") + "?policy_uploaded=False",
                    "link_label": "Все не подгруженные полисы",
                },
            ]
        }

    def _serialize_payment_relay_row(
        self,
        *,
        payment,
        today: date,
        overdue: bool,
    ) -> Dict[str, Any]:
        policy = payment.policy
        client = getattr(policy, "client", None)
        overdue_days = max((today - payment.due_date).days, 0)

        return {
            "policy_id": policy.pk,
            "policy_number": policy.policy_number or "—",
            "dfa_number": policy.dfa_number or "—",
            "client_name": getattr(client, "client_name", "Не указано"),
            "due_date": payment.due_date,
            "amount": payment.amount,
            "hint": (
                f"{overdue_days} дн. проср."
                if overdue
                else f"{payment.year_number}/{payment.installment_number}"
            ),
        }

    def _serialize_policy_relay_row(self, policy) -> Dict[str, Any]:
        client = getattr(policy, "client", None)
        insurer = getattr(policy, "insurer", None)

        return {
            "policy_id": policy.pk,
            "policy_number": policy.policy_number or "—",
            "dfa_number": policy.dfa_number or "—",
            "client_name": getattr(client, "client_name", "Не указано"),
            "start_date": policy.start_date,
            "end_date": policy.end_date,
            "hint": getattr(insurer, "insurer_name", "Не указано"),
        }
