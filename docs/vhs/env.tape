# The headline `.env` round-trip: push on one machine, pull in a fresh clone.
# Regenerate from the repo root: vhs docs/vhs/env.tape
#
# The preamble below is duplicated across the env tapes on purpose: VHS drops a
# tape's own `Set` lines when it uses `Source`, so a shared settings file would
# silently override the per-tape Height each tape needs.
Output docs/env.gif

Require tupacs
Require bash
Require git

Set Shell bash
Set FontSize 18
Set Width 1200
Set Height 480          # fits this tape's longest scene (~19 lines)
Set Framerate 12
Set Theme "Catppuccin Mocha"
Set TypingSpeed 45ms
Set Padding 20

# A fake $HOME pointed at the demo fixture (see setup-env-demo.sh): the prompt
# reads `~/code/my-saas` instead of a /tmp path, the vault lands somewhere
# throwaway, and the real ~/.gitconfig is untouched.
Env HOME "/tmp/tupacs-vhs-env"
Env GIT_CONFIG_GLOBAL "/tmp/tupacs-vhs-env/.gitconfig"

# Non-interactive passphrase, so the demo stays about `env` rather than about
# passphrase prompts. Never do this outside a throwaway demo vault.
Env TUPACS_PASSPHRASE "demo-passphrase-only"

# git on a tty opens `less`, which would eat every keystroke typed after it.
Env GIT_PAGER "cat"
Env PAGER "cat"

Hide
Type "bash docs/vhs/setup-env-demo.sh"
Enter
Wait+Screen@90s /demo home ready/
Type `export PS1="\[\e[38;5;147m\]\w\[\e[0m\] $ "`
Enter
Type "cd ~/code/my-saas && tupacs unlock -t 30 >/dev/null && clear"
Enter
Sleep 1s
Show

# --- scene 1: the laptop that has the .env -------------------------------
Type "# .env is gitignored, so it lives on this laptop and nowhere else"
Enter
Sleep 1500ms

Type "cat .env"
Enter
Sleep 3s

Type "git check-ignore -v .env"
Enter
Sleep 2500ms

Type "# encrypt it into the vault, keyed by this repo's origin URL"
Enter
Sleep 1500ms

Type "tupacs env push"
Enter
Sleep 3s

Type "tupacs env ls"
Enter
Sleep 3s

Hide
Type "clear"
Enter
Sleep 500ms
Show

# --- scene 2: months later, a fresh clone on another machine -------------
Type "# months later, a fresh clone on a different machine"
Enter
Sleep 1500ms

Type "cd ~/clones/my-saas"
Enter
Sleep 800ms

Type "git remote get-url origin"
Enter
Sleep 2s

Type "ls -a"
Enter
Sleep 3s

Type "# no .env, as expected. one command:"
Enter
Sleep 1500ms

Type "tupacs env pull"
Enter
Sleep 2500ms

Type "cat .env"
Enter
Sleep 3s

Type "ls -l .env"
Enter
Sleep 3500ms
