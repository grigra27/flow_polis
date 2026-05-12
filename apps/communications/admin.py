from django.contrib import admin, messages

from .models import (
    EmailDeliveryAttempt,
    MailAccount,
    OutboundEmail,
    OutboundEmailAttachment,
    OutboundEmailRecipient,
)
from .services import CommunicationsError, retry_outbound_email


@admin.register(MailAccount)
class MailAccountAdmin(admin.ModelAdmin):
    list_display = ["code", "name", "email", "provider", "is_default", "is_active"]
    list_filter = ["provider", "is_default", "is_active"]
    search_fields = ["code", "name", "email"]
    readonly_fields = ["created_at", "updated_at"]


class OutboundEmailRecipientInline(admin.TabularInline):
    model = OutboundEmailRecipient
    extra = 0
    readonly_fields = ["created_at", "updated_at"]
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False


class OutboundEmailAttachmentInline(admin.TabularInline):
    model = OutboundEmailAttachment
    extra = 0
    readonly_fields = [
        "original_filename",
        "content_type",
        "size",
        "checksum",
        "created_at",
        "updated_at",
    ]
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False


class EmailDeliveryAttemptInline(admin.TabularInline):
    model = EmailDeliveryAttempt
    extra = 0
    readonly_fields = [
        "attempt_number",
        "status",
        "started_at",
        "finished_at",
        "error_message",
        "provider_response",
        "created_at",
        "updated_at",
    ]
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(OutboundEmail)
class OutboundEmailAdmin(admin.ModelAdmin):
    list_display = [
        "id",
        "kind",
        "status",
        "subject",
        "from_email",
        "created_by",
        "sent_at",
        "created_at",
    ]
    list_filter = ["kind", "status", "account", "created_at", "sent_at"]
    search_fields = [
        "subject",
        "message_id",
        "provider_message_id",
        "recipients__address",
    ]
    raw_id_fields = ["created_by", "sent_by", "content_type"]
    readonly_fields = [
        "kind",
        "from_email",
        "from_name",
        "reply_to",
        "subject",
        "body_text",
        "body_html",
        "content_type",
        "object_id",
        "queued_at",
        "sending_started_at",
        "sent_at",
        "failed_at",
        "last_error",
        "message_id",
        "provider_message_id",
        "headers",
        "created_at",
        "updated_at",
    ]
    inlines = [
        OutboundEmailRecipientInline,
        OutboundEmailAttachmentInline,
        EmailDeliveryAttemptInline,
    ]
    actions = ["retry_failed_emails"]

    def has_add_permission(self, request):
        return False

    @admin.action(description="Повторить отправку failed-писем")
    def retry_failed_emails(self, request, queryset):
        retried = 0
        for email in queryset:
            try:
                retry_outbound_email(email, user=request.user)
                retried += 1
            except CommunicationsError as exc:
                self.message_user(
                    request,
                    f"Письмо #{email.id}: {exc}",
                    level=messages.WARNING,
                )
        if retried:
            self.message_user(
                request,
                f"Поставлено в очередь повторно: {retried}",
                level=messages.SUCCESS,
            )


@admin.register(OutboundEmailRecipient)
class OutboundEmailRecipientAdmin(admin.ModelAdmin):
    list_display = ["email", "recipient_type", "address", "name"]
    list_filter = ["recipient_type"]
    search_fields = ["address", "name", "email__subject"]
    raw_id_fields = ["email"]
    readonly_fields = ["created_at", "updated_at"]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(OutboundEmailAttachment)
class OutboundEmailAttachmentAdmin(admin.ModelAdmin):
    list_display = ["email", "original_filename", "content_type", "size", "checksum"]
    search_fields = ["original_filename", "checksum", "email__subject"]
    raw_id_fields = ["email"]
    readonly_fields = ["created_at", "updated_at"]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(EmailDeliveryAttempt)
class EmailDeliveryAttemptAdmin(admin.ModelAdmin):
    list_display = ["email", "attempt_number", "status", "started_at", "finished_at"]
    list_filter = ["status", "created_at"]
    search_fields = ["email__subject", "error_message", "provider_response"]
    raw_id_fields = ["email"]
    readonly_fields = ["created_at", "updated_at"]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
