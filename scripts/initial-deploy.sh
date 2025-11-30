#!/bin/bash

# initial-deploy.sh
# Script for performing the initial deployment to Digital Ocean Droplet
# This script handles copying files, setting up environment, obtaining SSL, and verifying deployment

set -e  # Exit on error
set -o pipefail  # Exit on pipe failure

# Load deployment configuration if exists
if [ -f ".env.deployment" ]; then
    source .env.deployment
fi

# Configuration
DROPLET_IP="${DROPLET_IP:-64.227.75.233}"
DROPLET_USER="${DROPLET_USER:-root}"
APP_DIR="${APP_DIR:-/opt/insurance_broker}"
LOCAL_DIR="$(pwd)"

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

# Print banner
print_banner() {
    echo ""
    echo "========================================="
    echo "  Initial Deployment to Digital Ocean"
    echo "  Insurance Broker Application"
    echo "========================================="
    echo ""
}

# Check prerequisites
check_prerequisites() {
    log_step "Checking prerequisites..."

    # Check if running from project root
    if [ ! -f "docker-compose.prod.yml" ]; then
        log_error "docker-compose.prod.yml not found. Please run from project root."
        exit 1
    fi

    # Check for required files
    local required_files=(
        "Dockerfile"
        "docker-compose.prod.yml"
        ".env.prod.example"
        ".env.prod.db.example"
        "nginx/default.conf"
        "scripts/deploy.sh"
        "scripts/init-letsencrypt.sh"
    )

    for file in "${required_files[@]}"; do
        if [ ! -f "$file" ] && [ ! -d "$file" ]; then
            log_error "Required file not found: $file"
            exit 1
        fi
    done

    # Check for ssh command
    if ! command -v ssh &> /dev/null; then
        log_error "ssh command not found. Please install OpenSSH client."
        exit 1
    fi

    # Check for rsync (optional but recommended)
    if ! command -v rsync &> /dev/null; then
        log_warn "rsync not found. Will use scp instead (slower)."
    fi

    log_info "Prerequisites check passed"
}

# Get Droplet IP if not set
get_droplet_info() {
    if [ -z "$DROPLET_IP" ]; then
        echo ""
        echo -n "Enter Droplet IP address: "
        read -r DROPLET_IP

        if [ -z "$DROPLET_IP" ]; then
            log_error "Droplet IP is required"
            exit 1
        fi
    fi

    log_info "Droplet IP: $DROPLET_IP"
    log_info "Droplet User: $DROPLET_USER"
    log_info "App Directory: $APP_DIR"
}

# Test SSH connection
test_ssh_connection() {
    log_step "Testing SSH connection to Droplet..."

    # Try to connect with a simple command (allows passphrase input)
    if ssh -o ConnectTimeout=10 "$DROPLET_USER@$DROPLET_IP" "echo 'SSH connection successful'" 2>&1 | grep -q "SSH connection successful"; then
        log_info "SSH connection successful"
    else
        log_error "Cannot connect to Droplet via SSH"
        log_info "Please ensure:"
        log_info "  1. Droplet IP is correct"
        log_info "  2. SSH keys are properly configured"
        log_info "  3. Firewall allows SSH connections (port 22)"
        log_info "  4. You can enter the SSH key passphrase when prompted"
        exit 1
    fi
}

# Verify Droplet setup
verify_droplet_setup() {
    log_step "Verifying Droplet setup..."

    # Check Docker installation
    if ! ssh "$DROPLET_USER@$DROPLET_IP" "command -v docker &> /dev/null"; then
        log_error "Docker is not installed on Droplet"
        log_info "Please run: scripts/setup-droplet.sh"
        exit 1
    fi

    # Check Docker Compose installation
    if ! ssh "$DROPLET_USER@$DROPLET_IP" "command -v docker compose &> /dev/null"; then
        log_error "Docker Compose is not installed on Droplet"
        log_info "Please run: scripts/setup-droplet.sh"
        exit 1
    fi

    log_info "Droplet setup verified"
}

