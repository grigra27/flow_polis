"""
Unit-тесты для валидаторов паролей.

Validates: Requirements 2.1, 2.3, 2.4
"""
import pytest
from django.core.exceptions import ValidationError
from apps.accounts.validators import ComplexityPasswordValidator, WeakPasswordValidator


class TestComplexityPasswordValidator:
    """
    Unit-тесты для ComplexityPasswordValidator.

    Validates: Requirements 2.1, 2.3
    """

    def test_reject_short_password(self):
        """
        Тест отклонения короткого пароля.

        Validates: Requirement 2.1
        """
        validator = ComplexityPasswordValidator()

        # Пароли короче 12 символов должны быть отклонены
        short_passwords = [
            "",
            "a",
            "abc",
            "Pass1!",
            "Password1!",  # 10 символов
            "MyPass123!",  # 11 символов
        ]

        for password in short_passwords:
            with pytest.raises(ValidationError) as exc_info:
                validator.validate(password)

            error_messages = [str(e) for e in exc_info.value.messages]
            assert any(
                "12 символов" in msg for msg in error_messages
            ), f"Expected length error for password: {password}"

    def test_reject_simple_password_no_uppercase(self):
        """
        Тест отклонения пароля без заглавных букв.

        Validates: Requirement 2.3
        """
        validator = ComplexityPasswordValidator()

        # Пароли без заглавных букв
        passwords = [
            "password123!",
            "mypassword123!",
            "test12345678!",
            "абвгд123456!",
        ]

        for password in passwords:
            with pytest.raises(ValidationError) as exc_info:
                validator.validate(password)

            error_messages = [str(e) for e in exc_info.value.messages]
            assert any(
                "заглавную букву" in msg for msg in error_messages
            ), f"Expected uppercase error for password: {password}"

    def test_reject_simple_password_no_lowercase(self):
        """
        Тест отклонения пароля без строчных букв.

        Validates: Requirement 2.3
        """
        validator = ComplexityPasswordValidator()

        # Пароли без строчных букв
        passwords = [
            "PASSWORD123!",
            "MYPASSWORD123!",
            "TEST12345678!",
            "АБВГД123456!",
        ]

        for password in passwords:
            with pytest.raises(ValidationError) as exc_info:
                validator.validate(password)

            error_messages = [str(e) for e in exc_info.value.messages]
            assert any(
                "строчную букву" in msg for msg in error_messages
            ), f"Expected lowercase error for password: {password}"

    def test_reject_simple_password_no_digit(self):
        """
        Тест отклонения пароля без цифр.

        Validates: Requirement 2.3
        """
        validator = ComplexityPasswordValidator()

        # Пароли без цифр
        passwords = [
            "MyPassword!!!",
            "TestPassword!",
            "SecurePass!!!",
            "МойПароль!!!",
        ]

        for password in passwords:
            with pytest.raises(ValidationError) as exc_info:
                validator.validate(password)

            error_messages = [str(e) for e in exc_info.value.messages]
            assert any(
                "цифру" in msg for msg in error_messages
            ), f"Expected digit error for password: {password}"

    def test_reject_simple_password_no_special_char(self):
        """
        Тест отклонения пароля без специальных символов.

        Validates: Requirement 2.3
        """
        validator = ComplexityPasswordValidator()

        # Пароли без специальных символов
        passwords = [
            "MyPassword123",
            "TestPassword456",
            "SecurePass789",
            "МойПароль123",
        ]

        for password in passwords:
            with pytest.raises(ValidationError) as exc_info:
                validator.validate(password)

            error_messages = [str(e) for e in exc_info.value.messages]
            assert any(
                "специальный символ" in msg for msg in error_messages
            ), f"Expected special char error for password: {password}"

    def test_accept_complex_password(self):
        """
        Тест принятия сложного пароля.

        Validates: Requirements 2.1, 2.3
        """
        validator = ComplexityPasswordValidator()

        # Валидные сложные пароли
        valid_passwords = [
            "MyPassword123!",
            "SecurePass456@",
            "TestPassword789#",
            "Complex$Pass123",
            "МойПароль123!",
            "Тест123Пароль!",
            "Abc123!@#Def456",
            "P@ssw0rd!Complex",
            "!Qwerty123456!",
            "MyStr0ng!Pass",
            "C0mpl3x&Secure",
            "Test!ng123Pass",
        ]

        for password in valid_passwords:
            # Не должно быть исключений
            try:
                validator.validate(password)
            except ValidationError as e:
                pytest.fail(
                    f"Valid password rejected: {password}, errors: {e.messages}"
                )

    def test_multiple_errors(self):
        """
        Тест что валидатор возвращает все ошибки сразу.

        Validates: Requirements 2.1, 2.3
        """
        validator = ComplexityPasswordValidator()

        # Пароль с множественными проблемами
        password = "short"  # Короткий, без заглавных, без цифр, без спецсимволов

        with pytest.raises(ValidationError) as exc_info:
            validator.validate(password)

        error_messages = [str(e) for e in exc_info.value.messages]

        # Должно быть несколько ошибок
        assert len(error_messages) >= 2, "Expected multiple validation errors"

    def test_get_help_text(self):
        """
        Тест что валидатор возвращает текст помощи.
        """
        validator = ComplexityPasswordValidator()
        help_text = validator.get_help_text()

        assert "12 символов" in help_text
        assert "заглавные" in help_text or "строчные" in help_text


