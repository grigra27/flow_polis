#!/bin/bash

# backup-retention.sh
# P1-05: shared local-retention/prune helper for backup-db-telegram.sh and
# backup-media-telegram.sh.
#
# Context (docs/prod-backup-improvement-backlog-2026-09-19.md, P1-01..04):
# the owner decided (2026-09-23) not to build an independent offsite store.
# Local retention is therefore the ONLY guaranteed safety net — age-based
# cleanup here must never be able to empty the backup directory outright.
# `prune_backups` always keeps at least MIN_RETAINED_BACKUPS files
# regardless of age, on top of the RETENTION_DAYS age cutoff, and supports
# PRINT_ONLY=true for a dry run before a new retention config goes live.
#
# Sourced by the two backup-*-telegram.sh scripts; relies on the sourcing
# script providing log_info/log_warn (stderr).

# validate_retention_int <value> <default> <var-name-for-warning>
# Falls back to <default> (with a warning) if <value> is not a
# non-negative integer — same guard pattern as MIN_BACKUP_BYTES in
# backup-db-telegram.sh, so a typo'd env var degrades safely instead of
# breaking arithmetic or find(1) below.
validate_retention_int() {
    local value="$1" default="$2" name="$3"
    case "$value" in
        ''|*[!0-9]*)
            log_warn "$name='$value' is not a non-negative integer, using $default"
            printf '%s' "$default"
            ;;
        *)
            printf '%s' "$value"
            ;;
    esac
}

# prune_backups <label> <min_retained> <retention_days> <file...>
#
# <file...> MUST be passed newest-first (by mtime) — callers build this
# list with `ls -t`, which is portable across GNU/BSD (works the same in
# CI/macOS and on the Linux production host).
#
# Files at positions [0, min_retained) in that order are never touched
# regardless of age — this is the floor that keeps cleanup from ever
# emptying the directory (e.g. a misconfigured RETENTION_DAYS=0, or a
# system clock jump). Beyond that floor, a file is deleted — or, under
# PRINT_ONLY=true, only logged as a dry run — once it is older than
# retention_days.
#
# Prints ONLY the count of files deleted/would-delete to stdout (all
# logging goes to stderr via log_info), so callers can capture it with
# command substitution the same way the rest of this codebase does.
prune_backups() {
    local label="$1"
    local min_retained="$2"
    local retention_days="$3"
    shift 3

    local dry_run=0
    [ "${PRINT_ONLY:-false}" = "true" ] && dry_run=1

    local now cutoff_seconds
    now=$(date +%s)
    cutoff_seconds=$((retention_days * 86400))

    local index=0
    local deleted=0
    local file mtime age

    for file in "$@"; do
        index=$((index + 1))
        if [ "$index" -le "$min_retained" ]; then
            continue # floor: newest N are never pruned by age
        fi
        [ -e "$file" ] || continue

        mtime=$(stat -c %Y "$file" 2>/dev/null || stat -f %m "$file" 2>/dev/null)
        [ -n "$mtime" ] || continue
        age=$((now - mtime))

        if [ "$age" -le "$cutoff_seconds" ]; then
            continue # still within the retention window
        fi

        if [ "$dry_run" -eq 1 ]; then
            log_info "[dry-run] would delete old $label: $(basename "$file") (age $((age / 86400))d, floor=$min_retained)"
        else
            rm -f "$file"
            log_info "Deleted old $label: $(basename "$file")"
        fi
        deleted=$((deleted + 1))
    done

    echo "$deleted"
}
