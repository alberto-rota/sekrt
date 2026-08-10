import hashlib

import pytest

from sekrt import filetools


def test_store_and_restore_binary_roundtrip(vault, tmp_path):
    v, key = vault
    content = bytes(range(256)) * 4  # arbitrary binary payload
    src = tmp_path / "blob.bin"
    src.write_bytes(content)

    entry_id = filetools.store(v, key, "backups/blob", src)
    assert entry_id == "file/backups/blob"

    dest = filetools.restore(v, key, "backups/blob", out=tmp_path / "out.bin")
    assert dest.read_bytes() == content
    assert dest.stat().st_mode & 0o777 == 0o600


def test_restore_default_filename(vault, tmp_path, monkeypatch):
    v, key = vault
    src = tmp_path / "recovery-codes.txt"
    src.write_text("code-1\ncode-2\ncode-3\n")
    filetools.store(v, key, "codes", src)

    workdir = tmp_path / "elsewhere"
    workdir.mkdir()
    monkeypatch.chdir(workdir)

    dest = filetools.restore(v, key, "codes")
    assert dest.resolve() == workdir / "recovery-codes.txt"
    assert dest.read_text() == "code-1\ncode-2\ncode-3\n"


def test_restore_refuses_overwrite(vault, tmp_path):
    v, key = vault
    src = tmp_path / "a.txt"
    src.write_text("hello")
    filetools.store(v, key, "a", src)

    out = tmp_path / "out.txt"
    filetools.restore(v, key, "a", out=out)
    with pytest.raises(filetools.FileToolError):
        filetools.restore(v, key, "a", out=out)
    filetools.restore(v, key, "a", out=out, force=True)


def test_store_missing_file(vault, tmp_path):
    v, key = vault
    with pytest.raises(filetools.FileToolError):
        filetools.store(v, key, "nope", tmp_path / "does-not-exist")


def test_store_records_digest(vault, tmp_path):
    v, key = vault
    content = b"some file content"
    src = tmp_path / "f.bin"
    src.write_bytes(content)
    filetools.store(v, key, "f", src)

    entry = v.read(key, "file/f")
    assert entry["data"]["sha256"] == hashlib.sha256(content).hexdigest()
    assert entry["data"]["size"] == str(len(content))
