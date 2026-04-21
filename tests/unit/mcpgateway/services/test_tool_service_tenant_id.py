# -*- coding: utf-8 -*-
"""Tenant-id population in the tool-service GlobalContext fallback paths (G1).

Covers ``ToolService._build_rust_tool_hook_global_context`` and the same
``else`` branch inside ``invoke_tool`` that fires when middleware didn't
run and a fresh ``GlobalContext`` has to be constructed from the
already-extracted tool payload. Without these tests the rate limiter's
``by_tenant`` dimension is silently a no-op on the fallback path.
"""

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

    assert ctx.tenant_id == "team_a", (
        "fallback-path GlobalContext must carry tool_payload['team_id'] as tenant_id — "
        f"got tenant_id={ctx.tenant_id!r}"
    )


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

    assert ctx.tenant_id is None, (
        "tenant_id must remain None when tool_payload has no team_id, "
        f"got tenant_id={ctx.tenant_id!r}"
    )


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

    assert ctx.tenant_id is None, (
        "Non-string team_id must not be accepted as tenant_id; "
        f"got tenant_id={ctx.tenant_id!r}"
    )
