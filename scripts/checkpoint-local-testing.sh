#!/bin/bash
# Checkpoint script for local Docker production testing
# This script verifies that docker-compose.prod.yml works correctly locally
# before deploying to production

set -e  # Exit on error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Project name for isolation
PROJECT_NAME="insurance_broker_test"
COMPOSE_FILE="docker-compose.prod.yml"

echo "=========================================="
echo "Docker Production Setup - Local Testing"
echo "=========================================="
echo ""

# Function to print status
print_status() {
    if [ $1 -eq 0 ]; then
        echo -e "${GREEN}✓${NC} $2"
    else
        echo -e "${RED}✗${NC} $2"
        return 1
    fi
}

# Function to print info
print_info() {
    echo -e "${YELLOW}ℹ${NC} $1"
}

# Check if Docker is installed
echo "1. Checking Docker installation..."
if ! command -v docker &> /dev/null; then
    echo -e "${RED}✗${NC} Docker is not installed"
    echo "Please install Docker Desktop from https://www.docker.com/products/docker-desktop"
    exit 1
fi
print_status 0 "Docker is installed"

# Check if Docker is running
echo ""
echo "2. Checking if Docker is running..."
if ! docker info &> /dev/null; then
    echo -e "${RED}✗${NC} Docker is not running"
    echo "Please start Docker Desktop"
    exit 1
fi
print_status 0 "Docker is running"

# Check if environment files exist
echo ""
echo "3. Checking environment files..."
if [ ! -f ".env.prod" ]; then
    echo -e "${RED}✗${NC} .env.prod not found"
    echo "Please create .env.prod from .env.prod.example"
    exit 1
fi
print_status 0 ".env.prod exists"

if [ ! -f ".env.prod.db" ]; then
    echo -e "${RED}✗${NC} .env.prod.db not found"
    echo "Please create .env.prod.db from .env.prod.db.example"
    exit 1
fi
print_status 0 ".env.prod.db exists"

# Validate docker-compose.yml syntax
echo ""
echo "4. Validating docker-compose.prod.yml syntax..."
if docker compose -f $COMPOSE_FILE config --quiet; then
    print_status 0 "docker-compose.prod.yml syntax is valid"
else
    print_status 1 "docker-compose.prod.yml has syntax errors"
    exit 1
fi

# Start Docker Compose services
echo ""
echo "5. Starting Docker Compose services..."
print_info "This may take a few minutes on first run (downloading images)..."
docker compose -f $COMPOSE_FILE -p $PROJECT_NAME up -d

# Wait for services to initialize
echo ""
echo "6. Waiting for services to initialize..."
sleep 15

# Check all services are running
echo ""
echo "7. Checking service status..."
SERVICES=("db" "redis" "web" "celery_worker" "celery_beat" "nginx")
ALL_RUNNING=true

for service in "${SERVICES[@]}"; do
    STATUS=$(docker compose -f $COMPOSE_FILE -p $PROJECT_NAME ps --format json $service | grep -o '"State":"[^"]*"' | cut -d'"' -f4 || echo "not_found")
    if [ "$STATUS" = "running" ]; then
        print_status 0 "$service is running"
    else
        print_status 1 "$service is not running (status: $STATUS)"
        ALL_RUNNING=false
    fi
done

if [ "$ALL_RUNNING" = false ]; then
    echo ""
    echo -e "${RED}Some services failed to start. Showing logs:${NC}"
    docker compose -f $COMPOSE_FILE -p $PROJECT_NAME logs --tail=50
    exit 1
fi

# Wait for health checks
echo ""
echo "8. Waiting for health checks..."
print_info "Waiting for services to become healthy (up to 2 minutes)..."
sleep 30

# Check database connection
echo ""
echo "9. Testing database connection..."
if docker compose -f $COMPOSE_FILE -p $PROJECT_NAME exec -T web python manage.py check --database default &> /dev/null; then
    print_status 0 "Web can connect to PostgreSQL"
else
    print_status 1 "Web cannot connect to PostgreSQL"
    docker compose -f $COMPOSE_FILE -p $PROJECT_NAME logs web
    exit 1
fi

# Run migrations
echo ""
echo "10. Running database migrations..."
if docker compose -f $COMPOSE_FILE -p $PROJECT_NAME exec -T web python manage.py migrate --noinput; then
    print_status 0 "Database migrations completed"
else
    print_status 1 "Database migrations failed"
    exit 1
fi

# Collect static files
echo ""
echo "11. Collecting static files..."
if docker compose -f $COMPOSE_FILE -p $PROJECT_NAME exec -T web python manage.py collectstatic --noinput; then
    print_status 0 "Static files collected"
else
    print_status 1 "Static file collection failed"
    exit 1
fi

# Test Celery connection
echo ""
echo "12. Testing Celery worker connection to Redis..."
sleep 10  # Give Celery time to fully start
if docker compose -f $COMPOSE_FILE -p $PROJECT_NAME exec -T celery_worker celery -A config inspect ping &> /dev/null; then
    print_status 0 "Celery worker connected to Redis"
else
    print_status 1 "Celery worker cannot connect to Redis"
    docker compose -f $COMPOSE_FILE -p $PROJECT_NAME logs celery_worker
    exit 1
fi

# Test Nginx accessibility
echo ""
echo "13. Testing Nginx accessibility..."
sleep 5
HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:80/admin/login/ || echo "000")
if [ "$HTTP_CODE" = "200" ] || [ "$HTTP_CODE" = "302" ]; then
    print_status 0 "Nginx is accessible (HTTP $HTTP_CODE)"
else
    print_status 1 "Nginx is not accessible (HTTP $HTTP_CODE)"
    docker compose -f $COMPOSE_FILE -p $PROJECT_NAME logs nginx
    exit 1
fi

# Test static file serving
echo ""
echo "14. Testing static file serving through Nginx..."
HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:80/static/admin/css/base.css || echo "000")
if [ "$HTTP_CODE" = "200" ]; then
    print_status 0 "Nginx serves static files correctly"
else
    print_status 1 "Nginx cannot serve static files (HTTP $HTTP_CODE)"
    exit 1
fi

# Run integration tests
echo ""
echo "15. Running integration tests..."
print_info "This will run the full test suite..."
if python -m pytest tests/test_docker_integration.py -v; then
    print_status 0 "All integration tests passed"
else
    print_status 1 "Some integration tests failed"
    echo ""
    echo -e "${YELLOW}Note: Test failures should be investigated before deploying to production${NC}"
    exit 1
fi

# Summary
echo ""
echo "=========================================="
echo -e "${GREEN}✓ All checkpoint tests passed!${NC}"
echo "=========================================="
echo ""
echo "Your Docker production setup is working correctly locally."
echo ""
echo "Next steps:"
echo "  1. Review the running services: docker compose -f $COMPOSE_FILE -p $PROJECT_NAME ps"
echo "  2. Check logs if needed: docker compose -f $COMPOSE_FILE -p $PROJECT_NAME logs [service]"
echo "  3. Stop services: docker compose -f $COMPOSE_FILE -p $PROJECT_NAME down"
echo "  4. Clean up volumes: docker compose -f $COMPOSE_FILE -p $PROJECT_NAME down -v"
echo ""
echo "When ready, proceed to production deployment (tasks 17-22)."
echo ""
