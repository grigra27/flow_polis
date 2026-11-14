"""Dashboard 3.0: один срез портфеля, публичные показатели и рабочие списки.

Поля вознаграждения намеренно не выбираются из БД. Сервер формирует только
суммы страховой стоимости/премии и операционные показатели для любой роли.
"""

from collections import defaultdict
from datetime import timedelta
from decimal import Decimal

from django.urls import reverse
from django.utils import timezone

from apps.policies.models import PaymentSchedule, Policy, in_force_q
from apps.reports.services.insured_value import select_current_insured_sums

from .portfolio_scope import dfa_in_force_q
from .reference_images import ReferenceImages

ZERO = Decimal("0")
HUNDRED = Decimal("100")
COLORS = ["#2563eb", "#16a085", "#a78bda", "#e0a039", "#5ba5ce", "#9aa9bb"]
DIMENSIONS = (
    ("branch", "Филиалы"),
    ("insurer", "Страховщики"),
    ("type", "Виды страхования"),
)
TABS = (
    ("overview", "Обзор"),
    ("portfolio", "Портфель"),
    ("payments", "Платежи и продления"),
    ("quality", "Качество данных"),
)


def percent(part, total):
    return Decimal(part) / Decimal(total) * HUNDRED if total else ZERO


def amount(rows):
    return sum((r["amount"] for r in rows), ZERO)


def activity_score(x30, x60, x90):
    def ratio(a, b):
        return a / b if b else (Decimal("1.5") if a else Decimal("1"))

    daily = [Decimal(x) / n for x, n in zip((x30, x60, x90), (30, 60, 90))]
    momentum = Decimal("0.6") * ratio(daily[0], daily[1]) + Decimal("0.4") * ratio(
        daily[0], daily[2]
    )
    return HUNDRED * (
        min(Decimal("1.5"), max(Decimal("0.5"), momentum)) - Decimal("0.5")
    )


