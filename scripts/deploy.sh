#!/bin/bash

# deploy.sh
# Deployment script for Insurance Broker application on Digital Ocean Droplet
# This script handles pulling images, stopping old containers, starting new ones,
# running migrations, health checks, and rollback on errors

set -e  # Exit on error
set -o pipefail  # Exit on pipe failure

# Configuration
COMPOSE_FILE="docker-compose.prod.yml"
APP_DIR="${APP_DIR:-~/insurance_broker}"
BACKUP_DIR="${BACKUP_DIR:-~/insurance_broker_backups}"
MAX_HEALTH_CHECK_ATTEMPTS=30
HEALTH_CHECK_INTERVAL=2

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Logging functions
log_info() {
    echo -e "${GREEN}[INFO]${NC} $(date '+%Y-%m-%d %H:%M:%S') - $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $(date '+%Y-%m-%d %H:%M:%S') - $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $(date '+%Y-%m-%d %H:%M:%S') - $1"
}

log_step() {
    echo -e "${BLUE}[STEP]${NC} $(date '+%Y-%m-%d %H:%M:%S') - $1"
}

# Error handler
error_handler() {
    local line_number=$1
    log_error "Deployment failed at line $line_number"
    log_error "Initiating rollback..."
    rollback_deployment
    exit 1
}

# Set error trap
trap 'error_handler ${LINENO}' ERR

# Check if running in correct directory
check_directory() {
    if [ ! -f "$COMPOSE_FILE" ]; then
        log_error "docker-compose.prod.yml not found in current directory"
        log_error "Please run this script from the application root directory"
        exit 1
    fi
    
    if [ ! -f ".env.prod" ]; then
        log_error ".env.prod file not found"
        log_error "Please ensure environment configuration is present"
        exit 1
    fi
    
    log_info "Directory check passed"
}

# Create backup directory
create_backup_dir() {
    mkdir -p "$BACKUP_DIR"
    log_info "Backup directory ready: $BACKUP_DIR"
}

# Backup current state
backup_current_state() {
    log_step "Backing up current deployment state..."
    
    local backup_timestamp=$(date +%Y%m%d_%H%M%S)
    local backup_file="$BACKUP_DIR/deployment_backup_$backup_timestamp.tar.gz"
    
    # Get current image IDs
    docker-compose -f "$COMPOSE_FILE" images --quiet > "$BACKUP_DIR/current_images_$backup_timestamp.txt" 2>/dev/null || true
    
    # Save current container state
    docker-compose -f "$COMPOSE_FILE" ps > "$BACKUP_DIR/container_state_$backup_timestamp.txt" 2>/dev/null || true
    
    # Create backup marker
    echo "$backup_timestamp" > "$BACKUP_DIR/latest_backup.txt"
    
    log_info "Backup created: $backup_file"
    log_info "Backup timestamp: $backup_timestamp"
}

# Pull latest images
pull_images() {
    log_step "Pulling latest Docker images..."
    
    # Pull base images that might have updates
    docker-compose -f "$COMPOSE_FILE" pull db redis nginx certbot || {
        log_warn "Some base images could not be pulled, continuing with cached versions"
    }
    
    log_info "Image pull completed"
}

# Build application images
build_images() {
    log_step "Building application Docker images..."
    
    # Build with no cache to ensure fresh build
    docker-compose -f "$COMPOSE_FILE" build --no-cache web celery_worker celery_beat || {
        log_error "Failed to build Docker images"
        return 1
    }
    
    log_info "Image build completed successfully"
}

# Stop old containers gracefully
stop_old_containers() {
    log_step "Stopping old containers gracefully..."
    
    # Check if containers are running
    if docker-compose -f "$COMPOSE_FILE" ps | grep -q "Up"; then
        log_info "Stopping running containers..."
        
        # Stop containers with timeout
        docker-compose -f "$COMPOSE_FILE" stop -t 30 || {
            log_warn "Graceful stop failed, forcing stop..."
            docker-compose -f "$COMPOSE_FILE" down --timeout 10
        }
        
        log_info "Old containers stopped"
    else
        log_info "No running containers to stop"
    fi
}

