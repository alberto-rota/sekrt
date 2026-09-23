"""Handing secrets to one process, for exactly as long as it runs.

``sekrt expose && service log --token="$MY_TOKEN"`` cannot be made to work: a
child process cannot set variables in the shell that started it, and the one
shape that could — ``eval "$(sekrt expose)"`` — leaves every secret sitting in
the shell's environment for the rest of the session, inherited by everything
started from it, with nothing to say when it should stop. So the exposure goes
the other way round: sekrt keeps the secrets and *wraps* the command.

    sekrt run 'service log'                        # secrets in its environment
    sekrt run 'service log --token="$MY_TOKEN"'    # ...a shell expands them
    sekrt run -- service log --flag-of-its-own     # ...an argv, run directly
    sekrt shell                                    # a subshell; `exit` revokes

The child's environment is the only place a value is written. Nothing touches
the disk, nothing is left in the calling shell, and when the process ends the
last copy goes with it.

Two sources decide what a command gets:

1. every password and API key in the vault, under the variable its name reads as
   — ``api/my-token`` answers ``$MY_TOKEN``;
2. the ``.env`` files this repository has stored in the vault (``sekrt env
   push``) — the same variables the process would have had from the file itself,
   spelled the way the repo spells them, and winning over a vault-wide name.

Naming variables (``-e MY_TOKEN``, ``-e MY_TOKEN=some/other/entry``) *narrows*
the first source to those, which is how a command gets one secret rather than
all of them. What is never handed over either way is ``$SEKRT_PASSPHRASE``: it
is stripped from the child, so a wrapped command holding one secret cannot go
and decrypt the rest.
"""

from __future__ import annotations

import difflib
import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from sekrt import compat, envtools, session
from sekrt.vault import Vault, VaultError, _atomic_write, primary_field

# Shell-style variable references, so a `-c` command tells us which secrets it
# needs without being asked twice. `$$` is a shell's own PID rather than a
# reference, so it is matched first and discarded — `$$FOO` mentions nothing.
_REFERENCE = re.compile(r"\$\$|\$(?:([A-Za-z_]\w*)|\{([A-Za-z_]\w*)\})")

_VAR_NAME = re.compile(r"[A-Za-z_]\w*", re.ASCII)

# Never inherited by a wrapped command: the passphrase is the key to everything
# in the vault, and `run` exists to hand over one thing.
STRIPPED_VARS = (compat.PREFIX + "PASSPHRASE", compat.LEGACY_PREFIX + "PASSPHRASE")

# The *names* of what was exposed (never the values), so a shell prompt can say
# it is running inside an exposure. Entry names are already plaintext metadata.
MARKER_VAR = compat.PREFIX + "EXPOSED"

# Entry types whose secret is a *value* a program can read out of a variable.
# A note is prose, an SSH key belongs in a file (`sekrt ssh restore`), a stored
# file is bytes — none of them is what an unnamed `sekrt run` should hand over,
# though `-e VAR=entry` will still expose one if that is what you mean.
EXPOSABLE_TYPES = ("password", "api_key")

# Prefixes owned by the subcommands that write those types, so recognising them
# costs no decryption: entry names are plaintext.
_MANAGED_PREFIXES = ("env/", "ssh/", "file/")


class ExposeError(VaultError):
    """A variable a command asked for cannot be answered from the vault."""


@dataclass(frozen=True)
class Exposure:
    """One variable, its value, and the entry it came from."""

    var: str
    value: str
    origin: str  # for `--dry-run` to name a source without printing a secret


def references(text: str) -> list[str]:
    """The ``$VAR`` / ``${VAR}`` names *text* mentions, in order, without repeats."""
    found: list[str] = []
    for match in _REFERENCE.finditer(text):
        name = match.group(1) or match.group(2)
        if name and name not in found:
            found.append(name)
    return found


def is_var_name(text: str) -> bool:
    return bool(_VAR_NAME.fullmatch(text))


def var_name(entry_name: str) -> str:
    """The variable an entry answers to by default: ``api/my-token`` → ``MY_TOKEN``."""
    return re.sub(r"\W", "_", entry_name.rsplit("/", 1)[-1], flags=re.ASCII).upper()


