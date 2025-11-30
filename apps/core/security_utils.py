"""
Security utilities for input validation and sanitization.
Validates: Requirements 3.3, 3.4, 12.1, 12.3, 12.5
"""
import re
import logging
from typing import Any, Optional, Dict
from django.utils.html import escape

# Get security logger
security_logger = logging.getLogger("security")


class InputSanitizer:
    """
    Sanitizes user input to prevent SQL injection and other attacks.
    """

    # SQL special characters that need escaping
    SQL_SPECIAL_CHARS = ["'", '"', "--", ";", "/*", "*/", "xp_", "sp_", "\\"]

    # Patterns that indicate potential SQL injection attempts
    SQL_INJECTION_PATTERNS = [
        r"(\bOR\b|\bAND\b)\s+['\"]?\d+['\"]?\s*=\s*['\"]?\d+['\"]?",  # OR 1=1, AND 1=1, OR '1'='1'
        r"['\"]?\s*\bOR\b\s+['\"]?[a-zA-Z0-9]+['\"]?\s*=\s*['\"]?[a-zA-Z0-9]+['\"]?",  # OR 'x'='x', OR 'a'='a'
        r"\bUNION\b.*\bSELECT\b",  # UNION SELECT
        r"\bDROP\b.*\bTABLE\b",  # DROP TABLE
        r"\bINSERT\b.*\bINTO\b",  # INSERT INTO
        r"\bDELETE\b.*\bFROM\b",  # DELETE FROM
        r"\bUPDATE\b.*\bSET\b",  # UPDATE SET
        r"--",  # SQL comment
        r"/\*.*\*/",  # SQL comment block
        r"\bEXEC\b|\bEXECUTE\b",  # EXEC/EXECUTE
        r"\bxp_\w+",  # Extended stored procedures
        r"\bsp_\w+",  # System stored procedures
        r"['\"];?\s*(DROP|DELETE|INSERT|UPDATE|EXEC)",  # Quotes followed by dangerous commands
    ]

    @classmethod
    def sanitize_string(cls, value: str) -> str:
        """
        Sanitizes a string by escaping SQL special characters.

        Args:
            value: The string to sanitize

        Returns:
            Sanitized string with special characters escaped
        """
        if not isinstance(value, str):
            return value

        # Escape HTML first to prevent XSS
        sanitized = escape(value)

        # Remove null bytes
        sanitized = sanitized.replace("\x00", "")

        return sanitized

    @classmethod
    def contains_sql_injection(cls, value: str) -> bool:
        """
        Checks if a string contains potential SQL injection patterns.

        Args:
            value: The string to check

        Returns:
            True if potential SQL injection detected, False otherwise
        """
        if not isinstance(value, str):
            return False

        # Check for SQL special characters in suspicious contexts
        value_upper = value.upper()

        for pattern in cls.SQL_INJECTION_PATTERNS:
            if re.search(pattern, value_upper, re.IGNORECASE):
                return True

        return False

    @classmethod
    def validate_and_sanitize(cls, value: Any) -> tuple[bool, Optional[str]]:
        """
        Validates and sanitizes user input.

        Args:
            value: The value to validate and sanitize

        Returns:
            Tuple of (is_valid, sanitized_value)
            - is_valid: False if SQL injection detected, True otherwise
            - sanitized_value: Sanitized value if valid, None if invalid
        """
        if value is None:
            return True, None

        if not isinstance(value, str):
            return True, value

        # Check for SQL injection
        if cls.contains_sql_injection(value):
            return False, None

        # Sanitize the value
        sanitized = cls.sanitize_string(value)

        return True, sanitized

    @classmethod
    def sanitize_dict(cls, data: dict) -> dict:
        """
        Sanitizes all string values in a dictionary.

        Args:
            data: Dictionary with potentially unsafe values

        Returns:
            Dictionary with sanitized values
        """
        sanitized = {}
        for key, value in data.items():
            if isinstance(value, str):
                is_valid, sanitized_value = cls.validate_and_sanitize(value)
                if is_valid:
                    sanitized[key] = sanitized_value
                else:
                    # Skip invalid values
                    continue
            elif isinstance(value, dict):
                sanitized[key] = cls.sanitize_dict(value)
            elif isinstance(value, list):
                sanitized[key] = [
                    cls.sanitize_string(item) if isinstance(item, str) else item
                    for item in value
                ]
            else:
                sanitized[key] = value

        return sanitized


