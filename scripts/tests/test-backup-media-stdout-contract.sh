#!/bin/bash

# test-backup-media-stdout-contract.sh
# Regression tests for P0-05: backup_media() captured via command substitution
# must return ONLY the backup .tar.gz path on stdout; all logs go to stderr.
# The main-loop guard `[ -f "$backup_file" ] && [[ "$backup_file" == *.tar.gz ]]`
# must therefore pass and verification must actually run.
# Also pins count_media_files() to a read-only volume mount (:ro).
#
# Runs fully isolated: scripts are copied to a temp dir (repo .env is NOT loaded),
# docker/curl are stubbed on PATH, notifications are stubbed in-process.
# No production access, no real volume, no real Telegram/VK traffic.

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

# --- fixtures -----------------------------------------------------------------

mkdir -p "$TMP/bin" "$TMP/repo/scripts" "$TMP/vol"
cp "$REPO_ROOT/scripts/backup-media-telegram.sh" \
   "$REPO_ROOT/scripts/telegram-notify.sh" \
   "$REPO_ROOT/scripts/telegram-config.sh" \
   "$TMP/repo/scripts/"

# fake media volume content (host dir; stub docker "mounts" it via FAKE_VOL_DIR)
echo "media-a" > "$TMP/vol/a.txt"
echo "media-b" > "$TMP/vol/b.txt"

