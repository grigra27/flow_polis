"""
Custom logging filters for security.
Validates: Requirements 3.5, 6.1
"""
import logging
import re
from .security_utils import SQLLogFilter


class SensitiveDataFilter(logging.Filter):
    """
    Filters sensitive data from log records.
    Validates: Requirements 3.5, 6.1
    """

    # Patterns for sensitive data in logs
    SENSITIVE_PATTERNS = [
        # Passwords - match quoted values first, then unquoted
        (r"'password':\s*'([^']*)'", "'password': '***'"),
        (r'"password":\s*"([^"]*)"', '"password": "***"'),
        (r"password\s*[:=]\s*'([^']*)'", "password='***'"),
        (r'password\s*[:=]\s*"([^"]*)"', 'password="***"'),
        (r"password\s*[:=]\s*(\S+)", "password=***"),
        # Tokens
        (r"'token':\s*'([^']*)'", "'token': '***'"),
        (r'"token":\s*"([^"]*)"', '"token": "***"'),
        (r"token\s*[:=]\s*'([^']*)'", "token='***'"),
        (r'token\s*[:=]\s*"([^"]*)"', 'token="***"'),
        (r"token\s*[:=]\s*(\S+)", "token=***"),
        # API keys
        (r"'api_key':\s*'([^']*)'", "'api_key': '***'"),
        (r'"api_key":\s*"([^"]*)"', '"api_key": "***"'),
        (r"api[_-]?key\s*[:=]\s*'([^']*)'", "api_key='***'"),
        (r'api[_-]?key\s*[:=]\s*"([^"]*)"', 'api_key="***"'),
        (r"api[_-]?key\s*[:=]\s*(\S+)", "api_key=***"),
        # Secrets
        (r"'secret':\s*'([^']*)'", "'secret': '***'"),
        (r'"secret":\s*"([^"]*)"', '"secret": "***"'),
        (r"secret\s*[:=]\s*'([^']*)'", "secret='***'"),
        (r'secret\s*[:=]\s*"([^"]*)"', 'secret="***"'),
        (r"secret\s*[:=]\s*(\S+)", "secret=***"),
        # Session keys
        (r"session[_-]?key\s*[:=]\s*'([^']*)'", "session_key='***'"),
        (r'session[_-]?key\s*[:=]\s*"([^"]*)"', 'session_key="***"'),
        (r"session[_-]?key\s*[:=]\s*(\S+)", "session_key=***"),
        # Credit card numbers (basic pattern)
        (r"\b\d{4}[\s-]?\d{4}[\s-]?\d{4}[\s-]?\d{4}\b", "****-****-****-****"),
        # Email addresses (partial masking)
        (r"\b([a-zA-Z0-9._%+-]+)@([a-zA-Z0-9.-]+\.[a-zA-Z]{2,})\b", r"\1***@\2"),
    ]

    def filter(self, record):
        """
        Filter sensitive data from log record.

        Args:
            record: LogRecord instance

        Returns:
            True to allow the record to be logged
        """
        # Filter the message
        if hasattr(record, "msg") and isinstance(record.msg, str):
            record.msg = self._filter_sensitive_data(record.msg)

        # Filter SQL queries if present
        if hasattr(record, "sql"):
            record.sql = SQLLogFilter.filter_sql(record.sql)

        # Filter args if present
        if hasattr(record, "args") and record.args:
            if isinstance(record.args, dict):
                record.args = self._filter_dict(record.args)
            elif isinstance(record.args, (list, tuple)):
                record.args = tuple(
                    self._filter_sensitive_data(str(arg))
                    if isinstance(arg, str)
                    else arg
                    for arg in record.args
                )

        return True

    def _filter_sensitive_data(self, text: str) -> str:
        """
        Filters sensitive data from text.

        Args:
            text: Text to filter

        Returns:
            Filtered text
        """
        filtered = text

        for pattern, replacement in self.SENSITIVE_PATTERNS:
            filtered = re.sub(pattern, replacement, filtered, flags=re.IGNORECASE)

        return filtered

    def _filter_dict(self, data: dict) -> dict:
        """
        Filters sensitive data from dictionary.

        Args:
            data: Dictionary to filter

        Returns:
            Filtered dictionary
        """
        filtered = {}

        for key, value in data.items():
            if isinstance(value, str):
                filtered[key] = self._filter_sensitive_data(value)
            elif isinstance(value, dict):
                filtered[key] = self._filter_dict(value)
            else:
                filtered[key] = value

        return filtered


class SQLQueryFilter(logging.Filter):
    """
    Filters SQL queries to remove sensitive parameter values.
    Validates: Requirement 3.5
    """

    def filter(self, record):
        """
        Filter SQL queries from log record.

        Args:
            record: LogRecord instance

        Returns:
            True to allow the record to be logged
        """
        # Filter SQL queries
        if hasattr(record, "sql"):
            record.sql = SQLLogFilter.filter_sql(record.sql)

        # Filter the message if it contains SQL
        if hasattr(record, "msg") and isinstance(record.msg, str):
            if (
                "SELECT" in record.msg.upper()
                or "INSERT" in record.msg.upper()
                or "UPDATE" in record.msg.upper()
            ):
                record.msg = SQLLogFilter.filter_sql(record.msg)

        return True
