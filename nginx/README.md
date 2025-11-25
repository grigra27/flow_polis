# Nginx Configuration

This directory contains the Nginx configuration files for the Insurance Broker application.

## Files

- **default.conf**: Main server configuration with SSL/TLS settings, reverse proxy, and static file serving
- **nginx.conf**: Global Nginx configuration (optional, for custom global settings)

## Features

### HTTP to HTTPS Redirect
All HTTP traffic on port 80 is automatically redirected to HTTPS on port 443, except for Let's Encrypt ACME challenge requests.

### SSL/TLS Configuration
- **Protocols**: TLS 1.2 and TLS 1.3 only
- **Ciphers**: Modern, secure cipher suites
- **HSTS**: Enabled with 1-year max-age
- **OCSP Stapling**: Enabled for improved SSL performance

### Static and Media Files
- **Static files** (`/static/`): Served directly with 30-day cache
- **Media files** (`/media/`): Served directly with 7-day cache

### Reverse Proxy
All dynamic requests are proxied to the Django application running on Gunicorn (web:8000).

### Let's Encrypt Support
The `/.well-known/acme-challenge/` location is configured to serve ACME challenge files for SSL certificate validation.

## SSL Certificate Setup

Before enabling HTTPS, you need to obtain SSL certificates from Let's Encrypt:

1. **Initial setup** (HTTP only):
   - Comment out the HTTPS server block in `default.conf`
   - Start only the HTTP server to handle ACME challenges

2. **Obtain certificate**:
   ```bash
   docker-compose run --rm certbot certonly --webroot \
     --webroot-path=/var/www/certbot \
     -d onbr.site -d www.onbr.site \
     --email admin@onbr.site \
     --agree-tos \
     --no-eff-email
   ```

3. **Enable HTTPS**:
   - Uncomment the HTTPS server block
   - Restart Nginx: `docker-compose restart nginx`

## Testing Configuration

Test the Nginx configuration syntax:
```bash
docker-compose exec nginx nginx -t
```

Reload Nginx after configuration changes:
```bash
docker-compose exec nginx nginx -s reload
```

## Security Headers

The configuration includes several security headers:
- **Strict-Transport-Security**: Forces HTTPS for 1 year
- **X-Frame-Options**: Prevents clickjacking
- **X-Content-Type-Options**: Prevents MIME sniffing
- **X-XSS-Protection**: Enables XSS filter

## Performance Optimizations

- **Gzip compression**: Enabled for text and application files
- **Static file caching**: Long cache times with immutable flag
- **Connection keep-alive**: Reduces connection overhead
- **Buffering**: Optimized for typical Django responses

## Troubleshooting

### 502 Bad Gateway
- Check if the web container is running: `docker-compose ps web`
- Check web container logs: `docker-compose logs web`
- Verify the upstream configuration points to `web:8000`

### SSL Certificate Errors
- Verify certificates exist: `ls -la certbot/conf/live/onbr.site/`
- Check certificate expiry: `docker-compose exec nginx openssl x509 -in /etc/letsencrypt/live/onbr.site/fullchain.pem -noout -dates`
- Renew certificate: `docker-compose run --rm certbot renew`

### Static Files Not Loading
- Verify static files are collected: `docker-compose exec web python manage.py collectstatic --noinput`
- Check volume mounts: `docker-compose exec nginx ls -la /app/staticfiles/`
- Check Nginx logs: `docker-compose logs nginx`
