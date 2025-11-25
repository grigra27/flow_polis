#!/bin/bash

# Production Verification Script
# Run this script on the Digital Ocean Droplet to verify production deployment

# Don't exit on error - we want to run all checks
set +e

echo "=========================================="
echo "PRODUCTION DEPLOYMENT VERIFICATION"
echo "=========================================="
echo ""
echo "Domain: onbr.site"
echo "Date: $(date)"
echo ""

# Colors
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

PASSED=0
FAILED=0
WARNINGS=0

print_result() {
    if [ $1 -eq 0 ]; then
        echo -e "${GREEN}✓ PASSED${NC}: $2"
        PASSED=$((PASSED + 1))
    else
        echo -e "${RED}✗ FAILED${NC}: $2"
        FAILED=$((FAILED + 1))
    fi
}

print_warning() {
    echo -e "${YELLOW}⚠ WARNING${NC}: $1"
    WARNINGS=$((WARNINGS + 1))
}

print_section() {
    echo ""
    echo -e "${BLUE}$1${NC}"
    echo "----------------------------------------"
}

# 1. Check Docker and Docker Compose
print_section "1. Docker Environment"

if command -v docker &> /dev/null; then
    DOCKER_VERSION=$(docker --version)
    print_result 0 "Docker is installed: $DOCKER_VERSION"
else
    print_result 1 "Docker is not installed"
fi

if docker compose version &> /dev/null; then
    COMPOSE_VERSION=$(docker compose version)
    print_result 0 "Docker Compose is installed: $COMPOSE_VERSION"
else
    print_result 1 "Docker Compose is not installed"
fi

# 2. Check running containers
print_section "2. Container Status"

EXPECTED_CONTAINERS=("web" "db" "redis" "celery_worker" "celery_beat" "nginx")
for container in "${EXPECTED_CONTAINERS[@]}"; do
    if docker compose -f docker-compose.prod.yml ps | grep -q "$container.*Up"; then
        print_result 0 "Container $container is running"
    else
        print_result 1 "Container $container is not running"
    fi
done

# 3. Check HTTPS and SSL
print_section "3. HTTPS and SSL Configuration"

# Check if site is accessible via HTTPS
if curl -s -o /dev/null -w "%{http_code}" https://onbr.site | grep -q "200\|301\|302"; then
    print_result 0 "HTTPS site is accessible"
else
    print_result 1 "HTTPS site is not accessible"
fi

# Check HTTP to HTTPS redirect
HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" -L http://onbr.site)
if [ "$HTTP_CODE" = "200" ]; then
    print_result 0 "HTTP redirects to HTTPS successfully"
else
    print_warning "HTTP redirect returned code: $HTTP_CODE"
fi

# Check SSL certificate
if [ -d "/etc/letsencrypt/live/onbr.site" ] || [ -d "certbot/conf/live/onbr.site" ]; then
    print_result 0 "SSL certificate directory exists"
    
    # Check certificate expiry
    if command -v openssl &> /dev/null; then
        if [ -f "certbot/conf/live/onbr.site/cert.pem" ]; then
            EXPIRY=$(openssl x509 -enddate -noout -in certbot/conf/live/onbr.site/cert.pem 2>/dev/null | cut -d= -f2)
            if [ -n "$EXPIRY" ]; then
                print_result 0 "SSL certificate expires: $EXPIRY"
            fi
        fi
    fi
else
    print_result 1 "SSL certificate directory not found"
fi

# 4. Check database
print_section "4. Database Connectivity"

if docker compose -f docker-compose.prod.yml exec -T db psql -U postgres -d insurance_broker_prod -c "SELECT 1;" &> /dev/null; then
    print_result 0 "PostgreSQL database is accessible"
    
    # Check number of tables
    TABLE_COUNT=$(docker compose -f docker-compose.prod.yml exec -T db psql -U postgres -d insurance_broker_prod -t -c "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema = 'public';" 2>/dev/null | tr -d ' ')
    if [ "$TABLE_COUNT" -gt 0 ]; then
        print_result 0 "Database has $TABLE_COUNT tables"
    else
        print_warning "Database appears to be empty"
    fi
