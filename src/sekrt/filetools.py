"""Store and restore arbitrary files (binary or text), encrypted whole.

Unlike ``sekrt env`` (text-only, keyed to a repo) or ``sekrt ssh``
(keypair-shaped), ``sekrt file`` just encrypts whatever bytes you hand it
under ``file/<name>`` and hands them back later — recovery codes, a PDF,
a keystore, anything.
"""

from __future__ import annotations

import base64
import hashlib
import os
from pathlib import Path

from sekrt.vault import Vault, VaultError, new_entry

FILE_PREFIX = "file"

# GitHub and GitLab reject a single blob over 100 MiB. Encryption inflates the
# payload (~4/3 via base64), so a source this large will not `sekrt sync`.
WARN_FILE_BYTES = 100 * 1024 * 1024


class FileToolError(VaultError):
    pass


def full_name(name: str) -> str:
    return name if name.startswith(f"{FILE_PREFIX}/") else f"{FILE_PREFIX}/{name}"


def store(
    vault: Vault,
    key: bytes,
    name: str,
    path: Path,
    *,
    force: bool = False,
) -> str:
    """Encrypt the file at *path* into the vault under ``file/<name>``."""
    if not path.is_file():
        raise FileToolError(f"no such file: {path}")
    content = path.read_bytes()
    entry_id = full_name(name)
    data = {
        "filename": path.name,
        "content_b64": base64.b64encode(content).decode(),
        "sha256": hashlib.sha256(content).hexdigest(),
        "size": str(len(content)),
    }
    entry = new_entry("file", data)
    vault.write(key, entry_id, entry, overwrite=force, message=f"file: add {entry_id}")
    return entry_id


def restore(
    vault: Vault,
    key: bytes,
    name: str,
    *,
    out: Path | None = None,
    force: bool = False,
) -> Path:
    """Decrypt the stored file back to disk. Returns the path written."""
    entry = vault.read(key, full_name(name))
    data = entry["data"]
    fname = data.get("filename") or name.split("/")[-1]
    dest = out if out is not None else Path(fname)
    if dest.is_dir():
        dest = dest / fname
    if dest.exists() and not force:
        raise FileToolError(f"{dest} already exists (use --force to overwrite)")

    content = base64.b64decode(data["content_b64"])
    dest.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(dest, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.write(fd, content)
    finally:
        os.close(fd)
    return dest
