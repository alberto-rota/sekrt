"""The tupacs vault: a directory of individually-encrypted entries.

Layout (mirrors `pass`, one file per secret, so git diffs stay small)::

    ~/.local/share/tupacs/
        .tupacs.json          # vault config: KDF params, keycheck, options
        .gitattributes
        work/github.tup        # entry "work/github"
        env/github.com/you/proj/.env.tup
        ssh/deploy-key.tup

Entry names and folder structure are visible metadata (like `pass`);
contents are AES-256-GCM encrypted with the entry name as associated data.
Each decrypted entry is a JSON document::

    {"version": 1, "type": "password", "created": ..., "modified": ...,
     "data": {"password": "...", "username": "...", ...}}
"""

from __future__ import annotations

import json
import os
import re
import tempfile
import time
from pathlib import Path

from tupacs import crypto, gitsync
from tupacs.crypto import KdfParams, WrongPassphraseError

CONFIG_NAME = ".tupacs.json"
ENTRY_SUFFIX = ".tup"
ENTRY_VERSION = 1

TYPES = ("password", "api_key", "note", "env", "ssh")
PRIMARY_FIELD = {
    "password": "password",
    "api_key": "key",
    "note": "notes",
    "env": "content",
    "ssh": "private",
}

_SEGMENT_RE = re.compile(r"^[\w.@+ -]+$", re.ASCII)


class VaultError(Exception):
    pass


class VaultNotInitializedError(VaultError):
    pass


class EntryNotFoundError(VaultError):
    pass


class EntryExistsError(VaultError):
    pass


class InvalidNameError(VaultError):
    pass


def default_vault_dir() -> Path:
    if env := os.environ.get("TUPACS_VAULT"):
        return Path(env).expanduser()
    data_home = os.environ.get("XDG_DATA_HOME") or "~/.local/share"
    return Path(data_home).expanduser() / "tupacs"


def validate_name(name: str) -> str:
    """Validate a logical entry name like ``work/github``. Returns it unchanged."""
    if not name or len(name) > 300:
        raise InvalidNameError("entry name must be 1-300 characters")
    if name.startswith("/") or name.endswith("/"):
        raise InvalidNameError("entry name must not start or end with '/'")
    for seg in name.split("/"):
        if (
            not seg
            or seg in (".", "..")
            or seg.startswith(".git")
            or seg == CONFIG_NAME
            or seg != seg.strip()
            or not _SEGMENT_RE.match(seg)
        ):
            raise InvalidNameError(
                f"invalid name segment {seg!r} — use letters, digits, and . _ @ + - "
                "(separate folders with '/')"
            )
    return name


def sanitize_segment(seg: str) -> str:
    """Coerce an arbitrary string into a valid name segment."""
    seg = re.sub(r"[^\w.@+-]", "-", seg.strip(), flags=re.ASCII).strip(".-")
    return seg or "x"


def new_entry(type_: str, data: dict[str, str]) -> dict:
    if type_ not in TYPES:
        raise VaultError(f"unknown entry type {type_!r} (expected one of {', '.join(TYPES)})")
    now = int(time.time())
    return {"version": ENTRY_VERSION, "type": type_, "created": now, "modified": now, "data": data}


def primary_field(entry: dict) -> str | None:
    """Name of the entry's main secret field, if present."""
    field = PRIMARY_FIELD.get(entry.get("type", ""), "password")
    if field in entry.get("data", {}):
        return field
    return next(iter(entry.get("data", {})), None)


