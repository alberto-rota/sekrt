import pytest

from sekrt.tui.app import ConfirmModal, SekrtApp, window_chrome_sequences
from sekrt.vault import new_entry


@pytest.fixture
def populated_vault(vault):
    v, key = vault
    v.write(key, "work/github", new_entry("password", {"password": "s3cret", "username": "al"}))
    v.write(key, "personal/bank", new_entry("password", {"password": "pin"}))
    return v, key


async def test_tree_lists_entries(populated_vault):
    v, key = populated_vault
    app = SekrtApp(vault=v, key=key)
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        tree = app.query_one("#tree")
        labels = {str(node.label) for node in tree.root.children}
        assert labels == {"📁 work", "📁 personal"}


async def test_select_shows_masked_detail(populated_vault):
    v, key = populated_vault
    app = SekrtApp(vault=v, key=key)
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


async def test_note_field_masked_by_default(vault):
    v, key = vault
    v.write(key, "wifi/office", new_entry("note", {"notes": "WPA2 s3cr3t-phrase"}))
    app = SekrtApp(vault=v, key=key)
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        leaf = app.query_one("#tree").root.children[0].children[0]
        app.query_one("#tree").select_node(leaf)
        await pilot.pause()
        assert "s3cr3t-phrase" not in app.detail_markup

        await pilot.press("r")
        assert "s3cr3t-phrase" in app.detail_markup


async def test_unlock_screen_shown_when_locked(vault):
    v, _ = vault
    app = SekrtApp(vault=v)  # no key provided, no session cache
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        assert app.screen.__class__.__name__ == "UnlockScreen"


async def test_window_chrome_follows_the_active_screen(populated_vault):
    """Each screen retitles (and recolours) the window like a freshly opened tab."""
    v, key = populated_vault
    app = SekrtApp(vault=v, key=key)
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        main = app.window_chrome
        assert main == (f"sekrt — {v.path.name}", SekrtApp.WINDOW_BACKGROUND)

        await pilot.press("a")  # add entry
        await pilot.pause()
        assert app.window_chrome == ("sekrt — new entry", None)

        await pilot.press("escape")
        await pilot.pause()
        assert app.window_chrome == main

        leaf = app.query_one("#tree").root.children[0].children[0]
        app.query_one("#tree").select_node(leaf)
        await pilot.pause()
        await pilot.press("d")  # delete confirmation
        await pilot.pause()
        title, background = app.window_chrome
        assert title == "sekrt — confirm"
        assert background == ConfirmModal.WINDOW_BACKGROUND

        await pilot.press("n")
        await pilot.pause()
        assert app.window_chrome == main


def test_window_chrome_sequences_reset_background_when_unset():
    assert window_chrome_sequences("sekrt", "#1c0000") == "\x1b]0;sekrt\x07\x1b]11;#1c0000\x07"
    assert window_chrome_sequences("sekrt", None) == "\x1b]0;sekrt\x07\x1b]111\x07"


async def test_search_filters_tree(populated_vault):
    v, key = populated_vault
    app = SekrtApp(vault=v, key=key)
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        app.refresh_tree("bank")
        await pilot.pause()
        tree = app.query_one("#tree")
        labels = {str(node.label) for node in tree.root.children}
        assert labels == {"📁 personal"}


async def test_colors_modal_previews_live_saves_on_enter(populated_vault):
    """`t` opens the editor; the TUI behind it repaints, and enter persists."""
    from textual.widgets import Input

    from sekrt.prefs import load_palette
    from sekrt.tui.app import PaletteModal

    v, key = populated_vault
    app = SekrtApp(vault=v, key=key)
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        leaf = app.query_one("#tree").root.children[0].children[0]
        app.query_one("#tree").select_node(leaf)
        await pilot.pause()

        await pilot.press("t")
        await pilot.pause()
        assert isinstance(app.screen, PaletteModal)
        assert app.window_chrome == ("sekrt — colors", None)

        field = app.screen.query_one("#c-accent", Input)
        field.focus()
        field.clear()
        await pilot.pause()
        await pilot.press(*"#00d7af")
        await pilot.pause()
        assert app.current_theme.accent == "#00d7af"  # live, before saving

        await pilot.press("enter")
        await pilot.pause()
        assert app.palette.accent == "#00d7af"
        assert load_palette().accent == "#00d7af"  # written to the config file
        assert "#00d7af" in app.detail_markup  # the entry's fields, recolored


async def test_cancelling_the_colors_modal_restores_the_old_palette(populated_vault):
    from textual.widgets import Input

    from sekrt.prefs import DEFAULT_PALETTE, prefs_path

    v, key = populated_vault
    app = SekrtApp(vault=v, key=key)
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        await pilot.press("t")
        await pilot.pause()
        field = app.screen.query_one("#c-accent", Input)
        field.focus()
        field.clear()
        await pilot.pause()
        await pilot.press(*"#00d7af")
        await pilot.pause()

        await pilot.press("escape")
        await pilot.pause()
        assert app.palette == DEFAULT_PALETTE
        assert app.current_theme.accent == DEFAULT_PALETTE.accent
        assert not prefs_path().exists()


async def test_the_tui_starts_in_the_saved_colors(vault):
    from sekrt.prefs import Palette, save_palette

    save_palette(Palette(primary="#8fb3ff", accent="#00d7af"))
    v, key = vault
    app = SekrtApp(vault=v, key=key)
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        assert app.current_theme.primary == "#8fb3ff"
        assert "#00d7af" in app.detail_markup  # the welcome line's key hints


async def test_arrowing_a_preset_in_the_modal_and_saving_from_the_preset_row(vault):
    """The quick path: `t`, arrow to a palette, enter — no typing at all."""
    from sekrt.prefs import PRESET_NAMES, PRESETS, load_palette
    from sekrt.tui.colors import PresetBar

    v, key = vault
    app = SekrtApp(vault=v, key=key)
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        await pilot.press("t")
        await pilot.pause()
        bar = app.screen.query_one(PresetBar)
        assert app.focused is bar

        await pilot.press("right")
        await pilot.pause()
        expected = PRESETS[PRESET_NAMES[1]]
        assert app.current_theme.primary == expected.primary  # live behind the modal

        await pilot.press("enter")
        await pilot.pause()
        assert app.palette == expected
        assert load_palette() == expected
