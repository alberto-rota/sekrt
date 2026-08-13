# The inline form: `sekrt add` with no arguments, and the unlock prompt above it.
# Regenerate from the repo root: vhs docs/vhs/forms.tape
#
# The preamble below is duplicated across tapes on purpose: VHS drops a tape's
# own `Set` lines when it uses `Source`, so a shared settings file would
# silently override the per-tape Height each tape needs.
Output docs/forms.gif

Require sekrt
Require bash
Require git

Set Shell bash
Set FontSize 18
Set Width 1200
Set Height 340          # fits this tape's longest scene (the form, ~11 lines)
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

Env HOME "/tmp/sekrt-vhs-run"
Env GIT_CONFIG_GLOBAL "/tmp/sekrt-vhs-run/.gitconfig"
Env GIT_PAGER "cat"
Env PAGER "cat"

# Deliberately no $SEKRT_PASSPHRASE here: the unlock prompt is half of what this
# tape is showing.

Hide
Type "bash docs/vhs/setup-run-demo.sh"
Enter
Wait+Screen@90s /demo home ready/
Type `export PS1="\[\e[38;2;170;170;170m\]\w \[\e[1;38;2;255;0;0m\]❯\[\e[0m\] "`
Enter
Type "cd ~/code/my-saas && clear"
Enter
Sleep 1s
Show

# No NAME: the six flags become six fields.
Type "sekrt add"
Enter
Sleep 1s
Type "demo-passphrase-only"
Enter
Sleep 2500ms

Type "cloud/stripe"
Sleep 1s
Tab
Sleep 700ms
# ←/→ walks the type row
Right
Sleep 1500ms
Tab
Sleep 500ms
Tab
Sleep 700ms
# ctrl+g fills the secret in
Ctrl+G
Sleep 2s
Enter
Sleep 3s

Type "sekrt show cloud/stripe"
Enter
Sleep 1s
Type "demo-passphrase-only"
Enter
Sleep 4s
