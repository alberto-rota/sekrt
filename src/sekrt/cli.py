"""sekrt command-line interface."""

from __future__ import annotations

import difflib
import functools
import json
import re
import shutil
import sys
from pathlib import Path

import click

from sekrt import (
    __version__,
    clipboard,
    compat,
    envtools,
    filetools,
    gitsync,
    prefs,
    runtools,
    session,
    sshtools,
)
from sekrt.clipboard import ClipboardError
from sekrt.crypto import CryptoError, WrongPassphraseError
from sekrt.generate import DEFAULT_LENGTH, generate_password, generate_token
from sekrt.prefs import PrefsError
from sekrt.util import EditorError, edit_text
from sekrt.vault import (
    PRIMARY_FIELD,
    Vault,
    VaultError,
    new_entry,
    primary_field,
)

SENSITIVE_FIELDS = {
    "password", "key", "secret", "token", "private", "content", "notes", "content_b64",
}
MASK = "********"

# The unlock prompt: the same padlock the picker puts on an entry, and the same
# ❯ it puts on the row under the cursor.
UNLOCK_BADGE = "🔐"
PROMPT_MARKER = "❯"

# C0/C1 control characters minus \t and \n — entry data can originate from
# files other people authored (`sekrt env push`), so `show` must not let
# ANSI escape sequences reach the terminal.
_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b-\x1f\x7f-\x9f]")


def _printable(value: str) -> str:
    return _CONTROL_CHARS.sub("", value)

ALIASES = {
    "insert": "add",
    "list": "ls",
    "remove": "rm",
    "delete": "rm",
    "rename": "mv",
    "search": "find",
    "gen": "generate",
    "ui": "tui",
    "colors": "config",
    "theme": "config",
    "exec": "run",
    "sh": "shell",
}


class AliasedGroup(click.Group):
    def get_command(self, ctx, cmd_name):
        return super().get_command(ctx, ALIASES.get(cmd_name, cmd_name))


def friendly_errors(f):
    @functools.wraps(f)
    def wrapper(*args, **kwargs):
        try:
            return f(*args, **kwargs)
        except (VaultError, CryptoError, ClipboardError, EditorError, PrefsError) as exc:
            raise click.ClickException(str(exc)) from exc

    return wrapper


def get_vault(must_exist: bool = True) -> Vault:
    vault = Vault()
    if must_exist and not vault.initialized:
        raise click.ClickException(
            f"no vault found at {vault.path}\n"
            "  new vault:                    sekrt init\n"
            "  existing vault on a remote:   sekrt clone <url>"
            + compat.migration_hint()
        )
    return vault


def _rgb(color: str) -> tuple[int, int, int]:
    return (int(color[1:3], 16), int(color[3:5], 16), int(color[5:7], 16))


def _paint(text: str, color: str, *, bold: bool = False) -> str:
    """*text* in one of the palette's colors — plain where nothing can show it.

    `click.style` always emits escapes; the prompt can end up on a pipe (no
    terminal to interpret them), so the check happens here rather than being
    left to `echo`.
    """
    if not text or not _at_terminal():
        return text
    return click.style(text, fg=_rgb(color), bold=bold)


def unlock_prompt(vault: Vault, palette: prefs.Palette) -> str:
    """The passphrase prompt, wearing the colors the rest of sekrt wears.

    Names the vault only when `$SEKRT_VAULT` points at one: whoever keeps a
    scratch vault there gets to see which one they are about to open, and nobody
    on the stock path pays for the noise.
    """
    where = f" {vault.path.name}" if compat.env("VAULT") else ""
    return (
        f"{UNLOCK_BADGE} {_paint('passphrase', palette.primary, bold=True)}"
        f"{_paint(where, palette.secondary)} {_paint(PROMPT_MARKER, palette.accent)} "
    )


def obtain_key(vault: Vault) -> bytes:
    """Session cache -> $SEKRT_PASSPHRASE -> interactive prompt."""
    key = session.load_key(vault.path)
    if key is not None and vault.verify_key(key):
        return key
    phrase = compat.env("PASSPHRASE")
    if phrase is not None:
        return vault.unlock(phrase)

    palette = prefs.load_palette()
    prompt = unlock_prompt(vault, palette)
    for attempt in range(3):
        # getpass writes the prompt to the terminal itself, which is what keeps
        # stdout free for the secret: `sekrt get > .token` catches only the value.
        phrase = click.prompt(prompt, hide_input=True, prompt_suffix="", err=True)
        try:
            return vault.unlock(phrase)
        except WrongPassphraseError:
            left = 2 - attempt
            if left:
                tries = "try" if left == 1 else "tries"
                click.echo(
                    _paint(f"  ✗ wrong passphrase — {left} {tries} left", palette.accent),
                    err=True,
                )
    raise click.ClickException("wrong passphrase (3 attempts)")


def _suggest(vault: Vault, name: str) -> str:
    matches = difflib.get_close_matches(name, vault.list_entries(), n=3, cutoff=0.5)
    return f" — did you mean: {', '.join(matches)}?" if matches else ""


def _picker_entries(vault: Vault, name: str | None) -> list[str] | None:
    """The entries to offer for NAME, or None when NAME can be used as it is.

    Nobody remembers `cloud/aws-access-key-prod` exactly, so an omitted or
    unknown NAME is answered with the inline picker at a terminal. Pipes and
    scripts keep the old behaviour — a hard error — because there is nobody
    there to answer. Everything that can fail is decided here, before the
    caller asks for the passphrase.
    """
    if name is not None and vault.exists(name):
        return None

    from sekrt.tui import picker

    if not picker.interactive():
        if name is None:
            raise click.ClickException("NAME is required when not running in a terminal")
        raise click.ClickException(f"no entry named {name!r}{_suggest(vault, name)}")

    names = vault.list_entries()
    if not names:
        raise click.ClickException("vault is empty — add something with `sekrt add`")
    return names


def _pick(names: list[str], query: str | None, action: str) -> str:
    from sekrt.tui import picker

    chosen = picker.pick(names, query=query or "", action=action)
    if chosen is None:
        raise click.Abort
    return chosen


def resolve_name(vault: Vault, name: str | None, *, action: str = "select") -> str:
    """Turn what the user typed into an entry name, picking one interactively if needed."""
    names = _picker_entries(vault, name)
    return name if names is None else _pick(names, name, action)  # type: ignore[return-value]


def resolve_entry(vault: Vault, name: str | None, *, action: str = "select") -> tuple[str, bytes]:
    """Resolve NAME *and* unlock the vault, in that order.

    The passphrase is asked for before the picker draws: a list you can already
    act on beats one that hands you a prompt after you have chosen.
    """
    names = _picker_entries(vault, name)
    key = obtain_key(vault)
    if names is None:
        return name, key  # type: ignore[return-value]
    return _pick(names, name, action), key


