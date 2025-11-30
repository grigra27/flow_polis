# Logging and Monitoring Configuration Summary

This document summarizes the logging and monitoring configuration implemented for the Insurance Broker Docker deployment.

## ✅ Implemented Features

### 1. Docker Logging Driver Configuration

All services in `docker-compose.prod.yml` are configured with the `json-file` logging driver and automatic log rotation:

```yaml
logging:
  driver: "json-file"
  options:
    max-size: "10m"      # Maximum size per log file
    max-file: "3"        # Number of rotated files to keep
    tag: "{{.Name}}"     # Container name tag
```

**Services configured:**
- ✅ db (PostgreSQL)
- ✅ redis
- ✅ web (Django + Gunicorn)
- ✅ celery_worker
- ✅ celery_beat
- ✅ nginx
- ✅ certbot

**Benefits:**
- Automatic log rotation prevents disk space issues
- Each container stores maximum ~30MB of logs (3 files × 10MB)
- Logs are tagged with container names for easy identification
- No manual log cleanup required

### 2. Health Checks

All critical services already have health checks configured in `docker-compose.prod.yml`:

**PostgreSQL (db):**
```yaml
healthcheck:
  test: ["CMD-SHELL", "pg_isready -U postgres"]
  interval: 10s
  timeout: 5s
  retries: 5
```

**Redis:**
```yaml
healthcheck:
  test: ["CMD", "redis-cli", "ping"]
  interval: 10s
  timeout: 5s
  retries: 5
```

**Web (Django):**
```yaml
healthcheck:
  test: ["CMD", "curl", "-f", "http://localhost:8000/admin/login/"]
  interval: 30s
  timeout: 10s
  retries: 3
  start_period: 40s
```

**Celery Worker:**
```yaml
healthcheck:
  test: ["CMD-SHELL", "celery -A config inspect ping"]
  interval: 30s
  timeout: 10s
  retries: 3
  start_period: 30s
```

**Nginx:**
```yaml
healthcheck:
  test: ["CMD", "wget", "--quiet", "--tries=1", "--spider", "http://localhost/"]
  interval: 30s
  timeout: 10s
  retries: 3
```

### 3. Log Viewing Script

**File:** `scripts/view-logs.sh`

A user-friendly script for viewing Docker container logs with multiple options:

**Features:**
- View logs from all services or specific services
- Follow logs in real-time (`-f` flag)
- Limit number of lines (`-n` flag)
- Show timestamps (`-t` flag)
- Support for both dev and prod environments

**Usage examples:**
```bash
./scripts/view-logs.sh                    # All services, last 100 lines
./scripts/view-logs.sh web -f             # Follow web logs
./scripts/view-logs.sh celery_worker -n 50  # Last 50 lines
./scripts/view-logs.sh all -f -t          # Follow all with timestamps
```

### 4. Health Monitoring Script

**File:** `scripts/monitor-health.sh`

Automated health monitoring script for all Docker containers:

**Features:**
- Checks health status of all services
- Monitors disk usage (alerts if > 80%)
- Shows Docker disk usage statistics
- Optional email alerts for failures
- Exit codes for automation (0 = healthy, 1 = issues)
- Colored output for easy reading

**Usage examples:**
```bash
./scripts/monitor-health.sh                              # Manual check
./scripts/monitor-health.sh --alert-email admin@example.com  # With alerts
```

**Can be automated via cron:**
```bash
*/5 * * * * cd /path/to/app && ./scripts/monitor-health.sh --alert-email admin@example.com
```

### 5. Comprehensive Documentation

**Main documentation:** `docs/MONITORING.md` (14KB)

Complete guide covering:
- Log viewing commands (Docker Compose and Docker)
- Logging configuration details
- Health check information
- Resource monitoring (CPU, memory, disk)
- Troubleshooting common issues
- Production monitoring strategies
- Advanced monitoring options (Prometheus, Grafana, ELK)

**Quick reference:** `MONITORING_QUICK_REFERENCE.md` (3.2KB)

Cheat sheet with most common commands:
- Log viewing
- Container status
- Health checks
- Resource monitoring
- Service management
- Troubleshooting
- Cleanup commands

### 6. Updated Documentation

**README.md:**
- Added "Мониторинг и логирование" section
- Quick examples for common tasks
- Links to detailed documentation

**scripts/README.md:**
- Added documentation for `view-logs.sh`
- Added documentation for `monitor-health.sh`
- Usage examples and options

## 📊 Monitoring Capabilities

### Real-time Monitoring

```bash
# Container status
docker compose -f docker-compose.prod.yml ps

# Resource usage
docker stats

# Live logs
./scripts/view-logs.sh web -f
```

### Health Checks

```bash
# Automated health check
./scripts/monitor-health.sh

# Manual health check
docker inspect --format='{{.State.Health.Status}}' insurance_broker_web
```

### Log Analysis

