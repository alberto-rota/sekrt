# `sekrt config`: ←/→ through the presets, then the unlock / clipboard / length
# fields, enter to keep them.

# Regenerate from the repo root: vhs docs/vhs/config.tape
#
# The preamble below is duplicated across tapes on purpose: VHS drops a tape's
# own `Set` lines when it uses `Source`, so a shared settings file would
# silently override the per-tape Height each tape needs.
Output docs/config.gif

Require sekrt

Set Shell bash
Set FontSize 18
Set Width 1200
Set Height 440          # 13 panel rows, plus the prompt above them
Set Framerate 12
# Palette mirrors the TUI's own `metal` theme (see src/sekrt/tui/app.py): gray
# structure, red accent, near-black background. The panel repaints over this
# as the presets change.
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

Env HOME "/tmp/sekrt-vhs-config"
Env GIT_CONFIG_GLOBAL "/tmp/sekrt-vhs-config/.gitconfig"
Env COLORTERM "truecolor"

# No vault and no passphrase: colors live in the config file, not the vault.
# Fake $HOME (and an unset $SEKRT_CONFIG) keeps this off the real palette.

Hide
# VHS's stock bash prompt is purple; this one keeps the red accent instead. No
# `\w` here: the recording runs from the repo root, whatever that happens to be.
Type `export PS1="\[\e[1;38;2;255;0;0m\]❯\[\e[0m\] "`
Enter
# The recording shell inherits the host env. Drop a config override so the
# panel opens on the stock metal palette, under the fake home. `NO_COLOR`
# makes Textual draw the panel in gray, which hides the whole point of this
# tape — an empty value still counts, so it has to be unset, not blanked.
Type "unset SEKRT_CONFIG TUPACS_CONFIG XDG_CONFIG_HOME NO_COLOR; rm -rf /tmp/sekrt-vhs-config && mkdir -p /tmp/sekrt-vhs-config; clear"
Enter
Sleep 2s
Show

Type "sekrt config"
Enter
Sleep 2s

# metal → teal → amber. Each lands as you arrive, chrome and all.
Right
Sleep 900ms
Right
Sleep 1200ms

# preset row, then primary, secondary, accent, unlock, clipboard.
Down
Sleep 200ms
Down
Sleep 200ms
Down
Sleep 200ms
Down
Sleep 200ms
Down
Sleep 600ms
# The field selects its contents on focus, so this replaces 45.
Type "15"
Sleep 900ms
Down
Sleep 400ms
Type "32"
Sleep 1200ms
Enter
Sleep 4s

Sleep 2s
