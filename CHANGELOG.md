# Changelog

All notable changes to this project are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/) and the
project adheres to [Semantic Versioning](https://semver.org/).

## [Unreleased]

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
