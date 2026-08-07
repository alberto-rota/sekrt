# 🔐 tupacss

> **TU**i **PA**ssword & **C**redential **S**torage, **S**ynced.
> All eyez on your secrets — but only you can read them.

A fast TUI + CLI secret manager for developers and DevOps engineers.
Like [`pass`](https://www.passwordstore.org/), but with a modern
[Textual](https://textual.textualize.io/) interface, first-class **API key**,
**SSH keypair** and **`.env` file** support, and painless sync through any
private git remote (GitHub, GitLab, self-hosted — anything).

![tupacss TUI](docs/screenshot.svg)

- 🔑 **Passwords & API keys** — organised in folders, generated, copied with auto-clearing clipboard
- 📄 **`.env` files** — encrypt the `.env` of any repo into your vault, restore it in any fresh clone with one command
- 🗝️ **SSH keypairs** — import, generate (ed25519), and restore with correct permissions
- ☁️ **Git sync** — every change is a commit; `tupacss sync` pushes/pulls a private repo
- 🖥️ **TUI + CLI** — a full keyboard-driven interface *and* script-friendly commands
- 🪶 **Lightweight** — three dependencies (`textual`, `click`, `cryptography`), no daemon, no sudo, no gpg setup

## Install

```bash
uv tool install tupacss      # recommended
# or: pipx install tupacss
# or: pip install --user tupacss
```

## Quickstart

```bash
tupacss init --remote git@github.com:you/secrets.git   # create vault + connect a PRIVATE repo
tupacss add work/github -u alberto -g                  # generate & store a password
tupacss get work/github -c                             # copy it (clipboard clears in 45s)
tupacss                                                # open the TUI
tupacss sync                                           # pull + push the encrypted vault
```

Run `tupacss unlock` once and commands stop prompting for your passphrase for
an hour (cached in a RAM-backed, user-private runtime dir — like gpg-agent,
without the agent).

## The `.env` workflow

`.env` files never land in your project repos — so every fresh clone starts
with a scavenger hunt. tupacss ends it:

```bash
cd ~/code/my-saas        # any git repo
tupacss env push         # encrypts .env into the vault, keyed by the repo's origin URL
tupacss sync
```

Months later, on another machine:

```bash
git clone git@github.com:you/my-saas.git && cd my-saas
tupacss env pull         # .env is back, byte for byte (0600 perms)
```

It works with multiple env files per repo (`tupacss env push apps/api/.env.production`),
detects unchanged/modified files, never overwrites local edits without
`--force`, and `tupacss env ls` shows everything you've stored.

## SSH keys

```bash
tupacss ssh add laptop --key ~/.ssh/id_ed25519    # import an existing keypair
tupacss ssh add deploy --generate                 # or generate a fresh ed25519 key
tupacss ssh pub deploy                            # print the public key for GitHub
tupacss ssh restore deploy --dir ~/.ssh           # on a new machine: 0600/0644, done
```

## The TUI

`tupacss` with no arguments opens the interface: a folder tree of your vault,
fuzzy filtering, masked detail view, add/edit forms with a password generator,
and one-key sync.

| Key | Action                              |
| --- | ----------------------------------- |
| `/` | filter entries                      |
| `c` | copy secret (auto-clears in 45s)    |
| `r` | reveal / mask fields                |
| `a` / `e` / `d` | add / edit / delete     |
| `s` | sync with the git remote            |
| `l` | lock the vault                      |
| `q` | quit                                |

## CLI reference

```text
tupacss init [--remote URL]      create a vault
tupacss add NAME [-u USER] [-g]  add password/api_key/note   (alias: insert)
tupacss get NAME [-c] [-f FIELD] print or copy a secret
tupacss show NAME [--reveal]     show all fields
tupacss ls [PREFIX]              list entries                (alias: list)
tupacss find QUERY               search names                (alias: search)
tupacss edit NAME                edit fields in $EDITOR
tupacss mv OLD NEW               rename                      (alias: rename)
tupacss rm NAME [-f]             delete                      (alias: remove)
tupacss generate [LEN] [--token] generate without storing
tupacss env push|pull|ls|show|rm .env files per repository
tupacss ssh add|restore|ls|pub   SSH keypairs
tupacss remote URL               set the sync remote
tupacss sync                     pull --rebase + push
tupacss autosync on|off          push automatically on every change
tupacss git <args...>            raw git inside the vault
tupacss unlock [-t MIN] / lock   cache / forget the vault key
tupacss passwd                   change passphrase (re-encrypts everything)
tupacss status                   vault, remote, session info
```

## Security model

- **Encryption**: every entry is an independent file encrypted with
  **AES-256-GCM**. The key is derived from your passphrase with **scrypt**
  (N=2¹⁵, r=8, p=1, random per-vault salt).
- **Tamper binding**: an entry's logical name is the GCM associated data —
  a ciphertext moved or renamed by an attacker fails to decrypt.
- **What the remote sees**: entry *names* and folder structure (like `pass`),
  timestamps, and commit history. Entry *contents* are always ciphertext.
  Use names accordingly (`work/github`, not `password-is-hunter2`).
- **Session cache**: `tupacss unlock` stores the derived key (never the
  passphrase) in `$XDG_RUNTIME_DIR` — tmpfs on Linux: RAM-backed, user-only
  (0600), wiped on logout — with a TTL. `tupacss lock` clears it immediately.
- **Clipboard**: auto-clears after 45 s, and only if it still holds the copied
  value. Secrets are never passed through argv.
- **Files**: vault dir `0700`, entries `0600`, atomic writes, restored SSH
  keys `0600`/`0644`.
- **Threat model**: protects secrets at rest and in your git remote. It does
  **not** protect against an attacker with root/physical access to your
  unlocked machine — nothing userspace does.

Found a vulnerability? Please report it privately via GitHub security
advisories rather than a public issue.

## Vault location & configuration

| What | Default | Override |
| --- | --- | --- |
| Vault directory | `~/.local/share/tupacss` | `$TUPACSS_VAULT` |
| Passphrase (CI/scripts) | interactive prompt | `$TUPACSS_PASSPHRASE` |
| Editor for `tupacss edit` | `$EDITOR` | `$VISUAL` |

The vault is a plain git repository — inspect it any time with
`tupacss git log`.

## Why not just `pass`?

`pass` is excellent, and tupacss borrows its best idea (one encrypted file
per secret, git-friendly). Differences: no GPG key management — a single
passphrase with scrypt+AES-GCM; a real TUI; structured entries (username,
URL, notes — not just a text blob); and purpose-built `.env` and SSH-key
workflows.

## Development

```bash
git clone https://github.com/albertorota/tupacss && cd tupacss
uv sync                 # installs everything incl. dev deps
uv run pytest           # tests
uv run ruff check .     # lint
uv run tupacss --help
```

Contributions welcome — see [CONTRIBUTING.md](CONTRIBUTING.md).

## Roadmap

- [ ] `tupacss grep` — search inside decrypted entries
- [ ] TOTP / 2FA codes (`tupacss otp NAME`)
- [ ] Import from `pass`, Bitwarden, 1Password CSV
- [ ] Diceware passphrase generation
- [ ] Windows clipboard & session-cache support

## License

[MIT](LICENSE)
