"""Choosing sekrt's colors: one editor widget, two places to open it.

`sekrt config` runs it inline — a handful of lines under the shell prompt, like
the entry picker — and the full TUI pushes the same widget as a modal on `t`.

Two ways down, in the order most people want them: a row of ready-made palettes
that ←/→ walks and applies as you land on each one, and three fields for naming
a color yourself. Everything repaints live — swatches, preview, and the
surrounding chrome through :func:`sekrt.tui.theme.apply_palette` — so a palette
is judged in place rather than after a restart.

A half-typed or invalid color is not an error to argue with: the field simply
keeps the last color that parsed, and marks itself until it reads as a color
again.
"""

from __future__ import annotations

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.message import Message
from textual.widgets import Input, Label, Rule, Static

from sekrt.prefs import (
    CLIPBOARD_SECONDS_RANGE,
    DEFAULT_PALETTE,
    DEFAULT_SETTINGS,
    PASSWORD_LENGTH_RANGE,
    PRESET_NAMES,
    PRESETS,
    PRESETS_PER_ROW,
    ROLE_BLURBS,
    ROLES,
    SETTING_BLURBS,
    SETTING_KEYS,
    UNLOCK_MINUTES_RANGE,
    Palette,
    PrefsError,
    Settings,
    check_setting,
    load_settings,
    preset_name,
)
from sekrt.tui.theme import BADGE, WARNING, apply_palette

SWATCH = "███"
# The modal spells `defaults` and `cancel` out on its buttons; the inline panel
# has only the keys, so it says them.
NAV_HINT = "←→ preset · tab/↑↓ fields · enter save"
# ←/→ nudges whichever number field has the cursor, and still walks presets
# when the chip row does.
MODAL_HINT = "←→ preset or value · tab/↑↓ fields · enter save"
KEY_HINT = f"{MODAL_HINT} · ctrl+r defaults · esc cancel"