class Vault:
    def __init__(self, path: Path | str | None = None):
        self.path = Path(path) if path else default_vault_dir()

    # -- lifecycle -----------------------------------------------------------

    @property
    def config_path(self) -> Path:
        return self.path / CONFIG_NAME

    @property
    def initialized(self) -> bool:
        return self.config_path.is_file()

    def _config(self) -> dict:
        if not self.initialized:
            raise VaultNotInitializedError(
                f"no vault at {self.path} — run `tupacs init` first"
            )
        try:
            return json.loads(self.config_path.read_text())
        except (OSError, ValueError) as exc:
            raise VaultError(f"unreadable vault config: {exc}") from exc

    def _save_config(self, config: dict) -> None:
        _atomic_write(self.config_path, json.dumps(config, indent=2).encode() + b"\n")

    def create(self, passphrase: str) -> bytes:
        """Initialise a new vault and return the derived key."""
        if self.initialized:
            raise VaultError(f"vault already exists at {self.path}")
        if not passphrase:
            raise VaultError("passphrase must not be empty")
        self.path.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(self.path, 0o700)

        params = KdfParams.generate()
        key = crypto.derive_key(passphrase, params)
        config = {
            "version": 1,
            "kdf": params.to_dict(),
            "keycheck": crypto.make_keycheck(key),
            "auto_sync": False,
        }
        self._save_config(config)
        gitsync.ensure_repo(self.path)
        gitsync.commit_all(self.path, "tupacs: initialize vault")
        return key

    def unlock(self, passphrase: str) -> bytes:
        """Derive the key from *passphrase* and verify it. Raises WrongPassphraseError."""
        config = self._config()
        key = crypto.derive_key(passphrase, KdfParams.from_dict(config["kdf"]))
        if not crypto.verify_keycheck(key, config["keycheck"]):
            raise WrongPassphraseError("wrong passphrase")
        return key

    def verify_key(self, key: bytes) -> bool:
        try:
            return crypto.verify_keycheck(key, self._config()["keycheck"])
        except VaultError:
            return False

    # -- config options ------------------------------------------------------

    @property
    def auto_sync(self) -> bool:
        return bool(self._config().get("auto_sync", False))

    def set_auto_sync(self, enabled: bool) -> None:
        config = self._config()
        config["auto_sync"] = enabled
        self._save_config(config)
        self._commit(f"tupacs: auto-sync {'on' if enabled else 'off'}")

    # -- entries -------------------------------------------------------------

    def _entry_file(self, name: str) -> Path:
        validate_name(name)
        file = self.path / (name + ENTRY_SUFFIX)
        if not file.resolve().is_relative_to(self.path.resolve()):
            raise InvalidNameError(f"entry name escapes the vault: {name!r}")
        return file

    def exists(self, name: str) -> bool:
        return self._entry_file(name).is_file()

    def list_entries(self, prefix: str = "") -> list[str]:
        if not self.initialized:
            raise VaultNotInitializedError(
                f"no vault at {self.path} — run `tupacs init` first"
            )
        names = []
        for file in self.path.rglob(f"*{ENTRY_SUFFIX}"):
            rel = file.relative_to(self.path)
            if rel.parts[0] == ".git":
                continue
            name = str(rel)[: -len(ENTRY_SUFFIX)]
            if name.startswith(prefix):
                names.append(name)
        return sorted(names)

    def search(self, query: str) -> list[str]:
        q = query.lower()
        return [n for n in self.list_entries() if q in n.lower()]

    def read(self, key: bytes, name: str) -> dict:
        file = self._entry_file(name)
        if not file.is_file():
            raise EntryNotFoundError(f"no entry named {name!r}")
        plaintext = crypto.decrypt(key, file.read_bytes(), aad=name.encode())
        return json.loads(plaintext)

    def write(
        self,
        key: bytes,
        name: str,
        entry: dict,
        *,
        overwrite: bool = False,
        message: str | None = None,
    ) -> None:
        file = self._entry_file(name)
        if file.is_file() and not overwrite:
            raise EntryExistsError(f"entry {name!r} already exists (use --force to overwrite)")
        if file.is_dir():
            raise VaultError(f"{name!r} is a folder, not an entry")
        entry["modified"] = int(time.time())
        blob = crypto.encrypt(key, json.dumps(entry).encode(), aad=name.encode())
        file.parent.mkdir(parents=True, exist_ok=True)
        _atomic_write(file, blob)
        self._commit(message or f"{'update' if overwrite else 'add'} {name}")

    def delete(self, name: str, *, message: str | None = None) -> None:
        file = self._entry_file(name)
        if not file.is_file():
            raise EntryNotFoundError(f"no entry named {name!r}")
        file.unlink()
        parent = file.parent
        while parent != self.path and not any(parent.iterdir()):
            parent.rmdir()
            parent = parent.parent
        self._commit(message or f"remove {name}")

    def move(self, key: bytes, old: str, new: str, *, overwrite: bool = False) -> None:
        if old == new:
            return
        entry = self.read(key, old)  # AAD is the name, so re-encrypt under the new one
        if self.exists(new) and not overwrite:
            raise EntryExistsError(f"entry {new!r} already exists")
        self.write(key, new, entry, overwrite=overwrite, message=f"move {old} -> {new}")
        self.delete(old, message=f"move {old} -> {new} (cleanup)")

    def rekey(self, old_key: bytes, new_passphrase: str) -> bytes:
        """Change the vault passphrase, re-encrypting every entry.

        Entries are decrypted up-front so a wrong key fails before anything
        is written; the auto-commits mean git history can restore any state.
        """
        if not new_passphrase:
            raise VaultError("passphrase must not be empty")
        entries = {name: self.read(old_key, name) for name in self.list_entries()}

        params = KdfParams.generate()
        new_key = crypto.derive_key(new_passphrase, params)
        config = self._config()
        config["kdf"] = params.to_dict()
        config["keycheck"] = crypto.make_keycheck(new_key)
        self._save_config(config)
        for name, entry in entries.items():
            blob = crypto.encrypt(new_key, json.dumps(entry).encode(), aad=name.encode())
            _atomic_write(self.path / (name + ENTRY_SUFFIX), blob)
        self._commit("tupacs: rekey vault")
        return new_key

    # -- git -----------------------------------------------------------------

    def _commit(self, message: str) -> None:
        if gitsync.commit_all(self.path, message) and self.auto_sync:
            gitsync.push(self.path)  # best-effort; `tupacs sync` reports errors


def _atomic_write(path: Path, data: bytes) -> None:
    """Write with 0600 permissions, atomically (write temp file + rename)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tup-tmp-")
    try:
        try:
            os.write(fd, data)
        finally:
            os.close(fd)
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
