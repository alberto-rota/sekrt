"""sekrt command-line interface."""

from __future__ import annotations

import difflib
import functools
import json
import os
import re
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import click
from click.shell_completion import CompletionItem

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
from sekrt.generate import generate_password, generate_token
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


def _completion_names(ctx: click.Context) -> list[str]:
    """Entry names the shell may offer, or nothing when the vault is locked.

    ``ssh`` and ``file`` take the name without their folder prefix, the same
    way ``ssh ls`` and ``file ls`` print it. Every other command takes the
    full logical name. The session key is not loaded: unlock is the expiry
    on the cache file, and the names are the vault's filenames.
    """
    vault = Vault()
    if not vault.initialized or not session.unlocked(vault.path):
        return []
    parent = ctx.parent.info_name if ctx.parent is not None else None
    if parent == "ssh":
        prefix = f"{sshtools.SSH_PREFIX}/"
    elif parent == "file":
        prefix = f"{filetools.FILE_PREFIX}/"
    else:
        prefix = ""
    names = vault.list_entries(prefix)
    if prefix:
        names = [name[len(prefix) :] for name in names]
    return names


def complete_entry(
    ctx: click.Context, _param: click.Parameter, incomplete: str
) -> list[CompletionItem]:
    """Tab-complete an entry name, only while ``sekrt unlock`` is in effect."""
    try:
        names = _completion_names(ctx)
    except (VaultError, OSError):
        return []
    return [CompletionItem(name) for name in names if name.startswith(incomplete)]


def complete_named_entry(
    ctx: click.Context, param: click.Parameter, incomplete: str
) -> list[CompletionItem]:
    """The entry half of ``-e VAR=ENTRY``. A bare ``VAR`` is not an entry name."""
    var, sep, partial = incomplete.partition("=")
    if not sep:
        return []
    return [
        CompletionItem(f"{var}={item.value}")
        for item in complete_entry(ctx, param, partial)
    ]


def entry_argument(name: str, **kwargs: object):
    """An argument that names an entry. Completes only while the vault is unlocked."""
    return click.argument(name, shell_complete=complete_entry, **kwargs)


def _suggest(vault: Vault, name: str) -> str:
    matches = difflib.get_close_matches(name, vault.list_entries(), n=3, cutoff=0.5)
    return f" — did you mean: {', '.join(matches)}?" if matches else ""


def _tilde(path: Path) -> str:
    """``~/…`` when *path* is under ``$HOME``, otherwise the path as written."""
    try:
        return "~/" + path.expanduser().resolve().relative_to(Path.home().resolve()).as_posix()
    except ValueError:
        return str(path)


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
@click.option(
    "--timeout", "-t", type=int, default=None,
    help=f"Minutes to stay unlocked (default: `sekrt config`, or {prefs.DEFAULT_UNLOCK_MINUTES}).",
)
@friendly_errors
def unlock(timeout: int | None) -> None:
    """Cache the vault key so commands stop prompting for a while.

    On a terminal, this also installs tab completion for the shell that ran
    it, into a directory that shell already loads. zsh reads that file the
    next time it starts.
    """
    if timeout is None:
        timeout = prefs.load_settings().unlock_minutes
    vault = get_vault()
    key = obtain_key(vault)
    if not session.store_key(vault.path, key, ttl=timeout * 60):
        raise click.ClickException("no private runtime directory available for the session cache")
    where = "RAM-backed" if session.is_ram_backed() else "temp-dir (not RAM-backed)"
    click.secho(f"✔ unlocked for {timeout} min ({where} session cache)", fg="green")
    _offer_completion_install()


@main.command()
@friendly_errors
def lock() -> None:
    """Forget the cached vault key."""
    vault = get_vault()
    session.clear(vault.path)
    click.secho("✔ locked", fg="green")


_SHELLS = frozenset({"bash", "zsh", "fish"})


def completion_source(shell: str) -> str:
    """The static completion script for *shell*. No entry names, no key."""
    from click.shell_completion import get_completion_class

    cls = get_completion_class(shell)
    if cls is None:
        raise click.ClickException(f"unsupported shell {shell!r}")
    return cls(main, {}, "sekrt", "_SEKRT_COMPLETE").source()


