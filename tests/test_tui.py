from ananta.tui import AnantaUrwidTUI, format_host_prompt
from unittest.mock import patch, MagicMock, AsyncMock
import asyncio
import pytest
import urwid

# Mark all tests in this file as TUI tests
pytestmark = pytest.mark.tui


@pytest.fixture
def mock_tui():
    """Fixture to create a mocked AnantaUrwidTUI instance for testing."""
    with (
        patch("ananta.tui.get_hosts") as mock_get_hosts,
        patch("ananta.tui.RefreshingPile", spec=urwid.Pile) as mock_pile,
        patch("ananta.tui.urwid") as mock_urwid,
    ):
        # Setup mock for get_hosts
        mock_hosts_data = [
            ("host-1", "10.0.0.1", 22, "user1", "/key1"),
            ("host-2", "10.0.0.2", 2222, "user2", "#"),
        ]
        mock_get_hosts.return_value = (mock_hosts_data, 6)  # (hosts, max_len)

        # Instantiate the TUI. It will use the mocked get_hosts.
        tui = AnantaUrwidTUI(
            host_file="dummy.csv",
            initial_command=None,
            host_tags=None,
            default_key=None,
            separate_output=False,
            allow_empty_line=True,
        )
        # Attach mocks for later inspection
        tui.urwid = mock_urwid
        tui.main_pile = mock_pile

        # Replace walkers and boxes with mocks.
        tui.output_walker = MagicMock(spec=urwid.SimpleFocusListWalker)
        tui.output_box = MagicMock(spec=urwid.ListBox)
        tui.main_layout = MagicMock(spec=urwid.Frame)
        tui.prompt_attr_map = MagicMock(spec=urwid.AttrMap)
        tui.main_pile.focus_position = 2  # Start with input focused

        # Mock the main loop and its nested properties to avoid AttributeErrors
        tui.loop = MagicMock(spec=urwid.MainLoop)
        tui.loop.event_loop = MagicMock(spec=urwid.AsyncioEventLoop)
        tui.loop.screen = MagicMock()
        tui.loop.screen.get_cols_rows.return_value = (80, 24)

        # Provide a basic mock for the asyncio_loop.
        # Tests that need a real loop will replace this.
        tui.asyncio_loop = MagicMock()
        tui.asyncio_loop.is_closed.return_value = False

        yield tui


def test_tui_initialization(mock_tui):
    """Test if TUI initializes correctly."""
    # Check if hosts were loaded
    assert len(mock_tui.hosts) == 2
    assert mock_tui.hosts[0][0] == "host-1"
    assert mock_tui.max_name_length == 6

    # Check that main layout components were instantiated
    mock_tui.urwid.Frame.assert_called_once()
    # mock_tui.urwid.Pile.assert_called_once()
    assert mock_tui.main_pile is not None
    mock_tui.urwid.Edit.assert_called_once()

    # Check initial state
    assert mock_tui.is_exiting is False


def test_tui_initialization_welcome_message():
    """Test if the TUI welcome message is shown."""
    # This test does not use the fixture to isolate the check
    with patch("ananta.tui.get_hosts", return_value=([], 0)):
        tui = AnantaUrwidTUI(
            host_file="dummy.csv",
            initial_command=None,
            host_tags=None,
            default_key=None,
            separate_output=False,
            allow_empty_line=False,
        )
        # The warning is added to the output walker
        assert tui.output_walker
        # Check if the first message in the walker is the warning
        warning_widget = tui.output_walker[0]
        assert "Welcome to Ananta TUI mode." in str(warning_widget.get_text())


def test_tui_initialization_separate_output_warning():
    """Test if the warning for separate output mode is shown."""
    # This test does not use the fixture to isolate the check
    with patch("ananta.tui.get_hosts", return_value=([], 0)):
        tui = AnantaUrwidTUI(
            host_file="dummy.csv",
            initial_command=None,
            host_tags=None,
            default_key=None,
            separate_output=True,  # Enable separate output
            allow_empty_line=False,
        )
        # The warning is added to the output walker
        assert tui.output_walker
        # Check if the first message in the walker is the warning
        warning_widget = tui.output_walker[1]
        assert "Separate Output mode [-s] enabled." in str(
            warning_widget.get_text()
        )


