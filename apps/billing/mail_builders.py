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


def get_alliance_branch_extra_emails(policy):
    """Дополнительные адреса альянс-письма для филиала.
    Возвращает список (возможно пустой) непустых, очищенных от пробелов email."""
    mapping = getattr(settings, "ALLIANCE_BRANCH_EXTRA_EMAILS", {}) or {}
    branch_id = getattr(policy, "branch_id", None)
    raw = mapping.get(branch_id, [])
    if isinstance(raw, str):
        raw = [raw]
    cleaned = []
    seen = set()
    for address in raw or []:
        address = (address or "").strip()
        if address and address not in seen:
            seen.add(address)
            cleaned.append(address)
    return cleaned


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
    policy = task.payment_schedule.policy
    manager = get_alliance_primary_manager(policy)
    primary_email = (getattr(manager, "email", "") or "").strip() if manager else ""
    backup_manager = get_alliance_backup_manager()
    backup_email = (backup_manager.email or "").strip() if backup_manager else ""
    branch_extra_emails = get_alliance_branch_extra_emails(policy)
    snapshot = []
    for address in (primary_email, backup_email, *branch_extra_emails):
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
