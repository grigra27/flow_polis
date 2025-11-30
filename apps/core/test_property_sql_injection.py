"""
Property-based tests for SQL injection prevention.
Feature: security-optimization-audit, Property 8: Санитизация пользовательского ввода
Validates: Requirements 3.3, 3.4
"""
import pytest
from hypothesis import given, strategies as st, settings, assume
from apps.core.security_utils import InputSanitizer


# Strategy for generating strings with SQL injection patterns
@st.composite
def sql_injection_strings(draw):
    """Generate strings that contain SQL injection patterns."""
    injection_patterns = [
        "' OR '1'='1",
        "' OR 1=1--",
        "'; DROP TABLE users--",
        "' UNION SELECT * FROM users--",
        "admin'--",
        "' OR 'x'='x",
        "1' AND '1'='1",
        "'; DELETE FROM policies WHERE '1'='1",
        "' OR 1=1#",
        "' OR 'a'='a",
        "1' UNION SELECT NULL, NULL--",
        "' EXEC sp_executesql--",
        "'; EXEC xp_cmdshell('dir')--",
        "' INSERT INTO users VALUES('hacker', 'password')--",
        "' UPDATE users SET password='hacked' WHERE '1'='1",
        "/* comment */ OR 1=1",
        "-- comment\nOR 1=1",
    ]

    # Choose a random injection pattern
    pattern = draw(st.sampled_from(injection_patterns))

    # Optionally add some normal text before or after
    prefix = draw(
        st.text(
            alphabet=st.characters(whitelist_categories=("Lu", "Ll", "Nd")), max_size=20
        )
    )
    suffix = draw(
        st.text(
            alphabet=st.characters(whitelist_categories=("Lu", "Ll", "Nd")), max_size=20
        )
    )

    position = draw(st.integers(min_value=0, max_value=2))

    if position == 0:
        return pattern
    elif position == 1:
        return prefix + pattern
    else:
        return pattern + suffix


# Strategy for generating safe strings (no SQL injection)
@st.composite
def safe_strings(draw):
    """Generate strings that don't contain SQL injection patterns."""
    # Generate normal text without SQL keywords
    text = draw(
        st.text(
            alphabet=st.characters(
                whitelist_categories=("Lu", "Ll", "Nd", "Zs"),
                blacklist_characters="';-/*",
            ),
            min_size=0,
            max_size=100,
        )
    )

    # Ensure it doesn't accidentally contain SQL keywords
    sql_keywords = [
        "OR",
        "AND",
        "UNION",
        "SELECT",
        "DROP",
        "INSERT",
        "DELETE",
        "UPDATE",
        "EXEC",
        "EXECUTE",
    ]
    text_upper = text.upper()

    # If it contains SQL keywords, reject it
    for keyword in sql_keywords:
        if keyword in text_upper:
            assume(False)

    return text


