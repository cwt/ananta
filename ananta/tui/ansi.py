import functools
import re
from dataclasses import dataclass, field

import urwid

_DEFAULT_FG_COLOR = "default"  # Urwid's default color string for foreground
_DEFAULT_BG_COLOR = "default"  # Urwid's default color string for background

# Styles that Urwid's AttrSpec parses from the foreground string
_URWID_SUPPORTED_STYLES = {
    "bold",
    "underline",
    "standout",
    "italics",
    "blink",
    "strikethrough",
}


@functools.lru_cache(maxsize=4096)
def _build_attr_spec(
    fg: str, bg: str, styles: tuple[str, ...]
) -> urwid.AttrSpec:
    """Create and cache an Urwid AttrSpec from color and style specifications."""
    current_fg_color = fg
    current_bg_color = bg

    active_style_parts = [s for s in styles if s in _URWID_SUPPORTED_STYLES]

    # Handle 'reverse' by swapping fg and bg colors
    if "reverse" in styles:
        current_fg_color, current_bg_color = (
            current_bg_color,
            current_fg_color,
        )

    # Handle 'conceal' by making fg the same as bg
    if "conceal" in styles:
        current_fg_color = current_bg_color

    # Construct the foreground specification string
    fg_spec_parts = []
    if active_style_parts:
        fg_spec_parts.extend(sorted(active_style_parts))

    if current_fg_color != _DEFAULT_FG_COLOR or not fg_spec_parts:
        fg_spec_parts.append(current_fg_color)

    final_fg_spec = ",".join(fg_spec_parts)
    if not final_fg_spec:
        final_fg_spec = _DEFAULT_FG_COLOR

    final_bg_spec = current_bg_color

    try:
        return urwid.AttrSpec(final_fg_spec, final_bg_spec)
    except Exception:
        return urwid.AttrSpec(_DEFAULT_FG_COLOR, _DEFAULT_BG_COLOR)


@dataclass
class _AnsiState:
    """Manages the current state of ANSI SGR attributes."""

    fg: str = _DEFAULT_FG_COLOR
    bg: str = _DEFAULT_BG_COLOR
    styles: set[str] = field(default_factory=set)

    def reset(self):
        """Reset all attributes to default."""
        self.fg = _DEFAULT_FG_COLOR
        self.bg = _DEFAULT_BG_COLOR
        self.styles.clear()

    def get_attr_spec(self) -> urwid.AttrSpec:
        """Create an Urwid AttrSpec from the current state."""
        # Sort styles so identical states always produce the same cache key,
        # regardless of insertion order into the set.
        styles_tuple = tuple(sorted(self.styles))
        return _build_attr_spec(self.fg, self.bg, styles_tuple)


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
_SINGLE_ESC_SEQUENCES = re.compile(r"\x1b\x1b*[^[\x1b]|\x1b+$")


def _strip_ansi_control_sequences(text: str) -> str:
    """
    Strips non-SGR ANSI escape sequences and other problematic control characters.
    Tabs are NOT handled here; they are expanded later on plain text segments.
    Importantly, \x1b (ESC) is NOT stripped by this function if it's part of an SGR.
    """
    if "\x1b" in text:
        text = _OSC_CONTROL_SEQUENCES.sub("", text)
    text = _ANSI_CONTROL_SEQUENCES.sub("", text)
    if "\x1b" in text:
        text = _NON_SGR_CSI_SEQUENCES.sub("", text)
    if "\x1b" in text:
        # Strip lone ESC sequences such as ESC c (reset), ESC M,
        # ESC 7/8 and ESC =/> while preserving CSI (ESC [) for SGR.
        text = _SINGLE_ESC_SEQUENCES.sub("", text)

    if "\r" in text:
        line_ending = ""
        if text.endswith("\r\n"):
            line_ending = "\r\n"
            content = text[:-2]
        elif text.endswith("\n"):
            line_ending = "\n"
            content = text[:-1]
        elif text.endswith("\r"):
            line_ending = "\r"
            content = text[:-1]
        else:
            content = text

        if "\r" in content:
            parts = content.split("\r")
            chosen = ""
            for part in reversed(parts):
                if part:
                    chosen = part
                    break
            content = chosen

        text = content + line_ending

    return text


def _expand_tabs_with_col_tracking(
    text: str, starting_col: int, tab_width: int = 8  # default tab width
) -> tuple[str, int]:
    """Expands tabs in a string to spaces, tracking column position."""
    if "\t" not in text:
        return text, starting_col + len(text)

    expanded_text = []
    current_col = starting_col
    for char in text:
        if char == "\t":
            spaces_to_add = tab_width - (current_col % tab_width)
            expanded_text.append(" " * spaces_to_add)
            current_col += spaces_to_add
        else:
            expanded_text.append(char)
            current_col += 1
    return "".join(expanded_text), current_col


