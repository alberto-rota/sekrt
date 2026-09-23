"""Store, generate and restore SSH keypairs.

Keys live under ``ssh/<name>`` in the vault. ``restore`` writes them back
with correct permissions (0600 private / 0644 public). ``authorize`` (and
``restore --authorize``) appends the public half to ``authorized_keys`` so
this machine accepts the key for login. Generation produces ed25519 keys
in OpenSSH format via the ``cryptography`` package — no ``ssh-keygen``
subprocess needed.
"""

from __future__ import annotations

import os
from pathlib import Path

from cryptography.exceptions import UnsupportedAlgorithm
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from sekrt.vault import Vault, VaultError, new_entry

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


def public_from_private(private: str, comment: str = "") -> str | None:
    """OpenSSH authorized_keys line for *private*, or None if it cannot be parsed.

    Encrypted keys (a passphrase was set) cannot be derived without that
    passphrase; the stored ``.pub`` is the only copy in that case.
    """
    raw = private.encode()
    key = None
    for loader in (
        lambda: serialization.load_ssh_private_key(raw, password=None),
        lambda: serialization.load_pem_private_key(raw, password=None),
    ):
        try:
            key = loader()
            break
        except (TypeError, ValueError, UnsupportedAlgorithm):
            continue
    if key is None:
        return None
    try:
        public = (
            key.public_key()
            .public_bytes(serialization.Encoding.OpenSSH, serialization.PublicFormat.OpenSSH)
            .decode()
        )
    except (ValueError, UnsupportedAlgorithm):
        return None
    if comment:
        public += f" {comment.strip()}"
    return public + "\n"


def public_line(data: dict) -> str | None:
    """Stored authorized_keys line, or one derived from the private key."""
    if public := data.get("public"):
        return public
    private = data.get("private")
    if not private:
        return None
    return public_from_private(private, data.get("comment") or "")


def load_keypair(private_path: Path) -> tuple[str, str | None, str]:
    """Read (private, public, comment) from disk.

    A companion ``.pub`` is used when present; otherwise the public half is
    derived from the private key so restore still writes both files.
    """
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
    if not public_str:
        public_str = public_from_private(private_str, comment)
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
    if not public:
        public = public_from_private(private, comment)
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
    authorize: bool = False,
) -> list[Path]:
    """Write the keypair to *directory* with proper permissions.

    With *authorize*, also append the public key to ``authorized_keys`` in
    the same directory (creating it at 0600 if needed).
    """
    entry = vault.read(key, full_name(name))
    data = entry["data"]
    fname = filename or data.get("filename") or name.split("/")[-1]
    if not fname or fname != Path(fname).name or fname in (".", ".."):
        raise SshError(f"invalid key file name {fname!r} — must be a bare file name")

    directory = directory.expanduser()
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    private_path = directory / fname
    public_path = directory / (fname + ".pub")

    written: list[Path] = []
    for path, content, mode in (
        (private_path, data["private"], 0o600),
        (public_path, public_line(data), 0o644),
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
    if authorize:
        public = public_line(data)
        if not public:
            raise SshError("no public key to add to authorized_keys")
        auth_path = directory / "authorized_keys"
        append_authorized(public, auth_path)
        written.append(auth_path)
    return written


_KEY_TYPE_PREFIXES = ("ssh-", "ecdsa-", "sk-")


def _key_blob(line: str) -> str | None:
    """The key material from an authorized_keys line, or None if it isn't one."""
    parts = line.strip().split()
    if not parts or parts[0].startswith("#"):
        return None
    types = [i for i, part in enumerate(parts) if part.startswith(_KEY_TYPE_PREFIXES)]
    if not types or types[0] + 1 >= len(parts):
        return None
    return parts[types[0] + 1]


def append_authorized(public: str, path: Path) -> bool:
    """Append *public* to ``authorized_keys`` if that key is not already listed.

    Creates the file at 0600. Returns True if a line was added.
    """
    line = public.strip()
    blob = _key_blob(line)
    if blob is None:
        raise SshError("public key is not an OpenSSH authorized_keys line")

    path = path.expanduser()
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)

    existing = path.read_text() if path.is_file() else ""
    already = {_key_blob(current) for current in existing.splitlines()}
    if blob in already:
        os.chmod(path, 0o600)
        return False

    prefix = "" if not existing or existing.endswith("\n") else "\n"
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    try:
        os.write(fd, f"{prefix}{line}\n".encode())
    finally:
        os.close(fd)
    os.chmod(path, 0o600)
    return True


def authorize(
    vault: Vault,
    key: bytes,
    name: str,
    *,
    directory: Path,
) -> tuple[Path, bool]:
    """Append a stored public key to *directory*/authorized_keys.

    Returns ``(path, added)``. ``added`` is False when that key is already listed.
    Does not write the private key.
    """
    entry = vault.read(key, full_name(name))
    public = public_line(entry["data"])
    if not public:
        raise SshError(f"no public key for {name!r}")
    directory = directory.expanduser()
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    path = directory / "authorized_keys"
    return path, append_authorized(public, path)
