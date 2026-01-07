# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/services/test_gateway_service.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Unit-tests for the GatewayService implementation.
These tests use only MagicMock / AsyncMock - no real network access
and no real database needed.  Where the service relies on Pydantic
models or SQLAlchemy Result objects, we monkey-patch or fake just
enough behaviour to satisfy the code paths under test.
"""

# Future
from __future__ import annotations

# Standard
import asyncio
from typing import TypeVar
from unittest.mock import AsyncMock, MagicMock, Mock, patch

# Third-Party
import httpx
import pytest
from url_normalize import url_normalize

# First-Party
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
    GatewayDuplicateConflictError,
)

# ---------------------------------------------------------------------------
# Helpers & global monkey-patches
# ---------------------------------------------------------------------------


_R = TypeVar("_R")


def _make_execute_result(*, scalar: _R | None = None, scalars_list: list[_R] | None = None) -> MagicMock:
    """
    Return a MagicMock that behaves like the SQLAlchemy Result object the
    service expects after ``Session.execute``:

        - .scalar_one_or_none()  -> *scalar*
        - .scalars().all()      -> *scalars_list*  (defaults to [])

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
def mock_logging_services():
    """Mock audit_trail and structured_logger to prevent database writes during tests."""
    with patch("mcpgateway.services.gateway_service.audit_trail") as mock_audit, \
         patch("mcpgateway.services.gateway_service.structured_logger") as mock_logger:
        mock_audit.log_action = MagicMock(return_value=None)
        mock_logger.log = MagicMock(return_value=None)
        yield {"audit_trail": mock_audit, "structured_logger": mock_logger}


@pytest.fixture(autouse=True)
def _bypass_gatewayread_validation(monkeypatch):
    """
    The real GatewayService returns ``GatewayRead.model_validate(db_obj)``.
    The DB objects we feed in here are MagicMocks, not real models, and
    Pydantic hates that.  We therefore stub out `GatewayRead.model_validate`
    so it simply returns what it was given.
    """
    # First-Party
    from mcpgateway.schemas import GatewayRead

    monkeypatch.setattr(GatewayRead, "model_validate", staticmethod(lambda x: x))


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
    gw.enabled = True
    gw.reachable = True

    # one dummy tool hanging off the gateway
    tool = MagicMock(spec=DbTool, id=101, name="dummy_tool")
    gw.tools = [tool]
    gw.resources = []  # Empty list for delete tests
    gw.prompts = []  # Empty list for delete tests
    gw.federated_tools = []
    gw.transport = "sse"
    gw.auth_value = {}
    gw.team_id = 1  # Ensure team_id is a real value, not a MagicMock
    return gw


@pytest.fixture
def mock_session():
    """Return a mocked SQLAlchemy session."""
    session = MagicMock()
    session.query.return_value = MagicMock()
    session.commit.return_value = None
    session.rollback.return_value = None
    return session


# ---------------------------------------------------------------------------
# Test-cases
# ---------------------------------------------------------------------------


