# Several env files in one repo (a monorepo with one per service), reading one
# back, and the commit trail every push leaves in the vault.
# Regenerate from the repo root: vhs docs/vhs/env-multi.tape
#
# Preamble duplicated across the env tapes on purpose — see the note in env.tape.
Output docs/env-multi.gif

Require sekrt
Require bash
Require git

Set Shell bash
Set FontSize 18
Set Width 1200
Set Height 380          # fits this tape's longest scene (~13 lines)
Set Framerate 12
Set Theme "Catppuccin Mocha"
Set TypingSpeed 45ms
Set Padding 20

Env HOME "/tmp/sekrt-vhs-env"
Env GIT_CONFIG_GLOBAL "/tmp/sekrt-vhs-env/.gitconfig"
Env SEKRT_PASSPHRASE "demo-passphrase-only"
Env GIT_PAGER "cat"
Env PAGER "cat"

Hide
Type "bash docs/vhs/setup-env-demo.sh"
Enter
Wait+Screen@90s /demo home ready/
Type `export PS1="\[\e[38;5;147m\]\w\[\e[0m\] $ "`
Enter
Type "cd ~/code/acme-platform && sekrt unlock -t 30 >/dev/null && clear"
Enter
Sleep 1s
Show

# --- scene 1: push every service's env file in one go --------------------
Type "# a monorepo: one env file per service, none of them in git"
Enter
Sleep 1500ms

Type "find . -name '.env*' -not -path './.git/*' | sort"
Enter
Sleep 3s

# Ordinary shell globbing — `push` just takes paths, however you spell them.
Type "sekrt env push .env apps/*/.env.* infra/.env.staging"
Enter
Sleep 4s

Type "sekrt env ls"
Enter
Sleep 4s

Hide
Type "clear"
Enter
Sleep 500ms
Show

# --- scene 2: each file is its own entry, and the vault is just git -------
Type "# each file is its own encrypted entry — read one back without a checkout"
Enter
Sleep 1500ms

Type "sekrt env show apps/api/.env.production"
Enter
Sleep 3500ms

Type "# every push is a commit — `sekrt sync` is what sends them to the remote"
Enter
Sleep 1500ms

Type "sekrt git log --oneline -5"
Enter
Sleep 4s
