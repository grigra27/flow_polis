"""Ручная подтверждённая связь готового полиса со сделкой ЗС."""
import hashlib
import json
from datetime import datetime
from urllib.parse import urlencode

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core import signing
from django.db import transaction
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_http_methods

from .flow_permissions import explain_denial, require_access
from .models import FlowPolicySource, Policy
from .services import flow_client, flow_groups, flow_import
from .services.flow_matching import dfa_match

TOKEN_SALT = "policies.reverse-flow-link.v1"


def _access(request):
    if not settings.FLOW_HANDOFF_ENABLED:
        raise Http404
    require_access(request.user, link=True)


def _policy(pk):
    return get_object_or_404(
        Policy.objects.select_related("client", "insurer", "insurance_type"), pk=pk
    )


def _digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, default=str).encode()
    ).hexdigest()


def _policy_version(policy):
    return _digest(
        [
            [getattr(policy, field.attname) for field in policy._meta.concrete_fields],
            policy.client.client_name,
            policy.client.client_inn,
            policy.insurer.insurer_name,
            policy.insurance_type.name,
        ]
    )


def _plan_version(source):
    return _digest([source.mode, source.total, source.groups]) if source else None


def _source_url(summary_id):
    return f"{settings.FLOW_ZS_BASE_URL.rstrip('/')}/summaries/{summary_id}/"


def _accepted_label(value):
    try:
        accepted_at = datetime.fromisoformat(value)
        if timezone.is_aware(accepted_at):
            accepted_at = timezone.localtime(accepted_at)
        return accepted_at.strftime("%d.%m.%Y")
    except (TypeError, ValueError):
        return "—"


def _local_group_candidates(policy, q):
    """Only local plan hints; ZS filters their acceptance in the single search call."""
    matches = {}
    target = q or policy.dfa_number
    if not target or len(target) > 100:
        return matches
    sources = (
        FlowPolicySource.objects.exclude(groups=[])
        .only("summary_id", "groups")
        .order_by("-pk")
    )
    for source in sources.iterator():
        group = next(
            (
                g
                for g in source.groups
                if dfa_match(target, g.get("dfa", "")) in ("exact", "structure")
            ),
            None,
        )
        if group:
            matches[source.pk] = group["dfa"]
        if len(matches) == 20:
            break
    return matches


@never_cache
@login_required
@require_GET
@explain_denial
def search(request, pk):
    _access(request)
    policy = _policy(pk)
    q = request.GET.get("q", "").strip()
    context = {
        "policy": policy,
        "q": q,
        "candidates": [],
        "page": 1,
        "back_url": reverse("policies:detail", args=[pk]),
        "error": "",
    }
    status = 200
    try:
        page_text = request.GET.get("page", "1")
        if not page_text.isascii() or not page_text.isdigit() or len(page_text) > 6:
            raise flow_client.FlowError("Проверьте номер страницы поиска.")
        page = int(page_text)
        group_matches = _local_group_candidates(policy, q)
        data = flow_client.search_summaries(
            dfa=policy.dfa_number or "",
            inn=(policy.client.client_inn or "").strip(),
            q=q,
            page=page,
            summary_ids=list(group_matches),
        )
        candidates = list(data["results"])
        sources = {
            source.pk: source
            for source in FlowPolicySource.objects.filter(
                pk__in=[r["summary_id"] for r in candidates]
            ).prefetch_related("links")
        }
        for row in candidates:
            if row["summary_id"] in group_matches:
                row.update(
                    group_match=True,
                    group_dfa=group_matches[row["summary_id"]],
                    match_kind="group",
                    match_label="Совпал окончательный ДФА группы",
                )
            source = sources.get(row["summary_id"])
            links = list(source.links.all()) if source else []
            row.update(
                review_url=reverse(
                    "policies:link-zs-confirm", args=[pk, row["summary_id"]]
                ),
                source_url=_source_url(row["summary_id"]),
                linked_count=len(links),
                total=row["source_object_count"],
                mode=source.mode if source else "",
                covered_count=(
                    source.total if source.mode == "common" and links else len(links)
                )
                if source
                else 0,
                accepted_label=_accepted_label(row.get("accepted_at")),
            )
        context.update(candidates=candidates, page=page)
        base = reverse("policies:link-zs-search", args=[pk])
        if page > 1:
            context["previous_url"] = base + "?" + urlencode({"q": q, "page": page - 1})
        if data["has_next"]:
            context["next_url"] = base + "?" + urlencode({"q": q, "page": page + 1})
    except flow_client.FlowError as exc:
        context["error"] = str(exc)
        status = 503
    return render(request, "policies/flow_link_search.html", context, status=status)