# stub docker:
#   `volume ls`            -> reports the configured volume
#   `run ... find /media..`-> file count of the fake volume
#   `run ... tar czf /backup/<name> ...` -> really creates the archive in BACKUP_DIR
#   DOCKER_TAR_RC=N        -> makes the tar invocation fail with exit N
cat > "$TMP/bin/docker" <<'EOF'
#!/bin/bash
if [ "$1" = "volume" ]; then echo "$MEDIA_VOLUME"; exit 0; fi
if [ "$1" = "run" ]; then
    shift
    have_tar=0
    backup_target=""
    for a in "$@"; do
        case "$a" in
            find\ /media*) echo 2; exit 0 ;;
            tar)           have_tar=1 ;;
            /backup/*)     backup_target="$a" ;;
        esac
    done
    if [ "$have_tar" = "1" ] && [ -n "$backup_target" ]; then
        if [ "${DOCKER_TAR_RC:-0}" != "0" ]; then
            echo "tar: simulated failure" >&2
            exit "$DOCKER_TAR_RC"
        fi
        tar czf "$BACKUP_DIR/$(basename "$backup_target")" -C "$FAKE_VOL_DIR" .
        exit $?
    fi
    exit 127
fi
exit 127
EOF
# stub curl: any network call is a test failure
cat > "$TMP/bin/curl" <<'EOF'
#!/bin/bash
echo "UNEXPECTED curl call: $*" >&2
touch "$TMP_TEST/curl.called"
exit 99
EOF
chmod +x "$TMP/bin/docker" "$TMP/bin/curl"
export PATH="$TMP/bin:$PATH"
export TMP_TEST="$TMP"
export FAKE_VOL_DIR="$TMP/vol"
export MEDIA_VOLUME=test_media_volume
export RETENTION_DAYS=7
export TELEGRAM_ENABLED=false
export VK_ENABLED=false

# sources the copied script with the trailing `main "$@"` neutralized
source_backup_functions() {
    local drv="$TMP/repo/scripts/driver_$$.sh"
    sed 's|^main "\$@"$|true|' "$TMP/repo/scripts/backup-media-telegram.sh" > "$drv"
    grep -q '^true$' "$drv" || { echo "driver: failed to disable main"; exit 1; }
    # shellcheck disable=SC1090
    source "$drv"
}

# --- Test A: stdout contract + notification interaction ------------------------
#
# Notification stubs log via log_info/log_warn (like the real telegram-notify.sh
# layer) and return success. Before the fix this polluted the captured stdout.

OUT_A="$TMP/testA"
(
    set -u
    source_backup_functions
    export BACKUP_DIR="$TMP/database"
    mkdir -p "$BACKUP_DIR"

    notify_backup_success() {
        log_info "STUB notify_backup_success for $2"
        log_warn "STUB channel warning"
    }
    send_telegram_message() { log_info "STUB send_telegram_message: $1"; return 0; }
    send_telegram_file()    { log_warn "STUB send_telegram_file: $1";    return 0; }

    backup_file=$(backup_media 2>"$OUT_A.err")
    rc=$?
    printf '%s' "$backup_file" > "$OUT_A.out"
    exit $rc
)
rc_A=$?

if [ "$rc_A" -eq 0 ]; then
    ok "Test A: backup_media returns 0 on success"
else
    bad "Test A: backup_media exit code was $rc_A, expected 0"
fi

if [ ! -s "$OUT_A.out" ]; then
    bad "Test A: captured stdout is empty"
elif [ "$(awk 'END{print NR}' "$OUT_A.out")" = "1" ]; then
    ok "Test A: captured stdout is exactly one line"
else
    bad "Test A: captured stdout is not a single line: [$(cat "$OUT_A.out")]"
fi

path_A=$(cat "$OUT_A.out")
case "$path_A" in
    "$TMP"/database/media_backup_*.tar.gz)
        if [ -f "$path_A" ]; then
            ok "Test A: captured value equals the created .tar.gz path and the file exists"
        else
            bad "Test A: captured path does not exist on disk"
        fi ;;
    *)
        bad "Test A: captured value is not a bare .tar.gz path: [$path_A]" ;;
esac

if strip_colors < "$OUT_A.err" | grep -q '\[INFO\].*Starting media files backup' \
   && strip_colors < "$OUT_A.err" | grep -q 'STUB notify_backup_success' \
   && strip_colors < "$OUT_A.err" | grep -q 'STUB channel warning'; then
    ok "Test A: INFO/WARN and notification-layer logs remain visible via stderr"
else
    bad "Test A: stderr is missing expected INFO/WARN/stub log lines"
fi

# --- Test B: main-loop verification guard now fires -----------------------------
#
# End-to-end run of the real script under fixtures.
# Pre-fix HEAD behavior: 'Verifying backup integrity' NEVER appears (silent skip).
# Post-fix behavior:     guard passes and verification runs on the real archive.

OUT_B="$TMP/testB"
BACKUP_DIR="$TMP/database_e2e" bash "$TMP/repo/scripts/backup-media-telegram.sh" \
    > "$OUT_B.out" 2> "$OUT_B.err"
rc_B=$?
strip_colors < "$OUT_B.err" > "$OUT_B.err.clean"

if [ "$rc_B" -eq 0 ]; then
    ok "Test B: full fixture run exits 0"
else
    bad "Test B: full fixture run exited $rc_B"
fi
if grep -q 'Verifying backup integrity' "$OUT_B.err.clean"; then
    ok "Test B: verification guard passed, verify_backup was called"
else
    bad "Test B: verify_backup was silently skipped (P0-05 symptom present)"
fi
if grep -q 'Backup file integrity verified' "$OUT_B.err.clean"; then
    ok "Test B: integrity verification of the fixture archive succeeded"
else
    bad "Test B: integrity verification did not succeed"
fi
e2e_archive=$(find "$TMP/database_e2e" -name 'media_backup_*.tar.gz' -type f | head -1)
if [ -n "$e2e_archive" ]; then
    ok "Test B: backup archive physically exists ($(basename "$e2e_archive"))"
else
    bad "Test B: no archive produced by e2e run"
fi
if [ -f "$TMP/curl.called" ]; then
    bad "Test B: unexpected network activity"
else
    ok "Test B: no real notification traffic"
fi

# --- Test C: failure behaviour ---------------------------------------------------

OUT_C="$TMP/testC"
(
    set -u
    source_backup_functions
    export BACKUP_DIR="$TMP/database_fail"
    mkdir -p "$BACKUP_DIR"
    export DOCKER_TAR_RC=1
    notify_backup_error()   { log_error "STUB notify_backup_error: $2"; }
    send_telegram_message() { log_info "STUB send_telegram_message: $1"; return 0; }
    if backup_file=$(backup_media 2>"$OUT_C.err"); then
        printf '%s' "$backup_file" > "$OUT_C.out"
        exit 0
    else
        rc=$?
        printf '%s' "$backup_file" > "$OUT_C.out"
        exit $rc
    fi
)
rc_C=$?

if [ "$rc_C" -ne 0 ]; then
    ok "Test C: tar failure propagates non-zero exit ($rc_C)"
else
    bad "Test C: backup_media returned 0 despite failing tar"
fi
if [ ! -s "$OUT_C.out" ]; then
    ok "Test C: no false backup path on stdout for a failed backup"
else
    bad "Test C: stdout contained a bogus path: [$(cat "$OUT_C.out")]"
fi
if strip_colors < "$OUT_C.err" | grep -q 'Backup creation failed'; then
    ok "Test C: failure is reported on stderr"
else
    bad "Test C: failure message missing from stderr"
fi

# --- Test D: count_media_files mounts the volume read-only -----------------------

count_fn=$(awk '/^count_media_files\(\)/,/^}/' "$REPO_ROOT/scripts/backup-media-telegram.sh")
if printf '%s\n' "$count_fn" | grep -qF -- '"$MEDIA_VOLUME:/media:ro"'; then
    ok "Test D: count_media_files uses read-only mount \$MEDIA_VOLUME:/media:ro"
else
    bad "Test D: count_media_files does not mount :/media:ro"
fi
if printf '%s\n' "$count_fn" | grep -qE -- '"\$MEDIA_VOLUME:/media"'; then
    bad "Test D: count_media_files still contains a read-write :/media mount"
else
    ok "Test D: no read-write volume mount remains in count_media_files"
fi

# --- Test E: static checks ---------------------------------------------------------

if bash -n "$REPO_ROOT/scripts/backup-media-telegram.sh"; then
    ok "Test E: bash -n backup-media-telegram.sh clean"
else
    bad "Test E: bash -n failed"
fi

# --- summary ------------------------------------------------------------------------

echo
echo "Results: $pass passed, $fail failed"
[ "$fail" -eq 0 ]
