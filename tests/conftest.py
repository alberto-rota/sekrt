import shutil
import subprocess

import pytest
from click.testing import CliRunner

from keyp.vault import Vault

PASSPHRASE = "correct horse battery staple"

requires_git = pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")


@pytest.fixture(autouse=True)
def fast_kdf(monkeypatch):
    """Keep scrypt cheap in tests (still a power of two >= 1024)."""
    monkeypatch.setenv("KEYP_SCRYPT_N", "2048")


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
    monkeypatch.setenv("KEYP_VAULT", str(d))
    monkeypatch.setenv("KEYP_PASSPHRASE", PASSPHRASE)
    return d


@pytest.fixture
def vault(vault_dir):
    v = Vault(vault_dir)
    key = v.create(PASSPHRASE)
    return v, key


@pytest.fixture
def runner():
    return CliRunner()


def make_git_repo(path, origin=None):
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q", str(path)], check=True)
    if origin:
        subprocess.run(["git", "-C", str(path), "remote", "add", "origin", origin], check=True)
    return path
