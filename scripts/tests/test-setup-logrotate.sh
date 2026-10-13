#!/bin/bash

# test-setup-logrotate.sh
# P2-03 regression tests for scripts/setup-logrotate.sh's config content.
#
# Does NOT require the real `logrotate` binary or root: it only checks
# generate_logrotate_config()'s text output directly. Actual `logrotate -d`
# / `logrotate -f` validation was done for real against production's
# logrotate 3.21.0 (see the task's "Как проверить" — there is no portable
# local logrotate to replicate that against on a dev machine), and is
# exactly what caught that this build doesn't resolve a numeric UID/GID
# in `create` despite its own man page — see the comment above
# generate_logrotate_config() in the script under test.

set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

pass=0
fail=0
ok()  { echo "PASS: $1"; pass=$((pass+1)); }
bad() { echo "FAIL: $1"; fail=$((fail+1)); }

# Driver: disable `main "$@"` so sourcing doesn't execute the install
# steps (which require root) — same pattern as the other scripts/tests/*.
DRV="$TMP/setup-logrotate_drv.sh"
sed 's|^main "\$@"$|true|' "$REPO_ROOT/scripts/setup-logrotate.sh" > "$DRV"
grep -q '^true$' "$DRV" || { echo "driver: failed to disable main"; exit 1; }

# shellcheck disable=SC1090
source "$DRV"

CONFIG=$(generate_logrotate_config "/root/insurance_broker")

# --- the six scoped logs are present, with the real production path ---
for name in backup-db.log backup-media.log backup-cleanup.log \
            health-check.log daily-digest.log cleanup-login-attempts.log; do
    if echo "$CONFIG" | grep -qF "/root/insurance_broker/logs/$name"; then
        ok "config includes $name"
    else
        bad "config missing $name"
    fi
done

# --- django.log / security.log must never be a rotated PATH (mentioning them
# in the explanatory comment is fine — only an actual /logs/<name> target matters) ---
if echo "$CONFIG" | grep -E "^\S*/logs/(django|security)\.log$" >/dev/null; then
    bad "config must not touch django.log/security.log (RotatingFileHandler already rotates them)"
else
    ok "django.log/security.log correctly excluded as rotation targets"
fi

# --- D7 directives: weekly, rotate 8, compress, missingok, notifempty, create 0644 ---
for directive in "weekly" "rotate 8" "compress" "missingok" "notifempty" \
                  "create 0644"; do
    if echo "$CONFIG" | grep -qF "$directive"; then
        ok "directive present: $directive"
    else
        bad "directive missing: $directive"
    fi
done

# --- create must NOT hardcode an owner/group: production logrotate 3.21.0
# fails to resolve a numeric UID/GID here (confirmed against the real
# binary) despite its own man page describing a numeric fallback; a bare
# `create 0644` instead inherits owner/group from the file being rotated. ---
if echo "$CONFIG" | grep -qE "create 0644 [0-9]"; then
    bad "create must not hardcode a numeric owner/group — this logrotate build can't resolve it"
else
    ok "create has no hardcoded owner/group (inherits from the rotated file)"
fi

# --- respects the app_dir argument rather than hardcoding a path ---
OTHER=$(generate_logrotate_config "/tmp/other-app-dir")
if echo "$OTHER" | grep -qF "/tmp/other-app-dir/logs/backup-db.log" \
   && ! echo "$OTHER" | grep -qF "/root/insurance_broker"; then
    ok "config path derives from the app_dir argument, not hardcoded"
else
    bad "config did not follow a different app_dir argument"
fi

# --- two stanzas: cron logs (P2-03) + nginx logs (H-15) ---
opens=$(echo "$CONFIG" | grep -c '^{$')
closes=$(echo "$CONFIG" | grep -c '^}$')
if [ "$opens" = "2" ] && [ "$closes" = "2" ]; then
    ok "exactly two logrotate stanzas ({ ... })"
else
    bad "expected exactly two { and two }, got $opens/$closes"
fi

# --- H-15: nginx logs rotated, and nginx is told to reopen them ---
NGINX_STANZA=$(echo "$CONFIG" | sed -n '/logs\/nginx\/access.log/,/^}$/p')
for needle in "/root/insurance_broker/logs/nginx/access.log" \
              "/root/insurance_broker/logs/nginx/error.log" \
              "postrotate" "nginx -s reopen" "|| true" "sharedscripts"; do
    if echo "$NGINX_STANZA" | grep -qF -- "$needle"; then
        ok "nginx stanza: $needle"
    else
        bad "nginx stanza missing: $needle"
    fi
done
if echo "$NGINX_STANZA" | grep -qF "backup-db.log"; then
    bad "nginx stanza must not include cron logs"
else
    ok "nginx stanza is separate from cron logs"
fi

echo
echo "Results: $pass passed, $fail failed"
[ "$fail" -eq 0 ]
