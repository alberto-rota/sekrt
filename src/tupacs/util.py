"""Small shared helpers."""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
import tempfile
from pathlib import Path

from tupacs import session


class EditorError(Exception):
    pass


def edit_text(initial: str, *, suffix: str = ".json") -> str | None:
    """Open $EDITOR on *initial* in a private (ideally RAM-backed) temp file.

    Returns the new text, or None if unchanged / editor aborted.
    """
    editor = os.environ.get("VISUAL") or os.environ.get("EDITOR")
    if not editor:
        editor = next((e for e in ("nano", "vi") if shutil.which(e)), None)
    if not editor:
        raise EditorError("no editor found — set $EDITOR")

    directory = session.private_tmpdir() or Path(tempfile.gettempdir())
    fd, path = tempfile.mkstemp(dir=directory, suffix=suffix, prefix="tupacs-")
    try:
        os.write(fd, initial.encode())
        os.close(fd)
        result = subprocess.call([*shlex.split(editor), path])
        if result != 0:
            return None
        new = Path(path).read_text()
        return None if new == initial else new
    finally:
        Path(path).unlink(missing_ok=True)
