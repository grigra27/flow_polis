"""
Unit tests for Django settings configuration.

**Feature: docker-deployment, Property 2: Конфигурация через переменные окружения**
**Feature: docker-deployment, Property 3: Разделение окружений development/production**
**Feature: docker-deployment, Property 5: Безопасность ALLOWED_HOSTS**
**Validates: Требования 5.1, 5.2, 5.4, 5.5, 10.1, 10.2, 10.5**
"""
import os
import sys
import unittest
from unittest.mock import patch
from pathlib import Path
import importlib


class SettingsEnvironmentVariablesTest(unittest.TestCase):
    """
    Test that settings are loaded from environment variables.
    **Property 2: Конфигурация через переменные окружения**
    """

    def _reload_settings(self):
        """Force reload of settings module."""
        # Remove all related modules
        modules_to_remove = [
            key for key in sys.modules.keys() if key.startswith("config")
        ]
        for module in modules_to_remove:
            del sys.modules[module]

    def test_secret_key_from_environment(self):
        """Test that SECRET_KEY is loaded from environment variable."""
        test_secret = "test-secret-key-from-env-12345"
        with patch.dict(
            os.environ, {"SECRET_KEY": test_secret, "DEBUG": "True"}, clear=True
        ):
            self._reload_settings()
            from config import settings

            self.assertEqual(settings.SECRET_KEY, test_secret)

    def test_debug_from_environment(self):
        """Test that DEBUG is loaded from environment variable."""
        with patch.dict(
            os.environ,
            {
                "DEBUG": "False",
                "SECRET_KEY": "test-key",
                "DB_NAME": "test",
                "DB_USER": "test",
                "DB_PASSWORD": "test",
                "ALLOWED_HOSTS": "test.com",
            },
            clear=True,
        ):
            self._reload_settings()
            from config import settings

            self.assertFalse(settings.DEBUG)

        with patch.dict(
            os.environ, {"DEBUG": "True", "SECRET_KEY": "test-key"}, clear=True
        ):
            self._reload_settings()
            from config import settings

            self.assertTrue(settings.DEBUG)

    def test_allowed_hosts_from_environment(self):
        """Test that ALLOWED_HOSTS is loaded from environment variable."""
        test_hosts = "example.com,www.example.com,api.example.com"
        with patch.dict(
            os.environ,
            {"ALLOWED_HOSTS": test_hosts, "DEBUG": "True", "SECRET_KEY": "test"},
            clear=True,
        ):
            self._reload_settings()
            from config import settings

            self.assertEqual(
                settings.ALLOWED_HOSTS,
                ["example.com", "www.example.com", "api.example.com"],
            )

    def test_database_from_environment(self):
        """Test that database settings are loaded from environment variables."""
        db_config = {
            "DB_NAME": "test_db",
            "DB_USER": "test_user",
            "DB_PASSWORD": "test_password",
            "DB_HOST": "test_host",
            "DB_PORT": "5433",
            "DEBUG": "True",
            "SECRET_KEY": "test",
        }
        with patch.dict(os.environ, db_config, clear=True):
            self._reload_settings()
            from config import settings

            self.assertEqual(settings.DATABASES["default"]["NAME"], "test_db")
            self.assertEqual(settings.DATABASES["default"]["USER"], "test_user")
            self.assertEqual(settings.DATABASES["default"]["PASSWORD"], "test_password")
            self.assertEqual(settings.DATABASES["default"]["HOST"], "test_host")
            self.assertEqual(settings.DATABASES["default"]["PORT"], "5433")

    def test_celery_from_environment(self):
        """Test that Celery settings are loaded from environment variables."""
        celery_config = {
            "CELERY_BROKER_URL": "redis://test-redis:6379/1",
            "CELERY_RESULT_BACKEND": "redis://test-redis:6379/2",
            "DEBUG": "True",
            "SECRET_KEY": "test",
        }
        with patch.dict(os.environ, celery_config, clear=True):
            self._reload_settings()
            from config import settings

            self.assertEqual(settings.CELERY_BROKER_URL, "redis://test-redis:6379/1")
            self.assertEqual(
                settings.CELERY_RESULT_BACKEND, "redis://test-redis:6379/2"
            )

    def test_email_from_environment(self):
        """Test that email settings are loaded from environment variables."""
        email_config = {
            "EMAIL_BACKEND": "django.core.mail.backends.smtp.EmailBackend",
            "EMAIL_HOST": "smtp.test.com",
            "EMAIL_PORT": "465",
            "EMAIL_USE_TLS": "False",
            "EMAIL_HOST_USER": "test@test.com",
            "EMAIL_HOST_PASSWORD": "test_password",
            "DEBUG": "True",
            "SECRET_KEY": "test",
        }
        with patch.dict(os.environ, email_config, clear=True):
            self._reload_settings()
            from config import settings

            self.assertEqual(
                settings.EMAIL_BACKEND, "django.core.mail.backends.smtp.EmailBackend"
            )
            self.assertEqual(settings.EMAIL_HOST, "smtp.test.com")
            self.assertEqual(settings.EMAIL_PORT, 465)
            self.assertFalse(settings.EMAIL_USE_TLS)


