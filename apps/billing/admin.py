from django.contrib import admin

from .models import BillingPeriod, BillingTask, BillingTaskEvent


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


@admin.register(BillingTaskEvent)
class BillingTaskEventAdmin(admin.ModelAdmin):
    list_display = ["task", "event_type", "user", "created_at"]
    list_filter = ["event_type", "created_at"]
    search_fields = [
        "task__payment_schedule__policy__policy_number",
        "task__payment_schedule__policy__dfa_number",
    ]
    readonly_fields = ["created_at", "updated_at"]
