# Regenerate: run quickstart.tape first (populates the demo vault), then
# `vhs docs/vhs/tui.tape` (from repo root, with tupacs installed)
Output docs/tui.gif

Require tupacs

Set Shell bash
Set FontSize 18
Set Width 1200
Set Height 720
Set Framerate 12
Set Theme "Catppuccin Mocha"
Set Padding 20

Env TUPACS_VAULT "/tmp/tupacs-vhs-demo"
Env TUPACS_PASSPHRASE "demo-passphrase-only"

Hide
Type "tupacs unlock -t 5 && clear"
Enter
Sleep 4s
Show

Type "tupacs"
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