def parse_env(content: str) -> dict[str, str]:
    """The ``KEY=VALUE`` pairs of a ``.env`` file, in file order.

    Deliberately small: ``export`` prefixes, ``#`` comments, blank lines and one
    layer of surrounding quotes are what these files actually hold. Anything
    else stays the literal text it is — this reads a file sekrt stored, it does
    not emulate a shell.
    """
    values: dict[str, str] = {}
    for raw in content.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, _, value = line.partition("=")
        name = name.strip().removeprefix("export ").strip()
        if not is_var_name(name):
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        values[name] = value
    return values


class Resolver:
    """Where the value behind a variable name comes from.

    Reads the vault lazily and only where it has to: entry *names* are
    plaintext, so answering ``$MY_TOKEN`` from ``api/my-token`` costs one
    decryption rather than a walk through the whole vault.
    """

    def __init__(
        self,
        vault: Vault,
        key: bytes,
        *,
        slug: str | None = None,
        cwd: Path | None = None,
        env_files: bool = True,
    ) -> None:
        self.vault = vault
        self.key = key
        self.env_files = env_files
        self.slug = envtools.resolve_slug(vault, slug or envtools.current_context(cwd)[1])
        self._stored: dict[str, Exposure] | None = None
        self._bulk: dict[str, Exposure] | None = None
        # Variables two entries both answer to, filled in by `bulk`.
        self.ambiguous: dict[str, list[str]] = {}

    @property
    def stored(self) -> dict[str, Exposure]:
        """Every variable this repository's stored env files define.

        Several files for one repo (``.env``, ``.env.local``) are read in name
        order, later ones winning — the precedence the files themselves have
        when a process loads them in that order.
        """
        if self._stored is None:
            self._stored = {}
            if self.env_files:
                for relpath in sorted(envtools.stored_files(self.vault, self.slug)):
                    name = envtools.entry_name(self.slug, relpath)
                    content = self.vault.read(self.key, name)["data"].get("content", "")
                    for var, value in parse_env(content).items():
                        self._stored[var] = Exposure(var, value, name)
        return self._stored

    @property
    def bulk(self) -> dict[str, Exposure]:
        """Every password and API key, under the variable its name reads as.

        What an unnamed ``sekrt run`` hands over. Two things are left out rather
        than guessed at: a name that is not a variable name (``2fa/backup`` wants
        to be ``$2FA_BACKUP``, which no shell will accept), and a variable two
        entries both answer to — picking one of two secrets silently is worse than
        leaving it unset, so those are collected in :attr:`ambiguous` for the
        caller to complain about and named with ``-e`` instead.
        """
        if self._bulk is None:
            candidates: dict[str, list[Exposure]] = {}
            for name in self.vault.list_entries():
                var = var_name(name)
                if name.startswith(_MANAGED_PREFIXES) or not is_var_name(var):
                    continue
                entry = self.vault.read(self.key, name)
                if entry.get("type") not in EXPOSABLE_TYPES:
                    continue
                field = primary_field(entry)
                if field is None:
                    continue
                candidates.setdefault(var, []).append(
                    Exposure(var, entry["data"][field], f"{name}:{field}")
                )
            self._bulk = {}
            self.ambiguous = {}
            for var, matches in candidates.items():
                if len(matches) == 1:
                    self._bulk[var] = matches[0]
                else:
                    self.ambiguous[var] = [m.origin.rsplit(":", 1)[0] for m in matches]
        return self._bulk

    def from_entry(self, var: str, entry_name: str) -> Exposure:
        """*var* answered by the main secret field of a named entry."""
        if not self.vault.exists(entry_name):
            raise ExposeError(f"no entry named {entry_name!r}")
        entry = self.vault.read(self.key, entry_name)
        field = primary_field(entry)
        if field is None:
            raise ExposeError(f"{entry_name} has no fields to expose")
        if field == "content_b64":
            raise ExposeError(
                f"{entry_name} holds file bytes, not a variable — "
                "get those with `sekrt file get`"
            )
        return Exposure(var, entry["data"][field], f"{entry_name}:{field}")

    def candidates(self, var: str) -> list[str]:
        """Entries whose name reads as *var*."""
        return [name for name in self.vault.list_entries() if var_name(name) == var]

    def known(self) -> list[str]:
        """Every variable this vault could answer here — for suggesting a typo's fix."""
        names = {var_name(name) for name in self.vault.list_entries()}
        return sorted(names | set(self.stored))

    def lookup(self, var: str) -> Exposure:
        """*var*, from this repo's stored env files or from the entry it names."""
        if var in self.stored:
            return self.stored[var]
        matches = self.candidates(var)
        if len(matches) == 1:
            return self.from_entry(var, matches[0])
        if matches:
            raise ExposeError(
                f"${var} could come from any of {', '.join(matches)} — "
                f"say which: -e {var}={matches[0]}"
            )
        hint = difflib.get_close_matches(var, self.known(), n=3, cutoff=0.5)
        raise ExposeError(
            f"nothing in the vault answers ${var}"
            + (f" — did you mean: {', '.join(hint)}?" if hint else "")
            + f"\n  or name the entry yourself: -e {var}=<entry>"
        )


