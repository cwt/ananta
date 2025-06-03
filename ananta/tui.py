#!/usr/bin/env python
"""
Urwid-based Text User Interface for Ananta.
Manages asynchronous SSH connections and command execution on multiple remote hosts.
"""
from __future__ import annotations

import asyncio
import re
from itertools import cycle
from random import shuffle
from typing import Any, Dict, List, Set, Tuple

import asyncssh
import urwid

from ananta.config import get_hosts
from ananta.ssh import establish_ssh_connection, stream_command_output


# --- Color and Palette Configuration ---
URWID_FG_COLORS = [
    "dark red", "dark green", "brown", "dark blue",
    "dark magenta", "dark cyan", "light gray", "yellow",
    "light red", "light green", "light blue", "light magenta", "light cyan"
]
shuffle(URWID_FG_COLORS)
COLORS_CYCLE = cycle(URWID_FG_COLORS)

HOST_PALETTE_CONFIG: Dict[str, Tuple[str, str, str]] = {}
URWID_PALETTE: List[Tuple[str, str, str, str | None, str | None, str | None]] = []

# ANSI SGR codes to Urwid attributes mapping
ANSI_SGR_PALETTE_MAP = {
    "0": ("", "", "", None),  # Reset
    "1": ("", "", "", "bold"),  # Bold
    "4": ("", "", "", "underline"),  # Underline
    "30": ("ansifg_black", "black", "default", None),
    "31": ("ansifg_red", "dark red", "default", None),
    "32": ("ansifg_green", "dark green", "default", None),
    "33": ("ansifg_yellow", "brown", "default", None),
    "34": ("ansifg_blue", "dark blue", "default", None),
    "35": ("ansifg_magenta", "dark magenta", "default", None),
    "36": ("ansifg_cyan", "dark cyan", "default", None),
    "37": ("ansifg_white", "light gray", "default", None),
    "90": ("ansifg_bright_black", "dark gray", "default", None),
    "91": ("ansifg_bright_red", "light red", "default", None),
    "92": ("ansifg_bright_green", "light green", "default", None),
    "93": ("ansifg_bright_yellow", "yellow", "default", None),
    "94": ("ansifg_bright_blue", "light blue", "default", None),
    "95": ("ansifg_bright_magenta", "light magenta", "default", None),
    "96": ("ansifg_bright_cyan", "light cyan", "default", None),
    "97": ("ansifg_bright_white", "white", "default", None),
    "40": ("ansibg_black", "default", "black", None),
    "41": ("ansibg_red", "default", "dark red", None),
    "42": ("ansibg_green", "default", "dark green", None),
    "43": ("ansibg_yellow", "default", "brown", None),
    "44": ("ansibg_blue", "default", "dark blue", None),
    "45": ("ansibg_magenta", "default", "dark magenta", None),
    "46": ("ansibg_cyan", "default", "dark cyan", None),
    "47": ("ansibg_white", "default", "light gray", None),
    "100": ("ansibg_bright_black", "default", "dark gray", None),
    "101": ("ansibg_bright_red", "default", "light red", None),
    "102": ("ansibg_bright_green", "default", "light green", None),
    "103": ("ansibg_bright_yellow", "default", "yellow", None),
    "104": ("ansibg_bright_blue", "default", "light blue", None),
    "105": ("ansibg_bright_magenta", "default", "light magenta", None),
    "106": ("ansibg_bright_cyan", "default", "light cyan", None),
    "107": ("ansibg_bright_white", "default", "white", None),
}

ANSI_SGR_PATTERN = re.compile(r"\x1b\[([\d;]*)m")


def generate_ansi_palette_entries() -> List[Tuple[str, str, str, str | None, str | None, str | None]]:
    """Generate Urwid palette entries for ANSI SGR codes."""
    return [
        (attr_name, fg, bg, style or "", None, None)
        for code, (attr_name, fg, bg, style) in ANSI_SGR_PALETTE_MAP.items()
        if attr_name
    ]

URWID_PALETTE.extend(generate_ansi_palette_entries())


