from django.conf import settings

from apps.communications.models import OutboundEmail
from apps.insurers.models import LeasingManager


def get_alliance_backup_manager():
    """Резервный получатель альянс-писем по ID из настроек.
    Возвращает LeasingManager или None, если ID не задан или карточка удалена."""
    manager_id = getattr(settings, "ALLIANCE_BACKUP_MANAGER_ID", 0)
    if not manager_id:
        return None
    return LeasingManager.objects.filter(pk=manager_id).first()


def get_alliance_primary_manager(policy):
    """Основной получатель альянс-письма для конкретного полиса.
    Для филиалов из ALLIANCE_BRANCH_MANAGER_OVERRIDES берётся фиксированный
    LeasingManager, для остальных — leasing_manager из карточки полиса."""
    overrides = getattr(settings, "ALLIANCE_BRANCH_MANAGER_OVERRIDES", {}) or {}
    branch_id = getattr(policy, "branch_id", None)
    override_id = overrides.get(branch_id)
    if override_id:
        manager = LeasingManager.objects.filter(pk=override_id).first()
        if manager:
            return manager
    return policy.leasing_manager


def build_insurer_request_email_payload(task, recipient_emails):
    insurer = task.payment_schedule.policy.insurer
    snapshot = list(getattr(insurer, "emails", []) or [])
    return {
        "kind": OutboundEmail.KIND_BILLING_INSURER_REQUEST,
        "content_object": task,
        "subject": task.build_letter_subject(),
        "body_text": task.build_letter_text(),
        "body_html": task.build_letter_html(),
        "to": recipient_emails,
        "metadata": {"insurer_emails_snapshot": snapshot},
    }


def build_alliance_forward_email_payload(task, recipient_emails):
    manager = get_alliance_primary_manager(task.payment_schedule.policy)
    primary_email = (getattr(manager, "email", "") or "").strip() if manager else ""
    backup_manager = get_alliance_backup_manager()
    backup_email = (backup_manager.email or "").strip() if backup_manager else ""
    snapshot = []
    for address in (primary_email, backup_email):
        if address and address not in snapshot:
            snapshot.append(address)
    return {
        "kind": OutboundEmail.KIND_BILLING_ALLIANCE_FORWARD,
        "content_object": task,
        "subject": task.build_alliance_letter_subject(),
        "body_text": task.build_alliance_letter_text(),
        "body_html": task.build_alliance_letter_html(),
        "to": recipient_emails,
        "metadata": {"manager_emails_snapshot": snapshot},
    }
