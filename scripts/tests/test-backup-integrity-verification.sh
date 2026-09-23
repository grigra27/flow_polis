#!/bin/bash

# test-backup-integrity-verification.sh
# P0-06 regression tests: minimal content-level integrity verification.
#
# DB  (backup-db-telegram.sh:verify_backup):
#   DB-A valid dump                     -> PASS
#   DB-B truncated gzip                 -> FAIL (gzip integrity)
#   DB-C arbitrary gzip text            -> FAIL (not a PostgreSQL dump)
#   DB-D header but no completion marker-> FAIL (incomplete dump)
#   DB-E valid dump below MIN_BACKUP_BYTES -> FAIL (too small)
#   DB-F MIN_BACKUP_BYTES is configurable + invalid env falls back safely
#
# MEDIA (backup-media-telegram.sh:verify_backup):
#   MEDIA-A archive + matching .meta    -> PASS
#   MEDIA-B broken tar.gz               -> FAIL
#   MEDIA-C directories only            -> FAIL (no regular files)
#   MEDIA-D count mismatch              -> FAIL
#   MEDIA-E missing .meta               -> FAIL
#   MEDIA-F malformed .meta             -> FAIL
#   MEDIA-G dirs don't count            -> PASS
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

# --- fixtures: isolated repo copy + drivers -----------------------------------

mkdir -p "$TMP/bin" "$TMP/repo/scripts" "$TMP/fixtures" "$TMP/tmpdir"
cp "$REPO_ROOT/scripts/telegram-notify.sh" \
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

# run_verify <driver> <backup_file> <stdout_file> <stderr_file> [env assignments...]
# TMPDIR is sandboxed per call: verify_backup's mktemp files must land in
# "$TMP/tmpdir" and be gone again when verify_backup returns (asserted in expect).
run_verify() {
    local drv="$1" target="$2" outf="$3" errf="$4"
    shift 4
    (
        set -u
        # config blocks read env at source time — export before sourcing
        # (guard: `export` with zero args prints the whole environment)
        if [ "$#" -gt 0 ]; then export "$@"; fi
        export TMPDIR="$TMP/tmpdir"
        # shellcheck disable=SC1090
        source "$drv"
        verify_backup "$target" >"$outf" 2>"$errf"
    )
}

sed_colors() { sed 's/\x1b\[[0-9;]*[a-zA-Z]//g'; }

# expect <name> <driver> <target> <expect:0|1> <stderr-substring> [env...]
expect() {
    local name="$1" drv="$2" target="$3" want="$4" reason="$5"
    shift 5
    local outf="$TMP/last.out" errf="$TMP/last.err" rc=0
    run_verify "$drv" "$target" "$outf" "$errf" "$@" || rc=$?

    # temp-file lifecycle: verify_backup must leave nothing in the sandboxed TMPDIR
    local leftovers
    leftovers=$(find "$TMP/tmpdir" -mindepth 1)
    if [ -n "$leftovers" ]; then
        bad "$name: verification temp files left behind in TMPDIR: $leftovers"
        return
    fi

    if [ "$want" = "0" ] && [ "$rc" -ne 0 ]; then
        bad "$name: expected rc=0, got $rc"; sed_colors < "$errf" | sed 's/^/    /'; return
    fi
    if [ "$want" != "0" ] && [ "$rc" -eq 0 ]; then
        bad "$name: expected failure but verify_backup returned 0"; return
    fi
    if [ -n "$reason" ] && ! sed_colors < "$errf" | grep -qF -- "$reason"; then
        bad "$name: rc=$rc as expected but stderr lacks reason '$reason'"
        sed_colors < "$errf" | sed 's/^/    /'; return
    fi
    if [ -s "$outf" ]; then
        bad "$name: verify_backup polluted stdout: [$(cat "$outf")]"; return
    fi
    ok "$name (rc=$rc, reason '$reason' ${reason:+confirmed}, stdout clean)"
}

# --- DB fixtures ---------------------------------------------------------------

DB_DRV="$TMP/repo/scripts/db_drv.sh"

# big incompressible-ish filler so the gz exceeds the default 10240-byte floor
filler() { head -c "$2" /dev/urandom | base64 | awk -v n="$1" 'BEGIN{q=sprintf("%c",39)} { print n " | INSERT INTO t VALUES (" q $0 q ");"; n++ }'; }

db_build_dump() { # $1=path.sql (header, filler, completion marker + trailing pg15 \unrestrict)
    {
        echo "-- PostgreSQL database dump"
        echo ""
        echo "SET statement_timeout = 0;"
        filler 1 30000
        echo ""
        echo "-- PostgreSQL database dump complete"
        echo "\\unrestrict aBcD1234xEfGhIjK;"
    } > "$1"
}

# DB-A: valid dump (completion marker NOT the literal last line)
db_build_dump "$TMP/fixtures/db_a.sql"
gzip -kc "$TMP/fixtures/db_a.sql" > "$TMP/fixtures/db_a.sql.gz"
wc_a=$(wc -c < "$TMP/fixtures/db_a.sql.gz")
if [ "$wc_a" -gt 10240 ]; then
    ok "DB fixture sanity: valid dump gz is $wc_a bytes (> default 10240 floor)"
