import pytest

from ananta.tui.ansi import _strip_ansi_control_sequences

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
        ("line1\rline2\r\n", "line2\r\n"),  # Carriage return with trailing CRLF
        ("line1\rline2\n", "line2\n"),  # Carriage return with trailing LF
        ("line1\rline2\r", "line2\r"),  # Carriage return with trailing CR
        (
            "step1\rstep2\rstep3\r\n",
            "step3\r\n",
        ),  # Multiple carriage returns with CRLF
        ("\rhello\r\n", "hello\r\n"),  # Leading carriage return with CRLF
        (
            "line1\r\r\rline2\r\n",
            "line2\r\n",
        ),  # Consecutive carriage returns with CRLF
        # C0 control characters are stripped
        ("bell\x07here", "bellhere"),
        ("a\x0bb", "ab"),
        # C1 control characters are stripped
        ("esc\x9bhalf", "eschalf"),
        # DCS sequences are stripped
        ("\x1bP1;2q\x1b\\", ""),
        # APC sequences are stripped
        ("\x1b_info\x1b\\", ""),
        # PM sequences are stripped
        ("\x1b^secret\x1b\\", ""),
        # Mixed: SGR kept, control stripped
        ("\x1b[31mred\x1b[0m\x07clean", "\x1b[31mred\x1b[0mclean"),
    ],
)
def test_strip_ansi_control_sequences(input_str, expected_output):
    """Test the _strip_ansi_control_sequences function."""
    assert _strip_ansi_control_sequences(input_str) == expected_output
