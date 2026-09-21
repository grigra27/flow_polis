#!/bin/bash

# test-backup-exit-codes.sh
# Regression tests for P0-07: main-flow exit-code contract.
#
#   success                  -> exit 0, normal post-verification flow runs
#   integrity verification
#     failure                -> exit 2, "Backup verification failed",
#                               notify_backup_error sent, backup FILE PRESERVED,
#                               normal flow stops (no cleanup/list steps)
#   creation failure         -> existing non-zero exit (1), NOT re-coded to 2,
#                               verification never called
#   media empty-volume       -> .empty marker path stays a success (exit 0),
#                               tar.gz verification not called
#
# The FULL script is executed (main), not individual functions. Runs fully
# isolated: scripts copied to a temp dir (repo .env NOT loaded), docker/curl
# stubbed on PATH, notifications go to the stubbed curl (recorded, never sent).
# No production access, no real Telegram/VK traffic.

set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

pass=0
fail=0
ok()  { echo "PASS: $1"; pass=$((pass+1)); }
bad() { echo "FAIL: $1"; fail=$((fail+1)); }

strip_colors() { sed 's/\x1b\[[0-9;]*[a-zA-Z]//g'; }

# --- isolated repo copy + stubs -------------------------------------------------

mkdir -p "$TMP/bin" "$TMP/repo/scripts" "$TMP/vol" "$TMP/vol_empty" "$TMP/tmpdir"
cp "$REPO_ROOT/scripts/backup-db-telegram.sh" \
   "$REPO_ROOT/scripts/backup-media-telegram.sh" \
   "$REPO_ROOT/scripts/telegram-notify.sh" \
   "$REPO_ROOT/scripts/telegram-config.sh" \
   "$REPO_ROOT/scripts/backup-status.sh" \
   "$TMP/repo/scripts/"

echo "media-a" > "$TMP/vol/a.txt"
echo "media-b" > "$TMP/vol/b.txt"

