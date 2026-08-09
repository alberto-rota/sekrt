# The `.env` workflow

`.env` files are the one thing every project needs and no project commits.
They end up pasted into Slack, stashed in a note, or lost — and every fresh
clone starts with a scavenger hunt for the values that make the app boot.

tupacs stores them the way it stores any other secret: one AES-256-GCM
encrypted entry per file, keyed by the repository the file belongs to, so
`tupacs env pull` in a fresh clone puts it back byte for byte.

- [The round trip](#the-round-trip)
- [How repositories are identified](#how-repositories-are-identified)
- [More than one env file per repo](#more-than-one-env-file-per-repo)
- [What it will and won't overwrite](#what-it-will-and-wont-overwrite)
- [Reading, listing and removing](#reading-listing-and-removing)
- [Moving env files between machines](#moving-env-files-between-machines)
- [Command reference](#command-reference)
- [What the remote can see](#what-the-remote-can-see)
- [Troubleshooting](#troubleshooting)

## The round trip

Two commands, and the second one runs months later on a different machine:

```bash
cd ~/code/my-saas
tupacs env push          # encrypt .env into the vault, keyed by this repo
```

```bash
git clone git@github.com:you/my-saas.git && cd my-saas
tupacs env pull          # .env is back, 0600, byte for byte
```

![The .env round trip](env.gif)

Note the restored file's permissions: `env pull` writes atomically and the file
is `0600` from creation, so a restored `.env` is never briefly world-readable.

## How repositories are identified

`env push` doesn't care where on disk you are — it identifies the *repository*
from its `origin` remote and stores the file under
`env/<slug>/<path-relative-to-repo-root>`. That's why a clone at a completely
different path still finds its own file.

The remote URL is reduced to a host-and-path slug, so the URL *form* doesn't
matter. All of these are the same repository:

| `origin` URL | key |
| --- | --- |
| `git@github.com:you/proj.git` | `github.com/you/proj` |
| `https://github.com/you/proj.git` | `github.com/you/proj` |
| `https://github.com/you/proj` | `github.com/you/proj` |
| `https://user:token@github.com/you/proj.git` | `github.com/you/proj` |
| `ssh://git@gitlab.com/team/sub/proj.git` | `gitlab.com/team/sub/proj` |

So cloning over HTTPS on one machine and SSH on another works fine, and
credentials embedded in a remote URL are stripped rather than stored.

A repo with **no `origin` remote** falls back to `local/<directory-name>`.
That's a per-machine key by nature: two unrelated `~/code/scratch` directories
on two machines would collide, and the same directory renamed becomes a
different key. For anything you intend to move between machines, give the repo
a remote first.

> **Caveat:** in scp-style URLs with an explicit port
> (`git@gitea.example.org:2222/me/proj.git`), the port becomes part of the key
> (`gitea.example.org/2222/me/proj`). Keep the remote URL form consistent
> across machines, or pass `--repo` to pull the key you actually stored.

## More than one env file per repo

`push` takes any number of paths, and a path can point anywhere inside the
repo — the position relative to the repo root is part of the key, so a monorepo
with one env file per service round-trips as a set.

```bash
tupacs env push .env apps/*/.env.* infra/.env.staging
```

![Several env files in one repo](env-multi.gif)

Each file is a separate encrypted entry, and each push is a commit in the
vault's git history — `tupacs sync` is what sends them to your remote.

A bare `tupacs env pull` restores **every** file stored for the current repo,
so on a fresh clone of the monorepo above, one command repopulates all four.

## What it will and won't overwrite

Both directions compare content first and tell you what actually happened, so
running either twice is safe and quiet.

`tupacs env push`:

| | meaning |
| --- | --- |
| `+ … (added)` | first time this file was stored |
| `~ … (updated)` | the file changed; the vault entry was rewritten |
| `= … (unchanged)` | identical to what's stored — nothing written, no commit |

`tupacs env pull`:

| | meaning |
| --- | --- |
| `✔ … restored` | written to disk (`0600`) |
| `= … unchanged` | the local file already matches |
| `! … skipped` | **a local file exists and differs — left alone** |

![Change detection and the no-clobber guard](env-safety.gif)

That last one is the important one: `pull` never silently overwrites local
edits. Pass `--force` when you genuinely want the stored version to win:

```bash
tupacs env pull --force
```

There's no reverse guard on `push` — it treats your working copy as the truth
and overwrites the stored entry. The old content stays in the vault's git
history, so `tupacs git log -p` can recover it.

## Reading, listing and removing

```bash
tupacs env ls                              # every stored env file; '*' marks this repo's
tupacs env show                            # print this repo's stored .env
tupacs env show apps/api/.env.production   # or a specific one
tupacs env rm                              # forget this repo's stored .env (asks first)
tupacs env rm apps/api/.env.production -f  # a specific one, no prompt
```

`env show` prints the stored content without touching your working tree —
useful for checking what's in the vault before pulling over a file you've
edited.

Env entries are ordinary vault entries, so the generic commands see them too.
`tupacs show` masks the content by default and gives you a fingerprint instead,
which is the quickest way to compare two machines without printing secrets:

```console
$ tupacs show env/github.com/you/my-saas/.env
env/github.com/you/my-saas/.env
  type: env
  content: (5 lines — use --reveal)
  slug: github.com/you/my-saas
  relpath: .env
  sha256: ff2bad2c61f38e32
```

They also appear in the TUI's tree, read-only — add, restore and inspect them
from the CLI.

## Moving env files between machines

The vault is a git repository; `env push` only writes locally. Syncing is the
same as for any other entry:

```bash
tupacs env push
tupacs sync              # or: tupacs autosync on, once
```

To pull a *different* repo's env files into the directory you're standing in —
handy for a fork, a rename, or a worktree whose remote differs — name the key:

```bash
tupacs env pull --repo github.com/you/my-saas
```

The stored relative paths are written under the **current** repo's root, so
this is also how you'd migrate a project's env files to a renamed repo: pull
with `--repo <old-slug>`, then `push` to store them under the new one.

## Command reference

```text
tupacs env push [FILES...]      encrypt env file(s) of the current repo   (default: .env)
tupacs env pull [FILES...]      restore this repo's stored env file(s)    (default: all)
    --repo SLUG                 pull another repo's files into this directory
    --force, -f                 overwrite local files that differ
tupacs env ls                   list every stored env file; '*' = current repo
tupacs env show [FILE]          print stored content                     (default: .env)
tupacs env rm [FILE]            remove a stored env file                 (default: .env)
    --force, -f                 skip the confirmation prompt
```

Paths are relative to the repo root (or absolute, as long as they're inside
it). Every command takes `--help`.

## What the remote can see

Same as the rest of the vault, with one wrinkle worth being deliberate about:
entry *names* are not encrypted, and an env entry's name contains **your repo's
host, owner, name, and the file's path within it** — e.g.
`env/github.com/you/my-saas/apps/api/.env.production`.

Contents are always ciphertext, and the name is bound into the encryption as
associated data, so a moved or renamed ciphertext fails to decrypt. But if the
existence of a private repository is itself sensitive, remember that whoever
hosts your sync remote can read that structure. See the
[security model](../README.md#security-model) for the full picture.

## Troubleshooting

**`no env files stored for 'local/my-project' — run tupacs env push in that repo first`**
The `local/` prefix means no `origin` remote was found. Either you're not in
the repo you think you are, or the remote is named something other than
`origin`. Check with `git remote -v`.

**`no env files stored for 'github.com/you/proj'`, but you know you pushed it**
The key is derived from `origin`, so it changed if the repo was renamed,
transferred, or you cloned a fork. `tupacs env ls` lists every key you've
stored; pull the right one with `--repo <slug>`.

**`/etc/hosts is outside the repository …`**
`push` only accepts files inside the current repo — the path relative to the
repo root is what makes the entry restorable elsewhere. For secrets that
aren't part of a repository, use a normal entry (`tupacs add`) instead.

**`env pull` says `skipped`**
A local file exists and differs. Compare it against the stored copy with
`tupacs env show`, then re-run with `--force` if the stored version should win.

**Nothing prompts for a passphrase / everything prompts**
`push`, `pull` and `show` decrypt, so they need the key; `ls` doesn't.
`tupacs unlock` caches the key for an hour, `tupacs lock` forgets it.

---

## Regenerating the GIFs on this page

They're recorded with [VHS](https://github.com/charmbracelet/vhs) from the
tapes in [`vhs/`](vhs/). The tapes record against a throwaway fixture — real
git repos with real remotes, a fresh clone, and a scratch vault — built by
[`vhs/setup-env-demo.sh`](vhs/setup-env-demo.sh) under `/tmp/tupacs-vhs-env`,
which each tape rebuilds itself. Your own vault and `~/.gitconfig` are never
touched.

```bash
vhs docs/vhs/env.tape          # -> docs/env.gif
vhs docs/vhs/env-multi.tape    # -> docs/env-multi.gif
vhs docs/vhs/env-safety.tape   # -> docs/env-safety.gif
```

Run them from the repo root with `tupacs` on `$PATH`.
