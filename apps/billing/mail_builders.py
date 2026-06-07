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


def get_alliance_branch_managers(policy):
    """Менеджеры-получатели альянс-письма для конкретного полиса.

    В список попадают:
    1) все LeasingManager филиала полиса с непустым email;
    2) leasing_manager карточки полиса, если у него есть email и он
       не вошёл в выборку по филиалу (например, прикреплён к другому филиалу).

    Сортировка по name, дедуп по pk. Менеджеры без email отбрасываются —
    кликабельный чип без адреса бесполезен.
    """
    managers = []
    seen_ids = set()
    branch_id = getattr(policy, "branch_id", None)
    if branch_id:
        for manager in (
            LeasingManager.objects.filter(branch_id=branch_id)
            .exclude(email="")
            .order_by("name")
        ):
            managers.append(manager)
            seen_ids.add(manager.pk)
    policy_manager = policy.leasing_manager
    if (
        policy_manager
        and policy_manager.pk not in seen_ids
        and (policy_manager.email or "").strip()
    ):
        managers.append(policy_manager)
    return managers


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
    branch_managers = get_alliance_branch_managers(policy)
    backup_manager = get_alliance_backup_manager()
    backup_email = (backup_manager.email or "").strip() if backup_manager else ""
    branch_extra_emails = get_alliance_branch_extra_emails(policy)
    snapshot = []
    for manager in branch_managers:
        address = (manager.email or "").strip()
        if address and address not in snapshot:
            snapshot.append(address)
    for address in (backup_email, *branch_extra_emails):
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


def build_prolongation_forward_email_payload(
    batch, recipient_emails, policies_count=None
):
    return {
        "kind": OutboundEmail.KIND_PROLONGATION_FORWARD,
        "content_object": batch,
        "subject": batch.build_letter_subject(),
        "body_text": batch.build_letter_text(policies_count),
        "body_html": batch.build_letter_html(policies_count),
        "to": recipient_emails,
        "metadata": {"period": batch.code, "policies_count": policies_count or 0},
    }