def use_form(name: str | None, interactive: bool) -> bool:
    """Should this command draw its inline form instead of reading flags?

    The rule the picker already set: an omitted NAME at a terminal is answered
    with a few lines of TUI, and a pipe or a cron job — where there is nobody to
    answer — keeps insisting on arguments.
    """
    from sekrt.tui import picker

    if not interactive and name is not None:
        return False
    if picker.interactive():
        return True
    if interactive:
        raise click.ClickException("--interactive needs a terminal to draw on")
    raise click.ClickException("NAME is required when not running in a terminal")


def _fill(fields: list, *, title: str) -> dict[str, str]:
    """Run the inline form, treating a cancelled one as `esc` always means here."""
    from sekrt.tui import form

    filled = form.fill(fields, title=title)
    if filled is None:
        raise click.Abort
    return filled


@click.group(cls=AliasedGroup, invoke_without_command=True)
@click.version_option(version=__version__, prog_name="sekrt")
@click.pass_context
def main(ctx: click.Context) -> None:
    """🔐 sekrt — passwords, API keys, SSH keys and .env files, encrypted and git-synced.

    Run without arguments to open the TUI. Vault location: ~/.local/share/sekrt
    (override with $SEKRT_VAULT).
    """
    if ctx.invoked_subcommand is None:
        from sekrt.tui.app import run_tui

        run_tui()


# --------------------------------------------------------------------------- vault


def _clone_into(vault: Vault, url: str) -> None:
    """Populate *vault* from the existing vault repo at *url*."""
    ok, msg = gitsync.clone(url, vault.path)
    if not ok:
        raise click.ClickException(msg)

    if not vault.initialized:
        # Cloned something, but it isn't a vault — don't leave the debris behind.
        shutil.rmtree(vault.path, ignore_errors=True)
        raise click.ClickException(
            f"{url} does not look like a sekrt vault (no {vault.config_path.name})"
        )

    click.secho(f"✔ vault cloned to {vault.path}", fg="green")
    entries = vault.list_entries()
    click.echo(f"  {len(entries)} entr{'y' if len(entries) == 1 else 'ies'} available")
    click.echo("  unlock with the passphrase that created this vault: `sekrt unlock`")


@main.command()
@click.option("--remote", "remote_url", default=None, help="Git remote URL for sync.")
@friendly_errors
def init(remote_url: str | None) -> None:
    """Create a new vault, or set this machine up from an existing one."""
    vault = get_vault(must_exist=False)
    if vault.initialized:
        raise click.ClickException(f"vault already exists at {vault.path}")
    if remote_url and gitsync.remote_has_commits(remote_url):
        raise click.ClickException(
            f"{remote_url} already contains a vault — use `sekrt clone {remote_url}` instead.\n"
            "  `init` would create a second vault with its own encryption salt, which could "
            "never be merged with the existing one."
        )

    # The fork most people arrive at `init` needing: a second machine has to
    # clone, because a fresh vault gets a fresh salt that can never decrypt the
    # entries already on the remote. Only ask when there's a human to answer —
    # scripts and CI keep the plain create-a-vault behaviour.
    interactive = remote_url is None and click.get_text_stream("stdin").isatty()
    if interactive and click.confirm(
        "Do you already have a sekrt vault pushed to a git repo?", default=False
    ):
        _clone_into(vault, click.prompt("Vault repo URL").strip())
        return

    phrase = compat.env("PASSPHRASE") or click.prompt(
        "Choose a vault passphrase", hide_input=True, confirmation_prompt=True
    )
    vault.create(phrase)
    if remote_url:
        gitsync.set_remote(vault.path, remote_url)
    click.secho(f"✔ vault created at {vault.path}", fg="green")
    if remote_url:
        click.echo(f"  remote set to {remote_url} — push with `sekrt sync`")
    else:
        click.echo("  connect a private GitHub repo with `sekrt remote <url>`")


@main.command()
@click.argument("url")
@friendly_errors
def clone(url: str) -> None:
    """Set up this machine from an existing vault repo (e.g. a private GitHub repo)."""
    vault = get_vault(must_exist=False)
    if vault.initialized:
        raise click.ClickException(
            f"vault already exists at {vault.path} — "
            f"move it aside first if you mean to replace it"
        )
    _clone_into(vault, url)


@main.command()
@click.option("--timeout", "-t", default=60, show_default=True, help="Minutes to stay unlocked.")
@friendly_errors
def unlock(timeout: int) -> None:
    """Cache the vault key so commands stop prompting for a while."""
    vault = get_vault()
    key = obtain_key(vault)
    if not session.store_key(vault.path, key, ttl=timeout * 60):
        raise click.ClickException("no private runtime directory available for the session cache")
    where = "RAM-backed" if session.is_ram_backed() else "temp-dir (not RAM-backed)"
    click.secho(f"✔ unlocked for {timeout} min ({where} session cache)", fg="green")


@main.command()
@friendly_errors
def lock() -> None:
    """Forget the cached vault key."""
    vault = get_vault()
    session.clear(vault.path)
    click.secho("✔ locked", fg="green")


@main.command()
@friendly_errors
def passwd() -> None:
    """Change the vault passphrase (re-encrypts every entry)."""
    vault = get_vault()
    key = obtain_key(vault)
    new_phrase = click.prompt("New passphrase", hide_input=True, confirmation_prompt=True)
    vault.rekey(key, new_phrase)
    session.clear(vault.path)
    click.secho("✔ passphrase changed, all entries re-encrypted", fg="green")


@main.command()
@friendly_errors
def status() -> None:
    """Vault location, entry count, sync and session state."""
    vault = get_vault()
    entries = vault.list_entries()
    remote = gitsync.get_remote(vault.path)
    ttl = session.remaining(vault.path)
    click.echo(f"vault     {vault.path}")
    click.echo(f"entries   {len(entries)}")
    click.echo(f"remote    {remote or '(none — set with `sekrt remote <url>`)'}")
    click.echo(f"autosync  {'on' if vault.auto_sync else 'off'}")
    click.echo(f"session   {'unlocked, ' + str(ttl // 60) + ' min left' if ttl else 'locked'}")


# --------------------------------------------------------------------------- entries


ADD_TYPES = ("password", "api_key", "note")


