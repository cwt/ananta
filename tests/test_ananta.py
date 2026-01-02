from ananta.ananta import run_cli
from unittest.mock import AsyncMock, MagicMock, patch
import os
import sys
import importlib
import builtins

# ananta.ananta module, to be reloaded in some tests
import ananta.ananta as ananta_module


@patch(
    "ananta.ananta.main", new_callable=AsyncMock
)  # Mock main to prevent full execution
@patch("ananta.ananta.argparse.ArgumentParser.parse_args")
@patch("ananta.ananta.asyncio.set_event_loop_policy")
@patch("sys.platform", "linux")
def test_run_cli_uvloop_linux_success(
    mock_set_policy, mock_parse_args, mock_main_func
):
    mock_parse_args.return_value = MagicMock(
        host_file="hosts.csv",
        command=["cmd"],
        version=False,
        terminal_width=80,
        tui=False,
        tui_light=False,
    )
    # Simulate uvloop being successfully imported and set in ananta_module.uvloop
    with patch.dict(
        sys.modules, {"uvloop": MagicMock(EventLoopPolicy=MagicMock())}
    ):
        # Reload ananta_module to re-trigger its module-level uvloop import logic
        # This is tricky because ananta_module.uvloop is what ananta.ananta.run_cli checks
        # For this test, we'll patch ananta_module.uvloop directly to simulate successful import
        with patch(
            "ananta.ananta.uvloop", MagicMock(EventLoopPolicy=MagicMock())
        ) as mock_uvloop_module:
            run_cli()
            mock_set_policy.assert_called_once_with(
                mock_uvloop_module.EventLoopPolicy()
            )


@patch("ananta.ananta.main", new_callable=AsyncMock)
@patch("ananta.ananta.argparse.ArgumentParser.parse_args")
@patch("ananta.ananta.asyncio.set_event_loop_policy")
@patch("sys.platform", "linux")
def test_run_cli_uvloop_linux_fail(
    mock_set_policy, mock_parse_args, mock_main_func
):
    mock_parse_args.return_value = MagicMock(
        host_file="hosts.csv",
        command=["cmd"],
        version=False,
        terminal_width=80,
        tui=False,
        tui_light=False,
    )
    # Simulate uvloop being None (import failed)
    with patch("ananta.ananta.uvloop", None):
        run_cli()
        mock_set_policy.assert_not_called()


@patch("ananta.ananta.main", new_callable=AsyncMock)
@patch("ananta.ananta.argparse.ArgumentParser.parse_args")
@patch("ananta.ananta.asyncio.set_event_loop_policy")
@patch("sys.platform", "win32")
def test_run_cli_winloop_windows_success(
    mock_set_policy, mock_parse_args, mock_main_func
):
    mock_parse_args.return_value = MagicMock(
        host_file="hosts.csv",
        command=["cmd"],
        version=False,
        terminal_width=80,
        tui=False,
        tui_light=False,
    )
    # Simulate winloop being successfully imported and set in ananta_module.uvloop
    with patch.dict(
        sys.modules, {"winloop": MagicMock(EventLoopPolicy=MagicMock())}
    ):
        # Patch ananta_module.uvloop directly to simulate successful import of winloop
        with patch(
            "ananta.ananta.uvloop", MagicMock(EventLoopPolicy=MagicMock())
        ) as mock_winloop_module:  # ananta.ananta.uvloop will point to winloop
            run_cli()
            mock_set_policy.assert_called_once_with(
                mock_winloop_module.EventLoopPolicy()
            )


@patch("ananta.ananta.main", new_callable=AsyncMock)  # Mock main
@patch("ananta.ananta.argparse.ArgumentParser.parse_args")
@patch("os.get_terminal_size")
@patch.dict(os.environ, {}, clear=True)  # Ensure COLUMNS is not in environ
def test_run_cli_terminal_width_from_os_get_terminal_size(
    mock_get_terminal_size, mock_parse_args, mock_main_func
):
    mock_parse_args.return_value = MagicMock(
        host_file="hosts.csv",
        command=["cmd"],
        version=False,
        terminal_width=None,
        tui=False,
        tui_light=False,
    )
    mock_get_terminal_size.return_value = os.terminal_size(
        (120, 24)
    )  # Simulate terminal size

    run_cli()

    # Check that main was called with local_display_width = 120
    args, kwargs = mock_main_func.call_args  # noqa
    assert (
        args[2] == 120
    )  # local_display_width is the 3rd positional arg to main


