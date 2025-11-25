# Backup & Restore Quick Reference

Quick reference guide for backup and restore operations.

## Database Backup

```bash
# Create backup
./scripts/backup-db.sh

# List backups
./scripts/backup-db.sh --list

# Verify backup
./scripts/backup-db.sh --verify /path/to/backup.sql.gz

# Cleanup old backups
./scripts/backup-db.sh --cleanup

# Custom retention (14 days)
RETENTION_DAYS=14 ./scripts/backup-db.sh
```

## Database Restore

```bash
# Interactive restore (recommended)
./scripts/restore-db.sh --interactive

# Restore from latest
./scripts/restore-db.sh --latest

# Restore from specific file
./scripts/restore-db.sh --file /path/to/backup.sql.gz

# List available backups
./scripts/restore-db.sh --list
```

## Media Files Backup

```bash
# Create backup
./scripts/backup-media.sh

# List backups
./scripts/backup-media.sh --list

# Verify backup
./scripts/backup-media.sh --verify /path/to/backup.tar.gz

# Cleanup old backups
./scripts/backup-media.sh --cleanup
```

## Media Files Restore

```bash
# Stop application
docker-compose -f docker-compose.prod.yml stop web celery_worker

# Restore media files
docker run --rm \
  -v insurance_broker_media_volume:/media \
  -v ~/insurance_broker_backups/media:/backup:ro \
  alpine \
  sh -c "rm -rf /media/* && tar xzf /backup/latest_backup.tar.gz -C /media"

# Start application
docker-compose -f docker-compose.prod.yml up -d
```

## Automated Backups

```bash
# Setup cron jobs
./scripts/setup-backup-cron.sh

# View cron jobs
crontab -l | grep "Insurance Broker"

# View backup logs
tail -f ~/insurance_broker/logs/backup-db.log
tail -f ~/insurance_broker/logs/backup-media.log
```

## Default Schedule

- **Database backup**: Daily at 2:00 AM
- **Media backup**: Daily at 3:00 AM
- **Cleanup**: Weekly on Sunday at 4:00 AM

## Default Locations

- **Database backups**: `~/insurance_broker_backups/database/`
- **Media backups**: `~/insurance_broker_backups/media/`
- **Logs**: `~/insurance_broker/logs/`

## Environment Variables

```bash
# Custom backup directory
BACKUP_DIR=/mnt/backups ./scripts/backup-db.sh

# Custom retention period
RETENTION_DAYS=30 ./scripts/backup-db.sh

# Custom database name
DB_NAME=my_database ./scripts/backup-db.sh
```

## Emergency Recovery

```bash
# 1. Restore database
./scripts/restore-db.sh --latest

# 2. Restore media files
docker run --rm \
  -v insurance_broker_media_volume:/media \
  -v ~/insurance_broker_backups/media:/backup:ro \
  alpine \
  tar xzf /backup/latest_backup.tar.gz -C /media

# 3. Restart services
docker-compose -f docker-compose.prod.yml restart

# 4. Verify
docker-compose -f docker-compose.prod.yml ps
curl https://onbr.site/admin/login/
```

## Troubleshooting

```bash
# Check container status
docker-compose -f docker-compose.prod.yml ps

# View logs
docker-compose -f docker-compose.prod.yml logs db
docker-compose -f docker-compose.prod.yml logs web

# Check disk space
df -h

# Check backup directory
ls -lh ~/insurance_broker_backups/database/
ls -lh ~/insurance_broker_backups/media/

# Test database connection
docker exec insurance_broker_db psql -U postgres -d insurance_broker_prod -c "SELECT 1;"
```

## Full Documentation

For complete documentation, see [docs/BACKUP_RESTORE.md](../docs/BACKUP_RESTORE.md)
