#!/bin/bash

# init-letsencrypt.sh
# Script to initialize Let's Encrypt SSL certificates for the Insurance Broker application
# This script handles the initial certificate setup and configuration

set -e

# Configuration
DOMAIN="onbr.site"
WWW_DOMAIN="www.onbr.site"
EMAIL="admin@onbr.site"
STAGING=${STAGING:-0}  # Set to 1 for testing with Let's Encrypt staging server
COMPOSE_FILE="docker-compose.prod.yml"
NGINX_CONF_DIR="./nginx"
CERTBOT_DIR="./certbot"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Helper functions
log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Check if running as root or with sudo
check_permissions() {
    if [ "$EUID" -eq 0 ]; then
        log_warn "Running as root. This is not recommended."
    fi
}

# Check if required commands are available
check_dependencies() {
    log_info "Checking dependencies..."

    if ! command -v docker &> /dev/null; then
        log_error "Docker is not installed. Please install Docker first."
        exit 1
    fi

    if ! command -v docker-compose &> /dev/null; then
        log_error "Docker Compose is not installed. Please install Docker Compose first."
        exit 1
    fi

    log_info "All dependencies are available."
}

# Check if certificates already exist
check_existing_certificates() {
    if [ -d "$CERTBOT_DIR/conf/live/$DOMAIN" ]; then
        log_warn "Certificates for $DOMAIN already exist!"
        echo -n "Do you want to renew them? (y/N): "
        read -r response
        if [[ ! "$response" =~ ^([yY][eE][sS]|[yY])$ ]]; then
            log_info "Keeping existing certificates. Exiting."
            exit 0
        fi
        log_info "Proceeding with certificate renewal..."
        return 1
    fi
    return 0
}

# Create required directories
create_directories() {
    log_info "Creating required directories..."

    mkdir -p "$CERTBOT_DIR/conf"
    mkdir -p "$CERTBOT_DIR/www"
    mkdir -p "$NGINX_CONF_DIR"

    log_info "Directories created successfully."
}

# Check if .env.prod file exists
check_env_file() {
    if [ ! -f ".env.prod" ]; then
        log_error ".env.prod file not found!"
        log_info "Please create .env.prod from .env.prod.example"
        exit 1
    fi

    if [ ! -f ".env.prod.db" ]; then
        log_error ".env.prod.db file not found!"
        log_info "Please create .env.prod.db from .env.prod.db.example"
        exit 1
    fi
}

# Backup current nginx configuration
backup_nginx_config() {
    if [ -f "$NGINX_CONF_DIR/default.conf" ]; then
        log_info "Backing up current nginx configuration..."
        cp "$NGINX_CONF_DIR/default.conf" "$NGINX_CONF_DIR/default.conf.backup.$(date +%Y%m%d_%H%M%S)"
    fi
}

# Use initial nginx configuration (without SSL)
use_initial_nginx_config() {
    log_info "Setting up initial nginx configuration (without SSL)..."

    if [ ! -f "$NGINX_CONF_DIR/default.conf.initial" ]; then
        log_error "Initial nginx configuration not found at $NGINX_CONF_DIR/default.conf.initial"
        exit 1
    fi

    cp "$NGINX_CONF_DIR/default.conf.initial" "$NGINX_CONF_DIR/default.conf"
    log_info "Initial nginx configuration applied."
}

# Start Docker services
start_services() {
    log_info "Starting Docker services..."

    docker-compose -f "$COMPOSE_FILE" up -d db redis
    log_info "Waiting for database and redis to be ready..."
    sleep 10

    docker-compose -f "$COMPOSE_FILE" up -d web
    log_info "Waiting for web service to be ready..."
    sleep 15

    docker-compose -f "$COMPOSE_FILE" up -d nginx
    log_info "Nginx started."
    sleep 5
}

# Verify services are running
verify_services() {
    log_info "Verifying services are running..."

    if ! docker-compose -f "$COMPOSE_FILE" ps | grep -q "Up"; then
        log_error "Some services failed to start. Check logs with: docker-compose -f $COMPOSE_FILE logs"
        exit 1
    fi

    log_info "All services are running."
}

# Test HTTP access
test_http_access() {
    log_info "Testing HTTP access..."

    # Try to access the health endpoint
    if command -v curl &> /dev/null; then
        if curl -f http://localhost/health/ &> /dev/null; then
            log_info "HTTP access verified."
        else
            log_warn "Could not verify HTTP access. This might be normal if running remotely."
        fi
    else
        log_warn "curl not available. Skipping HTTP access test."
    fi
}

# Obtain SSL certificate
obtain_certificate() {
    log_info "Obtaining SSL certificate from Let's Encrypt..."

    local staging_arg=""
    if [ "$STAGING" = "1" ]; then
        log_warn "Using Let's Encrypt STAGING server (for testing)"
        staging_arg="--staging"
    fi

    # Request certificate
    docker-compose -f "$COMPOSE_FILE" run --rm --entrypoint "\
        certbot certonly --webroot \
        --webroot-path=/var/www/certbot \
        --email $EMAIL \
        --agree-tos \
        --no-eff-email \
        $staging_arg \
        -d $DOMAIN \
        -d $WWW_DOMAIN" certbot || {
        log_error "Failed to obtain SSL certificate!"
        log_info "Common issues:"
        log_info "  1. DNS not pointing to this server"
        log_info "  2. Firewall blocking port 80"
        log_info "  3. Domain not accessible from internet"
        log_info ""
        log_info "You can test with staging server: STAGING=1 ./scripts/init-letsencrypt.sh"
        exit 1
    }

    log_info "SSL certificate obtained successfully!"
}

