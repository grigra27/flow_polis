from apps.communications.models import OutboundEmail


def build_insurer_request_email_payload(task, recipient_email):
    return {
        "kind": OutboundEmail.KIND_BILLING_INSURER_REQUEST,
        "content_object": task,
        "subject": task.build_letter_subject(),
        "body_text": task.build_letter_text(),
        "body_html": task.build_letter_html(),
        "to": recipient_email,
    }


def build_alliance_forward_email_payload(task, recipient_email):
    return {
        "kind": OutboundEmail.KIND_BILLING_ALLIANCE_FORWARD,
        "content_object": task,
        "subject": task.build_alliance_letter_subject(),
        "body_text": task.build_alliance_letter_text(),
        "body_html": task.build_alliance_letter_html(),
        "to": recipient_email,
    }
