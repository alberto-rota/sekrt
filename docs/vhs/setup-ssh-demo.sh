#!/usr/bin/env bash
# Build the fixture the SSH authorize demo tape records against.
#
# Two fake machines (host / other) share one vault. An unprivileged sshd
# listens on localhost and only accepts keys that land in the host's
# authorized_keys — so the tape can show `ssh studio` fail, then
# `sekrt ssh authorize` make it work.
#
# Usage: setup-ssh-demo.sh [DEMO_HOME]   (default: /tmp/sekrt-vhs-ssh)
# Safe to re-run: the directory is deleted and rebuilt from scratch.

set -euo pipefail

DEMO_HOME="${1:-/tmp/sekrt-vhs-ssh}"
PORT=22222

case "$DEMO_HOME" in
    /tmp/* | /private/tmp/* | /var/folders/*) ;;
    *) echo "refusing to rm -rf '$DEMO_HOME' — pick a path under /tmp" >&2; exit 1 ;;
esac

stop_sshd() {
    if [[ -f "$DEMO_HOME/sshd.pid" ]]; then
        kill "$(cat "$DEMO_HOME/sshd.pid")" 2>/dev/null || true
        rm -f "$DEMO_HOME/sshd.pid"
    fi
    if command -v lsof >/dev/null; then
        lsof -ti "tcp:${PORT}" | xargs kill 2>/dev/null || true
    fi
}

stop_sshd

rm -rf "$DEMO_HOME"
mkdir -p \
    "$DEMO_HOME/host/.ssh" \
    "$DEMO_HOME/other/.ssh" \
    "$DEMO_HOME/vault" \
    "$DEMO_HOME/runtime" \
    "$DEMO_HOME/config"

chmod 700 "$DEMO_HOME/host/.ssh" "$DEMO_HOME/other/.ssh"
: > "$DEMO_HOME/host/.ssh/authorized_keys"
chmod 600 "$DEMO_HOME/host/.ssh/authorized_keys"

# git needs an identity for the vault's auto-commits. A fake one, in the
# fake home, so the real ~/.gitconfig is never in reach.
cat > "$DEMO_HOME/.gitconfig" <<'EOF'
[user]
	name = Demo
	email = demo@example.com
[init]
	defaultBranch = main
EOF

# The "other machine" types `ssh studio`. Paths are absolute: OpenSSH on
# macOS expands `~` from the passwd home, not $HOME, so a relative
# IdentityFile would pick up the host's real keys. IdentityAgent none so a
# forwarded agent cannot make the first attempt succeed before authorize.
cat > "$DEMO_HOME/other/.ssh/config" <<EOF
Host studio
	HostName 127.0.0.1
	Port ${PORT}
	User $(whoami)
	IdentityFile ${DEMO_HOME}/other/.ssh/studio
	IdentitiesOnly yes
	IdentityAgent none
	PreferredAuthentications publickey
	StrictHostKeyChecking no
	UserKnownHostsFile /dev/null
	LogLevel ERROR
	BatchMode yes
EOF
chmod 600 "$DEMO_HOME/other/.ssh/config"

# Wrapper so the tape can type `ssh studio` without reading the host's
# ~/.ssh/config (OpenSSH ignores $HOME for that file).
mkdir -p "$DEMO_HOME/other/bin"
cat > "$DEMO_HOME/other/bin/ssh" <<EOF
#!/bin/sh
# -F: ignore the host's ~/.ssh/config (OpenSSH does not honour \$HOME for it).
# Rewrite the deny line so the recording does not leak the real \$USER.
err=\$(mktemp)
/usr/bin/ssh -F "${DEMO_HOME}/other/.ssh/config" "\$@" 2>"\$err"
code=\$?
sed -e '/^[[:space:]]*$/d' -e 's/.*Permission denied.*/Permission denied (publickey)./' "\$err" >&2
rm -f "\$err"
exit \$code
EOF
chmod 755 "$DEMO_HOME/other/bin/ssh"

ssh-keygen -q -t ed25519 -f "$DEMO_HOME/ssh_host_ed25519_key" -N "" -C ""
chmod 600 "$DEMO_HOME/ssh_host_ed25519_key"

SSHD=/usr/sbin/sshd
if [[ ! -x "$SSHD" ]]; then
    SSHD="$(command -v sshd)"
fi

# ForceCommand keeps a successful login to one canned line — no real
# hostname, no real $USER leaking into the recording.
cat > "$DEMO_HOME/sshd_config" <<EOF
Port ${PORT}
ListenAddress 127.0.0.1
HostKey ${DEMO_HOME}/ssh_host_ed25519_key
PidFile ${DEMO_HOME}/sshd.pid
AuthorizedKeysFile ${DEMO_HOME}/host/.ssh/authorized_keys
PasswordAuthentication no
KbdInteractiveAuthentication no
PubkeyAuthentication yes
UsePAM no
StrictModes no
PrintMotd no
PrintLastLog no
ForceCommand /bin/echo '✔ connected'
EOF

"$SSHD" -f "$DEMO_HOME/sshd_config" -E "$DEMO_HOME/sshd.log"

export HOME="$DEMO_HOME"
export GIT_CONFIG_GLOBAL="$DEMO_HOME/.gitconfig"
export SEKRT_VAULT="$DEMO_HOME/vault"
export SEKRT_PASSPHRASE="${SEKRT_PASSPHRASE:-demo-passphrase-only}"
export XDG_RUNTIME_DIR="$DEMO_HOME/runtime"
export XDG_CONFIG_HOME="$DEMO_HOME/config"

# </dev/null skips the "already have a vault pushed to a git repo?" fork,
# which `init` only asks on a tty — and under VHS this script *is* on one.
sekrt init </dev/null >/dev/null

echo "demo home ready: $DEMO_HOME"
