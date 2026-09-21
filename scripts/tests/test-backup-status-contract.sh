#!/bin/bash

# test-backup-status-contract.sh
# P0-08 regression suite: machine-readable status contract
# (created/verified/offsite/mirror/notify/result/exit), notification
# sequencing fix, required-stage configuration (DB/media independence),
# last_status.json + single BACKUP_RESULT line.
#
# Cases S1–S12 per the agreed backlog spec. Fully isolated: scripts copied to
# a temp dir (repo .env NOT loaded), docker/curl stubbed on PATH, the two
# low-level send functions replaced by a test hook that emits EV:* call-event
# markers (for sequencing assertions) and returns a forced tri-state code
# (FORCE_TEXT_RC / FORCE_FILE_RC: 0=delivered, 1=all failed, 2=no channels).
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

# --- isolated repo copy + stubs ------------------------------------------------

mkdir -p "$TMP/bin" "$TMP/repo/scripts" "$TMP/vol" "$TMP/vol_empty" "$TMP/tmpdir" "$TMP/drivers"
cp "$REPO_ROOT/scripts/backup-db-telegram.sh" \
   "$REPO_ROOT/scripts/backup-media-telegram.sh" \
   "$REPO_ROOT/scripts/telegram-notify.sh" \
   "$REPO_ROOT/scripts/telegram-config.sh" \
   "$REPO_ROOT/scripts/backup-status.sh" \
   "$TMP/repo/scripts/"

echo "media-a" > "$TMP/vol/a.txt"
echo "media-b" > "$TMP/vol/b.txt"

# stub docker — same modes as the P0-07 suite:
#   DB:    DOCKER_DB_MODE = valid | garbage | fail
#   media: DOCKER_MEDIA_MODE = ok | corrupt | fail ; count from $FAKE_VOL_DIR
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

# stub curl: any network call at all is a contract violation here (the hook
# replaces the real send path), recorded for the tripwire assertion.
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
export TELEGRAM_UPLOAD_FILES=true
export VK_ENABLED=false
export MIN_BACKUP_BYTES=10
export P008_HOOK_FILE="$TMP/hook.sh"

# test hook: deterministic tri-state + call-event markers (stderr)
cat > "$TMP/hook.sh" <<'EOF'
send_telegram_message() {
    local head
    head=$(printf '%s' "$1" | awk 'NR==1{print; exit}')
    case "$head" in
        *"Backup Started"*)                echo "EV:text:start" >&2 ;;
        *"Backup Completed Successfully"*) echo "EV:text:success" >&2 ;;
        *"Backup Failed"*)                 echo "EV:text:error" >&2
                                           printf '%s' "$1" | awk '/Error:/{sub(/.*Error: /,""); print "EV:text:error_reason: " $0; exit}' >&2 ;;
        *)                                 echo "EV:text:other" >&2 ;;
    esac
    return "${FORCE_TEXT_RC:-0}"
}
send_telegram_file() {
    echo "EV:file:$(basename "$1")" >&2
    return "${FORCE_FILE_RC:-0}"
}
EOF

# driver = real script with an injected hook-source before main
make_driver() { # $1=source script name, $2=driver path
    awk '
        $0 == "main \"$@\"" && hook != "" { print hook }
        { print }
    ' hook='if [ -n "${P008_HOOK_FILE:-}" ]; then source "$P008_HOOK_FILE"; fi' \
        "$TMP/repo/scripts/$1" > "$2"
    grep -q 'P008_HOOK_FILE' "$2" || { echo "driver: failed to inject hook into $1"; exit 1; }
    grep -q '^main "\$@"$' "$2"   || { echo "driver: main call missing in $1"; exit 1; }
}
make_driver backup-db-telegram.sh    "$TMP/repo/scripts/drv_db.sh"
make_driver backup-media-telegram.sh "$TMP/repo/scripts/drv_media.sh"

# run_case <db|media> — fresh BACKUP_DIR + curl.log; sets RC
run_case() {
    local which="$1"
    : > "$TMP/curl.log"
    rm -rf "$TMP/backups"
    mkdir -p "$TMP/backups"
    (
        export BACKUP_DIR="$TMP/backups"
        export TMPDIR="$TMP/tmpdir"
        bash "$TMP/repo/scripts/drv_$which.sh" >"$TMP/run.out" 2>"$TMP/run.err"
    )
    RC=$?
}

