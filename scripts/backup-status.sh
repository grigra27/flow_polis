#!/bin/bash

# backup-status.sh
# P0-08: machine-readable backup run status contract (decisions D3/D5).
#
# Sourced by backup-db-telegram.sh and backup-media-telegram.sh. It relies on
# the sourcing script providing log_info/log_warn/log_error (stderr) and
# BACKUP_DIR, and on telegram-notify.sh providing NOTIFY_TEXT_RC /
# NOTIFY_FILE_RC (0=delivered, 1=all channels failed, 2=no enabled channels).
#
# Contract fields (meaning is fixed for P0 and P1):
#   created  1|0        backup artifact created (.sql.gz / .tar.gz / .empty)
#   verified 1|0        P0-06 integrity verification passed (the .empty marker
#                       path counts as verified by definition — file_count=0)
#   offsite  1|0|-      real offsite storage; P0: always "-" / JSON null.
#                       Messenger delivery NEVER sets offsite=1.
#   mirror   1|0|-      backup artifact delivered to a messenger file channel
#   notify   1|0|-      final outcome text delivered to a messenger channel
#   result   ok|fail    computed ONLY from the required stages of the backup
#                       type (plus workflow create/verify failures)
#   exit     0|1|2|3|4  D5 table with precedence creation > verification >
#                       offsite > notify

# Stages that may be made required. `mirror` is deliberately absent: it is an
# observational/convenience stage and can never be required at P0.
BACKUP_STATUS_REQUIRED_ALLOWED="created verified offsite notify"

# ---------------------------------------------------------------------------
# Configuration parsing
# ---------------------------------------------------------------------------

# init_backup_status <db|media>
# Reads DB_REQUIRED_STAGES / MEDIA_REQUIRED_STAGES (fallback REQUIRED_STAGES,
# default "created,verified"). Whitespace is trimmed, empty elements ignored,
# unknown stage names are a configuration error (return 1 — caller must abort
# the run before doing anything else).
init_backup_status() {
    local type="$1"
    STATUS_TYPE="$type"
    STATUS_TS=$(date -u '+%Y-%m-%dT%H:%M:%SZ')

    STATUS_CREATED=0
    STATUS_VERIFIED=0
    STATUS_OFFSITE="-"
    STATUS_MIRROR="-"
    STATUS_NOTIFY="-"
    STATUS_FILE=""
    STATUS_RESULT="fail"
    STATUS_EXIT=1
    STATUS_WORKFLOW_FAIL=0

    local raw
    case "$type" in
        db)    raw="${DB_REQUIRED_STAGES-${REQUIRED_STAGES-created,verified}}" ;;
        media) raw="${MEDIA_REQUIRED_STAGES-${REQUIRED_STAGES-created,verified}}" ;;
        *)
            log_error "backup-status: unknown backup type '$type'"
            return 1
            ;;
    esac

    STATUS_REQUIRED=""
    local token
    for token in $(printf '%s' "$raw" | tr ',' ' '); do
        case " $BACKUP_STATUS_REQUIRED_ALLOWED " in
            *" $token "*) ;;
            *)
                if [ "$token" = "mirror" ]; then
                    log_error "Configuration error: stage 'mirror' is observational and cannot be a required stage (allowed: created,verified,offsite,notify)"
                else
                    log_error "Configuration error: unknown required stage '$token' (allowed: created,verified,offsite,notify)"
                fi
                return 1
                ;;
        esac
        case " $STATUS_REQUIRED " in
            *" $token "*) ;;
            *) STATUS_REQUIRED="$STATUS_REQUIRED $token" ;;
        esac
    done
    STATUS_REQUIRED="${STATUS_REQUIRED# }"

    if [ -z "$STATUS_REQUIRED" ]; then
        log_error "Configuration error: required stages list is empty (raw value: '$raw')"
        return 1
    fi

    STATUS_REQUIRED_CSV=$(printf '%s' "$STATUS_REQUIRED" | tr ' ' ',')
    return 0
}

# required_has <stage>
required_has() {
    case " $STATUS_REQUIRED " in
        *" $1 "*) return 0 ;;
        *) return 1 ;;
    esac
}

