import pytest
from ananta.output import (
    get_prompt,
    get_end_marker,
    adjust_cursor_with_prompt,
    _get_host_color,  # Import for potential direct testing if needed
    RED,
    GREEN,
    YELLOW,
    BLUE,
    MAGENTA,
    CYAN,
    RESET,  # Import colors
    print_output,
)
from unittest.mock import AsyncMock, patch


ALL_COLORS = [RED, GREEN, YELLOW, BLUE, MAGENTA, CYAN]


# Clear color cache between tests if necessary, though unlikely needed here
@pytest.fixture(autouse=True)
def clear_host_color_cache():
    from ananta.output import HOST_COLOR

    HOST_COLOR.clear()


def test_get_prompt_no_color():
    """Tests prompt generation without color."""
    prompt = get_prompt("myhost", 10, color=False)
    assert prompt == "[    myhost] "  # Padded to max_name_length=10


def test_get_prompt_with_color():
    """Tests prompt generation with color."""
    prompt = get_prompt("host-1", 8, color=True)
    # Check it starts with an ANSI color code, contains the padded name,
    # ends with RESET code and a space.
    assert any([prompt.startswith(color) for color in ALL_COLORS])
    assert "[  host-1]" in prompt
    assert prompt.endswith(f"{RESET} ")
    # Ensure the color assigned is consistent for the same host within a run
    color_code_1 = prompt.split("[")[0]
    prompt_again = get_prompt("host-1", 8, color=True)
    color_code_2 = prompt_again.split("[")[0]
    assert color_code_1 == color_code_2
    # Ensure different hosts get different colors (usually)
    prompt2 = get_prompt("host-2", 8, color=True)
    # This might fail if COLORS cycle wraps around quickly with few hosts
    # but generally should hold true for different hosts.
    assert [prompt.startswith(color) for color in ALL_COLORS] != [
        prompt2.startswith(color) for color in ALL_COLORS
    ]


def test_get_end_marker_no_color():
    """Tests end marker generation without color."""
    marker = get_end_marker("myhost", 20, color=False)
    assert marker == "-" * 20


def test_get_end_marker_with_color():
    """Tests end marker generation with color, matching the host's color."""
    # Get color for host first
    prompt_color_code = get_prompt("myhost", 10, color=True).split("[")[0]
    marker = get_end_marker("myhost", 20, color=True)
    assert marker.startswith(prompt_color_code)
    assert "-" * 20 in marker
    assert marker.endswith(RESET)


# --- Tests for adjust_cursor_with_prompt ---


@pytest.mark.parametrize(
    "line_input, expected_output_no_control",
    [
        ("Simple line", "Simple line"),
        # Colors are kept
        ("Line with \x1b[31mcolor\x1b[0m", "Line with \x1b[31mcolor\x1b[0m"),
        # Cursor control removed
        ("Line with cursor up \x1b[1A", "Line with cursor up "),
        # Screen clear removed
        ("Line with clear screen \x1b[2J", "Line with clear screen "),
        # Carriage return gets prompt prepended
        ("Line \rwith carriage return", "Line \r[prompt] with carriage return"),
        # Erase to beginning gets prompt prepended after jump
        (
            "Text\x1b[1KPartial erase",
            "Text\x1b[1K\x1b[s\x1b[G[prompt] \x1b[uPartial erase",
        ),
        # Erase line gets prompt prepended after jump
        (
            "Text\x1b[2KFull erase",
            "Text\x1b[2K\x1b[s\x1b[G[prompt] \x1b[uFull erase",
        ),
    ],
)
def test_adjust_cursor_no_control(line_input, expected_output_no_control):
    """Tests that cursor controls are stripped when allow_cursor_control=False."""
    prompt = "[prompt] "
    adjusted = adjust_cursor_with_prompt(
        line_input,
        prompt,
        allow_cursor_control=False,
        max_name_length=len(prompt) - 3,
    )
    # We also strip trailing whitespace/ANSI codes in the function
    assert adjusted == expected_output_no_control.rstrip()


@pytest.mark.parametrize(
    "line_input, expected_output_with_control",
    [
        ("Simple line", "Simple line"),
        ("Line with \x1b[31mcolor\x1b[0m", "Line with \x1b[31mcolor\x1b[0m"),
        ("Line with cursor up \x1b[1A", "Line with cursor up \x1b[1A"),  # Kept
        (
            "Line with clear screen \x1b[2J",
            "Line with clear screen \x1b[2J",
        ),  # Kept
        # Carriage return gets prompt prepended
        ("Line \rwith carriage return", "Line \r[prompt] with carriage return"),
        # Erase to beginning gets prompt prepended after jump
        (
            "Text\x1b[1KPartial erase",
            "Text\x1b[1K\x1b[s\x1b[G[prompt] \x1b[uPartial erase",
        ),
        # Erase line gets prompt prepended after jump
        (
            "Text\x1b[2KFull erase",
            "Text\x1b[2K\x1b[s\x1b[G[prompt] \x1b[uFull erase",
        ),
        # Adjust cursor movement to a specific column n+len('[prompt] ')
        (
            "Line with cursor moved to column 1\x1b[1G",
            "Line with cursor moved to column 1\x1b[10G",
        ),
    ],
)
def test_adjust_cursor_with_control(line_input, expected_output_with_control):
    """Tests that cursor controls are adjusted when allow_cursor_control=True."""
    prompt = "[prompt] "
    adjusted = adjust_cursor_with_prompt(
        line_input,
        prompt,
        allow_cursor_control=True,
        max_name_length=len(prompt) - 3,
    )
    assert adjusted == expected_output_with_control.rstrip()


@pytest.mark.asyncio
async def test_print_output_separate_output(capsys):
    """Test print_output with separate_output=True."""
    queue = AsyncMock()
    queue.get.side_effect = [
        "line1\nline2\n",  # Multiline output
        None,  # Signal end
    ]
    lock = AsyncMock()
    with patch("ananta.output.print") as mock_print:
        await print_output(
            host_name="host-1",
            max_name_length=7,
            allow_empty_line=True,
            allow_cursor_control=False,
            separate_output=True,
            print_lock=lock,
            output_queue=queue,
            color=False,
        )
        # Verify print calls
        expected_prompt = "[ host-1] "
        mock_print.assert_any_call(f"{expected_prompt}line1{RESET}")
        mock_print.assert_any_call(f"{expected_prompt}line2{RESET}")
        # Verify lock was used
        lock.__aenter__.assert_called()


@pytest.mark.asyncio
async def test_print_output_interleaved(capsys):
    """Test print_output with separate_output=False."""
    queue = AsyncMock()
    queue.get.side_effect = [
        "line1\n",  # Single line
        "",  # Empty line
        None,  # Signal end
    ]
    lock = AsyncMock()
    with patch("ananta.output.print") as mock_print:
        await print_output(
            host_name="host-2",
            max_name_length=7,
            allow_empty_line=False,
            allow_cursor_control=False,
            separate_output=False,
            print_lock=lock,
            output_queue=queue,
            color=False,
        )
        # Verify only non-empty line printed
        expected_prompt = "[ host-2] "
        mock_print.assert_called_once_with(f"{expected_prompt}line1{RESET}")
        # Verify lock was used for each line
        lock.__aenter__.assert_called()