def _add_form(name: str | None, type_: str) -> dict[str, str]:
    """The six fields of `sekrt add`, as a form instead of six flags."""
    from sekrt.tui import form

    return _fill(
        [
            form.Field("name", "name", placeholder="work/github", value=name or "",
                       required=True),
            form.Field("type", "type", value=type_, choices=ADD_TYPES),
            form.Field("username", "username", placeholder="optional"),
            form.Field("secret", "secret", placeholder="type it, or ctrl+g to generate",
                       secret=True, generate=True),
            form.Field("url", "url", placeholder="optional"),
            form.Field("notes", "notes", placeholder="optional"),
        ],
        title="new entry",
    )


@main.command()
@click.argument("name", required=False)
@click.option("--type", "-t", "type_", type=click.Choice(ADD_TYPES),
              default="password", show_default=True)
@click.option("--username", "-u", default=None, help="Username / login.")
@click.option("--url", default=None, help="Associated URL.")
@click.option("--notes", default=None, help="Free-form notes.")
@click.option("--generate", "-g", "generate_", is_flag=True, help="Generate the secret.")
@click.option("--length", "-L", default=DEFAULT_LENGTH, show_default=True)
@click.option("--no-symbols", is_flag=True, help="Generated secret: letters and digits only.")
@click.option("--show", "-s", is_flag=True, help="Print the generated secret.")
@click.option("--force", "-f", is_flag=True, help="Overwrite an existing entry.")
@click.option("--interactive", "-i", is_flag=True, help="Fill the inline form even with a NAME.")
@friendly_errors
def add(name, type_, username, url, notes, generate_, length, no_symbols, show, force,
        interactive) -> None:
    """Add an entry (a password, an API key, or a note).

    With no NAME (or with -i) this opens a few lines of inline form — name,
    type, username, secret, url, notes — instead of asking for the same thing
    in flags. `ctrl+g` fills the secret in for you.

    \b
      sekrt add                                    # the form
      sekrt add work/github -u alberto -g
      sekrt add cloud/aws-key -t api_key
      sekrt add wifi/office -t note --notes "WPA2 ..."
    """
    vault = get_vault()
    # Everything that can fail is settled before the passphrase is asked for,
    # and the passphrase before the form draws — the picker's order, for the same
    # reason: a form you can submit beats one that prompts after you fill it.
    wants_form = use_form(name, interactive)
    key = obtain_key(vault)

    form_secret: str | None = None
    if wants_form:
        filled = _add_form(name, type_)
        name, type_ = filled["name"], filled["type"]
        username = filled["username"] or username
        url = filled["url"] or url
        notes = filled["notes"] or notes
        form_secret = filled["secret"]
        generate_ = False  # ctrl+g already put a generated secret in the field

    data: dict[str, str] = {}
    secret_field = PRIMARY_FIELD[type_]
    if type_ == "note":
        # A note typed into the form's `secret` field is the note: whichever of
        # the two rows it was written on, it is the same text. $EDITOR opens only
        # when neither holds anything.
        text = notes if notes is not None else (form_secret or edit_text("", suffix=".txt"))
        if not text:
            raise click.ClickException("empty note — nothing saved")
        data["notes"] = text
        notes = None
    elif form_secret is not None:
        if not form_secret:
            raise click.ClickException("empty secret — nothing saved")
        data[secret_field] = form_secret
    elif generate_:
        data[secret_field] = generate_password(length, symbols=not no_symbols)
    else:
        label = "Password" if type_ == "password" else "API key"
        data[secret_field] = click.prompt(label, hide_input=True, confirmation_prompt=True)

    for field, value in (("username", username), ("url", url), ("notes", notes)):
        if value:
            data[field] = value

    vault.write(key, name, new_entry(type_, data), overwrite=force)
    click.secho(f"✔ stored {name}", fg="green")

    if generate_:
        secret = data[secret_field]
        copied = False
        if clipboard.available():
            clipboard.copy(secret)
            copied = True
        if show:
            click.echo(secret)
        elif copied:
            click.echo(f"  generated {length}-char secret copied to clipboard (clears in 45s)")
        else:
            click.echo("  generated secret stored — reveal with `sekrt get " + name + "`")


@main.command()
@click.argument("name", required=False)
@click.option("--field", "-f", "field", default=None, help="Field to output (default: the secret).")
@click.option("--copy", "-c", "copy_", is_flag=True, help="Copy to clipboard instead of printing.")
@friendly_errors
def get(name: str | None, field: str | None, copy_: bool) -> None:
    """Print (or copy) an entry's secret. Script-friendly: value only, to stdout.

    \b
      sekrt get cloud/aws-key        # exact name
      sekrt get aws                  # partial: pick from the matches
      sekrt get                      # pick from every entry
    """
    vault = get_vault()
    name, key = resolve_entry(vault, name, action="print")
    entry = vault.read(key, name)
    field = field or primary_field(entry)
    if field is None or field not in entry["data"]:
        have = ", ".join(entry["data"]) or "(none)"
        raise click.ClickException(f"no field {field!r} in {name} — available: {have}")
    value = entry["data"][field]
    if copy_:
        clipboard.copy(value)
        click.secho(f"✔ {name}:{field} copied to clipboard (clears in 45s)", fg="green", err=True)
    else:
        click.echo(value)


def _secret_block(field: str, value: str) -> None:
    """Print a revealed secret set apart, alone on its lines, at column 0.

    Nothing shares a line with a secret: a double- or triple-click selects the
    value and nothing else, and a revealed SSH key comes out pasteable rather
    than indented into something that is no longer an SSH key.
    """
    click.echo()
    click.secho(f"  {field}:", dim=True)
    for line in value.split("\n"):
        click.echo(line)


def _copy_target(entry: dict, secrets: list[tuple[str, str]]) -> tuple[str, str]:
    """Which revealed secret `c` copies: the entry's main one, else the first."""
    main = primary_field(entry)
    return next((pair for pair in secrets if pair[0] == main), secrets[0])


def _at_terminal() -> bool:
    """Is there a terminal on stderr to prompt on?"""
    try:
        return sys.stderr.isatty()
    except (AttributeError, ValueError):  # closed or replaced streams
        return False


def _offer_copy(field: str, value: str) -> None:
    """A `press c to copy` prompt under the secret, when there is a terminal.

    The prompt and its answer are stderr-only and erase themselves, so what
    stays on screen (and in a redirect) is the secret alone.
    """
    if not _at_terminal() or not clipboard.available():
        return
    click.secho(f"\n  press c to copy {field} · any other key to dismiss",
                dim=True, err=True, nl=False)
    key = clipboard.read_key()
    click.echo("\r\x1b[2K", nl=False, err=True)  # take the prompt line back
    if key and key.lower() == "c":
        clipboard.copy(value)
        click.secho(f"  ✔ {field} copied to clipboard (clears in 45s)", fg="green", err=True)


