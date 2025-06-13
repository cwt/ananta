from ananta.ssh import retry_connect
from unittest.mock import AsyncMock, patch
import asyncio
import asyncssh
import pytest

# Mark all tests in this file as asyncio tests
pytestmark = pytest.mark.asyncio


async def test_retry_connect_success():
    with patch("ananta.ssh.asyncssh.connect", new=AsyncMock()) as mock_connect:
        mock_connect.return_value = AsyncMock(spec=asyncssh.SSHClientConnection)
        conn = await retry_connect(
            ip_address="10.0.0.1",
            ssh_port=22,
            username="user",
            client_keys=["/key"],
            timeout=0.1,
            max_retries=2,
        )
        assert mock_connect.call_count == 1
        assert isinstance(conn, AsyncMock)


async def test_retry_connect_success_on_first_attempt():
    """Tests successful connection on the first attempt."""
    # Create an AsyncMock for asyncssh.connect
    with patch(
        "ananta.ssh.asyncssh.connect", new_callable=AsyncMock
    ) as mock_connect:
        # Configure the mock to return a successful connection object
        mock_connection_object = AsyncMock(spec=asyncssh.SSHClientConnection)
        mock_connect.return_value = mock_connection_object

        # Call the function under test
        conn = await retry_connect(
            ip_address="10.0.0.1",
            ssh_port=22,
            username="user",
            client_keys=["/key"],
            timeout=0.1,  # Short timeout for testing
            max_retries=2,
        )

        # Assertions
        mock_connect.assert_called_once()  # Should only be called once
        assert (
            conn == mock_connection_object
        )  # Ensure the connection object is returned


async def test_retry_connect_success_after_one_retry_timeout():
    """Tests successful connection after one retry due to TimeoutError."""
    with (
        patch(
            "ananta.ssh.asyncssh.connect", new_callable=AsyncMock
        ) as mock_connect,
        patch("ananta.ssh.asyncio.sleep", new_callable=AsyncMock) as mock_sleep,
    ):
        # Simulate a TimeoutError on the first call, then success
        mock_connection_object = AsyncMock(spec=asyncssh.SSHClientConnection)
        mock_connect.side_effect = [
            asyncio.TimeoutError("Simulated timeout"),
            mock_connection_object,
        ]

        conn = await retry_connect(
            ip_address="10.0.0.1",
            ssh_port=22,
            username="user",
            client_keys=["/key"],
            timeout=0.1,
            max_retries=2,
        )

        assert mock_connect.call_count == 2  # Called twice (initial + 1 retry)
        mock_sleep.assert_called_once_with(
            1
        )  # Ensure sleep was called between retries
        assert conn == mock_connection_object


async def test_retry_connect_fails_after_all_retries_timeout():
    """Tests connection failure after all retries due to consistent TimeoutError."""
    with (
        patch(
            "ananta.ssh.asyncssh.connect", new_callable=AsyncMock
        ) as mock_connect,
        patch("ananta.ssh.asyncio.sleep", new_callable=AsyncMock) as mock_sleep,
    ):
        # Simulate TimeoutError on all attempts
        max_retries = 2
        mock_connect.side_effect = [
            asyncio.TimeoutError("Simulated timeout")
            for _ in range(max_retries + 1)
        ]

        with pytest.raises(ConnectionError) as excinfo:
            await retry_connect(
                ip_address="10.0.0.1",
                ssh_port=22,
                username="user",
                client_keys=["/key"],
                timeout=0.1,
                max_retries=max_retries,
            )

        assert "timed out after 0.1s" in str(excinfo.value)
        assert mock_connect.call_count == max_retries + 1
        assert mock_sleep.call_count == max_retries  # Slept before each retry


async def test_retry_connect_fails_after_all_retries_ssh_error():
    """Tests connection failure after all retries due to consistent asyncssh.Error."""
    with (
        patch(
            "ananta.ssh.asyncssh.connect", new_callable=AsyncMock
        ) as mock_connect,
        patch("ananta.ssh.asyncio.sleep", new_callable=AsyncMock) as mock_sleep,
    ):
        # Simulate asyncssh.Error on all attempts
        max_retries = 3
        # Explicitly use keyword argument for 'reason'
        simulated_error = asyncssh.Error(
            code=1, reason="Persistent SSH failure"
        )
        mock_connect.side_effect = [
            simulated_error for _ in range(max_retries + 1)
        ]

        with pytest.raises(ConnectionError) as excinfo:
            await retry_connect(
                ip_address="10.0.0.1",
                ssh_port=22,
                username="user",
                client_keys=["/key"],
                timeout=0.1,
                max_retries=max_retries,
            )

        # The final error message should contain the last error raised by asyncssh.connect
        assert f"Error connecting to 10.0.0.1: {simulated_error}" in str(
            excinfo.value
        )
        assert mock_connect.call_count == max_retries + 1
        assert mock_sleep.call_count == max_retries


