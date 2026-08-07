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
import shutil
import subprocess
import sys
from dataclasses import dataclass

DEFAULT_CLEAR_AFTER = 45


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


def copy(text: str, clear_after: int | None = DEFAULT_CLEAR_AFTER) -> None:
    """Copy *text* to the clipboard, scheduling an auto-clear."""
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
