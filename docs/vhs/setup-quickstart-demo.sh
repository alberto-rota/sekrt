#!/usr/bin/env bash
# Fixture for docs/quickstart.gif.
#
# A vault that already holds one password, and a repo whose .env is not stored
# yet — the tape adds an API key, pushes that file, and runs a command with
# both. Everything lives under a fake $HOME except the vault, which stays at
# /tmp/sekrt-vhs-demo so docs/vhs/tui.tape can record against the same one.
#
# Usage: setup-quickstart-demo.sh [DEMO_HOME]
# Safe to re-run: both directories are deleted and rebuilt from scratch.

set -euo pipefail

DEMO_HOME="${1:-/tmp/sekrt-vhs-quickstart}"
VAULT="${SEKRT_VAULT:-/tmp/sekrt-vhs-demo}"

case "$DEMO_HOME" in
    /tmp/* | /private/tmp/* | /var/folders/*) ;;
    *) echo "refusing to rm -rf '$DEMO_HOME' — pick a path under /tmp" >&2; exit 1 ;;
esac
case "$VAULT" in
    /tmp/* | /private/tmp/* | /var/folders/*) ;;
    *) echo "refusing to rm -rf '$VAULT' — pick a path under /tmp" >&2; exit 1 ;;
esac

rm -rf "$DEMO_HOME" "$VAULT"
mkdir -p "$DEMO_HOME/code/my-saas"

cat > "$DEMO_HOME/.gitconfig" <<'EOF'
[user]
	name = Demo
	email = demo@example.com
[init]
	defaultBranch = main
EOF

# The subshell `sekrt shell` opens sources this, so its prompt matches the
# recording except for the `(sekrt)` tag.
cat > "$DEMO_HOME/.bashrc" <<'EOF'
PS1="\[\e[38;2;170;170;170m\]\w \[\e[1;38;2;255;0;0m\]❯\[\e[0m\] "
EOF

export HOME="$DEMO_HOME"
export GIT_CONFIG_GLOBAL="$DEMO_HOME/.gitconfig"
export SEKRT_VAULT="$VAULT"
export SEKRT_PASSPHRASE="${SEKRT_PASSPHRASE:-demo-passphrase-only}"

printf 'n\n' | sekrt init >/dev/null

# Already in the vault, so `ls` looks used. Generated: `sekrt add` reads a
# typed secret from /dev/tty, which a pipe cannot feed under vhs.
sekrt add work/github -u alberto -g >/dev/null

cd "$DEMO_HOME/code/my-saas"
git init -q .
git remote add origin git@github.com:you/my-saas.git
printf 'DATABASE_URL=postgres://localhost/dev\nPORT=8080\n' > .env

echo "demo home ready"
