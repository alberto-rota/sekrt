# Changelog

All notable changes to this project are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/) and the
project adheres to [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added
- `sekrt run` and `sekrt shell`: hand a command your secrets in its environment
  only, for exactly as long as it runs. `sekrt run 'npm start'` exposes every
  password and API key in the vault, each under the variable its name reads as
  (`api/my-token` becomes `$MY_TOKEN`), plus whatever this repository stored with
  `sekrt env push` — which wins where the names collide. Notes, SSH keys and
  stored files are left out (prose, a key file and a blob of bytes are not what a
  variable carries), as is a variable two entries both answer to, which is
  reported instead of guessed at. `-e MY_TOKEN` *narrows* the exposure to that
  one, `-e MY_TOKEN=work/api-token` names the entry outright, and
  `--no-env-files` drops the repository's own — together, a command that gets one
  secret and nothing else.
  A command quoted into one argument —
  `sekrt run 'service log --token="$MY_TOKEN"'` — goes to `$SHELL`, which is what
  expands the reference; several arguments (`sekrt run -- npm start`) are run
  directly, with no shell in the way. sekrt tells the two apart from what you
  typed, so nothing has to be flagged as one or the other. It never substitutes a
  secret into a command line, since `argv` is world-readable in `ps`, and it says
  so when a quoted reference reaches the direct form as text, or when a command
  arrives with the hole an expanded-away reference leaves behind (a leftover
  `--token=`, a trailing space, an empty argument) — signatures of a reference
  eaten by the shell that typed it, before sekrt existed.
  `sekrt shell` opens a subshell holding those variables, where `exit` revokes
  them. It asks you to be specific where `run` does not: a subshell lasts as long
  as you leave it open and hands what it holds to everything started from it, so
  `-e` names what goes in, no flags at all means this repository's stored `.env`
  files and nothing more, and the whole vault takes `--all`, which lists what
  that covers and waits for a `y` (`--yes` answers in advance; with no terminal
  to ask on it refuses rather than assuming). With nothing named and nothing
  stored, nothing is decrypted and no shell opens.
  A `sekrt shell` tags its prompt `(sekrt)` so a shell holding secrets never
  looks like an ordinary one — through the shell's own startup files (a generated rc for
  bash, `ZDOTDIR` for zsh, `--init-command` for fish), which sources your real
  config first and hooks the prompt after it, so a theme that rebuilds the prompt
  every line keeps the tag, and aliases, functions and history are untouched.
  Any other shell opens untagged, with `$SEKRT_EXPOSED` there to build an
  indicator from. The tag is plain ASCII on purpose: an emoji in a prompt is two
  display cells the shell counts as one character, which misplaces the cursor on
  a long edited line. Nothing is written to disk or left in the calling shell, and
  `$SEKRT_PASSPHRASE` is stripped from the child, so a wrapped command cannot
  decrypt anything it was not handed. `--dry-run` lists the variables and where
  each comes from without printing a value — worth a look, since the default
  exposure is broad; `--repo` borrows another repo's stored files;
  `$SEKRT_EXPOSED` carries the names for a shell prompt to show. Aliases:
  `sekrt exec`, `sekrt sh`.
- Inline forms for the two commands with the most flags. `sekrt add` and
  `sekrt ssh add` without a NAME (or with `-i`, which starts from what you
  already typed) open a few lines of form under the prompt instead: labelled
  fields, `tab`/`↑↓` between them, `←`/`→` on the rows that are a choice
  (password / api key / note, generate / import), `ctrl+g` to fill in a
  generated secret, `enter` to save, `esc` to leave. Like the picker they draw
  on stderr and claim only the lines they need, and where there is no terminal
  both commands still insist on their arguments.
- Customizable colors. `sekrt config` opens a small inline panel: a row of
  ready-made palettes — `metal`, `teal`, `amber`, `indigo`, `magenta`, `mono`,
  `matrix`, `ice`, `violet`, `rose`, `sepia`, one per hue — that `←`/`→` walks
  and applies as you land on each one, and three fields (`primary`,
  `secondary`, `accent`) underneath for naming a color yourself.
  Everything — swatches, preview, the panel's own chrome — repaints live;
  `enter` saves, `esc` leaves it as it was, `ctrl+r` restores the stock
  metal-and-red. The preset row deselects itself once a hand-typed color takes
  the palette off all eleven, and re-selects when one is typed back onto. The
  same editor is bound to `t` in the TUI, where the interface behind it recolors
  live and `esc` puts the old palette back. Non-interactively:
  `sekrt config --preset teal`, `--accent '#00d7af'` (they compose), `--show`,
  `--reset` (aliases: `sekrt colors`, `sekrt theme`). Values can be hex
  (`#00d7af`, `0d7`) or CSS names (`cyan`); the dark background stays fixed,
  since it is what keeps an arbitrary accent readable. The palette is stored in
  `~/.config/sekrt/config.json` (`$SEKRT_CONFIG` overrides) rather than in the
  vault, so recoloring is not a commit and each machine can differ. A config
  file that has been hand-edited into nonsense costs the colors it broke and
  nothing else.
