"""`sekrt mcp`: the vault as tools for an AI agent, without handing it a secret.

An agent working in a repository needs secrets the way a build does — to run
the tests that call an API, to publish a package, to set up a fresh clone — and
almost never needs to *read* one. So nothing here returns a secret value. The
tools hand secrets to processes (``run_command``), to files the repo expects
(``env_pull``) or to the vault (``generate_secret``), and answer questions about
them by name only (``list_entries``, ``describe_entry``, ``env_status``,
``scan_for_leaks``). Output that comes back from a wrapped command has every
exposed value replaced by its variable name before the agent sees it.

The server never asks for the passphrase. It uses the key `sekrt unlock` cached,
and a locked vault is an error that tells the agent to ask the user to unlock it.
The passphrase never passes through the model, and the user decides how long the
agent gets access for (`sekrt unlock -t MIN`, or `sekrt lock` to end it now).

The transport is MCP over stdio: newline-delimited JSON-RPC 2.0. The protocol
surface a tools-only server needs is small enough to speak directly, which keeps
sekrt free of another dependency.
"""

from __future__ import annotations

import json
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sekrt import __version__, envtools, gitsync, prefs, runtools, session
from sekrt.crypto import CryptoError
from sekrt.generate import generate_password, generate_token
from sekrt.vault import PRIMARY_FIELD, Vault, VaultError, new_entry, primary_field

PROTOCOL_VERSIONS = ("2025-11-25", "2025-06-18", "2025-03-26", "2024-11-05")

# Fields `describe_entry` shows as they are. Anything else, including fields a
# future entry type adds, is reported as hidden: the safe side of not knowing.
VISIBLE_FIELDS = frozenset(
    {"username", "url", "comment", "filename", "public", "slug", "relpath", "sha256", "size"}
)
HIDDEN = "<hidden>"

# Values shorter than this are left alone by redaction and by the leak scan:
# `true`, `3000` or `dev` would match half of any output and protect nothing.
MIN_REDACT_LEN = 6
MIN_LEAK_LEN = 8

OUTPUT_LIMIT = 20_000  # characters kept per stream, from the end
DEFAULT_TIMEOUT = 120
MAX_TIMEOUT = 1800
SCAN_MAX_BYTES = 1_000_000
SCAN_MAX_HITS = 200

# Template files that list the variables a repo expects, values left blank.
EXAMPLE_FILES = (".env.example", ".env.sample", ".env.template", ".env.dist")

LOCKED = (
    "the vault is locked — ask the user to run `sekrt unlock` in their own terminal "
    "(the passphrase must never be typed into this conversation), then retry"
)

INSTRUCTIONS = """\
sekrt is the user's encrypted secret vault. These tools never return a secret value, \
and you should never ask the user to paste one into the conversation.
- Need a secret for a command (tests, deploy, publish)? Use run_command and reference \
the variable ($MY_TOKEN) or name it in `vars`; the value goes to the process only, and \
its output comes back with the value redacted.
- Don't know what is available? list_entries (names and the variable each answers to) \
and describe_entry (metadata, secrets hidden).
- Setting up a clone? env_status, then env_pull.
- Before committing, scan_for_leaks checks the repo for any vault value.
- If a tool says the vault is locked, ask the user to run `sekrt unlock`. Never ask \
for the passphrase.
- To create a new secret, use generate_secret, or ask the user to run \
`sekrt add NAME -t api_key` themselves for a value only they have."""


class ToolError(Exception):
    """A tool call that failed in a way the agent should read and act on."""


# --------------------------------------------------------------------- helpers


def _vault() -> Vault:
    vault = Vault()
    if not vault.initialized:
        raise ToolError(
            f"no vault at {vault.path} — the user needs to run `sekrt init` "
            "(or `sekrt clone <url>`) first"
        )
    return vault


def _key(vault: Vault) -> bytes:
    """The key `sekrt unlock` cached. Never a prompt, never `$SEKRT_PASSPHRASE`."""
    key = session.load_key(vault.path)
    if key is None or not vault.verify_key(key):
        raise ToolError(LOCKED)
    return key


