# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/services/test_tool_service_tenant_id.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Tenant-id population in the tool-service GlobalContext fallback paths (G1).

Covers ``ToolService._build_rust_tool_hook_global_context`` and the same
``else`` branch inside ``invoke_tool`` that fires when middleware didn't
run and a fresh ``GlobalContext`` has to be constructed from the
already-extracted tool payload. Without these tests the rate limiter's
``by_tenant`` dimension is silently a no-op on the fallback path.
"""

from cpex.framework import GlobalContext
from mcpgateway.services.tool_service import ToolService


def test_build_rust_tool_hook_global_context_propagates_team_id_as_tenant_id():
    """tool_payload['team_id'] flows into GlobalContext.tenant_id on the fallback path."""
    service = ToolService()

    ctx = service._build_rust_tool_hook_global_context(
        app_user_email="alice@example.com",
        server_id=None,
        tool_gateway_id=None,
        plugin_global_context=None,  # forces the fallback branch
        tool_payload={"team_id": "team_a", "name": "search"},
        gateway_payload=None,
        request_headers=None,
    )

    assert ctx.tenant_id == "team_a", f"fallback-path GlobalContext must carry tool_payload['team_id'] as tenant_id — got tenant_id={ctx.tenant_id!r}"


def test_build_rust_tool_hook_global_context_tenant_id_none_when_team_id_absent():
    """Missing team_id → tenant_id stays None; no crash, no spurious default."""
    service = ToolService()

    ctx = service._build_rust_tool_hook_global_context(
        app_user_email="alice@example.com",
        server_id=None,
        tool_gateway_id=None,
        plugin_global_context=None,
        tool_payload={"name": "search"},  # no team_id
        gateway_payload=None,
        request_headers=None,
    )

    assert ctx.tenant_id is None, f"tenant_id must remain None when tool_payload has no team_id, got tenant_id={ctx.tenant_id!r}"


def test_build_rust_tool_hook_global_context_non_string_team_id_is_ignored():
    """Defensive: a non-string team_id (unexpected shape) must not crash or be coerced."""
    service = ToolService()

    ctx = service._build_rust_tool_hook_global_context(
        app_user_email="alice@example.com",
        server_id=None,
        tool_gateway_id=None,
        plugin_global_context=None,
        tool_payload={"team_id": 42, "name": "search"},  # numeric, not str
        gateway_payload=None,
        request_headers=None,
    )

    assert ctx.tenant_id is None, f"Non-string team_id must not be accepted as tenant_id; got tenant_id={ctx.tenant_id!r}"


def test_build_rust_tool_hook_global_context_fills_missing_existing_tenant_id():
    """Existing GlobalContext with tenant_id=None is filled from payload team_id."""
    service = ToolService()
    existing_context = GlobalContext(request_id="request-1", tenant_id=None)

    ctx = service._build_rust_tool_hook_global_context(
        app_user_email="alice@example.com",
        server_id=None,
        tool_gateway_id=None,
        plugin_global_context=existing_context,
        tool_payload={"team_id": "team_a", "name": "search"},
        gateway_payload=None,
        request_headers=None,
    )

    assert ctx is existing_context
    assert ctx.tenant_id == "team_a", f"existing GlobalContext with tenant_id=None must be filled from tool_payload['team_id']; got tenant_id={ctx.tenant_id!r}"


def test_build_rust_tool_hook_global_context_preserves_existing_tenant_id():
    """Existing GlobalContext with tenant_id already set is NOT overwritten by payload team_id.

    This covers the branch where plugin_global_context exists AND has tenant_id,
    so the condition `if not global_context.tenant_id and payload_tenant_id:` is False.
    Line 4568 in tool_service.py.
    """
    service = ToolService()
    existing_context = GlobalContext(request_id="request-1", tenant_id="team_middleware")

    ctx = service._build_rust_tool_hook_global_context(
        app_user_email="alice@example.com",
        server_id=None,
        tool_gateway_id=None,
        plugin_global_context=existing_context,
        tool_payload={"team_id": "team_payload", "name": "search"},
        gateway_payload=None,
        request_headers=None,
    )

    assert ctx is existing_context
    assert ctx.tenant_id == "team_middleware", (
        f"existing GlobalContext with tenant_id already set must NOT be overwritten by tool_payload['team_id']; expected 'team_middleware', got tenant_id={ctx.tenant_id!r}"
    )


def test_build_rust_tool_hook_global_context_uses_virtual_server_id():
    """An explicit virtual-server ID must win over gateway and existing context IDs."""
    service = ToolService()
    existing_context = GlobalContext(request_id="request-1", server_id="middleware-server")

    ctx = service._build_rust_tool_hook_global_context(
        app_user_email="alice@example.com",
        server_id="virtual-server",
        tool_gateway_id="gateway-server",
        plugin_global_context=existing_context,
        tool_payload={"name": "search"},
        gateway_payload=None,
        request_headers=None,
    )

    assert ctx is existing_context
    assert ctx.server_id == "virtual-server"


def test_build_rust_tool_hook_global_context_preserves_existing_server_id_without_virtual_server():
    """Without a virtual-server scope, an existing server ID is not replaced by the gateway ID."""
    service = ToolService()
    existing_context = GlobalContext(request_id="request-1", server_id="middleware-server")

    ctx = service._build_rust_tool_hook_global_context(
        app_user_email=None,
        server_id=None,
        tool_gateway_id="gateway-server",
        plugin_global_context=existing_context,
        tool_payload=None,
        gateway_payload=None,
        request_headers=None,
    )

    assert ctx is existing_context
    assert ctx.server_id == "middleware-server"


def test_build_rust_tool_hook_global_context_falls_back_to_gateway_server_id():
    """A fresh context uses the gateway ID when no virtual-server ID is provided."""
    service = ToolService()

    ctx = service._build_rust_tool_hook_global_context(
        app_user_email=None,
        server_id=None,
        tool_gateway_id="gateway-server",
        plugin_global_context=None,
        tool_payload=None,
        gateway_payload=None,
        request_headers=None,
    )

    assert ctx.server_id == "gateway-server"
