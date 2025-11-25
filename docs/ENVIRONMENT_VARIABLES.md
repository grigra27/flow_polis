# Environment Variables Documentation

This document provides comprehensive documentation for all environment variables used in the Insurance Broker System.

## Table of Contents

- [Overview](#overview)
- [Environment Files](#environment-files)
- [Variable Reference](#variable-reference)
- [Security Best Practices](#security-best-practices)
- [Setup Instructions](#setup-instructions)

## Overview

The application uses environment variables to manage configuration across different environments (development, production). This approach follows the [12-factor app methodology](https://12factor.net/config) and ensures:

- **Security**: Sensitive data (passwords, API keys) are never committed to version control
- **Flexibility**: Easy configuration changes without code modifications
- **Environment Separation**: Different settings for development and production

## Environment Files

### Development Environment

**File**: `.env` (created from `.env.example`)

Used for local development with SQLite database and console email backend.

```bash
cp .env.example .env
# Edit .env with your local settings
```

### Production Environment

**Files**: 
- `.env.prod` (created from `.env.prod.example`)
- `.env.prod.db` (created from `.env.prod.db.example`)

Used for production deployment with PostgreSQL, Redis, and real SMTP email.

```bash
cp .env.prod.example .env.prod
cp .env.prod.db.example .env.prod.db
# Edit both files with your production settings
```

⚠️ **IMPORTANT**: Never commit `.env`, `.env.prod`, or `.env.prod.db` to version control!

## Variable Reference

### Django Core Settings

#### `SECRET_KEY` (Required)

**Purpose**: Cryptographic signing key for Django security features (sessions, CSRF, password reset tokens)

**Development**: Any string (insecure key is acceptable)
```
SECRET_KEY=django-insecure-dev-key-change-in-production
```

**Production**: Strong random 50+ character string
```bash
# Generate using:
python -c 'from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())'
```

**Example**:
```
SECRET_KEY=django-insecure-a8f#2k9$mxp@4v7n!q3w&e5r^t6y*u8i(o0p)
```

**Security**: Must be kept secret. Changing this will invalidate all sessions and signed data.

---

#### `DEBUG` (Required)

**Purpose**: Enables/disables Django debug mode

**Development**: `True`
**Production**: `False` (MUST be False for security)

**Values**: `True` or `False`

**Impact**:
- When `True`: Shows detailed error pages with stack traces, uses SQLite by default
- When `False`: Shows generic error pages, requires proper logging configuration

**Security**: NEVER set to `True` in production - exposes sensitive information!

---

#### `ALLOWED_HOSTS` (Required)

**Purpose**: List of host/domain names that Django will serve

**Development**: 
```
ALLOWED_HOSTS=localhost,127.0.0.1
```

**Production**:
```
ALLOWED_HOSTS=onbr.site,www.onbr.site
```

**Format**: Comma-separated list of domains (no spaces)

**Security**: Django will reject requests with Host headers not in this list (prevents Host header attacks)

---

### Database Configuration

#### `DB_NAME` (Required for Production)

**Purpose**: PostgreSQL database name

**Development**: Leave empty (uses SQLite)
```
DB_NAME=
```

**Production**:
```
DB_NAME=insurance_broker_prod
```

---

#### `DB_USER` (Required for Production)

**Purpose**: PostgreSQL username

**Development**: Leave empty
```
DB_USER=
```

**Production**:
```
DB_USER=postgres
```

**Note**: Can use a different user than `postgres` for better security

---

#### `DB_PASSWORD` (Required for Production)

**Purpose**: PostgreSQL password

**Development**: Leave empty
```
DB_PASSWORD=
```

**Production**: Strong random password
```bash
# Generate using:
python -c 'import secrets; print(secrets.token_urlsafe(32))'
```

**Example**:
```
DB_PASSWORD=xK9mP2nQ5rT8wY3zA6bC9dF2gH5jK8lM
```

**Security**: 
- Must match `POSTGRES_PASSWORD` in `.env.prod.db`
- Use at least 20 characters
- Include uppercase, lowercase, numbers, and special characters
- Never use default passwords like 'postgres' or 'password'

---

#### `DB_HOST` (Required for Production)

**Purpose**: PostgreSQL server hostname

**Development**: Leave empty
```
DB_HOST=
```

**Production** (Docker):
```
DB_HOST=db
```

**Note**: In Docker Compose, `db` is the service name of the PostgreSQL container

---

#### `DB_PORT` (Required for Production)

**Purpose**: PostgreSQL server port

**Development**: Leave empty
```
DB_PORT=
```

**Production**:
```
DB_PORT=5432
```

**Note**: 5432 is the default PostgreSQL port

---

### Celery Configuration

#### `CELERY_BROKER_URL` (Required for Background Tasks)

**Purpose**: Redis connection URL for Celery message broker

**Development**:
```
CELERY_BROKER_URL=redis://localhost:6379/0
```

**Production** (Docker):
```
CELERY_BROKER_URL=redis://redis:6379/0
```

**Format**: `redis://[host]:[port]/[db_number]`

---

#### `CELERY_RESULT_BACKEND` (Required for Background Tasks)

**Purpose**: Redis connection URL for storing Celery task results

**Development**:
```
CELERY_RESULT_BACKEND=redis://localhost:6379/0
```

**Production** (Docker):
```
CELERY_RESULT_BACKEND=redis://redis:6379/0
```

---

### Email Configuration

#### `EMAIL_BACKEND` (Required)

**Purpose**: Django email backend class

**Development** (prints emails to console):
```
EMAIL_BACKEND=django.core.mail.backends.console.EmailBackend
```

**Production** (sends real emails via SMTP):
```
EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend
```

**Other Options**:
- `django.core.mail.backends.filebased.EmailBackend` - saves emails to files
- `django.core.mail.backends.dummy.EmailBackend` - discards emails (testing)

---

#### `EMAIL_HOST` (Required for Production)

**Purpose**: SMTP server hostname

**Common Values**:
- Gmail: `smtp.gmail.com`
- Outlook: `smtp-mail.outlook.com`
- SendGrid: `smtp.sendgrid.net`
- Mailgun: `smtp.mailgun.org`

**Example**:
```
EMAIL_HOST=smtp.gmail.com
```

---

#### `EMAIL_PORT` (Required for Production)

**Purpose**: SMTP server port

**Common Values**:
- `587` - TLS (recommended)
- `465` - SSL
- `25` - Unencrypted (not recommended)

**Example**:
```
EMAIL_PORT=587
```

---

#### `EMAIL_USE_TLS` (Required for Production)

**Purpose**: Enable TLS encryption for SMTP

**Values**: `True` or `False`

**Recommended**:
```
EMAIL_USE_TLS=True
```

---

#### `EMAIL_HOST_USER` (Required for Production)

**Purpose**: SMTP authentication username (usually your email address)

**Example**:
```
EMAIL_HOST_USER=your-email@gmail.com
```

---

#### `EMAIL_HOST_PASSWORD` (Required for Production)

**Purpose**: SMTP authentication password

**Gmail Users**: Use an [App Password](https://support.google.com/accounts/answer/185833), not your regular password

**Example**:
```
EMAIL_HOST_PASSWORD=abcd efgh ijkl mnop
```

**Security**: Keep this secret! Never commit to version control.

---

#### `DEFAULT_FROM_EMAIL` (Optional)

**Purpose**: Default "from" email address for outgoing emails

**Example**:
```
DEFAULT_FROM_EMAIL=noreply@onbr.site
```

---

### Security Settings (Production Only)

#### `SECURE_SSL_REDIRECT` (Production)

**Purpose**: Redirect all HTTP requests to HTTPS

**Production**:
```
SECURE_SSL_REDIRECT=True
```

**Note**: Only enable after SSL certificate is configured

---

#### `SECURE_HSTS_SECONDS` (Production)

**Purpose**: HTTP Strict Transport Security (HSTS) max-age in seconds

**Production**:
```
SECURE_HSTS_SECONDS=31536000
```

**Note**: 31536000 = 1 year. Tells browsers to only use HTTPS for this domain.

---

#### `SECURE_HSTS_INCLUDE_SUBDOMAINS` (Production)

**Purpose**: Apply HSTS to all subdomains

**Production**:
```
SECURE_HSTS_INCLUDE_SUBDOMAINS=True
```

---

#### `SECURE_HSTS_PRELOAD` (Production)

**Purpose**: Allow domain to be included in browser HSTS preload lists

**Production**:
```
SECURE_HSTS_PRELOAD=True
```

---

#### `SESSION_COOKIE_SECURE` (Production)

**Purpose**: Only send session cookies over HTTPS

**Production**:
```
SESSION_COOKIE_SECURE=True
```

---

#### `CSRF_COOKIE_SECURE` (Production)

**Purpose**: Only send CSRF cookies over HTTPS

**Production**:
```
CSRF_COOKIE_SECURE=True
```

---

#### `SECURE_CONTENT_TYPE_NOSNIFF` (Production)

**Purpose**: Prevent browsers from MIME-sniffing

**Production**:
```
SECURE_CONTENT_TYPE_NOSNIFF=True
```

---

#### `SECURE_BROWSER_XSS_FILTER` (Production)

**Purpose**: Enable browser XSS filtering

**Production**:
```
SECURE_BROWSER_XSS_FILTER=True
```

---

#### `X_FRAME_OPTIONS` (Production)

**Purpose**: Prevent clickjacking attacks

**Production**:
```
X_FRAME_OPTIONS=DENY
```

**Values**: `DENY`, `SAMEORIGIN`, or `ALLOW-FROM uri`

---

### Static and Media Files

#### `STATIC_ROOT` (Production)

**Purpose**: Absolute path where static files are collected

**Production** (Docker):
```
STATIC_ROOT=/app/staticfiles
```

---

#### `MEDIA_ROOT` (Production)

**Purpose**: Absolute path where user-uploaded files are stored

**Production** (Docker):
```
MEDIA_ROOT=/app/media
```

---

#### `STATIC_URL` (Optional)

**Purpose**: URL prefix for static files

**Default**:
```
STATIC_URL=/static/
```

---

#### `MEDIA_URL` (Optional)

**Purpose**: URL prefix for media files

**Default**:
```
MEDIA_URL=/media/
```

---

### Logging Configuration

#### `LOG_LEVEL` (Optional)

**Purpose**: Minimum logging level

**Values**: `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL`

**Development**: `DEBUG`
**Production**: `INFO` or `WARNING`

**Example**:
```
LOG_LEVEL=INFO
```

---

### PostgreSQL Container Variables (.env.prod.db)

These variables are used by the PostgreSQL Docker container and must match the database settings in `.env.prod`.

#### `POSTGRES_DB` (Required)

**Purpose**: Database name to create

**Must Match**: `DB_NAME` in `.env.prod`

**Example**:
```
POSTGRES_DB=insurance_broker_prod
```

---

#### `POSTGRES_USER` (Required)

**Purpose**: PostgreSQL superuser name

**Must Match**: `DB_USER` in `.env.prod`

**Example**:
```
POSTGRES_USER=postgres
```

---

#### `POSTGRES_PASSWORD` (Required)

**Purpose**: PostgreSQL superuser password

**Must Match**: `DB_PASSWORD` in `.env.prod`

**Example**:
```
POSTGRES_PASSWORD=xK9mP2nQ5rT8wY3zA6bC9dF2gH5jK8lM
```

---

## Security Best Practices

### 1. Never Commit Secrets

✅ **DO**:
- Use `.env.example` files with placeholder values
- Add `.env`, `.env.prod`, `.env.prod.db` to `.gitignore`
- Document required variables without exposing actual values

❌ **DON'T**:
- Commit files containing real passwords, API keys, or secret keys
- Share `.env` files via email or chat
- Store secrets in code comments

### 2. Use Strong Passwords

✅ **DO**:
- Generate random passwords with at least 20 characters
- Use a mix of uppercase, lowercase, numbers, and special characters
- Use different passwords for different services

❌ **DON'T**:
- Use default passwords like 'postgres', 'admin', 'password'
- Reuse passwords across environments
- Use dictionary words or personal information

### 3. Rotate Secrets Regularly

- Change `SECRET_KEY` if compromised
- Rotate database passwords periodically
- Update API keys when team members leave

### 4. Limit Access

- Only share production credentials with authorized personnel
- Use GitHub Secrets for CI/CD (never hardcode in workflows)
- Consider using a secrets management service (AWS Secrets Manager, HashiCorp Vault)

### 5. Production Checklist

Before deploying to production, verify:

- [ ] `DEBUG=False`
- [ ] Strong `SECRET_KEY` (50+ random characters)
- [ ] Strong `DB_PASSWORD` (20+ random characters)
- [ ] `ALLOWED_HOSTS` includes only your domains
- [ ] All security settings enabled (`SECURE_SSL_REDIRECT`, etc.)
- [ ] Real SMTP credentials configured
- [ ] `.env.prod` and `.env.prod.db` are in `.gitignore`
- [ ] No secrets committed to version control

## Setup Instructions

### Development Setup

1. Copy the example file:
   ```bash
   cp .env.example .env
   ```

2. Edit `.env` with your local settings (usually defaults are fine)

3. Run migrations:
   ```bash
   python manage.py migrate
   ```

4. Start development server:
   ```bash
   python manage.py runserver
   ```

### Production Setup

1. Copy the example files:
   ```bash
   cp .env.prod.example .env.prod
   cp .env.prod.db.example .env.prod.db
   ```

2. Generate a strong secret key:
   ```bash
   python -c 'from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())'
   ```

3. Generate a strong database password:
   ```bash
   python -c 'import secrets; print(secrets.token_urlsafe(32))'
   ```

4. Edit `.env.prod`:
   - Set `SECRET_KEY` to the generated value
   - Set `DEBUG=False`
   - Set `ALLOWED_HOSTS` to your domain(s)
   - Set `DB_PASSWORD` to the generated password
   - Configure email settings with your SMTP credentials
   - Enable all security settings

5. Edit `.env.prod.db`:
   - Set `POSTGRES_PASSWORD` to the SAME password as `DB_PASSWORD` in `.env.prod`
   - Ensure `POSTGRES_DB` matches `DB_NAME`
   - Ensure `POSTGRES_USER` matches `DB_USER`

6. Verify files are in `.gitignore`:
   ```bash
   git check-ignore .env.prod .env.prod.db
   ```
   Should output both filenames.

7. Deploy using Docker Compose:
   ```bash
   docker-compose -f docker-compose.prod.yml up -d
   ```

### GitHub Actions Setup

For CI/CD, add these secrets to your GitHub repository:

1. Go to repository Settings → Secrets and variables → Actions
2. Add the following secrets:
   - `SSH_PRIVATE_KEY` - SSH key for connecting to your server
   - `DROPLET_HOST` - Your server IP address
   - `DROPLET_USER` - SSH username (usually `root` or `ubuntu`)
   - `SECRET_KEY` - Django secret key
   - `DB_PASSWORD` - Database password
   - `EMAIL_HOST_PASSWORD` - SMTP password

Never hardcode these values in `.github/workflows/` files!

## Troubleshooting

### "SECRET_KEY not found"

**Problem**: Django can't find the SECRET_KEY environment variable

**Solution**: 
1. Ensure `.env` or `.env.prod` file exists
2. Check the file contains `SECRET_KEY=...`
3. Restart your application/container

### "Database connection failed"

**Problem**: Can't connect to PostgreSQL

**Solution**:
1. Verify `DB_PASSWORD` in `.env.prod` matches `POSTGRES_PASSWORD` in `.env.prod.db`
2. Check `DB_HOST=db` (the Docker service name)
3. Ensure PostgreSQL container is running: `docker-compose ps`

### "ALLOWED_HOSTS validation failed"

**Problem**: Django rejects requests with "Invalid HTTP_HOST header"

**Solution**:
1. Add your domain to `ALLOWED_HOSTS` in `.env.prod`
2. Format: `ALLOWED_HOSTS=domain1.com,domain2.com` (no spaces)
3. Restart the application

### "Email not sending"

**Problem**: Emails aren't being sent in production

**Solution**:
1. Check `EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend`
2. Verify SMTP credentials are correct
3. For Gmail, use an App Password, not your regular password
4. Check firewall allows outbound connections on port 587
5. View logs: `docker-compose logs web`

## Additional Resources

- [Django Settings Documentation](https://docs.djangoproject.com/en/4.2/ref/settings/)
- [12-Factor App Config](https://12factor.net/config)
- [Django Security Checklist](https://docs.djangoproject.com/en/4.2/howto/deployment/checklist/)
- [PostgreSQL Environment Variables](https://www.postgresql.org/docs/current/libpq-envars.html)
- [Celery Configuration](https://docs.celeryproject.org/en/stable/userguide/configuration.html)
