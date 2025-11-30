# Logging Tests Summary

This document describes the logging tests implemented for the Docker deployment.

## Overview

The logging tests validate that Docker properly captures and makes accessible all application logs, including error logs with full tracebacks. These tests ensure compliance with requirements 8.1 and 8.2 from the design specification.

## Test Class: TestLogging

**Location:** `tests/test_docker_integration.py`

**Validates:** Requirements 8.1, 8.2

### Test Methods

#### 1. test_docker_captures_application_logs

**Purpose:** Verify that Docker captures application logs and makes them accessible via `docker logs`.

**Validates:** Requirement 8.1

**What it tests:**
- Docker logging driver captures Django/Gunicorn application logs
- Logs are accessible through `docker compose logs` command
- Logs contain expected application output (Django/Gunicorn messages)

**How it works:**
1. Waits for web service to become healthy
2. Generates log entries by making HTTP requests to the application
3. Retrieves logs using `docker compose logs web`
4. Verifies logs are not empty
5. Checks for Django/Gunicorn-specific content in logs

#### 2. test_application_logs_errors_with_traceback

**Purpose:** Verify that application logs errors with full traceback information.

**Validates:** Requirement 8.2

**What it tests:**
- Application logs errors with complete traceback
- Python exceptions are properly captured in logs
- Traceback information includes file names, line numbers, and error messages

**How it works:**
1. Waits for web service to become healthy
2. Triggers errors by accessing invalid URLs
3. Executes Python code that raises an exception with traceback
4. Retrieves logs using `docker compose logs web`
5. Verifies logs contain traceback elements:
   - "Traceback" keyword
   - Exception type (e.g., ValueError)
   - File and line information
   - Error messages

#### 3. test_celery_logs_are_captured

**Purpose:** Verify that Celery worker logs are captured by Docker.

**Validates:** Requirement 8.1

**What it tests:**
- Docker captures Celery worker logs
- Celery logs are accessible through `docker logs`
- Logs contain expected Celery worker output

**How it works:**
1. Waits for Celery worker to become healthy
2. Retrieves logs using `docker compose logs celery_worker`
3. Verifies logs are not empty
4. Checks for Celery-specific content (worker, ready, connected)

#### 4. test_nginx_logs_are_captured

**Purpose:** Verify that Nginx access and error logs are captured by Docker.

**Validates:** Requirement 8.1

**What it tests:**
- Docker captures Nginx access logs
- HTTP request information is logged
- Logs are accessible through `docker logs`

**How it works:**
1. Waits for Nginx to become healthy
2. Generates access logs by making multiple HTTP requests
3. Retrieves logs using `docker compose logs nginx`
4. Verifies logs are not empty
5. Checks for HTTP access log patterns (GET requests, status codes)

## Requirements Validation

### Requirement 8.1 ✅
**"КОГДА Приложение логирует сообщение ТО Docker ДОЛЖЕН захватить его и сделать доступным через docker logs"**

**Validated by:**
- `test_docker_captures_application_logs` - Django/Gunicorn logs
- `test_celery_logs_are_captured` - Celery worker logs
- `test_nginx_logs_are_captured` - Nginx access logs

**Evidence:**
- All services configured with json-file logging driver
- Logs successfully retrieved using `docker compose logs` command
- Logs contain expected application output

### Requirement 8.2 ✅
**"КОГДА происходит ошибка ТО Приложение ДОЛЖНО залогировать её с полным traceback"**

**Validated by:**
- `test_application_logs_errors_with_traceback`

**Evidence:**
- Python exceptions logged with full traceback
- Traceback includes file names, line numbers, and error messages
- Error information accessible through Docker logs

## Running the Tests

### Prerequisites

1. Docker and Docker Compose installed
2. `.env.prod` and `.env.prod.db` files configured
3. Docker containers running

### Run All Logging Tests

```bash
# Using unittest
python -m unittest tests.test_docker_integration.TestLogging -v

# Or run all integration tests
python tests/test_docker_integration.py
```

### Run Individual Tests

```bash
# Test application log capture
python -m unittest tests.test_docker_integration.TestLogging.test_docker_captures_application_logs -v

# Test error logging with traceback
python -m unittest tests.test_docker_integration.TestLogging.test_application_logs_errors_with_traceback -v

# Test Celery log capture
python -m unittest tests.test_docker_integration.TestLogging.test_celery_logs_are_captured -v

# Test Nginx log capture
python -m unittest tests.test_docker_integration.TestLogging.test_nginx_logs_are_captured -v
```

## Test Environment

These are integration tests that require:
- Docker daemon running
- Docker Compose available
- Production Docker Compose configuration (`docker-compose.prod.yml`)
- All services started and healthy

## Expected Behavior

### Successful Test Run

