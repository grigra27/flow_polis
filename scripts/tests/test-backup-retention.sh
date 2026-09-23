#!/bin/bash

# test-backup-retention.sh
# P1-05 regression tests: local-retention pruning (scripts/backup-retention.sh),
# wired into cleanup_old_backups() in both backup-db-telegram.sh and
# backup-media-telegram.sh.
#
# DB:
#   DB-RET-A   everything within RETENTION_DAYS               -> nothing deleted
#   DB-RET-B   floor + age interact: older-than-floor deleted  -> only the excess deleted
#   DB-RET-C   floor exceeds population                        -> nothing deleted, however old
#   DB-RET-D   PRINT_ONLY=true                                 -> dry run, disk untouched, no notify
#   DB-RET-E   orphaned .meta (no matching .sql.gz)             -> swept on a real run
#   DB-RET-F   PRINT_ONLY=true                                 -> orphaned .meta left alone
#   DB-RET-G   RETENTION_DAYS invalid                           -> safe fallback, no crash
#   DB-RET-H   MIN_RETAINED_BACKUPS invalid                     -> safe fallback, no crash
#
# MEDIA:
#   MEDIA-RET-A  .tar.gz + .empty combined into one newest-first sequence
#                -> floor spans both kinds; only the excess-and-stale ones go
#   MEDIA-RET-B  .tar.gz's .meta sidecar deleted alongside it; .empty needs none
#
# Fully isolated: scripts copied to a temp dir (repo .env NOT loaded), curl
# stubbed, notifications disabled. No production, no real Telegram/VK traffic.

set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

pass=0
fail=0
ok()  { echo "PASS: $1"; pass=$((pass+1)); }
bad() { echo "FAIL: $1"; fail=$((fail+1)); }

# --- fixtures: isolated repo copy + drivers ---------------------------------

mkdir -p "$TMP/bin" "$TMP/repo/scripts"
cp "$REPO_ROOT/scripts/backup-db-telegram.sh" \
   "$REPO_ROOT/scripts/backup-media-telegram.sh" \
   "$REPO_ROOT/scripts/telegram-notify.sh" \
   "$REPO_ROOT/scripts/telegram-config.sh" \
   "$REPO_ROOT/scripts/backup-status.sh" \
   "$REPO_ROOT/scripts/backup-retention.sh" \
   "$TMP/repo/scripts/"

make_driver() { # $1=source script, $2=driver path
    sed 's|^main "\$@"$|true|' "$1" > "$2"
    grep -q '^true$' "$2" || { echo "driver: failed to disable main in $1"; exit 1; }
}
make_driver "$REPO_ROOT/scripts/backup-db-telegram.sh"    "$TMP/repo/scripts/db_drv.sh"
make_driver "$REPO_ROOT/scripts/backup-media-telegram.sh" "$TMP/repo/scripts/media_drv.sh"
DB_DRV="$TMP/repo/scripts/db_drv.sh"
MEDIA_DRV="$TMP/repo/scripts/media_drv.sh"

# stub curl: any network call is a test failure
cat > "$TMP/bin/curl" <<'EOF'
#!/bin/bash
echo "UNEXPECTED curl call: $*" >&2
touch "$TMP_TEST/curl.called"
exit 99
EOF
chmod +x "$TMP/bin/curl"
export PATH="$TMP/bin:$PATH"
export TMP_TEST="$TMP"
export TELEGRAM_ENABLED=false
export VK_ENABLED=false

# set_mtime_days_ago <file> <days> — portable across GNU and BSD date/touch.
set_mtime_days_ago() {
    local file="$1" days="$2" ts
    if ts=$(date -d "-${days} days" +%Y%m%d%H%M.%S 2>/dev/null); then
        touch -t "$ts" "$file"           # GNU date
    else
        ts=$(date -v-"${days}"d +%Y%m%d%H%M.%S)
        touch -t "$ts" "$file"           # BSD date (macOS)
    fi
}

# run_cleanup <drv> <backup_dir> [ENV=val ...] — sources the driver in a
# subshell (config vars are read at source time, so env must be exported
# first) and calls cleanup_old_backups directly, exactly like run_verify()
# in test-backup-integrity-verification.sh does for verify_backup().
run_cleanup() {
    local drv="$1" backup_dir="$2"
    shift 2
    (
        set -u
        export BACKUP_DIR="$backup_dir"
        if [ "$#" -gt 0 ]; then export "$@"; fi
        # shellcheck disable=SC1090
        source "$drv"
        cleanup_old_backups
    )
}

# ============================= DB scenarios =================================

db_file() { # $1=dir $2=timestamp $3=days_old (also writes a matching .meta)
    local f="$1/db_backup_$2.sql.gz"
    printf 'not a real dump, just a fixture\n' > "$f"
    printf 'timestamp=%s\n' "$2" > "$1/backup_$2.meta"
    set_mtime_days_ago "$f" "$3"
}