@patch("ananta.ananta.main", new_callable=AsyncMock)
@patch("ananta.ananta.argparse.ArgumentParser.parse_args")
@patch("ananta.ananta.os.get_terminal_size")
@patch.dict(os.environ, {"COLUMNS": "100"}, clear=True)
def test_run_cli_terminal_width_from_env_columns(
    mock_os_get_terminal_size, mock_parse_args, mock_main_func
):
    mock_parse_args.return_value = MagicMock(
        host_file="hosts.csv",
        command=["cmd"],
        version=False,
        terminal_width=None,
        tui=False,
        tui_light=False,
    )

    # os.get_terminal_size() WILL be called to prepare the default for os.environ.get()
    # Let it return a dummy value different from 100 to ensure it's not the source of the width.
    mock_os_get_terminal_size.return_value = os.terminal_size((50, 24))

    run_cli()

    args_call, kwargs_call = mock_main_func.call_args  # noqa
    # The crucial part: local_display_width should be 100 (from COLUMNS), not 50 (from mocked get_terminal_size)
    assert args_call[2] == 100


@patch("ananta.ananta.main", new_callable=AsyncMock)  # Mock main
@patch("ananta.ananta.argparse.ArgumentParser.parse_args")
def test_run_cli_terminal_width_from_arg(mock_parse_args, mock_main_func):
    mock_parse_args.return_value = MagicMock(
        host_file="hosts.csv",
        command=["cmd"],
        version=False,
        terminal_width=90,
        tui=False,
        tui_light=False,
    )

    run_cli()
    args, kwargs = mock_main_func.call_args  # noqa
    assert args[2] == 90  # local_display_width from args.terminal_width


@patch("ananta.ananta.main", new_callable=AsyncMock)  # Mock main
@patch("ananta.ananta.argparse.ArgumentParser.parse_args")
@patch("os.get_terminal_size", side_effect=OSError("Simulated OSError"))
@patch.dict(os.environ, {}, clear=True)
def test_run_cli_terminal_width_os_error(
    mock_get_terminal_size, mock_parse_args, mock_main_func
):
    mock_parse_args.return_value = MagicMock(
        host_file="hosts.csv",
        command=["cmd"],
        version=False,
        terminal_width=None,
        tui=False,
        tui_light=False,
    )

    run_cli()
    args, kwargs = mock_main_func.call_args  # noqa
    assert args[2] == 80  # Default width on OSError


