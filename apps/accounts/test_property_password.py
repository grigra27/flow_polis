"""
Property-based тесты для валидации паролей.

Feature: security-optimization-audit
Validates: Requirements 2.1, 2.3
"""
import pytest
from hypothesis import given, strategies as st, settings
from django.core.exceptions import ValidationError
from apps.accounts.validators import ComplexityPasswordValidator, WeakPasswordValidator


# Стратегии для генерации паролей
@st.composite
def short_passwords(draw):
    """Генерирует пароли короче 12 символов."""
    length = draw(st.integers(min_value=0, max_value=11))
    return draw(st.text(min_size=length, max_size=length))


@st.composite
def passwords_without_uppercase(draw):
    """Генерирует пароли без заглавных букв (минимум 12 символов)."""
    # Используем только строчные буквы, цифры и спецсимволы
    alphabet = "abcdefghijklmnopqrstuvwxyzабвгдежзийклмнопрстуфхцчшщъыьэюя0123456789!@#$%^&*()_+-=[]{};':\"|,.<>?/\\`~"
    length = draw(st.integers(min_value=12, max_value=50))
    return draw(st.text(alphabet=alphabet, min_size=length, max_size=length))


@st.composite
def passwords_without_lowercase(draw):
    """Генерирует пароли без строчных букв (минимум 12 символов)."""
    # Используем только заглавные буквы, цифры и спецсимволы
    alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZАБВГДЕЖЗИЙКЛМНОПРСТУФХЦЧШЩЪЫЬЭЮЯ0123456789!@#$%^&*()_+-=[]{};':\"|,.<>?/\\`~"
    length = draw(st.integers(min_value=12, max_value=50))
    return draw(st.text(alphabet=alphabet, min_size=length, max_size=length))


@st.composite
def passwords_without_digits(draw):
    """Генерирует пароли без цифр (минимум 12 символов)."""
    # Используем только буквы и спецсимволы
    alphabet = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZабвгдежзийклмнопрстуфхцчшщъыьэюяАБВГДЕЖЗИЙКЛМНОПРСТУФХЦЧШЩЪЫЬЭЮЯ!@#$%^&*()_+-=[]{};':\"|,.<>?/\\`~"
    length = draw(st.integers(min_value=12, max_value=50))
    return draw(st.text(alphabet=alphabet, min_size=length, max_size=length))


@st.composite
def passwords_without_special_chars(draw):
    """Генерирует пароли без специальных символов (минимум 12 символов)."""
    # Используем только буквы и цифры
    alphabet = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZабвгдежзийклмнопрстуфхцчшщъыьэюяАБВГДЕЖЗИЙКЛМНОПРСТУФХЦЧШЩЪЫЬЭЮЯ0123456789"
    length = draw(st.integers(min_value=12, max_value=50))
    return draw(st.text(alphabet=alphabet, min_size=length, max_size=length))


@st.composite
def valid_complex_passwords(draw):
    """Генерирует валидные сложные пароли."""
    # Гарантируем наличие всех требуемых типов символов
    length = draw(st.integers(min_value=12, max_value=50))

    # Обязательные символы
    uppercase = draw(
        st.sampled_from("ABCDEFGHIJKLMNOPQRSTUVWXYZАБВГДЕЖЗИЙКЛМНОПРСТУФХЦЧШЩЪЫЬЭЮЯ")
    )
    lowercase = draw(
        st.sampled_from("abcdefghijklmnopqrstuvwxyzабвгдежзийклмнопрстуфхцчшщъыьэюя")
    )
    digit = draw(st.sampled_from("0123456789"))
    special = draw(st.sampled_from("!@#$%^&*()_+-=[]{};':\"|,.<>?/\\`~"))

    # Остальные символы
    remaining_length = length - 4
    all_chars = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789!@#$%^&*()_+-=[]{};':\"|,.<>?/\\`~"
    remaining = draw(
        st.text(
            alphabet=all_chars, min_size=remaining_length, max_size=remaining_length
        )
    )

    # Собираем пароль и перемешиваем
    password_list = list(uppercase + lowercase + digit + special + remaining)
    draw(st.randoms()).shuffle(password_list)
    return "".join(password_list)


