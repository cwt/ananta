"""Mandatory SSH host-key verification for Ananta.

Every connection validates the server's host key against ~/.ssh/known_hosts:

- Known key that matches          -> connect normally
- Missing entry                   -> TOFU: trust, append to known_hosts,
                                     and surface in the post-session report
- Entry present but key differs   -> hard failure; batch dispatch is aborted

The decision logic lives in :class:`HostKeyPolicy`, wired into asyncssh via a
custom ``SSHClient.validate_host_public_key`` hook (see ``make_client_factory``).
"""

import base64
import hashlib
import hmac
import os
import tempfile
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import List, Tuple

import asyncssh

DEFAULT_KNOWN_HOSTS_PATH = Path("~/.ssh/known_hosts").expanduser()

# Marker-prefixed entries (@cert-authority/@revoked) are out of scope for v1.
_MARKERS = ("@",)


def _host_entry_name(host: str, port: int) -> str:
    """Return the known_hosts-style entry name for host:port."""
    return f"[{host}]:{port}" if port != 22 else host


class HostKeyChangedError(ConnectionError):
    """Raised when a server's host key differs from the recorded one."""


def _hashed_match(line_name: str, hostname: str) -> bool:
    """Check whether a hashed known_hosts entry (|1|salt|hash) matches."""
    parts = line_name.split("|")
    try:
        salt = base64.b64decode(parts[2])
        expected = base64.b64decode(parts[3])
    except (IndexError, ValueError):
        return False
    digest = hmac.new(salt, hostname.encode(), hashlib.sha1).digest()
    return hmac.compare_digest(digest, expected)


@dataclass
class MismatchRecord:
    """Details about a host whose key differs from the recorded one."""

    entry: str
    old_fingerprint: str
    new_fingerprint: str
    new_blob: str  # OpenSSH-format key, kept for --override-mismatched-keys


