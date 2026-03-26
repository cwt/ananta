import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import asyncssh
import pytest

from ananta.ssh import execute, execute_command, stream_command_output

# Mark all tests in this file as asyncio tests
pytestmark = pytest.mark.asyncio


async def test_execute_command_success_bytes():
    """Test execute_command with successful execution returning bytes."""
    mock_conn = AsyncMock()
    mock_result = MagicMock()
    mock_result.stdout = b"some byte output"
    mock_conn.run.return_value = mock_result

    output = await execute_command(mock_conn, "a command", 80, True)

    assert output == "some byte output"
    mock_conn.run.assert_awaited_once()
    # Connection close is now handled by execute(), not execute_command()
    mock_conn.close.assert_not_called()


async def test_execute_command_success_str():
    """Test execute_command with successful execution returning a string."""
    mock_conn = AsyncMock()
    mock_result = MagicMock()
    mock_result.stdout = "some string output"
    mock_conn.run.return_value = mock_result

    output = await execute_command(mock_conn, "a command", 80, False)

    assert output == "some string output"
    mock_conn.run.assert_awaited_once()
    # Connection close is now handled by execute(), not execute_command()
    mock_conn.close.assert_not_called()


async def test_execute_command_unsupported_type():
    """Test execute_command with an unsupported stdout type."""
    mock_conn = AsyncMock()
    mock_result = MagicMock()
    mock_result.stdout = 12345  # Unsupported type
    mock_conn.run.return_value = mock_result

    output = await execute_command(mock_conn, "a command", 80, True)

    assert "unprintable output, got int" in output
    mock_conn.run.assert_awaited_once()
    # Connection close is now handled by execute(), not execute_command()
    mock_conn.close.assert_not_called()


async def test_execute_command_unicode_decode_error():
    """Test execute_command handling a UnicodeDecodeError."""
    mock_conn = AsyncMock()
    mock_result = MagicMock()
    mock_result.stdout = b"\x80abc"  # Invalid UTF-8 byte
    mock_conn.run.return_value = mock_result

    output = await execute_command(mock_conn, "a command", 80, True)

    assert "cannot be decoded as UTF-8" in output
    mock_conn.run.assert_awaited_once()
    # Connection close is now handled by execute(), not execute_command()
    mock_conn.close.assert_not_called()


async def test_execute_command_asyncssh_error():
    """Test execute_command handling an asyncssh.Error."""
    mock_conn = AsyncMock()
    mock_conn.run.side_effect = asyncssh.Error(code=1, reason="Command failed")

    output = await execute_command(mock_conn, "a command", 80, True)

    assert "Error executing command: Command failed" in output
    mock_conn.run.assert_awaited_once()
    # Connection close is now handled by execute(), not execute_command()
    mock_conn.close.assert_not_called()


async def test_stream_command_output_success():
    """Test stream_command_output with successful streaming."""
    mock_conn = AsyncMock()
    mock_process = AsyncMock()
    mock_process.terminate = MagicMock()  # Not async anymore
    mock_process.wait = AsyncMock()
    mock_process.__aenter__.return_value = mock_process

    async def async_iterator():
        yield b"line 1"
        yield "line 2"
        yield 123  # Invalid type

    mock_process.stdout = async_iterator()
    mock_conn.create_process.return_value = mock_process
    output_queue = AsyncMock(spec=asyncio.Queue)

    await stream_command_output(mock_conn, "a command", 80, output_queue, True)

    assert output_queue.put.call_count == 3
    output_queue.put.assert_any_await("line 1")
    output_queue.put.assert_any_await("line 2")
    output_queue.put.assert_any_await("Host returns unprintable line: 123")

    # Verify that terminate and wait were called
    mock_process.terminate.assert_called_once()
    mock_process.wait.assert_awaited_once()


async def test_stream_command_output_unicode_error():
    """Test stream_command_output with a UnicodeDecodeError."""
    mock_conn = AsyncMock()
    mock_process = AsyncMock()
    mock_process.terminate = MagicMock()  # Not async anymore
    mock_process.wait = AsyncMock()
    mock_process.__aenter__.return_value = mock_process

    async def async_iterator():
        yield b"\x80invalid"

    mock_process.stdout = async_iterator()
    mock_conn.create_process.return_value = mock_process
    output_queue = AsyncMock(spec=asyncio.Queue)

    await stream_command_output(mock_conn, "a command", 80, output_queue, True)

    output_queue.put.assert_awaited_once()
    assert "cannot be decoded" in output_queue.put.await_args.args[0]

    # Verify that terminate and wait were called
    mock_process.terminate.assert_called_once()
    mock_process.wait.assert_awaited_once()


async def test_stream_command_output_asyncssh_error():
    """Test stream_command_output handling an asyncssh.Error."""
    mock_conn = AsyncMock()
    mock_conn.create_process.side_effect = asyncssh.Error(
        code=1, reason="Stream failed"
    )
    output_queue = AsyncMock(spec=asyncio.Queue)

    await stream_command_output(mock_conn, "a command", 80, output_queue, True)

    output_queue.put.assert_awaited_once_with(
        "Error executing command: Stream failed"
    )


@patch("ananta.ssh.establish_ssh_connection", new_callable=AsyncMock)
async def test_execute_connection_error(mock_establish_conn):
    """Test execute handling a ConnectionError."""
    mock_establish_conn.side_effect = ConnectionError("Failed to connect")
    output_queue = AsyncMock(spec=asyncio.Queue)

    await execute(
        "host1",
        "1.1.1.1",
        22,
        "user",
        None,
        "cmd",
        10,
        80,
        False,
        None,
        output_queue,
        True,
        5.0,
        2,
    )

    output_queue.put.assert_any_await(
        "Error connecting to host1: Failed to connect"
    )


