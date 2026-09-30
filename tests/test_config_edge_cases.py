from unittest.mock import patch

import pytest

from ananta.config import (
    UNSPECIFIED_KEY_PATH,
    _get_hosts_from_csv,
    _get_hosts_from_toml,
    _load_toml_data,
    get_hosts,
)

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
    toml_with_invalid_section.write_text("""
[host1]
ip = "1.1.1.1"
port = 22
username = "user1"

[invalid_section]
this = "is not a dictionary of hosts"
""")

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
    toml_without_username.write_text("""
[host1]
ip = "1.1.1.1"
port = 22
""")

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
    toml_with_invalid_tags.write_text("""
[host1]
ip = "1.1.1.1"
port = 22
username = "user1"
tags = "not-a-list"
""")

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
    toml_with_invalid_port.write_text("""
[host1]
ip = "1.1.1.1"
port = "not-a-number"
username = "user1"
""")

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
    assert "must be an integer" in captured.out


def test_get_hosts_from_csv_out_of_range_port(tmp_path, capsys):
    """
    Test that _get_hosts_from_csv handles an out-of-range port gracefully.
    """
    out_of_range_csv = tmp_path / "out_of_range_port.csv"
    out_of_range_csv.write_text("host1,1.1.1.1,70000,user1")

    hosts, max_len = _get_hosts_from_csv(str(out_of_range_csv), None)
    captured = capsys.readouterr()

    assert hosts == []
    assert max_len == 0
    assert "Port 70000 is not in valid range 1-65535" in captured.out


def test_get_hosts_from_csv_file_not_found(capsys):
    """
    Test that _get_hosts_from_csv handles a FileNotFoundError gracefully.
    """
    hosts, max_len = _get_hosts_from_csv("non_existent_file.csv", None)
    captured = capsys.readouterr()

    assert hosts == []
    assert max_len == 0
    assert "Error: CSV hosts file not found" in captured.out


def test_get_hosts_from_toml_invalid_defaults_non_dict(tmp_path, capsys):
    """
    Test that _get_hosts_from_toml handles a non-dictionary 'default' section gracefully.
    """
    toml_with_invalid_default = tmp_path / "invalid_default.toml"
    toml_with_invalid_default.write_text("""
default = "not-a-dictionary"
[host1]
ip = "1.1.1.1"
username = "user1"
""")

    hosts, max_len = _get_hosts_from_toml(str(toml_with_invalid_default), None)
    captured = capsys.readouterr()

    assert len(hosts) == 1
    assert max_len == 5
    assert "Skipping non-dictionary 'default' section" in captured.out


def test_get_hosts_from_toml_invalid_default_tags(tmp_path, capsys):
    """
    Test that _get_hosts_from_toml handles non-list 'tags' in 'default' gracefully.
    """
    toml_with_invalid_default_tags = tmp_path / "invalid_default_tags.toml"
    toml_with_invalid_default_tags.write_text("""
[default]
tags = "not-a-list"
[host1]
ip = "1.1.1.1"
username = "user1"
""")

    hosts, max_len = _get_hosts_from_toml(
        str(toml_with_invalid_default_tags), None
    )
    captured = capsys.readouterr()

    assert len(hosts) == 1
    assert max_len == 5
    assert "Invalid default 'tags'" in captured.out


def test_get_hosts_from_csv_duplicate_names(tmp_path, capsys):
    """Test that duplicate host names in CSV are detected and renamed."""
    csv_file = tmp_path / "hosts.csv"
    csv_file.write_text(
        "name,ip,port,user\n"
        "host-a,10.0.0.1,22,user1\n"
        "host-b,10.0.0.2,22,user2\n"
        "host-a,10.0.0.3,22,user3\n"
    )
    hosts, _ = _get_hosts_from_csv(str(csv_file), None)
    captured = capsys.readouterr()

    assert len(hosts) == 3
    assert hosts[0][0] == "host-a"
    assert hosts[1][0] == "host-b"
    assert hosts[2][0] == "host-a-1"
    assert "Duplicate host name 'host-a' renamed to 'host-a-1'" in captured.out


