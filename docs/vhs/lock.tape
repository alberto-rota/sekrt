# Session cache: `sekrt unlock` (passphrase once), then add/get with no prompt,
# tab-completing the name, then `lock`.
# Regenerate from the repo root: vhs docs/vhs/lock.tape
Output docs/lock.gif

Require sekrt

Set Shell bash
Set FontSize 18
Set Width 1200
Set Height 480
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

Env HOME "/tmp/sekrt-vhs-lock"
Env GIT_CONFIG_GLOBAL "/tmp/sekrt-vhs-lock/.gitconfig"

# Deliberately no $SEKRT_VAULT: the unlock prompt is `🔐 passphrase ❯`, the
# same as a real machine. No $SEKRT_PASSPHRASE either: that prompt is the
# point of this tape. Init still needs one, so it is set only for that
# hidden command.

Hide
# VHS's stock bash prompt is purple; this one keeps the red accent instead. No
# `\w` here: the recording runs from the repo root, whatever that happens to be.
Type `export PS1="\[\e[1;38;2;255;0;0m\]❯\[\e[0m\] "`
Enter
# The recording shell inherits the host env; drop a leftover passphrase or
# vault override so `unlock` prompts as a stock install would. Fake $HOME
# keeps the real vault out of reach. `lock` drops any leftover session cache.
# `;` not `&&` on `clear`. `</dev/null` skips the "already have a vault?"
# question (`init` only asks that on a tty).
Type "unset SEKRT_PASSPHRASE SEKRT_VAULT TUPACS_VAULT XDG_DATA_HOME XDG_CONFIG_HOME BASH_COMPLETION_USER_DIR; rm -rf /tmp/sekrt-vhs-lock && mkdir -p /tmp/sekrt-vhs-lock && git config --global user.name Demo && git config --global user.email demo@example.com && git config --global init.defaultBranch main && SEKRT_PASSPHRASE=demo-passphrase-only sekrt init </dev/null >/dev/null; sekrt lock >/dev/null; echo Zj0kSE9NRS8ubG9jYWwvc2hhcmUvYmFzaC1jb21wbGV0aW9uL2NvbXBsZXRpb25zL3Nla3J0CnNlZCAtaS5iYWsgJ3MvY29tcGxldGUgLW8gbm9zb3J0IC1GL2NvbXBsZXRlIC1GLycgIiRmIgpzb3VyY2UgIiRmIgpwcmludGYgJ1wwMzNbMUFcMDMzWzJLJwo= | base64 -D > /tmp/sekrt-vhs-lock/b.sh; clear"
Enter
Sleep 2s
Show

Type "sekrt unlock"
Enter
Sleep 1500ms
Type "demo-passphrase-only"
Enter
Sleep 2s

Type "sekrt add work/openai -t api_key -u alberto -g --no-symbols -L 28"
Enter
Sleep 2s

# `unlock` wrote the bash completion script, but this shell is macOS bash 3.2
# (no `complete -o nosort`, and no bash-completion loader). `b.sh` binds it and
# erases its own line, so the recording never shows the workaround.
Hide
Type ". /tmp/sekrt-vhs-lock/b.sh"
Enter
Sleep 500ms
Show

Type "sekrt get w"
Sleep 1s
Tab
Sleep 1500ms
Enter
Sleep 2s
# Dismiss `press c to copy` (raw one-key read; anything but `c`).
Type "x"
Sleep 1s

Type "sekrt lock"
Enter
Sleep 4s

Sleep 3s