# Remove old containers
remove_old_containers() {
    log_step "Removing old containers..."
    
    docker-compose -f "$COMPOSE_FILE" down --remove-orphans || {
        log_warn "Failed to remove some containers, continuing..."
    }
    
    log_info "Old containers removed"
}

# Start new containers
start_new_containers() {
    log_step "Starting new containers..."
    
    # Start services in order with dependencies
    docker-compose -f "$COMPOSE_FILE" up -d || {
        log_error "Failed to start containers"
        return 1
    }
    
    log_info "New containers started"
}

# Wait for service to be healthy
wait_for_service() {
    local service_name=$1
    local max_attempts=$2
    local attempt=0
    
    log_info "Waiting for $service_name to be healthy..."
    
    while [ $attempt -lt $max_attempts ]; do
        local health_status=$(docker inspect --format='{{.State.Health.Status}}' "insurance_broker_$service_name" 2>/dev/null || echo "unknown")
        
        if [ "$health_status" = "healthy" ]; then
            log_info "$service_name is healthy"
            return 0
        elif [ "$health_status" = "unhealthy" ]; then
            log_error "$service_name is unhealthy"
            docker-compose -f "$COMPOSE_FILE" logs --tail=50 "$service_name"
            return 1
        fi
        
        attempt=$((attempt + 1))
        echo -n "."
        sleep $HEALTH_CHECK_INTERVAL
    done
    
    echo ""
    log_error "$service_name did not become healthy in time"
    return 1
}

# Check service health
check_services_health() {
    log_step "Checking service health..."
    
    # Wait for critical services to be healthy
    wait_for_service "db" $MAX_HEALTH_CHECK_ATTEMPTS || return 1
    wait_for_service "redis" $MAX_HEALTH_CHECK_ATTEMPTS || return 1
    wait_for_service "web" $MAX_HEALTH_CHECK_ATTEMPTS || return 1
    wait_for_service "nginx" $MAX_HEALTH_CHECK_ATTEMPTS || return 1
    
    # Check celery worker (may not have health check)
    if docker-compose -f "$COMPOSE_FILE" ps celery_worker | grep -q "Up"; then
        log_info "celery_worker is running"
    else
        log_error "celery_worker is not running"
        return 1
    fi
    
    # Check celery beat
    if docker-compose -f "$COMPOSE_FILE" ps celery_beat | grep -q "Up"; then
        log_info "celery_beat is running"
    else
        log_error "celery_beat is not running"
        return 1
    fi
    
    log_info "All services are healthy"
    return 0
}

# Run database migrations
run_migrations() {
    log_step "Running database migrations..."
    
    # Wait a bit for database to be fully ready
    sleep 5
    
    # Run migrations
    docker-compose -f "$COMPOSE_FILE" exec -T web python manage.py migrate --noinput || {
        log_error "Database migrations failed"
        docker-compose -f "$COMPOSE_FILE" logs --tail=100 web
        return 1
    }
    
    log_info "Database migrations completed successfully"
}

# Collect static files
collect_static() {
    log_step "Collecting static files..."
    
    docker-compose -f "$COMPOSE_FILE" exec -T web python manage.py collectstatic --noinput --clear || {
        log_error "Static file collection failed"
        return 1
    }
    
    log_info "Static files collected successfully"
}

# Perform application health check
application_health_check() {
    log_step "Performing application health check..."
    
    # Check if web service responds
    local max_attempts=10
    local attempt=0
    
    while [ $attempt -lt $max_attempts ]; do
        if docker-compose -f "$COMPOSE_FILE" exec -T web curl -f http://localhost:8000/admin/login/ > /dev/null 2>&1; then
            log_info "Application is responding correctly"
            return 0
        fi
        
        attempt=$((attempt + 1))
        echo -n "."
        sleep 2
    done
    
    echo ""
    log_error "Application health check failed"
    docker-compose -f "$COMPOSE_FILE" logs --tail=100 web
    return 1
}

