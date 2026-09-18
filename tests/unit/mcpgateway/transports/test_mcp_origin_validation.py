# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/transports/test_mcp_origin_validation.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Unit tests for MCP Streamable HTTP Origin / DNS-rebinding protection.

Covers:
- _check_mcp_origin helper: missing, allowlisted, unapproved, 'null', empty allowlist
- handle_streamable_http integration: 403 returned before any session/backend logic
  when MCP_ALLOWED_ORIGINS is configured and the Origin header is rejected.
- Internally-forwarded requests (loopback + x-forwarded-internally) bypass the check.
- SDK TransportSecuritySettings wiring: security_settings passed when mcp_allowed_hosts is
  set; None when mcp_allowed_hosts is empty.
- Split-enforcement path: mcp_allowed_hosts set, mcp_allowed_origins empty — custom gate
  enforces origins while SDK receives allowed_origins=[].
"""

# Future
from __future__ import annotations

# Standard
from contextlib import asynccontextmanager

# Third-Party
import pytest

# First-Party
from mcpgateway.transports import streamablehttp_transport as tr
from mcpgateway.transports.streamablehttp_transport import (
    _check_mcp_origin,
    SessionManagerWrapper,
)


# ---------------------------------------------------------------------------
# _check_mcp_origin unit tests
# ---------------------------------------------------------------------------


class TestCheckMcpOrigin:
    """Unit tests for _check_mcp_origin."""

    def _patch_allowed(self, monkeypatch, origins: set):
        """Patch settings.mcp_allowed_origins on the transport module."""
        monkeypatch.setattr(tr.settings, "mcp_allowed_origins", origins)

    # ------------------------------------------------------------------
    # Empty allowlist (default) — enforcement disabled
    # ------------------------------------------------------------------

    def test_missing_origin_always_accepted_when_allowlist_empty(self, monkeypatch):
        """Missing Origin header is always accepted regardless of allowlist."""
        self._patch_allowed(monkeypatch, set())
        assert _check_mcp_origin(None) is True

    def test_any_origin_accepted_when_allowlist_empty(self, monkeypatch):
        """Any present Origin is accepted when mcp_allowed_origins is empty (opt-in default)."""
        self._patch_allowed(monkeypatch, set())
        assert _check_mcp_origin("https://attacker.invalid") is True

    def test_null_literal_accepted_when_allowlist_empty(self, monkeypatch):
        """'null' origin is accepted when enforcement is not configured."""
        self._patch_allowed(monkeypatch, set())
        assert _check_mcp_origin("null") is True

    # ------------------------------------------------------------------
    # Non-empty allowlist — enforcement enabled
    # ------------------------------------------------------------------

    def test_missing_origin_accepted_when_allowlist_configured(self, monkeypatch):
        """Missing Origin is always accepted even when the allowlist is configured."""
        self._patch_allowed(monkeypatch, {"https://myapp.example.com"})
        assert _check_mcp_origin(None) is True

    def test_allowlisted_origin_accepted(self, monkeypatch):
        """An Origin that is in the allowlist must be accepted."""
        self._patch_allowed(monkeypatch, {"https://myapp.example.com", "https://admin.example.com"})
        assert _check_mcp_origin("https://myapp.example.com") is True
        assert _check_mcp_origin("https://admin.example.com") is True

    def test_unapproved_origin_rejected(self, monkeypatch):
        """An Origin not in the allowlist must be rejected (returns False)."""
        self._patch_allowed(monkeypatch, {"https://myapp.example.com"})
        assert _check_mcp_origin("https://attacker.invalid") is False

    def test_null_literal_rejected_by_default_when_allowlist_set(self, monkeypatch):
        """The literal string 'null' is rejected unless explicitly listed."""
        self._patch_allowed(monkeypatch, {"https://myapp.example.com"})
        assert _check_mcp_origin("null") is False

    def test_null_literal_accepted_when_explicitly_listed(self, monkeypatch):
        """'null' is accepted when the operator has explicitly listed it."""
        self._patch_allowed(monkeypatch, {"null"})
        assert _check_mcp_origin("null") is True

    def test_malformed_origin_rejected(self, monkeypatch):
        """A malformed / garbage Origin string is rejected."""
        self._patch_allowed(monkeypatch, {"https://myapp.example.com"})
        assert _check_mcp_origin("not-a-valid-origin") is False
        assert _check_mcp_origin("javascript:alert(1)") is False


# ---------------------------------------------------------------------------
# handle_streamable_http integration — Origin guard fires before session logic
# ---------------------------------------------------------------------------


def _make_scope(
    path: str,
    headers: list[tuple[bytes, bytes]] | None = None,
    method: str = "POST",
    client: tuple[str, int] | None = ("10.0.0.1", 51234),
) -> dict:
    """Build a minimal ASGI HTTP scope dict."""
    scope: dict = {
        "type": "http",
        "method": method,
        "path": path,
        "headers": headers or [],
        "modified_path": path,
        "scheme": "https",
        "server": ("localhost", 4444),
    }
    if client is not None:
        scope["client"] = client
    return scope


class DummySessionManager:
    """Minimal stub for StreamableHTTPSessionManager."""

    def __init__(self, **_kwargs):
        self._server_instances = {}
        self.called = False

    @asynccontextmanager
    async def run(self):
        yield self

    async def handle_request(self, scope, receive, send_func):
        self.called = True
        await send_func({"type": "http.response.start", "status": 200, "headers": []})
        await send_func({"type": "http.response.body", "body": b"ok"})


@pytest.mark.asyncio
async def test_unapproved_origin_returns_403_before_session(monkeypatch):
    """An unapproved Origin must yield HTTP 403 before the SDK session manager is touched."""
    monkeypatch.setattr(tr.settings, "mcp_allowed_origins", {"https://trusted.example.com"})
    monkeypatch.setattr(tr, "StreamableHTTPSessionManager", DummySessionManager)

    wrapper = SessionManagerWrapper()
    await wrapper.initialize()

    sent: list[dict] = []

    async def send(msg):
        sent.append(msg)

    async def receive():
        return {"type": "http.disconnect"}

    scope = _make_scope(
        "/mcp",
        headers=[(b"origin", b"https://attacker.invalid")],
    )
    await wrapper.handle_streamable_http(scope, receive, send)
    await wrapper.shutdown()

    assert sent, "Expected at least one ASGI message"
    start_msg = sent[0]
    assert start_msg["type"] == "http.response.start"
    assert start_msg["status"] == 403, f"Expected 403, got {start_msg['status']}"
    assert not wrapper.session_manager.called, "Session manager must NOT be called for rejected Origin"


@pytest.mark.asyncio
async def test_missing_origin_not_rejected(monkeypatch):
    """A request with no Origin header must NOT be rejected with 403 even when allowlist is set."""
    monkeypatch.setattr(tr.settings, "mcp_allowed_origins", {"https://trusted.example.com"})
    monkeypatch.setattr(tr, "StreamableHTTPSessionManager", DummySessionManager)

    wrapper = SessionManagerWrapper()
    await wrapper.initialize()

    sent: list[dict] = []

    async def send(msg):
        sent.append(msg)

    async def receive():
        return {"type": "http.disconnect"}

    scope = _make_scope("/mcp")  # no origin header
    await wrapper.handle_streamable_http(scope, receive, send)
    await wrapper.shutdown()

    # Must NOT result in a 403 from the Origin guard.  Other guards (RBAC, session) may
    # fire later and produce a different status, but the Origin guard must not reject it.
    origin_403 = any(m.get("status") == 403 for m in sent if m.get("type") == "http.response.start")
    assert not origin_403, f"Missing Origin must not produce a 403, got {sent}"


@pytest.mark.asyncio
async def test_allowlisted_origin_not_rejected(monkeypatch):
    """A request with an allowlisted Origin must not be rejected by the Origin guard."""
    monkeypatch.setattr(tr.settings, "mcp_allowed_origins", {"https://trusted.example.com"})
    monkeypatch.setattr(tr, "StreamableHTTPSessionManager", DummySessionManager)

    wrapper = SessionManagerWrapper()
    await wrapper.initialize()

    sent: list[dict] = []

    async def send(msg):
        sent.append(msg)

    async def receive():
        return {"type": "http.disconnect"}

    scope = _make_scope(
        "/mcp",
        headers=[(b"origin", b"https://trusted.example.com")],
    )
    await wrapper.handle_streamable_http(scope, receive, send)
    await wrapper.shutdown()

    # Must NOT result in a 403 from the Origin guard.
    origin_403 = any(m.get("status") == 403 for m in sent if m.get("type") == "http.response.start")
    assert not origin_403, f"Allowlisted Origin must not produce a 403, got {sent}"


@pytest.mark.asyncio
async def test_null_origin_rejected_when_allowlist_set(monkeypatch):
    """The literal 'null' Origin is rejected unless explicitly in the allowlist."""
    monkeypatch.setattr(tr.settings, "mcp_allowed_origins", {"https://trusted.example.com"})
    monkeypatch.setattr(tr, "StreamableHTTPSessionManager", DummySessionManager)

    wrapper = SessionManagerWrapper()
    await wrapper.initialize()

    sent: list[dict] = []

    async def send(msg):
        sent.append(msg)

    async def receive():
        return {"type": "http.disconnect"}

    scope = _make_scope("/mcp", headers=[(b"origin", b"null")])
    await wrapper.handle_streamable_http(scope, receive, send)
    await wrapper.shutdown()

    assert sent[0]["status"] == 403, f"Expected 403 for 'null' Origin, got {sent}"


@pytest.mark.asyncio
async def test_internal_forward_bypasses_origin_check(monkeypatch):
    """Internally-forwarded (loopback + x-forwarded-internally) requests skip Origin validation."""
    monkeypatch.setattr(tr.settings, "mcp_allowed_origins", {"https://trusted.example.com"})
    monkeypatch.setattr(tr, "StreamableHTTPSessionManager", DummySessionManager)

    wrapper = SessionManagerWrapper()
    await wrapper.initialize()

    sent: list[dict] = []

    async def send(msg):
        sent.append(msg)

    async def receive():
        return {"type": "http.disconnect"}

    scope = _make_scope(
        "/mcp",
        headers=[
            (b"origin", b"https://attacker.invalid"),
            (b"x-forwarded-internally", b"true"),
        ],
        client=("127.0.0.1", 0),
    )
    await wrapper.handle_streamable_http(scope, receive, send)
    await wrapper.shutdown()

    # Must NOT be 403 from the Origin guard.  Other middleware may produce a
    # different status (401, 405, etc.), but the Origin guard itself must not
    # reject internally-forwarded requests.
    assert not any(m.get("status") == 403 for m in sent if m.get("type") == "http.response.start"), f"Internal forward should not get 403, got {sent}"


@pytest.mark.asyncio
async def test_unapproved_origin_on_server_scoped_route_returns_403(monkeypatch):
    """Unapproved Origin is rejected on virtual-server-scoped /servers/{id}/mcp routes too."""
    monkeypatch.setattr(tr.settings, "mcp_allowed_origins", {"https://trusted.example.com"})
    monkeypatch.setattr(tr, "StreamableHTTPSessionManager", DummySessionManager)

    wrapper = SessionManagerWrapper()
    await wrapper.initialize()

    sent: list[dict] = []

    async def send(msg):
        sent.append(msg)

    async def receive():
        return {"type": "http.disconnect"}

    scope = _make_scope(
        "/servers/abc123/mcp",
        headers=[(b"origin", b"https://attacker.invalid")],
    )
    await wrapper.handle_streamable_http(scope, receive, send)
    await wrapper.shutdown()

    assert sent[0]["status"] == 403, f"Expected 403 on server-scoped route, got {sent}"


@pytest.mark.asyncio
async def test_unapproved_origin_on_get_method_returns_403(monkeypatch):
    """Unapproved Origin is rejected for GET /mcp requests too."""
    monkeypatch.setattr(tr.settings, "mcp_allowed_origins", {"https://trusted.example.com"})
    monkeypatch.setattr(tr, "StreamableHTTPSessionManager", DummySessionManager)

    wrapper = SessionManagerWrapper()
    await wrapper.initialize()

    sent: list[dict] = []

    async def send(msg):
        sent.append(msg)

    async def receive():
        return {"type": "http.disconnect"}

    scope = _make_scope(
        "/mcp",
        method="GET",
        headers=[(b"origin", b"https://attacker.invalid")],
    )
    await wrapper.handle_streamable_http(scope, receive, send)
    await wrapper.shutdown()

    assert sent[0]["status"] == 403, f"Expected 403 for GET with bad Origin, got {sent}"


@pytest.mark.asyncio
async def test_unapproved_origin_on_delete_method_returns_403(monkeypatch):
    """Unapproved Origin is rejected for DELETE /mcp requests too."""
    monkeypatch.setattr(tr.settings, "mcp_allowed_origins", {"https://trusted.example.com"})
    monkeypatch.setattr(tr, "StreamableHTTPSessionManager", DummySessionManager)

    wrapper = SessionManagerWrapper()
    await wrapper.initialize()

    sent: list[dict] = []

    async def send(msg):
        sent.append(msg)

    async def receive():
        return {"type": "http.disconnect"}

    scope = _make_scope(
        "/mcp",
        method="DELETE",
        headers=[(b"origin", b"https://attacker.invalid")],
    )
    await wrapper.handle_streamable_http(scope, receive, send)
    await wrapper.shutdown()

    assert sent[0]["status"] == 403, f"Expected 403 for DELETE with bad Origin, got {sent}"


def test_session_manager_wrapper_builds_sdk_security_settings(monkeypatch):
    """SessionManagerWrapper passes TransportSecuritySettings to the SDK when mcp_allowed_hosts is set."""
    captured_kwargs: dict = {}

    class CapturingSessionManager(DummySessionManager):
        def __init__(self, **kwargs):
            captured_kwargs.update(kwargs)
            super().__init__(**kwargs)

    monkeypatch.setattr(tr.settings, "mcp_allowed_hosts", {"myapp.example.com:4444"})
    monkeypatch.setattr(tr.settings, "mcp_allowed_origins", {"https://myapp.example.com"})
    monkeypatch.setattr(tr, "StreamableHTTPSessionManager", CapturingSessionManager)

    SessionManagerWrapper()

    security = captured_kwargs.get("security_settings")
    assert security is not None, "security_settings must be passed when mcp_allowed_hosts is set"
    assert security.enable_dns_rebinding_protection is True
    assert "myapp.example.com:4444" in security.allowed_hosts
    assert "https://myapp.example.com" in security.allowed_origins


def test_session_manager_wrapper_no_sdk_security_when_hosts_empty(monkeypatch):
    """SessionManagerWrapper passes security_settings=None to the SDK when mcp_allowed_hosts is empty."""
    captured_kwargs: dict = {}

    class CapturingSessionManager(DummySessionManager):
        def __init__(self, **kwargs):
            captured_kwargs.update(kwargs)
            super().__init__(**kwargs)

    monkeypatch.setattr(tr.settings, "mcp_allowed_hosts", set())
    monkeypatch.setattr(tr.settings, "mcp_allowed_origins", {"https://myapp.example.com"})
    monkeypatch.setattr(tr, "StreamableHTTPSessionManager", CapturingSessionManager)

    SessionManagerWrapper()

    assert captured_kwargs.get("security_settings") is None, (
        "security_settings must be None when mcp_allowed_hosts is empty — "
        "enabling SDK host validation with an empty allowlist would reject all requests"
    )


@pytest.mark.asyncio
async def test_origin_enforced_by_custom_gate_when_sdk_hosts_not_configured(monkeypatch):
    """When mcp_allowed_hosts is empty but mcp_allowed_origins is set, the custom gate still rejects
    unapproved origins (the SDK receives allowed_origins=[] and enforces nothing on its own)."""
    monkeypatch.setattr(tr.settings, "mcp_allowed_hosts", set())
    monkeypatch.setattr(tr.settings, "mcp_allowed_origins", {"https://trusted.example.com"})
    monkeypatch.setattr(tr, "StreamableHTTPSessionManager", DummySessionManager)

    wrapper = SessionManagerWrapper()
    await wrapper.initialize()

    sent: list[dict] = []

    async def send(msg):
        sent.append(msg)

    async def receive():
        return {"type": "http.disconnect"}

    scope = _make_scope(
        "/mcp",
        headers=[(b"origin", b"https://attacker.invalid")],
    )
    await wrapper.handle_streamable_http(scope, receive, send)
    await wrapper.shutdown()

    # The custom _check_mcp_origin gate must reject this — the SDK is not configured for
    # Origin enforcement in this path (allowed_origins=[] is not passed to TransportSecuritySettings
    # because mcp_allowed_hosts is empty and _sdk_security is None).
    assert sent, "Expected at least one ASGI message"
    start_msg = sent[0]
    assert start_msg["type"] == "http.response.start"
    assert start_msg["status"] == 403, (
        f"Custom origin gate must reject unapproved origins even when mcp_allowed_hosts is empty, got {sent}"
    )
    assert not wrapper.session_manager.called, "Session manager must NOT be called when origin is rejected"