err() { strip_colors < "$TMP/run.err"; }

br_line() { err | grep 'BACKUP_RESULT ' | tail -1; }
br_count() { err | grep -c 'BACKUP_RESULT ' || true; }
br_get() { br_line | tr ' ' '\n' | sed -n "s/^$1=//p" | head -1; }
ev_line() { err | grep -nF "$1" | head -1 | cut -d: -f1; }

a_exit()   { [ "$RC" -eq "$2" ] && ok "$1: exit=$RC" || { bad "$1: expected exit $2, got $RC"; err | sed 's/^/    /'; }; }
a_br()     { local got; got=$(br_get "$2"); [ "$got" = "$3" ] && ok "$1: $2=$got" || bad "$1: $2 expected '$3', got '$got' [$(br_line)]"; }
a_single() { local n; n=$(br_count); [ "$n" = "1" ] && ok "$1: exactly one BACKUP_RESULT" || bad "$1: BACKUP_RESULT lines = $n"; }
a_errhas() { err | grep -qF "$2" && ok "$1: stderr has '$2'" || { bad "$1: stderr lacks '$2'"; err | sed 's/^/    /'; }; }
a_errno()  { err | grep -qF "$2" && { bad "$1: stderr unexpectedly has '$2'"; err | sed 's/^/    /'; } || ok "$1: stderr has no '$2'"; }
a_file()   { [ -f "$2" ] && ok "$1: file exists ($(basename "$2"))" || bad "$1: file missing: $2"; }
a_noglob() { local n; n=$(find "$TMP/backups" -maxdepth 1 -name "$2" | wc -l | tr -d ' '); [ "$n" = "0" ] && ok "$1: no $2" || bad "$1: found $n × $2"; }
a_json()   {
    local st="$TMP/backups/last_status.json"
    if [ ! -f "$st" ]; then bad "$1: no last_status.json"; return; fi
    if ! python3 -m json.tool "$st" >/dev/null 2>&1; then bad "$1: last_status.json is not valid JSON"; return; fi
    ok "$1: last_status.json valid JSON"
}
# json_get <key> — prints scalar (null for None) or comma-joined list
json_get() {
    python3 - "$TMP/backups/last_status.json" "$1" <<'PY'
import json, sys
d = json.load(open(sys.argv[1]))
v = d.get(sys.argv[2])
if isinstance(v, list):
    print(",".join(v))
elif v is None:
    print("null")
else:
    print(v)
PY
}
a_jsonfield() { local got; got=$(json_get "$2"); [ "$got" = "$3" ] && ok "$1: json $2=$got" || bad "$1: json $2 expected '$3', got '$got'"; }

latest() { ls "$TMP/backups"/$1 2>/dev/null | sort | tail -1; }

reset_required() { unset DB_REQUIRED_STAGES MEDIA_REQUIRED_STAGES REQUIRED_STAGES 2>/dev/null || true; }
delivery_ok()  { export FORCE_TEXT_RC=0 FORCE_FILE_RC=0; }
delivery_dead() { export FORCE_TEXT_RC=1 FORCE_FILE_RC=1; }
delivery_none() { export FORCE_TEXT_RC=2 FORCE_FILE_RC=2; }

# =============================================================================
# S1 — normal DB success, communications success
# =============================================================================
reset_required; delivery_ok
export DOCKER_DB_MODE=valid
run_case db
a_exit   "S1" 0
a_single "S1"
a_br "S1" type db
a_br "S1" created 1
a_br "S1" verified 1
a_br "S1" offsite -
a_br "S1" mirror 1
a_br "S1" notify 1
a_br "S1" required created,verified
a_br "S1" result ok
a_br "S1" exit 0
a_file "S1 backup present" "$(latest 'db_backup_*.sql.gz')"
a_json "S1"
a_jsonfield "S1" type db
a_jsonfield "S1" created 1
a_jsonfield "S1" verified 1
a_jsonfield "S1" offsite null
a_jsonfield "S1" mirror 1
a_jsonfield "S1" notify 1
a_jsonfield "S1" required created,verified
a_jsonfield "S1" result ok
a_jsonfield "S1" exit 0
S1_FILE=$(json_get file)
case "$(latest 'db_backup_*.sql.gz')" in
    */"$S1_FILE") ok "S1: json file matches created artifact ($S1_FILE)" ;;
    *) bad "S1: json file '$S1_FILE' != artifact '$(latest 'db_backup_*.sql.gz')'" ;;
