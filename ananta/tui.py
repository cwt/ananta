#!/usr/bin/env python
# ananta/tui.py (Urwid Version)
"""
Urwid-based Text User Interface for Ananta.
Handles asynchronous SSH connections and command execution on multiple hosts.
"""
from __future__ import annotations

import asyncio
import urwid
import asyncssh
import re # Import re for ANSI code parsing
from itertools import cycle
from random import shuffle
from typing import List, Dict, Tuple, Any, Set

# Assuming these are in the ananta package structure
from ananta.config import get_hosts
from ananta.ssh import establish_ssh_connection, stream_command_output

# --- Urwid-specific color and prompt generation ---
URWID_FG_COLORS: List[str] = [
    "dark red", "dark green", "brown", "dark blue",
    "dark magenta", "dark cyan", "light gray", "yellow", "light red",
    "light green", "light blue", "light magenta", "light cyan"
]
shuffle(URWID_FG_COLORS)
URWID_COLORS_CYCLE: cycle = cycle(URWID_FG_COLORS)

HOST_PALETTE_CONFIG: Dict[str, Tuple[str, str, str]] = {}
URWID_PALETTE: List[Any] = []

# --- ANSI to Urwid Markup Conversion ---
# Basic SGR to Urwid attribute mapping
# We'll define palette entries for these attributes later.
# Format: (urwid_attr_name, urwid_fg_color, urwid_bg_color, font_style_mono, urwid_fg_high, urwid_bg_high)
# For simplicity, we'll mostly use (name, fg, bg_default, style).
ANSI_SGR_PALETTE_MAP: Dict[str, Tuple[str, str, str, str | None]] = {
    # Reset and Basic Colors
    "0": ("", "", "", None), # Special case for reset
    "1": ("", "", "", "bold"), # Bold
    "4": ("", "", "", "underline"), # Underline (mono attribute)
    "30": ("ansifg_black", "black", "default", None),
    "31": ("ansifg_red", "dark red", "default", None),
    "32": ("ansifg_green", "dark green", "default", None),
    "33": ("ansifg_yellow", "brown", "default", None), # Urwid's 'yellow' is often bright
    "34": ("ansifg_blue", "dark blue", "default", None),
    "35": ("ansifg_magenta", "dark magenta", "default", None),
    "36": ("ansifg_cyan", "dark cyan", "default", None),
    "37": ("ansifg_white", "light gray", "default", None),
    # Bright Colors (often implemented as bold version of normal color or specific light colors)
    "90": ("ansifg_bright_black", "dark gray", "default", None),
    "91": ("ansifg_bright_red", "light red", "default", None),
    "92": ("ansifg_bright_green", "light green", "default", None),
    "93": ("ansifg_bright_yellow", "yellow", "default", None),
    "94": ("ansifg_bright_blue", "light blue", "default", None),
    "95": ("ansifg_bright_magenta", "light magenta", "default", None),
    "96": ("ansifg_bright_cyan", "light cyan", "default", None),
    "97": ("ansifg_bright_white", "white", "default", None),
    # Background Colors
    "40": ("ansibg_black", "default", "black", None),
    "41": ("ansibg_red", "default", "dark red", None),
    "42": ("ansibg_green", "default", "dark green", None),
    "43": ("ansibg_yellow", "default", "brown", None),
    "44": ("ansibg_blue", "default", "dark blue", None),
    "45": ("ansibg_magenta", "default", "dark magenta", None),
    "46": ("ansibg_cyan", "default", "dark cyan", None),
    "47": ("ansibg_white", "default", "light gray", None),
    # Bright Background Colors
    "100": ("ansibg_bright_black", "default", "dark gray", None),
    "101": ("ansibg_bright_red", "default", "light red", None),
    "102": ("ansibg_bright_green", "default", "light green", None),
    "103": ("ansibg_bright_yellow", "default", "yellow", None),
    "104": ("ansibg_bright_blue", "default", "light blue", None),
    "105": ("ansibg_bright_magenta", "default", "light magenta", None),
    "106": ("ansibg_bright_cyan", "default", "light cyan", None),
    "107": ("ansibg_bright_white", "default", "white", None),
}

# Compile the ANSI SGR pattern
ANSI_SGR_PATTERN = re.compile(r"\x1b\[([\d;]*)m")

