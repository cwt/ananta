from ananta.ssh import stream_command_output
from unittest.mock import AsyncMock, MagicMock
import asyncio
import pytest

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