class SQLLogFilter:
    """
    Filters sensitive data from SQL logs.
    Validates: Requirement 3.5
    """

    # Patterns for sensitive data
    SENSITIVE_PATTERNS = [
        (r"password\s*=\s*'[^']*'", "password='***'"),
        (r'password\s*=\s*"[^"]*"', 'password="***"'),
        (r"token\s*=\s*'[^']*'", "token='***'"),
        (r'token\s*=\s*"[^"]*"', 'token="***"'),
        (r"api_key\s*=\s*'[^']*'", "api_key='***'"),
        (r'api_key\s*=\s*"[^"]*"', 'api_key="***"'),
        (r"secret\s*=\s*'[^']*'", "secret='***'"),
        (r'secret\s*=\s*"[^"]*"', 'secret="***"'),
        (r"passport_data\s*=\s*'[^']*'", "passport_data='***'"),
        (r'passport_data\s*=\s*"[^"]*"', 'passport_data="***"'),
        (r"inn\s*=\s*'[^']*'", "inn='***'"),
        (r'inn\s*=\s*"[^"]*"', 'inn="***"'),
    ]

    @classmethod
    def filter_sql(cls, sql: str) -> str:
        """
        Filters sensitive data from SQL query strings.

        Args:
            sql: SQL query string

        Returns:
            SQL query with sensitive data masked
        """
        filtered = sql

        for pattern, replacement in cls.SENSITIVE_PATTERNS:
            filtered = re.sub(pattern, replacement, filtered, flags=re.IGNORECASE)

        return filtered


class SecurityEventLogger:
    """
    Centralized security event logging.
    Validates: Requirements 12.1, 12.3, 12.5
    """

    @staticmethod
    def log_failed_login(username: str, ip_address: str, user_agent: str = ""):
        """
        Log failed login attempt.

        Args:
            username: Username that failed to login
            ip_address: IP address of the attempt
            user_agent: User agent string
        """
        security_logger.warning(
            f"Failed login attempt - Username: {username}, IP: {ip_address}, User-Agent: {user_agent}"
        )

    @staticmethod
    def log_successful_login(username: str, ip_address: str):
        """
        Log successful login.

        Args:
            username: Username that logged in
            ip_address: IP address of the login
        """
        security_logger.info(
            f"Successful login - Username: {username}, IP: {ip_address}"
        )

    @staticmethod
    def log_access_denied(user: str, url: str, ip_address: str):
        """
        Log access denied event.

        Args:
            user: Username attempting access
            url: URL that was denied
            ip_address: IP address of the attempt
        """
        security_logger.warning(
            f"Access denied - User: {user}, URL: {url}, IP: {ip_address}"
        )

    @staticmethod
    def log_privilege_escalation_attempt(user: str, action: str, ip_address: str = ""):
        """
        Log privilege escalation attempt.

        Args:
            user: Username attempting escalation
            action: Action that was attempted
            ip_address: IP address of the attempt
        """
        security_logger.critical(
            f"Privilege escalation attempt - User: {user}, Action: {action}, IP: {ip_address}"
        )

    @staticmethod
    def log_suspicious_activity(event_type: str, details: Dict[str, Any]):
        """
        Log suspicious activity.

        Args:
            event_type: Type of suspicious activity
            details: Dictionary with event details
        """
        details_str = ", ".join([f"{k}: {v}" for k, v in details.items()])
        security_logger.warning(
            f"Suspicious activity - Type: {event_type}, Details: {details_str}"
        )

    @staticmethod
    def log_sql_injection_attempt(ip_address: str, input_value: str, field: str = ""):
        """
        Log SQL injection attempt.

        Args:
            ip_address: IP address of the attempt
            input_value: The suspicious input value
            field: Field name where injection was attempted
        """
        security_logger.critical(
            f"SQL injection attempt detected - IP: {ip_address}, Field: {field}, Input: {input_value[:100]}"
        )

    @staticmethod
    def log_brute_force_detected(ip_address: str, username: str, attempt_count: int):
        """
        Log brute force attack detection.

        Args:
            ip_address: IP address of the attack
            username: Username being targeted
            attempt_count: Number of failed attempts
        """
        security_logger.critical(
            f"Brute force attack detected - IP: {ip_address}, Username: {username}, Attempts: {attempt_count}"
        )

    @staticmethod
    def log_account_locked(username: str, ip_address: str, reason: str = ""):
        """
        Log account lockout.

        Args:
            username: Username that was locked
            ip_address: IP address that triggered the lock
            reason: Reason for lockout
        """
        security_logger.warning(
            f"Account locked - Username: {username}, IP: {ip_address}, Reason: {reason}"
        )