@main.command()
@click.argument("name", required=False)
@click.option("--reveal", "-r", is_flag=True, help="Show secret fields in clear text.")
@friendly_errors
def show(name: str | None, reveal: bool) -> None:
    """Show all fields of an entry (secrets masked unless --reveal).

    Revealed secrets come last, each on a line of its own, and at a terminal
    `c` copies the main one to the clipboard.

    With no NAME (or a partial one) an inline picker lists the vault.
    """
    vault = get_vault()
    name, key = resolve_entry(vault, name, action="show")
    entry = vault.read(key, name)
    click.secho(name, bold=True)
    click.echo(f"  type: {entry['type']}")

    secrets: list[tuple[str, str]] = []  # revealed secrets, kept for the end
    for field, value in entry["data"].items():
        if field == "content_b64":
            size = entry["data"].get("size", "?")
            click.echo(f"  content: ({size} bytes — use `sekrt file get {name}`)")
            continue
        value = _printable(value)
        if field in SENSITIVE_FIELDS:
            if reveal:
                secrets.append((field, value))
            elif "\n" in value:
                click.echo(f"  {field}: ({len(value.splitlines())} lines — use --reveal)")
            else:
                click.echo(f"  {field}: {MASK}")
        elif "\n" in value:
            click.echo(f"  {field}:")
            for line in value.splitlines():
                click.echo(f"    {line}")
        else:
            click.echo(f"  {field}: {value}")

    for field, value in secrets:
        _secret_block(field, value)
    if secrets:
        _offer_copy(*_copy_target(entry, secrets))


@main.command()
@click.argument("prefix", default="")
@friendly_errors
def ls(prefix: str) -> None:
    """List entries (optionally under a folder prefix)."""
    vault = get_vault()
    names = vault.list_entries(prefix)
    if not names:
        click.echo("(vault is empty — add something with `sekrt add`)" if not prefix
                   else f"(nothing under {prefix!r})")
        return
    for name in names:
        click.echo(name)


@main.command()
@click.argument("query")
@friendly_errors
def find(query: str) -> None:
    """Search entry names."""
    vault = get_vault()
    for name in vault.search(query):
        click.echo(name)


@main.command()
@click.argument("name", required=False)
@friendly_errors
def edit(name: str | None) -> None:
    """Edit an entry's fields in $EDITOR.

    A note's text is edited raw (multiline, no JSON escaping); every other
    type is edited as its JSON field dict. With no NAME (or a partial one) an
    inline picker lists the vault.
    """
    vault = get_vault()
    name, key = resolve_entry(vault, name, action="edit")
    entry = vault.read(key, name)

    if entry["type"] == "note":
        text = edit_text(entry["data"].get("notes", ""), suffix=".txt")
        if text is None:
            click.echo("no changes")
            return
        entry["data"]["notes"] = text
    else:
        text = edit_text(json.dumps(entry["data"], indent=2) + "\n")
        if text is None:
            click.echo("no changes")
            return
        try:
            data = json.loads(text)
        except ValueError as exc:
            raise click.ClickException(f"invalid JSON: {exc}") from exc
        if not isinstance(data, dict) or not all(
            isinstance(k, str) and isinstance(v, str) for k, v in data.items()
        ):
            raise click.ClickException("entry data must be a flat JSON object of strings")
        entry["data"] = data

    vault.write(key, name, entry, overwrite=True, message=f"edit {name}")
    click.secho(f"✔ updated {name}", fg="green")


@main.command()
@click.argument("old")
@click.argument("new")
@click.option("--force", "-f", is_flag=True, help="Overwrite the destination.")
@friendly_errors
def mv(old: str, new: str, force: bool) -> None:
    """Rename / move an entry."""
    vault = get_vault()
    key = obtain_key(vault)
    vault.move(key, old, new, overwrite=force)
    click.secho(f"✔ {old} -> {new}", fg="green")


@main.command()
@click.argument("name", required=False)
@click.option("--force", "-f", is_flag=True, help="Skip confirmation.")
@friendly_errors
def rm(name: str | None, force: bool) -> None:
    """Delete an entry (picked inline when NAME is omitted or partial)."""
    vault = get_vault()
    name = resolve_name(vault, name, action="delete")
    if not force and not click.confirm(f"Delete {name!r}?"):
        return
    vault.delete(name)
    click.secho(f"✔ removed {name}", fg="green")


@main.command()
@click.argument("length", default=DEFAULT_LENGTH, type=int)
@click.option("--no-symbols", is_flag=True, help="Letters and digits only.")
@click.option("--token", is_flag=True, help="URL-safe token instead (for API keys).")
@click.option("--copy", "-c", "copy_", is_flag=True, help="Copy instead of printing.")
@friendly_errors
def generate(length: int, no_symbols: bool, token: bool, copy_: bool) -> None:
    """Generate a random password (not stored)."""
    secret = generate_token() if token else generate_password(length, symbols=not no_symbols)
    if copy_:
        clipboard.copy(secret)
        click.secho("✔ copied to clipboard (clears in 45s)", fg="green", err=True)
    else:
        click.echo(secret)


# --------------------------------------------------------------------------- sync


@main.command()
@click.argument("url")
@friendly_errors
def remote(url: str) -> None:
    """Set the git remote used for sync (e.g. a private GitHub repo)."""
    vault = get_vault()
    if gitsync.remote_has_commits(url) and not vault.list_entries():
        # Empty local vault + populated remote: almost certainly a second machine
        # that ran `init` by mistake. Pointing it at the remote guarantees an
        # unmergeable sync later, so stop here while nothing is lost.
        raise click.ClickException(
            f"{url} already contains a vault, and this one is empty.\n"
            "  Setting it as a remote would leave two vaults with different encryption "
            "salts that can never be merged.\n"
            f"  Adopt the existing vault instead:\n"
            f"    rm -rf {vault.path} && sekrt clone {url}"
        )
    gitsync.set_remote(vault.path, url)
    click.secho(f"✔ remote set to {url}", fg="green")
    click.echo("  run `sekrt sync` to push, `sekrt autosync on` to push automatically")


@main.command()
@friendly_errors
def sync() -> None:
    """Pull remote changes and push local ones."""
    vault = get_vault()
    ok, msg = gitsync.sync(vault.path)
    if not ok:
        raise click.ClickException(msg)
    click.secho(f"✔ {msg}", fg="green")


@main.command()
@click.argument("state", type=click.Choice(["on", "off"]))
@friendly_errors
def autosync(state: str) -> None:
    """Push to the remote automatically after every change."""
    vault = get_vault()
    vault.set_auto_sync(state == "on")
    click.secho(f"✔ autosync {state}", fg="green")


