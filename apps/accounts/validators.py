"""
Кастомные валидаторы паролей для усиления политики безопасности.

Validates: Requirements 2.1, 2.3, 2.4
"""
import re
from django.core.exceptions import ValidationError
from django.utils.translation import gettext as _


class ComplexityPasswordValidator:
    """
    Валидатор сложности пароля.

    Проверяет что пароль содержит:
    - Минимум 12 символов
    - Как минимум одну заглавную букву
    - Как минимум одну строчную букву
    - Как минимум одну цифру
    - Как минимум один специальный символ

    Validates: Requirements 2.1, 2.3
    """

    def __init__(self, min_length=12):
        self.min_length = min_length

    def validate(self, password, user=None):
        """
        Валидирует пароль на соответствие требованиям сложности.

        Args:
            password: Пароль для проверки
            user: Объект пользователя (опционально)

        Raises:
            ValidationError: Если пароль не соответствует требованиям
        """
        errors = []

        # Проверка минимальной длины
        if len(password) < self.min_length:
            errors.append(
                _(f"Пароль должен содержать минимум {self.min_length} символов.")
            )

        # Проверка наличия заглавной буквы
        if not re.search(r"[A-ZА-ЯЁ]", password):
            errors.append(_("Пароль должен содержать хотя бы одну заглавную букву."))

        # Проверка наличия строчной буквы
        if not re.search(r"[a-zа-яё]", password):
            errors.append(_("Пароль должен содержать хотя бы одну строчную букву."))

        # Проверка наличия цифры
        if not re.search(r"\d", password):
            errors.append(_("Пароль должен содержать хотя бы одну цифру."))

        # Проверка наличия специального символа
        if not re.search(r'[!@#$%^&*()_+\-=\[\]{};:\'",.<>?/\\|`~]', password):
            errors.append(
                _(
                    "Пароль должен содержать хотя бы один специальный символ (!@#$%^&* и т.д.)."
                )
            )

        if errors:
            raise ValidationError(errors)

    def get_help_text(self):
        """Возвращает текст помощи для пользователя."""
        return _(
            f"Ваш пароль должен содержать минимум {self.min_length} символов, "
            "включая заглавные и строчные буквы, цифры и специальные символы."
        )


class WeakPasswordValidator:
    """
    Валидатор слабых паролей.

    Проверяет пароль против списка часто используемых слабых паролей.

    Validates: Requirement 2.4
    """

    # Список слабых паролей (расширяемый)
    WEAK_PASSWORDS = {
        "admin",
        "administrator",
        "root",
        "superuser",
        "password",
        "password123",
        "password1",
        "pass123",
        "12345678",
        "123456789",
        "1234567890",
        "123123123",
        "qwerty",
        "qwerty123",
        "qwertyuiop",
        "letmein",
        "welcome",
        "welcome123",
        "admin123",
        "admin1234",
        "root123",
        "пароль",
        "пароль123",
        "администратор",
        "test",
        "test123",
        "testing",
        "user",
        "user123",
        "username",
        "changeme",
        "change123",
        "default",
        "default123",
        "guest",
        "guest123",
        "demo",
        "demo123",
        "sample",
        "sample123",
        "temp",
        "temp123",
        "temporary",
        "password!",
        "password@123",
        "password#123",
        "admin!",
        "admin@123",
        "admin#123",
        "qwerty!",
        "qwerty@123",
        "12345678!",
        "123456789!",
        "abc123",
        "abc123!",
        "abc@123",
        "iloveyou",
        "iloveyou123",
        "monkey",
        "monkey123",
        "dragon",
        "dragon123",
        "master",
        "master123",
        "sunshine",
        "sunshine123",
        "princess",
        "princess123",
        "football",
        "football123",
        "baseball",
        "baseball123",
        "trustno1",
        "trustno1!",
    }

    def validate(self, password, user=None):
        """
        Валидирует пароль на отсутствие в списке слабых паролей.

        Args:
            password: Пароль для проверки
            user: Объект пользователя (опционально)

        Raises:
            ValidationError: Если пароль находится в списке слабых
        """
        # Проверяем пароль в нижнем регистре для case-insensitive сравнения
        if password.lower() in self.WEAK_PASSWORDS:
            raise ValidationError(
                _(
                    "Этот пароль слишком распространен и небезопасен. Пожалуйста, выберите более надежный пароль."
                ),
                code="weak_password",
            )

    def get_help_text(self):
        """Возвращает текст помощи для пользователя."""
        return _(
            "Ваш пароль не должен быть слишком распространенным или легко угадываемым."
        )
