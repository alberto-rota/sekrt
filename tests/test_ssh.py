import pytest

from tupacs import sshtools


def test_generate_ed25519():
    private, public = sshtools.generate_ed25519("me@laptop")
    assert private.startswith("-----BEGIN OPENSSH PRIVATE KEY-----")
    assert public.startswith("ssh-ed25519 ")
    assert public.rstrip().endswith("me@laptop")


def test_store_and_restore(vault, tmp_path):
    v, key = vault
    private, public = sshtools.generate_ed25519("deploy@ci")
    entry_id = sshtools.store(v, key, "deploy", private=private, public=public, comment="deploy@ci")
    assert entry_id == "ssh/deploy"

    dest = tmp_path / "sshdir"
    written = sshtools.restore(v, key, "deploy", directory=dest)
    priv_file, pub_file = written
    assert priv_file.read_text() == private
    assert pub_file.read_text() == public
    assert priv_file.stat().st_mode & 0o777 == 0o600
    assert pub_file.stat().st_mode & 0o777 == 0o644
    assert dest.stat().st_mode & 0o777 == 0o700


def test_restore_refuses_overwrite(vault, tmp_path):
    v, key = vault
    private, public = sshtools.generate_ed25519("x")
    sshtools.store(v, key, "k", private=private, public=public)
    dest = tmp_path / "sshdir"
    sshtools.restore(v, key, "k", directory=dest)
    with pytest.raises(sshtools.SshError):
        sshtools.restore(v, key, "k", directory=dest)
    sshtools.restore(v, key, "k", directory=dest, force=True)


def test_restore_rejects_path_traversal(vault, tmp_path):
    v, key = vault
    private, public = sshtools.generate_ed25519("x")
    sshtools.store(v, key, "k", private=private, public=public)
    dest = tmp_path / "sshdir"
    for bad in ("../escape", "/etc/cron.d/x", "a/b", ".."):
        with pytest.raises(sshtools.SshError):
            sshtools.restore(v, key, "k", directory=dest, filename=bad)
    assert not (tmp_path / "escape").exists()


def test_load_keypair(vault, tmp_path):
    private, public = sshtools.generate_ed25519("orig@host")
    key_file = tmp_path / "id_ed25519"
    key_file.write_text(private)
    (tmp_path / "id_ed25519.pub").write_text(public)

    loaded_private, loaded_public, comment = sshtools.load_keypair(key_file)
    assert loaded_private == private
    assert loaded_public == public
    assert comment == "orig@host"


def test_load_keypair_rejects_non_key(tmp_path):
    bogus = tmp_path / "notakey"
    bogus.write_text("hello world\n")
    with pytest.raises(sshtools.SshError):
        sshtools.load_keypair(bogus)