def resolve(
    resolver: Resolver,
    *,
    requested: tuple[str, ...] | list[str] = (),
    referenced: tuple[str, ...] | list[str] = (),
) -> tuple[list[Exposure], list[tuple[str, str]]]:
    """What to expose, and what could not be found.

    With nothing named, a command gets everything the vault can offer as a
    variable. *requested* — the ``-e`` arguments (``VAR``, or ``VAR=entry/name``)
    — narrows that to those, which is how one secret is handed over instead of
    all of them; the repository's own stored env files come along either way
    (``--no-env-files`` is what drops them).

    Three layers, each overriding the one before: every entry, then this repo's
    files, then what was named outright — the more specific the claim on a
    variable, the later it lands.

    *referenced* are the names a command mentions. One already in the environment
    is left alone — a command asking for ``$HOME`` is not asking the vault for
    anything — and one that resolves nowhere is reported rather than fatal, since
    a shell command is free to mention variables of its own making.

    Returns ``(exposures, unresolved)``, where *unresolved* pairs each name with
    why it could not be answered.
    """
    chosen: dict[str, Exposure] = {} if requested else dict(resolver.bulk)
    chosen.update(resolver.stored)
    for item in requested:
        var, sep, entry_name = item.partition("=")
        var = var.strip()
        if not is_var_name(var):
            raise ExposeError(
                f"{item!r} is not a variable — expected VAR, or VAR=entry/name"
            )
        chosen[var] = (
            resolver.from_entry(var, entry_name.strip()) if sep else resolver.lookup(var)
        )

    unresolved: list[tuple[str, str]] = []
    for var in referenced:
        if var in chosen or var in os.environ:
            continue
        try:
            chosen[var] = resolver.lookup(var)
        except ExposeError as exc:
            unresolved.append((var, str(exc)))
    return sorted(chosen.values(), key=lambda e: e.var), unresolved


def child_env(
    exposures: list[Exposure], base: dict[str, str] | None = None
) -> dict[str, str]:
    """The environment for the wrapped command: ours, plus the secrets, minus the key."""
    env = dict(os.environ if base is None else base)
    for var in STRIPPED_VARS:
        env.pop(var, None)
    for exposure in exposures:
        env[exposure.var] = exposure.value
    if exposures:
        env[MARKER_VAR] = " ".join(exposure.var for exposure in exposures)
    return env


# The characters that mean a single argument was written for a shell to read
# rather than for a program to be called by name: whitespace, expansion, quoting,
# redirection, globbing. A lone `npm` has none of them and is simply exec'd.
_SHELL_CHARS = frozenset(" \t\n$|&;<>()`*?\"'\\")


def needs_shell(command: tuple[str, ...] | list[str]) -> bool:
    """Is *command* one string a shell should interpret, rather than an argv?

    ``sekrt run 'service log --token="$MY_TOKEN"'`` is a sentence in shell, not a
    program and its arguments — one word holding spaces, a `$` and quotes, none
    of which mean anything to :func:`os.execvpe`. ``sekrt run -- npm start`` is
    the other shape and stays exec'd directly, with no shell in the way.
    """
    return len(command) == 1 and any(char in _SHELL_CHARS for char in command[0])


