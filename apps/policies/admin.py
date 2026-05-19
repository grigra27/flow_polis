from django.contrib import admin
from django.contrib.admin.options import IS_POPUP_VAR
from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import Sum
from django.template.response import TemplateResponse
from django.utils.html import format_html
from django.contrib.admin import SimpleListFilter
from django.shortcuts import redirect
from django.urls import path, reverse
from urllib.parse import urlencode
from decimal import Decimal
from uuid import uuid4

from .forms import AcceptUploadForm
from .models import Policy, PaymentSchedule, PolicyInfo
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


class PaymentScheduleInline(admin.TabularInline):
    model = PaymentSchedule
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

    class Media:
        js = (
            "policies/js/copy_payment_inline.js",
            "policies/js/auto_commission_rate.js",
            "policies/js/validate_payment_dates.js",
        )
        css = {
            "all": (
                "policies/css/copy_payment_inline.css",
                "policies/css/auto_commission_rate.css",
            )
        }


class PolicyInfoInline(admin.TabularInline):
    model = PolicyInfo
    extra = 1
    autocomplete_fields = ["tag"]


@admin.register(Policy)
class PolicyAdmin(admin.ModelAdmin):
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
    readonly_fields = ["created_at", "updated_at"]
    actions = ["copy_policy"]

    fieldsets = (
        (
            "Основная информация",
            {
                "fields": (
                    "policy_number",
                    "dfa_number",
                    "client",
                    "policyholder",
                    "branch",
                    "leasing_manager",
                )
            },
        ),
        (
            "Детали страхования",
            {
                "fields": (
                    "insurance_type",
                    "property_description",
                    "property_year",
                    "vin_number",
                    "franchise",
                    "start_date",
                    "end_date",
                )
            },
        ),
        ("Дополнительная информация", {"fields": ("info3", "info4")}),
        (
            "Статусы",
            {
                "fields": (
                    "policy_active",
                    "termination_date",
                    "dfa_active",
                    "policy_uploaded",
                    "broker_participation",
                    "renewal_to_old_dfa",
                )
            },
        ),
        (
            "Системная информация",
            {"fields": ("created_at", "updated_at"), "classes": ("collapse",)},
        ),
        ("Страховщик", {"fields": ("insurer",)}),
    )

    inlines = [PaymentScheduleInline, PolicyInfoInline]

    class Media:
        js = ("policies/js/auto_copy_policyholder.js",)
        css = {"all": ("policies/css/auto_copy_policyholder.css",)}

    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path(
                "import-accept/",
                self.admin_site.admin_view(self.import_accept_view),
                name="policies_policy_import_accept",
            ),
        ]
        return custom_urls + urls

    def import_accept_view(self, request):
        if not self.has_add_permission(request):
            raise PermissionDenied

        if request.method == "POST":
            form = AcceptUploadForm(request.POST, request.FILES)
            if form.is_valid():
                try:
                    parse_result = parse_accept_file(form.cleaned_data["accept_file"])
                    resolved = resolve_accept_data(
                        parse_result.data,
                        parser_warnings=parse_result.warnings,
                    )
                except ValidationError as exc:
                    form.add_error("accept_file", exc.messages[0])
                else:
                    payload = resolved.to_session_payload(parse_result.data)
                    token = self._store_accept_import_payload(request, payload)
                    context = {
                        **self.admin_site.each_context(request),
                        "title": "Проверка акцепта",
                        "opts": self.model._meta,
                        "token": token,
                        "payload": payload,
                        "parsed_rows": self._build_accept_parsed_rows(payload),
                        "resolved_rows": self._build_accept_resolved_rows(payload),
                        "add_url": f"{reverse('admin:policies_policy_add')}?accept_token={token}",
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
            "title": "Загрузить акцепт",
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
        payload = self._get_accept_import_payload(request) if add else None
        if payload:
            context["accept_import_warnings"] = payload.get("warnings", [])
            context["accept_import_parsed_rows"] = self._build_accept_parsed_rows(
                payload
            )
        return super().render_change_form(
            request,
            context,
            add=add,
            change=change,
            form_url=form_url,
            obj=obj,
        )

    def get_changeform_initial_data(self, request):
        initial = super().get_changeform_initial_data(request)
        payload = self._get_accept_import_payload(request)
        if payload:
            initial.update(payload.get("policy_initial", {}))
        return initial

    def get_formset_kwargs(self, request, obj, inline, prefix):
        kwargs = super().get_formset_kwargs(request, obj, inline, prefix)
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
        return imports.get(token)

    def _build_accept_parsed_rows(self, payload):
        parsed = payload.get("parsed", {})
        return [
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
            return redirect(self._get_frontend_detail_url(obj))
        return super().response_change(request, obj)

    def get_queryset(self, request):
        # list_display обращается к client и insurer по каждой строке.
        # Без select_related это N+1: 1 + 2 × len(page).
        # premium_total_db — annotate'нутая сумма платежей; используется
        # вместо @property Policy.premium_total чтобы избежать +50 SQL'ей
        # на страницу listing'а.
        return (
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

    @admin.action(description="Копировать выбранный полис с графиком платежей")
    def copy_policy(self, request, queryset):
        """
        Copy selected policy with all related data (payment schedule and info tags).

        This action creates a complete copy of the selected policy including:
        - All policy fields (with "-COPY" suffix added to policy numbers)
        - All payment schedule entries
        - All info tags

        The new policy is saved immediately and the user is redirected to edit it.
        """
        from django.contrib import messages
        from datetime import datetime

        # Get the first policy to copy
        policy = queryset.first()

        if not policy:
            self.message_user(
                request, "Не выбран полис для копирования", messages.ERROR
            )
            return

        try:
            # Create a copy of the policy
            # Add timestamp to make policy number unique
            timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")

            new_policy = Policy.objects.create(
                policy_number=f"{policy.policy_number}-COPY-{timestamp}",
                dfa_number=f"{policy.dfa_number}-COPY-{timestamp}"
                if policy.dfa_number
                else "",
                client=policy.client,
                policyholder=policy.policyholder,
                insurer=policy.insurer,
                property_description=policy.property_description,
                property_year=policy.property_year,
                start_date=policy.start_date,
                end_date=policy.end_date,
                insurance_type=policy.insurance_type,
                branch=policy.branch,
                leasing_manager=policy.leasing_manager,
                franchise=policy.franchise,
                info3=policy.info3,
                info4=policy.info4,
                policy_active=policy.policy_active,
                dfa_active=policy.dfa_active,
                policy_uploaded=policy.policy_uploaded,
                broker_participation=policy.broker_participation,
                renewal_to_old_dfa=policy.renewal_to_old_dfa,
            )

            # Copy payment schedule
            payment_count = 0
            for payment in policy.payment_schedule.all():
                PaymentSchedule.objects.create(
                    policy=new_policy,
                    year_number=payment.year_number,
                    installment_number=payment.installment_number,
                    due_date=payment.due_date,
                    amount=payment.amount,
                    insurance_sum=payment.insurance_sum,
                    commission_rate=payment.commission_rate,  # Копируем commission_rate
                    kv_rub=payment.kv_rub,
                    paid_date=payment.paid_date,
                    insurer_date=payment.insurer_date,
                    alliance_paid=payment.alliance_paid,
                    payment_info=payment.payment_info,
                )
                payment_count += 1

            # Copy info tags
            info_count = 0
            for info in policy.info_tags.all():
                PolicyInfo.objects.create(
                    policy=new_policy,
                    tag=info.tag,
                    info_field=info.info_field,
                )
                info_count += 1

            # Show success message
            message = f'Полис "{policy.policy_number}" успешно скопирован. '
            message += (
                f"Скопировано платежей: {payment_count}, инфо-меток: {info_count}."
            )
            self.message_user(request, message, messages.SUCCESS)

            # Redirect to edit the new policy
            change_url = reverse("admin:policies_policy_change", args=[new_policy.id])
            return redirect(change_url)

        except Exception as e:
            self.message_user(
                request, f"Ошибка при копировании полиса: {str(e)}", messages.ERROR
            )
            return


@admin.register(PaymentSchedule)
class PaymentScheduleAdmin(admin.ModelAdmin):
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
