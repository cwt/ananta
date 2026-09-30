"""
Urwid-based Text User Interface for Ananta.
Manages asynchronous SSH connections and command execution on multiple remote hosts.
"""

from __future__ import annotations

import asyncio
import tempfile
from typing import Any

import asyncssh
import urwid

from ..config import get_hosts
from ..host_keys import (
    HostKeyChangedError,
    HostKeyPolicy,
    _host_entry_name,
)
from ..output import calculate_remote_width, make_color_cycle
from ..ssh import (
    _close_ssh_connection,
    establish_ssh_connection,
    stream_command_output,
)
from .ansi import _AnsiState, ansi_to_urwid_markup


class ListBoxWithScrollBar(urwid.WidgetWrap):
    """A ListBox with a visual scrollbar."""

    def __init__(
        self,
        walker: urwid.SimpleFocusListWalker,
        tui: "AnantaUrwidTUI | None" = None,
    ):
        self._walker = walker
        self._tui = tui
        self._list_box = urwid.ListBox(self._walker)
        self._scrollbar = urwid.Text("", align="left")
        self._last_scrollbar_state: tuple[int, int, int] | None = None
        self._wrapped_widget = urwid.Columns(
            [
                (self._list_box),
                ("given", 1, urwid.AttrMap(self._scrollbar, "body")),
            ],
            box_columns=[0],
        )
        super().__init__(self._wrapped_widget)

    def render(
        self, size: tuple[int, int], focus: bool = False
    ) -> urwid.Canvas:
        """Render the widget and update the scrollbar."""
        self._update_scrollbar(size)
        return super().render(size, focus)

    def _update_scrollbar(self, size: tuple[int, int]) -> None:
        """Update the scrollbar's appearance based on the list box's state."""
        max_height = size[1]
        if max_height <= 0 or not self._walker:
            if self._last_scrollbar_state != (0, 0, 0):
                self._scrollbar.set_text("")
                self._last_scrollbar_state = (0, 0, 0)
            return

        content_length = len(self._walker)
        if content_length <= max_height:
            if self._last_scrollbar_state != (0, 0, max_height):
                self._scrollbar.set_text("")  # No scrollbar needed
                self._last_scrollbar_state = (0, 0, max_height)
            return

        focus_pos = self._walker.focus
        if focus_pos is None or not (0 <= focus_pos < content_length):
            focus_pos = content_length - 1

        if content_length > 1:
            scroll_ratio = focus_pos / (content_length - 1)
        else:
            scroll_ratio = 0

        handle_size = max(1, round(max_height * (max_height / content_length)))
        handle_size = min(max_height, handle_size)

        scrollable_space = max_height - handle_size
        handle_top = round(scroll_ratio * scrollable_space)

        current_state = (handle_top, handle_size, max_height)
        if self._last_scrollbar_state == current_state:
            return
        self._last_scrollbar_state = current_state

        bar_chars = []
        for i in range(max_height):
            if handle_top <= i < handle_top + handle_size:
                bar_chars.append("█")
            else:
                bar_chars.append("░")

        self._scrollbar.set_text("\n".join(bar_chars))

    def keypress(
        self, size: tuple[int, int] | tuple[int, ...], key: str
    ) -> str | None:
        """Pass keypresses to the list box."""
        return self._list_box.keypress(size, key)  # type: ignore

    def mouse_event(
        self,
        size: tuple[int, int],
        event: str,
        button: int,
        col: int,
        row: int,
        focus: bool,
    ) -> bool | None:
        """Handle mouse events, specifically for scrolling."""
        if event == "mouse press":
            if button == 4:  # Scroll up
                self._list_box.keypress(size, "page up")
                if self._tui:
                    self._tui._schedule_draw()
                return True
            if button == 5:  # Scroll down
                self._list_box.keypress(size, "page down")
                if self._tui:
                    self._tui._schedule_draw()
                return True
        return self._list_box.mouse_event(size, event, button, col, row, focus)


# --- Setup colors for hosts ---
# Colors are now handled within the _populate_host_fg_colors method


def _retrieve_task_exception(task: asyncio.Task[Any]) -> None:
    """Retrieve a task exception so it is never reported as unretrieved."""
    try:
        task.exception()
    except asyncio.CancelledError:
        pass


