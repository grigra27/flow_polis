from django.contrib import admin

from .models import BillingPeriod, BillingTask, BillingTaskEvent
from .services import update_task


@admin.register(BillingPeriod)
class BillingPeriodAdmin(admin.ModelAdmin):
    list_display = ["label", "status", "created_at", "updated_at"]
    list_filter = ["status", "year", "month"]
    ordering = ["-year", "-month"]


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