def _handle_extended_color(
    params: list[str], idx: int, state: _AnsiState, is_fg: bool
) -> int:
    """Handle extended color codes (38;5;n or 38;2;r;g;b for fg, 48 for bg)."""
    if idx >= len(params):
        return idx
    color_mode = params[idx]
    idx += 1
    if color_mode == "5":
        if idx < len(params):
            color_id = params[idx]
            try:
                n = int(color_id)
                if 0 <= n <= 255:
                    color_val = f"h{n}"
                    if is_fg:
                        state.fg = color_val
                    else:
                        state.bg = color_val
            except ValueError:
                pass
            idx += 1
    elif color_mode == "2":
        if idx + 2 < len(params):
            try:
                r = int(params[idx])
                g = int(params[idx + 1])
                b = int(params[idx + 2])
                if 0 <= r <= 255 and 0 <= g <= 255 and 0 <= b <= 255:
                    color_val = f"#{r:02x}{g:02x}{b:02x}"
                    if is_fg:
                        state.fg = color_val
                    else:
                        state.bg = color_val
            except ValueError:
                pass
            idx += 3
        else:
            # Malformed sequence, consume rest of params to avoid misinterpretation.
            return len(params)
    return idx


_ANSI_SGR_PATTERN = re.compile(r"\x1b\[([\d;]*)m")
_ANSI_FG_COLOR_MAP = {
    "30": "black",
    "31": "dark red",
    "32": "dark green",
    "33": "brown",
    "34": "dark blue",
    "35": "dark magenta",
    "36": "dark cyan",
    "37": "light gray",
    "90": "dark gray",
    "91": "light red",
    "92": "light green",
    "93": "yellow",
    "94": "light blue",
    "95": "light magenta",
    "96": "light cyan",
    "97": "white",
}
# Background colors (40-47, 100-107) correspond to foreground colors (30-37, 90-97) offset by 10.
_ANSI_BG_COLOR_MAP = {
    str(int(code) + 10): color for code, color in _ANSI_FG_COLOR_MAP.items()
}


def ansi_to_urwid_markup(
    line: str, state: _AnsiState | None = None
) -> tuple[list[tuple[urwid.AttrSpec, str] | str], _AnsiState]:
    """
    Convert a string containing ANSI SGR codes to Urwid markup list.
    Non-SGR control codes are stripped, and tabs are expanded.
    Optionally accepts a persistent _AnsiState to carry SGR attributes
    across lines (real terminals persist state across newlines).
    """
    cleaned_line = _strip_ansi_control_sequences(line)

    markup: list[tuple[urwid.AttrSpec, str] | str] = []
    last_pos = 0
    current_col = 0
    if state is None:
        state = _AnsiState()

    for match in _ANSI_SGR_PATTERN.finditer(cleaned_line):
        start, end = match.span()

        if start > last_pos:
            text_segment = cleaned_line[last_pos:start]
            expanded_segment, new_col = _expand_tabs_with_col_tracking(
                text_segment, current_col
            )
            current_col = new_col
            if expanded_segment:
                markup.append((state.get_attr_spec(), expanded_segment))

        last_pos = end

        codes_str = match.group(1)
        if not codes_str:
            state.reset()
        else:
            params = codes_str.split(";")
            idx = 0
            while idx < len(params):
                code = params[idx]
                if not code:
                    idx += 1
                    continue
                # turn off black formatting to make code more readable
                # fmt: off
                match code:
                    # reset all attributes
                    case "0":
                        state.reset()
                    # add, update, or remove styles based on ANSI codes 
                    case "1": state.styles.add("bold")
                    case "2": pass  # faint not supported by urwid
                    case "3": state.styles.add("italics")
                    case "4": state.styles.add("underline")
                    case "5" | "6": state.styles.add("blink")
                    case "7": state.styles.update({"reverse", "standout"})
                    case "8": state.styles.add("conceal")
                    case "9": state.styles.add("strikethrough")
                    case "21": state.styles.add("underline")
                    case "22": state.styles.discard("bold")
                    case "23": state.styles.discard("italics")
                    case "24": state.styles.discard("underline")
                    case "25": state.styles.discard("blink")
                    case "27": state.styles.difference_update({"reverse", "standout"})
                    case "28": state.styles.discard("conceal")
                    case "29": state.styles.discard("strikethrough")
                    # foreground and background color codes
                    case code if code in _ANSI_FG_COLOR_MAP:
                        state.fg = _ANSI_FG_COLOR_MAP[code]
                    case "39":
                        state.fg = _DEFAULT_FG_COLOR
                    case code if code in _ANSI_BG_COLOR_MAP:
                        state.bg = _ANSI_BG_COLOR_MAP[code]
                    case "49":
                        state.bg = _DEFAULT_BG_COLOR
                    # extended color codes
                    case "38":
                        idx = _handle_extended_color(
                            params, idx + 1, state, True
                        )
                        continue
                    case "48":
                        idx = _handle_extended_color(
                            params, idx + 1, state, False
                        )
                        continue
                    # do nothing for unsupported or unrecognized codes
                    case _:
                        pass
                # fmt: on
                # turn on black formatting
                idx += 1

    if last_pos < len(cleaned_line):
        text_segment = cleaned_line[last_pos:]
        expanded_segment, _ = _expand_tabs_with_col_tracking(
            text_segment, current_col
        )
        if expanded_segment:
            markup.append((state.get_attr_spec(), expanded_segment))

    return markup, state