@main.command(context_settings={"ignore_unknown_options": True, "help_option_names": []})
@click.argument("args", nargs=-1, type=click.UNPROCESSED)
@friendly_errors
def git(args: tuple[str, ...]) -> None:
    """Run a raw git command inside the vault (e.g. `sekrt git log --oneline`)."""
    import subprocess

    vault = get_vault()
    raise SystemExit(subprocess.call(["git", "-C", str(vault.path), *args]))


# --------------------------------------------------------------------------- env


@main.group()
def env() -> None:
    """Store and restore .env files per repository."""


@env.command("push")
@click.argument("files", nargs=-1, type=click.Path(path_type=Path))
@friendly_errors
def env_push(files: tuple[Path, ...]) -> None:
    """Encrypt .env file(s) of the current repo into the vault."""
    vault = get_vault()
    key = obtain_key(vault)
    for file in files or (Path(".env"),):
        name, action = envtools.push(vault, key, file)
        symbol = {"added": "+", "updated": "~", "unchanged": "="}[action]
        click.secho(f"{symbol} {name} ({action})", fg="green" if action != "unchanged" else None)


@env.command("pull")
@click.argument("files", nargs=-1)
@click.option("--repo", "slug", default=None,
              help="Pull another repo's env files (slug like github.com/you/proj).")
@click.option("--force", "-f", is_flag=True, help="Overwrite local files that differ.")
@friendly_errors
def env_pull(files: tuple[str, ...], slug: str | None, force: bool) -> None:
    """Restore this repo's stored .env file(s) from the vault."""
    vault = get_vault()
    key = obtain_key(vault)
    results = envtools.pull(vault, key, files=list(files) or None, force=force, slug=slug)
    for relpath, action in results:
        symbol = {"restored": "✔", "unchanged": "=", "skipped": "!"}[action]
        color = {"restored": "green", "unchanged": None, "skipped": "yellow"}[action]
        suffix = " (local file differs — use --force)" if action == "skipped" else ""
        click.secho(f"{symbol} {relpath} {action}{suffix}", fg=color)


@env.command("ls")
@friendly_errors
def env_ls() -> None:
    """List every stored env file; '*' marks the current repo's."""
    vault = get_vault()
    stored = envtools.list_all(vault)
    if not stored:
        click.echo("(no env files stored — run `sekrt env push` inside a repo)")
        return
    _, current = envtools.current_context()
    for item in stored:
        marker = "*" if item.startswith(current + "/") else " "
        click.echo(f"{marker} {item}")


@env.command("show")
@click.argument("file", default=".env")
@friendly_errors
def env_show(file: str) -> None:
    """Print the stored content of an env file for the current repo."""
    vault = get_vault()
    key = obtain_key(vault)
    _, slug = envtools.current_context()
    entry = vault.read(key, envtools.entry_name(slug, file))
    click.echo(entry["data"]["content"], nl=False)


@env.command("rm")
@click.argument("file", default=".env")
@click.option("--force", "-f", is_flag=True, help="Skip confirmation.")
@friendly_errors
def env_rm(file: str, force: bool) -> None:
    """Remove a stored env file for the current repo."""
    vault = get_vault()
    _, slug = envtools.current_context()
    name = envtools.entry_name(slug, file)
    if not force and not click.confirm(f"Delete stored {name!r}?"):
        return
    vault.delete(name)
    click.secho(f"✔ removed {name}", fg="green")


# --------------------------------------------------------------------------- run


def expose_options(f):
    """The options that decide what a wrapped process gets to see.

    Shared by `run` and `shell`, which differ only in what they then start.
    """
    for option in reversed([
        click.option("--var", "-e", "requested", multiple=True, metavar="VAR[=ENTRY]",
                     help="Expose only VAR (optionally naming the entry it comes from). "
                          "Repeatable."),
        click.option("--repo", "slug", default=None,
                     help="Use another repo's stored env files (slug like github.com/you/proj)."),
        click.option("--no-env-files", is_flag=True,
                     help="Expose only what -e asks for, not this repo's stored .env files."),
        click.option("--dry-run", "-n", "dry_run", is_flag=True,
                     help="List what would be exposed (names only) and stop."),
    ]):
        f = option(f)
    return f


def _exposures(
    vault: Vault,
    requested: tuple[str, ...],
    slug: str | None,
    no_env_files: bool,
    referenced: list[str] | None = None,
    bulk: bool | None = None,
) -> tuple[list[runtools.Exposure], list[tuple[str, str]]]:
    """Decrypt what the command asked for, and nothing else.

    Whether there is anything to expose at all is settled from entry *names*,
    which are plaintext — so a command that was never going to get a variable
    says so instead of asking for the passphrase first.

    *bulk* is passed through to :func:`runtools.resolve`: `sekrt run` lets an
    unnamed command have the whole vault, `sekrt shell` only when asked.
    """
    referenced = referenced or []
    slug = slug or envtools.current_context()[1]
    stored = [] if no_env_files else envtools.stored_files(vault, slug)
    if (
        not requested
        and not referenced
        and not stored
        and not (bulk is not False and runtools.might_expose(vault))
    ):
        raise click.ClickException(
            "nothing to expose — the vault holds no password or API key entries"
            + (f", and no env files are stored for {slug!r}" if not no_env_files else "")
            + ".\n  add one with `sekrt add`, or store this repo's env file with "
            "`sekrt env push`"
        )

    key = obtain_key(vault)
    resolver = runtools.Resolver(vault, key, slug=slug, env_files=not no_env_files)
    exposures, unresolved = runtools.resolve(
        resolver, requested=requested, referenced=referenced, bulk=bulk
    )
    if not exposures:
        raise click.ClickException(
            "nothing to expose — no entry here holds a value a variable could carry "
            "(notes, SSH keys and stored files do not), and no stored env file "
            f"for {slug!r} defines one"
        )
    for var, names in resolver.ambiguous.items():
        click.secho(
            f"note: ${var} left unset — {' and '.join(names)} both answer to it. "
            f"Pick one with `-e {var}={names[0]}`.",
            fg="yellow",
            err=True,
        )
    return exposures, unresolved


def _echo_plan(exposures: list[runtools.Exposure], argv: list[str]) -> None:
    """`--dry-run`: every variable and where it comes from, values left out of it."""
    for exposure in exposures:
        click.echo(f"{exposure.var:<24}{exposure.origin}")
    click.echo(f"\nwould run: {' '.join(argv)}")


