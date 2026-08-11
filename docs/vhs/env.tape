# The headline `.env` round-trip: push on one machine, pull in a fresh clone.
# Regenerate from the repo root: vhs docs/vhs/env.tape
#
# The preamble below is duplicated across the env tapes on purpose: VHS drops a
# tape's own `Set` lines when it uses `Source`, so a shared settings file would
# silently override the per-tape Height each tape needs.
Output docs/env.gif

Require sekrt
Require bash
Require git

Set Shell bash
Set FontSize 18
Set Width 1200
Set Height 480          # fits this tape's longest scene (~19 lines)
Set Framerate 12
# Palette mirrors the TUI's own `metal` theme (see src/sekrt/tui/app.py): gray
# structure, red accent, near-black background.
Set Theme {
  "name": "metal",
  "background": "#0d0e10", "foreground": "#d7dade",
  "selection": "#3a1010", "cursor": "#ff0000", "cursorAccent": "#0d0e10",
  "black": "#16181b",   "brightBlack":   "#6e737a",
  "red": "#ff0000",     "brightRed":     "#ff4d4d",
  "green": "#8fbf7a",   "brightGreen":   "#a9d197",
  "yellow": "#d9a13b",  "brightYellow":  "#e8bb6a",
  "blue": "#8b9199",    "brightBlue":    "#aab0b8",
  "magenta": "#c07a7a", "brightMagenta": "#d49a9a",
  "cyan": "#9aa2ab",    "brightCyan":    "#c3cad1",
  "white": "#aaaaaa",   "brightWhite":   "#eef0f2"
}
Set TypingSpeed 45ms
Set Padding 20

# A fake $HOME pointed at the demo fixture (see setup-env-demo.sh): the prompt
# reads `~/code/my-saas` instead of a /tmp path, the vault lands somewhere
# throwaway, and the real ~/.gitconfig is untouched.
Env HOME "/tmp/sekrt-vhs-env"
Env GIT_CONFIG_GLOBAL "/tmp/sekrt-vhs-env/.gitconfig"

# Non-interactive passphrase, so the demo stays about `env` rather than about
# passphrase prompts. Never do this outside a throwaway demo vault.
Env SEKRT_PASSPHRASE "demo-passphrase-only"

# git on a tty opens `less`, which would eat every keystroke typed after it.
Env GIT_PAGER "cat"
Env PAGER "cat"

Hide
Type "bash docs/vhs/setup-env-demo.sh"
Enter
Wait+Screen@90s /demo home ready/
# Prompt in metal gray with the red accent chevron, to match the TUI.
Type `export PS1="\[\e[38;2;170;170;170m\]\w \[\e[1;38;2;255;0;0m\]❯\[\e[0m\] "`
Enter
Type "cd ~/code/my-saas && sekrt unlock -t 30 >/dev/null && clear"
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

Type "sekrt env push"
Enter
Sleep 3s

Type "sekrt env ls"
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

Type "sekrt env pull"
Enter
Sleep 2500ms

Type "cat .env"
Enter
Sleep 3s

Type "ls -l .env"
Enter
Sleep 3500ms