def swallowed_text(command: str) -> bool:
    """Does *command* carry the hole an eaten ``$VAR`` reference leaves behind?

    ``sekrt run "echo $MY_TOKEN"`` — double quotes — is expanded by the shell that
    runs sekrt, before sekrt exists; unset there, what arrives is ``echo ``, and
    the command prints nothing at all. Nothing in the string can prove that is
    what happened, but the shapes it leaves — a trailing space, a gap of two, an
    argument ending in ``=``, an empty pair of quotes — are not shapes a command
    written by hand usually has, and a silently empty value is the worst way to
    find out. A reference that survived (any ``$`` at all) is left alone.
    """
    if "$" in command:
        return False
    body = command.rstrip()
    return (
        (bool(command) and body != command)
        or "  " in body
        or '""' in body
        or "''" in body
        or any(word.endswith("=") for word in body.split())
    )


def swallowed_args(command: tuple[str, ...] | list[str]) -> list[str]:
    """Arguments shaped like a variable the *calling* shell expanded away.

    ``sekrt run -- svc --token=$MY_TOKEN`` is expanded by the shell that runs
    sekrt, before sekrt exists; unset there, what arrives is ``--token=``. The
    double-quoted spelling leaves an empty argument instead. Neither is something
    a command line usually holds, and both mean the command is about to run
    without the value it asked for.

    The bare ``-- echo $MY_TOKEN`` cannot be caught this way: an unquoted unset
    variable removes the argument altogether, leaving nothing behind to notice.
    """
    return [arg for arg in list(command)[1:] if arg == "" or (len(arg) > 1 and arg[-1] == "=")]


def might_expose(vault: Vault) -> bool:
    """Could an unnamed `sekrt run` find anything here? Decided from names alone.

    Enough to tell an empty (or entirely `.env`/SSH/file) vault apart before the
    passphrase is asked for. Whether those entries turn out to be the right
    *type* needs decrypting them, and is settled later.
    """
    return any(
        not name.startswith(_MANAGED_PREFIXES) and is_var_name(var_name(name))
        for name in vault.list_entries()
    )


def is_shell_command(argv: tuple[str, ...] | list[str]) -> bool:
    """Is *argv* a shell being handed a command to interpret?

    ``sekrt run -- sh -c '… $MY_TOKEN …'`` is the long way round to the quoted form,
    and it works: that shell expands the reference itself. Worth telling apart
    from a program being handed the same text, which does not.
    """
    if len(argv) < 2:
        return False
    name = Path(argv[0]).name.removesuffix(".exe")
    return name.endswith("sh") and "-c" in argv[1:]


def default_shell() -> str:
    if os.name == "posix":
        return os.environ.get("SHELL") or "/bin/sh"
    return os.environ.get("COMSPEC") or "cmd.exe"


# ----------------------------------------------------------------------- the tag

# A shell holding secrets should not look like an ordinary one. Plain ASCII, in
# the shape `(venv)`/`(nix-shell)` already taught everyone to read: an emoji here
# would be two display cells the shell counts as one character, which is how a
# prompt ends up misplacing the cursor on a long edited line.
SHELL_TAG = "(sekrt)"
_TAG = "@SEKRT_TAG@"  # placeholder in the templates below

_HEADER = "# Written by `sekrt shell` — prompt wiring, no secrets. Safe to delete.\n"

# zsh resolves each startup file against whatever ZDOTDIR holds when it gets
# there, so .zshenv must *not* put the real one back: .zshrc, the file that adds
# the tag, would stop being ours.
_ZSHENV = _HEADER + """\
[ -f "${SEKRT_ZDOTDIR:-$HOME}/.zshenv" ] && . "${SEKRT_ZDOTDIR:-$HOME}/.zshenv"
"""

# A precmd hook rather than one assignment: a themed prompt rebuilds PROMPT
# before every line and would drop a prefix set only once. The guard is what
# keeps it from stacking up one tag per prompt.
_ZSHRC = _HEADER + """\
if [ -n "${SEKRT_ZDOTDIR-}" ]; then ZDOTDIR="$SEKRT_ZDOTDIR"; else unset ZDOTDIR; fi
[ -f "${ZDOTDIR:-$HOME}/.zshrc" ] && . "${ZDOTDIR:-$HOME}/.zshrc"
_sekrt_tag() {
    case "$PROMPT" in "@SEKRT_TAG@ "*) ;; *) PROMPT="@SEKRT_TAG@ $PROMPT" ;; esac
}
precmd_functions+=(_sekrt_tag)
"""

