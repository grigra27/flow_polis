from django import forms

from apps.core.file_validators import FileUploadValidator


class AcceptUploadForm(forms.Form):
    accept_file = forms.FileField(
        label="Файл акцепта",
        help_text="Загрузите распоряжение на страхование в формате .xls или .xlsx.",
    )

    def clean_accept_file(self):
        uploaded_file = self.cleaned_data["accept_file"]
        extension = FileUploadValidator.get_extension(uploaded_file.name)
        if extension not in {"xls", "xlsx"}:
            raise forms.ValidationError("Поддерживаются только файлы .xls и .xlsx.")

        is_valid, error, _ = FileUploadValidator.validate_file(uploaded_file)
        if not is_valid:
            raise forms.ValidationError(error)
        return uploaded_file
