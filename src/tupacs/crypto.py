"""Encryption primitives for tupacs.

Every entry is encrypted independently with AES-256-GCM. The 256-bit key is
derived from the vault passphrase with scrypt (parameters stored, per-vault
random salt). Each entry uses its logical name as GCM associated data, so a
ciphertext cannot be silently swapped to a different entry name.

Entry file format: ``b"TUP1" || nonce (12 bytes) || ciphertext+tag``.
"""

from __future__ import annotations

import base64
import os
from dataclasses import dataclass

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

MAGIC = b"TUP1"
KEY_LEN = 32
NONCE_LEN = 12
KEYCHECK_PLAINTEXT = b"tupacs keycheck v1"
KEYCHECK_AAD = b"keycheck"

DEFAULT_SCRYPT_N = 2**15  # ~32 MiB, <100ms on a modern laptop
DEFAULT_SCRYPT_R = 8
DEFAULT_SCRYPT_P = 1

MIN_SCRYPT_N = 2**10
MAX_SCRYPT_R = 64
MAX_SCRYPT_P = 16
MAX_SCRYPT_MEMORY = 2**31  # scrypt needs 128*n*r bytes; cap at 2 GiB


class CryptoError(Exception):
    """Base class for cryptographic failures."""


class DecryptionError(CryptoError):
    """Decryption failed: wrong key, wrong entry name, or tampered data."""


class WrongPassphraseError(CryptoError):
    """The supplied passphrase does not unlock this vault."""


def validate_scrypt_params(n: int, r: int, p: int) -> None:
    """Reject scrypt parameters that are too weak or absurdly expensive.

    The vault config is plaintext and git-synced, so KDF parameters read from
    it are untrusted: a tampered config must not be able to weaken key
    derivation or force a multi-GiB allocation on unlock.
    """
    if n < MIN_SCRYPT_N or n & (n - 1):
        raise CryptoError(f"scrypt n must be a power of two >= {MIN_SCRYPT_N}")
    if not 1 <= r <= MAX_SCRYPT_R:
        raise CryptoError(f"scrypt r must be in 1..{MAX_SCRYPT_R}")
    if not 1 <= p <= MAX_SCRYPT_P:
        raise CryptoError(f"scrypt p must be in 1..{MAX_SCRYPT_P}")
    if 128 * n * r > MAX_SCRYPT_MEMORY:
        raise CryptoError("scrypt parameters require an implausible amount of memory")


@dataclass(frozen=True)
class KdfParams:
    """scrypt parameters, persisted in the vault config."""

    salt: bytes
    n: int = DEFAULT_SCRYPT_N
    r: int = DEFAULT_SCRYPT_R
    p: int = DEFAULT_SCRYPT_P

    @classmethod
    def generate(cls) -> KdfParams:
        n = int(os.environ.get("TUPACS_SCRYPT_N", DEFAULT_SCRYPT_N))
        validate_scrypt_params(n, DEFAULT_SCRYPT_R, DEFAULT_SCRYPT_P)
        return cls(salt=os.urandom(16), n=n)

    def to_dict(self) -> dict:
        return {
            "algo": "scrypt",
            "salt": base64.b64encode(self.salt).decode(),
            "n": self.n,
            "r": self.r,
            "p": self.p,
        }

    @classmethod
    def from_dict(cls, d: dict) -> KdfParams:
        if d.get("algo") != "scrypt":
            raise CryptoError(f"unsupported KDF {d.get('algo')!r}")
        try:
            salt = base64.b64decode(d["salt"])
            n, r, p = int(d["n"]), int(d["r"]), int(d["p"])
        except (KeyError, TypeError, ValueError) as exc:
            raise CryptoError(f"malformed KDF parameters: {exc}") from exc
        validate_scrypt_params(n, r, p)
        return cls(salt=salt, n=n, r=r, p=p)


def derive_key(passphrase: str, params: KdfParams) -> bytes:
    kdf = Scrypt(salt=params.salt, length=KEY_LEN, n=params.n, r=params.r, p=params.p)
    return kdf.derive(passphrase.encode("utf-8"))


def encrypt(key: bytes, plaintext: bytes, aad: bytes = b"") -> bytes:
    nonce = os.urandom(NONCE_LEN)
    ciphertext = AESGCM(key).encrypt(nonce, plaintext, aad or None)
    return MAGIC + nonce + ciphertext


def decrypt(key: bytes, blob: bytes, aad: bytes = b"") -> bytes:
    if not blob.startswith(MAGIC) or len(blob) < len(MAGIC) + NONCE_LEN + 16:
        raise DecryptionError("not a tupacs entry (bad header)")
    nonce = blob[len(MAGIC) : len(MAGIC) + NONCE_LEN]
    ciphertext = blob[len(MAGIC) + NONCE_LEN :]
    try:
        return AESGCM(key).decrypt(nonce, ciphertext, aad or None)
    except InvalidTag as exc:
        raise DecryptionError(
            "decryption failed — wrong passphrase, or the entry was tampered with"
        ) from exc


def make_keycheck(key: bytes) -> str:
    return base64.b64encode(encrypt(key, KEYCHECK_PLAINTEXT, aad=KEYCHECK_AAD)).decode()


def verify_keycheck(key: bytes, keycheck: str) -> bool:
    try:
        return decrypt(key, base64.b64decode(keycheck), aad=KEYCHECK_AAD) == KEYCHECK_PLAINTEXT
    except (CryptoError, ValueError):
        return False