def test_get_hosts_from_toml_duplicate_names(tmp_path, capsys):
    """Test that TOML parser naturally prevents duplicate section names.

    TOML spec does not allow duplicate keys, so the last definition wins
    and no deduplication is needed at the config layer.
    """
    toml_file = tmp_path / "hosts.toml"
    toml_file.write_text(
        '[host-x]\nip = "10.0.0.1"\nusername = "user1"\n'
        '[host-y]\nip = "10.0.0.2"\nusername = "user2"\n'
    )
    hosts, _ = _get_hosts_from_toml(str(toml_file), None)
    captured = capsys.readouterr()

    assert len(hosts) == 2
    assert hosts[0][0] == "host-x"
    assert hosts[1][0] == "host-y"
    assert "Duplicate" not in captured.out


def test_get_hosts_from_csv_duplicate_names_with_existing_suffix(
    tmp_path, capsys
):
    """Test that duplicates avoid colliding with names that already exist with suffixes."""
    csv_file = tmp_path / "hosts.csv"
    csv_file.write_text(
        "name,ip,port,user\n"
        "host-a,10.0.0.1,22,user1\n"
        "host-a-1,10.0.0.2,22,user2\n"
        "host-a,10.0.0.3,22,user3\n"
    )
    hosts, _ = _get_hosts_from_csv(str(csv_file), None)
    captured = capsys.readouterr()

    assert len(hosts) == 3
    assert hosts[0][0] == "host-a"
    assert hosts[1][0] == "host-a-1"
    assert hosts[2][0] == "host-a-2"
    assert "Duplicate host name 'host-a' renamed to 'host-a-2'" in captured.out


def test_deduplicate_preserves_legit_suffix_name(capsys):
    """A legit name colliding with a generated rename must keep its name."""
    from ananta.config import _deduplicate_hosts

    def make_host(name, ip):
        return (name, ip, 22, "u", "#", 5.0, 2)

    hosts = [
        make_host("a", "1.1.1.1"),
        make_host("a", "2.2.2.2"),
        make_host("a-1", "3.3.3.3"),
    ]
    result = _deduplicate_hosts(hosts)
    captured = capsys.readouterr()
    assert [h[0] for h in result] == ["a", "a-2", "a-1"]
    assert "Duplicate host name 'a' renamed to 'a-2'" in captured.out
    assert "Duplicate host name 'a-1'" not in captured.out


def test_get_hosts_from_csv_indented_comments_and_blank_lines(tmp_path, capsys):
    """Test that CSV rows with leading whitespace before '#' and blank lines are ignored."""
    csv_file = tmp_path / "hosts.csv"
    csv_file.write_text(
        "   # Indented comment line\n"
        "\n"
        "   \n"
        "host-1,10.0.0.1,22,user1\n"
        "\t# Tab-indented comment\n"
        "host-2,10.0.0.2,22,user2\n"
    )
    hosts, _ = _get_hosts_from_csv(str(csv_file), None)
    captured = capsys.readouterr()

    assert len(hosts) == 2
    assert hosts[0][0] == "host-1"
    assert hosts[1][0] == "host-2"
    assert "incomplete" not in captured.out
    assert "empty required fields" not in captured.out


def test_get_hosts_from_toml_strips_whitespace_fields(tmp_path):
    """Test that TOML ip, username, and key_path fields are stripped of surrounding whitespace."""
    toml_file = tmp_path / "whitespace_hosts.toml"
    toml_file.write_text("""
[host1]
ip = "  192.168.1.10  "
port = 22
username = "  admin  "
key_path = "  /path/to/key  "
""")
    hosts, _ = _get_hosts_from_toml(str(toml_file), None)
    assert len(hosts) == 1
    host = hosts[0]
    assert host[1] == "192.168.1.10"
    assert host[3] == "admin"
    assert host[4] == "/path/to/key"


def test_get_hosts_from_toml_whitespace_only_key_path_normalizes(tmp_path):
    """Test that whitespace-only key_path in TOML falls back to UNSPECIFIED_KEY_PATH."""
    toml_file = tmp_path / "blank_key_path.toml"
    toml_file.write_text("""
[host1]
ip = "192.168.1.10"
port = 22
username = "admin"
key_path = "    "
""")
    hosts, _ = _get_hosts_from_toml(str(toml_file), None)
    assert len(hosts) == 1
    assert hosts[0][4] == UNSPECIFIED_KEY_PATH