def _completion_source_quiet(shell: str) -> str:
    """The completion script, without Click's bash-version warning.

    ``sekrt completion bash`` still prints that warning. ``sekrt unlock``
    should not: it writes the script either way.
    """
    import contextlib
    import io

    with contextlib.redirect_stderr(io.StringIO()):
        return completion_source(shell)


def invoking_shell() -> str | None:
    """The shell that ran sekrt, when it is one we can complete for."""
    name = _process_name(os.getppid())
    if name in _SHELLS:
        return name
    fallback = Path(os.environ.get("SHELL", "")).name
    return fallback if fallback in _SHELLS else None


def _process_name(pid: int) -> str:
    try:
        comm = subprocess.check_output(
            ["ps", "-o", "comm=", "-p", str(pid)],
            text=True,
            stderr=subprocess.DEVNULL,
        )
    except (OSError, subprocess.CalledProcessError):
        return ""
    return Path(comm.strip()).name.lstrip("-")


def _completion_dir_ok(directory: Path) -> bool:
    """A directory we may drop a completion script into.

    It has to exist, be owned by us, and not be world-writable: the shell
    will execute whatever lands there.
    """
    try:
        st = directory.stat()
    except OSError:
        return False
    if not stat.S_ISDIR(st.st_mode) or st.st_mode & stat.S_IWOTH:
        return False
    if hasattr(os, "getuid") and st.st_uid != os.getuid():
        return False
    return os.access(directory, os.W_OK)


def _zsh_completion_dir() -> Path | None:
    """The first safe directory already on ``$FPATH``.

    zsh exported that list when it started, and ``compinit`` scans it. Writing
    here is how a new terminal learns the script without an rc change.
    """
    for raw in os.environ.get("FPATH", "").split(":"):
        if raw and _completion_dir_ok(Path(raw)):
            return Path(raw)
    return None


def _bash_completion_dir() -> Path:
    if custom := os.environ.get("BASH_COMPLETION_USER_DIR"):
        return Path(custom) / "completions"
    data = os.environ.get("XDG_DATA_HOME")
    base = Path(data) if data else Path.home() / ".local" / "share"
    return base / "bash-completion" / "completions"


def _fish_completion_dir() -> Path:
    config = os.environ.get("XDG_CONFIG_HOME")
    base = Path(config) if config else Path.home() / ".config"
    return base / "fish" / "completions"


def _write_if_changed(dest: Path, text: str) -> bool:
    """Write *text* to *dest*. False when the file already holds it."""
    data = text.encode()
    try:
        if dest.is_file() and dest.read_bytes() == data:
            return False
    except OSError:
        pass
    tmp = dest.with_name(dest.name + ".tmp")
    try:
        tmp.write_bytes(data)
        os.chmod(tmp, 0o644)
        os.replace(tmp, dest)
    except OSError:
        tmp.unlink(missing_ok=True)
        raise
    return True


def install_completion(shell: str) -> tuple[Path, bool] | None:
    """Install the completion script where *shell* loads it on its own.

    Returns ``(path, changed)``, or None when this shell has nowhere safe to
    put it. The script is static: later unlocks leave an unchanged file alone,
    so zsh's compinit dump stays valid.
    """
    if shell == "zsh":
        directory = _zsh_completion_dir()
        if directory is None:
            return None
        name = "_sekrt"
    elif shell == "bash":
        directory = _bash_completion_dir()
        directory.mkdir(parents=True, exist_ok=True)
        name = "sekrt"
    elif shell == "fish":
        directory = _fish_completion_dir()
        directory.mkdir(parents=True, exist_ok=True)
        name = "sekrt.fish"
    else:
        return None
    dest = directory / name
    return dest, _write_if_changed(dest, _completion_source_quiet(shell))