async def test_retry_connect_key_exchange_failure_then_fails_again():
    """Tests key exchange failure, retry with different algos, then another failure."""
    with (
        patch(
            "ananta.ssh.asyncssh.connect", new_callable=AsyncMock
        ) as mock_connect,
        patch("ananta.ssh.asyncio.sleep", new_callable=AsyncMock) as mock_sleep,
    ):
        # Simulate key exchange failure, then another generic error
        key_exchange_error = asyncssh.Error(
            code=asyncssh.DISC_KEY_EXCHANGE_FAILED, reason="Key exchange failed"
        )

        final_error = asyncssh.Error(
            code=1, reason="Another SSH error after key exchange retry"
        )

        mock_connect.side_effect = [
            key_exchange_error,
            final_error,  # Error on the retry attempt
        ]

        max_retries = 1  # Allow for one retry after the key exchange failure

        with pytest.raises(ConnectionError) as excinfo:
            await retry_connect(
                ip_address="10.0.0.1",
                ssh_port=22,
                username="user",
                client_keys=["/key"],
                timeout=0.1,
                max_retries=max_retries,
            )

        assert f"Error connecting to 10.0.0.1: {final_error}" in str(
            excinfo.value
        )
        assert mock_connect.call_count == 2  # Initial attempt + 1 retry

        # fmt: off
        # Check algorithm options were changed
        # First call uses specific algorithms
        first_call_args, first_call_kwargs = mock_connect.call_args_list[0]  # noqa
        assert "aes128-gcm@openssh.com" in first_call_kwargs.get(
            "encryption_algs", []
        )

        # Second call should have empty algorithm options (to use all available)
        second_call_args, second_call_kwargs = mock_connect.call_args_list[1]  # noqa
        # fmt: on
        assert (
            "encryption_algs" not in second_call_kwargs
        )  # or second_call_kwargs.get("encryption_algs") is None
        assert (
            "mac_algs" not in second_call_kwargs
        )  # or second_call_kwargs.get("mac_algs") is None

        # Sleep should have been called with 0 for key exchange error, then 1 for the next error if it retried again
        # In this case, it fails on the second attempt, so only one sleep for the key exchange error.
        mock_sleep.assert_called_once_with(
            0
        )  # Sleep 0 after key exchange failure


async def test_retry_connect_key_exchange_failure_then_success():
    """Tests key exchange failure, then success on retry with different algos."""
    with (
        patch(
            "ananta.ssh.asyncssh.connect", new_callable=AsyncMock
        ) as mock_connect,
        patch("ananta.ssh.asyncio.sleep", new_callable=AsyncMock) as mock_sleep,
    ):

        key_exchange_error = asyncssh.Error(
            code=asyncssh.DISC_KEY_EXCHANGE_FAILED, reason="Key exchange failed"
        )

        mock_successful_connection = AsyncMock(
            spec=asyncssh.SSHClientConnection
        )

        mock_connect.side_effect = [
            key_exchange_error,
            mock_successful_connection,
        ]

        max_retries = 1

        conn = await retry_connect(
            ip_address="10.0.0.1",
            ssh_port=22,
            username="user",
            client_keys=["/key"],
            timeout=0.1,
            max_retries=max_retries,
        )

        assert conn == mock_successful_connection
        assert mock_connect.call_count == 2
        mock_sleep.assert_called_once_with(
            0
        )  # Sleep 0 after key exchange failure

        first_call_kwargs = mock_connect.call_args_list[0].kwargs
        assert "encryption_algs" in first_call_kwargs
        second_call_kwargs = mock_connect.call_args_list[1].kwargs
        assert "encryption_algs" not in second_call_kwargs


async def test_retry_connect_no_retries_on_success():
    """Tests that no retries occur if the first connection attempt is successful (max_retries=0)."""
    with patch(
        "ananta.ssh.asyncssh.connect", new_callable=AsyncMock
    ) as mock_connect:
        mock_connection_object = AsyncMock(spec=asyncssh.SSHClientConnection)
        mock_connect.return_value = mock_connection_object

        conn = await retry_connect(
            ip_address="10.0.0.1",
            ssh_port=22,
            username="user",
            client_keys=["/key"],
            timeout=0.1,
            max_retries=0,  # No retries allowed
        )
        assert mock_connect.call_count == 1
        assert conn == mock_connection_object


async def test_retry_connect_fails_immediately_if_no_retries_allowed_timeout():
    """Tests immediate failure with TimeoutError if max_retries is 0."""
    with patch(
        "ananta.ssh.asyncssh.connect", new_callable=AsyncMock
    ) as mock_connect:
        mock_connect.side_effect = asyncio.TimeoutError("Simulated timeout")

        with pytest.raises(ConnectionError) as excinfo:
            await retry_connect(
                ip_address="10.0.0.1",
                ssh_port=22,
                username="user",
                client_keys=["/key"],
                timeout=0.1,
                max_retries=0,
            )
        assert "timed out after 0.1s" in str(excinfo.value)
        assert mock_connect.call_count == 1


async def test_retry_connect_fails_immediately_if_no_retries_allowed_ssh_error():
    """Tests immediate failure with asyncssh.Error if max_retries is 0."""
    with patch(
        "ananta.ssh.asyncssh.connect", new_callable=AsyncMock
    ) as mock_connect:
        simulated_error = asyncssh.Error(
            code=1, reason="Simulated SSH error"
        )  # Added code
        mock_connect.side_effect = simulated_error

        with pytest.raises(ConnectionError) as excinfo:
            await retry_connect(
                ip_address="10.0.0.1",
                ssh_port=22,
                username="user",
                client_keys=["/key"],
                timeout=0.1,
                max_retries=0,
            )
        assert f"Error connecting to 10.0.0.1: {simulated_error}" in str(
            excinfo.value
        )
        assert mock_connect.call_count == 1
