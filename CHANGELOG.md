# Changelog

All notable changes to this project are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/) and the
project adheres to [Semantic Versioning](https://semver.org/).

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