def _offer_completion_install() -> None:
    """Install completion for an interactive unlock. A pipe never writes a file."""
    if not _stdout_is_tty():
        return
    shell = invoking_shell()
    if shell is None:
        return
    try:
        installed = install_completion(shell)
    except OSError:
        return
    if installed is None:
        if shell == "zsh":
            click.echo("  `sekrt completion zsh` prints the tab-completion snippet")
        return
    _path, changed = installed
    if not changed:
        return
    if shell == "zsh":
        click.echo("  entry names tab-complete in a new terminal while the vault is unlocked")
    else:
        click.echo("  entry names tab-complete while the vault is unlocked")


@main.command()
@click.argument("shell", type=click.Choice(("bash", "zsh", "fish")))
def completion(shell: str) -> None:
    """Print the snippet that teaches your shell to complete entry names.

    ``sekrt unlock`` installs this itself on a terminal. The snippet is static:
    it does not contain your entry names, and names are offered only while the
    vault is unlocked.

    \b
      eval "$(sekrt completion zsh)"   # only if unlock could not install it
      eval "$(sekrt completion bash)"  # bash 4.4 or newer
      sekrt completion fish > ~/.config/fish/completions/sekrt.fish
    """
    click.echo(completion_source(shell))


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
@entry_argument("name", required=False)
@click.option("--type", "-t", "type_", type=click.Choice(ADD_TYPES),
              default="password", show_default=True)
@click.option("--username", "-u", default=None, help="Username / login.")
@click.option("--url", default=None, help="Associated URL.")
@click.option("--notes", default=None, help="Free-form notes.")
@click.option("--generate", "-g", "generate_", is_flag=True, help="Generate the secret.")
@click.option(
    "--length", "-L", type=int, default=None,
    help=f"Generated secret length (default: `sekrt config`, or {prefs.DEFAULT_PASSWORD_LENGTH}).",
)
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
    if length is None:
        length = prefs.load_settings().password_length
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
            click.echo(f"  generated {length}-char secret copied to clipboard ({_clears_in()})")
        else:
            click.echo("  generated secret stored — reveal with `sekrt get " + name + "`")


