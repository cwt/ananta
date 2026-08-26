"""Tests for mandatory host-key verification (ananta.host_keys)."""

import asyncssh
import pytest

from ananta.host_keys import (
    HostKeyChangedError,
    HostKeyPolicy,
    _host_entry_name,
    make_client_factory,
)
from ananta.ssh import retry_connect

pytestmark = pytest.mark.asyncio


def _openssh_blob(key: asyncssh.SSHKey) -> str:
    return key.export_public_key("openssh").decode().strip()


@pytest.fixture
def key_a():
    return asyncssh.generate_private_key("ssh-ed25519")


@pytest.fixture
def key_b():
    return asyncssh.generate_private_key("ssh-ed25519")


@pytest.fixture
def known_hosts_file(tmp_path, key_a):
    """known_hosts pre-seeded with a single entry for web-01."""
    kh = tmp_path / "known_hosts"
    blob = _openssh_blob(key_a).split(maxsplit=1)[1]
    kh.write_text(
        "# comment\n" f"web-01 ssh-ed25519 {blob}\n",
        encoding="utf-8",
    )
    return kh


class TestValidateKey:
    async def test_known_key_match_connects(self, known_hosts_file, key_a):
        policy = HostKeyPolicy(known_hosts_path=known_hosts_file)
        assert policy.validate_key("web-01", "web-01", key_a) is True
        assert not policy.mismatches
        assert not policy.added_keys

    async def test_unknown_key_tofu_appends_and_reports(
        self, known_hosts_file, key_b
    ):
        policy = HostKeyPolicy(known_hosts_path=known_hosts_file)
        assert policy.validate_key("web-new", "web-new", key_b) is True

        # Trusted for the session and persisted for future runs.
        assert policy.added_keys[0][0] == "web-new"
        content = known_hosts_file.read_text(encoding="utf-8")
        assert "web-new" in content

    async def test_mismatch_fails_and_is_recorded(
        self, known_hosts_file, key_b
    ):
        policy = HostKeyPolicy(known_hosts_path=known_hosts_file)
        assert policy.validate_key("web-01", "web-01", key_b) is False

        assert len(policy.mismatches) == 1
        record = policy.mismatches[0]
        assert record.entry == "web-01"
        # Nothing was persisted: mismatch never touches the file.
        assert len(known_hosts_file.read_text().strip().splitlines()) == 2

    async def test_non_default_port_entry_name(self, known_hosts_file, key_a):
        assert _host_entry_name("web-01", 22) == "web-01"
        assert _host_entry_name("web-01", 2222) == "[web-01]:2222"

    async def test_hashed_entries_are_matched(self, tmp_path, key_a):
        import base64
        import hashlib
        import hmac as hmac_mod

        salt = b"0123456789abcdef"[:16]
        digest = hmac_mod.new(salt, b"secret-host", hashlib.sha1).digest()
        hashed = (
            "|1|"
            + base64.b64encode(salt).decode()
            + "|"
            + base64.b64encode(digest).decode()
        )
        blob = _openssh_blob(key_a).split(maxsplit=1)[1]

        kh = tmp_path / "known_hosts"
        kh.write_text(f"{hashed} ssh-ed25519 {blob}\n", encoding="utf-8")

        policy = HostKeyPolicy(known_hosts_path=kh)
        assert policy.validate_key("secret-host", "secret-host", key_a) is True
        assert (
            policy.validate_key(
                "secret-host",
                "secret-host",
                asyncssh.generate_private_key("ssh-ed25519"),
            )
            is False
        )


class TestOverrides:
    async def test_apply_overrides_replaces_entry(
        self, known_hosts_file, key_a, key_b
    ):
        policy = HostKeyPolicy(known_hosts_path=known_hosts_file)
        assert policy.validate_key("web-01", "web-01", key_b) is False
        assert policy.mismatches  # gate would trip here

        policy.apply_overrides()

        # The new key is now trusted and persisted; old line replaced.
        assert policy.validate_key("web-01", "web-01", key_b) is True
        assert not policy.mismatches
        content = known_hosts_file.read_text(encoding="utf-8")
        lines = [ln for ln in content.strip().splitlines() if ln]
        web_lines = [ln for ln in lines if ln.startswith("web-01")]
        assert len(web_lines) == 1
        assert _openssh_blob(key_b).split(maxsplit=1)[1] in web_lines[0]

    async def test_override_preserves_other_lines(self, tmp_path, key_a, key_b):
        other_blob = _openssh_blob(key_a).split(maxsplit=1)[1]
        new_blob = _openssh_blob(key_b).split(maxsplit=1)[1]
        kh = tmp_path / "known_hosts"
        kh.write_text(
            f"keep-me ssh-rsa {other_blob}\n"
            f"web-01 ssh-rsa {other_blob}\n"
            f"web-01,extra-host ssh-rsa {new_blob}\n",  # multi-name line
            encoding="utf-8",
        )
        policy = HostKeyPolicy(known_hosts_path=kh)
        # extra-host shares a line with web-01; override must split it.
        presented = asyncssh.generate_private_key("ssh-ed25519")
        assert policy.validate_key("web-01", "web-01", presented) is False
        policy.apply_overrides()

        content = kh.read_text()
        assert "keep-me" in content
        assert "extra-host" in content  # sibling name kept
        new_line = [
            ln for ln in content.splitlines() if ln.startswith("web-01")
        ]
        assert len(new_line) == 1


