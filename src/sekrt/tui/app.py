"""The sekrt TUI: browse, add, edit, copy and sync — all from the keyboard."""

from __future__ import annotations

from rich.markup import escape
from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Footer, Header, Input, Label, Select, Static, TextArea, Tree

from sekrt import clipboard, gitsync, session
from sekrt.crypto import CryptoError, WrongPassphraseError
from sekrt.generate import generate_password
from sekrt.prefs import (
    DEFAULT_PALETTE,
    DEFAULT_SETTINGS,
    Palette,
    PrefsError,
    Settings,
    load_palette,
    load_settings,
    save_palette,
    save_settings,
)
from sekrt.tui.colors import EDITOR_CSS, MODAL_HINT, PaletteEditor
from sekrt.tui.theme import BACKGROUND, BADGE, apply_palette
from sekrt.vault import Vault, VaultError, new_entry, primary_field

SENSITIVE_FIELDS = {"password", "key", "secret", "token", "private", "content", "notes"}
MASK = "••••••••••"
EDITABLE_TYPES = ("password", "api_key", "note")


def welcome_markup(p: Palette) -> str:
    return (
        f"[{p.secondary}]select an entry on the left — or press "
        f"[b {p.accent}]a[/] to add, [b {p.accent}]/[/] to filter, "
        f"[b {p.accent}]s[/] to sync[/]"
    )


def window_chrome_sequences(title: str, background: str | None) -> str:
    """OSC escapes that retitle — and optionally recolor — the host window/tab.

    ``background`` of ``None`` resets the window to the terminal's own color, so
    every screen gets the look of a freshly opened tab rather than inheriting the
    previous screen's.
    """
    seq = f"\x1b]0;{title}\x07"
    seq += f"\x1b]11;{background}\x07" if background else "\x1b]111\x07"
    return seq


class WindowChrome:
    """Mixin: a screen owns its host window's title and background.

    Pushing a screen onto the current window should feel like opening a new tab,
    so each screen claims the chrome when it resumes and hands it back to the
    screen underneath when it goes away.
    """

    WINDOW_TITLE = "sekrt"
    WINDOW_BACKGROUND: str | None = None

    def window_title(self) -> str:
        return self.WINDOW_TITLE

    def apply_window_chrome(self) -> None:
        app = self.app  # type: ignore[attr-defined]
        if isinstance(app, SekrtApp):
            app.set_window_chrome(self.window_title(), self.WINDOW_BACKGROUND)

    def on_screen_resume(self) -> None:
        self.apply_window_chrome()

    def on_unmount(self) -> None:
        app = self.app  # type: ignore[attr-defined]
        stack = app.screen_stack if isinstance(app, SekrtApp) else []
        if stack and stack[-1] is not self:
            app.restore_window_chrome()


class UnlockScreen(WindowChrome, ModalScreen[bytes]):
    """Passphrase prompt shown until the vault is unlocked."""

    BINDINGS = [Binding("escape", "give_up", "Quit")]
    WINDOW_TITLE = "sekrt — locked"

    def __init__(self, vault: Vault) -> None:
        super().__init__()
        self.vault = vault

    def compose(self) -> ComposeResult:
        with Vertical(id="unlock-box"):
            yield Label(f"{BADGE} sekrt", id="unlock-title")
            yield Label(f"{self.vault.path}", id="unlock-path")
            yield Input(password=True, placeholder="passphrase…", id="unlock-input")
            yield Static("", id="unlock-error")

    def on_mount(self) -> None:
        self.query_one("#unlock-input", Input).focus()

    @property
    def palette(self) -> Palette:
        return self.app.palette  # type: ignore[attr-defined]

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.value:
            self.query_one("#unlock-error", Static).update(
                f"[{self.palette.secondary}]unlocking…[/]"
            )
            self._unlock(event.value)

    @work(thread=True)
    def _unlock(self, phrase: str) -> None:
        try:
            key = self.vault.unlock(phrase)
        except WrongPassphraseError:
            def fail() -> None:
                self.query_one("#unlock-error", Static).update(
                    f"[b {self.palette.accent}]wrong passphrase[/]"
                )
                box = self.query_one("#unlock-input", Input)
                box.value = ""
                box.focus()

            self.app.call_from_thread(fail)
        else:
            self.app.call_from_thread(self.dismiss, key)

    def action_give_up(self) -> None:
        self.app.exit()


