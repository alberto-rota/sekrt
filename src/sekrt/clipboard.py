"""Clipboard helpers with automatic clearing.

Uses whatever tool the system already has (wl-copy, xclip, xsel, pbcopy) —
no extra Python dependencies, no sudo. After ``clear_after`` seconds a
detached helper process clears the clipboard, but only if it still holds the
value we put there. The secret is passed to the helper via stdin, never via
argv (argv is world-readable in /proc).
"""

from __future__ import annotations

import json
import os
import select
import shutil
import subprocess
import sys
from dataclasses import dataclass

DEFAULT_CLEAR_AFTER = 45
KEY_TIMEOUT = 20  # seconds a `press c to copy` prompt waits before giving up

# `copy()` with no delay reads `sekrt config`. This sentinel is how "omitted"
# stays different from an explicit None, which still means "do not clear".
_FROM_CONFIG = object()


class ClipboardError(Exception):
    """No usable clipboard tool was found (or copying failed)."""


@dataclass(frozen=True)
class ClipTool:
    copy_cmd: list[str]
    paste_cmd: list[str] | None


def _find_tool() -> ClipTool | None:
    if sys.platform == "darwin" and shutil.which("pbcopy"):
        return ClipTool(["pbcopy"], ["pbpaste"] if shutil.which("pbpaste") else None)
    if os.environ.get("WAYLAND_DISPLAY") and shutil.which("wl-copy"):
        paste = ["wl-paste", "--no-newline"] if shutil.which("wl-paste") else None
        return ClipTool(["wl-copy"], paste)
    if os.environ.get("DISPLAY"):
        if shutil.which("xclip"):
            base = ["xclip", "-selection", "clipboard"]
            return ClipTool(base, [*base, "-o"])
        if shutil.which("xsel"):
            return ClipTool(["xsel", "-b", "-i"], ["xsel", "-b", "-o"])
    return None


def available() -> bool:
    return _find_tool() is not None


def read_key(timeout: float | None = None) -> str | None:
    """One keypress from the controlling terminal, or None if none arrives.

    Used by the ``press c to copy`` prompt: reading the *terminal* rather than
    stdin keeps the prompt working when stdin is a pipe, and reading raw means
    a single ``c`` is enough — no Enter. The timeout is what keeps a command
    that merely prints something from turning into one that waits forever when
    nobody is watching the terminal (a pty in CI, a detached pane).
    """
    try:
        import termios
        import tty
    except ImportError:  # no POSIX terminal (Windows)
        return None
    try:
        with open("/dev/tty", "rb", buffering=0) as terminal:
            fd = terminal.fileno()
            saved = termios.tcgetattr(fd)
            try:
                tty.setraw(fd)
                # Whatever was typed while the command ran was not an answer to
                # a prompt that did not exist yet — an idle `c` must not copy.
                termios.tcflush(fd, termios.TCIFLUSH)
                wait = KEY_TIMEOUT if timeout is None else timeout
                if not select.select([fd], [], [], wait)[0]:
                    return None
                char = terminal.read(1)
            finally:
                termios.tcsetattr(fd, termios.TCSADRAIN, saved)
    except (OSError, termios.error):
        return None
    return char.decode(errors="replace") if char else None


_CLEAR_SRC = """
import json, subprocess, sys, time
cfg = json.loads(sys.argv[1])
orig = sys.stdin.buffer.read()
time.sleep(cfg["delay"])
try:
    if cfg["paste"]:
        cur = subprocess.run(cfg["paste"], capture_output=True, timeout=5).stdout
        if cur.rstrip(b"\\n") != orig.rstrip(b"\\n"):
            sys.exit(0)  # someone copied something else — leave it alone
    subprocess.run(cfg["copy"], input=b"", timeout=5)
except Exception:
    pass
"""


def copy(text: str, clear_after: object = _FROM_CONFIG) -> None:
    """Copy *text* to the clipboard, scheduling an auto-clear.

    With no *clear_after*, the delay is the one from ``sekrt config`` (45 seconds
    when nothing is saved). Pass an int to override it for this copy, or ``0``
    / ``None`` to leave the clipboard alone.
    """
    if clear_after is _FROM_CONFIG:
        from sekrt.prefs import load_settings

        clear_after = load_settings().clipboard_seconds
    elif not isinstance(clear_after, int) and clear_after is not None:
        raise TypeError(f"clear_after must be an int, not {type(clear_after).__name__}")
    tool = _find_tool()
    if tool is None:
        raise ClipboardError(
            "no clipboard tool found — install wl-clipboard, xclip or xsel"
        )
    try:
        subprocess.run(tool.copy_cmd, input=text.encode(), check=True, timeout=5)
    except (subprocess.SubprocessError, OSError) as exc:
        raise ClipboardError(f"copy failed: {exc}") from exc

    if clear_after and text:
        cfg = json.dumps(
            {"delay": clear_after, "copy": tool.copy_cmd, "paste": tool.paste_cmd}
        )
        proc = subprocess.Popen(
            [sys.executable, "-c", _CLEAR_SRC, cfg],
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        assert proc.stdin is not None
        proc.stdin.write(text.encode())
        proc.stdin.close()
