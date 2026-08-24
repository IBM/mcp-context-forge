# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/services/test_rest_tool_runtime_url_validation.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Regression coverage for runtime REST tool URL validation.

The tests run against production code with strict outbound URL protection:

- The registration-time gate resolves DNS and blocks a hostname that resolves
  to a disallowed local address. It only passes while the hostname resolves to
  an allowed public IP.
- ToolService.invoke_tool() re-validates the runtime URL and rejects a stored
  REST tool target that now resolves to a disallowed local address.
"""

# Future
from __future__ import annotations

# Standard
import socket
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from unittest.mock import Mock

# Third-Party
import pytest

# First-Party
from mcpgateway.common.validators import validate_core_url
from mcpgateway.config import settings
from mcpgateway.services.tool_service import ToolInvocationError, ToolService
from mcpgateway.utils.retry_manager import ResilientHttpClient

# Reuse the service-test fixtures for DbTool-shaped mocks and DB execute stubbing.
from tests.unit.mcpgateway.services.test_tool_service import (  # noqa: F401
    mock_gateway,
    mock_global_config_obj,
    mock_tool,
    setup_db_execute_mock,
)

INTERNAL_MARKER = "INTERNAL-RESOURCE-MARKER-DATA"
DYNAMIC_HOST = "runtime-validation-test.local"

# Test-controlled resolver state: maps the fake hostname to whatever IP the
# scenario needs for both validation and outbound connection setup.
_DNS: dict[str, str] = {}
_real_getaddrinfo = socket.getaddrinfo


def _fake_getaddrinfo(host, *args, **kwargs):
    if host in _DNS:
        return _real_getaddrinfo(_DNS[host], *args, **kwargs)
    return _real_getaddrinfo(host, *args, **kwargs)


@pytest.fixture(autouse=True)
def _patch_dns(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", _fake_getaddrinfo)
    _DNS.clear()
    yield
    _DNS.clear()


@pytest.fixture(autouse=True)
def _strict_outbound_url_policy(monkeypatch):
    """Force strict production-style outbound URL configuration."""
    monkeypatch.setattr(settings, "ssrf_protection_enabled", True, raising=False)
    monkeypatch.setattr(settings, "ssrf_allow_localhost", False, raising=False)
    monkeypatch.setattr(settings, "ssrf_allow_private_networks", False, raising=False)
    monkeypatch.setattr(settings, "ssrf_dns_fail_closed", True, raising=False)


@pytest.fixture
def internal_server():
    """A real HTTP listener bound to a local-only address.

    Records every request path it serves so the tests can prove whether the
    outbound request left the gateway process.
    """
    hits: list[str] = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            hits.append(self.path)
            body = INTERNAL_MARKER.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format, *args):  # noqa: A002 - match base signature, silence
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    port = server.server_address[1]
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        yield port, hits
    finally:
        server.shutdown()


def test_registration_gate_rejects_disallowed_resolution(internal_server):
    """Registration-time validation resolves DNS and rejects disallowed addresses."""
    port, _ = internal_server
    url = f"http://{DYNAMIC_HOST}:{port}/internal.txt"

    # Phase 1: hostname is public at registration -> validation PASSES.
    _DNS[DYNAMIC_HOST] = "8.8.4.4"
    assert validate_core_url(url, "Tool URL") == url  # does not raise

    # Phase 2: hostname resolves to a disallowed local target -> validation rejects it.
    _DNS[DYNAMIC_HOST] = "127.0.0.1"
    with pytest.raises(ValueError):
        validate_core_url(url, "Tool URL")


@pytest.mark.asyncio
async def test_invocation_rejects_disallowed_runtime_target(
    mock_tool,  # noqa: F811
    mock_global_config_obj,  # noqa: F811
    test_db,
    internal_server,
    monkeypatch,
):
    """invoke_tool() rejects a disallowed runtime target before outbound I/O."""
    port, hits = internal_server

    # Use the resolved local address directly here because httpx's async resolver
    # does not honor a patched socket.getaddrinfo in this unit-test path. The
    # registration-gate test above proves the validator rejects a hostname once it
    # points here.
    mock_tool.integration_type = "REST"
    mock_tool.request_type = "GET"
    mock_tool.auth_value = None
    mock_tool.jsonpath_filter = ""
    mock_tool.url = f"http://127.0.0.1:{port}/internal.txt"
    setup_db_execute_mock(test_db, mock_tool, mock_global_config_obj)

    # Sanity: registration WOULD reject this tool now (proves the target is
    # rejected under the current strict config).
    with pytest.raises(ValueError):
        validate_core_url(mock_tool.url, "Tool URL")

    service = ToolService()
    await service._http_client.aclose()
    service._http_client = ResilientHttpClient(client_args={"timeout": settings.federation_timeout, "verify": not settings.skip_ssl_verify})

    # Avoid real metrics DB writes.
    monkeypatch.setattr("mcpgateway.services.tool_service.metrics_buffer", Mock())

    try:
        with pytest.raises(ToolInvocationError, match="Outbound URL blocked by URL policy"):
            await service.invoke_tool(test_db, "test_tool", {}, request_headers=None, token_teams=None)
    finally:
        await service._http_client.aclose()

    assert not hits, "local listener was reached despite runtime URL validation"


@pytest.mark.asyncio
async def test_rpc_register_then_resolution_change_then_invoke(app, internal_server, monkeypatch):
    """The endpoint flow over real HTTP endpoints with a changed runtime resolution.

    Uses the real FastAPI app (real /tools create with its registration-time
    validator, real /rpc tools/call dispatch, real ToolService._http_client) driven
    in-process via ASGITransport. Auth is disabled -> platform-admin identity, so
    RBAC does not block.

    DNS is controlled at the resolver level (no root / no /etc/hosts): the fake
    hostname resolves to an allowed public address at registration and a
    disallowed local address at invocation.
    """
    # Third-Party
    import httpx

    # Strict outbound URL config on the app's live settings too.
    monkeypatch.setattr(settings, "ssrf_protection_enabled", True, raising=False)
    monkeypatch.setattr(settings, "ssrf_allow_localhost", False, raising=False)
    monkeypatch.setattr(settings, "ssrf_allow_private_networks", False, raising=False)
    monkeypatch.setattr(settings, "ssrf_dns_fail_closed", True, raising=False)

    port, hits = internal_server
    url = f"http://{DYNAMIC_HOST}:{port}/internal.txt"

    # --- install a test resolver honored by BOTH the sync validator
    #     (socket.getaddrinfo) and the async outbound httpx (loop.getaddrinfo) ---
    loop = __import__("asyncio").get_running_loop()
    real_loop_gai = loop.getaddrinfo
    real_sock_gai = socket.getaddrinfo

    def _key(host):
        # anyio ASCII-encodes hostnames to bytes before resolving.
        return host.decode() if isinstance(host, (bytes, bytearray)) else host

    def _sync_gai(host, *a, **k):
        return real_sock_gai(_DNS.get(_key(host), host), *a, **k)

    async def _async_gai(host, *a, **k):
        return await real_loop_gai(_DNS.get(_key(host), host), *a, **k)

    monkeypatch.setattr(socket, "getaddrinfo", _sync_gai)
    monkeypatch.setattr(loop, "getaddrinfo", _async_gai)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        # Step 1+2: hostname is PUBLIC -> register the REST tool (validation passes).
        _DNS[DYNAMIC_HOST] = "8.8.4.4"
        create = await client.post(
            "/tools",
            json={"tool": {"name": "runtime_validation_tool", "url": url, "integration_type": "REST", "request_type": "GET"}},
        )
        assert create.status_code in (200, 201), f"registration failed: {create.status_code} {create.text}"
        invocable_name = create.json().get("name") or create.json().get("customName") or "runtime_validation_tool"

        # Step 3: the hostname resolves to a disallowed local target.
        _DNS[DYNAMIC_HOST] = "127.0.0.1"

        # Step 5: invoke the already-registered tool via /rpc (no re-registration).
        rpc = await client.post(
            "/rpc",
            json={"jsonrpc": "2.0", "method": "tools/call", "params": {"name": invocable_name, "arguments": {}}, "id": 1},
        )

    body = rpc.text
    assert INTERNAL_MARKER not in body, f"internal marker leaked in /rpc response: {body!r}"
    assert not hits, "local listener was reached despite runtime URL validation"