```bash
# View logs
./scripts/view-logs.sh web -n 100

# Search for errors
docker compose -f docker-compose.prod.yml logs web | grep -i error

# Logs from specific time
docker logs --since=10m insurance_broker_web
```

## 🔧 Configuration Details

### Log Rotation Settings

| Parameter | Value | Description |
|-----------|-------|-------------|
| Driver | json-file | Docker's default JSON logging driver |
| Max Size | 10MB | Maximum size of each log file |
| Max Files | 3 | Number of rotated files to keep |
| Total Storage | ~30MB | Maximum storage per container |

### Health Check Intervals

| Service | Interval | Timeout | Retries | Start Period |
|---------|----------|---------|---------|--------------|
| PostgreSQL | 10s | 5s | 5 | - |
| Redis | 10s | 5s | 5 | - |
| Web | 30s | 10s | 3 | 40s |
| Celery Worker | 30s | 10s | 3 | 30s |
| Nginx | 30s | 10s | 3 | - |

## 📝 Requirements Validation

This implementation satisfies the following requirements from the design document:

### Requirement 8.1 ✅
**"КОГДА Приложение логирует сообщение ТО Docker ДОЛЖЕН захватить его и сделать доступным через docker logs"**

- All services configured with json-file logging driver
- Logs accessible via `docker logs` and `docker compose logs`
- Convenient `view-logs.sh` script for easy access

### Requirement 8.2 ✅
**"КОГДА происходит ошибка ТО Приложение ДОЛЖНО залогировать её с полным traceback"**

- Django configured to log errors with full traceback
- Logs captured by Docker logging driver
- Accessible through standard Docker logging commands

### Requirement 8.5 ✅
**"КОГДА логи накапливаются ТО система ДОЛЖНА ротировать их для предотвращения переполнения диска"**

- Automatic log rotation configured (max-size: 10MB, max-file: 3)
- Total storage limited to ~30MB per container
- No manual intervention required

## 🚀 Usage Guide

### For Developers

```bash
# View application logs during development
./scripts/view-logs.sh web -f

# Check if all services are healthy
./scripts/monitor-health.sh

# Debug specific service
./scripts/view-logs.sh celery_worker -n 100 -t
```

### For Operations

```bash
# Daily health check
./scripts/monitor-health.sh --alert-email ops@example.com

# Monitor resource usage
docker stats

# Check disk space
docker system df -v

# View error logs
docker compose -f docker-compose.prod.yml logs | grep -i error
```

### For Automation

```bash
# Add to crontab for automated monitoring
*/5 * * * * cd /path/to/app && ./scripts/monitor-health.sh --alert-email admin@example.com

# Or use systemd timer for more control
```

## 📚 Documentation Files

| File | Size | Description |
|------|------|-------------|
| `docs/MONITORING.md` | 14KB | Complete monitoring and logging guide |
| `MONITORING_QUICK_REFERENCE.md` | 3.2KB | Quick reference cheat sheet |
| `scripts/view-logs.sh` | 3.1KB | Log viewing script |
| `scripts/monitor-health.sh` | 5.0KB | Health monitoring script |
| `LOGGING_CONFIGURATION_SUMMARY.md` | This file | Implementation summary |

## ✨ Benefits

1. **Automatic Log Management:** No manual log cleanup needed
2. **Disk Space Protection:** Logs limited to ~30MB per container
3. **Easy Troubleshooting:** Convenient scripts for log viewing
4. **Proactive Monitoring:** Health check script can be automated
5. **Comprehensive Documentation:** Complete guides for all scenarios
6. **Production Ready:** All configurations follow best practices

## 🔗 Related Documentation

- [docs/MONITORING.md](docs/MONITORING.md) - Full monitoring guide
- [MONITORING_QUICK_REFERENCE.md](MONITORING_QUICK_REFERENCE.md) - Quick reference
- [scripts/README.md](scripts/README.md) - Scripts documentation
- [docker-compose.prod.yml](docker-compose.prod.yml) - Production configuration

## 🎯 Next Steps

For production deployment:

1. **Test the configuration:**
   ```bash
   docker compose -f docker-compose.prod.yml config
   ```

2. **Start services and verify logging:**
   ```bash
   docker compose -f docker-compose.prod.yml up -d
   ./scripts/view-logs.sh all
   ```

3. **Verify health checks:**
   ```bash
   ./scripts/monitor-health.sh
   ```

4. **Set up automated monitoring:**
   ```bash
   # Add to crontab
   crontab -e
   # Add line:
   # */5 * * * * cd /path/to/app && ./scripts/monitor-health.sh --alert-email admin@example.com
   ```

5. **Optional: Set up advanced monitoring:**
   - Prometheus + Grafana for metrics
   - Sentry for error tracking
   - ELK Stack for centralized logging
   - Uptime monitoring service

---

**Implementation Date:** November 25, 2024
**Task:** 13. Настроить логирование и мониторинг
**Status:** ✅ Complete
