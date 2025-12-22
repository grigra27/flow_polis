# Scripts Directory

This directory contains utility scripts for managing the Insurance Broker application deployment.

## Available Scripts

### migrate-database.sh

Automated database export script for server-to-server migration.

#### Purpose

Exports the PostgreSQL database from the old server (Digital Ocean) for migration to a new server (Timeweb Cloud). This script:
- Verifies SSH connectivity to the old server
- Checks database container status
- Gathers database statistics
- Creates a complete SQL dump
- Verifies backup integrity
- Creates checksums for data verification

#### Usage

**Basic usage (with defaults):**
```bash
./scripts/migrate-database.sh
```

**With custom parameters:**
```bash
OLD_SERVER_IP=64.227.75.233 \
OLD_SERVER_USER=root \
BACKUP_DIR=./backups \
./scripts/migrate-database.sh
```

#### Environment Variables

- `OLD_SERVER_IP` - IP address of old server (default: `64.227.75.233`)
- `OLD_SERVER_USER` - SSH user on old server (default: `root`)
- `BACKUP_DIR` - Directory for backup files (default: `./backups`)

#### Prerequisites

- SSH access to old server
- Docker and Docker Compose running on old server
- Database container running on old server
- Sufficient disk space for backup file

#### What It Does

1. **SSH Connection Check** - Verifies connectivity to old server
2. **Container Status Check** - Ensures database container is running
3. **Database Statistics** - Gathers table counts and row counts
4. **Backup Creation** - Creates SQL dump using pg_dump
5. **Integrity Verification** - Checks backup file size and content
6. **Checksum Creation** - Generates MD5 checksum for verification

#### Output

Creates two files in the backup directory:
- `insurance_broker_backup_YYYYMMDD_HHMMSS.sql` - Database dump
- `insurance_broker_backup_YYYYMMDD_HHMMSS.sql.md5` - Checksum file

#### Examples

```bash
# Export from default server
./scripts/migrate-database.sh

# Export from custom server
OLD_SERVER_IP=192.168.1.100 ./scripts/migrate-database.sh

# Export to custom directory
BACKUP_DIR=/mnt/backups ./scripts/migrate-database.sh
```

#### Related Documentation

See [docs/DATABASE_MIGRATION_GUIDE.md](../docs/DATABASE_MIGRATION_GUIDE.md) for complete migration guide.

### import-database.sh

Automated database import script for server-to-server migration.

#### Purpose

Imports a PostgreSQL database backup to the new server (Timeweb Cloud). This script:
- Verifies backup file integrity
- Checks Docker Compose installation
- Validates environment configuration
- Creates backup of existing database
- Imports database from backup file
- Verifies imported data
- Runs Django migrations

#### Usage

**Import from backup file:**
```bash
./scripts/import-database.sh insurance_broker_backup_20231204_120000.sql
```

#### Prerequisites

- Backup file from migrate-database.sh
- Docker and Docker Compose v1 installed
- `.env.prod` and `.env.prod.db` files configured
- `docker-compose.prod.yml` present
- Sufficient disk space

#### What It Does

1. **Checksum Verification** - Validates backup file integrity (if .md5 file present)
2. **Environment Check** - Verifies Docker Compose and configuration files
3. **Container Management** - Starts database container if not running
4. **Pre-Import Backup** - Creates backup of current database (if exists)
5. **Database Import** - Restores data from backup file
6. **Data Verification** - Checks table counts and key tables
7. **Django Migrations** - Runs migrations to ensure schema compatibility

#### Safety Features

- Creates automatic backup before import
- Verifies data integrity after import
- Checks for required environment files
- Validates backup file before import

#### Examples

```bash
# Import from backup file
cd ~/insurance_broker
./scripts/import-database.sh insurance_broker_backup_20231204_120000.sql

# Import will automatically:
# - Verify checksum if .md5 file exists
# - Backup current database
# - Import new data
# - Run migrations
# - Verify import success
```

#### Related Documentation

See [docs/DATABASE_MIGRATION_GUIDE.md](../docs/DATABASE_MIGRATION_GUIDE.md) for complete migration guide.

## Available Scripts

### init-letsencrypt.sh

Automated script for initializing Let's Encrypt SSL certificates.

#### Purpose

This script automates the entire process of obtaining and configuring SSL certificates for the application, including:
- Initial setup of nginx configuration
- Certificate obtainment from Let's Encrypt
- Configuration of automatic certificate renewal
- Verification of the setup