else
    bad "DB fixture sanity: valid dump gz only $wc_a bytes — fixtures unreliable"
fi
expect "DB-A valid dump" "$DB_DRV" "$TMP/fixtures/db_a.sql.gz" 0 "Backup file integrity verified"

# DB-B: truncated gzip (physically corrupt, still above size floor)
head -c $(( wc_a * 60 / 100 )) "$TMP/fixtures/db_a.sql.gz" > "$TMP/fixtures/db_b.sql.gz"
expect "DB-B truncated gzip" "$DB_DRV" "$TMP/fixtures/db_b.sql.gz" 1 "Backup file is corrupted"

# DB-C: valid gzip of arbitrary text (above floor, no PostgreSQL markers)
{ filler 1 30000; echo "just some random notes"; } | gzip -c > "$TMP/fixtures/db_c.sql.gz"
expect "DB-C arbitrary gzip text" "$DB_DRV" "$TMP/fixtures/db_c.sql.gz" 1 "Content is not a PostgreSQL dump"

# DB-D: header present, completion marker removed
{ echo "-- PostgreSQL database dump"; echo ""; filler 1 30000; echo "COPY t FROM stdin."; } \
    | gzip -c > "$TMP/fixtures/db_d.sql.gz"
expect "DB-D no completion marker" "$DB_DRV" "$TMP/fixtures/db_d.sql.gz" 1 "Dump is incomplete"

# DB-E: correct small dump below the default floor
{ echo "-- PostgreSQL database dump"; echo "-- PostgreSQL database dump complete"; } \
    | gzip -c > "$TMP/fixtures/db_e.sql.gz"
expect "DB-E below MIN_BACKUP_BYTES" "$DB_DRV" "$TMP/fixtures/db_e.sql.gz" 1 "too small"

# DB-F1: raising MIN_BACKUP_BYTES rejects the valid fixture
expect "DB-F1 MIN_BACKUP_BYTES=99999999 rejects valid dump" "$DB_DRV" "$TMP/fixtures/db_a.sql.gz" 1 "too small" "MIN_BACKUP_BYTES=99999999"
# DB-F2: lowering it accepts the tiny dump
expect "DB-F2 MIN_BACKUP_BYTES=10 accepts tiny dump" "$DB_DRV" "$TMP/fixtures/db_e.sql.gz" 0 "Backup file integrity verified" "MIN_BACKUP_BYTES=10"
# DB-F3: garbage env does not crash arithmetic; warns and falls back to 10240
(
    set -u
    # shellcheck disable=SC1090
    source "$DB_DRV"
    export MIN_BACKUP_BYTES="abc"
    export TMPDIR="$TMP/tmpdir"
    verify_backup "$TMP/fixtures/db_e.sql.gz" >"$TMP/f3.out" 2>"$TMP/f3.err"
)
rc_f3=$?
if [ -n "$(find "$TMP/tmpdir" -mindepth 1)" ]; then
    bad "DB-F3 verification temp files left behind in TMPDIR: $(find "$TMP/tmpdir" -mindepth 1)"
elif [ "$rc_f3" -ne 0 ] \
   && sed_colors < "$TMP/f3.err" | grep -qF "MIN_BACKUP_BYTES='abc' is not a non-negative integer" \
   && sed_colors < "$TMP/f3.err" | grep -qF "too small"; then
    ok "DB-F3 invalid MIN_BACKUP_BYTES='abc' -> warn + safe default, rc=$rc_f3"
else
    bad "DB-F3 invalid env handling (rc=$rc_f3)"; sed_colors < "$TMP/f3.err" | sed 's/^/    /'
fi
# DB-F4: missing file -> not found, non-zero
expect "DB-F4 missing file" "$DB_DRV" "$TMP/fixtures/does_not_exist.sql.gz" 1 "Backup file not found"

# --- MEDIA fixtures ------------------------------------------------------------

MEDIA_DRV="$TMP/repo/scripts/media_drv.sh"
TS=20260101_000000

media_dir() { # $1=dir $2=files $3=dirs
    mkdir -p "$1"
    local i n
    # NOT `seq 1 0` — on macOS that prints "1" and "0", creating stray files
    n="${3:-0}"; for ((i = 1; i <= n; i++)); do mkdir -p "$1/dir_$i"; done
    n="${2:-0}"; for ((i = 1; i <= n; i++)); do echo "content_$i" > "$1/file_$i.txt"; done
}

# MEDIA-A: 3 regular files, meta file_count=3
mkdir -p "$TMP/mdr_A"
arch="$TMP/mdr_A/media_backup_${TS}.tar.gz"
media_dir "$TMP/src_A" 3 0; tar czf "$arch" -C "$TMP/src_A" .; rm -rf "$TMP/src_A"
printf 'timestamp=%s\nvolume=test\nfile_count=3\nsize=1K\nfile=media_backup_%s.tar.gz\n' "$TS" "$TS" > "$TMP/mdr_A/backup_${TS}.meta"
expect "MEDIA-A valid archive+meta" "$MEDIA_DRV" "$arch" 0 "integrity verified (3 files)"

