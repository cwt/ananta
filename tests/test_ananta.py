from ananta.ananta import main
from ananta.ananta import run_cli
from unittest.mock import patch, MagicMock, AsyncMock
import pytest

pytestmark = pytest.mark.asyncio  # Enable async for all tests


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
