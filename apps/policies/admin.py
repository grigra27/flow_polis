from django import forms
from django.conf import settings
from django.contrib import admin
from django.contrib.admin.options import IS_POPUP_VAR
from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import Sum
from django.forms.models import BaseInlineFormSet
from django.template.response import TemplateResponse
from django.utils.html import format_html, format_html_join
from django.contrib.admin import SimpleListFilter
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect
from django.urls import path, reverse
from urllib.parse import urlencode
from decimal import Decimal
from uuid import uuid4

from apps.insurers.models import InsuranceType, get_osago_insurance_type

from . import flow_views
from .forms import AcceptUploadForm
from .models import OsagoPolicy, Policy, PaymentSchedule, PolicyInfo
from .navigation import journal_origin, policy_card_url
from .services.policy_template import (
    can_create_from_policy,
    policy_template_initial,
    object_initial,
    osago_for_vin,
)
from .services.accept_parser import parse_accept_file
from .services.accept_resolver import (
    ACCEPT_IMPORT_SESSION_KEY,
    resolve_accept_data,
)


class InsuranceSumRangeFilter(SimpleListFilter):
    """
    Custom filter for filtering PaymentSchedule by insurance_sum ranges.

    **Validates: Requirements 4.4**
    """

    title = "диапазон страховой суммы"
    parameter_name = "insurance_sum_range"

    def lookups(self, request, model_admin):
        """Define the filter options."""
        return (
            ("0-500k", "До 500 000"),
            ("500k-1m", "500 000 - 1 000 000"),
            ("1m-5m", "1 000 000 - 5 000 000"),
            ("5m-10m", "5 000 000 - 10 000 000"),
            ("10m+", "Более 10 000 000"),
        )

    def queryset(self, request, queryset):
        """Filter the queryset based on the selected range."""
        if self.value() == "0-500k":
            return queryset.filter(insurance_sum__lt=Decimal("500000"))
        elif self.value() == "500k-1m":
            return queryset.filter(
                insurance_sum__gte=Decimal("500000"),
                insurance_sum__lt=Decimal("1000000"),
            )
        elif self.value() == "1m-5m":
            return queryset.filter(
                insurance_sum__gte=Decimal("1000000"),
                insurance_sum__lt=Decimal("5000000"),
            )
        elif self.value() == "5m-10m":
            return queryset.filter(
                insurance_sum__gte=Decimal("5000000"),
                insurance_sum__lt=Decimal("10000000"),
            )
        elif self.value() == "10m+":
            return queryset.filter(insurance_sum__gte=Decimal("10000000"))
        return queryset