@main.command()
@entry_argument("name", required=False)
@click.option("--field", "-f", "field", default=None, help="Field to output (default: the secret).")
@click.option("--copy", "-c", "copy_", is_flag=True, help="Copy to clipboard instead of printing.")
@friendly_errors
def get(name: str | None, field: str | None, copy_: bool) -> None:
    """Print (or copy) an entry's secret. Script-friendly: value only, to stdout.

    \b
      sekrt get cloud/aws-key        # exact name
      sekrt get aws                  # partial: pick from the matches
      sekrt get                      # pick from every entry

    At a terminal, a green ``press c to copy`` waits under the secret; ``c``
    copies it. ``-c`` copies without printing, for scripts.
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
        click.secho(f"✔ {name}:{field} copied to clipboard ({_clears_in()})", fg="green", err=True)
        return
    click.echo(value)
    _offer_get_copy(value)


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


def _stdout_is_tty() -> bool:
    try:
        return sys.stdout.isatty()
    except (AttributeError, ValueError):
        return False


def _offer_get_copy(value: str) -> None:
    """Green ``press c to copy`` under a printed secret.

    Stdout must be a terminal too: ``sekrt get | pbcopy`` should not wait for
    a key, and the prompt stays off a redirect.
    """
    if not _stdout_is_tty() or not _at_terminal() or not clipboard.available():
        return
    click.secho("press c to copy", fg="green", err=True)
    key = clipboard.read_key()
    if key and key.lower() == "c":
        clipboard.copy(value)


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
        click.secho(f"  ✔ {field} copied to clipboard ({_clears_in()})", fg="green", err=True)


@main.command()
@entry_argument("name", required=False)
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
@entry_argument("prefix", default="")
@friendly_errors
def ls(prefix: str) -> None:
    """List entries (optionally under a folder prefix)."""
    vault = get_vault()
    obtain_key(vault)
    names = vault.list_entries(prefix)
    if not names:
        click.echo("(vault is empty — add something with `sekrt add`)" if not prefix
                   else f"(nothing under {prefix!r})")
        return
    for name in names:
        click.echo(name)


@main.command()
@entry_argument("query")
@friendly_errors
def find(query: str) -> None:
    """Search entry names."""
    vault = get_vault()
    for name in vault.search(query):
        click.echo(name)


@main.command()
@entry_argument("name", required=False)
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
@entry_argument("old")
@entry_argument("new")
@click.option("--force", "-f", is_flag=True, help="Overwrite the destination.")
@friendly_errors
def mv(old: str, new: str, force: bool) -> None:
    """Rename / move an entry."""
    vault = get_vault()
    key = obtain_key(vault)
    vault.move(key, old, new, overwrite=force)
    click.secho(f"✔ {old} -> {new}", fg="green")


@main.command()
@entry_argument("name", required=False)
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
@click.argument("length", required=False, type=int, default=None)
@click.option("--no-symbols", is_flag=True, help="Letters and digits only.")
@click.option("--token", is_flag=True, help="URL-safe token instead (for API keys).")
@click.option("--copy", "-c", "copy_", is_flag=True, help="Copy instead of printing.")
@friendly_errors
def generate(length: int | None, no_symbols: bool, token: bool, copy_: bool) -> None:
    """Generate a random password (not stored)."""
    if length is None:
        length = prefs.load_settings().password_length
    secret = generate_token() if token else generate_password(length, symbols=not no_symbols)
    if copy_:
        clipboard.copy(secret)
        click.secho(f"✔ copied to clipboard ({_clears_in()})", fg="green", err=True)
    else:
        click.echo(secret)


# --------------------------------------------------------------------------- sync


@main.command()
@click.argument("url", required=False)
@click.option("-v", "--verbose", is_flag=True, help="Print the current remote URL.")
@friendly_errors
def remote(url: str | None, verbose: bool) -> None:
    """Set or print the git remote used for sync (e.g. a private GitHub repo)."""
    vault = get_vault()
    if verbose and url is not None:
        raise click.UsageError("pass a URL to set the remote, or -v to print it, not both")
    if url is None:
        current = gitsync.get_remote(vault.path)
        if current is None:
            raise click.ClickException("no remote configured — run `sekrt remote <url>` first")
        click.echo(current)
        return
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


def _note_realign(vault: Vault, key: bytes, slug: str | None = None) -> None:
    """Print once if origin moved and stored env files were retagged."""
    if slug is not None:
        return
    notice = envtools.realign(vault, key)
    if notice:
        click.secho(notice, fg="green")


@env.command("push")
@click.argument("files", nargs=-1, type=click.Path(path_type=Path))
@friendly_errors
def env_push(files: tuple[Path, ...]) -> None:
    """Encrypt .env file(s) of the current repo into the vault."""
    vault = get_vault()
    key = obtain_key(vault)
    _note_realign(vault, key)
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
    _note_realign(vault, key, slug)
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
    current = envtools.resolve_slug(vault, envtools.current_context()[1])
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
    slug = envtools.resolve_slug(vault, envtools.current_context()[1])
    entry = vault.read(key, envtools.entry_name(slug, file))
    click.echo(entry["data"]["content"], nl=False)


@env.command("rm")
@click.argument("file", default=".env")
@click.option("--force", "-f", is_flag=True, help="Skip confirmation.")
@friendly_errors
def env_rm(file: str, force: bool) -> None:
    """Remove a stored env file for the current repo."""
    vault = get_vault()
    slug = envtools.resolve_slug(vault, envtools.current_context()[1])
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
                     shell_complete=complete_named_entry,
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
) -> tuple[list[runtools.Exposure], list[tuple[str, str]]]:
    """Decrypt what the command asked for, and nothing else.

    Whether there is anything to expose at all is settled from entry *names*,
    which are plaintext — so a command that was never going to get a variable
    says so instead of asking for the passphrase first.
    """
    referenced = referenced or []
    slug = envtools.resolve_slug(vault, slug or envtools.current_context()[1])
    stored = [] if no_env_files else envtools.stored_files(vault, slug)
    if not requested and not referenced and not stored and not runtools.might_expose(vault):
        raise click.ClickException(
            "nothing to expose — the vault holds no password or API key entries"
            + (f", and no env files are stored for {slug!r}" if not no_env_files else "")
            + ".\n  add one with `sekrt add`, or store this repo's env file with "
            "`sekrt env push`"
        )

    key = obtain_key(vault)
    resolver = runtools.Resolver(vault, key, slug=slug, env_files=not no_env_files)
    exposures, unresolved = runtools.resolve(
        resolver, requested=requested, referenced=referenced
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


@main.command()
@expose_options
@friendly_errors
def shell(requested, slug, no_env_files, dry_run) -> None:
    """Open a subshell holding vault secrets; they are gone when you `exit`.

    "Expose my tokens for a bit", bounded: the variables live in that shell and
    whatever you start from it, and nothing outside it. Chosen exactly as for
    `sekrt run` — everything the vault can offer, narrowed by -e.

    \b
      sekrt shell                        # every password and API key, + this repo's
      sekrt shell -e MY_TOKEN            # only this one
      sekrt shell -n                     # what would be exposed, without opening it
      exit                               # ...and they are gone
    """
    vault = get_vault()
    exposures, _ = _exposures(vault, requested, slug, no_env_files)

    if dry_run:
        _echo_plan(exposures, [runtools.default_shell()])
        return
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
@entry_argument("name", required=False)
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
        # Unindented: a double-click selects the key, and a half-width
        # terminal (the two-pane demo) does not wrap it.
        click.echo(public.strip())


@ssh.command("restore")
@entry_argument("name")
@click.option("--dir", "directory", type=click.Path(path_type=Path), default=Path("~/.ssh"),
              show_default=True, help="Destination directory.")
@click.option("--filename", default=None, help="Override the key file name.")
@click.option("--force", "-f", is_flag=True, help="Overwrite existing files.")
@click.option("--authorize", "-a", is_flag=True,
              help="Also append the public key to authorized_keys in --dir.")
@friendly_errors
def ssh_restore(name, directory, filename, force, authorize) -> None:
    """Write a stored keypair back to disk (0600/0644).

    With --authorize, the public key is also appended to authorized_keys
    in --dir so this machine accepts the key for login.
    """
    vault = get_vault()
    key = obtain_key(vault)
    written = sshtools.restore(
        vault, key, name, directory=directory, filename=filename, force=force,
        authorize=authorize,
    )
    for path in written:
        verb = "authorized" if path.name == "authorized_keys" else "wrote"
        click.secho(f"✔ {verb} {_tilde(path)}", fg="green")


@ssh.command("ls")
@friendly_errors
def ssh_ls() -> None:
    """List stored SSH keys."""
    vault = get_vault()
    for name in vault.list_entries("ssh/"):
        click.echo(name[len("ssh/"):])


@ssh.command("pub")
@entry_argument("name")
@friendly_errors
def ssh_pub(name: str) -> None:
    """Print a stored key's public half (paste it into GitHub)."""
    vault = get_vault()
    key = obtain_key(vault)
    entry = vault.read(key, sshtools.full_name(name))
    public = sshtools.public_line(entry["data"])
    if not public:
        raise click.ClickException(f"no public key stored for {name!r}")
    click.echo(public.strip())