# map_delivery_tri <telegram-notify rc> -> contract value 1|0|-
map_delivery_tri() {
    case "${1:-2}" in
        0) printf '1' ;;
        1) printf '0' ;;
        *) printf '-' ;;
    esac
}

# ---------------------------------------------------------------------------
# Evaluation (D5 precedence)
# ---------------------------------------------------------------------------

evaluate_backup_result() {
    local stage value all_ok=1
    for stage in $STATUS_REQUIRED; do
        case "$stage" in
            created)  value="$STATUS_CREATED" ;;
            verified) value="$STATUS_VERIFIED" ;;
            offsite)  value="$STATUS_OFFSITE" ;;
            notify)   value="$STATUS_NOTIFY" ;;
            *)        value="-" ;;
        esac
        if [ "$value" != "1" ]; then
            all_ok=0
        fi
    done

    # A create/verify workflow failure always fails the run, even if some
    # non-default required-stage set would not catch it.
    if [ "$STATUS_WORKFLOW_FAIL" != "0" ]; then
        all_ok=0
    fi

    if [ "$all_ok" = "1" ]; then
        STATUS_RESULT="ok"
        STATUS_EXIT=0
        return 0
    fi

    STATUS_RESULT="fail"
    if [ "$STATUS_CREATED" != "1" ]; then
        STATUS_EXIT=1
    elif [ "$STATUS_VERIFIED" != "1" ]; then
        STATUS_EXIT=2
    elif required_has offsite && [ "$STATUS_OFFSITE" != "1" ]; then
        STATUS_EXIT=3
    elif required_has notify && [ "$STATUS_NOTIFY" != "1" ]; then
        STATUS_EXIT=4
    else
        # result=fail without an attributable stage failure should not happen;
        # stay non-zero and explicit rather than claiming success.
        STATUS_EXIT=1
    fi
    return 0
}

# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

# evaluate_core_result — provisional outcome over the required stages of this
# backup type EXCLUDING 'notify'. Called after create/verify/offsite but
# BEFORE the final notification: the final text must match the outcome, so a
# known core failure (e.g. required offsite absent at P0) must never be
# announced as "Backup Completed Successfully".
evaluate_core_result() {
    local stage value
    if [ "$STATUS_WORKFLOW_FAIL" != "0" ]; then
        return 1
    fi
    for stage in $STATUS_REQUIRED; do
        [ "$stage" = "notify" ] && continue
        case "$stage" in
            created)  value="$STATUS_CREATED" ;;
            verified) value="$STATUS_VERIFIED" ;;
            offsite)  value="$STATUS_OFFSITE" ;;
            *)        value="-" ;;
        esac
        if [ "$value" != "1" ]; then
            return 1
        fi
    done
    return 0
}

# core_failure_reason — human-readable cause for the final error notification
# on the core-failure path (mirrors the D5 precedence order). Text is in
# Russian (2026-09-23 notification-wording review) — this string only ever
# feeds notify_backup_error, never the BACKUP_RESULT log line or the JSON
# status, so translating it doesn't affect anything machine-readable.
core_failure_reason() {
    if [ "$STATUS_CREATED" != "1" ]; then
        printf 'Не удалось создать бэкап'
    elif [ "$STATUS_VERIFIED" != "1" ]; then
        printf 'Бэкап не прошёл проверку целостности'
    elif required_has offsite && [ "$STATUS_OFFSITE" != "1" ]; then
        printf 'Не выполнена обязательная стадия offsite (настоящего внешнего хранилища нет; зеркало в мессенджер offsite не считается)'
    else
        printf 'Не пройдена обязательная стадия бэкапа'
    fi
}

# format_size_ru <du -h style value, e.g. "1.5M", "227K", "50M">
# Russian-friendly rendering: "." -> "," and the unit letter -> Cyrillic
# abbreviation (K->КБ, M->МБ, G->ГБ, T->ТБ). Falls back to the input
# unchanged for anything it doesn't recognize, so it never breaks a caller
# on an unexpected du(1) output.
format_size_ru() {
    local input="$1"
    local last_char="${input: -1}"
    local number="${input%?}"
    local unit
    case "$last_char" in
        K) unit="КБ" ;;
        M) unit="МБ" ;;
        G) unit="ГБ" ;;
        T) unit="ТБ" ;;
        *)
            printf '%s' "$input"
            return 0
            ;;
    esac
    printf '%s %s' "${number//./,}" "$unit"
}

