from django import forms
from django.core.exceptions import ValidationError
from django.core.validators import validate_email

from apps.communications.validators import validate_outbound_attachment


def parse_recipient_emails(raw):
    """Разбить строку с email-адресами через запятую/точку с запятой
    на список уникальных непустых значений в порядке появления."""
    if not raw:
        return []
    parts = raw.replace(";", ",").split(",")
    seen = set()
    result = []
    for part in parts:
        address = part.strip()
        if not address or address in seen:
            continue
        seen.add(address)
        result.append(address)
    return result


class RecipientEmailsField(forms.CharField):
    """Поле для нескольких email-адресов через запятую/точку с запятой."""

    default_error_messages = {
        "required": "Укажите хотя бы один email получателя",
    }

    def __init__(self, *args, **kwargs):
        kwargs.setdefault(
            "widget",
            forms.EmailInput(
                attrs={
                    "multiple": True,
                    "placeholder": "addr1@example.com, addr2@example.com",
                }
            ),
        )
        kwargs.setdefault("max_length", 1024)
        super().__init__(*args, **kwargs)

    def to_python(self, value):
        if value is None:
            return []
        return parse_recipient_emails(str(value))

    def validate(self, value):
        if not value:
            raise ValidationError(self.error_messages["required"], code="required")
        for address in value:
            try:
                validate_email(address)
            except ValidationError:
                raise ValidationError(f"Некорректный email: {address}", code="invalid")


class ManualRecipientEmailForm(forms.Form):
    recipient_email = RecipientEmailsField(
        label="Email получателя",
        help_text="Несколько адресов — через запятую или точку с запятой",
    )


class AllianceEmailForm(ManualRecipientEmailForm):
    invoice_file = forms.FileField(label="Счет")

    def clean_invoice_file(self):
        invoice_file = self.cleaned_data["invoice_file"]
        validate_outbound_attachment(invoice_file)
        return invoice_file
