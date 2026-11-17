"""Общие данные экранного отчёта, PDF и Excel для лизинговой компании."""
from datetime import timedelta
from decimal import Decimal
from django.utils import timezone
from apps.insurers.models import Branch
from apps.core.services.portfolio_scope import SCOPE_LABELS
from apps.core.services.reference_images import ReferenceImages
from .insured_value import insured_portfolio
from .property_report import (
    build_property_report,
    is_liability,
    _group,
    _totals,
    _matrix,
)

METHOD_VERSION = "2.0"


def build_property_document(as_of, branch_ids=(), structure_scope="all"):
    images = ReferenceImages()
    report = build_property_report(
        as_of,
        branch_ids,
        structure_scope,
        property_only=True,
        dynamics_rows_limit=None,
        images=images,
    )
    objects = insured_portfolio(as_of, branch_ids, structure_scope)
    property_objects = [o for o in objects if not is_liability(o)]
    liability = [o for o in objects if is_liability(o)]
    branch_images = {r["key"]: r["image_url"] for r in report["by_branch"]}
    managers = _group(
        [o for o in property_objects if o.manager_id],
        key=lambda o: o.manager_id,
        label=lambda o: f"{o.manager} ({o.branch})",
    )
    manager_branch = {}
    for obj in property_objects:
        manager_branch.setdefault(obj.manager_id, obj.branch_id)
    for row in managers:
        row["image_url"] = branch_images.get(manager_branch[row["key"]], "")
    report["all_managers"] = managers
    report["clients"] = _group(
        property_objects, key=lambda o: o.client_id, label=lambda o: o.client
    )
    report["liability"] = {
        **_totals(liability),
        "rows": [
            {
                "policy_number": o.policy_number,
                "dfa_number": o.dfa_number,
                "client": o.client,
                "insurer": o.insurer,
                "branch": o.branch,
                "insurer_image_url": images.get("insurer", o.insurer_id),
                "branch_image_url": images.get("branch", o.branch_id),
                "sum": o.insured_sum if o.insured_sum_known else None,
            }
            for o in liability
        ],
    }
    report["scope_total"] = report["totals"]["sum"] + report["liability"]["sum"]
    report["scope_count"] = len(objects)
    report["generated_at"] = timezone.localtime()
    report["methodology_version"] = METHOD_VERSION
    report["scope_label"] = SCOPE_LABELS[structure_scope]
    report["selected_branches"] = list(
        Branch.objects.filter(pk__in=branch_ids)
        .order_by("branch_name")
        .values_list("branch_name", flat=True)
    )
    report["renewals"] = []
    for days in (30, 60, 90):
        endings = [
            o
            for o in property_objects
            if as_of <= o.end_date <= as_of + timedelta(days=days)
        ]
        candidates = [
            o
            for o in endings
            if o.needs_prolongation
            and (not o.dfa_deactivation_date or o.dfa_deactivation_date > o.end_date)
            and (not o.termination_date or o.termination_date > o.end_date)
        ]
        report["renewals"].append(
            {
                "days": days,
                "endings": _totals(endings),
                "candidates": _totals(candidates),
            }
        )
    report["upcoming_objects"] = [
        o
        for o in sorted(
            property_objects,
            key=lambda o: (not o.insured_sum_known, -o.insured_sum, o.end_date, o.id),
        )
        if as_of <= o.end_date <= as_of + timedelta(days=90)
    ][:10]
    report["known_percent"] = (
        Decimal(100)
        * (report["totals"]["count"] - report["totals"]["missing_sum_count"])
        / report["totals"]["count"]
        if report["totals"]["count"]
        else None
    )
    report["full_branch_matrix"] = _matrix(
        property_objects,
        lambda o: o.branch_id,
        lambda o: o.branch,
        lambda o: o.insurer_id,
        lambda o: o.insurer,
    )
    matrix = report["full_branch_matrix"]
    images.attach(matrix["rows"], "branch")
    matrix["columns"] = [
        {"name": name, "image_url": images.get("insurer", pk)}
        for name, pk in zip(matrix["headers"], matrix.pop("column_keys"))
    ]
    report["history"] = []
    current_ids = {o.id for o in property_objects}
    for months in (3, 12):
        comparison = report["totals"][f"change_{months}m"]
        if comparison:
            old_objects = [
                o
                for o in insured_portfolio(
                    comparison["date"], branch_ids, structure_scope
                )
                if not is_liability(o)
            ]
            old_ids = {o.id for o in old_objects}
            report["history"].append(
                {
                    **comparison,
                    "months": months,
                    "entered": len(current_ids - old_ids),
                    "exited": len(old_ids - current_ids),
                    "previous_count": len(old_ids),
                    "missing_sum_count": sum(
                        not o.insured_sum_known for o in old_objects
                    ),
                }
            )
    return report
