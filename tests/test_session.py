import json
import subprocess
import sys

from tupacs import session


def test_store_load_clear(tmp_path):
    vault_path = tmp_path / "vault"
    assert session.store_key(vault_path, b"k" * 32, ttl=60)
    assert session.load_key(vault_path) == b"k" * 32
    assert session.remaining(vault_path) > 0
    session.clear(vault_path)
    assert session.load_key(vault_path) is None


def test_expired_key_not_returned(tmp_path):
    vault_path = tmp_path / "vault"
    session.store_key(vault_path, b"k" * 32, ttl=-1)
    assert session.load_key(vault_path) is None
    assert not session._session_file(vault_path).is_file()  # deleted on read


def test_reaper_deletes_expired_file(tmp_path):
    f = tmp_path / "x.session"
    f.write_text(json.dumps({"key": "aaaa", "expires": 0}))
    subprocess.run([sys.executable, "-c", session._REAPER_SRC, str(f), "0"], timeout=30)
    assert not f.exists()


def test_reaper_keeps_valid_file(tmp_path):
    f = tmp_path / "x.session"
    f.write_text(json.dumps({"key": "aaaa", "expires": 2**60}))
    subprocess.run([sys.executable, "-c", session._REAPER_SRC, str(f), "0"], timeout=30)
    assert f.exists()


def test_private_tmpdir_rejects_planted_symlink(tmp_path):
    """A symlink squatted at the expected path must not be used or chmod'd."""
    runtime = tmp_path / "runtime"  # created by the isolated_session fixture
    victim = tmp_path / "elsewhere"
    victim.mkdir(mode=0o755)
    uid = getattr(session.os, "getuid", lambda: "u")()
    (runtime / f"tupacs-{uid}").symlink_to(victim)

    d = session.private_tmpdir()
    assert d is None or not str(d).startswith(str(runtime))
    assert victim.stat().st_mode & 0o777 == 0o755  # untouched