When all tests pass, you should see:
```
test_application_logs_errors_with_traceback ... ok
test_celery_logs_are_captured ... ok
test_docker_captures_application_logs ... ok
test_nginx_logs_are_captured ... ok

----------------------------------------------------------------------
Ran 4 tests in XXX.XXXs

OK
```

### What the Tests Verify

1. **Log Capture:** Docker successfully captures logs from all services
2. **Log Accessibility:** Logs are accessible via `docker logs` and `docker compose logs`
3. **Log Content:** Logs contain expected application output
4. **Error Logging:** Errors are logged with complete traceback information
5. **Multi-Service:** Logging works across all services (web, Celery, Nginx)

## Troubleshooting

### Tests Fail with "Docker not found"

**Problem:** Docker is not installed or not in PATH

**Solution:**
```bash
# Check Docker installation
docker --version
docker compose version

# Ensure Docker daemon is running
docker ps
```

### Tests Fail with "Service did not become healthy"

**Problem:** Docker containers are not running or not healthy

**Solution:**
```bash
# Start Docker Compose services
docker compose -f docker-compose.prod.yml up -d

# Check service status
docker compose -f docker-compose.prod.yml ps

# Check service health
docker compose -f docker-compose.prod.yml ps --format json | jq '.[] | {Service, State, Health}'
```

### Tests Fail with "Logs are empty"

**Problem:** Services are not generating logs or logging is misconfigured

**Solution:**
```bash
# Check logging configuration in docker-compose.prod.yml
docker compose -f docker-compose.prod.yml config | grep -A 5 logging

# Manually check logs
docker compose -f docker-compose.prod.yml logs web

# Verify logging driver
docker inspect insurance_broker_web | jq '.[0].HostConfig.LogConfig'
```

## Integration with CI/CD

These tests can be integrated into CI/CD pipelines:

```yaml
# Example GitHub Actions workflow
- name: Run Logging Tests
  run: |
    docker compose -f docker-compose.prod.yml up -d
    sleep 30  # Wait for services to be healthy
    python -m unittest tests.test_docker_integration.TestLogging -v
    docker compose -f docker-compose.prod.yml down
```

## Related Documentation

- [tests/README.md](README.md) - Complete integration tests documentation
- [LOGGING_CONFIGURATION_SUMMARY.md](../LOGGING_CONFIGURATION_SUMMARY.md) - Logging configuration details
- [docs/MONITORING.md](../docs/MONITORING.md) - Monitoring and logging guide
- [MONITORING_QUICK_REFERENCE.md](../MONITORING_QUICK_REFERENCE.md) - Quick reference for log commands

## Implementation Notes

### Test Design Principles

1. **Real Environment:** Tests run against actual Docker containers, not mocks
2. **Comprehensive Coverage:** Tests cover all major services (web, Celery, Nginx)
3. **Requirement Traceability:** Each test explicitly validates specific requirements
4. **Clear Assertions:** Tests verify specific, measurable outcomes
5. **Helpful Output:** Tests print progress messages for debugging

### Logging Configuration

The tests rely on the logging configuration in `docker-compose.prod.yml`:

```yaml
logging:
  driver: "json-file"
  options:
    max-size: "10m"
    max-file: "3"
    tag: "{{.Name}}"
```

This configuration:
- Uses Docker's json-file logging driver
- Automatically rotates logs (max 10MB per file, 3 files)
- Tags logs with container names
- Makes logs accessible via `docker logs` command

### Django Logging Configuration

Django logging is configured in `config/settings.py`:

```python
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'verbose': {
            'format': '{levelname} {asctime} {module} {process:d} {thread:d} {message}',
            'style': '{',
        },
    },
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
            'formatter': 'verbose',
        },
        'file': {
            'class': 'logging.handlers.RotatingFileHandler',
            'filename': BASE_DIR / 'logs' / 'django.log',
            'maxBytes': 1024 * 1024 * 10,  # 10 MB
            'backupCount': 5,
            'formatter': 'verbose',
        },
    },
    'root': {
        'handlers': ['console', 'file'],
        'level': 'INFO',
    },
    'loggers': {
        'django.request': {
            'handlers': ['console', 'file'],
            'level': 'ERROR',
            'propagate': False,
        },
    },
}
```

This ensures:
- All logs go to console (captured by Docker)
- Errors include full traceback
- Log format includes timestamp, level, module, and message

## Conclusion

The logging tests provide comprehensive validation that:
1. Docker properly captures logs from all services
2. Logs are accessible through standard Docker commands
3. Errors are logged with complete traceback information
4. The logging system meets all specified requirements

These tests ensure the production logging infrastructure is working correctly and will help catch any logging configuration issues before deployment.

---

**Implementation Date:** November 25, 2024
**Task:** 14. Написать тесты для проверки логирования
**Status:** ✅ Complete
