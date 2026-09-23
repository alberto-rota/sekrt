# The headline `.env` round-trip: push on one machine, pull in a fresh clone.
# Two tmux panes side by side (VHS has no split of its own).
# Regenerate from the repo root: vhs docs/vhs/env.tape
#
# Requires tmux. The preamble below is duplicated across the env tapes on
# purpose: VHS drops a tape's own `Set` lines when it uses `Source`, so a
# shared settings file would silently override the per-tape Height each tape
# needs.
Output docs/env.gif

Require sekrt
Require bash
Require git
Require tmux

Set Shell bash
Set FontSize 16
Set Width 1920
Set Height 640
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
Set Padding 16

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
Env GIT_TERMINAL_PROMPT "0"

# tmux 3.x otherwise paints a second "active pane" marker that fights the
# metal palette.
Env TMUX ""

Hide
Type "bash docs/vhs/setup-env-demo.sh"
Enter
Wait+Screen@90s /demo home ready/

# Prompt in metal gray with the red accent chevron. Written to a file so both
# tmux panes can source the same one without fighting VHS quoting.
Type `printf '%s\n' 'export PS1="\[\e[38;2;170;170;170m\]\w \[\e[1;38;2;255;0;0m\]❯\[\e[0m\] "' > ~/.demo-ps1.sh`
Enter

# Isolated tmux server so this recording never touches a real session.
# `-d` on the split keeps focus on the left pane — without it, the new
# (right) pane would eat the laptop's `cd`.
Type "tmux -L sekrt-vhs-env kill-server >/dev/null 2>&1; tmux -f /dev/null -L sekrt-vhs-env new-session -s demo -- bash"
Enter
Sleep 800ms

Type "tmux split-window -d -h -- bash"
Enter
Type "tmux select-layout even-horizontal"
Enter
Type "tmux set -g status off"
Enter
Type "tmux set -g pane-border-status top"
Enter
Type "tmux set -g pane-border-format ' #{pane_title} '"
Enter
Type "tmux set -g pane-border-style 'fg=#6e737a'"
Enter
Type "tmux set -g pane-active-border-style 'fg=#ff0000'"
Enter
Type "tmux select-pane -t 0 -T 'this laptop'"
Enter
Type "tmux select-pane -t 1 -T 'fresh clone'"
Enter
Sleep 400ms

Type ". ~/.demo-ps1.sh && cd ~/code/my-saas && sekrt unlock -t 30 >/dev/null && clear"
Enter
Type `tmux send-keys -t 1 '. ~/.demo-ps1.sh && cd ~ && clear' Enter`
Enter
Sleep 1s
# Wipe the setup commands that were typed into this pane.
Type "clear"
Enter
Sleep 400ms
Show

# --- left: the laptop that has the .env ----------------------------------
Type "cat .env"
Enter
Sleep 3s

Type "git check-ignore -v .env"
Enter
Sleep 2500ms

Type "sekrt env push"
Enter
Sleep 3s

Type "sekrt ls | grep env"
Enter
Sleep 3s

# --- right: clone the same repo, no .env until pull ----------------------
Hide
Ctrl+B
Sleep 200ms
Type "o"
Sleep 400ms
Show

Type "git clone git@github.com:you/my-saas.git"
Enter
Sleep 3s

Type "cd my-saas"
Enter
Sleep 800ms

Type "ls -a"
Enter
Sleep 2500ms

Type "sekrt env pull"
Enter
Sleep 2500ms

Type "cat .env"
Enter
Sleep 4s
