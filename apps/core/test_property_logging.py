"""
Property-based tests for logging filters.
Feature: security-optimization-audit, Property 17: Фильтрация конфиденциальных данных в логах
Validates: Requirement 6.1
"""
import logging
import re
from hypothesis import given, strategies as st, settings
from hypothesis.extra.django import TestCase
from apps.core.logging_filters import SensitiveDataFilter


class TestSensitiveDataFilterProperties(TestCase):
    """
    Property-based tests for SensitiveDataFilter.
    """

    def setUp(self):
        """Set up test fixtures."""
        self.filter = SensitiveDataFilter()
        self.logger = logging.getLogger("test_logger")

        # Create a handler with our filter
        self.handler = logging.StreamHandler()
        self.handler.addFilter(self.filter)
        self.logger.addHandler(self.handler)
        self.logger.setLevel(logging.DEBUG)

    def tearDown(self):
        """Clean up after tests."""
        self.logger.removeHandler(self.handler)

    @given(
        password=st.text(
            min_size=8,
            max_size=50,
            alphabet=st.characters(
                blacklist_categories=("Cs", "Cc"), blacklist_characters="\x00\n\r'\""
            ),
        )
    )
    @settings(max_examples=100, deadline=5000)
    def test_property_passwords_filtered_from_logs(self, password):
        """
        Feature: security-optimization-audit, Property 17: Фильтрация конфиденциальных данных в логах
        Validates: Requirement 6.1

        Property: For any password value in a log message, the password should be masked
        in the filtered output.
        """
        # Create log messages with passwords in various formats
        test_cases = [
            f"User login with password={password}",
            f"Authentication failed: password: {password}",
            f"Config: {{'password': '{password}'}}",
            f'Data: {{"password": "{password}"}}',
            f"password='{password}'",
            f'password="{password}"',
        ]

        for message in test_cases:
            # Create a log record
            record = logging.LogRecord(
                name="test",
                level=logging.INFO,
                pathname="",
                lineno=0,
                msg=message,
                args=(),
                exc_info=None,
            )

            # Apply the filter
            self.filter.filter(record)

            # The filtered message should not contain the original password
            self.assertNotIn(
                password,
                record.msg,
                f"Password '{password}' was not filtered from message: {record.msg}",
            )

            # The filtered message should contain the mask
            self.assertIn(
                "***",
                record.msg,
                f"Mask '***' not found in filtered message: {record.msg}",
            )

    @given(
        token=st.text(
            min_size=16,
            max_size=64,
            alphabet=st.characters(
                whitelist_categories=("Lu", "Ll", "Nd"), blacklist_characters="\x00\n\r"
            ),
        )
    )
    @settings(max_examples=100, deadline=5000)
    def test_property_tokens_filtered_from_logs(self, token):
        """
        Feature: security-optimization-audit, Property 17: Фильтрация конфиденциальных данных в логах
        Validates: Requirement 6.1

        Property: For any token value in a log message, the token should be masked
        in the filtered output.
        """
        # Create log messages with tokens in various formats
        test_cases = [
            f"API request with token={token}",
            f"Authorization: token: {token}",
            f"Config: {{'token': '{token}'}}",
            f'Data: {{"token": "{token}"}}',
        ]

        for message in test_cases:
            # Create a log record
            record = logging.LogRecord(
                name="test",
                level=logging.INFO,
                pathname="",
                lineno=0,
                msg=message,
                args=(),
                exc_info=None,
            )

            # Apply the filter
            self.filter.filter(record)

            # The filtered message should not contain the original token
            self.assertNotIn(
                token,
                record.msg,
                f"Token '{token}' was not filtered from message: {record.msg}",
            )

            # The filtered message should contain the mask
            self.assertIn(
                "***",
                record.msg,
                f"Mask '***' not found in filtered message: {record.msg}",
            )

    @given(
        api_key=st.text(
            min_size=20,
            max_size=50,
            alphabet=st.characters(
                whitelist_categories=("Lu", "Ll", "Nd"), blacklist_characters="\x00\n\r"
            ),
        )
    )
    @settings(max_examples=100, deadline=5000)
    def test_property_api_keys_filtered_from_logs(self, api_key):
        """
        Feature: security-optimization-audit, Property 17: Фильтрация конфиденциальных данных в логах
        Validates: Requirement 6.1

        Property: For any API key value in a log message, the API key should be masked
        in the filtered output.
        """
        # Create log messages with API keys in various formats
        test_cases = [
            f"Service config: api_key={api_key}",
            f"API authentication: api-key: {api_key}",
            f"Config: {{'api_key': '{api_key}'}}",
            f'Data: {{"api_key": "{api_key}"}}',
        ]

        for message in test_cases:
            # Create a log record
            record = logging.LogRecord(
                name="test",
                level=logging.INFO,
                pathname="",
                lineno=0,
                msg=message,
                args=(),
                exc_info=None,
            )

            # Apply the filter
            self.filter.filter(record)

            # The filtered message should not contain the original API key
            self.assertNotIn(
                api_key,
                record.msg,
                f"API key '{api_key}' was not filtered from message: {record.msg}",
            )

            # The filtered message should contain the mask
            self.assertIn(
                "***",
                record.msg,
                f"Mask '***' not found in filtered message: {record.msg}",
            )

    @given(
        secret=st.text(
            min_size=16,
            max_size=64,
            alphabet=st.characters(
                whitelist_categories=("Lu", "Ll", "Nd"), blacklist_characters="\x00\n\r"
            ),
        )
    )
    @settings(max_examples=100, deadline=5000)
    def test_property_secrets_filtered_from_logs(self, secret):
        """
        Feature: security-optimization-audit, Property 17: Фильтрация конфиденциальных данных в логах
        Validates: Requirement 6.1

        Property: For any secret value in a log message, the secret should be masked
        in the filtered output.
        """
        # Create log messages with secrets in various formats
        test_cases = [
            f"Application secret={secret}",
            f"Configuration: secret: {secret}",
            f"Config: {{'secret': '{secret}'}}",
            f'Data: {{"secret": "{secret}"}}',
        ]

        for message in test_cases:
            # Create a log record
            record = logging.LogRecord(
                name="test",
                level=logging.INFO,
                pathname="",
                lineno=0,
                msg=message,
                args=(),
                exc_info=None,
            )

            # Apply the filter
            self.filter.filter(record)

            # The filtered message should not contain the original secret
            self.assertNotIn(
                secret,
                record.msg,
                f"Secret '{secret}' was not filtered from message: {record.msg}",
            )

            # The filtered message should contain the mask
            self.assertIn(
                "***",
                record.msg,
                f"Mask '***' not found in filtered message: {record.msg}",
            )