#### Usage

**Basic usage (production certificates):**
```bash
./scripts/init-letsencrypt.sh
```

**Testing with staging server:**
```bash
STAGING=1 ./scripts/init-letsencrypt.sh
```

#### Prerequisites

Before running the script, ensure:

1. **Environment files are configured:**
   ```bash
   cp .env.prod.example .env.prod
   cp .env.prod.db.example .env.prod.db
   # Edit these files with your actual values
   ```

2. **DNS is pointing to your server:**
   ```bash
   dig onbr.site
   # Should return your server's IP address
   ```

3. **Firewall allows ports 80 and 443:**
   ```bash
   sudo ufw status
   # Should show 80/tcp and 443/tcp as ALLOW
   ```

4. **Docker and Docker Compose are installed:**
   ```bash
   docker --version
   docker-compose --version
   ```

#### What It Does

The script performs these steps automatically:

1. **Dependency Check** - Verifies Docker and Docker Compose are available
2. **Certificate Check** - Checks if certificates already exist
3. **Directory Setup** - Creates required directories (certbot/conf, certbot/www)
4. **Configuration Backup** - Backs up current nginx configuration
5. **Initial Configuration** - Applies HTTP-only nginx config
6. **Service Startup** - Starts Docker services (db, redis, web, nginx)
7. **Certificate Request** - Obtains SSL certificate from Let's Encrypt
8. **Certificate Verification** - Verifies all certificate files were created
9. **SSL Configuration** - Restores SSL-enabled nginx configuration
10. **Nginx Reload** - Reloads nginx with new certificates
11. **Auto-Renewal Setup** - Starts certbot container for automatic renewal

#### Environment Variables

- `STAGING` - Set to `1` to use Let's Encrypt staging server (for testing)

#### Configuration

The script uses these default values (can be modified in the script):

```bash
DOMAIN="onbr.site"
WWW_DOMAIN="www.onbr.site"
EMAIL="admin@onbr.site"
COMPOSE_FILE="docker-compose.prod.yml"
```

#### Exit Codes

- `0` - Success
- `1` - Error occurred (check output for details)

#### Output

The script provides colored output for easy reading:
- **Green [INFO]** - Normal progress messages
- **Yellow [WARN]** - Warnings (non-fatal)
- **Red [ERROR]** - Errors (fatal)

#### Examples

**First-time setup:**
```bash
# Test with staging server first
STAGING=1 ./scripts/init-letsencrypt.sh

# If successful, run with production server
./scripts/init-letsencrypt.sh
```

**Renewing existing certificates:**
```bash
# The script will detect existing certificates and ask if you want to renew
./scripts/init-letsencrypt.sh
```

#### Troubleshooting

**Script fails with "Docker is not installed":**
- Install Docker: https://docs.docker.com/engine/install/

**Script fails with "DNS not pointing to this server":**
- Verify DNS configuration: `dig onbr.site`
- Wait for DNS propagation (can take up to 48 hours)

**Script fails with "Firewall blocking port 80":**
- Check firewall: `sudo ufw status`
- Allow port 80: `sudo ufw allow 80/tcp`

**Script fails with ACME challenge error:**
- Ensure port 80 is accessible from the internet
- Check nginx logs: `docker-compose -f docker-compose.prod.yml logs nginx`
- Try with staging server: `STAGING=1 ./scripts/init-letsencrypt.sh`

**Rate limit errors:**
- Let's Encrypt limits: 5 certificates per domain per week
- Use staging server for testing: `STAGING=1 ./scripts/init-letsencrypt.sh`
- Wait 7 days for rate limit to reset

#### Related Documentation