class TestComplexityPasswordValidator:
    """
    Тесты для ComplexityPasswordValidator.

    Feature: security-optimization-audit, Property 5: Минимальная длина пароля
    Feature: security-optimization-audit, Property 6: Сложность пароля
    Validates: Requirements 2.1, 2.3
    """

    @given(password=short_passwords())
    @settings(max_examples=100, deadline=5000)
    def test_property_minimum_length_rejection(self, password):
        """
        Property 5: Минимальная длина пароля

        Для любого пароля длиной менее 12 символов, попытка валидации
        должна вызвать ValidationError.

        Validates: Requirement 2.1
        """
        validator = ComplexityPasswordValidator()

        with pytest.raises(ValidationError) as exc_info:
            validator.validate(password)

        # Проверяем что ошибка связана с длиной
        error_messages = [str(e) for e in exc_info.value.messages]
        assert any(
            "12 символов" in msg for msg in error_messages
        ), f"Expected length error for password of length {len(password)}"

    @given(password=passwords_without_uppercase())
    @settings(max_examples=100, deadline=5000)
    def test_property_uppercase_requirement(self, password):
        """
        Property 6: Сложность пароля (заглавные буквы)

        Для любого пароля без заглавных букв, попытка валидации
        должна вызвать ValidationError с соответствующим сообщением.

        Validates: Requirement 2.3
        """
        validator = ComplexityPasswordValidator()

        with pytest.raises(ValidationError) as exc_info:
            validator.validate(password)

        # Проверяем что ошибка связана с заглавными буквами
        error_messages = [str(e) for e in exc_info.value.messages]
        assert any(
            "заглавную букву" in msg for msg in error_messages
        ), "Expected uppercase letter error"

    @given(password=passwords_without_lowercase())
    @settings(max_examples=100, deadline=5000)
    def test_property_lowercase_requirement(self, password):
        """
        Property 6: Сложность пароля (строчные буквы)

        Для любого пароля без строчных букв, попытка валидации
        должна вызвать ValidationError с соответствующим сообщением.

        Validates: Requirement 2.3
        """
        validator = ComplexityPasswordValidator()

        with pytest.raises(ValidationError) as exc_info:
            validator.validate(password)

        # Проверяем что ошибка связана со строчными буквами
        error_messages = [str(e) for e in exc_info.value.messages]
        assert any(
            "строчную букву" in msg for msg in error_messages
        ), "Expected lowercase letter error"

    @given(password=passwords_without_digits())
    @settings(max_examples=100, deadline=5000)
    def test_property_digit_requirement(self, password):
        """
        Property 6: Сложность пароля (цифры)

        Для любого пароля без цифр, попытка валидации
        должна вызвать ValidationError с соответствующим сообщением.

        Validates: Requirement 2.3
        """
        validator = ComplexityPasswordValidator()

        with pytest.raises(ValidationError) as exc_info:
            validator.validate(password)

        # Проверяем что ошибка связана с цифрами
        error_messages = [str(e) for e in exc_info.value.messages]
        assert any("цифру" in msg for msg in error_messages), "Expected digit error"

    @given(password=passwords_without_special_chars())
    @settings(max_examples=100, deadline=5000)
    def test_property_special_char_requirement(self, password):
        """
        Property 6: Сложность пароля (специальные символы)

        Для любого пароля без специальных символов, попытка валидации
        должна вызвать ValidationError с соответствующим сообщением.

        Validates: Requirement 2.3
        """
        validator = ComplexityPasswordValidator()

        with pytest.raises(ValidationError) as exc_info:
            validator.validate(password)

        # Проверяем что ошибка связана со специальными символами
        error_messages = [str(e) for e in exc_info.value.messages]
        assert any(
            "специальный символ" in msg for msg in error_messages
        ), "Expected special character error"

    @given(password=valid_complex_passwords())
    @settings(max_examples=100, deadline=5000)
    def test_property_valid_password_acceptance(self, password):
        """
        Property 6: Сложность пароля (валидные пароли)

        Для любого пароля соответствующего всем требованиям сложности,
        валидация должна пройти без ошибок.

        Validates: Requirements 2.1, 2.3
        """
        validator = ComplexityPasswordValidator()

        # Не должно быть исключений
        try:
            validator.validate(password)
        except ValidationError as e:
            pytest.fail(f"Valid password rejected: {password}, errors: {e.messages}")


class TestWeakPasswordValidator:
    """
    Тесты для WeakPasswordValidator.

    Feature: security-optimization-audit
    Validates: Requirement 2.4
    """

    @given(weak_password=st.sampled_from(list(WeakPasswordValidator.WEAK_PASSWORDS)))
    @settings(max_examples=100, deadline=5000)
    def test_property_weak_password_rejection(self, weak_password):
        """
        Property: Отклонение слабых паролей

        Для любого пароля из списка слабых паролей, попытка валидации
        должна вызвать ValidationError.

        Validates: Requirement 2.4
        """
        validator = WeakPasswordValidator()

        with pytest.raises(ValidationError) as exc_info:
            validator.validate(weak_password)

        # Проверяем что ошибка связана со слабым паролем
        assert exc_info.value.code == "weak_password"

    @given(weak_password=st.sampled_from(list(WeakPasswordValidator.WEAK_PASSWORDS)))
    @settings(max_examples=100, deadline=5000)
    def test_property_weak_password_case_insensitive(self, weak_password):
        """
        Property: Отклонение слабых паролей (case-insensitive)

        Для любого пароля из списка слабых паролей в любом регистре,
        попытка валидации должна вызвать ValidationError.

        Validates: Requirement 2.4
        """
        validator = WeakPasswordValidator()

        # Тестируем разные варианты регистра
        variations = [
            weak_password.upper(),
            weak_password.lower(),
            weak_password.capitalize(),
        ]

        for variation in variations:
            with pytest.raises(ValidationError) as exc_info:
                validator.validate(variation)

            assert exc_info.value.code == "weak_password"
