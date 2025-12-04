#!/bin/bash

# SSL Certificate Acquisition Script for polis.insflow.ru
# This script automates the process of obtaining Let's Encrypt SSL certificate

set -e  # Exit on any error

# Configuration
DOMAIN="polis.insflow.ru"
EMAIL="${SSL_EMAIL:-admin@insflow.ru}"
PROJECT_DIR="${PROJECT_DIR:-~/insurance_broker}"
COMPOSE_FILE="docker-compose.prod.yml"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Helper functions
print_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

print_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

print_header() {
    echo ""
    echo -e "${BLUE}========================================${NC}"
    echo -e "${BLUE}$1${NC}"
    echo -e "${BLUE}========================================${NC}"
    echo ""
}

# Check if running as root or with sudo
check_permissions() {
    if [ "$EUID" -eq 0 ]; then
        print_warning "Running as root. This is acceptable but not required."
    fi
}

# Check if required commands are available
check_requirements() {
    print_header "Checking Requirements"

    local missing_requirements=0

    if ! command -v docker &> /dev/null; then
        print_error "Docker is not installed"
        missing_requirements=1
    else
        print_success "Docker is installed"
    fi

    if ! command -v docker-compose &> /dev/null; then
        print_error "Docker Compose is not installed"
        missing_requirements=1
    else
        print_success "Docker Compose is installed"
    fi

    if ! command -v curl &> /dev/null; then
        print_error "curl is not installed"
        missing_requirements=1
    else
        print_success "curl is installed"
    fi

    if [ $missing_requirements -eq 1 ]; then
        print_error "Please install missing requirements before continuing"
        exit 1
    fi
}

# Check DNS resolution
check_dns() {
    print_header "Checking DNS Resolution"

    print_info "Checking DNS for $DOMAIN..."

    if command -v dig &> /dev/null; then
        local resolved_ip=$(dig +short $DOMAIN | tail -n1)
        if [ -z "$resolved_ip" ]; then
            print_error "DNS resolution failed for $DOMAIN"
            print_warning "Please ensure DNS is configured correctly before obtaining SSL certificate"
            read -p "Do you want to continue anyway? (y/N): " -n 1 -r
            echo
            if [[ ! $REPLY =~ ^[Yy]$ ]]; then
                exit 1
            fi
        else
            print_success "DNS resolved to: $resolved_ip"
        fi
    elif command -v nslookup &> /dev/null; then
        if nslookup $DOMAIN &> /dev/null; then
            print_success "DNS resolution successful"
        else
            print_error "DNS resolution failed for $DOMAIN"
            print_warning "Please ensure DNS is configured correctly before obtaining SSL certificate"
            read -p "Do you want to continue anyway? (y/N): " -n 1 -r
            echo
            if [[ ! $REPLY =~ ^[Yy]$ ]]; then
                exit 1
            fi
        fi
    else
        print_warning "Neither dig nor nslookup found, skipping DNS check"
    fi
}

# Check HTTP accessibility
check_http_access() {
    print_header "Checking HTTP Accessibility"

    print_info "Checking if $DOMAIN is accessible via HTTP..."

    if curl -s -o /dev/null -w "%{http_code}" --max-time 10 http://$DOMAIN/health/ | grep -q "200"; then
        print_success "HTTP access to $DOMAIN is working"
    else
        print_warning "HTTP access check failed"
        print_info "This might be normal if nginx is not yet configured"
        read -p "Do you want to continue? (y/N): " -n 1 -r
        echo
        if [[ ! $REPLY =~ ^[Yy]$ ]]; then
            exit 1
        fi
    fi
}

# Check if containers are running
check_containers() {
    print_header "Checking Docker Containers"

    cd "$PROJECT_DIR" || exit 1

    print_info "Checking if containers are running..."

    if docker-compose -f $COMPOSE_FILE ps | grep -q "Up"; then
        print_success "Docker containers are running"
    else
        print_error "Docker containers are not running"
        print_info "Starting containers..."
        docker-compose -f $COMPOSE_FILE up -d
        sleep 5
        print_success "Containers started"
    fi

    # Check nginx specifically
    if docker-compose -f $COMPOSE_FILE ps nginx | grep -q "Up"; then
        print_success "Nginx container is running"
    else
        print_error "Nginx container is not running"
        exit 1
    fi
}

