"""Machine preferences: the colors sekrt draws itself in, and the defaults the
commands use when a flag is left off.

These are settings, not secrets, and they describe *this machine* — so they
live in the XDG config dir (``~/.config/sekrt/config.json``) rather than in the
vault. The vault is a git repo pushed to a remote: putting a color or a timeout
there would make every tweak a commit, and force the same choice on every
machine that clones it.

Nothing here imports the TUI, so the CLI can read and write the file without
paying for a Textual import. A file that has been hand-edited into nonsense is
never fatal: :func:`load_palette` and :func:`load_settings` fall back to the
default per field, so a typo costs you that one value rather than the ability
to open your vault.
"""

from __future__ import annotations

import contextlib
import json
import os
import re
from dataclasses import dataclass, fields, replace
from pathlib import Path

from sekrt import compat

PREFS_NAME = "config.json"
PREFS_VERSION = 1

# Stock command defaults — the same numbers the commands used before these were
# configurable (`session.DEFAULT_TTL` is 60 minutes, `clipboard.DEFAULT_CLEAR_AFTER`
# is 45 seconds, `generate.DEFAULT_LENGTH` is 20). A saved value replaces the
# stock one; a flag on the command still wins for that one run.
DEFAULT_UNLOCK_MINUTES = 60
DEFAULT_CLIPBOARD_SECONDS = 45
DEFAULT_PASSWORD_LENGTH = 20

# What `sekrt config` will accept. Outside this, a hand-edited value is ignored
# and the stock default is used — same rule as a color that does not parse.
UNLOCK_MINUTES_RANGE = (1, 7 * 24 * 60)  # 1 minute .. 7 days
CLIPBOARD_SECONDS_RANGE = (1, 10 * 60)  # 1 second .. 10 minutes
PASSWORD_LENGTH_RANGE = (4, 128)  # generate_password needs one char per class

SETTING_KEYS = ("unlock_minutes", "clipboard_seconds", "password_length")

# The stock look: brushed metal with a red accent.
DEFAULT_PRIMARY = "#aaaaaa"
DEFAULT_SECONDARY = "#6e737a"
DEFAULT_ACCENT = "#ff0000"

_BARE_HEX = re.compile(r"^[0-9a-fA-F]{3}(?:[0-9a-fA-F]{3})?$")


class PrefsError(Exception):
    pass


@dataclass(frozen=True)
class Palette:
    """The three colors the user gets to choose.

    ``primary`` draws the structure (borders, titles, entry names),
    ``secondary`` the quiet text (hints, muted labels), and ``accent`` the
    things that must catch the eye (the cursor, key hints, the reveal).
    Backgrounds stay fixed: they are what makes the accent readable.
    """

    primary: str = DEFAULT_PRIMARY
    secondary: str = DEFAULT_SECONDARY
    accent: str = DEFAULT_ACCENT

    def with_color(self, role: str, value: str) -> Palette:
        """This palette with *role* set to *value* (parsed and normalized)."""
        if role not in ROLES:
            raise PrefsError(f"unknown color role {role!r} — expected one of {', '.join(ROLES)}")
        return replace(self, **{role: parse_color(value)})

    def to_dict(self) -> dict[str, str]:
        return {role: getattr(self, role) for role in ROLES}


ROLES: tuple[str, ...] = tuple(f.name for f in fields(Palette))
DEFAULT_PALETTE = Palette()

