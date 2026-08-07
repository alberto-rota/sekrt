"""Store, generate and restore SSH keypairs.

Keys live under ``ssh/<name>`` in the vault. ``restore`` writes them back
with correct permissions (0600 private / 0644 public). Generation produces
ed25519 keys in OpenSSH format via the ``cryptography`` package — no
``ssh-keygen`` subprocess needed.
"""

from __future__ import annotations

import os
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from keyp.vault import Vault, VaultError, new_entry

SSH_PREFIX = "ssh"


class SshError(VaultError):
    pass


def full_name(name: str) -> str:
    return name if name.startswith(f"{SSH_PREFIX}/") else f"{SSH_PREFIX}/{name}"


def generate_ed25519(comment: str) -> tuple[str, str]:
    """Return (private OpenSSH PEM, public authorized_keys line)."""
    private = Ed25519PrivateKey.generate()
    private_str = private.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.OpenSSH,
        serialization.NoEncryption(),
    ).decode()
    public_str = (
        private.public_key()
        .public_bytes(serialization.Encoding.OpenSSH, serialization.PublicFormat.OpenSSH)
        .decode()
    )
    if comment:
        public_str += f" {comment}"
    return private_str, public_str + "\n"


def load_keypair(private_path: Path) -> tuple[str, str | None, str]:
    """Read (private, public, comment) from disk. Public key is optional."""
    if not private_path.is_file():
        raise SshError(f"no such key file: {private_path}")
    private_str = private_path.read_text()
    if "PRIVATE KEY" not in private_str.splitlines()[0]:
        raise SshError(f"{private_path} does not look like a private key")
    public_path = private_path.with_name(private_path.name + ".pub")
    public_str = public_path.read_text() if public_path.is_file() else None
    comment = ""
    if public_str:
        parts = public_str.split(None, 2)
        if len(parts) == 3:
            comment = parts[2].strip()
    return private_str, public_str, comment


def store(
    vault: Vault,
    key: bytes,
    name: str,
    *,
    private: str,
    public: str | None,
    comment: str = "",
    filename: str = "",
    force: bool = False,
) -> str:
    entry_id = full_name(name)
    data = {"private": private, "comment": comment, "filename": filename or name.split("/")[-1]}
    if public:
        data["public"] = public
    entry = new_entry("ssh", data)
    vault.write(key, entry_id, entry, overwrite=force, message=f"ssh: add {entry_id}")
    return entry_id


def restore(
    vault: Vault,
    key: bytes,
    name: str,
    *,
    directory: Path,
    filename: str | None = None,
    force: bool = False,
) -> list[Path]:
    """Write the keypair to *directory* with proper permissions."""
    entry = vault.read(key, full_name(name))
    data = entry["data"]
    fname = filename or data.get("filename") or name.split("/")[-1]

    directory = directory.expanduser()
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    private_path = directory / fname
    public_path = directory / (fname + ".pub")

    written: list[Path] = []
    for path, content, mode in (
        (private_path, data["private"], 0o600),
        (public_path, data.get("public"), 0o644),
    ):
        if content is None:
            continue
        if path.exists() and not force:
            raise SshError(f"{path} already exists (use --force to overwrite)")
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, mode)
        try:
            os.write(fd, content.encode())
        finally:
            os.close(fd)
        os.chmod(path, mode)
        written.append(path)
    return written
