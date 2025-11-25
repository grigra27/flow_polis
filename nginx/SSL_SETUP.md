# SSL Certificate Setup Guide

This guide explains how to set up SSL certificates for the Insurance Broker application using Let's Encrypt.

## Prerequisites

- Domain name (onbr.site) pointing to your server's IP address
- Docker and Docker Compose installed
- Ports 80 and 443 open in firewall
- Environment files configured (.env.prod and .env.prod.db)

## Quick Start (Recommended)

The easiest way to set up SSL certificates is using the automated initialization script:

```bash
./scripts/init-letsencrypt.sh
```

This script handles everything automatically. Skip to the [Using init-letsencrypt.sh Script](#using-init-letsencryptsh-script) section for details.

## Initial Deployment (Without SSL)

For the first deployment, you can start without SSL and add it later:

1. **Use the initial configuration**:
   ```bash
   cp nginx/default.conf.initial nginx/default.conf
   ```

2. **Start the services**:
   ```bash
   docker-compose -f docker-compose.prod.yml up -d
   ```

3. **Verify the application is accessible** via HTTP:
   ```bash
   curl http://onbr.site
   ```

## Obtaining SSL Certificates

### Using init-letsencrypt.sh Script (Recommended)

The automated script handles the entire SSL setup process including certificate obtainment, nginx configuration, and automatic renewal setup.

#### Prerequisites

1. **Ensure environment files are configured**:
   ```bash
   # Copy and edit the environment files
   cp .env.prod.example .env.prod
   cp .env.prod.db.example .env.prod.db
   # Edit these files with your actual production values
   ```

2. **Verify DNS is pointing to your server**:
   ```bash
   dig onbr.site
   # Should return your server's IP address
   ```

#### Running the Script

1. **For production (real certificates)**:
   ```bash
   ./scripts/init-letsencrypt.sh
   ```

2. **For testing (staging certificates)**:
   ```bash
   STAGING=1 ./scripts/init-letsencrypt.sh
   ```
   
   Using staging is recommended for testing to avoid hitting Let's Encrypt rate limits (5 certificates per domain per week).

#### What the Script Does

The script performs the following steps automatically:

1. **Checks dependencies** - Verifies Docker and Docker Compose are installed
2. **Checks for existing certificates** - Asks if you want to renew if they exist
3. **Creates required directories** - Sets up certbot/conf and certbot/www
4. **Backs up nginx configuration** - Saves current config with timestamp
5. **Applies initial HTTP-only configuration** - Temporarily disables SSL
6. **Starts Docker services** - Brings up db, redis, web, and nginx
7. **Obtains SSL certificate** - Requests certificate from Let's Encrypt
8. **Verifies certificate files** - Checks that all required files were created
9. **Restores SSL configuration** - Switches nginx back to HTTPS mode
10. **Reloads nginx** - Applies the new SSL configuration
11. **Sets up automatic renewal** - Starts the certbot container for auto-renewal

#### Script Output

The script provides colored output:
- **Green [INFO]** - Normal progress messages
- **Yellow [WARN]** - Warnings that don't stop execution
- **Red [ERROR]** - Errors that stop execution

#### Troubleshooting the Script

If the script fails:

1. **Check DNS configuration**:
   ```bash
   nslookup onbr.site
   dig onbr.site
   ```

2. **Verify port 80 is accessible**:
   ```bash
   curl http://onbr.site/.well-known/acme-challenge/test
   ```

3. **Check Docker services are running**:
   ```bash
   docker-compose -f docker-compose.prod.yml ps
   ```

4. **View detailed logs**:
   ```bash
   docker-compose -f docker-compose.prod.yml logs nginx
   docker-compose -f docker-compose.prod.yml logs certbot
   ```

5. **Try with staging server first**:
   ```bash
   STAGING=1 ./scripts/init-letsencrypt.sh
   ```

### Manual Certificate Obtainment

If you prefer manual control over each step:

1. **Start services with initial configuration** (HTTP only):
   ```bash
   cp nginx/default.conf.initial nginx/default.conf
   docker-compose -f docker-compose.prod.yml up -d
   ```

2. **Obtain the certificate**:
   ```bash
   docker-compose -f docker-compose.prod.yml run --rm certbot certonly \
     --webroot \
     --webroot-path=/var/www/certbot \
     --email admin@onbr.site \
     --agree-tos \
     --no-eff-email \
     -d onbr.site \
     -d www.onbr.site
   ```

3. **Verify certificates were created**:
   ```bash
   ls -la certbot/conf/live/onbr.site/
   ```

   You should see:
   - `fullchain.pem` - Full certificate chain
   - `privkey.pem` - Private key
   - `chain.pem` - Certificate chain
   - `cert.pem` - Certificate only

4. **Restore SSL-enabled nginx configuration**:
   ```bash
   # If you have the original in git
   git checkout nginx/default.conf
   
   # Or copy from backup
   cp nginx/default.conf.backup.YYYYMMDD_HHMMSS nginx/default.conf
   ```

5. **Test and reload nginx**:
   ```bash
   docker-compose -f docker-compose.prod.yml exec nginx nginx -t
   docker-compose -f docker-compose.prod.yml restart nginx
   ```

## Enabling HTTPS

After obtaining certificates, ensure nginx is using the SSL configuration:

1. **Verify nginx configuration includes SSL**:
   ```bash
   grep "ssl_certificate" nginx/default.conf
   ```

2. **Test nginx configuration**:
   ```bash
   docker-compose -f docker-compose.prod.yml exec nginx nginx -t
   ```

3. **Reload nginx**:
   ```bash
   docker-compose -f docker-compose.prod.yml exec nginx nginx -s reload
   ```

   Or restart the container:
   ```bash
   docker-compose -f docker-compose.prod.yml restart nginx
   ```

4. **Test HTTPS**:
   ```bash
   curl https://onbr.site
   ```

5. **Verify HTTP to HTTPS redirect**:
   ```bash
   curl -I http://onbr.site
   # Should return 301 redirect to https://
   ```

## Certificate Renewal

Let's Encrypt certificates expire after 90 days. The system is configured for automatic renewal.

### Automatic Renewal (Configured by Default)

The certbot container runs continuously and checks for renewal twice daily:

```yaml
certbot:
  image: certbot/certbot
  volumes:
    - ./certbot/conf:/etc/letsencrypt
    - ./certbot/www:/var/www/certbot
  entrypoint: "/bin/sh -c 'trap exit TERM; while :; do certbot renew --quiet; sleep 12h & wait $${!}; done;'"
```

**Verify certbot is running**:
```bash
docker-compose -f docker-compose.prod.yml ps certbot
```

**Check certbot logs**:
```bash
docker-compose -f docker-compose.prod.yml logs certbot
```

### Manual Renewal

To manually renew certificates:

1. **Renew certificates**:
   ```bash
   docker-compose -f docker-compose.prod.yml run --rm certbot renew
   ```

2. **Reload nginx** to use new certificates:
   ```bash
   docker-compose -f docker-compose.prod.yml exec nginx nginx -s reload
   ```

### Dry Run (Test Renewal)

Test the renewal process without actually renewing:

```bash
docker-compose -f docker-compose.prod.yml run --rm certbot renew --dry-run
```

### Check Certificate Status

View certificate information and expiry dates:

```bash
docker-compose -f docker-compose.prod.yml run --rm certbot certificates
```

## Testing SSL Configuration

### Check Certificate Expiry

```bash
docker-compose -f docker-compose.prod.yml exec nginx \
  openssl x509 -in /etc/letsencrypt/live/onbr.site/fullchain.pem -noout -dates
```

### Test SSL Configuration Online

Use SSL Labs to test your SSL configuration:
https://www.ssllabs.com/ssltest/analyze.html?d=onbr.site

Expected grade: A or A+

### Verify TLS Version

```bash
# Test TLS 1.2
openssl s_client -connect onbr.site:443 -tls1_2

# Test TLS 1.3
openssl s_client -connect onbr.site:443 -tls1_3
```

### Check Security Headers

```bash
curl -I https://onbr.site
```

Should include:
- `Strict-Transport-Security: max-age=31536000; includeSubDomains`
- `X-Frame-Options: SAMEORIGIN`
- `X-Content-Type-Options: nosniff`
- `X-XSS-Protection: 1; mode=block`

## Troubleshooting

### Certificate Not Found Error

If Nginx fails to start with certificate errors:

1. **Check if certificates exist**:
   ```bash
   ls -la certbot/conf/live/onbr.site/
   ```

2. **Use initial configuration** without SSL:
   ```bash
   cp nginx/default.conf.initial nginx/default.conf
   docker-compose -f docker-compose.prod.yml restart nginx
   ```

3. **Obtain certificates** again:
   ```bash
   ./scripts/init-letsencrypt.sh
   ```

### ACME Challenge Failed

If certificate issuance fails with ACME challenge errors:

1. **Verify DNS** is pointing to your server:
   ```bash
   dig onbr.site
   nslookup onbr.site
   ```

2. **Check port 80 is accessible** from the internet:
   ```bash
   # From another machine or online tool
   curl http://YOUR_SERVER_IP/.well-known/acme-challenge/test
   ```

3. **Check firewall rules**:
   ```bash
   sudo ufw status
   # Ports 80 and 443 should be open
   ```

4. **Check Nginx logs**:
   ```bash
   docker-compose -f docker-compose.prod.yml logs nginx
   ```

5. **Verify certbot directory permissions**:
   ```bash
   ls -la certbot/www/
   # Should be readable by nginx container
   ```

6. **Test with staging server**:
   ```bash
   STAGING=1 ./scripts/init-letsencrypt.sh
   ```

### Certificate Renewal Failed

If automatic renewal fails:

1. **Check certbot logs**:
   ```bash
   docker-compose -f docker-compose.prod.yml logs certbot
   ```

2. **Try manual renewal** with verbose output:
   ```bash
   docker-compose -f docker-compose.prod.yml run --rm certbot renew --dry-run
   ```

3. **Check certificate expiry**:
   ```bash
   docker-compose -f docker-compose.prod.yml run --rm certbot certificates
   ```

4. **Verify certbot container is running**:
   ```bash
   docker-compose -f docker-compose.prod.yml ps certbot
   ```

5. **Restart certbot container**:
   ```bash
   docker-compose -f docker-compose.prod.yml restart certbot
   ```

### Rate Limit Errors

Let's Encrypt has rate limits:
- 5 certificates per domain per week
- 50 certificates per registered domain per week

If you hit rate limits:

1. **Wait for the rate limit to reset** (usually 7 days)
2. **Use staging server for testing**:
   ```bash
   STAGING=1 ./scripts/init-letsencrypt.sh
   ```
3. **Check rate limit status**: https://crt.sh/?q=onbr.site

### Nginx Configuration Test Failed

If nginx configuration test fails:

1. **Check syntax**:
   ```bash
   docker-compose -f docker-compose.prod.yml exec nginx nginx -t
   ```

2. **View detailed error**:
   ```bash
   docker-compose -f docker-compose.prod.yml logs nginx
   ```

3. **Verify certificate paths** in nginx/default.conf:
   ```nginx
   ssl_certificate /etc/letsencrypt/live/onbr.site/fullchain.pem;
   ssl_certificate_key /etc/letsencrypt/live/onbr.site/privkey.pem;
   ```

4. **Check certificate files exist** in container:
   ```bash
   docker-compose -f docker-compose.prod.yml exec nginx ls -la /etc/letsencrypt/live/onbr.site/
   ```

## Security Best Practices

1. **Keep certificates secure**: Never commit certificates to git (already in .gitignore)
2. **Monitor expiry**: Set up alerts for certificate expiration (30 days before)
3. **Use strong ciphers**: The configuration uses modern, secure ciphers
4. **Enable HSTS**: Already configured with 1-year max-age
5. **Regular updates**: Keep Nginx and certbot images updated
6. **Backup certificates**: Include certbot/conf in your backup strategy
7. **Test renewals**: Periodically test renewal with --dry-run
8. **Monitor logs**: Regularly check certbot logs for renewal issues

## Certificate Backup and Restore

### Backup Certificates

```bash
# Backup entire certbot directory
tar -czf certbot-backup-$(date +%Y%m%d).tar.gz certbot/

# Or just the certificates
tar -czf certs-backup-$(date +%Y%m%d).tar.gz certbot/conf/
```

### Restore Certificates

```bash
# Extract backup
tar -xzf certbot-backup-YYYYMMDD.tar.gz

# Restart nginx to use restored certificates
docker-compose -f docker-compose.prod.yml restart nginx
```

## Additional Resources

- [Let's Encrypt Documentation](https://letsencrypt.org/docs/)
- [Certbot Documentation](https://certbot.eff.org/docs/)
- [Nginx SSL Configuration](https://nginx.org/en/docs/http/configuring_https_servers.html)
- [Mozilla SSL Configuration Generator](https://ssl-config.mozilla.org/)
- [SSL Labs Server Test](https://www.ssllabs.com/ssltest/)
- [Let's Encrypt Rate Limits](https://letsencrypt.org/docs/rate-limits/)

## Summary

The recommended workflow for SSL setup is:

1. Configure environment files (.env.prod, .env.prod.db)
2. Ensure DNS points to your server
3. Run `./scripts/init-letsencrypt.sh`
4. Verify HTTPS is working
5. Let automatic renewal handle certificate updates

For any issues, check the troubleshooting section or review the logs.
