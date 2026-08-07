import pytest

from tupacs.tui.app import TupacsApp
from tupacs.vault import new_entry


@pytest.fixture
def populated_vault(vault):
    v, key = vault
    v.write(key, "work/github", new_entry("password", {"password": "s3cret", "username": "al"}))
    v.write(key, "personal/bank", new_entry("password", {"password": "pin"}))
    return v, key


async def test_tree_lists_entries(populated_vault):
    v, key = populated_vault
    app = TupacsApp(vault=v, key=key)
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        tree = app.query_one("#tree")
        labels = {str(node.label) for node in tree.root.children}
        assert labels == {"📁 work", "📁 personal"}


async def test_select_shows_masked_detail(populated_vault):
    v, key = populated_vault
    app = TupacsApp(vault=v, key=key)
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        leaf = app.query_one("#tree").root.children[0].children[0]
        app.query_one("#tree").select_node(leaf)
        await pilot.pause()
        assert app.current is not None
        assert app.current_entry["data"]["password"] in ("s3cret", "pin")
        assert "s3cret" not in app.detail_markup  # masked by default
        assert "pin" not in app.detail_markup

        await pilot.press("r")  # reveal
        assert "s3cret" in app.detail_markup or "pin" in app.detail_markup


async def test_unlock_screen_shown_when_locked(vault):
    v, _ = vault
    app = TupacsApp(vault=v)  # no key provided, no session cache
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        assert app.screen.__class__.__name__ == "UnlockScreen"


async def test_search_filters_tree(populated_vault):
    v, key = populated_vault
    app = TupacsApp(vault=v, key=key)
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        app.refresh_tree("bank")
        await pilot.pause()
        tree = app.query_one("#tree")
        labels = {str(node.label) for node in tree.root.children}
        assert labels == {"📁 personal"}
