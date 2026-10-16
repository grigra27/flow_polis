"""
Вкладка «Сводка»: как идут дела и на что обратить внимание прямо сейчас
(docs/analytics-2.0-plan.md, §4 A).

Сводка всегда на сегодня: фильтр периода не используется, разрезы — да.
"""

from datetime import date, timedelta

from django.db.models import Count, Q

from .. import money, portfolio
from . import data_quality
from ..drilldown import POLICIES, metric

USES_PERIOD = False

# Пороги сигналов (утверждены владельцем 2026-10-16).
AWAITING_ACT_SIGNAL_DAYS = 60
RECENT_LOSS_DAYS = 30
MANAGER_WINDOW_DAYS = 90
MANAGER_MIN_PREVIOUS = 4  # меньше — шум, а не падение


def same_day_last_year(value: date) -> date:
    try:
        return value.replace(year=value.year - 1)
    except ValueError:  # 29 февраля
        return value.replace(year=value.year - 1, day=28)


@metric("new_business", "Новый бизнес (дата начала полиса в периоде)", POLICIES)
def new_business(params, opts):
    queryset = portfolio.new_business(
        params.policies(), params.date_from, params.date_to
    )
    if opts.get("to_old_dfa") == "1":
        queryset = queryset.filter(renewal_to_old_dfa=True)
    return queryset


@metric(
    "ending_soon",
    f"Заканчиваются в ближайшие {portfolio.ENDING_SOON_DAYS} дней при активном ДФА",
    POLICIES,
    note="Полисы в силе с открытым ДФА — по ним нужен новый полис.",
)
def ending_soon(params, opts):
    return portfolio.ending_soon(params.policies(), params.today)


def _compare(current, previous, previous_from):
    """Изменение к прошлому году в процентах.

    None — сравнивать не с чем: прошлый период пуст или попадает на неполную
    историю (до money.HISTORY_RELIABLE_FROM).
    """
    if not previous or not money.history_is_reliable(previous_from):
        return None
    return (current - previous) / previous * 100


def _new_business_block(policies, start, today):
    current = portfolio.new_business_totals(policies, start, today)
    previous = portfolio.new_business_totals(
        policies, same_day_last_year(start), same_day_last_year(today)
    )
    previous_from = same_day_last_year(start)
    return {
        "date_from": start,
        "date_to": today,
        "current": current,
        "previous": previous,
        "history_incomplete": not money.history_is_reliable(previous_from),
        "count_change": _compare(current["count"], previous["count"], previous_from),
        "commission_change": _compare(
            current["commission"], previous["commission"], previous_from
        ),
    }


def _manager_drops(policies, today):
    recent_from = today - timedelta(days=MANAGER_WINDOW_DAYS - 1)
    previous_from = recent_from - timedelta(days=MANAGER_WINDOW_DAYS)
    rows = (
        policies.filter(leasing_manager__isnull=False, start_date__gte=previous_from)
        .filter(start_date__lte=today)
        .values("leasing_manager_id", "leasing_manager__name")
        .annotate(
            recent=Count("id", filter=Q(start_date__gte=recent_from)),
            previous=Count("id", filter=Q(start_date__lt=recent_from)),
        )
        .order_by()
    )
    drops = [
        {
            "id": row["leasing_manager_id"],
            "name": row["leasing_manager__name"],
            "recent": row["recent"],
            "previous": row["previous"],
        }
        for row in rows
        if row["previous"] >= MANAGER_MIN_PREVIOUS
        and row["recent"] * 2 < row["previous"]
    ]
    drops.sort(key=lambda r: r["recent"] - r["previous"])
    return {"date_from": recent_from, "rows": drops}


def build(params, query=None):
    today = params.today
    payments = params.payments()
    policies = params.policies()
    year_start = date(today.year, 1, 1)

    bridge = money.build_current_year_outlook(payments, today)
    loss_rows = money.lost_rows(payments)
    lost_ytd = money.sum_rows(money.lost_in_period(loss_rows, year_start, today))
    lost_undated = money.sum_rows([r for r in loss_rows if r["loss_date"] is None])

    ytd = money.year_to_date_totals(payments, today)
    ytd_previous = money.year_to_date_totals(payments, today, year=today.year - 1)

    quarter_start = date(today.year, (today.month - 1) // 3 * 3 + 1, 1)
    secured = money.secured_by_year(payments, today)

    # Сигналы.
    debt = money.awaiting_act_by_insurer(payments, today)
    stale_cutoff = today - timedelta(days=AWAITING_ACT_SIGNAL_DAYS)
    stale = money._totals(
        money.awaiting_act_payments(payments).filter(paid_date__lt=stale_cutoff)
    )
    stale_insurers = [
        row["insurer"] for row in debt if row["oldest"] and row["oldest"] < stale_cutoff
    ]
    recent_loss_from = today - timedelta(days=RECENT_LOSS_DAYS - 1)
    recent_losses = money.sum_rows(
        money.lost_in_period(loss_rows, recent_loss_from, today)
    )
    ending = portfolio.ending_soon(policies, today).count()

    return {
        "today": today,
        "year_start": year_start,
        "year_end": date(today.year, 12, 31),
        "bridge": bridge,
        "lost_ytd": lost_ytd,
        "lost_undated": lost_undated,
        "ytd": {
            "current": ytd,
            "previous": ytd_previous,
            "change": _compare(
                ytd["commission"],
                ytd_previous["commission"],
                date(today.year - 1, 1, 1),
            ),
            "history_incomplete": not money.history_is_reliable(
                date(today.year - 1, 1, 1)
            ),
            "previous_from": date(today.year - 1, 1, 1),
            "previous_to": same_day_last_year(today),
        },
        "new_business_rows": [
            ("Месяц", _new_business_block(policies, today.replace(day=1), today)),
            ("Квартал", _new_business_block(policies, quarter_start, today)),
            ("Год", _new_business_block(policies, year_start, today)),
        ],
        "secured": secured,
        "secured_next_year": secured[0]
        if secured and secured[0]["year"] == today.year + 1
        else None,
        "signals": {
            "stale_act": {
                **stale,
                "days": AWAITING_ACT_SIGNAL_DAYS,
                "insurers": stale_insurers,
            },
            "ending_soon": {"count": ending, "days": portfolio.ENDING_SOON_DAYS},
            "recent_losses": {
                **recent_losses,
                "days": RECENT_LOSS_DAYS,
                "date_from": recent_loss_from,
            },
            "manager_drops": _manager_drops(policies, today),
            "lost_undated": lost_undated,
            "data_problems": data_quality.money_problem_count(params),
        },
    }
