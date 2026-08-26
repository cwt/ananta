import unittest
from importlib.metadata import version
from unittest.mock import ANY, AsyncMock, MagicMock, patch

import pytest

from ananta.ananta import main, run_cli

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
    assert f"Ananta-{version('ananta')}" in captured.out


@patch("ananta.ananta._close_ssh_connection", new_callable=AsyncMock)
@patch("ananta.ananta.establish_ssh_connection", new_callable=AsyncMock)
@patch("ananta.ananta.execute", new_callable=AsyncMock)
@patch("ananta.ananta.print_output", new_callable=AsyncMock)
@patch("ananta.ananta.get_hosts")
@patch("ananta.ananta.asyncio.Queue")  # Mock asyncio.Queue
async def test_main_with_hosts_and_options(
    mock_queue_cls,
    mock_get_hosts,
    mock_print_output,
    mock_execute,
    mock_establish,
    mock_close,
):
    # Setup mock_get_hosts to return some hosts
    mock_hosts_data = [
        ("host1", "10.0.0.1", 22, "user1", "/key1", 5.0, 2),
        ("host2", "10.0.0.2", 2222, "user2", "#", 5.0, 2),
    ]
    mock_get_hosts.return_value = (
        mock_hosts_data,
        5,
    )  # (hosts_list, max_name_length)

    # Create plain AsyncMocks for q1 and q2, as their 'put' method will be an AsyncMock by default.
    q1, q2 = AsyncMock(), AsyncMock()
    # Ensure Queue() constructor returns our specific mocks in order
    mock_queue_cls.side_effect = [q1, q2]
    conn1, conn2 = MagicMock(), MagicMock()
    mock_establish.side_effect = [conn1, conn2]

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
        5.0,
        2,
        conn=ANY,
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
        5.0,
        2,
        conn=ANY,
    )

    assert mock_execute.call_args.kwargs["conn"] == conn2
    calls = {c.args[0]: c for c in mock_execute.call_args_list}
    assert calls["host1"].kwargs["conn"] == conn1
    assert calls["host2"].kwargs["conn"] == conn2

    q1.put.assert_called_with(None)
    q2.put.assert_called_with(None)


@patch("ananta.ananta.execute", new_callable=AsyncMock)
@patch("ananta.ananta.print_output", new_callable=AsyncMock)
@patch("ananta.ananta.get_hosts")
@patch("ananta.ananta.asyncio.Queue")
async def test_main_signals_printers_when_execute_raises(
    mock_queue_cls, mock_get_hosts, mock_print_output, mock_execute
):
    """Regression: an unexpected exception escaping execute() must not leave
    print tasks hanging. End-of-output sentinels must still be delivered and
    printing tasks awaited before the error propagates."""
    hosts_data = [("host1", "10.0.0.1", 22, "user1", "/key1", 5.0, 2)]
    mock_get_hosts.return_value = (hosts_data, 5)

    q1 = MagicMock()
    q1.put = AsyncMock()
    mock_queue_cls.side_effect = [q1]

    mock_execute.side_effect = OSError("unexpected failure")

    with pytest.raises(OSError):
        await main(
            host_file="hosts.toml",
            ssh_command="uptime",
            local_display_width=80,
            separate_output=False,
            allow_empty_line=False,
            allow_cursor_control=False,
            default_key=None,
            color=True,
            host_tags=None,
        )

    # The sentinel must have been queued despite the failure.
    q1.put.assert_called_with(None)
    # Printing tasks must have been started and completed (gathered).
    mock_print_output.assert_called_once()


# ---------------------------------------------------------------------------
# Host-key verification gate (pre-flight phase)
# ---------------------------------------------------------------------------


