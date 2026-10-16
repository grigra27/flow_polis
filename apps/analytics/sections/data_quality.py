"""
Вкладка «Качество данных»: какие ошибки в данных искажают аналитику
(docs/analytics-2.0-plan.md, §4 I). Каждая проверка — число и список для
исправления. Срез на сегодня, период не используется.
"""

from datetime import timedelta

from django.db.models import F, Min, Q

from apps.policies.models import PaymentSchedule

from .. import money, portfolio
from ..drilldown import PAYMENTS, POLICIES, metric

USES_PERIOD = False

# Полис закончился больше N дней назад, а ДФА всё ещё открыт и нового полиса
# по нему нет — скорее всего, ДФА забыли закрыть.
STALE_DFA_DAYS = 60
PAID_EARLY_DAYS = 180


def kv_zero(params):
    return params.payments().filter(kv_rub=0, amount__gt=0)


def dfa_closed_without_date(params):
    return params.all_policies().filter(
        dfa_active=False, dfa_deactivation_date__isnull=True
    )


def inactive_without_termination(params):
    return params.all_policies().filter(
        policy_active=False, termination_date__isnull=True
    )


def stale_open_dfa(params):
    cutoff = params.today - timedelta(days=STALE_DFA_DAYS)
    due = portfolio.renewal_due(
        params.all_policies(), money.HISTORY_RELIABLE_FROM, cutoff
    ).filter(dfa_active=True)
    statuses = portfolio.renewal_statuses(due)
    return due.filter(
        id__in=[
            pk for pk, s in statuses.items() if s["status"] == portfolio.NOT_RENEWED
        ]
    )


def missing_first_installment(params):
    broken = (
        PaymentSchedule.objects.filter(policy__in=params.all_policies())
        .values("policy_id", "year_number")
        .annotate(first=Min("installment_number"))
        .filter(first__gt=1)
        .values_list("policy_id", flat=True)
    )
    return params.all_policies().filter(id__in=list(broken))


def no_insurance_sum(params):
    return (
        params.all_payments()
        .filter(installment_number=1, policy__insurance_type__is_osago=False)
        .filter(Q(insurance_sum__isnull=True) | Q(insurance_sum=0))
    )


def paid_far_early(params):
    return params.all_payments().filter(
        paid_date__lt=F("due_date") - timedelta(days=PAID_EARLY_DAYS)
    )


def no_manager(params):
    return params.all_policies().filter(leasing_manager__isnull=True)


# (ключ, название, что делать, тип, функция, влияет на деньги)
CHECKS = [
    (
        "stale_open_dfa",
        f"ДФА открыт, полис закончился больше {STALE_DFA_DAYS} дней назад, нового полиса по ДФА нет",
        "Если лизинг закончился — снять «ДФА активен» и указать дату закрытия. "
        "Иначе это непродлённый полис. Искажает удержание и календарь окончаний.",
        POLICIES,
        stale_open_dfa,
        True,
    ),
    (
        "kv_zero",
        "КВ = 0 при участии брокера",
        "Проверить ставку КВ СК по виду страхования. Занижает заработанное и план.",
        PAYMENTS,
        kv_zero,
        True,
    ),
    (
        "dfa_closed_without_date",
        "ДФА закрыт без даты закрытия",
        "Указать дату закрытия ДФА. Без неё потери нельзя отнести к месяцу, "
        "а выкуп — к досрочному или плановому.",
        POLICIES,
        dfa_closed_without_date,
        True,
    ),
    (
        "inactive_without_termination",
        "Полис неактивен без даты расторжения",
        "Указать дату расторжения — иначе полис выпадает из исторических срезов.",
        POLICIES,
        inactive_without_termination,
        True,
    ),
    (
        "missing_first_installment",
        "В году полиса нет первого взноса",
        "Обычно это полисы, внесённые в базу без прошлых взносов. Добавить первый "
        "взнос года, если он важен: без него не считается тариф года.",
        POLICIES,
        missing_first_installment,
        False,
    ),
    (
        "no_insurance_sum",
        "Нет страховой суммы у первого взноса (кроме ОСАГО)",
        "Заполнить страховую сумму — иначе тариф не считается.",
        PAYMENTS,
        no_insurance_sum,
        False,
    ),
    (
        "paid_far_early",
        f"Оплачен раньше даты платежа больше чем на {PAID_EARLY_DAYS} дней",
        "Вероятная ошибка ввода даты оплаты или даты платежа.",
        PAYMENTS,
        paid_far_early,
        False,
    ),
    (
        "no_manager",
        "Не указан менеджер лизинга",
        "Заполнить менеджера — иначе полис не попадает в аналитику каналов.",
        POLICIES,
        no_manager,
        False,
    ),
]


def _register(key, title, hint, kind, func):
    metric(f"dq_{key}", title, kind, note=hint)(lambda params, opts: func(params))


for _key, _title, _hint, _kind, _func, _ in CHECKS:
    _register(_key, _title, _hint, _kind, _func)


def build(params, query=None):
    rows = []
    for key, title, hint, kind, func, affects_money in CHECKS:
        queryset = func(params)
        row = {
            "key": f"dq_{key}",
            "title": title,
            "hint": hint,
            "affects_money": affects_money,
            "count": queryset.count(),
            "is_payments": kind == PAYMENTS,
        }
        if kind == PAYMENTS:
            row["commission"] = money._totals(queryset)["commission"]
        rows.append(row)
    return {
        "rows": rows,
        "problems": sum(1 for row in rows if row["count"]),
        "money_problems": sum(row["count"] for row in rows if row["affects_money"]),
    }


def money_problem_count(params):
    """Число записей с проблемами, влияющими на деньги — для сигнала сводки."""
    return sum(
        func(params).count()
        for _, _, _, _, func, affects_money in CHECKS
        if affects_money
    )
