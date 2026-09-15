# The README's opening gif: both halves of sekrt — the CLI and the TUI — in
# under 20 seconds. Everything on screen is a single continuous session.
# Regenerate from the repo root: vhs docs/vhs/hero.tape
#
# The preamble below is duplicated across tapes on purpose: VHS drops a tape's
# own `Set` lines when it uses `Source`, so a shared settings file would
# silently override the per-tape Height each tape needs.
Output docs/hero.gif

Require sekrt
Require bash
Require git

Set Shell bash
Set FontSize 18
Set Width 1200
Set Height 620          # ~26 rows: the CLI scene never scrolls, the tree never clips
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
# Faster than the other tapes: a hero gif spends its budget on what the output
# says, not on watching a command being typed.
Set TypingSpeed 25ms
Set Padding 20

# A fake $HOME pointed at the demo fixture (see setup-hero-demo.sh).
Env HOME "/tmp/sekrt-vhs-hero"
Env GIT_CONFIG_GLOBAL "/tmp/sekrt-vhs-hero/.gitconfig"

# `sekrt run` hands a quoted command to $SHELL; name it, so the recording does
# not depend on the host's.
Env SHELL "/bin/bash"

# Non-interactive passphrase, so 20 seconds go on features rather than on
# passphrase prompts. Never do this outside a throwaway demo vault.
Env SEKRT_PASSPHRASE "demo-passphrase-only"

Env GIT_PAGER "cat"
Env PAGER "cat"

Hide
Type "bash docs/vhs/setup-hero-demo.sh"
Enter
Wait+Screen@90s /demo home ready/
# Prompt in metal gray with the red accent chevron, to match the TUI.
Type `export PS1="\[\e[38;2;170;170;170m\]\w \[\e[1;38;2;255;0;0m\]❯\[\e[0m\] "`
Enter
# `;` not `&&`: clear unconditionally, so a failed unlock can't leak this
# hidden setup onto the first visible frame.
Type "cd ~/code/my-saas && sekrt unlock -t 30 >/dev/null; clear"
Enter
Sleep 1s
Show

# --- the CLI: store a secret, then hand it to a command -------------------
Type "sekrt add api/openai-api-key -t api_key -g"
Enter
Sleep 1700ms

# What a command would get, and where each variable comes from — no values.
Type "sekrt run -n 'npm start'"
Enter
Sleep 2800ms

# ...and the value really is in the child's environment, and nowhere else.
Type "sekrt run -- printenv OPENAI_API_KEY"
Enter
Sleep 1600ms

# --- the TUI: the same vault, browsable -----------------------------------
Type "sekrt"
Enter
Sleep 1600ms

Down
Sleep 350ms
Down
Sleep 350ms
Enter
Sleep 1400ms

# `r` reveals the masked fields, `c` copies the secret.
Type "r"
Sleep 1600ms
Type "c"
Sleep 1300ms

# `/` filters the tree as you type; enter hands focus back to it. `work` narrows
# to exactly two entries — anything matching the env entry's long slug would put
# folders in the way of the two Downs below — and lands the closing frame on the
# entry with the most fields.
Type "/"
Sleep 300ms
Type "work"
Sleep 1200ms
Enter
# The filtered tree keeps whatever line the cursor was on, so walk to the top
# first: from the root, two Downs are `work/github` no matter what came before.
Up 3
Sleep 250ms
Down
Sleep 250ms
Down
Sleep 250ms
Enter
# The last frame is a masked entry, which is what the TUI shows by default —
# and no `q`, so the loop restarts from the prompt rather than from the
# scrollback the TUI would uncover on its way out.
Sleep 1700ms
