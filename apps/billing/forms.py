from django import forms

from apps.communications.validators import validate_outbound_attachment


class ManualRecipientEmailForm(forms.Form):
    recipient_email = forms.EmailField(label="Email получателя")


class AllianceEmailForm(ManualRecipientEmailForm):
    invoice_file = forms.FileField(label="Счет")

    def clean_invoice_file(self):
        invoice_file = self.cleaned_data["invoice_file"]
        validate_outbound_attachment(invoice_file)
        return invoice_file
