from django.contrib import admin, messages
from django.db import transaction

from .models import BillingPeriod, BillingTask, BillingTaskEvent, ProlongationBatch
from .services import update_task


@admin.register(BillingPeriod)
class BillingPeriodAdmin(admin.ModelAdmin):
    list_display = ["label", "status", "created_at", "updated_at"]
    list_filter = ["status", "year", "month"]
    ordering = ["-year", "-month"]


@admin.register(ProlongationBatch)
class ProlongationBatchAdmin(admin.ModelAdmin):
    list_display = ["label", "year", "month", "created_at", "updated_at"]
    list_filter = ["year", "month"]
    ordering = ["-year", "-month"]
    readonly_fields = ["created_at", "updated_at"]


@admin.register(BillingTask)
class BillingTaskAdmin(admin.ModelAdmin):
    list_display = [
        "payment_schedule",
        "period",
        "status",
        "invoice_request_deadline",
        "responsible",
    ]
    list_filter = ["status", "period", "responsible"]
    search_fields = [
        "payment_schedule__policy__policy_number",
        "payment_schedule__policy__dfa_number",
        "payment_schedule__policy__client__client_name",
        "payment_schedule__policy__insurer__insurer_name",
    ]
    raw_id_fields = ["payment_schedule", "responsible"]
    readonly_fields = ["created_at", "updated_at"]
    actions = [
        "bulk_set_to_request",
        "bulk_set_requested",
        "bulk_set_sent_to_leasing",
    ]
    # Ключи admin-actions, доступные только суперюзеру (см. get_actions).
    _SUPERUSER_ONLY_ACTIONS = (
        "bulk_set_to_request",
        "bulk_set_requested",
        "bulk_set_sent_to_leasing",
    )

    def get_actions(self, request):
        actions = super().get_actions(request)
        if not request.user.is_superuser:
            for key in self._SUPERUSER_ONLY_ACTIONS:
                actions.pop(key, None)
        return actions

    def _bulk_change_status(self, request, queryset, new_status, status_label):
        """Переводит выбранные задачи в new_status через сервис update_task.

        Сервис сам проставляет таймстампы (requested_at / sent_to_leasing_at),
        пишет BillingTaskEvent с пользователем и при необходимости назначает
        ответственного — поэтому идём через него поштучно, не bulk-update."""
        changed = 0
        skipped = 0
        with transaction.atomic():
            for task in queryset:
                if task.status == new_status:
                    skipped += 1
                    continue
                update_task(task, request.user, new_status=new_status)
                changed += 1

        if changed:
            self.message_user(
                request,
                f"Переведено в «{status_label}»: {changed}",
                level=messages.SUCCESS,
            )
        if skipped:
            self.message_user(
                request,
                f"Уже были в этом статусе и пропущены: {skipped}",
                level=messages.INFO,
            )

    @admin.action(description="Перевести в «Требуется запрос»")
    def bulk_set_to_request(self, request, queryset):
        self._bulk_change_status(
            request,
            queryset,
            BillingTask.STATUS_TO_REQUEST,
            "Требуется запрос",
        )

    @admin.action(description="Перевести в «Счет запрошен у СК»")
    def bulk_set_requested(self, request, queryset):
        self._bulk_change_status(
            request,
            queryset,
            BillingTask.STATUS_REQUESTED,
            "Счет запрошен у СК",
        )

    @admin.action(description="Перевести в «Передан в оплату в Альянс»")
    def bulk_set_sent_to_leasing(self, request, queryset):
        self._bulk_change_status(
            request,
            queryset,
            BillingTask.STATUS_SENT_TO_LEASING,
            "Передан в оплату в Альянс",
        )

    def save_model(self, request, obj, form, change):
        """Ручная правка статуса/комментария через админку идёт через сервис
        update_task — он пишет BillingTaskEvent с пользователем и proставляет
        timestamps. Иначе админ-изменения не попадали бы в блок «История»
        на карточке задачи."""
        if not change:
            super().save_model(request, obj, form, change)
            return

        changed_status = "status" in form.changed_data
        changed_comment = "comment" in form.changed_data
        other_fields_changed = [
            f for f in form.changed_data if f not in {"status", "comment"}
        ]

        if changed_status or changed_comment:
            previous = BillingTask.objects.get(pk=obj.pk)
            new_status = obj.status if changed_status else None
            new_comment = obj.comment if changed_comment else None
            # Применяем «бизнесовые» поля через сервис на оригинале из БД,
            # чтобы он сам рассчитал timestamps и записал event.
            update_task(
                previous,
                request.user,
                new_status=new_status,
                comment=new_comment,
            )
            # Если в форме поменялись ещё какие-то поля (responsible,
            # дедлайн и т.п.) — применяем их сверху обычным save_model.
            if other_fields_changed:
                # Обновляем obj свежими данными от сервиса, чтобы не затереть
                # status/comment/timestamps на старые значения формы.
                previous.refresh_from_db()
                for field in other_fields_changed:
                    setattr(previous, field, getattr(obj, field))
                previous.save(update_fields=[*other_fields_changed, "updated_at"])
            return

        super().save_model(request, obj, form, change)


@admin.register(BillingTaskEvent)
class BillingTaskEventAdmin(admin.ModelAdmin):
    list_display = ["task", "event_type", "user", "created_at"]
    list_filter = ["event_type", "created_at"]
    search_fields = [
        "task__payment_schedule__policy__policy_number",
        "task__payment_schedule__policy__dfa_number",
    ]
    readonly_fields = ["created_at", "updated_at"]
