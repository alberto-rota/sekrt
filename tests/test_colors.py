import pytest
from textual.widgets import Input, Static

from sekrt import prefs
from sekrt.prefs import DEFAULT_PALETTE, Palette
from sekrt.tui.colors import ColorsApp, PaletteEditor, preview_markup

TEAL = "#00d7af"


def _type(pilot, text: str):
    return pilot.press(*text)


async def _clear(pilot, app, role: str) -> Input:
    field = app.screen.query_one(f"#c-{role}", Input)
    field.focus()
    field.clear()
    await pilot.pause()
    return field


async def test_typing_a_color_repaints_swatch_preview_and_theme():
    app = ColorsApp(DEFAULT_PALETTE)
    async with app.run_test(size=(90, 10)) as pilot:
        await pilot.pause()
        await _clear(pilot, app, "accent")
        await _type(pilot, TEAL)
        await pilot.pause()

        editor = app.query_one(PaletteEditor)
        assert editor.palette.accent == TEAL
        assert editor.palette.primary == DEFAULT_PALETTE.primary  # untouched
        assert TEAL in str(app.query_one("#sw-accent", Static).content)
        assert TEAL in str(app.query_one("#preview", Static).content)
        assert app.current_theme.accent == TEAL  # the chrome follows too


async def test_a_half_typed_color_marks_the_field_and_changes_nothing():
    """Mid-typing is not an error to argue with: the last color that parsed stays."""
    app = ColorsApp(DEFAULT_PALETTE)
    async with app.run_test(size=(90, 10)) as pilot:
        await pilot.pause()
        field = await _clear(pilot, app, "primary")
        editor = app.query_one(PaletteEditor)

        await _type(pilot, "#00d")  # three-digit hex — already a color
        await pilot.pause()
        assert editor.palette.primary == "#0000dd"
        assert not field.has_class("-bad-color")

        await _type(pilot, "7a")  # five digits — not a color at all
        await pilot.pause()
        assert editor.palette.primary == "#0000dd"  # unchanged, not reset
        assert field.has_class("-bad-color")

        await _type(pilot, "f")
        await pilot.pause()
        assert editor.palette.primary == TEAL
        assert not field.has_class("-bad-color")


async def test_enter_saves_and_escape_cancels():
    app = ColorsApp(DEFAULT_PALETTE)
    async with app.run_test(size=(90, 10)) as pilot:
        await pilot.pause()
        await _clear(pilot, app, "secondary")
        await _type(pilot, TEAL)
        await pilot.press("enter")
    assert app.return_value[0] == Palette(secondary=TEAL)

    app = ColorsApp(DEFAULT_PALETTE)
    async with app.run_test(size=(90, 10)) as pilot:
        await pilot.pause()
        await _clear(pilot, app, "secondary")
        await _type(pilot, TEAL)
        await pilot.press("escape")
    assert app.return_value is None


async def test_ctrl_r_restores_the_stock_colors():
    app = ColorsApp(Palette(primary=TEAL, secondary=TEAL, accent=TEAL))
    async with app.run_test(size=(90, 10)) as pilot:
        await pilot.pause()
        await pilot.press("ctrl+r")
        await pilot.pause()
        assert app.query_one(PaletteEditor).palette == DEFAULT_PALETTE
        assert app.screen.query_one("#c-accent", Input).value == DEFAULT_PALETTE.accent
        assert app.current_theme.accent == DEFAULT_PALETTE.accent


async def test_the_panel_claims_only_the_lines_it_needs():
    """It draws inline, in the middle of your scrollback: the rows it has, no more."""
    app = ColorsApp(DEFAULT_PALETTE)
    async with app.run_test(size=(90, 14)) as pilot:
        await pilot.pause()
        assert app.screen.styles.height.value == 13


def test_preview_shows_every_chosen_color():
    markup = preview_markup(Palette(primary="#111111", secondary="#222222", accent="#333333"))
    assert "#111111" in markup and "#222222" in markup and "#333333" in markup


@pytest.mark.parametrize("app_factory", [lambda: ColorsApp(), lambda: ColorsApp(None)])
async def test_the_panel_opens_without_being_handed_a_palette(app_factory):
    app = app_factory()
    async with app.run_test(size=(90, 10)) as pilot:
        await pilot.pause()
        assert app.query_one(PaletteEditor).palette == DEFAULT_PALETTE


async def test_the_picker_draws_its_cursor_in_the_chosen_accent():
    prefs.save_palette(Palette(accent=TEAL))
    from sekrt.tui.picker import MARKER, PickerApp

    app = PickerApp(["work/github", "cloud/aws"])
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        marked = str(app.query_one("#options").options[0].prompt)
        assert MARKER in marked and TEAL in marked
        assert app.current_theme.accent == TEAL


