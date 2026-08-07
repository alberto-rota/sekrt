"""tupacs command-line interface."""

from __future__ import annotations

import difflib
import functools
import json
import os
from pathlib import Path

import click

from tupacs import __version__, clipboard, envtools, gitsync, session, sshtools
from tupacs.clipboard import ClipboardError
from tupacs.crypto import CryptoError, WrongPassphraseError
from tupacs.generate import DEFAULT_LENGTH, generate_password, generate_token
from tupacs.util import EditorError, edit_text
from tupacs.vault import (
    PRIMARY_FIELD,
    Vault,
    VaultError,
    new_entry,
    primary_field,
)

SENSITIVE_FIELDS = {"password", "key", "secret", "token", "private", "content"}
MASK = "********"

ALIASES = {
    "insert": "add",
    "list": "ls",
    "remove": "rm",
    "delete": "rm",
    "rename": "mv",
    "search": "find",
    "gen": "generate",
    "ui": "tui",
}


class AliasedGroup(click.Group):
    def get_command(self, ctx, cmd_name):
        return super().get_command(ctx, ALIASES.get(cmd_name, cmd_name))


def friendly_errors(f):
    @functools.wraps(f)
    def wrapper(*args, **kwargs):
        try:
            return f(*args, **kwargs)
        except (VaultError, CryptoError, ClipboardError, EditorError) as exc:
            raise click.ClickException(str(exc)) from exc

    return wrapper


def get_vault(must_exist: bool = True) -> Vault:
    vault = Vault()
    if must_exist and not vault.initialized:
        raise click.ClickException(
            f"no vault found at {vault.path} — create one with `tupacs init`"
        )
    return vault


def obtain_key(vault: Vault) -> bytes:
    """Session cache -> $TUPACS_PASSPHRASE -> interactive prompt."""
    key = session.load_key(vault.path)
    if key is not None and vault.verify_key(key):
        return key
    phrase = os.environ.get("TUPACS_PASSPHRASE")
    if phrase is not None:
        return vault.unlock(phrase)
    for attempt in range(3):
        phrase = click.prompt("Passphrase", hide_input=True)
        try:
            return vault.unlock(phrase)
        except WrongPassphraseError:
            if attempt < 2:
                click.secho("wrong passphrase, try again", fg="red", err=True)
    raise click.ClickException("wrong passphrase (3 attempts)")


def _suggest(vault: Vault, name: str) -> str:
    matches = difflib.get_close_matches(name, vault.list_entries(), n=3, cutoff=0.5)
    return f" — did you mean: {', '.join(matches)}?" if matches else ""


@click.group(cls=AliasedGroup, invoke_without_command=True)
@click.version_option(version=__version__, prog_name="tupacs")
@click.pass_context
def main(ctx: click.Context) -> None:
    """🔐 tupacs — passwords, API keys, SSH keys and .env files, encrypted and git-synced.

    Run without arguments to open the TUI. Vault location: ~/.local/share/tupacs
    (override with $TUPACS_VAULT).
    """
    if ctx.invoked_subcommand is None:
        from tupacs.tui.app import run_tui

        run_tui()


# --------------------------------------------------------------------------- vault


@main.command()
@click.option("--remote", "remote_url", default=None, help="Git remote URL for sync.")
@friendly_errors
def init(remote_url: str | None) -> None:
    """Create a new vault (and its git repository)."""
    vault = get_vault(must_exist=False)
    if vault.initialized:
        raise click.ClickException(f"vault already exists at {vault.path}")
    phrase = os.environ.get("TUPACS_PASSPHRASE") or click.prompt(
        "Choose a vault passphrase", hide_input=True, confirmation_prompt=True
    )
    vault.create(phrase)
    if remote_url:
        gitsync.set_remote(vault.path, remote_url)
    click.secho(f"✔ vault created at {vault.path}", fg="green")
    if remote_url:
        click.echo(f"  remote set to {remote_url} — push with `tupacs sync`")
    else:
        click.echo("  connect a private GitHub repo with `tupacs remote <url>`")


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
    click.echo(f"remote    {remote or '(none — set with `tupacs remote <url>`)'}")
    click.echo(f"autosync  {'on' if vault.auto_sync else 'off'}")
    click.echo(f"session   {'unlocked, ' + str(ttl // 60) + ' min left' if ttl else 'locked'}")


# --------------------------------------------------------------------------- entries


@main.command()
@click.argument("name")
@click.option("--type", "-t", "type_", type=click.Choice(["password", "api_key", "note"]),
              default="password", show_default=True)
