from typing import List, Tuple, Dict, Any, Set
import csv
import os
import sys

# Conditional import for TOML parsing
if sys.version_info >= (3, 11):
    import tomllib  # pylint: disable=unused-import
else:
    try:
        import tomli as tomllib  # Alias tomli as tomllib for consistent use
    except ImportError:
        tomllib = None  # type: ModuleType | None


def _load_toml_data(toml_file_path: str) -> Dict[str, Any]:
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


def _get_hosts_from_toml(
    toml_file_path: str, host_tags_filter_str: str | None
) -> Tuple[List[Tuple[str, str, int, str, str]], int]:
    """
    Reads hosts from a TOML file and returns a list of tuples with host details.
    """
    hosts_to_execute: List[Tuple[str, str, int, str, str]] = []
    active_tags_filter: Set[str] = (
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

    defaults: Dict[str, Any] = data.get("default", {})
    default_port: int = defaults.get("port", 22)
    default_username: str | None = defaults.get("username")
    default_key_path: str = defaults.get("key_path", "#")
    # default tags won't be overridden but got appended by host-specific tags
    default_tags: List[str] = defaults.get("tags", [])

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
            username = host_config.get("username", default_username)
            if not username or not isinstance(username, str):
                print(
                    f"Warning: Host '{host_name}' in '{toml_file_path}' is missing "
                    "'username' or 'username' is not a string. Skipping!"
                )
                continue
            key_path = str(host_config.get("key_path", default_key_path))
            current_host_tags_list: List[str] = host_config.get("tags", [])
            if not isinstance(current_host_tags_list, list) or not all(
                isinstance(tag, str) for tag in current_host_tags_list
            ):
                print(
                    f"Warning: Host '{host_name}' in '{toml_file_path}' has "
                    "invalid 'tags' (must be a list of strings). Treating as no tags."
                )
                current_host_tags_set: Set[str] = set()
            else:
                # Append default tags to host-specific tags
                current_host_tags_set = set(
                    default_tags + current_host_tags_list
                )
            if not active_tags_filter or active_tags_filter.intersection(
                current_host_tags_set
            ):
                hosts_to_execute.append(
                    (host_name, ip_address, ssh_port, username, key_path)
                )
        except ValueError:
            print(
                f"Hosts file (TOML) '{toml_file_path}': Error parsing port for "
                f"host '{host_name}'. Port must be an integer. Skipping!"
            )
        except Exception as e:
            print(
                f"Hosts file (TOML) '{toml_file_path}': Unexpected error processing "
                f"host '{host_name}': {e}. Skipping!"
            )

    if hosts_to_execute:
        max_name_length = max(len(name) for name, *_ in hosts_to_execute)
        return hosts_to_execute, max_name_length
    return [], 0


def _get_hosts_from_csv(
    csv_file_path: str, host_tags_filter_str: str | None
) -> Tuple[List[Tuple[str, str, int, str, str]], int]:
    """
    Reads hosts from a CSV file and returns a list of tuples with host details.
    """
    hosts_to_execute: List[Tuple[str, str, int, str, str]] = []
    active_tags_filter: Set[str] = (
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
                    ssh_port = int(
                        str_port
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

                current_host_tags_set: Set[str] = (
                    set(tags_in_csv_str.split(":"))
                    if tags_in_csv_str
                    else set()
                )
                if not active_tags_filter or active_tags_filter.intersection(
                    current_host_tags_set
                ):
                    hosts_to_execute.append(
                        (host_name, ip_address, ssh_port, username, key_path)
                    )
    except FileNotFoundError:
        print(f"Error: CSV hosts file not found at '{csv_file_path}'")
        return [], 0
    except Exception as e:
        print(
            f"An unexpected error occurred while reading CSV file '{csv_file_path}': {e}"
        )
        return [], 0

    if hosts_to_execute:
        max_name_length = max(len(name) for name, *_ in hosts_to_execute)
        return hosts_to_execute, max_name_length
    return [], 0


def get_hosts(
    host_file_path: str, host_tags: str | None
) -> Tuple[List[Tuple[str, str, int, str, str]], int]:
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
