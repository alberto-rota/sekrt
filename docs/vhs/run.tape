# `sekrt run`: a command gets the secrets, the shell around it never does.
# Regenerate from the repo root: vhs docs/vhs/run.tape
#
# The preamble below is duplicated across tapes on purpose: VHS drops a tape's
# own `Set` lines when it uses `Source`, so a shared settings file would
# silently override the per-tape Height each tape needs.
Output docs/run.gif

Require sekrt
Require bash
Require git

Set Shell bash
Set FontSize 18
Set Width 1200
Set Height 560          # fits this tape's longest scene (~23 lines)
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

# A fake $HOME pointed at the demo fixture (see setup-run-demo.sh).
Env HOME "/tmp/sekrt-vhs-run"
Env GIT_CONFIG_GLOBAL "/tmp/sekrt-vhs-run/.gitconfig"

# `sekrt shell` opens $SHELL; name it, so the recording does not depend on the host.
Env SHELL "/bin/bash"

# Non-interactive passphrase, so the demo stays about `run` rather than about
# passphrase prompts. Never do this outside a throwaway demo vault.
Env SEKRT_PASSPHRASE "demo-passphrase-only"

Env GIT_PAGER "cat"
Env PAGER "cat"

Hide
Type "bash docs/vhs/setup-run-demo.sh"
Enter
Wait+Screen@90s /demo home ready/
# Prompt in metal gray with the red accent chevron, to match the TUI.
Type `export PS1="\[\e[38;2;170;170;170m\]\w \[\e[1;38;2;255;0;0m\]❯\[\e[0m\] "`
Enter
Type "cd ~/code/my-saas && clear"
Enter
Sleep 1s
Show

# What a command would get, without running it: names and sources, no values.
Type "sekrt run -n 'npm start'"
Enter
Sleep 5s

# The value really is in the child's environment.
Type "sekrt run -- printenv UV_PUBLISH_TOKEN"
Enter
Sleep 4s

# Single quotes: the shell sekrt starts is what expands the reference.
Type `sekrt run 'echo publishing with $UV_PUBLISH_TOKEN'`
Enter
Sleep 4s

# ...and none of it was ever here.
Type "printenv UV_PUBLISH_TOKEN"
Enter
Sleep 3s

# A whole session instead of one command: the prompt says so, and `exit` ends it.
Type "sekrt shell"
Enter
Sleep 3s
Type "echo $UV_PUBLISH_TOKEN"
Enter
Sleep 3s
Type "exit"
Enter
Sleep 4s
