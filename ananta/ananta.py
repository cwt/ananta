#!/usr/bin/env python
"""
Ananta: a command-line tool that allows users to execute commands on multiple
remote hosts at once via SSH. With Ananta, you can streamline your workflow,
automate repetitive tasks, and save time and effort.
"""

import argparse
import asyncio
import os
import sys
from types import ModuleType

import asyncssh

from . import __version__
from .config import get_hosts
from .host_keys import HostKeyPolicy, MismatchRecord, _host_entry_name
from .output import print_output  # Used by non-TUI mode
from .ssh import (  # Used by non-TUI mode
    _close_ssh_connection,
    establish_ssh_connection,
    execute,
    get_end_marker,
)

uvloop: ModuleType | None = None
try:
    import warnings

    with warnings.catch_warnings():
        warnings.simplefilter(
            "ignore",
            category=DeprecationWarning,
        )
        if sys.platform == "win32":
            import winloop as uvloop
        else:
            import uvloop
except ImportError:
    pass  # uvloop or winloop is an optional for speedup, not a requirement


def _create_policy(override: bool = False) -> HostKeyPolicy:
    """Build the session-wide host-key policy (seam for testing)."""
    return HostKeyPolicy(override=override)


async def _open_connection(
    host_details: tuple,
    default_key: str | None,
    output_queue: asyncio.Queue[str | None],
    color: bool,
    local_display_width: int,
    max_name_length: int,
    policy: HostKeyPolicy,
) -> asyncssh.SSHClientConnection | None:
    """Pre-flight worker: connect to one host and verify its host key.

    Returns the established connection, or None after reporting the failure
    through the host's own output queue (down/unreachable/auth failures do
    not block the rest of the batch).
    """
    host_name, ip_address, ssh_port, username, key_path, timeout, retries = (
        host_details
    )
    try:
        return await establish_ssh_connection(
            ip_address,
            ssh_port,
            username,
            key_path,
            default_key,
            timeout,
            retries,
            policy,
        )
    except Exception as error:
        await output_queue.put(f"Error connecting to {host_name}: {error}")
        return None


def _print_mismatch_report(mismatches: list[MismatchRecord]) -> None:
    """Loudly report host-key mismatches; no commands have run yet."""
    print(
        "\n!! HOST KEY MISMATCH DETECTED - batch aborted, no commands executed."
    )
    for record in mismatches:
        print(
            f"  {record.entry}: recorded {record.old_fingerprint} / "
            f"presented {record.new_fingerprint}"
        )
    print(
        "\nThis may indicate a server rebuild or a man-in-the-middle attack.\n"
        "Verify out-of-band (console access, colleague, change ticket), then:\n"
        "  - fix or remove the affected hosts from your inventory and re-run, or\n"
        "  - re-run with --override-mismatched-keys to accept the new keys."
    )


