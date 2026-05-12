from apps.communications.models import OutboundEmail

from .models import BillingTask
from .services import update_task


_STATUS_ORDER = {
    BillingTask.STATUS_TO_REQUEST: 0,
    BillingTask.STATUS_REQUESTED: 1,
    BillingTask.STATUS_SENT_TO_LEASING: 2,
}


def _is_forward_status_change(task, target_status):
    current = _STATUS_ORDER.get(task.status)
    target = _STATUS_ORDER.get(target_status)
    if current is None or target is None:
        return False
    return target > current


def handle_billing_email_sent(email):
    task = email.content_object
    if not isinstance(task, BillingTask):
        return

    if email.kind == OutboundEmail.KIND_BILLING_INSURER_REQUEST:
        target_status = BillingTask.STATUS_REQUESTED
    elif email.kind == OutboundEmail.KIND_BILLING_ALLIANCE_FORWARD:
        target_status = BillingTask.STATUS_SENT_TO_LEASING
    else:
        return

    if not _is_forward_status_change(task, target_status):
        return

    user = email.sent_by or email.created_by
    update_task(task, user, new_status=target_status)
