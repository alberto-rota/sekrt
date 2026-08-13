"""A few lines of form under the shell prompt.

``add`` and ``ssh add`` carry the most options of any command here, and typing
six flags to store one password is worse than the thing it replaces. Leave the
NAME out at a terminal — or pass ``-i`` — and this opens instead: labelled
fields, ``tab`` or ``↑``/``↓`` between them, ``←``/``→`` for the fields that are
a choice rather than something to type, ``ctrl+g`` to generate a secret,
``enter`` to save.

Same rules as the entry picker (:mod:`sekrt.tui.picker`): it draws on stderr,
it claims only as many lines as it has fields, and where there is no terminal
there is nothing to draw — so the CLI keeps insisting on arguments in pipes,
cron and CI.
"""

from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field as dataclass_field

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal
from textual.widgets import Input, Label, Static

from sekrt.prefs import Palette, load_palette
from sekrt.tui.theme import apply_palette

MARKER = "❯"  # the same cursor the picker uses, on the chosen option


@dataclass(frozen=True)
class Field:
    """One row of the form.

    A field with *choices* is walked with ``←``/``→`` instead of typed into; one
    with *generate* is what ``ctrl+g`` fills with a fresh secret.
    """

    key: str
    label: str
    placeholder: str = ""
    value: str = ""
    secret: bool = False
    required: bool = False
    generate: bool = False
    choices: tuple[str, ...] = dataclass_field(default_factory=tuple)


class Choice(Static):
    """A row of mutually exclusive options; ``←``/``→`` (or space) walks them."""

    can_focus = True

    BINDINGS = [
        Binding("left", "step(-1)", "previous", show=False),
        Binding("right,space", "step(1)", "next", show=False),
    ]

    def __init__(self, options: tuple[str, ...], value: str, palette: Palette, **kwargs) -> None:
        super().__init__(**kwargs)
        self.options = options
        self.palette = palette
        self.index = options.index(value) if value in options else 0

    @property
    def value(self) -> str:
        return self.options[self.index]

    def on_mount(self) -> None:
        self._redraw()

    def action_step(self, delta: int) -> None:
        self.index = (self.index + delta) % len(self.options)
        self._redraw()

    def _redraw(self) -> None:
        p = self.palette
        # Every option carries a two-column prefix, chosen or not, so walking the
        # row moves the cursor instead of shuffling the labels sideways.
        parts = [
            f"[b {p.accent}]{MARKER} {option.replace('_', ' ')}[/]"
            if index == self.index
            else f"[{p.secondary}]  {option.replace('_', ' ')}[/]"
            for index, option in enumerate(self.options)
        ]
        self.update("  ".join(parts))


class FormApp(App[dict]):
    """The fields, inline; exits with ``{key: value}`` or None when cancelled."""

    CSS = """
    Screen { background: $surface; }

    #form-title { height: 1; padding: 0 1; color: $primary; text-style: bold; }
    .field { height: 1; }
    .field-label { width: 12; padding: 0 0 0 1; color: $primary; }
    .field-input {
        width: 1fr; height: 1; border: none; padding: 0;
        background: $surface; color: $foreground;
    }
    .field-input:focus { background: $panel; }
    /* A field that has to be filled in says so by wearing the warning color,
       rather than by an error line stealing one of the few rows we have. */
    .field-input.-missing { color: $warning; }
    Choice { width: 1fr; height: 1; color: $foreground; }
    Choice:focus { background: $panel; }
    #form-hint { height: 1; padding: 0 1; color: $text-muted; }
    """

    BINDINGS = [
        # Not priority: a focused Input's own `enter` submits first and arrives
        # here anyway. This is what saves from a choice row.
        Binding("enter", "save", "save", show=False),
        Binding("escape", "cancel", "cancel", priority=True),
        Binding("ctrl+g", "generate", "generate", priority=True),
        Binding("down,ctrl+n", "move(1)", "next field", priority=True, show=False),
        Binding("up,ctrl+p", "move(-1)", "previous field", priority=True, show=False),
    ]

    def __init__(self, fields: list[Field], *, title: str = "", action: str = "save") -> None:
        super().__init__()
        self.fields = fields
        self.form_title = title
        self.action_label = action
        self.palette = load_palette()  # the user's colors (`sekrt config`)

    def compose(self) -> ComposeResult:
        if self.form_title:
            yield Label(self.form_title, id="form-title")
        for spec in self.fields:
            with Horizontal(classes="field"):
                yield Label(spec.label, classes="field-label")
                if spec.choices:
                    yield Choice(spec.choices, spec.value, self.palette, id=f"f-{spec.key}")
                else:
                    yield Input(
                        value=spec.value,
                        placeholder=spec.placeholder,
                        password=spec.secret,
                        id=f"f-{spec.key}",
                        classes="field-input",
                    )
        yield Label(self.hint(), id="form-hint")

    def hint(self) -> str:
        """The keys that actually do something on *this* form."""
        keys = ["tab/↑↓ fields"]
        if any(spec.choices for spec in self.fields):
            keys.append("←→ choose")
        if any(spec.generate for spec in self.fields):
            keys.append("ctrl+g generate")
        keys += [f"enter {self.action_label}", "esc cancel"]
        return " · ".join(keys)

    def on_mount(self) -> None:
        apply_palette(self, self.palette)
        # Claim the rows the form has content for, and no scrollback beyond them.
        self.screen.styles.height = len(self.fields) + 1 + bool(self.form_title)
        self._widget(self.fields[0].key).focus()

    def _widget(self, key: str):
        return self.query_one(f"#f-{key}")

    @property
    def values(self) -> dict[str, str]:
        """What the fields hold. A secret is taken verbatim — its spaces may be real."""
        filled = {}
        for spec in self.fields:
            value = self._widget(spec.key).value
            filled[spec.key] = value if spec.secret else value.strip()
        return filled

    def on_input_changed(self, event: Input.Changed) -> None:
        event.input.remove_class("-missing")

    def on_input_submitted(self) -> None:
        self.action_save()

    def action_save(self) -> None:
        values = self.values
        for spec in self.fields:
            if spec.required and not values[spec.key]:
                widget = self._widget(spec.key)
                widget.add_class("-missing")
                widget.focus()
                self.query_one("#form-hint", Label).update(
                    f"{spec.label} is required · esc cancel"
                )
                return
        self.exit(values)

    def action_generate(self) -> None:
        spec = next((spec for spec in self.fields if spec.generate), None)
        if spec is None:
            return
        from sekrt.generate import generate_password

        widget = self._widget(spec.key)
        widget.value = generate_password()
        widget.focus()

    def action_move(self, delta: int) -> None:
        if delta > 0:
            self.screen.focus_next()
        else:
            self.screen.focus_previous()

    def action_cancel(self) -> None:
        self.exit(None)


def fill(fields: list[Field], *, title: str = "", action: str = "save") -> dict | None:
    """Run the form inline; returns the filled values, or None if cancelled."""
    return FormApp(fields, title=title, action=action).run(inline=True)
