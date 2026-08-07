# Regenerate: `vhs docs/vhs/quickstart.tape` (from repo root, with tupacs installed)
Output docs/quickstart.gif

Require tupacs

Set Shell bash
Set FontSize 18
Set Width 1200
Set Height 680
Set Framerate 12
Set Theme "Catppuccin Mocha"
Set TypingSpeed 45ms
Set Padding 20

Env TUPACS_VAULT "/tmp/tupacs-vhs-demo"
Env TUPACS_PASSPHRASE "demo-passphrase-only"

Hide
Type "rm -rf /tmp/tupacs-vhs-demo && clear"
Enter
Sleep 500ms
Show

Type "tupacs init"
Enter
Sleep 6s

Type "tupacs add work/github -u alberto -g"
Enter
Sleep 5s

Type "tupacs get work/github"
Enter
Sleep 4s

Type "tupacs add cloud/aws -t api_key -g"
Enter
Sleep 5s

Type "tupacs ls"
Enter
Sleep 3s

Type "tupacs show work/github"
Enter
Sleep 5s

Type "tupacs status"
Enter
Sleep 3s
