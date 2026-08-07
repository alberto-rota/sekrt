# 🔐 tupacs

[![PyPI](https://img.shields.io/pypi/v/tupacs.svg)](https://pypi.org/project/tupacs/)
[![CI](https://github.com/alberto-rota/tupacs/actions/workflows/ci.yml/badge.svg)](https://github.com/alberto-rota/tupacs/actions/workflows/ci.yml)
[![Python](https://img.shields.io/pypi/pyversions/tupacs.svg)](https://pypi.org/project/tupacs/)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

> **TU**i **PA**ssword & **C**redential **S**torage.
> All eyez on your secrets — but only you can read them.

A fast TUI + CLI secret manager for developers and DevOps engineers.
Like [`pass`](https://www.passwordstore.org/), but with a modern
[Textual](https://textual.textualize.io/) interface, first-class **API key**,
**SSH keypair** and **`.env` file** support, and painless sync through any
private git remote (GitHub, GitLab, self-hosted — anything).

![tupacs TUI](docs/screenshot.svg)

- 🔑 **Passwords & API keys** — organised in folders, generated, copied with auto-clearing clipboard
- 📄 **`.env` files** — encrypt the `.env` of any repo into your vault, restore it in any fresh clone with one command
- 🗝️ **SSH keypairs** — import, generate (ed25519), and restore with correct permissions
- ☁️ **Git sync** — every change is a commit; `tupacs sync` pushes/pulls a private repo
- 🖥️ **TUI + CLI** — a full keyboard-driven interface *and* script-friendly commands
- 🪶 **Lightweight** — three dependencies (`textual`, `click`, `cryptography`), no daemon, no sudo, no gpg setup

## Contents

- [Install](#install)
- [Quickstart](#quickstart)
- [Syncing with a git remote](#syncing-with-a-git-remote)
- [The `.env` workflow](#the-env-workflow)
- [SSH keys](#ssh-keys)
- [The TUI](#the-tui)
- [CLI reference](#cli-reference)
- [Security model](#security-model)
- [Vault location & configuration](#vault-location--configuration)
- [Why not just `pass`?](#why-not-just-pass)
- [Development](#development)
- [Roadmap](#roadmap)

## Install

```bash
uv tool install tupacs      # recommended
# or: pipx install tupacs
# or: pip install --user tupacs
```

Requires Python 3.11+. Nothing else to set up — no daemon, no GPG keyring,
no sudo.

## Quickstart

```bash
tupacs init                             # create a vault at ~/.local/share/tupacs
tupacs add work/github -u alberto -g    # generate & store a password
tupacs get work/github -c               # copy it (clipboard clears in 45s)
tupacs                                  # open the TUI
```

That's a working local vault. `init` prompts you to choose (and confirm) a
passphrase — that passphrase *is* the vault; there's no recovery if you
lose it, so pick something you'll remember, and see the
[security model](#security-model) below before you rely on it for real.

Anything that touches a secret's contents (`get`, `show`, `edit`, `add`,
`mv`, `env`, `ssh`, …) decrypts the vault key on demand, so by default
you'll be prompted for the passphrase each time — `ls`, `find`, `rm` and
`status` don't need to decrypt anything, so they never prompt. Run
`tupacs unlock` once and the rest stop prompting for an hour (`-t MIN` to
change that), courtesy of a RAM-backed, user-private session cache — like
`gpg-agent`, without the agent. `tupacs lock` forgets it immediately.

```bash
tupacs unlock              # cache the key for 60 min
tupacs get work/github -c  # no prompt this time
tupacs lock                # forget it now
```

## Syncing with a git remote

The vault is a plain git repository. `tupacs sync` is `git pull --rebase`
then `git push` against `origin` — so you need an empty **private** repo to
point it at (GitHub, GitLab, Gitea, a bare repo over SSH — anything git can
push to).

```bash
# 1. create an empty private repo, e.g. `gh repo create secrets --private --clone=false`
tupacs remote git@github.com:you/secrets.git   # or: tupacs init --remote <url> on a fresh vault
tupacs sync                                    # first push
```

On another machine, point `$TUPACS_VAULT` at a fresh directory (or just run
`tupacs init`, then `tupacs remote <url>` — `sync` will pull the rest):

```bash
tupacs remote git@github.com:you/secrets.git
tupacs sync
```

Every `add`/`edit`/`mv`/`rm` auto-commits locally; `tupacs sync` is what
actually talks to the remote. Want every change pushed immediately instead?

```bash
tupacs autosync on
```

Remember: the remote only ever sees ciphertext and entry *names* — see
[what the remote sees](#security-model) below.

## The `.env` workflow

`.env` files never land in your project repos — so every fresh clone starts
with a scavenger hunt. tupacs ends it:

```bash
cd ~/code/my-saas       # any git repo
tupacs env push         # encrypts .env into the vault, keyed by the repo's origin URL
tupacs sync
```

Months later, on another machine:

```bash
git clone git@github.com:you/my-saas.git && cd my-saas
tupacs env pull         # .env is back, byte for byte (0600 perms)
```

It works with multiple env files per repo (`tupacs env push apps/api/.env.production`),
detects unchanged/modified files, never overwrites local edits without
`--force`, and `tupacs env ls` shows everything you've stored (repos without
a git remote fall back to a `local/<dirname>` key).

## SSH keys

```bash
tupacs ssh add laptop --key ~/.ssh/id_ed25519    # import an existing keypair
tupacs ssh add deploy --generate                 # or generate a fresh ed25519 key
tupacs ssh pub deploy                            # print the public key for GitHub
tupacs ssh restore deploy --dir ~/.ssh           # on a new machine: 0600/0644, done
```

## The TUI

`tupacs` with no arguments (or `tupacs tui`) opens the interface: a folder
tree of your vault, fuzzy filtering, a masked detail view, add/edit forms
with a built-in password generator, and one-key sync.

![tupacs TUI walkthrough](docs/tui.gif)

| Key | Action |
| --- | --- |
| `/` | filter entries |
| `c` | copy the entry's secret (auto-clears in 45s) |
| `u` | copy the entry's username |
| `r` | reveal / mask fields |
| `a` / `e` / `d` | add / edit / delete |
| `s` | sync with the git remote |
| `l` | lock the vault (prompts for the passphrase again) |
| `q` | quit |

`.env` and SSH entries show up in the tree read-only — add, restore and
inspect those from the CLI (`tupacs env`, `tupacs ssh`) instead.

## CLI reference

```text
tupacs init [--remote URL]      create a vault
tupacs add NAME [-u USER] [-g]  add password/api_key/note   (alias: insert)
tupacs get NAME [-c] [-f FIELD] print or copy a secret
tupacs show NAME [--reveal]     show all fields
tupacs ls [PREFIX]              list entries                (alias: list)
tupacs find QUERY               search names                (alias: search)
tupacs edit NAME                edit fields in $EDITOR
tupacs mv OLD NEW               rename                      (alias: rename)
tupacs rm NAME [-f]             delete                      (alias: remove)
tupacs generate [LEN] [--token] generate without storing
tupacs env push|pull|ls|show|rm .env files per repository
tupacs ssh add|restore|ls|pub   SSH keypairs
tupacs remote URL               set the sync remote
tupacs sync                     pull --rebase + push
tupacs autosync on|off          push automatically on every change
tupacs git <args...>            raw git inside the vault
tupacs unlock [-t MIN] / lock   cache / forget the vault key
tupacs passwd                   change passphrase (re-encrypts everything)
tupacs status                   vault, remote, session info
tupacs tui                      open the interactive TUI
```

Every command has `--help` (e.g. `tupacs add --help`) with the full option
list and examples.

![tupacs CLI walkthrough](docs/quickstart.gif)

## Security model

- **Encryption**: every entry is an independent file encrypted with
  **AES-256-GCM**. The key is derived from your passphrase with **scrypt**
  (N=2¹⁵, r=8, p=1, random per-vault salt).
- **Tamper binding**: an entry's logical name is the GCM associated data —
  a ciphertext moved or renamed by an attacker fails to decrypt.
- **What the remote sees**: entry *names* and folder structure (like `pass`),
  timestamps, and commit history. Entry *contents* are always ciphertext.
  Use names accordingly (`work/github`, not `password-is-hunter2`).
- **Session cache**: `tupacs unlock` stores the derived key (never the
  passphrase) in `$XDG_RUNTIME_DIR` — tmpfs on Linux: RAM-backed, user-only
  (0600), wiped on logout — with a TTL. `tupacs lock` clears it immediately.
- **Clipboard**: auto-clears after 45 s, and only if it still holds the copied
  value. Secrets are never passed through argv.
- **Files**: vault dir `0700`, entries `0600`, atomic writes, restored SSH
  keys `0600`/`0644`.
- **Threat model**: protects secrets at rest and in your git remote. It does
  **not** protect against an attacker with root/physical access to your
  unlocked machine — nothing userspace does.
- **Your passphrase is the whole game**: anyone who obtains the vault files
  (including whoever hosts your sync remote) can attempt an offline
  brute-force. scrypt makes each guess expensive, but a weak passphrase
  falls anyway — use a long one. tupacs enforces a minimum of 8 characters;
  treat that as a floor, not a target.
- **A compromised remote** cannot read entry contents or swap ciphertexts
  between names (AEAD name binding), but it *can* delete entries, serve you
  an old version of the vault (rollback), or corrupt the vault config. If
  `tupacs sync` suddenly reports missing entries or a passphrase failure,
  investigate before typing your passphrase anywhere else.

Found a vulnerability? Please report it privately via GitHub security
advisories rather than a public issue.

## Vault location & configuration

| What | Default | Override |
| --- | --- | --- |
| Vault directory | `~/.local/share/tupacs` | `$TUPACS_VAULT` |
| Passphrase (CI/scripts) | interactive prompt | `$TUPACS_PASSPHRASE` |
| Editor for `tupacs edit` | `$EDITOR` | `$VISUAL` |

The vault is a plain git repository — inspect it any time with
`tupacs git log`.

## Why not just `pass`?

`pass` is excellent, and tupacs borrows its best idea (one encrypted file
per secret, git-friendly). Differences: no GPG key management — a single
passphrase with scrypt+AES-GCM; a real TUI; structured entries (username,
URL, notes — not just a text blob); and purpose-built `.env` and SSH-key
workflows.

## Development

```bash
git clone https://github.com/alberto-rota/tupacs && cd tupacs
uv sync                 # installs everything incl. dev deps
uv run pytest           # tests
uv run ruff check .     # lint
uv run tupacs --help
```

Try changes against a throwaway vault so you never touch your real one:

```bash
export TUPACS_VAULT=/tmp/tupacs-dev TUPACS_PASSPHRASE=dev
uv run tupacs init && uv run tupacs
```

Contributions welcome — see [CONTRIBUTING.md](CONTRIBUTING.md).

The `docs/*.gif` demos are recorded with [VHS](https://github.com/charmbracelet/vhs)
from the tapes in `docs/vhs/`:

```bash
vhs docs/vhs/quickstart.tape   # -> docs/quickstart.gif
vhs docs/vhs/tui.tape          # -> docs/tui.gif (run quickstart.tape first to seed the demo vault)
```

## Roadmap

- [ ] `tupacs grep` — search inside decrypted entries
- [ ] TOTP / 2FA codes (`tupacs otp NAME`)
- [ ] Import from `pass`, Bitwarden, 1Password CSV
- [ ] Diceware passphrase generation
- [ ] Windows clipboard & session-cache support

## License

[MIT](LICENSE)