class AnantaMainLoop(urwid.MainLoop):
    def entering_idle(self) -> None:
        """
        Override the base method to prevent automatic screen redraws on idle.
        This helps avoid `BlockingIOError` by giving us manual control over the redraw cycle.
        """


class RefreshingPile(urwid.Pile):
    """A Pile that forces a redraw after any keypress is handled."""

    def __init__(
        self, widget_list: list[Any], tui: "AnantaUrwidTUI", **kwargs: Any
    ):
        self._tui = tui
        super().__init__(widget_list, **kwargs)

    def keypress(
        self, size: tuple[int, int] | tuple[int, ...] | tuple[()], key: str
    ) -> str | None:
        """Handle keypress and then request a redraw."""
        result = super().keypress(size, key)  # type: ignore
        self._tui.update_prompt_attribute()
        # After any keypress, handled or not by a child, request a redraw.
        # This is necessary because the main loop's idle handler is disabled.
        self._tui._schedule_draw()
        return result


_THEME_PALETTE_FOREGROUNDS: dict[str, tuple[str, str]] = {
    # attr_name: (dark_foreground, light_foreground)
    "status_ok": ("light green", "dark green"),
    "status_error": ("light red", "dark red"),
    "status_neutral": ("yellow", "brown"),
    "command_echo": ("light cyan,bold", "dark blue,bold"),
    "body": ("white", "black"),
    "input_prompt": ("light blue", "dark blue"),
    "input_prompt_inactive": ("dark gray", "light gray"),
    "ansi_bold": ("bold", "bold"),
    "ansi_underline": ("underline", "underline"),
    "ansi_standout": ("standout", "standout"),
}

DEFAULT_MAX_OUTPUT_LINES = 5000
DEFAULT_TRIM_OUTPUT_LINES = 500


