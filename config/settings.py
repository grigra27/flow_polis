"""
Django settings for insurance_broker project.
"""
from pathlib import Path
from decouple import config, Csv
import sys
import warnings

# Подавляем предупреждения urllib3 о LibreSSL
warnings.filterwarnings("ignore", message="urllib3 v2 only supports OpenSSL 1.1.1+")
warnings.filterwarnings("ignore", category=UserWarning, module="urllib3")

# Build paths
BASE_DIR = Path(__file__).resolve().parent.parent

# Security
SECRET_KEY = config("SECRET_KEY", default="django-insecure-change-this-key")
DEBUG = config("DEBUG", default=True, cast=bool)
ALLOWED_HOSTS = config("ALLOWED_HOSTS", default="localhost,127.0.0.1", cast=Csv())

# Sentry Configuration for Error Monitoring
SENTRY_DSN = config("SENTRY_DSN", default="")
if SENTRY_DSN:
    import sentry_sdk
    from sentry_sdk.integrations.django import DjangoIntegration
    from sentry_sdk.integrations.celery import CeleryIntegration
    from sentry_sdk.integrations.redis import RedisIntegration

    sentry_sdk.init(
        dsn=SENTRY_DSN,
        integrations=[
            DjangoIntegration(
                transaction_style="url",
                middleware_spans=True,
                signals_spans=True,
            ),
            CeleryIntegration(
                monitor_beat_tasks=True,
                propagate_traces=True,
            ),
            RedisIntegration(),
        ],
        # Performance monitoring
        traces_sample_rate=0.1 if not DEBUG else 0.0,
        # Error sampling
        sample_rate=1.0,
        # Send user information (be careful with PII)
        send_default_pii=False,
        # Environment
        environment="production" if not DEBUG else "development",
        # Release tracking
        release=config("SENTRY_RELEASE", default="unknown"),
        # Additional options
        attach_stacktrace=True,
        max_breadcrumbs=50,
        # Filter out some common errors
        before_send=lambda event, hint: event
        if not _should_filter_sentry_event(event, hint)
        else None,
    )


def _should_filter_sentry_event(event, hint):
    """
    Filter out common errors that we don't want to track in Sentry
    """
    if "exc_info" in hint:
        exc_type, exc_value, tb = hint["exc_info"]

        # Filter out common Django errors that are not actionable
        if exc_type.__name__ in [
            "DisallowedHost",  # Invalid Host header
            "SuspiciousOperation",  # CSRF, etc.
            "PermissionDenied",  # 403 errors
        ]:
            return False

        # Filter out specific error messages
        error_message = str(exc_value).lower()
        filtered_messages = [
            "broken pipe",
            "connection reset by peer",
            "client disconnected",
        ]

        if any(msg in error_message for msg in filtered_messages):
            return False

    return True


# Production environment checks
# Check if we're running in production mode (DEBUG=False)
if not DEBUG:
    # Validate required environment variables for production
    required_env_vars = [
        "SECRET_KEY",
        "DB_NAME",
        "DB_USER",
        "DB_PASSWORD",
        "ALLOWED_HOSTS",
    ]
    missing_vars = []

    for var in required_env_vars:
        # Check if the variable is set and not using default values
        if var == "SECRET_KEY":
            if SECRET_KEY == "django-insecure-change-this-key":
                missing_vars.append(var)
        elif var == "ALLOWED_HOSTS":
            if ALLOWED_HOSTS == ["localhost", "127.0.0.1"]:
                missing_vars.append(var)
        else:
            # For other vars, check if they're set in environment
            try:
                value = config(var)
                if not value:
                    missing_vars.append(var)
            except:
                missing_vars.append(var)

    if missing_vars:
        raise ValueError(
            f"Production mode requires the following environment variables to be set: "
            f"{', '.join(missing_vars)}"
        )

    # Ensure DEBUG is explicitly False in production
    if DEBUG:
        raise ValueError("DEBUG must be False in production environment")

# Application definition
INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # Third party apps
    "django_extensions",
    "django_filters",
    "import_export",
    "auditlog",
    "django_celery_beat",
    # Local apps
    "apps.accounts",
    "apps.core",
    "apps.clients",
    "apps.insurers",
    "apps.policies",
    "apps.notifications",
    "apps.reports",
]

