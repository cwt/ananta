from ananta.tui import AnantaUrwidTUI
from unittest.mock import patch, MagicMock, AsyncMock
import asyncio
import asyncssh
import pytest
import urwid

# Mark all tests in this file as TUI tests
pytestmark = pytest.mark.tui


@pytest.fixture
def mock_tui():
    """Fixture to create a mocked AnantaUrwidTUI instance for testing."""
    with patch("ananta.tui.get_hosts") as mock_get_hosts:
        mock_hosts_data = [("host-1", "10.0.0.1", 22, "user1", "/key1")]
        mock_get_hosts.return_value = (mock_hosts_data, 6)

        tui = AnantaUrwidTUI(
            host_file="dummy.csv",
            initial_command=None,
            host_tags=None,
            default_key=None,
            separate_output=False,
            allow_empty_line=True,
        )

        tui.output_walker = MagicMock(spec=urwid.SimpleFocusListWalker)
        tui.main_layout = MagicMock(spec=urwid.Frame)
        tui.loop = MagicMock(spec=urwid.MainLoop)
        tui.loop.screen = MagicMock()
        tui.loop.event_loop = MagicMock()
        tui.loop.screen.get_cols_rows.return_value = (80, 24)
        tui.asyncio_loop = MagicMock()
        tui.asyncio_loop.is_closed.return_value = False
        tui.is_exiting = False
        tui.connections["host-1"] = AsyncMock(spec=asyncssh.SSHClientConnection)
        tui.connections["host-1"].is_closed.return_value = False

        yield tui


def test_process_command_exit_and_empty(mock_tui):
    """Test processing the 'exit' command and an empty command."""
    mock_tui.initiate_exit = MagicMock()
    mock_tui.add_output = MagicMock()
    mock_tui.input_field = MagicMock()
    mock_tui.input_field.edit_text = "exit"

    mock_tui.process_command("exit")
    mock_tui.initiate_exit.assert_called_once()
    mock_tui.add_output.assert_not_called()

    mock_tui.initiate_exit.reset_mock()
    mock_tui.process_command("   ")
    mock_tui.initiate_exit.assert_not_called()


@pytest.mark.asyncio
async def test_run_command_separate_output(mock_tui):
    """Tests command execution with separate_output=True."""
    mock_tui.asyncio_loop = asyncio.get_running_loop()
    mock_tui.separate_output = True
    host_name = "host-1"
    conn = mock_tui.connections[host_name]
    queue = mock_tui.output_queues[host_name]

    await queue.put("line 1")
    await queue.put(None)

    # --- FIX START ---
    # Patch the source of the coroutine, not the task scheduler.
    # This ensures the coroutine is properly awaited inside the task.
    with patch(
        "ananta.tui.stream_command_output", new_callable=AsyncMock
    ) as mock_stream_func:
        await mock_tui.run_command_on_host(host_name, conn, "test command")
        # The task is created and runs in the background, awaiting our mock.
        await asyncio.sleep(0)  # Yield control to allow the task to run.
        mock_stream_func.assert_called_once()
    # --- FIX END ---


@pytest.mark.asyncio
async def test_run_command_on_host_cancelled(mock_tui):
    """Test command cancellation during execution."""
    mock_tui.asyncio_loop = asyncio.get_running_loop()
    host_name = "host-1"
    conn = mock_tui.connections[host_name]

    inner_task_mock = MagicMock()
    original_create_task = asyncio.create_task

    def capture_task(coro, *args, **kwargs):
        task = original_create_task(coro, *args, **kwargs)
        inner_task_mock.task = task
        return task

    with patch("asyncio.create_task", side_effect=capture_task):
        run_host_task = original_create_task(
            mock_tui.run_command_on_host(host_name, conn, "some command")
        )
        await asyncio.sleep(0)

        assert inner_task_mock.task is not None
        inner_task_mock.task.cancel()

        await asyncio.sleep(0)
        await run_host_task

    assert any(
        "Command cancelled/interrupted" in str(call.args[0].get_text())
        for call in mock_tui.output_walker.append.call_args_list
    )


@pytest.mark.asyncio
async def test_perform_shutdown_cancels_tasks(mock_tui):
    """Test that perform_shutdown cancels pending async tasks."""
    mock_tui.asyncio_loop = asyncio.get_running_loop()
    dummy_task = asyncio.create_task(asyncio.sleep(1))
    mock_tui.async_tasks.add(dummy_task)

    await mock_tui.perform_shutdown()

    assert dummy_task.cancelled()
    assert any(
        "Cleaning up 1 tasks..." in str(call.args[0].get_text())
        for call in mock_tui.output_walker.append.call_args_list
    )


def test_add_output_when_exiting_with_keywords(mock_tui):
    """Test that output containing specific keywords is still added when exiting."""
    mock_tui.is_exiting = True

    mock_tui.add_output("regular message")
    mock_tui.output_walker.append.assert_not_called()

    mock_tui.add_output("An error occurred during shutdown")
    mock_tui.output_walker.append.assert_called_once()


@patch("ananta.tui.urwid.AsyncioEventLoop")
@patch("ananta.tui.urwid.MainLoop")
def test_run_method_exceptions(mock_main_loop, mock_event_loop, mock_tui):
    """Test exception handling in the main run method."""
    mock_loop_instance = mock_main_loop.return_value

    mock_loop_instance.run.side_effect = KeyboardInterrupt
    mock_tui.initiate_exit = MagicMock()

    with patch("builtins.print") as mock_print:
        mock_tui.run()
        mock_print.assert_any_call(
            "\nAnanta TUI interrupted by user (KeyboardInterrupt)."
        )
        mock_tui.initiate_exit.assert_called_once()

    mock_loop_instance.run.side_effect = ValueError("A test error")
    with (
        patch("builtins.print") as mock_print,
        patch("traceback.print_exc") as mock_traceback,
    ):
        mock_tui.run()
        mock_print.assert_any_call(
            "\nAnanta TUI encountered an unexpected error: A test error"
        )
        mock_traceback.assert_called_once()
