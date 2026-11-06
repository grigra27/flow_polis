#!/bin/bash
# Manual root installation only. This does not rotate/remove any existing root key.
set -euo pipefail
umask 077
export PATH=/usr/sbin:/usr/bin:/sbin:/bin

ACCOUNT=onlinepolis-deploy
ACCOUNT_UID=20001
ACCOUNT_GID=20001
PROJECT=/root/insurance_broker
STATE=/var/lib/onlinepolis-deploy
CONFIG=/etc/onlinepolis-deploy
LOCK=/root/.local/state/onlinepolis-deploy.lock
HOME_DIR=$STATE/home
GATE=/usr/local/libexec/onlinepolis-deploy-gate
CONTROLLER=/usr/local/sbin/onlinepolis-deploy-controller
KEYS=/etc/ssh/authorized_keys/onlinepolis-deploy
SSHD_CONFIG=/etc/ssh/sshd_config.d/10-onlinepolis-deploy.conf
SUDOERS=/etc/sudoers.d/onlinepolis-deploy
SOURCE_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
COMMITTED=0
RELOAD_ATTEMPTED=0
ACCOUNT_CREATED=0
GROUP_CREATED=0
declare -a CHANGED_PATHS=() BACKUP_FILES=() CREATED_DIRS=() TEMP_FILES=()
declare -a META_PATHS=() META_UIDS=() META_GIDS=() META_MODES=()

die() { echo "Installation refused: $*" >&2; exit 1; }

