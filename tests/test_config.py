from ananta.config import get_hosts
from unittest.mock import patch
import sys

# Sample CSV content for testing
HOSTS_CSV_CONTENT = """# This is a comment line
host-1,10.0.0.1,22,user1,/path/to/key1,web:db
host-2,10.0.0.2,2202,user2,#,web
host-3,10.0.0.3,22,user3,/specific/key3,app
#host-4,10.0.0.4,22,user4,#,disabled
host-5,10.0.0.5,22,user5,#
host-6,10.0.0.6,bad-port-format,user6,#, Tag With Space
"""

# Sample TOML content for testing
HOSTS_TOML_CONTENT_VALID = """
[default]
port = 2222
username = "default_user"
key_path = "/default/key.pem"
tags = ["common"]

[host-toml-1]
ip = "192.168.1.1"

[host-toml-2]
ip = "192.168.1.2"
port = 22
username = "toml_user2"
tags = ["web", "prod"]

[host-toml-3]
ip = "192.168.1.3"
key_path = "#"
tags = ["db", "prod"]

["host-toml-4 with space"]
ip = "192.168.1.4"
username = "another_user"
"""

HOSTS_TOML_CONTENT_NO_DEFAULTS = """
[host-no-default-1]
ip = "10.10.0.1"
port = 22
username = "nodef_user1"
key_path = "/key1.pem"
tags = ["special"]
"""

HOSTS_TOML_CONTENT_MALFORMED_PORT = """
[host-bad-port]
ip = "10.20.0.1"
port = "not-an-integer"
username = "badportuser"
"""

HOSTS_TOML_CONTENT_MISSING_IP = """
[host-missing-ip]
port = 22
username = "noipuser"
"""

HOSTS_TOML_CONTENT_MISSING_USERNAME = """
[default]
username = "default_user_for_test"

[host-missing-username]
ip = "10.30.0.1"
"""

HOSTS_TOML_CONTENT_ONLY_DEFAULT = """
[default]
port = 22
username = "only_default"
"""

# === CSV Tests ===


def test_get_hosts_no_tags(tmp_path):
    """Tests parsing the hosts file without any tag filtering."""
    p = tmp_path / "hosts.csv"
    p.write_text(HOSTS_CSV_CONTENT, encoding="utf-8")

    hosts, max_len = get_hosts(str(p), None)  # host_tags is None

    assert (
        len(hosts) == 4
    )  # host-1, host-2, host-3, host-5 (host-4 is commented, host-6 bad format)
    assert max_len == 6  # Length of "host-1", "host-2", etc.
    assert hosts[0] == ("host-1", "10.0.0.1", 22, "user1", "/path/to/key1")
    assert hosts[1] == ("host-2", "10.0.0.2", 2202, "user2", "#")
    assert hosts[2] == ("host-3", "10.0.0.3", 22, "user3", "/specific/key3")
    assert hosts[3] == ("host-5", "10.0.0.5", 22, "user5", "#")


def test_get_hosts_with_tags(tmp_path):
    """Tests parsing with tag filtering."""
    p = tmp_path / "hosts.csv"
    p.write_text(HOSTS_CSV_CONTENT, encoding="utf-8")

    # Filter for 'web' tag
    hosts_web, max_len_web = get_hosts(str(p), "web")
    assert len(hosts_web) == 2
    assert [h[0] for h in hosts_web] == ["host-1", "host-2"]
    assert max_len_web == 6

    # Filter for 'app' tag
    hosts_app, max_len_app = get_hosts(str(p), "app")
    assert len(hosts_app) == 1
    assert hosts_app[0][0] == "host-3"
    assert max_len_app == 6

    # Filter for multiple tags 'db' or 'app'
    hosts_db_app, max_len_db_app = get_hosts(str(p), "db,app")
    assert len(hosts_db_app) == 2
    assert [h[0] for h in hosts_db_app] == ["host-1", "host-3"]
    assert max_len_db_app == 6

    # Filter for non-existent tag
    hosts_empty, max_len_zero = get_hosts(str(p), "nomatch")
    assert hosts_empty == []
    assert max_len_zero == 0


