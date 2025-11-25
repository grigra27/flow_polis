# Docker Integration Tests

This directory contains integration tests for the Docker deployment setup.

## Overview

The integration tests validate the complete Docker Compose environment including:

- Container startup and health checks
- Database connectivity (PostgreSQL)
- Celery and Redis connectivity
- Nginx reverse proxy functionality
- Static file serving
- Data persistence across container restarts
- Automatic container restart policies

## Requirements

- Docker and Docker Compose installed
- Python 3.9+ with required packages
- `.env.prod` and `.env.prod.db` files configured

## Running the Tests

### Quick Start

Run all integration tests:

```bash
python -m pytest tests/test_docker_integration.py -v
```

Or using unittest:

```bash
python tests/test_docker_integration.py
```

### Running Specific Test Classes

```bash
# Test container startup only
python -m pytest tests/test_docker_integration.py::TestDockerContainerStartup -v

# Test data persistence
python -m pytest tests/test_docker_integration.py::TestDataPersistence -v

# Test auto-restart functionality
python -m pytest tests/test_docker_integration.py::TestAutoRestart -v
```

## Test Structure

### TestDockerContainerStartup
Tests that all required Docker containers start successfully.

**Validates:** Requirements 1.2, 1.3

### TestDatabaseConnection
Tests web container connection to PostgreSQL database.

**Validates:** Requirements 1.3, 6.1

### TestCeleryRedisConnection
Tests Celery worker and beat connections to Redis.

**Validates:** Requirements 7.1, 7.3

### TestNginxAccess
Tests application accessibility through Nginx reverse proxy.

**Validates:** Requirements 1.5, 2.2

### TestStaticFiles
Tests static file collection and serving through Nginx.

**Validates:** Requirements 1.5, 2.3

### TestDataPersistence
Tests data persistence across container restarts (Property 1).

**Validates:** Requirements 6.1, 6.2, 6.3

**Property 1:** For any container with a Docker volume, when data is written to the volume and the container is restarted, the data should remain accessible and unchanged.

### TestAutoRestart
Tests automatic restart of failed containers (Property 4).

**Validates:** Requirements 7.4, 8.3

**Property 4:** For any container with a restart policy, when the container fails or stops, Docker should automatically restart it.

### TestLogging
Tests logging functionality and Docker log capture.

**Validates:** Requirements 8.1, 8.2

Tests include:
- Docker captures application logs and makes them accessible via `docker logs`
- Application logs errors with full traceback information
- Celery worker logs are captured by Docker
- Nginx access and error logs are captured by Docker

## Important Notes

1. **Test Environment**: Tests use `.env.prod` and `.env.prod.db` files. Make sure these are configured before running tests.

2. **Docker Resources**: Tests will start the full Docker Compose stack. Ensure you have sufficient resources (CPU, memory, disk space).

3. **Port Conflicts**: Tests expect ports 80 and 443 to be available. Stop any services using these ports before running tests.

4. **Test Duration**: Integration tests can take several minutes to complete as they involve starting containers, waiting for health checks, and testing various scenarios.

5. **Cleanup**: The test suite includes a cleanup test that runs last (TestDockerCleanup) to stop and remove all containers and volumes.

## Troubleshooting

### Tests Fail to Start Containers

- Check Docker is running: `docker ps`
- Check Docker Compose version: `docker compose version`
- Verify environment files exist: `.env.prod` and `.env.prod.db`

### Timeout Errors

- Increase timeout values in test code if your system is slow
- Check Docker resource limits
- Ensure no other services are consuming resources

### Port Already in Use

- Stop existing containers: `docker compose -f docker-compose.prod.yml down`
- Check for processes using ports 80/443: `lsof -i :80` or `lsof -i :443`

### Permission Errors

- Ensure Docker daemon is running
- Check user has permissions to run Docker commands
- On Linux, add user to docker group: `sudo usermod -aG docker $USER`

## CI/CD Integration

These tests can be integrated into CI/CD pipelines:

```yaml
# Example GitHub Actions workflow
- name: Run Docker Integration Tests
  run: |
    cp .env.prod.example .env.prod
    cp .env.prod.db.example .env.prod.db
    # Update with test values
    python tests/test_docker_integration.py
```

## Contributing

When adding new integration tests:

1. Follow the existing test structure
2. Use descriptive test names
3. Add proper docstrings with validation references
4. Clean up resources after tests
5. Update this README with new test information
