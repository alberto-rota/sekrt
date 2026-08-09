#!/usr/bin/env bash
# Build the fixture the `.env` demo tapes record against.
#
# The tapes need something the real workflow can't fake: actual git repos with
# an `origin` remote (that URL is what sekrt keys stored env files by) and a
# *fresh clone* of one of them with no `.env` in it. This script creates both,
# plus a throwaway vault, under a single directory used as a fake $HOME so the
# recorded prompt reads `~/code/my-saas` instead of a /tmp path.
#
# Usage: setup-env-demo.sh [DEMO_HOME]        (default: /tmp/sekrt-vhs-env)
# Safe to re-run: the directory is deleted and rebuilt from scratch.

set -euo pipefail

DEMO_HOME="${1:-/tmp/sekrt-vhs-env}"

case "$DEMO_HOME" in
    /tmp/* | /private/tmp/* | /var/folders/*) ;;
    *) echo "refusing to rm -rf '$DEMO_HOME' — pick a path under /tmp" >&2; exit 1 ;;
esac

rm -rf "$DEMO_HOME"
mkdir -p "$DEMO_HOME/code" "$DEMO_HOME/clones"

# Fake HOME: git needs an identity to commit, and sekrt's auto-commits would
# fail without one. Also keeps the demo off the real ~/.gitconfig.
cat > "$DEMO_HOME/.gitconfig" <<'EOF'
[user]
	name = Demo
	email = demo@example.com
[init]
	defaultBranch = main
[advice]
	detachedHead = false
EOF

export HOME="$DEMO_HOME"
export GIT_CONFIG_GLOBAL="$DEMO_HOME/.gitconfig"

# --- the "laptop" repo: a small SaaS with one .env ------------------------
saas="$DEMO_HOME/code/my-saas"
mkdir -p "$saas"
git -C "$saas" init -q
git -C "$saas" remote add origin git@github.com:you/my-saas.git

cat > "$saas/.env" <<'EOF'
DATABASE_URL=postgres://app:EXAMPLE-ONLY@db.internal:5432/my_saas
STRIPE_SECRET_KEY=sk_test_EXAMPLE_NOT_A_REAL_KEY
SESSION_SECRET=EXAMPLE-9f2b7c41ea8d6503b1fa77cc2e40d9be
SMTP_PASSWORD=EXAMPLE-not-a-real-password
EOF

cat > "$saas/.gitignore" <<'EOF'
.env
.env.*
!.env.example
__pycache__/
EOF

cat > "$saas/.env.example" <<'EOF'
DATABASE_URL=
STRIPE_SECRET_KEY=
SESSION_SECRET=
SMTP_PASSWORD=
EOF

cat > "$saas/README.md" <<'EOF'
# my-saas

Copy `.env.example` to `.env` and fill it in. (Or: `sekrt env pull`.)
EOF

git -C "$saas" add -A
git -C "$saas" -c commit.gpgsign=false commit -qm "Initial commit"

# --- the monorepo: several env files, one per service ---------------------
mono="$DEMO_HOME/code/acme-platform"
mkdir -p "$mono/apps/api" "$mono/apps/web" "$mono/infra"
git -C "$mono" init -q
git -C "$mono" remote add origin git@github.com:acme/platform.git

cat > "$mono/.env" <<'EOF'
COMPOSE_PROJECT_NAME=acme
LOG_LEVEL=debug
EOF

cat > "$mono/apps/api/.env.production" <<'EOF'
DATABASE_URL=postgres://api:EXAMPLE-ONLY@prod-db.acme.internal:5432/api
REDIS_URL=redis://prod-cache.acme.internal:6379/0
JWT_SIGNING_KEY=EXAMPLE-eyJhbGciOiJIUzI1NiJ9-not-real
EOF

cat > "$mono/apps/web/.env.local" <<'EOF'
NEXT_PUBLIC_API_URL=https://api.acme.dev
SENTRY_AUTH_TOKEN=EXAMPLE-sntrys-not-real
EOF

cat > "$mono/infra/.env.staging" <<'EOF'
AWS_ACCESS_KEY_ID=AKIAIOSFODNN7EXAMPLE
AWS_SECRET_ACCESS_KEY=wJalrXUtnFEMI-K7MDENG-EXAMPLEKEY
EOF

printf '.env\n.env.*\n' > "$mono/.gitignore"
git -C "$mono" add -A
git -C "$mono" -c commit.gpgsign=false commit -qm "Initial commit"

# --- the "other machine": a fresh clone with no .env ---------------------
# Cloned from the local path, then origin is rewritten to the URL a real
# `git clone git@github.com:you/my-saas.git` would leave behind — that URL is
# the vault key, so it has to match the laptop repo's.
git clone -q "$saas" "$DEMO_HOME/clones/my-saas"
git -C "$DEMO_HOME/clones/my-saas" remote set-url origin git@github.com:you/my-saas.git
rm -f "$DEMO_HOME/clones/my-saas/.env"   # .env is gitignored, but the clone source has one

# --- a repo with no remote, to show the local/<dirname> fallback ---------
scratch="$DEMO_HOME/code/scratch-tool"
mkdir -p "$scratch"
git -C "$scratch" init -q
printf 'OPENAI_API_KEY=sk-proj-EXAMPLE-NOT-A-REAL-KEY\n' > "$scratch/.env"
printf '.env\n' > "$scratch/.gitignore"
git -C "$scratch" add -A
git -C "$scratch" -c commit.gpgsign=false commit -qm "Initial commit"

# --- the vault -----------------------------------------------------------
# SEKRT_PASSPHRASE makes init non-interactive; the vault lands in the fake
# HOME's default location so nothing in the demo references a /tmp path.
export SEKRT_PASSPHRASE="${SEKRT_PASSPHRASE:-demo-passphrase-only}"
sekrt init >/dev/null
sekrt add work/github -u alberto -g >/dev/null   # so `ls` isn't env-only

echo "demo home ready: $DEMO_HOME"