def test_get_hosts_from_toml_whitespace_only_ip_or_user_skipped(
    tmp_path, capsys
):
    """Test that hosts with whitespace-only ip or username are rejected with warnings."""
    toml_file = tmp_path / "empty_fields.toml"
    toml_file.write_text("""
[empty_ip]
ip = "   "
username = "admin"

[empty_user]
ip = "192.168.1.10"
username = "   "
""")
    hosts, _ = _get_hosts_from_toml(str(toml_file), None)
    captured = capsys.readouterr()

    assert hosts == []
    assert "missing 'ip' or 'ip' is not a string" in captured.out
    assert "missing 'username' or 'username' is not a string" in captured.out


def test_strict_validators_reject_bad_values():
    """Bool, NaN, inf and truncated floats must be rejected."""
    import math

    from ananta.config import (
        _parse_port_value,
        _parse_retries_value,
        _parse_timeout_value,
        _validate_port,
        _validate_retries,
        _validate_timeout,
    )

    with pytest.raises(ValueError):
        _validate_timeout(float("nan"))
    with pytest.raises(ValueError):
        _validate_timeout(float("inf"))
    with pytest.raises(ValueError):
        _validate_timeout(True)
    with pytest.raises(ValueError):
        _validate_port(True)
    with pytest.raises(ValueError):
        _validate_retries(True)
    with pytest.raises(ValueError):
        _parse_port_value(True)
    with pytest.raises(ValueError):
        _parse_port_value(22.9)
    with pytest.raises(ValueError):
        _parse_retries_value(True)
    with pytest.raises(ValueError):
        _parse_retries_value(2.9)
    with pytest.raises(ValueError):
        _parse_timeout_value(float("nan"))
    with pytest.raises(ValueError):
        _parse_timeout_value(float("inf"))
    assert math.isclose(_parse_timeout_value(5), 5.0)
    assert _parse_port_value(22) == 22
    assert _parse_port_value(22.0) == 22
    assert _parse_retries_value(2) == 2


def test_toml_invalid_timeout_and_port_fall_back(tmp_path, capsys):
    """NaN timeout, bool port and float port fall back to defaults."""
    toml_file = tmp_path / "bad_values.toml"
    toml_file.write_text(
        "[default]\n"
        'username = "u"\n'
        "port = true\n"
        "timeout = nan\n"
        "retries = true\n"
        "\n"
        "[h1]\n"
        'ip = "1.1.1.1"\n'
        "\n"
        "[h2]\n"
        'ip = "2.2.2.2"\n'
        "port = 22.9\n"
    )
    hosts, _ = _get_hosts_from_toml(str(toml_file), None)
    captured = capsys.readouterr()
    assert len(hosts) == 1
    assert hosts[0][0] == "h1"
    assert hosts[0][2] == 22
    assert hosts[0][5] == 5.0
    assert hosts[0][6] == 2
    assert "Invalid default port" in captured.out
    assert "Invalid default timeout" in captured.out
    assert "Invalid default retries" in captured.out
    assert "h2" in captured.out


def test_toml_dotted_table_hint_and_quoted_name(tmp_path, capsys):
    """Dotted sections hint at quoting; quoted dotted names parse as one host."""
    dotted = tmp_path / "dotted.toml"
    dotted.write_text('[web.1]\nip = "1.2.3.4"\nusername = "u"\n')
    hosts, _ = _get_hosts_from_toml(str(dotted), None)
    captured = capsys.readouterr()
    assert hosts == []
    assert "missing 'ip'" in captured.out
    assert "quote it" in captured.out

    quoted = tmp_path / "quoted.toml"
    quoted.write_text('["web.1"]\nip = "1.2.3.4"\nusername = "u"\n')
    hosts, _ = _get_hosts_from_toml(str(quoted), None)
    assert len(hosts) == 1
    assert hosts[0][0] == "web.1"
    assert hosts[0][1] == "1.2.3.4"
