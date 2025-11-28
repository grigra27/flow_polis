from django import forms


class CustomExportForm(forms.Form):
    """Форма для конструктора кастомного экспорта"""
    
    DATA_SOURCE_CHOICES = [
        ('policies', 'Полисы'),
        ('payments', 'Платежи'),
        ('clients', 'Клиенты'),
        ('insurers', 'Страховщики'),
    ]
    
    data_source = forms.ChoiceField(
        choices=DATA_SOURCE_CHOICES,
        label='Источник данных',
        widget=forms.RadioSelect,
        initial='policies'
    )
    
    def clean_data_source(self):
        """Валидация источника данных"""
        data_source = self.cleaned_data.get('data_source')
        valid_sources = [choice[0] for choice in self.DATA_SOURCE_CHOICES]
        if data_source not in valid_sources:
            raise forms.ValidationError('Недопустимый источник данных')
        return data_source
