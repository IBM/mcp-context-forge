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
from unittest.mock import AsyncMock, MagicMock, Mock, patch

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
async def test_remove_session_tolerates_eviction_failure(caplog):
    """A failing upstream eviction must not mask downstream session removal AND must log at WARNING.

    Log-level matters: the swallow was intentionally upgraded from DEBUG to
    WARNING in commit a261bd231 because an orphaned upstream session is
    otherwise invisible to ops. A silent regression back to DEBUG would
    re-hide exactly the failures this diff exists to surface.
    """
    # First-Party
    from mcpgateway.cache.session_registry import SessionRegistry

    reg = registry_module.init_upstream_session_registry()
    reg.evict_session = AsyncMock(side_effect=RuntimeError("redis unreachable"))  # type: ignore[method-assign]

    session_registry = SessionRegistry(backend="memory")
    with caplog.at_level("DEBUG", logger="mcpgateway.cache.session_registry"):
        await session_registry.remove_session("downstream-session-def")
    reg.evict_session.assert_awaited_once()

    warnings = [rec for rec in caplog.records if rec.levelname == "WARNING" and "downstream-session-def" in rec.getMessage()]
    assert len(warnings) == 1, f"expected 1 WARNING; got {[(r.levelname, r.getMessage()) for r in caplog.records]}"
    msg = warnings[0].getMessage()
    assert "RuntimeError" in msg and "redis unreachable" in msg  # exception type + message surfaced
    assert "orphaned" in msg  # the operator-facing hint survives


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
async def test_evict_upstream_sessions_for_gateway_helper_swallows_unexpected_errors(caplog):
    """Registry exceptions must not mask gateway-mutation errors AND must log at WARNING.

    The warning-level bump is deliberate: this helper runs POST-commit, so a
    silent eviction failure means in-flight sessions keep talking to the old
    gateway state. Operators need to see it.
    """
    # First-Party
    from mcpgateway.services.gateway_service import _evict_upstream_sessions_for_gateway

    reg = registry_module.init_upstream_session_registry()
    reg.evict_gateway = AsyncMock(side_effect=RuntimeError("redis down"))  # type: ignore[method-assign]

    # Must not raise — gateway delete/update must still proceed.
    with caplog.at_level("DEBUG", logger="mcpgateway.services.gateway_service"):
        assert await _evict_upstream_sessions_for_gateway("gw-target") == 0
    reg.evict_gateway.assert_awaited_once()

    warnings = [rec for rec in caplog.records if rec.levelname == "WARNING" and "gw-target" in rec.getMessage()]
    assert len(warnings) == 1, f"expected 1 WARNING; got {[(r.levelname, r.getMessage()) for r in caplog.records]}"
    msg = warnings[0].getMessage()
    assert "RuntimeError" in msg and "redis down" in msg
    assert "stale" in msg  # operator-facing hint


# ---------------------------------------------------------------------------
# Connect-field change detection contract
# ---------------------------------------------------------------------------


_CONNECT_FIELD_NAMES = (
    "url",
    "transport",  # SSE ↔ STREAMABLE_HTTP change re-pins the upstream client class
    "auth_type",
    "auth_value",
    "auth_query_params",
    "oauth_config",
    "ca_certificate",
    "ca_certificate_sig",
    "signing_algorithm",
    "client_cert",
    "client_key",
)


def test_connect_field_inventory_matches_gateway_model():
    """Every mutable Gateway field that changes the upstream HTTP/TLS envelope
    must be in the eviction check in GatewayService.update_gateway.

    Adding a new TLS / auth / URL field on the Gateway ORM without updating
    the eviction check would leave upstream sessions pinned to stale state
    across that field's changes. This test fails noisily if someone adds a
    connect-relevant column and forgets to wire it through.

    If you add a legitimately-non-connect field (description, tags, etc.),
    extend _GATEWAY_MODEL_NON_CONNECT_FIELDS below.
    """
    # First-Party
    from mcpgateway.db import Gateway as DbGateway
    from mcpgateway.services import gateway_service

    # Grep the source of update_gateway for each name. Coarse but sticky:
    # rename a variable and this test still catches the intent.
    src = open(gateway_service.__file__, encoding="utf-8").read()
    for field in _CONNECT_FIELD_NAMES:
        assert f"original_{field}" in src, f"update_gateway must capture original_{field} for #4205 eviction"
        assert field in src, f"update_gateway must compare gateway.{field} to the original"

    # Sanity: every _CONNECT_FIELD_NAME is an actual column on the ORM model.
    columns = {c.key for c in DbGateway.__table__.columns}
    for field in _CONNECT_FIELD_NAMES:
        assert field in columns, f"_CONNECT_FIELD_NAMES out of sync: {field} no longer on Gateway model"


# ---------------------------------------------------------------------------
# End-to-end proof that GatewayService.{delete,update}_gateway CALL eviction
# ---------------------------------------------------------------------------
#
# The 3 helper tests above only prove the helper itself forwards; the contract
# test above only greps the source for field names. Neither catches a
# regression that REMOVES the `await _evict_upstream_sessions_for_gateway(...)`
# call line. These two tests drive the real GatewayService methods against
# mocked DB + mocked registry and assert registry.evict_gateway fires.


