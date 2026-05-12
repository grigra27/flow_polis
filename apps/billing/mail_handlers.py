from apps.communications.models import OutboundEmail

from .models import BillingTask
from .services import update_task


def handle_billing_email_sent(email):
    task = email.content_object
    if not isinstance(task, BillingTask):
        return

    user = email.sent_by or email.created_by
    if email.kind == OutboundEmail.KIND_BILLING_INSURER_REQUEST:
        update_task(task, user, new_status=BillingTask.STATUS_REQUESTED)
    elif email.kind == OutboundEmail.KIND_BILLING_ALLIANCE_FORWARD:
        update_task(task, user, new_status=BillingTask.STATUS_SENT_TO_LEASING)
