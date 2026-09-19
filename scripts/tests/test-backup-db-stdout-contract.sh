#!/bin/bash

# test-backup-db-stdout-contract.sh
# Regression tests for P0-04: backup_database() captured via command substitution
# must return ONLY the backup file path on stdout; all logs go to stderr.
#
# Runs fully isolated: scripts are copied to a temp dir (repo .env is NOT loaded),
# docker/curl are stubbed on PATH, notifications are stubbed in-process.
# No production access, no real Telegram/VK traffic.

set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

pass=0
fail=0
ok()   { echo "PASS: $1"; pass=$((pass+1)); }
bad()  { echo "FAIL: $1"; fail=$((fail+1)); }

strip_colors() { sed 's/\x1b\[[0-9;]*[a-zA-Z]//g'; }

# --- fixtures -----------------------------------------------------------------

mkdir -p "$TMP/bin" "$TMP/repo/scripts"
cp "$REPO_ROOT/scripts/backup-db-telegram.sh" \
   "$REPO_ROOT/scripts/telegram-notify.sh" \
   "$REPO_ROOT/scripts/telegram-config.sh" \
   "$TMP/repo/scripts/"

# stub docker: `ps` lists the container; `exec ... pg_dump` depends on DOCKER_EXEC_RC
cat > "$TMP/bin/docker" <<'EOF'
#!/bin/bash
if [ "$1" = "ps" ]; then echo "insurance_broker_db"; exit 0; fi
if [ "$1" = "exec" ]; then
    if [ "${DOCKER_EXEC_RC:-0}" != "0" ]; then
        echo "pg_dump: error" >&2
        exit "${DOCKER_EXEC_RC}"
    fi
    echo "-- PostgreSQL database dump"
    echo "-- PostgreSQL database dump complete"
    exit 0
fi
exit 127
EOF
# stub curl: any network call is a test failure
cat > "$TMP/bin/curl" <<'EOF'
#!/bin/bash
echo "UNEXPECTED curl call: $*" >&2
exit 99
EOF
chmod +x "$TMP/bin/docker" "$TMP/bin/curl"
export PATH="$TMP/bin:$PATH"

export BACKUP_DIR="$TMP/database"
export RETENTION_DAYS=7
export TELEGRAM_ENABLED=false
export VK_ENABLED=false

# shellcheck source=/dev/null
source_backup_functions() {
    # sources the copied script with the trailing `main "$@"` neutralized
    local drv="$TMP/repo/scripts/driver_$$.sh"
    sed 's|^main "\$@"$|true|' "$TMP/repo/scripts/backup-db-telegram.sh" > "$drv"
    grep -q '^true$' "$drv" || { echo "driver: failed to disable main"; exit 1; }
    # shellcheck disable=SC1090
    source "$drv"
}

# --- Test A: stdout contract + notification interaction -----------------------
#
# notify_* internals are replaced with stubs that LOG via log_info/log_warn
# (i.e. they behave like the real telegram-notify.sh layer, which logs) and
# return success. Before the fix this polluted the captured stdout.

OUT_A="$TMP/testA"
(
    set -u
    source_backup_functions
    BACKUP_DIR="$TMP/database"
    mkdir -p "$BACKUP_DIR"

    notify_backup_success() {
        log_info "STUB notify_backup_success for $2"
        log_warn "STUB channel warning"
    }
    send_telegram_message() { log_info "STUB send_telegram_message: $1"; return 0; }
    send_telegram_file()    { log_warn "STUB send_telegram_file: $1";    return 0; }

    backup_file=$(backup_database 2>"$OUT_A.err")
    rc=$?
    printf '%s' "$backup_file" > "$OUT_A.out"
    exit $rc
)
rc_A=$?

if [ "$rc_A" -eq 0 ]; then
    ok "Test A: backup_database returns 0 on success"
else
    bad "Test A: backup_database exit code was $rc_A, expected 0"
fi

if [ ! -s "$OUT_A.out" ]; then
    bad "Test A: captured stdout is empty"