- [SSL Setup Guide](../nginx/SSL_SETUP.md) - Comprehensive SSL setup documentation
- [Docker Compose Reference](../DOCKER_COMPOSE_REFERENCE.md) - Docker Compose configuration details
- [Let's Encrypt Documentation](https://letsencrypt.org/docs/) - Official Let's Encrypt docs

#### Manual Alternative

If you prefer manual control, see the "Manual Certificate Obtainment" section in [SSL_SETUP.md](../nginx/SSL_SETUP.md).

### deploy.sh

Automated deployment script for the Insurance Broker application on Digital Ocean Droplet.

#### Purpose

This script automates the entire deployment process, including:
- Pulling latest Docker images
- Building application images
- Stopping old containers gracefully
- Starting new containers
- Running database migrations
- Collecting static files
- Performing comprehensive health checks
- Automatic rollback on failure

#### Usage

**Basic usage:**
```bash
./scripts/deploy.sh
```

**With custom configuration:**
```bash
APP_DIR=/path/to/app BACKUP_DIR=/path/to/backups ./scripts/deploy.sh
```

#### Prerequisites

Before running the script, ensure:

1. **You are in the application directory:**
   ```bash
   cd ~/insurance_broker
   ```

2. **Environment files are present:**
   - `.env.prod` - Production environment variables
   - `.env.prod.db` - Database environment variables

3. **Docker and Docker Compose are running:**
   ```bash
   docker ps
   docker-compose --version
   ```

4. **You have sufficient permissions:**
   - User should be in the `docker` group or use `sudo`

#### What It Does

The script performs these steps in order:

1. **Pre-deployment Checks**
   - Verifies docker-compose.prod.yml exists
   - Checks for .env.prod configuration
   - Creates backup directory

2. **Backup Current State**
   - Saves current image IDs
   - Records container state
   - Creates backup timestamp marker

3. **Pull Latest Images**
   - Pulls base images (postgres, redis, nginx, certbot)
   - Continues with cached versions if pull fails

4. **Build Application Images**
   - Builds web, celery_worker, and celery_beat images
   - Uses --no-cache for fresh builds

5. **Stop Old Containers**
   - Gracefully stops running containers (30s timeout)
   - Forces stop if graceful shutdown fails
   - Removes old containers and orphans

6. **Start New Containers**
   - Starts all services with docker-compose up -d
   - Respects service dependencies

7. **Wait for Services**
   - Waits 15 seconds for initialization
   - Monitors health checks for critical services

8. **Run Migrations**
   - Executes Django database migrations
   - Fails deployment if migrations fail

9. **Collect Static Files**
   - Runs collectstatic with --clear flag
   - Ensures fresh static files

10. **Comprehensive Health Checks**
    - Verifies all services are healthy
    - Tests application HTTP responses
    - Checks database connectivity
    - Verifies Celery connectivity

11. **Cleanup**
    - Removes dangling Docker images
    - Frees up disk space

12. **Display Summary**
    - Shows container status
    - Provides useful commands

#### Health Checks

The script performs multiple health checks:

**Service Health Checks:**
- PostgreSQL database (via Docker health check)
- Redis (via Docker health check)
- Web application (via Docker health check)
- Nginx (via Docker health check)
- Celery worker (via process check)
- Celery beat (via process check)

**Application Health Checks:**
- HTTP response test (admin login page)
- Database connectivity (Django check command)
- Celery connectivity (celery inspect ping)

#### Rollback on Failure

If any step fails, the script automatically:

1. Stops the failed deployment
2. Restores the previous container state
3. Starts containers with previous configuration
4. Verifies rollback success
5. Logs detailed error information

#### Environment Variables

- `APP_DIR` - Application directory (default: `~/insurance_broker`)
- `BACKUP_DIR` - Backup directory (default: `~/insurance_broker_backups`)

#### Configuration

The script uses these default values:

```bash
COMPOSE_FILE="docker-compose.prod.yml"
MAX_HEALTH_CHECK_ATTEMPTS=30
HEALTH_CHECK_INTERVAL=2
```

#### Exit Codes

- `0` - Deployment successful
- `1` - Deployment failed (rollback attempted)

#### Output

The script provides colored output:
- **Green [INFO]** - Normal progress messages
- **Yellow [WARN]** - Warnings (non-fatal)
- **Red [ERROR]** - Errors (triggers rollback)
- **Blue [STEP]** - Major deployment steps

#### Examples

**Standard deployment:**
```bash
cd ~/insurance_broker
./scripts/deploy.sh
```

**Deployment with custom backup location:**
```bash
cd ~/insurance_broker
BACKUP_DIR=/mnt/backups ./scripts/deploy.sh
```

**View deployment logs:**
```bash
# During deployment, logs are shown in real-time
# After deployment, view service logs:
docker-compose -f docker-compose.prod.yml logs -f web
```

#### Troubleshooting

**Script fails with "docker-compose.prod.yml not found":**
- Ensure you're in the application root directory
- Run: `cd ~/insurance_broker`

**Script fails with ".env.prod file not found":**
- Create environment file: `cp .env.prod.example .env.prod`
- Edit with actual values: `nano .env.prod`

**Health checks fail:**
- Check service logs: `docker-compose -f docker-compose.prod.yml logs [service]`
- Verify environment variables are correct
- Ensure database credentials match

**Migrations fail:**
- Check database connectivity
- Review migration logs in output
- Manually run: `docker-compose -f docker-compose.prod.yml exec web python manage.py migrate`

**Rollback fails:**
- Check Docker daemon status: `systemctl status docker`
- Manually start services: `docker-compose -f docker-compose.prod.yml up -d`
- Review logs for specific errors

**Out of disk space:**
- Clean up old images: `docker system prune -a`
- Check disk usage: `df -h`
- Remove old backups: `rm -rf ~/insurance_broker_backups/old_*`

#### Integration with GitHub Actions

This script is designed to be called from GitHub Actions workflow:

```yaml
- name: Deploy on server
  run: |
    ssh user@host 'cd ~/insurance_broker && ./scripts/deploy.sh'
```

The GitHub Actions workflow (`.github/workflows/deploy.yml`) handles:
- Code checkout and file transfer
- SSH connection setup
- Calling this deployment script
- Handling deployment failures

#### Related Documentation

- [GitHub Actions Workflow](../.github/workflows/deploy.yml) - CI/CD pipeline
- [Docker Compose Reference](../DOCKER_COMPOSE_REFERENCE.md) - Service configuration
- [Deployment Guide](../docs/DEPLOYMENT.md) - Full deployment documentation

#### Manual Deployment Steps

If you prefer manual control instead of using this script:

```bash
# Pull images
docker-compose -f docker-compose.prod.yml pull

# Build images
docker-compose -f docker-compose.prod.yml build

# Stop old containers
docker-compose -f docker-compose.prod.yml down

# Start new containers
docker-compose -f docker-compose.prod.yml up -d

# Run migrations
docker-compose -f docker-compose.prod.yml exec web python manage.py migrate

# Collect static
docker-compose -f docker-compose.prod.yml exec web python manage.py collectstatic --noinput

# Check status
docker-compose -f docker-compose.prod.yml ps
```

### backup-db.sh

Automated PostgreSQL database backup script.

#### Purpose

Creates timestamped backups of the PostgreSQL database with automatic compression, verification, and cleanup of old backups.

#### Usage

**Create a backup:**
```bash
./scripts/backup-db.sh
```

**List existing backups:**
```bash
./scripts/backup-db.sh --list
```

**Verify backup integrity:**
```bash
./scripts/backup-db.sh --verify ~/insurance_broker_backups/database/db_backup_20240115_020000.sql.gz
```

**Clean up old backups:**
```bash
./scripts/backup-db.sh --cleanup
```

**Custom retention period:**
```bash
RETENTION_DAYS=14 ./scripts/backup-db.sh
```

#### Environment Variables

- `COMPOSE_FILE` - Docker compose file (default: `docker-compose.prod.yml`)
- `BACKUP_DIR` - Backup directory (default: `~/insurance_broker_backups/database`)
- `DB_CONTAINER` - Database container name (default: `insurance_broker_db`)
- `DB_NAME` - Database name (default: `insurance_broker_prod`)
- `DB_USER` - Database user (default: `postgres`)
- `RETENTION_DAYS` - Days to keep backups (default: `7`)

#### Related Documentation

See [docs/BACKUP_RESTORE.md](../docs/BACKUP_RESTORE.md) for complete backup and restore guide.

### restore-db.sh

Automated PostgreSQL database restore script.

#### Purpose

Restores the database from backup files with automatic pre-restore backup, service management, and rollback on failure.

#### Usage

**Interactive restore (recommended):**
```bash
./scripts/restore-db.sh --interactive
```

**Restore from latest backup:**
```bash
./scripts/restore-db.sh --latest
```

**Restore from specific file:**
```bash
./scripts/restore-db.sh --file ~/insurance_broker_backups/database/db_backup_20240115_020000.sql.gz
```

**List available backups:**
```bash
./scripts/restore-db.sh --list
```

#### Safety Features

- Creates pre-restore backup automatically
- Stops application services before restore
- Verifies database after restore
- Automatic rollback on failure
- Restarts services after completion

#### Related Documentation

See [docs/BACKUP_RESTORE.md](../docs/BACKUP_RESTORE.md) for complete backup and restore guide.

### backup-media.sh

Automated media files backup script.

#### Purpose

Creates timestamped backups of user-uploaded media files with automatic compression and cleanup.

#### Usage

**Create a backup:**
```bash
./scripts/backup-media.sh
```

**List existing backups:**
```bash
./scripts/backup-media.sh --list
```

**Verify backup integrity:**
```bash
./scripts/backup-media.sh --verify ~/insurance_broker_backups/media/media_backup_20240115_030000.tar.gz
```

**Clean up old backups:**
```bash
./scripts/backup-media.sh --cleanup
```

#### Environment Variables

- `COMPOSE_FILE` - Docker compose file (default: `docker-compose.prod.yml`)
- `BACKUP_DIR` - Backup directory (default: `~/insurance_broker_backups/media`)
- `MEDIA_VOLUME` - Media volume name (default: `insurance_broker_media_volume`)
- `RETENTION_DAYS` - Days to keep backups (default: `7`)

#### Related Documentation

See [docs/BACKUP_RESTORE.md](../docs/BACKUP_RESTORE.md) for complete backup and restore guide.

### setup-backup-cron.sh

Automated cron job setup for scheduled backups.

#### Purpose

Configures cron jobs for automated daily backups of database and media files.

#### Usage

```bash
./scripts/setup-backup-cron.sh
```

#### What It Does

Sets up the following cron jobs:
- Database backup: Daily at 2:00 AM
- Media backup: Daily at 3:00 AM
- Cleanup old backups: Weekly on Sunday at 4:00 AM

#### Prerequisites

- Backup scripts must be present and executable
- Application directory must be accessible
- User must have permission to modify crontab

#### Related Documentation

See [docs/BACKUP_RESTORE.md](../docs/BACKUP_RESTORE.md) for complete backup and restore guide.

### Telegram Integration for Backups

#### telegram-config.sh

Configuration file for Telegram bot credentials and settings.

**Configuration:**
- `TELEGRAM_BOT_TOKEN` - Bot token from @BotFather
- `TELEGRAM_CHAT_ID` - Chat or channel ID for notifications
- `TELEGRAM_ENABLED` - Enable/disable notifications (true/false)
- `TELEGRAM_UPLOAD_FILES` - Enable/disable file uploads (true/false)
- `TELEGRAM_MAX_FILE_SIZE` - Maximum file size for upload in MB (default: 45)

#### telegram-notify.sh

Core Telegram notification functions for backup scripts.

**Purpose:**
Provides functions to send messages and files to Telegram.

**Usage:**

```bash
# Test Telegram connection
./scripts/telegram-notify.sh test

# Send a test message
./scripts/telegram-notify.sh send "Test message"

# Upload a test file
./scripts/telegram-notify.sh upload /path/to/file.txt "Test file"
```

**Functions:**
- `send_telegram_message` - Send text messages with HTML formatting
- `send_telegram_file` - Upload files to Telegram (up to 50MB)
- `notify_backup_start` - Send backup start notification
- `notify_backup_success` - Send backup success notification with file
- `notify_backup_error` - Send backup error notification
- `notify_cleanup_result` - Send cleanup results notification
- `test_telegram_connection` - Test Telegram bot connection

#### backup-db-telegram.sh

Database backup script with Telegram notifications.

**Purpose:**
Same as backup-db.sh but with integrated Telegram notifications and file uploads.

**Usage:**

```bash
# Create backup with Telegram notifications
./scripts/backup-db-telegram.sh

# Test Telegram connection
./scripts/backup-db-telegram.sh --test-telegram

# List backups
./scripts/backup-db-telegram.sh --list

# Cleanup old backups
./scripts/backup-db-telegram.sh --cleanup
```

**Notifications:**
- 🔄 Backup start notification
- ✅ Backup success with file upload
- ❌ Error notifications with details
- 🧹 Cleanup results

#### backup-media-telegram.sh

Media files backup script with Telegram notifications.

**Purpose:**
Same as backup-media.sh but with integrated Telegram notifications and file uploads.

**Usage:**

```bash
# Create backup with Telegram notifications
./scripts/backup-media-telegram.sh

# Test Telegram connection
./scripts/backup-media-telegram.sh --test-telegram

# List backups
./scripts/backup-media-telegram.sh --list

# Cleanup old backups
./scripts/backup-media-telegram.sh --cleanup
```

**Notifications:**
- 🔄 Backup start notification
- ✅ Backup success with file upload
- ❌ Error notifications with details
- 🧹 Cleanup results

#### Setting Up Telegram Backups

**Step 1: Create Telegram Bot**
1. Find @BotFather in Telegram
2. Send `/newbot` command
3. Follow instructions to create bot
4. Save the bot token (keep it secure!)

**Step 2: Get Chat ID**
1. Create a private channel for backups
2. Add bot as administrator
3. Send a message to the channel
4. Get chat ID from `https://api.telegram.org/bot<TOKEN>/getUpdates`

**Step 3: Configure Securely**
Use the setup script for secure configuration:
```bash
./scripts/setup-telegram.sh
```

This script will:
- Prompt for bot token and chat ID
- Update your `.env.prod` file securely
- Test the Telegram connection
- Provide next steps

**Manual Configuration (Alternative):**
1. Edit `.env.prod` file (NOT committed to Git)
2. Add Telegram variables:
   ```bash
   TELEGRAM_BOT_TOKEN=your-bot-token-here
   TELEGRAM_CHAT_ID=your-chat-id-here
   TELEGRAM_ENABLED=true
   TELEGRAM_UPLOAD_FILES=true
   TELEGRAM_MAX_FILE_SIZE=45
   ```

**Step 4: Test**
```bash
./scripts/telegram-notify.sh test
```

**Step 5: Update Cron Jobs**
Replace backup scripts in crontab with Telegram versions:
```bash
# Edit crontab
crontab -e

# Replace:
# /path/to/backup-db.sh
# With:
# /path/to/backup-db-telegram.sh

# Replace:
# /path/to/backup-media.sh
# With:
# /path/to/backup-media-telegram.sh
```

**Security Notes:**
- Bot token and chat ID are stored in `.env.prod` (not in Git)
- Use environment variables for production deployment
- Never commit credentials to version control
- The setup script helps configure credentials securely

### view-logs.sh

Convenient script for viewing Docker container logs with filtering and formatting options.

#### Purpose

Provides a user-friendly interface for viewing logs from Docker containers with support for:
- Viewing logs from all services or specific services
- Following logs in real-time
- Limiting number of lines
- Adding timestamps
- Support for both development and production environments

#### Usage

**View logs from all services:**
```bash
./scripts/view-logs.sh
```

**Follow logs from specific service:**
```bash
./scripts/view-logs.sh web -f
```

**Show last 50 lines with timestamps:**
```bash
./scripts/view-logs.sh celery_worker -n 50 -t
```

**Follow all logs with timestamps:**
```bash
./scripts/view-logs.sh all -f -t
```

**View logs in development environment:**
```bash
./scripts/view-logs.sh web --dev
```

#### Available Services

- `web` - Django application logs
- `db` - PostgreSQL database logs
- `redis` - Redis cache logs
- `celery_worker` - Celery worker logs
- `celery_beat` - Celery beat scheduler logs
- `nginx` - Nginx reverse proxy logs
- `certbot` - SSL certificate management logs
- `all` - All services logs (default)

#### Options

- `-f, --follow` - Follow log output (like tail -f)
- `-n, --lines NUM` - Number of lines to show (default: 100)
- `-t, --timestamps` - Show timestamps
- `--dev` - Use development compose file
- `-h, --help` - Show help message

#### Examples

```bash
# Show last 100 lines from all services
./scripts/view-logs.sh

# Follow web service logs
./scripts/view-logs.sh web -f

# Show last 50 lines from celery worker
./scripts/view-logs.sh celery_worker -n 50

# Follow all logs with timestamps
./scripts/view-logs.sh all -f -t

# Show nginx logs from dev environment
./scripts/view-logs.sh nginx --dev
```

#### Related Documentation

See [docs/MONITORING.md](../docs/MONITORING.md) for complete monitoring and logging guide.

### check-dns.sh

DNS propagation checker script for domain configuration.

#### Purpose

Checks DNS propagation status for the domain onbr.site, providing:
- DNS record verification from multiple DNS servers
- Propagation status across global DNS infrastructure
- HTTP/HTTPS availability testing
- TTL information
- Nameserver verification

#### Usage

**Basic check:**
```bash
./scripts/check-dns.sh onbr.site
```

**Check with expected IP:**
```bash
./scripts/check-dns.sh onbr.site 123.45.67.89
```

#### What It Checks

**DNS Records:**
- Root domain (onbr.site) A record
- WWW subdomain (www.onbr.site) A record
- Checks against multiple public DNS servers:
  - Google DNS (8.8.8.8, 8.8.4.4)
  - Cloudflare DNS (1.1.1.1, 1.0.0.1)
  - OpenDNS (208.67.222.222, 208.67.220.220)
  - System DNS

**Additional Checks:**
- NS (nameserver) records
- TTL (Time To Live) values
- HTTP availability
- HTTPS availability (if SSL configured)

#### Output

The script provides colored output:
- **Green ✓** - DNS record found and correct
- **Yellow ⚠** - DNS record found but doesn't match expected IP
- **Red ✗** - DNS record not found

**Propagation Status:**
- Shows percentage of successful DNS checks
- Provides recommendations based on propagation status
- Lists online tools for additional verification

#### Examples

```bash
# Check DNS propagation
./scripts/check-dns.sh onbr.site

# Check with expected IP address
./scripts/check-dns.sh onbr.site 167.99.123.45

# Continuous monitoring (every 30 seconds)
watch -n 30 "./scripts/check-dns.sh onbr.site"
```

#### Troubleshooting

**DNS not propagating:**
- Wait 15-60 minutes for A records
- Wait 24-48 hours for NS records
- Clear local DNS cache
- Check with multiple DNS servers

**Shows old IP address:**
- Check TTL - cache may not have expired
- Verify DNS records are correct at provider
- Wait for TTL period to pass

**NXDOMAIN error:**
- Verify domain is added to DNS provider
- Check NS records are correct
- Ensure domain is not expired

#### Related Documentation

- [DNS Setup Guide](../docs/DNS_SETUP.md) - Complete DNS configuration guide
- [DNS Quick Reference](../docs/DNS_QUICK_REFERENCE.md) - Quick DNS commands
- [Deployment Guide](../docs/DEPLOYMENT.md) - Full deployment documentation

### monitor-health.sh

Automated health monitoring script for Docker containers.

#### Purpose

Monitors the health status of all Docker containers and provides:
- Health check status for all services
- Disk usage monitoring
- Docker disk usage statistics
- Optional email alerts
- Exit codes for automation/cron

#### Usage

**Check health status:**
```bash
./scripts/monitor-health.sh
```

**With email alerts:**
```bash
./scripts/monitor-health.sh --alert-email admin@example.com
```

**For development environment:**
```bash
./scripts/monitor-health.sh --dev
```

#### What It Checks

**Service Health:**
- Container running status
- Health check status (healthy/unhealthy/starting)
- Service availability

**System Health:**
- Disk usage percentage
- Docker disk usage (images, containers, volumes)
- Alerts when disk usage > 80%

#### Output

The script provides colored output:
- **Green ✓** - Service is healthy
- **Red ✗** - Service is down or unhealthy
- **Yellow ⟳** - Service is starting
- **Yellow ?** - Unknown status

#### Exit Codes

- `0` - All services are healthy
- `1` - One or more services are unhealthy or down

#### Examples

```bash
# Manual health check
./scripts/monitor-health.sh

# Automated monitoring with alerts
./scripts/monitor-health.sh --alert-email ops@example.com

# Add to cron for regular monitoring
# */5 * * * * /path/to/scripts/monitor-health.sh --alert-email admin@example.com
```

#### Automation

Add to crontab for regular monitoring:

```bash
# Check health every 5 minutes
*/5 * * * * cd /path/to/app && ./scripts/monitor-health.sh --alert-email admin@example.com

# Or create a wrapper script
cat > /usr/local/bin/check-docker-health.sh << 'EOF'
#!/bin/bash
cd /path/to/insurance_broker
./scripts/monitor-health.sh --alert-email admin@example.com
EOF

chmod +x /usr/local/bin/check-docker-health.sh
```

#### Related Documentation

See [docs/MONITORING.md](../docs/MONITORING.md) for complete monitoring and logging guide.

## Contributing

When adding new scripts:
1. Make them executable: `chmod +x scripts/script-name.sh`
2. Add proper error handling and logging
3. Document usage in this README
4. Use consistent output formatting (colored messages)
5. Include help text (`--help` flag)
