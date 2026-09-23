# Store a key, fail to log in, authorize, then connect.
# Two tmux panes side by side (VHS has no split of its own).
# Regenerate from the repo root: vhs docs/vhs/ssh.tape
#
# Requires tmux and an unprivileged sshd (see setup-ssh-demo.sh). The
# preamble is duplicated across tapes on purpose: VHS drops a tape's own
# `Set` lines when it uses `Source`.
Output docs/ssh.gif

Require sekrt
Require bash
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

# A fake $HOME pointed at the demo fixture (see setup-ssh-demo.sh): two
# machines share a vault, the recorded prompt reads `~`, and the real
# ~/.ssh / ~/.gitconfig are never in reach.
Env HOME "/tmp/sekrt-vhs-ssh"
Env GIT_CONFIG_GLOBAL "/tmp/sekrt-vhs-ssh/.gitconfig"
Env SEKRT_VAULT "/tmp/sekrt-vhs-ssh/vault"
Env XDG_RUNTIME_DIR "/tmp/sekrt-vhs-ssh/runtime"
Env XDG_CONFIG_HOME "/tmp/sekrt-vhs-ssh/config"

# Non-interactive passphrase, so the demo stays about `ssh authorize`
# rather than about passphrase prompts. Never do this outside a throwaway
# demo vault.
Env SEKRT_PASSPHRASE "demo-passphrase-only"

Env PAGER "cat"
Env GIT_PAGER "cat"

# tmux 3.x otherwise paints a second "active pane" marker that fights the
# metal palette.
Env TMUX ""

Hide
Type "bash docs/vhs/setup-ssh-demo.sh"
Enter
Wait+Screen@90s /demo home ready/

# Prompt in metal gray with the red accent chevron. Written to a file so
# both tmux panes can source the same one without fighting VHS quoting.
Type `printf '%s\n' 'export PS1="\[\e[38;2;170;170;170m\]\w \[\e[1;38;2;255;0;0m\]❯\[\e[0m\] "' > ~/.demo-ps1.sh`
Enter

# Isolated tmux server so this recording never touches a real session.
# `-d` on the split keeps focus on the left pane.
Type "tmux -L sekrt-vhs-ssh kill-server >/dev/null 2>&1; tmux -f /dev/null -L sekrt-vhs-ssh new-session -s demo -- bash"
Enter
Sleep 800ms

# Left pane is wider so the public key stays on one line at FontSize 16.
Type "tmux split-window -d -h -p 34 -- bash"
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
Type "tmux select-pane -t 0 -T 'this machine'"
Enter
Type "tmux select-pane -t 1 -T 'other machine'"
Enter
Sleep 400ms

Type "export HOME=/tmp/sekrt-vhs-ssh/host && . /tmp/sekrt-vhs-ssh/.demo-ps1.sh && cd && clear"
Enter
# Pane 1 waits for the vault entry, restores the private key, then clears
# — so the tape never types `restore` and this pane stays a clean prompt.
Type `tmux send-keys -t 1 'export HOME=/tmp/sekrt-vhs-ssh/other PATH="/tmp/sekrt-vhs-ssh/other/bin:$PATH" && . /tmp/sekrt-vhs-ssh/.demo-ps1.sh && cd && clear && while [ ! -f /tmp/sekrt-vhs-ssh/vault/ssh/studio.skr ]; do sleep 0.2; done && sekrt ssh restore studio --dir ~/.ssh >/dev/null && clear' Enter`
Enter
Sleep 1s
Type "clear"
Enter
Sleep 400ms
Show

# --- left: store a fresh keypair -----------------------------------------
# The other machine's private key is restored as soon as this entry
# hits the vault — no `tmux send-keys` on this pane.
Type "sekrt ssh add studio --generate --comment studio"
Enter
Sleep 4s

Hide
Ctrl+B
Sleep 200ms
Type "o"
Sleep 400ms
Show

# --- right: no login yet -------------------------------------------------
Type "ssh studio"
Enter
Sleep 4s

# --- left: authorize the key for login -----------------------------------
Hide
Ctrl+B
Sleep 200ms
Type "o"
Sleep 400ms
Show

Type "sekrt ssh authorize studio"
Enter
Sleep 3s

# --- right: the same ssh now lands ---------------------------------------
Hide
Ctrl+B
Sleep 200ms
Type "o"
Sleep 400ms
Show

Type "ssh studio"
Enter
Sleep 6s
