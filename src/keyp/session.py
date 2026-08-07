"""Short-lived unlocked-key cache (`keyp unlock` / `keyp lock`).

The derived vault key is cached in a user-private directory so repeated
commands don't re-prompt for the passphrase — the moral equivalent of
gpg-agent for `pass`. Preference order for the cache location:

1. ``$XDG_RUNTIME_DIR`` (tmpfs on systemd Linux — RAM-backed, wiped at logout)
2. ``/dev/shm`` (RAM-backed)
3. the platform temp dir (private per-user on macOS)

Files are created ``0600`` inside a ``0700`` directory and expire after a TTL.
No sudo, no daemon.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import tempfile
import time
from pathlib import Path

DEFAULT_TTL = 3600  # seconds


def private_tmpdir() -> Path | None:
    """Return a user-private (ideally RAM-backed) scratch directory."""
    candidates: list[Path] = []
    if xdg := os.environ.get("XDG_RUNTIME_DIR"):
        candidates.append(Path(xdg))
    candidates.append(Path("/dev/shm"))
    candidates.append(Path(tempfile.gettempdir()))

    uid = getattr(os, "getuid", lambda: "u")()
    for base in candidates:
        if not base.is_dir() or not os.access(base, os.W_OK):
            continue
        d = base / f"keyp-{uid}"
        try:
            d.mkdir(mode=0o700, exist_ok=True)
            os.chmod(d, 0o700)
        except OSError:
            continue
        return d
    return None


def is_ram_backed() -> bool:
    d = private_tmpdir()
    return d is not None and (
        str(d).startswith(os.environ.get("XDG_RUNTIME_DIR", "\0"))
        or str(d).startswith("/dev/shm")
    )


def _session_file(vault_path: Path) -> Path | None:
    d = private_tmpdir()
    if d is None:
        return None
    tag = hashlib.sha256(str(Path(vault_path).resolve()).encode()).hexdigest()[:16]
    return d / f"{tag}.session"


def store_key(vault_path: Path, key: bytes, ttl: int = DEFAULT_TTL) -> bool:
    """Cache *key* for *ttl* seconds. Returns False if no usable location."""
    f = _session_file(vault_path)
    if f is None:
        return False
    payload = json.dumps(
        {"key": base64.b64encode(key).decode(), "expires": int(time.time()) + ttl}
    ).encode()
    fd = os.open(f, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.write(fd, payload)
    finally:
        os.close(fd)
    return True


def load_key(vault_path: Path) -> bytes | None:
    """Return the cached key, or None if absent/expired/corrupt."""
    f = _session_file(vault_path)
    if f is None or not f.is_file():
        return None
    try:
        data = json.loads(f.read_bytes())
        if int(data["expires"]) < time.time():
            f.unlink(missing_ok=True)
            return None
        return base64.b64decode(data["key"])
    except (OSError, ValueError, KeyError):
        f.unlink(missing_ok=True)
        return None


def remaining(vault_path: Path) -> int:
    """Seconds until the cached key expires (0 if not cached)."""
    f = _session_file(vault_path)
    if f is None or not f.is_file():
        return 0
    try:
        data = json.loads(f.read_bytes())
        return max(0, int(data["expires"]) - int(time.time()))
    except (OSError, ValueError, KeyError):
        return 0


def clear(vault_path: Path) -> None:
    f = _session_file(vault_path)
    if f is not None:
        f.unlink(missing_ok=True)
