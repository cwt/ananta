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

# Pattern to match common cursor control and screen clear ANSI codes
ansi_cursor_control = re.compile(
    r"\x1b\[(\d+)?[ABEFCDGHf]|"  # cursor movement + home(H) + HVP(f)
    r"\x1b\[\d+;\d+[HF]|"  # cursor position
    r"\x1b\[[?]\d+[hl]|"  # cursor visibility
    r"\x1b\[[sSu]|"  # cursor save/restore
    r"\x1b\[\d*J"  # screen clear
    r"|\x1b\[\d*K"  # erase line (K not in movement class)
)

# Pattern to match cursor movement to a specific column (\x1b[nG)
ansi_cursor_move_to_column = re.compile(r"\x1b\[(\d+)?G")


def adjust_cursor_with_prompt(
    line: str, prompt: str, allow_cursor_control: bool, max_name_length: int
) -> str:
    """Adjust the cursor control codes to display correctly with Ananta prompt."""
    if "\x1b" not in line:
        return line.rstrip()

    if not allow_cursor_control:
        line = ansi_cursor_control.sub("", line)
    else:
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
