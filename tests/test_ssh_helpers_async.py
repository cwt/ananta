from ananta.ssh import retry_connect
from unittest.mock import AsyncMock, patch
import asyncssh
import pytest


@pytest.mark.asyncio
async def test_retry_connect_success():
    with patch("ananta.ssh.asyncssh.connect", new=AsyncMock()) as mock_connect:
        mock_connect.return_value = AsyncMock(spec=asyncssh.SSHClientConnection)
        conn = await retry_connect(
            ip_address="10.0.0.1",
            ssh_port=22,
            username="user",
            client_keys=["/key"],
            timeout=0.1,
            max_retries=2
        )
        assert mock_connect.call_count == 1
        assert isinstance(conn, AsyncMock)
