import pytest

from tupacss import crypto
from tupacss.crypto import DecryptionError, KdfParams


def test_kdf_params_roundtrip():
    params = KdfParams.generate()
    restored = KdfParams.from_dict(params.to_dict())
    assert restored == params


def test_derive_is_deterministic():
    params = KdfParams.generate()
    assert crypto.derive_key("hunter2", params) == crypto.derive_key("hunter2", params)
    assert crypto.derive_key("hunter2", params) != crypto.derive_key("hunter3", params)


def test_encrypt_decrypt_roundtrip():
    key = b"k" * 32
    blob = crypto.encrypt(key, b"attack at dawn", aad=b"work/plan")
    assert blob.startswith(crypto.MAGIC)
    assert crypto.decrypt(key, blob, aad=b"work/plan") == b"attack at dawn"


def test_wrong_key_fails():
    blob = crypto.encrypt(b"k" * 32, b"secret")
    with pytest.raises(DecryptionError):
        crypto.decrypt(b"x" * 32, blob)


def test_wrong_aad_fails():
    key = b"k" * 32
    blob = crypto.encrypt(key, b"secret", aad=b"name-a")
    with pytest.raises(DecryptionError):
        crypto.decrypt(key, blob, aad=b"name-b")


def test_tampered_ciphertext_fails():
    key = b"k" * 32
    blob = bytearray(crypto.encrypt(key, b"secret"))
    blob[-1] ^= 0xFF
    with pytest.raises(DecryptionError):
        crypto.decrypt(key, bytes(blob))


def test_garbage_blob_fails():
    with pytest.raises(DecryptionError):
        crypto.decrypt(b"k" * 32, b"not an entry")


def test_keycheck():
    key = b"k" * 32
    check = crypto.make_keycheck(key)
    assert crypto.verify_keycheck(key, check)
    assert not crypto.verify_keycheck(b"x" * 32, check)
    assert not crypto.verify_keycheck(key, "bm90IHZhbGlk")