class AnantaUrwidTUI:
    """Ananta Text User Interface using Urwid."""

    def _get_default_palette(
        self,
    ) -> list[tuple[str, str, str, None, None, None]]:
        """Return the default palette based on theme."""
        fg_index = 1 if self.light_theme else 0
        return [
            (name, fgs[fg_index], "default", None, None, None)
            for name, fgs in _THEME_PALETTE_FOREGROUNDS.items()
        ]

    def __init__(
        self,
        host_file: str,
        initial_command: str | None,
        host_tags: str | None,
        default_key: str | None,
        separate_output: bool,
        allow_empty_line: bool,
        light_theme: bool = False,
    ):
        """Initialize the Ananta TUI."""
        # --- SSH, connection, and output setup ---
        self.host_file = host_file
        self.initial_command = initial_command
        self.host_tags = host_tags
        self.default_key = default_key
        self.separate_output = separate_output
        self.allow_empty_line = allow_empty_line
        self.light_theme = light_theme
        self.hosts, self.max_name_length = get_hosts(host_file, host_tags)
        self.connections: dict[str, asyncssh.SSHClientConnection | None] = {
            host[0]: None for host in self.hosts
        }
        # Mandatory host-key verification shared across all connections.
        self.host_key_policy = HostKeyPolicy()
        self.mismatch_abort = False
        self._ansi_states: dict[str, _AnsiState] = {}
        self._host_locks: dict[str, asyncio.Lock] = {}
        self._host_attr_names: dict[str, str] = {}
        self._taken_attr_names: set[str] = set()
        self._host_prompts: dict[str, list[tuple[str, str]]] = {}
        # --- Urwid setup ---
        # Maps host attr names to their foreground color for the palette.
        self.host_fg_colors: dict[str, str] = {}
        self._populate_host_fg_colors()
        self.current_palette = self._build_palette()
        self.max_output_lines = DEFAULT_MAX_OUTPUT_LINES
        self.trim_output_lines = DEFAULT_TRIM_OUTPUT_LINES
        self.output_walker: urwid.SimpleFocusListWalker = (
            urwid.SimpleFocusListWalker([])
        )
        self.output_box = ListBoxWithScrollBar(self.output_walker, tui=self)
        self.input_field = urwid.Edit(edit_text="")
        self.prompt_widget = urwid.Text(">>> ")
        self.prompt_attr_map = urwid.AttrMap(self.prompt_widget, "input_prompt")
        self.input_wrapper = urwid.Columns(
            [
                ("given", 4, self.prompt_attr_map),
                self.input_field,
            ],
            dividechars=0,
        )
        widgets = [
            ("weight", 1, urwid.AttrMap(self.output_box, "body")),
            ("fixed", 1, urwid.SolidFill("─")),
            ("fixed", 1, urwid.AttrMap(self.input_wrapper, "body")),
        ]
        # focus_item=2 puts the initial focus on the input field.
        self.main_pile = RefreshingPile(widgets, tui=self, focus_item=2)
        self.main_layout: urwid.Frame = urwid.Frame(body=self.main_pile)
        # --- Event loop and async tasks setup ---
        self.loop: urwid.MainLoop | None = None
        self.async_tasks: set[asyncio.Task[Any]] = set()
        self.is_exiting = False
        self.asyncio_loop: asyncio.AbstractEventLoop | None = None
        self.draw_screen_handle: Any = None
        self.shutdown_task: asyncio.Task[None] | None = None

        # --- Show the TUI welcome message ---
        self.add_output(
            [
                (
                    "status_ok",
                    "+------------------------------------------+\n"
                    "|        Welcome to Ananta TUI mode.       |\n"
                    "|Press [Up] to focus on the Output window. |\n"
                    "|Press [PgUp] or [PgDn] to scroll up/down. |\n"
                    "|Press [Down] to focus on the Input window.|\n"
                    "|Press [Ctrl-D] or `exit` command to exit. |\n"
                    "+------------------------------------------+",
                )
            ]
        )

        # --- Show warning for Separate Output mode ---
        if self.separate_output:
            self.add_output(
                [
                    (
                        "status_error",
                        "+------------------------------------------+\n"
                        "|    Separate Output mode [-s] enabled.    |\n"
                        "|    Avoid feeding LARGE amount of data.   |\n"
                        "|       !!!!You have been WARNED!!!!       |\n"
                        "+------------------------------------------+",
                    )
                ]
            )

    def _get_host_attr_name(self, host_name: str) -> str:
        """Return a unique palette attribute name for a host."""
        if host_name not in self._host_attr_names:
            sanitized = (
                host_name.lower()
                .replace("-", "_")
                .replace(" ", "_")
                .replace(".", "_")
            )
            attr_name = f"host_{sanitized}"
            # Distinct hosts can sanitize to the same name (e.g. "web-1"
            # and "web_1"); suffix until unique so colors never merge.
            suffix = 1
            while attr_name in self._taken_attr_names:
                attr_name = f"host_{sanitized}_{suffix}"
                suffix += 1
            self._taken_attr_names.add(attr_name)
            self._host_attr_names[host_name] = attr_name
        return self._host_attr_names[host_name]

    def format_host_prompt(
        self, host_name: str, max_name_length: int
    ) -> list[tuple[str, str]]:
        if host_name not in self._host_prompts:
            attr_name = self._get_host_attr_name(host_name)
            padded_host = host_name.rjust(max_name_length)
            self._host_prompts[host_name] = [(attr_name, f"[{padded_host}] ")]
        return list(self._host_prompts[host_name])

    def _populate_host_fg_colors(self) -> None:
        """Assign each host a foreground color for its palette entry."""
        if self.light_theme:
            fg_colors = [
                "dark red",
                "dark green",
                "dark blue",
                "dark magenta",
                "dark cyan",
                "brown",
                "black",
            ]
        else:
            # dark colors are not used to avoid confusion with similarity of colors
            fg_colors = [
                "yellow",
                "light red",
                "light green",
                "light blue",
                "light magenta",
                "light cyan",
            ]

        color_cycle = make_color_cycle(fg_colors)
        for host_name, *_ in self.hosts:
            attr_name = self._get_host_attr_name(host_name)
            if attr_name not in self.host_fg_colors:
                self.host_fg_colors[attr_name] = next(color_cycle)

    def _build_palette(self) -> list[tuple[str | None, ...]]:
        """Build the complete palette for Urwid, including default and host-specific styles."""
        palette = list(self._get_default_palette())
        palette.extend(
            (attr_name, fg_color, "default", None, None, None)
            for attr_name, fg_color in self.host_fg_colors.items()
        )

        seen_names = set()
        unique_palette: list[tuple[str | None, ...]] = []
        for entry in reversed(palette):
            if isinstance(entry, tuple) and entry[0] is not None:
                if entry[0] not in seen_names:
                    unique_palette.append(entry)
                    seen_names.add(entry[0])
        unique_palette.reverse()
        return unique_palette

    @staticmethod
    def _exit_message_text(message_parts: list[Any] | str) -> str:
        """Return filterable text excluding host prompts to avoid smuggling."""
        if isinstance(message_parts, str):
            return message_parts.lower()
        texts: list[str] = []
        for part in message_parts:
            if isinstance(part, tuple) and len(part) == 2:
                attr_name, text = part
                if isinstance(attr_name, str) and attr_name.startswith("host_"):
                    continue
                texts.append(str(text))
            else:
                texts.append(str(part))
        return " ".join(texts).lower()

    def add_output(self, message_parts: list[Any] | str) -> None:
        """Add output to the display."""
        if self.is_exiting and not any(
            s in self._exit_message_text(message_parts)
            for s in [
                "exiting",
                "closing",
                "closed",
                "cleanup",
                "cleaning up",
                "shutdown",
                "processed",
                "failed",
                "error",
            ]
        ):
            return

        processed_markup: Any
        if isinstance(message_parts, str):
            processed_markup, _ = ansi_to_urwid_markup(message_parts)
        else:
            processed_markup = message_parts

        if (
            not processed_markup
            and isinstance(message_parts, str)
            and message_parts.strip() == ""
        ):
            widget = urwid.Text("")
        elif not processed_markup:
            return
        else:
            widget = urwid.Text(processed_markup)

        try:
            focus = self.output_walker.focus
            was_at_bottom = (
                focus is None or focus >= len(self.output_walker) - 1
            )
        except Exception:
            was_at_bottom = True

        self.output_walker.append(widget)
        if len(self.output_walker) > self.max_output_lines:
            del self.output_walker[
                0 : len(self.output_walker)
                - (self.max_output_lines - self.trim_output_lines)
            ]

        if was_at_bottom:
            self.output_walker.set_focus(len(self.output_walker) - 1)

        self._schedule_draw()

    def _schedule_draw(self) -> None:
        """Schedule a redraw of the screen on the event loop."""
        if self.loop and self.loop.event_loop and not self.draw_screen_handle:
            self.draw_screen_handle = self.loop.event_loop.alarm(
                0, self._request_draw
            )

    def _request_draw(self, *_args: Any) -> None:
        """Request a redraw of the screen."""
        try:
            if self.loop and not (
                self.is_exiting
                and self.asyncio_loop
                and self.asyncio_loop.is_closed()
            ):
                self.loop.draw_screen()
        except (BlockingIOError, OSError):
            pass  # Screen busy or terminal already tearing down; skip.
        finally:
            # Allow later output events to reschedule a clean redraw.
            self.draw_screen_handle = None

    async def connect_host(
        self,
        host_name: str,
        ip: str,
        port: int,
        user: str,
        key: str,
        timeout: float,
        retries: int,
    ) -> None:
        """Establish an SSH connection to a single host."""
        if self.is_exiting:
            return

        prompt = self.format_host_prompt(
            host_name, self.max_name_length
        )  # No longer needs self.current_palette
        self.add_output(prompt + [("status_neutral", "Connecting...")])

        try:
            conn = await establish_ssh_connection(
                ip,
                port,
                user,
                key,
                self.default_key,
                timeout,
                retries,
                policy=self.host_key_policy,
            )
        except HostKeyChangedError as e:
            self.connections[host_name] = None
            self.add_output(
                prompt
                + [
                    (
                        "status_error",
                        f"HOST KEY MISMATCH - not connected. {e}",
                    )
                ]
            )
        except asyncio.CancelledError:
            self.connections[host_name] = None
            raise
        except Exception as e:
            self.connections[host_name] = None
            self.add_output(
                prompt + [("status_error", f"Connection failed: {e}")]
            )
        else:
            conn.set_keepalive(interval=30, count_max=3)
            self.connections[host_name] = conn
            self.add_output(prompt + [("status_ok", "Connected.")])

    async def connect_all_hosts(self) -> None:
        """Connect to all hosts defined in the host file."""
        if self.is_exiting:
            return

        if not self.hosts:
            self.add_output(
                [
                    (
                        "status_error",
                        f"No hosts found in '{self.host_file}'. Check file and tags.",
                    )
                ]
            )
            return

        connect_tasks = [
            asyncio.create_task(self.connect_host(*host_details))
            for host_details in self.hosts
        ]
        for task in connect_tasks:
            self.async_tasks.add(task)
            task.add_done_callback(self.async_tasks.discard)

        await asyncio.gather(*connect_tasks, return_exceptions=True)

        if self.host_key_policy.mismatches and not self.is_exiting:
            self.mismatch_abort = True
            self._report_mismatches()
            return

        if self.initial_command and not self.is_exiting:
            self.input_field.set_edit_text(self.initial_command)
            self.process_command(self.initial_command)

    def _report_mismatches(self) -> None:
        """Show a loud mismatch report and how to recover."""
        self.add_output(
            [
                (
                    "status_error",
                    "!! HOST KEY MISMATCH DETECTED - batch aborted, "
                    "no commands executed.",
                )
            ]
        )
        for record in self.host_key_policy.mismatches:
            self.add_output(
                [
                    (
                        "status_error",
                        f"  {record.entry}: recorded "
                        f"{record.old_fingerprint} / presented "
                        f"{record.new_fingerprint}",
                    )
                ]
            )
        self.add_output(
            [
                (
                    "status_neutral",
                    "Verify out-of-band, then type `override` to accept "
                    "the new keys or `exit` to quit.",
                )
            ]
        )

    async def _override_and_reconnect(self) -> None:
        """Accept mismatched keys and reconnect affected hosts."""
        overridden_entries = {m.entry for m in self.host_key_policy.mismatches}
        self.host_key_policy.apply_overrides()
        self.mismatch_abort = False
        self.add_output(
            [("status_ok", "Mismatched keys accepted. Reconnecting...")]
        )
        retry_hosts = [
            h
            for h in self.hosts
            if _host_entry_name(h[1], h[2]) in overridden_entries
        ]
        reconnect_tasks = [
            asyncio.create_task(self.connect_host(*host_details))
            for host_details in retry_hosts
        ]
        for task in reconnect_tasks:
            self.async_tasks.add(task)
            task.add_done_callback(self.async_tasks.discard)
        await asyncio.gather(*reconnect_tasks, return_exceptions=True)

    def process_command(self, command: str) -> None:
        """Process a command entered in the input field."""
        if self.is_exiting or not command.strip():
            return

        command = command.strip()
        if command.lower() == "exit":
            self.initiate_exit()
            return
        if command.lower() == "override":
            if not self.host_key_policy.mismatches and not self.mismatch_abort:
                self.add_output(
                    [("status_neutral", "No mismatched keys to accept.")]
                )
                self.input_field.set_edit_text("")
                return
            self.add_output([("command_echo", ">>> override")])
            self.input_field.set_edit_text("")
            task = asyncio.create_task(self._override_and_reconnect())
            self.async_tasks.add(task)
            task.add_done_callback(self.async_tasks.discard)
            return
        if self.mismatch_abort:
            self.add_output(
                [
                    (
                        "status_error",
                        "Aborted: resolve host key mismatches first "
                        "(`override` or `exit`).",
                    )
                ]
            )
            self.input_field.set_edit_text("")
            return

        self.add_output([("command_echo", f">>> {command}")])
        self.input_field.set_edit_text("")

        for host_name, conn in self.connections.items():
            if self.is_exiting:
                break
            if conn and not conn.is_closed():
                task = asyncio.create_task(
                    self.run_command_on_host(host_name, conn, command)
                )
                self.async_tasks.add(task)
                task.add_done_callback(self.async_tasks.discard)
            else:
                prompt = self.format_host_prompt(
                    host_name, self.max_name_length
                )
                self.add_output(
                    prompt + [("status_error", "Not connected, skipping.")]
                )

    def _display_stream_line(
        self,
        host_name: str,
        prompt: list[tuple[str, str]],
        line_data: str,
    ) -> None:
        """Convert one streamed output line to Urwid markup and display it.

        The per-host ANSI state persists across lines so SGR attributes
        carry over just like in a real terminal.
        """
        host_state = self._ansi_states.get(host_name, _AnsiState())
        markup, host_state = ansi_to_urwid_markup(
            line_data.rstrip("\r\n"), host_state
        )
        self._ansi_states[host_name] = host_state
        if markup:
            self.add_output(prompt + markup)
        elif self.allow_empty_line and line_data.strip() == "":
            self.add_output(prompt + [""])

    def _get_host_lock(self, host_name: str) -> asyncio.Lock:
        """Return the per-host lock serializing commands for one host."""
        lock = self._host_locks.get(host_name)
        if lock is None:
            lock = asyncio.Lock()
            self._host_locks[host_name] = lock
        return lock

    async def run_command_on_host(
        self,
        host_name: str,
        conn: asyncssh.SSHClientConnection,
        command: str,
    ) -> None:
        """Run a command on a specific host and stream the output."""
        async with self._get_host_lock(host_name):
            await self._run_command_on_host_locked(host_name, conn, command)

    async def _run_command_on_host_locked(
        self,
        host_name: str,
        conn: asyncssh.SSHClientConnection,
        command: str,
    ) -> None:
        """Inner command runner; caller holds the per-host lock."""
        if self.is_exiting:  # If exiting, do not run commands
            return

        prompt = self.format_host_prompt(host_name, self.max_name_length)

        cols = 80
        if self.loop and self.loop.screen:
            cols = self.loop.screen.get_cols_rows()[0]
        remote_width = calculate_remote_width(
            cols, self.max_name_length, extra_margin=1
        )  # Decrease 1 column for the scrollbar.

        output_queue: asyncio.Queue[str | None] = asyncio.Queue()

        stream_task = asyncio.create_task(
            stream_command_output(
                conn, command, remote_width, output_queue, color=True
            )
        )
        self.async_tasks.add(stream_task)

        def done_cb(task):
            self.async_tasks.discard(task)
            try:
                exc = task.exception()
                if exc:
                    output_queue.put_nowait(
                        f"Cmd error: {type(exc).__name__} {exc}"
                    )
            except asyncio.CancelledError:
                pass
            output_queue.put_nowait(None)

        stream_task.add_done_callback(done_cb)

        try:
            if self.separate_output:
                # Buffer lines first with temporary spillover to avoid unbounded RAM usage,
                # then render as one block per host.
                with tempfile.SpooledTemporaryFile(
                    max_size=10 * 1024 * 1024, mode="w+", encoding="utf-8"
                ) as buf:
                    while not self.is_exiting:
                        line_data = await output_queue.get()
                        if line_data is None:
                            break
                        buf.write(
                            line_data
                            if line_data.endswith("\n")
                            else f"{line_data}\n"
                        )
                    buf.seek(0)
                    for raw_line in buf:
                        self._display_stream_line(
                            host_name, prompt, raw_line.rstrip("\r\n")
                        )
            else:
                while not self.is_exiting:
                    line_data = await output_queue.get()
                    if line_data is None:
                        break
                    self._display_stream_line(host_name, prompt, line_data)

        except asyncio.CancelledError:
            raise
        except Exception as e:
            if not self.is_exiting:
                self.add_output(
                    prompt
                    + [("status_error", f"Cmd error: {type(e).__name__} {e}")]
                )
        finally:
            if not stream_task.done():
                stream_task.cancel()
            try:
                await stream_task
            except asyncio.CancelledError:
                if not self.is_exiting:
                    self.add_output(
                        prompt
                        + [("status_neutral", "Command cancelled/interrupted.")]
                    )
                raise
            except Exception:
                pass

    def update_prompt_attribute(self, *args, **kwargs):
        """Update input prompt color"""
        if self.main_pile.focus_position == 2:
            self.prompt_attr_map.set_attr_map({None: "input_prompt"})
        else:
            self.prompt_attr_map.set_attr_map({None: "input_prompt_inactive"})
        self._schedule_draw()

    def handle_input(self, key: str | tuple[str, int, int, int]) -> bool | None:
        """Handle user input from the keyboard."""
        # Note: prompt color refreshes are handled by RefreshingPile.keypress,
        # which every keypress passes through.
        if self.is_exiting:
            return True

        if key == "enter":
            self.process_command(self.input_field.edit_text)
            return True
        if key in ("ctrl d", "ctrl c"):
            self.initiate_exit()
            return True

        return None

    def initiate_exit(self) -> None:
        """Initiate the exit process for the TUI."""
        if self.is_exiting:
            return
        self.is_exiting = True

        if self.asyncio_loop and not self.asyncio_loop.is_closed():
            self.shutdown_task = self.asyncio_loop.create_task(
                self.perform_shutdown()
            )
            self.shutdown_task.add_done_callback(_retrieve_task_exception)
        else:
            self._direct_exit_loop()

    def _direct_exit_loop(self) -> None:
        """Directly exit the Urwid main loop without waiting for async tasks."""
        if self.loop:
            raise urwid.ExitMainLoop()

    async def perform_shutdown(self) -> None:
        """Perform the shutdown process for the TUI."""
        self.add_output(
            [("status_neutral", "Exiting... Closing connections...")]
        )

        close_conn_tasks = []
        for host_name, conn in self.connections.items():
            if conn and not conn.is_closed():
                self.add_output(
                    self.format_host_prompt(host_name, self.max_name_length)
                    + [("status_neutral", "Closing...")]
                )
                close_conn_tasks.append(
                    asyncio.create_task(_close_ssh_connection(conn))
                )

        if close_conn_tasks:
            await asyncio.gather(*close_conn_tasks, return_exceptions=True)
        self.add_output(
            [("status_neutral", "All connections closed or timed out.")]
        )

        tasks_to_cleanup = [t for t in self.async_tasks if not t.done()]
        if tasks_to_cleanup:
            self.add_output(
                [
                    (
                        "status_neutral",
                        f"Cleaning up {len(tasks_to_cleanup)} tasks...",
                    )
                ]
            )
            for task in tasks_to_cleanup:
                task.cancel()
            await asyncio.gather(*tasks_to_cleanup, return_exceptions=True)
        self.async_tasks.clear()

        self.add_output(
            [("status_neutral", "Cleanup complete. Ananta TUI will now exit.")]
        )

        if self.loop and self.loop.event_loop:
            self.loop.event_loop.alarm(0, self._direct_exit_loop)

    def _initial_setup_tasks(self, *_args: Any) -> None:
        """Perform initial setup tasks after the main loop starts."""
        if self.asyncio_loop and not self.asyncio_loop.is_closed():
            task = self.asyncio_loop.create_task(self.connect_all_hosts())
            self.async_tasks.add(task)
            task.add_done_callback(self.async_tasks.discard)
        else:
            self.add_output(
                [
                    (
                        "status_error",
                        "Asyncio loop not available for initial tasks.",
                    )
                ]
            )

    def run(self) -> None:
        """Run the Ananta TUI main loop."""
        # Create a new event loop for the TUI
        self.asyncio_loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.asyncio_loop)

        urwid_event_loop = urwid.AsyncioEventLoop(loop=self.asyncio_loop)

        self.loop = AnantaMainLoop(
            widget=self.main_layout,
            palette=self.current_palette,  # type: ignore
            event_loop=urwid_event_loop,
            unhandled_input=self.handle_input,
        )

        self.input_wrapper.focus_position = 1

        try:
            self.loop.screen.set_terminal_properties(colors=256)  # type: ignore
            self.loop.screen.set_mouse_tracking(True)
        except (AttributeError, OSError):
            pass

        self.loop.event_loop.alarm(0, self._initial_setup_tasks)

        try:
            self.loop.run()
        except KeyboardInterrupt:
            print("\nAnanta TUI interrupted by user (KeyboardInterrupt).")
            if not self.is_exiting:
                self.initiate_exit()

        except Exception as e:
            print(f"\nAnanta TUI encountered an unexpected error: {e}")
            import traceback

            traceback.print_exc()
        else:
            # MainLoop.run suppresses ExitMainLoop internally, so a clean
            # return means a normal exit.
            print("\nAnanta TUI exiting normally.")
        finally:
            if not self.is_exiting:
                self.is_exiting = True

            if self.asyncio_loop and not self.asyncio_loop.is_closed():
                try:
                    pending = asyncio.all_tasks(self.asyncio_loop)
                    if pending:
                        self.asyncio_loop.run_until_complete(
                            asyncio.gather(*pending, return_exceptions=True)
                        )
                except RuntimeError:
                    pass
                finally:
                    if (
                        not self.asyncio_loop.is_closed()
                    ):  # Check again before closing
                        self.asyncio_loop.close()
            print("Ananta TUI has finished.")