# Preset rows, the color fields, the three defaults, the rule, the preview, the hint.
PANEL_HEIGHT = (
    -(-len(PRESET_NAMES) // PRESETS_PER_ROW) + len(ROLES) + len(SETTING_KEYS) + 1 + 3 + 1
)

# How far ←/→ moves each default. Length is one character at a time; the other
# two jump, because tapping from 45 seconds to 15, or from 60 minutes to 120,
# should not take a row of keypresses.
_SETTING_STEP = {
    "unlock_minutes": 15,
    "clipboard_seconds": 5,
    "password_length": 1,
}
_SETTING_RANGE = {
    "unlock_minutes": UNLOCK_MINUTES_RANGE,
    "clipboard_seconds": CLIPBOARD_SECONDS_RANGE,
    "password_length": PASSWORD_LENGTH_RANGE,
}
_SETTING_LABEL = {
    "unlock_minutes": "unlock",
    "clipboard_seconds": "clipboard",
    "password_length": "length",
}
BAD = " ✗ "
MASK = "••••••••"

EDITOR_CSS = """
PaletteEditor { height: auto; }
PresetBar { height: auto; }
/* A row of six chips needs ~78 columns; in a narrower terminal it scrolls to
   keep the selected chip in view instead of hiding it off the right edge. */
PresetBar .preset-row { height: 1; overflow-x: auto; scrollbar-size-horizontal: 0; }
/* Six chips plus their label have to fit an 80-column terminal, so the gap
   between them is padding rather than padding + margin. */
PresetBar .preset { width: auto; height: 1; padding: 0 1; color: $foreground; }
PresetBar .preset.-selected { background: $boost; text-style: bold; }
PresetBar:focus .preset.-selected { background: $accent; color: $background; }
PaletteEditor .role { height: 1; }
PaletteEditor .role-name { width: 10; color: $primary; text-style: bold; }
PaletteEditor .role-input {
    width: 14; height: 1; border: none; padding: 0;
    background: $panel; color: $foreground;
}
PaletteEditor .role-input:focus { background: $boost; }
PaletteEditor .role-input.-bad-color { color: $warning; }
PaletteEditor .swatch { width: 5; content-align-horizontal: center; }
PaletteEditor .role-blurb { color: $text-muted; }
PaletteEditor Rule { height: 1; margin: 0; color: $text-muted; }
PaletteEditor #preview { height: 3; }
"""


class PresetBar(Vertical):
    """The ready-made palettes: ←/→ walks them, and each one lands at once.

    The bar takes the focus first, so the quickest way through the panel is to
    arrow until something looks right and press enter — the three color fields
    below are there for when you want to tune what a preset got close to.

    Chips wrap onto as many rows as it takes; ←/→ walks the whole set in order,
    crossing from the end of one row to the start of the next.
    """

    can_focus = True

    BINDINGS = [
        Binding("left", "step(-1)", "previous preset", show=False),
        Binding("right", "step(1)", "next preset", show=False),
    ]

    class Selected(Message):
        def __init__(self, palette: Palette) -> None:
            super().__init__()
            self.palette = palette

    def __init__(self, selected: str | None, **kwargs) -> None:
        super().__init__(**kwargs)
        self.selected = selected

    def compose(self) -> ComposeResult:
        for start in range(0, len(PRESET_NAMES), PRESETS_PER_ROW):
            row = PRESET_NAMES[start : start + PRESETS_PER_ROW]
            with Horizontal(classes="preset-row"):
                # Only the first row is labelled; the rest indent to line up under it.
                yield Label("preset" if start == 0 else "", classes="role-name")
                for name in row:
                    yield Static(chip_markup(name, PRESETS[name]), id=f"p-{name}",
                                 classes="preset")

    def on_mount(self) -> None:
        self.show(self.selected)

    def show(self, name: str | None) -> None:
        """Mark *name* as the current preset — or nothing, for a hand-tuned palette."""
        self.selected = name
        for known in PRESET_NAMES:
            chip = self.query_one(f"#p-{known}", Static)
            chip.set_class(known == name, "-selected")
            if known == name:
                chip.scroll_visible(animate=False)

    def action_step(self, delta: int) -> None:
        """Move to the next/previous preset, wrapping around, and apply it."""
        if self.selected is None:
            index = 0 if delta > 0 else -1  # tuning something lands you back at either end
        else:
            index = (PRESET_NAMES.index(self.selected) + delta) % len(PRESET_NAMES)
        self._choose(PRESET_NAMES[index])

    def on_click(self, event) -> None:
        widget = getattr(event, "widget", None)
        name = str(getattr(widget, "id", "") or "")
        if name.startswith("p-"):
            self.focus()
            self._choose(name[len("p-") :])

    def _choose(self, name: str) -> None:
        self.show(name)
        self.post_message(self.Selected(PRESETS[name]))


def chip_markup(name: str, palette: Palette) -> str:
    """One preset as three blocks of its own colors, then its name."""
    blocks = "".join(f"[{color}]█[/]" for color in palette.to_dict().values())
    return f"{blocks} {name}"


class NumberField(Input):
    """A whole number. Type it, or ←/→ to step it, staying inside its range."""

    BINDINGS = [
        Binding("left", "nudge(-1)", show=False, priority=True),
        Binding("right", "nudge(1)", show=False, priority=True),
    ]

    def __init__(self, value: int, *, lo: int, hi: int, step: int, **kwargs) -> None:
        super().__init__(value=str(value), type="integer", **kwargs)
        self.lo = lo
        self.hi = hi
        self.step = step

    def action_nudge(self, direction: int) -> None:
        try:
            current = int(self.value)
        except ValueError:
            current = self.lo
        self.value = str(min(self.hi, max(self.lo, current + direction * self.step)))


class PaletteEditor(Vertical):
    """Presets and three color fields over a live preview of what they paint.

    Pass *settings* and three more rows appear under the colors: unlock time,
    clipboard clear, and generated length. Both ``sekrt config`` and the TUI
    screen pass them.
    """

    class Changed(Message):
        """A color was edited; *palette* is the newest valid combination."""

        def __init__(self, palette: Palette) -> None:
            super().__init__()
            self.palette = palette

    def __init__(self, palette: Palette, settings: Settings | None = None, **kwargs) -> None:
        super().__init__(**kwargs)
        self.palette = palette
        self.settings = settings

    def compose(self) -> ComposeResult:
        yield PresetBar(preset_name(self.palette))
        for role in ROLES:
            with Horizontal(classes="role"):
                yield Label(role, classes="role-name")
                yield Input(
                    value=getattr(self.palette, role),
                    id=f"c-{role}",
                    classes="role-input",
                    placeholder="#rrggbb",
                )
                yield Static(id=f"sw-{role}", classes="swatch")
                yield Label(ROLE_BLURBS[role], classes="role-blurb")
        if self.settings is not None:
            for key in SETTING_KEYS:
                lo, hi = _SETTING_RANGE[key]
                with Horizontal(classes="role"):
                    yield Label(_SETTING_LABEL[key], classes="role-name")
                    yield NumberField(
                        getattr(self.settings, key),
                        lo=lo,
                        hi=hi,
                        step=_SETTING_STEP[key],
                        id=f"s-{key}",
                        classes="role-input",
                    )
                    yield Static("", classes="swatch")
                    yield Label(SETTING_BLURBS[key], classes="role-blurb")
        yield Rule(line_style="solid")
        yield Static(id="preview")

    def on_mount(self) -> None:
        self._redraw()
        self.query_one(PresetBar).focus()

    # -- editing -------------------------------------------------------------

    def on_preset_bar_selected(self, event: PresetBar.Selected) -> None:
        event.stop()
        self.set_palette(event.palette, mark_preset=False)  # the bar marked itself

    def on_input_changed(self, event: Input.Changed) -> None:
        field_id = str(event.input.id or "")
        if field_id.startswith("s-"):
            self._on_setting_changed(event, field_id[len("s-") :])
            return
        role = field_id[len("c-") :]
        if role not in ROLES:
            return
        event.stop()
        try:
            self.palette = self.palette.with_color(role, event.value)
        except PrefsError:
            event.input.add_class("-bad-color")
            self.query_one(f"#sw-{role}", Static).update(f"[{WARNING}]{BAD}[/]")
            return
        event.input.remove_class("-bad-color")
        # Typing a color by hand can land exactly on a preset, or off all of them.
        self.query_one(PresetBar).show(preset_name(self.palette))
        self._redraw()
        self.post_message(self.Changed(self.palette))

    def set_palette(self, palette: Palette, *, mark_preset: bool = True) -> None:
        """Load *palette* into the fields (a preset, or `restore defaults`)."""
        self.palette = palette
        for role in ROLES:
            field = self.query_one(f"#c-{role}", Input)
            with field.prevent(Input.Changed):
                field.value = getattr(palette, role)
            field.remove_class("-bad-color")
        if mark_preset:
            self.query_one(PresetBar).show(preset_name(palette))
        self._redraw()
        self.post_message(self.Changed(palette))

    def set_settings(self, settings: Settings) -> None:
        """Load *settings* into the number fields. No-op when this editor has none."""
        if self.settings is None:
            return
        self.settings = settings
        for key in SETTING_KEYS:
            field = self.query_one(f"#s-{key}", Input)
            with field.prevent(Input.Changed):
                field.value = str(getattr(settings, key))
            field.remove_class("-bad-color")

    def _on_setting_changed(self, event: Input.Changed, key: str) -> None:
        """Keep the last in-range number. A half-typed or wild one marks the field."""
        event.stop()
        if self.settings is None or key not in SETTING_KEYS:
            return
        try:
            checked = check_setting(key, int(event.value))
        except (ValueError, PrefsError):
            event.input.add_class("-bad-color")
            return
        event.input.remove_class("-bad-color")
        self.settings = Settings(**{**self.settings.to_dict(), key: checked})

    def _redraw(self) -> None:
        for role in ROLES:
            color = getattr(self.palette, role)
            self.query_one(f"#sw-{role}", Static).update(f"[{color}]{SWATCH}[/]")
        self.query_one("#preview", Static).update(preview_markup(self.palette))


def preview_markup(p: Palette) -> str:
    """A miniature of the real thing: a title, an entry row, the key hints.

    The badge stays an emoji, uncolored, because that is what the TUI shows: a
    Tree label paints itself and would ignore a color asked for here, so
    coloring it in the preview would promise something the app can't keep.
    """
    sep = f"[{p.secondary}]·[/]"
    keys = f" {sep} ".join(
        f"[b {p.accent}]{key}[/] [{p.primary}]{what}[/]"
        for key, what in (("c", "copy"), ("r", "reveal"), ("/", "filter"), ("s", "sync"))
    )
    return "\n".join(
        [
            f"{BADGE} [b {p.primary}]sekrt[/] "
            f"[{p.secondary}]— your secrets, encrypted & synced[/]",
            f"[{p.accent}]❯[/] 🔐 [{p.primary}]work/github[/]"
            f"   [b {p.accent}]password[/][{p.secondary}]:[/] {MASK}",
            keys,
        ]
    )


class ColorsApp(App[tuple[Palette, Settings]]):
    """`sekrt config`: the editor on its own, inline under the shell prompt."""

    CSS = (
        EDITOR_CSS
        + f"""
    Screen {{ height: {PANEL_HEIGHT}; background: $surface; padding: 0 1; }}
    #hint {{ color: $text-muted; }}
    """
    )

    BINDINGS = [
        # Not priority: a focused Input's own `enter` binding submits first, and
        # ends up here anyway. This is what saves when the preset row has focus.
        Binding("enter", "save", "save", show=False),
        Binding("escape", "cancel", "cancel", priority=True),
        Binding("ctrl+r", "defaults", "defaults", priority=True),
        Binding("down,ctrl+n", "move(1)", "next", priority=True, show=False),
        Binding("up,ctrl+p", "move(-1)", "previous", priority=True, show=False),
    ]

    def __init__(
        self, palette: Palette | None = None, settings: Settings | None = None
    ) -> None:
        super().__init__()
        self.palette = palette if palette is not None else DEFAULT_PALETTE
        self.settings = settings if settings is not None else load_settings()

    def compose(self) -> ComposeResult:
        yield PaletteEditor(self.palette, self.settings)
        yield Label(KEY_HINT, id="hint")

    def on_mount(self) -> None:
        apply_palette(self, self.palette)

    def on_palette_editor_changed(self, event: PaletteEditor.Changed) -> None:
        self.palette = event.palette
        apply_palette(self, event.palette)

    def on_input_submitted(self) -> None:
        self.action_save()

    def action_save(self) -> None:
        editor = self.query_one(PaletteEditor)
        assert editor.settings is not None
        self.exit((self.palette, editor.settings))

    def action_defaults(self) -> None:
        editor = self.query_one(PaletteEditor)
        editor.set_palette(DEFAULT_PALETTE)
        editor.set_settings(DEFAULT_SETTINGS)

    def action_move(self, delta: int) -> None:
        if delta > 0:
            self.screen.focus_next()
        else:
            self.screen.focus_previous()

    def action_cancel(self) -> None:
        self.exit(None)


def edit_palette(
    palette: Palette, settings: Settings | None = None
) -> tuple[Palette, Settings] | None:
    """Run the inline editor. Returns the palette and defaults, or None if cancelled."""
    return ColorsApp(palette, settings).run(inline=True)


__all__ = [
    "EDITOR_CSS",
    "KEY_HINT",
    "MODAL_HINT",
    "NAV_HINT",
    "NumberField",
    "ColorsApp",
    "PaletteEditor",
    "PresetBar",
    "edit_palette",
    "preview_markup",
]
