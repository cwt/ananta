#!/usr/bin/env python
"""
Urwid-based Text User Interface for Ananta.
Manages asynchronous SSH connections and command execution on multiple remote hosts.
"""
from __future__ import annotations
from ..config import get_hosts
from ..ssh import establish_ssh_connection, stream_command_output
from .ansi import ansi_to_urwid_markup
from itertools import cycle
from random import shuffle
from typing import Any, Dict, List, Set, Tuple
import asyncio
import asyncssh
import re
import urwid


# --- Setup colors for hosts ---
URWID_FG_COLORS = [
    "yellow",
    "light red",
    "light green",
    "light blue",
    "light magenta",
    "light cyan",
]  # dark colors are not used to avoid confusion with similarity of colors
shuffle(URWID_FG_COLORS)  # Shuffle to randomize color assignment
COLORS_CYCLE = cycle(URWID_FG_COLORS)  # Create a cycle in case of many hosts


def _get_host_attr_name(host_name: str) -> str:
    return f"host_{host_name.lower().replace('-', '_').replace(' ', '_').replace('.', '_')}"


# format_host_prompt no longer needs palette_list or self
def format_host_prompt(
    host_name: str, max_name_length: int
) -> List[Tuple[str, str]]:
    attr_name = _get_host_attr_name(host_name)
    padded_host = host_name.rjust(max_name_length)
    return [(attr_name, f"[{padded_host}] ")]