@click.option("--username", "-u", default=None, help="Username / login.")
@click.option("--url", default=None, help="Associated URL.")
@click.option("--notes", default=None, help="Free-form notes.")
@click.option("--generate", "-g", "generate_", is_flag=True, help="Generate the secret.")
@click.option("--length", "-L", default=DEFAULT_LENGTH, show_default=True)
@click.option("--no-symbols", is_flag=True, help="Generated secret: letters and digits only.")
@click.option("--show", "-s", is_flag=True, help="Print the generated secret.")
@click.option("--force", "-f", is_flag=True, help="Overwrite an existing entry.")
@friendly_errors
def add(name, type_, username, url, notes, generate_, length, no_symbols, show, force) -> None:
    """Add an entry (a password, an API key, or a note).

    \b
      tupacs add work/github -u alberto -g
      tupacs add cloud/aws-key -t api_key
      tupacs add wifi/office -t note --notes "WPA2 ..."
    """
    vault = get_vault()
    key = obtain_key(vault)

    data: dict[str, str] = {}
    secret_field = PRIMARY_FIELD[type_]
    if type_ == "note":
        text = notes if notes is not None else edit_text("", suffix=".txt")
        if not text:
            raise click.ClickException("empty note — nothing saved")
        data["notes"] = text
        notes = None
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
            click.echo("  generated secret stored — reveal with `tupacs get " + name + "`")


@main.command()
@click.argument("name")
@click.option("--field", "-f", "field", default=None, help="Field to output (default: the secret).")
@click.option("--copy", "-c", "copy_", is_flag=True, help="Copy to clipboard instead of printing.")
@friendly_errors
def get(name: str, field: str | None, copy_: bool) -> None:
    """Print (or copy) an entry's secret. Script-friendly: value only, to stdout."""
    vault = get_vault()
    if not vault.exists(name):
        raise click.ClickException(f"no entry named {name!r}{_suggest(vault, name)}")
    key = obtain_key(vault)
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


@main.command()
@click.argument("name")
@click.option("--reveal", "-r", is_flag=True, help="Show secret fields in clear text.")
@friendly_errors
def show(name: str, reveal: bool) -> None:
    """Show all fields of an entry (secrets masked unless --reveal)."""
    vault = get_vault()
    if not vault.exists(name):
        raise click.ClickException(f"no entry named {name!r}{_suggest(vault, name)}")
    key = obtain_key(vault)
    entry = vault.read(key, name)
    click.secho(name, bold=True)
    click.echo(f"  type: {entry['type']}")
    for field, value in entry["data"].items():
        hidden = field in SENSITIVE_FIELDS and not reveal
        if "\n" in value:
            if hidden:
                click.echo(f"  {field}: ({len(value.splitlines())} lines — use --reveal)")
            else:
                click.echo(f"  {field}:")
                for line in value.splitlines():
                    click.echo(f"    {line}")
        else:
            click.echo(f"  {field}: {MASK if hidden else value}")


@main.command()
@click.argument("prefix", default="")
@friendly_errors
def ls(prefix: str) -> None:
    """List entries (optionally under a folder prefix)."""
    vault = get_vault()
    names = vault.list_entries(prefix)
    if not names:
        click.echo("(vault is empty — add something with `tupacs add`)" if not prefix
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
@click.argument("name")
@friendly_errors
def edit(name: str) -> None:
    """Edit an entry's fields as JSON in $EDITOR."""
    vault = get_vault()
    if not vault.exists(name):
        raise click.ClickException(f"no entry named {name!r}{_suggest(vault, name)}")
    key = obtain_key(vault)
    entry = vault.read(key, name)
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
@click.argument("name")
@click.option("--force", "-f", is_flag=True, help="Skip confirmation.")
@friendly_errors
def rm(name: str, force: bool) -> None:
    """Delete an entry."""
    vault = get_vault()
    if not vault.exists(name):
        raise click.ClickException(f"no entry named {name!r}{_suggest(vault, name)}")
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
    gitsync.set_remote(vault.path, url)
    click.secho(f"✔ remote set to {url}", fg="green")
    click.echo("  run `tupacs sync` to push, `tupacs autosync on` to push automatically")


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
    """Run a raw git command inside the vault (e.g. `tupacs git log --oneline`)."""
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
        click.echo("(no env files stored — run `tupacs env push` inside a repo)")
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


# --------------------------------------------------------------------------- ssh


@main.group()
def ssh() -> None:
    """Store, generate and restore SSH keypairs."""


@ssh.command("add")
@click.argument("name")
@click.option("--key", "key_path", type=click.Path(path_type=Path), default=None,
              help="Existing private key to import (e.g. ~/.ssh/id_ed25519).")
@click.option("--generate", "-g", "generate_", is_flag=True, help="Generate a new ed25519 key.")
@click.option("--comment", default="", help="Key comment (shown in .pub).")
@click.option("--force", "-f", is_flag=True, help="Overwrite an existing entry.")
@friendly_errors
def ssh_add(name, key_path, generate_, comment, force) -> None:
    """Import or generate an SSH keypair into the vault."""
    if bool(key_path) == generate_:
        raise click.ClickException("choose exactly one of --key PATH or --generate")
    vault = get_vault()
    key = obtain_key(vault)
    if generate_:
        comment = comment or f"{name}@tupacs"
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


# --------------------------------------------------------------------------- tui


@main.command()
@friendly_errors
def tui() -> None:
    """Open the interactive TUI (same as running `tupacs` with no arguments)."""
    from tupacs.tui.app import run_tui

    run_tui()


if __name__ == "__main__":
    main()
