#!/usr/bin/env bash
# Build the fixture the README's hero tape records against.
#
# The hero gif has 20 seconds to show both halves of sekrt, so the vault has to
# look like a vault someone actually uses: a few folders, every entry type, and
# a repo whose `.env` is already stored. Everything lives under a single
# directory used as a fake $HOME, so the recorded prompt reads `~/code/my-saas`
# instead of a /tmp path and the real vault is never in reach.
#
# `api/openai-api-key` is deliberately absent — the tape adds it on camera.
#
# Usage: setup-hero-demo.sh [DEMO_HOME]       (default: /tmp/sekrt-vhs-hero)
# Safe to re-run: the directory is deleted and rebuilt from scratch.

set -euo pipefail

DEMO_HOME="${1:-/tmp/sekrt-vhs-hero}"

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

# The prompt for the recorded shell — and for any subshell it opens, which
# sources this file like any other bash session.
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
# Entry names are chosen for what `sekrt run` reads them as: `api/anthropic-api-key`
# is handed over as $ANTHROPIC_API_KEY, so the dry-run table looks like a real
# .env rather than a list of nicknames.
sekrt add work/github -u alberto -g \
    --url https://github.com --notes 'personal account · 2fa via authenticator' >/dev/null
sekrt add work/gitlab   -u alberto -g >/dev/null
sekrt add infra/grafana -u admin   -g >/dev/null
sekrt add api/anthropic-api-key -t api_key -g --no-symbols -L 28 \
    --url https://console.anthropic.com --notes 'billing alerts on at $200' >/dev/null
for name in cloud/aws-access-key cloud/cloudflare-token; do
    sekrt add "$name" -t api_key -g --no-symbols -L 28 >/dev/null
done
sekrt ssh add laptop --generate >/dev/null

cd "$DEMO_HOME/code/my-saas"
git init -q .
git remote add origin git@github.com:you/my-saas.git
printf 'DATABASE_URL=postgres://localhost/dev\nPORT=8080\n' > .env
printf '.env\n' > .gitignore
sekrt env push >/dev/null

echo "demo home ready"
