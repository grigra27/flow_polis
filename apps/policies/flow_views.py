"""Переход из акцептованного свода в журнал полисов."""
from datetime import date
from decimal import Decimal, InvalidOperation
from time import time
from uuid import uuid4

from django.conf import settings
from django import forms
from django.core.exceptions import ValidationError
from django.contrib import messages
from django.contrib import admin
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import redirect_to_login
from django.http import Http404
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_http_methods

from .flow_permissions import can_create, can_link, explain_denial, require_access
from .models import FlowPolicySource, Policy
from .services import flow_client, flow_groups, flow_import

DRAFTS = "flow_policy_drafts"
PENDING = "flow_pending_tickets"
MAX_PENDING_TICKETS = 10


def available():
    if not settings.FLOW_HANDOFF_ENABLED:
        raise Http404


def put_draft(request, key, draft):
    drafts = request.session.get(DRAFTS, {})
    drafts[key] = draft
    request.session[DRAFTS] = drafts


def get_draft(request, key):
    available()
    require_access(request.user)
    draft = request.session.get(DRAFTS, {}).get(str(key))
    if not draft or draft["user_id"] != request.user.pk:
        raise Http404("Откройте свод в ЗС и начните оформление заново.")
    return draft


def review_url(key):
    return reverse("flow_policy_review", args=[key])


def source_url(summary_id):
    return f"{settings.FLOW_ZS_BASE_URL.rstrip('/')}/summaries/{summary_id}/"


def groups_for(snapshot):
    return (
        FlowPolicySource.objects.filter(
            pk=snapshot["summary_id"], total=snapshot["source_object_count"]
        )
        .values_list("groups", flat=True)
        .first()
        or []
    )


def form_draft(draft, slot, groups, reviewed_ids=None):
    snapshot = draft["snapshot"]
    group = flow_groups.group_for(groups, slot)
    if group and group["revision"] != snapshot["revision"]:
        raise flow_client.FlowError(
            "Условия акцепта обновились. Подтвердите диапазон в группах ДФА."
        )
    search_dfa = draft.get("search_dfa", draft["dfa"])
    return dict(
        draft,
        slot=slot,
        reviewed_ids=reviewed_ids,
        dfa=group["dfa"] if group else search_dfa,
        search_dfa=search_dfa,
        group=group,
    )


def form_url(key):
    return reverse("policies:flow-add", query={"flow_draft": key})


@never_cache
@login_required
@require_http_methods(["GET", "POST"])
@explain_denial
def add(request):
    require_access(request.user, create=True)
    if not request.GET.get("flow_draft"):
        raise Http404
    return admin.site.get_model_admin(Policy).add_view(request)


def error_page(request, error, *, draft_key=None):
    return render(
        request,
        "policies/flow_error.html",
        {
            "error": str(error),
            "form_url": form_url(draft_key) if draft_key else "",
            "review_url": review_url(draft_key) if draft_key else "",
        },
        status=409,
    )


def pending_tickets(request):
    now = time()
    return {
        key: row
        for key, row in request.session.get(PENDING, {}).items()
        if row["expires_at"] > now
    }


def continuation_url(key):
    # Локальный ключ находит код только в сессии браузера, начавшего переход.
    return reverse("flow_policy_landing", query={"continue": key})


@never_cache
@require_GET
@explain_denial
def landing(request):
    available()
    if request.user.is_authenticated:
        require_access(request.user)
    pending = pending_tickets(request)
    code = request.GET.get("code")
    if code:
        if len(code) > 512:
            raise Http404
        key = uuid4().hex
        while len(pending) >= MAX_PENDING_TICKETS:
            del pending[next(iter(pending))]
        pending[key] = {"code": code, "expires_at": int(time()) + 600}
        request.session[PENDING] = pending
        response = redirect(continuation_url(key))
        response["Referrer-Policy"] = "no-referrer"
        return response
    key = request.GET.get("continue", "")
    if key not in pending:
        return error_page(request, "Откройте «Создать полис» в исходном своде ЗС.")
    if not request.user.is_authenticated:
        return redirect_to_login(continuation_url(key), reverse("accounts:login"))
    code = pending[key]["code"]
    try:
        snapshot = flow_client.exchange_ticket(code)
    except flow_client.FlowError as error:
        return error_page(request, error)
    del pending[key]
    request.session[PENDING] = pending
    key = uuid4().hex
    drafts = request.session.get(DRAFTS, {})
    for old_key in list(drafts)[:-9]:
        drafts.pop(old_key)
    request.session[DRAFTS] = drafts
    draft = {
        "user_id": request.user.pk,
        "snapshot": snapshot,
        "dfa": snapshot["dfa_number"],
        "slot": None,
    }
    links = flow_import.links_for(snapshot["summary_id"])
    if (
        snapshot["source_object_count"] == 1
        and snapshot["offers"]
        and snapshot["variant"]
        and can_create(request.user)
        and not links.exists()
        and not flow_import.candidate_policies(draft["dfa"]).exists()
    ):
        draft.update(slot=0, reviewed_ids="")
        put_draft(request, key, draft)
        return redirect(form_url(key))
    put_draft(request, key, draft)
    return redirect(review_url(key))