@patch("ananta.ssh.establish_ssh_connection", new_callable=AsyncMock)
async def test_execute_runtime_error(mock_establish_conn):
    """Test execute handling a RuntimeError."""
    # This is a bit tricky to trigger naturally, so we'll mock a later call to raise it.
    mock_conn = AsyncMock()
    mock_conn.is_closed = MagicMock(return_value=False)
    mock_conn.close = MagicMock()
    mock_establish_conn.return_value = mock_conn
    with patch(
        "ananta.ssh.stream_command_output", new_callable=AsyncMock
    ) as mock_stream:
        mock_stream.side_effect = RuntimeError("Something went wrong")
        output_queue = AsyncMock(spec=asyncio.Queue)

        await execute(
            "host1",
            "1.1.1.1",
            22,
            "user",
            None,
            "cmd",
            10,
            80,
            False,
            None,
            output_queue,
            True,
            5.0,
            2,
        )

        # The error from stream_command_output is caught inside stream_command_output and put on the queue.
        # The RuntimeError in the 'execute' function's except block is harder to hit.
        # Let's adjust the test to trigger the RuntimeError in the `execute` function's `except` block.
        mock_establish_conn.side_effect = RuntimeError("Forced runtime error")
        await execute(
            "host1",
            "1.1.1.1",
            22,
            "user",
            None,
            "cmd",
            10,
            80,
            False,
            None,
            output_queue,
            True,
            5.0,
            2,
        )
        output_queue.put.assert_any_await(
            "Error executing command on host1: Forced runtime error"
        )


@patch("ananta.ssh.establish_ssh_connection", new_callable=AsyncMock)
async def test_execute_closes_connection_separate_output(mock_establish_conn):
    """Test that execute properly closes the connection in separate output mode."""

    mock_conn = AsyncMock()
    # is_closed() is a regular method in asyncssh, not async
    mock_conn.is_closed = MagicMock(return_value=False)
    # close() is also a regular method in asyncssh
    mock_conn.close = MagicMock()
    mock_conn.wait_closed = AsyncMock()
    mock_establish_conn.return_value = mock_conn

    with patch(
        "ananta.ssh.execute_command", new_callable=AsyncMock
    ) as mock_exec_cmd:
        mock_exec_cmd.return_value = "command output"
        output_queue = AsyncMock(spec=asyncio.Queue)

        await execute(
            "host1",
            "1.1.1.1",
            22,
            "user",
            None,
            "cmd",
            10,
            80,
            True,  # separate_output
            None,
            output_queue,
            True,
            5.0,
            2,
        )

        # Verify connection was closed
        mock_conn.close.assert_called_once()
        mock_conn.wait_closed.assert_awaited_once()


@patch("ananta.ssh.establish_ssh_connection", new_callable=AsyncMock)
async def test_execute_closes_connection_streaming(mock_establish_conn):
    """Test that execute properly closes the connection in streaming mode."""
    mock_conn = AsyncMock()
    mock_conn.is_closed = MagicMock(return_value=False)
    mock_conn.close = MagicMock()
    mock_conn.wait_closed = AsyncMock()
    mock_establish_conn.return_value = mock_conn

    with patch("ananta.ssh.stream_command_output", new_callable=AsyncMock):
        output_queue = AsyncMock(spec=asyncio.Queue)

        await execute(
            "host1",
            "1.1.1.1",
            22,
            "user",
            None,
            "cmd",
            10,
            80,
            False,  # streaming mode
            None,
            output_queue,
            True,
            5.0,
            2,
        )

        # Verify connection was closed
        mock_conn.close.assert_called_once()
        mock_conn.wait_closed.assert_awaited_once()


@patch("ananta.ssh.establish_ssh_connection", new_callable=AsyncMock)
async def test_execute_handles_connection_close_timeout(mock_establish_conn):
    """Test that execute handles connection close timeout gracefully."""
    mock_conn = AsyncMock()
    mock_conn.is_closed = MagicMock(return_value=False)
    mock_conn.close = MagicMock()
    mock_conn.wait_closed = AsyncMock(side_effect=asyncio.TimeoutError())
    mock_establish_conn.return_value = mock_conn

    with patch(
        "ananta.ssh.execute_command", new_callable=AsyncMock
    ) as mock_exec_cmd:
        mock_exec_cmd.return_value = "command output"
        output_queue = AsyncMock(spec=asyncio.Queue)

        # Should not raise, should handle timeout gracefully
        await execute(
            "host1",
            "1.1.1.1",
            22,
            "user",
            None,
            "cmd",
            10,
            80,
            True,
            None,
            output_queue,
            True,
            5.0,
            2,
        )

        # Verify connection close was attempted
        mock_conn.close.assert_called_once()
        mock_conn.wait_closed.assert_awaited_once()


@patch("ananta.ssh.establish_ssh_connection", new_callable=AsyncMock)
async def test_execute_skips_close_if_already_closed(mock_establish_conn):
    """Test that execute skips closing if connection is already closed."""
    mock_conn = AsyncMock()
    mock_conn.is_closed = MagicMock(return_value=True)  # Already closed
    # close() should not be called if already closed
    mock_conn.close = MagicMock()
    mock_establish_conn.return_value = mock_conn

    with patch(
        "ananta.ssh.execute_command", new_callable=AsyncMock
    ) as mock_exec_cmd:
        mock_exec_cmd.return_value = "command output"
        output_queue = AsyncMock(spec=asyncio.Queue)

        await execute(
            "host1",
            "1.1.1.1",
            22,
            "user",
            None,
            "cmd",
            10,
            80,
            True,
            None,
            output_queue,
            True,
            5.0,
            2,
        )

        # Verify connection close was NOT called (already closed)
        mock_conn.close.assert_not_called()