class PaymentScheduleInlineFormSet(BaseInlineFormSet):
    """
    H-02 (2026-10-13): порядок дат графика проверяется по ИТОГОВОМУ набору
    строк (сохраняемые формы + удаляемые исключены), а не построчно против БД.

    Раньше PaymentSchedule.save() вызывал full_clean() для каждой строки по
    очереди: при создании полиса проверка на этапе формы пропускалась
    (policy_id ещё None), а при правке нескольких строк промежуточное
    состояние в БД нарушало порядок — в обоих случаях ValidationError
    вылетал из save() и пользователь получал HTTP 500.
    """

    def __init__(self, *args, allow_commission_override=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.allow_commission_override = allow_commission_override

    def _construct_form(self, i, **kwargs):
        form = super()._construct_form(i, **kwargs)
        form.instance._date_sequence_checked_by_formset = True
        if self.allow_commission_override and "kv_rub" in form.fields:
            form.fields["kv_rub"].required = False
            form.fields["kv_rub"].widget.attrs["placeholder"] = "По ставке"
            if "kv_rub" not in form.initial:
                form.initial["kv_rub"] = None
        return form

    def clean(self):
        super().clean()
        if any(self.errors):
            return

        if self._add_insurance_kind_errors():
            return

        rows = []
        form_by_row = {}
        for form in self.forms:
            if not form.cleaned_data or self._should_delete_form(form):
                continue
            rows.append(form.instance)
            form_by_row[id(form.instance)] = form

        # Строки полиса, которых нет в formset (на случай, если inline
        # показывает не все платежи) — участвуют в проверке как есть.
        if self.instance.pk:
            shown_pks = [f.instance.pk for f in self.initial_forms]
            rows.extend(
                PaymentSchedule.objects.filter(policy=self.instance).exclude(
                    pk__in=shown_pks
                )
            )

        rows.sort(key=lambda p: (p.year_number, p.installment_number))
        for previous_payment, payment in zip(rows, rows[1:]):
            errors = payment.date_sequence_errors(previous_payment)
            if not errors:
                continue
            form = form_by_row.get(id(payment))
            if form is None:
                raise ValidationError(list(errors.values()))
            for field, message in errors.items():
                form.add_error(field, message)

        if hasattr(self, "flow_request"):
            self._check_flow_amounts(rows)

    def save_new(self, form, commit=True):
        if self.allow_commission_override:
            payment = form.instance
            # Оставленная пустой сумма рассчитывается по ставке. Введённый ноль тоже является выбором.
            payment._explicit_commission = payment.kv_rub is not None
            if payment.kv_rub is None:
                payment.kv_rub = Decimal("0")
        return super().save_new(form, commit)

    def _check_flow_amounts(self, rows):
        request = self.flow_request
        offers = request.flow_source["offers"]
        by_year = {offer["year"]: [] for offer in offers}
        for row in rows:
            if row.year_number not in by_year:
                raise ValidationError("Проверьте номера лет в графике по своду.")
            by_year[row.year_number].append(row)
        if not all(by_year.values()):
            raise ValidationError(
                "Заполните взносы по каждому году выбранного предложения."
            )
        if request.flow_slot:
            return  # Для отдельных объектов суммы распределяются по выданным договорам.
        changes = []
        for offer in offers:
            year = offer["year"]
            payments = by_year[year]
            total = sum(p.amount for p in payments)
            if total != Decimal(offer["premium"]):
                changes.append(
                    f"{year} год: премия по своду {offer['premium']}, в графике {total}."
                )
            if any(
                p.insurance_sum != Decimal(offer["insurance_sum"]) for p in payments
            ):
                changes.append(
                    f"{year} год: страховая сумма отличается от {offer['insurance_sum']} по своду."
                )
        if changes and request.POST.get("_flow_actual") != "yes":
            request.flow_finance_mismatches = changes
            raise ValidationError("Подтвердите расхождения с принятым предложением.")

    def _add_insurance_kind_errors(self):
        """
        Правила вида страхования по родительскому полису formset'а: ОСАГО —
        один платёж без страховой суммы, КВ ≤ 10%; остальные виды —
        страховая сумма обязательна. У нового полиса policy_id ещё None,
        PaymentSchedule.clean() их пропускает — без этой проверки ошибка
        вылетала бы из save() как HTTP 500 (как в H-02).
        Возвращает True, если ошибки найдены.
        """
        found = False
        for form in self.forms:
            if not form.cleaned_data or self._should_delete_form(form):
                continue
            errors = form.instance.insurance_kind_errors(policy=self.instance)
            for field, message in errors.items():
                form.add_error(field if field in form.fields else None, message)
                found = True
        return found


# Nginx отдаёт статику с кэшем на 30 дней и без хэша в имени: при правке
# скрипта меняйте версию, иначе браузеры сотрудников возьмут старый файл.
# Полный путь: static() закодировал бы «?» в %3F.
AUTO_COMMISSION_RATE_JS = (
    f"{settings.STATIC_URL}policies/js/auto_commission_rate.js?v=2026-11-13.2"
)


class OsagoPaymentInlineFormSet(PaymentScheduleInlineFormSet):
    """Единственный платёж ОСАГО: год 1, платёж 1, без страховой суммы."""

    def _construct_form(self, i, **kwargs):
        form = super()._construct_form(i, **kwargs)
        form.instance.year_number = 1
        form.instance.installment_number = 1
        form.instance.insurance_sum = None
        return form


class PaymentScheduleInline(admin.TabularInline):
    model = PaymentSchedule
    formset = PaymentScheduleInlineFormSet
    template = "admin/policies/policy/payment_inline.html"
    extra = 1
    fields = [
        "year_number",
        "installment_number",
        "due_date",
        "insurance_sum",
        "amount",
        "kv_rub",
        "paid_date",
        "insurer_date",
        "alliance_paid",
        "payment_info",
    ]
    # commission_rate is excluded from visible fields but still saved via JavaScript

    def get_extra(self, request, obj=None, **kwargs):
        if hasattr(request, "flow_initial"):
            return len(request.flow_initial["payments"])
        if hasattr(request, "template_payments"):
            return max(1, len(request.template_payments))
        return super().get_extra(request, obj, **kwargs)

    def get_formset(self, request, obj=None, **kwargs):
        formset = super().get_formset(request, obj, **kwargs)
        if hasattr(request, "flow_source"):
            formset.flow_request = request
        return formset

    class Media:
        js = (
            f"{settings.STATIC_URL}policies/js/copy_payment_inline.js?v=2026-11-13",
            AUTO_COMMISSION_RATE_JS,
            "policies/js/validate_payment_dates.js",
        )
        css = {
            "all": (
                f"{settings.STATIC_URL}policies/css/copy_payment_inline.css?v=2026-11-13",
                "policies/css/auto_commission_rate.css",
            )
        }


class OsagoPaymentInline(admin.TabularInline):
    model = PaymentSchedule
    formset = OsagoPaymentInlineFormSet
    verbose_name = "Платёж"
    verbose_name_plural = "Платёж по полису ОСАГО"
    extra = 0
    min_num = 1
    max_num = 1
    can_delete = False
    fields = [
        "due_date",
        "amount",
        "kv_rub",
        "paid_date",
        "insurer_date",
        "alliance_paid",
        "payment_info",
    ]

    class Media:
        js = (AUTO_COMMISSION_RATE_JS,)
        css = {"all": ("policies/css/auto_commission_rate.css",)}


class PolicyInfoInline(admin.TabularInline):
    def get_extra(self, request, obj=None, **kwargs):
        if hasattr(request, "flow_initial") and request.flow_initial.get("tags"):
            return len(request.flow_initial["tags"]) + 1
        return super().get_extra(request, obj, **kwargs)

    model = PolicyInfo
    extra = 1
    autocomplete_fields = ["tag"]


def policy_fieldsets(*, osago=False):
    contract = {
        "classes": ("policy-fields",),
        "fields": (
            "policy_number",
            "dfa_number",
            "insurer",
            "insurance_type",
            ("start_date", "end_date"),
        ),
    }
    if osago:
        contract["description"] = "ОСАГО: один платёж, срок не больше года."
    else:
        contract["fields"] += ("franchise",)
    return (
        ("Условия страхования", contract),
        (
            "Стороны и филиал",
            {
                "classes": ("policy-fields",),
                "fields": ("client", "policyholder", "branch", "leasing_manager"),
            },
        ),
        (
            "Объект страхования",
            {
                "classes": ("policy-fields",),
                "fields": ("property_description", "property_year", "vin_number"),
            },
        ),
        (
            "Статусы",
            {
                "classes": ("policy-fields", "policy-secondary", "policy-statuses"),
                "fields": (
                    (
                        "policy_active",
                        "termination_date",
                        "dfa_active",
                        "dfa_deactivation_date",
                    ),
                    ("policy_uploaded", "renewal_to_old_dfa", "broker_participation"),
                ),
            },
        ),
        (
            "Дополнительная информация",
            {
                "classes": ("policy-fields", "policy-secondary"),
                "fields": ("info3", "info4"),
            },
        ),
        (
            "Системная информация",
            {
                "fields": ("created_at", "updated_at"),
                "classes": ("collapse", "policy-secondary"),
            },
        ),
    )


@admin.register(Policy)
class PolicyAdmin(admin.ModelAdmin):
    # Раздел «Полисы» — портфель без ОСАГО; ОСАГО заводится и правится
    # в разделе «Полисы ОСАГО» (OsagoPolicyAdmin, та же таблица).
    osago_section = False
    change_form_template = "admin/policies/policy/change_form.html"
    change_list_template = "admin/policies/policy/change_list.html"
    save_and_open_front_button_name = "_save_and_open_front"

    list_display = [
        "policy_number",
        "dfa_number",
        "client",
        "insurer",
        "start_date",
        "end_date",
        "premium_total_display",
        "policy_status",
        "dfa_status",
    ]
    list_filter = [
        "policy_active",
        "dfa_active",
        "policy_uploaded",
        "broker_participation",
        "insurance_type",
        "branch",
        "insurer",
        "start_date",
    ]
    search_fields = [
        "policy_number",
        "dfa_number",
        "client__client_name",
        "insurer__insurer_name",
        "vin_number",
    ]
    autocomplete_fields = [
        "client",
        "policyholder",
        "insurer",
        "insurance_type",
        "branch",
        "leasing_manager",
    ]
    readonly_fields = ["created_at", "updated_at", "flow_provenance"]
    actions = ["copy_policy"]

    fieldsets = policy_fieldsets()

    inlines = [PaymentScheduleInline, PolicyInfoInline]

    def get_fieldsets(self, request, obj=None):
        sections = super().get_fieldsets(request, obj)
        if obj is None or not obj.flow_links.exists():
            return sections
        result = []
        for title, options in sections:
            fields = list(options.get("fields", ()))
            if "dfa_number" in fields:
                fields.append("flow_provenance")
                options = dict(options, fields=fields)
            result.append((title, options))
        return result

    @admin.display(description="Источник оформления")
    def flow_provenance(self, obj):
        return format_html_join(
            " · ",
            '<a href="{}">{}</a>',
            (
                (link.source_url, link.source_label)
                for link in obj.flow_links.select_related("source").order_by(
                    "source_id"
                )
            ),
        )

    class Media:
        js = (
            f"{settings.STATIC_URL}policies/js/auto_copy_policyholder.js?v=2026-11-13",
        )
        css = {"all": ("policies/css/auto_copy_policyholder.css",)}

    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path(
                "import-accept/",
                self.admin_site.admin_view(self.import_accept_view),
                name=self._admin_url_name("import_accept"),
            ),
        ]
        return custom_urls + urls

    def _admin_url_name(self, action):
        """policies_policy_<action> / policies_osagopolicy_<action>."""
        return f"{self.opts.app_label}_{self.opts.model_name}_{action}"

    def _accept_title(self, title):
        return f"{title} (ОСАГО)" if self.osago_section else title

    def add_view(self, request, form_url="", extra_context=None):
        add = super().add_view
        if "from_policy" in request.GET or "from_object" in request.GET:
            return self._add_from_policy(request, form_url, extra_context)
        if "flow_draft" not in request.GET:
            return add(request, form_url, extra_context)
        if self.osago_section:
            raise PermissionDenied
        return flow_views.flow_admin_add(
            request,
            request.GET["flow_draft"],
            lambda context: add(
                request, form_url, {**(extra_context or {}), **context}
            ),
        )

    def _add_from_policy(self, request, form_url, extra_context):
        if not can_create_from_policy(request.user):
            raise PermissionDenied
        from_object = "from_object" in request.GET
        if (
            from_object
            and ("from_policy" in request.GET or not self.osago_section)
            or "flow_draft" in request.GET
            or "accept_token" in request.GET
        ):
            raise Http404
        source_id = request.GET["from_object" if from_object else "from_policy"]
        if not source_id.isascii() or not source_id.isdecimal() or len(source_id) > 19:
            raise Http404
        sources = (
            Policy.objects.without_osago()
            if from_object
            else self.filter_portfolio(Policy.objects.all())
        )
        source = get_object_or_404(sources, pk=source_id)
        request.template_source = source
        if request.method == "GET":
            if from_object:
                request.template_initial = object_initial(source)
            else:
                request.template_initial = policy_template_initial(source)
                request.template_payments = list(
                    source.payment_schedule.order_by(
                        "year_number", "installment_number"
                    ).values(
                        "year_number",
                        "installment_number",
                        "due_date",
                        "insurance_sum",
                        "amount",
                        "kv_rub",
                    )
                )
        context = {
            **(extra_context or {}),
            "template_source": source,
            "osago_from_object": from_object,
            "title": "Оформить ОСАГО на этот объект"
            if from_object
            else "Создать полис по образцу",
        }
        if from_object:
            vin = (
                request.POST.get("vin_number", "")
                if request.method == "POST"
                else source.vin_number
            )
            context["osago_matches"] = osago_for_vin(vin)
        return super().add_view(request, form_url, context)

    def import_accept_view(self, request):
        if not self.has_add_permission(request):
            raise PermissionDenied

        if request.method == "POST":
            form = AcceptUploadForm(request.POST, request.FILES)
            if form.is_valid():
                try:
                    parse_result = parse_accept_file(
                        form.cleaned_data["accept_file"], osago=self.osago_section
                    )
                    resolved = resolve_accept_data(
                        parse_result.data,
                        parser_warnings=parse_result.warnings,
                        osago=self.osago_section,
                    )
                except ValidationError as exc:
                    form.add_error("accept_file", exc.messages[0])
                else:
                    payload = resolved.to_session_payload(parse_result.data)
                    token = self._store_accept_import_payload(request, payload)
                    context = {
                        **self.admin_site.each_context(request),
                        "title": self._accept_title("Проверка акцепта"),
                        "opts": self.model._meta,
                        "token": token,
                        "payload": payload,
                        "parsed_rows": self._build_accept_parsed_rows(payload),
                        "resolved_rows": self._build_accept_resolved_rows(payload),
                        "add_url": (
                            f"{reverse('admin:' + self._admin_url_name('add'))}"
                            f"?accept_token={token}"
                        ),
                    }
                    return TemplateResponse(
                        request,
                        "admin/policies/policy/import_accept_preview.html",
                        context,
                    )
        else:
            form = AcceptUploadForm()

        context = {
            **self.admin_site.each_context(request),
            "title": self._accept_title("Загрузить акцепт"),
            "opts": self.model._meta,
            "form": form,
        }
        return TemplateResponse(
            request,
            "admin/policies/policy/import_accept.html",
            context,
        )

    def render_change_form(
        self, request, context, add=False, change=False, form_url="", obj=None
    ):
        context[
            "save_and_open_front_button_name"
        ] = self.save_and_open_front_button_name
        context["show_schedule_shortcut"] = any(
            inline.opts.model is PaymentSchedule
            for inline in context["inline_admin_formsets"]
        )
        payload = self._get_accept_import_payload(request) if add else None
        if payload:
            context["accept_import_warnings"] = payload.get("warnings", [])
            context["accept_import_parsed_rows"] = self._build_accept_parsed_rows(
                payload
            )
        response = super().render_change_form(
            request,
            context,
            add=add,
            change=change,
            form_url=form_url,
            obj=obj,
        )
        if hasattr(request, "flow_source"):
            response.template_name = "policies/flow_form.html"
        return response

    def get_changeform_initial_data(self, request):
        if hasattr(request, "template_initial"):
            return request.template_initial
        initial = super().get_changeform_initial_data(request)
        if hasattr(request, "flow_initial"):
            initial.update(request.flow_initial["policy"])
            return initial
        payload = self._get_accept_import_payload(request)
        if payload:
            initial.update(payload.get("policy_initial", {}))
        return initial

    def get_formset_kwargs(self, request, obj, inline, prefix):
        kwargs = super().get_formset_kwargs(request, obj, inline, prefix)
        if inline.model is PaymentSchedule and (
            hasattr(request, "flow_initial") or hasattr(request, "template_source")
        ):
            kwargs["allow_commission_override"] = True
            if hasattr(request, "template_payments"):
                kwargs["initial"] = request.template_payments
        if hasattr(request, "flow_initial"):
            if request.method == "GET":
                if inline.model is PaymentSchedule:
                    kwargs["initial"] = request.flow_initial["payments"]
                elif inline.model is PolicyInfo:
                    kwargs["initial"] = request.flow_initial.get("tags", [])
            return kwargs
        payload = self._get_accept_import_payload(request)
        if (
            request.method == "GET"
            and obj is None
            and inline.model is PaymentSchedule
            and payload
            and payload.get("payment_initial")
        ):
            kwargs["initial"] = [payload["payment_initial"]]
        return kwargs

    def _should_redirect_to_front(self, request):
        """
        Redirect to frontend detail page only for the dedicated admin button.
        Standard admin buttons keep their default redirect behavior.
        """
        return (
            self.save_and_open_front_button_name in request.POST
            and IS_POPUP_VAR not in request.POST
        )

    def _get_frontend_detail_url(self, obj):
        return reverse("policies:detail", args=[obj.pk])

    def _store_accept_import_payload(self, request, payload):
        token = uuid4().hex
        imports = request.session.get(ACCEPT_IMPORT_SESSION_KEY, {})
        imports[token] = payload

        # Keep the session compact if several accepts are previewed in a row.
        for old_token in list(imports.keys())[:-5]:
            imports.pop(old_token, None)

        request.session[ACCEPT_IMPORT_SESSION_KEY] = imports
        request.session.modified = True
        return token

    def _get_accept_import_payload(self, request):
        token = request.GET.get("accept_token")
        if not token:
            return None
        imports = request.session.get(ACCEPT_IMPORT_SESSION_KEY, {})
        payload = imports.get(token)
        # Акцепт, разобранный для другого раздела, форму не предзаполняет.
        if payload and bool(payload.get("osago")) != self.osago_section:
            return None
        return payload

    def _build_accept_parsed_rows(self, payload):
        parsed = payload.get("parsed", {})
        rows = [
            ("Файл", parsed.get("source_filename")),
            ("Номер ДФА", parsed.get("dfa_number")),
            ("Дата ДФА", parsed.get("dfa_date")),
            ("ИНН", parsed.get("client_inn")),
            ("Клиент", parsed.get("client_full") or parsed.get("client_short")),
            ("Страхователь", parsed.get("policyholder_text")),
            ("Вид страхования", parsed.get("insurance_type_name")),
            ("ОСАГО", parsed.get("osago")),
            ("Имущество", parsed.get("property_description")),
            ("VIN/ID", parsed.get("vin_number")),
            ("Год выпуска", parsed.get("property_year")),
            ("Дата начала", parsed.get("start_date")),
            ("Дата окончания", parsed.get("end_date")),
            ("Стоимость по ДКП", parsed.get("purchase_price")),
            ("Банк-кредитор", parsed.get("bank")),
        ]
        if payload.get("osago"):
            # У ОСАГО нет страховой суммы, а «Вид страхования» акцепта — про КАСКО.
            hidden = {"Стоимость по ДКП", "Вид страхования"}
            rows = [row for row in rows if row[0] not in hidden]
        return rows

    def _build_accept_resolved_rows(self, payload):
        resolved = payload.get("resolved", {})
        rows = []
        labels = {
            "client": "Лизингополучатель",
            "policyholder": "Страхователь",
            "insurance_type": "Вид страхования",
            "branch": "Филиал",
            "vin_number": "VIN/ID",
            "payment_schedule": "График платежей",
        }
        if payload.get("osago"):
            labels["term"] = "Срок полиса"
            labels["payment_schedule"] = "Платёж"
        for key, label in labels.items():
            item = resolved.get(key, {})
            rows.append(
                {
                    "label": label,
                    "value": item.get("label", ""),
                    "status": self._accept_status_label(item.get("status")),
                    "status_code": item.get("status", "manual"),
                }
            )
        return rows

    def _accept_status_label(self, status):
        return {
            "matched": "Подставится",
            "partial": "Частично",
            "manual": "Вручную",
            "invalid": "Не подставится",
        }.get(status, "Вручную")

    def response_add(self, request, obj, post_url_continue=None):
        if hasattr(request, "flow_initial"):
            request.flow_saved_policy = obj
            return redirect(self._get_frontend_detail_url(obj))
        if self._should_redirect_to_front(request):
            return redirect(self._get_frontend_detail_url(obj))
        if request.GET.get("accept_token"):
            self.message_user(
                request,
                "Полис создан из предзаполненной формы акцепта.",
                messages.SUCCESS,
            )
        return super().response_add(request, obj, post_url_continue)

    def response_change(self, request, obj):
        if self._should_redirect_to_front(request):
            return redirect(policy_card_url(obj.pk, request.GET))
        return super().response_change(request, obj)

    def change_view(self, request, object_id, form_url="", extra_context=None):
        kind_redirect = self._redirect_to_kind_section(request, object_id)
        if kind_redirect is not None:
            return kind_redirect
        return super().change_view(request, object_id, form_url, extra_context)

    def _redirect_to_kind_section(self, request, object_id):
        """Полис ОСАГО открыт в «Полисах» (или наоборот) — ведём в его раздел.

        Ссылки «Редактировать» с сайта ведут в policies_policy_change для
        любого полиса; без редиректа ОСАГО дал бы «объект не найден».
        """
        try:
            pk = int(object_id)
        except (TypeError, ValueError):
            return None
        policy = Policy.objects.select_related("insurance_type").filter(pk=pk).first()
        if policy is None or policy.is_osago == self.osago_section:
            return None
        url_name = (
            "admin:policies_osagopolicy_change"
            if policy.is_osago
            else "admin:policies_policy_change"
        )
        url = reverse(url_name, args=[pk])
        query = request.GET.urlencode()
        return redirect(f"{url}?{query}" if query else url)

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "insurance_type":
            kwargs["queryset"] = InsuranceType.objects.filter(is_osago=False)
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

    def filter_portfolio(self, queryset):
        return queryset.without_osago()

    def get_queryset(self, request):
        # list_display обращается к client и insurer по каждой строке.
        # Без select_related это N+1: 1 + 2 × len(page).
        # premium_total_db — annotate'нутая сумма платежей; используется
        # вместо @property Policy.premium_total чтобы избежать +50 SQL'ей
        # на страницу listing'а.
        return self.filter_portfolio(
            super()
            .get_queryset(request)
            .select_related(
                "client",
                "policyholder",
                "insurer",
                "insurance_type",
                "branch",
                "leasing_manager",
            )
            .annotate(premium_total_db=Sum("payment_schedule__amount"))
        )

    @admin.display(
        description="Общая сумма страховой премии",
        ordering="premium_total_db",
    )
    def premium_total_display(self, obj):
        # premium_total_db приходит из annotate в get_queryset.
        # Fallback на @property только если атрибута нет (объект пришёл
        # из other queryset без annotate — например, change_form preview).
        # is None — а не truthy — чтобы не обращаться к @property для нулевой суммы.
        value = getattr(obj, "premium_total_db", None)
        if value is None:
            value = obj.premium_total
        return value if value is not None else Decimal("0")

    def policy_status(self, obj):
        if obj.policy_active:
            return format_html('<span style="color: green;">✓ Активен</span>')
        return format_html('<span style="color: red;">✗ Закрыт</span>')

    policy_status.short_description = "Статус полиса"

    def dfa_status(self, obj):
        if obj.dfa_active:
            return format_html('<span style="color: green;">✓ Активен</span>')
        return format_html('<span style="color: red;">✗ Закрыт</span>')

    dfa_status.short_description = "Статус ДФА"

    def has_create_from_policy_permission(self, request):
        return can_create_from_policy(request.user)

    @admin.action(permissions=["create_from_policy"], description="Создать по образцу")
    def copy_policy(self, request, queryset):
        sources = list(queryset.values_list("pk", flat=True)[:2])
        if len(sources) != 1:
            self.message_user(request, "Выберите один полис-образец.", messages.WARNING)
            return
        return redirect(
            reverse(
                "admin:" + self._admin_url_name("add"),
                query={"from_policy": sources[0]},
            )
        )