def check_revision(request, key, draft):
    fresh = flow_client.fetch_snapshot(draft["snapshot"]["summary_id"])
    if fresh["revision"] == draft["snapshot"]["revision"]:
        return True
    draft["previous"] = draft["snapshot"]
    if draft["dfa"] == draft["snapshot"]["dfa_number"]:
        draft["dfa"] = fresh["dfa_number"]
    if draft.get("search_dfa") == draft["snapshot"]["dfa_number"]:
        draft["search_dfa"] = fresh["dfa_number"]
    draft.update(snapshot=fresh, slot=None)
    draft.pop("reviewed_ids", None)
    put_draft(request, key, draft)
    messages.warning(request, "Условия акцепта изменились. Сверьте обновлённые данные.")
    return False


def get_slot(value, total):
    try:
        slot = int(value)
    except (TypeError, ValueError):
        raise flow_client.FlowError("Выберите общий полис или номер объекта.")
    if slot < 0 or slot > total or (total == 1 and slot != 0):
        raise flow_client.FlowError("Проверьте номер объекта.")
    return slot


def free_slots(total, used):
    if total == 1 or 0 in used:
        return []
    return [slot for slot in range(1, total + 1) if slot not in used]


def review_context(request, key, draft, error=None):
    source = draft["snapshot"]
    links = list(flow_import.links_for(source["summary_id"]).select_related("policy"))
    total = source["source_object_count"]
    used = {link.slot for link in links}
    slots = free_slots(total, used)
    groups = groups_for(source) if total > 1 else []
    selected = draft.get("selected_slot")
    if selected not in slots:
        selected = slots[0] if groups and slots else None
    group = flow_groups.group_for(groups, selected) if selected else None
    search_dfa = group["dfa"] if group else draft.get("search_dfa", draft["dfa"])
    candidates = list(
        flow_import.candidate_policies(
            search_dfa, exclude_summary_id=source["summary_id"]
        ).prefetch_related("flow_links")
    )
    return {
        "changes": source_changes(draft.get("previous"), source),
        "source": source,
        "draft": draft,
        "key": key,
        "links": links,
        "candidates": candidates,
        "error": error,
        "can_create": can_create(request.user),
        "can_link": can_link(request.user),
        "slots": slots,
        "selected_slot": selected,
        "search_dfa": search_dfa,
        "has_selected_group": bool(group),
        "groups": groups,
        "plan_version": flow_groups.plan_version(groups),
        "source_url": source_url(source["summary_id"]),
        "allow_common": not links and not groups,
        "total": total,
        "variant_url": f"{settings.FLOW_ZS_BASE_URL.rstrip('/')}/summaries/{source['summary_id']}/policy/variant/",
        "candidate_mark": candidate_mark(candidates),
    }


def candidate_mark(candidates):
    # Публичные ID позволяют обнаружить добавленный договор между просмотром и POST.
    return ",".join(str(pk) for pk in sorted(p.pk for p in candidates))


