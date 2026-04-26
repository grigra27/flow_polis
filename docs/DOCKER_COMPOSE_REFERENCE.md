# Docker Compose Production Reference

## Overview

This document provides a reference for the `docker-compose.prod.yml` configuration.

## Services

### 1. db (PostgreSQL)
- **Image**: `postgres:15-alpine`
- **Purpose**: Main application database
- **Volume**: `postgres_data:/var/lib/postgresql/data`
- **Network**: `backend`
- **Restart**: `unless-stopped`
- **Health Check**: PostgreSQL readiness check every 10s

### 2. redis
- **Image**: `redis:7-alpine`
- **Purpose**: Message broker for Celery
- **Volume**: `redis_data:/data`
- **Network**: `backend`
- **Restart**: `unless-stopped`
- **Health Check**: Redis ping every 10s
- **Command**: `redis-server --appendonly yes` (enables persistence)

### 3. web (Django + Gunicorn)
- **Build**: From local Dockerfile
- **Purpose**: Main Django application
- **Command**: `gunicorn config.wsgi:application --bind 0.0.0.0:8000 --workers 3 --timeout 120`
- **Volumes**:
  - `static_volume:/app/staticfiles`
  - `media_volume:/app/media`
- **Networks**: `backend`, `frontend`
- **Restart**: `unless-stopped`
- **Dependencies**: db (healthy), redis (healthy)
- **Health Check**: HTTP check to admin login page every 30s

### 4. celery_worker
- **Build**: From local Dockerfile
- **Purpose**: Execute background tasks asynchronously
- **Command**: `celery -A config worker -l info`
- **Volume**: `media_volume:/app/media`
- **Network**: `backend`
- **Restart**: `unless-stopped`
- **Dependencies**: db (healthy), redis (healthy)
- **Health Check**: Celery inspect ping every 30s

### 5. celery_beat
- **Build**: From local Dockerfile
- **Purpose**: Schedule periodic tasks
- **Command**: `celery -A config beat -l info --scheduler django_celery_beat.schedulers:DatabaseScheduler`
- **Volume**: `media_volume:/app/media`
- **Network**: `backend`
- **Restart**: `unless-stopped`
- **Dependencies**: db (healthy), redis (healthy)

### 6. nginx
- **Image**: `nginx:alpine`
- **Purpose**: Reverse proxy, SSL termination, static file serving
- **Ports**:
  - `80:80` (HTTP)
  - `443:443` (HTTPS)
- **Volumes**:
  - `./nginx:/etc/nginx/conf.d:ro` (configuration)
  - `./certbot/conf:/etc/letsencrypt:ro` (SSL certificates)
  - `./certbot/www:/var/www/certbot:ro` (ACME challenge)
  - `static_volume:/app/staticfiles:ro` (static files)
  - `media_volume:/app/media:ro` (media files)
- **Network**: `frontend`
- **Restart**: `unless-stopped`
- **Dependencies**: web
- **Health Check**: HTTP check every 30s

## Volumes

All volumes use the `local` driver for data persistence:

- **postgres_data**: PostgreSQL database files
- **redis_data**: Redis persistence files
- **static_volume**: Django static files (CSS, JS, images)
- **media_volume**: User-uploaded files

## Networks

- **backend**: Internal network for database and cache services
  - Services: db, redis, web, celery_worker, celery_beat
  - Isolated from external access

- **frontend**: Network for web-facing services
  - Services: web, nginx
  - Nginx exposes ports 80 and 443 to the host

## Restart Policies

All services use `restart: unless-stopped`:
- Containers restart automatically if they crash
- Containers start automatically on system boot
- Containers only stop when explicitly stopped with `docker compose down`

## Health Checks

Health checks ensure services are ready before dependent services start:

| Service | Check Type | Interval | Timeout | Retries | Start Period |
|---------|-----------|----------|---------|---------|--------------|
| db | pg_isready | 10s | 5s | 5 | - |
| redis | redis-cli ping | 10s | 5s | 5 | - |
| web | HTTP curl | 30s | 10s | 3 | 40s |
| celery_worker | celery inspect | 30s | 10s | 3 | 30s |
| nginx | HTTP wget | 30s | 10s | 3 | - |

## Environment Files

- **.env.prod**: Django and application configuration
- **.env.prod.db**: PostgreSQL configuration

See `.env.prod.example` and `.env.prod.db.example` for required variables.

## Common Commands

```bash
# Start all services
docker compose -f docker-compose.prod.yml up -d

# View logs
docker compose -f docker-compose.prod.yml logs -f [service_name]

# Stop all services
docker compose -f docker-compose.prod.yml down

# Restart a specific service
docker compose -f docker-compose.prod.yml restart [service_name]

# Execute command in a service
docker compose -f docker-compose.prod.yml exec [service_name] [command]

# View service status
docker compose -f docker-compose.prod.yml ps

# Remove volumes (WARNING: deletes data)
docker compose -f docker-compose.prod.yml down -v
```

## Requirements Validation

This configuration satisfies the following requirements:

- ✅ 1.2: All necessary services running (Django, PostgreSQL, Redis, Nginx, Celery)
- ✅ 1.3: Services connected through internal Docker network
- ✅ 6.1: PostgreSQL data persists through container restarts
- ✅ 6.2: Media files persist through container restarts
- ✅ 6.3: Static files persist through container restarts
- ✅ 6.4: Docker volumes mounted to appropriate container paths
- ✅ 7.1: Celery worker connects to Redis broker
- ✅ 7.2: Celery beat schedules periodic tasks
- ✅ 7.4: Celery worker restarts automatically on failure
- ✅ 8.3: All containers restart automatically on failure

## Security Considerations

1. **Network Isolation**: Database and Redis are only accessible within the backend network
2. **Read-Only Mounts**: Nginx configuration and SSL certificates mounted as read-only
3. **No Exposed Ports**: Only Nginx exposes ports to the host (80, 443)
4. **Environment Files**: Sensitive data stored in .env files (excluded from git)
5. **Health Checks**: Ensure services are functioning correctly before accepting traffic

## Troubleshooting

### Service won't start
```bash
# Check logs
docker compose -f docker-compose.prod.yml logs [service_name]

# Check service status
docker compose -f docker-compose.prod.yml ps
```

### Database connection issues
```bash
# Verify database is healthy
docker compose -f docker-compose.prod.yml ps db

# Check database logs
docker compose -f docker-compose.prod.yml logs db

# Test connection from web container
docker compose -f docker-compose.prod.yml exec web python manage.py dbshell
```

### Celery not processing tasks
```bash
# Check worker logs
docker compose -f docker-compose.prod.yml logs celery_worker

# Check Redis connection
docker compose -f docker-compose.prod.yml exec redis redis-cli ping

# Inspect Celery
docker compose -f docker-compose.prod.yml exec celery_worker celery -A config inspect active
```

### Static files not loading
```bash
# Collect static files
docker compose -f docker-compose.prod.yml exec web python manage.py collectstatic --noinput

# Check nginx logs
docker compose -f docker-compose.prod.yml logs nginx

# Verify volume mount
docker compose -f docker-compose.prod.yml exec nginx ls -la /app/staticfiles
```
