# Ananta (formerly Hydra)

Ananta is a *powerful* command-line tool designed to simplify simultaneous SSH command execution across multiple remote hosts. It enhances workflows, automates repetitive tasks, and improves efficiency for system administrators and developers managing distributed systems.

## Namesake

Ananta draws inspiration from Ananta Shesha or Ananta Nagaraja (อนันตนาคราช), the many-headed serpentine demigod from Hindu mythology deeply rooted in Thai culture.

Initially, this project was named Hydra, referencing the many-headed serpent in Greek mythology. However, due to the abundance of projects named Hydra or hydra-* on PyPI (e.g., the previous project at [https://pypi.org/project/hydra-ssh/](https://pypi.org/project/hydra-ssh/)), it was renamed to Ananta. The commands you now use are `ananta`, which is shorter, more distinctive, and easier to remember than `hydra-ssh`.

## Features

- Concurrent execution of commands across multiple remote hosts
- Flexible host list configuration in **TOML** or **CSV** format
- SSH authentication with public key support
- Lightweight and user-friendly command-line interface
- Color-coded output for easy host differentiation
- Option to separate host outputs for clarity
- Support for cursor control codes for specific layouts (e.g., `fastfetch`, `neofetch`)

## Installation

### System Requirements

- Python 3.10 or higher
- `pip` package manager
- Required dependencies: `asyncssh`, `argparse`, `asyncio`
- Optional: `uvloop` (Unix-based systems) or `winloop` (Windows) for enhanced performance
- For TOML host files on Python 3.10: `tomli` (automatically installed)

### Installing via pip

Install Ananta using pip:

```bash
pip install ananta --user
```

Install Ananta with `uvloop` or `winloop` for *speed* enhancement:

```bash
pip install ananta[speed] --user
```

**Note:** Ensure Python 3.10 or higher is installed. For TOML host files, Python 3.10 requires `tomli`, while Python 3.11 and above use the built-in `tomllib`. If you previously used `hydra-ssh`, update to `pip install ananta` to get the latest version.

## Usage

### Hosts File Format

Ananta supports host files in **TOML** or **CSV** format, allowing flexible configuration of remote hosts. Below are the structures for each format.
***Note:** The TOML format is recommended for its clarity and ease of use. Any hosts file without `.toml` extension will be treated as a CSV file.*

#### TOML Host File

Create a TOML file with a `[default]` section (optional) and host sections. Example:

```toml
[default]
port = 22
username = "user"
key_path = "#"
tags = ["common"]

[host-1]
ip = "10.0.0.1"
port = 2222
key_path = "/home/user/.ssh/id_ed25519"

[host-2]
ip = "10.0.0.2"
tags = ["web"]

[host-3]
ip = "10.0.0.3"
tags = ["arch", "web"]

["host-4"]
ip = "10.0.0.4"
tags = ["ubuntu", "db"]
```

- **[default] Section**:
  - Optional section to set default values for `port`, `username`, `key_path`, and `tags`.
  - `key_path` can be `#` to use the default SSH key which can be specified via `-k` or common keys in `~/.ssh/`.
  - Fields not specified in a host section will use these defaults (except `ip`, which is required).
  - `tags`: Default tags applied to all hosts, appended to host-specific tags.
- **Host Sections**:
  - Each section (e.g., `[host-1]`) defines a host with the following fields to override defaults:
    - `ip`: Required IP address or resolvable hostname
    - `port`: SSH port
    - `username`: SSH username
    - `key_path`: Path to SSH private key
    - `tags`: Optional list of tags (e.g., `["web", "prod"]`)
- **Tags**:
  - Tags from `[default]` are *appended* to tags specified in each host section.
  - For example, if `default.tags = ["common"]` and `host-3.tags = ["arch", "web"]`, `host-3` will have tags `["common", "arch", "web"]`.
  - Use the `-t` option to filter hosts by tags (e.g., `-t common,web` matches hosts with any of these tags).
- **Note**: TOML parsing requires `tomli` on Python 3.10 (included in Ananta's dependencies) or `tomllib` on Python 3.11 and above.

#### CSV Host File

Create a CSV file with the following structure:

```csv
#alias,ip,port,username,key_path,tags(optional - colon separated)
host-1,10.0.0.1,2222,user,/home/user/.ssh/id_ed25519
host-2,10.0.0.2,22,user,#,web
host-3,10.0.0.3,22,user,#,arch:web
host-4,10.0.0.4,22,user,#,ubuntu:db
```

- Lines starting with `#` are ignored.
- **Fields**:
  - `alias`: Unique name for the host
  - `ip`: IP address or resolvable hostname
  - `port`: SSH port number
  - `username`: SSH username
  - `key_path`: Path to SSH private key, or `#` to use the default key (via `-k` or common keys in `~/.ssh/`)
  - `tags`: Optional tags, separated by colons (e.g., `web:db`)
- **Tags**: Used for filtering hosts with the `-t` option (e.g., `-t web,db`).

### Running Commands

Run commands on remote hosts with:

```bash
ananta <options> [hosts file] [command]
```

**Examples:**

```console
# Run 'uptime' on all hosts in a CSV hosts file
$ ananta hosts.csv uptime

# Run 'sensors' with separate output on all hosts in a CSV hosts file
$ ananta -s host.csv sensors

# Run 'fastfetch' with cursor control enabled and separate output on all hosts in a TOML hosts file
$ ananta -cs hosts.toml fastfetch

# Filter hosts by tags 'web' or 'db' (CSV hosts file)
$ ananta -t web,db hosts.csv uptime

# Filter hosts by tags 'common' or 'web' (TOML hosts file, includes default tags)
$ ananta -t common,web hosts.toml uptime

# Update Arch Linux hosts (TOML hosts file)
$ ananta -t arch hosts.toml sudo pacman -Syu --noconfirm
```

### Options

**Single-letter options are case-insensitive.**

- `-n, --no-color`: Disable colorized output
- `-s, --separate-output`: Display output from each host separately
- `-t, --host-tags`: Filter hosts by tag(s), comma-separated (e.g., `web,db`)
- `-w, --terminal-width`: Manually set terminal width
- `-e, --allow-empty-line`: Permit printing of empty lines
- `-c, --allow-cursor-control`: Enable cursor control codes (e.g., for `fastfetch` or `neofetch`)
- `-v, --version`: Display the Ananta version
- `-k, --default-key`: Specify the default SSH private key path

### Demo

[![asciicast](https://asciinema.org/a/711115.svg)](https://asciinema.org/a/711115)

[![asciicast](https://asciinema.org/a/711116.svg)](https://asciinema.org/a/711116)

## Contributing

We welcome contributions to Ananta! Whether you're fixing bugs, adding features, or improving docs, check out our [CONTRIBUTING.md](CONTRIBUTING.md) for details on how to get started.

## [License](LICENSE)