@never_cache
@require_http_methods(["GET", "POST"])
@explain_denial
def review(request, key):
    draft = get_draft(request, key)
    source = draft["snapshot"]
    if request.method == "GET" and "sample" in request.GET:
        require_access(request.user, create=True)
        pk = request.GET["sample"]
        if not pk.isascii() or not pk.isdigit() or len(pk) > 18:
            raise Http404
        sample = (
            flow_import.links_for(source["summary_id"])
            .filter(policy_id=int(pk), revision=source["revision"])
            .select_related(
                "policy__client",
                "policy__insurer",
                "policy__insurance_type",
                "policy__policyholder",
                "policy__branch",
                "policy__leasing_manager",
            )
            .first()
        )
        if not sample:
            raise Http404
        return render(request, "policies/flow_sample.html", {"policy": sample.policy})
    error = None
    try:
        context = review_context(request, key, draft)
        if request.method == "GET":
            if len(context["links"]) == 1 and context["links"][0].slot == 0:
                return redirect("policies:detail", pk=context["links"][0].policy_id)
        else:
            action = request.POST.get("action")
            if action in ("plan", "remove-group"):
                require_access(request.user, create=True)
                if check_revision(request, key, draft):
                    flow_groups.edit_plan(
                        source, request.POST, remove=action == "remove-group"
                    )
                return redirect(review_url(key))
            if action == "select":
                draft["selected_slot"] = get_slot(
                    request.POST.get("slot"), context["total"]
                )
                put_draft(request, key, draft)
                return redirect(review_url(key))
            if action == "search":
                draft["dfa"] = request.POST.get("dfa", "").strip()[:100]
                draft["search_dfa"] = draft["dfa"]
                draft["slot"] = None
                put_draft(request, key, draft)
                return redirect(review_url(key))
            slot = get_slot(request.POST.get("slot"), context["total"])
            if action == "link":
                require_access(request.user, link=True)
            elif action == "new":
                require_access(request.user, create=True)
            else:
                raise Http404
            if not check_revision(request, key, draft):
                return redirect(review_url(key))
            selected_group = flow_groups.group_for(context["groups"], slot)
            effective_dfa = (
                selected_group["dfa"]
                if selected_group
                else draft.get("search_dfa", draft["dfa"])
            )
            if effective_dfa != context["search_dfa"]:
                draft["selected_slot"] = slot
                put_draft(request, key, draft)
                return redirect(review_url(key))
            if request.POST.get("candidates", "") != context["candidate_mark"]:
                raise flow_client.FlowError(
                    "Список полисов по ДФА изменился. Проверьте совпадения ещё раз."
                )
            existing = next(
                (
                    link
                    for link in context["links"]
                    if link.slot == slot or link.slot == 0
                ),
                None,
            )
            if existing:
                return redirect("policies:detail", pk=existing.policy_id)
            if not context["allow_common"] and slot == 0:
                raise flow_client.FlowError(
                    "По своду уже оформляются отдельные полисы."
                )
            if action == "link":
                policy_id = request.POST.get("policy_id", "")
                candidate = next(
                    (p for p in context["candidates"] if str(p.pk) == policy_id), None
                )
                if not candidate:
                    raise flow_client.FlowError("Выберите полис из списка по ДФА.")
                policy, _ = flow_import.save_linked_policy(
                    source,
                    slot,
                    request.user,
                    existing_policy=candidate,
                    dfa_number=effective_dfa,
                    group_version=selected_group["version"] if selected_group else None,
                )
                return redirect("policies:detail", pk=policy.pk)
            if not source.get("variant") or not source["offers"]:
                raise flow_client.FlowError(
                    "Для создания выберите вариант с премией в ЗС."
                )
            form_key = uuid4().hex
            put_draft(
                request,
                form_key,
                form_draft(draft, slot, context["groups"], context["candidate_mark"]),
            )
            return redirect(form_url(form_key))
    except flow_client.FlowError as exc:
        error = str(exc)
    context = review_context(request, key, draft, error) if error else context
    return render(
        request, "policies/flow_review.html", context, status=409 if error else 200
    )


class InvalidPolicyForm(Exception):
    """Откатить создание записи источника и показать ошибки штатной формы."""

    def __init__(self, response):
        self.response = response


EDITABLE_FIELDS = (
    "policy_number",
    "dfa_number",
    "client",
    "policyholder",
    "insurer",
    "insurance_type",
    "branch",
    "leasing_manager",
    "property_description",
    "property_year",
    "vin_number",
    "start_date",
    "end_date",
    "franchise",
    "info3",
    "info4",
    "termination_date",
    "dfa_deactivation_date",
)
PAYMENT_FIELDS = (
    "due_date",
    "amount",
    "insurance_sum",
    "kv_rub",
    "payment_info",
    "paid_date",
    "insurer_date",
)


