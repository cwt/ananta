from ananta.tui.ansi import _strip_ansi_control_sequences
import pytest

# Mark all tests in this file as TUI tests
pytestmark = pytest.mark.tui


@pytest.mark.parametrize(
    "input_str, expected_output",
    [
        ("plain text", "plain text"),
        ("\x1b[1mbold\x1b[0m", "\x1b[1mbold\x1b[0m"),  # SGR sequences are kept
        ("\x1b[31mred\x1b[0m", "\x1b[31mred\x1b[0m"),  # SGR sequences are kept
        ("\x1b[1Atext", "text"),  # Non-SGR CSI sequence is stripped
        ("text\x1b[2J", "text"),  # Non-SGR CSI sequence is stripped
        ("text\r\n", "text\r\n"),  # Carriage return and newline are kept
        ("text\r", "text\r"),  # Carriage return is kept
        (
            "line1\rline2",
            "line2",
        ),  # Only the part after the last carriage return is kept
    ],
)
def test_strip_ansi_control_sequences(input_str, expected_output):
    """Test the _strip_ansi_control_sequences function."""
    assert _strip_ansi_control_sequences(input_str) == expected_output
