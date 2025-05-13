#!/usr/bin/env python
"""
Ananta: a command-line tool that allows users to execute commands on multiple
remote hosts at once via SSH. With Ananta, you can streamline your workflow,
automate repetitive tasks, and save time and effort.
"""

from . import __version__

from .config import get_hosts
from .output import print_output
from .ssh import execute
from types import ModuleType
from typing import Dict
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


async def main(
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
    """Main function to execute commands on multiple remote hosts."""

    hosts_to_execute, max_name_length = get_hosts(host_file, host_tags)

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
    asyncio.ensure_future(asyncio.gather(*print_tasks))

    # Create a task for each host to execute the SSH command
    tasks = [
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
            output_queues[host_name],
            color,
        )
        for host_name, ip_address, ssh_port, username, key_path in hosts_to_execute
    ]

    # Execute all tasks concurrently
    await asyncio.gather(*tasks)

    # Put None in each host's output queue to signal the end of printing
    for host_name in output_queues:
        await output_queues[host_name].put(None)


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
        "-n",
        "-N",
        "--no-color",
        action="store_true",
        help="Disable host coloring",
    )
    parser.add_argument(
        "-s",
        "-S",
        "--separate-output",
        action="store_true",
        help="Print output from each host without interleaving",
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
        help="Set terminal width",
    )
    parser.add_argument(
        "-e",
        "-E",
        "--allow-empty-line",
        action="store_true",
        help="Allow printing the empty line",
    )
    parser.add_argument(
        "-c",
        "-C",
        "--allow-cursor-control",
        action="store_true",
        help=(
            "Allow cursor control codes (useful for commands like fastfetch "
            "or neofetch that rely on cursor positioning for layout)"
        ),
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
        asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())
    if args.version:
        # Print the version of Ananta with the asyncio event loop module
        print(
            f"Ananta-{__version__} "
            f"powered by {asyncio.get_event_loop_policy().__module__}"
        )
        sys.exit(0)
    host_file: str | None = args.host_file
    ssh_command: str = " ".join(args.command)
    if (host_file is None) or (not ssh_command.strip()):
        parser.print_help()  # Print help message if no arguments are provided
        sys.exit(0)
    try:
        local_display_width: int = args.terminal_width or int(
            os.environ.get("COLUMNS", os.get_terminal_size().columns)
        )  # Try to get terminal width as best as possible
    except OSError:
        # If unable to get terminal size, default to 80
        local_display_width = args.terminal_width or 80  # type: ignore
    color = not args.no_color
    asyncio.run(
        main(
            host_file,
            ssh_command,
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