# DB-RET-A: 3 files, ages 1/2/3 days, RETENTION_DAYS=30 (default) -> none deleted
D=$(mktemp -d)
db_file "$D" 20260101_010101 1
db_file "$D" 20260102_010101 2
db_file "$D" 20260103_010101 3
out=$(run_cleanup "$DB_DRV" "$D" 2>&1)
remaining=$(find "$D" -name 'db_backup_*.sql.gz' | wc -l | tr -d ' ')
if [ "$remaining" = "3" ] && echo "$out" | grep -q "No old backups to clean up"; then
    ok "DB-RET-A: everything within retention, nothing deleted"
else
    bad "DB-RET-A: expected 3 files left, got $remaining. Output: $out"
fi
rm -rf "$D"

# DB-RET-B: 8 files aged 1..8 days, RETENTION_DAYS=5 MIN_RETAINED_BACKUPS=5
# -> newest 5 (ages 1-5) protected by floor; ages 6,7,8 are beyond both the
# floor and the retention window -> exactly those 3 deleted.
D=$(mktemp -d)
for age in 1 2 3 4 5 6 7 8; do
    db_file "$D" "ts_$age" "$age"
done
out=$(run_cleanup "$DB_DRV" "$D" RETENTION_DAYS=5 MIN_RETAINED_BACKUPS=5 2>&1)
remaining=$(find "$D" -name 'db_backup_*.sql.gz' | wc -l | tr -d ' ')
if [ "$remaining" = "5" ] \
   && [ -e "$D/db_backup_ts_5.sql.gz" ] && [ ! -e "$D/db_backup_ts_6.sql.gz" ] \
   && echo "$out" | grep -q "Cleaned up 3 old backup(s)"; then
    ok "DB-RET-B: floor keeps 5 newest, only the 3 beyond floor+retention deleted"
else
    bad "DB-RET-B: expected 5 files left (ts_1..ts_5), got $remaining. Output: $out"
fi
rm -rf "$D"

# DB-RET-C: only 3 files, all 10 days old, RETENTION_DAYS=1 MIN_RETAINED_BACKUPS=5
# -> floor (5) exceeds population (3): nothing is deleted no matter how old.
D=$(mktemp -d)
for age in 8 9 10; do
    db_file "$D" "old_$age" "$age"
done
out=$(run_cleanup "$DB_DRV" "$D" RETENTION_DAYS=1 MIN_RETAINED_BACKUPS=5 2>&1)
remaining=$(find "$D" -name 'db_backup_*.sql.gz' | wc -l | tr -d ' ')
if [ "$remaining" = "3" ] && echo "$out" | grep -q "No old backups to clean up"; then
    ok "DB-RET-C: floor exceeds population, nothing deleted regardless of age"
else
    bad "DB-RET-C: expected all 3 kept, got $remaining. Output: $out"
fi
rm -rf "$D"

# DB-RET-D: PRINT_ONLY=true on the DB-RET-B setup -> disk untouched, no notify,
# log says what WOULD be deleted.
D=$(mktemp -d)
for age in 1 2 3 4 5 6 7 8; do
    db_file "$D" "ts_$age" "$age"
done
rm -f "$TMP/curl.called"
out=$(run_cleanup "$DB_DRV" "$D" RETENTION_DAYS=5 MIN_RETAINED_BACKUPS=5 PRINT_ONLY=true 2>&1)
remaining=$(find "$D" -name 'db_backup_*.sql.gz' | wc -l | tr -d ' ')
if [ "$remaining" = "8" ] \
   && echo "$out" | grep -q "\[dry-run\] would delete" \
   && echo "$out" | grep -q "Would clean up 3 old backup(s) (dry run" \
   && ! echo "$out" | grep -q "^.*Deleted old backup:" \
   && [ ! -f "$TMP/curl.called" ]; then
    ok "DB-RET-D: PRINT_ONLY=true is a true dry run (disk untouched, no notify)"
else
    bad "DB-RET-D: expected 8 files left and dry-run log, got $remaining left. Output: $out"
fi
rm -rf "$D"

# DB-RET-E: orphaned .meta (no matching .sql.gz) is swept on a real run;
# a valid pair beyond floor+retention is deleted together.
D=$(mktemp -d)
db_file "$D" fresh 1
db_file "$D" old_pair 40
printf 'timestamp=orphan\n' > "$D/backup_orphan.meta"   # no db_backup_orphan.sql.gz
out=$(run_cleanup "$DB_DRV" "$D" RETENTION_DAYS=30 MIN_RETAINED_BACKUPS=1 2>&1)
if [ ! -e "$D/backup_orphan.meta" ] \
   && [ ! -e "$D/db_backup_old_pair.sql.gz" ] && [ ! -e "$D/backup_old_pair.meta" ] \
   && [ -e "$D/db_backup_fresh.sql.gz" ] && [ -e "$D/backup_fresh.meta" ]; then
    ok "DB-RET-E: orphaned .meta swept, deleted pair's .meta removed, kept pair intact"
else
    bad "DB-RET-E: unexpected leftovers: $(ls "$D"). Output: $out"
fi
rm -rf "$D"