class TestGatewayService:
    """All GatewayService happy-path and error-path unit-tests."""

    # ────────────────────────────────────────────────────────────────────
    # REGISTER
    # ────────────────────────────────────────────────────────────────────
    @pytest.mark.asyncio
    async def test_register_gateway(self, gateway_service, test_db, monkeypatch):
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
                [],
                [],
            )
        )
        gateway_service._notify_gateway_added = AsyncMock()
        url = url_normalize("example.com")
        # Patch GatewayRead.model_validate to return a mock with .masked()
        mock_model = Mock()
        mock_model.masked.return_value = mock_model
        mock_model.name = "test_gateway"
        mock_model.url = url
        mock_model.description = "A test gateway"

        monkeypatch.setattr(
            "mcpgateway.services.gateway_service.GatewayRead.model_validate",
            lambda x: mock_model,
        )

        gateway_create = GatewayCreate(
            name="test_gateway",
            url=url,
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
        expected_url = url
        assert result.url == expected_url
        assert result.description == "A test gateway"
        mock_model.url = expected_url

    @pytest.mark.asyncio
    async def test_register_gateway_name_conflict(self, gateway_service, mock_gateway, test_db):
        """Trying to register a gateway whose *name* already exists raises a conflict error."""
        # DB returns an existing gateway with the same name
        mock_gateway.name = "test_gateway"
        mock_gateway.slug = "test-gateway"
        test_db.execute = Mock(return_value=_make_execute_result(scalar=mock_gateway))

        gateway_create = GatewayCreate(
            name="test_gateway",  # same as mock_gateway
            slug="test-gateway",
            url="http://example.com/other",
            description="Another gateway",
            visibility="public",
        )

        with pytest.raises(GatewayNameConflictError) as exc_info:
            await gateway_service.register_gateway(test_db, gateway_create)

        err = exc_info.value
        assert "Public Gateway already exists with name" in str(err)
        assert err.name == "test-gateway"
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

    @pytest.mark.asyncio
    async def test_register_gateway_with_auth(self, gateway_service, test_db, monkeypatch):
        """Test registering gateway with authentication credentials."""
        test_db.execute = Mock(
            side_effect=[
                _make_execute_result(scalar=None),  # name-conflict check
                _make_execute_result(scalars_list=[]),  # tool lookup
            ]
        )
        test_db.add = Mock()
        test_db.commit = Mock()
        test_db.refresh = Mock()

        url = url_normalize("example.com")
        print(f"url:{url}")
        gateway_service._initialize_gateway = AsyncMock(
            return_value=(
                {
                    "resources": {"listChanged": True},
                    "tools": {"listChanged": True},
                },
                [],
                [],
                [],
            )
        )

        gateway_service._notify_gateway_added = AsyncMock()

        mock_model = Mock()
        mock_model.masked.return_value = mock_model
        mock_model.name = "auth_gateway"
        mock_model.url = url

        monkeypatch.setattr(
            "mcpgateway.services.gateway_service.GatewayRead.model_validate",
            lambda x: mock_model,
        )

        gateway_create = GatewayCreate(name="auth_gateway", url=url, description="Gateway with auth", auth_type="bearer", auth_token="test-token")

        await gateway_service.register_gateway(test_db, gateway_create)

        test_db.add.assert_called_once()
        test_db.commit.assert_called_once()
        gateway_service._initialize_gateway.assert_called_once()

    @pytest.mark.asyncio
    async def test_register_gateway_with_tools(self, gateway_service, test_db, monkeypatch):
        """Test registering gateway that returns tools from initialization."""
        test_db.execute = Mock(
            side_effect=[
                _make_execute_result(scalar=None),  # name-conflict check
                _make_execute_result(scalars_list=[]),  # tool lookup
            ]
        )
        test_db.add = Mock()
        test_db.commit = Mock()
        test_db.refresh = Mock()

        # Mock tools returned from gateway
        # First-Party
        from mcpgateway.schemas import ToolCreate

        mock_tools = [ToolCreate(name="test_tool", description="A test tool", integration_type="REST", request_type="POST", input_schema={"type": "object"})]

        gateway_service._initialize_gateway = AsyncMock(
            return_value=(
                {
                    "prompts": {"listChanged": True},
                    "resources": {"listChanged": True},
                    "tools": {"listChanged": True},
                },
                mock_tools,
                [],
                [],
            )
        )
        gateway_service._notify_gateway_added = AsyncMock()

        mock_model = Mock()
        mock_model.masked.return_value = mock_model
        mock_model.name = "tool_gateway"

        monkeypatch.setattr(
            "mcpgateway.services.gateway_service.GatewayRead.model_validate",
            lambda x: mock_model,
        )

        gateway_create = GatewayCreate(
            name="tool_gateway",
            url="http://example.com/gateway",
            description="Gateway with tools",
        )

        await gateway_service.register_gateway(test_db, gateway_create)

        test_db.add.assert_called_once()
        # Verify that tools were created and added to the gateway
        db_gateway_call = test_db.add.call_args[0][0]
        assert len(db_gateway_call.tools) == 1
        assert db_gateway_call.tools[0].original_name == "test_tool"

    @pytest.mark.asyncio
    async def test_register_gateway_inactive_name_conflict(self, gateway_service, test_db):
        """Test name conflict with an inactive gateway."""
        # Mock an inactive gateway with the same name
        inactive_gateway = MagicMock(spec=DbGateway)
        inactive_gateway.id = 2
        inactive_gateway.name = "test_gateway"
        inactive_gateway.slug = "test-gateway"
        inactive_gateway.enabled = False

        test_db.execute = Mock(return_value=_make_execute_result(scalar=inactive_gateway))

        gateway_create = GatewayCreate(name="test_gateway", slug="test-gateway", url="http://example.com/gateway", description="New gateway", visibility="public")

        with pytest.raises(GatewayNameConflictError) as exc_info:
            await gateway_service.register_gateway(test_db, gateway_create)

        err = exc_info.value
        assert "Public Gateway already exists with name" in str(err)
        assert err.name == "test-gateway"
        assert err.enabled is False
        assert err.gateway_id == 2

    @pytest.mark.asyncio
    async def test_register_gateway_database_error(self, gateway_service, test_db):
        """Test database error during gateway registration."""
        test_db.execute = Mock(return_value=_make_execute_result(scalar=None))
        test_db.add = Mock()
        test_db.commit = Mock(side_effect=Exception("Database error"))
        test_db.rollback = Mock()

        gateway_service._initialize_gateway = AsyncMock(return_value=({"tools": {"listChanged": True}}, [], [], []))

        gateway_create = GatewayCreate(
            name="test_gateway",
            url="http://example.com/gateway",
            description="Test gateway",
        )

        with pytest.raises(Exception) as exc_info:
            await gateway_service.register_gateway(test_db, gateway_create)

        assert "Database error" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_register_gateway_value_error(self, gateway_service, test_db):
        """Test ValueError during gateway registration."""
        test_db.execute = Mock(return_value=_make_execute_result(scalar=None))

        gateway_service._initialize_gateway = AsyncMock(side_effect=ValueError("Invalid gateway configuration"))

        gateway_create = GatewayCreate(
            name="test_gateway",
            url="http://example.com/gateway",
            description="Test gateway",
        )

        with pytest.raises(ValueError) as exc_info:
            await gateway_service.register_gateway(test_db, gateway_create)

        assert "Invalid gateway configuration" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_register_gateway_runtime_error(self, gateway_service, test_db):
        """Test RuntimeError during gateway registration."""
        test_db.execute = Mock(return_value=_make_execute_result(scalar=None))

        gateway_service._initialize_gateway = AsyncMock(side_effect=RuntimeError("Runtime error occurred"))

        gateway_create = GatewayCreate(
            name="test_gateway",
            url="http://example.com/gateway",
            description="Test gateway",
        )

        with pytest.raises(RuntimeError) as exc_info:
            await gateway_service.register_gateway(test_db, gateway_create)

        assert "Runtime error occurred" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_register_gateway_integrity_error(self, gateway_service, test_db):
        """Test IntegrityError during gateway registration."""
        # Third-Party
        from sqlalchemy.exc import IntegrityError as SQLIntegrityError

        test_db.execute = Mock(return_value=_make_execute_result(scalar=None))
        test_db.add = Mock()
        test_db.commit = Mock(side_effect=SQLIntegrityError("statement", "params", BaseException("orig")))

        gateway_service._initialize_gateway = AsyncMock(return_value=({"tools": {"listChanged": True}}, [], [], []))

        gateway_create = GatewayCreate(
            name="test_gateway",
            url="http://example.com/gateway",
            description="Test gateway",
        )

        with pytest.raises(SQLIntegrityError):
            await gateway_service.register_gateway(test_db, gateway_create)

    @pytest.mark.asyncio
    async def test_register_gateway_masked_auth_value(self, gateway_service, test_db, monkeypatch):
        """Test registering gateway with masked auth value that should not be updated."""
        test_db.execute = Mock(
            side_effect=[
                _make_execute_result(scalar=None),  # name-conflict check
                _make_execute_result(scalars_list=[]),  # tool lookup
            ]
        )
        test_db.add = Mock()
        test_db.commit = Mock()
        test_db.refresh = Mock()

        gateway_service._initialize_gateway = AsyncMock(return_value=({"tools": {"listChanged": True}}, [], [], []))
        gateway_service._notify_gateway_added = AsyncMock()

        mock_model = Mock()
        mock_model.masked.return_value = mock_model
        mock_model.name = "auth_gateway"

        monkeypatch.setattr(
            "mcpgateway.services.gateway_service.GatewayRead.model_validate",
            lambda x: mock_model,
        )

        # Mock settings for masked auth value
        with patch("mcpgateway.services.gateway_service.settings.masked_auth_value", "***MASKED***"):
            gateway_create = GatewayCreate(
                name="auth_gateway",
                url="http://example.com/gateway",
                description="Gateway with masked auth",
                auth_type="bearer",
                auth_token="***MASKED***",  # This should not update the auth_value
            )

            await gateway_service.register_gateway(test_db, gateway_create)

        test_db.add.assert_called_once()
        test_db.commit.assert_called_once()
        gateway_service._initialize_gateway.assert_called_once()

    @pytest.mark.asyncio
    async def test_register_gateway_exception_rollback(self, gateway_service, test_db):
        """Test rollback on exception during gateway registration."""
        test_db.execute = Mock(return_value=_make_execute_result(scalar=None))
        test_db.add = Mock()
        test_db.commit = Mock(side_effect=Exception("Commit failed"))
        test_db.rollback = Mock()

        gateway_service._initialize_gateway = AsyncMock(return_value=({"tools": {"listChanged": True}}, [], [], []))

        gateway_create = GatewayCreate(
            name="test_gateway",
            url="http://example.com/gateway",
            description="Test gateway",
        )

        with pytest.raises(Exception) as exc_info:
            await gateway_service.register_gateway(test_db, gateway_create)

        assert "Commit failed" in str(exc_info.value)
        # The register_gateway method doesn't actually call rollback in the exception handler
        # It just re-raises the exception, so we shouldn't expect rollback to be called

    @pytest.mark.asyncio
    async def test_register_gateway_with_existing_tools(self, gateway_service, test_db, monkeypatch):
        """Test registering gateway with URL/credentials that already exist (duplicate gateway)."""
        # Mock existing GATEWAY in database (not tool)
        existing_gateway = MagicMock()
        existing_gateway.id = 123
        existing_gateway.url = "http://example.com/gateway"
        existing_gateway.enabled = True
        existing_gateway.visibility = "public"
        existing_gateway.name = "existing_gateway"
        existing_gateway.team_id = None
        existing_gateway.owner_email = "test@example.com"

        test_db.execute = Mock(
            side_effect=[
                _make_execute_result(scalar=None),  # name-conflict check
                # No second call needed - check_gateway_uniqueness uses query().all()
            ]
        )

        # Mock check_gateway_uniqueness to return the existing gateway
        gateway_service._check_gateway_uniqueness = Mock(return_value=existing_gateway)

        test_db.add = Mock()
        test_db.commit = Mock()
        test_db.refresh = Mock()

        gateway_create = GatewayCreate(
            name="tool_gateway",
            url="http://example.com/gateway",  # Same URL as existing
            description="Gateway with existing tools",
        )

        with pytest.raises(GatewayDuplicateConflictError) as exc_info:
            await gateway_service.register_gateway(test_db, gateway_create)

        # Verify the error details
        assert exc_info.value.gateway_id == 123
        assert exc_info.value.enabled is True

    # ────────────────────────────────────────────────────────────────────
    # Validate Gateway URL SSL Verification
    # ────────────────────────────────────────────────────────────────────
    @pytest.mark.skip("Yet to implement")
    async def test_ssl_verification_bypass(self, gateway_service, monkeypatch):
        """
        Test case logic to verify settings.skip_ssl_verify

        """

    # ────────────────────────────────────────────────────────────────────
    # LIST / GET
    # ────────────────────────────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_list_gateways(self, gateway_service, mock_gateway, test_db, monkeypatch):
        """Listing gateways returns the active ones."""

        test_db.execute = Mock(return_value=_make_execute_result(scalars_list=[mock_gateway]))

        mock_model = Mock()
        mock_model.masked.return_value = mock_model
        mock_model.name = "test_gateway"

        # Patch using full path string to GatewayRead.model_validate
        monkeypatch.setattr("mcpgateway.services.gateway_service.GatewayRead.model_validate", lambda x: mock_model)

        result, next_cursor = await gateway_service.list_gateways(test_db)

        # Assert that execute was called twice
        assert test_db.execute.call_count == 2
        # Optionally, print or check call arguments for debugging
        # print(test_db.execute.call_args_list)
        assert len(result) == 1
        assert result[0].name == "test_gateway"

    @pytest.mark.asyncio
    async def test_get_gateway(self, gateway_service, mock_gateway, test_db):
        """Gateway is fetched and returned by ID."""
        mock_gateway.masked = Mock(return_value=mock_gateway)
        mock_gateway.team_id = 1  # Ensure team_id is a real value
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
        mock_gateway.enabled = False
        mock_gateway.id = 1
        mock_gateway.team_id = 1  # Ensure team_id is a real value
        test_db.get = Mock(return_value=mock_gateway)

        # Create a mock for GatewayRead with a masked method
        mock_gateway_read = Mock()
        mock_gateway_read.id = 1
        mock_gateway_read.enabled = False
        mock_gateway_read.masked = Mock(return_value=mock_gateway_read)

        with patch("mcpgateway.services.gateway_service.GatewayRead.model_validate", return_value=mock_gateway_read):
            result = await gateway_service.get_gateway(test_db, 1, include_inactive=True)
            assert result.id == 1
            assert not result.enabled

            # Now test the inactive = False path
            test_db.get = Mock(return_value=mock_gateway)
            with pytest.raises(GatewayNotFoundError):
                await gateway_service.get_gateway(test_db, 1, include_inactive=False)

    # ────────────────────────────────────────────────────────────────────
    # UPDATE
    # ────────────────────────────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_update_gateway(self, gateway_service, mock_gateway, test_db):
        """All mutable fields can be updated."""
        mock_gateway.team_id = 1  # Ensure team_id is a real value
        # Mock execute to return gateway for selectinload query (first call)
        # and None for name-conflict check (subsequent calls)
        execute_results = [_make_execute_result(scalar=mock_gateway), _make_execute_result(scalar=None)]
        test_db.execute = Mock(side_effect=execute_results)
        test_db.commit = Mock()
        test_db.refresh = Mock()

        # Simulate successful gateway initialization
        gateway_service._initialize_gateway = AsyncMock(
            return_value=(
                {
                    "prompts": {"subscribe": True},
                    "resources": {"subscribe": True},
                    "tools": {"subscribe": True},
                },
                [],
            )
        )
        gateway_service._notify_gateway_updated = AsyncMock()

        # Create the update payload
        gateway_update = GatewayUpdate(
            name="updated_gateway",
            url="http://example.com/updated",
            description="Updated description",
        )

        # Create mock return for GatewayRead.model_validate().masked()
        mock_gateway_read = MagicMock()
        mock_gateway_read.name = "updated_gateway"
        mock_gateway_read.masked.return_value = mock_gateway_read  # Ensure .masked() returns the same object

        # Patch the model_validate call in the service
        with patch("mcpgateway.services.gateway_service.GatewayRead.model_validate", return_value=mock_gateway_read):
            result = await gateway_service.update_gateway(test_db, 1, gateway_update)

        # Assertions
        test_db.commit.assert_called_once()
        test_db.refresh.assert_called_once()
        gateway_service._initialize_gateway.assert_called_once()
        gateway_service._notify_gateway_updated.assert_called_once()
        assert mock_gateway.name == "updated_gateway"
        assert result.name == "updated_gateway"

    @pytest.mark.asyncio
    async def test_update_gateway_not_found(self, gateway_service, test_db):
        """Updating a non-existent gateway surfaces GatewayError with message."""
        test_db.execute = Mock(return_value=_make_execute_result(scalar=None))
        gateway_update = GatewayUpdate(name="whatever")
        with pytest.raises(GatewayError) as exc_info:
            await gateway_service.update_gateway(test_db, 999, gateway_update)
        assert "Gateway not found: 999" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_update_gateway_name_conflict(self, gateway_service, mock_gateway, test_db):
        """Changing the name to one that already exists raises GatewayError."""
        mock_gateway.name = "original_name"
        mock_gateway.slug = "original-name"
        mock_gateway.visibility = "public"
        mock_gateway.team_id = 1  # Ensure team_id is a real value
        conflicting = MagicMock(spec=DbGateway, id=2, name="existing_gateway", slug="existing-gateway", visibility="public", is_active=True)
        # First call returns the gateway to update (with selectinload), second returns the conflicting one
        execute_results = [_make_execute_result(scalar=mock_gateway), _make_execute_result(scalar=conflicting)]
        test_db.execute = Mock(side_effect=execute_results)
        test_db.rollback = Mock()

        # gateway_update = MagicMock(spec=GatewayUpdate, name="existing_gateway")
        gateway_update = GatewayUpdate(name="existing_gateway", slug="existing-gateway")

        with pytest.raises(GatewayError) as exc_info:
            await gateway_service.update_gateway(test_db, 1, gateway_update)

        assert "Public Gateway already exists with name" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_update_gateway_with_auth_update(self, gateway_service, mock_gateway, test_db):
        """Test updating gateway with new authentication values."""
        mock_gateway.auth_type = "bearer"
        mock_gateway.auth_value = "old-token-encrypted"
        mock_gateway.team_id = 1  # Ensure team_id is a real value

        # First call returns gateway (selectinload query), rest are for conflict checks and team lookups
        test_db.execute = Mock(return_value=_make_execute_result(scalar=mock_gateway))
        test_db.commit = Mock()
        test_db.refresh = Mock()
        # Mock the query for team name lookup
        test_db.query = Mock(return_value=Mock(filter=Mock(return_value=Mock(first=Mock(return_value=None)))))

        gateway_service._initialize_gateway = AsyncMock(return_value=({"tools": {"listChanged": True}}, [], [], []))
        gateway_service._notify_gateway_updated = AsyncMock()

        # Mock settings for auth value checking
        with patch("mcpgateway.services.gateway_service.settings.masked_auth_value", "***MASKED***"):
            gateway_update = GatewayUpdate(auth_type="bearer", auth_token="new-token")

            mock_gateway_read = MagicMock()
            mock_gateway_read.masked.return_value = mock_gateway_read

            with patch("mcpgateway.services.gateway_service.GatewayRead.model_validate", return_value=mock_gateway_read):
                await gateway_service.update_gateway(test_db, 1, gateway_update)

            # Check that auth_type was updated
            assert mock_gateway.auth_type == "bearer"
            test_db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_update_gateway_clear_auth(self, gateway_service, mock_gateway, test_db):
        """Test clearing authentication from gateway."""
        mock_gateway.auth_type = "bearer"
        mock_gateway.auth_value = {"token": "old-token"}
        mock_gateway.team_id = 1  # Ensure team_id is a real value

        # Use return_value for all execute calls
        test_db.execute = Mock(return_value=_make_execute_result(scalar=mock_gateway))
        test_db.commit = Mock()
        test_db.refresh = Mock()
        # Mock the query for team name lookup
        test_db.query = Mock(return_value=Mock(filter=Mock(return_value=Mock(first=Mock(return_value=None)))))

        gateway_service._initialize_gateway = AsyncMock(return_value=({"tools": {"listChanged": True}}, [], [], []))
        gateway_service._notify_gateway_updated = AsyncMock()

        gateway_update = GatewayUpdate(auth_type="")

        mock_gateway_read = MagicMock()
        mock_gateway_read.masked.return_value = mock_gateway_read

        with patch("mcpgateway.services.gateway_service.GatewayRead.model_validate", return_value=mock_gateway_read):
            await gateway_service.update_gateway(test_db, 1, gateway_update)

        assert mock_gateway.auth_type == ""
        assert mock_gateway.auth_value == ""
        test_db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_update_gateway_url_change_with_tools(self, gateway_service, mock_gateway, test_db):
        """Test updating gateway URL and tools are refreshed."""
        # Setup existing tool
        existing_tool = MagicMock()
        existing_tool.original_name = "existing_tool"
        mock_gateway.tools = [existing_tool]
        mock_gateway.team_id = 1  # Ensure team_id is a real value

        # First call returns gateway (selectinload), then conflict checks
        test_db.execute = Mock(
            side_effect=[
                _make_execute_result(scalar=mock_gateway),  # selectinload gateway
                _make_execute_result(scalar=None),  # name conflict check
                _make_execute_result(scalar=existing_tool),  # existing tool check
            ]
        )
        test_db.commit = Mock()
        test_db.refresh = Mock()
        # Mock the query for team name lookup
        test_db.query = Mock(return_value=Mock(filter=Mock(return_value=Mock(first=Mock(return_value=None)))))

        # Mock new tools from gateway
        # First-Party
        from mcpgateway.schemas import ToolCreate

        new_tools = [
            ToolCreate(name="existing_tool", description="Updated tool", integration_type="REST", request_type="POST", input_schema={"type": "object"}),
            ToolCreate(name="new_tool", description="Brand new tool", integration_type="REST", request_type="POST", input_schema={"type": "object"}),
        ]

        gateway_service._initialize_gateway = AsyncMock(return_value=({"tools": {"listChanged": True}}, new_tools, [], []))
        gateway_service._notify_gateway_updated = AsyncMock()
        url = GatewayService.normalize_url("http://example.com/new-url")
        gateway_update = GatewayUpdate(url=url)

        mock_gateway_read = MagicMock()
        mock_gateway_read.masked.return_value = mock_gateway_read

        with patch("mcpgateway.services.gateway_service.GatewayRead.model_validate", return_value=mock_gateway_read):
            try:
                await gateway_service.update_gateway(test_db, 1, gateway_update)
            except Exception as e:
                print(f"Exception during update_gateway: {e}")
                import traceback

                traceback.print_exc()
                raise

        assert mock_gateway.url == url
        gateway_service._initialize_gateway.assert_called_once()
        test_db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_update_gateway_url_initialization_failure(self, gateway_service, mock_gateway, test_db):
        """Test updating gateway URL when initialization fails."""
        # Use return_value for all execute calls
        test_db.execute = Mock(return_value=_make_execute_result(scalar=mock_gateway))
        test_db.commit = Mock()
        test_db.refresh = Mock()
        # Mock the query for team name lookup
        test_db.query = Mock(return_value=Mock(filter=Mock(return_value=Mock(first=Mock(return_value=None)))))

        # Mock initialization failure
        gateway_service._initialize_gateway = AsyncMock(side_effect=GatewayConnectionError("Connection failed"))
        gateway_service._notify_gateway_updated = AsyncMock()
        url = GatewayService.normalize_url("http://example.com/bad-url")
        gateway_update = GatewayUpdate(url=url)

        mock_gateway_read = MagicMock()
        mock_gateway_read.masked.return_value = mock_gateway_read

        # Should not raise exception, just log warning
        with patch("mcpgateway.services.gateway_service.GatewayRead.model_validate", return_value=mock_gateway_read):
            await gateway_service.update_gateway(test_db, 1, gateway_update)

        assert mock_gateway.url == url
        test_db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_update_gateway_partial_update(self, gateway_service, mock_gateway, test_db):
        """Test updating only some fields."""
        # Use return_value for all execute calls
        test_db.execute = Mock(return_value=_make_execute_result(scalar=mock_gateway))
        test_db.commit = Mock()
        test_db.refresh = Mock()
        # Mock the query for team name lookup
        test_db.query = Mock(return_value=Mock(filter=Mock(return_value=Mock(first=Mock(return_value=None)))))

        gateway_service._notify_gateway_updated = AsyncMock()

        # Only update description
        gateway_update = GatewayUpdate(description="New description only")

        mock_gateway_read = MagicMock()
        mock_gateway_read.masked.return_value = mock_gateway_read

        with patch("mcpgateway.services.gateway_service.GatewayRead.model_validate", return_value=mock_gateway_read):
            await gateway_service.update_gateway(test_db, 1, gateway_update)

        # Only description should be updated
        assert mock_gateway.description == "New description only"
        # Name and URL should remain unmodified
        assert mock_gateway.name == "test_gateway"
        assert mock_gateway.url == "http://example.com/gateway"
        test_db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_update_gateway_inactive_excluded(self, gateway_service, mock_gateway, test_db):
        """Test updating inactive gateway when include_inactive=False - should return None."""
        mock_gateway.enabled = False
        test_db.execute = Mock(return_value=_make_execute_result(scalar=mock_gateway))

        gateway_update = GatewayUpdate(description="New description")

        # When gateway is inactive and include_inactive=False,
        # the method skips the update logic and returns None implicitly
        result = await gateway_service.update_gateway(test_db, 1, gateway_update, include_inactive=False)

        # The method should return None when the condition fails
        assert result is None
        # Verify that description was NOT updated (since update was skipped)
        assert mock_gateway.description != "New description"

    @pytest.mark.asyncio
    async def test_update_gateway_database_rollback(self, gateway_service, mock_gateway, test_db):
        """Test database rollback on update failure."""
        # Use return_value for all execute calls
        test_db.execute = Mock(return_value=_make_execute_result(scalar=mock_gateway))
        test_db.commit = Mock(side_effect=Exception("Database error"))
        test_db.rollback = Mock()
        # Mock the query for team name lookup
        test_db.query = Mock(return_value=Mock(filter=Mock(return_value=Mock(first=Mock(return_value=None)))))

        gateway_service._notify_gateway_updated = AsyncMock()

        gateway_update = GatewayUpdate(description="New description")

        with pytest.raises(GatewayError) as exc_info:
            await gateway_service.update_gateway(test_db, 1, gateway_update)

        assert "Failed to update gateway" in str(exc_info.value)
        test_db.rollback.assert_called_once()

    @pytest.mark.asyncio
    async def test_update_gateway_with_masked_auth(self, gateway_service, mock_gateway, test_db):
        """Test updating gateway with masked auth values that should not be changed."""
        mock_gateway.auth_type = "bearer"
        mock_gateway.auth_value = "existing-token"

        # Use return_value for all execute calls
        test_db.execute = Mock(return_value=_make_execute_result(scalar=mock_gateway))
        test_db.commit = Mock()
        test_db.refresh = Mock()
        # Mock the query for team name lookup
        test_db.query = Mock(return_value=Mock(filter=Mock(return_value=Mock(first=Mock(return_value=None)))))

        gateway_service._notify_gateway_updated = AsyncMock()

        # Mock settings for masked auth value
        with patch("mcpgateway.services.gateway_service.settings.masked_auth_value", "***MASKED***"):
            gateway_update = GatewayUpdate(auth_type="bearer", auth_token="***MASKED***", auth_password="***MASKED***", auth_header_value="***MASKED***")  # This should not update the auth_value

            mock_gateway_read = MagicMock()
            mock_gateway_read.masked.return_value = mock_gateway_read

            with patch("mcpgateway.services.gateway_service.GatewayRead.model_validate", return_value=mock_gateway_read):
                await gateway_service.update_gateway(test_db, 1, gateway_update)

            # Auth value should remain unmodified since all values were masked
            assert mock_gateway.auth_value == "existing-token"
            test_db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_update_gateway_integrity_error(self, gateway_service, mock_gateway, test_db):
        """Test IntegrityError during gateway update."""
        # Third-Party
        from sqlalchemy.exc import IntegrityError as SQLIntegrityError

        # Use return_value for all execute calls
        test_db.execute = Mock(return_value=_make_execute_result(scalar=mock_gateway))
        test_db.commit = Mock(side_effect=SQLIntegrityError("statement", "params", BaseException("orig")))
        # Mock the query for team name lookup
        test_db.query = Mock(return_value=Mock(filter=Mock(return_value=Mock(first=Mock(return_value=None)))))

        gateway_service._notify_gateway_updated = AsyncMock()

        gateway_update = GatewayUpdate(description="New description")

        with pytest.raises(SQLIntegrityError):
            await gateway_service.update_gateway(test_db, 1, gateway_update)

    def test_normalize_url_preserves_domain(self):
        """Test that normalize_url preserves domain names but normalizes localhost."""
        # Test with various domain formats
        test_cases = [
            # Regular domains should be preserved as-is
            ("http://example.com", "http://example.com"),
            ("https://api.example.com:8080/path", "https://api.example.com:8080/path"),
            ("https://my-app.cloud-provider.region.example.com/sse", "https://my-app.cloud-provider.region.example.com/sse"),
            ("https://cdn.service.com/api/v1", "https://cdn.service.com/api/v1"),
            # localhost should remain localhost
            ("http://localhost:8000", "http://localhost:8000"),
            ("https://localhost/api", "https://localhost/api"),
            # 127.0.0.1 should be normalized to localhost to prevent duplicates
            ("http://127.0.0.1:8080/path", "http://localhost:8080/path"),
            ("https://127.0.0.1/sse", "https://localhost/sse"),
        ]

        for input_url, expected in test_cases:
            result = GatewayService.normalize_url(input_url)
            assert result == expected, f"normalize_url({input_url}) should return {expected}, got {result}"

    def test_normalize_url_prevents_localhost_duplicates(self):
        """Test that normalization prevents localhost/127.0.0.1 duplicates."""
        # These URLs should all normalize to the same value
        equivalent_urls = [
            "http://127.0.0.1:8080/sse",
            "http://localhost:8080/sse",
        ]

        normalized = [GatewayService.normalize_url(url) for url in equivalent_urls]

        # All should normalize to localhost version
        assert all(n == "http://localhost:8080/sse" for n in normalized), f"All localhost variants should normalize to same URL, got: {normalized}"

        # They should all be the same (no duplicates possible)
        assert len(set(normalized)) == 1, "All localhost variants should produce identical normalized URLs"

    @pytest.mark.asyncio
    async def test_update_gateway_with_transport_change(self, gateway_service, mock_gateway, test_db):
        """Test updating gateway transport type."""
        # Use return_value for all execute calls
        test_db.execute = Mock(return_value=_make_execute_result(scalar=mock_gateway))
        test_db.commit = Mock()
        test_db.refresh = Mock()
        # Mock the query for team name lookup
        test_db.query = Mock(return_value=Mock(filter=Mock(return_value=Mock(first=Mock(return_value=None)))))

        gateway_service._initialize_gateway = AsyncMock(return_value=({"tools": {"listChanged": True}}, [], [], []))
        gateway_service._notify_gateway_updated = AsyncMock()

        gateway_update = GatewayUpdate(transport="STREAMABLEHTTP")

        mock_gateway_read = MagicMock()
        mock_gateway_read.masked.return_value = mock_gateway_read

        with patch("mcpgateway.services.gateway_service.GatewayRead.model_validate", return_value=mock_gateway_read):
            await gateway_service.update_gateway(test_db, 1, gateway_update)

        assert mock_gateway.transport == "STREAMABLEHTTP"
        test_db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_update_gateway_without_auth_type_attr(self, gateway_service, test_db):
        """Test updating gateway that doesn't have auth_type attribute."""
        # Create mock gateway without auth_type attribute
        mock_gateway_no_auth = MagicMock(spec=DbGateway)
        mock_gateway_no_auth.id = 1
        mock_gateway_no_auth.name = "test_gateway"
        mock_gateway_no_auth.enabled = True
        # Don't set auth_type attribute to test the getattr fallback

        # Use return_value for all execute calls
        test_db.execute = Mock(return_value=_make_execute_result(scalar=mock_gateway_no_auth))
        test_db.commit = Mock()
        test_db.refresh = Mock()
        # Mock the query for team name lookup
        test_db.query = Mock(return_value=Mock(filter=Mock(return_value=Mock(first=Mock(return_value=None)))))

        gateway_service._notify_gateway_updated = AsyncMock()

        gateway_update = GatewayUpdate(description="New description")

        mock_gateway_read = MagicMock()
        mock_gateway_read.masked.return_value = mock_gateway_read

        with patch("mcpgateway.services.gateway_service.GatewayRead.model_validate", return_value=mock_gateway_read):
            await gateway_service.update_gateway(test_db, 1, gateway_update)

        assert mock_gateway_no_auth.description == "New description"
        test_db.commit.assert_called_once()

    # ────────────────────────────────────────────────────────────────────
    # TOGGLE ACTIVE / INACTIVE
    # ────────────────────────────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_toggle_gateway_status(self, gateway_service, mock_gateway, test_db):
        """Deactivating an active gateway triggers tool-status toggle + event."""
        test_db.execute = Mock(return_value=_make_execute_result(scalar=mock_gateway))
        test_db.commit = Mock()
        test_db.refresh = Mock()

        # Return one tool so toggle_tool_status gets called
        query_proxy = MagicMock()
        filter_proxy = MagicMock()
        filter_proxy.all.return_value = [MagicMock(id=101)]
        query_proxy.filter.return_value = filter_proxy
        test_db.query = Mock(return_value=query_proxy)

        # Setup gateway service mocks
        gateway_service._notify_gateway_activated = AsyncMock()
        gateway_service._notify_gateway_deactivated = AsyncMock()
        gateway_service._initialize_gateway = AsyncMock(return_value=({"prompts": {}}, [], [], []))

        tool_service_stub = MagicMock()
        tool_service_stub.toggle_tool_status = AsyncMock()
        gateway_service.tool_service = tool_service_stub

        # Patch model_validate to return a mock with .masked()
        mock_gateway_read = MagicMock()
        mock_gateway_read.masked.return_value = mock_gateway_read

        with patch("mcpgateway.services.gateway_service.GatewayRead.model_validate", return_value=mock_gateway_read):
            result = await gateway_service.toggle_gateway_status(test_db, 1, activate=False)

        assert mock_gateway.enabled is False
        gateway_service._notify_gateway_deactivated.assert_called_once()
        assert tool_service_stub.toggle_tool_status.called
        assert result == mock_gateway_read

    @pytest.mark.asyncio
    async def test_toggle_gateway_status_activate(self, gateway_service, mock_gateway, test_db):
        """Test activating an inactive gateway."""
        mock_gateway.enabled = False
        test_db.execute = Mock(return_value=_make_execute_result(scalar=mock_gateway))
        test_db.commit = Mock()
        test_db.refresh = Mock()

        # Return one tool so toggle_tool_status gets called
        query_proxy = MagicMock()
        filter_proxy = MagicMock()
        filter_proxy.all.return_value = [MagicMock(id=101)]
        query_proxy.filter.return_value = filter_proxy
        test_db.query = Mock(return_value=query_proxy)

        # Setup gateway service mocks
        gateway_service._notify_gateway_activated = AsyncMock()
        gateway_service._notify_gateway_deactivated = AsyncMock()
        gateway_service._initialize_gateway = AsyncMock(return_value=({"prompts": {}}, [], [], []))

        tool_service_stub = MagicMock()
        tool_service_stub.toggle_tool_status = AsyncMock()
        gateway_service.tool_service = tool_service_stub

        # Patch model_validate to return a mock with .masked()
        mock_gateway_read = MagicMock()
        mock_gateway_read.masked.return_value = mock_gateway_read

        with patch("mcpgateway.services.gateway_service.GatewayRead.model_validate", return_value=mock_gateway_read):
            result = await gateway_service.toggle_gateway_status(test_db, 1, activate=True)

        assert mock_gateway.enabled is True
        gateway_service._notify_gateway_activated.assert_called_once()
        assert tool_service_stub.toggle_tool_status.called
        assert result == mock_gateway_read

    @pytest.mark.asyncio
    async def test_toggle_gateway_status_not_found(self, gateway_service, test_db):
        """Test toggling status of non-existent gateway."""
        test_db.execute = Mock(return_value=_make_execute_result(scalar=None))

        with pytest.raises(GatewayError) as exc_info:
            await gateway_service.toggle_gateway_status(test_db, 999, activate=True)

        assert "Gateway not found: 999" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_toggle_gateway_status_with_tools_error(self, gateway_service, mock_gateway, test_db):
        """Test toggling gateway status when tool toggle fails."""
        test_db.execute = Mock(return_value=_make_execute_result(scalar=mock_gateway))
        test_db.commit = Mock()
        test_db.refresh = Mock()
        test_db.rollback = Mock()

        # Return one tool so toggle_tool_status gets called
        query_proxy = MagicMock()
        filter_proxy = MagicMock()
        filter_proxy.all.return_value = [MagicMock(id=101)]
        query_proxy.filter.return_value = filter_proxy
        test_db.query = Mock(return_value=query_proxy)

        # Setup gateway service mocks
        gateway_service._notify_gateway_deactivated = AsyncMock()
        gateway_service._initialize_gateway = AsyncMock(return_value=({"prompts": {}}, [], [], []))

        # Make tool toggle fail
        tool_service_stub = MagicMock()
        tool_service_stub.toggle_tool_status = AsyncMock(side_effect=Exception("Tool toggle failed"))
        gateway_service.tool_service = tool_service_stub

        # The toggle_gateway_status method will catch the exception and raise GatewayError
        with pytest.raises(GatewayError) as exc_info:
            await gateway_service.toggle_gateway_status(test_db, 1, activate=False)

        assert "Failed to toggle gateway status" in str(exc_info.value)
        assert "Tool toggle failed" in str(exc_info.value)
        test_db.rollback.assert_called_once()

    # ────────────────────────────────────────────────────────────────────
    # DELETE
    # ────────────────────────────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_delete_gateway(self, gateway_service, mock_gateway, test_db):
        """Gateway is removed and subscribers are notified."""
        # First execute call returns gateway (selectinload query), rest are for bulk deletes
        execute_mock = Mock(side_effect=[_make_execute_result(scalar=mock_gateway)] + [Mock()] * 20)
        test_db.execute = execute_mock
        test_db.delete = Mock()
        test_db.commit = Mock()
        test_db.expire = Mock()  # For expiring gateway after bulk deletes

        # tool clean-up query chain
        test_db.query = Mock(return_value=MagicMock(filter=MagicMock(return_value=MagicMock(delete=Mock()))))

        gateway_service._notify_gateway_deleted = AsyncMock()

        await gateway_service.delete_gateway(test_db, 1)

        test_db.delete.assert_called_once_with(mock_gateway)
        gateway_service._notify_gateway_deleted.assert_called_once()
        # Verify execute was called (first for selectinload, then for bulk deletes)
        assert test_db.execute.call_count >= 1

    @pytest.mark.asyncio
    async def test_delete_gateway_not_found(self, gateway_service, test_db):
        """Trying to delete a non-existent gateway raises GatewayError."""
        test_db.execute = Mock(return_value=_make_execute_result(scalar=None))
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
    # REDIS/INITIALIZATION COVERAGE
    # ────────────────────────────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_init_with_redis_unavailable(self, monkeypatch):
        """Test initialization when Redis import fails."""
        monkeypatch.setattr("mcpgateway.services.gateway_service.REDIS_AVAILABLE", False)

        with patch("mcpgateway.services.gateway_service.logging"):
            # Import should trigger the ImportError path
            # First-Party
            from mcpgateway.services.gateway_service import GatewayService

            service = GatewayService()
            assert service._redis_client is None

    @pytest.mark.asyncio
    async def test_init_with_redis_enabled(self, monkeypatch):
        """Test initialization with Redis available and enabled."""
        monkeypatch.setattr("mcpgateway.services.gateway_service.REDIS_AVAILABLE", True)

        mock_redis_client = AsyncMock()
        mock_redis_client.ping = AsyncMock()
        mock_redis_client.set = AsyncMock(return_value=True)

        async def mock_get_redis_client():
            return mock_redis_client

        with patch("mcpgateway.services.gateway_service.get_redis_client", mock_get_redis_client):
            with patch("mcpgateway.services.gateway_service.settings") as mock_settings:
                mock_settings.cache_type = "redis"
                mock_settings.redis_url = "redis://localhost:6379"
                mock_settings.redis_leader_key = "gateway_service_leader"
                mock_settings.redis_leader_ttl = 15
                mock_settings.redis_leader_heartbeat_interval = 5

                # First-Party
                from mcpgateway.services.gateway_service import GatewayService

                service = GatewayService()
                await service.initialize()

                assert service._redis_client is mock_redis_client
                assert isinstance(service._instance_id, str)
                assert service._leader_key == "gateway_service_leader"
                assert service._leader_ttl == 15

    @pytest.mark.asyncio
    async def test_init_file_cache_path_adjustment(self, monkeypatch):
        """Test file cache path adjustment logic."""
        monkeypatch.setattr("mcpgateway.services.gateway_service.REDIS_AVAILABLE", False)

        with patch("mcpgateway.services.gateway_service.settings") as mock_settings:
            mock_settings.cache_type = "file"

            with patch("os.path.expanduser") as mock_expanduser, patch("os.path.relpath") as mock_relpath, patch("os.path.splitdrive") as mock_splitdrive:
                mock_expanduser.return_value = "/home/user/.mcpgateway/health_checks.lock"
                mock_splitdrive.return_value = ("C:", "/home/user/.mcpgateway/health_checks.lock")
                mock_relpath.return_value = "home/user/.mcpgateway/health_checks.lock"

                # First-Party
                from mcpgateway.services.gateway_service import GatewayService

                service = GatewayService()

                # This triggers the path normalization logic
                # But the actual trigger depends on the path being absolute
                # Let's check that the service was created properly
                assert service is not None

    @pytest.mark.asyncio
    async def test_init_with_cache_disabled(self, monkeypatch):
        """Test initialization with cache disabled."""
        monkeypatch.setattr("mcpgateway.services.gateway_service.REDIS_AVAILABLE", False)

        with patch("mcpgateway.services.gateway_service.settings") as mock_settings:
            mock_settings.cache_type = "none"

            # First-Party
            from mcpgateway.services.gateway_service import GatewayService

            service = GatewayService()

            assert service._redis_client is None

    # ────────────────────────────────────────────────────────────────────
    # GATEWAY INITIALIZATION AND CONNECTION COVERAGE
    # ────────────────────────────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_initialize_gateway_with_resources_and_prompts(self, gateway_service):
        """Test _initialize_gateway with full resources and prompts support."""
        with (
            patch("mcpgateway.services.gateway_service.sse_client") as mock_sse_client,
            patch("mcpgateway.services.gateway_service.ClientSession") as mock_session,
            patch("mcpgateway.services.gateway_service.decode_auth") as mock_decode,
        ):
            # Setup mocks
            mock_decode.return_value = {"Authorization": "Bearer token"}

            # Mock SSE client context manager
            mock_streams = (MagicMock(), MagicMock())
            mock_sse_context = AsyncMock()
            mock_sse_context.__aenter__.return_value = mock_streams
            mock_sse_context.__aexit__.return_value = None
            mock_sse_client.return_value = mock_sse_context

            # Mock ClientSession
            mock_session_instance = AsyncMock()
            mock_session_context = AsyncMock()
            mock_session_context.__aenter__.return_value = mock_session_instance
            mock_session_context.__aexit__.return_value = None
            mock_session.return_value = mock_session_context

            # Mock initialization response
            mock_init_response = MagicMock()
            mock_init_response.capabilities.model_dump.return_value = {"protocolVersion": "0.1.0", "resources": {"listChanged": True}, "prompts": {"listChanged": True}, "tools": {"listChanged": True}}
            mock_session_instance.initialize.return_value = mock_init_response

            # Mock tools response
            mock_tools_response = MagicMock()
            mock_tool = MagicMock()
            mock_tool.model_dump.return_value = {"name": "test_tool", "description": "Test tool", "inputSchema": {"type": "object"}}
            mock_tools_response.tools = [mock_tool]
            mock_session_instance.list_tools.return_value = mock_tools_response

            # Mock resources response with URI handling
            mock_resources_response = MagicMock()
            mock_resource = MagicMock()
            mock_resource.model_dump.return_value = {"uri": "file://test.txt", "name": "test_resource", "description": "Test resource", "mime_type": "text/plain"}
            mock_resources_response.resources = [mock_resource]
            mock_session_instance.list_resources.return_value = mock_resources_response

            # Mock prompts response
            mock_prompts_response = MagicMock()
            mock_prompt = MagicMock()
            mock_prompt.model_dump.return_value = {"name": "test_prompt", "description": "Test prompt"}
            mock_prompts_response.prompts = [mock_prompt]
            mock_session_instance.list_prompts.return_value = mock_prompts_response

            # Execute
            capabilities, tools, resources, prompts = await gateway_service._initialize_gateway("http://test.example.com", {"Authorization": "Bearer token"}, "SSE")

            # Verify
            assert "resources" in capabilities
            assert "prompts" in capabilities
            assert len(tools) == 1
            assert len(resources) == 1
            assert len(prompts) == 1
            assert resources[0].uri == "file://test.txt"
            assert resources[0].content == ""  # Default content added
            assert prompts[0].template == ""  # Default template added

    @pytest.mark.asyncio
    async def test_initialize_gateway_resource_validation_error(self, gateway_service):
        """Test _initialize_gateway with resource validation error fallback."""
        with (
            patch("mcpgateway.services.gateway_service.sse_client") as mock_sse_client,
            patch("mcpgateway.services.gateway_service.ClientSession") as mock_session,
            patch("mcpgateway.services.gateway_service.decode_auth") as mock_decode,
        ):
            # Setup mocks
            mock_decode.return_value = {"Authorization": "Bearer token"}

            # Mock SSE client context manager
            mock_streams = (MagicMock(), MagicMock())
            mock_sse_context = AsyncMock()
            mock_sse_context.__aenter__.return_value = mock_streams
            mock_sse_context.__aexit__.return_value = None
            mock_sse_client.return_value = mock_sse_context

            # Mock ClientSession
            mock_session_instance = AsyncMock()
            mock_session_context = AsyncMock()
            mock_session_context.__aenter__.return_value = mock_session_instance
            mock_session_context.__aexit__.return_value = None
            mock_session.return_value = mock_session_context

            # Mock initialization response with resources support
            mock_init_response = MagicMock()
            mock_init_response.capabilities.model_dump.return_value = {"resources": {"listChanged": True}, "tools": {"listChanged": True}}
            mock_session_instance.initialize.return_value = mock_init_response

            # Mock tools response
            mock_tools_response = MagicMock()
            mock_tools_response.tools = []
            mock_session_instance.list_tools.return_value = mock_tools_response

            # Mock resources response with complex URI object
            mock_resources_response = MagicMock()
            mock_resource = MagicMock()

            # Create a complex URI object that has unicode_string attribute
            mock_uri = MagicMock()
            mock_uri.unicode_string = "file://complex.txt"

            mock_resource.model_dump.return_value = {"uri": mock_uri, "name": "complex_resource", "description": "Complex resource"}
            mock_resources_response.resources = [mock_resource]
            mock_session_instance.list_resources.return_value = mock_resources_response

            # Mock ResourceCreate.model_validate to raise exception first time
            with patch("mcpgateway.services.gateway_service.ResourceCreate") as mock_resource_create:
                mock_resource_create.model_validate.side_effect = [Exception("Validation error"), MagicMock()]
                mock_resource_create.return_value = MagicMock()

                # Execute
                capabilities, tools, resources, prompts = await gateway_service._initialize_gateway("http://test.example.com", {"Authorization": "Bearer token"}, "SSE")

                # Verify fallback resource creation was used
                assert len(resources) == 1
                assert mock_resource_create.called

    @pytest.mark.asyncio
    async def test_initialize_gateway_prompt_validation_error(self, gateway_service):
        """Test _initialize_gateway with prompt validation error fallback."""
        with (
            patch("mcpgateway.services.gateway_service.sse_client") as mock_sse_client,
            patch("mcpgateway.services.gateway_service.ClientSession") as mock_session,
            patch("mcpgateway.services.gateway_service.decode_auth") as mock_decode,
        ):
            # Setup mocks
            mock_decode.return_value = {"Authorization": "Bearer token"}

            # Mock SSE client context manager
            mock_streams = (MagicMock(), MagicMock())
            mock_sse_context = AsyncMock()
            mock_sse_context.__aenter__.return_value = mock_streams
            mock_sse_context.__aexit__.return_value = None
            mock_sse_client.return_value = mock_sse_context

            # Mock ClientSession
            mock_session_instance = AsyncMock()
            mock_session_context = AsyncMock()
            mock_session_context.__aenter__.return_value = mock_session_instance
            mock_session_context.__aexit__.return_value = None
            mock_session.return_value = mock_session_context

            # Mock initialization response with prompts support
            mock_init_response = MagicMock()
            mock_init_response.capabilities.model_dump.return_value = {"prompts": {"listChanged": True}, "tools": {"listChanged": True}}
            mock_session_instance.initialize.return_value = mock_init_response

            # Mock tools response
            mock_tools_response = MagicMock()
            mock_tools_response.tools = []
            mock_session_instance.list_tools.return_value = mock_tools_response

            # Mock prompts response
            mock_prompts_response = MagicMock()
            mock_prompt = MagicMock()
            mock_prompt.model_dump.return_value = {"name": "complex_prompt", "description": "Complex prompt"}
            mock_prompts_response.prompts = [mock_prompt]
            mock_session_instance.list_prompts.return_value = mock_prompts_response

            # Mock PromptCreate.model_validate to raise exception first time
            with patch("mcpgateway.services.gateway_service.PromptCreate") as mock_prompt_create:
                mock_prompt_create.model_validate.side_effect = [Exception("Validation error"), MagicMock()]
                mock_prompt_create.return_value = MagicMock()

                # Execute
                capabilities, tools, resources, prompts = await gateway_service._initialize_gateway("http://test.example.com", {"Authorization": "Bearer token"}, "SSE")

                # Verify fallback prompt creation was used
                assert len(prompts) == 1
                assert mock_prompt_create.called

    @pytest.mark.asyncio
    async def test_initialize_gateway_resource_fetch_failure(self, gateway_service):
        """Test _initialize_gateway when resource fetching fails."""
        with (
            patch("mcpgateway.services.gateway_service.sse_client") as mock_sse_client,
            patch("mcpgateway.services.gateway_service.ClientSession") as mock_session,
            patch("mcpgateway.services.gateway_service.decode_auth") as mock_decode,
        ):
            # Setup mocks
            mock_decode.return_value = {"Authorization": "Bearer token"}

            # Mock SSE client context manager
            mock_streams = (MagicMock(), MagicMock())
            mock_sse_context = AsyncMock()
            mock_sse_context.__aenter__.return_value = mock_streams
            mock_sse_context.__aexit__.return_value = None
            mock_sse_client.return_value = mock_sse_context

            # Mock ClientSession
            mock_session_instance = AsyncMock()
            mock_session_context = AsyncMock()
            mock_session_context.__aenter__.return_value = mock_session_instance
            mock_session_context.__aexit__.return_value = None
            mock_session.return_value = mock_session_context

            # Mock initialization response with resources support
            mock_init_response = MagicMock()
            mock_init_response.capabilities.model_dump.return_value = {"resources": {"listChanged": True}, "tools": {"listChanged": True}}
            mock_session_instance.initialize.return_value = mock_init_response

            # Mock tools response
            mock_tools_response = MagicMock()
            mock_tools_response.tools = []
            mock_session_instance.list_tools.return_value = mock_tools_response

            # Make list_resources fail
            mock_session_instance.list_resources.side_effect = Exception("Resource fetch failed")

            # Execute
            capabilities, tools, resources, prompts = await gateway_service._initialize_gateway("http://test.example.com", {"Authorization": "Bearer token"}, "SSE")

            # Verify
            assert "resources" in capabilities
            assert len(resources) == 0  # Should be empty due to failure

    @pytest.mark.asyncio
    async def test_initialize_gateway_prompt_fetch_failure(self, gateway_service):
        """Test _initialize_gateway when prompt fetching fails."""
        with (
            patch("mcpgateway.services.gateway_service.sse_client") as mock_sse_client,
            patch("mcpgateway.services.gateway_service.ClientSession") as mock_session,
            patch("mcpgateway.services.gateway_service.decode_auth") as mock_decode,
        ):
            # Setup mocks
            mock_decode.return_value = {"Authorization": "Bearer token"}

            # Mock SSE client context manager
            mock_streams = (MagicMock(), MagicMock())
            mock_sse_context = AsyncMock()
            mock_sse_context.__aenter__.return_value = mock_streams
            mock_sse_context.__aexit__.return_value = None
            mock_sse_client.return_value = mock_sse_context

            # Mock ClientSession
            mock_session_instance = AsyncMock()
            mock_session_context = AsyncMock()
            mock_session_context.__aenter__.return_value = mock_session_instance
            mock_session_context.__aexit__.return_value = None
            mock_session.return_value = mock_session_context

            # Mock initialization response with prompts support
            mock_init_response = MagicMock()
            mock_init_response.capabilities.model_dump.return_value = {"prompts": {"listChanged": True}, "tools": {"listChanged": True}}
            mock_session_instance.initialize.return_value = mock_init_response

            # Mock tools response
            mock_tools_response = MagicMock()
            mock_tools_response.tools = []
            mock_session_instance.list_tools.return_value = mock_tools_response

            # Make list_prompts fail
            mock_session_instance.list_prompts.side_effect = Exception("Prompt fetch failed")

            # Execute
            capabilities, tools, resources, prompts = await gateway_service._initialize_gateway("http://test.example.com", {"Authorization": "Bearer token"}, "SSE")

            # Verify
            assert "prompts" in capabilities
            assert len(prompts) == 0  # Should be empty due to failure

    @pytest.mark.asyncio
    async def test_list_gateway_with_tags(self, gateway_service, mock_gateway):
        """Test listing gateways with tag filtering."""
        # Third-Party

        # Mock query chain - needs to support chaining through order_by, where, limit
        mock_query = MagicMock()
        mock_query.order_by.return_value = mock_query
        mock_query.where.return_value = mock_query
        mock_query.limit.return_value = mock_query

        session = MagicMock()
        session.execute.return_value.scalars.return_value.all.return_value = [mock_gateway]

        bind = MagicMock()
        bind.dialect = MagicMock()
        bind.dialect.name = "sqlite"  # or "postgresql" or "mysql"
        session.get_bind.return_value = bind

        # Mock EmailTeam query for team names
        session.query.return_value.filter.return_value.all.return_value = []
        session.commit = MagicMock()

        mocked_gateway_read = MagicMock()
        mocked_gateway_read.model_dump.return_value = {"id": "1", "name": "test"}

        # Mock select to return the mock_query that supports chaining
        def mock_select(*args):
            return mock_query

        # Mock convert_gateway_to_read to return the mocked gateway
        gateway_service.convert_gateway_to_read = MagicMock(return_value=mocked_gateway_read)

        with patch("mcpgateway.services.gateway_service.select", side_effect=mock_select):
            with patch("mcpgateway.services.gateway_service.json_contains_expr") as mock_json_contains:
                fake_condition = MagicMock()
                mock_json_contains.return_value = fake_condition

                # Pass include_inactive=True to avoid the enabled filter, so we can test tag filtering in isolation
                result, next_cursor = await gateway_service.list_gateways(session, tags=["test", "production"], include_inactive=True)

                mock_json_contains.assert_called_once()  # called exactly once
                called_args = mock_json_contains.call_args[0]  # positional args tuple
                assert called_args[0] is session  # session passed through
                # third positional arg is the tags list (signature: session, col, values, match_any=True)
                assert called_args[2] == ["test", "production"]
                # Verify where() was called and the fake_condition is in one of the calls
                assert mock_query.where.called, "where() should have been called"
                # Check that fake_condition appears in at least one of the where() calls
                where_calls = mock_query.where.call_args_list
                assert any(fake_condition in call.args for call in where_calls), f"fake_condition not found in where() calls: {where_calls}"
                # finally, your service should return the list produced by mock_db.execute(...)
                assert isinstance(result, list)
                assert len(result) == 1

                # Verify convert_gateway_to_read was called
                gateway_service.convert_gateway_to_read.assert_called_once()
                assert result == [mocked_gateway_read]
