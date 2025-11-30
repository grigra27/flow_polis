from django import forms
from django.contrib.auth.forms import (
    AuthenticationForm,
    PasswordChangeForm,
    SetPasswordForm,
)
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError


class CustomAuthenticationForm(AuthenticationForm):
    """
    Кастомная форма входа с русскими метками и Bootstrap стилями.

    Validates: Requirements 1.2, 1.3, 2.3
    """

    username = forms.CharField(
        label="Имя пользователя",
        max_length=150,
        widget=forms.TextInput(
            attrs={
                "class": "form-control",
                "placeholder": "Введите имя пользователя",
                "autofocus": True,
            }
        ),
        error_messages={
            "required": "Пожалуйста, введите имя пользователя.",
        },
    )

    password = forms.CharField(
        label="Пароль",
        strip=False,
        widget=forms.PasswordInput(
            attrs={
                "class": "form-control",
                "placeholder": "Введите пароль",
                "autocomplete": "current-password",
            }
        ),
        error_messages={
            "required": "Пожалуйста, введите пароль.",
        },
    )

    error_messages = {
        "invalid_login": "Неверное имя пользователя или пароль.",
        "inactive": "Ваша учетная запись деактивирована.",
    }


class CustomPasswordChangeForm(PasswordChangeForm):
    """
    Кастомная форма смены пароля с понятными сообщениями об ошибках.

    Validates: Requirements 2.1, 2.3, 2.4
    """

    old_password = forms.CharField(
        label="Текущий пароль",
        strip=False,
        widget=forms.PasswordInput(
            attrs={
                "class": "form-control",
                "placeholder": "Введите текущий пароль",
                "autocomplete": "current-password",
                "autofocus": True,
            }
        ),
        error_messages={
            "required": "Пожалуйста, введите текущий пароль.",
        },
    )

    new_password1 = forms.CharField(
        label="Новый пароль",
        strip=False,
        widget=forms.PasswordInput(
            attrs={
                "class": "form-control",
                "placeholder": "Введите новый пароль",
                "autocomplete": "new-password",
            }
        ),
        help_text=(
            "Ваш пароль должен содержать минимум 12 символов, "
            "включая заглавные и строчные буквы, цифры и специальные символы."
        ),
        error_messages={
            "required": "Пожалуйста, введите новый пароль.",
        },
    )

    new_password2 = forms.CharField(
        label="Подтверждение нового пароля",
        strip=False,
        widget=forms.PasswordInput(
            attrs={
                "class": "form-control",
                "placeholder": "Введите новый пароль еще раз",
                "autocomplete": "new-password",
            }
        ),
        error_messages={
            "required": "Пожалуйста, подтвердите новый пароль.",
        },
    )

    error_messages = {
        "password_mismatch": "Введенные пароли не совпадают.",
        "password_incorrect": "Текущий пароль введен неверно.",
    }

    def clean_new_password1(self):
        """Валидирует новый пароль с понятными сообщениями об ошибках."""
        password = self.cleaned_data.get("new_password1")
        if password:
            try:
                validate_password(password, self.user)
            except ValidationError as error:
                # Преобразуем ошибки в более понятный формат
                raise ValidationError(error.messages)
        return password


class CustomSetPasswordForm(SetPasswordForm):
    """
    Кастомная форма установки пароля с понятными сообщениями об ошибках.

    Используется при сбросе пароля.

    Validates: Requirements 2.1, 2.3, 2.4
    """

    new_password1 = forms.CharField(
        label="Новый пароль",
        strip=False,
        widget=forms.PasswordInput(
            attrs={
                "class": "form-control",
                "placeholder": "Введите новый пароль",
                "autocomplete": "new-password",
                "autofocus": True,
            }
        ),
        help_text=(
            "Ваш пароль должен содержать минимум 12 символов, "
            "включая заглавные и строчные буквы, цифры и специальные символы."
        ),
        error_messages={
            "required": "Пожалуйста, введите новый пароль.",
        },
    )

    new_password2 = forms.CharField(
        label="Подтверждение нового пароля",
        strip=False,
        widget=forms.PasswordInput(
            attrs={
                "class": "form-control",
                "placeholder": "Введите новый пароль еще раз",
                "autocomplete": "new-password",
            }
        ),
        error_messages={
            "required": "Пожалуйста, подтвердите новый пароль.",
        },
    )

    error_messages = {
        "password_mismatch": "Введенные пароли не совпадают.",
    }

    def clean_new_password1(self):
        """Валидирует новый пароль с понятными сообщениями об ошибках."""
        password = self.cleaned_data.get("new_password1")
        if password:
            try:
                validate_password(password, self.user)
            except ValidationError as error:
                # Преобразуем ошибки в более понятный формат
                raise ValidationError(error.messages)
        return password
