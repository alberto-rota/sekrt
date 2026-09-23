# The inline picker: `sekrt get` with no arguments, and the unlock prompt above it.
# Regenerate from the repo root: vhs docs/vhs/get.tape
Output docs/get.gif

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

Env HOME "/tmp/sekrt-vhs-get"
Env GIT_CONFIG_GLOBAL "/tmp/sekrt-vhs-get/.gitconfig"

# Deliberately no $SEKRT_VAULT: the unlock prompt is `🔐 passphrase ❯`, the
# same as a real machine. No $SEKRT_PASSPHRASE either: that prompt is half of
# what this tape is showing. Init and the seeded `add`s still need one, so it
# is set only for those hidden commands.

Hide
# VHS's stock bash prompt is purple; this one keeps the red accent instead. No
# `\w` here: the recording runs from the repo root, whatever that happens to be.
Type `export PS1="\[\e[1;38;2;255;0;0m\]❯\[\e[0m\] "`
Enter
# The recording shell inherits the host env; drop a leftover passphrase or
# vault override so `get` prompts as a stock install would. Fake $HOME keeps
# the real vault out of reach. Seed a few entries for the picker, then `lock`
# so the passphrase is asked on camera. `;` not `&&` on `clear`. `</dev/null`
# skips the "already have a vault?" question (`init` only asks that on a tty).
Type "unset SEKRT_PASSPHRASE SEKRT_VAULT TUPACS_VAULT; rm -rf /tmp/sekrt-vhs-get && mkdir -p /tmp/sekrt-vhs-get && git config --global user.name Demo && git config --global user.email demo@example.com && git config --global init.defaultBranch main && P=demo-passphrase-only; SEKRT_PASSPHRASE=$P sekrt init </dev/null >/dev/null && SEKRT_PASSPHRASE=$P sekrt add work/github -u alberto -g >/dev/null && SEKRT_PASSPHRASE=$P sekrt add work/openai -t api_key -g --no-symbols -L 28 >/dev/null && SEKRT_PASSPHRASE=$P sekrt add cloud/aws -t api_key -g >/dev/null; sekrt lock >/dev/null; clear"
Enter
Sleep 3s
Show

Type "sekrt get"
Enter
Sleep 1500ms
Type "demo-passphrase-only"
Enter
Sleep 2500ms
Down
Sleep 700ms
Down
Sleep 1500ms
Enter
Sleep 2s
Type "c"
Sleep 4s

Sleep 3s