@ssh.command("authorize")
@entry_argument("name")
@click.option("--dir", "directory", type=click.Path(path_type=Path), default=Path("~/.ssh"),
              show_default=True, help="Directory containing authorized_keys.")
@friendly_errors
def ssh_authorize(name, directory) -> None:
    """Append a stored public key to authorized_keys (this machine accepts it).

    Does not write the private key. For a new laptop that also needs the
    keypair on disk, use `sekrt ssh restore NAME --authorize` instead.
    """
    vault = get_vault()
    key = obtain_key(vault)
    path, added = sshtools.authorize(vault, key, name, directory=directory)
    verb = "authorized" if added else "already in"
    click.secho(f"✔ {verb} {_tilde(path)}", fg="green")


# --------------------------------------------------------------------------- file


@main.group()
def file() -> None:
    """Store and restore whole files (binary-safe), encrypted."""


@file.command("add")
@entry_argument("name")
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
    size = path.stat().st_size
    entry_id = filetools.store(vault, key, name, path, force=force)
    click.secho(f"✔ stored {entry_id} ({size} bytes)", fg="green")
    if size > filetools.WARN_FILE_BYTES:
        mb = size / (1024 * 1024)
        click.secho(
            f"note: this file is {mb:.1f} MB. Encryption makes it larger still, "
            "and GitHub/GitLab reject blobs over 100 MB — `sekrt sync` will fail, "
            "and `sekrt rm` will not drop the blob from vault history.\n"
            "  stored locally; do not sync. undo this add with: "
            "sekrt git reset --hard HEAD~1",
            fg="yellow",
            err=True,
        )


