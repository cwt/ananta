import csv
import os
import sys
from typing import Any

from . import UNSPECIFIED_KEY_PATH

# A host record: (name, ip/hostname, ssh port, username, key_path, timeout, retries)
Host = tuple[str, str, int, str, str, float, int]

# Conditional import for TOML parsing
if sys.version_info >= (3, 11):
    import tomllib
else:
    try:
        import tomli as tomllib  # Alias tomli as tomllib for consistent use
    except ImportError:
        tomllib = None  # type: ModuleType | None


def _load_toml_data(toml_file_path: str) -> dict[str, Any]:
    """
    Loads data from a TOML file using the appropriate library (tomllib or tomli).
    Raises RuntimeError if tomli is needed but not installed on Python < 3.11.
    """
    if tomllib:
        with open(
            toml_file_path, "rb"
        ) as f:  # tomllib.load or tomli.load expects a binary file
            return tomllib.load(f)
    else:
        # This case should only be hit on Python < 3.11 if tomli failed to import
        raise RuntimeError(
            f"TOML host file ('{os.path.basename(toml_file_path)}') requires "
            "'tomli' to be installed on Python < 3.11. It should have been "
            "installed automatically with Ananta if using Python < 3.11. "
            "If not, please try reinstalling Ananta: "
            "pip install ananta --force-reinstall"
        )


def _validate_port(port: int) -> int:
    """Validate that port is in valid range 1-65535."""
    if not (1 <= port <= 65535):
        raise ValueError(f"Port {port} is not in valid range 1-65535")
    return port


def _validate_timeout(timeout: float) -> float:
    """Validate that timeout is positive."""
    if timeout <= 0:
        raise ValueError(f"Timeout {timeout} must be positive")
    return timeout


def _validate_retries(retries: int) -> int:
    """Validate that retries is non-negative."""
    if retries < 0:
        raise ValueError(f"Retries {retries} must be non-negative")
    return retries


def _deduplicate_hosts(hosts: list[Host]) -> list[Host]:
    """Detect and rename duplicate host names with a numeric suffix."""
    seen_counts: dict[str, int] = {}
    assigned_names: set[str] = set()
    result: list[Host] = []
    for host in hosts:
        name = host[0]
        if name in assigned_names or name in seen_counts:
            count = seen_counts.get(name, 0) + 1
            new_name = f"{name}-{count}"
            while new_name in assigned_names:
                count += 1
                new_name = f"{name}-{count}"
            seen_counts[name] = count
            assigned_names.add(new_name)
            print(
                f"Warning: Duplicate host name '{name}' renamed to '{new_name}'"
            )
            result.append((new_name, *host[1:]))
        else:
            seen_counts[name] = 0
            assigned_names.add(name)
            result.append(host)
    return result


def _finalize_hosts(
    hosts: list[Host],
) -> tuple[list[Host], int]:
    """Deduplicate hosts and compute the display width of the longest name."""
    if not hosts:
        return [], 0
    hosts = _deduplicate_hosts(hosts)
    max_name_length = max(len(name) for name, *_ in hosts)
    return hosts, max_name_length


