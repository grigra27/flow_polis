#!/bin/bash
# SSL Setup Script for First Deployment
# This script handles the initial SSL certificate setup

set -e

DOMAIN="polis.insflow.ru"
EMAIL="admin@insflow.ru"  # Change this to your email

echo "🔐 Starting SSL setup for $DOMAIN..."
echo ""

# Check if certificates already exist
if [ -d "certbot/conf/live/$DOMAIN" ]; then
    echo "⚠️  SSL certificates already exist for $DOMAIN"
    echo "If you want to renew them, use: docker-compose -f docker-compose.prod.yml run --rm certbot renew"
    exit 0
fi

# Check if DNS is configured
echo "🔍 Checking DNS configuration..."
DNS_IP=$(nslookup $DOMAIN | grep -A1 "Name:" | grep "Address:" | awk '{print $2}' | tail -1)
if [ -z "$DNS_IP" ]; then
    echo "❌ DNS is not configured for $DOMAIN"
    echo "Please configure DNS A record first"
    exit 1
fi
echo "✅ DNS configured: $DOMAIN -> $DNS_IP"
echo ""

# Step 1: Use initial nginx config without SSL
echo "📝 Step 1: Switching to initial nginx config (no SSL)..."
if [ ! -f "nginx/default.conf.initial" ]; then
    echo "❌ nginx/default.conf.initial not found"
    exit 1
fi

# Backup current config if not already backed up
if [ ! -f "nginx/default.conf.ssl" ]; then
    cp nginx/default.conf nginx/default.conf.ssl
    echo "✅ Backed up SSL config to nginx/default.conf.ssl"
fi

cp nginx/default.conf.initial nginx/default.conf
echo "✅ Switched to initial config"
echo ""

# Step 2: Restart nginx with initial config
echo "🔄 Step 2: Restarting nginx..."
docker-compose -f docker-compose.prod.yml restart nginx

# Wait for nginx to be ready
echo "⏳ Waiting for nginx to be ready..."
sleep 10

# Check if nginx is running
if ! docker-compose -f docker-compose.prod.yml ps | grep -q "nginx.*Up"; then
    echo "❌ Nginx is not running"
    docker-compose -f docker-compose.prod.yml logs nginx
    exit 1
fi
echo "✅ Nginx is running"
echo ""

# Test HTTP access
echo "🔍 Testing HTTP access..."
if curl -f -s -o /dev/null "http://$DOMAIN/health/"; then
    echo "✅ HTTP access works"
else
    echo "❌ Cannot access http://$DOMAIN/health/"
    echo "Please check nginx logs: docker-compose -f docker-compose.prod.yml logs nginx"
    exit 1
fi
echo ""

# Step 3: Obtain SSL certificate
echo "🔐 Step 3: Obtaining SSL certificate..."
echo "This may take a minute..."
if docker-compose -f docker-compose.prod.yml run --rm certbot certonly \
    --webroot \
    --webroot-path=/var/www/certbot \
    --email $EMAIL \
    --agree-tos \
    --no-eff-email \
    -d $DOMAIN; then
    echo "✅ SSL certificate obtained successfully"
else
    echo "❌ Failed to obtain SSL certificate"
    echo "Please check certbot logs above"
    exit 1
fi
echo ""

# Verify certificate files
echo "🔍 Verifying certificate files..."
if docker-compose -f docker-compose.prod.yml exec -T nginx ls /etc/letsencrypt/live/$DOMAIN/fullchain.pem > /dev/null 2>&1; then
    echo "✅ Certificate files verified"
else
    echo "❌ Certificate files not found"
    exit 1
fi
echo ""

# Step 4: Switch back to SSL config
echo "📝 Step 4: Switching to SSL nginx config..."
cp nginx/default.conf.ssl nginx/default.conf
echo "✅ Switched to SSL config"
echo ""

# Step 5: Restart nginx with SSL config
echo "🔄 Step 5: Restarting nginx with SSL..."
docker-compose -f docker-compose.prod.yml restart nginx

# Wait for nginx to restart
echo "⏳ Waiting for nginx to restart..."
sleep 10

# Check if nginx is running
if ! docker-compose -f docker-compose.prod.yml ps | grep -q "nginx.*Up"; then
    echo "❌ Nginx failed to start with SSL config"
    docker-compose -f docker-compose.prod.yml logs nginx
    exit 1
fi
echo "✅ Nginx is running with SSL"
echo ""

# Test HTTPS access
echo "🔍 Testing HTTPS access..."
if curl -f -s -o /dev/null "https://$DOMAIN/health/"; then
    echo "✅ HTTPS access works"
else
    echo "⚠️  HTTPS access test failed, but this might be normal if DNS hasn't fully propagated"
fi
echo ""

echo "✅ SSL setup complete!"
echo "🌐 Your site should now be accessible at https://$DOMAIN"
echo ""
echo "Next steps:"
echo "1. Test the site: https://$DOMAIN"
echo "2. Check all containers: docker-compose -f docker-compose.prod.yml ps"
echo "3. View logs if needed: docker-compose -f docker-compose.prod.yml logs"