# MEDIA-B: broken tar.gz (truncate a valid archive; must fail at MEDIA-1)
head -c 30 "$arch" > "$TMP/mdr_A/broken.tar.gz"
expect "MEDIA-B broken tar.gz" "$MEDIA_DRV" "$TMP/mdr_A/broken.tar.gz" 1 "Backup file is corrupted"

# MEDIA-C: directories only
mkdir -p "$TMP/mdr_C"
media_dir "$TMP/src_C" 0 4
tar czf "$TMP/mdr_C/media_backup_${TS}.tar.gz" -C "$TMP/src_C" .; rm -rf "$TMP/src_C"
printf 'file_count=0\n' > "$TMP/mdr_C/backup_${TS}.meta"
expect "MEDIA-C directories only" "$MEDIA_DRV" "$TMP/mdr_C/media_backup_${TS}.tar.gz" 1 "no regular files"

# MEDIA-D: 3 files, meta claims 4
mkdir -p "$TMP/mdr_D"
media_dir "$TMP/src_D" 3 0
tar czf "$TMP/mdr_D/media_backup_${TS}.tar.gz" -C "$TMP/src_D" .; rm -rf "$TMP/src_D"
printf 'file_count=4\n' > "$TMP/mdr_D/backup_${TS}.meta"
expect "MEDIA-D count mismatch" "$MEDIA_DRV" "$TMP/mdr_D/media_backup_${TS}.tar.gz" 1 "file count mismatch: archive has 3, metadata file_count=4"

# MEDIA-E: no metadata at all
mkdir -p "$TMP/mdr_E"
media_dir "$TMP/src_E" 2 0
tar czf "$TMP/mdr_E/media_backup_${TS}.tar.gz" -C "$TMP/src_E" .; rm -rf "$TMP/src_E"
expect "MEDIA-E missing metadata" "$MEDIA_DRV" "$TMP/mdr_E/media_backup_${TS}.tar.gz" 1 "Metadata file not found"

# MEDIA-F: malformed metadata variants
mkdir -p "$TMP/mdr_F"
media_dir "$TMP/src_F" 2 0
tar czf "$TMP/mdr_F/media_backup_${TS}.tar.gz" -C "$TMP/src_F" .; rm -rf "$TMP/src_F"
printf 'timestamp=%s\nvolume=test\n' "$TS" > "$TMP/mdr_F/backup_${TS}.meta"
expect "MEDIA-F2 no file_count key" "$MEDIA_DRV" "$TMP/mdr_F/media_backup_${TS}.tar.gz" 1 "has no file_count= entry"
printf 'file_count=abc\n' > "$TMP/mdr_F/backup_${TS}.meta"
expect "MEDIA-F3 file_count=abc" "$MEDIA_DRV" "$TMP/mdr_F/media_backup_${TS}.tar.gz" 1 "not a non-negative integer"
printf 'file_count=\n' > "$TMP/mdr_F/backup_${TS}.meta"
expect "MEDIA-F4 file_count empty" "$MEDIA_DRV" "$TMP/mdr_F/media_backup_${TS}.tar.gz" 1 "not a non-negative integer"
printf 'file_count=2\nfile_count=3\n' > "$TMP/mdr_F/backup_${TS}.meta"
expect "MEDIA-F5 duplicate file_count" "$MEDIA_DRV" "$TMP/mdr_F/media_backup_${TS}.tar.gz" 1 "entries (ambiguous)"
printf 'file_count=0\n' > "$TMP/mdr_F/backup_${TS}.meta"
expect "MEDIA-F6 file_count=0 for tar.gz" "$MEDIA_DRV" "$TMP/mdr_F/media_backup_${TS}.tar.gz" 1 "file_count=0"

# MEDIA-G: 3 files + 5 dirs, meta=3 -> PASS (regular files only)
mkdir -p "$TMP/mdr_G"
media_dir "$TMP/src_G" 3 5
tar czf "$TMP/mdr_G/media_backup_${TS}.tar.gz" -C "$TMP/src_G" .; rm -rf "$TMP/src_G"
printf 'file_count=3\n' > "$TMP/mdr_G/backup_${TS}.meta"
expect "MEDIA-G dirs do not count" "$MEDIA_DRV" "$TMP/mdr_G/media_backup_${TS}.tar.gz" 0 "integrity verified (3 files)"

# --- notification / network guard ----------------------------------------------

if [ -f "$TMP/curl.called" ]; then
    bad "unexpected network activity during verification tests"
else
    ok "no real notification traffic"
fi

# --- summary ---------------------------------------------------------------------

echo
echo "Results: $pass passed, $fail failed"
[ "$fail" -eq 0 ]
