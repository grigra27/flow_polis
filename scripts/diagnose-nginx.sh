#!/bin/bash

# Script to diagnose nginx issues on production server

set -e

echo "🔍 Diagnosing nginx issues..."
echo ""

# Check nginx container status
echo "📊 Nginx container status:"
echo "========================="
docker-compose -f docker-compose.prod.yml ps nginx
echo ""

# Check nginx logs
echo "📋 Nginx error logs (last 30 lines):"
echo "===================================="
docker-compose -f docker-compose.prod.yml logs nginx --tail 30
echo ""

# Check if SSL certificates exist
echo "🔐 Checking SSL certificates:"
echo "============================="
if [ -d "certbot/conf/live/onbr.site" ]; then
    echo "✅ Certificate directory exists"
    ls -la certbot/conf/live/onbr.site/ || echo "Cannot list certificate files"
else
    echo "❌ Certificate directory NOT found: certbot/conf/live/onbr.site"
    echo "This is likely why nginx is failing!"
fi
echo ""

# Check nginx config syntax
echo "🔧 Testing nginx configuration:"
echo "==============================="
docker-compose -f docker-compose.prod.yml exec -T nginx nginx -t 2>&1 || echo "Nginx config test failed"
echo ""

# Check if web container is accessible
echo "🌐 Testing connection to web container:"
echo "======================================="
docker-compose -f docker-compose.prod.yml exec -T nginx wget -q -O- http://web:8000/health/ 2>&1 || echo "Cannot connect to web container"
echo ""

echo "💡 Common issues and solutions:"
echo "================================"
echo "1. Missing SSL certificates:"
echo "   - Temporarily disable HTTPS in nginx/default.conf"
echo "   - Get certificates with certbot"
echo "   - Re-enable HTTPS"
echo ""
echo "2. Web container not responding:"
echo "   - Check web container logs: docker-compose -f docker-compose.prod.yml logs web"
echo "   - Check if gunicorn is running"
echo ""
echo "3. Nginx config syntax error:"
echo "   - Review nginx/default.conf"
echo "   - Test locally before deploying"
