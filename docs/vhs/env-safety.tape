# The guard rails: sekrt notices what actually changed, and never overwrites a
# local env file you've edited unless you ask it to.
# Regenerate from the repo root: vhs docs/vhs/env-safety.tape
#
# Preamble duplicated across the env tapes on purpose — see the note in env.tape.
Output docs/env-safety.gif

Require sekrt
Require bash
Require git

Set Shell bash
Set FontSize 18
Set Width 1200
Set Height 340          # fits this tape's longest scene (~11 lines)
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

Env HOME "/tmp/sekrt-vhs-env"
Env GIT_CONFIG_GLOBAL "/tmp/sekrt-vhs-env/.gitconfig"
Env SEKRT_PASSPHRASE "demo-passphrase-only"
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

# --- scene 1: push is idempotent, and reports what changed ----------------
Type "sekrt env push"
Enter
Sleep 2500ms

Type "# push again — nothing changed, so nothing is rewritten"
Enter
Sleep 1500ms

Type "sekrt env push"
Enter
Sleep 2500ms

Type "echo 'FEATURE_FLAGS=new-billing' >> .env"
Enter
Sleep 1200ms

Type "sekrt env push"
Enter
Sleep 3s

Hide
Type "clear"
Enter
Sleep 500ms
Show

# --- scene 2: pull refuses to clobber local edits -------------------------
Type "cd ~/clones/my-saas && sekrt env pull"
Enter
Sleep 2500ms

Type "# now edit the restored file locally, the way you would mid-debugging"
Enter
Sleep 1500ms

Type "echo 'LOG_LEVEL=trace' >> .env"
Enter
Sleep 1200ms

Type "sekrt env pull"
Enter
Sleep 3500ms

Type "# your edit survived. overwrite it only when you say so:"
Enter
Sleep 1500ms

Type "sekrt env pull --force"
Enter
Sleep 3s

Hide
Type "clear"
Enter
Sleep 500ms
Show

# --- scene 3: repos with no remote, and cleaning up ----------------------
Type "cd ~/code/scratch-tool"
Enter
Sleep 800ms

Type "# no origin remote here, so the vault key falls back to local/<dirname>"
Enter
Sleep 1500ms

Type "sekrt env push"
Enter
Sleep 3s

Type "sekrt env rm -f"
Enter
Sleep 3500ms