class EntryModal(WindowChrome, ModalScreen["dict | None"]):
    """Add/edit form for password, api_key and note entries."""

    BINDINGS = [Binding("escape", "cancel", "Cancel")]

    def __init__(
        self,
        *,
        title: str,
        name: str = "",
        type_: str = "password",
        data: dict[str, str] | None = None,
    ) -> None:
        super().__init__()
        self._title = title
        self._name = name
        self._type = type_ if type_ in EDITABLE_TYPES else "password"
        self._data = data or {}

    def window_title(self) -> str:
        return f"sekrt — {self._title.lower()}"

    def compose(self) -> ComposeResult:
        d = self._data
        secret = d.get("password") or d.get("key") or ""
        with Vertical(id="entry-box"):
            yield Label(self._title, id="entry-title")
            yield Input(value=self._name, placeholder="name  (e.g. work/github)", id="f-name")
            yield Select(
                [(t.replace("_", " "), t) for t in EDITABLE_TYPES],
                value=self._type,
                allow_blank=False,
                id="f-type",
            )
            yield Input(value=d.get("username", ""), placeholder="username (optional)", id="f-user")
            yield Input(value=secret, password=True, placeholder="secret", id="f-secret")
            yield Input(value=d.get("url", ""), placeholder="url (optional)", id="f-url")
            yield TextArea(d.get("notes", ""), id="f-notes")
            with Horizontal(classes="buttons"):
                yield Button("Generate", id="btn-gen")
                yield Button("Save", variant="primary", id="btn-save")
                yield Button("Cancel", id="btn-cancel")

    def on_mount(self) -> None:
        self.query_one("#f-name" if not self._name else "#f-secret", Input).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-gen":
            length = load_settings().password_length
            self.query_one("#f-secret", Input).value = generate_password(length)
            self.notify(f"generated a {length}-char password", timeout=3)
        elif event.button.id == "btn-save":
            self._save()
        elif event.button.id == "btn-cancel":
            self.dismiss(None)

    def _save(self) -> None:
        name = self.query_one("#f-name", Input).value.strip()
        if not name:
            self.notify("name is required", severity="error", timeout=4)
            return
        self.dismiss(
            {
                "name": name,
                "type": self.query_one("#f-type", Select).value,
                "username": self.query_one("#f-user", Input).value.strip(),
                "secret": self.query_one("#f-secret", Input).value,
                "url": self.query_one("#f-url", Input).value.strip(),
                "notes": self.query_one("#f-notes", TextArea).text,
            }
        )

    def action_cancel(self) -> None:
        self.dismiss(None)


class PaletteModal(WindowChrome, ModalScreen["tuple[Palette, Settings] | None"]):
    """Colors and the three defaults, live: the TUI behind it repaints as you edit.

    Escape puts the palette you arrived with back on screen, so backing out of
    a bad experiment costs nothing. The numeric defaults are not applied until
    you save.
    """

    BINDINGS = [
        Binding("enter", "save", "Save", show=False),  # what saves from the preset row
        Binding("escape", "cancel", "Cancel"),
        Binding("ctrl+r", "defaults", "Defaults"),
        Binding("down,ctrl+n", "move(1)", "next", priority=True, show=False),
        Binding("up,ctrl+p", "move(-1)", "previous", priority=True, show=False),
    ]
    WINDOW_TITLE = "sekrt — config"

    def __init__(self, palette: Palette, settings: Settings) -> None:
        super().__init__()
        self.original = palette
        self.settings = settings

    def compose(self) -> ComposeResult:
        with Vertical(id="palette-box"):
            yield Label("Config", id="palette-title")
            yield PaletteEditor(self.original, self.settings)
            yield Label(MODAL_HINT, id="palette-hint")
            with Horizontal(classes="buttons"):
                yield Button("Defaults", id="btn-defaults")
                yield Button("Save", variant="primary", id="btn-save")
                yield Button("Cancel", id="btn-cancel")

    def on_palette_editor_changed(self, event: PaletteEditor.Changed) -> None:
        apply_palette(self.app, event.palette)

    def on_input_submitted(self) -> None:
        self.action_save()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-save":
            self.action_save()
        elif event.button.id == "btn-defaults":
            self.action_defaults()
        else:
            self.action_cancel()

    def action_save(self) -> None:
        editor = self.query_one(PaletteEditor)
        assert editor.settings is not None
        self.dismiss((editor.palette, editor.settings))

    def action_defaults(self) -> None:
        editor = self.query_one(PaletteEditor)
        editor.set_palette(DEFAULT_PALETTE)
        editor.set_settings(DEFAULT_SETTINGS)

    def action_move(self, delta: int) -> None:
        if delta > 0:
            self.focus_next()
        else:
            self.focus_previous()

    def action_cancel(self) -> None:
        apply_palette(self.app, self.original)
        self.dismiss(None)