def _cwd(args: dict) -> Path:
    raw = args.get("cwd")
    cwd = Path(raw).expanduser() if raw else Path.cwd()
    if not cwd.is_dir():
        raise ToolError(f"no such directory: {cwd}")
    return cwd.resolve()


def _strings(args: dict, field: str) -> list[str]:
    value = args.get(field) or []
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise ToolError(f"`{field}` must be a list of strings")
    return value


def _managed(name: str) -> bool:
    return name.startswith(runtools._MANAGED_PREFIXES)


def _variable(name: str) -> str | None:
    """The variable `run_command` would expose *name* as, if it is one."""
    var = runtools.var_name(name)
    return var if not _managed(name) and runtools.is_var_name(var) else None


def redact(text: str, values: dict[str, str]) -> str:
    """*text* with every value in *values* (var -> value) replaced by ``***VAR***``.

    Longest first, so a secret that contains another is replaced whole.
    """
    for var, value in sorted(values.items(), key=lambda item: -len(item[1])):
        if len(value) >= MIN_REDACT_LEN:
            text = text.replace(value, f"***{var}***")
    return text


def _tail(text: str) -> str:
    if len(text) <= OUTPUT_LIMIT:
        return text
    return f"…({len(text) - OUTPUT_LIMIT} characters cut)\n" + text[-OUTPUT_LIMIT:]


def _decode(raw: str | bytes | None) -> str:
    if raw is None:
        return ""
    return raw.decode(errors="replace") if isinstance(raw, bytes) else raw


# ----------------------------------------------------------------------- tools


def tool_status(args: dict) -> dict:
    vault = Vault()
    result: dict[str, Any] = {"vault": str(vault.path), "initialized": vault.initialized}
    if not vault.initialized:
        return result
    cwd = _cwd(args)
    root, slug = envtools.current_context(cwd)
    slug = envtools.resolve_slug(vault, slug)
    result |= {
        "entries": len(vault.list_entries()),
        "unlocked": session.unlocked(vault.path),
        "unlock_seconds_left": session.remaining(vault.path),
        "remote": gitsync.get_remote(vault.path),
        "autosync": vault.auto_sync,
        "repo_root": str(root),
        "repo_slug": slug,
        "stored_env_files": envtools.stored_files(vault, slug),
    }
    return result


def tool_list_entries(args: dict) -> dict:
    vault = _vault()
    prefix = args.get("prefix") or ""
    entries = [{"name": name, "var": _variable(name)} for name in vault.list_entries(prefix)]
    return {"entries": entries}


def tool_describe_entry(args: dict) -> dict:
    vault = _vault()
    name = args.get("name") or ""
    if not vault.exists(name):
        close = vault.search(name.rsplit("/", 1)[-1])[:5]
        raise ToolError(f"no entry named {name!r}" + (f" — did you mean: {', '.join(close)}?"
                                                       if close else ""))
    entry = vault.read(_key(vault), name)
    fields = {
        field: value if field in VISIBLE_FIELDS else HIDDEN
        for field, value in entry.get("data", {}).items()
    }
    return {
        "name": name,
        "type": entry.get("type"),
        "created": entry.get("created"),
        "modified": entry.get("modified"),
        "var": _variable(name),
        "secret_field": primary_field(entry),
        "fields": fields,
    }