# Check nginx configuration
check_nginx_config() {
    print_header "Checking Nginx Configuration"

    cd "$PROJECT_DIR" || exit 1

    print_info "Testing nginx configuration..."

    if docker-compose -f $COMPOSE_FILE exec -T nginx nginx -t &> /dev/null; then
        print_success "Nginx configuration is valid"
    else
        print_error "Nginx configuration has errors"
        docker-compose -f $COMPOSE_FILE exec -T nginx nginx -t
        exit 1
    fi

    # Check if HTTP-only config is in use
    if docker-compose -f $COMPOSE_FILE exec -T nginx grep -q "listen 443" /etc/nginx/conf.d/default.conf 2>/dev/null; then
        print_warning "Nginx is configured for HTTPS"
        print_warning "For initial SSL certificate acquisition, HTTP-only configuration is recommended"
        print_info "You can switch to HTTP-only config with:"
        print_info "  cp nginx/default.conf.http-only nginx/default.conf"
        print_info "  docker-compose -f $COMPOSE_FILE restart nginx"
        read -p "Do you want to continue with current configuration? (y/N): " -n 1 -r
        echo
        if [[ ! $REPLY =~ ^[Yy]$ ]]; then
            exit 1
        fi
    else
        print_success "Nginx is using HTTP-only configuration (recommended for initial setup)"
    fi
}

# Obtain SSL certificate
obtain_certificate() {
    print_header "Obtaining SSL Certificate"

    cd "$PROJECT_DIR" || exit 1

    print_info "Domain: $DOMAIN"
    print_info "Email: $EMAIL"
    print_warning "Let's Encrypt will send certificate expiration notices to this email"

    read -p "Is this email correct? (Y/n): " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Nn]$ ]]; then
        read -p "Enter your email address: " EMAIL
    fi

    print_info "Requesting SSL certificate from Let's Encrypt..."
    print_info "This may take a minute..."

    if docker-compose -f $COMPOSE_FILE run --rm certbot certonly \
        --webroot \
        --webroot-path=/var/www/certbot \
        --email "$EMAIL" \
        --agree-tos \
        --no-eff-email \
        --force-renewal \
        -d "$DOMAIN"; then
        print_success "SSL certificate obtained successfully!"
    else
        print_error "Failed to obtain SSL certificate"
        print_info "Common issues:"
        print_info "  1. DNS is not configured or not propagated yet"
        print_info "  2. Port 80 is not accessible from the internet"
        print_info "  3. Firewall is blocking HTTP traffic"
        print_info "  4. Nginx is not serving /.well-known/acme-challenge/ correctly"
        exit 1
    fi
}

# Verify certificate files
verify_certificate() {
    print_header "Verifying Certificate Files"

    cd "$PROJECT_DIR" || exit 1

    print_info "Checking certificate files..."

    local cert_files=("cert.pem" "chain.pem" "fullchain.pem" "privkey.pem")
    local all_files_exist=1

    for file in "${cert_files[@]}"; do
        if docker-compose -f $COMPOSE_FILE exec -T nginx test -f "/etc/letsencrypt/live/$DOMAIN/$file" 2>/dev/null; then
            print_success "$file exists"
        else
            print_error "$file not found"
            all_files_exist=0
        fi
    done

    if [ $all_files_exist -eq 1 ]; then
        print_success "All certificate files are present"

        # Show certificate expiration date
        print_info "Certificate details:"
        docker-compose -f $COMPOSE_FILE exec -T nginx openssl x509 -in "/etc/letsencrypt/live/$DOMAIN/cert.pem" -noout -dates 2>/dev/null || true
    else
        print_error "Some certificate files are missing"
        exit 1
    fi
}

# Provide next steps
show_next_steps() {
    print_header "Next Steps"

    print_success "SSL certificate has been obtained successfully!"
    echo ""
    print_info "To enable HTTPS, follow these steps:"
    echo ""
    echo "1. Switch to HTTPS nginx configuration:"
    echo "   ${GREEN}cp nginx/default.conf.backup nginx/default.conf${NC}"
    echo "   Or pull from repository:"
    echo "   ${GREEN}git pull origin main${NC}"
    echo ""
    echo "2. Restart nginx to apply HTTPS configuration:"
    echo "   ${GREEN}docker-compose -f $COMPOSE_FILE restart nginx${NC}"
    echo ""
    echo "3. Verify HTTPS is working:"
    echo "   ${GREEN}curl -I https://$DOMAIN${NC}"
    echo ""
    echo "4. Check that HTTP redirects to HTTPS:"
    echo "   ${GREEN}curl -I http://$DOMAIN${NC}"
    echo ""
    echo "5. Test in browser:"
    echo "   ${GREEN}https://$DOMAIN${NC}"
    echo ""
    print_info "Certificate will auto-renew via certbot container"
    print_info "Certbot runs every 12 hours and renews certificates 30 days before expiration"
    echo ""
}

# Main execution
main() {
    print_header "SSL Certificate Acquisition Script"
    print_info "Domain: $DOMAIN"
    print_info "Project Directory: $PROJECT_DIR"
    echo ""

    check_permissions
    check_requirements
    check_dns
    check_containers
    check_nginx_config
    check_http_access
    obtain_certificate
    verify_certificate
    show_next_steps

    print_success "Script completed successfully!"
}

# Run main function
main "$@"
