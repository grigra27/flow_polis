"""
Unit tests for security headers configuration.

**Feature: security-optimization-audit**
**Validates: Requirements 9.1, 9.2, 9.3, 9.4, 9.5**
"""
import os
import sys
import unittest
from unittest.mock import patch
from pathlib import Path


class SecurityHeadersProductionTest(unittest.TestCase):
    """
    Test that security headers are properly configured in production mode.
    Validates: Requirements 9.1, 9.2, 9.3, 9.4, 9.5
    """

    def _reload_settings(self):
        """Force reload of settings module."""
        modules_to_remove = [
            key for key in sys.modules.keys() if key.startswith("config")
        ]
        for module in modules_to_remove:
            del sys.modules[module]

    def test_x_content_type_options_nosniff(self):
        """
        Test that X-Content-Type-Options is set to nosniff in production.
        Validates: Requirement 9.1
        """
        prod_config = {
            "DEBUG": "False",
            "SECRET_KEY": "production-secret-key-12345",
            "DB_NAME": "prod_db",
            "DB_USER": "prod_user",
            "DB_PASSWORD": "prod_password",
            "ALLOWED_HOSTS": "onbr.site",
        }

        with patch.dict(os.environ, prod_config, clear=True):
            self._reload_settings()
            from config import settings

            # Validates: Requirement 9.1 - X-Content-Type-Options: nosniff
            self.assertTrue(settings.SECURE_CONTENT_TYPE_NOSNIFF)

    def test_x_frame_options_deny(self):
        """
        Test that X-Frame-Options is set to DENY in production.
        Validates: Requirement 9.2
        """
        prod_config = {
            "DEBUG": "False",
            "SECRET_KEY": "production-secret-key-12345",
            "DB_NAME": "prod_db",
            "DB_USER": "prod_user",
            "DB_PASSWORD": "prod_password",
            "ALLOWED_HOSTS": "onbr.site",
        }

        with patch.dict(os.environ, prod_config, clear=True):
            self._reload_settings()
            from config import settings

            # Validates: Requirement 9.2 - X-Frame-Options: DENY
            self.assertEqual(settings.X_FRAME_OPTIONS, "DENY")

    def test_hsts_enabled_with_minimum_age(self):
        """
        Test that HSTS is enabled with max-age >= 31536000 seconds.
        Validates: Requirement 9.3
        """
        prod_config = {
            "DEBUG": "False",
            "SECRET_KEY": "production-secret-key-12345",
            "DB_NAME": "prod_db",
            "DB_USER": "prod_user",
            "DB_PASSWORD": "prod_password",
            "ALLOWED_HOSTS": "onbr.site",
        }

        with patch.dict(os.environ, prod_config, clear=True):
            self._reload_settings()
            from config import settings

            # Validates: Requirement 9.3 - HSTS with max-age >= 31536000
            self.assertGreaterEqual(settings.SECURE_HSTS_SECONDS, 31536000)
            self.assertTrue(settings.SECURE_HSTS_INCLUDE_SUBDOMAINS)
            self.assertTrue(settings.SECURE_HSTS_PRELOAD)

    def test_csp_configured(self):
        """
        Test that Content-Security-Policy is configured in production.
        Validates: Requirement 9.4
        """
        prod_config = {
            "DEBUG": "False",
            "SECRET_KEY": "production-secret-key-12345",
            "DB_NAME": "prod_db",
            "DB_USER": "prod_user",
            "DB_PASSWORD": "prod_password",
            "ALLOWED_HOSTS": "onbr.site",
        }

        with patch.dict(os.environ, prod_config, clear=True):
            self._reload_settings()
            from config import settings

            # Validates: Requirement 9.4 - Content-Security-Policy configured
            self.assertTrue(hasattr(settings, "CSP_DEFAULT_SRC"))
            self.assertIn("'self'", settings.CSP_DEFAULT_SRC)
            self.assertTrue(hasattr(settings, "CSP_FRAME_ANCESTORS"))
            self.assertIn("'none'", settings.CSP_FRAME_ANCESTORS)

    def test_referrer_policy_configured(self):
        """
        Test that Referrer-Policy is set to strict-origin-when-cross-origin.
        Validates: Requirement 9.5
        """
        prod_config = {
            "DEBUG": "False",
            "SECRET_KEY": "production-secret-key-12345",
            "DB_NAME": "prod_db",
            "DB_USER": "prod_user",
            "DB_PASSWORD": "prod_password",
            "ALLOWED_HOSTS": "onbr.site",
        }

        with patch.dict(os.environ, prod_config, clear=True):
            self._reload_settings()
            from config import settings

            # Validates: Requirement 9.5 - Referrer-Policy: strict-origin-when-cross-origin
            self.assertEqual(
                settings.SECURE_REFERRER_POLICY, "strict-origin-when-cross-origin"
            )

    def test_all_security_headers_present_in_production(self):
        """
        Test that all required security headers are configured in production.
        Validates: Requirements 9.1, 9.2, 9.3, 9.4, 9.5
        """
        prod_config = {
            "DEBUG": "False",
            "SECRET_KEY": "production-secret-key-12345",
            "DB_NAME": "prod_db",
            "DB_USER": "prod_user",
            "DB_PASSWORD": "prod_password",
            "ALLOWED_HOSTS": "onbr.site",
        }

        with patch.dict(os.environ, prod_config, clear=True):
            self._reload_settings()
            from config import settings

            # Check all security headers are configured
            security_settings = {
                "SECURE_CONTENT_TYPE_NOSNIFF": True,
                "X_FRAME_OPTIONS": "DENY",
                "SECURE_HSTS_SECONDS": 31536000,
                "SECURE_REFERRER_POLICY": "strict-origin-when-cross-origin",
            }

            for setting_name, expected_value in security_settings.items():
                actual_value = getattr(settings, setting_name)
                if isinstance(expected_value, int):
                    self.assertGreaterEqual(
                        actual_value,
                        expected_value,
                        f"{setting_name} should be >= {expected_value}, got {actual_value}",
                    )
                else:
                    self.assertEqual(
                        actual_value,
                        expected_value,
                        f"{setting_name} should be {expected_value}, got {actual_value}",
                    )

    def test_security_headers_not_set_in_development(self):
        """
        Test that some security headers are not enforced in development mode.
        This allows for easier development without HTTPS requirements.
        """
        dev_config = {"DEBUG": "True", "SECRET_KEY": "dev-secret-key"}

        with patch.dict(os.environ, dev_config, clear=True):
            self._reload_settings()
            from config import settings

            # In development, these should not be set or should be False
            self.assertFalse(
                hasattr(settings, "SESSION_COOKIE_SECURE")
                and settings.SESSION_COOKIE_SECURE
            )
            self.assertFalse(
                hasattr(settings, "CSRF_COOKIE_SECURE") and settings.CSRF_COOKIE_SECURE
            )