def tool_run_command(args: dict) -> dict:
    command = args.get("command")
    argv = _strings(args, "argv")
    if bool(command) == bool(argv):
        raise ToolError("give exactly one of `command` (a shell string) or `argv` (a list)")
    if command is not None and not isinstance(command, str):
        raise ToolError("`command` must be a string")
    requested = _strings(args, "vars")
    everything = bool(args.get("all_vault", False))
    env_files = bool(args.get("env_files", True))
    timeout = min(int(args.get("timeout") or DEFAULT_TIMEOUT), MAX_TIMEOUT)
    cwd = _cwd(args)

    vault = _vault()
    key = _key(vault)
    resolver = runtools.Resolver(
        vault, key, slug=args.get("repo"), cwd=cwd, env_files=env_files
    )
    referenced = runtools.references(command) if command else []
    try:
        exposures, unresolved = runtools.resolve(
            resolver, requested=requested, referenced=referenced, everything=everything
        )
    except runtools.ExposeError as exc:
        raise ToolError(str(exc)) from exc

    notes = [message for _, message in unresolved]
    notes += [
        f"${var} left unset — {' and '.join(names)} both answer to it; "
        f"pick one with vars: [\"{var}={names[0]}\"]"
        for var, names in resolver.ambiguous.items()
    ]
    if not command and any(f"${e.var}" in " ".join(argv) for e in exposures):
        notes.append("argv is not expanded by a shell — use `command` to expand $VAR")

    full_argv = runtools.shell_argv(command) if command else argv
    values = {exposure.var: exposure.value for exposure in exposures}
    try:
        proc = subprocess.run(
            full_argv,
            cwd=cwd,
            env=runtools.child_env(exposures),
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            errors="replace",
            timeout=timeout,
        )
        exit_code, stdout, stderr, timed_out = proc.returncode, proc.stdout, proc.stderr, False
    except subprocess.TimeoutExpired as exc:
        exit_code, timed_out = None, True
        stdout, stderr = _decode(exc.stdout), _decode(exc.stderr)
    except FileNotFoundError:
        raise ToolError(f"command not found: {full_argv[0]}") from None

    return {
        "exit_code": exit_code,
        "timed_out": timed_out,
        "exposed": {exposure.var: exposure.origin for exposure in exposures},
        "notes": notes,
        "stdout": _tail(redact(stdout, values)),
        "stderr": _tail(redact(stderr, values)),
    }


def tool_env_status(args: dict) -> dict:
    vault = _vault()
    cwd = _cwd(args)
    root, slug = envtools.current_context(cwd)
    slug = envtools.resolve_slug(vault, slug)
    stored = envtools.stored_files(vault, slug)
    key = _key(vault) if stored else None

    files = []
    defined: set[str] = set()
    for relpath in stored:
        content = vault.read(key, envtools.entry_name(slug, relpath))["data"].get("content", "")
        vault_vars = set(runtools.parse_env(content))
        defined |= vault_vars
        local = root / relpath
        item: dict[str, Any] = {"file": relpath}
        if not local.is_file():
            item["local"] = "missing"
        else:
            text = local.read_text(errors="replace")
            local_vars = set(runtools.parse_env(text))
            defined |= local_vars
            item["local"] = "same" if text == content else "differs"
            if text != content:
                item["only_in_vault"] = sorted(vault_vars - local_vars)
                item["only_local"] = sorted(local_vars - vault_vars)
        files.append(item)

    unstored = sorted(
        str(path.relative_to(root))
        for path in root.glob(".env*")
        if path.is_file()
        and path.name not in EXAMPLE_FILES
        and str(path.relative_to(root)) not in stored
    )
    for relpath in unstored:
        defined |= set(runtools.parse_env((root / relpath).read_text(errors="replace")))

    expected: dict[str, list[str]] = {}
    for name in EXAMPLE_FILES:
        example = root / name
        if example.is_file():
            missing = set(runtools.parse_env(example.read_text(errors="replace"))) - defined
            if missing:
                expected[name] = sorted(missing)

    return {
        "repo_root": str(root),
        "repo_slug": slug,
        "stored": files,
        "local_not_stored": unstored,
        "missing_from_example": expected,
    }


def tool_env_pull(args: dict) -> dict:
    vault = _vault()
    key = _key(vault)
    cwd = _cwd(args)
    slug = args.get("repo")
    renamed = envtools.realign(vault, key, cwd=cwd) if slug is None else None
    results = envtools.pull(
        vault,
        key,
        cwd=cwd,
        files=_strings(args, "files") or None,
        force=bool(args.get("force", False)),
        slug=slug,
    )
    out: dict[str, Any] = {"files": [{"file": f, "result": r} for f, r in results]}
    if any(r == "skipped" for _, r in results):
        out["note"] = "skipped files differ locally; force: true overwrites them"
    if renamed:
        out["renamed"] = renamed
    return out