def test_add_output_trimming(mock_tui):
    """Test that the output walker is trimmed when it gets too long."""
    # Configure screen size to calculate max_lines
    mock_tui.loop.screen.get_cols_rows.return_value = (80, 20)  # 20 rows
    max_lines = 20 * 5  # rows * 5 -> 100
    trim_lines = 20  # rows

    current_length = max_lines + 1
    # Make the mock walker report a length that exceeds the limit
    mock_tui.output_walker.__len__.return_value = current_length

    mock_tui.add_output("A new line")

    # Check that the trimming logic was called via __delitem__
    mock_tui.output_walker.__delitem__.assert_called_once()
    # Check that it was called with the correct slice to trim lines
    call_args = mock_tui.output_walker.__delitem__.call_args
    deleted_slice = call_args.args[0]

    # This calculation now correctly matches the logic in the application code.
    expected_stop_index = current_length - (max_lines - trim_lines)
    assert deleted_slice.start == 0
    assert deleted_slice.stop == expected_stop_index


def test_add_output_when_exiting(mock_tui):
    """Test that add_output does nothing if the TUI is exiting."""
    mock_tui.is_exiting = True
    mock_tui.add_output("This should not be added")
    mock_tui.output_walker.append.assert_not_called()


def test_format_host_prompt():
    """Test the static host prompt formatting function."""
    prompt_markup = format_host_prompt("my-host", 10)
    expected_attr_name = "host_my_host"
    expected_padding = "   my-host"
    assert prompt_markup == [(expected_attr_name, f"[{expected_padding}] ")]


@pytest.mark.asyncio
async def test_connect_all_hosts_no_hosts(mock_tui):
    """Test connect_all_hosts when no hosts are found."""
    mock_tui.hosts = []  # Simulate no hosts
    mock_tui.add_output = MagicMock()
    await mock_tui.connect_all_hosts()
    mock_tui.add_output.assert_called_once()
    assert "No hosts found" in str(mock_tui.add_output.call_args.args[0])


@pytest.mark.asyncio
async def test_connect_all_hosts_with_initial_command(mock_tui):
    """Test connect_all_hosts and that it runs an initial command."""
    mock_tui.initial_command = "uptime"
    mock_tui.connect_host = AsyncMock()
    mock_tui.process_command = MagicMock()

    await mock_tui.connect_all_hosts()

    # Check that connect_host was called for each host
    assert mock_tui.connect_host.call_count == len(mock_tui.hosts)
    # Check that the initial command was processed
    mock_tui.process_command.assert_called_once_with("uptime")


@pytest.mark.asyncio
async def test_connect_host_success(mock_tui):
    """Test the connection sequence for a single host that succeeds."""
    with patch(
        "ananta.tui.establish_ssh_connection", new_callable=AsyncMock
    ) as mock_establish:
        # Using MagicMock for the connection object fixes the RuntimeWarning
        mock_conn = MagicMock()
        mock_establish.return_value = mock_conn

        host_details = mock_tui.hosts[0]  # ('host-1', ...)
        await mock_tui.connect_host(*host_details)

        mock_establish.assert_awaited_once()
        assert mock_tui.connections["host-1"] is mock_conn
        # Check the "add_output" calls
        markup_calls = [c.args[0] for c in mock_tui.urwid.Text.call_args_list]
        assert any("Connecting..." in str(m) for m in markup_calls)
        assert any("Connected." in str(m) for m in markup_calls)


