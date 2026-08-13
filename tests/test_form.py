import pytest
from textual.widgets import Input, Label

from sekrt.tui.form import MARKER, Choice, Field, FormApp

FIELDS = [
    Field("name", "name", placeholder="work/github", required=True),
    Field("type", "type", choices=("password", "api_key", "note")),
    Field("secret", "secret", secret=True, generate=True),
    Field("url", "url"),
]


def form(**kwargs) -> FormApp:
    return FormApp([Field(f.key, f.label, f.placeholder, f.value, f.secret, f.required,
                          f.generate, f.choices) for f in FIELDS], **kwargs)


async def test_typing_fills_the_focused_field_and_enter_saves():
    app = form(title="new entry")
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.press("w", "o", "r", "k")
        await pilot.press("tab", "tab")  # past the choice row, into `secret`
        await pilot.press("s", "3", "c")
        await pilot.press("enter")
    assert app.return_value == {"name": "work", "type": "password", "secret": "s3c", "url": ""}


async def test_arrows_walk_a_choice_row():
    app = form()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.press("x")  # the required name
        await pilot.press("tab")
        await pilot.press("right", "right")
        await pilot.pause()
        assert app.query_one("#f-type", Choice).value == "note"
        await pilot.press("left")
        await pilot.pause()
        assert app.query_one("#f-type", Choice).value == "api_key"
        await pilot.press("right", "right")  # wraps around the end
        await pilot.pause()
        assert app.query_one("#f-type", Choice).value == "password"


async def test_the_chosen_option_is_the_only_one_wearing_the_cursor():
    app = form()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        row = str(app.query_one("#f-type", Choice).content)
        assert row.count(MARKER) == 1
        assert row.index(MARKER) < row.index("api key")  # the first option, to start


async def test_ctrl_g_generates_the_secret_without_showing_it():
    app = form()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.press("ctrl+g")
        await pilot.pause()
        secret = app.query_one("#f-secret", Input)
        assert len(secret.value) == 20
        assert secret.password  # masked on screen


async def test_a_required_field_left_empty_does_not_save():
    app = form()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.press("enter")
        await pilot.pause()
        assert app.is_running
        assert "name is required" in str(app.query_one("#form-hint", Label).content)
        assert app.query_one("#f-name", Input).has_class("-missing")

        await pilot.press("x")  # typing clears the complaint
        await pilot.pause()
        assert not app.query_one("#f-name", Input).has_class("-missing")
        await pilot.press("enter")
    assert app.return_value["name"] == "x"


async def test_a_secret_keeps_its_spaces_while_the_other_fields_are_trimmed():
    app = FormApp([Field("secret", "secret", secret=True), Field("url", "url")])
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.press("space", "a", "space")
        await pilot.press("tab")
        await pilot.press("space", "b", "space")
        await pilot.press("enter")
    assert app.return_value == {"secret": " a ", "url": "b"}


async def test_escape_cancels():
    app = form()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.press("a")
        await pilot.press("escape")
    assert app.return_value is None


@pytest.mark.parametrize(
    "fields, title, expected",
    [
        ([Field("a", "a")], "", 2),  # one field + hint
        ([Field("a", "a")], "new entry", 3),  # + title
        ([Field(k, k) for k in "abcdef"], "new entry", 8),
    ],
)
async def test_the_form_claims_only_the_lines_it_needs(fields, title, expected):
    app = FormApp(fields, title=title)
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        assert app.screen.styles.height.value == expected


async def test_the_hint_only_offers_keys_this_form_has():
    plain = FormApp([Field("a", "a")])
    async with plain.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        assert "choose" not in plain.hint() and "ctrl+g" not in plain.hint()

    full = form()
    async with full.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        assert "←→ choose" in full.hint() and "ctrl+g generate" in full.hint()