@patch("ananta.ananta.asyncio.set_event_loop_policy")
def test_run_cli_platform_imports(mock_set_event_loop_policy, capsys, tmp_path):
    args = MagicMock(
        host_file=str(tmp_path / "hosts.csv"),
        command=["cmd"],
        version=False,
        terminal_width=80,
        no_color=False,
        separate_output=False,
        host_tags=None,
        allow_empty_line=False,
        allow_cursor_control=False,
        default_key=None,
        tui=False,
        tui_light=False,
    )
    (tmp_path / "hosts.csv").write_text(
        "host1,1.1.1.1,22,user,#", encoding="utf-8"
    )

    original_ananta_uvloop = ananta_module.uvloop
    original_sys_modules = sys.modules.copy()
    _original_builtins_import = builtins.__import__  # Save original __import__

    # Scenario 1: Linux, uvloop success
    with patch("sys.platform", "linux"):
        mock_uvloop_module = MagicMock(EventLoopPolicy=MagicMock())
        sys.modules["uvloop"] = mock_uvloop_module
        if "winloop" in sys.modules:
            del sys.modules["winloop"]

        try:
            importlib.reload(ananta_module)
            assert (
                ananta_module.uvloop is mock_uvloop_module
            ), "ananta.ananta.uvloop not set to uvloop on Linux"
            with (
                patch(
                    "ananta.ananta.argparse.ArgumentParser.parse_args",
                    return_value=args,
                ),
                patch("ananta.ananta.main", AsyncMock()),
            ):
                ananta_module.run_cli()
            mock_set_event_loop_policy.assert_called_with(
                mock_uvloop_module.EventLoopPolicy()
            )
        finally:
            sys.modules.clear()
            sys.modules.update(original_sys_modules)
            builtins.__import__ = (
                _original_builtins_import  # Restore __import__
            )
            ananta_module.uvloop = original_ananta_uvloop
            importlib.reload(ananta_module)

    mock_set_event_loop_policy.reset_mock()

    # Scenario 2: Windows, winloop success
    with patch("sys.platform", "win32"):
        mock_winloop_module = MagicMock(EventLoopPolicy=MagicMock())
        sys.modules["winloop"] = mock_winloop_module
        if "uvloop" in sys.modules:
            del sys.modules["uvloop"]

        try:
            importlib.reload(ananta_module)
            assert (
                ananta_module.uvloop is mock_winloop_module
            ), "ananta.ananta.uvloop not set to winloop on Windows"
            with (
                patch(
                    "ananta.ananta.argparse.ArgumentParser.parse_args",
                    return_value=args,
                ),
                patch("ananta.ananta.main", AsyncMock()),
            ):
                ananta_module.run_cli()
            mock_set_event_loop_policy.assert_called_with(
                mock_winloop_module.EventLoopPolicy()
            )
        finally:
            sys.modules.clear()
            sys.modules.update(original_sys_modules)
            builtins.__import__ = _original_builtins_import
            ananta_module.uvloop = original_ananta_uvloop
            importlib.reload(ananta_module)

    mock_set_event_loop_policy.reset_mock()

    # Scenario 3: Linux, uvloop import fail
    def mocked_import_uvloop_missing(
        name, globals_map=None, locals_map=None, fromlist=(), level=0
    ):
        if name == "uvloop" or name == "winloop":  # Target specific modules
            raise ImportError(f"Simulated import failure for {name}")
        # Important: call the original import for other modules
        return _original_builtins_import(
            name, globals_map, locals_map, fromlist, level
        )

    with (
        patch("sys.platform", "linux"),
        patch("builtins.__import__", side_effect=mocked_import_uvloop_missing),
    ):
        try:
            importlib.reload(ananta_module)
            assert (
                ananta_module.uvloop is None
            ), "ananta.ananta.uvloop should be None when import is mocked to fail"

            with (
                patch(
                    "ananta.ananta.argparse.ArgumentParser.parse_args",
                    return_value=args,
                ),
                patch("ananta.ananta.main", AsyncMock()),
            ):
                ananta_module.run_cli()
            mock_set_event_loop_policy.assert_not_called()
        finally:
            sys.modules.clear()
            sys.modules.update(original_sys_modules)
            builtins.__import__ = (
                _original_builtins_import  # Ensure original import is restored
            )
            ananta_module.uvloop = original_ananta_uvloop
            importlib.reload(ananta_module)


@patch("ananta.ananta.main", new_callable=AsyncMock)  # Mock main
@patch("ananta.ananta.argparse.ArgumentParser.parse_args")
def test_run_cli_tui_light_option(mock_parse_args, mock_main_func):
    """Test that the --tui-light option is properly handled."""
    mock_parse_args.return_value = MagicMock(
        host_file="hosts.csv",
        command=["cmd"],
        version=False,
        terminal_width=80,
        tui=False,  # Regular tui is False
        tui_light=True,  # But tui_light is True
    )

    # Mock urwid import to avoid TUI issues in test
    with patch.dict("sys.modules", {"urwid": MagicMock()}):
        # Mock the TUI run method
        with patch("ananta.tui.AnantaUrwidTUI") as mock_tui_class:
            mock_tui_instance = MagicMock()
            mock_tui_class.return_value = mock_tui_instance
            try:
                run_cli()
            except SystemExit:
                # TUI was called, which is expected
                pass

    # Verify the TUI was initialized with light_theme=True
    mock_tui_class.assert_called_once()
    args, kwargs = mock_tui_class.call_args
    assert kwargs.get("light_theme") == True
