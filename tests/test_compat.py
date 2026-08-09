"""A vault created before the tupacs -> sekrt rename must keep working."""

import base64
import json

import pytest

from sekrt import compat, crypto
from sekrt.vault import Vault, new_entry

# -- environment variables ---------------------------------------------------


def test_env_prefers_new_name(monkeypatch):
    monkeypatch.setenv("SEKRT_THING", "new")
    monkeypatch.setenv("TUPACS_THING", "old")
    assert compat.env("THING") == "new"


def test_env_falls_back_to_legacy_name(monkeypatch):
    monkeypatch.delenv("SEKRT_THING", raising=False)
    monkeypatch.setenv("TUPACS_THING", "old")
    assert compat.env("THING") == "old"


def test_env_none_when_neither_set(monkeypatch):
    monkeypatch.delenv("SEKRT_THING", raising=False)
    monkeypatch.delenv("TUPACS_THING", raising=False)
    assert compat.env("THING") is None


def test_env_treats_empty_as_unset(monkeypatch):
    monkeypatch.setenv("SEKRT_THING", "")
    monkeypatch.setenv("TUPACS_THING", "old")
    assert compat.env("THING") == "old"


# -- on-disk formats ---------------------------------------------------------


def test_decrypt_accepts_legacy_magic():
    key = b"k" * 32
    blob = crypto.encrypt(key, b"payload", aad=b"n")
    assert blob.startswith(crypto.MAGIC)
    legacy = crypto.LEGACY_MAGIC + blob[len(crypto.MAGIC) :]
    assert crypto.decrypt(key, legacy, aad=b"n") == b"payload"


def test_verify_keycheck_accepts_legacy_plaintext():
    key = b"k" * 32
    legacy = base64.b64encode(
        crypto.encrypt(key, crypto.LEGACY_KEYCHECK_PLAINTEXT, aad=crypto.KEYCHECK_AAD)
    ).decode()
    assert crypto.verify_keycheck(key, legacy)


def test_garbage_header_still_rejected():
    with pytest.raises(crypto.DecryptionError):
        crypto.decrypt(b"k" * 32, b"XXXX" + b"0" * 40)


def _make_legacy_vault(tmp_path, passphrase="legacy-passphrase"):
    """A vault as 0.1.0 wrote it: .tupacs.json, .tup entries, old magic/keycheck."""
    v = Vault(tmp_path / "vault")
    key = v.create(passphrase)
    v.write(key, "work/github", new_entry("password", {"password": "hunter2222"}))

    # Downgrade every format marker to its pre-rename form.
    config = json.loads(v.config_path.read_text())
    config["keycheck"] = base64.b64encode(
        crypto.encrypt(key, crypto.LEGACY_KEYCHECK_PLAINTEXT, aad=crypto.KEYCHECK_AAD)
    ).decode()
    v.config_path.write_text(json.dumps(config))
    v.config_path.rename(v.path / compat.LEGACY_CONFIG_NAME)

    entry = v.path / "work" / "github.skr"
    blob = entry.read_bytes()
    entry.with_name("github.tup").write_bytes(crypto.LEGACY_MAGIC + blob[len(crypto.MAGIC) :])
    entry.unlink()
    return v.path


def test_legacy_entry_is_listed_and_readable(tmp_path):
    path = _make_legacy_vault(tmp_path)
    # The config still has its old name, so point the vault at it the way the
    # documented migration does (rename the config, leave the .tup entries).
    (path / compat.LEGACY_CONFIG_NAME).rename(path / ".sekrt.json")

    v = Vault(path)
    key = v.unlock("legacy-passphrase")  # old keycheck must still verify
    assert v.list_entries() == ["work/github"]
    assert v.read(key, "work/github")["data"]["password"] == "hunter2222"


def test_updating_a_legacy_entry_does_not_duplicate_it(tmp_path):
    path = _make_legacy_vault(tmp_path)
    (path / compat.LEGACY_CONFIG_NAME).rename(path / ".sekrt.json")

    v = Vault(path)
    key = v.unlock("legacy-passphrase")
    v.write(key, "work/github", new_entry("password", {"password": "rotated!!"}), overwrite=True)

    assert v.list_entries() == ["work/github"]  # not listed twice
    assert v.read(key, "work/github")["data"]["password"] == "rotated!!"
    assert (path / "work" / "github.tup").is_file()   # rewritten in place
    assert not (path / "work" / "github.skr").exists()


def test_deleting_a_legacy_entry_works(tmp_path):
    path = _make_legacy_vault(tmp_path)
    (path / compat.LEGACY_CONFIG_NAME).rename(path / ".sekrt.json")

    v = Vault(path)
    v.unlock("legacy-passphrase")
    v.delete("work/github")
    assert v.list_entries() == []


# -- the migration hint ------------------------------------------------------


def test_migration_hint_points_at_a_legacy_vault(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    legacy = tmp_path / compat.LEGACY_DIRNAME
    legacy.mkdir()
    (legacy / compat.LEGACY_CONFIG_NAME).write_text("{}")

    hint = compat.migration_hint()
    assert str(legacy) in hint
    assert str(tmp_path / "sekrt") in hint


def test_migration_hint_empty_without_a_legacy_vault(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    assert compat.migration_hint() == ""
    (tmp_path / compat.LEGACY_DIRNAME).mkdir()  # empty dir is not a vault
    assert compat.migration_hint() == ""
