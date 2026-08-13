import pytest
from textual.widgets import Label, OptionList

from sekrt.tui.picker import MARKER, PickerApp, icon_for, rank

NAMES = ["cloud/aws-access-key-prod", "cloud/aws-key-staging", "work/github", "ssh/deploy-key"]


def test_rank_without_query_keeps_every_entry():
    assert rank(NAMES, "  ") == NAMES


def test_rank_prefers_substring_then_shortest():
    assert rank(NAMES, "aws")[0] == "cloud/aws-key-staging"


def test_rank_matches_scattered_subsequence():
    assert rank(NAMES, "wgh") == ["work/github"]  # w-ork/g-it-h-ub
    assert rank(NAMES, "zzz") == []


def test_rank_is_case_insensitive():
    assert rank(["Work/GitHub"], "github") == ["Work/GitHub"]


def test_icon_reflects_the_name_prefix():
    assert icon_for("ssh/deploy-key") == "🔑"
    assert icon_for("env/github.com/me/proj/.env") == "📄"
    assert icon_for("cloud/aws-key") == "🔐"


async def test_typing_filters_and_enter_picks():
    app = PickerApp(NAMES)
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.press("s", "t", "a", "g")
        await pilot.pause()
        assert app.matches == ["cloud/aws-key-staging"]
        await pilot.press("enter")
    assert app.return_value == "cloud/aws-key-staging"


async def test_arrows_move_the_highlight_while_typing():
    app = PickerApp(NAMES, query="key")
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        first = app.matches[0]
        await pilot.press("down")
        await pilot.press("enter")
    assert app.return_value == app.matches[1]
    assert app.return_value != first


def _cursor(app: PickerApp) -> int | None:
    """Index of the single row wearing the ❯ cursor."""
    options = app.query_one("#options", OptionList)
    marked = [i for i, option in enumerate(options.options) if MARKER in str(option.prompt)]
    assert len(marked) <= 1, "the cursor must never be on two rows at once"
    return marked[0] if marked else None


async def test_cursor_marks_the_highlighted_row_and_wraps():
    app = PickerApp(NAMES)
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        assert _cursor(app) == 0

        await pilot.press("down")
        await pilot.pause()
        assert _cursor(app) == 1

        await pilot.press("up", "up")  # wraps around the top
        await pilot.pause()
        assert _cursor(app) == len(NAMES) - 1

        await pilot.press("a", "w", "s")  # a new filter puts it back on top
        await pilot.pause()
        assert _cursor(app) == 0

        await pilot.press("z")  # nothing matches: no cursor anywhere
        await pilot.pause()
        assert _cursor(app) is None


async def test_escape_cancels():
    app = PickerApp(NAMES)
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.press("escape")
    assert app.return_value is None


async def test_enter_on_an_empty_match_list_does_nothing():
    app = PickerApp(NAMES)
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.press("z", "z", "z")
        await pilot.pause()
        assert app.matches == []
        assert "no entry matches" in str(app.query_one("#hint", Label).content)
        await pilot.press("enter")
        await pilot.pause()
        assert app.is_running
        await pilot.press("escape")
    assert app.return_value is None


@pytest.mark.parametrize("count,expected", [(1, 3), (3, 5), (50, 10)])
async def test_picker_claims_only_the_lines_it_needs(count, expected):
    app = PickerApp([f"entry/{i}" for i in range(count)])
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        assert app.screen.styles.height.value == expected
