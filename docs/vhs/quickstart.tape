# Regenerate: `vhs docs/vhs/quickstart.tape` (from repo root, with sekrt installed)
Output docs/quickstart.gif

Require sekrt

Set Shell bash
Set FontSize 18
Set Width 1200
Set Height 680
Set Framerate 12
Set Theme "Catppuccin Mocha"
Set TypingSpeed 45ms
Set Padding 20

Env SEKRT_VAULT "/tmp/sekrt-vhs-demo"
Env SEKRT_PASSPHRASE "demo-passphrase-only"

Hide
Type "rm -rf /tmp/sekrt-vhs-demo && clear"
Enter
Sleep 500ms
Show

Type "sekrt init"
Enter
Sleep 6s

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
