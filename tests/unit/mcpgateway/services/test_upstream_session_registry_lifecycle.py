# -*- coding: utf-8 -*-
"""Lifecycle wiring tests for UpstreamSessionRegistry (issue #4205).

These tests verify the registry's integration points outside the registry
itself: startup/shutdown in main.py, and the DELETE-triggered eviction that
SessionRegistry.remove_session() now forwards into the upstream registry.

Copyright 2026
SPDX-License-Identifier: Apache-2.0
"""

# Future
from __future__ import annotations

# Standard
from unittest.mock import AsyncMock, patch

# Third-Party
import pytest

# First-Party
from mcpgateway.services import upstream_session_registry as registry_module


@pytest.fixture(autouse=True)
def _reset_singleton():
    """Clear the module-level singleton around each test so state doesn't leak."""
    registry_module._registry = None
    yield
    registry_module._registry = None


@pytest.mark.asyncio
async def test_remove_session_calls_evict_session_on_upstream_registry():
    """SessionRegistry.remove_session() must forward the id to the upstream registry."""
    # First-Party
    from mcpgateway.cache.session_registry import SessionRegistry

    reg = registry_module.init_upstream_session_registry()
    reg.evict_session = AsyncMock(return_value=0)  # type: ignore[method-assign]

    session_registry = SessionRegistry(backend="memory")
    await session_registry.remove_session("downstream-session-xyz")

    reg.evict_session.assert_awaited_once_with("downstream-session-xyz")


@pytest.mark.asyncio
async def test_remove_session_tolerates_uninitialized_registry():
    """remove_session() must not raise when the upstream registry singleton is absent."""
    # First-Party
    from mcpgateway.cache.session_registry import SessionRegistry

    # Do NOT call init_upstream_session_registry() — singleton stays None.
    session_registry = SessionRegistry(backend="memory")
    # Should complete without raising.
    await session_registry.remove_session("downstream-session-abc")


@pytest.mark.asyncio
async def test_remove_session_tolerates_eviction_failure():
    """A failing upstream eviction must not mask downstream session removal."""
    # First-Party
    from mcpgateway.cache.session_registry import SessionRegistry

    reg = registry_module.init_upstream_session_registry()
    reg.evict_session = AsyncMock(side_effect=RuntimeError("redis unreachable"))  # type: ignore[method-assign]

    session_registry = SessionRegistry(backend="memory")
    # Should swallow and carry on.
    await session_registry.remove_session("downstream-session-def")
    reg.evict_session.assert_awaited_once()


@pytest.mark.asyncio
async def test_shutdown_drains_registry():
    """shutdown_upstream_session_registry() must call close_all() and clear the singleton."""
    reg = registry_module.init_upstream_session_registry()
    with patch.object(reg, "close_all", new=AsyncMock()) as mock_close:
        await registry_module.shutdown_upstream_session_registry()
        mock_close.assert_awaited_once()
    assert registry_module._registry is None


@pytest.mark.asyncio
async def test_init_is_idempotent_across_restarts():
    """Re-initializing after shutdown produces a fresh registry instance."""
    first = registry_module.init_upstream_session_registry()
    await registry_module.shutdown_upstream_session_registry()
    second = registry_module.init_upstream_session_registry()
    assert second is not first


# ---------------------------------------------------------------------------
# Gateway mutation → upstream session eviction (Codex review follow-up)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_evict_upstream_sessions_for_gateway_helper_forwards_to_registry():
    """The gateway_service helper must call registry.evict_gateway(gateway_id).

    Ensures admin-side gateway mutations (delete, URL change, auth change)
    invalidate upstream sessions so the next acquire reconnects against the
    new URL / with the new credentials instead of handing back a stale
    ClientSession. Without this forwarding, #4205's isolation would still
    hold across downstream sessions but each downstream session would keep
    talking to the PRE-admin-change gateway state.
    """
    # First-Party
    from mcpgateway.services.gateway_service import _evict_upstream_sessions_for_gateway

    reg = registry_module.init_upstream_session_registry()
    reg.evict_gateway = AsyncMock(return_value=3)  # type: ignore[method-assign]

    evicted = await _evict_upstream_sessions_for_gateway("gw-target")

    reg.evict_gateway.assert_awaited_once_with("gw-target")
    assert evicted == 3


@pytest.mark.asyncio
async def test_evict_upstream_sessions_for_gateway_helper_tolerates_uninitialized_registry():
    """A missing registry singleton must not block gateway mutation."""
    # First-Party
    from mcpgateway.services.gateway_service import _evict_upstream_sessions_for_gateway

    # Registry not initialized — eviction is best-effort, should return 0.
    assert await _evict_upstream_sessions_for_gateway("gw-anything") == 0


@pytest.mark.asyncio
async def test_evict_upstream_sessions_for_gateway_helper_swallows_unexpected_errors():
    """Registry exceptions must not mask gateway-mutation errors."""
    # First-Party
    from mcpgateway.services.gateway_service import _evict_upstream_sessions_for_gateway

    reg = registry_module.init_upstream_session_registry()
    reg.evict_gateway = AsyncMock(side_effect=RuntimeError("redis down"))  # type: ignore[method-assign]

    # Must not raise — gateway delete/update must still proceed.
    assert await _evict_upstream_sessions_for_gateway("gw-target") == 0
    reg.evict_gateway.assert_awaited_once()