class SessionSecurityTest(unittest.TestCase):
    """
    Test session security configuration.
    Validates: Requirements 1.3, 5.4
    """

    def _reload_settings(self):
        """Force reload of settings module."""
        modules_to_remove = [
            key for key in sys.modules.keys() if key.startswith("config")
        ]
        for module in modules_to_remove:
            del sys.modules[module]

    def test_session_cookie_secure_in_production(self):
        """
        Test that session cookies are marked as secure in production.
        Validates: Requirement 1.3
        """
        prod_config = {
            "DEBUG": "False",
            "SECRET_KEY": "production-secret-key-12345",
            "DB_NAME": "prod_db",
            "DB_USER": "prod_user",
            "DB_PASSWORD": "prod_password",
            "ALLOWED_HOSTS": "onbr.site",
        }

        with patch.dict(os.environ, prod_config, clear=True):
            self._reload_settings()
            from config import settings

            self.assertTrue(settings.SESSION_COOKIE_SECURE)
            self.assertTrue(settings.SESSION_COOKIE_HTTPONLY)
            self.assertEqual(settings.SESSION_COOKIE_SAMESITE, "Strict")

    def test_session_timeout_configured(self):
        """
        Test that session timeout is set to maximum 24 hours.
        Validates: Requirement 1.3
        """
        prod_config = {
            "DEBUG": "False",
            "SECRET_KEY": "production-secret-key-12345",
            "DB_NAME": "prod_db",
            "DB_USER": "prod_user",
            "DB_PASSWORD": "prod_password",
            "ALLOWED_HOSTS": "onbr.site",
        }

        with patch.dict(os.environ, prod_config, clear=True):
            self._reload_settings()
            from config import settings

            # 24 hours = 86400 seconds
            self.assertLessEqual(settings.SESSION_COOKIE_AGE, 86400)

    def test_csrf_cookie_secure_in_production(self):
        """
        Test that CSRF cookies are marked as secure in production.
        Validates: Requirement 5.4
        """
        prod_config = {
            "DEBUG": "False",
            "SECRET_KEY": "production-secret-key-12345",
            "DB_NAME": "prod_db",
            "DB_USER": "prod_user",
            "DB_PASSWORD": "prod_password",
            "ALLOWED_HOSTS": "onbr.site",
        }

        with patch.dict(os.environ, prod_config, clear=True):
            self._reload_settings()
            from config import settings

            # Validates: Requirement 5.4 - CSRF SameSite=Strict
            self.assertTrue(settings.CSRF_COOKIE_SECURE)
            self.assertTrue(settings.CSRF_COOKIE_HTTPONLY)
            self.assertEqual(settings.CSRF_COOKIE_SAMESITE, "Strict")


