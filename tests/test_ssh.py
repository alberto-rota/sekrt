import pytest

from sekrt import sshtools
from sekrt.vault import new_entry


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
    assert not (dest / "authorized_keys").exists()


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


def test_load_keypair_derives_public_without_pub_file(tmp_path):
    private, public = sshtools.generate_ed25519("orig@host")
    key_file = tmp_path / "id_ed25519"
    key_file.write_text(private)

    loaded_private, loaded_public, comment = sshtools.load_keypair(key_file)
    assert loaded_private == private
    assert comment == ""
    assert loaded_public is not None
    assert loaded_public.split()[:2] == public.split()[:2]


def test_restore_derives_public_when_entry_has_only_private(vault, tmp_path):
    v, key = vault
    private, public = sshtools.generate_ed25519("me@laptop")
    v.write(
        key,
        "ssh/k",
        new_entry("ssh", {"private": private, "comment": "me@laptop", "filename": "k"}),
    )
    dest = tmp_path / "sshdir"
    written = sshtools.restore(v, key, "k", directory=dest)
    assert [p.name for p in written] == ["k", "k.pub"]
    assert written[1].read_text() == public
    assert written[1].stat().st_mode & 0o777 == 0o644


def test_load_keypair_rejects_non_key(tmp_path):
    bogus = tmp_path / "notakey"
    bogus.write_text("hello world\n")
    with pytest.raises(sshtools.SshError):
        sshtools.load_keypair(bogus)


def test_authorize_appends_public_key(vault, tmp_path):
    v, key = vault
    private, public = sshtools.generate_ed25519("me@laptop")
    sshtools.store(v, key, "laptop", private=private, public=public, comment="me@laptop")
    dest = tmp_path / "sshdir"
    path, added = sshtools.authorize(v, key, "laptop", directory=dest)
    assert added
    assert path == dest / "authorized_keys"
    assert path.read_text() == public
    assert path.stat().st_mode & 0o777 == 0o600
    assert dest.stat().st_mode & 0o777 == 0o700
    assert not (dest / "laptop").exists()


def test_authorize_is_idempotent_on_key_blob(vault, tmp_path):
    v, key = vault
    private, public = sshtools.generate_ed25519("me@laptop")
    sshtools.store(v, key, "laptop", private=private, public=public)
    dest = tmp_path / "sshdir"
    dest.mkdir()
    other = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIotherkey comment\n"
    blob = public.split()[1]
    (dest / "authorized_keys").write_text(other + f"ssh-ed25519 {blob} old-comment\n")

    path, added = sshtools.authorize(v, key, "laptop", directory=dest)
    assert not added
    text = path.read_text()
    assert other in text
    assert text.count(blob) == 1


def test_restore_authorize_writes_authorized_keys(vault, tmp_path):
    v, key = vault
    private, public = sshtools.generate_ed25519("me@laptop")
    sshtools.store(v, key, "laptop", private=private, public=public)
    dest = tmp_path / "sshdir"
    written = sshtools.restore(v, key, "laptop", directory=dest, authorize=True)
    assert [p.name for p in written] == ["laptop", "laptop.pub", "authorized_keys"]
    assert written[2].read_text().strip() == public.strip()
    assert written[2].stat().st_mode & 0o777 == 0o600