@file.command("get")
@entry_argument("name")
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


def _clears_in() -> str:
    """The clipboard sentence, using this machine's configured delay."""
    return f"clears in {prefs.load_settings().clipboard_seconds}s"


def _echo_settings() -> None:
    settings = prefs.load_settings()
    rows = (
        ("unlock", f"{settings.unlock_minutes} min", "unlock_minutes"),
        ("clipboard", f"{settings.clipboard_seconds} s", "clipboard_seconds"),
        ("length", str(settings.password_length), "password_length"),
    )
    for label, value, key in rows:
        click.echo(f"{label:<10}{value:<8}{prefs.SETTING_BLURBS[key]}")


def _swatch(color: str) -> str:
    """A block of *color* itself — click drops the styling when it isn't a terminal."""
    return click.style("███", fg=_rgb(color))


def _chip(name: str, palette: prefs.Palette) -> str:
    """A preset as its three colors, then its name."""
    blocks = "".join(click.style("█", fg=_rgb(color)) for color in palette.to_dict().values())
    return f"{blocks} {name}"


def _echo_where() -> None:
    path = prefs.prefs_path()
    saved = path.is_file()
    note = "" if saved else " (nothing saved yet — stock defaults)"
    click.echo(f"\nstored in {path}{note}")


def _echo_palette(palette: prefs.Palette, *, where: bool = True) -> None:
    for role in prefs.ROLES:
        color = getattr(palette, role)
        click.echo(f"{role:<10}{color}  {_swatch(color)}  {prefs.ROLE_BLURBS[role]}")
    click.echo(f"{'preset':<10}{prefs.preset_name(palette) or '(custom)'}")
    if where:
        _echo_where()


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
@click.option(
    "--unlock", type=click.IntRange(*prefs.UNLOCK_MINUTES_RANGE), default=None, metavar="MIN",
    help=(
        "Minutes `sekrt unlock` stays open, "
        f"{prefs.UNLOCK_MINUTES_RANGE[0]}–{prefs.UNLOCK_MINUTES_RANGE[1]} "
        f"(default {prefs.DEFAULT_UNLOCK_MINUTES})."
    ),
)
@click.option(
    "--clipboard", type=click.IntRange(*prefs.CLIPBOARD_SECONDS_RANGE), default=None,
    metavar="SEC",
    help=(
        "Seconds before a copied secret is cleared, "
        f"{prefs.CLIPBOARD_SECONDS_RANGE[0]}–{prefs.CLIPBOARD_SECONDS_RANGE[1]} "
        f"(default {prefs.DEFAULT_CLIPBOARD_SECONDS})."
    ),
)
@click.option(
    "--length", "length_", type=click.IntRange(*prefs.PASSWORD_LENGTH_RANGE), default=None,
    metavar="N",
    help=(
        "Length of a generated secret, "
        f"{prefs.PASSWORD_LENGTH_RANGE[0]}–{prefs.PASSWORD_LENGTH_RANGE[1]} "
        f"(default {prefs.DEFAULT_PASSWORD_LENGTH})."
    ),
)
@click.option("--show", "show_", is_flag=True,
              help="Print the current colors, defaults and presets.")