esac
S1_BYTES=$(json_get bytes)
case "$S1_BYTES" in
    ''|*[!0-9]*) bad "S1: json bytes not numeric: '$S1_BYTES'" ;;
    0) bad "S1: json bytes is 0 for a created backup" ;;
    *) ok "S1: json bytes numeric > 0 ($S1_BYTES)" ;;
esac

# =============================================================================
# S2 — communication failure, communication NOT required
# =============================================================================
reset_required; delivery_dead
run_case db
a_exit   "S2" 0
a_br "S2" mirror 0
a_br "S2" notify 0
a_br "S2" result ok
a_br "S2" exit 0
a_errhas "S2" "degraded communication"
a_json "S2"
a_jsonfield "S2" mirror 0
a_jsonfield "S2" notify 0
a_jsonfield "S2" result ok
a_jsonfield "S2" exit 0

# =============================================================================
# S3 — no channels enabled
# =============================================================================
reset_required; delivery_none
run_case db
a_exit   "S3" 0
a_br "S3" mirror -
a_br "S3" notify -
a_br "S3" result ok
a_br "S3" exit 0
a_errhas "S3" "degraded communication"
a_jsonfield "S3" mirror null
a_jsonfield "S3" notify null

# =============================================================================
# S4 — notify required, channels unavailable
# =============================================================================
reset_required; delivery_none
export DB_REQUIRED_STAGES="created,verified,notify"
run_case db
a_exit   "S4" 4
a_br "S4" notify -
a_br "S4" result fail
a_br "S4" exit 4
# core stages OK → the success-notification attempt itself is made (notify
# failure stays distinguishable from a known core failure, cf. S5)
a_errhas "S4" "EV:text:success"
a_json "S4"
a_jsonfield "S4" required created,verified,notify
a_jsonfield "S4" notify null
a_jsonfield "S4" result fail
a_jsonfield "S4" exit 4
unset DB_REQUIRED_STAGES

# notify required + delivery attempted-but-failed → also exit 4
reset_required; export DB_REQUIRED_STAGES="created,verified,notify"; delivery_dead
run_case db
a_br "S4b" notify 0
a_br "S4b" result fail
a_exit "S4b" 4
unset DB_REQUIRED_STAGES

# =============================================================================
# S5 — offsite required before implementation
# (review fix: the provisional core outcome is evaluated BEFORE the final
#  notification — a known core failure must produce one error notification,
#  never "Backup Completed Successfully" + file mirror)
# =============================================================================
reset_required; delivery_ok
export DB_REQUIRED_STAGES="created,verified,offsite"
run_case db
a_exit   "S5" 3
a_single "S5"
a_br "S5" created 1
a_br "S5" verified 1
a_br "S5" offsite -
a_br "S5" mirror -
a_br "S5" notify 1
a_br "S5" result fail
a_br "S5" exit 3
a_errno  "S5" "EV:text:success"
a_errno  "S5" "EV:file:"
a_errhas "S5" "EV:text:error"
a_errhas "S5" "Required stage offsite is not satisfied"
a_json "S5"
a_jsonfield "S5" offsite null
a_jsonfield "S5" mirror null
a_jsonfield "S5" notify 1
a_jsonfield "S5" result fail
a_jsonfield "S5" exit 3
unset DB_REQUIRED_STAGES
# error-notification delivery itself failing/absent must not change the outcome
reset_required; export DB_REQUIRED_STAGES="created,verified,offsite"; delivery_dead
run_case db
a_exit "S5b (error notif delivery failed)" 3
a_br "S5b (error notif delivery failed)" notify 0
a_br "S5b (error notif delivery failed)" result fail
a_br "S5b (error notif delivery failed)" exit 3
delivery_none
run_case db
a_exit "S5c (no channels)" 3
a_br "S5c (no channels)" notify -
a_br "S5c (no channels)" result fail
a_br "S5c (no channels)" exit 3
unset DB_REQUIRED_STAGES; delivery_ok