# Ready-made palettes, so nobody has to invent three colors that work together
# to change the one they don't like. Each is a light structural color, a muted
# version of it, and an accent that carries on the near-black background;
# `metal` is the stock look. One per hue — a set where two entries are hard to
# tell apart is a set that wastes a keypress. Order is the order they appear in
# the panel, and names stay short enough for a row of chips to fit 80 columns.
PRESETS: dict[str, Palette] = {
    "metal": DEFAULT_PALETTE,
    "teal": Palette(primary="#9db8b1", secondary="#5f7370", accent="#00d7af"),
    "amber": Palette(primary="#c3b393", secondary="#7d7259", accent="#ffaf00"),
    "indigo": Palette(primary="#a6b0d6", secondary="#6a7290", accent="#6c8cff"),
    "magenta": Palette(primary="#c0a8bd", secondary="#7c6a78", accent="#ff5fd7"),
    "mono": Palette(primary="#cfcfcf", secondary="#808080", accent="#ffffff"),
    "matrix": Palette(primary="#8fbf8f", secondary="#5f8a5f", accent="#00ff5f"),
    "ice": Palette(primary="#b0c4d0", secondary="#67788a", accent="#5fd7ff"),
    "violet": Palette(primary="#bcaedb", secondary="#756d90", accent="#af87ff"),
    "rose": Palette(primary="#cdb2b8", secondary="#7f696f", accent="#ff6f8f"),
    "sepia": Palette(primary="#d0bfa8", secondary="#8a7862", accent="#d7875f"),
}
PRESET_NAMES: tuple[str, ...] = tuple(PRESETS)

# Chips per row, in the panel and in `sekrt config --show`: six of these names
# plus their swatches are as much as an 80-column terminal holds.
PRESETS_PER_ROW = 6


def preset(name: str) -> Palette:
    """The named preset palette. Raises PrefsError for a name that isn't one."""
    try:
        return PRESETS[name.strip().lower()]
    except KeyError:
        raise PrefsError(
            f"no preset named {name!r} — pick one of: {', '.join(PRESET_NAMES)}"
        ) from None


def preset_name(palette: Palette) -> str | None:
    """The name of the preset *palette* is, or None once it has been hand-tuned."""
    return next((name for name, known in PRESETS.items() if known == palette), None)


# What each color paints, for `sekrt config` to label its fields with.
ROLE_BLURBS = {
    "primary": "borders, titles, entry names",
    "secondary": "hints and muted text",
    "accent": "cursor, key hints, highlights",
}


@dataclass(frozen=True)
class Settings:
    """The three defaults that are not colors.

    ``unlock_minutes`` is how long ``sekrt unlock`` caches the key,
    ``clipboard_seconds`` is how long a copied secret stays, and
    ``password_length`` is what ``sekrt generate``, ``sekrt add -g`` and the
    TUI's generator use when no length is given.
    """

    unlock_minutes: int = DEFAULT_UNLOCK_MINUTES
    clipboard_seconds: int = DEFAULT_CLIPBOARD_SECONDS
    password_length: int = DEFAULT_PASSWORD_LENGTH

    def to_dict(self) -> dict[str, int]:
        return {key: getattr(self, key) for key in SETTING_KEYS}


DEFAULT_SETTINGS = Settings()

_SETTING_RANGES = {
    "unlock_minutes": UNLOCK_MINUTES_RANGE,
    "clipboard_seconds": CLIPBOARD_SECONDS_RANGE,
    "password_length": PASSWORD_LENGTH_RANGE,
}

# How `sekrt config --show` labels each one.
SETTING_BLURBS = {
    "unlock_minutes": "how long `sekrt unlock` stays open",
    "clipboard_seconds": "how long a copied secret stays",
    "password_length": "characters in a generated secret",
}


def parse_color(value: str) -> str:
    """Normalize a user-typed color to ``#rrggbb``.

    Accepts what someone is likely to type: ``#ff5f5f``, ``ff5f5f``, ``#f55``,
    ``cyan``, ``CYAN``, ``rgb(255,95,95)``. Any alpha channel is dropped — these
    colors are painted on top of each other, so a translucent border is a bug.
    """
    text = value.strip().lower()  # hex, names and rgb() are all case-insensitive to us
    if _BARE_HEX.match(text):
        text = "#" + text
    try:
        from textual.color import Color, ColorParseError

        color = Color.parse(text)
    except (ColorParseError, ValueError, TypeError) as exc:
        raise PrefsError(
            f"{value!r} is not a color — try a hex value like #ff5f5f or a name like 'cyan'"
        ) from exc
    return f"#{color.r:02x}{color.g:02x}{color.b:02x}"


