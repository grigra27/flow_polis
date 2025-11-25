# Backup and Restore Guide

This guide explains how to backup and restore the Insurance Broker application data, including the PostgreSQL database and user-uploaded media files.

## Table of Contents

- [Overview](#overview)
- [Backup Scripts](#backup-scripts)
- [Database Backup](#database-backup)
- [Database Restore](#database-restore)
- [Media Files Backup](#media-files-backup)
- [Automated Backups](#automated-backups)
- [Backup Storage](#backup-storage)
- [Disaster Recovery](#disaster-recovery)
- [Troubleshooting](#troubleshooting)

## Overview

The application provides three main backup scripts:

1. **backup-db.sh** - Backs up the PostgreSQL database
2. **restore-db.sh** - Restores the database from a backup
3. **backup-media.sh** - Backs up user-uploaded media files

All scripts are located in the `scripts/` directory and are designed to work with the Docker-based production deployment.

### Backup Strategy

- **Database backups**: Daily at 2:00 AM (via cron)
- **Media backups**: Daily at 3:00 AM (via cron)
- **Retention period**: 7 days by default (configurable)
- **Backup location**: `~/insurance_broker_backups/` by default

## Backup Scripts

### Prerequisites

- Docker and Docker Compose must be installed
- The application containers must be running
- Sufficient disk space for backups

### Environment Variables

All scripts support the following environment variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `COMPOSE_FILE` | `docker-compose.prod.yml` | Docker Compose file to use |
| `BACKUP_DIR` | `~/insurance_broker_backups/` | Directory for storing backups |
| `RETENTION_DAYS` | `7` | Number of days to keep backups |
| `DB_CONTAINER` | `insurance_broker_db` | Database container name |
| `DB_NAME` | `insurance_broker_prod` | Database name |
| `DB_USER` | `postgres` | Database user |

## Database Backup

### Manual Backup

To create a manual database backup:

```bash
cd /path/to/insurance_broker
./scripts/backup-db.sh
```

This will:
1. Create a timestamped SQL dump of the database
2. Compress the dump with gzip
3. Save it to the backup directory
4. Create a symlink to the latest backup
5. Clean up backups older than the retention period

### List Existing Backups

```bash
./scripts/backup-db.sh --list
```

Output example:
```
Backup File                    Size            Date
----------                     ----            ----
db_backup_20240115_020000.sql.gz  2.5M            2024-01-15 02:00:00
db_backup_20240114_020000.sql.gz  2.4M            2024-01-14 02:00:00
db_backup_20240113_020000.sql.gz  2.3M            2024-01-13 02:00:00
```

### Verify Backup Integrity

```bash
./scripts/backup-db.sh --verify ~/insurance_broker_backups/database/db_backup_20240115_020000.sql.gz
```

### Custom Backup Location

```bash
BACKUP_DIR=/mnt/external/backups ./scripts/backup-db.sh
```

### Custom Retention Period

```bash
RETENTION_DAYS=14 ./scripts/backup-db.sh
```

## Database Restore

### Interactive Restore

The easiest way to restore is using interactive mode:

```bash
cd /path/to/insurance_broker
./scripts/restore-db.sh --interactive
```

This will:
1. Display a list of available backups
2. Prompt you to select a backup
3. Ask for confirmation
4. Create a pre-restore backup of the current database
5. Stop application services
6. Drop and recreate the database
7. Restore from the selected backup
8. Verify the restored database
9. Restart application services

### Restore from Latest Backup

```bash
./scripts/restore-db.sh --latest
```

### Restore from Specific File

```bash
./scripts/restore-db.sh --file ~/insurance_broker_backups/database/db_backup_20240115_020000.sql.gz
```

### List Available Backups

```bash
./scripts/restore-db.sh --list
```

### Important Notes

⚠️ **Warning**: Restoring a database will:
- Stop the web application and Celery workers
- Drop the existing database
- Replace it with the backup data
- Restart all services

✅ **Safety**: The restore script automatically:
- Creates a pre-restore backup before making changes
- Allows rollback if the restore fails
- Verifies the database after restore

## Media Files Backup

### Manual Backup

To create a manual media files backup:

```bash
cd /path/to/insurance_broker
./scripts/backup-media.sh
```

This will:
1. Create a timestamped tar.gz archive of all media files
2. Save it to the backup directory
3. Create a symlink to the latest backup
4. Clean up backups older than the retention period

### List Existing Backups

```bash
./scripts/backup-media.sh --list
```

Output example:
```
Backup File                         Size            Date                Files
----------                          ----            ----                -----
media_backup_20240115_030000.tar.gz 150M            2024-01-15 03:00:00 1234
media_backup_20240114_030000.tar.gz 148M            2024-01-14 03:00:00 1220
```

### Verify Backup Integrity

```bash
./scripts/backup-media.sh --verify ~/insurance_broker_backups/media/media_backup_20240115_030000.tar.gz
```

### Restore Media Files

To restore media files, extract the backup archive to the media volume:

```bash
# Stop the application
docker-compose -f docker-compose.prod.yml stop web celery_worker

# Restore media files
docker run --rm \
  -v insurance_broker_media_volume:/media \
  -v ~/insurance_broker_backups/media:/backup:ro \
  alpine \
  sh -c "rm -rf /media/* && tar xzf /backup/media_backup_20240115_030000.tar.gz -C /media"

# Start the application
docker-compose -f docker-compose.prod.yml up -d
```

## Automated Backups

### Setup Cron Jobs

To set up automated daily backups:

```bash
cd /path/to/insurance_broker
./scripts/setup-backup-cron.sh
```

This will configure cron to:
- Backup database daily at 2:00 AM
- Backup media files daily at 3:00 AM
- Clean up old backups weekly on Sunday at 4:00 AM

### Verify Cron Jobs

```bash
crontab -l | grep "Insurance Broker"
```

### View Backup Logs

```bash
# Database backup logs
tail -f ~/insurance_broker/logs/backup-db.log

# Media backup logs
tail -f ~/insurance_broker/logs/backup-media.log

# Cleanup logs
tail -f ~/insurance_broker/logs/backup-cleanup.log
```

### Manual Cron Configuration

If you prefer to configure cron manually, add these entries:

```cron
# Database backup - Daily at 2:00 AM
0 2 * * * cd /path/to/insurance_broker && ./scripts/backup-db.sh >> logs/backup-db.log 2>&1

# Media files backup - Daily at 3:00 AM
0 3 * * * cd /path/to/insurance_broker && ./scripts/backup-media.sh >> logs/backup-media.log 2>&1

# Cleanup old backups - Weekly on Sunday at 4:00 AM
0 4 * * 0 cd /path/to/insurance_broker && ./scripts/backup-db.sh --cleanup >> logs/backup-cleanup.log 2>&1
0 4 * * 0 cd /path/to/insurance_broker && ./scripts/backup-media.sh --cleanup >> logs/backup-cleanup.log 2>&1
```

## Backup Storage

### Local Storage

By default, backups are stored locally in `~/insurance_broker_backups/`:

```
~/insurance_broker_backups/
├── database/
│   ├── db_backup_20240115_020000.sql.gz
│   ├── db_backup_20240114_020000.sql.gz
│   └── latest_backup.sql.gz -> db_backup_20240115_020000.sql.gz
└── media/
    ├── media_backup_20240115_030000.tar.gz
    ├── media_backup_20240114_030000.tar.gz
    └── latest_backup.tar.gz -> media_backup_20240115_030000.tar.gz
```

### Remote Storage (Recommended)

For production, it's recommended to copy backups to remote storage:

#### Using rsync to Remote Server

```bash
# Add to cron after backup jobs
0 5 * * * rsync -avz ~/insurance_broker_backups/ user@backup-server:/backups/insurance_broker/
```

#### Using Digital Ocean Spaces (S3-compatible)

```bash
# Install s3cmd
apt-get install s3cmd

# Configure s3cmd
s3cmd --configure

# Sync backups to Spaces
0 5 * * * s3cmd sync ~/insurance_broker_backups/ s3://your-bucket/insurance_broker_backups/
```

#### Using AWS S3

```bash
# Install AWS CLI
pip install awscli

# Configure AWS CLI
aws configure

# Sync backups to S3
0 5 * * * aws s3 sync ~/insurance_broker_backups/ s3://your-bucket/insurance_broker_backups/
```

### Backup Retention

The default retention period is 7 days. To change it:

```bash
# Keep backups for 30 days
RETENTION_DAYS=30 ./scripts/backup-db.sh
RETENTION_DAYS=30 ./scripts/backup-media.sh
```

Or update the cron jobs:

```cron
0 2 * * * cd /path/to/insurance_broker && RETENTION_DAYS=30 ./scripts/backup-db.sh >> logs/backup-db.log 2>&1
```

## Disaster Recovery

### Complete System Recovery

In case of complete system failure, follow these steps:

#### 1. Set Up New Server

```bash
# Install Docker and Docker Compose
curl -fsSL https://get.docker.com -o get-docker.sh
sh get-docker.sh

# Install Docker Compose
apt-get install docker-compose-plugin
```

#### 2. Clone Application

```bash
# Clone repository or copy application files
git clone https://github.com/your-repo/insurance_broker.git
cd insurance_broker
```

#### 3. Configure Environment

```bash
# Copy environment files
cp .env.prod.example .env.prod
cp .env.prod.db.example .env.prod.db

# Edit with production values
nano .env.prod
nano .env.prod.db
```

#### 4. Start Services

```bash
# Start database and redis first
docker-compose -f docker-compose.prod.yml up -d db redis

# Wait for services to be ready
sleep 10
```

#### 5. Restore Database

```bash
# Copy backup file to server
scp backup.sql.gz user@new-server:~/

# Restore database
./scripts/restore-db.sh --file ~/backup.sql.gz
```

#### 6. Restore Media Files

```bash
# Copy media backup to server
scp media_backup.tar.gz user@new-server:~/

# Restore media files
docker run --rm \
  -v insurance_broker_media_volume:/media \
  -v ~/:/backup:ro \
  alpine \
  tar xzf /backup/media_backup.tar.gz -C /media
```

#### 7. Start Application

```bash
# Start all services
docker-compose -f docker-compose.prod.yml up -d

# Verify services
docker-compose -f docker-compose.prod.yml ps
```

#### 8. Verify Application

```bash
# Check application health
curl https://your-domain.com/admin/login/

# Check logs
docker-compose -f docker-compose.prod.yml logs -f web
```

### Partial Recovery

#### Recover Single Table

```bash
# Extract specific table from backup
gunzip -c backup.sql.gz | grep -A 10000 "CREATE TABLE your_table" > table_backup.sql

# Restore single table
docker exec -i insurance_broker_db psql -U postgres -d insurance_broker_prod < table_backup.sql
```

#### Recover Specific Media Files

```bash
# List files in backup
tar tzf media_backup.tar.gz

# Extract specific files
tar xzf media_backup.tar.gz path/to/specific/file.jpg
```

## Troubleshooting

### Backup Issues

#### "Database container is not running"

```bash
# Check container status
docker-compose -f docker-compose.prod.yml ps

# Start database container
docker-compose -f docker-compose.prod.yml up -d db
```

#### "Permission denied"

```bash
# Make scripts executable
chmod +x scripts/*.sh

# Check backup directory permissions
ls -la ~/insurance_broker_backups/
```

#### "Disk space full"

```bash
# Check disk space
df -h

# Clean up old backups manually
./scripts/backup-db.sh --cleanup
./scripts/backup-media.sh --cleanup

# Remove old Docker images
docker image prune -a
```

### Restore Issues

#### "Restore failed"

The restore script automatically creates a pre-restore backup. To rollback:

```bash
# Find pre-restore backup
ls -la ~/insurance_broker_backups/database/pre_restore_*

# Restore from pre-restore backup
./scripts/restore-db.sh --file ~/insurance_broker_backups/database/pre_restore_backup_20240115_100000.sql.gz
```

#### "Database verification failed"

```bash
# Check database manually
docker exec -it insurance_broker_db psql -U postgres -d insurance_broker_prod

# List tables
\dt

# Check table counts
SELECT COUNT(*) FROM your_table;
```

#### "Services won't start after restore"

```bash
# Check logs
docker-compose -f docker-compose.prod.yml logs web

# Restart services
docker-compose -f docker-compose.prod.yml restart

# If still failing, rebuild
docker-compose -f docker-compose.prod.yml down
docker-compose -f docker-compose.prod.yml up -d --build
```

### Cron Issues

#### "Cron jobs not running"

```bash
# Check cron service
systemctl status cron

# Check cron logs
grep CRON /var/log/syslog

# Test script manually
cd /path/to/insurance_broker
./scripts/backup-db.sh
```

#### "Permission issues in cron"

```bash
# Ensure scripts have correct permissions
chmod +x scripts/*.sh

# Ensure backup directory is writable
mkdir -p ~/insurance_broker_backups
chmod 755 ~/insurance_broker_backups
```

## Best Practices

1. **Test Restores Regularly**: Verify backups work by testing restores on a staging environment
2. **Monitor Backup Logs**: Regularly check backup logs for errors
3. **Use Remote Storage**: Always copy backups to remote storage for disaster recovery
4. **Document Recovery Procedures**: Keep this guide updated with your specific configuration
5. **Encrypt Sensitive Backups**: Consider encrypting backups containing sensitive data
6. **Monitor Disk Space**: Ensure sufficient disk space for backups
7. **Version Control**: Keep backup scripts in version control
8. **Alert on Failures**: Set up monitoring to alert on backup failures

## Security Considerations

- Backup files contain sensitive data - protect them appropriately
- Restrict access to backup directories (chmod 700)
- Use encrypted connections when transferring backups
- Consider encrypting backup files at rest
- Regularly audit who has access to backups
- Follow your organization's data retention policies

## Support

For issues or questions:
- Check the troubleshooting section above
- Review application logs: `docker-compose -f docker-compose.prod.yml logs`
- Contact your system administrator
- Refer to the main deployment documentation: `docs/DEPLOYMENT.md`
