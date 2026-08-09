"""Bridges from the pre-0.2 name (``tupacs``) to the current one.

The project was published as ``tupacs`` through 0.1.0. Two things follow anyone
who upgrades across the rename: ``TUPACS_*`` variables sitting in shell
profiles and CI configs, and a vault at ``~/.local/share/tupacs`` whose config
file is still named ``.tupacs.json``.

Environment variables are handled transparently — the new name wins, the old
one still works. The vault directory deliberately is *not*: silently reading a
differently-named directory hides where your secrets actually live, and moving
it without being asked is worse. Instead :func:`migration_hint` turns the
otherwise baffling "no vault found" into the two commands that fix it.

This module imports nothing from the package, so it is safe to use from the
lowest layers (``crypto``, ``vault``).
"""

from __future__ import annotations

import os
from pathlib import Path

PREFIX = "SEKRT_"
LEGACY_PREFIX = "TUPACS_"
LEGACY_DIRNAME = "tupacs"
LEGACY_CONFIG_NAME = ".tupacs.json"
LEGACY_ENTRY_SUFFIX = ".tup"


def env(suffix: str) -> str | None:
    """Read ``SEKRT_<suffix>``, falling back to the pre-rename ``TUPACS_<suffix>``.

    Returns the first non-empty value, matching how callers treat these (an
    empty string means "not set"), or None if neither is set.
    """
    for name in (PREFIX + suffix, LEGACY_PREFIX + suffix):
        if value := os.environ.get(name):
            return value
    return None


def legacy_vault_dir() -> Path | None:
    """A pre-rename vault in the default data dir, if one is still there."""
    data_home = os.environ.get("XDG_DATA_HOME") or "~/.local/share"
    legacy = Path(data_home).expanduser() / LEGACY_DIRNAME
    return legacy if (legacy / LEGACY_CONFIG_NAME).is_file() else None


def migration_hint() -> str:
    """Instructions to move a pre-rename vault, or '' if there isn't one."""
    legacy = legacy_vault_dir()
    if legacy is None:
        return ""
    new = legacy.with_name("sekrt")
    return (
        f"\n\nFound a vault from before the rename at {legacy}.\n"
        f"Move it and rename its config file to finish upgrading:\n"
        f"  mv {legacy} {new}\n"
        f"  mv {new / LEGACY_CONFIG_NAME} {new / '.sekrt.json'}\n"
        f"(the vault is a git repo, so commit the rename afterwards if you sync it)"
    )