def _get_hosts_from_toml(
    toml_file_path: str, host_tags_filter_str: str | None
) -> tuple[list[Host], int]:
    """
    Reads hosts from a TOML file and returns a list of tuples with host details.
    """
    hosts_to_execute: list[Host] = []
    active_tags_filter: set[str] = (
        set(host_tags_filter_str.split(",")) if host_tags_filter_str else set()
    )

    try:
        data = _load_toml_data(toml_file_path)
    except FileNotFoundError:
        print(f"Error: TOML hosts file not found at '{toml_file_path}'")
        return [], 0
    except RuntimeError as e:
        print(f"Error: {e}")
        return [], 0
    except tomllib.TOMLDecodeError if tomllib else Exception as e:
        print(f"Error decoding TOML file '{toml_file_path}': {e}")
        return [], 0
    except Exception as e:
        print(
            f"An unexpected error occurred while loading TOML file "
            f"'{toml_file_path}': {e}"
        )
        return [], 0

    defaults = data.get("default", {})
    if not isinstance(defaults, dict):
        print(
            f"Warning: Skipping non-dictionary 'default' section in '{toml_file_path}'."
        )
        defaults = {}

    # Validate and set default values
    try:
        default_port = _validate_port(int(defaults.get("port", 22)))
    except (ValueError, TypeError):
        print(f"Warning: Invalid default port in '{toml_file_path}', using 22")
        default_port = 22

    default_username: str | None = defaults.get("username")
    default_key_path: str = defaults.get("key_path", UNSPECIFIED_KEY_PATH)

    # default tags won't be overridden but got appended by host-specific tags
    default_tags: list[str] = defaults.get("tags", [])
    if not isinstance(default_tags, list) or not all(
        isinstance(tag, str) for tag in default_tags
    ):
        print(
            f"Warning: Invalid default 'tags' in '{toml_file_path}' "
            "(must be a list of strings). Ignoring default tags."
        )
        default_tags = []

    try:
        default_timeout = _validate_timeout(float(defaults.get("timeout", 5.0)))
    except (ValueError, TypeError):
        print(
            f"Warning: Invalid default timeout in '{toml_file_path}', using 5.0"
        )
        default_timeout = 5.0

    try:
        default_retries = _validate_retries(int(defaults.get("retries", 2)))
    except (ValueError, TypeError):
        print(
            f"Warning: Invalid default retries in '{toml_file_path}', using 2"
        )
        default_retries = 2

    for host_name, host_config in data.items():
        if host_name == "default":
            continue
        if not isinstance(host_config, dict):
            print(
                f"Warning: Skipping non-dictionary section '{host_name}' in "
                f"TOML file '{toml_file_path}'."
            )
            continue

        ip_address: str | None = host_config.get("ip")
        # ip_address accepts both IP address and resolvable hostname
        if not ip_address or not isinstance(ip_address, str):
            print(
                f"Warning: Host '{host_name}' in '{toml_file_path}' is missing "
                "'ip' or 'ip' is not a string. Skipping!"
            )
            continue

        try:
            port_str = host_config.get("port", default_port)
            ssh_port = int(port_str)
            ssh_port = _validate_port(ssh_port)
            username = host_config.get("username", default_username)
            if not username or not isinstance(username, str):
                print(
                    f"Warning: Host '{host_name}' in '{toml_file_path}' is missing "
                    "'username' or 'username' is not a string. Skipping!"
                )
                continue
            key_path = str(host_config.get("key_path", default_key_path))
            try:
                timeout = _validate_timeout(
                    float(host_config.get("timeout", default_timeout))
                )
            except (ValueError, TypeError):
                print(
                    f"Warning: Invalid timeout for host '{host_name}' in '{toml_file_path}', using {default_timeout}"
                )
                timeout = default_timeout
            try:
                retries = _validate_retries(
                    int(host_config.get("retries", default_retries))
                )
            except (ValueError, TypeError):
                print(
                    f"Warning: Invalid retries for host '{host_name}' in '{toml_file_path}', using {default_retries}"
                )
                retries = default_retries
            current_host_tags_list: list[str] = host_config.get("tags", [])
            if not isinstance(current_host_tags_list, list) or not all(
                isinstance(tag, str) for tag in current_host_tags_list
            ):
                print(
                    f"Warning: Host '{host_name}' in '{toml_file_path}' has "
                    "invalid 'tags' (must be a list of strings). Treating as no tags."
                )
                current_host_tags_list = []

            if (
                not active_tags_filter
                or not active_tags_filter.isdisjoint(default_tags)
                or not active_tags_filter.isdisjoint(current_host_tags_list)
            ):
                hosts_to_execute.append(
                    (
                        host_name,
                        ip_address,
                        ssh_port,
                        username,
                        key_path,
                        timeout,
                        retries,
                    )
                )
        except ValueError as error:
            if "Port" in str(error):
                print(
                    f"Hosts file (TOML) '{toml_file_path}': Error parsing port for "
                    f"host '{host_name}': {error}. Skipping!"
                )
            else:
                print(
                    f"Hosts file (TOML) '{toml_file_path}': Error parsing port for "
                    f"host '{host_name}'. Port must be an integer. Skipping!"
                )
        except Exception as e:
            print(
                f"Hosts file (TOML) '{toml_file_path}': Unexpected error processing "
                f"host '{host_name}': {e}. Skipping!"
            )

    return _finalize_hosts(hosts_to_execute)


def _get_hosts_from_csv(
    csv_file_path: str, host_tags_filter_str: str | None
) -> tuple[list[Host], int]:
    """
    Reads hosts from a CSV file and returns a list of tuples with host details.
    """
    hosts_to_execute: list[Host] = []
    active_tags_filter: set[str] = (
        set(host_tags_filter_str.split(",")) if host_tags_filter_str else set()
    )

    try:
        with open(csv_file_path, "r", encoding="utf-8") as hosts_file_obj:
            csv_reader = csv.reader(hosts_file_obj)
            for row_line, row in enumerate(csv_reader, start=1):
                if not row or row[0].startswith("#"):
                    continue

                # Check for minimum number of columns before unpacking
                if len(row) < 4:
                    print(
                        f"Hosts file (CSV): '{csv_file_path}' row {row_line} is incomplete "
                        "(expected at least 4 columns for name, ip, port, user). Skipping!"
                    )
                    continue

                try:
                    host_name, ip_address, str_port, username = row[:4]
                    ssh_port = _validate_port(
                        int(str_port)
                    )  # ValueError here is specific to port format

                    key_path = row[4] if len(row) > 4 else ""
                    tags_in_csv_str = row[5] if len(row) > 5 else ""
                except ValueError:  # Catches error from int(str_port)
                    print(
                        f"Hosts file (CSV): '{csv_file_path}' parse error at row {row_line} "
                        "(port must be an integer). Skipping!"
                    )
                    continue
                # IndexError for key_path or tags_in_csv_str is avoided by conditional access

                tags_list = (
                    tags_in_csv_str.split(":") if tags_in_csv_str else []
                )
                if not active_tags_filter or not active_tags_filter.isdisjoint(
                    tags_list
                ):
                    hosts_to_execute.append(
                        (
                            host_name,
                            ip_address,
                            ssh_port,
                            username,
                            key_path,
                            5.0,
                            2,
                        )
                    )
    except FileNotFoundError:
        print(f"Error: CSV hosts file not found at '{csv_file_path}'")
        return [], 0
    except Exception as e:
        print(
            f"An unexpected error occurred while reading CSV file '{csv_file_path}': {e}"
        )
        return [], 0

    return _finalize_hosts(hosts_to_execute)


def get_hosts(
    host_file_path: str, host_tags: str | None
) -> tuple[list[Host], int]:
    """
    Reads hosts from a file (TOML or CSV) and returns a list of tuples with host details.
    """
    if not host_file_path:
        return [], 0
    _root, file_ext = os.path.splitext(host_file_path.lower())
    if file_ext == ".toml":
        return _get_hosts_from_toml(host_file_path, host_tags)
    elif file_ext == ".csv":
        return _get_hosts_from_csv(host_file_path, host_tags)
    else:
        print(
            f"Warning: Unknown or missing host file extension for "
            f"'{os.path.basename(host_file_path)}'. Attempting to parse as CSV."
        )
        return _get_hosts_from_csv(host_file_path, host_tags)