async def _make_verified_session(monkeypatch, tmp_path, mismatch_host=None):
    """Wire main() to a controlled environment.

    Returns (policy, mocks dict). If mismatch_host is set, connections to it
    record a mismatch into the policy and raise HostKeyChangedError; on the
    second attempt for the same host they succeed (override path).
    """
    from unittest.mock import AsyncMock, MagicMock, patch

    from ananta.host_keys import (
        HostKeyChangedError,
        HostKeyPolicy,
        MismatchRecord,
    )

    kh = tmp_path / "known_hosts"
    policy = HostKeyPolicy(known_hosts_path=kh)
    attempts = {}
    conns = {"ok": MagicMock(name="conn")}

    async def fake_establish(
        ip, port, user, key_path, dflt, timeout, retries, pol
    ):
        if mismatch_host and ip == mismatch_host:
            attempts[ip] = attempts.get(ip, 0) + 1
            if attempts[ip] == 1:
                pol.mismatches.append(
                    MismatchRecord(
                        entry=ip,
                        old_fingerprint="SHA256:OLD",
                        new_fingerprint="SHA256:NEW",
                        new_blob="ssh-ed25519 NEWBLOB",
                    )
                )
                raise HostKeyChangedError(f"HOST KEY MISMATCH for {ip}")
            return conns["ok"]
        return conns["ok"]

    monkeypatch.setattr("ananta.ananta._create_policy", lambda **kw: policy)
    establish_mock = AsyncMock(side_effect=fake_establish)
    monkeypatch.setattr(
        "ananta.ananta.establish_ssh_connection", establish_mock
    )

    hosts = [("web-01", "192.0.2.1", 22, "u", "#", 5.0, 2)]
    if mismatch_host:
        hosts.append(("bad-01", mismatch_host, 22, "u", "#", 5.0, 2))

    get_hosts = MagicMock(return_value=(hosts, 6))
    monkeypatch.setattr("ananta.ananta.get_hosts", get_hosts)
    print_output = AsyncMock()
    monkeypatch.setattr("ananta.ananta.print_output", print_output)
    execute_mock = AsyncMock()
    monkeypatch.setattr("ananta.ananta.execute", execute_mock)
    queues = [AsyncMock(), AsyncMock()] if len(hosts) > 1 else [AsyncMock()]
    queue_cls = MagicMock(side_effect=queues)
    monkeypatch.setattr("ananta.ananta.asyncio.Queue", queue_cls)

    async def run_main(override=False, confirm_answer="CONFIRM"):
        with patch(
            "builtins.input",
            return_value=confirm_answer,
        ):
            await main(
                host_file="hosts.csv",
                ssh_command="uptime",
                local_display_width=100,
                separate_output=False,
                allow_empty_line=False,
                allow_cursor_control=False,
                default_key=None,
                color=False,
                host_tags=None,
                override_mismatched_keys=override,
            )

    return policy, {
        "execute": execute_mock,
        "print_output": print_output,
        "queues": queue_cls.return_value,
        "run_main": run_main,
    }


async def test_main_aborts_on_host_key_mismatch(monkeypatch, tmp_path, capsys):
    """Any mismatch stops the batch before a single command executes."""
    _, m = await _make_verified_session(
        monkeypatch, tmp_path, mismatch_host="192.0.2.9"
    )
    with pytest.raises(SystemExit) as excinfo:
        await m["run_main"]()
    assert excinfo.value.code == 3
    out = capsys.readouterr().out
    assert "HOST KEY MISMATCH DETECTED" in out
    assert "SHA256:OLD" in out and "SHA256:NEW" in out
    # No command ever dispatched.
    m["execute"].assert_not_called()


async def test_main_override_confirmed_replaces_and_continues(
    monkeypatch, tmp_path
):
    """Typing CONFIRM re-trusts the key, reconnects, and runs everywhere."""
    policy, m = await _make_verified_session(
        monkeypatch, tmp_path, mismatch_host="192.0.2.9"
    )
    await m["run_main"](override=True, confirm_answer="CONFIRM")

    called_hosts = {c.args[0] for c in m["execute"].call_args_list}
    assert called_hosts == {"web-01", "bad-01"}


async def test_main_override_declined_aborts(monkeypatch, tmp_path):
    """Anything other than an exact all-caps CONFIRM aborts."""
    _, m = await _make_verified_session(
        monkeypatch, tmp_path, mismatch_host="192.0.2.9"
    )
    with pytest.raises(SystemExit) as excinfo:
        await m["run_main"](override=True, confirm_answer="confirm")
    assert excinfo.value.code == 3
    m["execute"].assert_not_called()


async def test_main_reports_added_keys_after_session(
    monkeypatch, tmp_path, capsys
):
    """TOFU additions are summarized once, after the whole session."""
    from ananta.host_keys import HostKeyPolicy

    kh = tmp_path / "known_hosts"
    policy = HostKeyPolicy(known_hosts_path=kh)
    policy._added.append(("new-host", "SHA256:FPR"))

    monkeypatch.setattr("ananta.ananta._create_policy", lambda **kw: policy)
    monkeypatch.setattr(
        "ananta.ananta.establish_ssh_connection",
        AsyncMock(return_value=MagicMock()),
    )
    monkeypatch.setattr(
        "ananta.ananta.get_hosts",
        MagicMock(
            return_value=([("n1", "192.0.2.50", 22, "u", "#", 5.0, 2)], 2)
        ),
    )
    monkeypatch.setattr("ananta.ananta.print_output", AsyncMock())
    monkeypatch.setattr("ananta.ananta.execute", AsyncMock())
    monkeypatch.setattr(
        "ananta.ananta.asyncio.Queue", MagicMock(return_value=AsyncMock())
    )

    await main(
        host_file="hosts.csv",
        ssh_command="uptime",
        local_display_width=80,
        separate_output=False,
        allow_empty_line=False,
        allow_cursor_control=False,
        default_key=None,
        color=False,
        host_tags=None,
    )

    out = capsys.readouterr().out
    assert "Added 1 new host key(s)" in out
    assert "new-host (SHA256:FPR)" in out