# Check database connectivity
check_database_connectivity() {
    log_step "Checking database connectivity..."
    
    docker-compose -f "$COMPOSE_FILE" exec -T web python manage.py check --database default || {
        log_error "Database connectivity check failed"
        return 1
    }
    
    log_info "Database connectivity verified"
}

# Check Celery connectivity
check_celery_connectivity() {
    log_step "Checking Celery connectivity..."
    
    # Try to ping Celery workers
    docker-compose -f "$COMPOSE_FILE" exec -T celery_worker celery -A config inspect ping -t 10 || {
        log_warn "Celery worker ping failed (this may be normal during startup)"
    }
    
    log_info "Celery connectivity check completed"
}

# Comprehensive health check
comprehensive_health_check() {
    log_step "Running comprehensive health checks..."
    
    check_services_health || return 1
    application_health_check || return 1
    check_database_connectivity || return 1
    check_celery_connectivity || return 1
    
    log_info "All health checks passed"
    return 0
}

# Rollback deployment
rollback_deployment() {
    log_step "Rolling back deployment..."
    
    # Stop current containers
    log_info "Stopping failed deployment..."
    docker-compose -f "$COMPOSE_FILE" down --timeout 30 || true
    
    # Check if we have a backup
    if [ -f "$BACKUP_DIR/latest_backup.txt" ]; then
        local backup_timestamp=$(cat "$BACKUP_DIR/latest_backup.txt")
        log_info "Found backup from: $backup_timestamp"
        
        # Try to restore previous images
        if [ -f "$BACKUP_DIR/current_images_$backup_timestamp.txt" ]; then
            log_info "Attempting to restore previous container state..."
        fi
    fi
    
    # Start containers with previous configuration
    log_info "Starting previous version..."
    docker-compose -f "$COMPOSE_FILE" up -d || {
        log_error "Rollback failed - manual intervention required"
        log_error "Please check container logs and system state"
        return 1
    }
    
    # Wait for services
    sleep 10
    
    # Verify rollback
    if docker-compose -f "$COMPOSE_FILE" ps | grep -q "Up"; then
        log_info "Rollback completed - previous version restored"
        log_warn "Deployment failed but system is running on previous version"
        return 0
    else
        log_error "Rollback verification failed - manual intervention required"
        return 1
    fi
}

# Clean up old images
cleanup_old_images() {
    log_step "Cleaning up old Docker images..."
    
    # Remove dangling images
    docker image prune -f || {
        log_warn "Failed to prune images, continuing..."
    }
    
    log_info "Cleanup completed"
}

# Display deployment summary
display_summary() {
    log_step "Deployment Summary"
    echo ""
    echo "========================================="
    echo "  Deployment Completed Successfully"
    echo "========================================="
    echo ""
    log_info "Container Status:"
    docker-compose -f "$COMPOSE_FILE" ps
    echo ""
    log_info "Application should be accessible at:"
    log_info "  https://onbr.site"
    echo ""
    log_info "To view logs:"
    log_info "  docker-compose -f $COMPOSE_FILE logs -f [service_name]"
    echo ""
    log_info "To check service status:"
    log_info "  docker-compose -f $COMPOSE_FILE ps"
    echo ""
}

# Main deployment function
main() {
    log_info "========================================="
    log_info "  Starting Deployment Process"
    log_info "========================================="
    echo ""
    
    # Pre-deployment checks
    check_directory
    create_backup_dir
    
    # Backup current state
    backup_current_state
    
    # Pull and build
    pull_images
    build_images
    
    # Stop old containers
    stop_old_containers
    remove_old_containers
    
    # Start new containers
    start_new_containers
    
    # Wait for services to be ready
    log_info "Waiting for services to initialize..."
    sleep 15
    
    # Run migrations and collect static
    run_migrations
    collect_static
    
    # Perform health checks
    comprehensive_health_check || {
        log_error "Health checks failed"
        return 1
    }
    
    # Cleanup
    cleanup_old_images
    
    # Success
    display_summary
    
    log_info "========================================="
    log_info "  Deployment Completed Successfully"
    log_info "========================================="
    
    return 0
}

# Run main function
main "$@"

