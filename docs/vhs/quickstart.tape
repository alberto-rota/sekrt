# Regenerate: `vhs docs/vhs/quickstart.tape` (from repo root, with sekrt installed)
Output docs/quickstart.gif

Require sekrt

Set Shell bash
Set FontSize 18
Set Width 1200
Set Height 680
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

Env SEKRT_VAULT "/tmp/sekrt-vhs-demo"
Env SEKRT_PASSPHRASE "demo-passphrase-only"

Hide
# VHS's stock bash prompt is purple; this one keeps the red accent instead. No
# `\w` here: the recording runs from the repo root, whatever that happens to be.
Type `export PS1="\[\e[1;38;2;255;0;0m\]❯\[\e[0m\] "`
Enter
Type "rm -rf /tmp/sekrt-vhs-demo && clear"
Enter
Sleep 500ms
Show

Type "sekrt init"
Enter
Sleep 2s

# `init` asks this on a tty: a second machine has to `clone`, not `init`. This
# demo is the first machine, so: no.
Type "n"
Enter
Sleep 5s

Type "sekrt add work/github -u alberto -g"
Enter
Sleep 5s

Type "sekrt get work/github"
Enter
Sleep 4s

Type "sekrt add cloud/aws -t api_key -g"
Enter
Sleep 5s

Type "sekrt ls"
Enter
Sleep 3s

Type "sekrt show work/github"
Enter
Sleep 5s

Type "sekrt status"
Enter
Sleep 3s