elif [ "$(awk 'END{print NR}' "$OUT_A.out")" = "1" ]; then
    ok "Test A: captured stdout is exactly one line"
else
    bad "Test A: captured stdout is not a single line: [$(cat "$OUT_A.out")]"
fi

case "$(cat "$OUT_A.out")" in
    "$TMP"/database/db_backup_*.sql.gz)
        if [ -f "$(cat "$OUT_A.out")" ]; then
            ok "Test A: captured value equals the created backup path and the file exists"
        else
            bad "Test A: captured path does not exist on disk"
        fi ;;
    *)
        bad "Test A: captured value is not a bare backup path: [$(cat "$OUT_A.out")]" ;;
esac

if strip_colors < "$OUT_A.err" | grep -q '\[INFO\].*Starting database backup' \
   && strip_colors < "$OUT_A.err" | grep -q 'STUB notify_backup_success' \
   && strip_colors < "$OUT_A.err" | grep -q 'STUB channel warning'; then
    ok "Test A: INFO/WARN and notification-layer logs remain visible to the operator via stderr"
else
    bad "Test A: stderr is missing expected INFO/WARN/stub log lines"
fi

# --- Test B: failure behaviour -------------------------------------------------

OUT_B="$TMP/testB"
(
    set -u
    source_backup_functions
    BACKUP_DIR="$TMP/database_fail"
    mkdir -p "$BACKUP_DIR"
    export DOCKER_EXEC_RC=1
    notify_backup_error()    { log_error "STUB notify_backup_error: $2"; }
    send_telegram_message()  { log_info "STUB send_telegram_message: $1"; return 0; }
    if backup_file=$(backup_database 2>"$OUT_B.err"); then
        printf '%s' "$backup_file" > "$OUT_B.out"
        exit 0
    else
        rc=$?
        printf '%s' "$backup_file" > "$OUT_B.out"
        exit $rc
    fi
)
rc_B=$?

if [ "$rc_B" -ne 0 ]; then
    ok "Test B: dump failure propagates non-zero exit ($rc_B)"
else
    bad "Test B: backup_database returned 0 despite failing dump"
fi
if [ ! -s "$OUT_B.out" ]; then
    ok "Test B: no false backup path on stdout for a failed backup"
else
    bad "Test B: stdout contained a bogus path: [$(cat "$OUT_B.out")]"
fi
if strip_colors < "$OUT_B.err" | grep -q 'Database dump failed'; then
    ok "Test B: failure is reported on stderr"
else
    bad "Test B: failure message missing from stderr"
fi

# --- Test C: end-to-end script run (verification gets a real path) -------------

OUT_C="$TMP/testC"
BACKUP_DIR="$TMP/database_e2e" bash "$TMP/repo/scripts/backup-db-telegram.sh" \
    > "$OUT_C.out" 2> "$OUT_C.err"
rc_C=$?
strip_colors < "$OUT_C.err" > "$OUT_C.err.clean"

if [ "$rc_C" -eq 0 ]; then
    ok "Test C: full fixture run exits 0"
else
    bad "Test C: full fixture run exited $rc_C"
fi
if grep -q 'Backup file integrity verified' "$OUT_C.err.clean"; then
    ok "Test C: verify_backup received the real path and passed"
else
    bad "Test C: integrity verification did not pass"
fi
if grep -q 'Backup file not found' "$OUT_C.err.clean"; then
    bad "Test C: verify_backup still received a polluted path"
else
    ok "Test C: no 'Backup file not found' (P0-04 symptom absent)"
fi
if [ -f "$TMP/curl.calls" ]; then
    bad "Test C: unexpected curl activity"
else
    ok "Test C: no real notification traffic"
fi

# --- Test D: static checks -----------------------------------------------------

if bash -n "$REPO_ROOT/scripts/backup-db-telegram.sh"; then
    ok "Test D: bash -n clean"
else
    bad "Test D: bash -n failed"
fi

# --- summary --------------------------------------------------------------------

echo
echo "Results: $pass passed, $fail failed"
[ "$fail" -eq 0 ]