- An inline picker for entry names: `get`, `show`, `edit` and `rm` accept a
  partial NAME (or none at all) and open a few lines of fuzzy-filtered list
  under the shell prompt instead of failing. The passphrase is asked for
  before the list appears, and the picker draws on stderr, so
  `sekrt get | pbcopy` still pipes the secret and nothing else; without a
  terminal (pipes, cron, CI) the commands still require an exact NAME.
- `sekrt show --reveal` offers `press c to copy` at a terminal: `c` puts the
  entry's main secret on the clipboard (cleared after 45s), any other key —
  or 20 seconds of silence — dismisses it. The prompt is stderr-only and
  erases itself, and there is no prompt where there is no terminal.

### Changed
- The unlock prompt is `🔐 passphrase ❯` in your own colors (`sekrt config`)
  rather than a bare `Passphrase:`, with the failed attempts counted down
  (`✗ wrong passphrase — 2 tries left`). It names the vault when `$SEKRT_VAULT`
  points at one (`🔐 passphrase sekrt-dev ❯`), so a scratch vault is not mistaken
  for the real one, and stays unstyled where there is no terminal to show it.
- `sekrt show --reveal` lays a revealed secret out to be copied: secrets come
  last, after the metadata, each alone on an unindented line of its own. A
  double- or triple-click now selects the value and nothing else, and a
  revealed SSH key is pasteable instead of indented four spaces.

## [0.2.0] - unreleased

### Added
- `sekrt file add|get|ls`: encrypt and restore whole files of any kind
  (binary-safe, base64-encoded at rest) — recovery-code lists, keystores,
  PDFs, anything that isn't a `.env` or an SSH key.

### Changed
- `sekrt edit` on a note now opens its text raw in `$EDITOR` (no JSON
  escaping), so multiline notes are as easy to edit as they already were
  to create.

### Changed — the project is now called `sekrt` (was `tupacs`)

Everything user-facing follows the name: the `sekrt` command, the `sekrt`
import package, `SEKRT_*` environment variables, the default vault at
`~/.local/share/sekrt`, its `.sekrt.json` config, and `.skr` entry files.

**Migrating a 0.1.0 vault.** Environment variables and entry files are handled
for you — `TUPACS_VAULT`/`TUPACS_PASSPHRASE` still work as fallbacks, and `.tup`
entries written by 0.1.0 are read (and updated) in place. The vault *directory*
is deliberately left alone, because silently reading a differently-named
directory would hide where your secrets live. Move it once:

```bash
mv ~/.local/share/tupacs ~/.local/share/sekrt
mv ~/.local/share/sekrt/.tupacs.json ~/.local/share/sekrt/.sekrt.json
sekrt git commit -am "rename vault config"   # the vault is a git repo
```

Running any command before you do prints these instructions. To finish the job,
rename your `TUPACS_*` variables and re-point the git remote if you renamed the
GitHub repository too.

### Documentation
- `docs/env.md`: a full guide to the `.env` workflow — how repos are identified
  from their `origin` URL, monorepos with several env files, the push/pull
  overwrite rules, `--repo` for forks and renames, what the sync remote can see,
  and troubleshooting.
- Three new VHS demos of that workflow (`docs/env*.gif`), recorded from
  self-contained tapes in `docs/vhs/` against a throwaway fixture built by
  `docs/vhs/setup-env-demo.sh`.

## [0.1.0] - 2026-08-07

Initial release.

### Added
- Encrypted vault: one AES-256-GCM file per entry, scrypt key derivation,
  entry name bound as GCM associated data.
- CLI: `init`, `add`, `get`, `show`, `ls`, `find`, `edit`, `mv`, `rm`,
  `generate`, `passwd`, `status` (+ `pass`-style aliases like `insert`).
- Textual TUI: tree browser, filtering, masked detail view, add/edit/delete,
  password generator, clipboard copy, sync, lock.
- Git sync: auto-commit on every change, `remote`, `sync`, `autosync`,
  raw `git` passthrough.
- `.env` workflows: `env push/pull/ls/show/rm`, keyed by the repo's origin URL.
- SSH keys: `ssh add` (import or generate ed25519), `restore` with 0600/0644
  permissions, `ls`, `pub`.
- Session cache: `unlock`/`lock` with a TTL in a RAM-backed runtime dir.
- Clipboard auto-clear after 45 s (wl-copy / xclip / xsel / pbcopy).
