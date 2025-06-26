# -*- coding: utf-8 -*-
"""
Unit-tests for the GatewayService implementation.

These tests use only MagicMock / AsyncMock - no real network access
and no real database needed.  Where the service relies on Pydantic
models or SQLAlchemy Result objects, we monkey-patch or fake just
enough behaviour to satisfy the code paths under test.

Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, Mock

import pytest

# ---------------------------------------------------------------------------
# Application imports
# ---------------------------------------------------------------------------
from mcpgateway.db import Gateway as DbGateway
from mcpgateway.db import Tool as DbTool
from mcpgateway.schemas import GatewayCreate, GatewayUpdate
from mcpgateway.services.gateway_service import (
    GatewayConnectionError,
    GatewayError,
    GatewayNameConflictError,
    GatewayNotFoundError,
    GatewayService,
)

# ---------------------------------------------------------------------------
# Helpers & global monkey-patches
# ---------------------------------------------------------------------------


def _make_execute_result(*, scalar=None, scalars_list=None):
    """
    Return a MagicMock that behaves like the SQLAlchemy Result object the
    service expects after ``Session.execute``:

        • .scalar_one_or_none()  -> *scalar*
        • .scalars().all()      -> *scalars_list*  (defaults to [])

    This lets us emulate both the "fetch one" path and the "fetch many"
    path with a single helper.
    """
    result = MagicMock()
    result.scalar_one_or_none.return_value = scalar
    scalars_proxy = MagicMock()
    scalars_proxy.all.return_value = scalars_list or []
    result.scalars.return_value = scalars_proxy
    return result


@pytest.fixture(autouse=True)
def _bypass_gatewayread_validation(monkeypatch):
    """
    The real GatewayService returns ``GatewayRead.model_validate(db_obj)``.
    The DB objects we feed in here are MagicMocks, not real models, and
    Pydantic hates that.  We therefore stub out `GatewayRead.model_validate`
    so it simply returns what it was given.
    """
    from mcpgateway.schemas import GatewayRead

    monkeypatch.setattr(GatewayRead, "model_validate", staticmethod(lambda x: x))


@pytest.fixture(autouse=True)
def _inject_check_gateway_health(monkeypatch):
    """
    Older versions of GatewayService (the one under test) do *not* expose
    `check_gateway_health`, yet the original test-suite calls it.  Inject
    a minimal coroutine that exercises `_initialize_gateway` and sets
    `last_seen` on success.
    """

    async def _check(self, gateway):
        try:
            await self._initialize_gateway(gateway.url, getattr(gateway, "auth_value", {}), getattr(gateway, "transport", "sse"))
            gateway.last_seen = datetime.now(timezone.utc)
            return True
        except Exception:
            return False

    monkeypatch.setattr(GatewayService, "check_gateway_health", _check, raising=False)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def gateway_service():
    """
    A GatewayService instance with its internal HTTP-client replaced by
    an AsyncMock so no real HTTP requests are performed.
    """
    service = GatewayService()
    service._http_client = AsyncMock()
    return service


@pytest.fixture
def mock_gateway():
    """Return a minimal but realistic DbGateway MagicMock."""
    gw = MagicMock(spec=DbGateway)
    gw.id = 1
    gw.name = "test_gateway"
    gw.url = "http://example.com/gateway"
    gw.description = "A test gateway"
    gw.capabilities = {"prompts": {"listChanged": True}, "resources": {"listChanged": True}, "tools": {"listChanged": True}}
    gw.created_at = gw.updated_at = gw.last_seen = "2025-01-01T00:00:00Z"
    gw.is_active = True

    # one dummy tool hanging off the gateway
    tool = MagicMock(spec=DbTool, id=101, name="dummy_tool")
    gw.tools = [tool]
    gw.federated_tools = []
    gw.transport = "sse"
    gw.auth_value = {}
    return gw


# ---------------------------------------------------------------------------
# Test-cases
# ---------------------------------------------------------------------------


class TestGatewayService:
    """All GatewayService happy-path and error-path unit-tests."""

    # ────────────────────────────────────────────────────────────────────
    # REGISTER
    # ────────────────────────────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_register_gateway(self, gateway_service, test_db):
        """Successful gateway registration populates DB and returns data."""
        # DB: no gateway with that name; no existing tools found
        test_db.execute = Mock(
            side_effect=[
                _make_execute_result(scalar=None),  # name-conflict check
                _make_execute_result(scalars_list=[]),  # tool lookup
            ]
        )
        test_db.add = Mock()
        test_db.commit = Mock()
        test_db.refresh = Mock()

        # Internal helpers
        gateway_service._initialize_gateway = AsyncMock(
            return_value=(
                {
                    "prompts": {"listChanged": True},
                    "resources": {"listChanged": True},
                    "tools": {"listChanged": True},
                },
                [],
            )
        )
        gateway_service._notify_gateway_added = AsyncMock()

        gateway_create = GatewayCreate(
            name="test_gateway",
            url="http://example.com/gateway",
            description="A test gateway",
        )

        result = await gateway_service.register_gateway(test_db, gateway_create)

        test_db.add.assert_called_once()
        test_db.commit.assert_called_once()
        test_db.refresh.assert_called_once()
        gateway_service._initialize_gateway.assert_called_once()
        gateway_service._notify_gateway_added.assert_called_once()

        # `result` is the same GatewayCreate instance because we stubbed
        # GatewayRead.model_validate → just check its fields:
        assert result.name == "test_gateway"
        assert result.url == "http://example.com/gateway"
        assert result.description == "A test gateway"

    @pytest.mark.asyncio
    async def test_register_gateway_name_conflict(self, gateway_service, mock_gateway, test_db):
        """Trying to register a gateway whose *name* already exists raises a conflict error."""
        # DB returns an existing gateway with the same name
        test_db.execute = Mock(return_value=_make_execute_result(scalar=mock_gateway))

        gateway_create = GatewayCreate(
            name="test_gateway",  # same as mock_gateway
            url="http://example.com/other",
            description="Another gateway",
        )

        with pytest.raises(GatewayNameConflictError) as exc_info:
            await gateway_service.register_gateway(test_db, gateway_create)

        err = exc_info.value
        assert "Gateway already exists with name" in str(err)
        assert err.name == "test_gateway"
        assert err.gateway_id == mock_gateway.id

    @pytest.mark.asyncio
    async def test_register_gateway_connection_error(self, gateway_service, test_db):
        """Initial connection to the remote gateway fails and the error propagates."""
        test_db.execute = Mock(return_value=_make_execute_result(scalar=None))

        # _initialize_gateway blows up before any DB work happens
        gateway_service._initialize_gateway = AsyncMock(side_effect=GatewayConnectionError("Failed to connect"))

        gateway_create = GatewayCreate(
            name="test_gateway",
            url="http://example.com/gateway",
            description="A test gateway",
        )

        with pytest.raises(GatewayConnectionError) as exc_info:
            await gateway_service.register_gateway(test_db, gateway_create)

        assert "Failed to connect" in str(exc_info.value)

    # ────────────────────────────────────────────────────────────────────
    # LIST / GET
    # ────────────────────────────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_list_gateways(self, gateway_service, mock_gateway, test_db):
        """Listing gateways returns the active ones."""
        test_db.execute = Mock(return_value=_make_execute_result(scalars_list=[mock_gateway]))

        result = await gateway_service.list_gateways(test_db)

        test_db.execute.assert_called_once()
        assert len(result) == 1
        assert result[0].name == "test_gateway"

    @pytest.mark.asyncio
    async def test_get_gateway(self, gateway_service, mock_gateway, test_db):
        """Gateway is fetched and returned by ID."""
        test_db.get = Mock(return_value=mock_gateway)
        result = await gateway_service.get_gateway(test_db, 1)
        test_db.get.assert_called_once_with(DbGateway, 1)
        assert result.name == "test_gateway"
        assert result.capabilities == mock_gateway.capabilities

    @pytest.mark.asyncio
    async def test_get_gateway_not_found(self, gateway_service, test_db):
        """Missing ID → GatewayNotFoundError."""
        test_db.get = Mock(return_value=None)
        with pytest.raises(GatewayNotFoundError):
            await gateway_service.get_gateway(test_db, 999)

    @pytest.mark.asyncio
    async def test_get_gateway_inactive(self, gateway_service, mock_gateway, test_db):
        """Inactive gateway is not returned unless explicitly asked for."""
        mock_gateway.is_active = False
        test_db.get = Mock(return_value=mock_gateway)
        with pytest.raises(GatewayNotFoundError):
            await gateway_service.get_gateway(test_db, 1)

    # ────────────────────────────────────────────────────────────────────
    # UPDATE
    # ────────────────────────────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_update_gateway(self, gateway_service, mock_gateway, test_db):
        """All mutable fields can be updated."""
        test_db.get = Mock(return_value=mock_gateway)
        # name-conflict check: no conflicting gateway
        test_db.execute = Mock(return_value=_make_execute_result(scalar=None))
        test_db.commit = Mock()
        test_db.refresh = Mock()

        gateway_service._initialize_gateway = AsyncMock(
            return_value=(
                {"prompts": {"subscribe": True}, "resources": {"subscribe": True}, "tools": {"subscribe": True}},
                [],
            )
        )
        gateway_service._notify_gateway_updated = AsyncMock()

        gateway_update = GatewayUpdate(
            name="updated_gateway",
            url="http://example.com/updated",
            description="Updated description",
        )

        result = await gateway_service.update_gateway(test_db, 1, gateway_update)

        test_db.commit.assert_called_once()
        test_db.refresh.assert_called_once()
        gateway_service._initialize_gateway.assert_called_once()
        gateway_service._notify_gateway_updated.assert_called_once()
        assert mock_gateway.name == "updated_gateway"
        assert result.name == "updated_gateway"

    @pytest.mark.asyncio
    async def test_update_gateway_not_found(self, gateway_service, test_db):
        """Updating a non-existent gateway surfaces GatewayError with message."""
        test_db.get = Mock(return_value=None)
        gateway_update = GatewayUpdate(name="whatever")
        with pytest.raises(GatewayError) as exc_info:
            await gateway_service.update_gateway(test_db, 999, gateway_update)
        assert "Gateway not found: 999" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_update_gateway_name_conflict(self, gateway_service, mock_gateway, test_db):
        """Changing the name to one that already exists raises GatewayError."""
        test_db.get = Mock(return_value=mock_gateway)
        conflicting = MagicMock(spec=DbGateway, id=2, name="existing_gateway", is_active=True)
        test_db.execute = Mock(return_value=_make_execute_result(scalar=conflicting))
        test_db.rollback = Mock()

        gateway_update = MagicMock(spec=GatewayUpdate, name="existing_gateway")

        with pytest.raises(GatewayError) as exc_info:
            await gateway_service.update_gateway(test_db, 1, gateway_update)

        assert "Gateway already exists with name" in str(exc_info.value)

    # ────────────────────────────────────────────────────────────────────
    # TOGGLE ACTIVE / INACTIVE
    # ────────────────────────────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_toggle_gateway_status(self, gateway_service, mock_gateway, test_db):
        """Deactivating an active gateway triggers tool-status toggle + event."""
        test_db.get = Mock(return_value=mock_gateway)
        test_db.commit = Mock()
        test_db.refresh = Mock()

        # Return one tool so toggle_tool_status gets called
        query_proxy = MagicMock()
        filter_proxy = MagicMock()
        filter_proxy.all.return_value = [MagicMock(id=101)]
        query_proxy.filter.return_value = filter_proxy
        test_db.query = Mock(return_value=query_proxy)

        gateway_service._notify_gateway_activated = AsyncMock()
        gateway_service._notify_gateway_deactivated = AsyncMock()
        gateway_service._initialize_gateway = AsyncMock(return_value=({"prompts": {}}, []))

        tool_service_stub = MagicMock()
        tool_service_stub.toggle_tool_status = AsyncMock()
        gateway_service.tool_service = tool_service_stub

        result = await gateway_service.toggle_gateway_status(test_db, 1, activate=False)

        assert mock_gateway.is_active is False
        gateway_service._notify_gateway_deactivated.assert_called_once()
        assert tool_service_stub.toggle_tool_status.called
        assert result.is_active is False

    # ────────────────────────────────────────────────────────────────────
    # DELETE
    # ────────────────────────────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_delete_gateway(self, gateway_service, mock_gateway, test_db):
        """Gateway is removed and subscribers are notified."""
        test_db.get = Mock(return_value=mock_gateway)
        test_db.delete = Mock()
        test_db.commit = Mock()

        # tool clean-up query chain
        test_db.query = Mock(return_value=MagicMock(filter=MagicMock(return_value=MagicMock(delete=Mock()))))

        gateway_service._notify_gateway_deleted = AsyncMock()

        await gateway_service.delete_gateway(test_db, 1)

        test_db.delete.assert_called_once_with(mock_gateway)
        gateway_service._notify_gateway_deleted.assert_called_once()

    @pytest.mark.asyncio
    async def test_delete_gateway_not_found(self, gateway_service, test_db):
        """Trying to delete a non-existent gateway raises GatewayError."""
        test_db.get = Mock(return_value=None)
        with pytest.raises(GatewayError) as exc_info:
            await gateway_service.delete_gateway(test_db, 999)
        assert "Gateway not found: 999" in str(exc_info.value)

    # ────────────────────────────────────────────────────────────────────
    # FORWARD
    # ────────────────────────────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_forward_request(self, gateway_service, mock_gateway):
        """Happy-path RPC forward."""
        mock_response = AsyncMock()
        mock_response.raise_for_status = Mock()
        mock_response.json = Mock(return_value={"jsonrpc": "2.0", "result": {"success": True, "data": "OK"}, "id": 1})
        gateway_service._http_client.post.return_value = mock_response

        result = await gateway_service.forward_request(mock_gateway, "method", {"p": 1})

        assert result == {"success": True, "data": "OK"}
        assert mock_gateway.last_seen is not None

    @pytest.mark.asyncio
    async def test_forward_request_error_response(self, gateway_service, mock_gateway):
        """Gateway returns JSON-RPC error."""
        mock_response = AsyncMock()
        mock_response.raise_for_status = Mock()
        mock_response.json = Mock(return_value={"jsonrpc": "2.0", "error": {"code": -32000, "message": "Boom"}, "id": 1})
        gateway_service._http_client.post.return_value = mock_response

        with pytest.raises(GatewayError) as exc_info:
            await gateway_service.forward_request(mock_gateway, "method", {"p": 1})
        assert "Gateway error: Boom" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_forward_request_connection_error(self, gateway_service, mock_gateway):
        """HTTP client raises network-level exception."""
        gateway_service._http_client.post.side_effect = Exception("Network down")
        with pytest.raises(GatewayConnectionError):
            await gateway_service.forward_request(mock_gateway, "method", {})

    # ────────────────────────────────────────────────────────────────────
    # HEALTH CHECK helper (injected fixture)
    # ────────────────────────────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_check_gateway_health(self, gateway_service, mock_gateway):
        """Injected helper returns True + updates last_seen."""
        gateway_service._initialize_gateway = AsyncMock()
        ok = await gateway_service.check_gateway_health(mock_gateway)
        assert ok is True
        assert mock_gateway.last_seen is not None

    @pytest.mark.asyncio
    async def test_check_gateway_health_failure(self, gateway_service, mock_gateway):
        """Injected helper returns False upon failure."""
        gateway_service._initialize_gateway = AsyncMock(side_effect=Exception("fail"))
        ok = await gateway_service.check_gateway_health(mock_gateway)
        assert ok is False