if DEBUG:
    INSTALLED_APPS += ["debug_toolbar"]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "auditlog.middleware.AuditlogMiddleware",
    "apps.accounts.middleware.LoginAttemptMiddleware",  # Validates: Requirements 1.1, 1.5
    "apps.accounts.middleware.PermissionCheckMiddleware",  # Validates: Requirements 3.5, 4.1
    # 'apps.core.middleware.InputValidationMiddleware',  # Validates: Requirements 3.3, 3.4 (Optional - enable if needed)
]

if DEBUG:
    MIDDLEWARE += ["debug_toolbar.middleware.DebugToolbarMiddleware"]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "apps.accounts.context_processors.user_permissions",  # Validates: Requirements 3.2, 4.2
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

# Database
db_name = config("DB_NAME", default="")
if db_name:
    # PostgreSQL
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": db_name,
            "USER": config("DB_USER", default="postgres"),
            "PASSWORD": config("DB_PASSWORD", default=""),
            "HOST": config("DB_HOST", default="localhost"),
            "PORT": config("DB_PORT", default="5432"),
        }
    }
else:
    # SQLite (default for development)
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        }
    }

# Password validation
# Validates: Requirements 2.1, 2.3, 2.4
AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"
    },
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
        "OPTIONS": {"min_length": 12},
    },
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
    {"NAME": "apps.accounts.validators.ComplexityPasswordValidator"},
    {"NAME": "apps.accounts.validators.WeakPasswordValidator"},
]

# Internationalization
LANGUAGE_CODE = "ru-ru"
TIME_ZONE = "Europe/Moscow"
USE_I18N = True
USE_TZ = True

# Static files
STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]

# Use WhiteNoise only in development, nginx serves static files in production
if DEBUG:
    STATICFILES_STORAGE = "whitenoise.storage.CompressedManifestStaticFilesStorage"
else:
    STATICFILES_STORAGE = "django.contrib.staticfiles.storage.StaticFilesStorage"

# Media files
MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"

# Default primary key
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Celery Configuration
CELERY_BROKER_URL = config("CELERY_BROKER_URL", default="redis://localhost:6379/0")
CELERY_RESULT_BACKEND = config(
    "CELERY_RESULT_BACKEND", default="redis://localhost:6379/0"
)
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TASK_SERIALIZER = "json"
CELERY_RESULT_SERIALIZER = "json"
CELERY_TIMEZONE = TIME_ZONE

# Email Configuration
EMAIL_BACKEND = config(
    "EMAIL_BACKEND", default="django.core.mail.backends.console.EmailBackend"
)
EMAIL_HOST = config("EMAIL_HOST", default="smtp.gmail.com")
EMAIL_PORT = config("EMAIL_PORT", default=587, cast=int)
EMAIL_USE_TLS = config("EMAIL_USE_TLS", default=True, cast=bool)
EMAIL_HOST_USER = config("EMAIL_HOST_USER", default="")
EMAIL_HOST_PASSWORD = config("EMAIL_HOST_PASSWORD", default="")

# Debug Toolbar
INTERNAL_IPS = ["127.0.0.1"]

# Authentication settings
# Validates: Requirements 1.1, 2.1, 5.2
LOGIN_URL = "accounts:login"
LOGIN_REDIRECT_URL = "core:dashboard"
LOGOUT_REDIRECT_URL = "accounts:login"