def same_value(field, entered, original):
    if field in (
        "start_date",
        "end_date",
        "due_date",
        "paid_date",
        "insurer_date",
        "termination_date",
        "dfa_deactivation_date",
    ):
        try:
            date_field = forms.DateField()
            return date_field.to_python(entered) == date_field.to_python(original)
        except ValidationError:
            return False
    if field in ("franchise", "amount", "insurance_sum", "kv_rub"):
        if original not in (None, "") and entered not in (None, ""):
            try:
                return Decimal(entered) == Decimal(str(original))
            except InvalidOperation:
                pass
    return entered == ("" if original is None else str(original))


def posted_rows(post, prefix):
    try:
        count = int(post.get(prefix + "-TOTAL_FORMS", 0))
    except ValueError:
        count = 0
    for idx in range(min(count, 1000)):
        yield f"{prefix}-{idx}-"


def typed_edits(post, initial, slot):
    """Keep manual edits and schedule rows independently of the source revision."""
    policy = {}
    for field in EDITABLE_FIELDS:
        if field in post and not same_value(
            field, post[field], initial["policy"].get(field)
        ):
            policy[field] = post[field]
    for field, default in (
        ("dfa_active", True),
        ("policy_active", True),
        ("broker_participation", True),
        ("policy_uploaded", False),
        ("renewal_to_old_dfa", False),
    ):
        if (field in post) != default:
            policy[field] = field in post
    original = {
        (str(p["year_number"]), str(p["installment_number"])): p
        for p in initial["payments"]
    }
    changes, extra, present = {}, [], set()
    for prefix in posted_rows(post, "payment_schedule"):
        identity = (
            post.get(prefix + "year_number"),
            post.get(prefix + "installment_number"),
        )
        if not all(identity) or post.get(prefix + "DELETE"):
            continue
        key = "/".join(identity)
        present.add(key)
        edited = {
            field: post[prefix + field]
            for field in PAYMENT_FIELDS
            if prefix + field in post
            and not same_value(
                field, post[prefix + field], original.get(identity, {}).get(field)
            )
        }
        if post.get(prefix + "alliance_paid"):
            edited["alliance_paid"] = True
        if identity in original:
            changes[key] = edited
        else:
            extra.append(
                dict(edited, year_number=identity[0], installment_number=identity[1])
            )
    removed = sorted("/".join(k) for k in original if "/".join(k) not in present)
    tags = [
        {"info_field": post.get(prefix + "info_field"), "tag": post[prefix + "tag"]}
        for prefix in posted_rows(post, "info_tags")
        if post.get(prefix + "tag") and not post.get(prefix + "DELETE")
    ]
    return {
        "policy": policy,
        "rows": changes,
        "extra": extra,
        "removed": removed,
        "tags": tags,
        "slot": slot,
    }


def apply_edits(initial, edits):
    initial["policy"].update(edits["policy"])
    restored = []
    for row in initial["payments"]:
        identity = f"{row['year_number']}/{row['installment_number']}"
        if identity not in edits["removed"]:
            row.update(edits["rows"].get(identity, {}))
            restored.append(row)
    indexes = {
        (str(row["year_number"]), str(row["installment_number"])): row
        for row in restored
    }
    for row in edits["extra"]:
        identity = (row["year_number"], row["installment_number"])
        if identity in indexes:
            indexes[identity].update(row)
        else:
            restored.append(row)
    initial["payments"] = restored
    initial["tags"] = edits["tags"]


def source_extras(snapshot):
    labels = {
        "transport_cost": "Стоимость перевозки (отдельная оплата)",
        "transport_terms": "Условия перевозки",
        "smr_cost": "Стоимость СМР",
        "smr_terms": "Условия СМР",
        "smr_status": "СМР",
        "coverage_territory": "Территория",
        "notes": "Примечания страховщика",
        "deal_note": "Примечание к акцепту",
        "inspection_status": "Осмотр",
        "rnpk_status": "Риски РНПК",
        "ce_risks_status": "Риски C/E",
        "ce_risks_comment": "Условия C/E",
        "osvr_status": "Риски ОСВР",
        "osvr_terms": "Условия ОСВР",
    }
    extras = snapshot.get("extras", {})
    return [
        (label, extras.get(key + "_display") or extras[key])
        for key, label in labels.items()
        if extras.get(key) not in (None, "")
    ]