def generate_ansi_palette_entries() -> List[Tuple[str, str, str, str | None, str | None, str | None]]:
    """Generates palette entries for the ANSI_SGR_PALETTE_MAP."""
    entries = []
    for code_str, (attr_name, fg, bg, style) in ANSI_SGR_PALETTE_MAP.items():
        if not attr_name: # Skip reset or style-only codes that don't define a full palette entry by themselves
            continue
        # Basic palette entry: (name, foreground, background, mono_style, foreground_high, background_high)
        # We use None for fg_high/bg_high as we are not defining separate high-color versions here.
        entries.append((attr_name, fg, bg, style if style else "", None, None))
    return entries

URWID_PALETTE.extend(generate_ansi_palette_entries())


def ansi_to_urwid_markup(line: str) -> List[Tuple[str, str] | str]:
    """
    Converts a string with ANSI SGR codes to Urwid markup list.
    """
    markup_list: List[Tuple[str, str] | str] = []
    last_pos = 0
    current_styles: Set[str] = set() # Store active SGR codes like "1", "31", "42"

    for match in ANSI_SGR_PATTERN.finditer(line):
        start, end = match.span()
        codes_str = match.group(1)

        # Add text segment before this ANSI code
        if start > last_pos:
            text_segment = line[last_pos:start]
            if current_styles:
                # Combine active styles to form a composite attribute name if needed,
                # or find a pre-defined one. For now, let's try to find one primary style.
                # This is a simplification; true composite styles are complex.
                # We'll prioritize color, then bold.
                attr_name_to_apply = ""
                # Try to find a color attribute
                color_attr = None
                style_attr = None

                active_fg_code = None
                active_bg_code = None
                is_bold = "1" in current_styles
                is_underline = "4" in current_styles

                for s_code in current_styles:
                    if '30' <= s_code <= '37' or '90' <= s_code <= '97': # Foreground
                        active_fg_code = s_code
                    elif '40' <= s_code <= '47' or '100' <= s_code <= '107': # Background
                        active_bg_code = s_code
                
                # Construct a composite key for a lookup or generate dynamically
                # For simplicity, we'll use the first found style that has an attr_name.
                # A more robust solution would combine styles into new palette entries.
                
                final_attr_name = ""
                # Prioritize combined bold/color if such palette entries exist
                # (e.g., 'ansifg_bold_red'). This part needs careful palette design.
                # For now, we'll just pick one.
                
                if active_fg_code and active_fg_code in ANSI_SGR_PALETTE_MAP:
                    final_attr_name = ANSI_SGR_PALETTE_MAP[active_fg_code][0]
                elif active_bg_code and active_bg_code in ANSI_SGR_PALETTE_MAP:
                     final_attr_name = ANSI_SGR_PALETTE_MAP[active_bg_code][0]
                elif is_bold: # If only bold is active among recognized styles
                    final_attr_name = "ansi_bold" # Requires ('ansi_bold', '', '', 'bold')
                elif is_underline:
                    final_attr_name = "ansi_underline" # Requires ('ansi_underline', '', '', 'underline')


                if final_attr_name:
                    markup_list.append((final_attr_name, text_segment))
                else:
                    markup_list.append(text_segment) # No specific style, plain text
            else:
                markup_list.append(text_segment)

        last_pos = end

        if not codes_str or codes_str == "0": # Reset
            current_styles.clear()
        else:
            codes = codes_str.split(';')
            for code in codes:
                if code == "0": # Reset among other codes
                    current_styles.clear()
                    # If reset is part of a multi-code sequence, subsequent codes in the same sequence apply *after* reset.
                    # Example: \x1b[0;31m means reset then set red.
                    # The loop will process next codes.
                    continue 
                if code in ANSI_SGR_PALETTE_MAP: # Check if it's a code we handle
                    current_styles.add(code)
                # Add more specific handling if needed, e.g., removing color if a new one is set.
                # For now, additive. `ls --color` usually resets before setting new colors.

    # Add any remaining text after the last ANSI code
    if last_pos < len(line):
        text_segment = line[last_pos:]
        if current_styles:
            attr_name_to_apply = ""
            active_fg_code = None
            active_bg_code = None
            is_bold = "1" in current_styles
            is_underline = "4" in current_styles
            for s_code in current_styles:
                if '30' <= s_code <= '37' or '90' <= s_code <= '97': active_fg_code = s_code
                elif '40' <= s_code <= '47' or '100' <= s_code <= '107': active_bg_code = s_code

            final_attr_name = ""
            if active_fg_code and active_fg_code in ANSI_SGR_PALETTE_MAP:
                final_attr_name = ANSI_SGR_PALETTE_MAP[active_fg_code][0]
            elif active_bg_code and active_bg_code in ANSI_SGR_PALETTE_MAP:
                 final_attr_name = ANSI_SGR_PALETTE_MAP[active_bg_code][0]
            elif is_bold: final_attr_name = "ansi_bold"
            elif is_underline: final_attr_name = "ansi_underline"

            if final_attr_name:
                markup_list.append((final_attr_name, text_segment))
            else:
                markup_list.append(text_segment)
        else:
            markup_list.append(text_segment)
            
    # Filter out empty strings that might result from consecutive ANSI codes
    return [part for part in markup_list if isinstance(part, tuple) or (isinstance(part, str) and part)]