def ansi_to_urwid_markup(line: str) -> List[Tuple[str, str] | str]:
    """
    Convert ANSI SGR codes in a string to Urwid markup.

    Args:
        line: Input string containing ANSI escape codes.

    Returns:
        List of tuples (attribute, text) or plain strings for Urwid.
    """
    markup: List[Tuple[str, str] | str] = []
    last_pos = 0
    active_styles: Set[str] = set()

    for match in ANSI_SGR_PATTERN.finditer(line):
        start, end = match.span()
        codes_str = match.group(1)

        # Append text before the ANSI code
        if start > last_pos:
            markup.append(_apply_styles(line[last_pos:start], active_styles))

        last_pos = end

        # Process reset or new styles
        if not codes_str or codes_str == "0":
            active_styles.clear()
        else:
            codes = codes_str.split(";")
            for code in codes:
                if code == "0":
                    active_styles.clear()
                    continue
                if code in ANSI_SGR_PALETTE_MAP:
                    active_styles.add(code)

    # Append remaining text
    if last_pos < len(line):
        markup.append(_apply_styles(line[last_pos:], active_styles))

    return [part for part in markup if part and (isinstance(part, tuple) or part.strip())]


def _apply_styles(text: str, styles: Set[str]) -> Tuple[str, str] | str:
    """Apply active ANSI styles to text for Urwid markup."""
    if not text:
        return ""

    if not styles:
        return text

    fg_code = next((s for s in styles if "30" <= s <= "37" or "90" <= s <= "97"), None)
    bg_code = next((s for s in styles if "40" <= s <= "47" or "100" <= s <= "107"), None)
    is_bold = "1" in styles
    is_underline = "4" in styles

    attr_name = ""
    if fg_code and fg_code in ANSI_SGR_PALETTE_MAP:
        attr_name = ANSI_SGR_PALETTE_MAP[fg_code][0]
    elif bg_code and bg_code in ANSI_SGR_PALETTE_MAP:
        attr_name = ANSI_SGR_PALETTE_MAP[bg_code][0]
    elif is_bold:
        attr_name = "ansi_bold"
    elif is_underline:
        attr_name = "ansi_underline"

    return (attr_name, text) if attr_name else text


def _get_host_attr_name(host_name: str) -> str:
    """Generate a sanitized attribute name for a host."""
    return f"host_{host_name.lower().replace('-', '_').replace(' ', '_').replace('.', '_')}"


def _ensure_host_palette(host_name: str) -> str:
    """
    Ensure a palette entry exists for a host.

    Args:
        host_name: Name of the host.

    Returns:
        Attribute name for the host's palette entry.
    """
    attr_name = _get_host_attr_name(host_name)
    if host_name not in HOST_PALETTE_CONFIG:
        fg_color = next(COLORS_CYCLE)
        entry = (attr_name, fg_color, "default")
        HOST_PALETTE_CONFIG[host_name] = entry
        if entry not in URWID_PALETTE:
            URWID_PALETTE.append(entry)
    return attr_name


def format_host_prompt(host_name: str, max_name_length: int) -> List[Tuple[str, str] | str]:
    """
    Format a host prompt for Urwid display.

    Args:
        host_name: Name of the host.
        max_name_length: Maximum length for host name alignment.

    Returns:
        Urwid markup list for the prompt.
    """
    attr_name = _ensure_host_palette(host_name)
    padded_host = host_name.rjust(max_name_length)
    return [(attr_name, f"[{padded_host}] ")]