class DashboardV3Service:
    def __init__(self, scope):
        self.scope = scope
        self.today = scope.as_of
        self.images = ReferenceImages()
        self.queryset = scope.apply(Policy.objects.all())
        fields = (
            "id",
            "policy_number",
            "dfa_number",
            "client_id",
            "client__client_name",
            "branch_id",
            "branch__branch_name",
            "insurer_id",
            "insurer__insurer_name",
            "insurance_type_id",
            "insurance_type__name",
            "insurance_type__is_osago",
            "insurance_type__needs_prolongation",
            "start_date",
            "end_date",
            "termination_date",
            "policy_active",
            "policy_uploaded",
            "dfa_active",
            "dfa_deactivation_date",
            "created_at",
            "leasing_manager_id",
        )
        self.policies = {p["id"]: p for p in self.queryset.values(*fields)}
        self.payments = list(
            PaymentSchedule.objects.filter(policy__in=self.queryset)
            .values(
                "id",
                "policy_id",
                "year_number",
                "installment_number",
                "due_date",
                "amount",
                "insurance_sum",
                "paid_date",
            )
            .order_by("due_date", "id")
        )
        self.sum_rows = [
            (
                r["policy_id"],
                r["year_number"],
                r["installment_number"],
                r["due_date"],
                r["insurance_sum"],
            )
            for r in self.payments
        ]
        self._snapshots = {}
        self.active, self.property, self.sums = self.snapshot(self.today)
        self.current_payments = [
            p
            for p in self.payments
            if p["policy_id"] in self.active and self.payment_eligible(p)
        ]
        self.year_payments = [
            p for p in self.current_payments if p["due_date"].year == self.today.year
        ]
        self.unpaid = [p for p in self.current_payments if not self.is_paid(p)]
        self.overdue = [p for p in self.unpaid if p["due_date"] < self.today]
        self.upcoming = [
            p
            for p in self.unpaid
            if self.today <= p["due_date"] < self.today + timedelta(days=30)
        ]
        self.paid_recent = [
            p
            for p in self.current_payments
            if p["paid_date"]
            and self.today - timedelta(days=29) <= p["paid_date"] <= self.today
        ]
        self.missing_sum = self.property - self.sums.keys()
        self.missing_file = {
            pk for pk in self.property if not self.policies[pk]["policy_uploaded"]
        }
        self.conflicts = {
            pk
            for pk, p in self.policies.items()
            if p["start_date"] <= self.today
            and (
                (not p["policy_active"] and not p["termination_date"])
                or (
                    p["policy_active"]
                    and p["termination_date"]
                    and p["termination_date"] <= self.today
                )
                or (not p["dfa_active"] and not p["dfa_deactivation_date"])
                or (
                    p["dfa_active"]
                    and p["dfa_deactivation_date"]
                    and p["dfa_deactivation_date"] <= self.today
                )
            )
        }

    def snapshot(self, when):
        if when not in self._snapshots:
            active = set(
                self.queryset.filter(
                    in_force_q(when), dfa_in_force_q(when)
                ).values_list("pk", flat=True)
            )
            property_ids = {
                pk for pk in active if not self.policies[pk]["insurance_type__is_osago"]
            }
            sums = select_current_insured_sums(self.sum_rows, when)
            self._snapshots[when] = (
                active,
                property_ids,
                {pk: sums[pk] for pk in property_ids if pk in sums},
            )
        return self._snapshots[when]

    def is_paid(self, payment):
        return payment["paid_date"] is not None and payment["paid_date"] <= self.today

    def payment_eligible(self, payment):
        # Оплаченный взнос остаётся фактом. Из будущих обязательств убираем
        # известные взносы после расторжения полиса / закрытия ДФА.
        if self.is_paid(payment):
            return True
        policy = self.policies[payment["policy_id"]]
        return not (
            (
                policy["termination_date"]
                and payment["due_date"] >= policy["termination_date"]
            )
            or (
                policy["dfa_deactivation_date"]
                and payment["due_date"] > policy["dfa_deactivation_date"]
            )
        )

    def url(self, tab="overview", **extra):
        url = reverse("core:dashboard") + "?" + self.scope.query(tab=tab, **extra)
        return url + ("#dashboard-detail" if extra.get("detail") else "")

    def policy_row(self, pk):
        p = self.policies[pk]
        return {
            "id": pk,
            "number": p["policy_number"],
            "client": p["client__client_name"],
            "branch": p["branch__branch_name"],
            "branch_image_url": self.images.get("branch", p["branch_id"]),
            "insurer": p["insurer__insurer_name"],
            "insurer_image_url": self.images.get("insurer", p["insurer_id"]),
            "type": p["insurance_type__name"],
            "type_image_url": self.images.get("type", p["insurance_type_id"]),
            "date": p["end_date"],
            "amount": self.sums.get(pk),
            "value_note": self.unknown_sum_reason(pk) if pk in self.missing_sum else "",
            "url": reverse("policies:detail", args=[pk]),
        }

    def unknown_sum_reason(self, pk):
        rows = [p for p in self.payments if p["policy_id"] == pk]
        if not rows:
            return "Нет графика платежей"
        started = [p for p in rows if p["due_date"] <= self.today]
        if not started:
            first = min(p["due_date"] for p in rows)
            return f"Первый срок взноса {first:%d.%m.%Y} — после даты среза"
        year = max(p["year_number"] for p in started)
        first = next(
            (
                p
                for p in started
                if p["year_number"] == year and p["installment_number"] == 1
            ),
            None,
        )
        return (
            f"Нет первого взноса страхового года {year}"
            if first is None
            else f"Не заполнена СС страхового года {year}"
        )

    def payment_row(self, payment):
        return {
            **self.policy_row(payment["policy_id"]),
            "payment_id": payment["id"],
            "date": payment["due_date"],
            "amount": payment["amount"],
            "status": (
                "Оплачено"
                if self.is_paid(payment)
                else (
                    "Нет отметки об оплате"
                    if payment["due_date"] < self.today
                    else "Предстоит"
                )
            ),
            "paid_date": payment["paid_date"] if self.is_paid(payment) else None,
        }

    def distribution(self, dimension, measure):
        field, name_field = {
            "branch": ("branch_id", "branch__branch_name"),
            "insurer": ("insurer_id", "insurer__insurer_name"),
            "type": ("insurance_type_id", "insurance_type__name"),
        }[dimension]
        values = self.sums if measure == "sum" else defaultdict(lambda: ZERO)
        if measure == "premium":
            for payment in self.year_payments:
                values[payment["policy_id"]] += payment["amount"]
        grouped = {}
        ids = self.property if measure == "sum" else self.active
        for pk in ids:
            p = self.policies[pk]
            row = grouped.setdefault(
                p[field],
                {
                    "id": p[field],
                    "name": p[name_field],
                    "image_url": self.images.get(dimension, p[field]),
                    "amount": ZERO,
                    "count": 0,
                    "unknown": 0,
                },
            )
            row["amount"] += values.get(pk, ZERO)
            row["count"] += 1
            row["unknown"] += int(measure == "sum" and pk not in values)
        rows = sorted(grouped.values(), key=lambda r: (-r["amount"], r["name"]))
        total = amount(rows)
        for index, row in enumerate(rows):
            row.update(
                share=percent(row["amount"], total),
                color=COLORS[index % 5],
                url=self.url(
                    "portfolio",
                    detail="segment",
                    dimension=dimension,
                    measure=measure,
                    entity=row["id"],
                ),
            )
        chart = [dict(row) for row in rows[:5] if row["amount"] > ZERO]
        rest = rows[5:]
        if rest and amount(rest) > ZERO:
            chart.append(
                {
                    "name": "Прочие",
                    "amount": amount(rest),
                    "share": percent(amount(rest), total),
                    "color": COLORS[5],
                    "url": self.url(
                        "portfolio",
                        detail="segment",
                        dimension=dimension,
                        measure=measure,
                        entity="other",
                    ),
                }
            )
        cursor = ZERO
        segments = []
        for index, row in enumerate(chart):
            end = HUNDRED if index == len(chart) - 1 else cursor + row["share"]
            segments.append(f'{row["color"]} {cursor:.4f}% {end:.4f}%')
            cursor = end
        return {
            "key": dimension,
            "title": dict(DIMENSIONS)[dimension],
            "measure": measure,
            "rows": rows,
            "chart": chart,
            "total": total,
            "gradient": (
                f'conic-gradient({", ".join(segments)})'
                if segments
                else "conic-gradient(#e6edf5 0% 100%)"
            ),
        }

    def flow(self, days):
        before = self.today - timedelta(days=days)
        _, previous, sums = self.snapshot(before)
        previous_sum = sum(sums.values(), ZERO)
        current_sum = sum(self.sums.values(), ZERO)
        return {
            "days": days,
            "date": before,
            "entered": len(self.property - previous),
            "left": len(previous - self.property),
            "net": len(self.property) - len(previous),
            "previous_sum": previous_sum,
            "sum_delta": current_sum - previous_sum,
            "sum_percent": (
                percent(current_sum - previous_sum, previous_sum)
                if previous_sum
                else None
            ),
            "previous_unknown": len(previous - sums.keys()),
        }

    def activity(self):
        windows = []
        for days in (30, 60, 90):
            start = self.today - timedelta(days=days - 1)
            ids = {
                pk
                for pk, p in self.policies.items()
                if start <= p["start_date"] <= self.today
                and not p["insurance_type__is_osago"]
            }
            # Премия первого страхового года — сопоставимая база для одно-
            # и многолетних договоров; СС на выбранную дату, один раз.
            premium = amount(
                [
                    p
                    for p in self.payments
                    if p["policy_id"] in ids and p["year_number"] == 1
                ]
            )
            sums = select_current_insured_sums(self.sum_rows, self.today)
            windows.append(
                {
                    "days": days,
                    "count": len(ids),
                    "premium": premium,
                    "sum": sum((sums.get(pk, ZERO) for pk in ids), ZERO),
                    "unknown": len(ids - sums.keys()),
                }
            )
        components = []
        for key, title, weight in (
            ("count", "Полисы", 20),
            ("premium", "Премия первого года", 30),
            ("sum", "Страховая стоимость", 15),
        ):
            components.append(
                {
                    "key": key,
                    "title": title,
                    "weight": Decimal(weight) / 65,
                    "score": activity_score(*(w[key] for w in windows)),
                }
            )
        empty = not windows[-1]["count"]
        score = sum((c["score"] * c["weight"] for c in components), ZERO)
        label = (
            "Нет новых полисов"
            if empty
            else (
                "Снижение"
                if score < 45
                else "Ровная динамика"
                if score < 55
                else "Рост активности"
            )
        )
        return {
            "score": None if empty else score,
            "label": label,
            "components": components,
            "windows": windows,
        }

    def renewal_ids(self, days):
        limit = self.today + timedelta(days=days)
        return {
            pk
            for pk in self.active
            if self.policies[pk]["insurance_type__needs_prolongation"]
            and self.policies[pk]["end_date"] <= limit
            and (
                not self.policies[pk]["termination_date"]
                or self.policies[pk]["termination_date"]
                >= self.policies[pk]["end_date"]
            )
            and (
                not self.policies[pk]["dfa_deactivation_date"]
                or self.policies[pk]["dfa_deactivation_date"]
                > self.policies[pk]["end_date"]
            )
        }

    def context(self, tab="overview", measure="sum"):
        measure = measure if measure in {"sum", "premium"} else "sum"
        structure = [
            self.distribution(d, m) for m in ("sum", "premium") for d, _ in DIMENSIONS
        ]
        annual_paid = [p for p in self.year_payments if self.is_paid(p)]
        annual_overdue = [
            p
            for p in self.year_payments
            if not self.is_paid(p) and p["due_date"] < self.today
        ]
        annual_future = [
            p
            for p in self.year_payments
            if not self.is_paid(p) and p["due_date"] >= self.today
        ]
        annual_total = amount(self.year_payments)
        bridge = [
            {
                "label": label,
                "amount": amount(rows),
                "count": len(rows),
                "share": percent(amount(rows), annual_total),
                "color": color,
                "url": self.url("payments", detail=key),
            }
            for key, label, rows, color in (
                ("annual_paid", "Оплачено на дату среза", annual_paid, "#16a085"),
                (
                    "annual_overdue",
                    "Срок прошёл, оплаты нет",
                    annual_overdue,
                    "#d87055",
                ),
                ("annual_future", "Предстоящие взносы", annual_future, "#5291db"),
            )
        ]
        aging = []
        for start, end, label in (
            (1, 30, "1–30 дней"),
            (31, 60, "31–60 дней"),
            (61, 90, "61–90 дней"),
            (91, None, "Более 90 дней"),
        ):
            rows = [
                p
                for p in self.overdue
                if (self.today - p["due_date"]).days >= start
                and (end is None or (self.today - p["due_date"]).days <= end)
            ]
            aging.append(
                {
                    "label": label,
                    "count": len(rows),
                    "amount": amount(rows),
                    "share": percent(amount(rows), amount(self.overdue)),
                    "url": self.url("payments", detail="overdue", age=start),
                }
            )
        renewal = [
            {
                "days": days,
                "count": len(ids),
                "sum": sum((self.sums.get(pk, ZERO) for pk in ids), ZERO),
                "url": self.url("payments", detail=f"renewal_{days}"),
            }
            for days in (30, 60, 90)
            for ids in [self.renewal_ids(days)]
        ]
        max_renewal = max((r["count"] for r in renewal), default=0)
        for row in renewal:
            row["share"] = percent(row["count"], max_renewal)
        insurers = structure[1]["rows"]
        hhi = sum((r["share"] ** 2 for r in insurers), ZERO)
        quality_good = len(self.property - self.missing_sum - self.missing_file)
        problems = [
            {
                "key": key,
                "title": title,
                "count": len(ids),
                "url": self.url("quality", detail=key),
            }
            for key, title, ids in (
                ("missing_sum", "Не определена СС текущего года", self.missing_sum),
                ("missing_file", "Не подгружен полис", self.missing_file),
                ("conflicts", "Статусы требуют проверки", self.conflicts),
            )
        ]
        tasks = [
            {
                "title": "Срок оплаты прошёл",
                "count": len(self.overdue),
                "amount": amount(self.overdue),
                "url": self.url("payments", detail="overdue"),
                "tone": "danger",
            },
            {
                "title": "Взносы в ближайшие 30 дней",
                "count": len(self.upcoming),
                "amount": amount(self.upcoming),
                "url": self.url("payments", detail="upcoming"),
                "tone": "accent",
            },
            {
                "title": "Не подгружены полисы",
                "count": len(self.missing_file),
                "amount": None,
                "url": self.url("quality", detail="missing_file"),
                "tone": "warning",
            },
        ]
        context = {
            "scope": self.scope,
            "tab": tab,
            "measure": measure,
            "generated_at": timezone.now(),
            "historical": self.today < timezone.localdate(),
            "projected": self.today > timezone.localdate(),
            "tabs": [
                {"key": key, "title": title, "url": self.url(key, measure=measure)}
                for key, title in TABS
            ],
            "total_sum": sum(self.sums.values(), ZERO),
            "policy_count": len(self.property),
            "all_policy_count": len(self.active),
            "lessees": len({self.policies[pk]["client_id"] for pk in self.property}),
            "annual_premium": annual_total,
            "missing_sum_count": len(self.missing_sum),
            "structure": structure,
            "overview_charts": [s for s in structure if s["measure"] == measure],
            "sum_url": self.url(tab, measure="sum"),
            "premium_url": self.url(tab, measure="premium"),
            "policies_url": self.url("portfolio", detail="policies"),
            "annual_url": self.url("payments", detail="annual"),
            "snapshot_url": reverse("reports:property_snapshot_report")
            + "?"
            + self.scope.query(),
            "report_url": reverse("reports:property_report") + "?" + self.scope.query(),
            "excel_url": reverse("reports:property_report")
            + "?"
            + self.scope.query(format="xlsx"),
            "flows": [self.flow(days) for days in (30, 90)],
            "activity": self.activity(),
            "bridge": bridge,
            "aging": aging,
            "renewal": renewal,
            "concentration": {
                "hhi": hhi,
                "branch_hhi": sum(
                    (r["share"] ** 2 for r in structure[0]["rows"]), ZERO
                ),
                "branch_top1": (
                    structure[0]["rows"][0]["share"] if structure[0]["rows"] else ZERO
                ),
                "top1": insurers[0]["share"] if insurers else ZERO,
                "top3": sum((r["share"] for r in insurers[:3]), ZERO),
                "level": (
                    "Нет данных"
                    if not self.sums or not sum(self.sums.values(), ZERO)
                    else (
                        "Низкая"
                        if hhi < 1000
                        else "Умеренная"
                        if hhi < 1800
                        else "Высокая"
                    )
                ),
            },
            "quality_score": (
                percent(quality_good, len(self.property)) if self.property else None
            ),
            "quality_good": quality_good,
            "problems": problems,
            "tasks": tasks,
            "paid_recent": {
                "count": len(self.paid_recent),
                "amount": amount(self.paid_recent),
                "url": self.url("payments", detail="paid_recent"),
            },
            "recent_count": sum(
                1
                for p in self.policies.values()
                if self.today - timedelta(days=6)
                <= timezone.localdate(p["created_at"])
                <= self.today
            ),
            "recent_url": self.url("payments", detail="recent"),
        }
        if tab == "portfolio":
            from apps.reports.services.property_report import build_property_report

            context["property_report"] = build_property_report(
                self.today,
                self.scope.branch_ids,
                self.scope.structure_scope,
                images=self.images,
            )
        if tab == "payments":
            from apps.reports.services.property_report import _add_months, MONTH_SHORT

            months = []
            for offset in range(12):
                start = _add_months(self.today.replace(day=1), offset)
                end = _add_months(start, 1)
                ids = {
                    pk
                    for pk in self.active
                    if start <= self.policies[pk]["end_date"] < end
                }
                months.append(
                    {
                        "label": f"{MONTH_SHORT[start.month - 1]} {start:%y}",
                        "count": len(ids),
                        "sum": sum((self.sums.get(pk, ZERO) for pk in ids), ZERO),
                        "url": self.url(
                            "payments", detail="ending", month=start.isoformat()
                        ),
                    }
                )
            largest = max((m["sum"] for m in months), default=ZERO)
            for month in months:
                month["share"] = percent(month["sum"], largest)
            context["ending_months"] = months
        return context

    def detail(self, query):
        key = query.get("detail")
        payment_sets = {
            "annual": ("График премии выбранного года", self.year_payments),
            "upcoming": ("Взносы в ближайшие 30 дней", self.upcoming),
            "overdue": ("Срок прошёл — нет отметки об оплате", self.overdue),
            "paid_recent": ("Оплачено за последние 30 дней", self.paid_recent),
            "annual_paid": (
                "Годовой график: оплачено на дату среза",
                [p for p in self.year_payments if self.is_paid(p)],
            ),
            "annual_overdue": (
                "Годовой график: срок прошёл",
                [
                    p
                    for p in self.year_payments
                    if not self.is_paid(p) and p["due_date"] < self.today
                ],
            ),
            "annual_future": (
                "Годовой график: предстоит",
                [
                    p
                    for p in self.year_payments
                    if not self.is_paid(p) and p["due_date"] >= self.today
                ],
            ),
        }
        if key in payment_sets:
            title, payments = payment_sets[key]
            if key == "overdue" and query.get("age") in {"1", "31", "61", "91"}:
                age = int(query["age"])
                payments = [
                    p
                    for p in payments
                    if (self.today - p["due_date"]).days >= age
                    and (age == 91 or (self.today - p["due_date"]).days < age + 30)
                ]
            return {
                "title": title,
                "kind": "payment",
                "rows": [self.payment_row(p) for p in payments],
            }
        policy_sets = {
            "policies": ("Полисы имущественного портфеля", self.property),
            "missing_sum": ("Не определена СС текущего года", self.missing_sum),
            "missing_file": ("Не подгружены полисы", self.missing_file),
            "conflicts": ("Статусы требуют проверки", self.conflicts),
            "recent": (
                "Добавлено в систему за 7 дней",
                {
                    pk
                    for pk, p in self.policies.items()
                    if self.today - timedelta(days=6)
                    <= timezone.localdate(p["created_at"])
                    <= self.today
                },
            ),
        }
        for days in (30, 60, 90):
            policy_sets[f"renewal_{days}"] = (
                f"К продлению в течение {days} дней",
                self.renewal_ids(days),
            )
        if key == "segment":
            dimension = query.get("dimension", "branch")
            measure = query.get("measure", "sum")
            if dimension not in dict(DIMENSIONS) or measure not in {"sum", "premium"}:
                return None
            distribution = self.distribution(dimension, measure)
            selected = (
                distribution["rows"][5:]
                if query.get("entity") == "other"
                else [
                    r
                    for r in distribution["rows"]
                    if str(r["id"]) == query.get("entity")
                ]
            )
            entity_ids = {r["id"] for r in selected}
            field = {
                "branch": "branch_id",
                "insurer": "insurer_id",
                "type": "insurance_type_id",
            }[dimension]
            title = ", ".join(r["name"] for r in selected) or "Нет выбранных сегментов"
            if measure == "premium":
                return {
                    "title": title + " · годовая премия",
                    "kind": "payment",
                    "rows": [
                        self.payment_row(p)
                        for p in self.year_payments
                        if self.policies[p["policy_id"]][field] in entity_ids
                    ],
                }
            policy_sets[key] = (
                title,
                {pk for pk in self.property if self.policies[pk][field] in entity_ids},
            )
        if key == "ending":
            from datetime import date
            from apps.reports.services.property_report import _add_months

            try:
                month = date.fromisoformat(query.get("month", "")).replace(day=1)
            except ValueError:
                return None
            end = _add_months(month, 1)
            policy_sets[key] = (
                f"Окончание полисов · {month:%m.%Y}",
                {
                    pk
                    for pk in self.active
                    if month <= self.policies[pk]["end_date"] < end
                },
            )
        if key not in policy_sets:
            return None
        title, ids = policy_sets[key]
        return {
            "title": title,
            "kind": "policy",
            "rows": [
                self.policy_row(pk)
                for pk in sorted(
                    ids, key=lambda pk: (self.policies[pk]["end_date"], pk)
                )
            ],
        }