# DB-RET-F: same orphan, but PRINT_ONLY=true -> nothing touched at all.
D=$(mktemp -d)
db_file "$D" fresh 1
printf 'timestamp=orphan\n' > "$D/backup_orphan.meta"
run_cleanup "$DB_DRV" "$D" RETENTION_DAYS=30 MIN_RETAINED_BACKUPS=1 PRINT_ONLY=true >/dev/null 2>&1
if [ -e "$D/backup_orphan.meta" ]; then
    ok "DB-RET-F: PRINT_ONLY=true leaves orphaned .meta alone"
else
    bad "DB-RET-F: dry run deleted the orphaned .meta — it must not touch anything"
fi
rm -rf "$D"

# DB-RET-G / DB-RET-H: invalid env values fall back safely instead of crashing.
D=$(mktemp -d)
db_file "$D" fresh 1
out=$(run_cleanup "$DB_DRV" "$D" RETENTION_DAYS=notanumber 2>&1)
rc=$?
if [ "$rc" -eq 0 ] && echo "$out" | grep -q "is not a non-negative integer, using 30"; then
    ok "DB-RET-G: invalid RETENTION_DAYS falls back to 30 without crashing"
else
    bad "DB-RET-G: rc=$rc, output: $out"
fi
rm -rf "$D"

D=$(mktemp -d)
db_file "$D" fresh 1
out=$(run_cleanup "$DB_DRV" "$D" MIN_RETAINED_BACKUPS="-1" 2>&1)
rc=$?
if [ "$rc" -eq 0 ] && echo "$out" | grep -q "is not a non-negative integer, using 5"; then
    ok "DB-RET-H: invalid MIN_RETAINED_BACKUPS falls back to 5 without crashing"
else
    bad "DB-RET-H: rc=$rc, output: $out"
fi
rm -rf "$D"

# ============================ MEDIA scenarios ================================

media_archive() { # $1=dir $2=timestamp $3=days_old
    local f="$1/media_backup_$2.tar.gz"
    printf 'not a real archive\n' > "$f"
    printf 'file_count=1\n' > "$1/backup_$2.meta"
    set_mtime_days_ago "$f" "$3"
}
media_empty() { # $1=dir $2=timestamp $3=days_old
    local f="$1/media_backup_$2.empty"
    printf 'Empty backup - no media files\n' > "$f"
    set_mtime_days_ago "$f" "$3"
}

# MEDIA-RET-A: 2 fresh .tar.gz + 1 fresh .empty (ages 1,2,3 — floor=3 protects
# all three regardless of kind) + 2 old .tar.gz (ages 20,21, beyond
# RETENTION_DAYS=10) -> exactly the 2 old ones are deleted.
D=$(mktemp -d)
media_archive "$D" newest_a 1
media_archive "$D" newest_b 2
media_empty   "$D" newest_c 3
media_archive "$D" old_a 20
media_archive "$D" old_b 21
out=$(run_cleanup "$MEDIA_DRV" "$D" RETENTION_DAYS=10 MIN_RETAINED_BACKUPS=3 2>&1)
if [ -e "$D/media_backup_newest_a.tar.gz" ] && [ -e "$D/media_backup_newest_b.tar.gz" ] \
   && [ -e "$D/media_backup_newest_c.empty" ] \
   && [ ! -e "$D/media_backup_old_a.tar.gz" ] && [ ! -e "$D/media_backup_old_b.tar.gz" ] \
   && echo "$out" | grep -q "Cleaned up 2 old backup(s)"; then
    ok "MEDIA-RET-A: floor spans .tar.gz + .empty together; only stale excess deleted"
else
    bad "MEDIA-RET-A: unexpected leftovers: $(ls "$D"). Output: $out"
fi
rm -rf "$D"

# MEDIA-RET-B: deleting a .tar.gz beyond floor+retention also removes its
# .meta; an .empty marker (which never has a .meta) deletes cleanly too.
D=$(mktemp -d)
media_archive "$D" fresh 1
media_archive "$D" old_pair 40
media_empty   "$D" old_empty 41
out=$(run_cleanup "$MEDIA_DRV" "$D" RETENTION_DAYS=30 MIN_RETAINED_BACKUPS=1 2>&1)
if [ ! -e "$D/media_backup_old_pair.tar.gz" ] && [ ! -e "$D/backup_old_pair.meta" ] \
   && [ ! -e "$D/media_backup_old_empty.empty" ] \
   && [ -e "$D/media_backup_fresh.tar.gz" ] && [ -e "$D/backup_fresh.meta" ]; then
    ok "MEDIA-RET-B: .tar.gz + its .meta deleted together; .empty needs none"
else
    bad "MEDIA-RET-B: unexpected leftovers: $(ls "$D"). Output: $out"
fi
rm -rf "$D"

# --- notification / network guard -------------------------------------------

if [ -f "$TMP/curl.called" ]; then
    bad "unexpected network activity during retention tests"
else
    ok "no real notification traffic"
fi

# --- syntax sanity -----------------------------------------------------------

if bash -n "$REPO_ROOT/scripts/backup-retention.sh"; then
    ok "bash -n backup-retention.sh clean"
else
    bad "bash -n backup-retention.sh failed"
fi

# --- summary ------------------------------------------------------------------

echo
echo "Results: $pass passed, $fail failed"
[ "$fail" -eq 0 ]
