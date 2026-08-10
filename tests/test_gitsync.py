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


def test_remote_has_commits(vault, tmp_path):
    v, key = vault
    bare = tmp_path / "origin.git"
    subprocess.run(["git", "init", "-q", "--bare", str(bare)], check=True)

    assert gitsync.remote_has_commits(str(bare)) is False
    gitsync.set_remote(v.path, str(bare))
    gitsync.sync(v.path)
    assert gitsync.remote_has_commits(str(bare)) is True


def test_remote_has_commits_unreachable():
    assert gitsync.remote_has_commits("/nonexistent/nope.git") is None


def test_clone_reproduces_the_vault(vault, tmp_path):
    v, key = vault
    bare = tmp_path / "origin.git"
    subprocess.run(["git", "init", "-q", "--bare", str(bare)], check=True)
    gitsync.set_remote(v.path, str(bare))
    v.write(key, "shared/entry", new_entry("password", {"password": "x"}))
    assert gitsync.sync(v.path)[0]

    dest = tmp_path / "machine2"
    ok, msg = gitsync.clone(str(bare), dest)
    assert ok, msg
    assert (dest / ".sekrt.json").is_file()

    # Same salt, so the original key still decrypts — the whole point of cloning.
    from sekrt.vault import Vault
    cloned = Vault(dest)
    assert cloned.verify_key(key)
    assert cloned.read(key, "shared/entry")["data"]["password"] == "x"
    assert oct(dest.stat().st_mode)[-3:] == "700"


def test_clone_refuses_nonempty_destination(tmp_path):
    dest = tmp_path / "occupied"
    dest.mkdir()
    (dest / "something").write_text("x")
    ok, msg = gitsync.clone("/nonexistent.git", dest)
    assert not ok
    assert "not empty" in msg


def test_unrelated_history_is_detected(vault, tmp_path, monkeypatch):
    """Two independent `init`s against one remote: the bug this all exists for."""
    v, key = vault
    bare = tmp_path / "origin.git"
    subprocess.run(["git", "init", "-q", "--bare", str(bare)], check=True)
    gitsync.set_remote(v.path, str(bare))
    v.write(key, "from/machine1", new_entry("password", {"password": "x"}))
    assert gitsync.sync(v.path)[0]

    # A second machine that ran `init` instead of `clone`.
    from sekrt.vault import Vault
    other = Vault(tmp_path / "machine2")
    other.create("a different passphrase entirely")
    gitsync.set_remote(other.path, str(bare))

    assert gitsync.has_unrelated_history(other.path, "main")
    ok, msg = gitsync.sync(other.path)
    assert not ok
    assert "initialised separately" in msg
    assert "sekrt clone" in msg
    # and it must not leave a rebase half-applied
    assert not (other.path / ".git" / "rebase-merge").exists()
