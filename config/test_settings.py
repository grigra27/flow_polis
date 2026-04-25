"""
Test settings for running tests with SQLite database
"""
from .settings import *

# Use SQLite for testing
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
    }
}


# Disable migrations for faster tests
class DisableMigrations:
    def __contains__(self, item):
        return True

    def __getitem__(self, item):
        return None


MIGRATION_MODULES = DisableMigrations()

# Speed up password hashing for tests
PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.MD5PasswordHasher",
]

# Используем простой staticfiles storage без manifest/сжатия:
# WhiteNoise CompressedManifestStaticFilesStorage в проде требует, чтобы
# collectstatic был выполнен заранее. В тестах он не запускается, и любой
# {% static %} в шаблонах падает с "Missing staticfiles manifest entry".
STORAGES = {
    "default": {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
    },
    "staticfiles": {
        "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage",
    },
}