# =============================================================================
# S6 — DB/media required-stage independence (one environment)
# =============================================================================
reset_required; delivery_ok
export DB_REQUIRED_STAGES="created,verified,offsite"
export MEDIA_REQUIRED_STAGES="created,verified"
export DOCKER_MEDIA_MODE=ok FAKE_VOL_DIR="$TMP/vol"
run_case db
a_exit "S6 DB (offsite required)" 3
a_br   "S6 DB" result fail
a_br   "S6 DB" exit 3
run_case media
a_exit "S6 media (default required)" 0
a_br   "S6 media" required created,verified
a_br   "S6 media" result ok
a_br   "S6 media" exit 0
unset DB_REQUIRED_STAGES MEDIA_REQUIRED_STAGES

# REQUIRED_STAGES shared fallback applies to both types
reset_required; delivery_ok
export REQUIRED_STAGES="created,verified,offsite"
run_case db
a_exit "S6 fallback DB" 3
run_case media
a_exit "S6 fallback media" 3
unset REQUIRED_STAGES

# =============================================================================
# S7 — verification failure (DB garbage dump; media corrupt archive)
# =============================================================================
reset_required; delivery_ok
export DOCKER_DB_MODE=garbage
run_case db
s7_file="$(latest 'db_backup_*.sql.gz')"
a_exit   "S7 DB" 2
a_single "S7 DB"
a_br "S7 DB" created 1
a_br "S7 DB" verified 0
a_br "S7 DB" mirror -
a_br "S7 DB" result fail
a_br "S7 DB" exit 2
a_file   "S7 DB suspect backup preserved" "$s7_file"
a_errno  "S7 DB no success notification" "EV:text:success"
a_errno  "S7 DB no file mirror" "EV:file:"
a_errhas "S7 DB error notification" "EV:text:error"
a_json "S7 DB"
a_jsonfield "S7 DB" verified 0
a_jsonfield "S7 DB" result fail
a_jsonfield "S7 DB" exit 2
[ "$(json_get file)" = "$(basename "$s7_file")" ] && ok "S7 DB: json file names the suspect backup" || bad "S7 DB: json file='$(json_get file)' expected '$(basename "$s7_file")'"

export DOCKER_DB_MODE=valid
export DOCKER_MEDIA_MODE=corrupt FAKE_VOL_DIR="$TMP/vol"
run_case media
a_exit   "S7 MEDIA" 2
a_single "S7 MEDIA"
a_br "S7 MEDIA" created 1
a_br "S7 MEDIA" verified 0
a_br "S7 MEDIA" mirror -
a_br "S7 MEDIA" result fail
a_br "S7 MEDIA" exit 2
a_json "S7 MEDIA"

# =============================================================================
# S8 — creation failure
# =============================================================================
reset_required; delivery_ok
export DOCKER_DB_MODE=fail
run_case db
a_exit   "S8 DB" 1
a_single "S8 DB"
a_br "S8 DB" created 0
a_br "S8 DB" verified 0
a_br "S8 DB" file -
a_br "S8 DB" mirror -
a_br "S8 DB" result fail
a_br "S8 DB" exit 1
a_errhas "S8 DB error notification" "EV:text:error"
a_json "S8 DB"
a_jsonfield "S8 DB" file null
a_jsonfield "S8 DB" bytes 0
a_jsonfield "S8 DB" created 0
a_jsonfield "S8 DB" result fail
a_jsonfield "S8 DB" exit 1
a_noglob "S8 DB no artifacts" 'db_backup_*'

export DOCKER_DB_MODE=valid
export DOCKER_MEDIA_MODE=fail
run_case media
a_exit   "S8 MEDIA" 1
a_br "S8 MEDIA" created 0
a_br "S8 MEDIA" result fail
a_json "S8 MEDIA"
a_jsonfield "S8 MEDIA" file null
a_jsonfield "S8 MEDIA" bytes 0

