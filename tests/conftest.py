import shutil
import subprocess

import pytest
from click.testing import CliRunner

from sekrt.vault import Vault

PASSPHRASE = "correct horse battery staple"

requires_git = pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")


@pytest.fixture(autouse=True)
def fast_kdf(monkeypatch):
    """Keep scrypt cheap in tests (still a power of two >= 1024)."""
    monkeypatch.setenv("SEKRT_SCRYPT_N", "2048")


@pytest.fixture(autouse=True)
def isolated_session(tmp_path, monkeypatch):
    """Never touch the user's real session cache or clipboard."""
    runtime = tmp_path / "runtime"
    runtime.mkdir(mode=0o700)
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(runtime))
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    monkeypatch.delenv("DISPLAY", raising=False)


@pytest.fixture
def vault_dir(tmp_path, monkeypatch):
    d = tmp_path / "vault"
    monkeypatch.setenv("SEKRT_VAULT", str(d))
    monkeypatch.setenv("SEKRT_PASSPHRASE", PASSPHRASE)
    return d


@pytest.fixture
def vault(vault_dir):
    v = Vault(vault_dir)
    key = v.create(PASSPHRASE)
    return v, key


@pytest.fixture
def runner():
    return CliRunner()


def make_pushed_vault(tmp_path, entries=()):
    """A bare 'remote' plus a vault that has pushed *entries* to it.

    Stands in for "the other machine" in sync/clone tests. Returns
    ``(bare_url, vault, key)``.
    """
    from sekrt import gitsync
    from sekrt.vault import Vault, new_entry

    bare = tmp_path / "origin.git"
    subprocess.run(["git", "init", "-q", "--bare", str(bare)], check=True)
    v = Vault(tmp_path / "machine1")
    key = v.create(PASSPHRASE)
    gitsync.set_remote(v.path, str(bare))
    for name, secret in entries:
        v.write(key, name, new_entry("password", {"password": secret}))
    ok, msg = gitsync.sync(v.path)
    assert ok, msg
    return str(bare), v, key


def make_git_repo(path, origin=None):
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q", str(path)], check=True)
    if origin:
        subprocess.run(["git", "-C", str(path), "remote", "add", "origin", origin], check=True)
    return path
