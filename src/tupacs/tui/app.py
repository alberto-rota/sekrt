"""The tupacs TUI: browse, add, edit, copy and sync — all from the keyboard."""

from __future__ import annotations

from rich.markup import escape
from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Footer, Header, Input, Label, Select, Static, TextArea, Tree

from tupacs import clipboard, gitsync, session
from tupacs.crypto import CryptoError, WrongPassphraseError
from tupacs.generate import generate_password
from tupacs.vault import Vault, VaultError, new_entry, primary_field

SENSITIVE_FIELDS = {"password", "key", "secret", "token", "private", "content"}
MASK = "••••••••••"
EDITABLE_TYPES = ("password", "api_key", "note")

WELCOME = (
    "[dim]select an entry on the left — or press "
    "[b]a[/b] to add, [b]/[/b] to filter, [b]s[/b] to sync[/dim]"
)


class UnlockScreen(ModalScreen[bytes]):
    """Passphrase prompt shown until the vault is unlocked."""

    BINDINGS = [Binding("escape", "give_up", "Quit")]

    def __init__(self, vault: Vault) -> None:
        super().__init__()
        self.vault = vault

    def compose(self) -> ComposeResult:
        with Vertical(id="unlock-box"):
            yield Label("🔐 tupacs", id="unlock-title")
            yield Label(f"{self.vault.path}", id="unlock-path")
            yield Input(password=True, placeholder="passphrase…", id="unlock-input")
            yield Static("", id="unlock-error")

    def on_mount(self) -> None:
        self.query_one("#unlock-input", Input).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.value:
            self.query_one("#unlock-error", Static).update("[dim]unlocking…[/dim]")
            self._unlock(event.value)

    @work(thread=True)
    def _unlock(self, phrase: str) -> None:
        try:
            key = self.vault.unlock(phrase)
        except WrongPassphraseError:
            def fail() -> None:
                self.query_one("#unlock-error", Static).update("[red]wrong passphrase[/red]")
                box = self.query_one("#unlock-input", Input)
                box.value = ""
                box.focus()

            self.app.call_from_thread(fail)
        else:
            self.app.call_from_thread(self.dismiss, key)

    def action_give_up(self) -> None:
        self.app.exit()


class EntryModal(ModalScreen["dict | None"]):
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
                yield Button("🎲 Generate", id="btn-gen")
                yield Button("Save", variant="primary", id="btn-save")
                yield Button("Cancel", id="btn-cancel")

    def on_mount(self) -> None:
        self.query_one("#f-name" if not self._name else "#f-secret", Input).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-gen":
            self.query_one("#f-secret", Input).value = generate_password()
            self.notify("generated a 20-char password", timeout=3)
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


class ConfirmModal(ModalScreen[bool]):
    BINDINGS = [
        Binding("y", "yes", "Yes"),
        Binding("n", "no", "No"),
        Binding("escape", "no", "No"),
    ]

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


class TupacsApp(App[None]):
    TITLE = "tupacs"
    SUB_TITLE = "your secrets, encrypted & synced"

    CSS = """
    #sidebar { width: 36; min-width: 24; border-right: tall $primary; }
    #search { margin: 0 1; }
    #tree { padding: 0 1; }
    #detail-pane { padding: 1 2; }

    UnlockScreen, EntryModal, ConfirmModal { align: center middle; }
    #unlock-box { width: 60; height: auto; border: round $primary; padding: 1 2;
                  background: $surface; }
    #unlock-title { width: 100%; text-align: center; text-style: bold; }
    #unlock-path { width: 100%; text-align: center; color: $text-muted; margin-bottom: 1; }
    #unlock-error { height: 1; margin-top: 1; }

    #entry-box { width: 72; height: auto; border: round $primary; padding: 1 2;
                 background: $surface; }
    #entry-title { text-style: bold; margin-bottom: 1; }
    #entry-box Input, #entry-box Select { margin-bottom: 1; }
    #f-notes { height: 4; margin-bottom: 1; }

    #confirm-box { width: 56; height: auto; border: round $warning; padding: 1 2;
                   background: $surface; }
    .buttons { height: auto; align-horizontal: right; }
    .buttons Button { margin-left: 2; }
    """

    BINDINGS = [
        Binding("a", "add_entry", "Add"),
        Binding("e", "edit_entry", "Edit"),
        Binding("d", "delete_entry", "Delete"),
        Binding("c", "copy_secret", "Copy secret"),
        Binding("u", "copy_username", "Copy user", show=False),
        Binding("r", "toggle_reveal", "Reveal"),
        Binding("s", "sync", "Sync"),
        Binding("slash", "focus_search", "Filter", key_display="/"),
        Binding("l", "lock", "Lock"),
        Binding("q", "quit", "Quit"),
    ]

    def __init__(self, vault: Vault | None = None, key: bytes | None = None) -> None:
        super().__init__()
        self.vault = vault or Vault()
        self.key = key
        self.current: str | None = None
        self.current_entry: dict | None = None
        self.revealed = False
        self.detail_markup = WELCOME  # mirrors the #detail Static, handy for tests
        self._editing_name: str | None = None  # entry being edited, None while adding

    # -- lifecycle -----------------------------------------------------------

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        with Horizontal():
            with Vertical(id="sidebar"):
                yield Input(placeholder="filter…  ( / )", id="search")
                yield Tree("🔐 vault", id="tree")
            yield VerticalScroll(Static(WELCOME, id="detail"), id="detail-pane")
        yield Footer()

    def on_mount(self) -> None:
        if self.key is None:
            cached = session.load_key(self.vault.path)
            if cached is not None and self.vault.verify_key(cached):
                self.key = cached
        if self.key is None:
            self.push_screen(UnlockScreen(self.vault), self._on_unlocked)
        else:
            self.refresh_tree()
            self.query_one("#tree", Tree).focus()

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
            self.show_detail_message(
                "[dim]vault is empty — press [b]a[/b] to add your first entry[/dim]"
                if not filter_text
                else "[dim]no entries match the filter[/dim]"
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
        lines = [f"[b]{escape(self.current)}[/b]  [dim]({escape(entry['type'])})[/dim]", ""]
        for field, value in entry["data"].items():
            hidden = field in SENSITIVE_FIELDS and not self.revealed
            label = f"[b cyan]{escape(field)}[/b cyan]"
            if "\n" in value:
                if hidden:
                    lines.append(f"{label}: [dim]({len(value.splitlines())} lines — press r)[/dim]")
                else:
                    lines.append(f"{label}:")
                    lines.extend("  " + escape(line) for line in value.splitlines())
            else:
                lines.append(f"{label}: {MASK if hidden else escape(value)}")
        lines += ["", "[dim]c copy · r reveal · e edit · d delete[/dim]"]
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
        self.notify(f"{field} copied — clipboard clears in 45s", timeout=4)

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
                "(tupacs env / tupacs ssh)",
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
        self.show_detail_message(WELCOME)
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

    def action_lock(self) -> None:
        session.clear(self.vault.path)
        self.key = None
        self.show_detail_message(WELCOME)
        self.query_one("#tree", Tree).clear()
        self.push_screen(UnlockScreen(self.vault), self._on_unlocked)


def run_tui() -> None:
    vault = Vault()
    if not vault.initialized:
        raise SystemExit(
            f"no vault found at {vault.path} — create one with `tupacs init`"
        )
    TupacsApp(vault=vault).run()
