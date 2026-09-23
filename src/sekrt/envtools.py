"""Store and restore .env files, keyed by the repository they belong to.

``sekrt env push`` run anywhere inside a git repo figures out the repo's
identity from its ``origin`` remote (``github.com/you/project``) and stores
the file under ``env/<slug>/<relative-path>``. On any machine, in a fresh
clone, ``sekrt env pull`` puts it back. Repos without a remote fall back
to ``local/<dirname>``.

If origin is renamed, the host still serves the old URL (HTTP redirect, or
the same ``git ls-remote`` HEAD). A miss then moves the stored files onto
the new slug and remembers the old name, so existing clones keep working.
"""

from __future__ import annotations

import hashlib
import os
import re
import subprocess
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

from sekrt.vault import (
    EntryNotFoundError,
    Vault,
    VaultError,
    _atomic_write,
    new_entry,
    sanitize_segment,
)

ENV_PREFIX = "env"
PROBE_TIMEOUT = 5  # seconds; a miss must not hang on an unreachable host


class EnvError(VaultError):
    pass


def find_repo_root(start: Path | None = None) -> Path | None:
    """Root of the git repo containing *start* (default: cwd), or None."""
    try:
        res = subprocess.run(
            ["git", "-C", str(start or Path.cwd()), "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    top = res.stdout.strip()
    return Path(top) if res.returncode == 0 and top else None


def normalize_remote_url(url: str) -> str | None:
    """Reduce a git remote URL to a slug like ``github.com/you/proj``."""
    url = url.strip()
    if not url:
        return None
    if "://" in url:
        parsed = urlparse(url)
        host, path = (parsed.hostname or "").lower(), parsed.path
    else:
        scp_like = re.match(r"^(?:[\w.-]+@)?([\w.-]+):(.+)$", url)
        if scp_like:
            host, path = scp_like.group(1).lower(), scp_like.group(2)
        else:
            host, path = "", url
    path = path.strip("/")
    path = path.removesuffix(".git")
    slug = "/".join(part for part in (host, *path.split("/")) if part)
    return slug or None


def repo_slug(root: Path) -> str:
    """Stable identity for a repo: its origin remote, or ``local/<dirname>``."""
    try:
        res = subprocess.run(
            ["git", "-C", str(root), "config", "--get", "remote.origin.url"],
            capture_output=True,
            text=True,
            timeout=15,
        )
        slug = normalize_remote_url(res.stdout) if res.returncode == 0 else None
    except (OSError, subprocess.SubprocessError):
        slug = None
    if slug:
        return "/".join(sanitize_segment(part) for part in slug.split("/"))
    return f"local/{sanitize_segment(root.name)}"


def current_context(cwd: Path | None = None) -> tuple[Path, str]:
    """(repo root, slug) for the current directory; falls back to cwd itself."""
    cwd = cwd or Path.cwd()
    root = find_repo_root(cwd)
    if root is None:
        return cwd, f"local/{sanitize_segment(cwd.name)}"
    return root, repo_slug(root)


def entry_name(slug: str, relpath: str) -> str:
    return f"{ENV_PREFIX}/{slug}/{relpath}"


def resolve_slug(vault: Vault, slug: str) -> str:
    """Follow env aliases recorded after a repo rename."""
    aliases = vault.env_aliases
    seen: set[str] = set()
    while slug in aliases and slug not in seen:
        seen.add(slug)
        slug = aliases[slug]
    return slug


def stored_slugs(vault: Vault, key: bytes) -> list[str]:
    """Unique repo slugs that have at least one stored env file."""
    slugs: set[str] = set()
    for name in vault.list_entries(f"{ENV_PREFIX}/"):
        slug = vault.read(key, name)["data"].get("slug")
        if not slug:
            rest = name[len(ENV_PREFIX) + 1 :]
            slug = rest.rpartition("/")[0]
        if slug:
            slugs.add(slug)
    return sorted(slugs)


def stored_files(vault: Vault, slug: str) -> list[str]:
    """Relative paths of env files stored for *slug* (aliases followed)."""
    slug = resolve_slug(vault, slug)
    prefix = f"{ENV_PREFIX}/{slug}/"
    return [n[len(prefix) :] for n in vault.list_entries(prefix)]


def list_all(vault: Vault) -> list[str]:
    """Every stored env entry, with the ``env/`` prefix stripped."""
    prefix = f"{ENV_PREFIX}/"
    return [n[len(prefix) :] for n in vault.list_entries(prefix)]


def _relpath(root: Path, file: Path) -> str:
    try:
        rel = file.resolve().relative_to(root.resolve())
    except ValueError:
        raise EnvError(f"{file} is outside the repository {root}") from None
    return str(rel)


def _host(slug: str) -> str:
    return slug.split("/", 1)[0]


def _owner_key(slug: str) -> tuple[str, str] | None:
    """``(host, owner)`` for ``host/owner/repo`` slugs; None for ``local/``."""
    parts = slug.split("/")
    if len(parts) < 3 or parts[0] == "local":
        return None
    return parts[0], parts[1]


def https_url(slug: str) -> str:
    return f"https://{slug}.git"


def ssh_url(slug: str) -> str:
    host, _, path = slug.partition("/")
    return f"git@{host}:{path}.git" if path else f"git@{host}.git"


def _follow_redirect_slug(slug: str) -> str | None:
    """Slug the HTTPS remote for *slug* redirects to, or None if unknown."""
    url = https_url(slug)
    headers = {"User-Agent": "sekrt"}
    for method in ("HEAD", "GET"):
        req = urllib.request.Request(url, method=method, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=PROBE_TIMEOUT) as resp:
                return normalize_remote_url(resp.geturl())
        except urllib.error.HTTPError as exc:
            if exc.code in (301, 302, 303, 307, 308) and exc.headers.get("Location"):
                return normalize_remote_url(exc.headers["Location"])
            if method == "HEAD" and exc.code in (403, 405):
                continue
            return None
        except (OSError, urllib.error.URLError, ValueError):
            return None
    return None


def _remote_head(url: str) -> str | None:
    """HEAD commit advertised by *url*, or None if it cannot be reached."""
    env = os.environ.copy()
    env["GIT_TERMINAL_PROMPT"] = "0"
    env.setdefault("GIT_SSH_COMMAND", "ssh -o BatchMode=yes -o ConnectTimeout=5")
    try:
        res = subprocess.run(
            ["git", "ls-remote", url, "HEAD"],
            capture_output=True,
            text=True,
            timeout=PROBE_TIMEOUT,
            env=env,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if res.returncode != 0:
        return None
    line = res.stdout.strip().split("\n", 1)[0]
    sha = line.split()[0] if line else ""
    return sha or None


def find_renamed_slug(vault: Vault, key: bytes, current: str) -> str | None:
    """The one stored slug that is this same repository under another name.

    A unique HTTP redirect to *current* wins; otherwise same-owner remotes
    with the same ``ls-remote`` HEAD. Forks (same HEAD, different owner,
    no redirect) are left alone. ``None`` if it is not unique or not proven.
    """
    if current.startswith("local/"):
        return None
    host = _host(current)
    matches: list[str] = []
    for candidate in stored_slugs(vault, key):
        if candidate == current or candidate.startswith("local/") or _host(candidate) != host:
            continue
        redirected = _follow_redirect_slug(candidate)
        if redirected == current:
            matches.append(candidate)
            if len(matches) > 1:
                return None
            continue
        if redirected is not None and redirected != candidate:
            continue  # the host says this slug is some other repo now
        if _owner_key(candidate) != _owner_key(current):
            continue
        old_head = _remote_head(ssh_url(candidate)) or _remote_head(https_url(candidate))
        new_head = _remote_head(ssh_url(current)) or _remote_head(https_url(current))
        if old_head and new_head and old_head == new_head:
            matches.append(candidate)
            if len(matches) > 1:
                return None
    return matches[0] if len(matches) == 1 else None


def adopt(vault: Vault, key: bytes, old: str, new: str) -> str | None:
    """Move env files from *old* to *new* and alias the old name. One commit."""
    old = resolve_slug(vault, old)
    if old == new or old == resolve_slug(vault, new):
        return None
    prefix = f"{ENV_PREFIX}/{old}/"
    names = vault.list_entries(prefix)
    if not names:
        return None
    for name in names:
        relpath = name[len(prefix) :]
        entry = vault.read(key, name)
        entry["data"]["slug"] = new
        vault.write(
            key,
            entry_name(new, relpath),
            entry,
            overwrite=True,
            commit=False,
        )
        vault.delete(name, commit=False)
    aliases = vault.env_aliases
    aliases[old] = new
    for source, target in list(aliases.items()):
        if target == old:
            aliases[source] = new
    vault.set_env_aliases(aliases, commit=False)
    vault._commit(f"env: {old} is now {new}")
    return f"{old} is now {new} — moved stored env files"


def realign(
    vault: Vault, key: bytes, slug: str | None = None, *, cwd: Path | None = None
) -> str | None:
    """If this origin is a rename of a stored slug, move the files over."""
    if slug is None:
        _, slug = current_context(cwd)
    if stored_files(vault, slug):
        return None
    found = find_renamed_slug(vault, key, slug)
    if not found:
        return None
    return adopt(vault, key, found, slug)


def _miss(vault: Vault, key: bytes, slug: str) -> EntryNotFoundError:
    others = [s for s in stored_slugs(vault, key) if resolve_slug(vault, s) != slug]
    hint = ""
    if others:
        hint = (
            f"\n  stored under: {', '.join(others)}"
            f"\n  a fork? `sekrt env pull --repo <slug>`"
        )
    return EntryNotFoundError(
        f"no env files stored for {slug!r} — run `sekrt env push` in that repo first{hint}"
    )


def push(vault: Vault, key: bytes, file: Path, *, cwd: Path | None = None) -> tuple[str, str]:
    """Store *file* in the vault. Returns (entry name, 'added'|'updated'|'unchanged')."""
    root, slug = current_context(cwd)
    realign(vault, key, slug, cwd=cwd)
    slug = resolve_slug(vault, slug)
    file = (cwd or Path.cwd()) / file if not file.is_absolute() else file
    if not file.is_file():
        raise EnvError(f"no such file: {file}")
    content = file.read_text()
    relpath = _relpath(root, file)
    name = entry_name(slug, relpath)

    if vault.exists(name):
        entry = vault.read(key, name)
        if entry["data"].get("content") == content:
            return name, "unchanged"
        entry["data"]["content"] = content
        entry["data"]["sha256"] = _digest(content)
        vault.write(key, name, entry, overwrite=True, message=f"env: update {name}")
        return name, "updated"

    entry = new_entry(
        "env",
        {"content": content, "slug": slug, "relpath": relpath, "sha256": _digest(content)},
    )
    vault.write(key, name, entry, message=f"env: add {name}")
    return name, "added"


def pull(
    vault: Vault,
    key: bytes,
    *,
    cwd: Path | None = None,
    files: list[str] | None = None,
    force: bool = False,
    slug: str | None = None,
) -> list[tuple[str, str]]:
    """Restore stored env files into the current repo.

    Returns a list of (relpath, 'restored'|'unchanged'|'skipped') tuples.
    Existing files with different content are only overwritten with *force*.
    *slug* (``--repo``) borrows another identity and does not retag a rename.
    """
    root, detected = current_context(cwd)
    if slug is None:
        realign(vault, key, detected, cwd=cwd)
        slug = resolve_slug(vault, detected)
    else:
        slug = resolve_slug(vault, slug)
    relpaths = files if files else stored_files(vault, slug)
    if not relpaths:
        raise _miss(vault, key, slug)

    results: list[tuple[str, str]] = []
    for relpath in relpaths:
        entry = vault.read(key, entry_name(slug, relpath))
        content = entry["data"]["content"]
        target = root / relpath
        if target.is_file():
            if target.read_text() == content:
                results.append((relpath, "unchanged"))
                continue
            if not force:
                results.append((relpath, "skipped"))
                continue
        _atomic_write(target, content.encode())  # 0600 from creation, never world-readable
        results.append((relpath, "restored"))
    return results


def _digest(content: str) -> str:
    return hashlib.sha256(content.encode()).hexdigest()[:16]