# WARNING per §7: communication degradation is recorded, not fatal, when the
# backup itself satisfied its required stages.
warn_degraded_communication() {
    if [ "$STATUS_RESULT" = "ok" ] \
       && { [ "$STATUS_MIRROR" != "1" ] || [ "$STATUS_NOTIFY" != "1" ]; }; then
        log_warn "degraded communication: mirror=$STATUS_MIRROR notify=$STATUS_NOTIFY (result stays $STATUS_RESULT)"
    fi
    return 0
}

status_tri_to_json() {
    case "$1" in
        1) printf '1' ;;
        0) printf '0' ;;
        *) printf 'null' ;;
    esac
}

# Atomic write: temp file in the same directory, then mv (D3).
write_backup_status_json() {
    local target="$BACKUP_DIR/last_status.json"
    local tmp="$target.tmp.$$"

    local file_json="null"
    local bytes=0
    if [ -n "$STATUS_FILE" ] && [ -f "$STATUS_FILE" ]; then
        file_json="\"$(basename "$STATUS_FILE")\""
        bytes=$(wc -c < "$STATUS_FILE" | tr -d '[:space:]')
        case "$bytes" in
            ''|*[!0-9]*) bytes=0 ;;
        esac
    fi

    local required_json=""
    local stage
    for stage in $STATUS_REQUIRED; do
        if [ -n "$required_json" ]; then
            required_json="$required_json, "
        fi
        required_json="$required_json\"$stage\""
    done

    if ! printf '{\n  "ts": "%s",\n  "type": "%s",\n  "file": %s,\n  "bytes": %s,\n  "created": %s,\n  "verified": %s,\n  "offsite": %s,\n  "mirror": %s,\n  "notify": %s,\n  "required": [%s],\n  "result": "%s",\n  "exit": %s\n}\n' \
        "$STATUS_TS" "$STATUS_TYPE" "$file_json" "$bytes" \
        "$STATUS_CREATED" "$STATUS_VERIFIED" \
        "$(status_tri_to_json "$STATUS_OFFSITE")" \
        "$(status_tri_to_json "$STATUS_MIRROR")" \
        "$(status_tri_to_json "$STATUS_NOTIFY")" \
        "$required_json" "$STATUS_RESULT" "$STATUS_EXIT" > "$tmp"; then
        log_error "backup-status: failed to write $tmp"
        rm -f "$tmp"
        return 1
    fi

    if ! mv -f "$tmp" "$target"; then
        log_error "backup-status: failed to move $tmp to $target"
        rm -f "$tmp"
        return 1
    fi

    if command -v python3 >/dev/null 2>&1; then
        if ! python3 -m json.tool "$target" >/dev/null 2>&1; then
            log_error "backup-status: $target is not valid JSON"
            return 1
        fi
    fi
    return 0
}

log_backup_result_line() {
    local file_disp="-"
    if [ -n "$STATUS_FILE" ]; then
        file_disp=$(basename "$STATUS_FILE")
    fi
    log_info "BACKUP_RESULT type=$STATUS_TYPE file=$file_disp created=$STATUS_CREATED verified=$STATUS_VERIFIED offsite=$STATUS_OFFSITE mirror=$STATUS_MIRROR notify=$STATUS_NOTIFY required=$STATUS_REQUIRED_CSV result=$STATUS_RESULT exit=$STATUS_EXIT"
    return 0
}

# finalize_backup_run — evaluate, warn, persist JSON, emit the single
# BACKUP_RESULT log line. Returns the contract exit code.
finalize_backup_run() {
    evaluate_backup_result
    warn_degraded_communication
    if ! write_backup_status_json; then
        log_error "Backup process failed: could not persist status file"
    fi
    log_backup_result_line
    return "$STATUS_EXIT"
}
