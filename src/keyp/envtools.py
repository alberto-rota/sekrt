"""Store and restore .env files, keyed by the repository they belong to.

``keyp env push`` run anywhere inside a git repo figures out the repo's
identity from its ``origin`` remote (``github.com/you/project``) and stores
the file under ``env/<slug>/<relative-path>``. On any machine, in a fresh
clone, ``keyp env pull`` puts it back. Repos without a remote fall back
to ``local/<dirname>``.
"""

from __future__ import annotations

import hashlib
import re
import subprocess
from pathlib import Path
from urllib.parse import urlparse

from keyp.vault import (
    EntryNotFoundError,
    Vault,
    VaultError,
    new_entry,
    sanitize_segment,
)

ENV_PREFIX = "env"


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


def _relpath(root: Path, file: Path) -> str:
    try:
        rel = file.resolve().relative_to(root.resolve())
    except ValueError:
        raise EnvError(f"{file} is outside the repository {root}") from None
    return str(rel)


def push(vault: Vault, key: bytes, file: Path, *, cwd: Path | None = None) -> tuple[str, str]:
    """Store *file* in the vault. Returns (entry name, 'added'|'updated'|'unchanged')."""
    root, slug = current_context(cwd)
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


def stored_files(vault: Vault, slug: str) -> list[str]:
    """Relative paths of env files stored for *slug*."""
    prefix = f"{ENV_PREFIX}/{slug}/"
    return [n[len(prefix) :] for n in vault.list_entries(prefix)]


def list_all(vault: Vault) -> list[str]:
    """Every stored env entry, with the ``env/`` prefix stripped."""
    prefix = f"{ENV_PREFIX}/"
    return [n[len(prefix) :] for n in vault.list_entries(prefix)]


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
    """
    root, detected = current_context(cwd)
    slug = slug or detected
    relpaths = files if files else stored_files(vault, slug)
    if not relpaths:
        raise EntryNotFoundError(
            f"no env files stored for {slug!r} — run `keyp env push` in that repo first"
        )

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
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)
        target.chmod(0o600)
        results.append((relpath, "restored"))
    return results


def _digest(content: str) -> str:
    return hashlib.sha256(content.encode()).hexdigest()[:16]