def source_changes(previous, current):
    if not previous:
        return []
    fields = (
        ("dfa_number", "ДФА"),
        ("client_name", "Клиент"),
        ("client_inn", "ИНН"),
        ("branch", "Филиал"),
        ("insurance_type", "Вид страхования"),
        ("selected_company", "Страховщик"),
        ("variant", "Выбранный вариант"),
        ("insured_party", "Страхователь"),
        ("manager_name", "Менеджер лизинга"),
        ("property_description", "Объект"),
        ("property_year", "Год выпуска"),
        ("source_object_count", "Количество одинаковых объектов"),
        ("insurance_period", "Срок страхования"),
        ("lease_start_date", "Начало лизинга"),
        ("lease_end_date", "Окончание лизинга"),
    )
    changes = [
        (label, previous.get(key), current.get(key))
        for key, label in fields
        if previous.get(key) != current.get(key)
    ]
    old_years = {row["year"]: row for row in previous["offers"]}
    new_years = {row["year"]: row for row in current["offers"]}
    for year in sorted(set(old_years) | set(new_years)):
        before, after = old_years.get(year, {}), new_years.get(year, {})
        for key, label in (
            ("premium", "премия"),
            ("insurance_sum", "страховая сумма"),
            ("franchise", "франшиза"),
            ("installments", "число взносов"),
        ):
            if before.get(key) != after.get(key):
                changes.append(
                    (f"{year} год, {label}", before.get(key), after.get(key))
                )
    old_extras, new_extras = dict(source_extras(previous)), dict(source_extras(current))
    changes.extend(
        (label, old_extras.get(label), new_extras.get(label))
        for label in sorted(set(old_extras) | set(new_extras))
        if old_extras.get(label) != new_extras.get(label)
    )
    return changes


def confirm_candidates(request, key, dfa, candidates, mark, error=""):
    hidden = [
        (name, value)
        for name, values in request.POST.lists()
        if name not in {"csrfmiddlewaretoken", "_flow_confirm", "_flow_link"}
        for value in values
    ]
    return render(
        request,
        "policies/flow_confirm.html",
        {
            "dfa": dfa,
            "candidates": candidates,
            "mark": mark,
            "hidden": hidden,
            "can_link": can_link(request.user),
            "review_url": review_url(key),
            "error": error,
        },
        status=409 if error else 200,
    )


def redirect_after_save(request, key, draft, policy, created):
    if not (created and draft["slot"] and "_flow_next" in request.POST):
        return redirect("policies:detail", pk=policy.pk)
    source = draft["snapshot"]
    used = set(
        flow_import.links_for(source["summary_id"]).values_list("slot", flat=True)
    )
    slots = free_slots(source["source_object_count"], used)
    if not slots:
        return redirect("policies:detail", pk=policy.pk)
    next_key = uuid4().hex
    next_draft = {
        "user_id": request.user.pk,
        "snapshot": source,
        "dfa": source["dfa_number"],
        "slot": slots[0],
    }
    # Повтор того же POST возвращает ту же форму. Новая позиция получает
    # реквизиты свода, даже если менеджер изменил конечный ДФА у предыдущей.
    draft["next_key"] = next_key
    put_draft(request, key, draft)
    groups = groups_for(source)
    next_group = flow_groups.group_for(groups, slots[0])
    if next_group and next_group["revision"] != source["revision"]:
        next_draft["slot"] = None
        put_draft(request, next_key, next_draft)
        return redirect(review_url(next_key))
    put_draft(request, next_key, form_draft(next_draft, slots[0], groups))
    messages.success(
        request, f"Объект {draft['slot']} оформлен. Полис {policy.policy_number}."
    )
    return redirect(form_url(next_key))