def test_get_hosts_skips_malformed(tmp_path, capsys):
    """Tests that lines with format errors (like non-integer port) are skipped."""
    p = tmp_path / "hosts.csv"
    p.write_text(
        HOSTS_CSV_CONTENT, encoding="utf-8"
    )  # Includes host-6 with bad port

    hosts, _ = get_hosts(str(p), None)
    assert len(hosts) == 4  # host-6 should be skipped
    assert "host-6" not in [h[0] for h in hosts]

    # Check if the error message was printed (optional, requires capsys fixture)
    captured = capsys.readouterr()
    assert (
        f"Hosts file (CSV): '{str(p)}' parse error at row 7 (port must be an integer). Skipping!"
        in captured.out
    )  # Row numbers start from 1


# === TOML Tests ===


def test_get_hosts_toml_valid_with_defaults(tmp_path):
    """Test parsing TOML hosts file with default values."""
    p = tmp_path / "hosts.toml"
    p.write_text(HOSTS_TOML_CONTENT_VALID, encoding="utf-8")
    hosts, max_len = get_hosts(str(p), None)
    assert len(hosts) == 4
    assert max_len == 22  # Longest host name: "host-toml-4 with space"
    expected_hosts_dict = {
        "host-toml-1": (
            "host-toml-1",
            "192.168.1.1",
            2222,
            "default_user",
            "/default/key.pem",
        ),
        "host-toml-2": (
            "host-toml-2",
            "192.168.1.2",
            22,
            "toml_user2",
            "/default/key.pem",
        ),
        "host-toml-3": (
            "host-toml-3",
            "192.168.1.3",
            2222,
            "default_user",
            "#",
        ),
        "host-toml-4 with space": (
            "host-toml-4 with space",
            "192.168.1.4",
            2222,
            "another_user",
            "/default/key.pem",
        ),
    }
    for host_data in hosts:
        assert host_data == expected_hosts_dict[host_data[0]]


def test_get_hosts_toml_no_defaults(tmp_path):
    """Test parsing TOML hosts file without default section."""
    p = tmp_path / "hosts.toml"
    p.write_text(HOSTS_TOML_CONTENT_NO_DEFAULTS, encoding="utf-8")
    hosts, max_len = get_hosts(str(p), None)
    assert len(hosts) == 1
    assert max_len == 17  # Host name: "host-no-default-1"
    assert hosts[0] == (
        "host-no-default-1",
        "10.10.0.1",
        22,
        "nodef_user1",
        "/key1.pem",
    )


def test_get_hosts_toml_with_tags_filter_on_default_tags(tmp_path):
    """Test parsing TOML hosts file with tag filtering."""
    p = tmp_path / "hosts.toml"
    p.write_text(HOSTS_TOML_CONTENT_VALID, encoding="utf-8")
    hosts_prod, max_len = get_hosts(str(p), "common")
    assert len(hosts_prod) == 4
    assert {h[0] for h in hosts_prod} == {
        "host-toml-1",
        "host-toml-2",
        "host-toml-3",
        "host-toml-4 with space",
    }
    assert max_len == 22  # Longest host name: "host-toml-4 with space"


def test_get_hosts_toml_with_tags_filter(tmp_path):
    """Test parsing TOML hosts file with tag filtering."""
    p = tmp_path / "hosts.toml"
    p.write_text(HOSTS_TOML_CONTENT_VALID, encoding="utf-8")
    hosts_prod, max_len = get_hosts(str(p), "prod")
    assert len(hosts_prod) == 2
    assert {h[0] for h in hosts_prod} == {"host-toml-2", "host-toml-3"}
    assert max_len == 11  # Longest host name: "host-toml-3"


def test_get_hosts_toml_malformed_port(tmp_path, capsys):
    """Test TOML parsing skips hosts with non-integer port."""
    p = tmp_path / "hosts.toml"
    p.write_text(HOSTS_TOML_CONTENT_MALFORMED_PORT, encoding="utf-8")
    hosts, max_len = get_hosts(str(p), None)
    assert len(hosts) == 0
    assert max_len == 0
    captured = capsys.readouterr()
    assert "Error parsing port for host 'host-bad-port'" in captured.out


