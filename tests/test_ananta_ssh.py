import asyncio
from unittest.mock import AsyncMock

import pytest

from ananta.ssh import stream_command_output

# Mark all tests in this file as asyncio tests
pytestmark = pytest.mark.asyncio


class MockSSHProcess:
    def __init__(self, stdout_chunks):
        self.stdout = self._async_iterator(stdout_chunks)
        self.terminate_called = False
        self.wait_called = False

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        pass

    def terminate(self):  # Not async anymore
        self.terminate_called = True

    async def wait(self):
        self.wait_called = True

    @staticmethod
    async def _async_iterator(chunks):
        for chunk in chunks:
            yield chunk


@pytest.mark.asyncio
async def test_stream_command_output_various_chunks():
    """Test stream_command_output with various output chunks."""
    # 1. Setup
    mock_conn = AsyncMock()
    output_chunks = [
        b"some bytes",
        "a string",
        b"\x80invalid utf-8",
        "another string",
        12345,  # Invalid type
    ]
    mock_process = MockSSHProcess(output_chunks)
    mock_conn.create_process.return_value = mock_process
    output_queue = asyncio.Queue()

    # 2. Execute
    await stream_command_output(mock_conn, "a command", 80, output_queue, True)

    # 3. Assert
    results = []
    while not output_queue.empty():
        results.append(await output_queue.get())

    assert "some bytes" in results
    assert "a string" in results
    assert (
        "Host returns line with bytes that cannot be decoded: 'utf-8' codec can't decode byte 0x80 in position 0: invalid start byte"
        in results
    )
    assert "another string" in results
    assert "Host returns unprintable line: 12345" in results
    assert len(results) == 5


@pytest.mark.asyncio
async def test_execute_clamps_remote_width_to_minimum():
    """Regression: narrow terminals with long host names must not produce a
    non-positive remote width (which was interpolated into the remote env)."""
    from unittest.mock import AsyncMock, patch

    from ananta.ssh import execute

    mock_conn = AsyncMock()
    output_queue = asyncio.Queue()

    with (
        patch(
            "ananta.ssh.establish_ssh_connection",
            new_callable=AsyncMock,
            return_value=mock_conn,
        ),
        patch(
            "ananta.ssh.stream_command_output", new_callable=AsyncMock
        ) as mock_stream,
        patch("ananta.ssh._close_ssh_connection", new_callable=AsyncMock),
    ):
        # local width 12 - max name length 5 - 3 = 4, which must be clamped to 10.
        await execute(
            "hostname-with-long-name",
            "192.0.2.1",
            22,
            "user",
            "/key",
            "uptime",
            5,
            12,
            False,
            None,
            output_queue,
            True,
            5.0,
            2,
        )

    # stream_command_output(conn, ssh_command, remote_width, queue, color)
    call_args = mock_stream.call_args.args
    remote_width = call_args[2]
    assert remote_width == 10


@pytest.mark.asyncio
async def test_stream_command_output_passes_width_in_env():
    """The remote command must carry the resolved width via COLUMNS."""
    mock_conn = AsyncMock()
    mock_process = MockSSHProcess([b"ok"])
    mock_conn.create_process.return_value = mock_process
    output_queue = asyncio.Queue()

    await stream_command_output(mock_conn, "uptime", 10, output_queue, True)

    _, kwargs = mock_conn.create_process.call_args
    assert "COLUMNS=10 LINES=1000 uptime" in kwargs["command"]
