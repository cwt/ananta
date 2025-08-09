import pytest
from unittest.mock import patch, MagicMock
from ananta.config import (
    _load_toml_data,
    _get_hosts_from_toml,
    _get_hosts_from_csv,
    get_hosts,
)
import os

# Mark all tests in this file as config tests
pytestmark = pytest.mark.config


@patch("sys.version_info", (3, 10, 0))  # Simulate Python 3.10
@patch("ananta.config.tomllib", None)  # Simulate tomli not being installed
def test_load_toml_data_missing_tomli_raises_runtime_error():
    """
    Test that _load_toml_data raises a RuntimeError on Python < 3.11
    if tomli is not installed.
    """
    with pytest.raises(RuntimeError) as excinfo:
        _load_toml_data("dummy_path.toml")

    assert "requires 'tomli' to be installed" in str(excinfo.value)
    assert "pip install ananta --force-reinstall" in str(excinfo.value)


def test_get_hosts_from_toml_file_not_found(capsys):
    """
    Test that _get_hosts_from_toml handles a FileNotFoundError gracefully.
    """
    hosts, max_len = _get_hosts_from_toml("non_existent_file.toml", None)
    captured = capsys.readouterr()

    assert hosts == []
    assert max_len == 0
    assert "Error: TOML hosts file not found" in captured.out


def test_get_hosts_from_toml_decode_error(tmp_path, capsys):
    """
    Test that _get_hosts_from_toml handles a TOMLDecodeError gracefully.
    """
    malformed_toml = tmp_path / "malformed.toml"
    malformed_toml.write_text("this is not valid toml")

    hosts, max_len = _get_hosts_from_toml(str(malformed_toml), None)
    captured = capsys.readouterr()

    assert hosts == []
    assert max_len == 0
    assert "Error decoding TOML file" in captured.out


def test_get_hosts_from_toml_non_dictionary_section(tmp_path, capsys):
    """
    Test that _get_hosts_from_toml handles non-dictionary sections gracefully.
    """
    toml_with_invalid_section = tmp_path / "invalid_section.toml"
    toml_with_invalid_section.write_text(
        """
[host1]
ip = "1.1.1.1"
port = 22
username = "user1"

[invalid_section]
this = "is not a dictionary of hosts"
"""
    )

    hosts, max_len = _get_hosts_from_toml(str(toml_with_invalid_section), None)
    captured = capsys.readouterr()

    assert len(hosts) == 1
    assert max_len == 5
    assert "is missing 'ip' or 'ip' is not a string" in captured.out


def test_get_hosts_from_toml_missing_username(tmp_path, capsys):
    """
    Test that _get_hosts_from_toml handles a missing username gracefully.
    """
    toml_without_username = tmp_path / "missing_username.toml"
    toml_without_username.write_text(
        """
[host1]
ip = "1.1.1.1"
port = 22
"""
    )

    hosts, max_len = _get_hosts_from_toml(str(toml_without_username), None)
    captured = capsys.readouterr()

    assert hosts == []
    assert max_len == 0
    assert "is missing 'username' or 'username' is not a string" in captured.out


def test_get_hosts_from_toml_invalid_tags(tmp_path, capsys):
    """
    Test that _get_hosts_from_toml handles invalid tags gracefully.
    """
    toml_with_invalid_tags = tmp_path / "invalid_tags.toml"
    toml_with_invalid_tags.write_text(
        """
[host1]
ip = "1.1.1.1"
port = 22
username = "user1"
tags = "not-a-list"
"""
    )

    hosts, max_len = _get_hosts_from_toml(str(toml_with_invalid_tags), None)
    captured = capsys.readouterr()

    assert len(hosts) == 1
    assert max_len == 5
    assert "invalid 'tags' (must be a list of strings)" in captured.out


def test_get_hosts_from_toml_invalid_port(tmp_path, capsys):
    """
    Test that _get_hosts_from_toml handles an invalid port gracefully.
    """
    toml_with_invalid_port = tmp_path / "invalid_port.toml"
    toml_with_invalid_port.write_text(
        """
[host1]
ip = "1.1.1.1"
port = "not-a-number"
username = "user1"
"""
    )

    hosts, max_len = _get_hosts_from_toml(str(toml_with_invalid_port), None)
    captured = capsys.readouterr()

    assert hosts == []
    assert max_len == 0
    assert "Error parsing port for host 'host1'" in captured.out


@patch(
    "ananta.config._load_toml_data", side_effect=Exception("Unexpected error")
)
def test_get_hosts_from_toml_unexpected_error(mock_load, capsys):
    """
    Test that _get_hosts_from_toml handles an unexpected error gracefully.
    """
    hosts, max_len = _get_hosts_from_toml("dummy_path.toml", None)
    captured = capsys.readouterr()

    assert hosts == []
    assert max_len == 0
    assert "An unexpected error occurred" in captured.out


@patch("builtins.open", side_effect=Exception("Unexpected error"))
def test_get_hosts_from_csv_unexpected_error(mock_open, capsys):
    """
    Test that _get_hosts_from_csv handles an unexpected error gracefully.
    """
    hosts, max_len = _get_hosts_from_csv("dummy_path.csv", None)
    captured = capsys.readouterr()

    assert hosts == []
    assert max_len == 0
    assert "An unexpected error occurred" in captured.out


def test_get_hosts_unknown_extension(tmp_path, capsys):
    """
    Test that get_hosts handles an unknown file extension gracefully.
    """
    unknown_ext_file = tmp_path / "hosts.txt"
    unknown_ext_file.write_text("host1,1.1.1.1,22,user1")

    hosts, max_len = get_hosts(str(unknown_ext_file), None)
    captured = capsys.readouterr()

    assert len(hosts) == 1
    assert max_len == 5
    assert "Warning: Unknown or missing host file extension" in captured.out


def test_get_hosts_empty_path():
    """
    Test that get_hosts handles an empty path gracefully.
    """
    hosts, max_len = get_hosts("", None)

    assert hosts == []
    assert max_len == 0


def test_get_hosts_from_csv_incomplete_row(tmp_path, capsys):
    """
    Test that _get_hosts_from_csv handles an incomplete row gracefully.
    """
    incomplete_csv = tmp_path / "incomplete.csv"
    incomplete_csv.write_text("host1,1.1.1.1,22")

    hosts, max_len = _get_hosts_from_csv(str(incomplete_csv), None)
    captured = capsys.readouterr()

    assert hosts == []
    assert max_len == 0
    assert "row 1 is incomplete" in captured.out


def test_get_hosts_from_csv_invalid_port(tmp_path, capsys):
    """
    Test that _get_hosts_from_csv handles an invalid port gracefully.
    """
    invalid_port_csv = tmp_path / "invalid_port.csv"
    invalid_port_csv.write_text("host1,1.1.1.1,not-a-number,user1")

    hosts, max_len = _get_hosts_from_csv(str(invalid_port_csv), None)
    captured = capsys.readouterr()

    assert hosts == []
    assert max_len == 0
    assert "parse error at row 1" in captured.out


def test_get_hosts_from_csv_file_not_found(capsys):
    """
    Test that _get_hosts_from_csv handles a FileNotFoundError gracefully.
    """
    hosts, max_len = _get_hosts_from_csv("non_existent_file.csv", None)
    captured = capsys.readouterr()

    assert hosts == []
    assert max_len == 0
    assert "Error: CSV hosts file not found" in captured.out