[[ $(id -u) == 0 ]] || die "run manually as root."
[[ $# == 1 && -f $1 && ! -L $1 ]] || die "provide one regular SSH public-key file."
for command in python3 ssh-keygen sshd visudo sudo systemctl install getent useradd groupadd userdel groupdel stat flock passwd awk; do
    command -v "$command" >/dev/null || die "required utility missing: $command"
done
for source in "$SOURCE_DIR/gate.py" "$SOURCE_DIR/controller.py" "$SOURCE_DIR/security.override.yml" "$PROJECT/docker-compose.prod.yml" "$PROJECT/nginx/nginx.conf" "$PROJECT/nginx/default.conf"; do
    [[ -f $source && ! -L $source ]] || die "a required trusted installation source is missing or is a symlink."
done
[[ -d $PROJECT && ! -L $PROJECT && -d $PROJECT/nginx && ! -L $PROJECT/nginx ]] || die "project directories must be real directories."
[[ -f $PROJECT/.env.prod && ! -L $PROJECT/.env.prod && $(stat -c '%u:%g:%a' "$PROJECT/.env.prod") == 0:0:600 ]] || die ".env.prod must remain a root-owned mode 0600 regular file."

# Do not resolve installation targets through a user-controlled or symlinked parent.
assert_safe_parent() {
    python3 -I - "$1" <<'PY'
import os, pathlib, stat, sys
path = pathlib.Path(sys.argv[1])
for parent in reversed(path.parents):
    if not parent.exists():
        continue
    info = parent.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
        raise SystemExit("Unsafe installation directory.")
PY
}

for target in "$GATE" "$CONTROLLER" "$KEYS" "$SSHD_CONFIG" "$SUDOERS" "$CONFIG/compose.yml" "$STATE/releases"; do
    assert_safe_parent "$target"
done
if systemctl is-active --quiet ssh.service; then
    SSH_SERVICE=ssh.service
elif systemctl is-active --quiet sshd.service; then
    SSH_SERVICE=sshd.service
else
    die "no active SSH service found."
fi

BACKUP_BASE=/root/.local/state/onlinepolis-deploy/installer
assert_safe_parent "$BACKUP_BASE/snapshot"
install -d -m 0700 -o root -g root "$BACKUP_BASE"
BACKUP=$(mktemp -d "$BACKUP_BASE/$(date -u +%Y%m%dT%H%M%SZ)-XXXXXX")
chmod 0700 "$BACKUP"

on_exit() {
    local status=$? i path temp rollback_failed=0
    trap - EXIT INT TERM
    if [[ $COMMITTED != 1 ]]; then
        set +e
        for ((i=${#CHANGED_PATHS[@]}-1; i>=0; i--)); do
            path=${CHANGED_PATHS[i]}
            if [[ ${BACKUP_FILES[i]} == absent ]]; then
                rm -f -- "$path" || rollback_failed=1
            else
                temp=$(mktemp "${path}.restore.XXXXXX")
                if ! { cp -a -- "${BACKUP_FILES[i]}" "$temp" && mv -fT -- "$temp" "$path"; }; then rollback_failed=1; fi
                rm -f -- "$temp"
            fi
        done
        for ((i=${#META_PATHS[@]}-1; i>=0; i--)); do
            chown "${META_UIDS[i]}:${META_GIDS[i]}" "${META_PATHS[i]}" || rollback_failed=1
            chmod "${META_MODES[i]}" "${META_PATHS[i]}" || rollback_failed=1
        done
        [[ $ACCOUNT_CREATED != 1 ]] || userdel "$ACCOUNT" || rollback_failed=1
        [[ $GROUP_CREATED != 1 ]] || groupdel "$ACCOUNT" || rollback_failed=1
        for temp in "${TEMP_FILES[@]}"; do rm -f -- "$temp"; done
        for ((i=${#CREATED_DIRS[@]}-1; i>=0; i--)); do rmdir -- "${CREATED_DIRS[i]}" 2>/dev/null; done
        if [[ $RELOAD_ATTEMPTED == 1 ]]; then
            if ! { sshd -t && systemctl reload "$SSH_SERVICE"; }; then rollback_failed=1; fi
        fi
        if [[ $rollback_failed == 0 ]]; then
            echo "Installation rolled back; root-only snapshot: $BACKUP" >&2
        else
            echo "Automatic rollback incomplete; inspect root-only snapshot: $BACKUP" >&2
        fi
        [[ $status != 0 ]] || status=1
    fi
    exit "$status"
}
trap on_exit EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

make_directory() {
    local path=$1 mode=$2
    if [[ -e $path || -L $path ]]; then
        [[ -d $path && ! -L $path && $(stat -c '%u:%g:%a' "$path") == "0:0:$mode" ]] || die "existing managed directory ownership or permissions differ."
    else
        CREATED_DIRS+=("$path")
        install -d -m "$mode" -o root -g root "$path"
    fi
}

backup_file() {
    local path=$1 saved=absent
    if [[ -e $path || -L $path ]]; then
        [[ -f $path && ! -L $path ]] || die "managed target is not a regular file."
        saved=$BACKUP/file-${#CHANGED_PATHS[@]}
        cp -a -- "$path" "$saved"
    fi
    CHANGED_PATHS+=("$path")
    BACKUP_FILES+=("$saved")
    printf '%s\t%s\n' "$path" "$saved" >> "$BACKUP/files.tsv"
}

atomic_install() {
    local source=$1 target=$2 mode=$3 temp
    backup_file "$target"
    temp=$(mktemp "${target}.install.XXXXXX")
    TEMP_FILES+=("$temp")
    install -m "$mode" -o root -g root -- "$source" "$temp"
    mv -fT -- "$temp" "$target"
}

root_own() {
    local path=$1 uid gid mode
    read -r uid gid mode < <(stat -c '%u %g %a' "$path")
    META_PATHS+=("$path"); META_UIDS+=("$uid"); META_GIDS+=("$gid"); META_MODES+=("$mode")
    printf '%s\t%s\t%s\t%s\n' "$path" "$uid" "$gid" "$mode" >> "$BACKUP/ownership.tsv"
    chown root:root "$path"
    chmod go-w "$path"
}

# The same lock is used by the previous workflow and the restricted controller.
assert_safe_parent "$LOCK"
if [[ -e $LOCK || -L $LOCK ]]; then
    [[ -f $LOCK && ! -L $LOCK && $(stat -c '%u' "$LOCK") == 0 ]] || die "deployment lock must be a root-owned regular file."
    lock_mode=$(stat -c '%a' "$LOCK")
    [[ $((8#$lock_mode & 8#022)) == 0 ]] || die "deployment lock is writable by others."
else
    install -m 0600 -o root -g root /dev/null "$LOCK"
fi
exec 9>>"$LOCK"
flock -n 9 || die "a deployment operation is active; retry after it completes."

# Accept a single plain public key, stripping comments/options; never print key bytes.
python3 -I - "$1" "$BACKUP/key.pub" "$BACKUP/authorized_keys" <<'PY'
import pathlib, re, sys
with open(sys.argv[1], "rb") as source:
    raw = source.read(16385)
if len(raw) > 16384:
    raise SystemExit("Public key input too large.")
try:
    lines = raw.decode("ascii").strip().splitlines()
except UnicodeError:
    raise SystemExit("Public key must be ASCII.")
if len(lines) != 1:
    raise SystemExit("Exactly one public key is required.")
fields = lines[0].split()
types = {"ssh-ed25519", "ssh-rsa", "ecdsa-sha2-nistp256", "ecdsa-sha2-nistp384", "ecdsa-sha2-nistp521"}
if len(fields) < 2 or fields[0] not in types or not re.fullmatch(r"[A-Za-z0-9+/]+={0,2}", fields[1]):
    raise SystemExit("A plain SSH public key without options is required.")
key = " ".join(fields[:2]) + "\n"
pathlib.Path(sys.argv[2]).write_text(key)
pathlib.Path(sys.argv[3]).write_text("restrict " + key)
PY
fingerprint=$(ssh-keygen -l -E sha256 -f "$BACKUP/key.pub")
read -r _ fingerprint _ <<< "$fingerprint"
[[ $fingerprint == SHA256:* ]] || die "public key fingerprint validation failed."
python3 -I - "$SOURCE_DIR/gate.py" "$SOURCE_DIR/controller.py" <<'PY'
import pathlib, sys
for filename in sys.argv[1:]:
    compile(pathlib.Path(filename).read_text(), filename, "exec")
PY

if getent passwd "$ACCOUNT" >/dev/null; then
    IFS=: read -r name _ uid gid _ home shell < <(getent passwd "$ACCOUNT")
    [[ $uid == "$ACCOUNT_UID" && $gid == "$ACCOUNT_GID" && $home == "$HOME_DIR" && $shell == /bin/sh ]] || die "existing deployment account does not match fixed identity."
    [[ $(id -G "$ACCOUNT") == "$ACCOUNT_GID" ]] || die "deployment account has supplementary privileges."
    [[ $(passwd -S "$ACCOUNT" | awk '{print $2}') == L ]] || die "deployment account password must be locked."
else
    ! getent passwd "$ACCOUNT_UID" >/dev/null || die "UID 20001 is already allocated."
fi
if getent group "$ACCOUNT" >/dev/null; then
    IFS=: read -r _ _ gid members < <(getent group "$ACCOUNT")
    [[ $gid == "$ACCOUNT_GID" && -z $members ]] || die "existing deployment group does not match fixed identity."
else
    ! getent group "$ACCOUNT_GID" >/dev/null || die "GID 20001 is already allocated."
    GROUP_CREATED=1
    groupadd --gid "$ACCOUNT_GID" "$ACCOUNT"
fi
if ! getent passwd "$ACCOUNT" >/dev/null; then
    ACCOUNT_CREATED=1
    useradd --uid "$ACCOUNT_UID" --gid "$ACCOUNT_GID" --no-user-group --no-create-home \
        --home-dir "$HOME_DIR" --shell /bin/sh --password '!' "$ACCOUNT"
fi

make_directory "$STATE" 755
make_directory "$STATE/releases" 700
make_directory "$HOME_DIR" 755
make_directory "$CONFIG" 700
[[ -d /usr/local/libexec ]] || make_directory /usr/local/libexec 755
[[ -d /etc/ssh/authorized_keys ]] || make_directory /etc/ssh/authorized_keys 755

for policy in "$PROJECT" "$PROJECT/docker-compose.prod.yml" "$PROJECT/nginx" "$PROJECT/nginx/nginx.conf" "$PROJECT/nginx/default.conf"; do root_own "$policy"; done
atomic_install "$SOURCE_DIR/gate.py" "$GATE" 755
atomic_install "$SOURCE_DIR/controller.py" "$CONTROLLER" 755
atomic_install "$PROJECT/docker-compose.prod.yml" "$CONFIG/compose.yml" 600
atomic_install "$SOURCE_DIR/security.override.yml" "$CONFIG/security.override.yml" 600
atomic_install "$BACKUP/authorized_keys" "$KEYS" 644

cat > "$BACKUP/sshd.conf" <<EOF
# Managed by the manually installed Onlinepolis deployment policy.
Match User $ACCOUNT
    AuthorizedKeysFile $KEYS
    ForceCommand $GATE
    AuthenticationMethods publickey
    PubkeyAuthentication yes
    PasswordAuthentication no
    KbdInteractiveAuthentication no
    DisableForwarding yes
    PermitTTY no
    PermitUserRC no
Match all
EOF
cat > "$BACKUP/sudoers" <<EOF
Defaults:$ACCOUNT env_reset, !setenv
Defaults:$ACCOUNT secure_path=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
$ACCOUNT ALL=(root) NOPASSWD: $CONTROLLER *
EOF
visudo -cf "$BACKUP/sudoers" >/dev/null
atomic_install "$BACKUP/sudoers" "$SUDOERS" 440
atomic_install "$BACKUP/sshd.conf" "$SSHD_CONFIG" 600
visudo -cf /etc/sudoers >/dev/null
sshd -t
sshd -T -C "user=$ACCOUNT,host=localhost,addr=127.0.0.1" | python3 -I -c '
import sys
settings = dict(line.rstrip().split(" ", 1) for line in sys.stdin if " " in line)
expected = {"forcecommand": "/usr/local/libexec/onlinepolis-deploy-gate", "authorizedkeysfile": "/etc/ssh/authorized_keys/onlinepolis-deploy", "disableforwarding": "yes", "permittty": "no", "passwordauthentication": "no", "kbdinteractiveauthentication": "no", "permituserrc": "no", "authenticationmethods": "publickey"}
if any(settings.get(key) != value for key, value in expected.items()):
    raise SystemExit("Effective SSH deployment policy differs; refusing reload.")
'
RELOAD_ATTEMPTED=1
systemctl reload "$SSH_SERVICE"
COMMITTED=1
echo "Restricted deployment identity installed. Public-key fingerprint: $fingerprint"
echo "Root-only installation snapshot: $BACKUP"
echo "Existing root keys and GitHub secrets were not changed."
