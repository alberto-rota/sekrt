# CLI quickstart: store a key, push a .env, hand both to a command. About 20
# seconds, and no TUI. Regenerate from the repo root:
# vhs docs/vhs/quickstart.tape
#
# The preamble below is duplicated across tapes on purpose: VHS drops a tape's
# own `Set` lines when it uses `Source`, so a shared settings file would
# silently override the per-tape Height each tape needs.
Output docs/quickstart.gif

Require sekrt
Require bash
Require git

Set Shell bash
Set FontSize 18
Set Width 1200
Set Height 520
# No `Set Framerate`: VHS writes gifs at 25fps whatever the capture rate, so
# anything below that only duplicates frames and makes the typing look choppy.
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
# A 20 second gif spends its budget on what the output says.
Set TypingSpeed 25ms
Set Padding 20

# Fake $HOME for the prompt and the demo repo. The vault stays on the path
# tui.tape records against (see setup-quickstart-demo.sh).
Env HOME "/tmp/sekrt-vhs-quickstart"
Env GIT_CONFIG_GLOBAL "/tmp/sekrt-vhs-quickstart/.gitconfig"
Env SEKRT_VAULT "/tmp/sekrt-vhs-demo"
Env SEKRT_PASSPHRASE "demo-passphrase-only"
Env SHELL "/bin/bash"
Env BASH_SILENCE_DEPRECATION_WARNING "1"
Env GIT_PAGER "cat"
Env PAGER "cat"

Hide
Type "bash docs/vhs/setup-quickstart-demo.sh"
Enter
Wait+Screen@90s /demo home ready/
Type `export PS1="\[\e[38;2;170;170;170m\]\w \[\e[1;38;2;255;0;0m\]❯\[\e[0m\] "`
Enter
# The recording shell inherits the host env. `NO_COLOR` (even empty) strips
# the green check marks; a config override would change the generated length
# and the clipboard line. `;` not `&&` on clear.
Type "unset NO_COLOR SEKRT_CONFIG TUPACS_CONFIG XDG_CONFIG_HOME; cd ~/code/my-saas; clear"
Enter
Sleep 1s
Show

# A generated API key, printed once. `-s` is how it lands on screen; the
# secret is never an argument.
Type "sekrt add api/openai-api-key -t api_key -g -s"
Enter
Sleep 2s

Type "sekrt ls"
Enter
Sleep 1.6s

# The repo's .env, encrypted into the same vault.
Type "sekrt env push"
Enter
Sleep 2.2s

# Names and where they come from — the values stay out of this one.
Type "sekrt run -n 'npm start'"
Enter
Sleep 4s

# A whole session, tagged so it never looks like the shell around it.
# The key just stored, and the variable from the .env, both in this prompt only.
Type "sekrt shell"
Enter
Sleep 1.4s
Type "echo $OPENAI_API_KEY"
Enter
Sleep 1.5s
Type "echo $DATABASE_URL"
Enter
Sleep 1.5s
Type "exit"
Enter
Sleep 1.6s