async def test_arrowing_the_preset_row_applies_each_palette_as_you_land_on_it():
    from sekrt.prefs import PRESET_NAMES, PRESETS
    from sekrt.tui.colors import PresetBar

    app = ColorsApp(DEFAULT_PALETTE)
    async with app.run_test(size=(90, 12)) as pilot:
        await pilot.pause()
        bar = app.query_one(PresetBar)
        assert app.focused is bar  # presets first: the fastest way through the panel
        assert bar.selected == "metal"

        await pilot.press("right")
        await pilot.pause()
        second = PRESET_NAMES[1]
        assert bar.selected == second
        assert app.query_one(PaletteEditor).palette == PRESETS[second]
        assert app.screen.query_one("#c-accent", Input).value == PRESETS[second].accent
        assert app.current_theme.accent == PRESETS[second].accent  # the panel repaints

        await pilot.press("left", "left")  # wraps past the first, to the last
        await pilot.pause()
        assert bar.selected == PRESET_NAMES[-1]

        await pilot.press("enter")
    assert app.return_value[0] == PRESETS[PRESET_NAMES[-1]]


async def test_a_hand_typed_color_deselects_the_preset_and_a_match_reselects_it():
    from sekrt.prefs import PRESETS
    from sekrt.tui.colors import PresetBar

    app = ColorsApp(PRESETS["mono"])
    async with app.run_test(size=(90, 12)) as pilot:
        await pilot.pause()
        bar = app.query_one(PresetBar)
        assert bar.selected == "mono"

        field = await _clear(pilot, app, "accent")
        await _type(pilot, TEAL)
        await pilot.pause()
        assert bar.selected is None  # no longer any preset

        field.clear()
        await pilot.pause()
        await _type(pilot, PRESETS["mono"].accent)
        await pilot.pause()
        assert bar.selected == "mono"


async def test_clicking_a_preset_chip_picks_it():
    from sekrt.prefs import PRESETS
    from sekrt.tui.colors import PresetBar

    app = ColorsApp(DEFAULT_PALETTE)
    async with app.run_test(size=(90, 12)) as pilot:
        await pilot.pause()
        await pilot.click("#p-indigo")
        await pilot.pause()
        assert app.query_one(PresetBar).selected == "indigo"
        assert app.query_one(PaletteEditor).palette == PRESETS["indigo"]


async def test_stepping_from_a_tuned_palette_starts_at_either_end():
    from sekrt.prefs import PRESET_NAMES
    from sekrt.tui.colors import PresetBar

    app = ColorsApp(Palette(primary=TEAL, secondary=TEAL, accent=TEAL))
    async with app.run_test(size=(90, 12)) as pilot:
        await pilot.pause()
        bar = app.query_one(PresetBar)
        assert bar.selected is None

        await pilot.press("right")
        await pilot.pause()
        assert bar.selected == PRESET_NAMES[0]

        bar.show(None)
        await pilot.press("left")
        await pilot.pause()
        assert bar.selected == PRESET_NAMES[-1]


def test_every_preset_gets_a_chip_of_its_own_colors():
    from sekrt.prefs import PRESETS
    from sekrt.tui.colors import chip_markup

    for name, palette in PRESETS.items():
        chip = chip_markup(name, palette)
        assert chip.endswith(f" {name}")
        for color in palette.to_dict().values():
            assert color in chip


async def test_every_preset_is_on_screen_in_rows_that_fit_eighty_columns():
    from sekrt.prefs import PRESET_NAMES, PRESETS_PER_ROW
    from sekrt.tui.colors import PresetBar

    app = ColorsApp(DEFAULT_PALETTE)
    async with app.run_test(size=(80, 14)) as pilot:
        await pilot.pause()
        bar = app.query_one(PresetBar)
        rows = list(bar.query(".preset-row"))
        assert len(rows) == -(-len(PRESET_NAMES) // PRESETS_PER_ROW)  # ceil
        assert [c.id[2:] for row in rows for c in row.query(".preset")] == list(PRESET_NAMES)

        for row in rows:
            chips = list(row.query(".preset"))
            assert len(chips) <= PRESETS_PER_ROW
            assert chips[-1].region.right <= 80, "a chip row must fit an 80-column terminal"
            assert chips[0].region.x == rows[0].query(".preset")[0].region.x  # rows line up


async def test_arrowing_crosses_from_one_chip_row_to_the_next():
    from sekrt.prefs import PRESET_NAMES, PRESETS_PER_ROW
    from sekrt.tui.colors import PresetBar

    app = ColorsApp(DEFAULT_PALETTE)
    async with app.run_test(size=(90, 14)) as pilot:
        await pilot.pause()
        bar = app.query_one(PresetBar)
        await pilot.press(*["right"] * (PRESETS_PER_ROW - 1))
        await pilot.pause()
        assert bar.selected == PRESET_NAMES[PRESETS_PER_ROW - 1]  # last of row one

        await pilot.press("right")
        await pilot.pause()
        first_of_row_two = PRESET_NAMES[PRESETS_PER_ROW]
        assert bar.selected == first_of_row_two
        chip = bar.query_one(f"#p-{first_of_row_two}")
        assert chip.region.y > bar.query_one(f"#p-{PRESET_NAMES[0]}").region.y
