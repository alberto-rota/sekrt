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
    DEFAULT_PALETTE,
    PRESET_NAMES,
    PRESETS,
    PRESETS_PER_ROW,
    ROLE_BLURBS,
    ROLES,
    Palette,
    PrefsError,
    preset_name,
)
from sekrt.tui.theme import BADGE, WARNING, apply_palette

SWATCH = "███"
# The modal spells `defaults` and `cancel` out on its buttons; the inline panel
# has only the keys, so it says them.
NAV_HINT = "←→ preset · tab/↑↓ fields · enter save"
KEY_HINT = f"{NAV_HINT} · ctrl+r defaults · esc cancel"
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


class PaletteEditor(Vertical):
    """Presets and three color fields over a live preview of what they paint."""

    class Changed(Message):
        """A color was edited; *palette* is the newest valid combination."""

        def __init__(self, palette: Palette) -> None:
            super().__init__()
            self.palette = palette

    def __init__(self, palette: Palette, **kwargs) -> None:
        super().__init__(**kwargs)
        self.palette = palette

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
        role = str(event.input.id)[len("c-") :]
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


class ColorsApp(App[Palette]):
    """`sekrt config`: the editor on its own, inline under the shell prompt."""

    CSS = (
        EDITOR_CSS
        + """
    Screen { height: 10; background: $surface; padding: 0 1; }
    #hint { color: $text-muted; }
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

    def __init__(self, palette: Palette | None = None) -> None:
        super().__init__()
        self.palette = palette if palette is not None else DEFAULT_PALETTE

    def compose(self) -> ComposeResult:
        yield PaletteEditor(self.palette)
        yield Label(KEY_HINT, id="hint")

    def on_mount(self) -> None:
        apply_palette(self, self.palette)

    def on_palette_editor_changed(self, event: PaletteEditor.Changed) -> None:
        self.palette = event.palette
        apply_palette(self, event.palette)

    def on_input_submitted(self) -> None:
        self.action_save()

    def action_save(self) -> None:
        self.exit(self.palette)

    def action_defaults(self) -> None:
        self.query_one(PaletteEditor).set_palette(DEFAULT_PALETTE)

    def action_move(self, delta: int) -> None:
        if delta > 0:
            self.screen.focus_next()
        else:
            self.screen.focus_previous()

    def action_cancel(self) -> None:
        self.exit(None)


def edit_palette(palette: Palette) -> Palette | None:
    """Run the inline color editor; returns the chosen palette, or None if cancelled."""
    return ColorsApp(palette).run(inline=True)


__all__ = [
    "EDITOR_CSS",
    "KEY_HINT",
    "NAV_HINT",
    "ColorsApp",
    "PaletteEditor",
    "PresetBar",
    "edit_palette",
    "preview_markup",
]
