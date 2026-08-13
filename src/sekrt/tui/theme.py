"""The shared look: a brushed-metal palette with a red accent — or your own.

Both the full-screen TUI and the inline picker draw from here, so a secret
looks the same whether it is browsed in `sekrt tui` or picked under the
shell prompt by `sekrt get`.

Three colors come from the user's config (see :mod:`sekrt.prefs`); the
backgrounds do not. A dark, near-black ground is what keeps an arbitrary accent
readable, so it stays fixed and only the ink is customizable.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from textual.theme import Theme

from sekrt.prefs import DEFAULT_PALETTE, Palette

if TYPE_CHECKING:
    from textual.app import App

BADGE = "🔴"
THEME_NAME = "sekrt"

# The fixed ground the three chosen colors are painted on.
BACKGROUND = "#0d0e10"
SURFACE = "#16181b"
PANEL = "#1e2124"
FOREGROUND = "#d7dade"
BORDER_BLURRED = "#3a3e44"
SCROLLBAR = "#2a2e33"
WARNING = "#d9a13b"
SUCCESS = "#8fbf7a"


def build_theme(palette: Palette = DEFAULT_PALETTE) -> Theme:
    """A Textual theme painted in *palette*'s three colors."""
    return Theme(
        name=THEME_NAME,
        primary=palette.primary,
        secondary=palette.secondary,
        accent=palette.accent,
        error=palette.accent,
        warning=WARNING,
        success=SUCCESS,
        foreground=FOREGROUND,
        background=BACKGROUND,
        surface=SURFACE,
        panel=PANEL,
        dark=True,
        variables={
            "border": palette.primary,
            "border-blurred": BORDER_BLURRED,
            "block-cursor-background": palette.accent,
            "block-cursor-foreground": BACKGROUND,
            "block-cursor-text-style": "bold",
            "footer-key-foreground": palette.accent,
            "footer-description-foreground": palette.primary,
            "input-selection-background": f"{palette.accent} 35%",
            "input-cursor-background": palette.accent,
            "input-cursor-foreground": BACKGROUND,
            "scrollbar": SCROLLBAR,
            "scrollbar-hover": palette.secondary,
            "scrollbar-active": palette.primary,
            "text-muted": palette.secondary,
        },
    )


def apply_palette(app: App, palette: Palette) -> None:
    """Register *palette*'s theme on *app* and paint with it, immediately.

    Registering a theme under a name that is already active does not repaint on
    its own — the reactive only fires when the *name* changes — so the theme is
    switched away and straight back. Both assignments land in the same message
    turn, and the refreshes they schedule coalesce: no flicker.
    """
    app.register_theme(build_theme(palette))
    if app.theme == THEME_NAME:
        app.theme = "textual-dark"
    app.theme = THEME_NAME