def prefs_path() -> Path:
    """Where the palette is stored (``$SEKRT_CONFIG`` wins, if set)."""
    if override := compat.env("CONFIG"):
        return Path(override).expanduser()
    config_home = os.environ.get("XDG_CONFIG_HOME") or "~/.config"
    return Path(config_home).expanduser() / "sekrt" / PREFS_NAME


def _read() -> dict:
    """The config file as a dict, or ``{}`` when it is missing or not an object."""
    try:
        stored = json.loads(prefs_path().read_text())
    except (OSError, ValueError):
        return {}
    return stored if isinstance(stored, dict) else {}


def _write(data: dict) -> Path:
    """Write *data*, keeping every key except a rewritten ``version``.

    An empty document is removed, so "nothing saved" stays "no file" rather
    than a file that only says ``version``.
    """
    path = prefs_path()
    body = {key: value for key, value in data.items() if key != "version"}
    if not body:
        try:
            path.unlink(missing_ok=True)
        except OSError as exc:
            raise PrefsError(f"cannot remove {path}: {exc}") from exc
        return path
    try:
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        payload = {"version": PREFS_VERSION, **body}
        path.write_text(json.dumps(payload, indent=2) + "\n")
    except OSError as exc:
        raise PrefsError(f"cannot write {path}: {exc}") from exc
    return path


def load_palette() -> Palette:
    """The stored palette, falling back to the default color for anything unusable."""
    stored = _read().get("colors")
    if not isinstance(stored, dict):
        return DEFAULT_PALETTE

    palette = DEFAULT_PALETTE
    for role in ROLES:
        value = stored.get(role)
        if isinstance(value, str):
            with contextlib.suppress(PrefsError):  # a typo costs that color, nothing else
                palette = palette.with_color(role, value)
    return palette


def save_palette(palette: Palette) -> Path:
    """Write *palette*, leaving unlock, clipboard, length and any other keys."""
    data = _read()
    data["colors"] = palette.to_dict()
    return _write(data)


def reset_palette() -> Path:
    """Forget the stored palette. Other settings in the file stay."""
    data = _read()
    data.pop("colors", None)
    return _write(data)


def _coerce_setting(key: str, value: object) -> int:
    """*value* when it is an in-range int, otherwise the stock default for *key*."""
    default = getattr(DEFAULT_SETTINGS, key)
    lo, hi = _SETTING_RANGES[key]
    if isinstance(value, bool) or not isinstance(value, int) or not lo <= value <= hi:
        return default
    return value


def check_setting(key: str, value: int) -> int:
    """Validate a value the user just asked to save. Raises PrefsError."""
    if key not in _SETTING_RANGES:
        raise PrefsError(f"unknown setting {key!r} — expected one of {', '.join(SETTING_KEYS)}")
    lo, hi = _SETTING_RANGES[key]
    if isinstance(value, bool) or not isinstance(value, int):
        raise PrefsError(f"{key} must be a whole number")
    if not lo <= value <= hi:
        raise PrefsError(f"{key} must be between {lo} and {hi}")
    return value


def load_settings() -> Settings:
    """The stored defaults, falling back per field when a value is unusable."""
    stored = _read()
    return Settings(**{key: _coerce_setting(key, stored.get(key)) for key in SETTING_KEYS})


def save_settings(**updates: int) -> Path:
    """Write the given settings, leaving the palette and any other keys.

    A value equal to the stock default is dropped, so the file only records
    what this machine actually changed. Returns the config path.
    """
    data = _read()
    for key, value in updates.items():
        checked = check_setting(key, value)
        if checked == getattr(DEFAULT_SETTINGS, key):
            data.pop(key, None)
        else:
            data[key] = checked
    return _write(data)