class SettingsNoHardcodedSecretsTest(unittest.TestCase):
    """
    Test that no secrets are hardcoded in settings.
    **Property 2: Конфигурация через переменные окружения**
    """

    def _reload_settings(self):
        """Force reload of settings module."""
        modules_to_remove = [
            key for key in sys.modules.keys() if key.startswith("config")
        ]
        for module in modules_to_remove:
            del sys.modules[module]

    def test_no_hardcoded_secret_key_in_production(self):
        """Test that SECRET_KEY is not using default insecure value in production."""
        prod_config = {
            "DEBUG": "False",
            "SECRET_KEY": "django-insecure-change-this-key",  # Using default
            "DB_NAME": "test_db",
            "DB_USER": "test_user",
            "DB_PASSWORD": "test_pass",
            "ALLOWED_HOSTS": "example.com",
        }

        with patch.dict(os.environ, prod_config, clear=True):
            self._reload_settings()

            # Should raise ValueError because SECRET_KEY is using default insecure value
            with self.assertRaises(ValueError) as context:
                from config import settings

            self.assertIn("SECRET_KEY", str(context.exception))

    def test_settings_file_has_no_hardcoded_passwords(self):
        """Test that settings.py file doesn't contain hardcoded passwords."""
        settings_file = Path(__file__).resolve().parent.parent / "settings.py"
        with open(settings_file, "r") as f:
            content = f.read()

        # Check that there are no obvious hardcoded passwords
        # (passwords should come from config() calls, not string literals)
        suspicious_patterns = [
            "PASSWORD = '",
            'PASSWORD = "',
            "password = '",
            'password = "',
        ]

        for pattern in suspicious_patterns:
            # Allow config() calls but not direct assignments
            if pattern in content:
                # Make sure it's part of a config() call
                lines_with_pattern = [
                    line for line in content.split("\n") if pattern in line
                ]
                for line in lines_with_pattern:
                    if "config(" not in line and "#" not in line:
                        self.fail(f"Found potential hardcoded password in line: {line}")


class SettingsProductionModeTest(unittest.TestCase):
    """
    Test that DEBUG is False in production mode.
    **Property 3: Разделение окружений development/production**
    """

    def _reload_settings(self):
        """Force reload of settings module."""
        modules_to_remove = [
            key for key in sys.modules.keys() if key.startswith("config")
        ]
        for module in modules_to_remove:
            del sys.modules[module]

    def test_debug_false_in_production(self):
        """Test that DEBUG is False when production environment is set."""
        prod_config = {
            "DEBUG": "False",
            "SECRET_KEY": "production-secret-key-12345",
            "DB_NAME": "prod_db",
            "DB_USER": "prod_user",
            "DB_PASSWORD": "prod_password",
            "ALLOWED_HOSTS": "onbr.site,www.onbr.site",
        }

        with patch.dict(os.environ, prod_config, clear=True):
            self._reload_settings()
            from config import settings

            self.assertFalse(settings.DEBUG)

    def test_production_requires_environment_variables(self):
        """Test that production mode requires all necessary environment variables."""
        # Missing DB_NAME
        incomplete_config = {
            "DEBUG": "False",
            "SECRET_KEY": "production-secret-key-12345",
            "ALLOWED_HOSTS": "onbr.site",
        }

        with patch.dict(os.environ, incomplete_config, clear=True):
            self._reload_settings()

            with self.assertRaises(ValueError) as context:
                from config import settings

            self.assertIn("DB_NAME", str(context.exception))

    def test_production_uses_postgresql(self):
        """Test that production mode uses PostgreSQL, not SQLite."""
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

            self.assertEqual(
                settings.DATABASES["default"]["ENGINE"], "django.db.backends.postgresql"
            )

    def test_development_uses_sqlite(self):
        """Test that development mode can use SQLite."""
        dev_config = {"DEBUG": "True", "SECRET_KEY": "dev-secret-key"}

        with patch.dict(os.environ, dev_config, clear=True):
            self._reload_settings()
            from config import settings

            self.assertEqual(
                settings.DATABASES["default"]["ENGINE"], "django.db.backends.sqlite3"
            )

    def test_production_has_secure_settings(self):
        """Test that production mode enables security settings."""
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

            # Check security settings
            self.assertTrue(settings.SESSION_COOKIE_SECURE)
            self.assertTrue(settings.CSRF_COOKIE_SECURE)
            self.assertTrue(settings.SECURE_BROWSER_XSS_FILTER)
            self.assertTrue(settings.SECURE_CONTENT_TYPE_NOSNIFF)
            self.assertEqual(settings.X_FRAME_OPTIONS, "DENY")
            self.assertGreater(settings.SECURE_HSTS_SECONDS, 0)