# stub docker — behavior driven by env:
#   DB:    DOCKER_DB_MODE = valid | garbage | fail   (docker exec pg_dump)
#   media: DOCKER_MEDIA_MODE = ok | corrupt | fail   (docker run tar)
#          count comes from real files under $FAKE_VOL_DIR
cat > "$TMP/bin/docker" <<'EOF'
#!/bin/bash
case "$1" in
    ps)
        echo "${DB_CONTAINER:-insurance_broker_db}"
        exit 0
        ;;
    exec)
        case "${DOCKER_DB_MODE:-valid}" in
            fail)
                echo "pg_dump: simulated failure" >&2
                exit 1
                ;;
            garbage)
                printf 'just some random notes\nnot a postgres dump at all\n'
                exit 0
                ;;
            *)
                printf -- '-- PostgreSQL database dump\n\nSET statement_timeout = 0;\n-- PostgreSQL database dump complete\n\\unrestrict aBcD1234xEfGhIjK;\n'
                exit 0
                ;;
        esac
        ;;
    volume)
        echo "$MEDIA_VOLUME"
        exit 0
        ;;
    run)
        shift
        for a in "$@"; do
            case "$a" in
                find\ /media*)
                    find "$FAKE_VOL_DIR" -type f | wc -l | tr -d ' '
                    exit 0
                    ;;
            esac
        done
        backup_target=""
        for a in "$@"; do
            case "$a" in
                /backup/*) backup_target="$a" ;;
            esac
        done
        if [ -n "$backup_target" ]; then
            out="$BACKUP_DIR/$(basename "$backup_target")"
            case "${DOCKER_MEDIA_MODE:-ok}" in
                fail)
                    echo "tar: simulated failure" >&2
                    exit 9
                    ;;
                corrupt)
                    printf 'this is not a tar.gz archive, just junk bytes\n' > "$out"
                    exit 0
                    ;;
                *)
                    tar czf "$out" -C "$FAKE_VOL_DIR" .
                    exit $?
                    ;;
            esac
        fi
        exit 127
        ;;
esac
exit 127
EOF

# stub curl: records every notification attempt, answers like Telegram
cat > "$TMP/bin/curl" <<'EOF'
#!/bin/bash
printf 'curl: %s\n' "$*" >> "$TMP_TEST/curl.log"
echo '{"ok":true}'
exit 0
EOF
chmod +x "$TMP/bin/docker" "$TMP/bin/curl"

export PATH="$TMP/bin:$PATH"
export TMP_TEST="$TMP"
export MEDIA_VOLUME=test_media_volume
export RETENTION_DAYS=7
export TELEGRAM_ENABLED=true
export TELEGRAM_BOT_TOKEN=stub-token
export TELEGRAM_CHAT_ID=stub-chat
export TELEGRAM_UPLOAD_FILES=false
export VK_ENABLED=false
export MIN_BACKUP_BYTES=10

# run_main <script> — fresh BACKUP_DIR + curl.log per scenario; sets RC
run_main() {
    local script="$1"
    : > "$TMP/curl.log"
    rm -rf "$TMP/backups"
    mkdir -p "$TMP/backups"
    (
        export BACKUP_DIR="$TMP/backups"
        export TMPDIR="$TMP/tmpdir"
        # shellcheck disable=SC2091
        bash "$TMP/repo/scripts/$script" >"$TMP/run.out" 2>"$TMP/run.err"
    )
    RC=$?
}

err() { strip_colors < "$TMP/run.err"; }

a_exit()   { [ "$RC" -eq "$2" ] && ok "$1: exit=$RC" || { bad "$1: expected exit $2, got $RC"; err | sed 's/^/    /'; }; }
a_errhas() { err | grep -qF "$2" && ok "$1: stderr has '$2'" || { bad "$1: stderr lacks '$2'"; err | sed 's/^/    /'; }; }
a_errno()  { err | grep -qF "$2" && { bad "$1: stderr unexpectedly has '$2'"; err | sed 's/^/    /'; } || ok "$1: stderr has no '$2'"; }
a_file()   { [ -f "$2" ] && ok "$1: file preserved ($(basename "$2"))" || bad "$1: file missing: $2"; }
a_nofile() { [ -f "$2" ] && bad "$1: unexpected file $(basename "$2")" || ok "$1: no $(basename "$2")"; }
a_curlhas() { grep -qF "$2" "$TMP/curl.log" && ok "$1: notification contains '$2'" || bad "$1: notification lacks '$2'"; }
a_curlno()  { grep -qF "$2" "$TMP/curl.log" && bad "$1: unexpected notification '$2'" || ok "$1: no notification '$2'"; }
latest() { ls "$TMP/backups"/$1 2>/dev/null | sort | tail -1; }

# --- DB-1: success ----------------------------------------------------------------
export DOCKER_DB_MODE=valid
run_main backup-db-telegram.sh
a_exit   "DB-1" 0
a_file   "DB-1 backup preserved" "$(latest 'db_backup_*.sql.gz')"
a_errhas "DB-1" "Backup file integrity verified"
a_errno  "DB-1" "Backup verification failed"
a_curlno "DB-1" "Backup Failed"
a_errhas "DB-1 normal flow continues" "Cleaning up backups"

# --- DB-2: created backup fails integrity verification -----------------------------
export DOCKER_DB_MODE=garbage
run_main backup-db-telegram.sh
db2_file="$(latest 'db_backup_*.sql.gz')"
a_exit   "DB-2" 2
a_file   "DB-2 backup preserved on verification failure" "$db2_file"
a_errhas "DB-2" "Backup verification failed"
a_errhas "DB-2 verification reason" "Content is not a PostgreSQL dump"
a_curlhas "DB-2 error notification" "Backup Failed"
a_errno  "DB-2 normal flow stopped" "Cleaning up backups"

# --- DB-3: creation failure keeps its own semantics ---------------------------------
export DOCKER_DB_MODE=fail
run_main backup-db-telegram.sh
a_exit   "DB-3 creation failure not re-coded to 2" 1
a_errhas "DB-3" "Database dump failed"
a_errno  "DB-3 verification not called" "Verifying backup integrity"

# --- MEDIA-1: success ---------------------------------------------------------------
export DOCKER_MEDIA_MODE=ok
export FAKE_VOL_DIR="$TMP/vol"
run_main backup-media-telegram.sh
a_exit   "MEDIA-1" 0
a_file   "MEDIA-1 archive preserved" "$(latest 'media_backup_*.tar.gz')"
a_errhas "MEDIA-1" "Backup file integrity verified"
a_curlno "MEDIA-1" "Backup Failed"
a_errhas "MEDIA-1 normal flow continues" "Cleaning up backups"

# --- MEDIA-2: archive created but verification fails --------------------------------
export DOCKER_MEDIA_MODE=corrupt
run_main backup-media-telegram.sh
m2_file="$(latest 'media_backup_*.tar.gz')"
a_exit   "MEDIA-2" 2
a_file   "MEDIA-2 archive preserved on verification failure" "$m2_file"
a_errhas "MEDIA-2" "Backup verification failed"
a_errhas "MEDIA-2 verification reason" "Backup file is corrupted"
a_curlhas "MEDIA-2 error notification" "Backup Failed"
a_errno  "MEDIA-2 normal flow stopped" "Cleaning up backups"
a_file   "MEDIA-2 metadata not removed" "$(latest 'backup_*.meta')"

# --- MEDIA-3: tar creation fails ------------------------------------------------------
export DOCKER_MEDIA_MODE=fail
run_main backup-media-telegram.sh
a_exit   "MEDIA-3 creation failure not re-coded to 2" 1
a_errhas "MEDIA-3" "Backup creation failed"
a_errno  "MEDIA-3 verification not called" "Verifying backup integrity"

# --- MEDIA-4: empty volume -> .empty marker stays a success --------------------------
export DOCKER_MEDIA_MODE=ok
export FAKE_VOL_DIR="$TMP/vol_empty"
run_main backup-media-telegram.sh
a_exit   "MEDIA-4" 0
a_file   "MEDIA-4 empty marker created" "$(latest 'media_backup_*.empty')"
a_errno  "MEDIA-4 tar.gz verification not called" "Verifying backup integrity"
a_curlno "MEDIA-4" "Backup Failed"
a_errhas "MEDIA-4 normal flow continues" "Cleaning up backups"

# --- summary -------------------------------------------------------------------------

echo
echo "Results: $pass passed, $fail failed"
[ "$fail" -eq 0 ]