def _get_host_palette_attr_name(host_name: str) -> str:
    """Generates a sanitized attribute name for the urwid palette."""
    return f"host_{host_name.lower().replace('-', '_').replace(' ', '_').replace('.', '_')}"

def _ensure_host_palette_entry(host_name: str) -> str:
    """
    Ensures a palette entry exists for the host and returns its attribute name.
    This function populates HOST_PALETTE_CONFIG and URWID_PALETTE.
    """
    attr_name = _get_host_palette_attr_name(host_name)
    if host_name not in HOST_PALETTE_CONFIG:
        fg_color = next(URWID_COLORS_CYCLE)
        palette_entry = (attr_name, fg_color, "default") 
        HOST_PALETTE_CONFIG[host_name] = palette_entry
        if palette_entry not in URWID_PALETTE:
            URWID_PALETTE.append(palette_entry)
    return attr_name

def format_host_prompt_markup(host_name: str, max_name_length: int) -> List[Tuple[str, str] | str]:
    """
    Formats the host prompt for urwid.Text using markup.
    Returns a list suitable for urwid.Text constructor.
    """
    attr_name = _ensure_host_palette_entry(host_name)
    padded_host = host_name.rjust(max_name_length)
    return [(attr_name, f"[{padded_host}] ")]


class AnantaUrwidTUI:
    """
    Main class for Ananta's Urwid-based Text User Interface.
    """
    DEFAULT_PALETTE_ENTRIES = [
        ('status_ok', 'light green', 'default'),
        ('status_error', 'light red', 'default'),
        ('status_neutral', 'yellow', 'default'),
        ('command_echo', 'light cyan', 'default', 'bold'),
        ('body', 'white', 'default'),
        ('input_prompt', 'light blue', 'default'),
        # Add entries for basic styles if not covered by color attributes
        ('ansi_bold', '', '', 'bold', '', ''), # For bold text without specific color
        ('ansi_underline', '', '', 'underline', '', ''), # For underlined text
    ]

    def __init__(self, host_file: str, initial_command: str | None,
                 host_tags: str | None, default_key: str | None):
        self.host_file = host_file
        self.initial_command = initial_command
        self.host_tags = host_tags
        self.default_key = default_key

        self.hosts_to_execute, self.max_name_length = get_hosts(self.host_file, self.host_tags)

        for host_info in self.hosts_to_execute:
            _ensure_host_palette_entry(host_info[0])

        self.connections: Dict[str, asyncssh.SSHClientConnection | None] = \
            {host[0]: None for host in self.hosts_to_execute}

        self.output_walker = urwid.SimpleFocusListWalker([])
        self.output_box = urwid.ListBox(self.output_walker)
        self.input_field = urwid.Edit(edit_text="")

        self.input_wrapper = urwid.Columns([
            ('fixed', 2, urwid.AttrMap(urwid.Text([('input_prompt', "> ")]), 'input_prompt')),
            self.input_field
        ], dividechars=0)

        self.main_layout = urwid.Frame(
            body=urwid.AttrMap(self.output_box, 'body'),
            footer=urwid.AttrMap(self.input_wrapper, 'body')
        )

        self.loop: urwid.MainLoop | None = None
        self._running_async_tasks: Set[asyncio.Task[Any]] = set()
        self._is_exiting: bool = False
        self._actual_asyncio_loop: asyncio.AbstractEventLoop | None = None
        self._draw_screen_handle: Any = None 

    def _request_draw_screen(self, loop_arg=None, user_data_arg=None):
        if self.loop:
            self.loop.draw_screen()
        self._draw_screen_handle = None 

    def _add_output_line(self, message_parts: List[Any] | str, scroll: bool = True):
        can_schedule_draw = self.loop and \
                            self.loop.event_loop and \
                            self._actual_asyncio_loop and \
                            self._actual_asyncio_loop.is_running()

        if self._is_exiting and not any(s in str(message_parts).lower() for s in ["exiting", "closed", "cleanup", "shutdown", "processed"]):
            if not can_schedule_draw: 
                return

        # If message_parts is already Urwid markup, use it directly.
        # Otherwise, assume it's a plain string or a list to be wrapped.
        if isinstance(message_parts, list) and \
           all(isinstance(p, tuple) or isinstance(p, str) for p in message_parts):
            # This looks like Urwid markup already (e.g. from format_host_prompt_markup + status)
            # However, if it contains raw text that needs ANSI processing, that's an issue.
            # The prompt part is fine. Status messages are fine.
            # The key is that raw output from SSH (which needs ANSI processing)
            # should be processed *before* being combined with the prompt here.
            # So, this method expects `message_parts` to be *ready* for urwid.Text
            widget = urwid.Text(message_parts)

        elif isinstance(message_parts, str): # A single string, potentially with ANSI
            # This case is now less likely if _run_command_on_host_async pre-processes.
            # If it still happens, it implies a part of the code isn't using the converter.
            # For safety, we could process it here, but it's better to process at source.
            # For now, assume if it's a raw string, it's meant to be plain or already processed.
            widget = urwid.Text(ansi_to_urwid_markup(message_parts))
        else: # Fallback for unexpected types, treat as plain string
            widget = urwid.Text(str(message_parts))


        self.output_walker.append(widget)
        if len(self.output_walker) > 3000:
            del self.output_walker[0:len(self.output_walker)-2000]
        if scroll:
            self.output_walker.set_focus(len(self.output_walker) - 1)

        if can_schedule_draw and not self._draw_screen_handle:
             self._draw_screen_handle = self.loop.event_loop.alarm(0, self._request_draw_screen)


    async def _connect_single_host_async(self, host_name: str, ip_address: str,
                                         ssh_port: int, username: str, key_path: str):
        if self._is_exiting: return
        prompt_markup = format_host_prompt_markup(host_name, self.max_name_length)
        self._add_output_line(prompt_markup + [('status_neutral', "Connecting...")])
        try:
            conn = await establish_ssh_connection(
                ip_address, ssh_port, username, key_path, self.default_key,
                timeout=10.0
            )
            conn.set_keepalive(interval=30, count_max=3)
            self.connections[host_name] = conn
            self._add_output_line(prompt_markup + [('status_ok', "Connected.")])
        except Exception as e:
            self.connections[host_name] = None
            self._add_output_line(prompt_markup + [('status_error', f"Connection failed: {e}")])

    async def _connect_all_hosts_async(self):
        if self._is_exiting: return
        
        if not self.hosts_to_execute:
            self._add_output_line(ansi_to_urwid_markup(
                f"[status_neutral]No hosts found or parsed from '{self.host_file}'.\n"
                f"Please check the file path and format. Waiting for commands...[/status_neutral]"
            )) # Process potential markup in this message too
            return

        connect_tasks = []
        for host_details in self.hosts_to_execute:
            host_name, ip_address, ssh_port, username, key_path = host_details
            task = asyncio.create_task(
                self._connect_single_host_async(host_name, ip_address, ssh_port, username, key_path)
            )
            self._running_async_tasks.add(task)
            task.add_done_callback(self._running_async_tasks.discard)
            connect_tasks.append(task)
        
        await asyncio.gather(*connect_tasks, return_exceptions=True)

        if self.initial_command and not self._is_exiting:
            self.input_field.set_edit_text(self.initial_command)
            self._process_input_command(self.initial_command)

    def _process_input_command(self, command_text: str):
        if self._is_exiting: return
        command = command_text.strip()
        if not command: return

        if command.lower() == "exit":
            self._initiate_graceful_exit()
            return
        
        # The ">>> command" line itself does not contain remote ANSI codes
        self._add_output_line([('command_echo', f">>> {command}")])
        self.input_field.set_edit_text("")

        for host_name, conn in self.connections.items():
            if self._is_exiting: break
            if conn and not conn.is_closed():
                task = asyncio.create_task(
                    self._run_command_on_host_async(host_name, conn, command)
                )
                self._running_async_tasks.add(task)
                task.add_done_callback(self._running_async_tasks.discard)
            else:
                prompt_markup = format_host_prompt_markup(host_name, self.max_name_length)
                self._add_output_line(prompt_markup + [('status_error', "Not connected, skipping command.")])

    async def _run_command_on_host_async(self, host_name: str,
                                         conn: asyncssh.SSHClientConnection, command: str):
        if self._is_exiting: return
        prompt_markup = format_host_prompt_markup(host_name, self.max_name_length)
        
        cols = 80 
        if self.loop and self.loop.screen:
             current_cols, _ = self.loop.screen.get_cols_rows()
             cols = current_cols

        remote_width = cols - self.max_name_length - 3 
        if remote_width < 10: remote_width = 80

        output_queue: asyncio.Queue[str | None] = asyncio.Queue()

        stream_task = asyncio.create_task(
            stream_command_output(conn, command, remote_width, output_queue, color=True)
        )
        self._running_async_tasks.add(stream_task)
        task_done_callback = self._running_async_tasks.discard 
        stream_task.add_done_callback(task_done_callback)

        while not self._is_exiting:
            try:
                line = await asyncio.wait_for(output_queue.get(), timeout=0.1)
            except asyncio.TimeoutError:
                if stream_task.done(): break
                continue
            
            if line is None: break # End of stream for this command
            if self._is_exiting: break

            # Convert ANSI in the received line to Urwid markup
            processed_line_markup = ansi_to_urwid_markup(line.rstrip('\n\r'))
            # Combine with host prompt markup
            full_line_markup = prompt_markup + processed_line_markup
            self._add_output_line(full_line_markup)
        
        if not stream_task.done():
            stream_task.cancel()
        try:
            await stream_task
        except asyncio.CancelledError:
            if not self._is_exiting: 
                 self._add_output_line(prompt_markup + [('status_neutral', "Command cancelled.")])
        except Exception as e:
            if not self._is_exiting:
                self._add_output_line(prompt_markup + [('status_error', f"Error during command: {e}")])

    def _unhandled_input_handler(self, key: str):
        if self._is_exiting: return True

        if key == 'enter':
            command = self.input_field.edit_text
            self._process_input_command(command)
            return True
        if key in ('ctrl d', 'ctrl c'):
            self._initiate_graceful_exit()
            return True
        return False

    def _initiate_graceful_exit(self):
        if not self._is_exiting:
            self._is_exiting = True
            async def exit_sequence():
                await self._perform_shutdown_tasks()
                if self.loop and self.loop.event_loop: 
                    self.loop.event_loop.alarm(0, lambda _passed_event_loop=None, _passed_user_data=None: self._exit_main_loop_throw())
            
            if self._actual_asyncio_loop and not self._actual_asyncio_loop.is_closed():
                 asyncio.create_task(exit_sequence())
            else: 
                 print("Warning: Asyncio loop not available for graceful exit sequence.")
                 if self.loop: 
                     try:
                         self._exit_main_loop_throw()
                     except urwid.ExitMainLoop:
                         pass 
                     except Exception as e:
                         print(f"Error during fallback exit attempt: {e}")


    def _exit_main_loop_throw(self):
        raise urwid.ExitMainLoop()

    async def _perform_shutdown_tasks(self):
        self._add_output_line(ansi_to_urwid_markup("[status_neutral]Exiting... Closing connections...[/status_neutral]"))
        
        connection_close_tasks = []
        for host_name, conn in self.connections.items():
            if conn and not conn.is_closed():
                conn.close()
                async def await_conn_closed(c, hn):
                    try:
                        await asyncio.wait_for(c.wait_closed(), timeout=2.0)
                    except (asyncio.TimeoutError, Exception):
                        pass
                connection_close_tasks.append(asyncio.create_task(await_conn_closed(conn, host_name)))
        
        if connection_close_tasks:
            await asyncio.gather(*connection_close_tasks, return_exceptions=True)
        
        self._add_output_line(ansi_to_urwid_markup("[status_neutral]Connections processed for shutdown.[/status_neutral]"))
        await self._cleanup_all_remaining_async_tasks()

    async def _cleanup_all_remaining_async_tasks(self):
        if self._running_async_tasks:
            tasks_to_cancel = list(self._running_async_tasks)
            for task in tasks_to_cancel:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks_to_cancel, return_exceptions=True)
            self._running_async_tasks.clear()

    def _get_final_palette(self) -> List[Any]:
        # Combine default, host-specific, and ANSI-specific palette entries
        # Ensure host palette entries are generated if not already
        for host_data in self.hosts_to_execute:
            _ensure_host_palette_entry(host_data[0])
        
        # Get ANSI palette entries
        ansi_palette = generate_ansi_palette_entries()

        # Combine all, ensuring unique names (last one wins for duplicates)
        combined_palette = self.DEFAULT_PALETTE_ENTRIES + URWID_PALETTE + ansi_palette
        
        seen_names = set()
        unique_final_palette = []
        for entry_tuple in reversed(combined_palette):
            # Ensure entry_tuple is a tuple and has at least one element (the name)
            if isinstance(entry_tuple, tuple) and len(entry_tuple) > 0:
                name = entry_tuple[0]
                if name not in seen_names:
                    unique_final_palette.insert(0, entry_tuple)
                    seen_names.add(name)
            # else: log or handle malformed palette entry if necessary
        return unique_final_palette


    def _start_initial_tasks_callback(self, urwid_event_loop_obj=None, user_data_for_callback=None):
        if self._actual_asyncio_loop and not self._actual_asyncio_loop.is_closed():
            asyncio.create_task(self._connect_all_hosts_async())
        else:
            print("Warning: Cannot start initial tasks, asyncio loop not available or closed.")


    def run(self):
        self._actual_asyncio_loop = asyncio.get_event_loop_policy().get_event_loop()
        asyncio.set_event_loop(self._actual_asyncio_loop)

        urwid_event_loop_adapter = urwid.AsyncioEventLoop(loop=self._actual_asyncio_loop)

        self.loop = urwid.MainLoop(
            widget=self.main_layout,
            palette=self._get_final_palette(),
            event_loop=urwid_event_loop_adapter,
            unhandled_input=self._unhandled_input_handler
        )
        
        if self.loop.widget: 
            self.loop.widget.focus_position = 'footer'

        try:
            self.loop.screen.set_terminal_properties(colors=256)
        except Exception:
            pass # self._add_output_line("Note: Could not set 256 colors.") # Not safe here

        self.loop.event_loop.alarm(0, self._start_initial_tasks_callback)

        try:
            self.loop.run() 
        except urwid.ExitMainLoop:
            pass 
        except KeyboardInterrupt:
            print("\nAnanta TUI interrupted by KeyboardInterrupt.")
            if not self._is_exiting: 
                self._initiate_graceful_exit() 
                if self._actual_asyncio_loop and not self._actual_asyncio_loop.is_closed():
                    pass
        except Exception as e:
            print(f"\nAnanta TUI main loop crashed: {e}")
            import traceback
            traceback.print_exc()
        finally:
            if not self._is_exiting:
                self._is_exiting = True 

            if self._actual_asyncio_loop and not self._actual_asyncio_loop.is_closed():
                try:
                    # Ensure _perform_shutdown_tasks is awaited correctly
                    shutdown_task = self._actual_asyncio_loop.create_task(self._perform_shutdown_tasks())
                    self._actual_asyncio_loop.run_until_complete(shutdown_task)
                except RuntimeError as e_rt:
                    if "cannot schedule new futures after shutdown" not in str(e_rt) and \
                       "Event loop is closed" not in str(e_rt):
                        pass 
                except Exception:
                    pass
            
            print("\nAnanta TUI has finished.")