class OsagoPolicyForm(forms.ModelForm):
    """Форма ОСАГО: вид страхования всегда «ОСАГО», что бы ни пришло в POST.

    Поле остаётся в форме скрытым — auto_commission_rate.js берёт из
    #id_insurance_type вид для подстановки ставки КВ.
    """

    class Meta:
        model = OsagoPolicy
        fields = "__all__"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if "insurance_type" not in self.fields:
            return
        # disabled: значение из POST игнорируется, берётся initial.
        self.fields["insurance_type"].disabled = True
        osago_type = get_osago_insurance_type()
        if osago_type is not None:
            self.initial["insurance_type"] = osago_type.pk

    def clean_insurance_type(self):
        osago_type = get_osago_insurance_type()
        if osago_type is None:
            raise forms.ValidationError(
                "В справочнике нет вида страхования с признаком «ОСАГО»."
            )
        return osago_type


@admin.register(OsagoPolicy)
class OsagoPolicyAdmin(PolicyAdmin):
    osago_section = True
    form = OsagoPolicyForm

    list_filter = [
        "policy_active",
        "dfa_active",
        "policy_uploaded",
        "broker_participation",
        "branch",
        "insurer",
        "start_date",
    ]
    autocomplete_fields = [
        "client",
        "policyholder",
        "insurer",
        "branch",
        "leasing_manager",
    ]
    fieldsets = policy_fieldsets(osago=True)

    inlines = [OsagoPaymentInline, PolicyInfoInline]

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "insurance_type":
            kwargs["queryset"] = InsuranceType.objects.filter(is_osago=True)
            kwargs["widget"] = forms.HiddenInput()
            return db_field.formfield(**kwargs)
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

    def filter_portfolio(self, queryset):
        return queryset.osago()

    # Права на раздел — те же, что на обычные полисы (решение владельца
    # 2026-10-15), чтобы не выдавать отдельные права ограниченным админам.
    def _has_policy_perm(self, request, action):
        return request.user.has_perm(f"policies.{action}_policy")

    def has_view_permission(self, request, obj=None):
        return self._has_policy_perm(request, "view") or self._has_policy_perm(
            request, "change"
        )

    def has_add_permission(self, request):
        return self._has_policy_perm(request, "add")

    def has_change_permission(self, request, obj=None):
        return self._has_policy_perm(request, "change")

    def has_delete_permission(self, request, obj=None):
        return self._has_policy_perm(request, "delete")