class TestClientFactory:
    async def test_factory_wires_validation_hook(self, tmp_path, key_a, key_b):
        policy = HostKeyPolicy(known_hosts_path=tmp_path / "kh")
        factory = make_client_factory(policy, "some-host", "some-host")
        client = factory()
        assert (
            client.validate_host_public_key("some-host", "1.2.3.4", 22, key_a)
            is True
        )  # TOFU on first sight
        # Second connection sees a different key -> rejected.
        client_two = factory()
        assert (
            client_two.validate_host_public_key(
                "some-host", "1.2.3.4", 22, key_b
            )
            is False
        )


async def test_retry_connect_raises_fast_on_mismatch(tmp_path, key_a):
    """A recorded mismatch must abort retries immediately."""
    from unittest.mock import patch

    from ananta.ssh import retry_connect

    kh = tmp_path / "known_hosts"
    blob = key_a.export_public_key("openssh").decode().strip()
    kh.write_text(f"10.0.0.9 {blob}\n", encoding="utf-8")

    calls = {"n": 0}
    wrong_key = asyncssh.generate_private_key("ssh-ed25519")

    async def fake_connect(**kwargs):
        calls["n"] += 1
        # Simulate asyncssh invoking the client's validation hook.
        client = kwargs["client_factory"]()
        assert (
            client.validate_host_public_key(
                "10.0.0.9", "10.0.0.9", 22, wrong_key
            )
            is False
        )
        raise asyncssh.Error(code=1, reason="host key verification failed")

    with patch("ananta.ssh.asyncssh.connect", side_effect=fake_connect):
        with pytest.raises(HostKeyChangedError):
            await retry_connect(
                ip_address="10.0.0.9",
                ssh_port=22,
                username="user",
                client_keys=["/key"],
                timeout=1,
                max_retries=3,
                policy=HostKeyPolicy(known_hosts_path=kh),
            )
    assert calls["n"] == 1  # no retries on deterministic security failure


class TestAgainstRealSSHServer:
    """End-to-end tests against a live in-process asyncssh server.

    These guard the actual wiring between asyncssh and the policy hook —
    a previous regression had known_hosts=None silently bypassing
    validate_host_public_key entirely.
    """

    @staticmethod
    async def start_server(tmp_path):
        server_key_path = str(tmp_path / "server_key")
        server_key = asyncssh.generate_private_key("ssh-ed25519")
        server_key.write_private_key(server_key_path)

        class Server(asyncssh.SSHServer):
            def begin_auth(self, username):
                return False  # No auth required for these tests

        return (
            await asyncssh.create_server(
                Server, "127.0.0.1", 0, server_host_keys=[server_key_path]
            ),
            server_key,
        )

    async def test_unknown_host_is_tofu_appended(self, tmp_path):
        from ananta.ssh import _close_ssh_connection

        server, _ = await self.start_server(tmp_path)
        port = server.sockets[0].getsockname()[1]
        kh = tmp_path / "known_hosts"
        policy = HostKeyPolicy(known_hosts_path=kh)

        conn = await retry_connect(
            ip_address="127.0.0.1",
            ssh_port=port,
            username="u",
            client_keys=[],
            timeout=5,
            max_retries=0,
            policy=policy,
        )
        await _close_ssh_connection(conn)
        server.close()

        assert kh.exists(), "TOFU must persist the new host key"
        content = kh.read_text(encoding="utf-8")
        assert "127.0.0.1" in content
        assert len(policy.added_keys) == 1
        # Non-default port entries use the [host]:port form.
        assert policy.added_keys[0][0].startswith("[127.0.0.1]:")

    async def test_mismatch_refuses_connection_without_retry(self, tmp_path):
        server, server_key = await self.start_server(tmp_path)
        port = server.sockets[0].getsockname()[1]

        # Seed known_hosts with a DIFFERENT key than the real server's.
        other = asyncssh.generate_private_key("ssh-ed25519")
        kh = tmp_path / "known_hosts"
        blob = other.export_public_key("openssh").decode().strip()
        kh.write_text(f"[127.0.0.1]:{port} {blob}\n", encoding="utf-8")

        policy = HostKeyPolicy(known_hosts_path=kh)
        with pytest.raises(HostKeyChangedError):
            await retry_connect(
                ip_address="127.0.0.1",
                ssh_port=port,
                username="u",
                client_keys=[],
                timeout=5,
                max_retries=3,  # Would mask the failure if it retried
                policy=policy,
            )
        # The mismatched key must not have been persisted.
        assert kh.read_text(encoding="utf-8") == f"[127.0.0.1]:{port} {blob}\n"