def _comparisons(policy, snapshot):
    rows = []
    warnings = []
    for label, left, right, warn in (
        ("ДФА", policy.dfa_number, snapshot["dfa_number"], True),
        (
            "Лизингополучатель",
            policy.client.client_name,
            snapshot["client_name"],
            False,
        ),
        ("ИНН", policy.client.client_inn, snapshot["client_inn"], True),
        ("Страховщик", policy.insurer.insurer_name, snapshot["selected_company"], True),
        (
            "Вид страхования",
            policy.insurance_type.name,
            flow_import.TYPE_NAMES.get(
                snapshot["insurance_type"], snapshot["insurance_type"]
            ),
            True,
        ),
        (
            "Объект",
            policy.property_description,
            snapshot["property_description"],
            False,
        ),
    ):
        different = (
            " ".join((left or "").split()).casefold()
            != " ".join((right or "").split()).casefold()
        )
        rows.append(
            dict(
                label=label,
                policy_value=left or "—",
                source_value=right or "—",
                different=different,
            )
        )
        if different and warn:
            warnings.append(
                f"{label} в полисе и сделке отличается. Проверьте соответствие по документам."
            )
    return rows, warnings


def _slots(policy, snapshot, source):
    total = snapshot["source_object_count"]
    links = list(source.links.select_related("policy")) if source else []
    occupied = {link.slot: link for link in links}
    common = occupied.get(0)
    groups = source.groups if source else []
    # An empty source may be reset by the existing registration service.
    mode = source.mode if source and (links or groups) else None
    values = ([0] if mode != "separate" else []) + (
        list(range(1, total + 1)) if total > 1 and mode != "common" else []
    )
    rows = []
    for slot in values:
        link = common or occupied.get(slot)
        group = flow_groups.group_for(groups, slot)
        reason = ""
        if link:
            reason = (
                "Позиция уже связана с этим полисом."
                if link.policy_id == policy.pk
                else "Позиция уже связана с другим полисом."
            )
        elif source and (links or groups) and source.total != total:
            reason = "Количество объектов в своде изменилось. Проверьте план в ЗС."
        elif group and group["revision"] != snapshot["revision"]:
            reason = "Условия свода изменились. Подтвердите план группы из ЗС."
        elif group and dfa_match(policy.dfa_number, group["dfa"]) not in (
            "exact",
            "structure",
        ):
            reason = "ДФА полиса отличается от окончательного ДФА этой группы."
        label = (
            ("Один общий полис на все объекты" if total > 1 else "Полис по сделке")
            if slot == 0
            else f"Объект {slot} из {total}"
        )
        if group:
            label += f" · ДФА {group['dfa']}"
        rows.append(
            dict(
                value=slot,
                label=label,
                occupied=bool(link),
                disabled=bool(reason),
                reason=reason,
                policy_id=link.policy_id if link else None,
                policy_number=link.policy.policy_number if link else "",
            )
        )
    return rows, links


def _context(request, policy, snapshot, *, error="", selected_slot=None):
    source = FlowPolicySource.objects.filter(pk=snapshot["summary_id"]).first()
    rows, links = _slots(policy, snapshot, source)
    comparisons, warnings = _comparisons(policy, snapshot)
    available = [row["value"] for row in rows if not row["disabled"]]
    already_linked = any(link.policy_id == policy.pk for link in links)
    if selected_slot is None and len(available) == 1:
        selected_slot = available[0]
    payload = {
        "user": request.user.pk,
        "policy": policy.pk,
        "summary": snapshot["summary_id"],
        "policy_version": _policy_version(policy),
        "revision": snapshot["revision"],
        "plan_version": _plan_version(source),
        "slots": available,
    }
    return {
        "policy": policy,
        "source": snapshot,
        "source_url": _source_url(snapshot["summary_id"]),
        "back_url": reverse("policies:detail", args=[policy.pk]),
        "search_url": reverse("policies:link-zs-search", args=[policy.pk]),
        "comparisons": comparisons,
        "warnings": warnings,
        "slots": rows,
        "available_slots": [row for row in rows if not row["disabled"]],
        "unavailable_slots": [row for row in rows if row["disabled"]],
        "selected_slot": selected_slot,
        "already_linked": already_linked,
        "can_confirm": bool(available) and not already_linked,
        "error": error,
        "confirmation_token": signing.dumps(payload, salt=TOKEN_SALT, compress=True),
        "accepted_label": _accepted_label(snapshot.get("accepted_at")),
    }