def _warn_unresolved(unresolved: list[tuple[str, str]]) -> None:
    """Mention names the command refers to that the vault could not answer.

    Not fatal: a shell command is free to use variables of its own making, and
    the command runs with the ones that *did* resolve. It is worth saying out
    loud, though — this is what a mistyped variable name looks like.
    """
    for _, message in unresolved:
        click.secho(f"note: {message}", fg="yellow", err=True)


def _warn_swallowed(shell_command: str) -> None:
    """A command string with a hole in it: the calling shell probably ate a reference.

    `sekrt run "echo $MY_TOKEN"` — double quotes — is expanded by the shell that
    runs sekrt, before sekrt exists, so what arrives is `echo ` and the command
    prints nothing at all. `runtools.swallowed_text` knows the shapes that leaves.
    """
    if not runtools.swallowed_text(shell_command):
        return
    click.secho(
        'note: something is missing from that command — if you wrote "$VAR" in double '
        "quotes,\n"
        "      your own shell expanded it before sekrt ran. Single-quote it instead:\n"
        "        sekrt run 'svc --token=\"$VAR\"'",
        fg="yellow",
        err=True,
    )


def _warn_unexpanded(command: tuple[str, ...], exposures: list[runtools.Exposure]) -> None:
    """Catch `sekrt run -- svc --token='$MY_TOKEN'`, where nothing expands the text.

    sekrt deliberately does not substitute into a command line — a value written
    into argv is world-readable in `ps` — so a quoted reference arrives at the
    program as the literal characters. The two ways to actually get the value are
    right here rather than in a debugging session.

    A shell being handed a command (`sekrt run -- sh -c '… $VAR …'`) expands its
    own references, and is not warned about.
    """
    if runtools.is_shell_command(command):
        return
    exposed = {exposure.var for exposure in exposures}
    hits = [var for var in runtools.references(" ".join(command)) if var in exposed]
    if hits:
        click.secho(
            f"note: ${hits[0]} reached the command as text — sekrt never writes a secret "
            f"into a command line (`ps` can read those).\n"
            f"      the program can read {hits[0]} from its environment, or let a shell "
            f"expand it:  sekrt run '… ${hits[0]} …'",
            fg="yellow",
            err=True,
        )
        return

    empty = runtools.swallowed_args(command)
    if empty:
        click.secho(
            f"note: {', '.join(repr(arg) for arg in empty[:2])} looks like a variable your "
            "own shell expanded\n"
            "      away before sekrt ran — it expands what you type, and only sekrt's own "
            "child\n"
            "      knows the value. Single-quote it and let a shell do it:\n"
            "        sekrt run 'svc --token=\"$VAR\"'\n"
            "      or check what the command will see:  sekrt run -- printenv VAR",
            fg="yellow",
            err=True,
        )


@main.command(context_settings={"ignore_unknown_options": True, "allow_interspersed_args": False})
@click.argument("command", nargs=-1, type=click.UNPROCESSED)
@click.option("--shell", "-c", "shell_command", default=None, metavar="STRING",
              help="Run STRING through $SHELL even if it looks like a bare program name.")
@expose_options
@friendly_errors
def run(command, shell_command, requested, slug, no_env_files, dry_run) -> None:
    """Run one command with vault secrets in its environment, and nowhere else.

    The secrets exist only in the environment of the process sekrt starts: they
    are never written to disk, never put in your shell, and gone when the command
    exits.

    With nothing named, the command gets every password and API key in the vault
    — each under the variable its name reads as, so `api/my-token` becomes
    $MY_TOKEN — plus whatever this repository stored with `sekrt env push`. Name
    variables with -e to hand over those and nothing else.

    \b
      sekrt run 'npm start'                         # everything, like a loaded .env
      sekrt run -n 'npm start'                      # ...see exactly what that is
      sekrt run -e MY_TOKEN 'service log'           # only this one
      sekrt run -e MY_TOKEN=work/api-token svc      # ...from a named entry
      sekrt run 'service log --token="$MY_TOKEN"'   # a shell expands the reference
      sekrt run -- printenv MY_TOKEN                # what the command will see
    \b
    A command quoted into one argument is handed to $SHELL, which is what expands
    $VAR in it; several arguments (use -- first, so their flags are not read as
    sekrt's) are run directly, with no shell involved. Note that YOUR shell
    expands what you type before sekrt runs, so "echo $MY_TOKEN" in double quotes
    prints nothing — single-quote it. For a whole session, see `sekrt shell`.
    """
    if bool(command) == bool(shell_command):
        raise click.ClickException(
            "give a command to run:\n"
            "  sekrt run 'service log'\n"
            "  sekrt run 'service log --token=\"$MY_TOKEN\"'\n"
            "  sekrt shell                (a whole session instead of one command)"
        )
    # One quoted string is a command written for a shell; an argv is not. Saying
    # so with -c stays possible, for the string a shell is wanted for anyway.
    if command and runtools.needs_shell(command):
        command, shell_command = (), command[0]

    vault = get_vault()
    referenced = runtools.references(shell_command) if shell_command else []
    exposures, unresolved = _exposures(vault, requested, slug, no_env_files, referenced)
    argv = runtools.shell_argv(shell_command) if shell_command else list(command)

    if shell_command and not referenced:
        _warn_swallowed(shell_command)
    if dry_run:
        _echo_plan(exposures, argv)
        return
    _warn_unresolved(unresolved)
    if command:
        _warn_unexpanded(command, exposures)
    raise SystemExit(runtools.launch(argv, runtools.child_env(exposures)))


def _nothing_named(vault: Vault, slug: str | None, no_env_files: bool) -> None:
    """`sekrt shell` with nothing selected: say how to select, expose nothing.

    A subshell outlives the command that opened it, so the whole vault is not
    what an unnamed `sekrt shell` means — unlike `sekrt run`, where the exposure
    ends with the command. Entry names are plaintext, so this refuses before
    asking for the passphrase.
    """
    slug = slug or envtools.current_context()[1]
    stored = [] if no_env_files else envtools.stored_files(vault, slug)
    if stored:
        return
    lines = [
        "nothing named — say what to expose:",
        "  sekrt shell -e MY_TOKEN",
        "  sekrt shell -e MY_TOKEN -e OTHER_TOKEN",
        "  sekrt shell --all          (every password and API key in the vault)",
    ]
    if not no_env_files:
        lines.append(
            f"  no env file is stored for {slug!r} either — `sekrt env push` stores "
            "this repo's"
        )
    raise click.ClickException("\n".join(lines))