# =============================================================================
# S9 — media empty volume (.empty marker: created=1 verified=1, no tar verify)
# =============================================================================
reset_required; delivery_ok
export DOCKER_MEDIA_MODE=ok FAKE_VOL_DIR="$TMP/vol_empty"
run_case media
a_exit   "S9" 0
a_single "S9"
a_br "S9" type media
a_br "S9" created 1
a_br "S9" verified 1
a_br "S9" offsite -
a_br "S9" result ok
a_br "S9" exit 0
a_errno  "S9" "Verifying backup integrity"
a_file   "S9 empty marker" "$(latest 'media_backup_*.empty')"
a_json "S9"
a_jsonfield "S9" verified 1
a_jsonfield "S9" result ok
S9_FILE=$(json_get file)
case "$S9_FILE" in
    media_backup_*.empty) ok "S9: json file names the .empty marker ($S9_FILE)" ;;
    *) bad "S9: json file='$S9_FILE', expected the .empty marker" ;;
esac
S9_BYTES=$(json_get bytes)
case "$S9_BYTES" in
    ''|*[!0-9]*) bad "S9: json bytes not numeric: '$S9_BYTES'" ;;
    0) bad "S9: json bytes 0 for an existing marker" ;;
    *) ok "S9: marker bytes counted ($S9_BYTES)" ;;
esac
# notify required + empty volume: still ok (empty flow is a normal success)
export MEDIA_REQUIRED_STAGES="created,verified,notify"; delivery_none
run_case media
a_br "S9 notify-required/no-channels" result fail
a_exit "S9 notify-required/no-channels" 4
unset MEDIA_REQUIRED_STAGES

# =============================================================================
# S10 — success sequencing (start → create → verify → final success)
# =============================================================================
reset_required; delivery_ok
export DOCKER_DB_MODE=valid FAKE_VOL_DIR="$TMP/vol"
run_case db
n_start=$(ev_line "EV:text:start")
n_create=$(err | grep -nF "Starting database backup" | head -1 | cut -d: -f1)
n_verify=$(err | grep -nF "Verifying backup integrity" | head -1 | cut -d: -f1)
n_success=$(ev_line "EV:text:success")
n_file=$(ev_line "EV:file:")
if [ -n "$n_start" ] && [ -n "$n_create" ] && [ -n "$n_verify" ] && [ -n "$n_success" ] \
   && [ "$n_start" -lt "$n_create" ] && [ "$n_create" -lt "$n_verify" ] && [ "$n_verify" -lt "$n_success" ]; then
    ok "S10 DB: order start($n_start) < create($n_create) < verify($n_verify) < success($n_success)"
else
    bad "S10 DB: ordering violated start=$n_start create=$n_create verify=$n_verify success=$n_success"
fi
if [ -n "$n_file" ] && [ "$n_file" -gt "$n_verify" ]; then
    ok "S10 DB: file mirror($n_file) happens only after verification($n_verify)"
else
    bad "S10 DB: file mirror missing or before verification (file=$n_file verify=$n_verify)"
fi
# verify-failure order: start → verify failure → final error; no success
export DOCKER_DB_MODE=garbage
run_case db
n_start=$(ev_line "EV:text:start")
n_verify=$(err | grep -nF "Verifying backup integrity" | head -1 | cut -d: -f1)
n_error=$(ev_line "EV:text:error")
if [ -n "$n_start" ] && [ -n "$n_verify" ] && [ -n "$n_error" ] \
   && [ "$n_start" -lt "$n_verify" ] && [ "$n_verify" -lt "$n_error" ]; then
    ok "S10 DB verify-fail: order start < verify < final error (no 'Completed Successfully')"
else
    bad "S10 DB verify-fail: ordering violated start=$n_start verify=$n_verify error=$n_error"
fi
unset DOCKER_DB_MODE
# required-offsite failure: start → create → verify → error, no success/mirror
export DB_REQUIRED_STAGES="created,verified,offsite"; delivery_ok
run_case db
n_start=$(ev_line "EV:text:start")
n_create=$(err | grep -nF "Starting database backup" | head -1 | cut -d: -f1)
n_verify=$(err | grep -nF "Verifying backup integrity" | head -1 | cut -d: -f1)
n_error=$(ev_line "EV:text:error")
if [ -n "$n_start" ] && [ -n "$n_create" ] && [ -n "$n_verify" ] && [ -n "$n_error" ] \
   && [ "$n_start" -lt "$n_create" ] && [ "$n_create" -lt "$n_verify" ] && [ "$n_verify" -lt "$n_error" ]; then
    ok "S10 DB offsite-fail: order start < create < verify < final error"
