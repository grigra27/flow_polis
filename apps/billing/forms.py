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


class _MultipleFileInput(forms.ClearableFileInput):
    """Виджет file-input с поддержкой множественного выбора.

    В Django 4.2 базовый FileInput.value_from_datadict делает files.get(name)
    и теряет все файлы кроме последнего. Здесь явно дергаем getlist, чтобы
    форма получила все загруженные файлы целиком.

    HTML-атрибут `multiple` уже выставлен в шаблоне task_detail.html, так
    что сам виджет здесь нужен только ради value_from_datadict."""

    def value_from_datadict(self, data, files, name):
        if hasattr(files, "getlist"):
            return files.getlist(name)
        return files.get(name)


class _MultipleFileField(forms.FileField):
    """FileField, который валидирует список файлов целиком."""

    def __init__(self, *args, **kwargs):
        kwargs.setdefault("widget", _MultipleFileInput())
        super().__init__(*args, **kwargs)

    def clean(self, data, initial=None):
        single_clean = super().clean
        if not data:
            # Сохраняем поведение required: super().clean пустое значение
            # уронит ValidationError("This field is required").
            return single_clean(data, initial)
        if isinstance(data, (list, tuple)):
            return [single_clean(item, initial) for item in data]
        return [single_clean(data, initial)]


class AllianceEmailForm(ManualRecipientEmailForm):
    # До 2 файлов (типичный кейс: счёт + спецификация/доп. документ).
    MAX_INVOICE_FILES = 2

    invoice_file = _MultipleFileField(label="Счет")

    def clean_invoice_file(self):
        files = self.cleaned_data["invoice_file"] or []
        if not files:
            raise ValidationError("Прикрепите файл счета")
        if len(files) > self.MAX_INVOICE_FILES:
            raise ValidationError(
                f"Можно прикрепить не более {self.MAX_INVOICE_FILES} файлов"
            )
        for uploaded in files:
            validate_outbound_attachment(uploaded)
        return files