def _acknowledge_all(exposures: list[runtools.Exposure], yes: bool) -> None:
    """`--all` is a loaded gun: name what it hands over, and have it confirmed.

    Everything in the vault, for as long as the shell lives and to everything
    started from it — including whatever that shell runs next. Worth one keypress.
    """
    count = len(exposures)
    click.secho(
        f"⚠ this exposes all {count} secret{'' if count == 1 else 's'} the vault can "
        "offer as variables to that\n"
        "  subshell and to everything you start from it:",
        fg="yellow",
        err=True,
    )
    click.secho("  " + ", ".join(exposure.var for exposure in exposures), dim=True, err=True)
    if yes:
        return
    if not click.get_text_stream("stdin").isatty():
        raise click.ClickException(
            "refusing to expose the whole vault without confirmation — "
            "pass --yes if you meant it"
        )
    if not click.confirm(f"Expose all {count}?", default=False, err=True):
        raise click.Abort()


@main.command()
@click.option("--all", "-a", "expose_all", is_flag=True,
              help="Expose every password and API key in the vault (asks first).")
@click.option("--yes", "-y", is_flag=True, help="Skip the confirmation asked for --all.")
@expose_options
@friendly_errors
def shell(expose_all, yes, requested, slug, no_env_files, dry_run) -> None:
    """Open a subshell holding chosen vault secrets; gone when you `exit`.

    "Expose these tokens for a bit", bounded: the variables live in that shell
    and whatever you start from it, and nothing outside it. Say which with -e;
    with nothing named you get this repo's stored env files and no more. The
    whole vault takes --all, which asks first — unlike `sekrt run`, a subshell
    keeps the secrets for as long as you leave it open.

    \b
      sekrt shell -e MY_TOKEN            # only this one
      sekrt shell -e A_TOKEN -e B_TOKEN  # ...or a few
      sekrt shell                        # this repo's stored .env, nothing else
      sekrt shell --all                  # every password and API key, after y/N
      sekrt shell -n -e MY_TOKEN         # what would be exposed, without opening it
      exit                               # ...and they are gone
    """
    vault = get_vault()
    if not expose_all and not requested:
        _nothing_named(vault, slug, no_env_files)
    exposures, _ = _exposures(vault, requested, slug, no_env_files, bulk=expose_all)

    if dry_run:
        _echo_plan(exposures, [runtools.default_shell()])
        return
    if expose_all:
        _acknowledge_all(exposures, yes)
    # Count and consequence on the first line, names on the second: a vault with
    # twenty tokens should wrap the list, not the sentence explaining it.
    count = len(exposures)
    click.secho(
        f"✔ {count} variable{'' if count == 1 else 's'} exposed in this subshell — "
        f"the prompt says {runtools.SHELL_TAG} until you `exit`",
        fg="green",
        err=True,
    )
    click.secho("  " + ", ".join(exposure.var for exposure in exposures), dim=True, err=True)
    if not expose_all and not requested:
        click.secho(
            "  this repo's stored env files only — name others with -e, "
            "or take the vault with --all",
            dim=True,
            err=True,
        )
    argv, wiring = runtools.shell_launch()
    raise SystemExit(runtools.launch(argv, runtools.child_env(exposures) | wiring))


# --------------------------------------------------------------------------- ssh


@main.group()
def ssh() -> None:
    """Store, generate and restore SSH keypairs."""


SSH_SOURCES = ("generate", "import")


def _ssh_form(name: str | None) -> dict[str, str]:
    """`generate a key` vs `import that file`, as two rows rather than two flags."""
    from sekrt.tui import form

    return _fill(
        [
            form.Field("name", "name", placeholder="deploy-key", value=name or "",
                       required=True),
            form.Field("source", "source", choices=SSH_SOURCES),
            form.Field("key", "key file", placeholder="~/.ssh/id_ed25519  (import only)"),
            form.Field("comment", "comment", placeholder="optional"),
        ],
        title="new ssh key",
    )


@ssh.command("add")
@click.argument("name", required=False)
@click.option("--key", "key_path", type=click.Path(path_type=Path), default=None,
              help="Existing private key to import (e.g. ~/.ssh/id_ed25519).")
@click.option("--generate", "-g", "generate_", is_flag=True, help="Generate a new ed25519 key.")
@click.option("--comment", default="", help="Key comment (shown in .pub).")
@click.option("--force", "-f", is_flag=True, help="Overwrite an existing entry.")
@click.option("--interactive", "-i", is_flag=True, help="Fill the inline form even with a NAME.")
@friendly_errors
def ssh_add(name, key_path, generate_, comment, force, interactive) -> None:
    """Import or generate an SSH keypair into the vault.

    With no NAME (or with -i) an inline form asks for the name, whether to
    generate or import, and the key file if importing.
    """
    vault = get_vault()
    wants_form = use_form(name, interactive)  # see `add`: checks, passphrase, form
    key = obtain_key(vault)
    if wants_form:
        filled = _ssh_form(name)
        name, comment = filled["name"], filled["comment"] or comment
        generate_ = filled["source"] == "generate"
        key_path = None if generate_ else Path(filled["key"] or "")
        if not generate_ and not filled["key"]:
            raise click.ClickException("importing needs a key file — nothing saved")
    if bool(key_path) == generate_:
        raise click.ClickException("choose exactly one of --key PATH or --generate")
    if generate_:
        comment = comment or f"{name}@sekrt"
        private, public = sshtools.generate_ed25519(comment)
        filename = ""
    else:
        key_path = key_path.expanduser()
        private, public, file_comment = sshtools.load_keypair(key_path)
        comment = comment or file_comment
        filename = key_path.name
    entry_id = sshtools.store(
        vault, key, name, private=private, public=public,
        comment=comment, filename=filename, force=force,
    )
    click.secho(f"✔ stored {entry_id}", fg="green")
    if generate_ and public:
        click.echo("  public key (add it to GitHub/servers):\n")
        click.echo(f"  {public.strip()}")


@ssh.command("restore")
@click.argument("name")
@click.option("--dir", "directory", type=click.Path(path_type=Path), default=Path("~/.ssh"),
              show_default=True, help="Destination directory.")
@click.option("--filename", default=None, help="Override the key file name.")
@click.option("--force", "-f", is_flag=True, help="Overwrite existing files.")
@friendly_errors
def ssh_restore(name, directory, filename, force) -> None:
    """Write a stored keypair back to disk (0600/0644)."""
    vault = get_vault()
    key = obtain_key(vault)
    written = sshtools.restore(
        vault, key, name, directory=directory, filename=filename, force=force
    )
    for path in written:
        click.secho(f"✔ wrote {path}", fg="green")


@ssh.command("ls")
@friendly_errors
def ssh_ls() -> None:
    """List stored SSH keys."""
    vault = get_vault()
    for name in vault.list_entries("ssh/"):
        click.echo(name[len("ssh/"):])