# Create application directory on Droplet
create_app_directory() {
    log_step "Creating application directory on Droplet..."

    ssh "$DROPLET_USER@$DROPLET_IP" "mkdir -p $APP_DIR"
    ssh "$DROPLET_USER@$DROPLET_IP" "mkdir -p $APP_DIR/nginx"
    ssh "$DROPLET_USER@$DROPLET_IP" "mkdir -p $APP_DIR/certbot/conf"
    ssh "$DROPLET_USER@$DROPLET_IP" "mkdir -p $APP_DIR/certbot/www"
    ssh "$DROPLET_USER@$DROPLET_IP" "mkdir -p $APP_DIR/logs"
    ssh "$DROPLET_USER@$DROPLET_IP" "mkdir -p $APP_DIR/scripts"

    log_info "Application directory created"
}

# Copy files to Droplet
copy_files_to_droplet() {
    log_step "Copying files to Droplet..."

    # Files and directories to copy
    local items=(
        "apps"
        "config"
        "templates"
        "static"
        "fixtures"
        "nginx"
        "scripts"
        "Dockerfile"
        "docker-compose.prod.yml"
        "requirements.txt"
        "requirements.prod.txt"
        "manage.py"
        "entrypoint.sh"
        ".dockerignore"
        "create_superuser.py"
    )

    if command -v rsync &> /dev/null; then
        log_info "Using rsync for file transfer..."

        for item in "${items[@]}"; do
            if [ -e "$item" ]; then
                rsync -avz --progress "$item" "$DROPLET_USER@$DROPLET_IP:$APP_DIR/" || {
                    log_warn "Failed to copy $item, continuing..."
                }
            fi
        done
    else
        log_info "Using scp for file transfer..."

        for item in "${items[@]}"; do
            if [ -e "$item" ]; then
                scp -r "$item" "$DROPLET_USER@$DROPLET_IP:$APP_DIR/" || {
                    log_warn "Failed to copy $item, continuing..."
                }
            fi
        done
    fi

    log_info "Files copied successfully"
}

# Create production environment files
create_env_files() {
    log_step "Creating production environment files..."

    # Generate secure passwords
    local secret_key=$(openssl rand -base64 50 | tr -d '\n')
    local db_password=$(openssl rand -base64 32 | tr -d '\n')

    log_info "Generated secure credentials"

    # Prompt for email configuration
    echo ""
    echo "Email Configuration (for notifications):"
    echo -n "Email host (default: smtp.gmail.com): "
    read -r email_host
    email_host=${email_host:-smtp.gmail.com}

    echo -n "Email port (default: 587): "
    read -r email_port
    email_port=${email_port:-587}

    echo -n "Email user: "
    read -r email_user

    echo -n "Email password (or app password): "
    read -rs email_password
    echo ""

    # Create .env.prod
    ssh "$DROPLET_USER@$DROPLET_IP" "cat > $APP_DIR/.env.prod << 'EOF'
# Django Core Settings
SECRET_KEY=$secret_key
DEBUG=False
ALLOWED_HOSTS=onbr.site,www.onbr.site

# Database Configuration
DB_NAME=insurance_broker_prod
DB_USER=postgres
DB_PASSWORD=$db_password
DB_HOST=db
DB_PORT=5432

# Celery Configuration
CELERY_BROKER_URL=redis://redis:6379/0
CELERY_RESULT_BACKEND=redis://redis:6379/0

# Email Configuration
EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend
EMAIL_HOST=$email_host
EMAIL_PORT=$email_port
EMAIL_USE_TLS=True
EMAIL_HOST_USER=$email_user
EMAIL_HOST_PASSWORD=$email_password
DEFAULT_FROM_EMAIL=noreply@onbr.site

# Security Settings
SECURE_SSL_REDIRECT=True
SECURE_HSTS_SECONDS=31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS=True
SECURE_HSTS_PRELOAD=True
SESSION_COOKIE_SECURE=True
CSRF_COOKIE_SECURE=True
SECURE_CONTENT_TYPE_NOSNIFF=True
SECURE_BROWSER_XSS_FILTER=True
X_FRAME_OPTIONS=DENY

# Static and Media Files
STATIC_ROOT=/app/staticfiles
MEDIA_ROOT=/app/media
STATIC_URL=/static/
MEDIA_URL=/media/

# Logging
LOG_LEVEL=INFO
EOF"

    # Create .env.prod.db
    ssh "$DROPLET_USER@$DROPLET_IP" "cat > $APP_DIR/.env.prod.db << 'EOF'
POSTGRES_DB=insurance_broker_prod
POSTGRES_USER=postgres
POSTGRES_PASSWORD=$db_password
EOF"

    # Set proper permissions
    ssh "$DROPLET_USER@$DROPLET_IP" "chmod 600 $APP_DIR/.env.prod $APP_DIR/.env.prod.db"

    log_info "Environment files created"
    log_warn "IMPORTANT: Save these credentials securely!"
    echo ""
    echo "Database Password: $db_password"
    echo "Secret Key: $secret_key"
    echo ""
}

