#!/usr/bin/env python
"""
Ananta: a command-line tool that allows users to execute commands on multiple
remote hosts at once via SSH. With Ananta, you can streamline your workflow,
automate repetitive tasks, and save time and effort.
"""

from . import __version__

from .config import get_hosts
from .output import print_output  # Used by non-TUI mode
from .ssh import execute  # Used by non-TUI mode
from types import ModuleType
from typing import Dict, List
import argparse
import asyncio
import os
import sys

uvloop: ModuleType | None = None
try:
    if sys.platform == "win32":
        import winloop as uvloop
    else:
        import uvloop
except ImportError:
    pass  # uvloop or winloop is an optional for speedup, not a requirement


async def main(  # This is the non-TUI main function
    host_file: str,
    ssh_command: str,
    local_display_width: int,
    separate_output: bool,
    allow_empty_line: bool,
    allow_cursor_control: bool,
    default_key: str | None,
    color: bool,
    host_tags: str | None,
) -> None:
    """Main function to execute commands on multiple remote hosts (non-TUI mode)."""

    hosts_to_execute, max_name_length = get_hosts(host_file, host_tags)

    if not hosts_to_execute:
        print("No hosts found to execute the command on.")
        return

    # Dictionary to hold separate output queues for each host
    output_queues: Dict[str, asyncio.Queue[str | None]] = {
        host_name: asyncio.Queue() for host_name, *_ in hosts_to_execute
    }

    # Create a lock for synchronizing output printing
    print_lock = asyncio.Lock()

    # Create a separate task for each host to print the output
    print_tasks = [
        print_output(
            host_name,
            max_name_length,
            allow_empty_line,
            allow_cursor_control,
            separate_output,
            print_lock,
            output_queues[host_name],
            color,
        )
        for host_name, *_ in hosts_to_execute
    ]
    # Ensure future is created for Python 3.10 compatibility with some asyncio versions
    # For modern asyncio, ensure_future is often not needed for create_task results.
    # However, gathering them is the main point.
    # asyncio.gather itself will schedule them if they are bare coroutines.
    # If they are already tasks, gather works fine.
    # Let's keep ensure_future for clarity or remove if targeting only very new Python/asyncio.
    # For now, let's rely on gather to handle it.
    # asyncio.ensure_future(asyncio.gather(*print_tasks)) # Old way
    # Modern way: just gather the coroutines/tasks.
    # If print_output are coroutines, gather will schedule them.
    # If they are already tasks (e.g. from create_task), gather awaits them.
    # The list comprehension creates coroutines, so gather will schedule them.

    # We need to ensure print_tasks are running in the background
    # while execute tasks are also running.
    # One way is to create tasks for them and then gather execute tasks.

    printing_task_group = asyncio.gather(*print_tasks)

    # Create a task for each host to execute the SSH command
    exec_tasks = [
        execute(
            host_name,
            ip_address,
            ssh_port,
            username,
            key_path,
            ssh_command,
            max_name_length,
            local_display_width,
            separate_output,
            default_key,
            output_queues[host_name],  # Pass the queue here
            color,
        )
        for host_name, ip_address, ssh_port, username, key_path in hosts_to_execute
    ]

    # Execute all command execution tasks concurrently
    await asyncio.gather(*exec_tasks)

    # After all exec_tasks are done, signal end to print_tasks
    for host_name in output_queues:
        await output_queues[host_name].put(None)

    # Wait for all printing tasks to complete
    await printing_task_group