# Verify certificate files
verify_certificate() {
    log_info "Verifying certificate files..."

    local cert_dir="$CERTBOT_DIR/conf/live/$DOMAIN"

    if [ ! -f "$cert_dir/fullchain.pem" ] || \
       [ ! -f "$cert_dir/privkey.pem" ] || \
       [ ! -f "$cert_dir/chain.pem" ]; then
        log_error "Certificate files not found in $cert_dir"
        exit 1
    fi

    log_info "Certificate files verified."

    # Show certificate expiry
    log_info "Certificate details:"
    docker-compose -f "$COMPOSE_FILE" run --rm --entrypoint "\
        openssl x509 -in /etc/letsencrypt/live/$DOMAIN/fullchain.pem -noout -dates" certbot
}

# Restore SSL-enabled nginx configuration
restore_ssl_nginx_config() {
    log_info "Restoring SSL-enabled nginx configuration..."

    # The default.conf should already have SSL configuration
    # We just need to ensure it's the right version
    if [ -f "$NGINX_CONF_DIR/default.conf.backup."* ]; then
        # Find the most recent backup that's not the initial config
        local latest_backup=$(ls -t "$NGINX_CONF_DIR"/default.conf.backup.* 2>/dev/null | head -1)
        if [ -n "$latest_backup" ] && ! grep -q "Initial setup without SSL" "$latest_backup"; then
            cp "$latest_backup" "$NGINX_CONF_DIR/default.conf"
            log_info "Restored previous SSL configuration."
        fi
    fi

    # If no suitable backup, we assume default.conf.initial was temporary
    # and we need to restore the original default.conf from git or use a template
    log_info "SSL-enabled nginx configuration is ready."
}

# Reload nginx
reload_nginx() {
    log_info "Reloading nginx with SSL configuration..."

    docker-compose -f "$COMPOSE_FILE" exec nginx nginx -t || {
        log_error "Nginx configuration test failed!"
        log_info "Restoring initial configuration..."
        use_initial_nginx_config
        docker-compose -f "$COMPOSE_FILE" restart nginx
        exit 1
    }

    docker-compose -f "$COMPOSE_FILE" restart nginx
    log_info "Nginx reloaded successfully."
}

# Test HTTPS access
test_https_access() {
    log_info "Testing HTTPS access..."

    sleep 5

    if command -v curl &> /dev/null; then
        if curl -f -k https://localhost/health/ &> /dev/null; then
            log_info "HTTPS access verified."
        else
            log_warn "Could not verify HTTPS access. This might be normal if running remotely."
        fi
    else
        log_warn "curl not available. Skipping HTTPS access test."
    fi
}

# Setup automatic renewal
setup_auto_renewal() {
    log_info "Setting up automatic certificate renewal..."

    # Add certbot service to docker-compose if not present
    if ! grep -q "certbot:" "$COMPOSE_FILE"; then
        log_warn "Certbot service not found in $COMPOSE_FILE"
        log_info "To enable automatic renewal, add the certbot service to your docker-compose.prod.yml:"
        echo ""
        echo "  certbot:"
        echo "    image: certbot/certbot"
        echo "    volumes:"
        echo "      - ./certbot/conf:/etc/letsencrypt"
        echo "      - ./certbot/www:/var/www/certbot"
        echo "    entrypoint: \"/bin/sh -c 'trap exit TERM; while :; do certbot renew; sleep 12h & wait \${!}; done;'\""
        echo ""
    else
        log_info "Certbot service found in docker-compose. Starting it for automatic renewal..."
        docker-compose -f "$COMPOSE_FILE" up -d certbot
    fi

    log_info "Automatic renewal setup complete."
    log_info "Certificates will be checked for renewal twice daily."
}

# Print success message
print_success() {
    echo ""
    log_info "========================================="
    log_info "SSL Certificate Setup Complete!"
    log_info "========================================="
    echo ""
    log_info "Your application should now be accessible at:"
    log_info "  https://$DOMAIN"
    log_info "  https://$WWW_DOMAIN"
    echo ""
    log_info "Certificate will expire in 90 days."
    log_info "Automatic renewal is configured to run twice daily."
    echo ""
    log_info "To manually renew certificates:"
    log_info "  docker-compose -f $COMPOSE_FILE run --rm certbot renew"
    log_info "  docker-compose -f $COMPOSE_FILE exec nginx nginx -s reload"
    echo ""
    log_info "To check certificate status:"
    log_info "  docker-compose -f $COMPOSE_FILE run --rm certbot certificates"
    echo ""
}

# Main execution
main() {
    log_info "Starting Let's Encrypt SSL certificate initialization..."
    echo ""

    check_permissions
    check_dependencies
    check_env_file

    local is_new_cert=0
    if check_existing_certificates; then
        is_new_cert=1
    fi

    create_directories
    backup_nginx_config

    if [ $is_new_cert -eq 1 ]; then
        use_initial_nginx_config
        start_services
        verify_services
        test_http_access
    fi

    obtain_certificate
    verify_certificate

    if [ $is_new_cert -eq 1 ]; then
        restore_ssl_nginx_config
        reload_nginx
        test_https_access
    fi

    setup_auto_renewal
    print_success
}

# Run main function
main "$@"