def _confirm_override() -> bool:
    """Ask once per session for an explicit all-caps CONFIRM."""
    print(
        "Type CONFIRM (all capitals) to replace the recorded keys and "
        "continue this session:"
    )
    try:
        answer = input("> ")
    except EOFError:
        answer = ""
    if answer.strip() == "CONFIRM":
        return True
    print("Override not confirmed.")
    return False


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
    override_mismatched_keys: bool = False,
) -> None:
    """Main function to execute commands on multiple remote hosts (non-TUI mode).

    Runs in two phases:

      1. Pre-flight: connect to and verify the host key of every host.
         Any host-key mismatch aborts the batch before a single command runs.
      2. Dispatch: stream the command to every connected host.
    """
    hosts_to_execute, max_name_length = get_hosts(host_file, host_tags)

    if not hosts_to_execute:
        print("No hosts found to execute the command on.")
        return

    # Dictionary to hold separate output queues for each host
    output_queues: dict[str, asyncio.Queue[str | None]] = {
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
    printing_task_group = asyncio.gather(*print_tasks)

    policy = _create_policy(
        override=override_mismatched_keys,
    )

    # ---- Phase 1: pre-flight connect + host-key verification -------------
    connect_results = await asyncio.gather(
        *[
            _open_connection(
                host_details,
                default_key,
                output_queues[host_details[0]],
                color,
                local_display_width,
                max_name_length,
                policy,
            )
            for host_details in hosts_to_execute
        ],
        return_exceptions=True,
    )
    connections = {
        host[0]: result
        for host, result in zip(hosts_to_execute, connect_results)
        if result is not None and not isinstance(result, BaseException)
    }

    # Report hosts that could not be connected (down/unreachable/auth).
    for host_details, result in zip(hosts_to_execute, connect_results):
        if isinstance(result, BaseException) or result is None:
            error_text = (
                str(result)
                if isinstance(result, BaseException)
                else "connection failed"
            )
            await output_queues[host_details[0]].put(
                f"Error connecting to {host_details[0]}: {error_text}"
            )

    # Any host-key mismatch stops the whole batch right here.
    if policy.mismatches:
        _print_mismatch_report(policy.mismatches)
        proceed = False
        if override_mismatched_keys and _confirm_override():
            overridden_entries = {m.entry for m in policy.mismatches}
            policy.apply_overrides()

            # Reconnect only the hosts whose keys were just re-trusted.
            retry_hosts = [
                h
                for h in hosts_to_execute
                if _host_entry_name(h[1], h[2]) in overridden_entries
            ]
            retry_results = await asyncio.gather(
                *[
                    _open_connection(
                        host_details,
                        default_key,
                        output_queues[host_details[0]],
                        color,
                        local_display_width,
                        max_name_length,
                        policy,
                    )
                    for host_details in retry_hosts
                ],
                return_exceptions=True,
            )
            for host_details, result in zip(retry_hosts, retry_results):
                if isinstance(result, asyncssh.SSHClientConnection):
                    connections[host_details[0]] = result
            proceed = True
        if not proceed:
            # Abort before a single command runs; exit code 3 marks a
            # security abort so scripts can distinguish it. Every host —
            # connected or not — gets its queue drained with an abort line.
            remote_width = max(local_display_width - max_name_length - 3, 10)
            for conn in connections.values():
                await _close_ssh_connection(conn)
            for host_name, output_queue in output_queues.items():
                await output_queue.put(
                    "Aborted: batch not executed due to host key mismatch"
                )
                await output_queue.put(
                    get_end_marker(host_name, remote_width, color)
                )
                await output_queue.put(None)
            await printing_task_group
            sys.exit(3)

    # ---- Phase 2: dispatch the command to every connected host ------------

    # Create a task for each connected host to execute the SSH command
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
            timeout,
            retries,
            conn=connections.get(host_name),
        )
        for host_name, ip_address, ssh_port, username, key_path, timeout, retries in hosts_to_execute
    ]

    # Execute all command execution tasks concurrently
    try:
        await asyncio.gather(*exec_tasks)
    finally:
        # Signal end of output even if a task failed, so print tasks never hang.
        for host_name in output_queues:
            await output_queues[host_name].put(None)

        # Wait for all printing tasks to complete (they exit on the sentinel)
        await printing_task_group

    # Post-session report of keys trusted on first use.
    if policy.added_keys:
        print(
            f"Added {len(policy.added_keys)} new host key(s) to "
            f"{policy.path}:"
        )
        for entry, fingerprint in policy.added_keys:
            print(f"  - {entry} ({fingerprint})")


def _get_loop_module_name() -> str:
    """Return the module name of a freshly created event loop (uvloop if available)."""
    module: ModuleType = uvloop if uvloop else asyncio
    temp_loop = module.new_event_loop()
    try:
        return temp_loop.__class__.__module__
    finally:
        temp_loop.close()


def _resolve_display_width(terminal_width_arg: int | None) -> int:
    """Resolve display width from CLI arg, COLUMNS env var, or terminal size.

    An invalid COLUMNS value falls back to terminal size detection rather
    than skipping it.
    """
    if terminal_width_arg:
        return terminal_width_arg

    columns_env = os.environ.get("COLUMNS")
    if columns_env:
        try:
            return int(columns_env)
        except ValueError:
            pass  # Invalid COLUMNS; fall through to terminal size detection

    try:
        return os.get_terminal_size().columns
    except OSError:
        return 80


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
        "--tui-light",
        action="store_true",
        help="Launch the Urwid-based Text User Interface (TUI) mode with light theme for light terminal backgrounds.",
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
    parser.add_argument(
        "--override-mismatched-keys",
        action="store_true",
        help=(
            "Allow replacing recorded host keys after a mismatch, following "
            "a one-time explicit CONFIRM prompt"
        ),
    )
    args: argparse.Namespace = parser.parse_args()

    if uvloop and not (args.tui or args.tui_light):
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
        loop_module = _get_loop_module_name()
        print(f"Ananta-{__version__} " f"powered by {loop_module}")
        sys.exit(0)

    host_file: str | None = args.host_file
    ssh_command_list: list[str] = (
        args.command
    )  # Keep as list for TUI initial command
    ssh_command_str: str = " ".join(ssh_command_list)

    if not host_file:
        parser.print_help()
        sys.exit(0)

    if args.tui or args.tui_light:
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
            light_theme=args.tui_light,
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

    local_display_width: int = _resolve_display_width(args.terminal_width)

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
            override_mismatched_keys=args.override_mismatched_keys,
        )
    )


if __name__ == "__main__":
    run_cli()