def tool_env_push(args: dict) -> dict:
    vault = _vault()
    key = _key(vault)
    cwd = _cwd(args)
    renamed = envtools.realign(vault, key, cwd=cwd)
    results = [
        envtools.push(vault, key, Path(file), cwd=cwd)
        for file in _strings(args, "files") or [".env"]
    ]
    out: dict[str, Any] = {"files": [{"entry": n, "result": r} for n, r in results]}
    if renamed:
        out["renamed"] = renamed
    return out


def tool_generate_secret(args: dict) -> dict:
    vault = _vault()
    name = args.get("name") or ""
    type_ = args.get("type") or "api_key"
    if type_ not in ("password", "api_key"):
        raise ToolError("`type` must be password or api_key")
    overwrite = bool(args.get("overwrite", False))
    if vault.exists(name) and not overwrite:
        raise ToolError(f"{name!r} already exists — overwrite: true rotates it "
                        "(the old value stays in the vault's git history)")
    key = _key(vault)
    length = int(args.get("length") or prefs.load_settings().password_length)
    token = bool(args.get("token", type_ == "api_key"))
    secret = (
        generate_token(max(length * 3 // 4, 16))
        if token
        else generate_password(length, symbols=bool(args.get("symbols", True)))
    )
    data = {PRIMARY_FIELD[type_]: secret}
    for field in ("username", "url", "notes"):
        if args.get(field):
            data[field] = str(args[field])
    vault.write(key, name, new_entry(type_, data), overwrite=overwrite,
                message=f"{'rotate' if overwrite else 'add'} {name} (generated)")
    return {"stored": name, "type": type_, "length": len(secret), "var": _variable(name)}


def _scan_values(vault: Vault, key: bytes, slug: str) -> dict[str, str]:
    """value -> where it lives, for every vault value worth looking for."""
    values: dict[str, str] = {}
    for name in vault.list_entries():
        if _managed(name):
            continue
        entry = vault.read(key, name)
        if entry.get("type") not in runtools.EXPOSABLE_TYPES:
            continue
        field = primary_field(entry)
        if field and len(entry["data"][field]) >= MIN_LEAK_LEN:
            values[entry["data"][field]] = name
    for relpath in envtools.stored_files(vault, slug):
        entry_name = envtools.entry_name(slug, relpath)
        content = vault.read(key, entry_name)["data"].get("content", "")
        for var, value in runtools.parse_env(content).items():
            if len(value) >= MIN_LEAK_LEN:
                values.setdefault(value, f"{entry_name}:{var}")
    return values


def _committable(root: Path) -> list[str]:
    res = subprocess.run(
        ["git", "-C", str(root), "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
        capture_output=True,
        timeout=60,
    )
    if res.returncode != 0:
        raise ToolError(f"{root} is not a git repository")
    return [p for p in res.stdout.decode(errors="replace").split("\0") if p]


def tool_scan_for_leaks(args: dict) -> dict:
    vault = _vault()
    cwd = _cwd(args)
    root = envtools.find_repo_root(cwd)
    if root is None:
        raise ToolError(f"{cwd} is not inside a git repository")
    slug = envtools.resolve_slug(vault, envtools.repo_slug(root))
    values = _scan_values(vault, _key(vault), slug)

    hits: list[dict[str, Any]] = []
    scanned = 0
    for relpath in _committable(root):
        path = root / relpath
        try:
            if not path.is_file() or path.stat().st_size > SCAN_MAX_BYTES:
                continue
            raw = path.read_bytes()
        except OSError:
            continue
        if b"\0" in raw:
            continue  # binary
        scanned += 1
        text = raw.decode(errors="replace")
        for value, origin in values.items():
            if value not in text:
                continue
            for number, line in enumerate(text.splitlines(), 1):
                if value in line:
                    hits.append({"file": relpath, "line": number, "entry": origin})
        if len(hits) >= SCAN_MAX_HITS:
            break
    return {
        "scanned_files": scanned,
        "checked_values": len(values),
        "leaks": hits[:SCAN_MAX_HITS],
        "clean": not hits,
    }


# ------------------------------------------------------------------- registry


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    schema: dict
    handler: Callable[[dict], dict]
    read_only: bool = True
    destructive: bool = False


_CWD = {"type": "string", "description": "Directory to act in (default: the server's cwd)."}

TOOLS = [
    Tool(
        "status",
        "Vault location, entry count, whether it is unlocked (and for how long), the sync "
        "remote, and which .env files are stored for the current repo. Never needs unlocking.",
        {"type": "object", "properties": {"cwd": _CWD}},
        tool_status,
    ),
    Tool(
        "list_entries",
        "List entry names (plaintext metadata, no unlock needed), each with the environment "
        "variable run_command would expose it as (`api/my-token` -> MY_TOKEN), or null.",
        {
            "type": "object",
            "properties": {
                "prefix": {"type": "string", "description": "Folder prefix, e.g. `work/`."},
            },
        },
        tool_list_entries,
    ),
    Tool(
        "describe_entry",
        "An entry's type, dates and non-secret fields (username, url, ...). Secret fields "
        "are listed as <hidden>; there is no way to reveal them through this server.",
        {
            "type": "object",
            "properties": {"name": {"type": "string"}},
            "required": ["name"],
        },
        tool_describe_entry,
    ),
    Tool(
        "run_command",
        "Run a command with vault secrets in its environment only, like `sekrt run`. "
        "Secrets come from: variables the command string references ($VAR / ${VAR}), "
        "names in `vars`, and this repo's stored .env files. Output is returned with every "
        "exposed value replaced by ***VAR***. stdin is closed; the command must not be "
        "interactive.",
        {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "Shell command; $VAR references are expanded by the shell.",
                },
                "argv": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Run this argv directly, no shell (alternative to command).",
                },
                "vars": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Variables to expose: VAR, or VAR=entry/name.",
                },
                "env_files": {
                    "type": "boolean",
                    "default": True,
                    "description": "Include this repo's stored .env files.",
                },
                "all_vault": {
                    "type": "boolean",
                    "default": False,
                    "description": "Expose every password and API key in the vault. Avoid "
                                   "unless the user asked for it.",
                },
                "repo": {
                    "type": "string",
                    "description": "Use another repo's stored .env files (slug).",
                },
                "cwd": _CWD,
                "timeout": {
                    "type": "integer",
                    "default": DEFAULT_TIMEOUT,
                    "maximum": MAX_TIMEOUT,
                    "description": "Seconds before the command is killed.",
                },
            },
        },
        tool_run_command,
        read_only=False,
    ),
    Tool(
        "env_status",
        "Compare this repo's .env files with the copies stored in the vault: which are "
        "missing locally, which differ (by variable name, never value), which local .env "
        "files are not stored, and which variables a .env.example expects that nothing "
        "defines.",
        {"type": "object", "properties": {"cwd": _CWD}},
        tool_env_status,
    ),
    Tool(
        "env_pull",
        "Restore this repo's stored .env files into the working tree (`sekrt env pull`). "
        "Files that differ locally are skipped unless force is true. Contents are not "
        "returned.",
        {
            "type": "object",
            "properties": {
                "files": {"type": "array", "items": {"type": "string"},
                          "description": "Paths relative to the repo root (default: all)."},
                "force": {"type": "boolean", "default": False},
                "repo": {"type": "string", "description": "Pull another repo's files (slug)."},
                "cwd": _CWD,
            },
        },
        tool_env_pull,
        read_only=False,
        destructive=True,
    ),
    Tool(
        "env_push",
        "Encrypt this repo's .env file(s) into the vault (`sekrt env push`).",
        {
            "type": "object",
            "properties": {
                "files": {"type": "array", "items": {"type": "string"},
                          "description": "Paths relative to cwd (default: .env)."},
                "cwd": _CWD,
            },
        },
        tool_env_push,
        read_only=False,
    ),
    Tool(
        "generate_secret",
        "Generate a random password or token and store it in the vault, without returning "
        "it. Use for new credentials (a database password, a webhook secret); the value "
        "then reaches commands through run_command.",
        {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Entry name, e.g. `myapp/db-password`."},
                "type": {"type": "string", "enum": ["api_key", "password"],
                         "default": "api_key"},
                "length": {"type": "integer"},
                "token": {"type": "boolean",
                          "description": "URL-safe token (default for api_key)."},
                "symbols": {"type": "boolean", "default": True},
                "username": {"type": "string"},
                "url": {"type": "string"},
                "notes": {"type": "string"},
                "overwrite": {"type": "boolean", "default": False,
                              "description": "Rotate an existing entry."},
            },
            "required": ["name"],
        },
        tool_generate_secret,
        read_only=False,
        destructive=True,
    ),
    Tool(
        "scan_for_leaks",
        "Check every file git would commit in this repo (tracked plus untracked, not "
        "ignored) for any password, API key or stored .env value from the vault. Reports "
        "file, line and entry name, never the value.",
        {"type": "object", "properties": {"cwd": _CWD}},
        tool_scan_for_leaks,
    ),
]
_BY_NAME = {tool.name: tool for tool in TOOLS}