class TestInputSanitization:
    """
    Property-based tests for input sanitization.
    Feature: security-optimization-audit, Property 8: Санитизация пользовательского ввода
    """

    @settings(max_examples=100, deadline=5000)
    @given(malicious_input=sql_injection_strings())
    def test_property_8_detects_sql_injection_patterns(self, malicious_input):
        """
        Property 8: Санитизация пользовательского ввода

        For any string containing SQL injection patterns, the sanitizer
        should detect it as potentially malicious.

        Validates: Requirements 3.3, 3.4
        """
        # The sanitizer should detect SQL injection patterns
        contains_injection = InputSanitizer.contains_sql_injection(malicious_input)

        # Assert that the injection was detected
        assert (
            contains_injection
        ), f"Failed to detect SQL injection in: {malicious_input!r}"

    @settings(max_examples=100, deadline=5000)
    @given(safe_input=safe_strings())
    def test_property_8_allows_safe_input(self, safe_input):
        """
        Property 8: Санитизация пользовательского ввода (safe input)

        For any string without SQL injection patterns, the sanitizer
        should allow it through.

        Validates: Requirements 3.3, 3.4
        """
        # The sanitizer should not flag safe input
        contains_injection = InputSanitizer.contains_sql_injection(safe_input)

        # Assert that safe input is not flagged
        assert (
            not contains_injection
        ), f"False positive: Safe input flagged as malicious: {safe_input!r}"

    @settings(max_examples=100, deadline=5000)
    @given(malicious_input=sql_injection_strings())
    def test_property_8_validate_and_sanitize_rejects_injection(self, malicious_input):
        """
        Property 8: Санитизация пользовательского ввода (validation)

        For any string containing SQL injection patterns, validate_and_sanitize
        should return False for is_valid.

        Validates: Requirements 3.3, 3.4
        """
        is_valid, sanitized_value = InputSanitizer.validate_and_sanitize(
            malicious_input
        )

        # Assert that the input is marked as invalid
        assert not is_valid, f"Failed to reject SQL injection: {malicious_input!r}"

        # Assert that sanitized_value is None for invalid input
        assert (
            sanitized_value is None
        ), f"Sanitized value should be None for invalid input, got: {sanitized_value!r}"

    @settings(max_examples=100, deadline=5000)
    @given(safe_input=safe_strings())
    def test_property_8_validate_and_sanitize_accepts_safe_input(self, safe_input):
        """
        Property 8: Санитизация пользовательского ввода (safe validation)

        For any string without SQL injection patterns, validate_and_sanitize
        should return True for is_valid and a sanitized version of the input.

        Validates: Requirements 3.3, 3.4
        """
        is_valid, sanitized_value = InputSanitizer.validate_and_sanitize(safe_input)

        # Assert that the input is marked as valid
        assert is_valid, f"False positive: Safe input rejected: {safe_input!r}"

        # Assert that sanitized_value is not None
        assert (
            sanitized_value is not None
        ), f"Sanitized value should not be None for valid input"

    @settings(max_examples=100, deadline=5000)
    @given(text=st.text(min_size=0, max_size=100))
    def test_property_8_sanitize_string_escapes_html(self, text):
        """
        Property 8: Санитизация пользовательского ввода (HTML escaping)

        For any string, sanitize_string should escape HTML special characters
        to prevent XSS attacks.

        Validates: Requirements 3.3, 3.4
        """
        sanitized = InputSanitizer.sanitize_string(text)

        # Assert that HTML special characters are escaped
        assert (
            "<script>" not in sanitized.lower()
        ), f"Failed to escape <script> tag in: {text!r}"

        # If input contains <, it should be escaped to &lt;
        if "<" in text:
            assert (
                "&lt;" in sanitized or "<" not in sanitized
            ), f"Failed to escape < character in: {text!r}"

        # If input contains >, it should be escaped to &gt;
        if ">" in text:
            assert (
                "&gt;" in sanitized or ">" not in sanitized
            ), f"Failed to escape > character in: {text!r}"

    @settings(max_examples=100, deadline=5000)
    @given(
        data=st.dictionaries(
            keys=st.text(min_size=1, max_size=20),
            values=st.one_of(
                st.text(min_size=0, max_size=50),
                st.integers(),
                st.booleans(),
                st.none(),
            ),
            min_size=1,
            max_size=10,
        )
    )
    def test_property_8_sanitize_dict_preserves_structure(self, data):
        """
        Property 8: Санитизация пользовательского ввода (dict sanitization)

        For any dictionary, sanitize_dict should preserve the structure
        while sanitizing string values.

        Validates: Requirements 3.3, 3.4
        """
        # Filter out any keys/values that might contain SQL injection
        # to ensure we're testing structure preservation, not rejection
        safe_data = {}
        for key, value in data.items():
            if isinstance(value, str):
                if not InputSanitizer.contains_sql_injection(value):
                    safe_data[key] = value
            else:
                safe_data[key] = value

        if not safe_data:
            # Skip if all values were filtered out
            assume(False)

        sanitized = InputSanitizer.sanitize_dict(safe_data)

        # Assert that all non-string values are preserved
        for key, value in safe_data.items():
            if not isinstance(value, str):
                assert key in sanitized, f"Key {key} missing from sanitized dict"
                assert (
                    sanitized[key] == value
                ), f"Non-string value changed: {value} -> {sanitized[key]}"

    def test_property_8_specific_sql_injection_examples(self):
        """
        Test specific SQL injection examples to ensure detection.

        Validates: Requirements 3.3, 3.4
        """
        sql_injections = [
            "' OR '1'='1",
            "'; DROP TABLE users--",
            "' UNION SELECT * FROM passwords--",
            "admin'--",
            "1' OR 1=1--",
            "' EXEC sp_executesql--",
            "/* */ OR 1=1",
        ]

        for injection in sql_injections:
            assert InputSanitizer.contains_sql_injection(
                injection
            ), f"Failed to detect SQL injection: {injection}"

            is_valid, _ = InputSanitizer.validate_and_sanitize(injection)
            assert not is_valid, f"Failed to reject SQL injection: {injection}"

    def test_property_8_safe_input_examples(self):
        """
        Test specific safe input examples to ensure they're not flagged.

        Validates: Requirements 3.3, 3.4
        """
        safe_inputs = [
            "John Doe",
            "test@example.com",
            "123 Main Street",
            "Product Name 2024",
            "Normal text with spaces",
            "",
            "Текст на русском",
        ]

        for safe_input in safe_inputs:
            assert not InputSanitizer.contains_sql_injection(
                safe_input
            ), f"False positive for safe input: {safe_input}"

            is_valid, sanitized = InputSanitizer.validate_and_sanitize(safe_input)
            assert is_valid, f"Safe input rejected: {safe_input}"
            assert (
                sanitized is not None
            ), f"Sanitized value is None for safe input: {safe_input}"