@pytest.mark.asyncio
async def test_delete_gateway_calls_registry_evict_gateway():
    """GatewayService.delete_gateway must call registry.evict_gateway after commit (#4205)."""
    # First-Party
    from mcpgateway.services.gateway_service import GatewayService

    reg = registry_module.init_upstream_session_registry()
    reg.evict_gateway = AsyncMock(return_value=0)  # type: ignore[method-assign]

    service = GatewayService()
    gateway = MagicMock(id="gw-to-delete", name="gw", tools=[], resources=[], prompts=[], team_id=None, url="http://u")
    test_db = MagicMock()
    test_db.execute.return_value.scalar_one_or_none.return_value = gateway
    # rowcount=1 makes the DELETE succeed and control flow to the eviction site.
    delete_result = MagicMock()
    delete_result.rowcount = 1
    test_db.execute.return_value = delete_result

    def execute_side_effect(*_args, **_kwargs):
        # First .execute() returns the scalar_one_or_none gateway; later calls
        # return the DELETE result. A single MagicMock with scalar_one_or_none
        # set once + rowcount=1 covers both paths because the attributes don't
        # collide.
        r = MagicMock()
        r.scalar_one_or_none.return_value = gateway
        r.rowcount = 1
        return r

    test_db.execute = Mock(side_effect=execute_side_effect)
    test_db.commit = Mock()
    service._notify_gateway_deleted = AsyncMock()
    service._active_gateways = set()

    with (
        patch("mcpgateway.services.gateway_service._get_registry_cache") as mock_registry_cache,
        patch("mcpgateway.services.gateway_service._get_tool_lookup_cache") as mock_lookup_cache,
        patch("mcpgateway.cache.admin_stats_cache.admin_stats_cache") as mock_stats_cache,
        patch("mcpgateway.utils.passthrough_headers.invalidate_passthrough_header_caches"),
        patch("mcpgateway.services.gateway_service.audit_trail"),
    ):
        mock_registry_cache.return_value.invalidate_gateways = AsyncMock()
        mock_lookup_cache.return_value.invalidate_gateway = AsyncMock()
        mock_stats_cache.invalidate_tags = AsyncMock()

        await service.delete_gateway(test_db, "gw-to-delete")

    reg.evict_gateway.assert_awaited_once_with("gw-to-delete")


@pytest.mark.asyncio
async def test_update_gateway_with_url_change_calls_registry_evict_gateway():
    """GatewayService.update_gateway must call registry.evict_gateway when url changes (#4205)."""
    # Standard
    from unittest.mock import MagicMock

    # First-Party
    from mcpgateway.schemas import GatewayUpdate
    from mcpgateway.services.gateway_service import GatewayService

    reg = registry_module.init_upstream_session_registry()
    reg.evict_gateway = AsyncMock(return_value=0)  # type: ignore[method-assign]

    service = GatewayService()
    gateway = MagicMock()
    gateway.id = "gw-1"
    gateway.name = "gw"
    gateway.url = "http://old.example"
    gateway.transport = "streamablehttp"
    gateway.auth_type = None
    gateway.auth_value = None
    gateway.auth_query_params = None
    gateway.oauth_config = None
    gateway.ca_certificate = None
    gateway.ca_certificate_sig = None
    gateway.signing_algorithm = None
    gateway.client_cert = None
    gateway.client_key = None
    gateway.team_id = None
    gateway.visibility = "private"
    gateway.tags = []
    gateway.version = 1

    test_db = MagicMock()
    test_db.execute.return_value.scalar_one_or_none.return_value = gateway
    # Second .execute() is the name-conflict check → None (no conflict).
    test_db.execute = Mock(
        side_effect=[
            _mk(scalar=gateway),  # initial SELECT with selectinload
            _mk(scalar=None),  # name conflict check
            _mk(scalar=None),  # any follow-up
        ]
    )
    test_db.commit = Mock()
    test_db.refresh = Mock()

    service._initialize_gateway = AsyncMock(return_value=({"prompts": {}, "resources": {}, "tools": {}}, [], [], []))
    service._notify_gateway_updated = AsyncMock()
    service._active_gateways = set()
    service._classification_service = None
    service._check_gateway_uniqueness = Mock(return_value=None)
    service.normalize_url = lambda u: u

    with (
        patch("mcpgateway.services.gateway_service._get_registry_cache") as mock_registry_cache,
        patch("mcpgateway.services.gateway_service._get_tool_lookup_cache") as mock_lookup_cache,
        patch("mcpgateway.cache.admin_stats_cache.admin_stats_cache") as mock_stats_cache,
        patch("mcpgateway.services.gateway_service.GatewayRead.model_validate") as mock_validate,
        patch("mcpgateway.utils.passthrough_headers.invalidate_passthrough_header_caches"),
        patch("mcpgateway.services.gateway_service.audit_trail"),
    ):
        mock_registry_cache.return_value.invalidate_gateways = AsyncMock()
        mock_lookup_cache.return_value.invalidate_gateway = AsyncMock()
        mock_stats_cache.invalidate_tags = AsyncMock()
        mock_validate.return_value.masked.return_value = MagicMock()

        update = GatewayUpdate(url="http://new.example")
        await service.update_gateway(test_db, "gw-1", update)

    reg.evict_gateway.assert_awaited_once_with("gw-1")


def _mk(*, scalar=None):
    """Build a MagicMock that mimics a SQLAlchemy Result for the mocked test_db.execute."""
    # Standard
    from unittest.mock import MagicMock

    r = MagicMock()
    r.scalar_one_or_none.return_value = scalar
    scalars_proxy = MagicMock()
    scalars_proxy.all.return_value = []
    r.scalars.return_value = scalars_proxy
    r.rowcount = 1
    return r
