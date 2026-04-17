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