@ssh.command("pub")
@click.argument("name")
@friendly_errors
def ssh_pub(name: str) -> None:
    """Print a stored key's public half (paste it into GitHub)."""
    vault = get_vault()
    key = obtain_key(vault)
    entry = vault.read(key, sshtools.full_name(name))
    public = entry["data"].get("public")
    if not public:
        raise click.ClickException(f"no public key stored for {name!r}")
    click.echo(public.strip())


# --------------------------------------------------------------------------- file


@main.group()
def file() -> None:
    """Store and restore whole files (binary-safe), encrypted."""


@file.command("add")
@click.argument("name")
@click.argument("path", type=click.Path(path_type=Path, exists=True, dir_okay=False))
@click.option("--force", "-f", is_flag=True, help="Overwrite an existing entry.")
@friendly_errors
def file_add(name: str, path: Path, force: bool) -> None:
    """Encrypt a file of any kind into the vault.

    \b
      sekrt file add mfa/github-recovery ~/Downloads/recovery-codes.txt
      sekrt file get mfa/github-recovery -o ./codes.txt
    """
    vault = get_vault()
    key = obtain_key(vault)
    entry_id = filetools.store(vault, key, name, path, force=force)
    click.secho(f"✔ stored {entry_id} ({path.stat().st_size} bytes)", fg="green")


@file.command("get")
@click.argument("name")
@click.option("--out", "-o", type=click.Path(path_type=Path), default=None,
              help="Destination path (default: original filename, in the current directory).")
@click.option("--force", "-f", is_flag=True, help="Overwrite an existing file.")
@friendly_errors
def file_get(name: str, out: Path | None, force: bool) -> None:
    """Decrypt a stored file back to disk."""
    vault = get_vault()
    key = obtain_key(vault)
    dest = filetools.restore(vault, key, name, out=out, force=force)
    click.secho(f"✔ wrote {dest}", fg="green")


@file.command("ls")
@friendly_errors
def file_ls() -> None:
    """List stored files."""
    vault = get_vault()
    for name in vault.list_entries(f"{filetools.FILE_PREFIX}/"):
        click.echo(name[len(filetools.FILE_PREFIX) + 1 :])


# --------------------------------------------------------------------------- colors


def _swatch(color: str) -> str:
    """A block of *color* itself — click drops the styling when it isn't a terminal."""
    return click.style("███", fg=_rgb(color))


def _chip(name: str, palette: prefs.Palette) -> str:
    """A preset as its three colors, then its name."""
    blocks = "".join(click.style("█", fg=_rgb(color)) for color in palette.to_dict().values())
    return f"{blocks} {name}"


def _echo_palette(palette: prefs.Palette) -> None:
    for role in prefs.ROLES:
        color = getattr(palette, role)
        click.echo(f"{role:<10}{color}  {_swatch(color)}  {prefs.ROLE_BLURBS[role]}")
    click.echo(f"{'preset':<10}{prefs.preset_name(palette) or '(custom)'}")
    path = prefs.prefs_path()
    saved = path.is_file()
    click.echo(f"\nstored in {path}" + ("" if saved else " (nothing saved yet — stock colors)"))


def _echo_presets() -> None:
    """The presets as rows of colored chips — the same rows the panel shows."""
    click.echo()
    for start in range(0, len(prefs.PRESET_NAMES), prefs.PRESETS_PER_ROW):
        row = prefs.PRESET_NAMES[start : start + prefs.PRESETS_PER_ROW]
        label = "presets" if start == 0 else ""
        chips = "  ".join(_chip(name, prefs.PRESETS[name]) for name in row)
        click.echo(f"{label:<10}{chips}")
    click.echo("          pick one with `sekrt config --preset NAME`, or run `sekrt config`")


@main.command()
@click.option("--preset", "preset_", type=click.Choice(prefs.PRESET_NAMES), default=None,
              help="Use a ready-made palette.")
@click.option("--primary", default=None, metavar="COLOR", help="Borders, titles, entry names.")
@click.option("--secondary", default=None, metavar="COLOR", help="Hints and muted text.")
@click.option("--accent", default=None, metavar="COLOR", help="Cursor, key hints, highlights.")
@click.option("--show", "show_", is_flag=True, help="Print the current colors and exit.")
@click.option("--reset", is_flag=True, help="Go back to the stock metal-and-red palette.")
@friendly_errors
def config(preset_, primary, secondary, accent, show_, reset) -> None:
    """Choose the colors the TUI and the picker draw themselves in.

    With no options at a terminal this opens a few lines of inline panel: ←/→
    walks the ready-made palettes and applies each as you land on it, and the
    three fields underneath are there when you'd rather name a color yourself
    (hex like `#00d7af` or `0d7`, or a name like `cyan`). The dark background is
    fixed — it is what keeps an accent readable.

    \b
      sekrt config                       # the panel
      sekrt config --preset teal         # a ready-made palette, no panel
      sekrt config --accent '#00d7af'    # set one color
      sekrt config --show                # what is set right now, and the presets
      sekrt config --reset               # back to metal & red
    """
    chosen = {"primary": primary, "secondary": secondary, "accent": accent}
    given = {role: value for role, value in chosen.items() if value is not None}

    if reset:
        if given or preset_:
            raise click.ClickException("--reset sets everything back — pass it on its own")
        prefs.reset_palette()
        click.secho("✔ colors reset", fg="green")
        _echo_palette(prefs.DEFAULT_PALETTE)
        return

    # A preset is a starting point: --preset teal --accent red keeps the accent.
    palette = prefs.preset(preset_) if preset_ else prefs.load_palette()

    if given or preset_:
        for role, value in given.items():
            palette = palette.with_color(role, value)
        path = prefs.save_palette(palette)
        click.secho(f"✔ colors saved to {path}", fg="green")
        _echo_palette(palette)
        return

    from sekrt.tui import picker

    if show_ or not picker.interactive():
        _echo_palette(palette)
        _echo_presets()
        return

    from sekrt.tui.colors import edit_palette

    picked = edit_palette(palette)
    if picked is None or picked == palette:
        click.echo("colors unchanged")
        return
    path = prefs.save_palette(picked)
    click.secho(f"✔ colors saved to {path}", fg="green")
    _echo_palette(picked)


# --------------------------------------------------------------------------- tui


@main.command()
@friendly_errors
def tui() -> None:
    """Open the interactive TUI (same as running `sekrt` with no arguments)."""
    from sekrt.tui.app import run_tui

    run_tui()


if __name__ == "__main__":
    main()