@explain_denial
def flow_admin_add(request, key, show_form):
    draft = get_draft(request, key)
    require_access(request.user, create=True)
    slot = draft["slot"]
    if slot is None:
        return redirect(review_url(key))
    source = draft["snapshot"]
    used = dict(
        flow_import.links_for(source["summary_id"]).values_list("slot", "policy_id")
    )
    linked_id = used.get(slot) or used.get(0)
    if linked_id:
        if (
            "_flow_next" in request.POST
            and draft.get("next_key") in request.session[DRAFTS]
        ):
            return redirect(form_url(draft["next_key"]))
        return redirect("policies:detail", pk=linked_id)
    initial = flow_import.prepare_initial(source, slot=slot)
    group = draft.get("group")
    if group and group.get("template"):
        initial["policy"].update(group["template"]["policy"])
        initial["payments"] = [dict(row) for row in group["template"]["payments"]]
        for name in ("start_date", "end_date"):
            initial["policy"][name] = date.fromisoformat(initial["policy"][name])
        for row in initial["payments"]:
            row["due_date"] = date.fromisoformat(row["due_date"])
    if flow_import.normalize_dfa(draft["dfa"]):
        initial["policy"]["dfa_number"] = draft["dfa"]
    # Этот baseline содержит подтверждённые условия группы и позволяет
    # сохранить только ручные правки, если свод или план успели измениться.
    baseline = {
        "policy": dict(initial["policy"]),
        "payments": [dict(p) for p in initial["payments"]],
    }
    edits = draft.get("edits") or {}
    if edits.get("slot") == slot:
        apply_edits(initial, edits)
    request.flow_initial = initial
    request.flow_source = source
    request.flow_slot = slot
    context = {
        "flow_snapshot": source,
        "flow_slot": slot,
        "flow_has_next": slot > 0
        and len(free_slots(source["source_object_count"], used)) > 1,
        "flow_warnings": initial["warnings"],
        "flow_review_url": review_url(key),
        "flow_extras": source_extras(source),
        "flow_source_url": source_url(source["summary_id"]),
        "flow_group": group,
        "flow_actual_checked": request.POST.get("_flow_actual") == "yes",
        "flow_template_checked": request.POST.get("_flow_template") == "yes",
    }
    if request.method != "POST":
        return show_form(context)
    try:
        if not check_revision(request, key, draft):
            draft["edits"] = typed_edits(request.POST, baseline, slot)
            put_draft(request, key, draft)
            return redirect(review_url(key))
        current = flow_groups.group_for(groups_for(source), slot) if slot else None
        if current != group:
            draft["edits"] = typed_edits(request.POST, baseline, slot)
            draft.update(
                slot=None,
                selected_slot=slot,
                dfa=draft.get("search_dfa", source["dfa_number"]),
            )
            put_draft(request, key, draft)
            messages.warning(
                request,
                "Группа ДФА обновилась. Проверьте её условия перед сохранением.",
            )
            return redirect(review_url(key))
        dfa = request.POST.get("dfa_number", "")
        candidates = list(
            flow_import.candidate_policies(dfa, exclude_summary_id=source["summary_id"])
        )
        mark = candidate_mark(candidates)
        reviewed = mark == draft.get("reviewed_ids") and flow_import.normalize_dfa(
            dfa
        ) == flow_import.normalize_dfa(draft["dfa"])
        existing_id = request.POST.get("_flow_link")
        if existing_id is not None:
            require_access(request.user, link=True)
            candidate = next((p for p in candidates if str(p.pk) == existing_id), None)
            if not candidate or request.POST.get("_flow_confirm") != mark:
                return confirm_candidates(
                    request,
                    key,
                    dfa,
                    candidates,
                    mark,
                    "Выбранный полис больше не соответствует ДФА. Проверьте обновлённый список.",
                )
            policy, created = flow_import.save_linked_policy(
                source,
                slot,
                request.user,
                dfa_number=dfa,
                existing_policy=candidate,
                group_version=group["version"] if group else None,
            )
            return redirect_after_save(request, key, draft, policy, created)
        if mark and not reviewed:
            if request.POST.get("_flow_confirm") != mark:
                return confirm_candidates(request, key, dfa, candidates, mark)
            # Запоминаем выбор, когда форма должна ещё раз показать ошибки по графику.
            draft.update(dfa=dfa, reviewed_ids=mark)
            put_draft(request, key, draft)

        def create():
            response = show_form(context)
            if not hasattr(request, "flow_saved_policy"):
                raise InvalidPolicyForm(response)
            return request.flow_saved_policy

        policy, created = flow_import.save_linked_policy(
            source,
            slot,
            request.user,
            create_policy=create,
            dfa_number=dfa,
            group_version=group["version"] if group else None,
            confirm_template=request.POST.get("_flow_template") == "yes",
        )
        return redirect_after_save(request, key, draft, policy, created)
    except InvalidPolicyForm as invalid:
        return invalid.response
    except flow_client.FlowError as error:
        draft["edits"] = typed_edits(request.POST, baseline, slot)
        put_draft(request, key, draft)
        return error_page(request, error, draft_key=key)