else
    print_result 1 "Cannot connect to PostgreSQL database"
fi

# Check migrations
MIGRATION_COUNT=$(docker compose -f docker-compose.prod.yml exec -T web python manage.py showmigrations --plan 2>&1 | grep -c "\[X\]" || echo "0")
if [ "$MIGRATION_COUNT" -gt 0 ]; then
    print_result 0 "Database has $MIGRATION_COUNT applied migrations"
else
    print_result 1 "No migrations applied"
fi

# 5. Check Redis
print_section "5. Redis Connectivity"

if docker compose -f docker-compose.prod.yml exec -T redis redis-cli ping 2>&1 | grep -q "PONG"; then
    print_result 0 "Redis is responding"
    
    # Check Redis memory usage
    REDIS_MEMORY=$(docker compose -f docker-compose.prod.yml exec -T redis redis-cli info memory 2>/dev/null | grep "used_memory_human" | cut -d: -f2 | tr -d '\r')
    if [ -n "$REDIS_MEMORY" ]; then
        print_result 0 "Redis memory usage: $REDIS_MEMORY"
    fi
else
    print_result 1 "Redis is not responding"
fi

# 6. Check Celery
print_section "6. Celery Background Tasks"

# Check Celery worker
if docker compose -f docker-compose.prod.yml logs --tail=50 celery_worker 2>&1 | grep -q "ready"; then
    print_result 0 "Celery worker is ready"
else
    print_warning "Celery worker may not be fully initialized"
fi

# Check Celery beat
if docker compose -f docker-compose.prod.yml logs --tail=50 celery_beat 2>&1 | grep -q "beat"; then
    print_result 0 "Celery beat scheduler is running"
else
    print_warning "Celery beat may not be fully initialized"
fi

# 7. Check static and media files
print_section "7. Static and Media Files"

if docker compose -f docker-compose.prod.yml exec -T web ls /app/staticfiles/admin/css/base.css &> /dev/null; then
    print_result 0 "Static files are collected"
else
    print_result 1 "Static files not found"
fi

if docker compose -f docker-compose.prod.yml exec -T web ls -d /app/media &> /dev/null; then
    print_result 0 "Media directory exists"
else
    print_warning "Media directory not found"
fi

# 8. Check volumes
print_section "8. Docker Volumes"

VOLUMES=("postgres_data" "redis_data" "static_volume" "media_volume")
for volume in "${VOLUMES[@]}"; do
    if docker volume ls | grep -q "$volume"; then
        SIZE=$(docker volume inspect $volume --format '{{ .Mountpoint }}' 2>/dev/null | xargs du -sh 2>/dev/null | cut -f1 || echo "unknown")
        print_result 0 "Volume $volume exists (size: $SIZE)"
    else
        print_result 1 "Volume $volume not found"
    fi
done

# 9. Check environment configuration
print_section "9. Environment Configuration"

if [ -f ".env.prod" ]; then
    print_result 0 ".env.prod file exists"
    
    # Check DEBUG setting
    if grep -q "^DEBUG=False" .env.prod; then
        print_result 0 "DEBUG is set to False (production mode)"
    else
        print_result 1 "DEBUG is not set to False"
    fi
    
    # Check ALLOWED_HOSTS
    if grep -q "^ALLOWED_HOSTS=" .env.prod; then
        ALLOWED_HOSTS=$(grep "^ALLOWED_HOSTS=" .env.prod | cut -d= -f2)
        print_result 0 "ALLOWED_HOSTS is configured: $ALLOWED_HOSTS"
    else
        print_result 1 "ALLOWED_HOSTS not configured"
    fi
else
    print_result 1 ".env.prod file not found"
fi

# 10. Check firewall
print_section "10. Firewall Configuration"

