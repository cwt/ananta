from ananta.ananta import main
from ananta.ananta import run_cli
from unittest.mock import patch, AsyncMock, MagicMock
import pytest
import unittest

# Mark all tests in this file as asyncio tests
pytestmark = pytest.mark.asyncio


@pytest.fixture
def mock_args():
    return MagicMock(
        host_file="hosts.csv",
        command=["uptime"],
        no_color=False,
        separate_output=False,
        host_tags=None,
        terminal_width=None,
        allow_empty_line=False,
        allow_cursor_control=False,
        version=False,
        default_key=None,
    )


@pytest.mark.asyncio
async def test_main_empty_hosts(tmp_path):
    p = tmp_path / "hosts.csv"
    p.write_text("", encoding="utf-8")
    with patch("ananta.ananta.get_hosts", return_value=([], 0)):
        await main(
            str(p),
            "uptime",
            local_display_width=80,
            separate_output=False,
            allow_empty_line=False,
            allow_cursor_control=False,
            default_key=None,
            color=True,
            host_tags=None,
        )
        # No tasks created, so main should exit cleanly


@patch("ananta.ananta.uvloop", None)
@patch("ananta.ananta.argparse.ArgumentParser.parse_args")
async def test_run_cli_no_args(mock_parse_args, capsys):
    mock_parse_args.return_value = MagicMock(
        host_file=None, command=[], version=False
    )
    with pytest.raises(SystemExit):
        run_cli()
    captured = capsys.readouterr()
    assert "usage:" in captured.out  # Help message printed


@patch("ananta.ananta.uvloop", None)
@patch("ananta.ananta.argparse.ArgumentParser.parse_args")
async def test_run_cli_version(mock_parse_args, capsys):
    mock_parse_args.return_value = MagicMock(version=True)
    with pytest.raises(SystemExit):
        run_cli()
    captured = capsys.readouterr()
    assert "Ananta-1.2.0" in captured.out


@patch("ananta.ananta.execute", new_callable=AsyncMock)
@patch("ananta.ananta.print_output", new_callable=AsyncMock)
@patch("ananta.ananta.get_hosts")
@patch("ananta.ananta.asyncio.Queue")  # Mock asyncio.Queue
async def test_main_with_hosts_and_options(
    mock_queue_cls, mock_get_hosts, mock_print_output, mock_execute
):
    # Setup mock_get_hosts to return some hosts
    mock_hosts_data = [
        ("host1", "10.0.0.1", 22, "user1", "/key1"),
        ("host2", "10.0.0.2", 2222, "user2", "#"),
    ]
    mock_get_hosts.return_value = (
        mock_hosts_data,
        5,
    )  # (hosts_list, max_name_length)

    # Create plain AsyncMocks for q1 and q2, as their 'put' method will be an AsyncMock by default.
    q1, q2 = AsyncMock(), AsyncMock()
    # Ensure Queue() constructor returns our specific mocks in order
    mock_queue_cls.side_effect = [q1, q2]

    await main(
        host_file="dummy_hosts.toml",
        ssh_command="ls -l",
        local_display_width=100,
        separate_output=True,
        allow_empty_line=True,
        allow_cursor_control=True,  # This will be passed to print_output
        default_key="/default.key",
        color=False,
        host_tags="test,prod",
    )

    mock_get_hosts.assert_called_once_with("dummy_hosts.toml", "test,prod")

    assert mock_print_output.call_count == len(mock_hosts_data)
    assert mock_execute.call_count == len(mock_hosts_data)

    # Check print_output calls, including allow_cursor_control=True
    mock_print_output.assert_any_call(
        "host1", 5, True, True, True, unittest.mock.ANY, q1, False
    )
    mock_print_output.assert_any_call(
        "host2", 5, True, True, True, unittest.mock.ANY, q2, False
    )

    # Check execute calls
    mock_execute.assert_any_call(
        "host1",
        "10.0.0.1",
        22,
        "user1",
        "/key1",
        "ls -l",
        5,
        100,
        True,
        "/default.key",
        q1,
        False,
    )
    mock_execute.assert_any_call(
        "host2",
        "10.0.0.2",
        2222,
        "user2",
        "#",
        "ls -l",
        5,
        100,
        True,
        "/default.key",
        q2,
        False,
    )

    q1.put.assert_called_with(None)
    q2.put.assert_called_with(None)
