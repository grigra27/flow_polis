# Docker Integration Testing Guide

This document describes the integration tests for the Docker deployment setup and how to run them.

## Overview

The integration test suite validates the complete Docker Compose production environment, including:

- ✅ All containers start successfully
- ✅ Web application connects to PostgreSQL database
- ✅ Celery workers connect to Redis
- ✅ Nginx reverse proxy serves the application
- ✅ Static files are collected and served correctly
- ✅ **Property 1**: Data persists across container restarts (PostgreSQL, Redis, static files)
- ✅ **Property 4**: Containers automatically restart after failures

## Test Coverage

### Requirements Validated

The integration tests validate the following requirements from the specification:

- **1.2, 1.3**: Docker Compose starts all necessary services
- **1.5**: Application is accessible through Nginx
- **6.1, 6.2, 6.3**: Data persistence with Docker volumes
- **7.1, 7.3**: Celery and Redis connectivity
- **7.4, 8.3**: Automatic container restart policies

### Correctness Properties

#### Property 1: Data Persistence Across Container Restarts

**Statement**: *For any* container with a Docker volume, when data is written to the volume and the container is restarted, the data should remain accessible and unchanged.

**Tests**:
- `test_postgres_data_persists_after_restart`: Validates PostgreSQL data persistence
- `test_redis_data_persists_after_restart`: Validates Redis data persistence
- `test_static_files_persist_after_web_restart`: Validates static file persistence

#### Property 4: Automatic Container Restart

**Statement**: *For any* container with a restart policy, when the container fails or stops, Docker should automatically restart it.

**Tests**:
- `test_container_auto_restarts_after_stop`: Validates restart after graceful stop
- `test_celery_worker_auto_restarts`: Validates restart after crash/kill

## Prerequisites

### System Requirements

1. **Docker**: Version 20.10 or higher
   ```bash
   docker --version
   ```

2. **Docker Compose**: Version 2.0 or higher
   ```bash
   docker compose version
   ```

3. **Python**: Version 3.9 or higher
   ```bash
   python --version
   ```

4. **Available Ports**: Ports 80 and 443 must be free
   ```bash
   # Check if ports are in use
   lsof -i :80
   lsof -i :443
   ```

5. **System Resources**: 
   - At least 4GB RAM available
   - At least 10GB disk space
   - CPU with 2+ cores recommended

### Environment Setup

1. **Create environment files**:
   ```bash
   # Copy example files
   cp .env.prod.example .env.prod
   cp .env.prod.db.example .env.prod.db
   ```

2. **Configure test values** in `.env.prod`:
   ```bash
   SECRET_KEY=test-secret-key-for-integration-tests
   DEBUG=False
   ALLOWED_HOSTS=localhost,127.0.0.1
   DB_NAME=insurance_broker_prod
   DB_USER=postgres
   DB_PASSWORD=test_password_12345
   # ... (see .env.prod for complete configuration)
   ```

3. **Configure database values** in `.env.prod.db`:
   ```bash
   POSTGRES_DB=insurance_broker_prod
   POSTGRES_USER=postgres
   POSTGRES_PASSWORD=test_password_12345
   ```

## Running the Tests

### Method 1: Using the Test Runner Script (Recommended)

The easiest way to run the tests:

```bash
./tests/run_integration_tests.sh
```

This script will:
- Check Docker is running
- Verify environment files exist
- Clean up any existing test containers
- Run all integration tests
- Display results with color-coded output

### Method 2: Using Python Directly

Run all tests:
```bash
python tests/test_docker_integration.py
```

Run with verbose output:
```bash
python tests/test_docker_integration.py -v
```

### Method 3: Using pytest (if installed)

Run all tests:
```bash
python -m pytest tests/test_docker_integration.py -v
```

Run specific test class:
```bash
python -m pytest tests/test_docker_integration.py::TestDataPersistence -v
```

Run specific test method:
```bash
python -m pytest tests/test_docker_integration.py::TestDataPersistence::test_postgres_data_persists_after_restart -v
```

### Method 4: Validate Test Structure (No Docker Required)

To validate the test file structure without running Docker:

```bash
python tests/validate_tests.py
```

This is useful for:
- CI/CD environments without Docker
- Quick syntax validation
- Verifying test coverage

## Test Execution Flow

The tests run in the following order:

1. **TestDockerContainerStartup**: Starts all containers and verifies they're running
2. **TestDatabaseConnection**: Tests PostgreSQL connectivity and migrations
3. **TestCeleryRedisConnection**: Tests Celery and Redis connectivity
4. **TestNginxAccess**: Tests Nginx reverse proxy functionality
5. **TestStaticFiles**: Tests static file collection and serving
6. **TestDataPersistence**: Tests data persistence (Property 1)
7. **TestAutoRestart**: Tests automatic restart (Property 4)
8. **TestDockerCleanup**: Cleans up all containers and volumes

## Expected Test Duration

- **Full test suite**: 5-10 minutes
- **Container startup tests**: 1-2 minutes
- **Connectivity tests**: 1-2 minutes
- **Persistence tests**: 2-3 minutes (includes container restarts)
- **Auto-restart tests**: 2-3 minutes (includes simulated failures)

## Understanding Test Output

### Successful Test Run

```
test_all_containers_start ... ok
test_web_connects_to_postgresql ... ok
test_celery_connects_to_redis ... ok
test_nginx_is_accessible ... ok
test_postgres_data_persists_after_restart ... ok
test_container_auto_restarts_after_stop ... ok

----------------------------------------------------------------------
Ran 15 tests in 487.23s

OK
```

