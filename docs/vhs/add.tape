# The inline form: `sekrt add` with no arguments, and the unlock prompt above it.
# Regenerate from the repo root: vhs docs/vhs/add.tape
Output docs/add.gif

Require sekrt

Set Shell bash
Set FontSize 18
Set Width 1200
Set Height 340
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

Env HOME "/tmp/sekrt-vhs-add"
Env GIT_CONFIG_GLOBAL "/tmp/sekrt-vhs-add/.gitconfig"

# Deliberately no $SEKRT_VAULT: the unlock prompt is `🔐 passphrase ❯`, the
# same as a real machine. No $SEKRT_PASSPHRASE either: that prompt is half of
# what this tape is showing. Init still needs one, so it is set only for that
# one command.

Hide
# VHS's stock bash prompt is purple; this one keeps the red accent instead. No
# `\w` here: the recording runs from the repo root, whatever that happens to be.
Type `export PS1="\[\e[1;38;2;255;0;0m\]❯\[\e[0m\] "`
Enter
# The recording shell inherits the host env; drop a leftover passphrase or
# vault override so `add` prompts as a stock install would. Fake $HOME keeps
# the real vault out of reach. `lock` drops any leftover session cache.
# `;` not `&&` on `clear`: a failed init must not leak this hidden setup.
# `</dev/null` skips the "already have a vault?" question (`init` only asks
# that on a tty).
Type "unset SEKRT_PASSPHRASE SEKRT_VAULT TUPACS_VAULT; rm -rf /tmp/sekrt-vhs-add && mkdir -p /tmp/sekrt-vhs-add && git config --global user.name Demo && git config --global user.email demo@example.com && git config --global init.defaultBranch main && SEKRT_PASSPHRASE=demo-passphrase-only sekrt init </dev/null >/dev/null; sekrt lock >/dev/null; clear"
Enter
Sleep 2s
Show

Type "sekrt add"
Enter
Sleep 1500ms
Type "demo-passphrase-only"
Enter
Sleep 2500ms
Type "work/"
Sleep 500ms
Type "openai"
Sleep 500ms
Down
Sleep 500ms
Right
Sleep 1s
Down
Sleep 500ms
Type "username"
Sleep 500ms
Down
Sleep 500ms
Type "MY_OPENAI_API_KEY_35982v3cmhrutny3829cnmqhunow93f5inwhnh89f943852nv"
Enter
Sleep 4.5s

Sleep 3s