def _describe(tool: Tool) -> dict:
    return {
        "name": tool.name,
        "description": tool.description,
        "inputSchema": tool.schema,
        "annotations": {
            "readOnlyHint": tool.read_only,
            "destructiveHint": tool.destructive,
            "openWorldHint": tool.name == "run_command",
        },
    }


def call_tool(name: str, args: dict | None) -> dict:
    """An MCP ``tools/call`` result: the tool's JSON as text, or the error it raised."""
    tool = _BY_NAME.get(name)
    if tool is None:
        return _text(f"unknown tool {name!r}", error=True)
    try:
        return _text(json.dumps(tool.handler(args or {}), indent=2))
    except (ToolError, VaultError, CryptoError, ValueError, OSError) as exc:
        return _text(str(exc), error=True)


def _text(text: str, *, error: bool = False) -> dict:
    return {"content": [{"type": "text", "text": text}], "isError": error}


# ------------------------------------------------------------------- protocol


class _MethodNotFound(Exception):
    pass


def handle(message: dict) -> dict | None:
    """One JSON-RPC message in, its response out (None for a notification)."""
    method = message.get("method")
    msg_id = message.get("id")
    params = message.get("params") or {}
    if msg_id is None:
        return None  # notifications/initialized, cancelled, ...
    try:
        result = _dispatch(method, params)
    except _MethodNotFound:
        return _error(msg_id, -32601, f"method not found: {method}")
    except Exception as exc:  # a bug must not take the server down
        return _error(msg_id, -32603, f"internal error: {exc}")
    return {"jsonrpc": "2.0", "id": msg_id, "result": result}