# Start Docker containers
start_docker_containers() {
    log_step "Starting Docker containers..."

    ssh "$DROPLET_USER@$DROPLET_IP" "cd $APP_DIR && docker compose -f docker-compose.prod.yml up -d"

    log_info "Waiting for containers to start..."
    sleep 20

    # Check container status
    ssh "$DROPLET_USER@$DROPLET_IP" "cd $APP_DIR && docker compose -f docker-compose.prod.yml ps"

    log_info "Docker containers started"
}

# Run database migrations
run_migrations() {
    log_step "Running database migrations..."

    ssh "$DROPLET_USER@$DROPLET_IP" "cd $APP_DIR && docker compose -f docker-compose.prod.yml exec -T web python manage.py migrate --noinput"

    log_info "Database migrations completed"
}

# Collect static files
collect_static() {
    log_step "Collecting static files..."

    ssh "$DROPLET_USER@$DROPLET_IP" "cd $APP_DIR && docker compose -f docker-compose.prod.yml exec -T web python manage.py collectstatic --noinput --clear"

    log_info "Static files collected"
}

# Obtain SSL certificate
obtain_ssl_certificate() {
    log_step "Obtaining SSL certificate from Let's Encrypt..."

    log_info "This may take a few minutes..."

    # Make init-letsencrypt.sh executable
    ssh "$DROPLET_USER@$DROPLET_IP" "chmod +x $APP_DIR/scripts/init-letsencrypt.sh"

    # Run the SSL initialization script
    ssh "$DROPLET_USER@$DROPLET_IP" "cd $APP_DIR && ./scripts/init-letsencrypt.sh" || {
        log_error "Failed to obtain SSL certificate"
        log_info "Common issues:"
        log_info "  1. DNS not pointing to Droplet IP"
        log_info "  2. Firewall blocking port 80/443"
        log_info "  3. Domain not accessible from internet"
        log_info ""
        log_info "You can:"
        log_info "  1. Check DNS: dig onbr.site"
        log_info "  2. Test with staging: STAGING=1 ./scripts/init-letsencrypt.sh"
        log_info "  3. Check firewall: sudo ufw status"
        return 1
    }

    log_info "SSL certificate obtained successfully"
}

# Update Nginx configuration for HTTPS
update_nginx_config() {
    log_step "Updating Nginx configuration for HTTPS..."

    # The init-letsencrypt.sh script should handle this
    # Just verify and restart nginx

    ssh "$DROPLET_USER@$DROPLET_IP" "cd $APP_DIR && docker compose -f docker-compose.prod.yml exec nginx nginx -t" || {
        log_error "Nginx configuration test failed"
        return 1
    }

    ssh "$DROPLET_USER@$DROPLET_IP" "cd $APP_DIR && docker compose -f docker-compose.prod.yml restart nginx"

    log_info "Nginx configuration updated"
}

# Verify deployment
verify_deployment() {
    log_step "Verifying deployment..."

    # Check container status
    log_info "Checking container status..."
    ssh "$DROPLET_USER@$DROPLET_IP" "cd $APP_DIR && docker compose -f docker-compose.prod.yml ps"

    # Test HTTP (should redirect to HTTPS)
    log_info "Testing HTTP redirect..."
    if ssh "$DROPLET_USER@$DROPLET_IP" "curl -I http://localhost" | grep -q "301\|302"; then
        log_info "HTTP redirect working"
    else
        log_warn "HTTP redirect may not be working correctly"
    fi

    # Test HTTPS
    log_info "Testing HTTPS..."
    if ssh "$DROPLET_USER@$DROPLET_IP" "curl -k -I https://localhost" | grep -q "200\|301\|302"; then
        log_info "HTTPS working"
    else
        log_warn "HTTPS may not be working correctly"
    fi

    # Check database connectivity
    log_info "Checking database connectivity..."
    ssh "$DROPLET_USER@$DROPLET_IP" "cd $APP_DIR && docker compose -f docker-compose.prod.yml exec -T web python manage.py check --database default" || {
        log_warn "Database connectivity check failed"
    }

    log_info "Deployment verification completed"
}

