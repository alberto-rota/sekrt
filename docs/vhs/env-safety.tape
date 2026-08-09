# The guard rails: tupacs notices what actually changed, and never overwrites a
# local env file you've edited unless you ask it to.
# Regenerate from the repo root: vhs docs/vhs/env-safety.tape
#
# Preamble duplicated across the env tapes on purpose — see the note in env.tape.
Output docs/env-safety.gif

Require tupacs
Require bash
Require git

Set Shell bash
Set FontSize 18
Set Width 1200
Set Height 340          # fits this tape's longest scene (~11 lines)
Set Framerate 12
Set Theme "Catppuccin Mocha"
Set TypingSpeed 45ms
Set Padding 20

Env HOME "/tmp/tupacs-vhs-env"
Env GIT_CONFIG_GLOBAL "/tmp/tupacs-vhs-env/.gitconfig"
Env TUPACS_PASSPHRASE "demo-passphrase-only"
Env GIT_PAGER "cat"
Env PAGER "cat"

Hide
Type "bash docs/vhs/setup-env-demo.sh"
Enter
Wait+Screen@90s /demo home ready/
Type `export PS1="\[\e[38;5;147m\]\w\[\e[0m\] $ "`
Enter
Type "cd ~/code/my-saas && tupacs unlock -t 30 >/dev/null && clear"
Enter
Sleep 1s
Show

# --- scene 1: push is idempotent, and reports what changed ----------------
Type "tupacs env push"
Enter
Sleep 2500ms

Type "# push again — nothing changed, so nothing is rewritten"
Enter
Sleep 1500ms

Type "tupacs env push"
Enter
Sleep 2500ms

Type "echo 'FEATURE_FLAGS=new-billing' >> .env"
Enter
Sleep 1200ms

Type "tupacs env push"
Enter
Sleep 3s

Hide
Type "clear"
Enter
Sleep 500ms
Show

# --- scene 2: pull refuses to clobber local edits -------------------------
Type "cd ~/clones/my-saas && tupacs env pull"
Enter
Sleep 2500ms

Type "# now edit the restored file locally, the way you would mid-debugging"
Enter
Sleep 1500ms

Type "echo 'LOG_LEVEL=trace' >> .env"
Enter
Sleep 1200ms

Type "tupacs env pull"
Enter
Sleep 3500ms

Type "# your edit survived. overwrite it only when you say so:"
Enter
Sleep 1500ms

Type "tupacs env pull --force"
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

Type "tupacs env push"
Enter
Sleep 3s

Type "tupacs env rm -f"
Enter
Sleep 3500ms
