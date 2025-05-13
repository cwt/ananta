from typing import List, Tuple
import csv


def get_hosts(host_file: str, host_tags: str | None) -> Tuple[List, int]:
    """Read the hosts file and return a list of hosts to execute commands on."""
    hosts_to_execute: List[Tuple[str, str, int, str, str]] = []
    execute_tags = host_tags.split(",") if host_tags else []

    with open(host_file, "r", encoding="utf-8") as hosts:
        for row_line, row in enumerate(
            csv.reader(hosts), start=1
        ):  # Row line starts at 1 for human readability
            if row and not row[0].startswith("#"):
                # Process the row only if it is not empty and not a comment
                try:
                    host_name, ip_address, str_port, username = row[:4]
                    ssh_port = int(str_port)  # Port number must be an integer
                    key_path = row[4] if len(row) > 4 else ""  # Optional
                    tags = row[5] if len(row) > 5 else ""  # Optional
                except IndexError:
                    print(
                        f"Hosts file: {host_file} row {row_line} is incomplete. Skipping!"
                    )
                except ValueError:
                    print(
                        f"Hosts file: {host_file} parse error at row {row_line}. Skipping!"
                    )
                else:
                    if host_tags is None or set(tags.split(":")).intersection(
                        set(execute_tags)
                    ):
                        hosts_to_execute.append(
                            (
                                host_name,
                                ip_address,
                                ssh_port,
                                username,
                                key_path,
                            )
                        )

    if hosts_to_execute:
        max_name_length = max(len(name) for name, *_ in hosts_to_execute)
        return (hosts_to_execute, max_name_length)
    return ([], 0)
