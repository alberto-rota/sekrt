"""Look-and-feel preferences: the colors sekrt draws itself in.

These are settings, not secrets, and they describe *this machine's* terminal —
so they live in the XDG config dir (``~/.config/sekrt/config.json``) rather than
in the vault. The vault is a git repo pushed to a remote: putting a color there
would make every tweak a commit, and force the same palette on every machine
that clones it.

Nothing here imports the TUI, so the CLI can read and write the palette without
paying for a Textual import. A file that has been hand-edited into nonsense is
never fatal: :func:`load_palette` falls back to the default color per field, so
a typo costs you a color rather than the ability to open your vault.
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


def load_palette() -> Palette:
    """The stored palette, falling back to the default color for anything unusable."""
    path = prefs_path()
    try:
        stored = json.loads(path.read_text())["colors"]
    except (OSError, ValueError, KeyError, TypeError):
        return DEFAULT_PALETTE
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
    """Write *palette* to the config file (creating the directory). Returns the path."""
    path = prefs_path()
    try:
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        payload = {"version": PREFS_VERSION, "colors": palette.to_dict()}
        path.write_text(json.dumps(payload, indent=2) + "\n")
    except OSError as exc:
        raise PrefsError(f"cannot write {path}: {exc}") from exc
    return path


def reset_palette() -> Path:
    """Forget the stored palette, going back to the stock colors."""
    path = prefs_path()
    try:
        path.unlink(missing_ok=True)
    except OSError as exc:
        raise PrefsError(f"cannot remove {path}: {exc}") from exc
    return path