def run_cli() -> None:
    """Command-line interface for Ananta."""
    parser = argparse.ArgumentParser(
        description="Execute commands on multiple remote hosts via SSH."
    )
    parser.add_argument(
        "host_file",
        nargs="?",
        default=None,
        help="File containing host information",
    )
    parser.add_argument(
        "command",
        nargs=argparse.REMAINDER,
        help="Command to execute on remote hosts",
    )
    parser.add_argument(
        "--tui",
        action="store_true",
        help="Launch the Urwid-based Text User Interface (TUI) mode.",  # Updated help text
    )
    parser.add_argument(
        "-n",
        "-N",
        "--no-color",
        action="store_true",
        help="Disable host coloring (for non-TUI mode)",  # Clarified help
    )
    parser.add_argument(
        "-s",
        "-S",
        "--separate-output",
        action="store_true",
        help="Print output from each host without interleaving (for non-TUI mode)",  # Clarified help
    )
    parser.add_argument(
        "-t",
        "-T",
        "--host-tags",
        type=str,
        help="Host's tag(s) (comma separated)",
    )
    parser.add_argument(
        "-w",
        "-W",
        "--terminal-width",
        type=int,
        help="Set terminal width (for non-TUI mode)",  # Clarified help
    )
    parser.add_argument(
        "-e",
        "-E",
        "--allow-empty-line",
        action="store_true",
        help="Allow printing the empty line (for non-TUI mode)",  # Clarified help
    )
    parser.add_argument(
        "-c",
        "-C",
        "--allow-cursor-control",
        action="store_true",
        help=(
            "Allow cursor control codes (for non-TUI mode; "
            "useful for commands like fastfetch or neofetch)"
        ),  # Clarified help
    )
    parser.add_argument(
        "-v",
        "-V",
        "--version",
        action="store_true",
        help="Show the version of Ananta",
    )
    parser.add_argument(
        "-k",
        "-K",
        "--default-key",
        type=str,
        help="Path to default SSH private key",
    )
    args: argparse.Namespace = parser.parse_args()

    if uvloop:
        # To maintain compatibility with tests while addressing deprecation
        # Suppress the deprecation warning for the necessary function call
        import warnings

        with warnings.catch_warnings():
            warnings.filterwarnings(
                "ignore",
                message=".*set_event_loop_policy.*",
                category=DeprecationWarning,
            )
            asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())

    if args.version:
        # Print the version of Ananta with the asyncio event loop module
        # Determine which module will be used without directly calling get_event_loop_policy()
        if uvloop:
            # Use a new loop instance to get the module name
            temp_loop = uvloop.new_event_loop()
            loop_module = temp_loop.__class__.__module__
            temp_loop.close()
        else:
            # For default policy, we'll create a temporary loop to get its module
            temp_loop = asyncio.new_event_loop()
            loop_module = temp_loop.__class__.__module__
            temp_loop.close()
        print(f"Ananta-{__version__} " f"powered by {loop_module}")
        sys.exit(0)

    host_file: str | None = args.host_file
    ssh_command_list: List[str] = (
        args.command
    )  # Keep as list for TUI initial command
    ssh_command_str: str = " ".join(ssh_command_list)

    if not host_file:
        parser.print_help()
        sys.exit(0)

    if args.tui:
        try:
            import urwid  # noqa -- check if urwid is installed
        except ImportError:
            print(
                "Error: 'urwid' library is required for TUI mode but is not installed."
            )
            print("Please install it, for example: pip install urwid")
            sys.exit(1)

        # Assuming the new Urwid TUI class is in ananta.tui
        from ananta.tui import AnantaUrwidTUI

        app = AnantaUrwidTUI(
            host_file=host_file,  # Already checked it's not None
            initial_command=(
                ssh_command_str if ssh_command_str.strip() else None
            ),
            host_tags=args.host_tags,
            default_key=args.default_key,
            separate_output=args.separate_output,
            allow_empty_line=args.allow_empty_line,
        )
        app.run()  # This will block until the TUI exits
        sys.exit(0)  # Exit after TUI finishes

    # Non-TUI mode continues from here
    if (
        not ssh_command_str.strip()
    ):  # Check if command is empty for non-TUI mode
        print("Error: No command specified for non-TUI mode.")
        parser.print_help()
        sys.exit(1)  # Exit with error if no command for non-TUI

    try:
        local_display_width: int = args.terminal_width or int(
            os.environ.get("COLUMNS", os.get_terminal_size().columns)
        )
    except OSError:
        local_display_width = args.terminal_width or 80

    color = not args.no_color

    asyncio.run(
        main(
            host_file,
            ssh_command_str,
            local_display_width,
            args.separate_output,
            args.allow_empty_line,
            args.allow_cursor_control,
            args.default_key,
            color,
            args.host_tags,
        )
    )


if __name__ == "__main__":
    run_cli()