### Failed Test Example

```
test_postgres_data_persists_after_restart ... FAIL

======================================================================
FAIL: test_postgres_data_persists_after_restart
----------------------------------------------------------------------
AssertionError: Data was not persisted after container restart
```

## Troubleshooting

### Docker Not Running

**Error**: `Cannot connect to the Docker daemon`

**Solution**:
```bash
# Start Docker Desktop (macOS/Windows)
# Or start Docker service (Linux)
sudo systemctl start docker
```

### Port Already in Use

**Error**: `Bind for 0.0.0.0:80 failed: port is already allocated`

**Solution**:
```bash
# Find process using port 80
lsof -i :80

# Stop the process or stop existing containers
docker compose -f docker-compose.prod.yml down
```

### Environment Files Missing

**Error**: `FileNotFoundError: .env.prod`

**Solution**:
```bash
cp .env.prod.example .env.prod
cp .env.prod.db.example .env.prod.db
# Edit files with appropriate values
```

### Container Health Check Timeout

**Error**: `Service did not become healthy`

**Solution**:
- Check Docker resource limits (increase memory/CPU)
- Check container logs: `docker compose -f docker-compose.prod.yml logs web`
- Increase timeout values in test code
- Ensure no other services are consuming resources

### Database Connection Errors

**Error**: `Database connection check failed`

**Solution**:
```bash
# Check database container logs
docker compose -f docker-compose.prod.yml logs db

# Verify environment variables match
cat .env.prod | grep DB_
cat .env.prod.db | grep POSTGRES_

# Ensure passwords match between files
```

### Permission Denied Errors

**Error**: `Permission denied while trying to connect to Docker daemon`

**Solution** (Linux):
```bash
# Add user to docker group
sudo usermod -aG docker $USER

# Log out and back in, or run:
newgrp docker
```

### Tests Hang or Timeout

**Possible causes**:
- Insufficient system resources
- Network connectivity issues
- Container build failures

**Solutions**:
```bash
# Check Docker resource usage
docker stats

# Check container logs
docker compose -f docker-compose.prod.yml logs

# Rebuild containers
docker compose -f docker-compose.prod.yml build --no-cache

# Clean up and restart
docker compose -f docker-compose.prod.yml down -v
docker system prune -a
```

## Manual Testing

If automated tests fail, you can manually test components:

### 1. Start Containers

```bash
docker compose -f docker-compose.prod.yml up -d
```

### 2. Check Container Status

```bash
docker compose -f docker-compose.prod.yml ps
```

### 3. Check Container Logs

```bash
# All containers
docker compose -f docker-compose.prod.yml logs

# Specific container
docker compose -f docker-compose.prod.yml logs web
docker compose -f docker-compose.prod.yml logs db
```

### 4. Test Database Connection

```bash
docker compose -f docker-compose.prod.yml exec web python manage.py check --database default
```

### 5. Test Celery Connection

```bash
docker compose -f docker-compose.prod.yml exec celery_worker celery -A config inspect ping
```

### 6. Test Nginx

```bash
curl http://localhost:80/admin/login/
```

### 7. Test Static Files

```bash
docker compose -f docker-compose.prod.yml exec web python manage.py collectstatic --noinput
curl http://localhost:80/static/admin/css/base.css
```

### 8. Clean Up

```bash
docker compose -f docker-compose.prod.yml down -v
```

## CI/CD Integration

### GitHub Actions Example

```yaml
name: Docker Integration Tests

on:
  push:
    branches: [ main, develop ]
  pull_request:
    branches: [ main ]

jobs:
  integration-tests:
    runs-on: ubuntu-latest
    
    steps:
    - uses: actions/checkout@v3
    
    - name: Set up Python
      uses: actions/setup-python@v4
      with:
        python-version: '3.9'
    
    - name: Create environment files
      run: |
        cp .env.prod.example .env.prod
        cp .env.prod.db.example .env.prod.db
        # Update with test values
        sed -i 's/your-secret-key-here/test-secret-key/' .env.prod
        sed -i 's/your-strong-database-password-here/test_password/' .env.prod
        sed -i 's/your-strong-database-password-here/test_password/' .env.prod.db
    
    - name: Run integration tests
      run: |
        python tests/test_docker_integration.py
    
    - name: Clean up
      if: always()
      run: |
        docker compose -f docker-compose.prod.yml down -v
```

## Best Practices

1. **Always clean up after tests**: The test suite includes automatic cleanup, but if tests are interrupted, manually run:
   ```bash
   docker compose -f docker-compose.prod.yml -p insurance_broker_test down -v
   ```

2. **Use test-specific environment files**: Never use production credentials in test environment files.

3. **Monitor resource usage**: Integration tests can be resource-intensive. Monitor with:
   ```bash
   docker stats
   ```

4. **Run tests in isolation**: Don't run tests on a system with production containers running.

5. **Check logs on failure**: Always check container logs when tests fail:
   ```bash
   docker compose -f docker-compose.prod.yml logs
   ```

## Contributing

When adding new integration tests:

1. Follow the existing test structure and naming conventions
2. Add proper docstrings with requirement and property references
3. Ensure tests clean up after themselves
4. Update this documentation with new test information
5. Validate tests pass locally before committing

## Additional Resources

- [Docker Documentation](https://docs.docker.com/)
- [Docker Compose Documentation](https://docs.docker.com/compose/)
- [Python unittest Documentation](https://docs.python.org/3/library/unittest.html)
- [Project Deployment Guide](docs/DEPLOYMENT.md)
- [Docker Development Guide](DOCKER_DEV_GUIDE.md)
