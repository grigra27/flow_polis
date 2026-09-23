# Backup and Restore Guide

This guide explains how to backup and restore the Insurance Broker application data, including the PostgreSQL database and user-uploaded media files.

## Table of Contents

- [Overview](#overview)
- [Backup Scripts](#backup-scripts)
- [Database Backup](#database-backup)
- [Database Restore](#database-restore)
- [Media Files Backup](#media-files-backup)
- [Deploying Backup Script Changes](#deploying-backup-script-changes)
- [Automated Backups](#automated-backups)
- [Backup Storage](#backup-storage)
- [Disaster Recovery](#disaster-recovery)
- [Troubleshooting](#troubleshooting)

## Overview

The application's backup scripts are:

1. **backup-db-telegram.sh** - Backs up the PostgreSQL database (with VK/Telegram delivery and the status contract described below)
2. **backup-media-telegram.sh** - Backs up user-uploaded media files (same delivery/status contract)

All scripts are located in the `scripts/` directory and are designed to work with the Docker-based production deployment.

> Earlier versions of these scripts (`backup-db.sh` / `backup-media.sh`, no
> `-telegram` suffix) predated the VK/Telegram integration and the P0-08 status
> contract, were never used by production cron, and were removed (P2-06,
> 2026-09-23) once nothing referenced them as current anymore — their content
> is still available via `git log` if needed for reference.

### Backup Strategy

- **Database backups**: Daily at 2:00 AM (via cron)
- **Media backups**: Weekly, Monday at 3:00 AM (via cron)
- **Retention period**: 30 days for database, 28 days for media by default (configurable) — see [Backup Storage](#backup-storage) for why this is the primary safety net
- **Backup location**: `~/insurance_broker_backups/` by default
- **External copy**: mirrored to VK (and Telegram, when reachable) as a notification/convenience channel — **not** an independent offsite store; see [Backup Storage](#backup-storage)

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
| `RETENTION_DAYS` | `30` (DB) / `28` (media) | Days to keep backups — files older than this are pruned, but never below `MIN_RETAINED_BACKUPS` |
| `MIN_RETAINED_BACKUPS` | `5` (DB) / `4` (media) | Floor: cleanup always keeps at least this many backups regardless of age |
| `PRINT_ONLY` | `false` | `true` = dry-run cleanup (log what would be deleted, delete nothing) |
| `DB_CONTAINER` | `insurance_broker_db` | Database container name |
| `DB_NAME` | `insurance_broker_prod` | Database name |
| `DB_USER` | `postgres` | Database user |

## Database Backup

### Manual Backup

To create a manual database backup:

```bash
cd /path/to/insurance_broker
./scripts/backup-db-telegram.sh
```

This will:
1. Create a timestamped SQL dump of the database
2. Compress the dump with gzip
3. Save it to the backup directory
4. Create a symlink to the latest backup
5. Clean up backups older than the retention period

### List Existing Backups

```bash
./scripts/backup-db-telegram.sh --list
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
./scripts/backup-db-telegram.sh --verify ~/insurance_broker_backups/database/db_backup_20240115_020000.sql.gz
```

### Custom Backup Location

```bash
BACKUP_DIR=/mnt/external/backups ./scripts/backup-db-telegram.sh
```

### Custom Retention Period

```bash
RETENTION_DAYS=14 ./scripts/backup-db-telegram.sh
```

## Database Restore

> **Reality check (P2-06, 2026-09-23):** earlier revisions of this section
> documented a polished `restore-db.sh` with `--interactive`/`--latest`/
> `--file`/`--list` flags and automatic rollback. **That script has never
> existed in this repository.** What follows describes the actual tool —
> `scripts/import-database.sh` — as it really behaves, warts included. It
> is a **destructive, one-shot script with no confirmation prompt**: once
> you run it, it drops the target database immediately. There is no
> `--interactive` mode to talk you out of a mistake — you are the
> confirmation step. Read this whole section before running it.

### Full Database Restore

`scripts/import-database.sh` takes a single positional argument — a
**decompressed** `.sql` file (it pipes the file straight into `psql`, so a
`.sql.gz` will not work as-is):

```bash
cd /path/to/insurance_broker

# Nightly backups are gzipped — decompress a copy first (-k keeps the .gz)
gunzip -k ~/insurance_broker_backups/database/db_backup_20260115_020000.sql.gz

# Compose reads POSTGRES_* from the shell environment for interpolation
# (see docker-compose.prod.yml) — export .env.prod first, the same way
# deploy.yml and cron do
set -a; source .env.prod; set +a

./scripts/import-database.sh ~/insurance_broker_backups/database/db_backup_20260115_020000.sql
```

What it actually does, in order (`[1/9]`..`[9/9]` in its own output):
1. Verifies a `.md5` checksum sidecar if one exists next to the backup file
   (nightly backups don't currently produce one, so this step is normally
   skipped, not failed).
2. Checks `docker-compose` (v1) is installed.
3. Checks `docker-compose.prod.yml` exists in the current directory — run
   it from the project root.
4. Checks `.env.prod` (and, as a legacy leftover from before the `POSTGRES_*`
   consolidation, `.env.prod.db` — currently still present on production;
   if it's ever cleaned up this check will need updating) exist.
5. Starts the `db` container if it isn't already running.
6. **Automatically backs up the current database** with `pg_dump` to
   `current_db_backup_<timestamp>.sql` **in the current working directory**
   (not `~/insurance_broker_backups/`) — this is your rollback copy, see
   below.
7. **Drops and recreates** `insurance_broker_prod`, then imports the
   provided file.
8. Verifies the result: table count, `django_migrations` count, and row
   counts for `auth_user`, `policies_policy`, `clients_client`,
   `insurers_insurer`.
9. Starts the `web` container if needed and runs `python manage.py migrate`.

**What it does NOT do:** restart `celery_worker`, `celery_beat`, or `nginx`
— do that yourself afterward:

```bash
docker-compose -f docker-compose.prod.yml up -d
docker-compose -f docker-compose.prod.yml ps
```

Then verify the application manually (log in, open a policy) before
considering the restore complete.

### Restoring a Single Table or a Few Rows

For anything short of "replace the whole database", skip
`import-database.sh` entirely — see
[Recover Single Table](#recover-single-table) under Disaster Recovery,
which extracts just the relevant `CREATE TABLE` block from the dump and
applies it with plain `psql`, without touching anything else.

### Important Notes

⚠️ **Warning** — `import-database.sh` will, without asking:
- Drop the existing `insurance_broker_prod` database
- Replace it with the backup data
- Run Django migrations against the restored data

It does **not** stop the web/Celery containers first, and does **not**
restart them afterward — plan for a short window where the app may error
while the database is being replaced, and restart services yourself once
it's done.

✅ **What actually protects you:**
- It **does** create a pre-restore backup automatically — `current_db_backup_<timestamp>.sql` in the directory you ran it from (steps above).
- It **does** verify table/migration/row counts after import and fails loudly if the table count is zero.
- It does **not** have an automatic rollback — if something looks wrong after restore, you re-run the same import flow pointing at `current_db_backup_<timestamp>.sql` (see [Restore Issues](#restore-issues)).

## Media Files Backup

### Manual Backup

To create a manual media files backup:

```bash
cd /path/to/insurance_broker
./scripts/backup-media-telegram.sh
```

This will:
1. Create a timestamped tar.gz archive of all media files
2. Save it to the backup directory
3. Create a symlink to the latest backup
4. Clean up backups older than the retention period

### List Existing Backups

```bash
./scripts/backup-media-telegram.sh --list
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
./scripts/backup-media-telegram.sh --verify ~/insurance_broker_backups/media/media_backup_20240115_030000.tar.gz
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

## Deploying Backup Script Changes

The backup scripts are ordinary repository files — there is no separate delivery
channel for them:

- `scripts/backup-db-telegram.sh`
- `scripts/backup-media-telegram.sh`
- `scripts/telegram-notify.sh`

Production deployment is performed by the existing GitHub Actions workflow
(`.github/workflows/deploy.yml`), which runs on every push to `main`. The
workflow rsyncs the repository into `~/insurance_broker/` on the server; the
`scripts/` directory is not excluded from that sync, so changes to these files
reach production the same way as the rest of the code.

Deliver changes to the backup scripts through that CI/CD path. A manual `scp`
deployment is not a supported process and must not be used as a second
deployment path.

## Automated Backups

### Setup Cron Jobs

To set up automated daily backups:

```bash
cd /path/to/insurance_broker
./scripts/setup-backup-cron.sh
```

This will configure cron to:
- Backup database daily at 2:00 AM
- Backup media files weekly, Monday at 3:00 AM
- Clean up old backups weekly, Monday at 4:00 AM

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
0 2 * * * cd /path/to/insurance_broker && ./scripts/backup-db-telegram.sh >> logs/backup-db.log 2>&1

# Media files backup - Weekly, Monday at 3:00 AM
0 3 * * 1 cd /path/to/insurance_broker && ./scripts/backup-media-telegram.sh >> logs/backup-media.log 2>&1

# Cleanup old backups - Weekly, Monday at 4:00 AM
0 4 * * 1 cd /path/to/insurance_broker && ./scripts/backup-db-telegram.sh --cleanup >> logs/backup-cleanup.log 2>&1
0 4 * * 1 cd /path/to/insurance_broker && ./scripts/backup-media-telegram.sh --cleanup >> logs/backup-cleanup.log 2>&1
```

## Backup Storage

### Local Storage

By default, backups are stored locally in `~/insurance_broker_backups/`:

```
~/insurance_broker_backups/
├── database/
│   ├── db_backup_20240115_020000.sql.gz
│   ├── db_backup_20240114_020000.sql.gz
│   ├── last_status.json
│   └── latest_backup.sql.gz -> db_backup_20240115_020000.sql.gz
└── media/
    ├── media_backup_20240115_030000.tar.gz
    ├── media_backup_20240114_030000.tar.gz
    ├── last_status.json
    └── latest_backup.tar.gz -> media_backup_20240115_030000.tar.gz
```

`last_status.json` is the machine-readable result of the most recent run
(created/verified/result/exit — see the backup status contract below); it is
what `system_health_check --check-backups` reads to detect a stalled backup
circuit.

### External copy: VK/Telegram mirror — accepted risk, no independent offsite store

**There is no independent offsite backup storage.** This is a conscious
decision by the owner (2026-09-23), not an oversight or a temporary gap — see
`docs/prod-backup-improvement-backlog-2026-09-19.md` (tasks P1-01…P1-04,
P1-09, all `CANCELLED`, and P1-06 which this section implements). Anyone
building on this backup circuit — including a future engineer or agent —
should read the rest of this section before assuming a "real" offsite copy
exists.

What actually happens after every successful backup: the archive is
**mirrored** to VK (and to Telegram, when its network path is reachable —
it currently is not; see P1-07) as a convenience/notification channel. This
is deliberately **not** treated as storage by the backup status contract: a
successful VK/Telegram delivery only ever sets `mirror=1` / `notify=1`, and
**never** sets `offsite=1` — that field stays `null` permanently until an
independent store is actually built (it is not, at this stage).

**Known reliability of the VK mirror:** the 2026-09-19 audit found the VK
file upload failed on 2 of the last 8 observed nights (`no_free_space`,
`not saved`). It has since succeeded consistently, but treat it as a
best-effort convenience channel, not a guarantee — if the server is lost the
same day a mirror upload silently failed, that day's backup has no copy
anywhere.

**What actually mitigates the risk today:**
- content-level integrity verification on every run (`gzip`/`tar` +
  PostgreSQL dump markers + `file_count` cross-check — see `verify_backup()`
  in both scripts);
- a confirmed, real restore drill of a backup produced by the current code
  (scratch database, full schema/FK/orphan checks — 2026-09-22);
- local retention deep enough to survive more than a single bad night (30
  days DB / 28 days media, with a hard floor of the most recent 5/4 backups
  regardless of age — see [Backup Retention](#backup-retention) below).

**What this does *not* mitigate:** total loss of the server (disk failure,
account compromise, accidental deletion of `~/insurance_broker_backups/`)
leaves you dependent entirely on whatever VK happens to still have, with no
guaranteed retention or versioning on VK's side and no way to script a bulk
recovery from it. If that risk profile changes (more data, compliance
requirement, or the owner simply revisits the decision), reopen P1-01 in the
backlog rather than bolting on an ad hoc `rsync`/`s3cmd` cron job — the
engineering groundwork (status contract fields, required-stage wiring) is
already in place for exactly that addition.

### Backup Retention

Local retention is the only guaranteed safety net (see above), so cleanup is
built to never empty the backup directory outright:

- `RETENTION_DAYS` controls the age cutoff — default **30 days** for the
  database, **28 days** (~4 weekly runs) for media.
- `MIN_RETAINED_BACKUPS` is a floor — cleanup always keeps at least this many
  backups (default **5** DB / **4** media) regardless of how old they are.
  A misconfigured `RETENTION_DAYS=0`, or a server clock jump, cannot wipe out
  every backup in one run.
- `PRINT_ONLY=true` runs cleanup as a dry run: it logs exactly what it would
  delete without deleting anything, and skips the cleanup notification. Use
  it before changing either variable in production:

```bash
# Preview what a new retention setting would delete — nothing is removed
PRINT_ONLY=true RETENTION_DAYS=14 ./scripts/backup-db-telegram.sh --cleanup

# Once satisfied, run for real
RETENTION_DAYS=14 ./scripts/backup-db-telegram.sh --cleanup
```

Or update the cron jobs:

```cron
0 2 * * * cd /path/to/insurance_broker && RETENTION_DAYS=14 ./scripts/backup-db-telegram.sh >> logs/backup-db.log 2>&1
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
# Copy environment file
cp .env.prod.example .env.prod

# Edit with production values
nano .env.prod
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

# Decompress, export env, then restore — see Database Restore above for
# what import-database.sh actually does (no confirmation prompt, destructive)
gunzip ~/backup.sql.gz
cd insurance_broker
set -a; source .env.prod; set +a
./scripts/import-database.sh ~/backup.sql
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
./scripts/backup-db-telegram.sh --cleanup
./scripts/backup-media-telegram.sh --cleanup

# Remove old Docker images
docker image prune -a
```

### Restore Issues

#### "Restore failed"

`import-database.sh` automatically saved a pre-restore backup **in the
directory you ran it from** before it dropped the database (see
[Database Restore](#database-restore)) — it is not moved into
`~/insurance_broker_backups/`, so look where you invoked the script:

```bash
# Find the pre-restore backup import-database.sh made for you
ls -la current_db_backup_*.sql

# Restore from it the same way — decompressed .sql, env sourced first
set -a; source .env.prod; set +a
./scripts/import-database.sh current_db_backup_20260115_100000.sql
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
./scripts/backup-db-telegram.sh
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
3. **Know Your Offsite Exposure**: no independent offsite store exists today (accepted risk, see [Backup Storage](#backup-storage)) — the VK/Telegram mirror is a convenience channel, not a guarantee
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