if command -v ufw &> /dev/null; then
    if ufw status | grep -q "Status: active"; then
        print_result 0 "UFW firewall is active"
        
        # Check required ports
        if ufw status | grep -q "80"; then
            print_result 0 "Port 80 (HTTP) is open"
        else
            print_warning "Port 80 may not be open"
        fi
        
        if ufw status | grep -q "443"; then
            print_result 0 "Port 443 (HTTPS) is open"
        else
            print_warning "Port 443 may not be open"
        fi
        
        if ufw status | grep -q "22"; then
            print_result 0 "Port 22 (SSH) is open"
        else
            print_warning "Port 22 may not be open"
        fi
    else
        print_warning "UFW firewall is not active"
    fi
else
    print_warning "UFW not installed"
fi

# 11. Check DNS
print_section "11. DNS Configuration"

if command -v dig &> /dev/null; then
    DOMAIN_IP=$(dig +short onbr.site | tail -n1)
    if [ -n "$DOMAIN_IP" ]; then
        print_result 0 "DNS resolves onbr.site to $DOMAIN_IP"
        
        # Check if it matches server IP
        SERVER_IP=$(curl -s ifconfig.me)
        if [ "$DOMAIN_IP" = "$SERVER_IP" ]; then
            print_result 0 "DNS points to this server"
        else
            print_warning "DNS IP ($DOMAIN_IP) differs from server IP ($SERVER_IP)"
        fi
    else
        print_result 1 "DNS does not resolve onbr.site"
    fi
else
    print_warning "dig command not available"
fi

# 12. Check backup scripts
print_section "12. Backup Configuration"

BACKUP_SCRIPTS=("scripts/backup-db.sh" "scripts/restore-db.sh" "scripts/backup-media.sh")
for script in "${BACKUP_SCRIPTS[@]}"; do
    if [ -f "$script" ] && [ -x "$script" ]; then
        print_result 0 "Backup script $script is ready"
    elif [ -f "$script" ]; then
        print_warning "Backup script $script exists but is not executable"
    else
        print_result 1 "Backup script $script not found"
    fi
done

# 13. Check logs
print_section "13. Logging"

for container in "${EXPECTED_CONTAINERS[@]}"; do
    LOG_LINES=$(docker compose -f docker-compose.prod.yml logs --tail=10 $container 2>&1 | wc -l)
    if [ "$LOG_LINES" -gt 0 ]; then
        print_result 0 "Container $container is generating logs"
    else
        print_warning "No recent logs from $container"
    fi
done

# 14. Check system resources
print_section "14. System Resources"

if command -v free &> /dev/null; then
    MEMORY_USAGE=$(free -h | awk '/^Mem:/ {print $3 "/" $2}')
    print_result 0 "Memory usage: $MEMORY_USAGE"
fi

if command -v df &> /dev/null; then
    DISK_USAGE=$(df -h / | awk 'NR==2 {print $3 "/" $2 " (" $5 " used)"}')
    print_result 0 "Disk usage: $DISK_USAGE"
fi

# 15. Check Docker restart policies
print_section "15. Container Restart Policies"

if docker compose -f docker-compose.prod.yml config | grep -q "restart:"; then
    print_result 0 "Restart policies are configured"
else
    print_warning "No restart policies found"
fi

# Summary
print_section "VERIFICATION SUMMARY"

echo ""
echo -e "${GREEN}Passed: $PASSED${NC}"
echo -e "${RED}Failed: $FAILED${NC}"
echo -e "${YELLOW}Warnings: $WARNINGS${NC}"
echo ""

TOTAL=$((PASSED + FAILED))
if [ $TOTAL -gt 0 ]; then
    SUCCESS_RATE=$((PASSED * 100 / TOTAL))
    echo "Success Rate: ${SUCCESS_RATE}%"
fi

echo ""
if [ $FAILED -eq 0 ]; then
    echo -e "${GREEN}✓ Production deployment is fully operational!${NC}"
    exit 0
else
    echo -e "${RED}✗ Some checks failed. Please review the output above.${NC}"
    exit 1
fi