# Logging
# Validates: Requirements 3.5, 6.1, 12.1, 12.2, 12.3, 12.4, 12.5 - Secure logging with sensitive data filtering
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "filters": {
        "sensitive_data": {
            "()": "apps.core.logging_filters.SensitiveDataFilter",
        },
        "sql_query": {
            "()": "apps.core.logging_filters.SQLQueryFilter",
        },
    },
    "formatters": {
        "verbose": {
            "format": "{levelname} {asctime} {module} {process:d} {thread:d} {message}",
            "style": "{",
        },
        "simple": {
            "format": "{levelname} {message}",
            "style": "{",
        },
        "security": {
            "format": "{levelname} {asctime} {name} {message}",
            "style": "{",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "verbose" if not DEBUG else "simple",
            "filters": ["sensitive_data"],
        },
        "file": {
            "class": "logging.handlers.RotatingFileHandler",
            "filename": BASE_DIR / "logs" / "django.log",
            "maxBytes": 1024 * 1024 * 10,  # 10 MB
            "backupCount": 10,
            "formatter": "verbose",
            "filters": ["sensitive_data"],
        },
        "security_file": {
            "class": "logging.handlers.RotatingFileHandler",
            "filename": BASE_DIR / "logs" / "security.log",
            "maxBytes": 1024 * 1024 * 10,  # 10 MB
            "backupCount": 10,
            "formatter": "security",
            "filters": ["sensitive_data"],
        },
    },
    "root": {
        "handlers": ["console"] if DEBUG else ["console", "file"],
        "level": "DEBUG" if DEBUG else "INFO",
    },
    "loggers": {
        "django": {
            "handlers": ["console"] if DEBUG else ["console", "file"],
            "level": "INFO",
            "propagate": False,
        },
        "django.request": {
            "handlers": ["console"] if DEBUG else ["console", "file"],
            "level": "ERROR",
            "propagate": False,
        },
        "django.db.backends": {
            "handlers": ["console"] if DEBUG else ["console", "file"],
            "level": "DEBUG" if DEBUG else "INFO",
            "filters": ["sql_query"],
            "propagate": False,
        },
        "apps.reports": {
            "handlers": ["console"] if DEBUG else ["console", "file"],
            "level": "INFO",
            "propagate": False,
        },
        "security": {
            "handlers": ["security_file", "console"],
            "level": "INFO",
            "propagate": False,
        },
    },
}

# Security settings for production
# Validates: Requirements 9.1, 9.2, 9.3, 9.4, 9.5
if not DEBUG:
    # HTTPS/SSL settings
    SECURE_SSL_REDIRECT = config("SECURE_SSL_REDIRECT", default=True, cast=bool)
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True

    # Validates: Requirements 9.1 - X-Content-Type-Options
    SECURE_CONTENT_TYPE_NOSNIFF = True

    # Validates: Requirements 9.1 - X-XSS-Protection (legacy but still useful)
    SECURE_BROWSER_XSS_FILTER = True

    # Validates: Requirements 9.2 - X-Frame-Options
    X_FRAME_OPTIONS = "DENY"

    # Validates: Requirements 9.3 - HSTS settings
    SECURE_HSTS_SECONDS = config(
        "SECURE_HSTS_SECONDS", default=31536000, cast=int
    )  # 1 year minimum
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True

    # Validates: Requirements 9.4 - Content-Security-Policy
    # Note: CSP is primarily set in Nginx, but we ensure Django doesn't interfere
    CSP_DEFAULT_SRC = ("'self'",)
    CSP_SCRIPT_SRC = ("'self'", "'unsafe-inline'", "'unsafe-eval'")
    CSP_STYLE_SRC = ("'self'", "'unsafe-inline'")
    CSP_IMG_SRC = ("'self'", "data:", "https:")
    CSP_FONT_SRC = ("'self'", "data:")
    CSP_CONNECT_SRC = ("'self'",)
    CSP_FRAME_ANCESTORS = ("'none'",)
    CSP_BASE_URI = ("'self'",)
    CSP_FORM_ACTION = ("'self'",)

    # Validates: Requirements 9.5 - Referrer-Policy
    SECURE_REFERRER_POLICY = "strict-origin-when-cross-origin"

    # Proxy settings (for Nginx)
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    USE_X_FORWARDED_HOST = True
    USE_X_FORWARDED_PORT = True

    # Session security
    # Validates: Requirements 1.3 - Session timeout
    SESSION_COOKIE_AGE = 86400  # 24 hours
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Strict"
    SESSION_SAVE_EVERY_REQUEST = False
    SESSION_EXPIRE_AT_BROWSER_CLOSE = False

    # CSRF security
    # Validates: Requirements 5.4 - CSRF SameSite
    CSRF_COOKIE_HTTPONLY = True
    CSRF_COOKIE_SAMESITE = "Strict"
    CSRF_USE_SESSIONS = False

    # Create logs directory if it doesn't exist
    import os

    logs_dir = BASE_DIR / "logs"
    if not os.path.exists(logs_dir):
        os.makedirs(logs_dir)