def _dispatch(method: str | None, params: dict) -> dict:
    if method == "initialize":
        asked = params.get("protocolVersion")
        return {
            "protocolVersion": asked if asked in PROTOCOL_VERSIONS else PROTOCOL_VERSIONS[0],
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": "sekrt", "version": __version__},
            "instructions": INSTRUCTIONS,
        }
    if method == "ping":
        return {}
    if method == "tools/list":
        return {"tools": [_describe(tool) for tool in TOOLS]}
    if method == "tools/call":
        return call_tool(params.get("name", ""), params.get("arguments"))
    raise _MethodNotFound


def _error(msg_id: Any, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": msg_id, "error": {"code": code, "message": message}}


def serve(stdin=None, stdout=None) -> None:
    """Answer MCP messages on stdin until it closes.

    stdout belongs to the protocol, so anything else that would print there —
    a stray warning from a library — is sent to stderr for the duration.
    """
    stdin = stdin or sys.stdin
    out = stdout or sys.stdout
    saved, sys.stdout = sys.stdout, sys.stderr
    try:
        for line in stdin:
            line = line.strip()
            if not line:
                continue
            try:
                message = json.loads(line)
            except ValueError:
                _send(out, _error(None, -32700, "parse error"))
                continue
            batch = message if isinstance(message, list) else [message]
            replies = [r for r in (handle(m) for m in batch if isinstance(m, dict)) if r]
            if replies:
                _send(out, replies if isinstance(message, list) else replies[0])
    finally:
        sys.stdout = saved


def _send(out, payload: Any) -> None:
    out.write(json.dumps(payload) + "\n")
    out.flush()
