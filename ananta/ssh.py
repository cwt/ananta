from . import LINES
from ananta.output import get_end_marker
import asyncio
import asyncssh
import os


async def retry_connect(
    ip_address: str,
    ssh_port: int,
    username: str,
    client_keys: list[str],
    timeout: float,
    max_retries: int,
) -> asyncssh.SSHClientConnection:
    """Attempt to establish an SSH connection with retries."""
    last_error: asyncssh.Error | asyncio.TimeoutError | None = None
    algorithm_options = {
        "encryption_algs": [
            "aes128-gcm@openssh.com",
            "aes256-gcm@openssh.com",
            "chacha20-poly1305@openssh.com",
            "aes128-ctr",
            "aes256-ctr",
        ],
        "mac_algs": ["hmac-sha2-256", "hmac-sha1"],
    }  # try with the lowest latency algorithm first
    for attempt in range(max_retries + 1):
        try:
            return await asyncio.wait_for(
                asyncssh.connect(
                    host=ip_address,
                    port=ssh_port,
                    username=username,
                    client_keys=client_keys,
                    known_hosts=None,
                    compression_algs=None,
                    **algorithm_options,
                ),
                timeout=timeout,
            )
        except asyncssh.Error as error:
            last_error = error
            _sleep = 1
            if (
                getattr(error, "code", None)
                == asyncssh.DISC_KEY_EXCHANGE_FAILED
            ):
                algorithm_options = {}  # try again with all available algorithm
                _sleep = 0  # no need to sleep as this is an error on our side
            if attempt < max_retries:
                await asyncio.sleep(_sleep)
        except asyncio.TimeoutError as error:
            last_error = error
            if attempt < max_retries:
                await asyncio.sleep(1)
    if isinstance(last_error, asyncio.TimeoutError):
        raise ConnectionError(
            f"Connection to {ip_address} timed out after {timeout}s"
        )
    raise ConnectionError(f"Error connecting to {ip_address}: {last_error}")


def get_ssh_keys(key_path: str | None, default_key: str | None) -> list[str]:
    """Determine SSH keys to use based on provided inputs."""
    # If key path is specified in the hosts file
    if key_path and key_path != "#":
        return [key_path]
    # If key path is # (not specified) and default key is specified via -K
    if default_key:
        return [default_key]
    # If key path is # (not specified) and default key is also not specified via -K
    common_ssh_dir = os.path.expanduser("~/.ssh")
    common_keys = [
        os.path.join(common_ssh_dir, key)
        for key in ["id_ed25519", "id_rsa", "id_ecdsa", "id_dsa"]
    ]
    # Try to find the available ssh key
    available_keys = [key for key in common_keys if os.path.exists(key)]
    if not available_keys:
        raise ConnectionError(
            "No SSH keys found in ~/.ssh/ and no key specified"
        )
    return available_keys


async def establish_ssh_connection(
    ip_address: str,
    ssh_port: int,
    username: str,
    key_path: str | None,
    default_key: str | None,
    timeout: float = 5.0,
    max_retries: int = 2,
) -> asyncssh.SSHClientConnection:
    """Establish an SSH connection to the remote host."""
    try:
        client_keys = get_ssh_keys(key_path, default_key)
        return await retry_connect(
            ip_address, ssh_port, username, client_keys, timeout, max_retries
        )
    except Exception as error:
        raise ConnectionError(f"Error connecting to {ip_address}: {error}")


async def execute_command(
    conn: asyncssh.SSHClientConnection,
    ssh_command: str,
    remote_width: int,
    color: bool,
) -> str:
    """Execute the given command on the remote host through the SSH connection."""
    try:
        result = await conn.run(
            command=f"env COLUMNS={remote_width} LINES={LINES} {ssh_command}",
            term_type="ansi" if color else "dumb",
            term_size=(remote_width, LINES),
            env={},
        )
        if isinstance(result.stdout, bytes):
            return result.stdout.decode("utf-8")
        elif isinstance(result.stdout, str):
            return result.stdout
        else:
            return f"Host returns unprintable output, got {type(result.stdout).__name__}"
    except UnicodeDecodeError as error:
        return "Host returns bytes that cannot be decoded as UTF-8"
    except asyncssh.Error as error:
        return f"Error executing command: {error}"
    finally:
        conn.close()


async def stream_command_output(
    conn: asyncssh.SSHClientConnection,
    ssh_command: str,
    remote_width: int,
    output_queue: asyncio.Queue[str | None],
    color: bool,
) -> None:
    """Stream the output of the command from the remote host to the output queue."""
    try:
        async with conn.create_process(
            command=f"env COLUMNS={remote_width} LINES={LINES} {ssh_command}",
            term_type="ansi" if color else "dumb",
            term_size=(remote_width, 1000),
            env={},
        ) as process:  # type: asyncssh.SSHClientProcess
            async for line in process.stdout:  # type: bytes | str
                # Put output into the host's output queue
                if isinstance(line, bytes):
                    try:
                        await output_queue.put(line.decode("utf-8"))
                    except UnicodeDecodeError as error:
                        await output_queue.put(
                            f"Host returns line with bytes that cannot be decoded: {error}"
                        )
                elif isinstance(line, str):
                    await output_queue.put(line)
                else:
                    await output_queue.put(
                        f"Host returns unprintable line: {repr(line)}"
                    )
    except asyncssh.Error as error:
        await output_queue.put(f"Error executing command: {error}")


async def execute(
    host_name: str,
    ip_address: str,
    ssh_port: int,
    username: str,
    key_path: str | None,
    ssh_command: str,
    max_name_length: int,
    local_display_width: int,
    separate_output: bool,
    default_key: str | None,
    output_queue: asyncio.Queue,
    color: bool,
) -> None:
    """Execute the SSH command on the remote host and handle the output."""
    remote_width = local_display_width - max_name_length - 3

    try:
        conn = await establish_ssh_connection(
            ip_address, ssh_port, username, key_path, default_key
        )
        if separate_output:
            output = await execute_command(
                conn, ssh_command, remote_width, color
            )
            # Put output into the host's output queue
            await output_queue.put(output)
        else:
            await stream_command_output(
                conn, ssh_command, remote_width, output_queue, color
            )
    except ConnectionError as error:
        await output_queue.put(f"Error connecting to {host_name}: {error}")
    except RuntimeError as error:
        await output_queue.put(
            f"Error executing command on {host_name}: {error}"
        )
    finally:
        # Signal end of output once, regardless of success or failure
        await output_queue.put(get_end_marker(host_name, remote_width, color))