@click.option("--reset", is_flag=True, help="Go back to the stock metal-and-red palette.")
@friendly_errors
def config(preset_, primary, secondary, accent, unlock, clipboard, length_, show_, reset) -> None:
    """Choose colors, and the defaults the other commands use.

    With no options at a terminal this opens a few lines of inline panel: ←/→
    walks the ready-made palettes and applies each as you land on it, and the
    three fields underneath are there when you'd rather name a color yourself
    (hex like `#00d7af` or `0d7`, or a name like `cyan`). The dark background is
    fixed — it is what keeps an accent readable.

    The other three are this machine's defaults, in the same file: how long
    ``sekrt unlock`` stays open, how long a copied secret stays on the
    clipboard, and how long a generated secret is. A flag on the command
    (``sekrt unlock -t``, ``sekrt generate 32``, ``sekrt add -L``) still wins
    for that one run. ``--reset`` puts the colors back and leaves these three.

    \b
      sekrt config                       # the color panel
      sekrt config --preset teal         # a ready-made palette, no panel
      sekrt config --accent '#00d7af'    # set one color
      sekrt config --unlock 120          # `sekrt unlock` stays open for 2 hours
      sekrt config --clipboard 15        # copied secrets clear after 15 seconds
      sekrt config --length 32           # generated secrets are 32 characters
      sekrt config --show                # what is set right now, and the presets
      sekrt config --reset               # colors back to metal & red
    """
    chosen = {"primary": primary, "secondary": secondary, "accent": accent}
    given = {role: value for role, value in chosen.items() if value is not None}
    tuned = {
        key: value
        for key, value in (
            ("unlock_minutes", unlock),
            ("clipboard_seconds", clipboard),
            ("password_length", length_),
        )
        if value is not None
    }

    if reset:
        if given or preset_ or tuned:
            raise click.ClickException("--reset sets the colors back — pass it on its own")
        prefs.reset_palette()
        click.secho("✔ colors reset", fg="green")
        _echo_palette(prefs.DEFAULT_PALETTE, where=False)
        _echo_settings()
        _echo_where()
        return

    # A preset is a starting point: --preset teal --accent red keeps the accent.
    palette = prefs.preset(preset_) if preset_ else prefs.load_palette()
    saved_colors = bool(given or preset_)
    if saved_colors:
        for role, value in given.items():
            palette = palette.with_color(role, value)
        prefs.save_palette(palette)
    if tuned:
        prefs.save_settings(**tuned)

    if saved_colors or tuned:
        path = prefs.prefs_path()
        what = "config" if tuned else "colors"
        click.secho(f"✔ {what} saved to {path}", fg="green")
        if saved_colors:
            _echo_palette(palette, where=not tuned)
        if tuned:
            _echo_settings()
            _echo_where()
        return

    from sekrt.tui import picker

    if show_ or not picker.interactive():
        _echo_palette(palette, where=False)
        _echo_settings()
        _echo_where()
        _echo_presets()
        return

    from sekrt.tui.colors import edit_palette

    before = prefs.load_settings()
    picked = edit_palette(palette, before)
    if picked is None:
        click.echo("config unchanged")
        return
    # A test double may still return just a palette.
    settings = None
    if isinstance(picked, tuple):
        picked, settings = picked
    same_settings = settings is None or settings == before
    if picked == palette and same_settings:
        click.echo("config unchanged")
        return
    if picked != palette:
        prefs.save_palette(picked)
    if settings is not None and settings != before:
        prefs.save_settings(**settings.to_dict())
    path = prefs.prefs_path()
    click.secho(f"✔ config saved to {path}", fg="green")
    _echo_palette(picked, where=False)
    _echo_settings()
    _echo_where()


# --------------------------------------------------------------------------- tui


@main.command()
@friendly_errors
def tui() -> None:
    """Open the interactive TUI (same as running `sekrt` with no arguments)."""
    from sekrt.tui.app import run_tui

    run_tui()


if __name__ == "__main__":
    main()