class AnantaUrwidTUI:
    """Ananta Text User Interface using Urwid."""

    DEFAULT_PALETTE = [
        ("status_ok", "light green", "default", None, None, None),
        ("status_error", "light red", "default", None, None, None),
        ("status_neutral", "yellow", "default", None, None, None),
        ("command_echo", "light cyan,bold", "default", None, None, None),
        ("body", "white", "default", None, None, None),
        ("input_prompt", "light blue", "default", None, None, None),
        ("input_prompt_inactive", "dark gray", "default", None, None, None),
        ("ansi_bold", "bold", "default", None, None, None),
        ("ansi_underline", "underline", "default", None, None, None),
        ("ansi_standout", "standout", "default", None, None, None),
    ]

    def __init__(
        self,
        host_file: str,
        initial_command: str | None,
        host_tags: str | None,
        default_key: str | None,
        separate_output: bool,
        allow_empty_line: bool,
    ):
        """Initialize the Ananta TUI."""
        # --- SSH, connection, and output setup ---
        self.host_file = host_file
        self.initial_command = initial_command
        self.host_tags = host_tags
        self.default_key = default_key
        self.separate_output = separate_output
        self.allow_empty_line = allow_empty_line
        self.hosts, self.max_name_length = get_hosts(host_file, host_tags)
        self.connections: Dict[str, asyncssh.SSHClientConnection | None] = {
            host[0]: None for host in self.hosts
        }
        self.output_queues: Dict[str, asyncio.Queue[str | None]] = {
            host[0]: asyncio.Queue() for host in self.hosts
        }
        # --- Urwid setup ---
        self.host_palette_definitions: Dict[
            str, Tuple[str, str, str, None, None, None]
        ] = {}
        self._populate_host_palette_definitions()
        self.current_palette = self._build_palette()
        self.output_walker = urwid.SimpleFocusListWalker([])
        self.output_box = urwid.ListBox(self.output_walker)
        self.input_field = urwid.Edit(edit_text="")
        self.prompt_widget = urwid.Text(">>> ")
        self.prompt_attr_map = urwid.AttrMap(self.prompt_widget, "input_prompt")
        self.input_wrapper = urwid.Columns(
            [
                ("fixed", 4, self.prompt_attr_map),
                self.input_field,
            ],
            dividechars=0,
        )
        self.main_pile = urwid.Pile(
            [
                ("weight", 1, urwid.AttrMap(self.output_box, "body")),
                ("fixed", 1, urwid.SolidFill("─")),
                ("fixed", 1, urwid.AttrMap(self.input_wrapper, "body")),
            ]
        )
        self.main_layout = urwid.Frame(body=self.main_pile)
        self.main_pile.focus_position = 2
        urwid.connect_signal(
            self.input_field, "change", self.update_prompt_attribute
        )
        # --- Event loop and async tasks setup ---
        self.loop: urwid.MainLoop | None = None
        self.async_tasks: Set[asyncio.Task[Any]] = set()
        self.is_exiting = False
        self.asyncio_loop: asyncio.AbstractEventLoop | None = None
        self.draw_screen_handle: Any = None

    def _populate_host_palette_definitions(self) -> None:
        """Pre-populates host-specific palette entries."""
        for host_name, *_ in self.hosts:
            attr_name = _get_host_attr_name(host_name)
            if attr_name not in self.host_palette_definitions:
                fg_color = next(COLORS_CYCLE)
                self.host_palette_definitions[attr_name] = (
                    attr_name,
                    fg_color,
                    "default",
                    None,
                    None,
                    None,
                )

    def _build_palette(self) -> List[Tuple[str | None, ...]]:
        """Build the complete palette for Urwid, including default and host-specific styles."""
        palette = list(self.DEFAULT_PALETTE)

        # Add pre-defined host styles
        for host_entry in self.host_palette_definitions.values():
            # Simple check to avoid adding if somehow already present by name
            # More robust deduplication happens next anyway
            if not any(
                entry[0] == host_entry[0]
                for entry in palette
                if entry and entry[0]
            ):
                palette.append(host_entry)

        seen_names = set()
        unique_palette: List[Tuple[str | None, ...]] = []
        for entry in reversed(
            palette
        ):  # Iterate from the end to keep last definition of a name
            if isinstance(entry, tuple) and entry[0] is not None:
                if entry[0] not in seen_names:
                    unique_palette.insert(0, entry)
                    seen_names.add(entry[0])
        return unique_palette

    def add_output(
        self, message_parts: List[Any] | str, scroll: bool = True
    ) -> None:
        """Add output to the display."""
        if self.is_exiting and not any(
            s in str(message_parts).lower()
            for s in [
                "exiting",
                "closed",
                "cleanup",
                "shutdown",
                "processed",
                "failed",
                "error",
            ]
        ):
            return

        if isinstance(message_parts, str):
            processed_markup = ansi_to_urwid_markup(message_parts)
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

        self.output_walker.append(widget)

        _, rows = self.loop.screen.get_cols_rows()
        max_lines = rows * 5
        trim_lines = rows
        if len(self.output_walker) > max_lines:
            del self.output_walker[
                0 : len(self.output_walker) - (max_lines - trim_lines)
            ]

        if scroll:
            self.output_walker.set_focus(len(self.output_walker) - 1)

        if self.loop and self.loop.event_loop and not self.draw_screen_handle:
            self.draw_screen_handle = self.loop.event_loop.alarm(
                0, self._request_draw
            )

    def _request_draw(self, *_args: Any) -> None:
        """Request a redraw of the screen."""
        if self.loop:
            self.loop.draw_screen()
        self.draw_screen_handle = None

    async def connect_host(
        self, host_name: str, ip: str, port: int, user: str, key: str
    ) -> None:
        """Establish an SSH connection to a single host."""
        if self.is_exiting:
            return

        prompt = format_host_prompt(
            host_name, self.max_name_length
        )  # No longer needs self.current_palette
        self.add_output(prompt + [("status_neutral", "Connecting...")])

        try:
            conn = await establish_ssh_connection(
                ip, port, user, key, self.default_key, timeout=10.0
            )
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

        if self.initial_command and not self.is_exiting:
            self.input_field.set_edit_text(self.initial_command)
            self.process_command(self.initial_command)

    def process_command(self, command: str) -> None:
        """Process a command entered in the input field."""
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
                task = asyncio.create_task(
                    self.run_command_on_host(host_name, conn, command)
                )
                self.async_tasks.add(task)
                task.add_done_callback(self.async_tasks.discard)
            else:
                prompt = format_host_prompt(host_name, self.max_name_length)
                self.add_output(
                    prompt + [("status_error", "Not connected, skipping.")]
                )

    async def run_command_on_host(
        self, host_name: str, conn: asyncssh.SSHClientConnection, command: str
    ) -> None:
        """Run a command on a specific host and stream the output."""
        if self.is_exiting:  # If exiting, do not run commands
            return

        prompt = format_host_prompt(host_name, self.max_name_length)

        cols = 80
        if self.loop and self.loop.screen:
            cols = self.loop.screen.get_cols_rows()[0]
        remote_width = max(cols - self.max_name_length - 3, 10)

        output_queue: asyncio.Queue[str | None] = self.output_queues[host_name]

        stream_task = asyncio.create_task(
            stream_command_output(
                conn, command, remote_width, output_queue, color=True
            )
        )
        self.async_tasks.add(stream_task)
        stream_task.add_done_callback(self.async_tasks.discard)

        try:
            if self.separate_output:
                collected_output: List[str] = []
                while not self.is_exiting:
                    try:
                        line_data = await asyncio.wait_for(
                            output_queue.get(), timeout=0.1
                        )
                    except asyncio.TimeoutError:
                        if stream_task.done():
                            break
                        continue
                    if line_data is None:
                        break
                    collected_output.append(line_data)
                for line_data in collected_output:
                    processed_line_markup = ansi_to_urwid_markup(
                        line_data.rstrip("\r\n")
                    )
                    if processed_line_markup:
                        self.add_output(prompt + processed_line_markup)
                    elif self.allow_empty_line and line_data.strip() == "":
                        self.add_output(prompt + [""])
            else:
                while not self.is_exiting:
                    try:
                        line_data = await asyncio.wait_for(
                            output_queue.get(), timeout=0.1
                        )
                    except asyncio.TimeoutError:
                        if stream_task.done():
                            break
                        continue

                    if line_data is None:
                        break

                    processed_line_markup = ansi_to_urwid_markup(
                        line_data.rstrip("\r\n")
                    )
                    if processed_line_markup:
                        self.add_output(prompt + processed_line_markup)
                    elif (
                        self.allow_empty_line
                        and line_data.strip() == ""
                        and not processed_line_markup
                    ):
                        self.add_output(prompt + [""])

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
            except Exception:
                pass

    def update_prompt_attribute(self, *args, **kwargs):
        """Update input prompt color"""
        if self.main_pile.focus_position == 2:
            self.prompt_attr_map.set_attr_map({None: "input_prompt"})
        else:
            self.prompt_attr_map.set_attr_map({None: "input_prompt_inactive"})

    def handle_input(self, key: str) -> bool | None:
        """Handle user input from the keyboard."""
        if self.is_exiting:
            return True

        self.update_prompt_attribute()

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
            self.asyncio_loop.create_task(self.perform_shutdown())
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
                    format_host_prompt(host_name, self.max_name_length)
                    + [("status_neutral", "Closing...")]
                )
                close_conn_tasks.append(
                    asyncio.create_task(self._close_single_connection(conn))
                )

        if close_conn_tasks:
            await asyncio.gather(*close_conn_tasks, return_exceptions=True)
        self.add_output(
            [("status_neutral", "All connections closed or timed out.")]
        )

        if self.async_tasks:
            self.add_output(
                [
                    (
                        "status_neutral",
                        f"Cleaning up {len(self.async_tasks)} tasks...",
                    )
                ]
            )
            for task in list(self.async_tasks):
                if not task.done():
                    task.cancel()
            await asyncio.gather(*self.async_tasks, return_exceptions=True)
            self.async_tasks.clear()

        self.add_output(
            [("status_neutral", "Cleanup complete. Ananta TUI will now exit.")]
        )

        if self.loop and self.loop.event_loop:
            self.loop.event_loop.alarm(0, self._direct_exit_loop)

    async def _close_single_connection(
        self, conn: asyncssh.SSHClientConnection
    ) -> None:
        """Close a single SSH connection gracefully."""
        try:
            conn.close()
            await asyncio.wait_for(conn.wait_closed(), timeout=2.0)
        except (asyncio.TimeoutError, Exception):
            pass

    def _initial_setup_tasks(self, *_args: Any) -> None:
        """Perform initial setup tasks after the main loop starts."""
        if self.asyncio_loop and not self.asyncio_loop.is_closed():
            self.asyncio_loop.create_task(self.connect_all_hosts())
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
        try:
            self.asyncio_loop = asyncio.get_event_loop_policy().get_event_loop()
        except RuntimeError:
            self.asyncio_loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.asyncio_loop)

        urwid_event_loop = urwid.AsyncioEventLoop(loop=self.asyncio_loop)

        self.loop = urwid.MainLoop(
            widget=self.main_layout,
            palette=self.current_palette,  # Use the pre-built palette
            event_loop=urwid_event_loop,
            unhandled_input=self.handle_input,
        )

        self.main_pile.focus_position = 2
        if isinstance(self.input_wrapper, urwid.Columns):
            self.input_wrapper.focus_position = 1
        elif hasattr(self.input_wrapper, "focus_col"):
            self.input_wrapper.focus_col = 1

        try:
            self.loop.screen.set_terminal_properties(colors=256)
        except Exception:
            pass

        self.loop.event_loop.alarm(0, self._initial_setup_tasks)

        try:
            self.loop.run()
        except urwid.ExitMainLoop:
            print("\nAnanta TUI exiting normally.")
        except KeyboardInterrupt:
            print("\nAnanta TUI interrupted by user (KeyboardInterrupt).")
            if not self.is_exiting:
                self.initiate_exit()
                if (
                    self.asyncio_loop
                    and not self.asyncio_loop.is_closed()
                    and self.is_exiting
                ):
                    self.asyncio_loop.run_until_complete(
                        self.asyncio_loop.shutdown_asyncgens()
                    )
        except Exception as e:
            print(f"\nAnanta TUI encountered an unexpected error: {e}")
            import traceback

            traceback.print_exc()
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