class HostKeyPolicy:
    """Session-wide host-key state shared by all concurrent connections."""

    def __init__(
        self,
        known_hosts_path: os.PathLike | str | None = None,
        override: bool = False,
    ):
        self.path = (
            Path(known_hosts_path)
            if known_hosts_path
            else DEFAULT_KNOWN_HOSTS_PATH
        )
        self.override_requested = override

        # Maps entry name -> OpenSSH-format public key blob.
        self._entries: dict[str, str] = {}
        # Original file lines kept so overrides can rewrite surgically.
        self._file_lines: List[str] = []
        self._line_index: List[List[str]] = []  # names covered by each line

        self._lock = threading.Lock()
        self._added: List[Tuple[str, str]] = []  # (entry, fingerprint)
        self._mismatches: List[MismatchRecord] = []
        self._overridden: set[str] = set()

        self._load_known_hosts()

    # --- loading ---------------------------------------------------------

    def _load_known_hosts(self) -> None:
        try:
            raw_lines = self.path.read_text(encoding="utf-8").splitlines()
        except FileNotFoundError:
            return
        except OSError:
            return  # Unreadable file: treated like an empty one.

        for raw in raw_lines:
            stripped = raw.strip()
            if not stripped or stripped.startswith("#"):
                continue
            fields = stripped.split()
            if len(fields) < 3 or fields[0].startswith(_MARKERS):
                continue
            names = fields[0].split(",")
            blob = f"{fields[1]} {fields[2]}"
            self._file_lines.append(stripped)
            self._line_index.append(names)
            for name in names:
                self._entries.setdefault(name, blob)

    # --- lookup & decisions ----------------------------------------------

    def _find_recorded_blob(self, entry: str, hostname: str) -> str | None:
        """Look up the recorded key for an entry, honoring hashed names."""
        blob = self._entries.get(entry)
        if blob is not None:
            return blob
        # Port-22 entries are stored bare; also try the explicit form.
        if entry.startswith("["):
            bare = entry[1 : entry.index("]:")]
            blob = self._entries.get(bare)
            if blob is not None:
                return blob
        for idx, names in enumerate(self._line_index):
            for name in names:
                if name.startswith("|1|") and _hashed_match(name, hostname):
                    return self._entries.get(names[0]) or self._file_blob(idx)
        return None

    def _file_blob(self, index: int) -> str | None:
        fields = self._file_lines[index].split()
        return f"{fields[1]} {fields[2]}" if len(fields) >= 3 else None

    @staticmethod
    def _blob(key: asyncssh.SSHKey) -> str:
        return key.export_public_key("openssh").decode().strip()

    def validate_key(
        self, entry: str, hostname: str, key: asyncssh.SSHKey
    ) -> bool:
        """Decide whether the presented key may be trusted for this host.

        Synchronous by contract (called from the asyncssh client hook).
        """
        presented = self._blob(key)
        with self._lock:
            if entry in self._overridden:
                return True
            recorded = self._find_recorded_blob(entry, hostname)
            if recorded == presented:
                return True
            if recorded is None:
                # Unknown host: TOFU. Persist and report later.
                self._trust_new_key(entry, key, presented)
                return True
            self._mismatches.append(
                MismatchRecord(
                    entry=entry,
                    old_fingerprint=self._fp_of_blob(recorded),
                    new_fingerprint=key.get_fingerprint(),
                    new_blob=presented,
                )
            )
            return False

    def _trust_new_key(
        self, entry: str, key: asyncssh.SSHKey, blob: str
    ) -> None:
        self._entries.setdefault(entry, blob)
        self._append_to_file(f"{entry} {blob}")
        self._added.append((entry, key.get_fingerprint()))

    def _append_to_file(self, line: str) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.path, "a", encoding="utf-8") as fh:
                fh.write(line + "\n")
        except OSError:
            pass  # Trust decision stands for this session even if persistence fails.

    # --- override ----------------------------------------------------------

    @property
    def mismatches(self) -> List[MismatchRecord]:
        """Live view of detected mismatches (append via validate_key only)."""
        return self._mismatches

    @property
    def added_keys(self) -> List[Tuple[str, str]]:
        """Live view of keys trusted on first use this session."""
        return self._added

    def apply_overrides(self) -> None:
        """Replace every mismatched entry with its newly-presented key."""
        with self._lock:
            for record in self._mismatches:
                self._entries[record.entry] = record.new_blob
                self._remove_entries_from_file(record.entry)
                self._append_to_file(f"{record.entry} {record.new_blob}")
                self._overridden.add(record.entry)
            self._mismatches.clear()

    def _remove_entries_from_file(self, entry: str) -> None:
        kept_lines: List[str] = []
        kept_index: List[List[str]] = []
        for line, names in zip(self._file_lines, self._line_index):
            if entry in names:
                remaining = [n for n in names if n != entry]
                if not remaining:
                    continue  # Line belonged solely to this entry: drop it.
                fields = line.split(maxsplit=1)
                line = (
                    f"{','.join(remaining)} {fields[1]}"
                    if len(fields) > 1
                    else line
                )
                names = remaining
            kept_lines.append(line)
            kept_index.append(names)
        self._file_lines = kept_lines
        self._line_index = kept_index
        self._rewrite_file()

    def _rewrite_file(self) -> None:
        content = "".join(line + "\n" for line in self._file_lines)
        fd, tmp_path = tempfile.mkstemp(
            dir=str(self.path.parent), prefix=".known_hosts."
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(content)
            os.replace(tmp_path, self.path)
        except OSError:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass

    @staticmethod
    def _fp_of_blob(blob: str) -> str:
        try:
            key = asyncssh.import_public_key(blob)
        except (asyncssh.KeyImportError, ValueError):
            return "(unreadable)"
        return key.get_fingerprint()


def make_client_factory(policy: HostKeyPolicy, entry: str, hostname: str):
    """Build an asyncssh client_factory bound to a policy and target host."""

    class PolicySSHClient(asyncssh.SSHClient):
        def validate_host_public_key(
            self, host: str, addr: str, port: int, key: asyncssh.SSHKey
        ) -> bool:
            return policy.validate_key(entry, hostname, key)

    return PolicySSHClient
