from celery import shared_task
from django.core.mail import send_mail
from django.conf import settings
from django.utils import timezone
from datetime import timedelta
from apps.policies.models import PaymentSchedule


@shared_task
def check_upcoming_payments():
    """
    Check for upcoming payments and send notifications
    """
    today = timezone.now().date()

    # Check payments due in 7, 3, and 1 days
    for days_ahead in [7, 3, 1]:
        target_date = today + timedelta(days=days_ahead)

        payments = PaymentSchedule.objects.filter(
            due_date=target_date, paid_date__isnull=True
        ).select_related("policy", "policy__client", "policy__insurer")

        if payments.exists():
            send_payment_reminder(payments, days_ahead)

    return f"Checked payments for {today}"


@shared_task
def check_overdue_payments():
    """
    Check for overdue payments and send notifications
    """
    today = timezone.now().date()

    overdue_payments = PaymentSchedule.objects.filter(
        due_date__lt=today, paid_date__isnull=True
    ).select_related("policy", "policy__client", "policy__insurer")

    if overdue_payments.exists():
        send_overdue_notification(overdue_payments)

    return f"Checked overdue payments for {today}"


def send_payment_reminder(payments, days_ahead):
    """
    Send email reminder about upcoming payments
    """
    subject = f"Напоминание: платежи через {days_ahead} дней"

    message_lines = [
        f"Предстоящие платежи через {days_ahead} дней:\n",
    ]

    for payment in payments:
        message_lines.append(
            f"- Полис {payment.policy.policy_number}, "
            f"Клиент: {payment.policy.client.client_name}, "
            f"Сумма: {payment.amount} руб., "
            f'Дата: {payment.due_date.strftime("%d.%m.%Y")}'
        )

    message = "\n".join(message_lines)

    # Send email (configure recipients in settings or get from user model)
    send_mail(
        subject,
        message,
        settings.EMAIL_HOST_USER,
        [settings.EMAIL_HOST_USER],  # Replace with actual recipients
        fail_silently=True,
    )


def send_overdue_notification(payments):
    """
    Send email notification about overdue payments
    """
    subject = "Внимание: не оплаченные платежи"

    message_lines = [
        "Не оплаченные платежи:\n",
    ]

    for payment in payments:
        days_overdue = (timezone.now().date() - payment.due_date).days
        message_lines.append(
            f"- Полис {payment.policy.policy_number}, "
            f"Клиент: {payment.policy.client.client_name}, "
            f"Сумма: {payment.amount} руб., "
            f"Просрочка: {days_overdue} дней"
        )

    message = "\n".join(message_lines)

    send_mail(
        subject,
        message,
        settings.EMAIL_HOST_USER,
        [settings.EMAIL_HOST_USER],  # Replace with actual recipients
        fail_silently=True,
    )
