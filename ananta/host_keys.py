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
import functools
import hashlib
import hmac
import os
import tempfile
import threading
from dataclasses import dataclass
from pathlib import Path

import asyncssh

DEFAULT_KNOWN_HOSTS_PATH = Path("~/.ssh/known_hosts").expanduser()

# Marker-prefixed entries (@cert-authority/@revoked) are out of scope for v1.
_MARKERS = ("@",)


def _host_entry_name(host: str, port: int) -> str:
    """Return the known_hosts-style entry name for host:port."""
    return f"[{host}]:{port}" if port != 22 else host


class HostKeyChangedError(ConnectionError):
    """Raised when a server's host key differs from the recorded one."""


@functools.lru_cache(maxsize=4096)
def _parse_hashed_name(line_name: str) -> tuple[bytes, bytes] | None:
    parts = line_name.split("|")
    if len(parts) < 4:
        return None
    try:
        salt = base64.b64decode(parts[2])
        expected = base64.b64decode(parts[3])
        return salt, expected
    except (IndexError, ValueError):
        return None


def _hashed_match(line_name: str, hostname: str) -> bool:
    """Check whether a hashed known_hosts entry (|1|salt|hash) matches."""
    parsed = _parse_hashed_name(line_name)
    if parsed is None:
        return False
    salt, expected = parsed
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
        self._file_lines: list[str] = []
        self._line_index: list[list[str]] = []  # names covered by each line
        self._hashed_index: list[tuple[str, str]] = (
            []
        )  # (hashed_name, first_name)

        self._lock = threading.Lock()
        self._added: list[tuple[str, str]] = []  # (entry, fingerprint)
        self._mismatches: list[MismatchRecord] = []
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
                self._file_lines.append(raw)
                self._line_index.append([])
                continue
            fields = stripped.split()
            if len(fields) < 3 or fields[0].startswith(_MARKERS):
                self._file_lines.append(raw)
                self._line_index.append([])
                continue
            names = fields[0].split(",")
            blob = f"{fields[1]} {fields[2]}"
            self._file_lines.append(raw)
            self._line_index.append(names)
            for name in names:
                self._entries.setdefault(name, blob)
                if name.startswith("|1|"):
                    self._hashed_index.append((name, names[0]))

    # --- lookup & decisions ----------------------------------------------

    def _find_recorded_blob(self, entry: str, hostname: str) -> str | None:
        """Look up the recorded key for an entry, honoring hashed names."""
        blob = self._entries.get(entry)
        if blob is not None:
            return blob
        # Port-22 entries can be stored bare ("host") or explicitly ("[host]:22").
        if entry.endswith("]:22"):
            bare = entry[1:-4]
            blob = self._entries.get(bare) or self._entries.get(f"[{bare}]")
            if blob is not None:
                return blob
        elif not entry.startswith("["):
            explicit_22 = f"[{entry}]:22"
            blob = self._entries.get(explicit_22)
            if blob is not None:
                return blob
        for name, first_name in self._hashed_index:
            if _hashed_match(name, entry) or _hashed_match(name, hostname):
                blob = self._entries.get(first_name)
                if blob is not None:
                    # Cache positive match to avoid repeated linear scans
                    self._entries[entry] = blob
                    self._entries[hostname] = blob
                return blob
        return None

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
        new_line = f"{entry} {blob}"
        self._append_to_file(new_line)
        self._file_lines.append(new_line)
        self._line_index.append([entry])
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
    def mismatches(self) -> list[MismatchRecord]:
        """Live view of detected mismatches (append via validate_key only)."""
        return self._mismatches

    @property
    def added_keys(self) -> list[tuple[str, str]]:
        """Live view of keys trusted on first use this session."""
        return self._added

    def apply_overrides(self) -> None:
        """Replace every mismatched entry with its newly-presented key."""
        with self._lock:
            for record in self._mismatches:
                self._entries[record.entry] = record.new_blob
                self._remove_entry_from_lines(record.entry)
                new_line = f"{record.entry} {record.new_blob}"
                self._file_lines.append(new_line)
                self._line_index.append([record.entry])
                self._overridden.add(record.entry)
            self._mismatches.clear()
            self._rewrite_file()

    def _remove_entries_from_file(self, entry: str) -> None:
        self._remove_entry_from_lines(entry)
        self._rewrite_file()

    def _remove_entry_from_lines(self, entry: str) -> None:
        kept_lines: list[str] = []
        kept_index: list[list[str]] = []
        for line, names in zip(self._file_lines, self._line_index):
            matches_entry = False
            for name in names:
                if name == entry:
                    matches_entry = True
                    break
                if name.startswith("|1|") and _hashed_match(name, entry):
                    matches_entry = True
                    break
            if matches_entry:
                remaining: list[str] = []
                for n in names:
                    if n == entry or (
                        n.startswith("|1|") and _hashed_match(n, entry)
                    ):
                        continue
                    remaining.append(n)
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
        self._hashed_index = [
            (name, names[0])
            for names in kept_index
            for name in names
            if name.startswith("|1|")
        ]

    def _rewrite_file(self) -> None:
        content = "".join(line + "\n" for line in self._file_lines)
        self.path.parent.mkdir(parents=True, exist_ok=True)
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
