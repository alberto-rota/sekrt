"""Cryptographically secure secret generation (stdlib ``secrets`` only)."""

from __future__ import annotations

import secrets
import string

SYMBOLS = "!@#$%^&*()-_=+[]{};:,.<>?~"
DEFAULT_LENGTH = 20


def generate_password(
    length: int = DEFAULT_LENGTH,
    *,
    symbols: bool = True,
    digits: bool = True,
    upper: bool = True,
    lower: bool = True,
) -> str:
    """Generate a random password with at least one char of each enabled class."""
    classes: list[str] = []
    if lower:
        classes.append(string.ascii_lowercase)
    if upper:
        classes.append(string.ascii_uppercase)
    if digits:
        classes.append(string.digits)
    if symbols:
        classes.append(SYMBOLS)
    if not classes:
        raise ValueError("at least one character class must be enabled")
    if length < len(classes):
        raise ValueError(f"length must be >= {len(classes)} for the enabled classes")

    alphabet = "".join(classes)
    while True:
        password = "".join(secrets.choice(alphabet) for _ in range(length))
        if all(any(c in cls for c in password) for cls in classes):
            return password


def generate_token(nbytes: int = 32) -> str:
    """URL-safe token, handy for API keys and webhook secrets."""
    return secrets.token_urlsafe(nbytes)
