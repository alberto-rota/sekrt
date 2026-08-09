import subprocess

from sekrt import gitsync
from sekrt.vault import new_entry

from .conftest import requires_git

pytestmark = requires_git


def test_vault_is_a_repo(vault):
    v, _ = vault
    assert gitsync.is_repo(v.path)
    assert gitsync.log(v.path)  # initial commit exists


def test_mutations_are_committed(vault):
    v, key = vault
    v.write(key, "a/b", new_entry("password", {"password": "x"}))
    v.delete("a/b")
    log = gitsync.log(v.path)
    assert "add a/b" in log
    assert "remove a/b" in log


def test_sync_without_remote(vault):
    v, _ = vault
    ok, msg = gitsync.sync(v.path)
    assert not ok
    assert "remote" in msg


def test_sync_with_bare_remote(vault, tmp_path):
    v, key = vault
    bare = tmp_path / "origin.git"
    subprocess.run(["git", "init", "-q", "--bare", str(bare)], check=True)
    gitsync.set_remote(v.path, str(bare))

    v.write(key, "synced/entry", new_entry("password", {"password": "x"}))
    ok, msg = gitsync.sync(v.path)
    assert ok, msg

    files = subprocess.run(
        ["git", "-C", str(bare), "ls-tree", "-r", "--name-only", "main"],
        capture_output=True, text=True, check=True,
    ).stdout
    assert "synced/entry.skr" in files
    assert ".sekrt.json" in files

    # second sync is a no-op but still succeeds
    ok, _ = gitsync.sync(v.path)
    assert ok


def test_autosync_pushes(vault, tmp_path):
    v, key = vault
    bare = tmp_path / "origin.git"
    subprocess.run(["git", "init", "-q", "--bare", str(bare)], check=True)
    gitsync.set_remote(v.path, str(bare))
    gitsync.sync(v.path)

    v.set_auto_sync(True)
    v.write(key, "auto/pushed", new_entry("password", {"password": "x"}))

    files = subprocess.run(
        ["git", "-C", str(bare), "ls-tree", "-r", "--name-only", "main"],
        capture_output=True, text=True, check=True,
    ).stdout
    assert "auto/pushed.skr" in files