else
    bad "S10 DB offsite-fail: ordering violated start=$n_start create=$n_create verify=$n_verify error=$n_error"
fi
a_errno "S10 DB offsite-fail" "EV:text:success"
a_errno "S10 DB offsite-fail" "EV:file:"
unset DB_REQUIRED_STAGES

# media: same success ordering
export DOCKER_MEDIA_MODE=ok FAKE_VOL_DIR="$TMP/vol"
run_case media
n_create=$(err | grep -nF "Starting media files backup" | head -1 | cut -d: -f1)
n_verify=$(err | grep -nF "Verifying backup integrity" | head -1 | cut -d: -f1)
n_success=$(ev_line "EV:text:success")
if [ -n "$n_create" ] && [ -n "$n_verify" ] && [ -n "$n_success" ] \
   && [ "$n_create" -lt "$n_verify" ] && [ "$n_verify" -lt "$n_success" ]; then
    ok "S10 MEDIA: order create < verify < final success"
else
    bad "S10 MEDIA: ordering violated create=$n_create verify=$n_verify success=$n_success"
fi

# =============================================================================
# S11 — atomic JSON write
# =============================================================================
reset_required; delivery_ok
run_case db
a_noglob "S11" 'last_status.json.tmp*'
a_json "S11 final status valid"
n_status=$(find "$TMP/backups" -maxdepth 1 -name 'last_status.json*' | wc -l | tr -d ' ')
[ "$n_status" = "1" ] && ok "S11: exactly one status file (no partial leftovers)" || bad "S11: found $n_status last_status.json* files"
# the writer must use temp-file-in-same-dir + mv (static contract)
if grep -q 'tmp.\$\$' "$REPO_ROOT/scripts/backup-status.sh" && grep -q 'mv -f' "$REPO_ROOT/scripts/backup-status.sh"; then
    ok "S11: writer uses atomic temp→mv pattern"
else
    bad "S11: atomic write pattern not found in backup-status.sh"
fi

# =============================================================================
# S12 — invalid required-stage configuration
# =============================================================================
reset_required; delivery_ok
export DB_REQUIRED_STAGES="created,verified,banana"
run_case db
[ "$RC" -ne 0 ] && ok "S12: unknown stage aborts run with non-zero exit ($RC)" || bad "S12: unknown stage did not fail the run"
[ "$RC" -eq 1 ] && ok "S12: configuration failure exits 1 (documented choice, no new D5 code)" || bad "S12: expected exit 1, got $RC"
a_errhas "S12" "Configuration error"
a_errhas "S12" "banana"
a_errno  "S12" "BACKUP_RESULT"
a_noglob "S12 no backup attempted" 'db_backup_*'
a_noglob "S12 no status written"    'last_status.json'
unset DB_REQUIRED_STAGES
# 'mirror' can never be required (observational stage)
export DB_REQUIRED_STAGES="created,mirror"
run_case db
a_exit "S12 mirror-required" 1
a_errhas "S12 mirror-required" "Configuration error"
unset DB_REQUIRED_STAGES
# whitespace tolerated; empty elements ignored (notify required + dead
# channels → exit 4 proves the odd spacing parsed into the right stage set)
export DB_REQUIRED_STAGES=" created , verified ,, notify "; delivery_none
run_case db
a_exit "S12 whitespace/empty-elements" 4
a_br "S12 whitespace/empty-elements" required created,verified,notify
unset DB_REQUIRED_STAGES; delivery_ok
# and valid config on media is unaffected by the invalid DB values above
export MEDIA_REQUIRED_STAGES="created,verified"
export DOCKER_MEDIA_MODE=ok FAKE_VOL_DIR="$TMP/vol"
run_case media
a_exit "S12 media stays ok" 0
unset MEDIA_REQUIRED_STAGES

# =============================================================================
# tripwire: no real curl traffic in any scenario
# =============================================================================
if [ -s "$TMP/curl.log" ]; then
    bad "unexpected real curl activity: $(head -1 "$TMP/curl.log")"
else
    ok "no real notification traffic (curl never called)"
fi

# --- summary ------------------------------------------------------------------

echo
echo "Results: $pass passed, $fail failed"
[ "$fail" -eq 0 ]