@pytest.mark.asyncio
async def test_run_command_interleaved_output_and_empty_lines(mock_tui):
    """Tests interleaved command output and empty line handling."""
    mock_tui.asyncio_loop = asyncio.get_running_loop()
    mock_tui.separate_output = False
    mock_tui.allow_empty_line = True
    mock_tui.add_output = MagicMock()

    async def feed_queue(q):
        await q.put("line 1")
        await q.put("")  # Empty line
        await q.put(None)

    queue = mock_tui.output_queues["host-1"]
    feeder_task = mock_tui.asyncio_loop.create_task(feed_queue(queue))

    with patch(
        "ananta.tui.stream_command_output", new_callable=AsyncMock
    ) as mock_stream:
        await mock_tui.run_command_on_host("host-1", MagicMock(), "cmd")
        mock_stream.assert_awaited_once()

    await feeder_task
    # add_output called for "line 1" and for the empty line
    assert mock_tui.add_output.call_count == 2
    second_call_arg = mock_tui.add_output.call_args_list[1].args[0]
    assert "" in second_call_arg  # Check the empty line was added


@pytest.mark.asyncio
async def test_run_command_on_host_raises_error(mock_tui):
    """
    Tests that an error during command execution is caught.
    Note: The current implementation catches and swallows the error without display.
    This test verifies that behavior.
    """
    mock_tui.asyncio_loop = asyncio.get_running_loop()
    mock_tui.add_output = MagicMock()

    # Use an AsyncMock that will raise an exception when awaited by the stream_task
    mock_stream = AsyncMock(side_effect=Exception("command failed"))

    with patch("ananta.tui.stream_command_output", new=mock_stream):
        # The run_command_on_host method should not re-raise the exception
        await mock_tui.run_command_on_host("host-1", MagicMock(), "cmd")

    # Check that no command error message was added, because the current
    # implementation swallows the exception in the 'finally' block.
    markup_calls = [c.args[0] for c in mock_tui.add_output.call_args_list]
    assert not any("Cmd error" in str(m) for m in markup_calls)


def test_handle_input(mock_tui):
    """Tests the main input handler."""
    mock_tui.process_command = MagicMock()
    mock_tui.initiate_exit = MagicMock()

    # Test 'enter' key
    mock_tui.input_field.edit_text = "some command"
    mock_tui.handle_input("enter")
    mock_tui.process_command.assert_called_once_with("some command")

    # Test 'ctrl c'
    mock_tui.handle_input("ctrl c")
    assert mock_tui.initiate_exit.call_count == 1

    # Test 'ctrl d'
    mock_tui.handle_input("ctrl d")
    assert mock_tui.initiate_exit.call_count == 2


def test_handle_input_when_exiting(mock_tui):
    """Test handle_input returns immediately when exiting."""
    mock_tui.is_exiting = True
    result = mock_tui.handle_input("enter")
    assert result is True


def test_update_prompt_attribute(mock_tui):
    """Tests that the input prompt style changes with focus."""
    # Case 1: Input is focused
    mock_tui.main_pile.focus_position = 2
    mock_tui.update_prompt_attribute()
    mock_tui.prompt_attr_map.set_attr_map.assert_called_with(
        {None: "input_prompt"}
    )

    # Case 2: Input is not focused
    mock_tui.main_pile.focus_position = 0
    mock_tui.update_prompt_attribute()
    mock_tui.prompt_attr_map.set_attr_map.assert_called_with(
        {None: "input_prompt_inactive"}
    )


def test_initiate_exit_no_loop(mock_tui):
    """Test exit procedure when the asyncio loop is not running."""
    mock_tui.asyncio_loop = None
    mock_tui._direct_exit_loop = MagicMock()
    mock_tui.initiate_exit()
    mock_tui._direct_exit_loop.assert_called_once()


@pytest.mark.asyncio
async def test_perform_shutdown_with_timeout(mock_tui):
    """Test shutdown where closing a connection times out."""
    mock_tui.asyncio_loop = asyncio.get_running_loop()

    # Mock a connection where wait_closed will time out
    mock_conn = MagicMock()
    mock_conn.close = MagicMock()
    mock_conn.is_closed.return_value = False
    mock_conn.wait_closed = AsyncMock(side_effect=asyncio.TimeoutError)
    mock_tui.connections["host-1"] = mock_conn

    await mock_tui.perform_shutdown()

    # Check that close was called, even if wait_closed timed out
    mock_conn.close.assert_called_once()
    text_outputs = " ".join(
        [str(c.args[0]) for c in mock_tui.urwid.Text.call_args_list]
    )
    assert "All connections closed or timed out" in text_outputs
