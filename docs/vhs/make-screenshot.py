#!/usr/bin/env python3
"""Regenerate docs/screenshot.svg — the still image at the top of the README.

The GIFs next to this file are recorded with VHS; a Textual app can export its
own SVG, so this one is scripted instead. Run it from the repo root:

    uv run python docs/vhs/make-screenshot.py

It builds a throwaway vault in a temp directory (never your real one), fills it
with representative entries, selects the SSH key so the detail pane has both a
masked and an unmasked field to show, and writes docs/screenshot.svg.
"""

from __future__ import annotations

import asyncio
import os
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src"))

# A cheap KDF: this vault is thrown away, and it keeps the script snappy.
os.environ["SEKRT_SCRYPT_N"] = "2048"

from sekrt.tui.app import SekrtApp  # noqa: E402
from sekrt.vault import Vault, new_entry  # noqa: E402

OUTPUT = REPO_ROOT / "docs" / "screenshot.svg"
SELECT = "ssh/deploy"

PW = {"password": "EXAMPLE-not-a-real-password", "username": "alberto"}
ENV_CONTENT = "DATABASE_URL=postgres://localhost/my_saas\nSTRIPE_SECRET_KEY=sk_test_EXAMPLE\n"
PRIVATE_KEY = "-----BEGIN OPENSSH PRIVATE KEY-----\nEXAMPLE\n-----END OPENSSH PRIVATE KEY-----\n"

DEMO_ENTRIES = [
    ("cloud/aws-root", "api_key", {"key": "AKIAIOSFODNN7EXAMPLE", "username": "root"}),
    ("cloud/openai", "api_key", {"key": "sk-proj-EXAMPLE-NOT-A-REAL-KEY"}),
    ("env/github.com/alberto/my-saas/.env", "env", {"content": ENV_CONTENT}),
    ("personal/bank", "password", PW),
    ("ssh/deploy", "ssh", {"private": PRIVATE_KEY, "public": "ssh-ed25519 AAA... deploy"}),
    ("work/github", "password", PW),
    ("work/gitlab", "password", PW),
]


def build_vault(root: Path) -> tuple[Vault, bytes]:
    vault = Vault(root / "vault")
    key = vault.create("screenshot-passphrase")
    for name, type_, data in DEMO_ENTRIES:
        vault.write(key, name, new_entry(type_, data))
    return vault, key


async def main() -> int:
    with tempfile.TemporaryDirectory(prefix="sekrt-screenshot-") as tmp:
        vault, key = build_vault(Path(tmp))
        app = SekrtApp(vault=vault, key=key)
        # 100x33 keeps the exported SVG close to the previous image's proportions.
        async with app.run_test(size=(100, 33)) as pilot:
            await pilot.pause()
            tree = app.query_one("#tree")
            node = next((n for n in tree.root.children_flat() if n.data == SELECT), None) \
                if hasattr(tree.root, "children_flat") else None
            if node is None:  # walk the tree ourselves
                stack, node = list(tree.root.children), None
                while stack:
                    candidate = stack.pop(0)
                    if candidate.data == SELECT:
                        node = candidate
                        break
                    stack.extend(candidate.children)
            if node is None:
                raise SystemExit(f"could not find {SELECT!r} in the tree")
            tree.move_cursor(node)
            await pilot.press("enter")
            await pilot.pause()
            if app.current != SELECT:
                raise SystemExit(f"selection failed: detail pane shows {app.current!r}")
            OUTPUT.write_text(app.export_screenshot())

    print(f"wrote {OUTPUT.relative_to(REPO_ROOT)} (selected {SELECT})")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
