from django import forms
from django.contrib.auth.forms import AuthenticationForm


class CustomAuthenticationForm(AuthenticationForm):
    """
    Кастомная форма входа с русскими метками и Bootstrap стилями.
    
    Validates: Requirements 1.2, 1.3, 2.3
    """
    username = forms.CharField(
        label='Имя пользователя',
        max_length=150,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Введите имя пользователя',
            'autofocus': True,
        }),
        error_messages={
            'required': 'Пожалуйста, введите имя пользователя.',
        }
    )
    
    password = forms.CharField(
        label='Пароль',
        strip=False,
        widget=forms.PasswordInput(attrs={
            'class': 'form-control',
            'placeholder': 'Введите пароль',
            'autocomplete': 'current-password',
        }),
        error_messages={
            'required': 'Пожалуйста, введите пароль.',
        }
    )
    
    error_messages = {
        'invalid_login': 'Неверное имя пользователя или пароль.',
        'inactive': 'Ваша учетная запись деактивирована.',
    }