class ConfirmModal(WindowChrome, ModalScreen[bool]):
    BINDINGS = [
        Binding("y", "yes", "Yes"),
        Binding("n", "no", "No"),
        Binding("escape", "no", "No"),
    ]
    WINDOW_TITLE = "sekrt — confirm"
    WINDOW_BACKGROUND = "#1c0000"  # a destructive question deserves a red-lit window

    def __init__(self, message: str) -> None:
        super().__init__()
        self.message = message

    def compose(self) -> ComposeResult:
        with Vertical(id="confirm-box"):
            yield Static(self.message)
            with Horizontal(classes="buttons"):
                yield Button("Yes (y)", variant="error", id="btn-yes")
                yield Button("No (n)", id="btn-no")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "btn-yes")

    def action_yes(self) -> None:
        self.dismiss(True)

    def action_no(self) -> None:
        self.dismiss(False)


class SekrtApp(App[None]):
    TITLE = "sekrt"
    SUB_TITLE = "your secrets, encrypted & synced"
    WINDOW_TITLE = "sekrt"
    WINDOW_BACKGROUND = BACKGROUND  # the terminal window matches the theme

    CSS = (
        EDITOR_CSS
        + """
    Screen { background: $background; }

    Header { background: $panel; color: $primary; text-style: bold; }
    HeaderTitle { color: $primary; text-style: bold; }
    Footer { background: $panel; }
    FooterKey { background: $panel; }
    FooterKey .footer-key--key { color: $accent; text-style: bold; }

    #sidebar { width: 36; min-width: 24; background: $surface; border-right: solid $primary 40%; }
    #search { margin: 0 1; background: $panel; border: tall $panel; color: $foreground; }
    #search:focus { border: tall $accent; }
    #tree { padding: 0 1; background: $surface; }
    #tree > .tree--cursor { background: $accent; color: $background; text-style: bold; }
    #tree > .tree--highlight-line { background: $boost; }
    #tree > .tree--guides { color: #2a2e33; }
    #tree > .tree--guides-selected { color: $accent; }
    #detail-pane { padding: 1 2; background: $background; }

    UnlockScreen, EntryModal, ConfirmModal, PaletteModal { align: center middle; }
    #unlock-box { width: 60; height: auto; border: round $primary; padding: 1 2;
                  background: $surface; }
    #unlock-title { width: 100%; text-align: center; text-style: bold; color: $primary; }
    #unlock-path { width: 100%; text-align: center; color: $text-muted; margin-bottom: 1; }
    #unlock-error { height: 1; margin-top: 1; }
    #unlock-input { background: $panel; border: tall $panel; }
    #unlock-input:focus { border: tall $accent; }

    #entry-box { width: 72; height: auto; border: round $primary; padding: 1 2;
                 background: $surface; }
    #entry-title { text-style: bold; color: $primary; margin-bottom: 1; }
    #entry-box Input { margin-bottom: 1; background: $panel; border: tall $panel; }
    #entry-box Input:focus { border: tall $accent; }
    #entry-box Select { margin-bottom: 1; }
    #entry-box Select SelectCurrent { background: $panel; border: tall $panel; }
    #entry-box Select:focus SelectCurrent { border: tall $accent; }
    SelectOverlay { background: $panel; border: round $primary; }
    SelectOverlay > .option-list--option-highlighted { background: $accent;
                                                       color: $background; text-style: bold; }
    #f-notes { height: 4; margin-bottom: 1; background: $panel; border: tall $panel; }
    #f-notes:focus { border: tall $accent; }

    #confirm-box { width: 56; height: auto; border: round $accent; padding: 1 2;
                   background: $surface; }
    #confirm-box .buttons { margin-top: 1; }

    /* Wide enough for the preset row when the terminal allows it; the row
       scrolls rather than the box overflowing when it doesn't. */
    #palette-box { width: 84; max-width: 100%; height: auto; border: round $primary;
                   padding: 1 2; background: $surface; }
    #palette-title { text-style: bold; color: $primary; margin-bottom: 1; }
    #palette-hint { color: $text-muted; margin-top: 1; }
    #palette-box .buttons { margin-top: 1; }
    Toast { background: $panel; color: $foreground; border-left: outer $primary; }
    Toast.-error { border-left: outer $accent; }

    .buttons { height: auto; align-horizontal: right; }
    .buttons Button { margin-left: 2; border: none; min-width: 12;
                      background: $panel; color: $primary; }
    .buttons Button:hover { background: $primary; color: $background; }
    .buttons Button.-primary, .buttons Button.-error { background: $accent;
                                                       color: $background; text-style: bold; }
    .buttons Button.-primary:hover, .buttons Button.-error:hover { background: $primary;
                                                                   color: $background; }
    """
    )

    BINDINGS = [
        Binding("a", "add_entry", "Add"),
        Binding("e", "edit_entry", "Edit"),
        Binding("d", "delete_entry", "Delete"),
        Binding("c", "copy_secret", "Copy secret"),
        Binding("u", "copy_username", "Copy user", show=False),
        Binding("r", "toggle_reveal", "Reveal"),
        Binding("s", "sync", "Sync"),
        Binding("slash", "focus_search", "Filter", key_display="/"),
        Binding("t", "colors", "Config"),
        Binding("l", "lock", "Lock"),
        Binding("q", "quit", "Quit"),
    ]

    def __init__(self, vault: Vault | None = None, key: bytes | None = None) -> None:
        super().__init__()
        self.vault = vault or Vault()
        self.key = key
        self.palette = load_palette()  # the user's colors (`sekrt config`, or `t`)
        self.current: str | None = None
        self.current_entry: dict | None = None
        self.revealed = False
        self.detail_markup = self.welcome()  # mirrors the #detail Static, handy for tests
        self._editing_name: str | None = None  # entry being edited, None while adding
        # (title, background) currently claimed by the host window — mirrored for tests
        self.window_chrome: tuple[str, str | None] = (self.WINDOW_TITLE, None)

    def welcome(self) -> str:
        return welcome_markup(self.palette)

    # -- window chrome -------------------------------------------------------

    def window_title(self) -> str:
        return f"{self.WINDOW_TITLE} — {self.vault.path.name}"

    def set_window_chrome(self, title: str, background: str | None = None) -> None:
        """Retitle and recolor the host terminal window (or tab)."""
        self.window_chrome = (title, background)
        driver = self._driver
        if driver is None or self.is_headless:
            return
        driver.write(window_chrome_sequences(title, background))
        driver.flush()

    def restore_window_chrome(self) -> None:
        """Hand the window back to the main screen, e.g. after a modal closes."""
        self.set_window_chrome(self.window_title(), self.WINDOW_BACKGROUND)

    # -- lifecycle -----------------------------------------------------------

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        with Horizontal():
            with Vertical(id="sidebar"):
                yield Input(placeholder="filter…  ( / )", id="search")
                yield Tree(f"{BADGE} vault", id="tree")
            yield VerticalScroll(Static(self.welcome(), id="detail"), id="detail-pane")
        yield Footer()

    def on_mount(self) -> None:
        apply_palette(self, self.palette)
        self.restore_window_chrome()
        if self.key is None:
            cached = session.load_key(self.vault.path)
            if cached is not None and self.vault.verify_key(cached):
                self.key = cached
        if self.key is None:
            self.push_screen(UnlockScreen(self.vault), self._on_unlocked)
        else:
            self.refresh_tree()
            self.query_one("#tree", Tree).focus()

    def on_unmount(self) -> None:
        """Give the terminal its own title and colors back on the way out."""
        driver = self._driver
        if driver is None or self.is_headless:
            return
        driver.write("\x1b]0;\x07\x1b]111\x07")
        driver.flush()

    def _on_unlocked(self, key: bytes | None) -> None:
        if key is None:
            return
        self.key = key
        self.refresh_tree()
        self.query_one("#tree", Tree).focus()

    # -- tree / detail -------------------------------------------------------

    def refresh_tree(self, filter_text: str = "") -> None:
        tree = self.query_one("#tree", Tree)
        tree.clear()
        try:
            names = self.vault.list_entries()
        except VaultError as exc:
            self.notify(str(exc), severity="error")
            return
        if filter_text:
            names = [n for n in names if filter_text.lower() in n.lower()]
        folders: dict[str, object] = {"": tree.root}
        for name in names:
            parts = name.split("/")
            for depth in range(1, len(parts)):
                folder = "/".join(parts[:depth])
                if folder not in folders:
                    folders[folder] = folders["/".join(parts[: depth - 1])].add(
                        f"📁 {parts[depth - 1]}"
                    )
            folders["/".join(parts[:-1])].add_leaf(parts[-1], data=name)
        tree.root.expand_all()
        if not names:
            p = self.palette
            self.show_detail_message(
                f"[{p.secondary}]vault is empty — press [b {p.accent}]a[/] "
                f"[{p.secondary}]to add your first entry[/]"
                if not filter_text
                else f"[{p.secondary}]no entries match the filter[/]"
            )

    def show_detail_message(self, markup: str) -> None:
        self.current = None
        self.current_entry = None
        self.detail_markup = markup
        self.query_one("#detail", Static).update(markup)

    def on_tree_node_selected(self, event: Tree.NodeSelected) -> None:
        name = event.node.data
        if not isinstance(name, str) or self.key is None:
            return
        try:
            self.current_entry = self.vault.read(self.key, name)
        except (VaultError, CryptoError) as exc:
            self.notify(str(exc), severity="error")
            return
        self.current = name
        self.revealed = False
        self.render_detail()

    def render_detail(self) -> None:
        if self.current is None or self.current_entry is None:
            return
        entry = self.current_entry
        p = self.palette
        type_ = escape(entry["type"])
        lines = [
            f"[b {p.primary}]{escape(self.current)}[/]  [{p.secondary}]({type_})[/]",
            f"[{p.secondary}]{'─' * 40}[/]",
        ]
        for field, value in entry["data"].items():
            hidden = field in SENSITIVE_FIELDS and not self.revealed
            label = f"[b {p.accent}]{escape(field)}[/]"
            if "\n" in value:
                if hidden:
                    lines.append(
                        f"{label}: [{p.secondary}]({len(value.splitlines())} lines — press r)[/]"
                    )
                else:
                    lines.append(f"{label}:")
                    lines.extend("  " + escape(line) for line in value.splitlines())
            else:
                lines.append(f"{label}: {MASK if hidden else escape(value)}")
        keys = f" [{p.secondary}]·[/] ".join(
            f"[b {p.accent}]{k}[/] [{p.primary}]{d}[/]"
            for k, d in (("c", "copy"), ("r", "reveal"), ("e", "edit"), ("d", "delete"))
        )
        lines += ["", keys]
        self.detail_markup = "\n".join(lines)
        self.query_one("#detail", Static).update(self.detail_markup)

    # -- search --------------------------------------------------------------

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "search":
            self.refresh_tree(event.value)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "search":
            self.query_one("#tree", Tree).focus()

    def action_focus_search(self) -> None:
        self.query_one("#search", Input).focus()

    # -- actions -------------------------------------------------------------

    def _unlocked_or_notify(self) -> bool:
        if self.key is None:
            self.notify("vault is locked", severity="warning")
            return False
        return True

    def action_toggle_reveal(self) -> None:
        self.revealed = not self.revealed
        self.render_detail()

    def _copy_field(self, field: str) -> None:
        if not self._unlocked_or_notify() or self.current_entry is None:
            return
        value = self.current_entry["data"].get(field)
        if value is None:
            self.notify(f"no {field!r} field in this entry", severity="warning")
            return
        try:
            clipboard.copy(value)
        except clipboard.ClipboardError as exc:
            self.notify(str(exc), severity="error")
            return
        seconds = load_settings().clipboard_seconds
        self.notify(f"{field} copied — clipboard clears in {seconds}s", timeout=4)

    def action_copy_secret(self) -> None:
        if self.current_entry is not None:
            field = primary_field(self.current_entry)
            if field:
                self._copy_field(field)

    def action_copy_username(self) -> None:
        self._copy_field("username")

    def action_add_entry(self) -> None:
        if self._unlocked_or_notify():
            self._editing_name = None
            self.push_screen(EntryModal(title="New entry"), self._on_entry_saved)

    def action_edit_entry(self) -> None:
        if not self._unlocked_or_notify() or self.current is None or self.current_entry is None:
            return
        if self.current_entry["type"] not in EDITABLE_TYPES:
            self.notify(
                f"{self.current_entry['type']} entries are managed via the CLI "
                "(sekrt env / sekrt ssh)",
                severity="warning",
            )
            return
        self._editing_name = self.current
        self.push_screen(
            EntryModal(
                title=f"Edit {self.current}",
                name=self.current,
                type_=self.current_entry["type"],
                data=dict(self.current_entry["data"]),
            ),
            self._on_entry_saved,
        )

    def _on_entry_saved(self, result: dict | None) -> None:
        if result is None or self.key is None:
            self._editing_name = None
            return
        self._persist_entry(result)

    def _persist_entry(self, result: dict) -> None:
        assert self.key is not None
        name = result["name"]
        type_ = result["type"]
        data: dict[str, str] = {}
        secret_field = {"password": "password", "api_key": "key", "note": "notes"}[type_]
        if result["secret"]:
            data[secret_field] = result["secret"]
        for field in ("username", "url", "notes"):
            if result[field] and field not in data:
                data[field] = result[field]

        editing_name = self._editing_name
        try:
            if editing_name is not None:
                entry = self.vault.read(self.key, editing_name)
                entry["type"] = type_
                entry["data"] = data
                if name != editing_name:
                    self.vault.move(self.key, editing_name, name)
                self.vault.write(self.key, name, entry, overwrite=True, message=f"edit {name}")
            else:
                if not data.get(secret_field):
                    self.notify("secret is empty — nothing saved", severity="warning")
                    return
                self.vault.write(self.key, name, new_entry(type_, data))
        except (VaultError, CryptoError) as exc:
            self.notify(str(exc), severity="error")
            return
        finally:
            self._editing_name = None

        self.refresh_tree(self.query_one("#search", Input).value)
        self.current = name
        self.current_entry = self.vault.read(self.key, name)
        self.render_detail()
        self.notify(f"saved {name}", timeout=3)

    def action_delete_entry(self) -> None:
        if not self._unlocked_or_notify() or self.current is None:
            return
        name = self.current
        self.push_screen(
            ConfirmModal(f"Delete [b]{escape(name)}[/b]?"),
            lambda confirmed: self._delete(name) if confirmed else None,
        )

    def _delete(self, name: str) -> None:
        try:
            self.vault.delete(name)
        except VaultError as exc:
            self.notify(str(exc), severity="error")
            return
        self.show_detail_message(self.welcome())
        self.refresh_tree(self.query_one("#search", Input).value)
        self.notify(f"deleted {name}", timeout=3)

    def action_sync(self) -> None:
        self.notify("syncing…", timeout=2)
        self._sync_worker()

    @work(thread=True, exclusive=True)
    def _sync_worker(self) -> None:
        ok, msg = gitsync.sync(self.vault.path)
        self.call_from_thread(
            self.notify, msg, severity="information" if ok else "error", timeout=6
        )

    # -- colors --------------------------------------------------------------

    def action_colors(self) -> None:
        self.push_screen(
            PaletteModal(self.palette, load_settings()), self._on_palette_chosen
        )

    def _on_palette_chosen(self, chosen: tuple[Palette, Settings] | None) -> None:
        """Store a saved palette and the defaults; a cancelled edit needs nothing.

        Live editing only repaints the theme (borders, footer, cursor); the text
        whose colors are written into its markup is redrawn here, once, so a
        cancelled experiment leaves it untouched. The numeric defaults are
        written alongside the colors and take effect on the next copy, unlock,
        or generated secret.
        """
        if chosen is None:
            return
        palette, settings = chosen
        self.palette = palette
        apply_palette(self, palette)
        self.repaint_markup()
        try:
            save_palette(palette)
            path = save_settings(**settings.to_dict())
        except PrefsError as exc:
            self.notify(str(exc), severity="error")
            return
        self.notify(f"config saved to {path}", timeout=4)

    def repaint_markup(self) -> None:
        """Redraw the text whose colors are baked into markup, not the theme."""
        if self.current_entry is not None:
            self.render_detail()
        else:
            self.show_detail_message(self.welcome())

    def action_lock(self) -> None:
        session.clear(self.vault.path)
        self.key = None
        self.show_detail_message(self.welcome())
        self.query_one("#tree", Tree).clear()
        self.push_screen(UnlockScreen(self.vault), self._on_unlocked)


def run_tui() -> None:
    vault = Vault()
    if not vault.initialized:
        raise SystemExit(
            f"no vault found at {vault.path} — create one with `sekrt init`"
        )
    SekrtApp(vault=vault).run()
