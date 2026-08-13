import json

import pytest

from sekrt import prefs
from sekrt.prefs import DEFAULT_PALETTE, Palette, PrefsError


@pytest.mark.parametrize(
    "typed,expected",
    [
        ("#00d7af", "#00d7af"),
        ("#00D7AF", "#00d7af"),
        ("00d7af", "#00d7af"),
        ("#f55", "#ff5555"),
        ("0d7", "#00dd77"),
        ("cyan", "#00ffff"),
        ("  #00d7af  ", "#00d7af"),
        ("rgb(0,215,175)", "#00d7af"),
    ],
)
def test_parse_color_accepts_what_people_type(typed, expected):
    assert prefs.parse_color(typed) == expected


@pytest.mark.parametrize("typed", ["", "  ", "nope", "#12345", "#gggggg", "rgb(1,2)"])
def test_parse_color_rejects_the_rest(typed):
    with pytest.raises(PrefsError):
        prefs.parse_color(typed)


def test_parse_color_drops_alpha():
    """A translucent border would sit over the wrong background — keep it opaque."""
    assert prefs.parse_color("#00d7af80") == "#00d7af"


def test_with_color_normalizes_and_leaves_the_rest_alone():
    palette = DEFAULT_PALETTE.with_color("accent", "CYAN")
    assert palette.accent == "#00ffff"
    assert palette.primary == DEFAULT_PALETTE.primary
    with pytest.raises(PrefsError):
        DEFAULT_PALETTE.with_color("backround", "#000000")  # typo'd role


def test_load_returns_the_defaults_when_nothing_is_saved():
    assert not prefs.prefs_path().exists()
    assert prefs.load_palette() == DEFAULT_PALETTE


def test_save_then_load_round_trips():
    palette = Palette(primary="#8fb3ff", secondary="#5f6672", accent="#00d7af")
    path = prefs.save_palette(palette)
    assert json.loads(path.read_text())["colors"]["accent"] == "#00d7af"
    assert prefs.load_palette() == palette


def test_reset_goes_back_to_the_stock_colors():
    prefs.save_palette(Palette(accent="#00d7af"))
    prefs.reset_palette()
    assert prefs.load_palette() == DEFAULT_PALETTE
    prefs.reset_palette()  # already gone — still fine


def test_a_hand_edited_file_costs_at_most_one_color():
    """A broken config must never be the reason you can't open your vault."""
    path = prefs.prefs_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"colors": {"primary": "#00d7af", "accent": "banana"}}))
    palette = prefs.load_palette()
    assert palette.primary == "#00d7af"
    assert palette.accent == DEFAULT_PALETTE.accent


@pytest.mark.parametrize("garbage", ["not json at all", "[]", '{"colors": "red"}', "{}"])
def test_unusable_files_fall_back_to_the_defaults(garbage):
    path = prefs.prefs_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(garbage)
    assert prefs.load_palette() == DEFAULT_PALETTE


def test_sekrt_config_env_overrides_the_location(tmp_path, monkeypatch):
    elsewhere = tmp_path / "custom" / "colors.json"
    monkeypatch.setenv("SEKRT_CONFIG", str(elsewhere))
    prefs.save_palette(Palette(accent="#00d7af"))
    assert elsewhere.is_file()
    assert prefs.load_palette().accent == "#00d7af"


def test_every_preset_is_three_usable_colors():
    for name, palette in prefs.PRESETS.items():
        assert name == name.lower() and " " not in name
        for role in prefs.ROLES:
            color = getattr(palette, role)
            assert prefs.parse_color(color) == color, f"{name}.{role} is not normalized"


def test_metal_is_the_stock_palette_and_comes_first():
    assert prefs.PRESET_NAMES[0] == "metal"
    assert prefs.PRESETS["metal"] == DEFAULT_PALETTE


def test_preset_lookup_is_forgiving_about_case_and_spaces():
    assert prefs.preset("  TEAL ") == prefs.PRESETS["teal"]


def test_unknown_preset_names_what_is_available():
    with pytest.raises(PrefsError) as exc:
        prefs.preset("burnt-sienna")
    assert "metal" in str(exc.value) and "mono" in str(exc.value)


def test_preset_name_recognizes_a_palette_and_gives_up_on_a_tuned_one():
    assert prefs.preset_name(prefs.PRESETS["amber"]) == "amber"
    assert prefs.preset_name(DEFAULT_PALETTE) == "metal"
    assert prefs.preset_name(prefs.PRESETS["amber"].with_color("accent", "cyan")) is None


def test_presets_are_all_different():
    assert len({tuple(p.to_dict().values()) for p in prefs.PRESETS.values()}) == len(prefs.PRESETS)
