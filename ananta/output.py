import asyncio
import re
from itertools import cycle
from random import shuffle

from . import BLUE, CYAN, GREEN, MAGENTA, RED, RESET, YELLOW


def _make_color_cycle(colors: list[str]) -> cycle:
    """Shuffle a list of color strings and return a cycle iterator."""
    shuffled = list(colors)
    shuffle(shuffled)
    return cycle(shuffled)


COLORS = [RED, GREEN, YELLOW, BLUE, MAGENTA, CYAN]
COLORS_CYCLE = _make_color_cycle(COLORS)
HOST_COLOR: dict[str, str] = {}  # Dictionary to store host colors

# Patterns to match control and query ANSI codes
_ANSI_CONTROL_SEQUENCES = re.compile(
    r"(?:[\x00-\x08\x0B\x0C\x0E-\x1A\x1C-\x1F]"
    r"|[\x80-\x9F]"
    r"|\x1bP[^\x1b]*(?:\x1b\\|$)"
    r"|\x1b_[^\x1b]*(?:\x1b\\|$)"
    r"|\x1b\^[^\x1b]*(?:\x1b\\|$))"
)
_OSC_CONTROL_SEQUENCES = re.compile(
    r"\x1b\][^\x07\x1b]*(?:\x07|\x1b\\|$)", re.DOTALL
)
_NON_SGR_CSI_SEQUENCES = re.compile(r"\x1b\[[0-9;?><=]*[A-Za-ln-z]")
_TERMINAL_QUERY_SEQUENCES = re.compile(
    r"\x1b\[[?0-9;]*n|"  # DSR / CPR (e.g. \x1b[6n, \x1b[5n)
    r"\x1b\[[>?0-9;]*c|"  # DA (Device Attributes e.g. \x1b[c, \x1b[>c)
    r"\x1b\[[>?0-9;]*q|"  # XTVERSION query
    r"\x1b\[[0-9;]*t"  # Window title/size reports
)

ansi_cursor_control = _NON_SGR_CSI_SEQUENCES

# Pattern to match cursor movement to a specific column (\x1b[nG)
ansi_cursor_move_to_column = re.compile(r"\x1b\[(\d+)?G")


def adjust_cursor_with_prompt(
    line: str, prompt: str, allow_cursor_control: bool, max_name_length: int
) -> str:
    """Adjust the cursor control codes to display correctly with Ananta prompt."""
    if "\x1b" in line:
        line = _OSC_CONTROL_SEQUENCES.sub("", line)
    line = _ANSI_CONTROL_SEQUENCES.sub("", line)

    if "\x1b" not in line:
        return line.rstrip()

    if not allow_cursor_control:
        line = _NON_SGR_CSI_SEQUENCES.sub("", line)
    else:
        line = _TERMINAL_QUERY_SEQUENCES.sub("", line)
        # Adjust \x1b[nG to account for prompt length
        prompt_offset = max_name_length + 3

        def adjust_cursor_movement(match: re.Match) -> str:
            n = int(match.group(1)) if match.group(1) else 1
            n += prompt_offset
            return f"\x1b[{n}G"

        line = ansi_cursor_move_to_column.sub(adjust_cursor_movement, line)

        # If erase to the beginning of line, jump to col 0, add prompt, then return
        if "\x1b[1K" in line:
            line = line.replace("\x1b[1K", f"\x1b[1K\x1b[s\x1b[G{prompt}\x1b[u")

        # If erase the whole line, jump to col 0, add prompt, then return
        if "\x1b[2K" in line:
            line = line.replace("\x1b[2K", f"\x1b[2K\x1b[s\x1b[G{prompt}\x1b[u")

    return line.rstrip()


def _get_host_color(host_name: str) -> str:
    """Get the color associated with the host name."""
    if HOST_COLOR.get(host_name) is None:
        # If the host name is not in the dictionary, assign a new color
        HOST_COLOR[host_name] = next(COLORS_CYCLE)
    return HOST_COLOR[host_name]


def get_prompt(host_name: str, max_name_length: int, color: bool) -> str:
    """Generate a formatted prompt for displaying the host's name."""
    if color:
        return f"{_get_host_color(host_name)}[{host_name.rjust(max_name_length)}]{RESET} "
    return f"[{host_name.rjust(max_name_length)}] "


def get_end_marker(host_name: str, remote_width: int, color: bool) -> str:
    """Generate an ending line with color matched the host's color."""
    ending_line = "-" * remote_width
    if color:
        return f"{_get_host_color(host_name)}{ending_line}{RESET}"
    return ending_line


async def print_output(
    host_name: str,
    max_name_length: int,
    allow_empty_line: bool,
    allow_cursor_control: bool,
    separate_output: bool,
    print_lock: asyncio.Lock,
    output_queue: asyncio.Queue,
    color: bool,
):
    """Print the output from the remote host with the appropriate prompt."""
    prompt = get_prompt(host_name, max_name_length, color)

    if separate_output:
        chunks = []
        while True:
            output = await output_queue.get()
            if output is None:
                break
            chunks.append(output)

        async with print_lock:
            for chunk in chunks:
                for line in chunk.splitlines():
                    adjusted_line = adjust_cursor_with_prompt(
                        line, prompt, allow_cursor_control, max_name_length
                    )
                    if allow_empty_line or allow_cursor_control or line.strip():
                        print(f"{prompt}{adjusted_line}{RESET}")
    else:
        while True:
            output = await output_queue.get()
            if output is None:
                break
            lines_to_print = []
            for line in output.splitlines():
                adjusted_line = adjust_cursor_with_prompt(
                    line, prompt, allow_cursor_control, max_name_length
                )
                if allow_empty_line or allow_cursor_control or line.strip():
                    lines_to_print.append(f"{prompt}{adjusted_line}{RESET}")
            if lines_to_print:
                async with print_lock:
                    for formatted_line in lines_to_print:
                        print(formatted_line)