class NginxSecurityHeadersTest(unittest.TestCase):
    """
    Test that Nginx configuration includes all required security headers.
    Validates: Requirements 9.1, 9.2, 9.3, 9.4, 9.5
    """

    def setUp(self):
        """Load nginx configuration file."""
        nginx_config_path = (
            Path(__file__).resolve().parent.parent.parent / "nginx" / "default.conf"
        )
        with open(nginx_config_path, "r") as f:
            self.nginx_config = f.read()

    def test_nginx_has_x_content_type_options(self):
        """
        Test that Nginx config includes X-Content-Type-Options: nosniff.
        Validates: Requirement 9.1
        """
        self.assertIn("X-Content-Type-Options", self.nginx_config)
        self.assertIn("nosniff", self.nginx_config)

    def test_nginx_has_x_frame_options(self):
        """
        Test that Nginx config includes X-Frame-Options: DENY.
        Validates: Requirement 9.2
        """
        self.assertIn("X-Frame-Options", self.nginx_config)
        self.assertIn("DENY", self.nginx_config)

    def test_nginx_has_hsts(self):
        """
        Test that Nginx config includes HSTS with proper max-age.
        Validates: Requirement 9.3
        """
        self.assertIn("Strict-Transport-Security", self.nginx_config)
        self.assertIn("max-age=31536000", self.nginx_config)
        self.assertIn("includeSubDomains", self.nginx_config)

    def test_nginx_has_csp(self):
        """
        Test that Nginx config includes Content-Security-Policy.
        Validates: Requirement 9.4
        """
        self.assertIn("Content-Security-Policy", self.nginx_config)
        self.assertIn("default-src 'self'", self.nginx_config)
        self.assertIn("frame-ancestors 'none'", self.nginx_config)

    def test_nginx_has_referrer_policy(self):
        """
        Test that Nginx config includes Referrer-Policy.
        Validates: Requirement 9.5
        """
        self.assertIn("Referrer-Policy", self.nginx_config)
        self.assertIn("strict-origin-when-cross-origin", self.nginx_config)

    def test_nginx_has_permissions_policy(self):
        """
        Test that Nginx config includes Permissions-Policy.
        """
        self.assertIn("Permissions-Policy", self.nginx_config)


if __name__ == "__main__":
    unittest.main()