# Create superuser
create_superuser() {
    log_step "Creating Django superuser..."

    echo ""
    echo "You can create a superuser now or skip and do it later."
    echo -n "Create superuser now? (y/N): "
    read -r response

    if [[ "$response" =~ ^([yY][eE][sS]|[yY])$ ]]; then
        ssh -t "$DROPLET_USER@$DROPLET_IP" "cd $APP_DIR && docker compose -f docker-compose.prod.yml exec web python manage.py createsuperuser"
        log_info "Superuser created"
    else
        log_info "Skipping superuser creation"
        log_info "You can create it later with:"
        log_info "  ssh $DROPLET_USER@$DROPLET_IP"
        log_info "  cd $APP_DIR"
        log_info "  docker compose -f docker-compose.prod.yml exec web python manage.py createsuperuser"
    fi
}

# Print deployment summary
print_summary() {
    echo ""
    log_info "========================================="
    log_info "  Initial Deployment Completed!"
    log_info "========================================="
    echo ""
    log_info "Application Details:"
    log_info "  URL: https://onbr.site"
    log_info "  Admin: https://onbr.site/admin/"
    log_info "  Droplet IP: $DROPLET_IP"
    log_info "  App Directory: $APP_DIR"
    echo ""
    log_info "Next Steps:"
    log_info "  1. Visit https://onbr.site to verify the site is working"
    log_info "  2. Login to admin panel: https://onbr.site/admin/"
    log_info "  3. Configure GitHub Secrets for CI/CD (see task 20)"
    log_info "  4. Test automatic deployment (see task 21)"
    echo ""
    log_info "Useful Commands:"
    log_info "  View logs:"
    log_info "    ssh $DROPLET_USER@$DROPLET_IP"
    log_info "    cd $APP_DIR"
    log_info "    docker compose -f docker-compose.prod.yml logs -f [service]"
    echo ""
    log_info "  Restart services:"
    log_info "    docker compose -f docker-compose.prod.yml restart [service]"
    echo ""
    log_info "  Run management commands:"
    log_info "    docker compose -f docker-compose.prod.yml exec web python manage.py [command]"
    echo ""
    log_info "For troubleshooting, see: docs/DEPLOYMENT.md"
    echo ""
}

# Main execution
main() {
    print_banner

    check_prerequisites
    get_droplet_info
    test_ssh_connection
    verify_droplet_setup

    echo ""
    echo "This script will:"
    echo "  1. Copy application files to Droplet"
    echo "  2. Create production environment files"
    echo "  3. Start Docker containers"
    echo "  4. Obtain SSL certificate from Let's Encrypt"
    echo "  5. Configure HTTPS"
    echo "  6. Verify deployment"
    echo ""
    echo -n "Continue with deployment? (y/N): "
    read -r response

    if [[ ! "$response" =~ ^([yY][eE][sS]|[yY])$ ]]; then
        log_info "Deployment cancelled"
        exit 0
    fi

    create_app_directory
    copy_files_to_droplet
    create_env_files
    start_docker_containers
    run_migrations
    collect_static

    # SSL certificate setup
    echo ""
    echo "SSL Certificate Setup:"
    echo "Before obtaining SSL certificate, ensure:"
    echo "  1. DNS is pointing to Droplet IP: $DROPLET_IP"
    echo "  2. Domain onbr.site is accessible from internet"
    echo "  3. Firewall allows ports 80 and 443"
    echo ""
    echo -n "Proceed with SSL certificate setup? (y/N): "
    read -r ssl_response

    if [[ "$ssl_response" =~ ^([yY][eE][sS]|[yY])$ ]]; then
        obtain_ssl_certificate || {
            log_warn "SSL certificate setup failed"
            log_info "You can retry later with:"
            log_info "  ssh $DROPLET_USER@$DROPLET_IP"
            log_info "  cd $APP_DIR"
            log_info "  ./scripts/init-letsencrypt.sh"
        }
        update_nginx_config || {
            log_warn "Nginx configuration update failed"
        }
    else
        log_warn "Skipping SSL certificate setup"
        log_info "Application is running on HTTP only"
        log_info "To setup SSL later, run: ./scripts/init-letsencrypt.sh on the Droplet"
    fi

    verify_deployment
    create_superuser
    print_summary

    log_info "Deployment script completed successfully!"
}

# Run main function
main "$@"
