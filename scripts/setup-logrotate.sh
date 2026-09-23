#!/bin/bash

# setup-logrotate.sh
# P2-03: installs the logrotate rule for cron-written application logs.
#
# Scope: backup-db.log, backup-media.log, backup-cleanup.log,
# health-check.log, daily-digest.log, cleanup-login-attempts.log.
#
# Deliberately excludes django.log and security.log: those are already
# rotated by Django's own RotatingFileHandler (config/settings.py), and
# an external logrotate rule on top of it would conflict (two rotators
# racing on the same file).
#
# Strategy: `create` (rename the old file, start a fresh one) — NOT
# `copytruncate`. `lsof` on the production host confirmed none of these
# six logs are held open by a long-lived process: each cron line writes
# via a shell redirect (`>> file 2>&1`), so the file is reopened by name
# on every run, and `create` therefore never loses a line written between
# rotation and the next run. `copytruncate` only adds a copy/truncate
# race window that CAN lose lines, and is only actually needed for a log
# held open by a long-lived fd — which is exactly django.log/security.log
# (gunicorn/celery), the two logs this rule does not touch.
#
# `create 0644` — no explicit owner/group. Files are currently owned
# 10001:10001 (the app's in-container UID; there is no matching host
# /etc/passwd entry). logrotate's own man page says a numeric UID/GID is
# used as a fallback when the textual lookup fails, but production's
# logrotate 3.21.0 does not honor that fallback in practice — `create
# 0644 10001 10001` fails with "unknown user '10001'" (confirmed via a
# minimal repro on the server, 2026-09-23). Omitting owner/group instead
# relies on a *documented* behavior that was also verified end-to-end
# with a real `logrotate -f`: "Any of the log file attributes may be
# omitted, in which case those attributes for the new file will use the
# same values as the original log file for the omitted attributes" — so
# the freshly created file keeps 10001:10001 automatically, without
# needing a UID that this logrotate build can't resolve.

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log_info() { echo -e "${GREEN}[INFO]${NC} $1"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="$(dirname "$SCRIPT_DIR")"
# Overridable so this script's config-generation can be exercised from a
# test without touching the real system path or requiring root.
CONFIG_PATH="${LOGROTATE_CONFIG_PATH:-/etc/logrotate.d/insurance-broker}"

# generate_logrotate_config <app_dir>
# Pure function: prints the rule to stdout. Kept separate from the
# install steps below so it can be sourced and checked in isolation.
generate_logrotate_config() {
    local app_dir="$1"
    cat << EOF
# Managed by scripts/setup-logrotate.sh (P2-03) — do not edit by hand,
# re-run the script instead. django.log and security.log are NOT here:
# they are already rotated by Django's own RotatingFileHandler.
$app_dir/logs/backup-db.log
$app_dir/logs/backup-media.log
$app_dir/logs/backup-cleanup.log
$app_dir/logs/health-check.log
$app_dir/logs/daily-digest.log
$app_dir/logs/cleanup-login-attempts.log
{
    weekly
    rotate 8
    compress
    missingok
    notifempty
    create 0644
}
EOF
}

main() {
    log_info "========================================="
    log_info "  Logrotate Setup (P2-03)"
    log_info "========================================="
    echo ""
    log_info "Application directory: $APP_DIR"
    log_info "Target config: $CONFIG_PATH"
    echo ""

    if [ "$(id -u)" -ne 0 ]; then
        log_error "This writes to $(dirname "$CONFIG_PATH")/ — run as root (sudo)."
        exit 1
    fi

    if ! command -v logrotate >/dev/null 2>&1; then
        log_error "logrotate is not installed on this host."
        exit 1
    fi

    local new_config
    new_config="$(generate_logrotate_config "$APP_DIR")"

    if [ -f "$CONFIG_PATH" ] && [ "$(cat "$CONFIG_PATH")" = "$new_config" ]; then
        log_info "Config already up to date, nothing to do."
    else
        if [ -f "$CONFIG_PATH" ]; then
            log_warn "Existing config found, overwriting: $CONFIG_PATH"
        fi
        printf '%s\n' "$new_config" > "$CONFIG_PATH"
        chmod 0644 "$CONFIG_PATH"
        log_info "Wrote $CONFIG_PATH"
    fi

    echo ""
    log_info "Validating with logrotate -d (dry run — no files are touched)..."
    if logrotate -d "$CONFIG_PATH"; then
        log_info "Validation OK"
    else
        log_error "logrotate -d reported errors — see output above"
        exit 1
    fi

    echo ""
    log_info "========================================="
    log_info "  Done"
    log_info "========================================="
    log_info "Force an immediate rotation to test end-to-end: logrotate -f $CONFIG_PATH"
    log_info "Remove this rule entirely: rm $CONFIG_PATH"
}

main "$@"