@transaction.atomic
def _save(policy, snapshot, user, payload, slot):
    total = snapshot["source_object_count"]
    source, created = FlowPolicySource.objects.select_for_update().get_or_create(
        pk=snapshot["summary_id"],
        defaults={"mode": "separate" if slot else "common", "total": total},
    )
    existing = source.links.filter(slot=slot).first()
    if existing:
        if existing.policy_id == policy.pk:
            return
        raise flow_client.FlowError(
            "Эта позиция уже занята другим полисом. Выберите свободный объект."
        )
    if source.links.filter(policy_id=policy.pk).exists():
        raise flow_client.FlowError(
            "Этот полис уже связан с другой позицией выбранного свода."
        )
    if (None if created else _plan_version(source)) != payload["plan_version"]:
        raise flow_client.FlowError(
            "План объектов изменился. Проверьте актуальные позиции и подтвердите ещё раз."
        )
    locked = Policy.objects.select_for_update().get(pk=policy.pk)
    if _policy_version(locked) != payload["policy_version"]:
        raise flow_client.FlowError(
            "Полис изменился после сверки. Проверьте актуальные данные и подтвердите ещё раз."
        )
    if not source.groups and not source.links.exists():
        mode = "separate" if slot else "common"
        if source.mode != mode:
            source.mode = mode
            source.save(update_fields=["mode"])
    group = flow_groups.group_for(source.groups, slot)
    # Exact target policy is fixed. A different source DFA is an explicitly reviewed
    # association; range plans still restrict their final DFA independently.
    effective_dfa = group["dfa"] if group else locked.dfa_number
    if not flow_import.normalize_dfa(effective_dfa):
        raise flow_client.FlowError(
            "Укажите окончательный ДФА в полисе перед привязкой."
        )
    result, _ = flow_import.save_linked_policy(
        snapshot,
        slot,
        user,
        existing_policy=locked,
        dfa_number=effective_dfa,
        group_version=group["version"] if group else None,
        reviewed_dfa_format=True,
    )
    if result.pk != policy.pk:
        raise flow_client.FlowError("Позиция уже занята другим полисом.")


@never_cache
@login_required
@require_http_methods(["GET", "POST"])
@explain_denial
def confirm(request, pk, summary_id):
    _access(request)
    policy = _policy(pk)
    snapshot = None
    status = 200
    selected_slot = None
    try:
        snapshot = flow_client.fetch_snapshot(summary_id)
        if request.method == "POST":
            try:
                payload = signing.loads(
                    request.POST.get("confirmation_token", ""),
                    salt=TOKEN_SALT,
                    max_age=900,
                )
                selected_slot = int(request.POST.get("slot", ""))
                if not isinstance(payload, dict) or (
                    payload.get("user"),
                    payload.get("policy"),
                    payload.get("summary"),
                ) != (request.user.pk, pk, summary_id):
                    raise ValueError
                if selected_slot not in payload["slots"]:
                    raise ValueError
            except (signing.BadSignature, ValueError, KeyError, TypeError):
                raise flow_client.FlowError(
                    "Подтверждение устарело или изменено. Повторите сверку сделки."
                ) from None
            if snapshot["revision"] != payload["revision"]:
                raise flow_client.FlowError(
                    "Сделка изменилась после сверки. Проверьте обновлённые данные."
                )
            if request.POST.get("confirm") != "yes":
                raise flow_client.FlowError(
                    "Подтвердите связь выбранного полиса со сделкой."
                )
            _, warnings = _comparisons(policy, snapshot)
            if warnings and request.POST.get("acknowledge") != "yes":
                raise flow_client.FlowError(
                    "Подтвердите, что проверили различия между полисом и сделкой."
                )
            _save(policy, snapshot, request.user, payload, selected_slot)
            messages.success(request, "Полис связан со сделкой ЗС.")
            return redirect("policies:detail", pk=pk)
        context = _context(request, policy, snapshot)
    except flow_client.FlowError as exc:
        status = 409
        if snapshot:
            context = _context(
                request,
                _policy(pk),
                snapshot,
                error=str(exc),
                selected_slot=selected_slot,
            )
        else:
            context = {
                "policy": policy,
                "source": None,
                "error": str(exc),
                "can_confirm": False,
                "search_url": reverse("policies:link-zs-search", args=[pk]),
                "back_url": reverse("policies:detail", args=[pk]),
            }
    return render(request, "policies/flow_link_confirm.html", context, status=status)
