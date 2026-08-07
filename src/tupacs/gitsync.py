"""Git-backed sync for the vault directory.

The vault is a plain git repository: every mutation is auto-committed, and
``tupacs sync`` does pull --rebase + push against ``origin``. Only the
system ``git`` binary is used (via subprocess) — no GitPython dependency.
All functions degrade gracefully when git is missing.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

FALLBACK_IDENTITY = ["-c", "user.name=tupacs", "-c", "user.email=tupacs@localhost"]
GITATTRIBUTES = "*.tup binary\n"


def has_git() -> bool:
    return shutil.which("git") is not None


def is_repo(path: Path) -> bool:
    return (Path(path) / ".git").exists()


def _run(path: Path, *args: str, extra: list[str] | None = None) -> subprocess.CompletedProcess:
    cmd = ["git", "-C", str(path), *(extra or []), *args]
    return subprocess.run(cmd, capture_output=True, text=True, timeout=120)


def _identity(path: Path) -> list[str]:
    """Fallback committer identity so auto-commits never fail on fresh machines."""
    res = _run(path, "config", "user.email")
    return [] if res.stdout.strip() else FALLBACK_IDENTITY


def _short(text: str, limit: int = 300) -> str:
    text = text.strip()
    return text if len(text) <= limit else text[:limit] + "…"


def ensure_repo(path: Path) -> bool:
    """Initialise a git repo in *path* if needed. Returns True if a repo exists."""
    path = Path(path)
    if not has_git():
        return False
    if is_repo(path):
        return True
    res = _run(path, "init", "-q", "-b", "main")
    if res.returncode != 0:  # very old git without -b
        res = _run(path, "init", "-q")
    if res.returncode != 0:
        return False
    (path / ".gitattributes").write_text(GITATTRIBUTES)
    return True


def current_branch(path: Path) -> str:
    res = _run(path, "symbolic-ref", "--short", "HEAD")
    return res.stdout.strip() or "main"


def commit_all(path: Path, message: str) -> bool:
    """Stage everything and commit. Returns True if a commit was created."""
    if not has_git() or not is_repo(path):
        return False
    _run(path, "add", "-A")
    if _run(path, "diff", "--cached", "--quiet").returncode == 0:
        return False
    res = _run(path, "commit", "-q", "-m", message, extra=_identity(path))
    return res.returncode == 0


def get_remote(path: Path) -> str | None:
    if not has_git() or not is_repo(path):
        return None
    res = _run(path, "remote", "get-url", "origin")
    return res.stdout.strip() or None


def set_remote(path: Path, url: str) -> None:
    if get_remote(path) is None:
        _run(path, "remote", "add", "origin", url)
    else:
        _run(path, "remote", "set-url", "origin", url)


def push(path: Path) -> tuple[bool, str]:
    branch = current_branch(path)
    res = _run(path, "push", "-u", "origin", branch)
    if res.returncode != 0:
        return False, f"push failed: {_short(res.stderr)}"
    return True, f"pushed {branch}"


def sync(path: Path) -> tuple[bool, str]:
    """pull --rebase then push. Returns (ok, human-readable message)."""
    path = Path(path)
    if not has_git():
        return False, "git is not installed"
    if not is_repo(path):
        return False, "vault is not a git repository — re-run `tupacs init`"
    remote = get_remote(path)
    if remote is None:
        return False, "no remote configured — run `tupacs remote <url>` first"

    branch = current_branch(path)
    pull = _run(
        path, "pull", "--rebase", "--autostash", "origin", branch, extra=_identity(path)
    )
    if pull.returncode != 0:
        err = pull.stderr.lower()
        if "couldn't find remote ref" not in err and "does not appear" not in err:
            _run(path, "rebase", "--abort")
            return False, "pull failed (resolve manually with `tupacs git status`): " + _short(
                pull.stderr
            )

    ok, msg = push(path)
    if not ok:
        return False, msg
    return True, f"vault synced with {remote}"


def log(path: Path, n: int = 15) -> str:
    res = _run(path, "log", "--oneline", "--no-decorate", f"-{n}")
    return res.stdout.strip()