def test_get_hosts_toml_missing_ip(tmp_path, capsys):
    """Test TOML parsing skips hosts missing IP address."""
    p = tmp_path / "hosts.toml"
    p.write_text(HOSTS_TOML_CONTENT_MISSING_IP, encoding="utf-8")
    hosts, max_len = get_hosts(str(p), None)
    assert len(hosts) == 0
    assert max_len == 0
    captured = capsys.readouterr()
    assert "is missing 'ip' or 'ip' is not a string. Skipping!" in captured.out


def test_get_hosts_toml_missing_username_no_default(tmp_path, capsys):
    """Test TOML parsing skips hosts missing username without default."""
    toml_content_no_user = """
[host-no-user]
ip = "1.2.3.4"
"""
    p = tmp_path / "hosts.toml"
    p.write_text(toml_content_no_user, encoding="utf-8")
    hosts, max_len = get_hosts(str(p), None)
    assert len(hosts) == 0
    assert max_len == 0
    captured = capsys.readouterr()
    assert (
        "is missing 'username' or 'username' is not a string. Skipping!"
        in captured.out
    )


def test_get_hosts_toml_uses_default_username_if_host_missing(tmp_path):
    """Test TOML parsing uses default username if host username is missing."""
    p = tmp_path / "hosts.toml"
    p.write_text(HOSTS_TOML_CONTENT_MISSING_USERNAME, encoding="utf-8")
    hosts, max_len = get_hosts(str(p), None)
    assert len(hosts) == 1
    assert max_len == 21  # Host name: "host-missing-username"
    assert hosts[0][3] == "default_user_for_test"


def test_get_hosts_toml_only_default_section(tmp_path):
    """Test parsing TOML file with only default section returns no hosts."""
    p = tmp_path / "hosts.toml"
    p.write_text(HOSTS_TOML_CONTENT_ONLY_DEFAULT, encoding="utf-8")
    hosts, max_len = get_hosts(str(p), None)
    assert hosts == []
    assert max_len == 0


def test_get_hosts_toml_file_not_found(tmp_path, capsys):
    """Test TOML file not found returns empty hosts list."""
    p = tmp_path / "nonexistent.toml"
    hosts, max_len = get_hosts(str(p), None)
    assert hosts == []
    assert max_len == 0
    captured = capsys.readouterr()
    assert "Error: TOML hosts file not found" in captured.out


@patch("ananta.config.tomllib", None)
@patch("ananta.config.sys.version_info", (3, 10, 0))
def test_get_hosts_toml_python310_tomli_not_installed(tmp_path, capsys):
    """Test TOML parsing fails on Python 3.10 if tomli is not installed."""
    p = tmp_path / "hosts.toml"
    p.write_text(HOSTS_TOML_CONTENT_VALID, encoding="utf-8")
    hosts, max_len = get_hosts(str(p), None)
    assert hosts == []
    assert max_len == 0
    captured = capsys.readouterr()
    assert (
        "TOML host file ('hosts.toml') requires 'tomli' to be installed on Python < 3.11"
        in captured.out
    )


@patch("ananta.config.tomllib.load")
@patch("ananta.config.sys.version_info", (3, 11, 0))
def test_get_hosts_toml_python311_uses_tomllib(mock_tomllib_load, tmp_path):
    """Test TOML parsing on Python 3.11 uses tomllib."""
    p = tmp_path / "hosts.toml"
    p.write_text(HOSTS_TOML_CONTENT_NO_DEFAULTS, encoding="utf-8")
    mock_tomllib_load.return_value = {
        "host-no-default-1": {
            "ip": "10.10.0.1",
            "port": 22,
            "username": "nodef_user1",
            "key_path": "/key1.pem",
            "tags": ["special"],
        }
    }
    hosts, max_len = get_hosts(str(p), None)
    assert len(hosts) == 1
    assert max_len == 17
    assert hosts[0] == (
        "host-no-default-1",
        "10.10.0.1",
        22,
        "nodef_user1",
        "/key1.pem",
    )
    mock_tomllib_load.assert_called_once()