class SettingsAllowedHostsValidationTest(unittest.TestCase):
    """
    Test ALLOWED_HOSTS validation.
    **Property 5: Безопасность ALLOWED_HOSTS**
    """

    def _reload_settings(self):
        """Force reload of settings module."""
        modules_to_remove = [
            key for key in sys.modules.keys() if key.startswith("config")
        ]
        for module in modules_to_remove:
            del sys.modules[module]

    def test_allowed_hosts_not_default_in_production(self):
        """Test that ALLOWED_HOSTS is not using default localhost values in production."""
        prod_config = {
            "DEBUG": "False",
            "SECRET_KEY": "production-secret-key-12345",
            "DB_NAME": "prod_db",
            "DB_USER": "prod_user",
            "DB_PASSWORD": "prod_password",
            "ALLOWED_HOSTS": "localhost,127.0.0.1",  # Using default
        }

        with patch.dict(os.environ, prod_config, clear=True):
            self._reload_settings()

            # Should raise ValueError because ALLOWED_HOSTS is using default localhost
            with self.assertRaises(ValueError) as context:
                from config import settings

            self.assertIn("ALLOWED_HOSTS", str(context.exception))

    def test_allowed_hosts_set_in_production(self):
        """Test that ALLOWED_HOSTS is properly set in production."""
        prod_config = {
            "DEBUG": "False",
            "SECRET_KEY": "production-secret-key-12345",
            "DB_NAME": "prod_db",
            "DB_USER": "prod_user",
            "DB_PASSWORD": "prod_password",
            "ALLOWED_HOSTS": "onbr.site,www.onbr.site",
        }

        with patch.dict(os.environ, prod_config, clear=True):
            self._reload_settings()
            from config import settings

            self.assertEqual(settings.ALLOWED_HOSTS, ["onbr.site", "www.onbr.site"])
            self.assertNotIn("localhost", settings.ALLOWED_HOSTS)
            self.assertNotIn("127.0.0.1", settings.ALLOWED_HOSTS)

    def test_allowed_hosts_accepts_multiple_domains(self):
        """Test that ALLOWED_HOSTS can accept multiple domains."""
        prod_config = {
            "DEBUG": "False",
            "SECRET_KEY": "production-secret-key-12345",
            "DB_NAME": "prod_db",
            "DB_USER": "prod_user",
            "DB_PASSWORD": "prod_password",
            "ALLOWED_HOSTS": "domain1.com,domain2.com,domain3.com",
        }

        with patch.dict(os.environ, prod_config, clear=True):
            self._reload_settings()
            from config import settings

            self.assertEqual(len(settings.ALLOWED_HOSTS), 3)
            self.assertIn("domain1.com", settings.ALLOWED_HOSTS)
            self.assertIn("domain2.com", settings.ALLOWED_HOSTS)
            self.assertIn("domain3.com", settings.ALLOWED_HOSTS)


if __name__ == "__main__":
    unittest.main()
