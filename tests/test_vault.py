import pytest

from tupacs.crypto import WrongPassphraseError
from tupacs.vault import (
    EntryExistsError,
    EntryNotFoundError,
    InvalidNameError,
    Vault,
    VaultError,
    new_entry,
    primary_field,
    validate_name,
)

from .conftest import PASSPHRASE


def test_create_and_unlock(vault):
    v, key = vault
    assert v.initialized
    assert v.unlock(PASSPHRASE) == key
    assert v.verify_key(key)


def test_wrong_passphrase(vault):
    v, _ = vault
    with pytest.raises(WrongPassphraseError):
        v.unlock("nope")


def test_create_twice_fails(vault):
    v, _ = vault
    with pytest.raises(VaultError):
        v.create(PASSPHRASE)


def test_write_read_roundtrip(vault):
    v, key = vault
    entry = new_entry("password", {"password": "s3cret", "username": "alberto"})
    v.write(key, "work/github", entry)
    got = v.read(key, "work/github")
    assert got["data"]["password"] == "s3cret"
    assert got["type"] == "password"
    assert primary_field(got) == "password"


def test_overwrite_protection(vault):
    v, key = vault
    v.write(key, "a", new_entry("password", {"password": "1"}))
    with pytest.raises(EntryExistsError):
        v.write(key, "a", new_entry("password", {"password": "2"}))
    v.write(key, "a", new_entry("password", {"password": "2"}), overwrite=True)
    assert v.read(key, "a")["data"]["password"] == "2"


def test_list_and_search(vault):
    v, key = vault
    for name in ("work/github", "work/gitlab", "personal/bank"):
        v.write(key, name, new_entry("password", {"password": "x"}))
    assert v.list_entries() == ["personal/bank", "work/github", "work/gitlab"]
    assert v.list_entries("work/") == ["work/github", "work/gitlab"]
    assert v.search("git") == ["work/github", "work/gitlab"]


def test_move(vault):
    v, key = vault
    v.write(key, "old/name", new_entry("password", {"password": "x"}))
    v.move(key, "old/name", "new/name")
    assert not v.exists("old/name")
    assert v.read(key, "new/name")["data"]["password"] == "x"
    # empty parent folder is pruned
    assert not (v.path / "old").exists()


def test_delete(vault):
    v, key = vault
    v.write(key, "gone", new_entry("password", {"password": "x"}))
    v.delete("gone")
    with pytest.raises(EntryNotFoundError):
        v.read(key, "gone")


def test_invalid_names(vault):
    v, key = vault
    for bad in ("", "/abs", "a//b", "../escape", "a/../b", ".git/config",
                ".tupacs.json", "trailing/", "sp ace-ok/../nope"):
        with pytest.raises(InvalidNameError):
            v.write(key, bad, new_entry("password", {"password": "x"}))


def test_valid_names():
    for good in ("a", "work/github", ".env", "env/github.com/me/repo/.env",
                 "my key/with space", "user@host", "c++/notes"):
        assert validate_name(good) == good


def test_short_passphrase_rejected(tmp_path, vault):
    with pytest.raises(VaultError):
        Vault(tmp_path / "weak").create("hunter2")
    v, key = vault
    with pytest.raises(VaultError):
        v.rekey(key, "short")
    assert v.unlock(PASSPHRASE) == key  # vault untouched


def test_rekey(vault):
    v, key = vault
    v.write(key, "keep/me", new_entry("password", {"password": "x"}))
    new_key = v.rekey(key, "new passphrase")
    assert v.unlock("new passphrase") == new_key
    with pytest.raises(WrongPassphraseError):
        v.unlock(PASSPHRASE)
    assert v.read(new_key, "keep/me")["data"]["password"] == "x"


def test_uninitialized_vault(tmp_path):
    v = Vault(tmp_path / "nothing")
    assert not v.initialized
    with pytest.raises(VaultError):
        v.list_entries()


def test_entry_file_permissions(vault):
    v, key = vault
    v.write(key, "perm", new_entry("password", {"password": "x"}))
    mode = (v.path / "perm.tup").stat().st_mode & 0o777
    assert mode == 0o600
