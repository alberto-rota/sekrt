# 🔐 sekrt

[![PyPI](https://img.shields.io/pypi/v/sekrt.svg)](https://pypi.org/project/sekrt/)
[![CI](https://github.com/alberto-rota/sekrt/actions/workflows/ci.yml/badge.svg)](https://github.com/alberto-rota/sekrt/actions/workflows/ci.yml)
[![Python](https://img.shields.io/pypi/pyversions/sekrt.svg)](https://pypi.org/project/sekrt/)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

> **sekrt** — *secret*, with the vowels taken out.
> Everything else is AES-256, and only you can read it.

A fast TUI + CLI secret manager for developers and DevOps engineers.
Like [`pass`](https://www.passwordstore.org/), but with a modern
[Textual](https://textual.textualize.io/) interface, first-class **API key**,
**SSH keypair** and **`.env` file** support, and painless sync through any
private git remote (GitHub, GitLab, self-hosted — anything).

![sekrt TUI](docs/screenshot.svg)

- 🔑 **Passwords & API keys** — organised in folders, generated, copied with auto-clearing clipboard
- 📄 **`.env` files** — encrypt the `.env` of any repo into your vault, restore it in any fresh clone with one command
- 🗝️ **SSH keypairs** — import, generate (ed25519), and restore with correct permissions
- ☁️ **Git sync** — every change is a commit; `sekrt sync` pushes/pulls a private repo
- 🖥️ **TUI + CLI** — a full keyboard-driven interface *and* script-friendly commands
- 🪶 **Lightweight** — three dependencies (`textual`, `click`, `cryptography`), no daemon, no sudo, no gpg setup

## Contents

- [Install](#install)
- [Quickstart](#quickstart)
- [Syncing with a git remote](#syncing-with-a-git-remote)
- [The `.env` workflow](#the-env-workflow)
- [SSH keys](#ssh-keys)
- [Whole files](#whole-files)
- [The TUI](#the-tui)
- [CLI reference](#cli-reference)
- [Security model](#security-model)
- [Vault location & configuration](#vault-location--configuration)
- [Why not just `pass`?](#why-not-just-pass)
- [Development](#development)
- [Roadmap](#roadmap)

## Install

```bash
uv tool install sekrt      # recommended
# or: pipx install sekrt
# or: pip install --user sekrt
```

Requires Python 3.11+. Nothing else to set up — no daemon, no GPG keyring,
no sudo.

## Quickstart

```bash
sekrt init                             # create a vault at ~/.local/share/sekrt
sekrt add work/github -u alberto -g    # generate & store a password
sekrt get work/github -c               # copy it (clipboard clears in 45s)
sekrt                                  # open the TUI
```

On a second machine, `init` asks whether you already have a vault in a git repo
and clones it for you if so — or skip the question with `sekrt clone <url>`.

That's a working local vault. `init` prompts you to choose (and confirm) a
passphrase — that passphrase *is* the vault; there's no recovery if you
lose it, so pick something you'll remember, and see the
[security model](#security-model) below before you rely on it for real.

Anything that touches a secret's contents (`get`, `show`, `edit`, `add`,
`mv`, `env`, `ssh`, …) decrypts the vault key on demand, so by default
you'll be prompted for the passphrase each time — `ls`, `find`, `rm` and
`status` don't need to decrypt anything, so they never prompt. Run
`sekrt unlock` once and the rest stop prompting for an hour (`-t MIN` to
change that), courtesy of a RAM-backed, user-private session cache — like
`gpg-agent`, without the agent. `sekrt lock` forgets it immediately.

```bash
sekrt unlock              # cache the key for 60 min
sekrt get work/github -c  # no prompt this time
sekrt lock                # forget it now
```

## Syncing with a git remote

The vault is a plain git repository. `sekrt sync` is `git pull --rebase`
then `git push` against `origin` — so you need an empty **private** repo to
point it at (GitHub, GitLab, Gitea, a bare repo over SSH — anything git can
push to).

```bash
# 1. create an empty private repo, e.g. `gh repo create secrets --private --clone=false`
sekrt remote git@github.com:you/secrets.git   # or: sekrt init --remote <url> on a fresh vault
sekrt sync                                    # first push
```

On every **other** machine, `sekrt init` asks the one question that matters and
does the right thing with the answer:

```console
$ sekrt init
Do you already have a sekrt vault pushed to a git repo? [y/N]: y
Vault repo URL: git@github.com:you/secrets.git
✔ vault cloned to ~/.local/share/sekrt
  3 entries available
  unlock with the passphrase that created this vault: `sekrt unlock`
```

`sekrt clone <url>` does the same thing in one shot if you'd rather not be asked.

> [!IMPORTANT]
> A second machine must *clone* the vault, not create one. `init` generates a
> new encryption salt and a new git root, so two independently-created vaults
> share no history and cannot decrypt each other's entries. Cloning reuses the
> existing salt, which is why your original passphrase keeps working. You don't
> have to remember this: the prompt above steers you, `init --remote <url>` and
> `remote <url>` refuse when the remote already holds a vault, and `sync`
> refuses the impossible merge instead of corrupting anything.

Every `add`/`edit`/`mv`/`rm` auto-commits locally; `sekrt sync` is what
actually talks to the remote. Want every change pushed immediately instead?

```bash
sekrt autosync on
```

Remember: the remote only ever sees ciphertext and entry *names* — see
[what the remote sees](#security-model) below.

## The `.env` workflow

`.env` files never land in your project repos — so every fresh clone starts
with a scavenger hunt. sekrt ends it:

```bash
cd ~/code/my-saas       # any git repo
sekrt env push         # encrypts .env into the vault, keyed by the repo's origin URL
sekrt sync
```

Months later, on another machine:

```bash
git clone git@github.com:you/my-saas.git && cd my-saas
sekrt env pull         # .env is back, byte for byte (0600 perms)
```

![The .env round trip](docs/env.gif)

The key is the repo's `origin` URL, not the path on disk — so a clone anywhere
finds its own file, and HTTPS vs SSH remotes resolve to the same key. It
handles several env files per repo (`sekrt env push .env apps/*/.env.*`),
reports what actually changed rather than rewriting blindly, and never
overwrites a local file you've edited without `--force`.

**📄 [Full guide: the `.env` workflow](docs/env.md)** — how repos are
identified, monorepos with one env file per service, the overwrite rules, using
`--repo` for forks and renames, what the remote can see, and troubleshooting.

## SSH keys

```bash
sekrt ssh add laptop --key ~/.ssh/id_ed25519    # import an existing keypair
sekrt ssh add deploy --generate                 # or generate a fresh ed25519 key
sekrt ssh pub deploy                            # print the public key for GitHub
sekrt ssh restore deploy --dir ~/.ssh           # on a new machine: 0600/0644, done
```

## Whole files

For anything bigger than a note — a list of MFA recovery codes, a keystore,
a PDF — `sekrt file` encrypts the file itself, byte-for-byte, no `$EDITOR`
round-trip:

```bash
sekrt file add mfa/github-recovery ~/Downloads/recovery-codes.txt
sekrt file get mfa/github-recovery                    # restores original filename, cwd
sekrt file get mfa/github-recovery -o ./codes.txt      # or pick the destination
sekrt file ls
```

Binary-safe (content is base64-encoded at rest), and `sekrt show` only
prints its size — use `file get` to get the bytes back out.

## The TUI

`sekrt` with no arguments (or `sekrt tui`) opens the interface: a folder
tree of your vault, fuzzy filtering, a masked detail view, add/edit forms
with a built-in password generator, and one-key sync.

![sekrt TUI walkthrough](docs/tui.gif)

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

`.env`, SSH and file entries show up in the tree read-only — add, restore
and inspect those from the CLI (`sekrt env`, `sekrt ssh`, `sekrt file`)
instead.

## CLI reference

```text
sekrt init [--remote URL]      create a vault, or clone one if you have it already
sekrt clone URL                set up from an existing vault repo, no questions asked
sekrt add NAME [-u USER] [-g]  add password/api_key/note   (alias: insert)
sekrt get NAME [-c] [-f FIELD] print or copy a secret
sekrt show NAME [--reveal]     show all fields
sekrt ls [PREFIX]              list entries                (alias: list)
sekrt find QUERY               search names                (alias: search)
sekrt edit NAME                edit fields in $EDITOR (notes: raw multiline text)
sekrt mv OLD NEW               rename                      (alias: rename)
sekrt rm NAME [-f]             delete                      (alias: remove)
sekrt generate [LEN] [--token] generate without storing
sekrt env push|pull|ls|show|rm .env files per repository    (guide: docs/env.md)
sekrt ssh add|restore|ls|pub   SSH keypairs
sekrt file add|get|ls          whole files, binary-safe
sekrt remote URL               set the sync remote
sekrt sync                     pull --rebase + push
sekrt autosync on|off          push automatically on every change
sekrt git <args...>            raw git inside the vault
sekrt unlock [-t MIN] / lock   cache / forget the vault key
sekrt passwd                   change passphrase (re-encrypts everything)
sekrt status                   vault, remote, session info
sekrt tui                      open the interactive TUI
```

Every command has `--help` (e.g. `sekrt add --help`) with the full option
list and examples.

![sekrt CLI walkthrough](docs/quickstart.gif)

## Security model

- **Encryption**: every entry is an independent file encrypted with
  **AES-256-GCM**. The key is derived from your passphrase with **scrypt**
  (N=2¹⁵, r=8, p=1, random per-vault salt).
- **Tamper binding**: an entry's logical name is the GCM associated data —
  a ciphertext moved or renamed by an attacker fails to decrypt.
- **What the remote sees**: entry *names* and folder structure (like `pass`),
  timestamps, and commit history. Entry *contents* are always ciphertext.
  Use names accordingly (`work/github`, not `password-is-hunter2`).
- **Session cache**: `sekrt unlock` stores the derived key (never the
  passphrase) in `$XDG_RUNTIME_DIR` — tmpfs on Linux: RAM-backed, user-only
  (0600), wiped on logout — with a TTL. `sekrt lock` clears it immediately.
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
  falls anyway — use a long one. sekrt enforces a minimum of 8 characters;
  treat that as a floor, not a target.
- **A compromised remote** cannot read entry contents or swap ciphertexts
  between names (AEAD name binding), but it *can* delete entries, serve you
  an old version of the vault (rollback), or corrupt the vault config. If
  `sekrt sync` suddenly reports missing entries or a passphrase failure,
  investigate before typing your passphrase anywhere else.

Found a vulnerability? Please report it privately via GitHub security
advisories rather than a public issue.

## Vault location & configuration

| What | Default | Override |
| --- | --- | --- |
| Vault directory | `~/.local/share/sekrt` | `$SEKRT_VAULT` |
| Passphrase (CI/scripts) | interactive prompt | `$SEKRT_PASSPHRASE` |
| Editor for `sekrt edit` | `$EDITOR` | `$VISUAL` |

The vault is a plain git repository — inspect it any time with
`sekrt git log`.

> **Upgrading from `tupacs`?** This project was published under that name
> through 0.1.0. The `TUPACS_*` variables above still work as fallbacks, and
> vaults written by 0.1.0 (`.tup` entry files) are read as-is. Only the vault
> directory needs a hand — see [the migration note](CHANGELOG.md#020).

## Why not just `pass`?

`pass` is excellent, and sekrt borrows its best idea (one encrypted file
per secret, git-friendly). Differences: no GPG key management — a single
passphrase with scrypt+AES-GCM; a real TUI; structured entries (username,
URL, notes — not just a text blob); and purpose-built `.env` and SSH-key
workflows.

## Development

```bash
git clone https://github.com/alberto-rota/sekrt && cd sekrt
uv sync                 # installs everything incl. dev deps
uv run pytest           # tests
uv run ruff check .     # lint
uv run sekrt --help
```

Try changes against a throwaway vault so you never touch your real one:

```bash
export SEKRT_VAULT=/tmp/sekrt-dev SEKRT_PASSPHRASE=dev
uv run sekrt init && uv run sekrt
```

Contributions welcome — see [CONTRIBUTING.md](CONTRIBUTING.md).

The `docs/*.gif` demos are recorded with [VHS](https://github.com/charmbracelet/vhs)
from the tapes in `docs/vhs/`. Run them from the repo root with `sekrt` on
`$PATH` (`brew install vhs`, then `uv tool install --editable .`):

```bash
vhs docs/vhs/quickstart.tape   # -> docs/quickstart.gif
vhs docs/vhs/tui.tape          # -> docs/tui.gif (run quickstart.tape first to seed the demo vault)
vhs docs/vhs/env.tape          # -> docs/env.gif
vhs docs/vhs/env-multi.tape    # -> docs/env-multi.gif
vhs docs/vhs/env-safety.tape   # -> docs/env-safety.gif
```

The three `env` tapes are self-contained: each one rebuilds its fixture — real
git repos with remotes, a fresh clone, and a scratch vault under
`/tmp/sekrt-vhs-env` — by running `docs/vhs/setup-env-demo.sh`, and points
`$HOME` at it, so your real vault and `~/.gitconfig` are never touched.

`docs/screenshot.svg` (the image at the top of this file) is a Textual export
rather than a recording, so it has its own generator:

```bash
uv run python docs/vhs/make-screenshot.py   # -> docs/screenshot.svg
```

## Roadmap

- [ ] `sekrt grep` — search inside decrypted entries
- [ ] TOTP / 2FA codes (`sekrt otp NAME`)
- [ ] Import from `pass`, Bitwarden, 1Password CSV
- [ ] Diceware passphrase generation
- [ ] Windows clipboard & session-cache support

## License

[MIT](LICENSE)
