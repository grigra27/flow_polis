#!/bin/bash

# fix-ssl-no-www.sh
# Script to fix SSL setup for onbr.site without www subdomain

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

log_step() {
    echo -e "${BLUE}[STEP]${NC} $1"
}

log_step "Fixing Nginx configuration to remove www subdomain..."

# Update nginx configuration
log_info "Updating nginx/default.conf..."

# Backup current config
cp nginx/default.conf nginx/default.conf.backup.$(date +%Y%m%d_%H%M%S)

# Update server_name to remove www
sed -i 's/server_name onbr.site www.onbr.site;/server_name onbr.site;/g' nginx/default.conf

log_info "Nginx configuration updated"

log_step "Obtaining SSL certificate for onbr.site..."

# Get SSL certificate for onbr.site only
docker compose -f docker-compose.prod.yml run --rm certbot certonly \
  --webroot \
  --webroot-path=/var/www/certbot \
  -d onbr.site \
  --email admin@onbr.site \
  --agree-tos \
  --no-eff-email

if [ $? -eq 0 ]; then
    log_info "SSL certificate obtained successfully!"
    
    log_step "Verifying certificate..."
    docker compose -f docker-compose.prod.yml run --rm certbot certificates
    
    log_step "Testing Nginx configuration..."
    docker compose -f docker-compose.prod.yml exec nginx nginx -t
    
    if [ $? -eq 0 ]; then
        log_step "Restarting Nginx..."
        docker compose -f docker-compose.prod.yml restart nginx
        
        log_info "✅ SSL setup completed successfully!"
        log_info "Your site should now be accessible at: https://onbr.site"
        
        # Test HTTPS
        sleep 5
        log_step "Testing HTTPS access..."
        curl -I https://onbr.site 2>&1 | head -5
    else
        log_error "Nginx configuration test failed"
        exit 1
    fi
else
    log_error "Failed to obtain SSL certificate"
    exit 1
fi

log_info "Done!"