def test_get_hosts_toml_python310_tomli_missing(tmp_path, capsys):
    """Test TOML parsing on Python 3.10 when tomli is not installed."""
    with (
        patch("ananta.config.tomllib", None),
        patch.object(sys, "version_info", (3, 10, 0)),
    ):
        # Import get_hosts after patching to avoid premature module loading
        from ananta.config import get_hosts as test_get_hosts

        p = tmp_path / "hosts.toml"
        p.write_text(HOSTS_TOML_CONTENT_NO_DEFAULTS, encoding="utf-8")
        hosts, max_len = test_get_hosts(str(p), None)
        assert len(hosts) == 0
        assert max_len == 0
        captured = capsys.readouterr()
        assert (
            "TOML host file ('hosts.toml') requires 'tomli' to be installed on Python < 3.11"
            in captured.out
        )


@patch("ananta.config.tomllib.load")
@patch("ananta.config.sys.version_info", (3, 10, 0))
def test_get_hosts_toml_python310_tomli_installed(mock_tomllib_load, tmp_path):
    """Test TOML parsing on Python 3.10 when tomli is installed."""
    p = tmp_path / "hosts.toml"
    p.write_text(HOSTS_TOML_CONTENT_NO_DEFAULTS, encoding="utf-8")
    mock_tomllib_load.return_value = {
        "host-no-default-1": {
            "ip": "10.10.0.1",
            "port": 22,
            "username": "nodef_user1",
            "key_path": "/key1.pem",
            "tags": ["special"],
        }
    }
    hosts, max_len = get_hosts(str(p), None)
    assert len(hosts) == 1
    assert max_len == 17
    assert hosts[0] == (
        "host-no-default-1",
        "10.10.0.1",
        22,
        "nodef_user1",
        "/key1.pem",
    )
    mock_tomllib_load.assert_called_once()


def test_get_hosts_toml_without_ip(tmp_path, capsys):
    """Test handling missing IP in TOML."""
    toml_content = """
[default]
port = 22
[host-1]
ip = "10.0.0.1"
username = "user"
[host-invalid]
invalid = "something"
"""
    p = tmp_path / "hosts.toml"
    p.write_text(toml_content, encoding="utf-8")
    hosts, max_len = get_hosts(str(p), None)
    assert len(hosts) == 1
    assert hosts[0][0] == "host-1"
    captured = capsys.readouterr()
    assert "is missing 'ip' or 'ip' is not a string." in captured.out


def test_get_hosts_toml_invalid_tags(tmp_path, capsys):
    """Test handling invalid tags in TOML (lines 160-164)."""
    toml_content = """
[host-1]
ip = "10.0.0.1"
username = "user"
tags = "not-a-list"
"""
    p = tmp_path / "hosts.toml"
    p.write_text(toml_content, encoding="utf-8")
    hosts, max_len = get_hosts(str(p), None)
    assert len(hosts) == 1  # Host still included, tags treated as empty
    captured = capsys.readouterr()
    assert "invalid 'tags' (must be a list of strings)" in captured.out


def test_get_hosts_csv_incomplete_row(tmp_path, capsys):
    """Test skipping incomplete CSV rows (lines 215, 222-226)."""
    csv_content = """
host-1,10.0.0.1,22,user1,#,web
host-2,10.0.0.2  # Incomplete row
"""
    p = tmp_path / "hosts.csv"
    p.write_text(csv_content, encoding="utf-8")
    hosts, max_len = get_hosts(str(p), None)
    assert len(hosts) == 1
    assert hosts[0][0] == "host-1"
    captured = capsys.readouterr()
    assert "row 3 is incomplete" in captured.out


def test_get_hosts_csv_file_not_found(tmp_path, capsys):
    """Test FileNotFoundError in CSV parsing (lines 193-200)."""
    p = tmp_path / "nonexistent.csv"
    hosts, max_len = get_hosts(str(p), None)
    assert hosts == []
    assert max_len == 0
    captured = capsys.readouterr()
    assert "Error: CSV hosts file not found" in captured.out
