# Regenerate: run quickstart.tape first (populates the demo vault), then
# `vhs docs/vhs/tui.tape` (from repo root, with sekrt installed)
Output docs/tui.gif

Require sekrt

Set Shell bash
Set FontSize 18
Set Width 1200
Set Height 720
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
Set Padding 20

Env SEKRT_VAULT "/tmp/sekrt-vhs-demo"
Env SEKRT_PASSPHRASE "demo-passphrase-only"

Hide
# Matches quickstart.tape's prompt, so the two CLI/TUI demos look like one shell.
Type `export PS1="\[\e[1;38;2;255;0;0m\]❯\[\e[0m\] "`
Enter
# `;` not `&&`: clear unconditionally, so a failed unlock can't leak this
# hidden setup onto the first visible frame.
Type "sekrt unlock -t 5; clear"
Enter
Sleep 4s
Show

Type "sekrt"
Enter
Sleep 4s

Down
Sleep 1s
Down
Sleep 1s
Enter
Sleep 2s

Type "r"
Sleep 2s

Type "/"
Sleep 1s
Type "git"
Sleep 1s
Enter
Sleep 2s

Type "q"
Sleep 1s
