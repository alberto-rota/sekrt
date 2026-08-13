#!/usr/bin/env bash
# Build the fixture the `run` and inline-form demo tapes record against.
#
# Both tapes need what a real working machine has: a repo whose `.env` is
# already in the vault (that is half of what an unnamed `sekrt run` hands over)
# and a few API keys (the other half). Everything lives under a single directory
# used as a fake $HOME, so the recorded prompt reads `~/code/my-saas` instead of
# a /tmp path and the real vault is never in reach.
#
# Usage: setup-run-demo.sh [DEMO_HOME]        (default: /tmp/sekrt-vhs-run)
# Safe to re-run: the directory is deleted and rebuilt from scratch.

set -euo pipefail

DEMO_HOME="${1:-/tmp/sekrt-vhs-run}"

case "$DEMO_HOME" in
    /tmp/* | /private/tmp/* | /var/folders/*) ;;
    *) echo "refusing to rm -rf '$DEMO_HOME' — pick a path under /tmp" >&2; exit 1 ;;
esac

rm -rf "$DEMO_HOME"
mkdir -p "$DEMO_HOME/code/my-saas"

# git needs an identity to commit, and the vault's auto-commits would fail
# without one. A fake one, in the fake home, off the real ~/.gitconfig.
cat > "$DEMO_HOME/.gitconfig" <<'EOF'
[user]
	name = Demo
	email = demo@example.com
[init]
	defaultBranch = main
EOF

# The prompt for the recorded shell — and for the subshell `sekrt shell` opens,
# which sources this file like any other bash session, so the two match and the
# only difference on screen is the 🔓.
cat > "$DEMO_HOME/.bashrc" <<'EOF'
PS1="\[\e[38;2;170;170;170m\]\w \[\e[1;38;2;255;0;0m\]❯\[\e[0m\] "
EOF

export HOME="$DEMO_HOME"
export GIT_CONFIG_GLOBAL="$DEMO_HOME/.gitconfig"
# No $SEKRT_VAULT: the vault lands at its stock path *inside* the fake home, so
# the recording shows what a real machine shows.
export SEKRT_PASSPHRASE="demo-passphrase-only"

printf 'n\n' | sekrt init >/dev/null   # piped stdin: skips the "already have a vault?" question

# Generated, not piped in: `sekrt add` reads a typed secret through getpass,
# which reads /dev/tty — so a here-doc or a pipe is ignored under a recording's
# pty and the fixture would hang waiting for a keyboard.
for name in tokens/uv-publish-token work/github-token cloud/aws-access-key; do
    sekrt add "$name" -t api_key -g --no-symbols -L 28 >/dev/null
done

cd "$DEMO_HOME/code/my-saas"
git init -q .
git remote add origin git@github.com:you/my-saas.git
printf 'DATABASE_URL=postgres://localhost/dev\nPORT=8080\n' > .env
sekrt env push >/dev/null

echo "demo home ready"
