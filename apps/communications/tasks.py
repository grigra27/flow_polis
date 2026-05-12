from celery import shared_task

from .services import send_outbound_email_now


@shared_task(bind=True, max_retries=0)
def send_outbound_email(self, email_id):
    return send_outbound_email_now(email_id)