class AnantaUrwidTUI:
    """Urwid-based TUI for executing commands on multiple remote hosts via SSH."""
    DEFAULT_PALETTE = [
        ("status_ok", "light green", "default"),
        ("status_error", "light red", "default"),
        ("status_neutral", "yellow", "default"),
        ("command_echo", "light cyan", "default", "bold"),
        ("body", "white", "default"),
        ("input_prompt", "light blue", "default"),
        ("ansi_bold", "", "", "bold"),
        ("ansi_underline", "", "", "underline"),
    ]

    def __init__(
        self,
        host_file: str,
        initial_command: str | None,
        host_tags: str | None,
        default_key: str | None
    ):
        """Initialize the TUI with host configuration and UI components."""
        self.host_file = host_file
        self.initial_command = initial_command
        self.host_tags = host_tags
        self.default_key = default_key
        self.hosts, self.max_name_length = get_hosts(host_file, host_tags)
        self.connections: Dict[str, asyncssh.SSHClientConnection | None] = {
            host[0]: None for host in self.hosts
        }

        # Initialize UI components
        self.output_walker = urwid.SimpleFocusListWalker([])
        self.output_box = urwid.ListBox(self.output_walker)
        self.input_field = urwid.Edit(edit_text="")
        self.input_wrapper = urwid.Columns([
            ("fixed", 2, urwid.AttrMap(urwid.Text([("input_prompt", "> ")]), "input_prompt")),
            self.input_field
        ], dividechars=0)
        self.main_layout = urwid.Frame(
            body=urwid.AttrMap(self.output_box, "body"),
            footer=urwid.AttrMap(self.input_wrapper, "body")
        )

        self.loop: urwid.MainLoop | None = None
        self.async_tasks: Set[asyncio.Task[Any]] = set()
        self.is_exiting = False
        self.asyncio_loop: asyncio.AbstractEventLoop | None = None
        self.draw_screen_handle: Any = None

    def add_output(self, message: List[Any] | str, scroll: bool = True) -> None:
        """
        Add a line to the output display.

        Args:
            message: Urwid markup or string to display.
            scroll: Whether to scroll to the new line.
        """
        if self.is_exiting and not any(
            s in str(message).lower() for s in ["exiting", "closed", "cleanup", "shutdown", "processed"]
        ):
            return

        widget = urwid.Text(message if isinstance(message, list) else ansi_to_urwid_markup(message))
        self.output_walker.append(widget)

        if len(self.output_walker) > 3000:
            del self.output_walker[0:len(self.output_walker) - 2000]

        if scroll:
            self.output_walker.set_focus(len(self.output_walker) - 1)

        if self.loop and self.loop.event_loop and not self.draw_screen_handle:
            self.draw_screen_handle = self.loop.event_loop.alarm(0, self._request_draw)

    def _request_draw(self, *_args: Any) -> None:
        """Request a screen redraw."""
        if self.loop:
            self.loop.draw_screen()
        self.draw_screen_handle = None

    async def connect_host(self, host_name: str, ip: str, port: int, user: str, key: str) -> None:
        """Connect to a single host and update the UI with the status."""
        if self.is_exiting:
            return

        prompt = format_host_prompt(host_name, self.max_name_length)
        self.add_output(prompt + [("status_neutral", "Connecting...")])

        try:
            conn = await establish_ssh_connection(ip, port, user, key, self.default_key, timeout=10.0)
            conn.set_keepalive(interval=30, count_max=3)
            self.connections[host_name] = conn
            self.add_output(prompt + [("status_ok", "Connected.")])
        except Exception as e:
            self.connections[host_name] = None
            self.add_output(prompt + [("status_error", f"Connection failed: {e}")])

    async def connect_all_hosts(self) -> None:
        """Connect to all configured hosts concurrently."""
        if self.is_exiting or not self.hosts:
            self.add_output(ansi_to_urwid_markup(
                f"[status_neutral]No hosts found in '{self.host_file}'. "
                "Please check the file path and format.[/status_neutral]"
            ))
            return

        tasks = [
            asyncio.create_task(self.connect_host(*host))
            for host in self.hosts
        ]
        for task in tasks:
            self.async_tasks.add(task)
            task.add_done_callback(self.async_tasks.discard)

        await asyncio.gather(*tasks, return_exceptions=True)

        if self.initial_command and not self.is_exiting:
            self.input_field.set_edit_text(self.initial_command)
            self.process_command(self.initial_command)

    def process_command(self, command: str) -> None:
        """Process a user-entered command."""
        if self.is_exiting or not command.strip():
            return

        command = command.strip()
        if command.lower() == "exit":
            self.initiate_exit()
            return

        self.add_output([("command_echo", f">>> {command}")])
        self.input_field.set_edit_text("")

        for host_name, conn in self.connections.items():
            if self.is_exiting:
                break
            if conn and not conn.is_closed():
                task = asyncio.create_task(self.run_command(host_name, conn, command))
                self.async_tasks.add(task)
                task.add_done_callback(self.async_tasks.discard)
            else:
                prompt = format_host_prompt(host_name, self.max_name_length)
                self.add_output(prompt + [("status_error", "Not connected, skipping command.")])

    async def run_command(self, host_name: str, conn: asyncssh.SSHClientConnection, command: str) -> None:
        """Execute a command on a remote host and stream output."""
        if self.is_exiting:
            return

        prompt = format_host_prompt(host_name, self.max_name_length)
        cols = self.loop.screen.get_cols_rows()[0] if self.loop and self.loop.screen else 80
        remote_width = max(cols - self.max_name_length - 3, 10)

        output_queue: asyncio.Queue[str | None] = asyncio.Queue()
        stream_task = asyncio.create_task(
            stream_command_output(conn, command, remote_width, output_queue, color=True)
        )
        self.async_tasks.add(stream_task)
        stream_task.add_done_callback(self.async_tasks.discard)

        while not self.is_exiting:
            try:
                line = await asyncio.wait_for(output_queue.get(), timeout=0.1)
            except asyncio.TimeoutError:
                if stream_task.done():
                    break
                continue

            if line is None:
                break

            full_line = prompt + ansi_to_urwid_markup(line.rstrip("\n\r"))
            self.add_output(full_line)

        if not stream_task.done():
            stream_task.cancel()
        try:
            await stream_task
        except asyncio.CancelledError:
            if not self.is_exiting:
                self.add_output(prompt + [("status_neutral", "Command cancelled.")])
        except Exception as e:
            if not self.is_exiting:
                self.add_output(prompt + [("status_error", f"Error during command: {e}")])

    def handle_input(self, key: str) -> bool:
        """
        Handle unprocessed keyboard input.

        Args:
            key: Key pressed by the user.

        Returns:
            True if input was handled, False otherwise.
        """
        if self.is_exiting:
            return True

        if key == "enter":
            self.process_command(self.input_field.edit_text)
            return True
        if key in ("ctrl d", "ctrl c"):
            self.initiate_exit()
            return True
        return False

    def initiate_exit(self) -> None:
        """Begin the graceful shutdown process."""
        if self.is_exiting:
            return

        self.is_exiting = True
        if self.asyncio_loop and not self.asyncio_loop.is_closed():
            asyncio.create_task(self.shutdown())
        else:
            self.exit_loop()

    def exit_loop(self) -> None:
        """Exit the Urwid main loop."""
        raise urwid.ExitMainLoop()

    async def shutdown(self) -> None:
        """Perform shutdown tasks and close connections."""
        self.add_output(ansi_to_urwid_markup("[status_neutral]Exiting... Closing connections...[/status_neutral]"))

        tasks = [
            asyncio.create_task(self._close_connection(conn, host_name))
            for host_name, conn in self.connections.items()
            if conn and not conn.is_closed()
        ]
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

        self.add_output(ansi_to_urwid_markup("[status_neutral]Connections closed.[/status_neutral]"))
        await self._cleanup_tasks()

        if self.loop and self.loop.event_loop:
            self.loop.event_loop.alarm(0, self.exit_loop)

    async def _close_connection(self, conn: asyncssh.SSHClientConnection, host_name: str) -> None:
        """Close a single SSH connection with timeout."""
        conn.close()
        try:
            await asyncio.wait_for(conn.wait_closed(), timeout=2.0)
        except (asyncio.TimeoutError, Exception):
            pass

    async def _cleanup_tasks(self) -> None:
        """Cancel and await all running async tasks."""
        if self.async_tasks:
            for task in list(self.async_tasks):
                if not task.done():
                    task.cancel()
            await asyncio.gather(*self.async_tasks, return_exceptions=True)
            self.async_tasks.clear()

    def get_palette(self) -> List[Tuple[str, str, str, str | None, str | None, str | None]]:
        """Combine all palette entries, ensuring uniqueness."""
        for host in self.hosts:
            _ensure_host_palette(host[0])

        combined = self.DEFAULT_PALETTE + URWID_PALETTE
        seen = set()
        unique = []

        for entry in reversed(combined):
            if isinstance(entry, tuple) and entry[0] not in seen:
                unique.insert(0, entry)
                seen.add(entry[0])

        return unique

    def start_initial_tasks(self, *_args: Any) -> None:
        """Start initial connection tasks."""
        if self.asyncio_loop and not self.asyncio_loop.is_closed():
            asyncio.create_task(self.connect_all_hosts())
        else:
            print("Warning: Cannot start initial tasks, asyncio loop unavailable.")

    def run(self) -> None:
        """Run the TUI application."""
        self.asyncio_loop = asyncio.get_event_loop_policy().get_event_loop()
        asyncio.set_event_loop(self.asyncio_loop)

        event_loop = urwid.AsyncioEventLoop(loop=self.asyncio_loop)
        self.loop = urwid.MainLoop(
            widget=self.main_layout,
            palette=self.get_palette(),
            event_loop=event_loop,
            unhandled_input=self.handle_input
        )

        if self.loop.widget:
            self.loop.widget.focus_position = "footer"

        try:
            self.loop.screen.set_terminal_properties(colors=256)
        except Exception:
            pass

        self.loop.event_loop.alarm(0, self.start_initial_tasks)

        try:
            self.loop.run()
        except urwid.ExitMainLoop:
            pass
        except KeyboardInterrupt:
            print("\nAnanta TUI interrupted.")
            if not self.is_exiting:
                self.initiate_exit()
        except Exception as e:
            print(f"\nAnanta TUI crashed: {e}")
            import traceback
            traceback.print_exc()
        finally:
            if not self.is_exiting:
                self.is_exiting = True
            if self.asyncio_loop and not self.asyncio_loop.is_closed():
                self.asyncio_loop.run_until_complete(self.shutdown())
            print("\nAnanta TUI has finished.")
