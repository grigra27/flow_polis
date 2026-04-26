# Docker Development Environment Guide

This guide explains how to use Docker for local development of the Insurance Broker System.

## Overview

The development Docker environment provides:

- **Hot Reload**: Source code changes are reflected immediately without rebuilding
- **Django Development Server**: Uses `runserver` for better debugging
- **Debug Toolbar**: Django Debug Toolbar is enabled for performance analysis
- **SQLite Database**: Lightweight database for quick development (PostgreSQL optional)
- **Direct Port Access**: All services accessible on localhost
- **Console Email**: Emails printed to console instead of sending

## Prerequisites

- Docker Desktop (or Docker Engine + Docker Compose)
- Git

## Quick Start

### 1. Clone and Setup

```bash
# Clone the repository (if not already done)
git clone <repository-url>
cd insurance_broker

# Copy environment file
cp .env.dev.example .env
```

### 2. Start Development Environment

```bash
# Build and start all services
docker compose up --build

# Or run in background
docker compose up -d --build
```

The application will be available at: http://localhost:8000

### 3. Initialize Database

In a new terminal:

```bash
# Run migrations
docker compose exec web python manage.py migrate

# Load initial data
docker compose exec web python manage.py loaddata fixtures/initial_data.json

# Create superuser
docker compose exec web python create_superuser.py
```

Login credentials: `admin` / `admin`

### 4. Access the Application

Open your browser and navigate to:
- **Application**: http://localhost:8000
- **Admin Panel**: http://localhost:8000/admin

## Services

The development environment includes:

| Service | Port | Description |
|---------|------|-------------|
| web | 8000 | Django development server |
| redis | 6379 | Redis for Celery tasks |
| celery_worker | - | Background task worker |
| celery_beat | - | Periodic task scheduler |

## Common Commands

### Viewing Logs

```bash
# All services
docker compose logs -f

# Specific service
docker compose logs -f web
docker compose logs -f celery_worker
```

### Django Management Commands

```bash
# Run any Django management command
docker compose exec web python manage.py <command>

# Examples:
docker compose exec web python manage.py shell
docker compose exec web python manage.py makemigrations
docker compose exec web python manage.py migrate
docker compose exec web python manage.py createsuperuser
docker compose exec web python manage.py test
```

### Stopping Services

```bash
# Stop all services
docker compose down

# Stop and remove volumes (clean slate)
docker compose down -v
```

### Rebuilding After Changes

```bash
# Rebuild after changing requirements.txt or Dockerfile.dev
docker compose up --build

# Force rebuild
docker compose build --no-cache
docker compose up
```

## Development Workflow

### Making Code Changes

1. Edit files in your local directory
2. Changes are automatically reflected in the container (hot reload)
3. Django development server will restart automatically
4. Refresh your browser to see changes

### Adding Python Dependencies

1. Add package to `requirements.txt`
2. Rebuild the container:
   ```bash
   docker compose up --build
   ```

### Database Changes

1. Modify models in `apps/*/models.py`
2. Create migrations:
   ```bash
   docker compose exec web python manage.py makemigrations
   ```
3. Apply migrations:
   ```bash
   docker compose exec web python manage.py migrate
   ```

### Running Tests

```bash
# Run all tests
docker compose exec web python manage.py test

# Run specific app tests
docker compose exec web python manage.py test apps.policies

# Run with verbose output
docker compose exec web python manage.py test --verbosity=2
```

## Debugging

### Using Python Debugger (pdb)

To use `pdb` or `ipdb` for debugging:

1. Add breakpoint in your code:
   ```python
   import pdb; pdb.set_trace()
   ```

2. Run web service in interactive mode:
   ```bash
   docker compose run --rm --service-ports web
   ```

3. Access the breakpoint in the terminal

### Django Debug Toolbar

The Debug Toolbar is automatically enabled in development mode:

1. Visit any page in your browser
2. Look for the Debug Toolbar on the right side
3. Click to expand and view:
   - SQL queries
   - Request/Response data
   - Template rendering
   - Cache usage
   - Signals

### Viewing Email Output

Emails are printed to the console in development:

```bash
# Watch web logs to see emails
docker compose logs -f web
```

## Troubleshooting

### Port Already in Use

If port 8000 is already in use:

```bash
# Find and stop the process using port 8000
lsof -ti:8000 | xargs kill -9

# Or change the port in docker-compose.yml
ports:
  - "8001:8000"  # Use 8001 instead
```

### Container Won't Start

```bash
# Check container status
docker compose ps

# View detailed logs
docker compose logs web

# Rebuild from scratch
docker compose down -v
docker compose up --build
```

### Database Issues

```bash
# Reset database (WARNING: deletes all data)
docker compose down -v
docker compose up -d
docker compose exec web python manage.py migrate
docker compose exec web python manage.py loaddata fixtures/initial_data.json
```

### Permission Issues

If you encounter permission issues with mounted volumes:

```bash
# On Linux, you may need to adjust ownership
sudo chown -R $USER:$USER .
```

## Differences from Production

| Feature | Development | Production |
|---------|-------------|------------|
| Web Server | Django runserver | Gunicorn |
| Database | SQLite | PostgreSQL |
| Debug Mode | Enabled | Disabled |
| Email | Console | SMTP |
| Static Files | Served by Django | Served by Nginx |
| SSL/HTTPS | Not configured | Let's Encrypt |
| Volumes | Source code mounted | Only data volumes |
| Restart Policy | None | unless-stopped |

## Switching to PostgreSQL (Optional)

If you want to use PostgreSQL in development:

1. Add PostgreSQL service to `docker-compose.dev.yml`:
   ```yaml
   db:
     image: postgres:15-alpine
     environment:
       POSTGRES_DB: insurance_broker_dev
       POSTGRES_USER: postgres
       POSTGRES_PASSWORD: postgres
     ports:
       - "5432:5432"
     volumes:
       - postgres_dev_data:/var/lib/postgresql/data
   ```

2. Update `.env`:
   ```env
   DB_NAME=insurance_broker_dev
   DB_USER=postgres
   DB_PASSWORD=postgres
   DB_HOST=db
   DB_PORT=5432
   ```

3. Rebuild and migrate:
   ```bash
   docker compose up --build
   docker compose exec web python manage.py migrate
   ```

## Tips and Best Practices

1. **Keep containers running**: Leave `docker compose up` running in a terminal for faster development
2. **Use logs**: Monitor logs to catch errors early
3. **Commit often**: Docker makes it easy to reset, so commit working code frequently
4. **Clean up**: Periodically run `docker system prune` to free up disk space
5. **Environment files**: Never commit `.env` files with real credentials

## Getting Help

- Check logs: `docker compose logs -f`
- Inspect container: `docker compose exec web bash`
- View running processes: `docker compose ps`
- Check resource usage: `docker stats`

## Next Steps

- Read the main [README.md](README.md) for application features
- Check [docs/](docs/) for detailed documentation
- Review [DOCKER_COMPOSE_REFERENCE.md](DOCKER_COMPOSE_REFERENCE.md) for production deployment