@admin.register(PaymentSchedule)
class PaymentScheduleAdmin(admin.ModelAdmin):
    change_form_template = "admin/policies/paymentschedule/change_form.html"

    def render_change_form(
        self, request, context, add=False, change=False, form_url="", obj=None
    ):
        if change and obj is not None:
            back = policy_card_url(obj.policy_id, request.GET, obj.pk)
            if request.GET.get("entry") == "journal":
                back = journal_origin(request.GET.get("journal", "")) or back
            context["payment_back_url"] = back
        return super().render_change_form(request, context, add, change, form_url, obj)

    def response_change(self, request, obj):
        if "_save_and_open_front" in request.POST and IS_POPUP_VAR not in request.POST:
            return redirect(policy_card_url(obj.policy_id, request.GET, obj.pk))
        return super().response_change(request, obj)

    list_display = [
        "policy",
        "year_number",
        "installment_number",
        "due_date",
        "insurance_sum",
        "amount",
        "kv_rub",
        "payment_status",
    ]
    list_filter = ["due_date", "paid_date", InsuranceSumRangeFilter]
    search_fields = ["policy__policy_number", "policy__client__client_name"]
    autocomplete_fields = ["policy"]
    date_hierarchy = "due_date"
    actions = ["copy_payments"]
    exclude = ["commission_rate"]

    def get_queryset(self, request):
        # list_display обращается к str(policy), который тянет client.
        # Без select_related это N+1: 1 + 2 × len(page).
        return (
            super()
            .get_queryset(request)
            .select_related("policy", "policy__client", "policy__insurer")
        )

    @admin.action(description="Копировать выбранные платежи")
    def copy_payments(self, request, queryset):
        """
        Copy selected payments by redirecting to add form with pre-filled data.

        This action creates copies of selected payments by redirecting to the
        add form with all field values pre-populated via GET parameters.
        The user can then modify the values before saving.

        **Validates: Requirements 2.1, 2.2, 2.3, 2.4, 2.5**
        """
        # Get the first payment to copy
        # If multiple payments are selected, we copy the first one
        # (Django admin actions typically work on one item at a time for this use case)
        payment = queryset.first()

        if not payment:
            return

        # Build dictionary of field values to copy
        # Exclude id, created_at, updated_at, commission_rate as per requirements
        copy_data = {
            "policy": payment.policy.id,
            "year_number": payment.year_number,
            "installment_number": payment.installment_number,
            "due_date": payment.due_date,
            "amount": payment.amount,
            "insurance_sum": payment.insurance_sum,
            "kv_rub": payment.kv_rub,
            "alliance_paid": payment.alliance_paid,
            "payment_info": payment.payment_info,
        }

        # Add optional fields if they exist
        if payment.paid_date:
            copy_data["paid_date"] = payment.paid_date
        if payment.insurer_date:
            copy_data["insurer_date"] = payment.insurer_date

        # Build URL with query parameters
        add_url = reverse("admin:policies_paymentschedule_add")
        query_string = urlencode(copy_data)
        redirect_url = f"{add_url}?{query_string}"

        return redirect(redirect_url)

    def payment_status(self, obj):
        if obj.is_approved:
            return format_html('<span style="color: green;">✓ Акт согласован СК</span>')
        elif obj.is_paid:
            return format_html('<span style="color: blue;">✓ Оплачен</span>')
        elif obj.is_cancelled:
            return format_html('<span style="color: red;">✕ Отменен</span>')
        elif obj.is_overdue:
            return format_html('<span style="color: red;">✗ Не оплачен</span>')
        return format_html('<span style="color: orange;">⏳ Ожидается</span>')

    payment_status.short_description = "Статус"
