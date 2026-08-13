"""An inline entry picker: a few lines of TUI under the shell prompt.

Typing an entry name exactly (``sekrt get cloud/aws-access-key-prod``) is the
tedious part of a name-addressed vault, so commands that take a name open this
instead when the name is missing or unknown: type to fuzzy-filter, arrows to
move, enter to pick.

Textual's driver draws on **stderr**, which is what makes this safe to bolt
onto ``sekrt get``: the picker paints over the terminal while the secret still
goes to stdout alone, so ``sekrt get | pbcopy`` keeps working.
"""

from __future__ import annotations

import sys

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.widgets import Input, Label, OptionList
from textual.widgets.option_list import Option

from sekrt.prefs import load_palette
from sekrt.tui.theme import apply_palette

MAX_ROWS = 8  # visible rows; longer lists scroll
MARKER = "❯"  # the cursor, so the highlight doesn't have to shout to be found

# Entry names are plaintext metadata, so the picker can hint at what a name
# holds without decrypting anything.
ICONS = {"ssh": "🔑", "env": "📄", "file": "📎"}
DEFAULT_ICON = "🔐"


def icon_for(name: str) -> str:
    return ICONS.get(name.split("/")[0], DEFAULT_ICON)


def _score(query: str, name: str) -> tuple[int, int, int] | None:
    """Rank *name* against *query* (both lowercase). Lower sorts first.

    A substring beats a scattered subsequence, an earlier match beats a later
    one, and a short name beats a long one — so ``aws`` puts ``cloud/aws`` above
    ``work/paws-staging``.
    """
    index = name.find(query)
    if index != -1:
        return (0, index, len(name))
    position = -1
    start = None
    for char in query:
        position = name.find(char, position + 1)
        if position == -1:
            return None
        if start is None:
            start = position
    return (1, position - (start or 0), len(name))


def rank(names: list[str], query: str) -> list[str]:
    """The entries matching *query*, best match first."""
    if not query.strip():
        return list(names)
    q = query.strip().lower()
    scored = []
    for name in names:
        score = _score(q, name.lower())
        if score is not None:
            scored.append((score, name))
    scored.sort(key=lambda item: (item[0], item[1]))
    return [name for _, name in scored]


class PickerApp(App[str]):
    """Filter box + list of entry names; exits with the chosen name."""

    CSS = """
    Screen { height: 10; background: $surface; }

    #filter {
        height: 1; border: none; padding: 0 1;
        background: $surface; color: $foreground;
    }
    #options {
        height: 1fr; border: none; padding: 0; background: $surface;
        scrollbar-size-vertical: 1;
    }
    /* A lifted row, not a red bar: the picker sits in the middle of your
       scrollback, so the highlight should read as a cursor, not an alarm. */
    #options > .option-list--option-highlighted {
        background: $panel; color: $foreground; text-style: bold;
    }
    #hint { height: 1; padding: 0 1; color: $text-muted; }
    """

    BINDINGS = [
        Binding("escape", "cancel", "cancel", priority=True),
        Binding("down,ctrl+n", "move(1)", "next", priority=True, show=False),
        Binding("up,ctrl+p", "move(-1)", "previous", priority=True, show=False),
    ]

    def __init__(self, names: list[str], *, query: str = "", action: str = "select") -> None:
        super().__init__()
        self.names = names
        self.query = query
        self.action_label = action
        self.matches: list[str] = rank(names, query)
        self._marked: int | None = None  # row currently wearing the ❯ cursor
        self.palette = load_palette()  # the user's colors (`sekrt config`)

    def compose(self) -> ComposeResult:
        yield Input(value=self.query, placeholder="type to filter…", id="filter")
        yield OptionList(*self._options(), id="options")
        yield Label(self._hint(), id="hint")

    def _hint(self) -> str:
        if not self.matches:
            return "no entry matches · esc cancel"
        return f"↑↓ move · enter {self.action_label} · esc cancel"

    def _options(self) -> list[Option]:
        return [Option(self._label(name), id=name) for name in self.matches]

    def _label(self, name: str, marked: bool = False) -> str:
        marker = f"[{self.palette.accent}]{MARKER}[/]" if marked else " "
        return f"{marker} {icon_for(name)} {name}"

    def _mark(self, index: int | None) -> None:
        """Move the cursor to *index*, rewriting only the two rows involved."""
        options = self.query_one("#options", OptionList)
        for row in {self._marked, index}:
            if row is not None and 0 <= row < len(self.matches):
                options.replace_option_prompt_at_index(
                    row, self._label(self.matches[row], marked=row == index)
                )
        self._marked = index

    def on_mount(self) -> None:
        apply_palette(self, self.palette)
        # Claim only as many lines as there is content for: a two-entry vault
        # shouldn't push eight blank rows of scrollback off the screen.
        rows = max(1, min(len(self.matches) or 1, MAX_ROWS))
        self.screen.styles.height = rows + 2  # filter + rows + hint
        self.query_one("#options", OptionList).highlighted = 0
        self._mark(0 if self.matches else None)
        self.query_one("#filter", Input).focus()

    def on_input_changed(self, event: Input.Changed) -> None:
        self.matches = rank(self.names, event.value)
        options = self.query_one("#options", OptionList)
        self._marked = None  # fresh options come back without the cursor
        options.clear_options().add_options(self._options())
        options.highlighted = 0 if self.matches else None
        self._mark(options.highlighted)
        self.query_one("#hint", Label).update(self._hint())

    def on_input_submitted(self) -> None:
        self._choose(self.query_one("#options", OptionList).highlighted)

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        self._choose(event.option_index)

    def on_option_list_option_highlighted(self, event: OptionList.OptionHighlighted) -> None:
        self._mark(event.option_index)

    def _choose(self, index: int | None) -> None:
        if index is not None and 0 <= index < len(self.matches):
            self.exit(self.matches[index])

    def action_move(self, delta: int) -> None:
        """Move the highlight while the filter box keeps the focus (and wrap around)."""
        options = self.query_one("#options", OptionList)
        if not self.matches:
            return
        if delta > 0:
            options.action_cursor_down()
        else:
            options.action_cursor_up()

    def action_cancel(self) -> None:
        self.exit(None)


def interactive() -> bool:
    """Can we draw a picker? Needs a keyboard on stdin and a terminal on stderr."""
    try:
        return sys.stdin.isatty() and sys.stderr.isatty()
    except (AttributeError, ValueError):  # closed or replaced streams
        return False


def pick(names: list[str], *, query: str = "", action: str = "select") -> str | None:
    """Run the picker inline; returns the chosen entry name, or None if cancelled."""
    if not names:
        return None
    return PickerApp(names, query=query, action=action).run(inline=True)
