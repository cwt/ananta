from ananta.tui.ansi import ansi_to_urwid_markup, _AnsiState
import pytest
import urwid

# Mark all tests in this file as TUI tests
pytestmark = pytest.mark.tui


def test_ansi_state_defaults():
    """Tests the default initial state of _AnsiState."""
    state = _AnsiState()
    assert state.fg == "default"
    assert state.bg == "default"
    assert state.styles == set()
    spec = state.get_attr_spec()
    assert spec.foreground == "default"
    assert spec.background == "default"


def test_ansi_state_styling():
    """Tests applying styles and colors to _AnsiState."""
    state = _AnsiState()
    state.styles.add("bold")
    state.styles.add("underline")
    state.fg = "light red"
    state.bg = "dark blue"

    spec = state.get_attr_spec()
    # Urwid combines styles into the foreground string
    assert set(spec.foreground.split(",")) == set(
        ["bold", "underline", "light red"]
    )
    assert spec.background == "dark blue"


def test_ansi_state_reverse():
    """Tests the 'reverse' style which swaps foreground and background."""
    state = _AnsiState()
    state.styles.add("reverse")
    state.fg = "light red"
    state.bg = "dark blue"

    spec = state.get_attr_spec()
    assert spec.foreground == "dark blue"  # Swapped
    assert spec.background == "light red"  # Swapped


def test_ansi_state_conceal():
    """Tests the 'conceal' style which makes foreground same as background."""
    state = _AnsiState()
    state.styles.add("conceal")
    state.fg = "light red"
    state.bg = "dark blue"

    spec = state.get_attr_spec()
    assert spec.foreground == "dark blue"  # Swapped to be same as background
    assert spec.background == "dark blue"


def test_ansi_state_reset():
    """Tests resetting the state to defaults."""
    state = _AnsiState()
    state.styles.add("bold")
    state.fg = "light red"
    state.reset()
    assert state.fg == "default"
    assert state.bg == "default"
    assert state.styles == set()


@pytest.mark.parametrize(
    "input_str, expected_markup",
    [
        (
            "Plain text",
            [(urwid.AttrSpec("default", "default"), "Plain text")],
        ),
        (
            "\x1b[1mbold\x1b[0m normal",
            [
                (urwid.AttrSpec("bold,default", "default"), "bold"),
                (urwid.AttrSpec("default", "default"), " normal"),
            ],
        ),
        (
            "\x1b[4munderline\x1b[24m normal",
            [
                (urwid.AttrSpec("underline,default", "default"), "underline"),
                (urwid.AttrSpec("default", "default"), " normal"),
            ],
        ),
        (
            "\x1b[3mitalics\x1b[23m",
            [(urwid.AttrSpec("italics,default", "default"), "italics")],
        ),
        (
            "\x1b[9mstrikethrough\x1b[29m",
            [
                (
                    urwid.AttrSpec("strikethrough,default", "default"),
                    "strikethrough",
                )
            ],
        ),
        (
            "\x1b[31mdark red fg\x1b[39m",
            [
                (urwid.AttrSpec("dark red", "default"), "dark red fg"),
            ],
        ),
        (
            "\x1b[93myellow fg\x1b[39m",
            [
                (urwid.AttrSpec("yellow", "default"), "yellow fg"),
            ],
        ),
        (
            "\x1b[44mdark blue bg\x1b[49m",
            [
                (urwid.AttrSpec("default", "dark blue"), "dark blue bg"),
            ],
        ),
        (
            "\x1b[102mlight green bg\x1b[49m",
            [
                (urwid.AttrSpec("default", "light green"), "light green bg"),
            ],
        ),
        (
            "\x1b[1;31mbold red\x1b[22;39m normal",
            [
                (urwid.AttrSpec("bold,dark red", "default"), "bold red"),
                (urwid.AttrSpec("default", "default"), " normal"),
            ],
        ),
        (
            "Text with \t tab",
            [
                (
                    urwid.AttrSpec("default", "default"),
                    "Text with        tab",
                )
            ],
        ),
        (
            "Line with cursor up \x1b[1A should be stripped",
            [
                (
                    urwid.AttrSpec("default", "default"),
                    "Line with cursor up  should be stripped",
                )
            ],
        ),
        (
            "Line with \x1b[38;5;208m256-color\x1b[0m text",
            [
                (urwid.AttrSpec("default", "default"), "Line with "),
                (urwid.AttrSpec("h208", "default"), "256-color"),
                (urwid.AttrSpec("default", "default"), " text"),
            ],
        ),
        (
            "\x1b[38;2;10;20;30mtruecolor\x1b[0m",
            [(urwid.AttrSpec("#0a141e", "default"), "truecolor")],
        ),
        (
            "Final text segment",
            [(urwid.AttrSpec("default", "default"), "Final text segment")],
        ),
    ],
)
def test_ansi_to_urwid_markup(input_str, expected_markup):
    """
    Tests the conversion of various ANSI strings to Urwid markup.
    The expected markup is a list of (AttrSpec, text) tuples.
    """
    result = ansi_to_urwid_markup(input_str)
    # Compare AttrSpec properties and text content
    assert len(result) == len(expected_markup)
    for res_item, exp_item in zip(result, expected_markup):
        res_spec, res_text = res_item
        exp_spec, exp_text = exp_item
        assert res_text == exp_text
        assert res_spec.foreground == exp_spec.foreground
        assert res_spec.background == exp_spec.background