_BASHRC = _HEADER + """\
[ -f "$HOME/.bashrc" ] && . "$HOME/.bashrc"
_sekrt_tag() {
    case "$PS1" in "@SEKRT_TAG@ "*) ;; *) PS1="@SEKRT_TAG@ $PS1" ;; esac
}
# Appended, so a prompt framework already using PROMPT_COMMAND keeps working —
# including bash 5.1's array form, which a plain assignment would flatten.
case "$(declare -p PROMPT_COMMAND 2>/dev/null)" in
    "declare -a"*) PROMPT_COMMAND+=(_sekrt_tag) ;;
    *) PROMPT_COMMAND="${PROMPT_COMMAND:+$PROMPT_COMMAND; }_sekrt_tag" ;;
esac
"""

# fish needs no file: --init-command runs after config.fish, which is exactly
# where the real fish_prompt can be wrapped.
_FISH_INIT = (
    "functions -q fish_prompt; and functions -c fish_prompt _sekrt_inner_prompt; "
    "and function fish_prompt; echo -n '@SEKRT_TAG@ '; _sekrt_inner_prompt; end"
)


def _rc_dir() -> Path | None:
    """A private directory for the generated rc files, or None if there is none.

    The interactive shell *sources* these, so they may only live somewhere no
    other user can write: a planted rc file is code execution. That is the same
    requirement the session cache has, so it is the same directory.
    """
    base = session.private_tmpdir()
    if base is None:
        return None
    directory = base / "shell"
    try:
        directory.mkdir(mode=0o700, exist_ok=True)
        os.chmod(directory, 0o700)
    except OSError:
        return None
    return directory


def _write_rc(path: Path, template: str) -> Path:
    _atomic_write(path, template.replace(_TAG, SHELL_TAG).encode())  # 0600
    return path


def shell_launch(shell: str | None = None) -> tuple[list[str], dict[str, str]]:
    """The argv and extra environment that open a subshell wearing the tag.

    `PS1` handed over in the environment does not survive: the `.bashrc` or
    `.zshrc` that runs next sets its own. So the prompt is hooked through the
    shell's own startup instead — a generated rc that sources the real one first,
    for bash and zsh; a `--init-command` for fish. Any other shell opens plain,
    where the banner and `$SEKRT_EXPOSED` still say what is going on.
    """
    shell = shell or default_shell()
    name = Path(shell).name.removesuffix(".exe")

    if name == "fish":
        return [shell, "-C", _FISH_INIT.replace(_TAG, SHELL_TAG)], {}

    directory = _rc_dir() if name in ("bash", "zsh") else None
    if directory is None:
        return [shell], {}

    # `-i` for both: at a terminal it changes nothing, and with stdin on a pipe
    # it is what still gets the startup files read — so `echo cmd | sekrt shell`
    # lands in the same shell an interactive session would.
    if name == "zsh":
        _write_rc(directory / ".zshenv", _ZSHENV)
        _write_rc(directory / ".zshrc", _ZSHRC)
        env = {"ZDOTDIR": str(directory)}
        if real := os.environ.get("ZDOTDIR"):
            env["SEKRT_ZDOTDIR"] = real  # so the generated files find the real config
        return [shell, "-i"], env

    rc = _write_rc(directory / "bashrc", _BASHRC)
    return [shell, "--rcfile", str(rc), "-i"], {}


def shell_argv(command: str) -> list[str]:
    """The argv that runs *command* through the user's shell, so it expands ``$VAR``."""
    return [default_shell(), "-c" if os.name == "posix" else "/c", command]


def launch(argv: list[str], env: dict[str, str]) -> int:
    """Become *argv* — or, where that is impossible, run it and return its status.

    ``execvpe`` is the point on POSIX: no part of sekrt is left running while
    the command does its work, so nothing holds the vault key, the command owns
    the terminal outright, and its exit status and signals are its own. It never
    returns; the status is only ever passed back on platforms without exec.
    """
    if not argv:
        raise ExposeError("no command to run")
    try:
        if os.name == "posix":
            os.execvpe(argv[0], argv, env)  # never returns
        return subprocess.call(argv, env=env)
    except FileNotFoundError:
        raise ExposeError(f"command not found: {argv[0]}") from None
    except OSError as exc:
        raise ExposeError(f"cannot run {argv[0]}: {exc}") from exc