class TestWeakPasswordValidator:
    """
    Unit-тесты для WeakPasswordValidator.

    Validates: Requirement 2.4
    """

    def test_reject_weak_passwords_from_list(self):
        """
        Тест отклонения слабых паролей из списка.

        Validates: Requirement 2.4
        """
        validator = WeakPasswordValidator()

        # Примеры слабых паролей из списка
        weak_passwords = [
            "admin",
            "password",
            "password123",
            "12345678",
            "qwerty",
            "admin123",
            "пароль",
            "test123",
            "letmein",
            "welcome",
        ]

        for password in weak_passwords:
            with pytest.raises(ValidationError) as exc_info:
                validator.validate(password)

            assert (
                exc_info.value.code == "weak_password"
            ), f"Expected weak_password error for: {password}"

    def test_reject_weak_passwords_case_insensitive(self):
        """
        Тест отклонения слабых паролей независимо от регистра.

        Validates: Requirement 2.4
        """
        validator = WeakPasswordValidator()

        # Слабые пароли в разных регистрах
        test_cases = [
            ("admin", "ADMIN", "Admin", "aDmIn"),
            ("password", "PASSWORD", "Password", "PaSsWoRd"),
            ("qwerty", "QWERTY", "Qwerty", "qWeRtY"),
        ]

        for variations in test_cases:
            for password in variations:
                with pytest.raises(ValidationError) as exc_info:
                    validator.validate(password)

                assert (
                    exc_info.value.code == "weak_password"
                ), f"Expected weak_password error for: {password}"

    def test_accept_strong_password_not_in_list(self):
        """
        Тест принятия надежного пароля не из списка слабых.

        Validates: Requirement 2.4
        """
        validator = WeakPasswordValidator()

        # Пароли не из списка слабых (даже если они не соответствуют другим требованиям)
        strong_passwords = [
            "MyUniquePassword123!",
            "SecureAndComplex456@",
            "NotInWeakList789#",
            "CustomPassword$123",
            "МойУникальныйПароль!",
        ]

        for password in strong_passwords:
            # Не должно быть исключений от WeakPasswordValidator
            try:
                validator.validate(password)
            except ValidationError as e:
                pytest.fail(f"Strong password rejected: {password}, error: {e}")

    def test_reject_weak_password_with_modifications(self):
        """
        Тест отклонения слабых паролей с небольшими модификациями.

        Validates: Requirement 2.4
        """
        validator = WeakPasswordValidator()

        # Слабые пароли с добавлением символов (все еще в списке)
        weak_with_mods = [
            "password!",
            "password@123",
            "admin!",
            "admin@123",
            "qwerty!",
            "12345678!",
        ]

        for password in weak_with_mods:
            with pytest.raises(ValidationError) as exc_info:
                validator.validate(password)

            assert (
                exc_info.value.code == "weak_password"
            ), f"Expected weak_password error for: {password}"

    def test_get_help_text(self):
        """
        Тест что валидатор возвращает текст помощи.
        """
        validator = WeakPasswordValidator()
        help_text = validator.get_help_text()

        assert "распространенным" in help_text or "легко угадываемым" in help_text


class TestPasswordValidatorsIntegration:
    """
    Интеграционные тесты для комбинации валидаторов.

    Validates: Requirements 2.1, 2.3, 2.4
    """

    def test_both_validators_reject_weak_and_simple(self):
        """
        Тест что оба валидатора работают вместе.
        """
        complexity_validator = ComplexityPasswordValidator()
        weak_validator = WeakPasswordValidator()

        # Пароль который слабый И не соответствует требованиям сложности
        password = "admin"

        # Должен быть отклонен обоими валидаторами
        with pytest.raises(ValidationError):
            complexity_validator.validate(password)

        with pytest.raises(ValidationError):
            weak_validator.validate(password)

    def test_both_validators_accept_strong_complex(self):
        """
        Тест что оба валидатора принимают надежный сложный пароль.
        """
        complexity_validator = ComplexityPasswordValidator()
        weak_validator = WeakPasswordValidator()

        # Пароль который надежный И соответствует требованиям сложности
        password = "MyStr0ng!UniquePass"

        # Не должно быть исключений
        try:
            complexity_validator.validate(password)
            weak_validator.validate(password)
        except ValidationError as e:
            pytest.fail(f"Strong password rejected: {password}, error: {e}")

    def test_weak_but_complex_password(self):
        """
        Тест что слабый пароль отклоняется даже если он сложный.
        """
        complexity_validator = ComplexityPasswordValidator()
        weak_validator = WeakPasswordValidator()

        # Пароль из списка слабых, но соответствующий требованиям сложности
        password = "Password@123"

        # Должен пройти проверку сложности
        try:
            complexity_validator.validate(password)
        except ValidationError as e:
            pytest.fail(f"Complex password rejected by complexity validator: {e}")

        # Но должен быть отклонен как слабый
        with pytest.raises(ValidationError) as exc_info:
            weak_validator.validate(password)

        assert exc_info.value.code == "weak_password"
