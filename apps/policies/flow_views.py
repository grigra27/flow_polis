"""Переход из акцептованного свода в журнал полисов."""
from decimal import Decimal, InvalidOperation
from time import time
from uuid import uuid4

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.views import redirect_to_login
from django.http import Http404
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_http_methods

from .flow_permissions import can_create, can_link, explain_denial, require_access
from .services import flow_client, flow_import

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


def error_page(request, error):
    return render(
        request, "policies/flow_error.html", {"error": str(error)}, status=409
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
        return redirect(reverse("admin:policies_policy_add") + "?flow_draft=" + key)
    put_draft(request, key, draft)
    return redirect(review_url(key))


def check_revision(request, key, draft):
    fresh = flow_client.fetch_snapshot(draft["snapshot"]["summary_id"])
    if fresh["revision"] == draft["snapshot"]["revision"]:
        return True
    draft["previous"] = draft["snapshot"]
    if draft["dfa"] == draft["snapshot"]["dfa_number"]:
        draft["dfa"] = fresh["dfa_number"]
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


def review_context(request, key, draft, error=None):
    source = draft["snapshot"]
    links = list(flow_import.links_for(source["summary_id"]).select_related("policy"))
    total = source["source_object_count"]
    used = {link.slot for link in links}
    candidates = list(
        flow_import.candidate_policies(draft["dfa"]).prefetch_related("flow_links")
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
        "slots": [slot for slot in range(1, total + 1) if slot not in used]
        if total > 1 and 0 not in used
        else [],
        "allow_common": not links,
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
    error = None
    try:
        context = review_context(request, key, draft)
        if request.method == "GET":
            if len(context["links"]) == 1 and context["links"][0].slot == 0:
                return redirect("policies:detail", pk=context["links"][0].policy_id)
        else:
            action = request.POST.get("action")
            if action == "search":
                draft["dfa"] = request.POST.get("dfa", "").strip()[:100]
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
            if context["links"] and slot == 0:
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
                    dfa_number=draft["dfa"],
                )
                return redirect("policies:detail", pk=policy.pk)
            if not source.get("variant") or not source["offers"]:
                raise flow_client.FlowError(
                    "Для создания выберите вариант с премией в ЗС."
                )
            form_key = uuid4().hex
            form_draft = dict(draft, slot=slot, reviewed_ids=context["candidate_mark"])
            put_draft(request, form_key, form_draft)
            return redirect(
                reverse("admin:policies_policy_add") + "?flow_draft=" + form_key
            )
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


@explain_denial
def flow_admin_add(request, key, show_form):
    draft = get_draft(request, key)
    require_access(request.user, create=True)
    slot = draft["slot"]
    if slot is None:
        return redirect(review_url(key))
    source = draft["snapshot"]
    linked = flow_import.links_for(source["summary_id"]).filter(slot=slot).first()
    if linked:
        return redirect("policies:detail", pk=linked.policy_id)
    initial = flow_import.prepare_initial(source, slot=slot)
    if flow_import.normalize_dfa(draft["dfa"]):
        initial["policy"]["dfa_number"] = draft["dfa"]
    edits = draft.get("edits") or {}
    if edits.get("slot") == slot:
        apply_edits(initial, edits)
    request.flow_initial = initial
    request.flow_source = source
    request.flow_slot = slot
    context = {
        "flow_snapshot": source,
        "flow_slot": slot,
        "flow_warnings": initial["warnings"],
        "flow_review_url": review_url(key),
        "flow_extras": source_extras(source),
    }
    if request.method != "POST":
        return show_form(context)
    try:
        if not check_revision(request, key, draft):
            draft["edits"] = typed_edits(
                request.POST, flow_import.prepare_initial(source, slot=slot), slot
            )
            put_draft(request, key, draft)
            return redirect(review_url(key))
        dfa = request.POST.get("dfa_number", "")
        candidates = list(flow_import.candidate_policies(dfa))
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
            policy, _ = flow_import.save_linked_policy(
                source,
                slot,
                request.user,
                dfa_number=dfa,
                existing_policy=candidate,
            )
            return redirect("policies:detail", pk=policy.pk)
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

        policy, _ = flow_import.save_linked_policy(
            source, slot, request.user, create_policy=create
        )
        return redirect("policies:detail", pk=policy.pk)
    except InvalidPolicyForm as invalid:
        return invalid.response
    except flow_client.FlowError as error:
        return error_page(request, error)
